import collections
import random
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import formation_layer as fl  # noqa: E402
import pre_event as pe  # noqa: E402
import slc_playcall as slc  # noqa: E402
from test_slc_playcall import STATE, blank_artifact  # noqa: E402


def priors(cell_formation, league_formation, cell_personnel=None, league_personnel=None):
    """A synthetic prior table with one situation (dropback, 2nd and 7) and the league for the same intent."""
    cell = {'formation': collections.Counter(cell_formation), 'personnel': collections.Counter(cell_personnel or {'11': 1})}
    league = {'formation': collections.Counter(league_formation), 'personnel': collections.Counter(league_personnel or {'11': 1})}
    return {'cells': {('dropback', 2, 'mid'): cell}, 'league': {'dropback': league, 'run': league}, 'strength': 25.0}


class Personnel(unittest.TestCase):
    def test_the_personnel_code_counts_running_backs_and_tight_ends(self):
        self.assertEqual(fl.personnel_code('1 C, 2 G, 1 QB, 1 RB, 2 T, 1 TE, 3 WR'), '11')
        self.assertEqual(fl.personnel_code('1 C, 1 QB, 1 RB, 4 T, 2 TE, 2 WR'), '12')

    def test_missing_or_unreadable_personnel_is_unknown_not_guessed(self):
        self.assertEqual(fl.personnel_code(None), fl.UNKNOWN)
        self.assertEqual(fl.personnel_code('not a grouping'), fl.UNKNOWN)


class Decision(unittest.TestCase):
    def test_the_formation_decision_is_never_unknown(self):
        table = priors({'SHOTGUN': 1, fl.UNKNOWN: 99}, {'SHOTGUN': 1, fl.UNKNOWN: 99})
        drawn = {fl.choose(table, 'dropback', 2, 7, f'seed-{i}')[0] for i in range(300)}
        self.assertEqual(drawn, {'SHOTGUN'})

    def test_a_sparse_cell_falls_back_to_the_league_shares(self):
        table = {'cells': {}, 'league': {'dropback': {'formation': collections.Counter({'PISTOL': 3, 'SHOTGUN': 1}),
                                                       'personnel': collections.Counter({'11': 1})}}, 'strength': 25.0}
        shares = fl.distribution(table, 'dropback', 3, 9, 'formation')
        self.assertAlmostEqual(shares['PISTOL'], 0.75, places=6)

    def test_the_choice_is_the_same_for_the_same_seed(self):
        table = priors({'SHOTGUN': 3, 'UNDER CENTER': 1}, {'SHOTGUN': 3, 'UNDER CENTER': 1})
        self.assertEqual(fl.choose(table, 'dropback', 2, 7, 'a'), fl.choose(table, 'dropback', 2, 7, 'a'))


class FormationConditionedOutcomes(unittest.TestCase):
    def _cell(self):
        rows = []
        for i, (event, play, formation) in enumerate(
                [('pass_complete', 'pass', 'SHOTGUN')] * 40 + [('pass_incomplete', 'pass', 'UNDER CENTER')] * 40):
            rows.append((event, {'game_id': '2025_01_AAA_BBB', 'play_id': i, 'season': 2025, 'down': 2, 'ydstogo': 7,
                                 'yardline_100': 50, 'play_type': play, 'posteam': 'AAA', 'formation': formation}, 6.0, 52))
        return rows

    def test_a_formation_changes_which_outcome_is_drawn(self):
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(30.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        sampler.formation_outcomes = True  # a near-certain dropback: the formation reweights outcome types within it
        cell = self._cell()
        shotgun = collections.Counter()
        under = collections.Counter()
        rng = random.Random(4)
        for _ in range(400):
            sampler.participant_chooser = lambda intent, offense, state=None: {'formation': 'SHOTGUN', 'side': 'home',
                                                                                'team': 'AAA'}
            shotgun[sampler.sample(rng, cell, 'A', 'B', state=dict(STATE, down=2, togo=7))[0]] += 1
            sampler.participant_chooser = lambda intent, offense, state=None: {'formation': 'UNDER CENTER', 'side': 'home',
                                                                                'team': 'AAA'}
            under[sampler.sample(rng, cell, 'A', 'B', state=dict(STATE, down=2, togo=7))[0]] += 1
        self.assertGreater(shotgun['pass_complete'], shotgun['pass_incomplete'] * 3)
        self.assertGreater(under['pass_incomplete'], under['pass_complete'] * 3)

    def test_the_formation_is_chosen_before_the_outcome_is_drawn(self):
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(30.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        sampler.formation_outcomes = True
        calls = []

        def chooser(intent, offense, state=None):
            calls.append('formation')
            return {'formation': 'SHOTGUN', 'personnel': '11', 'side': 'home', 'team': 'AAA'}
        sampler.participant_chooser = chooser

        class Recording(random.Random):
            def random(self):
                if not calls:
                    calls.append('intent')
                return super().random()

            def choices(self, population, weights=None, **kw):
                calls.append('outcome_type')
                return super().choices(population, weights=weights, **kw)

            def choice(self, seq):
                calls.append('outcome_row')
                return super().choice(seq)
        sampler.sample(Recording(5), self._cell(), 'A', 'B', state=dict(STATE, down=2, togo=7))
        self.assertEqual(calls[:3], ['intent', 'formation', 'outcome_type'])
        self.assertEqual(sampler.decisions[-1]['formation'], 'SHOTGUN')
        self.assertTrue(sampler.decisions[-1]['formation_conditioned'])

    def test_the_formation_is_recorded_on_the_decision_even_without_the_outcome_layer(self):
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(30.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        sampler.participant_chooser = lambda intent, offense, state=None: {'formation': 'PISTOL', 'side': 'home', 'team': 'AAA'}
        sampler.sample(random.Random(6), self._cell(), 'A', 'B', state=dict(STATE, down=2, togo=7))
        self.assertEqual(sampler.decisions[-1]['formation'], 'PISTOL')
        self.assertFalse(sampler.decisions[-1]['formation_conditioned'])


class TeamTendencies(unittest.TestCase):
    def test_a_teams_own_formation_tendency_moves_the_choice_toward_it(self):
        table = priors({'SHOTGUN': 1}, {'SHOTGUN': 1, 'UNDER CENTER': 1})
        table['team_cells'] = {('GB', 'run', 1, '7-10'): {'formation': collections.Counter({'UNDER CENTER': 60}),
                                                          'personnel': collections.Counter({'11': 1})}}
        league_only = fl.distribution(table, 'run', 1, 8, 'formation')
        with_team = fl.distribution(table, 'run', 1, 8, 'formation', team='GB')
        self.assertGreater(with_team['UNDER CENTER'], league_only['UNDER CENTER'])

    def test_a_team_with_no_history_in_the_situation_gets_the_league_cell(self):
        table = priors({'SHOTGUN': 1}, {'SHOTGUN': 1, 'UNDER CENTER': 1})
        self.assertEqual(fl.distribution(table, 'run', 1, 8, 'formation', team='NEW'),
                         fl.distribution(table, 'run', 1, 8, 'formation'))

    def test_the_team_tendency_never_chooses_unknown(self):
        table = priors({'SHOTGUN': 1}, {'SHOTGUN': 1})
        table['team_cells'] = {('GB', 'dropback', 2, '7-10'): {'formation': collections.Counter({fl.UNKNOWN: 99}),
                                                               'personnel': collections.Counter({'11': 1})}}
        self.assertEqual({fl.choose(table, 'dropback', 2, 8, f's{i}', team='GB')[0] for i in range(100)}, {'SHOTGUN'})


class PreEventChoice(unittest.TestCase):
    def test_the_chooser_adds_formation_and_personnel_when_given_priors(self):
        from test_pre_event import SNAPSHOT
        table = priors({'SHOTGUN': 1}, {'SHOTGUN': 1})
        chosen = pe.chooser(SNAPSHOT, 7, formation_priors=table)('dropback', 'A', {'down': 2, 'togo': 7})
        self.assertEqual(chosen['formation'], 'SHOTGUN')
        self.assertEqual(chosen['personnel'], '11')
        self.assertIn('passer', chosen)

    def test_without_priors_the_participants_are_unchanged(self):
        from test_pre_event import SNAPSHOT
        chosen = pe.chooser(SNAPSHOT, 7)('dropback', 'A', {'down': 2, 'togo': 7})
        self.assertNotIn('formation', chosen)


if __name__ == '__main__':
    unittest.main()
