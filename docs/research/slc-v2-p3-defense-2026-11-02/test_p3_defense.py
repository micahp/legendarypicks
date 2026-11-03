"""Tests for the P3 defensive matchup component (SLC v2 Milestone 3).

P3 models yards per opportunity allowed to a receiving group (WR, TE, RB), a rushing group (RB) and passing (QB), with volume
kept separate from efficiency. The opponent adjustment uses the opponent offense's prior-season strength only.
"""
import datetime as dt
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'slc-v2-p2-usage-2026-11-02'))

import p3_defense as p3  # noqa: E402

UTC = dt.timezone.utc


def kick(text):
    return dt.datetime.strptime(text, '%Y-%m-%dT%H:%M').replace(tzinfo=UTC)


def obs(game='2024_01', kickoff='2024-09-08T17:00', defense='DAL', offense='PHI', yards=6.0, opportunities=10, tds=0):
    return {'season': 2024, 'game_id': game, 'kickoff': kick(kickoff), 'defense': defense, 'offense': offense,
            'yards': yards, 'opportunities': opportunities, 'tds': tds}


# Lag, leakage

def test_only_usable_earlier_games_of_the_same_defense_enter_the_estimate():
    target = obs(game='2024_03', kickoff='2024-09-22T17:00', defense='DAL', yards=9.0)
    history = [obs(game='2024_01', kickoff='2024-09-08T17:00', defense='DAL', yards=4.0),
               obs(game='2024_02', kickoff='2024-09-15T17:00', defense='NYG', yards=12.0),
               target]
    feature = p3.defense_feature(history, target, league=6.0, opponent_adjust=None, k=8)
    assert feature['game_ids_used'] == ['2024_01']


def test_the_target_game_is_never_an_input():
    target = obs(game='2024_02', kickoff='2024-09-15T17:00', defense='DAL', yards=9.0)
    feature = p3.defense_feature([target], target, league=6.0, opponent_adjust=None, k=8)
    assert feature['games_used'] == 0
    assert feature['effect'] == 0.0


# Opponent adjustment uses prior-season strength only

def test_opponent_adjustment_uses_the_prior_season_strength_of_the_target_offense():
    target = obs(game='2024_03', kickoff='2024-09-22T17:00', defense='DAL', offense='PHI')
    strength_prior = {'PHI': 7.4, 'NYG': 5.0}
    feature = p3.defense_feature([], target, league=6.0, opponent_adjust=strength_prior, k=8, league_strength=6.0)
    assert feature['prediction'] == pytest.approx(6.0 + (7.4 - 6.0))


def test_no_opponent_adjustment_leaves_the_league_plus_effect():
    target = obs(game='2024_03', kickoff='2024-09-22T17:00', defense='DAL', offense='PHI')
    feature = p3.defense_feature([], target, league=6.0, opponent_adjust=None, k=8, league_strength=6.0)
    assert feature['prediction'] == pytest.approx(6.0)


def test_an_earlier_game_residual_removes_its_own_opponent_strength():
    prior = {'NYG': 8.0, 'PHI': 6.0}
    early = obs(game='2024_01', kickoff='2024-09-08T17:00', defense='DAL', offense='NYG', yards=8.0)
    target = obs(game='2024_03', kickoff='2024-09-22T17:00', defense='DAL', offense='PHI')
    feature = p3.defense_feature([early], target, league=6.0, opponent_adjust=prior, k=0, league_strength=6.0)
    assert feature['effect'] == pytest.approx(8.0 - 6.0 - (8.0 - 6.0))


# Shrinkage and sparse touchdowns

def test_the_effect_shrinks_toward_zero_with_k_pseudo_games():
    early = obs(game='2024_01', kickoff='2024-09-08T17:00', defense='DAL', offense='PHI', yards=10.0)
    target = obs(game='2024_02', kickoff='2024-09-15T17:00', defense='DAL', offense='PHI')
    feature = p3.defense_feature([early], target, league=6.0, opponent_adjust=None, k=4)
    assert feature['effect'] == pytest.approx((10.0 - 6.0) / (1 + 4))


def test_touchdown_rates_use_a_much_stronger_prior_than_yards():
    assert p3.K_TD > p3.K_YARDS
    assert p3.K_TD >= 40


# Missing values and volume

def test_a_defense_game_with_no_opportunities_is_counted_not_averaged_in():
    rows = [obs(game='2024_01', kickoff='2024-09-08T17:00', defense='DAL', yards=None, opportunities=0)]
    target = obs(game='2024_02', kickoff='2024-09-15T17:00', defense='DAL')
    feature = p3.defense_feature(rows, target, league=6.0, opponent_adjust=None, k=4)
    assert feature['empty_defense_games'] == 1
    assert feature['games_used'] == 0


def test_volume_is_reported_separately_from_efficiency():
    early = obs(game='2024_01', kickoff='2024-09-08T17:00', defense='DAL', yards=6.0, opportunities=40)
    target = obs(game='2024_02', kickoff='2024-09-15T17:00', defense='DAL')
    feature = p3.defense_feature([early], target, league=6.0, opponent_adjust=None, k=4)
    assert feature['volume_mean'] == pytest.approx(40.0)
    assert 'effect' in feature
