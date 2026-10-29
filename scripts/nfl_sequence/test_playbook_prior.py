"""The playbook as a pre-event input: the team's pass depth, pass location and run gap, by situation, from its playbook files.

Written before playbook_prior.py. When on, the playbook's situational prior replaces the decision prior's draw for categories D, E and C
wherever the playbook has a prior for the situation. Where it has none, the decision label stands and the fallback is recorded.
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import playbook_prior as pbp  # noqa: E402
import pre_event as pe  # noqa: E402
from test_decision_layer import CELL, table_forcing  # noqa: E402
from test_pre_event import SNAPSHOT  # noqa: E402
from test_slc_playcall import STATE  # noqa: E402

EMPTY_SHARES = {'receive': {}, 'carry': {}}


def playbook(team, season, plays):
    return {'team_id': team, 'season': season, 'offense': {'observed_plays': [
        {'attributes': {'play_type': play_type, 'down': str(down), 'ydstogo': str(togo), 'yardline_100': str(yl),
                        'pass_length': length, 'pass_location': location, 'run_gap': gap}} for play_type, down, togo, yl, length,
        location, gap in plays]}}


class Rows(unittest.TestCase):
    def test_a_pass_gives_its_length_and_location_and_a_run_its_gap(self):
        rows = pbp.rows_of(playbook('AAA', 2025, [('pass', 1, 10, 50, 'deep', 'left', ''), ('run', 1, 10, 50, '', '', 'guard')]), 2025)
        self.assertEqual(rows[0]['labels'], {'D': 'deep', 'E': 'left'})
        self.assertEqual(rows[1]['labels'], {'C': 'guard'})
        self.assertEqual(rows[0]['cell'], CELL)

    def test_a_play_with_no_concept_gives_no_row(self):
        self.assertEqual(pbp.rows_of(playbook('AAA', 2025, [('pass', 1, 10, 50, '', '', '')]), 2025), [])

    def test_the_team_code_is_mapped_to_the_database_code(self):
        rows = pbp.rows_of(playbook('LA', 2025, [('pass', 1, 10, 50, 'short', 'right', '')]), 2025)
        self.assertEqual(rows[0]['team'], 'LAR')


class Choice(unittest.TestCase):
    def test_the_playbook_prior_replaces_the_decision_draw_for_pass_depth(self):
        decision = table_forcing({'D': 'short', 'E': 'middle'}, CELL)
        book = table_forcing({'D': 'deep'}, CELL)
        chosen = pe.choose(SNAPSHOT, 'home', 'dropback', seed=5, index=0, state=STATE, player_shares=EMPTY_SHARES,
                           decision_table=decision, playbook_table=book)
        self.assertEqual(chosen['labels']['D'], 'deep')
        self.assertEqual(chosen['labels']['E'], 'middle')  # the playbook has no E prior here, so the decision label stands
        self.assertEqual(chosen['playbook_fallback'], ['E'])

    def test_without_a_playbook_the_decision_labels_are_unchanged(self):
        decision = table_forcing({'D': 'short'}, CELL)
        chosen = pe.choose(SNAPSHOT, 'home', 'dropback', seed=5, index=0, state=STATE, player_shares=EMPTY_SHARES,
                           decision_table=decision)
        self.assertEqual(chosen['labels']['D'], 'short')
        self.assertNotIn('playbook_fallback', chosen)

    def test_a_run_takes_the_playbook_gap(self):
        decision = table_forcing({'C': 'tackle'}, CELL)
        book = table_forcing({'C': 'end'}, CELL)
        chosen = pe.choose(SNAPSHOT, 'home', 'run', seed=5, index=0, state=STATE, player_shares=EMPTY_SHARES,
                           decision_table=decision, playbook_table=book)
        self.assertEqual(chosen['labels']['C'], 'end')


if __name__ == '__main__':
    unittest.main()
