from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import arrival_gap_diagnostics as diagnosis
from kernel import Context, RenewalModel, Token, Transition, sample_trace


class ArrivalGapDiagnosticTests(unittest.TestCase):
    def test_repository_root_resolves_to_worktree_not_parent_directory(self):
        self.assertEqual(diagnosis.ROOT, Path(__file__).resolve().parents[4])
        self.assertEqual(diagnosis.PREREG_PATH.parent, diagnosis.ROOT / "docs/research")

    def test_large_machine_result_defaults_outside_repository(self):
        self.assertFalse(diagnosis.EXPECTED_OUTPUT.is_relative_to(diagnosis.ROOT))
        self.assertEqual(diagnosis.EXPECTED_OUTPUT.parent, Path("/root/lp-data"))

    def training_rows(self, n: int = 120, gap: int | None = None) -> list[Transition]:
        rows = []
        for index in range(n):
            context = Context("faceoff" if index % 2 == 0 else "shot-on-goal",
                              index % 3 != 0, (index % 3) - 1, (index // 11) % 4)
            rows.append(Transition(
                f"201902{index:04d}", index % 3 + 1, gap or (5 + index % 7),
                context, (Token("shot-on-goal", "home"),)))
        return rows

    def test_first_scored_gap_is_separate_from_later_retained_gaps(self):
        rows = [
            Transition("2021020001", 1, 7, Context("faceoff", True, 0, 0),
                       (Token("hit", "home"),)),
            Transition("2021020001", 1, 11, Context("hit", True, 0, 0),
                       (Token("shot-on-goal", "away"),)),
            Transition("2021020002", 1, 9, Context("faceoff", True, 0, 0),
                       (Token("faceoff", "away"),)),
        ]
        periods = [SimpleNamespace(transitions=rows[:2]),
                   SimpleNamespace(transitions=rows[2:])]
        split = diagnosis.observed_gap_partitions(periods, max_bundle_size=1)
        self.assertEqual([row.gap_seconds for row in split["first_scored_transition"]], [7, 9])
        self.assertEqual([row.gap_seconds for row in split["later_scored_transitions"]], [11])

    def test_period_clock_and_censored_exposure_must_reconcile(self):
        row = {
            "regulation_seconds": 1200,
            "shift_5v5_seconds": 900,
            "shift_non5v5_seconds": 290,
            "shift_ambiguous_seconds": 10,
            "entry_elapsed_seconds": 15,
            "entry_5v5_seconds": 10,
            "retained_gap_exposure_seconds": 800,
            "terminal_elapsed_seconds": 30,
            "terminal_5v5_seconds": 20,
            "unpaired_5v5_seconds": 70,
            "eligible_bundle_count": 83,
            "transition_count": 82,
        }
        result = diagnosis.observed_exposure_summary([row])
        self.assertEqual(result["shift_5v5_seconds"], 900)
        self.assertEqual(result["retained_gap_exposure_seconds"], 800)
        row["unpaired_5v5_seconds"] = 69
        with self.assertRaises(ValueError):
            diagnosis.observed_exposure_summary([row])

    def test_uniform_prior_mass_and_gap_pmf_normalize(self):
        self.assertAlmostEqual(diagnosis.prior_mass(100), 600 / 700)
        model = RenewalModel("A1")
        model.fit(self.training_rows())
        context = Context("faceoff", True, 0, 0)
        self.assertAlmostEqual(sum(model.gap_probability(context, second)
                                   for second in range(1, 1201)), 1.0)
        self.assertAlmostEqual(diagnosis.gap_survival(model, context, 0), 1.0)
        counts = model.stats[model.selected_key(context)].gaps
        expected_tail = sum(counts[second] for second in range(11, 1201))
        expected_tail += model.alpha * (1200 - 10)
        expected_denominator = sum(counts.values()) + model.alpha * 1200
        self.assertAlmostEqual(diagnosis.gap_survival(model, context, 10),
                               expected_tail / expected_denominator)
        self.assertEqual(diagnosis.gap_survival(model, context, 1200), 0.0)

    def test_gap_only_smoothing_probe_does_not_change_mark_likelihood(self):
        model = RenewalModel("A1")
        model.fit(self.training_rows())
        context = Context("faceoff", True, 0, 0)
        mark = (Token("shot-on-goal", "home"),)
        before = model.mark_log_probability(context, mark)
        unseen_gap = next(second for second in range(1, 1201)
                          if model.stats[model.selected_key(context)].gaps[second] == 0)
        self.assertEqual(diagnosis.gap_probability(model, context, unseen_gap, 0.0), 0.0)
        self.assertGreater(diagnosis.gap_probability(model, context, unseen_gap), 0.0)
        self.assertEqual(model.mark_log_probability(context, mark), before)

    def test_cached_unsmoothed_cdf_preserves_fixed_seed_trace(self):
        model = RenewalModel("A1")
        model.fit(self.training_rows())
        first = diagnosis.sample_trace_diagnostic(model, 20261027, alpha_gap=0.0)
        cdf_cache = getattr(model, "_diagnostic_gap_cdfs")
        cache_size = len(cdf_cache)
        second = diagnosis.sample_trace_diagnostic(model, 20261027, alpha_gap=0.0)
        self.assertEqual(first["trace"], second["trace"])
        self.assertEqual(len(model._diagnostic_gap_cdfs), cache_size)

    def test_cutoff_period_score_uses_only_goals_from_completed_prior_periods(self):
        def event(period: int, sort_order: int, event_type: str,
                  owner: str | None = None) -> dict:
            details = {"eventOwnerTeamId": owner} if owner else {}
            return {"sortOrder": sort_order, "typeDescKey": event_type,
                    "periodDescriptor": {"periodType": "REG", "number": period},
                    "details": details}

        pbp = {
            "id": "2021020001",
            "homeTeam": {"id": 1},
            "awayTeam": {"id": 2},
            "plays": [event(1, 1, "period-start"), event(1, 2, "goal", "1"),
                      event(2, 3, "period-start"), event(2, 4, "goal", "2"),
                      event(2, 5, "goal", "1"), event(3, 6, "period-start")],
        }
        sides = {"1": "home", "2": "away"}
        def owner_resolver(record, team_sides):
            owner = (record.get("details") or {}).get("eventOwnerTeamId")
            return team_sides.get(str(owner)) if owner is not None else None
        result = diagnosis.period_start_score_diffs(pbp, owner_resolver)
        self.assertEqual(result, {1: 0, 2: 1, 3: 1})

    def test_period_score_parser_fails_closed_when_period_boundary_missing(self):
        pbp = {"id": "2021020001", "homeTeam": {"id": 1},
               "awayTeam": {"id": 2}, "plays": []}
        with self.assertRaises(ValueError):
            diagnosis.period_start_score_diffs(pbp, lambda *_: None)

    def test_horizon_arrival_is_right_censored_not_emitted(self):
        model = RenewalModel("A0")
        model.fit(self.training_rows(120, gap=1200))
        result = diagnosis.sample_trace_diagnostic(model, 41, alpha_gap=0.0)
        self.assertEqual(result["trace"], [])
        self.assertEqual(result["terminal_gap"]["gap_seconds"], 1200)
        self.assertTrue(result["terminal_gap"]["censored_at_or_beyond_horizon"])

    def test_frozen_gap_sampler_is_reproduced_for_fixed_seed(self):
        model = RenewalModel("A1")
        model.fit(self.training_rows())
        context = Context("faceoff", True, 0, 0)
        expected = sample_trace(model, 20261027, initial=context)
        actual = diagnosis.sample_trace_diagnostic(model, 20261027, initial=context)
        self.assertEqual(actual["trace"], expected)
        self.assertEqual(sample_trace(model, 20261027, initial=context), expected)
        self.assertEqual(actual["emitted_gaps"], [
            second - (actual["trace"][index - 1][0] if index else 0)
            for index, (second, _) in enumerate(actual["trace"])])

    def test_source_transition_signature_includes_gap_context_and_mark(self):
        row = Transition("2021020001", 1, 9, Context("hit", False, 1, 2),
                         (Token("faceoff", "away"),))
        self.assertEqual(diagnosis.transition_signature([row]), [(9, row.context, row.mark)])
        changed = Transition("2021020001", 1, 10, row.context, row.mark)
        self.assertNotEqual(diagnosis.transition_signature([row]),
                            diagnosis.transition_signature([changed]))

    def test_source_clock_order_accepts_ties_and_rejects_backward_clock(self):
        def play(order: int, second: int) -> dict:
            return {"sortOrder": order, "timeInPeriod": str(second),
                    "periodDescriptor": {"periodType": "REG", "number": 1}}

        parse = lambda value: int(value)
        tied = {"id": "game", "plays": [play(1, 5), play(2, 5), play(3, 6)]}
        diagnosis.validate_source_clock_order(tied, 1, parse)
        backward = {"id": "game", "plays": [play(1, 6), play(2, 5)]}
        with self.assertRaisesRegex(ValueError, "non-monotone"):
            diagnosis.validate_source_clock_order(backward, 1, parse)

    def test_transition_reconciliation_rejects_missing_or_extra_rows(self):
        row = Transition("2021020001", 1, 9, Context("hit", False, 1, 2),
                         (Token("faceoff", "away"),))
        expected = diagnosis.transition_signature([row])
        diagnosis.assert_transition_reconciliation([row], expected, "fixture")
        with self.assertRaisesRegex(ValueError, "count/content mismatch"):
            diagnosis.assert_transition_reconciliation([row], [], "fixture")

    def test_game_clustered_gap_nll_interval_is_paired_and_rate_weighted(self):
        per_game = {
            "A0": {
                "g1": {"all": [10.0, 10.0], "first": [2.0, 10.0], "later": [8.0, 10.0]},
                "g2": {"all": [20.0, 20.0], "first": [4.0, 20.0], "later": [16.0, 20.0]},
            },
            "A1": {
                "g1": {"all": [20.0, 10.0], "first": [4.0, 10.0], "later": [16.0, 10.0]},
                "g2": {"all": [40.0, 20.0], "first": [8.0, 20.0], "later": [32.0, 20.0]},
            },
        }
        result = diagnosis.paired_game_clustered_gap_nll_bootstrap(
            per_game, "A0", "A1", replicates=40, seed=1)
        self.assertAlmostEqual(
            result["all"]["candidate_minus_reference_nats_per_5v5_minute"], 60.0)
        self.assertAlmostEqual(result["all"]["ci95_low"], 60.0)
        self.assertAlmostEqual(result["all"]["ci95_high"], 60.0)
        self.assertEqual(result["all"]["game_clusters"], 2)

    def test_score_start_changes_only_score_in_initial_context(self):
        start = {"score_diff": 2}
        default = diagnosis.initial_context_for_period(start, score_aware=False)
        aware = diagnosis.initial_context_for_period(start, score_aware=True)
        self.assertEqual(default, Context("faceoff", True, 0, 0))
        self.assertEqual(aware, Context("faceoff", True, 2, 0))
        self.assertEqual((default.previous_family, default.possession_known,
                          default.clock_bucket),
                         (aware.previous_family, aware.possession_known,
                          aware.clock_bucket))

    def test_frozen_hash_check_fails_closed_on_changed_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "frozen.json"
            path.write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "pinned hash mismatch"):
                diagnosis.require_hash(path, "0" * 64)


if __name__ == "__main__":
    unittest.main()
