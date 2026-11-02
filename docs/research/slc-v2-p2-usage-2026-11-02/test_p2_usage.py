"""Tests for the P2 player usage component (SLC v2 Milestone 3).

Rules under test: availability lag (owner ruling D), shrinkage toward a prior, no leakage from the target game, and loud handling
of missing values. Synthetic rows test each rule. The integration test reads the real published weekly logs.
"""
import datetime as dt
import math
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import p2_usage as p2  # noqa: E402

UTC = dt.timezone.utc


def kick(text):
    return dt.datetime.strptime(text, '%Y-%m-%dT%H:%M').replace(tzinfo=UTC)


def log(gsis='P1', season=2024, game='2024_01_A_B', kickoff='2024-09-08T17:00', share=0.2, off=0.8, team='A'):
    return {'gsis': gsis, 'season': season, 'game_id': game, 'kickoff': kick(kickoff), 'team': team,
            'target_share': share, 'off_pct': off}


# Availability lag

def test_game_is_usable_only_after_kickoff_plus_the_lag():
    game = log(kickoff='2024-09-08T17:00')
    assert not p2.usable(game, cutoff=kick('2024-09-09T02:59'))
    assert p2.usable(game, cutoff=kick('2024-09-09T03:00'))


def test_a_game_after_the_cutoff_is_never_usable():
    game = log(kickoff='2024-09-15T17:00')
    assert not p2.usable(game, cutoff=kick('2024-09-12T12:00'))


def test_lag_is_stated_in_hours_and_recorded():
    assert p2.AVAILABILITY_LAG_HOURS == 10


# Shrinkage

def test_no_history_returns_the_prior():
    assert p2.shrunk_mean([], prior=0.15, k=4) == pytest.approx(0.15)


def test_history_pulls_the_estimate_toward_the_observed_mean_as_games_accumulate():
    few = p2.shrunk_mean([0.5, 0.5], prior=0.1, k=4)
    many = p2.shrunk_mean([0.5] * 400, prior=0.1, k=4)
    assert few < many
    assert abs(many - 0.5) < 0.01


def test_shrinkage_matches_the_formula():
    assert p2.shrunk_mean([0.4, 0.2], prior=0.1, k=4) == pytest.approx((0.4 + 0.2 + 4 * 0.1) / (2 + 4))


# Leakage and prior choice

def test_the_target_game_is_never_an_input():
    rows = [log(game='2024_01_A_B', kickoff='2024-09-08T17:00', share=0.9),
            log(game='2024_02_A_C', kickoff='2024-09-15T17:00', share=0.1)]
    target = log(game='2024_02_A_C', kickoff='2024-09-15T17:00', share=0.1)
    feature = p2.player_feature(rows, target, prior_by_gsis={}, prior_pos=0.2, position='WR', k=4)
    assert feature['games_used'] == 1
    assert feature['game_ids_used'] == ['2024_01_A_B']
    assert all(g != '2024_02_A_C' for g in feature['game_ids_used'])


def test_a_player_without_enough_prior_games_uses_the_position_mean():
    target = log(kickoff='2024-09-15T17:00')
    feature = p2.player_feature([], target, prior_by_gsis={'P1': (2, 0.25)}, prior_pos=0.18, position='WR', k=4)
    assert feature['prior_source'] == 'position_mean'
    assert feature['prior_value'] == pytest.approx(0.18)


def test_a_player_with_enough_prior_games_uses_their_own_prior():
    target = log(kickoff='2024-09-15T17:00')
    feature = p2.player_feature([], target, prior_by_gsis={'P1': (8, 0.31)}, prior_pos=0.18, position='WR', k=4)
    assert feature['prior_source'] == 'player_prior'
    assert feature['prior_value'] == pytest.approx(0.31)


# Missing values fail loudly

def test_a_null_target_share_is_counted_and_not_read_as_zero():
    rows = [log(game='2024_01_A_B', kickoff='2024-09-08T17:00', share=None),
            log(game='2024_02_A_C', kickoff='2024-09-15T17:00', share=0.3)]
    target = log(game='2024_03_A_D', kickoff='2024-09-22T17:00')
    feature = p2.player_feature(rows, target, prior_by_gsis={}, prior_pos=0.2, position='WR', k=4)
    assert feature['null_target_share_games'] == 1
    assert feature['games_used'] == 1
    assert feature['mean_observed'] == pytest.approx(0.3)


def test_an_unknown_gsis_gets_the_unknown_position_and_is_counted():
    assert p2.position_group(None) == 'UNKNOWN'
    assert p2.position_group('ZZ') == 'OTHER'
    assert p2.position_group('WR') == 'WR'


# Integration with the published weekly logs

@pytest.fixture(scope='module')
def logs_2022_2024():
    return p2.load_logs((2022, 2023, 2024))


def test_real_logs_have_gsis_keys_and_the_usage_fields(logs_2022_2024):
    assert logs_2022_2024, 'no logs loaded'
    sample = logs_2022_2024[0]
    assert sample['gsis'].startswith('00-')
    assert 'target_share' in sample and 'off_pct' in sample


def test_real_logs_join_to_a_kickoff_for_every_regular_season_game(logs_2022_2024):
    kickoffs = p2.load_kickoffs()
    reg = [r for r in logs_2022_2024 if r['game_type'] == 'REG']
    missing = {r['game_id'] for r in reg if r['game_id'] not in kickoffs}
    assert not missing, f'{len(missing)} game IDs without a kickoff'
