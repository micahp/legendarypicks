"""The lineup table: hash refusal, grouping transitions, leave hazards, count-driven substitution and bench eligibility."""
import json
import random
import tempfile
import unittest
from pathlib import Path

import participation_field as pf


def _data(**overrides):
    data = {
        'schema': pf.SCHEMA,
        'league_transitions': [['1|long|red', 'START', {'11': 9.0, '12': 1.0}],
                               ['1|long|red', '11', {'11': 8.0, '12': 2.0}],
                               ['1|long|red', '12', {'11': 1.0, '12': 9.0}]],
        'team_transitions': [['KC', '1|long|red', '11', {'11': 2.0}]],
        'leave_counts': [['held', 'WR', 1, 0.0, 100.0], ['held', 'WR', 3, 40.0, 100.0],
                         ['changed', 'WR', 1, 0.0, 100.0], ['swap', 'WR', 0, 0.0, 100.0]],
        'appearances': [['rb1', 'KC', '11', 8.0], ['wr1', 'KC', '11', 20.0]],
        'team_plays': [['KC', '11', 40.0]],
        'position_prior': [['RB', '11', 0.5], ['WR', '11', 0.25]],
    }
    data.update(overrides)
    return data


def _player(gsis_id, pos, rank=1):
    return {'gsis_id': gsis_id, 'pos_abb': pos, 'pos_rank': rank}


def _roster():
    return [_player('rb1', 'RB'), _player('rb2', 'RB', 2), _player('fb1', 'FB'),
            _player('te1', 'TE'), _player('te2', 'TE', 2),
            _player('wr1', 'WR'), _player('wr2', 'WR', 2), _player('wr3', 'WR', 3), _player('wr4', 'WR', 4),
            _player('qb1', 'QB')]


def _field(**overrides):
    return pf.Field(_data(**overrides), 'h' * 64)


class Cells(unittest.TestCase):
    def test_buckets_match_the_model_cells(self):
        self.assertEqual(pf.cell_of(3, 7, 18), '3|long|red')
        self.assertEqual(pf.cell_of(1, 10, 75), '1|xl|own')
        self.assertEqual(pf.cell_of(None, None, None), 'na|na|na')

    def test_a_grouping_counts_its_five_skill_players(self):
        self.assertEqual(pf.group_counts('11'), {'RB': 1, 'TE': 1, 'WR': 3})
        self.assertEqual(pf.group_counts('22'), {'RB': 2, 'TE': 2, 'WR': 1})


class Loading(unittest.TestCase):
    def _write(self, data):
        handle = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8')
        json.dump(data, handle)
        handle.close()
        return Path(handle.name)

    def test_a_table_with_another_hash_is_refused(self):
        path = self._write(_data())
        with self.assertRaises(ValueError):
            pf.Field.load(path, '0' * 64)
        field = pf.Field.load(path, pf.sha256_file(path))
        self.assertEqual(field.sha256, pf.sha256_file(path))

    def test_a_wrong_schema_is_refused(self):
        with self.assertRaises(ValueError):
            pf.Field(_data(schema='lp.nfl.participation-field.v1'), 'x')


class GroupingTransitions(unittest.TestCase):
    def test_the_previous_grouping_moves_the_next_one(self):
        field = _field()
        stays = field.group_probs('ARI', '1|long|red', '11')  # no team data: the league transition decides
        self.assertGreater(stays['11'], stays['12'])
        after_twelve = field.group_probs('ARI', '1|long|red', '12')
        self.assertGreater(after_twelve['12'], after_twelve['11'])

    def test_a_team_with_its_own_data_leans_toward_it(self):
        field = _field(team_transitions=[['KC', '1|long|red', '11', {'12': 30.0}]])
        self.assertGreater(field.group_probs('KC', '1|long|red', '11')['12'],
                           field.group_probs('ARI', '1|long|red', '11')['12'])

    def test_an_unseen_situation_is_counted_not_filled(self):
        field = _field()
        self.assertIsNone(field.draw_group('KC', '11', '4|xl|deep', random.Random(1)))
        self.assertEqual(field.status['no_league_cell'], 1)


class Hazards(unittest.TestCase):
    def test_a_longer_stint_leaves_more_often_in_the_fitted_table(self):
        field = _field()
        self.assertGreater(field.leave_prob('held', 'WR', 3), field.leave_prob('held', 'WR', 1))

    def test_swap_churn_is_one_rate_for_the_class(self):
        field = _field()
        self.assertEqual(field.leave_prob('swap', 'WR', 1), field.leave_prob('swap', 'WR', 5))


class Advance(unittest.TestCase):
    def test_an_empty_lineup_fills_the_grouping_exactly(self):
        field = _field()
        nxt, record = field.advance('KC', {}, '11', _roster(), random.Random(2), prev_group=pf.START)
        self.assertEqual(record['status'], 'ok')
        classes = [pf.SKILL[next(p['pos_abb'] for p in _roster() if p['gsis_id'] == pid)] for pid in nxt]
        self.assertEqual(sorted(classes), ['RB', 'TE', 'WR', 'WR', 'WR'])
        self.assertEqual(set(nxt.values()), {1})  # every entrant starts a stint of one

    def test_a_held_grouping_with_no_hazard_keeps_the_lineup_and_counts_the_stint(self):
        field = _field(leave_counts=[])
        lineup = {'rb1': 2, 'te1': 3, 'wr1': 1, 'wr2': 4, 'wr3': 1}
        nxt, record = field.advance('KC', lineup, '11', _roster(), random.Random(3), prev_group='11')
        self.assertEqual(nxt, {'rb1': 3, 'te1': 4, 'wr1': 2, 'wr2': 5, 'wr3': 2})
        self.assertEqual(record['entrants'], [])

    def test_a_grouping_change_moves_only_the_counts_that_change(self):
        field = _field(leave_counts=[])
        lineup = {'rb1': 1, 'te1': 1, 'wr1': 1, 'wr2': 1, 'wr3': 1}
        nxt, record = field.advance('KC', lineup, '12', _roster(), random.Random(4), prev_group='11')
        self.assertEqual(record['entrants'], ['te2'])  # TE 1 to 2
        self.assertEqual(len(record['count_removed']), 1)  # WR 3 to 2
        self.assertIn('rb1', nxt)

    def test_a_zero_usage_receiver_on_the_roster_can_enter(self):
        field = _field(leave_counts=[])
        roster = [p for p in _roster() if p['gsis_id'] != 'wr4'] + [_player('wr9', 'WR', 9)]  # wr9: no appearances
        lineup = {'rb1': 1, 'te1': 1, 'wr1': 1, 'wr2': 1, 'wr3': 1}
        nxt, record = field.advance('KC', lineup, '10', roster, random.Random(5), prev_group='11')
        self.assertIn('wr9', record['entrants'])  # 10 means four receivers, so one receiver enters from the bench

    def test_a_short_bench_is_recorded_not_filled_silently(self):
        field = _field(leave_counts=[])
        roster = [p for p in _roster() if p['pos_abb'] != 'TE']
        nxt, record = field.advance('KC', {}, '11', roster, random.Random(6), prev_group=pf.START)
        self.assertEqual(record['status'], 'short')
        self.assertEqual(record['short'], {'TE': 1})
        self.assertEqual(field.status['short'], 1)


if __name__ == '__main__':
    unittest.main()
