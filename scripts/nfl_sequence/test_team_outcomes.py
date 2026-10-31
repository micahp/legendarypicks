import random
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import slc_playcall as slc  # noqa: E402
import team_tendency as tt  # noqa: E402
from test_slc_playcall import STATE, blank_artifact, cell  # noqa: E402


class Ratios:
    """A stand-in for TeamTendencies: a fixed event ratio per (side, team, event). Unknown teams raise, as the real one does."""
    def __init__(self, table, known):
        self.table, self.known = table, known

    def ratio(self, side, team, cell_key, event):
        if team not in self.known:
            raise ValueError(f'no {side} tendency for team {team!r}')
        return self.table.get((side, team, event), 1.0)


def sampler_with(table, known=('AAA', 'BBB')):
    sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(30.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
    sampler.team_outcomes = Ratios(table, set(known))
    return sampler


POOL = cell([('run', 'run'), ('pass_complete', 'pass'), ('pass_incomplete', 'pass')])


class TeamOutcomeSplits(unittest.TestCase):
    def test_an_offense_ratio_of_zero_removes_that_outcome_for_that_offense(self):
        sampler = sampler_with({('offense', 'AAA', 'pass_complete'): 0.0})
        rng = random.Random(1)
        drawn = {sampler.sample(rng, POOL, 'A', 'B', state=STATE)[0] for _ in range(400)}
        self.assertNotIn('pass_complete', drawn)
        self.assertIn('pass_incomplete', drawn)

    def test_a_defense_ratio_acts_on_the_defensive_team(self):
        sampler = sampler_with({('defense', 'BBB', 'pass_incomplete'): 0.0})
        rng = random.Random(2)
        drawn = {sampler.sample(rng, POOL, 'A', 'B', state=STATE)[0] for _ in range(400)}
        self.assertNotIn('pass_incomplete', drawn)
        self.assertIn('pass_complete', drawn)

    def test_a_team_without_a_prior_sample_adds_no_effect(self):
        sampler = sampler_with({}, known=('BBB',))  # AAA has no prior-season sample
        self.assertEqual(sampler._outcome_weight('pass_complete', 'A', 'B', ('cell',)), 1.0)

    def test_the_intent_is_not_changed_by_the_outcome_split(self):
        off = sampler_with({})
        on = sampler_with({('offense', 'AAA', 'pass_complete'): 0.0, ('offense', 'AAA', 'pass_incomplete'): 0.0})
        off.decisions.clear()
        on.decisions.clear()
        for seed in range(50):
            off.sample(random.Random(seed), POOL, 'A', 'B', state=STATE)
            on.sample(random.Random(seed), POOL, 'A', 'B', state=STATE)
        self.assertEqual([d['intent'] for d in off.decisions], [d['intent'] for d in on.decisions])
        dropbacks = [d for d in on.decisions if d['intent'] == 'dropback']
        self.assertTrue(dropbacks)
        self.assertTrue(all(
            d['outcome_weight_fallback'] == 'all_conditioned_weights_zero_within_selected_intent'
            for d in dropbacks
        ))
        self.assertTrue(all(d['outcome_weight_fallback'] is None
                            for d in on.decisions if d['intent'] != 'dropback'))

    def test_each_decision_records_whether_the_split_was_on(self):
        off, on = sampler_with({}), sampler_with({})
        off.team_outcomes = None
        off.sample(random.Random(3), POOL, 'A', 'B', state=STATE)
        on.sample(random.Random(3), POOL, 'A', 'B', state=STATE)
        self.assertFalse(off.decisions[-1]['team_outcome_split'])
        self.assertTrue(on.decisions[-1]['team_outcome_split'])


class PriorSeasonsOnly(unittest.TestCase):
    def test_a_2026_tendency_build_needs_an_explicit_cutoff(self):
        with self.assertRaises(ValueError):
            tt.build_from_pool({}, 2026)
        with self.assertRaises(ValueError):
            tt.build_from_rows([], 2026, cutoff=None)


if __name__ == '__main__':
    unittest.main()
