"""Scope of the E2 survey outputs: no blocked seed is described as a complete game, every seed passes validate_game, and the
scope reasons are counted. Reads the committed survey outputs in docs/evidence/e2-successor.

Run: python3 -m unittest scripts/nfl_sequence/evidence_e2/test_scope.py
"""
import csv
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / 'docs' / 'evidence' / 'e2-successor'
SURVEY = EVIDENCE / 'legality-survey-300.csv'
SUMMARY = EVIDENCE / 'legality-survey-300-summary.json'


def rows():
    with open(SURVEY, newline='') as f:
        return list(csv.DictReader(f))


class BlockedNeverComplete(unittest.TestCase):
    def test_every_blocked_seed_is_not_a_complete_regulation_game(self):
        blocked = [r for r in rows() if r['status'] == 'blocked']
        self.assertTrue(blocked, 'the survey has blocked seeds to check')
        self.assertTrue(all(r['complete_regulation'] == 'False' for r in blocked))

    def test_no_blocked_seed_is_legal_as_a_complete_game(self):
        self.assertTrue(all(r['legal_complete_game'] == 'False' for r in rows() if r['status'] == 'blocked'))

    def test_the_summary_counts_no_blocked_seed_described_as_complete(self):
        self.assertEqual(json.loads(SUMMARY.read_text())['blocked_described_complete'], 0)


class GuardedNeverComplete(unittest.TestCase):
    def test_no_seed_with_an_unmodelled_transition_is_a_complete_game(self):
        guarded = [r for r in rows() if int(r['unmodelled_transitions']) > 0]
        self.assertTrue(guarded, 'the survey has guarded seeds to check')
        self.assertTrue(all(r['complete_game'] == 'False' for r in guarded))
        self.assertTrue(all(r['status'] != 'complete_regulation' for r in guarded))

    def test_the_summary_counts_no_guarded_seed_described_as_complete(self):
        self.assertEqual(json.loads(SUMMARY.read_text())['guarded_described_complete'], 0)

    def test_the_summary_counts_zero_complete_games(self):
        self.assertEqual(json.loads(SUMMARY.read_text())['complete_game'], 0)


class EverySeedPassesTheValidator(unittest.TestCase):
    def test_all_seeds_passed_validate_game(self):
        summary = json.loads(SUMMARY.read_text())
        self.assertEqual(summary['validate_game_passed'], summary['seeds'])
        self.assertEqual(summary['seeds'], 300)


class ScopeReasonsAreCounted(unittest.TestCase):
    def test_every_non_complete_seed_has_a_named_scope_reason(self):
        for r in rows():
            if r['status'] == 'blocked':
                self.assertTrue(r['scope_out'], f"blocked seed {r['seed']} has no scope reason")

    def test_the_scope_counts_match_the_blocked_rows(self):
        summary = json.loads(SUMMARY.read_text())
        blocked = sum(1 for r in rows() if r['status'] == 'blocked')
        named = sum(summary['scope_out_seeds'][reason] for reason in ('overtime', 'rare kick outcome', 'thin E1 pool cell',
                                                                     'penalty', 'drive limit', 'other'))
        self.assertEqual(named, blocked, 'each blocked seed carries exactly one scope reason')


if __name__ == '__main__':
    unittest.main()
