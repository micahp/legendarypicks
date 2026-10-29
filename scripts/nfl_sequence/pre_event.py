"""Participants chosen before the play's outcome is drawn (SLC v1, research, not adopted).

After the play-call layer picks the intent (run or dropback), this module picks who carries the ball or who is the target. The
choice depends on the pregame roster and usage shares only, and it is made before the outcome row is drawn. The outcome then
determines what happens to the chosen player (a completion, an incompletion, a sack, a rush), and the player is not re-chosen
after the outcome.

The outcome is not yet conditioned on the player. Yards and results still come from the historical row of the play's situation
cell. That is a known limit of this version: participant-conditioned outcomes are not built.

Every draw is seeded from the snapshot hash, the game seed and the decision index, so a replay with the same inputs is identical.
"""
import hashlib
import random

PASS_EVENTS = ('pass_complete', 'pass_incomplete', 'interception', 'sack')
TARGET_EVENTS = ('pass_complete', 'pass_incomplete', 'interception')  # a sack has no target


def _draw(seed_text):
    return random.Random(int.from_bytes(hashlib.sha256(seed_text.encode()).digest()[:8], 'big'))


def _qb1(players, team):
    starters = [p for p in players if p['pos_abb'] == 'QB' and p['pos_rank'] == 1]
    if len(starters) != 1:
        raise ValueError(f'pregame snapshot must have exactly one QB1 for {team}')
    return starters[0]


def _by_usage(players, usage, team, label, draw):
    shares = usage['shares']
    positions = [pos for pos, share in shares.items() if share > 0 and any(p['pos_abb'] == pos for p in players)]
    if not positions:
        raise ValueError(f'pregame snapshot has no eligible {label} positions for {team}')
    position = draw.choices(positions, weights=[shares[pos] for pos in positions], k=1)[0]
    eligible = sorted((p for p in players if p['pos_abb'] == position), key=lambda p: (p['pos_rank'], p['gsis_id']))
    return draw.choices(eligible, weights=[1 / p['pos_rank'] for p in eligible], k=1)[0]


def player_shares_positions(role):
    import player_shares as ps
    return ps.TARGET_POSITIONS if role == 'receive' else ps.CARRY_POSITIONS


def _by_player_share(players, table, team, role, positions, draw):
    """A rostered player in the given positions, drawn in proportion to his prior-season share (the adapter)."""
    import player_shares as ps
    candidates = ps.eligible(players, positions)
    if not candidates:
        raise ValueError(f'pregame snapshot has no eligible {role} players for {team}')
    weights = [ps.weight(table, team, p['gsis_id'], 'receive' if role == 'receive' else 'carry') for p in candidates]
    return draw.choices(candidates, weights=weights, k=1)[0]


def choose(snapshot, side, intent, seed, index, formation_priors=None, state=None, player_shares=None, defense_priors=None,
           role_table=None):
    """{'passer': ..., 'receiver': ...} for a dropback, {'rusher': ...} for a run, None otherwise. Chosen before the outcome.

    With formation priors and the situation, also the formation and personnel grouping, from the historical shares."""
    if intent not in ('run', 'dropback'):
        return None
    roster = snapshot['rosters'][side]
    team, players = roster['team'], roster['players']
    observed = snapshot['model_reference']['observed_reference']
    base = f"{snapshot['snapshot_sha256']}:{seed}:{index}"
    chosen = {'side': side, 'team': team}
    if intent == 'dropback':
        chosen['passer'] = _qb1(players, team)
        if player_shares is None:
            chosen['receiver'] = _by_usage(players, observed['receiver_position_usage'], team, 'receiver',
                                           _draw(f'{base}:receiver:position'))
        else:  # the adapter: rostered receivers in proportion to their prior-season target shares
            positions = player_shares_positions('receive')
            if role_table is not None and state is not None:  # decision model category A: the target's role first
                import target_roles
                present = {p['pos_abb'] for p in players if p['pos_abb'] in ('RB', 'WR', 'TE')}
                role = target_roles.draw(role_table, team, state['down'], state['togo'], state['yl'], f'{base}:role',
                                         available=present | {'Other'})
                chosen['target_role'] = role
                if role in ('RB', 'WR', 'TE'):
                    positions = (role,)
            chosen['receiver'] = _by_player_share(players, player_shares, team, 'receive', positions,
                                                  _draw(f'{base}:receiver:player'))
    else:
        if player_shares is None:
            chosen['rusher'] = _by_usage(players, observed['runner_position_usage'], team, 'rusher',
                                         _draw(f'{base}:rusher:position'))
        else:
            chosen['rusher'] = _by_player_share(players, player_shares, team, 'carry', player_shares_positions('carry'),
                                                _draw(f'{base}:rusher:player'))
    if formation_priors is not None and state is not None:
        import formation_layer  # local: the formation layer is optional
        chosen['formation'], chosen['personnel'] = formation_layer.choose(
            formation_priors, intent, state['down'], state['togo'], f'{base}:formation', team=team)
    if defense_priors is not None and intent == 'dropback':
        import defense_layer
        other = 'away' if side == 'home' else 'home'  # the defense is the other roster's team
        chosen['coverage'] = defense_layer.choose(defense_priors, snapshot['rosters'][other]['team'], f'{base}:coverage')
    return chosen


def chooser(snapshot, seed, formation_priors=None, player_shares=None, defense_priors=None, role_table=None):
    """A callable for PlayCallSampler.participant_chooser: called once per scrimmage play, after the intent, before the outcome.
    The decision index counts those calls, so it is the same on every replay of the same game."""
    counter = {'index': 0}

    def pick(intent, offense, state=None):
        index = counter['index']
        counter['index'] += 1
        side = 'home' if offense == 'A' else 'away'
        return choose(snapshot, side, intent, seed, index, formation_priors=formation_priors, state=state,
                      player_shares=player_shares, defense_priors=defense_priors, role_table=role_table)
    return pick


def ids(pre):
    """The chosen players' GSIS ids, for the decision record."""
    if pre is None:
        return None
    return {role: player['gsis_id'] for role, player in pre.items() if isinstance(player, dict)}
