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


# decision category B (rusher role) to the positions that carry the ball: a WR or TE can run an end-around or a reverse
CARRY_ROLE_POSITIONS = {'RB': ('RB',), 'QB': ('QB',), 'WR_TE': ('WR', 'TE')}
# the plays a roster position does not usually make, measured on 2024 and 2025 pass plays (sacks excluded): a non-QB threw
# 63 of 35,293 passes, and a QB was the target on 17 of 33,802
TRICK_PASSER_RATE = 63 / 35293
QB_RECEIVER_RATE = 17 / 33802


def _passer(players, team, draw, trick_rate):
    """The starting QB, or with the trick rate a rostered back or receiver who throws instead."""
    starter = _qb1(players, team)
    if draw.random() >= trick_rate:
        return starter
    throwers = sorted((p for p in players if p['pos_abb'] in ('RB', 'WR', 'TE')), key=lambda p: (p['pos_rank'], p['gsis_id']))
    if not throwers:
        return starter
    return draw.choices(throwers, weights=[1 / p['pos_rank'] for p in throwers], k=1)[0]

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
           role_table=None, decision_table=None, trick_passer_rate=TRICK_PASSER_RATE, qb_receiver_rate=QB_RECEIVER_RATE,
           share_table=None):
    """{'passer': ..., 'receiver': ...} for a dropback, {'rusher': ...} for a run, None otherwise. Chosen before the outcome.

    With formation priors and the situation, also the formation and personnel grouping, from the historical shares."""
    if intent not in ('run', 'dropback'):
        return None
    roster = snapshot['rosters'][side]
    team, players = roster['team'], roster['players']
    observed = snapshot['model_reference']['observed_reference']
    base = f"{snapshot['snapshot_sha256']}:{seed}:{index}"
    chosen = {'side': side, 'team': team}
    labels = None
    if decision_table is not None and state is not None:  # decision model categories A to N, drawn before the outcome
        import decision_layer
        labels = decision_layer.draw(decision_table, team, state['down'], state['togo'], state['yl'], intent, f'{base}:labels')
        chosen['labels'] = labels
    if intent == 'dropback':
        chosen['passer'] = _passer(players, team, _draw(f'{base}:passer:trick'), trick_passer_rate)
        receivers = [p for p in players if p['gsis_id'] != chosen['passer']['gsis_id']]  # a passer does not also receive
        backups = sorted((p for p in receivers if p['pos_abb'] == 'QB'), key=lambda p: (p['pos_rank'], p['gsis_id']))
        if backups and _draw(f'{base}:receiver:qb').random() < qb_receiver_rate:  # a QB catches: the backup, to the starter
            chosen['receiver'] = backups[0]
        elif player_shares is None:
            chosen['receiver'] = _by_usage(receivers, observed['receiver_position_usage'], team, 'receiver',
                                           _draw(f'{base}:receiver:position'))
        else:  # the adapter: rostered receivers in proportion to their prior-season target shares
            positions = player_shares_positions('receive')
            if labels is not None and labels.get('A') is not None:  # decision category A: the target's role, from its prior
                role = labels['A']
                chosen['target_role'] = role
                present = {p['pos_abb'] for p in players}
                if role in ('RB', 'WR', 'TE') and role in present:
                    positions = (role,)
            elif role_table is not None and state is not None:  # decision model category A: the target's role first
                import target_roles
                present = {p['pos_abb'] for p in players if p['pos_abb'] in ('RB', 'WR', 'TE')}
                role = target_roles.draw(role_table, team, state['down'], state['togo'], state['yl'], f'{base}:role',
                                         available=present | {'Other'})
                chosen['target_role'] = role
                if role in ('RB', 'WR', 'TE'):
                    positions = (role,)
            eligible = [p for p in receivers if p['pos_abb'] in positions]
            if share_table is not None and eligible:  # the game's Dirichlet target shares, then this play's draw from them
                chosen['receiver'] = _by_game_share(eligible, share_table, team, 'receive', str(seed), snapshot['snapshot_sha256'],
                                                    _draw(f'{base}:receiver:dirichlet'))
            else:
                chosen['receiver'] = _by_player_share(receivers, player_shares, team, 'receive', positions,
                                                      _draw(f'{base}:receiver:player'))
    else:
        if player_shares is None:
            chosen['rusher'] = _by_usage(players, observed['runner_position_usage'], team, 'rusher',
                                         _draw(f'{base}:rusher:position'))
        else:
            positions = player_shares_positions('carry')
            if labels is not None and labels.get('B') is not None:  # decision category B: the carrier's role, from its prior
                carried = CARRY_ROLE_POSITIONS.get(labels['B'])
                if carried and any(p['pos_abb'] in carried for p in players):
                    positions = carried
            eligible = [p for p in players if p['pos_abb'] in positions]
            if share_table is not None and eligible:  # the game's Dirichlet carry shares, then this play's draw from them
                chosen['rusher'] = _by_game_share(eligible, share_table, team, 'carry', str(seed), snapshot['snapshot_sha256'],
                                                  _draw(f'{base}:rusher:dirichlet'))
            else:
                chosen['rusher'] = _by_player_share(players, player_shares, team, 'carry', positions,
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


def _by_game_share(candidates, share_table, team, role, game_id, seed_text, draw):
    """A rostered player drawn in proportion to his share in this game's Dirichlet draw (share_distributions)."""
    import share_distributions
    shares = share_distributions.game_shares(share_table, team, game_id, [p['gsis_id'] for p in candidates], role, seed_text)
    return draw.choices(candidates, weights=[shares[p['gsis_id']] for p in candidates], k=1)[0]


def chooser(snapshot, seed, formation_priors=None, player_shares=None, defense_priors=None, role_table=None, decision_table=None,
            share_table=None):
    """A callable for PlayCallSampler.participant_chooser: called once per scrimmage play, after the intent, before the outcome.
    The decision index counts those calls, so it is the same on every replay of the same game."""
    counter = {'index': 0}

    def pick(intent, offense, state=None):
        index = counter['index']
        counter['index'] += 1
        side = 'home' if offense == 'A' else 'away'
        return choose(snapshot, side, intent, seed, index, formation_priors=formation_priors, state=state,
                      player_shares=player_shares, defense_priors=defense_priors, role_table=role_table,
                      decision_table=decision_table, share_table=share_table)
    return pick


def ids(pre):
    """The chosen players' GSIS ids, for the decision record."""
    if pre is None:
        return None
    out = {role: player['gsis_id'] for role, player in pre.items() if isinstance(player, dict) and 'gsis_id' in player}
    if pre.get('target_role') is not None:  # the decision model's category, not a player: kept so the record shows it
        out['target_role'] = pre['target_role']
    if pre.get('labels') is not None:  # the drawn decision labels, for the record
        out['labels'] = pre['labels']
    return out
