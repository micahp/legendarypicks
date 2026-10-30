"""Participants chosen before the play's outcome is drawn (SLC v1, research, not adopted).

After the play-call layer picks the intent (run or dropback), this module picks who carries the ball or who is the target. The
choice depends on the pregame roster and usage shares only, and it is made before the outcome row is drawn. The outcome then
determines what happens to the chosen player (a completion, an incompletion, a sack, a rush), and the player is not re-chosen
after the outcome.

When the player-outcome adapter is enabled, the selected participant reweights eligible event and result rows before the game-state
transition. With that adapter off, the historical row is sampled without player-specific outcome weights.

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


def _passer(players, team, draw, trick_rate, injury_report=None):
    """The starting or next eligible QB, or a rostered back or receiver who throws at the trick rate."""
    if injury_report is None:
        starter = _qb1(players, team)
    else:
        eligible_qbs = sorted((p for p in players if p['pos_abb'] == 'QB'),
                              key=lambda p: (p['pos_rank'], p['gsis_id']))
        if not eligible_qbs:
            raise ValueError(f'pregame snapshot has no available quarterback for {team}')
        starter = eligible_qbs[0]
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


def combine_role_priors(decision_prior, target_role_prior, available_roles):
    """Combine the two category-A priors by normalized geometric mean over roster-available roles."""
    roles = sorted(set(decision_prior) & set(target_role_prior) & set(available_roles))
    weights = {role: (max(0.0, decision_prior[role]) * max(0.0, target_role_prior[role])) ** 0.5
               for role in roles}
    total = sum(weights.values())
    if not roles:
        return {}
    if total <= 0:
        return {role: 1.0 / len(roles) for role in roles}
    return {role: weight / total for role, weight in weights.items()}


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
           share_table=None, playbook_table=None, share_cache=None, qb_decision_table=None):
    """{'passer': ..., 'receiver': ...} for a dropback, {'rusher': ...} for a run, None otherwise. Chosen before the outcome.

    With formation priors and the situation, also the formation and personnel grouping, from the historical shares."""
    if intent not in ('run', 'dropback'):
        return None
    roster = snapshot['rosters'][side]
    team, players = roster['team'], roster['players']
    import share_distributions
    available_players = share_distributions.eligible_players(players, roster.get('injury_report'))
    observed = snapshot['model_reference']['observed_reference']
    base = f"{snapshot['snapshot_sha256']}:{seed}:{index}"
    chosen = {'side': side, 'team': team}
    if share_table is not None:
        chosen['participant_share_model'] = 'dirichlet_multinomial'
    elif player_shares is not None:
        chosen['participant_share_model'] = 'fixed_player_share'
    elif player_shares is None:
        chosen['participant_share_model'] = 'position_usage'
    labels = None
    if decision_table is not None and state is not None:  # decision model categories A to N, drawn before the outcome
        import decision_layer
        label_only = None
        if role_table is not None and intent == 'dropback':
            label_only = tuple(category for category in decision_layer.PASS_CATS + decision_layer.ALIGN_CATS
                               if category != 'A')
        labels = decision_layer.draw(decision_table, team, state['down'], state['togo'], state['yl'], intent,
                                     f'{base}:labels', only=label_only)
        if role_table is not None and intent == 'dropback':
            import target_roles
            decision_distribution = decision_layer.distribution(
                decision_table, team, decision_layer.cell_of(state['down'], state['togo'], state['yl']), 'A')
            target_distribution = target_roles.distribution(
                role_table, team, state['down'], state['togo'], state['yl'])
            present = {target_roles.role_of(p['pos_abb']) for p in available_players
                       if p['pos_abb'] in player_shares_positions('receive')}
            roles = combine_role_priors(decision_distribution, target_distribution, present | {'Other'})
            if roles:
                role_draw = _draw(f'{base}:combined-target-role')
                selected_role = role_draw.choices(sorted(roles), weights=[roles[r] for r in sorted(roles)], k=1)[0]
                labels = dict(labels or {})
                labels['A'] = selected_role
                chosen['target_role'] = selected_role
                chosen['target_role_prior_used'] = True
                chosen['target_role_prior_combined'] = True
        if playbook_table is not None and labels is not None:  # the playbook's pass depth, location and run gap, where it has a prior
            book = decision_layer.draw(playbook_table, team, state['down'], state['togo'], state['yl'], intent,
                                       f'{base}:playbook', only=('D', 'E', 'C'))
            fallback = []
            used = []
            for cat in book:  # the categories this intent takes; a category the playbook has no prior for keeps the decision label
                if book[cat] is not None:
                    labels[cat] = book[cat]
                    used.append(cat)
                else:
                    fallback.append(cat)
            chosen['playbook_used'] = used
            if fallback:
                chosen['playbook_fallback'] = fallback
        chosen['labels'] = labels
    if intent == 'dropback':
        qbd_players = available_players
        if qb_decision_table is not None:
            eligible_qbs = sorted((p for p in qbd_players if p['pos_abb'] == 'QB'),
                                  key=lambda p: (p['pos_rank'], p['gsis_id']))
            if not eligible_qbs:
                raise ValueError(f'pregame snapshot has no available quarterback for {team}')
            chosen['passer'] = eligible_qbs[0]
            trick = _draw(f'{base}:passer:trick')
            if trick.random() < trick_passer_rate:
                throwers = sorted((p for p in qbd_players if p['pos_abb'] in ('RB', 'WR', 'TE')),
                                  key=lambda p: (p['pos_rank'], p['gsis_id']))
                if throwers:
                    chosen['passer'] = trick.choices(throwers, weights=[1 / p['pos_rank'] for p in throwers], k=1)[0]
        else:
            chosen['passer'] = _passer(qbd_players, team, _draw(f'{base}:passer:trick'), trick_passer_rate,
                                       injury_report=roster.get('injury_report'))
        if qb_decision_table is not None and chosen['passer']['pos_abb'] == 'QB' and state is not None:
            import qb_decisions
            available_roles = {qb_decisions.target_role(p['pos_abb']) for p in qbd_players
                               if p['pos_abb'] in player_shares_positions('receive')}
            qb_decision = qb_decisions.draw(
                qb_decision_table, team, chosen['passer']['gsis_id'], state['down'], state['togo'], state['yl'],
                available_roles, f'{base}:qb-decision')
            chosen['qb_decision'] = qb_decision
            if qb_decision['action'] == 'scramble':
                chosen['rusher'] = chosen['passer']
                chosen['labels'] = None  # passing labels do not describe the QB's scramble decision
            else:
                labels = dict(labels or {})
                labels['A'] = qb_decision['target_role']
                chosen['labels'] = labels
                chosen['target_role'] = qb_decision['target_role']
        receivers = [p for p in qbd_players if p['gsis_id'] != chosen['passer']['gsis_id']]
        if chosen.get('qb_decision', {}).get('action') == 'scramble':
            pass  # the selected QB is the runner; a target is not assigned to a scramble
        else:
            backups = sorted((p for p in receivers if p['pos_abb'] == 'QB'), key=lambda p: (p['pos_rank'], p['gsis_id']))
            if backups and _draw(f'{base}:receiver:qb').random() < qb_receiver_rate:  # a QB catches: the backup, to the starter
                chosen['receiver'] = backups[0]
                if chosen.get('qb_decision') is not None:
                    chosen['qb_decision']['target_role'] = 'Other'
                    chosen['target_role'] = 'Other'
                    chosen['labels']['A'] = 'Other'
            elif player_shares is None and share_table is None:
                role = (chosen.get('qb_decision') or {}).get('target_role')
                if role in ('RB', 'WR', 'TE'):
                    eligible = sorted((p for p in receivers if p['pos_abb'] == role),
                                      key=lambda p: (p['pos_rank'], p['gsis_id']))
                    if not eligible:
                        raise ValueError(f'QB decision selected unavailable target role {role} for {team}')
                    chosen['receiver'] = _draw(f'{base}:receiver:qb-role').choices(
                        eligible, weights=[1 / p['pos_rank'] for p in eligible], k=1)[0]
                else:
                    chosen['receiver'] = _by_usage(receivers, observed['receiver_position_usage'], team, 'receiver',
                                                   _draw(f'{base}:receiver:position'))
            else:  # the adapter: rostered receivers in proportion to their prior-season target shares
                positions = player_shares_positions('receive')
                if labels is not None and labels.get('A') is not None:  # decision category A, including the QB-specific role
                    role = labels['A']
                    chosen['target_role'] = role
                    present = {p['pos_abb'] for p in receivers}
                    if role in ('RB', 'WR', 'TE') and role in present:
                        positions = (role,)
                elif role_table is not None and state is not None:  # the team target-role model when no decision label exists
                    import target_roles
                    present = {p['pos_abb'] for p in receivers if p['pos_abb'] in ('RB', 'WR', 'TE')}
                    role = target_roles.draw(role_table, team, state['down'], state['togo'], state['yl'], f'{base}:role',
                                             available=present | {'Other'})
                    chosen['target_role'] = role
                    chosen['target_role_prior_used'] = True
                    if role in ('RB', 'WR', 'TE'):
                        positions = (role,)
                if share_table is not None:  # the game's Dirichlet target shares over the eligible players, then this play's draw
                    import share_distributions
                    population = share_distributions.eligible_players(
                        [p for p in receivers if p['pos_abb'] in player_shares_positions('receive')],
                        roster.get('injury_report'))
                    eligible = [p for p in population if p['pos_abb'] in positions]
                    if not eligible:  # fail loudly: the adapter below does not know about injuries
                        raise ValueError(f'no eligible receivers for {team} after the injury report')
                    chosen['receiver'] = _by_game_share(eligible, share_table, team, 'receive', str(seed), snapshot['snapshot_sha256'],
                                                        _draw(f'{base}:receiver:dirichlet'), share_cache, population=population)
                else:
                    chosen['receiver'] = _by_player_share(receivers, player_shares, team, 'receive', positions,
                                                          _draw(f'{base}:receiver:player'))
    else:
        if player_shares is None and share_table is None:
            chosen['rusher'] = _by_usage(available_players, observed['runner_position_usage'], team, 'rusher',
                                         _draw(f'{base}:rusher:position'))
        else:
            positions = player_shares_positions('carry')
            if labels is not None and labels.get('B') is not None:  # decision category B: the carrier's role, from its prior
                carried = CARRY_ROLE_POSITIONS.get(labels['B'])
                if carried and any(p['pos_abb'] in carried for p in available_players):
                    positions = carried
            if share_table is not None:  # the game's Dirichlet carry shares over the eligible players, then this play's draw
                import share_distributions
                population = share_distributions.eligible_players(
                    [p for p in available_players if p['pos_abb'] in player_shares_positions('carry')],
                    roster.get('injury_report'))
                eligible = [p for p in population if p['pos_abb'] in positions]
                if not eligible:
                    raise ValueError(f'no eligible rushers for {team} after the injury report')
                chosen['rusher'] = _by_game_share(eligible, share_table, team, 'carry', str(seed), snapshot['snapshot_sha256'],
                                                  _draw(f'{base}:rusher:dirichlet'), share_cache, population=population)
            else:
                chosen['rusher'] = _by_player_share(available_players, player_shares, team, 'carry', positions,
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


def _by_game_share(candidates, share_table, team, role, game_id, seed_text, draw, cache=None, population=None):
    """A rostered player drawn in proportion to his share in this game's Dirichlet draw (share_distributions).

    The draw is over the full eligible team-role population. A decision-layer position filter only restricts this play's candidate
    set; it does not create another share draw. With a cache (one per game and seed, held by the chooser), each team and role is
    drawn once and every play reuses the draw."""
    import share_distributions
    population = candidates if population is None else population
    population_ids = tuple(sorted(p['gsis_id'] for p in population))
    candidate_ids = {p['gsis_id'] for p in candidates}
    if not candidate_ids.issubset(population_ids):
        raise ValueError(f'{role} candidates for {team} are outside the game share population')
    key = (team, role, game_id)
    if cache is not None and key in cache:
        cached_ids, shares = cache[key]
        if cached_ids != population_ids:
            raise ValueError(f'{role} eligible population changed within {team} game {game_id}')
    else:
        shares = share_distributions.game_shares(share_table, team, game_id, population_ids, role, seed_text)
        if cache is not None:
            cache[key] = (population_ids, shares)
    return draw.choices(candidates, weights=[shares[p['gsis_id']] for p in candidates], k=1)[0]


def chooser(snapshot, seed, formation_priors=None, player_shares=None, defense_priors=None, role_table=None, decision_table=None,
            share_table=None, playbook_table=None, qb_decision_table=None):
    """A callable for PlayCallSampler.participant_chooser: called once per scrimmage play, after the intent, before the outcome.
    The decision index counts those calls, so it is the same on every replay of the same game."""
    counter = {'index': 0}
    share_cache = {}  # one game and seed: each team's Dirichlet draw is made once and reused by every play

    def pick(intent, offense, state=None):
        index = counter['index']
        counter['index'] += 1
        side = 'home' if offense == 'A' else 'away'
        return choose(snapshot, side, intent, seed, index, formation_priors=formation_priors, state=state,
                      player_shares=player_shares, defense_priors=defense_priors, role_table=role_table,
                      decision_table=decision_table, share_table=share_table, playbook_table=playbook_table,
                      share_cache=share_cache, qb_decision_table=qb_decision_table)
    return pick


def ids(pre):
    """The chosen players' GSIS ids, for the decision record."""
    if pre is None:
        return None
    out = {role: player['gsis_id'] for role, player in pre.items() if isinstance(player, dict) and 'gsis_id' in player}
    if pre.get('target_role') is not None:  # the decision model's category, not a player: kept so the record shows it
        out['target_role'] = pre['target_role']
    for key in ('participant_share_model', 'target_role_prior_used', 'target_role_prior_combined',
                'playbook_used', 'playbook_fallback'):
        if pre.get(key) is not None:
            out[key] = pre[key]
    if pre.get('labels') is not None:  # the drawn decision labels, for the record
        out['labels'] = pre['labels']
    if pre.get('qb_decision') is not None:
        out['qb_decision'] = pre['qb_decision']
    return out
