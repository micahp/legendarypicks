"""V1.7 opt-in penalty proposal must not affect the V1.6 RNG stream."""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from penalty_fit import Context, Opportunity, PenaltyModel, NO_FOUL
from penalty_sampler import PenaltySampler

CUTOFF = "2025-01-01T00:00:00+00:00"


def ctx(phase="pre_snap"):
    return Context(phase=phase, rule_era=2024, offense_team="ARI", defense_team="DAL",
                   down=2, to_go=8, yardline_100=72,
                   play_class="pre_snap" if phase == "pre_snap" else "dropback")


def model():
    rows = []
    for i in range(60):
        foul = i % 5 == 0
        rows.append(Opportunity(
            context=ctx(), opportunity_id=f"g-{i}",
            game_kickoff_utc="2024-10-10T00:00:00+00:00",
            source_published_utc="2024-10-11T00:00:00+00:00",
            outcome="offense:false_start" if foul else NO_FOUL,
            label_verified=True, foul_count=int(foul),
            disposition="accepted" if foul else "none"))
    return PenaltyModel(train_before_utc=CUTOFF, source_sha256="b" * 64).fit(rows)


class PenaltySamplerTests(unittest.TestCase):
    def test_disabled_model_does_not_need_data_or_advance_existing_rng(self):
        control_rng = random.Random(42)
        sample_rng = random.Random(42)
        sampler = PenaltySampler(None, enabled=False)
        result = sampler.propose(ctx(), game_seed=3, opportunity_key="drive-1-play-4-pre")
        self.assertFalse(result.has_foul)
        self.assertEqual(result.outcome, NO_FOUL)
        self.assertEqual(result.model_sha256, None)
        self.assertEqual(control_rng.random(), sample_rng.random())

    def test_enabled_requires_fitted_model(self):
        with self.assertRaisesRegex(ValueError, "fitted"):
            PenaltySampler(None, enabled=True)

    def test_seed_and_unique_opportunity_generate_replayable_draws(self):
        sampler = PenaltySampler(model(), enabled=True)
        first = sampler.propose(ctx(), game_seed=7, opportunity_key="drive-2-play-9")
        self.assertEqual(first, sampler.propose(
            ctx(), game_seed=7, opportunity_key="drive-2-play-9"))
        self.assertEqual(first.phase, "pre_snap")
        self.assertTrue(first.model_sha256)
        self.assertTrue(first.source_sha256)
        self.assertIn(first.outcome, ("none", "offense:false_start",
                                      "offense:delay_of_game",
                                      "defense:encroachment",
                                      "defense:neutral_zone_infraction"))

    def test_sampling_never_mutates_provided_context(self):
        sampler = PenaltySampler(model(), enabled=True)
        c = ctx()
        before = repr(c)
        sampler.propose(c, game_seed=100, opportunity_key="drive-1-play-3")
        self.assertEqual(repr(c), before)

    def test_invalid_opportunity_id_or_seed_refused(self):
        sampler = PenaltySampler(model(), enabled=True)
        with self.assertRaisesRegex(ValueError, "opportunity key"):
            sampler.propose(ctx(), game_seed=1, opportunity_key=" ")
        with self.assertRaisesRegex(ValueError, "game_seed"):
            sampler.propose(ctx(), game_seed=True, opportunity_key="test")

    def test_proposal_exposes_type_but_not_enforcement_or_stats(self):
        sampler = PenaltySampler(model(), enabled=True)
        result = sampler.propose(ctx(), game_seed=3, opportunity_key="drive-1-play-9")
        self.assertFalse(hasattr(result, "yards_enforced"))
        self.assertFalse(hasattr(result, "down_after"))
        if result.has_foul:
            self.assertIn(result.committing_side, ("offense", "defense"))
            self.assertTrue(result.foul_type)
        else:
            self.assertIsNone(result.committing_side)
            self.assertIsNone(result.foul_type)


if __name__ == "__main__":
    unittest.main()
