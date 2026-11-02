"""Tests for the PBV1 package-level sampler (spec: docs/research/PBV1-SAMPLER-SPEC-2026-11-02.md).

Synthetic plays test each rule. The integration test rebuilds the HPV1 scrimmage total from the validated frame builder.
"""
import math
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', '..', '..', 'gridiron-playbooks-research', 'pipeline'))

import pbv1_sampler as pb  # noqa: E402


def play(season=2023, game='G1', team='KC', family='pass', down='1', distance='d7_9', red=0, package='11'):
    return {'season': season, 'game_id': game, 'team': team, 'family': family, 'down': down,
            'distance': distance, 'red_zone': red, 'package': package}


TRAIN = (
    [play(package='11', distance='d7_9')] * 30
    + [play(package='12', distance='d7_9')] * 10
    + [play(package='11', distance='d1_2', red=0)] * 5
    + [play(family='run', package='21', down='2', distance='d3_4')] * 4
)


# Sampler probabilities

def test_sampler_distribution_sums_to_one_for_a_supported_cell():
    model = pb.fit(TRAIN)
    dist = pb.sampler_dist(model, ('pass', '1', 'd7_9', 0), K=20)
    assert math.isclose(sum(dist.values()), 1.0)


def test_empty_cell_falls_back_exactly_to_the_parent():
    model = pb.fit(TRAIN)
    cell = pb.sampler_dist(model, ('pass', '1', 'd10_14', 0), K=20)
    parent = pb.sampler_dist(model, ('pass', '1', 'd7_9', 1), K=20)
    assert cell == parent


def test_large_cell_count_dominates_the_parent_prior():
    counts = [play(package='11', distance='d7_9')] * 5000 + [play(package='12', distance='d7_9')] * 5000
    model = pb.fit(counts + [play(package='21', distance='d1_2')])
    dist = pb.sampler_dist(model, ('pass', '1', 'd7_9', 0), K=20)
    assert abs(dist['11'] - 0.5) < 0.01
    assert abs(dist['12'] - 0.5) < 0.01


def test_package_unseen_in_the_parent_gets_no_mass():
    model = pb.fit(TRAIN + [play(family='run', down='1', package='22', distance='d1_2')])
    dist = pb.sampler_dist(model, ('pass', '1', 'd7_9', 0), K=20)
    assert '22' not in dist


def test_parent_with_no_training_support_returns_no_distribution():
    model = pb.fit(TRAIN)
    assert pb.sampler_dist(model, ('pass', '4', 'd1_2', 0), K=20) == {}


# Baselines and support

def test_unshrunk_cell_gives_zero_to_a_package_seen_only_in_the_parent():
    model = pb.fit(TRAIN)
    cell = pb.cell_dist(model, ('pass', '1', 'd1_2', 0))
    assert cell == {'11': 1.0}
    assert pb.sampler_dist(model, ('pass', '1', 'd1_2', 0), K=20)['12'] > 0


def test_package_supported_by_the_parent_is_unsupported_only_for_the_unshrunk_cell():
    model = pb.fit(TRAIN)
    unseen_in_cell = play(family='pass', down='1', distance='d1_2', red=0, package='12')
    scores = pb.score_play(model, unseen_in_cell, K=20)
    assert scores['sampler'] is not None
    assert scores['b1'] is None


def test_package_never_observed_in_the_parent_is_unsupported_for_every_arm():
    model = pb.fit(TRAIN)
    never = play(family='pass', down='1', distance='d1_2', red=0, package='99')
    scores = pb.score_play(model, never, K=20)
    assert scores['sampler'] is None
    assert scores['b1'] is None
    assert scores['b0'] is None


def test_training_ignores_plays_from_outside_the_training_seasons():
    plays = [play(season=2024, package='22')] * 50 + TRAIN
    model = pb.fit(plays, train_seasons=(2022, 2023))
    assert '22' not in model['marginal']


def test_marginal_baseline_is_the_training_package_share():
    model = pb.fit(TRAIN)
    assert pb.marginal_dist(model) == pytest.approx({'11': 35 / 49, '12': 10 / 49, '21': 4 / 49})


def test_cell_with_no_training_plays_is_unsupported_for_b1():
    model = pb.fit(TRAIN)
    assert pb.cell_dist(model, ('pass', '1', 'd15p', 0)) is None


# Bootstrap over games

def test_bootstrap_is_deterministic_for_a_fixed_seed():
    per_game = [(1.0, 100), (-1.0, 1), (0.0, 50)]
    first = pb.game_bootstrap_ci(per_game, draws=2000, seed=20261102)
    second = pb.game_bootstrap_ci(per_game, draws=2000, seed=20261102)
    assert first == second
    assert first[0] < first[1]


def test_identical_games_give_a_degenerate_interval_at_the_point_estimate():
    per_game = [(0.3, 10)] * 5
    lo, hi = pb.game_bootstrap_ci(per_game, draws=500, seed=20261102)
    assert lo == pytest.approx(0.03)
    assert hi == pytest.approx(0.03)


def test_bootstrap_interval_contains_the_point_estimate_for_a_symmetric_sample():
    per_game = [(0.5, 10), (-0.5, 10), (0.2, 10), (-0.2, 10)]
    lo, hi = pb.game_bootstrap_ci(per_game, draws=4000, seed=20261102)
    point = sum(s for s, _ in per_game) / sum(n for _, n in per_game)
    assert lo <= point <= hi


def test_bootstrap_uses_the_spec_seed_and_draw_count():
    assert pb.BOOTSTRAP_DRAWS == 10000
    assert pb.BOOTSTRAP_SEED == 20261102


# Integration with the validated HPV1 frame

@pytest.fixture(scope='module')
def hpv1_all_season_scrimmage():
    import hpv1_build as hb
    total = 0
    for season in (2022, 2023, 2024, 2025):
        rows, _ = hb.season_frame(season)
        total += int((rows['play_class'] == 'scrimmage').sum())
    return total


def test_frame_scrimmage_total_matches_the_hpv1_joint_total(hpv1_all_season_scrimmage):
    assert hpv1_all_season_scrimmage == 139798
