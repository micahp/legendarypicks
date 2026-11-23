"""Synthetic integration test; no fixture values represent measured NFL performance."""
import collections

from ball_flight import BallFlight, MovingPlayer
import live_one_play
from test_live_participation import inputs, priors
from test_participation_field import _player


def test_existing_personnel_then_one_live_dropback_to_reducer():
    field, roster, resolved = inputs()
    defense_roster = [_player('def' + str(i), 'DB', i + 1) for i in range(11)]
    defense_resolved = {'schema': 'lp-nfl-resolved-roster-2', 'team': 'MIN', 'blocks': [], 'roles': [],
                        'players': [{'gsis_id': p['gsis_id'], 'pos': 'DB', 'official_eligible': True,
                                     'membership': 'ACTIVE_ROSTER', 'exclusion_reason': None} for p in defense_roster]}
    table = priors()
    table['personnel_first']['personnel_league'] = collections.Counter({'11': 1})
    table['personnel_first']['personnel_cells'] = {}
    table['personnel_first']['personnel_previous'] = {}
    table['personnel_first']['personnel_team'] = {}
    rating = {'source': 'synthetic-test-only', 'source_sha256': 'a' * 64, 'evidence_type': 'synthetic',
              'observed_at': '2026-11-20T00:00:00Z', 'max_yards_per_second': 2.0}
    def assignments(offense, defense):
        result = {}
        wr_index = 0
        for pid, role in offense['players'].items():
            assignment = 'quarterback' if role == 'QB' else 'route' if role == 'WR' else 'block'
            x = 5 if assignment == 'route' and wr_index == 0 else 30 if assignment == 'route' else 0
            if assignment == 'route':
                wr_index += 1
            result[pid] = {'assignment': assignment, 'x': x, 'y': 0, 'vx': 0, 'vy': 0,
                           'speed_rating': dict(rating)}
        for index, pid in enumerate(defense['players']):
            result[pid] = {'assignment': 'coverage', 'x': 5 if index == 0 else 30, 'y': 0,
                           'vx': 0, 'vy': 0, 'reach': 0.3, 'speed_rating': dict(rating)}
        return result
    def throw(state, _decision):
        players = [MovingPlayer(p['player_id'], p['x'], p['y'], 0, 0, 0.2, 4) for p in state['receivers']]
        players += [MovingPlayer(p['player_id'], p['x'], p['y'], 0, 0, p['reach'], 0) for p in state['defenders']]
        return BallFlight(0, 0, 2, 10, 0, 10, 3), players
    state = {'quarter': 1, 'clock': 600, 'offense': 'A', 'defense': 'B', 'down': 1, 'togo': 10, 'yl': 50}
    result = live_one_play.dropback(
        state, field=field, offense_team='KC', season=2026, offense_resolved=resolved,
        defense_resolved=defense_resolved, offense_roster=roster, defense_roster=defense_roster,
        formation_priors=table, p_dropback=0.5, seed=7, defense_positions=['DB'] * 11,
        call_selector=lambda _: 'dropback', assignment_builder=assignments, as_of='2026-11-22T00:00:00Z',
        times=[0], qb_policy=lambda obs: {'action': 'throw', 'target': obs['receivers'][0]['player_id']},
        throw=throw, catch=lambda *_: True, allow_synthetic=True)
    assert len(result['offense']['players']) == len(result['defense']['players']) == 11
    assert result['live_result']['play']['event_type'] == 'pass_complete'
    assert result['live_result']['state_at_whistle']['yl'] == 46
    assert result['live_result']['input_classification'] == 'synthetic'
