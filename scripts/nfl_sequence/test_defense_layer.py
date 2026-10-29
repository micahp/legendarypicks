import collections
import random
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import defense_layer as dl  # noqa: E402
import slc_playcall as slc  # noqa: E402
from test_slc_playcall import STATE, blank_artifact  # noqa: E402

DB = '/root/legendarypicks/backend/data/picks.dev.db'


def table(team_counts, league_counts):
    return {'team': {'BBB': collections.Counter(team_counts)}, 'league': collections.Counter(league_counts), 'strength': 25.0}


class Choice(unittest.TestCase):
    def test_the_coverage_decision_is_never_unknown(self):
        t = table({dl.UNKNOWN: 99, 'COVER_1': 1}, {dl.UNKNOWN: 99, 'COVER_1': 1})
        self.assertEqual({dl.choose(t, 'BBB', f's{i}') for i in range(200)}, {'COVER_1'})

    def test_a_defense_with_no_history_takes_the_league_shares(self):
        t = {'team': {}, 'league': collections.Counter({'COVER_1': 3, 'COVER_3': 1}), 'strength': 25.0}
        self.assertAlmostEqual(dl.distribution(t, 'NEW')['COVER_1'], 0.75, places=6)

    def test_a_team_with_history_moves_toward_its_own_shares(self):
        t = table({'COVER_3': 40}, {'COVER_1': 30, 'COVER_3': 10})
        shares = dl.distribution(t, 'BBB')
        self.assertGreater(shares['COVER_3'], 0.5)

    def test_the_same_seed_gives_the_same_coverage(self):
        t = table({'COVER_1': 5, 'COVER_3': 5}, {'COVER_1': 5, 'COVER_3': 5})
        self.assertEqual(dl.choose(t, 'BBB', 'x'), dl.choose(t, 'BBB', 'x'))


class Outcome(unittest.TestCase):
    def _cell(self):
        out = []
        for i in range(40):
            out.append(('pass_complete', {'game_id': 'g', 'play_id': i, 'season': 2025, 'down': 2, 'ydstogo': 7,
                                          'yardline_100': 50, 'play_type': 'pass', 'posteam': 'AAA', 'coverage': 'COVER_1'}, 6.0, 52))
            out.append(('pass_incomplete', {'game_id': 'g', 'play_id': 100 + i, 'season': 2025, 'down': 2, 'ydstogo': 7,
                                            'yardline_100': 50, 'play_type': 'pass', 'posteam': 'AAA', 'coverage': 'COVER_3'}, 6.0, 52))
        return out

    def test_a_coverage_changes_the_outcome_mix_within_dropbacks(self):
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(30.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        sampler.coverage_outcomes = True
        counts = {}
        rng = random.Random(9)
        for cov in ('COVER_1', 'COVER_3'):
            c = collections.Counter()
            for _ in range(400):
                sampler.participant_chooser = lambda intent, offense, state=None, cov=cov: {'coverage': cov, 'side': 'away', 'team': 'BBB'}
                c[sampler.sample(rng, self._cell(), 'A', 'B', state=dict(STATE, down=2, togo=7))[0]] += 1
            counts[cov] = c
        self.assertGreater(counts['COVER_1']['pass_complete'], counts['COVER_1']['pass_incomplete'] * 3)
        self.assertGreater(counts['COVER_3']['pass_incomplete'], counts['COVER_3']['pass_complete'] * 3)

    def test_the_decision_records_the_coverage_and_whether_it_conditioned_the_outcome(self):
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(30.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        sampler.participant_chooser = lambda intent, offense, state=None: {'coverage': 'COVER_1', 'side': 'away', 'team': 'BBB'}
        sampler.sample(random.Random(2), self._cell(), 'A', 'B', state=dict(STATE, down=2, togo=7))
        self.assertEqual(sampler.decisions[-1]['coverage'], 'COVER_1')
        self.assertFalse(sampler.decisions[-1]['coverage_conditioned'])


@unittest.skipUnless(Path(DB).exists(), 'database not present')
class Prior(unittest.TestCase):
    def test_the_coverage_prior_uses_only_seasons_before_the_cutoff(self):
        t = dl.priors(DB, 2026)
        self.assertEqual(t['seasons'][0], 2016)
        self.assertEqual(t['seasons'][-1], 2025)
        self.assertTrue(t['team'])


if __name__ == '__main__':
    unittest.main()
