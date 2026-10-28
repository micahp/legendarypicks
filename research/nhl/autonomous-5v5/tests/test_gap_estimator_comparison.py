import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gap_estimator_comparison as gec
from kernel import Context, RenewalModel, Token, Transition


class GapEstimatorComparisonTests(unittest.TestCase):
    def setUp(self):
        self.context = Context("faceoff", True, 0, 0)
        self.mark = (Token("shot-on-goal", "home"),)
        self.transitions = [
            Transition("2019020001", 1, 2, self.context, self.mark),
            Transition("2019020001", 1, 2, self.context, self.mark),
            Transition("2019020002", 1, 4, self.context, self.mark),
        ]
        self.a1 = RenewalModel("A1")
        self.a1.fit(self.transitions)

    def test_event_before_boundary_and_same_second_censor(self):
        self.assertEqual(gec._spell_endpoint(10, 13, 20, ("5v5_exit",)),
                         (True, 3, None, False))
        self.assertEqual(gec._spell_endpoint(10, 20, 20, ("5v5_exit",)),
                         (False, 10, "same_second_eligible_event_5v5_exit", True))
        self.assertEqual(gec._spell_endpoint(10, 21, 20, ("period_end",)),
                         (False, 10, "period_end", False))
        with self.assertRaises(ValueError):
            gec._spell_endpoint(20, 20, 20, ("period_end",))

    def test_event_and_censor_risk_seconds(self):
        event = gec.RiskSpell("2019020001", 2019, 1, self.context, 5, True,
                              None, 10, 15, 0)
        censor = gec.RiskSpell("2019020001", 2019, 1, self.context, 5, False,
                               "period_end", 10, 15, 0)
        self.assertEqual(event.complete_risk_seconds, 5)
        self.assertEqual(censor.complete_risk_seconds, 4)

    def test_transition_reconciliation_counts_tied_transition_once(self):
        event = (2, self.context, self.mark)
        tied = (3, self.context, self.mark)
        gec._assert_transition_reconciliation([event], [tied], [event, tied], "fixture")
        with self.assertRaises(ValueError):
            gec._assert_transition_reconciliation([event], [], [event, tied], "fixture")

    def test_game_clustered_bootstrap_supports_both_frozen_references(self):
        a0 = RenewalModel("A0")
        a0.fit(self.transitions)
        result_a0 = gec._paired_event_gap_bootstrap(
            {"A0": a0, "A1": self.a1}, self.transitions,
            reference="A0", replicates=20, seed=7)
        result_a1 = gec._paired_event_gap_bootstrap(
            {"A0": a0, "A1": self.a1}, self.transitions,
            reference="A1", replicates=20, seed=7)
        self.assertEqual(result_a0["A1"]["status"], "ok")
        self.assertEqual(result_a1["A0"]["status"], "ok")
        self.assertEqual(result_a0["A1"]["ci95_low"], result_a1["A0"]["ci95_low"])

    def test_b1_pooled_shrinkage_normalizes_and_has_positive_support(self):
        pool = [1 / 1200] * 1200
        candidate = gec.TimingCandidate("B1", self.a1, "B1_pooled_shrinkage",
                                        pool_pmf=pool)
        probabilities = [candidate.gap_probability(self.context, second)
                         for second in range(1, 1201)]
        self.assertAlmostEqual(sum(probabilities), 1.0, places=12)
        self.assertTrue(all(probability > 0 for probability in probabilities))
        key = self.a1.selected_key(self.context)
        counts = self.a1.stats[key].gaps
        expected = (counts[2] + 600 * pool[1]) / (sum(counts.values()) + 600)
        self.assertAlmostEqual(candidate.gap_probability(self.context, 2), expected)

    def test_b2_exponential_support_survival_and_seeded_rollout(self):
        candidate = gec.TimingCandidate("B2-E", self.a1, "B2_exponential",
                                        hazards={("pooled",): 0.2})
        self.assertAlmostEqual(candidate.gap_probability(self.context, 1), 0.2)
        self.assertAlmostEqual(candidate.gap_probability(self.context, 2), 0.16)
        self.assertAlmostEqual(candidate.survival_left(self.context, 3), 0.64)
        trace_a, terminal_a = gec._candidate_trace(candidate, 12345)
        trace_b, terminal_b = gec._candidate_trace(candidate, 12345)
        self.assertEqual((trace_a, terminal_a), (trace_b, terminal_b))

    def test_discrete_weibull_distribution_and_censored_fit(self):
        scale, shape = 8.0, 1.4
        pmf = [gec.TimingCandidate.weibull_survival(d - 1, scale, shape)
               - gec.TimingCandidate.weibull_survival(d, scale, shape)
               for d in range(1, 2000)]
        self.assertAlmostEqual(sum(pmf), 1.0, places=10)
        spells = [
            gec.RiskSpell("2019020001", 2019, 1, self.context, 2, True,
                          None, 0, 2, 0),
            gec.RiskSpell("2019020001", 2019, 1, self.context, 4, True,
                          None, 2, 6, 1),
            gec.RiskSpell("2019020002", 2019, 1, self.context, 5, True,
                          None, 0, 5, 0),
            gec.RiskSpell("2019020002", 2019, 1, self.context, 4, False,
                          "period_end", 5, 9, 1),
        ]
        fitted, diagnostics = gec.fit_discrete_weibull(spells)
        self.assertTrue(diagnostics["converged"])
        self.assertTrue(math.isfinite(diagnostics["training_log_likelihood"]))
        self.assertGreater(fitted[0], 0)
        self.assertGreater(fitted[1], 0)

    def test_kaplan_meier_boundary_tie_conventions(self):
        spells = [
            gec.RiskSpell("2019020001", 2019, 1, self.context, 10, True,
                          None, 0, 10, 0),
            gec.RiskSpell("2019020002", 2019, 1, self.context, 10, False,
                          "same_second_eligible_event_5v5_exit", 0, 10, 0),
            gec.RiskSpell("2019020003", 2019, 1, self.context, 11, True,
                          None, 0, 11, 0),
        ]
        censor_first = gec._observed_kaplan_meier(spells, censor_first=True)
        event_first = gec._observed_kaplan_meier(spells, censor_first=False)
        self.assertEqual(censor_first["n_events_including_boundary_ties"], 2)
        self.assertEqual(event_first["n_events_including_boundary_ties"], 3)
        self.assertEqual(censor_first["n_boundary_ties"], 1)
        self.assertNotEqual(censor_first["survival_at_threshold"]["10"],
                            event_first["survival_at_threshold"]["10"])

    def test_frozen_hash_mismatch_fails_closed(self):
        with self.assertRaises(ValueError):
            gec._verify_hashes({"source": "bad"}, {"source": "expected"})

    def test_risk_cache_hash_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "risk.json.gz"
            path.write_bytes(b"not the pinned cache")
            with self.assertRaises(ValueError):
                gec._read_risk_cache(path, "0" * 64, {})


if __name__ == "__main__":
    unittest.main()
