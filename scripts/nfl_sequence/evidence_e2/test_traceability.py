"""Tests for the rule traceability matrix (traceability.py). Every cited transition, test and code snippet must resolve, and
the rows that lack a test are pinned, so a gap cannot disappear without a change to this file.

Run: python3 -m unittest scripts/nfl_sequence/evidence_e2/test_traceability.py
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import traceability as tb  # noqa: E402


class Resolution(unittest.TestCase):
    def test_every_transition_test_and_citation_resolves(self):
        problems, resolved = tb.build_checks()
        self.assertEqual(problems, [])
        self.assertEqual(resolved['transitions'], len(tb.ROWS))

    def test_every_row_has_a_rulebook_status(self):
        for row in tb.ROWS:
            self.assertIn(row['rulebook']['status'], ('verified', 'not verified', 'not applicable'), row['id'])


class Gaps(unittest.TestCase):
    def test_exactly_the_pinned_rows_carry_a_gap(self):
        tb.build_checks()
        gapped = {row['id'] for row in tb.ROWS if row['gaps']}
        self.assertEqual(gapped, {'R07', 'R10', 'R20'})

    def test_a_gap_is_written_not_skipped(self):
        tb.build_checks()
        r07 = next(r for r in tb.ROWS if r['id'] == 'R07')
        self.assertEqual(r07['gaps'], ['GAP: no adversarial test'])


class KickDisagreement(unittest.TestCase):
    def test_the_disagreement_is_written_in_exactly_one_row(self):
        marked = [r['id'] for r in tb.ROWS if 'DISAGREEMENT' in r['note']]
        self.assertEqual(marked, ['R12'])


if __name__ == '__main__':
    unittest.main()
