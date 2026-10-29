import random
import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import playcall_model as pm  # noqa: E402
import point_splits as sp  # noqa: E402
import slc_playcall as slc  # noqa: E402
from test_slc_playcall import STATE, blank_artifact, cell  # noqa: E402


def frame(seed=5, n=8000):
    rng = np.random.default_rng(seed)
    team = rng.integers(0, 2, n)
    score = rng.integers(0, 15, n)
    # team 0 passes when trailing (score buckets above the middle), team 1 does not depend on score
    p = np.where(team == 0, np.where(score > 7, 0.8, 0.3), 0.5)
    arrays = {'season': np.full(n, 2024), 'team': team, 'down': rng.integers(0, 4, n), 'dist': rng.integers(0, 6, n),
              'field': rng.integers(0, 5, n), 'score': score, 'clock': rng.integers(0, 8, n),
              'y': (rng.random(n) < p).astype(np.int64), 'flagged': np.zeros(n, dtype=bool), 'game': np.zeros(n, dtype=np.int64)}
    return pm.Frame(arrays, {'AAA': 0, 'BBB': 1})


class Shifts(unittest.TestCase):
    def test_a_team_that_passes_more_in_a_score_state_gets_a_positive_shift_there(self):
        table = sp.priors(frame(), 2026)
        trailing = sp.shift_for(table, 0, 12)
        leading = sp.shift_for(table, 0, 2)
        self.assertGreater(trailing, 0.5)
        self.assertLess(leading, 0.0)

    def test_a_team_with_no_score_dependence_has_a_small_shift(self):
        table = sp.priors(frame(), 2026)
        self.assertLess(abs(sp.shift_for(table, 1, 12)), 0.25)

    def test_an_unknown_team_or_bucket_adds_nothing(self):
        table = sp.priors(frame(), 2026)
        self.assertEqual(sp.shift_for(table, None, 3), 0.0)
        self.assertEqual(sp.shift_for({'shift': {}}, 0, 3), 0.0)

    def test_only_seasons_before_the_cutoff_are_used(self):
        f = frame()
        table = sp.priors(f, 2024)
        self.assertEqual(table['seasons'], [])
        self.assertEqual(sp.shift_for(table, 0, 12), 0.0)

    def test_the_sampler_records_the_shift_and_uses_it_for_the_dropback_rate(self):
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(0.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        sampler.point_shifts = {'shift': {(0, pm.score_bucket(-7)): 3.0}}
        pool = cell([('run', 'run'), ('pass_complete', 'pass')])
        sampler.sample(random.Random(1), pool, 'A', 'B', state=dict(STATE, score_diff=-7))
        self.assertGreater(sampler.decisions[-1]['p_dropback'], 0.9)
        self.assertAlmostEqual(sampler.decisions[-1]['point_shift'], 3.0, places=5)


if __name__ == '__main__':
    unittest.main()
