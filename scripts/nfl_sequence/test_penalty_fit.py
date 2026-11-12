"""Regression contract for V1.7 penalty modeling, independent of PBP downloads."""
import json
import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from penalty_fit import (
    CATALOG, Context, NO_FOUL, Opportunity, PenaltyModel,
)

TRAIN_END = "2025-01-01T00:00:00+00:00"
SHA = "a" * 64


def context(phase="pre_snap", offense="ARI", defense="DAL", down=1,
            distance=10, yardline=65, play_class=None, era=2024):
    return Context(
        phase=phase, rule_era=era, offense_team=offense,
        defense_team=defense, down=down, to_go=distance,
        yardline_100=yardline,
        play_class=play_class or ("pre_snap" if phase == "pre_snap" else "dropback"))


def observation(number, *, phase="pre_snap", outcome=NO_FOUL, offense="ARI",
                defense="DAL", year=2024, published=None, verified=True,
                count=None, disposition=None, play_class=None):
    if count is None:
        count = int(outcome != NO_FOUL)
    if disposition is None:
        disposition = "accepted" if count else "none"
    return Opportunity(
        context=context(phase, offense, defense, play_class=play_class, era=year),
        opportunity_id=f"{year}_01_{offense}_{defense}-{number}",
        game_kickoff_utc=f"{year}-09-08T17:00:00+00:00",
        source_published_utc=published or f"{year}-09-09T12:00:00+00:00",
        outcome=outcome, label_verified=verified, foul_count=count,
        disposition=disposition)


def fitted(*rows, team_effects=True):
    return PenaltyModel(train_before_utc=TRAIN_END, source_sha256=SHA,
                        team_effects=team_effects).fit(rows)


class PenaltyDataContractTests(unittest.TestCase):
    def test_phase_and_intent_context_are_not_interchangeable(self):
        with self.assertRaisesRegex(ValueError, "pre-snap"):
            context("pre_snap", play_class="run")
        with self.assertRaisesRegex(ValueError, "live-ball"):
            context("live_ball", play_class="pre_snap")
        with self.assertRaisesRegex(ValueError, "distinct"):
            context(defense="ARI")

    def test_training_requires_verified_label(self):
        with self.assertRaisesRegex(ValueError, "unverified"):
            fitted(observation(1, verified=False))

    def test_training_refuses_future_games_and_late_source_vintage(self):
        with self.assertRaisesRegex(ValueError, "future/holdout"):
            fitted(observation(1, year=2025))
        with self.assertRaisesRegex(ValueError, "published"):
            fitted(observation(1, published="2025-06-01T00:00:00+00:00"))

    def test_multi_foul_and_unknown_rulings_are_never_counted_as_no_foul(self):
        with self.assertRaisesRegex(ValueError, "multiple fouls"):
            fitted(observation(1, outcome="offense:false_start", count=2))
        with self.assertRaisesRegex(ValueError, "ambiguous/offsetting"):
            fitted(observation(1, outcome="offense:false_start", disposition="offsetting"))
        with self.assertRaisesRegex(ValueError, "unsupported"):
            fitted(observation(1, outcome="offense:unknown_penalty"))

    def test_no_foul_and_foul_count_must_agree(self):
        with self.assertRaisesRegex(ValueError, "disagree"):
            fitted(observation(1, outcome=NO_FOUL, count=1))

    def test_duplicate_opportunity_phase_fails_instead_of_double_counting_exposure(self):
        row = observation(1)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            fitted(row, row)

    def test_denominator_includes_verified_nonfouls_not_just_flagged_rows(self):
        rows = [observation(i, outcome="offense:false_start" if i == 1 else NO_FOUL)
                for i in range(1, 101)]
        model = fitted(*rows, team_effects=False)
        self.assertEqual(model.opportunities, 100)
        root = model.context_counts[context().keys()[0]]
        self.assertEqual(root[NO_FOUL], 99)
        self.assertEqual(root["offense:false_start"], 1)

    def test_foul_and_no_foul_opportunities_are_separated_by_phase(self):
        rows = [observation(i) for i in range(1, 51)]
        rows += [observation(i, phase="live_ball",
                             outcome="defense:roughing_passer", play_class="dropback")
                 for i in range(51, 101)]
        model = fitted(*rows)
        self.assertEqual(model.stage_exposures["pre_snap"], 50)
        self.assertEqual(model.stage_exposures["live_ball"], 50)
        self.assertNotIn("defense:roughing_passer", model.predict(context()))
        self.assertIn("defense:roughing_passer", model.predict(
            context("live_ball", play_class="run", era=2027)))
        pre_only = fitted(observation(800))
        with self.assertRaisesRegex(ValueError, "no training opportunities"):
            pre_only.predict(context("live_ball"))

    def test_prediction_has_valid_simplex_and_backoff_on_unknown_team(self):
        rows = [observation(i) for i in range(1, 20)]
        rows += [observation(20, outcome="offense:false_start")]
        model = fitted(*rows)
        result = model.predict(context(offense="BUF", defense="MIN", down=4, distance=17))
        self.assertEqual(set(result), set(CATALOG["pre_snap"]))
        self.assertAlmostEqual(sum(result.values()), 1., places=12)
        self.assertTrue(all(0 <= p <= 1 for p in result.values()))


class TeamFirstModelTests(unittest.TestCase):
    def test_committing_team_has_shrunk_increased_offense_foul_propensity(self):
        rows = []
        for i in range(250):
            rows.append(observation(
                i, offense="ARI", defense="DAL",
                outcome="offense:false_start" if i % 4 == 0 else NO_FOUL))
        for i in range(250, 500):
            rows.append(observation(
                i, offense="BUF", defense="MIN",
                outcome="offense:false_start" if i % 25 == 0 else NO_FOUL))
        model = fitted(*rows)
        ari = model.predict(context(offense="ARI", defense="DAL"))
        buf = model.predict(context(offense="BUF", defense="MIN"))
        self.assertGreater(ari["offense:false_start"], buf["offense:false_start"])
        no_team = fitted(*rows, team_effects=False)
        self.assertAlmostEqual(no_team.predict(context(offense="ARI", defense="DAL"))[
            "offense:false_start"], no_team.predict(context(offense="BUF", defense="MIN"))[
                "offense:false_start"], places=12)

    def test_pre_snap_and_live_ball_rates_are_independently_normalized(self):
        rows = [observation(i, outcome="offense:false_start" if i % 10 == 0 else NO_FOUL)
                for i in range(100)]
        rows += [observation(i, phase="live_ball",
                             outcome="defense:roughing_passer" if i % 3 == 0 else NO_FOUL)
                 for i in range(100, 200)]
        model = fitted(*rows)
        pre = model.predict(context())
        live = model.predict(context("live_ball", play_class="dropback"))
        self.assertEqual(set(pre), set(CATALOG["pre_snap"]))
        self.assertEqual(set(live), set(CATALOG["live_ball"]))
        self.assertAlmostEqual(sum(pre.values()), 1., places=12)
        self.assertAlmostEqual(sum(live.values()), 1., places=12)

    def test_same_seed_same_sample_without_hidden_rng_state(self):
        model = fitted(*[observation(i, outcome="offense:false_start" if i % 8 == 0
                                     else NO_FOUL) for i in range(100)])
        ctx = context()
        a = [model.sample(ctx, random.Random(i)) for i in range(100)]
        b = [model.sample(ctx, random.Random(i)) for i in range(100)]
        self.assertEqual(a, b)
        self.assertTrue(all(item in CATALOG["pre_snap"] for item in a))

    def test_json_round_trip_is_prediction_and_hash_identical(self):
        rows = [observation(i, outcome="defense:offside" if i % 13 == 0 else NO_FOUL)
                for i in range(80)]
        model = fitted(*rows)
        restored = PenaltyModel.from_json(model.to_json())
        self.assertEqual(restored.predict(context()), model.predict(context()))
        self.assertEqual(restored.sha256(), model.sha256())
        self.assertEqual(json.loads(restored.to_json())["schema"],
                         "lp.slc.penalty-occurrence.v1")

    def test_bad_model_hash_or_schema_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "SHA256"):
            PenaltyModel(train_before_utc=TRAIN_END, source_sha256="invalid")
        model = fitted(observation(1))
        doc = json.loads(model.to_json())
        doc["schema"] = "other.schema"
        with self.assertRaisesRegex(ValueError, "schema"):
            PenaltyModel.from_json(json.dumps(doc))

    def test_true_heldout_scoring_requires_post_cutoff_observations(self):
        model = fitted(*[observation(i, outcome="offense:false_start" if i % 8 == 0
                                     else NO_FOUL) for i in range(30)])
        holdout = [observation(i, year=2025, outcome="offense:false_start"
                               if i % 9 == 0 else NO_FOUL)
                   for i in range(100, 120)]
        metrics = model.score(holdout)
        self.assertEqual(metrics["n"], 20)
        self.assertTrue(math.isfinite(metrics["log_loss"]))
        self.assertTrue(0 <= metrics["any_foul_brier"] <= 1)
        with self.assertRaisesRegex(ValueError, "training-period"):
            model.score([observation(500)])


if __name__ == "__main__":
    unittest.main()
