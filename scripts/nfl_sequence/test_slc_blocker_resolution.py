"""Focused regression coverage for opt-in SLC blocker-resolution behavior."""
import csv
import hashlib
import json
import random
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import build_blocked_kick_outcomes as blocked_builder  # noqa: E402
import e0_single_play as e0  # noqa: E402
import e1_drive as e1  # noqa: E402
import e2_reference as e2r  # noqa: E402
import game_state as gs  # noqa: E402
import measure_kick_outcomes as mk  # noqa: E402
import qb_decisions as qbd  # noqa: E402
import reducer  # noqa: E402
import slc_engine as slc_engine_module  # noqa: E402
import slc_playcall as slc  # noqa: E402


ARTIFACT_SIZES = {
    'down_dist': 24, 'field': 5, 'score': 15, 'clock': 8,
    'score_clock': 120, 'down_field': 20,
}
STATE = {'quarter': 1, 'clock': 500, 'down': 1, 'togo': 10, 'yl': 50, 'score_diff': 0}


def layer(intercept=0.0):
    teams = ['AAA', 'BBB']
    sizes = dict(ARTIFACT_SIZES, team_down=4 * len(teams))
    artifact = {
        'artifact_id': slc.ARTIFACT_ID, 'reference_season': 2026,
        'recency_tau': 3.0, 'fit_seasons': [2022, 2023, 2024, 2025],
        'primary_plays_only': True, 'penalties': {}, 'fit_iterations': 0,
        'plays': 0, 'frame_sha256': 'blocker-resolution-test', 'teams': teams,
        'intercept': intercept,
        'blocks': {name: [0.0] * size for name, size in sizes.items()},
        'bucket_maps': {}, 'season_effect': 'test',
    }
    artifact['sha256'] = slc._sha(artifact)
    return slc.PlayCallLayer(artifact)


def sample(event, *, play_type=None, index=0, down=1, togo=10, yl=50, yards=4,
           qb_scramble=0, season=2025, game_id=None):
    row = {
        'game_id': game_id or f'G{index // 10}', 'play_id': index, 'season': season,
        'week': 1, 'game_date': '2025-01-01', 'posteam': 'AAA', 'defteam': 'BBB', 'qtr': 1,
        'game_seconds_remaining': 890, 'down': down, 'ydstogo': togo, 'yardline_100': yl,
        'play_type': play_type or ('run' if event == 'run' else 'pass'),
        'yards_gained': yards, 'qb_scramble': qb_scramble, 'penalty': 0,
        'two_point_attempt': 0, 'touchdown': 0, 'interception': 0, 'fumble_lost': 0,
        'sack': 0, 'complete_pass': int(event == 'pass_complete'),
    }
    return (event, row, 6, None)


def key_for(down, togo, yl):
    return (down, e0.ydstogo_bucket(togo), e0.yardline_bucket(yl))


class RunScrambleBackoff(unittest.TestCase):
    def test_sparse_run_cell_backs_off_without_changing_run_intent_and_replays_by_seed(self):
        target = key_for(1, 10, 50)
        broad_rows = [sample('run', index=i, togo=15, yards=3) for i in range(25)]
        source_pool = {key_for(1, 15, 50): broad_rows}
        current = [sample('pass_complete', index=900, play_type='pass')]

        results = []
        for _ in range(2):
            sampler = slc.PlayCallSampler(layer(-100.0), side_teams={'A': 'AAA', 'B': 'BBB'})
            sampler.source_pool = source_pool
            sampler.outcome_backoff_enabled = True
            sampler.allow_sparse_cells = True
            sampler.blocker_fixes = frozenset({'run_scramble_backoff'})
            event, row, _runoff, _spot = sampler.sample(random.Random(44), current, 'A', 'B', state=STATE)
            decision = sampler.decisions[-1]
            self.assertEqual((decision['intent'], decision['outcome_class'], event), ('run', 'run', 'run'))
            self.assertEqual(decision['outcome_fallback'], 'down_field')
            self.assertEqual(decision['outcome_fallback_support_n'], 25)
            self.assertEqual(row['play_type'], 'run')
            results.append((event, row['game_id'], row['play_id'], decision))
        self.assertEqual(results[0], results[1])
        self.assertEqual(target, key_for(1, 10, 50))

    def test_scramble_backoff_keeps_scrambles_distinct_and_rejects_out_of_support_gains(self):
        broad_rows = [sample('run', index=i, togo=15, yards=3, qb_scramble=1) for i in range(25)]
        broad_rows.append(sample('run', index=25, togo=15, yards=8, qb_scramble=1))
        current = [sample('pass_complete', index=900, play_type='pass')]
        sampler = slc.PlayCallSampler(layer(100.0), side_teams={'A': 'AAA', 'B': 'BBB'})
        sampler.source_pool = {key_for(1, 15, 50): broad_rows}
        sampler.outcome_backoff_enabled = True
        sampler.allow_sparse_cells = True
        sampler.scramble_backoff_enabled = True
        sampler.scramble_bounds = {'max_gain_yards': 5, 'max_loss_yards': 4}
        sampler.blocker_fixes = frozenset({'run_scramble_backoff'})
        sampler.participant_chooser = lambda *_: {
            'qb_decision': {'action': 'scramble', 'scramble_probability': 1.0,
                            'scramble_fallback': 'down_field', 'scramble_support_level': 'down_field',
                            'scramble_fallback_support_n': 25},
        }

        event, row, _runoff, _spot = sampler.sample(random.Random(7), current, 'A', 'B', state=STATE)
        decision = sampler.decisions[-1]
        self.assertEqual((decision['intent'], decision['outcome_intent'], decision['outcome_class']),
                         ('dropback', 'run', 'qb_scramble'))
        self.assertEqual(decision['outcome_fallback'], 'down_field')
        self.assertEqual(event, 'run')
        self.assertEqual(row['qb_scramble'], 1)
        self.assertEqual(row['yards_gained'], 3)
        self.assertEqual(decision['scramble_rejected_bounds'], 1)
        self.assertEqual(decision['scramble_eligible_candidates'], 25)
        after, _terminal, _flags = reducer.apply_play(
            {'offense': 'AAA', 'defense': 'BBB', 'down': 1, 'togo': 10, 'yl': 50}, event, row['yards_gained'])
        self.assertEqual(after, {'offense': 'AAA', 'defense': 'BBB', 'down': 2, 'togo': 7, 'yl': 47})

    def test_qb_scramble_decision_uses_supported_context_backoff(self):
        cell = qbd.cell_of(1, 10, 50)
        down_field = (cell[0], cell[2])
        support = {
            'exact_cell': {'scrambles': {}, 'dropbacks': {cell: 100}},
            'down_field': {'scrambles': {down_field: 25}, 'dropbacks': {down_field: 100}},
            'down_distance': {'scrambles': {}, 'dropbacks': {}},
            'field_zone': {'scrambles': {}, 'dropbacks': {}},
            'league_intent': {'scrambles': 25, 'dropbacks': 100},
        }
        table = {
            'league_cell': {}, 'team_cell': {}, 'qb_cell': {}, 'target_qb_cell': {},
            'target_team_cell': {}, 'target_league_cell': {}, 'row_target_roles': {},
            'scramble_cells': set(), 'scramble_support': support,
        }
        self.assertEqual(qbd.scramble_support_level(table, cell), ('down_field', 25))
        seed = next(f'paired-{i}' for i in range(1000)
                    if qbd._rng(f'paired-{i}').random() < 0.25)
        result = qbd.draw(table, 'AAA', 'QB1', 1, 10, 50, {'WR'}, seed,
                          allow_scramble_backoff=True)
        self.assertEqual(result['action'], 'scramble')
        self.assertEqual(result['scramble_fallback'], 'down_field')
        self.assertEqual(result['scramble_fallback_support_n'], 25)

    def test_sparse_e1_cell_delegates_to_opted_in_sampler_before_min_pool_guard(self):
        row = sample('run', index=1, yards=0)[1]

        class SparsePolicy:
            allow_sparse_cells = True

            def __init__(self):
                self.calls = 0

            def sample(self, _rng, _cell, **_kwargs):
                self.calls += 1
                return 'run', row, 1, None

        policy = SparsePolicy()
        start = {'offense': 'AAA', 'defense': 'BBB', 'quarter': 1, 'clock': 30,
                 'down': 4, 'togo': 10, 'yl': 50, 'dir': 1}
        result = e1.simulate(start, 5, {key_for(4, 10, 50): [('run', row, 1, None)]},
                             'sparse-test', sampling_policy=policy)
        self.assertEqual(policy.calls, 1)
        self.assertEqual(result[1], 'turnover_on_downs')


class FieldGoalFeasibility(unittest.TestCase):
    def _kick_results(self, path):
        columns = ('season', 'week', 'play_type', 'field_goal_result', 'kick_distance',
                   'game_id', 'play_id', 'series_result', 'yardline_100')
        with path.open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            play_id = 1
            for distance, makes in ((35, 18), (45, 14), (55, 8), (65, 3)):
                for index in range(20):
                    result = 'made' if index < makes else 'missed'
                    writer.writerow({'season': 2025, 'week': 10, 'play_type': 'field_goal',
                                     'field_goal_result': result, 'kick_distance': distance,
                                     'game_id': f'2025_{distance}_{index}', 'play_id': play_id,
                                     'series_result': 'Field goal' if result == 'made' else 'Missed field goal',
                                     'yardline_100': distance - 17})
                    play_id += 1
            writer.writerow({'season': 2025, 'week': 10, 'play_type': 'field_goal',
                             'field_goal_result': 'blocked', 'kick_distance': 70,
                             'game_id': '2025_MAX_ATTEMPT', 'play_id': 900,
                             'series_result': 'Blocked field goal', 'yardline_100': 53})
            writer.writerow({'season': 2026, 'week': 1, 'play_type': 'field_goal',
                             'field_goal_result': 'made', 'kick_distance': 77,
                             'game_id': '2026_FUTURE', 'play_id': 901,
                             'series_result': 'Field goal', 'yardline_100': 60})

    def test_distance_model_is_cutoff_safe_monotone_and_separates_block_probability(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'kicks.csv'
            self._kick_results(path)
            model = mk.load_field_goal_model(path, eligible_before=(2026, 1))
        short = mk.field_goal_distribution(model, 35)
        long = mk.field_goal_distribution(model, 65)
        self.assertGreater(short['made'], long['made'])
        for distribution in (short, long):
            self.assertAlmostEqual(sum(distribution[name] for name in ('made', 'missed', 'blocked')), 1.0)
            self.assertGreaterEqual(distribution['blocked'], 0.0)
        self.assertEqual(model['max_observed_attempt_yards'], 70)
        self.assertEqual(int(model['max_observed_attempt_source']['play_id']), 900)
        self.assertEqual(model['max_observed_made_yards'], 65)
        self.assertEqual(int(model['max_observed_made_source']['season']), 2025)
        self.assertNotEqual(model['max_observed_attempt_source']['game_id'], '2026_FUTURE')
        with self.assertRaisesRegex(ValueError, 'exceeds cutoff-specific observed maximum'):
            mk.field_goal_distribution(model, 77)

    def test_ordinary_cutoff_exception_and_historical_maximum_filter_field_goal_action(self):
        sampler = slc.PlayCallSampler(layer(0.0))
        sampler.blocker_fixes = frozenset({'long_field_goal_feasibility'})
        sampler.fg_ordinary_cutoff = 60.0
        sampler.field_goal_distance_model = {'max_observed_attempt_yards': 76}
        entry = {'base': Counter({('kick', 'field_goal_attempt'): 1, ('kick', 'punt'): 1})}

        ordinary, rejected, exception = sampler._field_goal_actions(
            entry, {'quarter': 1, 'clock': 500, 'yl': 48, 'score_diff': 0})
        self.assertEqual(ordinary, {'punt'})  # 65 yards is beyond the ordinary 60-yard decision cutoff.
        self.assertTrue(rejected)
        self.assertFalse(exception)

        end_window, rejected, exception = sampler._field_goal_actions(
            entry, {'quarter': 2, 'clock': 60, 'yl': 48, 'score_diff': 0})
        self.assertIn('field_goal_attempt', end_window)
        self.assertFalse(rejected)
        self.assertTrue(exception)

        desperation, _rejected, exception = sampler._field_goal_actions(
            entry, {'quarter': 4, 'clock': 300, 'yl': 48, 'score_diff': -8})
        self.assertIn('field_goal_attempt', desperation)
        self.assertTrue(exception)

        beyond_historical, rejected, _exception = sampler._field_goal_actions(
            entry, {'quarter': 2, 'clock': 10, 'yl': 60, 'score_diff': -21})
        self.assertNotIn('field_goal_attempt', beyond_historical)  # 77 yards exceeds the hard historical ceiling.
        self.assertTrue(rejected)

    def test_rejected_field_goal_leaves_a_supported_go_for_it_action_available(self):
        sampler = slc.PlayCallSampler(layer(-100.0), side_teams={'A': 'AAA', 'B': 'BBB'})
        sampler.blocker_fixes = frozenset({'long_field_goal_feasibility'})
        sampler.fg_ordinary_cutoff = 60.0
        sampler.field_goal_distance_model = {'max_observed_attempt_yards': 76}
        current = [sample('field_goal_attempt', index=10, play_type='field_goal', down=4, togo=10, yl=48),
                   sample('run', index=11, play_type='run', down=4, togo=10, yl=48, yards=2)]
        state = {'quarter': 1, 'clock': 500, 'down': 4, 'togo': 10, 'yl': 48, 'score_diff': 0}
        event, row, _runoff, _spot = sampler.sample(random.Random(2), current, 'A', 'B', state=state)
        self.assertEqual((event, row['play_type']), ('run', 'run'))
        self.assertTrue(sampler.decisions[-1]['fg_rejected_distance'])
        self.assertEqual(sampler.decisions[-1]['fg_rejection_reason'], 'beyond_ordinary_cutoff')


class BlockedKickResolution(unittest.TestCase):
    def test_audited_overlay_is_separate_and_changes_only_source_reviewed_rows(self):
        base = REPO / 'docs/fixtures/e2/blocked_kick_outcomes_2022_2025.csv'
        base_sha = hashlib.sha256(base.read_bytes()).hexdigest()
        with base.open(newline='') as handle:
            base_rows = list(csv.DictReader(handle))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'audited.csv'
            manifest = blocked_builder.apply_source_audit_overlay(base, target)
            with target.open(newline='') as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(hashlib.sha256(base.read_bytes()).hexdigest(), base_sha)
        self.assertEqual(manifest['audit_overlay']['reviewed_record_count'], 5)
        audited = [row for row in rows if row['source_audit_ref']]
        self.assertEqual(len(audited), 5)
        self.assertTrue(all(row['classification_status'] == 'classified_next_snap' for row in audited))
        self.assertTrue(all(row['source_audit_evidence'] and row['next_snap_play_id'] for row in audited))
        self.assertEqual({(row['game_id'], int(float(row['play_id']))) for row in audited},
                         set(blocked_builder.SOURCE_AUDIT))
        source_columns = tuple(base_rows[0])
        output_by_key = {(row['game_id'], int(float(row['play_id']))): row for row in rows}
        for original in base_rows:
            key = (original['game_id'], int(float(original['play_id'])))
            if key not in blocked_builder.SOURCE_AUDIT:
                self.assertEqual({name: output_by_key[key][name] for name in source_columns}, original)

    def test_audited_next_snap_projection_is_rule_legal_for_either_possession_team(self):
        receiving = {
            'kick_type': 'field_goal', 'classification_status': 'classified_next_snap',
            'possession_after_role': 'receiving_team', 'yardline_100': 22,
            'next_snap_yardline_100': 70, 'next_snap_yards_from_los': -8,
            'next_snap_down': 1, 'next_snap_ydstogo': 10,
        }
        receiver_state = {'offense': 'K', 'defense': 'R', 'down': 4, 'togo': 8, 'yl': 20}
        projected = reducer.project_blocked_kick_next_snap(receiving, receiver_state)
        after, terminal, flags = reducer.apply_blocked_kick(receiver_state, 'blocked_field_goal', projected)
        self.assertEqual((after['offense'], after['yl'], terminal, flags['turnover']), ('R', 72, 'turnover', True))

        kicking = {
            **receiving, 'possession_after_role': 'kicking_team',
            'next_snap_yardline_100': 14, 'next_snap_yards_from_los': 8,
        }
        kick_state = {'offense': 'K', 'defense': 'R', 'down': 4, 'togo': 8, 'yl': 20}
        projected = reducer.project_blocked_kick_next_snap(kicking, kick_state)
        after, terminal, flags = reducer.apply_blocked_kick(kick_state, 'blocked_field_goal', projected)
        self.assertEqual((after['offense'], after['yl'], after['down'], terminal), ('K', 12, 1, None))
        self.assertTrue(flags['first_down'])

    def test_reprojected_goal_line_snaps_reduce_distance_to_go_for_both_blocker_cases(self):
        cases = (
            ('punt', '2024_05_MIA_NE', 1249, 'receiving_team', 86, 6, 'blocked_punt', 11),
            ('field_goal', '2025_10_NO_CAR', 2504, 'kicking_team', 1, 1, 'blocked_field_goal', 1),
        )
        fixture = REPO / 'docs/fixtures/e2/blocked_kick_outcomes_2022_2025_audited_v1.csv'
        with fixture.open(newline='') as handle:
            source_rows = list(csv.DictReader(handle))
        int_fields = ('play_id', 'yardline_100', 'clock_runoff_seconds', 'next_snap_yardline_100',
                      'next_snap_down', 'next_snap_ydstogo', 'next_snap_yards_from_los')
        for kick_type, game_id, play_id, role, kick_yline, expected_yline, event, state_togo in cases:
            with self.subTest(game_id=game_id, play_id=play_id):
                source = next(row for row in source_rows
                              if row['game_id'] == game_id and int(row['play_id']) == play_id)
                for field in int_fields:
                    if source.get(field):
                        source[field] = int(source[field])
                self.assertEqual((source['kick_type'], source['classification_status'],
                                  source['possession_after_role']),
                                 (kick_type, 'classified_next_snap', role))
                state = {'offense': 'K', 'defense': 'R', 'down': 4,
                         'togo': state_togo, 'yl': kick_yline}
                game = object.__new__(gs._Game)
                game.ref = SimpleNamespace(
                    blocked_kicks={'records': {kick_type: [source]}, 'sha256': 'a' * 64},
                    blocker_fixes=('blocked_kick_geometry',),
                    contextual_sampler=SimpleNamespace(decisions=[{}]),
                )

                reason, outcome = game._sample_blocked_kick_by_category(
                    kick_type, [source], random.Random(1), 600, 2, state)
                self.assertIsNone(reason)
                self.assertEqual(outcome['next_snap_yardline_100'], expected_yline)
                self.assertEqual(outcome['next_snap_ydstogo'], expected_yline)

                after, _terminal, _flags = reducer.apply_blocked_kick(state, event, outcome)
                self.assertEqual(after['down'], 1)
                self.assertEqual((after['yl'], after['togo']), (expected_yline, expected_yline))

    def test_real_punt_fixture_filters_an_out_of_field_category_before_the_draw(self):
        fixture = e2r.load_blocked_kicks(e2r.AUDITED_BLOCKED_KICKS)
        self.assertEqual(fixture['sha256'], 'f1a29d215aba97addc429136d7fdaef9b28af7f5e6ce27d7c8f2eae25f4a1d22')

        class PreferOutOfFieldCategory:
            def __init__(self, wanted):
                self.wanted = wanted
                self.categories = None

            def choices(self, categories, weights, k):
                self.categories = list(categories)
                return [self.wanted if self.wanted in categories else categories[0]]

            @staticmethod
            def choice(rows):
                return rows[0]

        cases = (
            (92, 8, 'next_snap:receiving_team',
             'next_snap:receiving_team:blocked_kick_next_snap_outside_field'),
            (98, 2, 'recovery:receiving_team:0',
             'recovery:receiving_team:0:blocked_kick_receiving_return_outside_field'),
        )
        for yardline, togo, invalid_category, exclusion_prefix in cases:
            with self.subTest(yardline=yardline, invalid_category=invalid_category):
                game = object.__new__(gs._Game)
                game.ref = SimpleNamespace(blocked_kicks=fixture, blocker_fixes=('blocked_kick_geometry',),
                                           contextual_sampler=SimpleNamespace(decisions=[{}]))
                state = {'offense': 'A', 'defense': 'B', 'down': 4, 'togo': togo, 'yl': yardline}
                rng = PreferOutOfFieldCategory(invalid_category)

                reason, outcome = game._sample_blocked_kick_by_category(
                    'punt', fixture['records']['punt'], rng, 300, 1, state)

                self.assertIsNone(reason)
                self.assertNotIn(invalid_category, rng.categories)
                self.assertNotEqual(outcome['geometry_category'], invalid_category)
                self.assertGreater(outcome['geometry_candidate_count'], 0)
                self.assertTrue(any(key.startswith(exclusion_prefix)
                                    for key in outcome['geometry_category_exclusions']))

    def test_impossible_projection_is_rejected_without_clamping_and_unknown_records_stay_blocked(self):
        source = {
            'kick_type': 'field_goal', 'classification_status': 'classified_next_snap',
            'possession_after_role': 'receiving_team', 'yardline_100': 22,
            'next_snap_yardline_100': 99, 'next_snap_yards_from_los': 21,
            'next_snap_down': 1, 'next_snap_ydstogo': 10,
        }
        with self.assertRaisesRegex(reducer.UnmodelledOutcome, 'outside_field'):
            reducer.project_blocked_kick_next_snap(source, {'yl': 1})

        unresolved = {'kick_type': 'field_goal',
                      'classification_status': 'guarded_penalty_fumble_or_review'}
        game = object.__new__(gs._Game)
        game.ref = SimpleNamespace(
            blocked_kicks={'records': {'field_goal': [unresolved]}, 'sha256': 'a' * 64},
            blocker_fixes=('blocked_kick_geometry',),
            contextual_sampler=SimpleNamespace(decisions=[{}]),
        )
        reason, outcome = game._sample_blocked_kick_by_category(
            'field_goal', [unresolved], random.Random(1), 100, 1,
            {'offense': 'K', 'defense': 'R', 'down': 4, 'togo': 8, 'yl': 20})
        self.assertEqual(reason, 'blocked_kick_outcome_unresolved:field_goal:guarded_penalty_fumble_or_review')
        self.assertIsNone(outcome)


class SafetyFreeKickBoundaries(unittest.TestCase):
    def test_q1_and_q3_safety_kicks_advance_the_period_before_the_distinct_kick(self):
        for quarter, next_quarter in ((1, 2), (3, 4)):
            game = object.__new__(gs._Game)
            game.quarter, game.clock = quarter, 0
            applied = []
            game._new_quarter = lambda _kind, game=game: setattr(game, 'quarter', game.quarter + 1)
            game._apply = lambda then, clock_rule=None, applied=applied: applied.append((then, clock_rule))
            then = ('kick', 'safety_free_kick', 'B', 'A')
            game._continue(then)
            self.assertEqual(game.quarter, next_quarter)
            self.assertEqual(applied, [(then, gs.PRACTICE_RULE)])

    def test_overtime_opening_possession_safety_ends_after_the_safety_free_kick(self):
        game = object.__new__(gs._Game)
        game.quarter = 5
        game.overtime = {'possessions': ['B'], 'kicking_team': 'A'}
        game.points = {'A': 2, 'B': 0}
        game.status = None
        game._continue(('kick', 'safety_free_kick', 'B', 'A'))
        self.assertEqual(game.status, 'complete_overtime')
        self.assertEqual(game.overtime['winner'], 'A')


class BlockerReporting(unittest.TestCase):
    def test_fallback_and_source_audit_metrics_retain_class_team_and_situation(self):
        decision = {
            'state': {'team': 'AAA', 'down': 4, 'togo': 8, 'yardline_100': 40},
            'outcome_class': 'qb_scramble', 'outcome_fallback': 'down_field',
            'outcome_fallback_support_n': 25, 'qb_scramble_fallback': 'field_zone',
            'scramble_fallback_support_n': 55, 'scramble_support_level': 'field_zone',
            'scramble_rejected_bounds': 1, 'scramble_eligible_candidates': 25,
            'fg_fallback_level': 'league_distance_curve', 'fg_distribution_support_n': 12,
            'fg_rejected_distance': True, 'fg_rejection_reason': 'beyond_ordinary_cutoff',
            'fg_long_range_exception': False, 'blocked_kick_geometry_category': 'next_snap:receiving_team',
            'blocked_kick_geometry_candidates': 2,
        }
        record = {
            'drives': [{'plays': [{'outcome': {'blocked_kick': {
                'source_audit_ref': 'blocked-kick-source-audit-v1'}}}]}],
            'kickoffs': [{'kind': 'safety_free_kick'}],
        }
        summary = slc_engine_module._blocker_resolution_summary(
            [decision], ['run_scramble_backoff', 'long_field_goal_feasibility', 'blocked_kick_source_audit'], record)
        self.assertEqual(summary['scramble_outcome_fallback_level'], {'down_field': 1})
        self.assertEqual(summary['blocked_kick_source_audit_transitions'], 1)
        self.assertEqual(summary['safety_free_kicks'], 1)
        self.assertEqual(summary['blocked_kick_geometry_categories'], {'next_snap:receiving_team': 1})
        usage = next(row for row in summary['fallback_usage'] if row['kind'] == 'scramble_outcome')
        self.assertEqual((usage['team'], usage['down'], usage['distance_bucket'], usage['field_zone_bucket']),
                         ('AAA', 4, '7-10', '20-49'))
        self.assertEqual(usage['support_n'], {'min': 25, 'mean': 25.0, 'max': 25})


if __name__ == '__main__':
    unittest.main()
