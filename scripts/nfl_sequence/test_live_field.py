"""Synthetic field geometry; these fixture values are not NFL player ratings."""
import copy

import pytest

from ball_flight import BallFlight, MovingPlayer
import live_field


def fixture():
    rating = {'source': 'synthetic-test-only', 'source_sha256': 'a' * 64, 'evidence_type': 'synthetic',
              'observed_at': '2026-11-20T00:00:00Z', 'max_yards_per_second': 2.0}
    offense, defense, resolved = [], [], {}
    for side, lineup in (('offense', offense), ('defense', defense)):
        rows = []
        for i in range(11):
            pid = f'{side}{i}'
            pos = ('QB' if i == 0 else 'WR' if i == 1 else 'OL') if side == 'offense' else 'DB'
            assignment = ('quarterback' if i == 0 else 'route' if i == 1 else 'block') if side == 'offense' else 'coverage'
            x = (-1 if i == 0 else 5 if i == 1 else -5) if side == 'offense' else (5 if i == 0 else 30)
            lineup.append({'player_id': pid, 'position': pos, 'assignment': assignment, 'x': x, 'y': 0,
                           'vx': 1 if side == 'offense' and i == 0 else 0, 'vy': 0,
                           'speed_rating': dict(rating), 'reach': 0.3})
            rows.append({'gsis_id': pid, 'pos': pos, 'official_eligible': True, 'membership': 'ACTIVE_ROSTER',
                         'exclusion_reason': None})
        resolved[side] = {'schema': 'lp-nfl-resolved-roster-2', 'blocks': [], 'players': rows, 'roles': [],
                          'as_of_utc': '2026-11-22T00:00:00Z'}
    return offense, defense, resolved


def test_complete_dropback_from_roster_to_reducer_without_historical_row():
    offense, defense, resolved = fixture()
    seen = []
    def qb_policy(state):
        seen.append((state['seconds'], state['qb']['x']))
        return {'action': 'wait'} if state['seconds'] == 0 else {'action': 'throw', 'target': 'offense1'}
    def throw(state, _decision):
        players = [MovingPlayer('offense1', state['receivers'][0]['x'], 0, 0, 0, 0.2, 4)]
        players += [MovingPlayer(p['player_id'], p['x'], p['y'], 0, 0, p['reach'], 0) for p in state['defenders']]
        return BallFlight(state['qb']['x'], 0, 2, 10, 0, 10, 3), players
    state = {'quarter': 1, 'clock': 600, 'offense': 'A', 'defense': 'B', 'down': 1, 'togo': 10, 'yl': 50}
    result = live_field.dropback(state, offense=offense, defense=defense, resolved=resolved,
                                 as_of='2026-11-22T00:00:00Z', formation='fixture-formation', call='dropback', times=[0, 1],
                                 qb_policy=qb_policy, throw=throw, catch=lambda *_: True, allow_synthetic=True)
    assert seen == [(0, -1), (1, 0)]
    assert result['play']['event_type'] == 'pass_complete'
    assert result['input_classification'] == 'synthetic'
    assert result['state_at_whistle']['yl'] == 46
    assert result['clock_at_whistle'] == 598
    assert {p['player_id'] for p in result['player_statistics']} == {'offense0', 'offense1'}
    assert 'sampled_from' not in result['play']['outcome']
    replay = live_field.dropback(state, offense=offense, defense=defense, resolved=resolved,
                                 as_of='2026-11-22T00:00:00Z', formation='fixture-formation', call='dropback',
                                 times=[0, 1], qb_policy=qb_policy, throw=throw, catch=lambda *_: True, allow_synthetic=True)
    assert replay == result


def test_lineup_rejects_ineligible_players_and_post_cutoff_ratings():
    offense, defense, resolved = fixture()
    invalid = copy.deepcopy(resolved)
    invalid['offense']['players'][0]['official_eligible'] = False
    with pytest.raises(ValueError, match='live_field_ineligible_player'):
        live_field.validate_lineups(offense, defense, invalid, '2026-11-22T00:00:00Z', allow_synthetic=True)
    offense[0]['speed_rating']['observed_at'] = '2026-11-23T00:00:00Z'
    with pytest.raises(ValueError, match='live_field_invalid_rating_provenance'):
        live_field.validate_lineups(offense, defense, resolved, '2026-11-22T00:00:00Z', allow_synthetic=True)


def test_synthetic_and_unverified_ratings_are_not_real_evidence():
    offense, defense, resolved = fixture()
    with pytest.raises(ValueError, match='live_field_synthetic_rating_not_allowed'):
        live_field.validate_lineups(offense, defense, resolved, '2026-11-22T00:00:00Z')
    offense[0]['speed_rating']['evidence_type'] = 'estimated'
    with pytest.raises(ValueError, match='live_field_rating_not_verified'):
        live_field.validate_lineups(offense, defense, resolved, '2026-11-22T00:00:00Z')
