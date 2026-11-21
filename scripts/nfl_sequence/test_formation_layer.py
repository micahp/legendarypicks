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


def personnel_first_table(**overrides):
    """Personnel-first counts for one cell (1st and 10) and the league. 12 after 12 is sticky; 12 under center runs."""
    C = collections.Counter
    table = {'strength': 25.0, 'personnel_league': C({'11': 60, '12': 40}),
             'personnel_cells': {(False, 1, '7-10', '12'): C({'12': 90, '11': 10}),
                                 (False, 1, '7-10', fl.START): C({'11': 60, '12': 40})},
             'personnel_previous': {}, 'personnel_situation': {}, 'personnel_team': {},
             'formation_cells': {}, 'formation_league': {'11': C({'SHOTGUN': 1}), '12': C({'UNDER CENTER': 1})},
             'formation_team': {},
             'call_cells': {('12', 'UNDER CENTER', 1, '7-10'): C({'run': 80, 'dropback': 20}),
                            ('11', 'SHOTGUN', 1, '7-10'): C({'run': 30, 'dropback': 70})},
             'call_league': {}, 'call_team': {}, 'call_situation': {(1, '7-10'): C({'run': 50, 'dropback': 50})},
             'call_situation_team': {}, 'call_overall': C({'run': 50, 'dropback': 50})}
    table.update(overrides)
    return {'personnel_first': table}


FIRST_AND_TEN = {'down': 1, 'togo': 10, 'quarter': 1, 'clock': 600}


class PersonnelFirst(unittest.TestCase):
    """personnel_first() draws personnel from the situation and the previous personnel, then formation, then the call."""

    def test_the_personnel_does_not_see_the_call_probability(self):
        for seed in range(200):
            low = fl.personnel_first(personnel_first_table(), 0.1, FIRST_AND_TEN, fl.START, f'seed:{seed}')
            high = fl.personnel_first(personnel_first_table(), 0.9, FIRST_AND_TEN, fl.START, f'seed:{seed}')
            self.assertEqual(low[:2], high[:2])

    def test_the_previous_personnel_in_the_drive_moves_the_draw(self):
        n = 4000
        after_12 = sum(fl.personnel_first(personnel_first_table(), 0.5, FIRST_AND_TEN, '12', f's:{i}')[0] == '12'
                       for i in range(n)) / n
        at_start = sum(fl.personnel_first(personnel_first_table(), 0.5, FIRST_AND_TEN, fl.START, f's:{i}')[0] == '12'
                       for i in range(n)) / n
        self.assertAlmostEqual(at_start, 0.40, delta=0.03)
        self.assertGreater(after_12, 0.75)

    def test_the_call_is_shifted_by_the_personnel_and_formation(self):
        runs = {}
        for seed in range(400):
            personnel, formation, p = fl.personnel_first(personnel_first_table(), 0.5, FIRST_AND_TEN, fl.START, f's:{seed}')
            runs[(personnel, formation)] = p
        self.assertLess(runs[('12', 'UNDER CENTER')], 0.35)
        self.assertGreater(runs[('11', 'SHOTGUN')], 0.55)

    def test_a_certain_call_is_never_reversed(self):
        for seed in range(50):
            for p in (0.0, 1.0):
                self.assertEqual(fl.personnel_first(personnel_first_table(), p, FIRST_AND_TEN, fl.START, f's:{seed}')[2], p)

    def test_old_priors_without_the_tables_refuse(self):
        with self.assertRaises(ValueError):
            fl.personnel_first(priors({'SHOTGUN': 1}, {'SHOTGUN': 1}), 0.5, FIRST_AND_TEN, fl.START, 's')

    def test_the_fit_chains_personnel_within_a_drive_and_skips_unknown(self):
        import sqlite3
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            db = f'{folder}/fixture.db'
            con = sqlite3.connect(db)
            con.execute('CREATE TABLE nfl_pbp (game_id, play_id, season, week, posteam, drive, qtr, game_seconds_remaining, '
                        'down, ydstogo, play_type)')
            con.execute('CREATE TABLE nfl_hist_participation (nflverse_game_id, play_id, season, offense_formation, '
                        'offense_personnel)')
            plays = [(1, 1, 'run', '1 RB, 2 TE, 2 WR'), (2, 1, 'pass', '1 RB, 2 TE, 2 WR'), (3, 1, 'pass', None),
                     (4, 1, 'run', '1 RB, 1 TE, 3 WR'), (5, 2, 'pass', '1 RB, 1 TE, 3 WR')]
            for play_id, drive, play_type, personnel in plays:
                con.execute('INSERT INTO nfl_pbp VALUES (?, ?, 2020, 1, ?, ?, 1, 3000, 1, 10, ?)',
                            ('g', play_id, 'KC', drive, play_type))
                con.execute('INSERT INTO nfl_hist_participation VALUES (?, ?, 2020, ?, ?)',
                            ('g', play_id, 'SHOTGUN', personnel))
            con.commit()
            con.close()
            table = fl.personnel_first_priors(db, 2021)
        cells = table['personnel_cells']
        self.assertEqual(cells[(False, 1, '7-10', fl.START)], collections.Counter({'12': 1, '11': 1}))  # plays 1 and 5
        self.assertEqual(cells[(False, 1, '7-10', '12')], collections.Counter({'12': 1}))  # play 2
        self.assertNotIn((False, 1, '7-10', fl.UNKNOWN), cells)  # play 4 follows an unknown play: no transition
        self.assertEqual(table['personnel_league'], collections.Counter({'12': 2, '11': 2}))
        self.assertEqual(table['call_cells'][('12', 'SHOTGUN', 1, '7-10')], collections.Counter({'run': 1, 'dropback': 1}))


class PersonnelFirstChooser(unittest.TestCase):
    def test_the_previous_personnel_carries_within_a_drive_and_resets_on_a_change_of_offense(self):
        from test_pre_event import SNAPSHOT
        seen = []
        original = fl.personnel_first

        def recording(table, p, state, previous, seed_text, team=None):
            seen.append(previous)
            return '12', 'UNDER CENTER', p
        fl.personnel_first = recording
        try:
            prepare = pe.chooser(SNAPSHOT, 7, formation_priors=personnel_first_table()).prepare
            for offense, quarter in (('A', 1), ('A', 1), ('B', 1), ('B', 3)):
                prepare(offense, dict(FIRST_AND_TEN, quarter=quarter), 0.5)
        finally:
            fl.personnel_first = original
        self.assertEqual(seen, [fl.START, '12', fl.START, fl.START])


if __name__ == '__main__':
    unittest.main()
