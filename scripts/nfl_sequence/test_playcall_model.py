import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import playcall_model as pm  # noqa: E402
import run_playcall_eval as rpe  # noqa: E402

KEYS =('season', 'team', 'down', 'dist', 'field', 'score', 'clock', 'y', 'flagged', 'game')


def frame_from(rows, teams=None):
    arrays = {k: np.array([r[i] for r in rows], dtype=bool if k == 'flagged' else np.int64) for i, k in enumerate(KEYS)}
    return pm.Frame(arrays, teams or {'AAA': 0})


def arrays_from(rows):
    return {k: np.array([r[i] for r in rows], dtype=bool if k == 'flagged' else np.int64) for i, k in enumerate(KEYS)}


class Buckets(unittest.TestCase):
    def test_score_margin_edges(self):
        label = lambda d: pm.SCORE_BUCKETS[pm.score_bucket(d)]  # noqa: E731
        self.assertEqual(label(0), 'tied')
        self.assertEqual(label(2), 'up1_2')
        self.assertEqual(label(-2), 'dn1_2')
        self.assertEqual(label(3), 'up3')
        self.assertEqual(label(-6), 'dn4_6')
        self.assertEqual(label(7), 'up7')
        self.assertEqual(label(-7), 'dn7')
        self.assertEqual(label(14), 'up11_14')
        self.assertEqual(label(15), 'up15p')
        self.assertEqual(label(-15), 'dn15p')

    def test_distance_edges(self):
        self.assertEqual(pm.distance_bucket(1), 0)
        self.assertEqual(pm.distance_bucket(2), 0)
        self.assertEqual(pm.distance_bucket(15), 5)

    def test_field_edges(self):
        self.assertEqual(pm.field_bucket(85), 0)
        self.assertEqual(pm.field_bucket(60), 1)
        self.assertEqual(pm.field_bucket(30), 2)
        self.assertEqual(pm.field_bucket(15), 3)
        self.assertEqual(pm.field_bucket(10), 4)

    def test_clock_boundaries(self):
        name = lambda q, s: pm.CLOCK_BUCKETS[pm.clock_bucket(q, s)]  # noqa: E731
        self.assertEqual(name(1, 900), 'q1')
        self.assertEqual(name(2, 120), 'q2_2min')
        self.assertEqual(name(2, 121), 'q2')
        self.assertEqual(name(3, 0), 'q3')
        self.assertEqual(name(4, 120), 'q4_2min')
        self.assertEqual(name(4, 300), 'q4_late')
        self.assertEqual(name(4, 301), 'q4')
        self.assertEqual(name(5, None), 'ot')

    def test_a_regulation_play_needs_a_clock(self):
        with self.assertRaises(ValueError):
            pm.clock_bucket(4, None)

    def test_seconds_in_quarter_drives_the_late_and_two_minute_buckets(self):
        self.assertEqual(pm.CLOCK_BUCKETS[pm.clock_bucket(4, 900 - 600)], 'q4_late')
        self.assertEqual(pm.CLOCK_BUCKETS[pm.clock_bucket(4, 900 - 800)], 'q4_2min')


class Selection(unittest.TestCase):
    def test_flagged_scores_are_excluded_unless_asked_for(self):
        base = {'intent': 'run', 'down': 1, 'ydstogo': 10, 'yardline_100': 50, 'qtr': 1,
                'score_status': 'pre_play_nflverse_raw'}
        flagged = dict(base, score_status='flagged_continuity_exception')
        self.assertTrue(pm.keep_play(base, include_flagged=False))
        self.assertFalse(pm.keep_play(flagged, include_flagged=False))
        self.assertTrue(pm.keep_play(flagged, include_flagged=True))

    def test_special_teams_and_unknown_intents_are_not_modelled(self):
        base = {'intent': 'special_teams', 'down': 4, 'ydstogo': 10, 'yardline_100': 50, 'qtr': 1,
                'score_status': 'pre_play_nflverse_raw'}
        self.assertFalse(pm.keep_play(base, include_flagged=False))
        self.assertFalse(pm.keep_play(dict(base, intent='unknown'), include_flagged=False))

    def test_the_holdout_is_refused_before_any_row_is_read(self):
        with self.assertRaises(ValueError) as caught:
            pm.load_frame(range(2024, 2027))
        self.assertIn('holdout', str(caught.exception))
        with self.assertRaises(ValueError):
            pm.load_frame_cached(Path('/nonexistent/cache.npz'), range(2024, 2027))


class Design(unittest.TestCase):
    def test_team_group_is_sized_from_the_frame_not_from_32(self):
        rows = [(2024, t, 0, 0, 0, 7, 3, 1, False, t) for t in range(35)]
        teams = {f'T{t:02d}': t for t in range(35)}
        design = pm.Design(frame_from(rows, teams=teams))
        self.assertEqual(design.sizes['team_down'], 35 * pm.DOWN_COUNT)

    def test_the_design_is_built_once_with_one_nonzero_per_group_per_row(self):
        rows = [(2024, 0, 1, 2, 2, 7, 3, 1, False, 0), (2023, 1, 0, 0, 0, 0, 0, 0, False, 1)]
        design = pm.Design(frame_from(rows, teams={'AAA': 0, 'BBB': 1}))
        self.assertEqual(design.X.shape, (2, design.width))
        self.assertEqual(np.diff(design.X.indptr).tolist(), [9, 9])

    def test_an_unknown_team_contributes_no_team_effect(self):
        rows = ([(2024, 0, 0, 0, 0, 7, 3, 1, False, i) for i in range(3)]
                + [(2024, 1, 0, 0, 0, 7, 3, 0, False, 3 + i) for i in range(3)])
        teams = {'AAA': 0, 'BBB': 1}
        frame = frame_from(rows, teams=teams)
        design = pm.Design(frame)
        prep = pm.prepare(design, np.arange(len(frame)), ('team_down',))
        y = frame.a['y'].astype(float)
        beta, _ = pm.fit_prepared(design, prep, y, None, {'team_down': 1.0})
        aaa = pm.modelled_probability(design, prep['cols'], beta, teams, 1, 5, 'opp_side', 7, 'q1', team='AAA')
        bbb = pm.modelled_probability(design, prep['cols'], beta, teams, 1, 5, 'opp_side', 7, 'q1', team='BBB')
        unknown = pm.modelled_probability(design, prep['cols'], beta, teams, 1, 5, 'opp_side', 7, 'q1', team='ZZZ')
        self.assertGreater(aaa, bbb)
        beta_league = np.zeros_like(beta)
        beta_league[0] = beta[0]
        league = pm.modelled_probability(design, prep['cols'], beta_league, teams, 1, 5, 'opp_side', 7, 'q1')
        self.assertAlmostEqual(unknown, league, places=12)

    def test_an_unseen_season_contributes_nothing(self):
        rows = [(2010, 0, 0, 0, 0, 7, 3, 1, False, 0), (2010, 0, 0, 0, 0, 7, 3, 0, False, 1)]
        design = pm.Design(frame_from(rows))
        unseen = design.matrix(arrays_from([(2025, 0, 0, 0, 0, 7, 3, 0, False, 0)]))
        self.assertEqual(int(unseen.nnz), 8)  # intercept plus the seven groups that do not involve season


class Fit(unittest.TestCase):
    def test_a_score_effect_is_recovered_in_the_right_direction(self):
        rng = np.random.default_rng(3)
        rows = []
        for i in range(4000):
            trailing = i % 2 == 0
            p = 0.8 if trailing else 0.3
            rows.append((2010, 0, 1, 2, 0, pm.score_bucket(-7) if trailing else pm.score_bucket(7), 3,
                         int(rng.random() < p), False, i))
        frame = frame_from(rows)
        design = pm.Design(frame)
        prep = pm.prepare(design, np.arange(len(frame)), ('score',))
        beta, _ = pm.fit_prepared(design, prep, frame.a['y'].astype(float), None, {'score': 1.0})
        trailing_p = pm.modelled_probability(design, prep['cols'], beta, frame.teams, 2, 6, 'opp_side', -7, 'q3')
        leading_p = pm.modelled_probability(design, prep['cols'], beta, frame.teams, 2, 6, 'opp_side', 7, 'q3')
        self.assertGreater(trailing_p, 0.6)
        self.assertLess(leading_p, 0.45)

    def test_a_warm_start_reaches_the_same_optimum(self):
        rows = [(2010, 0, 1, 2, 0, pm.score_bucket(s), 3, int(i % 3 == 0), False, i)
                for i, s in enumerate([-7, 7, 0, 3] * 300)]
        frame = frame_from(rows)
        design = pm.Design(frame)
        prep = pm.prepare(design, np.arange(len(frame)), pm.GROUP_NAMES)
        y = frame.a['y'].astype(float)
        cold, _ = pm.fit_prepared(design, prep, y, None, {g: 10.0 for g in pm.GROUP_NAMES})
        warm, _ = pm.fit_prepared(design, prep, y, None, {g: 10.0 for g in pm.GROUP_NAMES}, start=cold)
        np.testing.assert_allclose(cold, warm, atol=1e-4)

    def test_recency_weights_decay_and_none_is_equal_weighting(self):
        seasons = np.array([2010, 2023])
        self.assertIsNone(pm.recency_weights(seasons, 2024, None))
        weights = pm.recency_weights(seasons, 2024, 3.0)
        self.assertGreater(weights[1], weights[0])
        self.assertAlmostEqual(weights[1], np.exp(-1 / 3.0))


class Baselines(unittest.TestCase):
    def test_the_24_cell_falls_back_to_the_league_rate_for_a_thin_cell(self):
        rates = pm.cell24(np.array([1.0, 0.0]), np.array([0, 0]), minimum=20)
        self.assertAlmostEqual(float(rates[0]), 0.5)
        self.assertEqual(len(rates), 24)

    def test_the_24_cell_uses_the_cell_rate_once_it_has_enough_plays(self):
        y = np.array([1.0] * 20 + [0.0] * 10)
        cells = np.zeros(30, dtype=np.int64)
        self.assertAlmostEqual(float(pm.cell24(y, cells, minimum=20)[0]), 2 / 3)


class Query(unittest.TestCase):
    def test_observed_counts_report_plays_dropbacks_and_seasons(self):
        frame = frame_from([(2010, 0, 1, 2, 2, pm.score_bucket(0), 3, 1, False, 0),
                            (2011, 0, 1, 2, 2, pm.score_bucket(0), 3, 0, False, 1)])
        counts = pm.observed_counts(frame, 2, 6, 'opp_side', 0, 'q3')
        self.assertEqual(counts['plays'], 2)
        self.assertEqual(counts['dropbacks'], 1)
        self.assertAlmostEqual(counts['observed_dropback_rate'], 0.5)
        self.assertEqual(counts['seasons'], [2010, 2011])


def synthetic_frame(seed=11, n=3000):
    rng = np.random.default_rng(seed)
    score = rng.integers(0, 15, n)
    arrays = {'season': rng.integers(2010, 2026, n), 'team': rng.integers(0, 4, n), 'down': rng.integers(0, 4, n),
              'dist': rng.integers(0, 6, n), 'field': rng.integers(0, 5, n), 'score': score, 'clock': rng.integers(0, 8, n),
              'y': (rng.random(n) < 0.3 + 0.4 * (score > 7)).astype(np.int64), 'flagged': np.zeros(n, dtype=bool),
              'game': np.zeros(n, dtype=np.int64)}
    return pm.Frame(arrays, {'AAA': 0, 'BBB': 1, 'CCC': 2, 'DDD': 3})


def with_outcomes_flipped(frame, seasons):
    arrays = dict(frame.a)
    arrays['y'] = np.where(np.isin(frame.a['season'], seasons), 1 - frame.a['y'], frame.a['y'])
    return pm.Frame(arrays, frame.teams)


def tune_outcome(frame):
    with mock.patch.object(rpe, 'log'):
        penalties, tau, validation = rpe.tune(pm.Design(frame), frame, rpe.Timer())
    return penalties, tau, validation


class Chronology(unittest.TestCase):
    def test_a_test_season_never_enters_its_own_training_rows(self):
        frame = synthetic_frame()
        primary = ~frame.a['flagged']
        for test_season in (2024, 2025):
            train = rpe.rows_for(frame.a['season'], primary, range(2010, test_season), primary=True)
            test = rpe.rows_for(frame.a['season'], primary, (test_season,), primary=True)
            self.assertGreater(len(train), 0)
            self.assertTrue(np.all(frame.a['season'][train] < test_season))
            self.assertTrue(np.all(frame.a['season'][test] == test_season))

    def test_a_split_that_includes_the_test_season_is_detected(self):
        frame = synthetic_frame()
        leaking = rpe.rows_for(frame.a['season'], ~frame.a['flagged'], range(2010, 2025), primary=True)
        self.assertTrue(np.any(frame.a['season'][leaking] == 2024))


class TuningIsolation(unittest.TestCase):
    def test_penalties_and_recency_do_not_change_when_2024_or_2025_outcomes_change(self):
        frame = synthetic_frame()
        penalties, tau, _ = tune_outcome(frame)
        flipped_penalties, flipped_tau, _ = tune_outcome(with_outcomes_flipped(frame, (2024, 2025)))
        self.assertEqual(flipped_penalties, penalties)
        self.assertEqual(flipped_tau, tau)

    def test_the_validation_loss_does_change_when_2023_outcomes_change(self):
        frame = synthetic_frame()
        _, _, validation = tune_outcome(frame)
        _, _, flipped = tune_outcome(with_outcomes_flipped(frame, (2023,)))
        self.assertNotAlmostEqual(flipped, validation, places=6)


def tiny_frame():
    return frame_from([(2012, 0, 1, 2, 2, 7, 3, 1, False, 0), (2012, 0, 0, 0, 0, 7, 3, 0, False, 1)])


def observed_play(**overrides):
    row = {'intent': 'run', 'down': 1, 'ydstogo': 10, 'yardline_100': 50, 'qtr': 1, 'seconds_in_quarter': 900,
           'score_status': 'pre_play_nflverse_raw', 'season': 2012, 'score_differential': 0, 'posteam': 'AAA',
           'game_id': '2012_01_AAA_BBB'}
    row.update(overrides)
    return row


class GameIdentity(unittest.TestCase):
    def test_each_play_keeps_its_own_game(self):
        rows = [observed_play(), observed_play(), observed_play(game_id='2012_02_AAA_CCC')]
        with mock.patch.object(pm.pco, 'observations', lambda *args, **kwargs: iter(rows)):
            frame = pm.load_frame((2012,))
        self.assertEqual(frame.games, ['2012_01_AAA_BBB', '2012_02_AAA_CCC'])
        self.assertEqual(frame.a['game'].tolist(), [0, 0, 1])


class CacheFingerprint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'frame.npz'
        self.db = Path(self.tmp.name) / 'db.sqlite3'
        self.db.write_bytes(b'x' * 10)

    def test_a_cache_is_reused_only_when_its_fingerprint_matches(self):
        with mock.patch.object(pm, 'source_fingerprint', return_value='A'), \
                mock.patch.object(pm, 'load_frame', return_value=tiny_frame()):
            first = pm.load_frame_cached(self.path, (2012,), db=self.db)
        self.assertEqual(first.cache_status, 'miss')
        with mock.patch.object(pm, 'source_fingerprint', return_value='A'), \
                mock.patch.object(pm, 'load_frame', side_effect=AssertionError('the cache should have been used')):
            hit = pm.load_frame_cached(self.path, (2012,), db=self.db)
        self.assertEqual(hit.cache_status, 'hit')
        with mock.patch.object(pm, 'source_fingerprint', return_value='B'), \
                mock.patch.object(pm, 'load_frame', return_value=tiny_frame()) as rebuild:
            stale = pm.load_frame_cached(self.path, (2012,), db=self.db)
        self.assertEqual(stale.cache_status, 'rebuilt')
        rebuild.assert_called_once()

    def test_a_cache_without_a_fingerprint_is_rebuilt(self):
        frame = tiny_frame()
        np.savez(self.path, team_codes=np.array(['AAA']), seasons_built=np.array([2012]), include_flagged=np.array(True),
                 **{k: frame.a[k] for k in pm.FRAME_KEYS})
        with mock.patch.object(pm, 'source_fingerprint', return_value='A'), \
                mock.patch.object(pm, 'load_frame', return_value=frame):
            self.assertEqual(pm.load_frame_cached(self.path, (2012,), db=self.db).cache_status, 'rebuilt')

    def test_the_fingerprint_changes_when_the_database_changes(self):
        with mock.patch.object(pm.pco, 'score_source', lambda season: ('unused', 'pin')):
            before = pm.source_fingerprint((2012,), self.db, True)
            self.db.write_bytes(b'x' * 11)
            after = pm.source_fingerprint((2012,), self.db, True)
        self.assertNotEqual(before, after)


class ScenarioSource(unittest.TestCase):
    def test_scenarios_are_scored_with_the_full_hierarchical_coefficients(self):
        frame = synthetic_frame()
        design = pm.Design(frame)
        full_width = len(design.columns(pm.GROUP_NAMES))
        no_team_width = len(design.columns(tuple(g for g in pm.GROUP_NAMES if g != 'team_down')))
        self.assertLess(no_team_width, full_width)  # the check below can tell the two fits apart
        widths = []
        original = rpe.scenario_table

        def record(frame_arg, design_arg, prep_cols, beta, train_rows):
            widths.append(len(prep_cols))
            return original(frame_arg, design_arg, prep_cols, beta, train_rows)

        with mock.patch.object(rpe, 'scenario_table', record), mock.patch.object(rpe, 'log'):
            rpe.evaluate_tests(frame, design, {g: 10.0 for g in pm.GROUP_NAMES}, None, rpe.Timer())
        self.assertEqual(len(widths), 4)
        self.assertTrue(all(width == full_width for width in widths))


if __name__ == '__main__':
    unittest.main()
