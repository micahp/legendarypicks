"""No-database tests for fail-closed two-sided pre-kickoff quote audit."""
import importlib.util
import pathlib
import unittest

P = pathlib.Path(__file__).with_name("audit_prop_quote_provenance.py")
S = importlib.util.spec_from_file_location("quote_provenance", P)
M = importlib.util.module_from_spec(S)
S.loader.exec_module(M)


class QuoteStatusTests(unittest.TestCase):
    def setUp(self):
        self.kickoff = "2026-09-20T17:00:00+00:00"
        self.over = {"odds_captured_at": "2026-09-20T16:58:00Z"}
        self.under = {"odds_captured_at": "2026-09-20T16:55:00+00:00"}

    def test_eligible_two_sided_before_kickoff(self):
        self.assertEqual(M.audit_status(self.kickoff, self.over, self.under),
                         "selected_quote_pre_kickoff_recorded")

    def test_post_kickoff_either_side_blocks(self):
        self.under["odds_captured_at"] = "2026-09-20T17:01:00+00:00"
        self.assertEqual(M.audit_status(self.kickoff, self.over, self.under),
                         "selected_quote_at_or_after_kickoff")

    def test_exact_kickoff_blocks(self):
        self.over["odds_captured_at"] = self.kickoff
        self.assertEqual(M.audit_status(self.kickoff, self.over, self.under),
                         "selected_quote_at_or_after_kickoff")

    def test_naive_or_missing_is_not_verified(self):
        self.over["odds_captured_at"] = "2026-09-20T16:58:00"
        self.assertEqual(M.audit_status(self.kickoff, self.over, self.under),
                         "odds_timestamp_unverifiable")
        self.assertEqual(M.audit_status(None, self.over, self.under), "kickoff_unverifiable")
        self.assertEqual(M.audit_status(self.kickoff, self.over, None), "selected_quote_side_missing")


if __name__ == "__main__":
    unittest.main()
