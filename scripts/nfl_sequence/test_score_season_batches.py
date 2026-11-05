import contextlib
import io
import json
import math
import random
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import score_season_batches as ssb  # noqa: E402


def outcome(seed, home, away, valid=True):
    return {'seed': seed, 'valid_full_game': valid, 'home_points': home, 'away_points': away}


def payload(game_id, rows):
    return {'game_id': game_id, 'summary': {'outcomes': rows}}


def write_schedule(db, games):
    con = sqlite3.connect(db)
    con.execute('DROP TABLE IF EXISTS nfl_schedule')
    con.execute('CREATE TABLE nfl_schedule (game_id TEXT, season INT, game_type TEXT, week INT, home_team TEXT, '
                'away_team TEXT, home_score INT, away_score INT)')
    con.executemany('INSERT INTO nfl_schedule VALUES (?, 2026, "REG", ?, ?, ?, ?, ?)', games)
    con.commit()
    con.close()


class Maths(unittest.TestCase):
    def test_crps_of_a_point_mass_on_the_observation_is_zero(self):
        self.assertAlmostEqual(ssb.crps([7, 7, 7], 7), 0.0)

    def test_crps_matches_the_pairwise_definition(self):
        samples, observed = [0, 2, 5, 9], 3
        pairs = [abs(a - b) for a in samples for b in samples]
        expected = sum(abs(x - observed) for x in samples) / 4 - 0.5 * sum(pairs) / 16
        self.assertAlmostEqual(ssb.crps(samples, observed), expected)

    def test_crps_hand_case(self):
        # samples {0, 2}, observed 1: E|X-1| = 1, E|X-X'| = 1 over all ordered pairs, so CRPS = 1 - 0.5 = 0.5
        self.assertAlmostEqual(ssb.crps([0, 2], 1), 0.5)

    def test_log_loss_and_brier_hand_values(self):
        self.assertAlmostEqual(ssb.log_loss(0.75, 1), -math.log(0.75))
        self.assertAlmostEqual(ssb.brier(0.75, 0), 0.5625)

    def test_log_loss_is_clipped_so_certain_forecasts_stay_finite(self):
        self.assertTrue(math.isfinite(ssb.log_loss(1.0, 0)))

    def test_probability_is_the_share_of_valid_untied_home_wins(self):
        valid = [outcome(1, 20, 17), outcome(2, 10, 24), outcome(3, 30, 3)]
        self.assertAlmostEqual(ssb.home_win_probability(valid), 2 / 3)

    def test_untied_filter_and_seed_list_come_from_all_rows(self):
        rows = [outcome(1, 20, 17), outcome(2, 14, 14), outcome(3, 9, 9, valid=False)]
        valid, seeds = ssb.seed_outcomes(payload('g', rows))
        self.assertEqual([row['seed'] for row in valid], [1])
        self.assertEqual(seeds, [1, 2, 3])

    def test_the_complete_game_rule_counts_unverified_archive_seeds_and_still_drops_blocked_ones(self):
        rows = [{'seed': 1, 'valid_full_game': False, 'complete_game': True, 'home_points': 20, 'away_points': 17},
                {'seed': 2, 'valid_full_game': False, 'complete_game': False, 'home_points': 0, 'away_points': 0},
                {'seed': 3, 'valid_full_game': False, 'complete_game': True, 'home_points': 10, 'away_points': 13}]
        self.assertEqual(ssb.seed_outcomes(payload('g', rows))[0], [])
        valid, seeds = ssb.seed_outcomes(payload('g', rows), 'complete_game')
        self.assertEqual([row['seed'] for row in valid], [1, 3])
        self.assertEqual(seeds, [1, 2, 3])

    def test_bootstrap_of_constant_values_is_that_value(self):
        low, high = ssb.bootstrap_interval([0.25] * 5, random.Random(1))
        self.assertAlmostEqual(low, 0.25)
        self.assertAlmostEqual(high, 0.25)

    def test_weeks_argument(self):
        self.assertEqual(ssb.parse_weeks('1-8'), list(range(1, 9)))
        with self.assertRaises(ValueError):
            ssb.parse_weeks('0-8')


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = str(root / 'schedule.db')
        self.base_dir, self.cand_dir = root / 'base', root / 'cand'
        self.base_dir.mkdir()
        self.cand_dir.mkdir()
        # Two games; home wins the first, away wins the second.
        write_schedule(self.db, [('g1', 1, 'HOM', 'AWY', 24, 17), ('g2', 2, 'HOM2', 'AWY2', 10, 21)])
        # Same seeds 1-4 in both arms. Baseline is 50/50 on both games; the candidate leans the right way on both.
        home, away = (20, 17), (17, 20)
        base = {'g1': [outcome(s, *(home if s <= 2 else away)) for s in (1, 2, 3, 4)],
                'g2': [outcome(s, *(home if s <= 2 else away)) for s in (1, 2, 3, 4)]}
        cand = {'g1': [outcome(s, *(home if s <= 3 else away)) for s in (1, 2, 3, 4)],
                'g2': [outcome(s, *(home if s == 1 else away)) for s in (1, 2, 3, 4)]}
        for game_id in base:
            (self.base_dir / f'{game_id}.json').write_text(json.dumps(payload(game_id, base[game_id])))
            (self.cand_dir / f'{game_id}.json').write_text(json.dumps(payload(game_id, cand[game_id])))

    def tearDown(self):
        self.tmp.cleanup()

    def test_scores_both_arms_and_applies_the_advance_rule(self):
        report = ssb.score(self.base_dir, self.cand_dir, self.db, [1, 2])
        self.assertEqual(report['games_scored'], 2)
        self.assertAlmostEqual(report['baseline']['season']['brier'], 0.25)
        self.assertLess(report['candidate']['season']['log_loss'], report['baseline']['season']['log_loss'])
        self.assertEqual(report['label'], 'retrospective-exposure')
        self.assertEqual(sorted(report['candidate']['by_week']), ['1', '2'])

    def test_mismatched_games_fail_loudly(self):
        (self.cand_dir / 'g2.json').unlink()
        with self.assertRaisesRegex(ValueError, 'different games'):
            ssb.score(self.base_dir, self.cand_dir, self.db, [1, 2])

    def test_mismatched_seed_lists_fail_loudly(self):
        bad = payload('g1', [outcome(9, 20, 17), outcome(2, 17, 20)])
        (self.cand_dir / 'g1.json').write_text(json.dumps(bad))
        with self.assertRaisesRegex(ValueError, 'seed list'):
            ssb.score(self.base_dir, self.cand_dir, self.db, [1, 2])

    def test_a_game_without_a_final_score_is_counted_not_scored(self):
        write_schedule(self.db, [('g1', 1, 'HOM', 'AWY', None, None), ('g2', 2, 'HOM2', 'AWY2', 10, 21)])
        report = ssb.score(self.base_dir, self.cand_dir, self.db, [1, 2])
        self.assertEqual(report['games_scored'], 1)
        self.assertIn('g1', report['accounting']['excluded'])

    def test_one_missing_score_is_not_final(self):
        write_schedule(self.db, [('g1', 1, 'HOM', 'AWY', 24, None), ('g2', 2, 'HOM2', 'AWY2', 10, 21)])
        report = ssb.score(self.base_dir, self.cand_dir, self.db, [1, 2])
        self.assertEqual(report['games_scored'], 1)
        self.assertIn('g1', report['accounting']['excluded'])

    def test_zero_final_scores_is_a_not_scored_result_not_a_crash(self):
        write_schedule(self.db, [('g1', 1, 'HOM', 'AWY', None, None), ('g2', 2, 'HOM2', 'AWY2', None, None)])
        report = ssb.score(self.base_dir, self.cand_dir, self.db, [1, 2])
        self.assertEqual(report['games_scored'], 0)
        self.assertEqual(sorted(report['accounting']['excluded']), ['g1', 'g2'])
        self.assertIsNone(report['baseline'])
        self.assertIsNone(report['candidate'])
        self.assertIsNone(report['paired'])
        self.assertEqual(report['advance_rule']['verdict'], 'NOT SCORED')
        self.assertFalse(report['advance_rule']['advance'])
        self.assertEqual(report['advance_rule']['reason'], 'no final score in nfl_schedule for the requested weeks')

    def test_finals_without_valid_untied_seeds_is_not_scored(self):
        write_schedule(self.db, [('g1', 1, 'HOM', 'AWY', 24, 17), ('g2', 2, 'HOM2', 'AWY2', 10, 21)])
        for directory in (self.base_dir, self.cand_dir):
            for game_id in ('g1', 'g2'):
                rows = [outcome(s, 20, 17, valid=False) for s in (1, 2)]
                (directory / f'{game_id}.json').write_text(json.dumps(payload(game_id, rows)))
        report = ssb.score(self.base_dir, self.cand_dir, self.db, [1, 2])
        self.assertEqual(report['games_scored'], 0)
        self.assertEqual(report['advance_rule']['verdict'], 'NOT SCORED')
        self.assertEqual(report['advance_rule']['reason'], 'no valid untied seeds in an arm')

    def test_cli_prints_zero_games_scored_and_writes_the_report(self):
        write_schedule(self.db, [('g1', 1, 'HOM', 'AWY', None, None), ('g2', 2, 'HOM2', 'AWY2', None, None)])
        out = Path(self.tmp.name) / 'report.json'
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            ssb.main(['--baseline-dir', str(self.base_dir), '--candidate-dir', str(self.cand_dir), '--weeks', '1-2',
                      '--db', self.db, '--out', str(out), '--seed-rule', 'complete_game'])
        self.assertIn('games scored 0, excluded 2', stdout.getvalue())
        self.assertIn('advance rule: NOT SCORED', stdout.getvalue())
        self.assertEqual(json.loads(out.read_text())['advance_rule']['verdict'], 'NOT SCORED')


if __name__ == '__main__':
    unittest.main()
