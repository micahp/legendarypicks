"""Decision model categories A to N as SLC pre-event decisions: labels, the team prior, the draw, and the target they name.

The label, cell, prior and draw tests run on decision_layer directly. The chooser tests pin what the decision labels do to the
pre-event choice: a drawn target role is the receiver's role, and the starting QB still throws. The chooser tests were written
before the chooser accepted a decision table, so they fail until pre_event.choose takes one.
"""
import random
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import decision_layer as dl  # noqa: E402
import pre_event as pe  # noqa: E402
import slc_playcall as slc  # noqa: E402
from test_pre_event import SNAPSHOT  # noqa: E402
from test_slc_playcall import STATE, blank_artifact  # noqa: E402

EMPTY_SHARES = {'receive': {}, 'carry': {}}  # every rostered player at the floor weight
CELL = dl.cell_of(1, 10, 50)  # the cell of STATE: first and ten at midfield (ten yards is "long" in the decision model)


def play(**kw):
    """A labelled-play input with every field empty; keyword arguments set the fields a test cares about."""
    base = {'is_pass': False, 'is_run': False, 'receiver_pos': None, 'rusher_pos': None, 'pass_length': None,
            'pass_location': None, 'run_gap': None, 'shotgun': None, 'is_play_action': None, 'is_motion': None,
            'n_blitzers': None, 'n_pass_rushers': None, 'qb_location': None, 'starting_hash': None,
            'n_offense_backfield': None, 'n_defense_box': None}
    base.update(kw)
    return base


def table_forcing(labels, cell, team='AAA', season=2025, n=200):
    """A prior in which every row of this cell carries the same labels, so the team and the league agree exactly."""
    rows = [{'game_id': f'g{i}', 'play_id': i, 'season': season, 'team': team, 'cell': cell, 'labels': dict(labels)}
            for i in range(n)]
    return dl.fit(rows, prior_season=season)


class LabelRules(unittest.TestCase):
    def test_a_pass_has_a_receiver_role_and_no_rusher_categories(self):
        labels = dl.label_row(play(is_pass=True, receiver_pos='TE', pass_length='deep', pass_location='left'))
        self.assertEqual(labels['A'], 'TE')
        self.assertEqual(labels['D'], 'deep')
        self.assertEqual(labels['E'], 'left')
        self.assertIsNone(labels['B'])
        self.assertIsNone(labels['C'])

    def test_a_run_has_a_rusher_role_and_a_gap_only_for_a_back(self):
        back = dl.label_row(play(is_run=True, rusher_pos='RB', run_gap='guard'))
        self.assertEqual((back['B'], back['C']), ('RB', 'guard'))
        qb = dl.label_row(play(is_run=True, rusher_pos='QB', run_gap='guard'))
        self.assertEqual(qb['B'], 'QB')
        self.assertIsNone(qb['C'])

    def test_a_wide_receiver_who_carries_is_the_wr_te_rusher_role(self):
        self.assertEqual(dl.label_row(play(is_run=True, rusher_pos='WR'))['B'], 'WR_TE')

    def test_uncharted_zero_codes_are_no_label(self):
        labels = dl.label_row(play(is_run=True, qb_location='0', starting_hash='0'))
        self.assertIsNone(labels['J'])
        self.assertIsNone(labels['K'])

    def test_a_backfield_of_three_or_more_is_3plus_and_a_box_of_eight_or_more_is_8plus(self):
        labels = dl.label_row(play(is_run=True, n_offense_backfield=4, n_defense_box=9))
        self.assertEqual((labels['L'], labels['M']), ('3+', '8+'))

    def test_a_pass_has_blitz_and_rusher_count_labels_and_a_run_does_not(self):
        passing = dl.label_row(play(is_pass=True, n_blitzers=0, n_pass_rushers=5))
        self.assertEqual((passing['I'], passing['N']), ('no', '5+'))
        running = dl.label_row(play(is_run=True, n_blitzers=0, n_pass_rushers=5))
        self.assertIsNone(running['I'])
        self.assertIsNone(running['N'])


class Cells(unittest.TestCase):
    def test_the_cell_is_down_a_distance_band_and_the_red_zone(self):
        self.assertEqual(dl.cell_of(3, 7, 25), '3|medium|other')
        self.assertEqual(dl.cell_of(3, 8, 25), '3|long|other')  # the decision model's bands: short 1 to 3, medium 4 to 7
        self.assertEqual(dl.cell_of(1, 2, 15), '1|short|red')
        self.assertEqual(dl.cell_of(2, 12, 60), '2|long|other')


class Draw(unittest.TestCase):
    def test_a_dropback_draws_pass_and_alignment_categories_only(self):
        table = table_forcing({'A': 'WR', 'B': 'RB', 'D': 'short', 'F': 'yes'}, CELL)
        drawn = dl.draw(table, 'AAA', 1, 10, 50, 'dropback', 'seed-1')
        self.assertTrue(set(drawn) <= set(dl.PASS_CATS) | set(dl.ALIGN_CATS))
        self.assertNotIn('B', drawn)
        self.assertNotIn('C', drawn)

    def test_a_run_draws_run_and_alignment_categories_only(self):
        table = table_forcing({'B': 'RB', 'C': 'guard', 'F': 'no'}, CELL)
        drawn = dl.draw(table, 'AAA', 1, 10, 50, 'run', 'seed-1')
        self.assertTrue(set(drawn) <= set(dl.RUN_CATS) | set(dl.ALIGN_CATS))
        self.assertNotIn('A', drawn)

    def test_the_same_seed_text_gives_the_same_labels(self):
        table = table_forcing({'A': 'WR', 'D': 'deep'}, CELL)
        self.assertEqual(dl.draw(table, 'AAA', 1, 10, 50, 'dropback', 'seed-9'),
                         dl.draw(table, 'AAA', 1, 10, 50, 'dropback', 'seed-9'))

    def test_a_cell_with_no_prior_draws_no_label(self):
        table = table_forcing({'A': 'WR'}, CELL)
        drawn = dl.draw(table, 'AAA', 4, 20, 90, 'dropback', 'seed-1')
        self.assertTrue(all(v is None for v in drawn.values()))

    def test_a_team_prior_is_shrunk_toward_the_league_with_k(self):
        rows = [{'game_id': f'L{i}', 'play_id': i, 'season': 2025, 'team': 'BBB', 'cell': CELL,
                 'labels': {'D': 'deep'}} for i in range(100)]
        rows += [{'game_id': f'T{i}', 'play_id': i, 'season': 2025, 'team': 'AAA', 'cell': CELL,
                  'labels': {'D': 'short'}} for i in range(10)]
        table = dl.fit(rows, prior_season=2025)
        dist = dl.distribution(table, 'AAA', CELL, 'D')
        league_short, league_deep = 10 / 110, 100 / 110  # the league's cell includes AAA's own rows
        self.assertAlmostEqual(dist['short'], (10 + 20 * league_short) / 30)
        self.assertAlmostEqual(dist['deep'], (0 + 20 * league_deep) / 30)


class Prior(unittest.TestCase):
    def test_the_prior_is_built_from_the_prior_season_only(self):
        rows = [{'game_id': 'g', 'play_id': 1, 'season': 2024, 'team': 'AAA', 'cell': CELL, 'labels': {'D': 'deep'}}]
        table = dl.fit(rows, prior_season=2025)
        self.assertEqual(dict(table['league']['D']), {})

    def test_a_play_with_no_charting_gets_an_empty_label_set(self):
        labelled = [{'game_id': 'g', 'play_id': 1, 'season': 2025, 'team': 'AAA', 'cell': CELL,
                     'labels': {'A': 'WR'}}]
        rows = dl.attach([{'game_id': 'g', 'play_id': 1}, {'game_id': 'g', 'play_id': 2}], labelled)
        self.assertEqual(rows[0]['labels'], {'A': 'WR'})
        self.assertEqual(rows[1]['labels'], {})

    def test_the_lift_average_is_neutral_when_empty_and_geometric_otherwise(self):
        self.assertEqual(dl.geometric_mean([]), 1.0)
        self.assertAlmostEqual(dl.geometric_mean([0.5, 2.0]), 1.0)


class ChooserWithLabels(unittest.TestCase):
    """The decision label for category A is the receiver's role, and the passer is still the starting QB."""

    def test_the_drawn_target_role_is_the_receiver_role_for_every_seed(self):
        table = table_forcing({'A': 'TE'}, CELL)
        for seed in range(1, 31):
            chosen = pe.choose(SNAPSHOT, 'home', 'dropback', seed=seed, index=0, state=STATE, player_shares=EMPTY_SHARES,
                               decision_table=table)
            self.assertEqual(chosen['receiver']['pos_abb'], 'TE', seed)
            self.assertEqual(chosen['target_role'], 'TE', seed)
            self.assertEqual(chosen['passer']['gsis_id'], 'AQB1', seed)

    def test_a_drawn_role_with_no_rostered_player_still_gives_a_target_and_the_starting_qb(self):
        table = table_forcing({'A': 'Other'}, CELL)
        chosen = pe.choose(SNAPSHOT, 'home', 'dropback', seed=5, index=0, state=STATE, player_shares=EMPTY_SHARES,
                           decision_table=table)
        self.assertIn(chosen['receiver']['pos_abb'], {'WR', 'TE', 'RB'})
        self.assertEqual(chosen['passer']['gsis_id'], 'AQB1')

    def test_the_drawn_labels_are_kept_on_the_choice(self):
        table = table_forcing({'A': 'TE'}, CELL)
        chosen = pe.choose(SNAPSHOT, 'home', 'dropback', seed=5, index=0, state=STATE, player_shares=EMPTY_SHARES,
                           decision_table=table)
        self.assertEqual(chosen['labels']['A'], 'TE')

    def test_a_cell_without_a_prior_still_gives_a_target_and_the_starting_qb(self):
        table = table_forcing({'A': 'TE'}, '4|long|red')
        chosen = pe.choose(SNAPSHOT, 'home', 'dropback', seed=5, index=0, state=STATE, player_shares=EMPTY_SHARES,
                           decision_table=table)
        self.assertIsNone(chosen['labels']['A'])
        self.assertEqual(chosen['passer']['gsis_id'], 'AQB1')
        self.assertIn(chosen['receiver']['pos_abb'], {'WR', 'TE', 'RB'})


if __name__ == '__main__':
    unittest.main()


def labelled_cell(events_and_labels):
    """A pool cell of pass or run rows, each carrying the decision labels given with it."""
    rows = []
    for i, (event, play_type, labels) in enumerate(events_and_labels):
        row = {'game_id': '2025_01_AAA_BBB', 'play_id': i, 'season': 2025, 'down': 1, 'ydstogo': 10, 'yardline_100': 50,
               'play_type': play_type, 'posteam': 'AAA', 'labels': labels}
        rows.append((event, row, 6.0, 52))
    return rows


class SamplerWithLabels(unittest.TestCase):
    """The outcome follows the drawn labels: the sampled row carries the labels that were drawn, when the cell has such a row."""

    def _sampler(self, table):
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(30.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        sampler.decision_table = table
        sampler.decision_outcomes = True
        return sampler

    def test_the_sampled_row_carries_the_drawn_pass_location(self):
        table = table_forcing({'E': 'left'}, CELL)
        pool = labelled_cell([('pass_complete', 'pass', {'E': 'left'}), ('pass_complete', 'pass', {'E': 'right'})] * 20)
        for seed in range(1, 41):
            sampler = self._sampler(table)
            sampler.participant_chooser = pe.chooser(SNAPSHOT, seed=seed, decision_table=table)
            _event, row, _runoff, _spot = sampler.sample(random.Random(seed), pool, 'A', 'B', state=dict(STATE))
            self.assertEqual(row['labels']['E'], 'left', seed)

    def test_a_drawn_label_with_no_matching_row_falls_back_to_the_cell(self):
        table = table_forcing({'E': 'middle'}, CELL)
        pool = labelled_cell([('pass_complete', 'pass', {'E': 'left'})] * 5)
        sampler = self._sampler(table)
        sampler.participant_chooser = pe.chooser(SNAPSHOT, seed=3, decision_table=table)
        _event, row, _runoff, _spot = sampler.sample(random.Random(3), pool, 'A', 'B', state=dict(STATE))
        self.assertEqual(row['labels']['E'], 'left')
        self.assertNotIn('E', sampler.decisions[-1]['labels_matched'])

    def test_the_decision_record_names_the_labels_it_conditioned_on(self):
        table = table_forcing({'E': 'left'}, CELL)
        pool = labelled_cell([('pass_complete', 'pass', {'E': 'left'}), ('pass_complete', 'pass', {'E': 'right'})] * 5)
        sampler = self._sampler(table)
        sampler.participant_chooser = pe.chooser(SNAPSHOT, seed=4, decision_table=table)
        sampler.sample(random.Random(4), pool, 'A', 'B', state=dict(STATE))
        record = sampler.decisions[-1]
        self.assertEqual(record['labels']['E'], 'left')
        self.assertTrue(record['labels_conditioned'])
        self.assertIn('E', record['labels_matched'])


DECISION_MODEL_2025 = {  # category_defined_2025 in the frozen validation record (validate2025.json, decision_model.py)
    'A': 16609, 'B': 14168, 'C': 8704, 'D': 17358, 'E': 17358, 'F': 32813, 'G': 18645, 'H': 32813, 'I': 18645,
    'J': 32757, 'K': 32765, 'L': 32773, 'M': 32761, 'N': 18553}


class DatabaseCalibration(unittest.TestCase):
    """The labels built from this database match the decision model's own 2025 counts, category by category."""

    @classmethod
    def setUpClass(cls):
        import e1_drive as e1
        cls.db = e1.DEFAULT_DB
        if not Path(cls.db).exists():
            raise FileNotFoundError(f'the play-by-play database is needed for the calibration: {cls.db}')
        cls.rows = dl.load_rows(cls.db, [2025])

    def test_each_category_has_the_decision_model_2025_count(self):
        counts = {c: sum(1 for r in self.rows if r['labels'].get(c) is not None) for c in dl.CATS}
        diff = {c: counts[c] - DECISION_MODEL_2025[c] for c in dl.CATS if counts[c] != DECISION_MODEL_2025[c]}
        self.assertEqual(diff, {}, f'label counts differ from the decision model (ours minus theirs): {diff}')


class Cutoffs(unittest.TestCase):
    def test_a_cutoff_with_no_charted_prior_season_fails_loudly(self):
        with self.assertRaises(ValueError):
            dl.load_rows('unused.db', [])  # no season before the cutoff is charted: nothing to label, nothing to prior
        with self.assertRaises(ValueError):
            dl.load_rows('unused.db', [2021])


class CarryLabels(unittest.TestCase):
    """The rusher role from decision category B names the position that carries: a WR or TE on an end-around, a back, or the QB."""

    def _run(self, role, seed):
        table = table_forcing({'B': role}, CELL)
        return pe.choose(SNAPSHOT, 'home', 'run', seed=seed, index=0, state=STATE, player_shares=EMPTY_SHARES,
                         decision_table=table)

    def test_a_wr_te_rusher_role_carries_the_ball_as_a_receiver_would(self):
        for seed in range(1, 41):
            chosen = self._run('WR_TE', seed)
            self.assertIn(chosen['rusher']['pos_abb'], {'WR', 'TE'}, seed)

    def test_an_rb_rusher_role_carries_from_a_back(self):
        for seed in range(1, 41):
            self.assertEqual(self._run('RB', seed)['rusher']['pos_abb'], 'RB', seed)

    def test_a_qb_rusher_role_carries_from_the_quarterbacks(self):
        for seed in range(1, 41):
            self.assertEqual(self._run('QB', seed)['rusher']['pos_abb'], 'QB', seed)
