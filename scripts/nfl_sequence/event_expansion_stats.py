"""Deterministic player/team accounting for validated ceg-play-2 event facts.

This adapter returns deltas; it does not mutate V2's existing game_stats
schema. The game integration must merge and reconcile these deltas before any
new source rows are admitted.
"""
from __future__ import annotations

import math
from collections import defaultdict

import ceg_contract as contract


class EventStatisticsError(ValueError):
    pass


CREDITED_FIELDS = (
    'pass_attempts', 'completions', 'passing_yards', 'interceptions_thrown',
    'targets', 'receptions', 'receiving_yards', 'rush_attempts', 'rushing_yards',
    'sacks_taken', 'sack_yards_lost', 'sacks', 'interceptions', 'fumbles',
    'fumbles_lost', 'fumble_recoveries', 'interception_returns',
    'interception_return_yards', 'fumble_returns', 'fumble_return_yards',
    'punt_attempts', 'punt_returns', 'punt_return_yards', 'kickoff_returns', 'kickoff_return_yards',
    'return_touchdowns', 'rushing_touchdowns', 'passing_touchdowns',
    'receiving_touchdowns', 'field_goal_attempts', 'field_goals_made',
    'penalties_called', 'penalties_accepted', 'penalties_accepted_yards',
)


def _role_team(role, state, kick=None):
    if role in ('offense', 'defense'):
        return state[role]
    if role == 'kicking_team' and kick is not None:
        return kick.kicking_team
    if role == 'receiving_team' and kick is not None:
        return kick.receiving_team
    raise EventStatisticsError('team_role_unresolved:' + str(role))


def play_deltas(play, state, *, penalty_enforcement=None):
    """Return per-play team, named-player and explicitly unattributed deltas."""
    contract.validate_v2(state, play)
    kick = play.kick
    teams = defaultdict(lambda: defaultdict(int))
    players = {}
    unattributed = defaultdict(lambda: defaultdict(int))

    def credit(team, field, value, role=None):
        teams[team][field] += value
        if role is None:
            return
        contract._v2_role(role, field)
        if role.status == 'named':
            entry = players.setdefault(role.player_id, {'team': team, 'stats': defaultdict(int)})
            if entry['team'] != team:
                raise EventStatisticsError('one_player_assigned_to_two_teams_in_play')
            entry['stats'][field] += value
        else:
            unattributed[team][field] += value

    offense, defense = state['offense'], state['defense']
    event = play.event
    roles = play.players
    if event in ('run', 'scramble', 'kneel'):
        carrier = roles.rusher
        credit(offense, 'rush_attempts', 1, carrier)
        credit(offense, 'rushing_yards', play.yards_gained, carrier)
    elif event in ('pass_complete', 'pass_incomplete', 'interception', 'sack'):
        passer = roles.passer
        if event == 'sack':
            credit(offense, 'sacks_taken', 1, passer)
            credit(offense, 'sack_yards_lost', abs(play.yards_gained), passer)
            credit(defense, 'sacks', 1, roles.sacker)
        else:
            credit(offense, 'pass_attempts', 1, passer)
            if event == 'pass_complete':
                credit(offense, 'completions', 1, passer)
                credit(offense, 'passing_yards', play.yards_gained, passer)
            if event == 'interception':
                credit(offense, 'interceptions_thrown', 1, passer)
                credit(defense, 'interceptions', 1, roles.interceptor)
            target = roles.receiver
            if target.status == 'none':
                target = contract.PlayerRoleV2.unmodelled('intended_receiver')
            credit(offense, 'targets', 1, target)
            if event == 'pass_complete':
                credit(offense, 'receptions', 1, target)
                credit(offense, 'receiving_yards', play.yards_gained, target)
    elif event == 'spike':
        credit(offense, 'pass_attempts', 1, roles.passer)
    elif event == 'punt':
        credit(offense, 'punt_attempts', 1, roles.punter)
    elif event == 'field_goal_attempt':
        kicker_team = kick.kicking_team
        credit(kicker_team, 'field_goal_attempts', 1, roles.kicker)

    if play.fumble:
        if event in ('punt', 'field_goal_attempt', 'kickoff'):
            fumbler_team = kick.receiving_team
            fumbler = kick.returner
            recovered_team = _role_team(kick.recovery_team, state, kick) if kick.recovery_team else None
            recoverer = kick.recoverer
        else:
            fumbler_team = offense
            fumbler = roles.fumbler
            recovered_team = _role_team(play.possession.team, state) if play.possession else None
            recoverer = play.possession.recovered_by if play.possession else contract.PlayerRoleV2.none()
        credit(fumbler_team, 'fumbles', 1, fumbler)
        if recovered_team is not None:
            if recovered_team != fumbler_team:
                credit(fumbler_team, 'fumbles_lost', 1, fumbler)
                teams[fumbler_team]['turnovers'] += 1
                teams[recovered_team]['takeaways'] += 1
            credit(recovered_team, 'fumble_recoveries', 1, recoverer)

    if play.event == 'interception':
        teams[offense]['turnovers'] += 1
        teams[defense]['takeaways'] += 1

    if play.possession is not None and play.possession.return_yards is not None:
        role = play.possession.team
        team = _role_team(role, state)
        if play.possession.how == 'interception':
            credit(team, 'interception_returns', 1, play.possession.returner)
            credit(team, 'interception_return_yards', play.possession.return_yards, play.possession.returner)
        elif play.possession.how == 'fumble_recovery' and play.possession.return_yards != 0:
            credit(team, 'fumble_returns', 1, play.possession.returner)
            credit(team, 'fumble_return_yards', play.possession.return_yards, play.possession.returner)

    if kick is not None and kick.result == 'return':
        return_team = kick.receiving_team
        if kick.kind == 'punt':
            credit(return_team, 'punt_returns', 1, kick.returner)
            credit(return_team, 'punt_return_yards', kick.return_yards or 0, kick.returner)
        elif kick.kind == 'kickoff':
            credit(return_team, 'kickoff_returns', 1, kick.returner)
            credit(return_team, 'kickoff_return_yards', kick.return_yards or 0, kick.returner)
    if kick is not None and kick.kind == 'field_goal' and kick.result == 'made':
        credit(kick.kicking_team, 'field_goals_made', 1, roles.kicker)

    scoring = play.scoring
    if scoring is not None:
        scorer = _role_team(scoring.team, state, kick)
        if scoring.kind == 'touchdown':
            teams[scorer]['touchdowns'] += 1
            teams[scorer]['points_scored'] += 6
            if scoring.team == 'offense' and event in ('run', 'scramble', 'kneel'):
                credit(scorer, 'rushing_touchdowns', 1, roles.rusher)
            elif scoring.team == 'offense' and event == 'pass_complete':
                credit(scorer, 'passing_touchdowns', 1, roles.passer)
                credit(scorer, 'receiving_touchdowns', 1, roles.receiver)
            else:
                if kick is not None:
                    credit(scorer, 'return_touchdowns', 1, kick.returner)
                elif play.possession is not None:
                    credit(scorer, 'return_touchdowns', 1, play.possession.returner)
        elif scoring.kind == 'field_goal':
            teams[scorer]['points_scored'] += 3
        elif scoring.kind == 'safety':
            teams[scorer]['safeties'] += 1
            teams[scorer]['points_scored'] += 2

    if play.penalty is not None:
        enforced_yards = 0
        if play.penalty.disposition == 'accepted':
            if not isinstance(penalty_enforcement, dict) or penalty_enforcement.get('accepted') is not True:
                raise EventStatisticsError('accepted_penalty_requires_rules_enforcement_result')
            enforced_yards = penalty_enforcement.get('yards')
            if (not isinstance(enforced_yards, (int, float)) or isinstance(enforced_yards, bool)
                    or not math.isfinite(enforced_yards) or enforced_yards < 0):
                raise EventStatisticsError('accepted_penalty_enforced_yards_invalid')
        elif penalty_enforcement is not None:
            if (not isinstance(penalty_enforcement, dict)
                    or penalty_enforcement.get('accepted') is not False):
                raise EventStatisticsError('penalty_enforcement_disposition_mismatch')
        for foul in play.penalty.fouls:
            team = _role_team(foul.team, state, kick)
            teams[team]['penalty_opportunities'] += 1
            credit(team, 'penalties_called', 1, foul.player)
            if play.penalty.disposition == 'accepted':
                credit(team, 'penalties_accepted', 1, foul.player)
                credit(team, 'penalties_accepted_yards', enforced_yards, foul.player)
            else:
                teams[team]['penalties_' + play.penalty.disposition] += 1

    # Convert defaultdicts into ordinary JSON-serializable mappings.
    team_rows = {team: dict(sorted(values.items())) for team, values in sorted(teams.items())}
    player_rows = {pid: {'team': row['team'], 'stats': dict(sorted(row['stats'].items()))}
                   for pid, row in sorted(players.items())}
    unassigned_rows = {team: dict(sorted(values.items())) for team, values in sorted(unattributed.items())}
    result = {'team': team_rows, 'player': player_rows, 'unattributed': unassigned_rows}
    reconcile_credited_stats(result)
    return result


def reconcile_credited_stats(deltas):
    """Check every player-creditable team total against named plus unassigned roles."""
    player_totals = defaultdict(lambda: defaultdict(int))
    for row in deltas['player'].values():
        for field, value in row['stats'].items():
            player_totals[row['team']][field] += value
    for team, values in deltas['team'].items():
        missing = deltas['unattributed'].get(team, {})
        for field in CREDITED_FIELDS:
            expected = values.get(field, 0)
            credited = player_totals[team].get(field, 0) + missing.get(field, 0)
            if credited != expected:
                raise EventStatisticsError(
                    f'stat_accounting:{team}:{field}:team={expected}:player_plus_unassigned={credited}')
        credited_touchdowns = sum(values.get(field, 0) for field in (
            'rushing_touchdowns', 'passing_touchdowns', 'return_touchdowns'))
        if values.get('touchdowns', 0) != credited_touchdowns:
            raise EventStatisticsError(
                f'stat_accounting:{team}:touchdowns:team={values.get("touchdowns", 0)}:'
                f'credited_categories={credited_touchdowns}')
        expected_points = (6 * values.get('touchdowns', 0) + 3 * values.get('field_goals_made', 0)
                           + 2 * values.get('safeties', 0))
        if values.get('points_scored', 0) != expected_points:
            raise EventStatisticsError(
                f'stat_accounting:{team}:points:team={values.get("points_scored", 0)}:'
                f'event_points={expected_points}')
    return True


def try_deltas(record, offense_team, defense_team):
    """Score a separate try record, including a defensive return for two points."""
    contract.validate_try_v2(record)
    if record.offense_team != offense_team:
        raise EventStatisticsError('try_offense_team_disagrees_with_game_state')
    if record.result == 'defensive_return' and record.scoring_team != defense_team:
        raise EventStatisticsError('try_defensive_return_scorer_disagrees_with_game_state')
    teams = {offense_team: {'try_points': 0, 'points_scored': 0},
             defense_team: {'try_points': 0, 'points_scored': 0}}
    if record.result == 'made':
        points = 1 if record.kind == 'extra_point' else 2
        team = offense_team
    elif record.result == 'defensive_return':
        points, team = 2, defense_team
    else:
        points, team = 0, None
    if team is not None:
        teams[team]['try_points'] += points
        teams[team]['points_scored'] += points
    return teams
