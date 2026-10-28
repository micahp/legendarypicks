import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e1_drive as e1  # noqa: E402
import e2_reference as er  # noqa: E402

CUTOFF = (2024, 8)
MANIFEST = er.BLOCKED_KICKS.with_suffix(er.BLOCKED_KICKS.suffix + '.manifest.json')


class FullWindowReproducesThePinnedRates(unittest.TestCase):
    """The recomputed rates use the pinned manifest's definitions. With no cutoff they must reproduce it exactly."""

    @classmethod
    def setUpClass(cls):
        cls.pinned = json.loads(MANIFEST.read_text())['observed_rates']
        cls.blocked = er.load_blocked_kicks()
        cls.rates = er.cutoff_blocked_rates(e1.DEFAULT_DB, cls.blocked, None)

    def test_field_goal_attempts_blocks_and_rates_match_the_manifest(self):
        for bucket, pinned in self.pinned['field_goal_blocked_by_snap_bucket'].items():
            got = self.rates['field_goal_blocked_by_snap_bucket'][bucket]
            self.assertEqual((got['attempts'], got['blocked']), (pinned['attempts'], pinned['blocked']), bucket)
            self.assertAlmostEqual(got['rate'], pinned['rate'], places=12, msg=bucket)
            self.assertLess(max(abs(a - b) for a, b in zip(got['wilson_95'], pinned['wilson_95'])), 1e-4, bucket)

    def test_punt_attempts_blocks_and_rate_match_the_manifest(self):
        pinned = self.pinned['punt_blocked']
        got = self.rates['punt_blocked']
        self.assertEqual((got['attempts'], got['blocked']), (pinned['attempts'], pinned['blocked']))
        self.assertAlmostEqual(got['rate'], pinned['rate'], places=12)


class CutoffRates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.full_blocked = er.load_blocked_kicks()
        cls.full = er.cutoff_blocked_rates(e1.DEFAULT_DB, cls.full_blocked, None)
        cls.cut_blocked = er.load_blocked_kicks(eligible_before=CUTOFF)
        cls.cut = er.cutoff_blocked_rates(e1.DEFAULT_DB, cls.cut_blocked, CUTOFF)

    def test_plays_at_or_after_the_cutoff_are_removed_from_both_denominators(self):
        self.assertLess(self.cut['punt_blocked']['attempts'], self.full['punt_blocked']['attempts'])
        full_fg = sum(v['attempts'] for v in self.full['field_goal_blocked_by_snap_bucket'].values())
        cut_fg = sum(v['attempts'] for v in self.cut['field_goal_blocked_by_snap_bucket'].values())
        self.assertLess(cut_fg, full_fg)

    def test_the_kept_records_are_all_before_the_cutoff(self):
        for kick_type, records in self.cut_blocked['records'].items():
            for record in records:
                self.assertTrue((record['season'], record['week']) < CUTOFF, (kick_type, record['game_id']))

    def test_the_kept_records_agree_with_the_cut_kick_results(self):
        field_goal_records = len(self.cut_blocked['records']['field_goal'])
        field_goal_blocked = sum(v['blocked'] for v in self.cut['field_goal_blocked_by_snap_bucket'].values())
        self.assertEqual(field_goal_records, field_goal_blocked)
        self.assertEqual(len(self.cut_blocked['records']['punt']), self.cut['punt_blocked']['blocked'])


class OvertimeChoiceBeforeTheCutoff(unittest.TestCase):
    def test_the_cutoff_uses_the_beta_prior_and_the_full_window_keeps_the_fit(self):
        prior, prior_sha = er.load_overtime_choice_model(eligible_before=CUTOFF)
        fitted, _ = er.load_overtime_choice_model()
        self.assertEqual(prior, 0.5)
        self.assertAlmostEqual(fitted, 0.6875, places=4)
        self.assertEqual(len(prior_sha), 64)


if __name__ == '__main__':
    unittest.main()
