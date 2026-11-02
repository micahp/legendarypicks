"""Tests for the P1 team play-calling component (SLC v2 Milestone 3): pass-share tendency with a coach-era prior.

Rules under test: availability lag (owner ruling D), head-coach identity carried from earlier games and never from the target
game's populated schedule row (owner ruling P1), prior fallbacks, shrinkage, and no leakage from the target game.
"""
import datetime as dt
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'slc-v2-p2-usage-2026-11-02'))

import p1_team as p1  # noqa: E402

UTC = dt.timezone.utc


def kick(text):
    return dt.datetime.strptime(text, '%Y-%m-%dT%H:%M').replace(tzinfo=UTC)


def tg(team='KC', season=2024, game='2024_01_KC_X', kickoff='2024-09-08T17:00', coach='Andy Reid', share=0.6):
    return {'team': team, 'season': season, 'game_id': game, 'kickoff': kick(kickoff), 'coach': coach,
            'pass_share': share, 'game_type': 'REG'}


# Lag and coach carry-forward

def test_coach_is_carried_from_the_latest_usable_earlier_game():
    history = [tg(game='2024_01', kickoff='2024-09-08T17:00', coach='Coach A'),
               tg(game='2024_02', kickoff='2024-09-15T17:00', coach='Coach B')]
    cutoff = kick('2024-09-16T03:00')
    assert p1.carried_coach(history, cutoff, prior_season_last='Coach Z') == ('Coach B', 'usable_game')


def test_target_game_coach_is_never_used():
    target_game = tg(game='2024_03', kickoff='2024-09-22T17:00', coach='Coach Future')
    history = [tg(game='2024_01', kickoff='2024-09-08T17:00', coach='Coach A')]
    coach, source = p1.carried_coach(history, kick('2024-09-21T16:00'), prior_season_last='Coach Z')
    assert coach == 'Coach A'
    assert coach != target_game['coach']


def test_season_opener_uses_the_prior_season_last_coach():
    coach, source = p1.carried_coach([], kick('2024-09-08T12:00'), prior_season_last='Coach Z')
    assert (coach, source) == ('Coach Z', 'prior_season_last')


def test_no_coach_information_is_counted_as_unknown():
    coach, source = p1.carried_coach([], kick('2024-09-08T12:00'), prior_season_last=None)
    assert (coach, source) == ('UNKNOWN', 'none')


def test_a_game_inside_the_lag_is_not_usable_for_the_carried_coach():
    history = [tg(game='2024_01', kickoff='2024-09-08T17:00', coach='Coach A')]
    coach, source = p1.carried_coach(history, kick('2024-09-09T02:00'), prior_season_last='Coach Z')
    assert (coach, source) == ('Coach Z', 'prior_season_last')


# Priors

def test_coach_era_prior_is_used_when_the_coach_has_enough_prior_games():
    prior_coach = {'Coach A': (10, 0.58)}
    prior_team = {'KC': (17, 0.55)}
    prior, source = p1.prior_for(coach='Coach A', team='KC', prior_by_coach=prior_coach, prior_by_team=prior_team,
                                 league=0.6)
    assert (prior, source) == (0.58, 'coach_era')


def test_team_prior_is_used_when_the_coach_has_too_few_prior_games():
    prior, source = p1.prior_for(coach='Coach A', team='KC', prior_by_coach={'Coach A': (3, 0.4)},
                                 prior_by_team={'KC': (17, 0.55)}, league=0.6)
    assert (prior, source) == (0.55, 'team_prior')


def test_league_prior_is_the_last_fallback():
    prior, source = p1.prior_for(coach='UNKNOWN', team='NEW', prior_by_coach={}, prior_by_team={}, league=0.6)
    assert (prior, source) == (0.6, 'league_prior')


# Shrinkage and leakage

def test_in_season_estimate_shrinks_toward_the_prior():
    history = [tg(game='2024_01', kickoff='2024-09-08T17:00', share=0.9)]
    target = tg(game='2024_02', kickoff='2024-09-15T17:00', share=0.1)
    feature = p1.team_feature(history, target, prior=0.5, prior_source='team_prior', k=4)
    assert feature['estimate'] == pytest.approx((0.9 + 4 * 0.5) / 5)
    assert feature['games_used'] == 1


def test_the_target_game_is_not_in_its_own_feature():
    target = tg(game='2024_02', kickoff='2024-09-15T17:00', share=0.1)
    history = [tg(game='2024_01', kickoff='2024-09-08T17:00', share=0.9), target]
    feature = p1.team_feature(history, target, prior=0.5, prior_source='team_prior', k=4)
    assert feature['game_ids_used'] == ['2024_01']


def test_a_null_pass_share_is_counted_not_read_as_zero():
    history = [tg(game='2024_01', kickoff='2024-09-08T17:00', share=None)]
    target = tg(game='2024_02', kickoff='2024-09-15T17:00', share=0.5)
    feature = p1.team_feature(history, target, prior=0.5, prior_source='team_prior', k=4)
    assert feature['null_metric_games'] == 1
    assert feature['games_used'] == 0
    assert feature['estimate'] == pytest.approx(0.5)


def test_go_rate_is_null_when_a_team_had_no_fourth_down_decision_and_is_counted():
    history = [dict(tg(game='2024_01', kickoff='2024-09-08T17:00'), go_rate=None),
               dict(tg(game='2024_02', kickoff='2024-09-15T17:00'), go_rate=0.5)]
    target = dict(tg(game='2024_03', kickoff='2024-09-22T17:00'), go_rate=0.2)
    feature = p1.team_feature(history, target, prior=0.3, prior_source='team_prior', k=4, metric='go_rate')
    assert feature['null_metric_games'] == 1
    assert feature['games_used'] == 1
    assert feature['estimate'] == pytest.approx((0.5 + 4 * 0.3) / 5)


def test_plays_metric_uses_the_plays_field():
    history = [dict(tg(game='2024_01', kickoff='2024-09-08T17:00'), plays=60.0)]
    target = dict(tg(game='2024_02', kickoff='2024-09-15T17:00'), plays=64.0)
    feature = p1.team_feature(history, target, prior=62.0, prior_source='team_prior', k=4, metric='plays')
    assert feature['estimate'] == pytest.approx((60.0 + 4 * 62.0) / 5)
