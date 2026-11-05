import json
import os
import sqlite3
import tempfile
import unittest

import backfill_nfl_rotowire_ids as backfill
import nfl_news


def sleeper_file(entries):
    """Sleeper's identity file as parse_sleeper_crosswalk reads it. It refuses fewer than 1000 mapped players."""
    players = {}
    for index, entry in enumerate(entries):
        players[f's{index}'] = entry
    for index in range(1000):
        players[f'filler{index}'] = {'rotowire_id': str(90000 + index), 'full_name': f'Filler {index}',
                                     'position': 'WR'}
    return json.dumps(players).encode()


def entry(rotowire_id, espn=None, gsis=None, name='Ann Smith', position='QB'):
    return {'rotowire_id': rotowire_id, 'espn_id': espn, 'gsis_id': gsis, 'full_name': name, 'position': position}


class BackfillTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.db = os.path.join(self._dir.name, 'ids.db')
        con = sqlite3.connect(self.db)
        con.execute('CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, league TEXT, espn_id TEXT, nfl_gsis_id TEXT)')
        con.execute('CREATE TABLE player_source_ids(id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, league TEXT, '
                    'source_player_key TEXT, player_id INTEGER, first_seen TEXT, last_seen TEXT)')
        con.commit()
        con.close()

    def tearDown(self):
        self._dir.cleanup()

    def add_player(self, player_id, espn=None, gsis=None, name='Ann Smith'):
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO players VALUES (?, ?, 'nfl', ?, ?)", (player_id, name, espn, gsis))
        con.commit()
        con.close()

    def store(self, player_id, key):
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO player_source_ids(source, league, source_player_key, player_id) "
                    "VALUES ('rotowire', 'nfl', ?, ?)", (key, player_id))
        con.commit()
        con.close()

    def run_backfill(self, entries, apply=True):
        crosswalk = nfl_news.parse_sleeper_crosswalk(sleeper_file(entries))
        con = sqlite3.connect(self.db, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            return backfill.run(con, crosswalk, apply=apply, now='2026-11-05T12:00:00+00:00')
        finally:
            con.close()

    def outcomes(self):
        con = sqlite3.connect(self.db)
        try:
            return {(row[0], row[1]): row[2] for row in con.execute(
                'SELECT player_id, rotowire_id, outcome FROM nfl_rotowire_id_decisions')}
        finally:
            con.close()

    def links(self):
        con = sqlite3.connect(self.db)
        try:
            return sorted(con.execute("SELECT source_player_key, player_id FROM player_source_ids "
                                      "WHERE source='rotowire' AND league='nfl'").fetchall())
        finally:
            con.close()

    def test_espn_id_links_to_its_rotowire_id(self):
        self.add_player(1, espn='111')
        self.run_backfill([entry('5001', espn='111')])
        self.assertEqual(self.links(), [('5001', 1)])
        self.assertEqual(self.outcomes(), {(1, '5001'): 'link'})

    def test_gsis_id_alone_links(self):
        self.add_player(2, gsis='GSIS2')
        self.run_backfill([entry('5002', gsis='GSIS2')])
        self.assertEqual(self.links(), [('5002', 2)])

    def test_native_ids_that_disagree_are_a_conflict_and_nothing_is_written(self):
        self.add_player(3, espn='333', gsis='GSIS3')
        self.run_backfill([entry('5003', espn='333'), entry('5099', gsis='GSIS3')])
        self.assertEqual(self.links(), [])
        self.assertEqual(self.outcomes()[(3, None)], 'conflict')

    def test_one_rotowire_id_claimed_by_two_players_is_a_conflict_for_both(self):
        self.add_player(4, espn='444')
        self.add_player(5, espn='444')
        self.run_backfill([entry('5004', espn='444')])
        self.assertEqual(self.links(), [])
        self.assertEqual(self.outcomes()[(4, '5004')], 'conflict')
        self.assertEqual(self.outcomes()[(5, '5004')], 'conflict')

    def test_a_different_id_already_stored_is_a_conflict_not_an_overwrite(self):
        self.add_player(6, espn='666')
        self.store(6, '7777')
        self.run_backfill([entry('5006', espn='666')])
        self.assertEqual(self.links(), [('7777', 6)])
        self.assertEqual(self.outcomes()[(6, '5006')], 'conflict')

    def test_an_id_stored_for_another_player_blocks_the_link(self):
        self.add_player(7, espn='777')
        self.store(8, '5007')
        self.run_backfill([entry('5007', espn='777')])
        self.assertEqual(self.links(), [('5007', 8)])
        self.assertEqual(self.outcomes()[(7, '5007')], 'conflict')

    def test_existing_identical_link_is_not_written_twice(self):
        self.add_player(9, espn='999')
        self.store(9, '5009')
        self.run_backfill([entry('5009', espn='999')])
        self.assertEqual(self.links(), [('5009', 9)])
        self.assertEqual(self.outcomes()[(9, '5009')], 'already_linked')

    def test_native_id_absent_from_sleeper_is_unresolved(self):
        self.add_player(10, espn='1010')
        self.run_backfill([entry('5010', espn='OTHER')])
        self.assertEqual(self.outcomes()[(10, None)], 'unresolved')
        self.assertEqual(self.links(), [])

    def test_player_without_any_native_id_is_not_decided(self):
        self.add_player(11, espn=None, gsis=None, name='Ann Smith')
        summary = self.run_backfill([entry('5011', espn='1111', name='Ann Smith')])
        self.assertEqual(summary['no_native_id'], 1)
        self.assertEqual(self.links(), [])

    def test_matching_name_alone_never_links(self):
        # The Sleeper entry carries the same full name and position, but the player has no native id.
        self.add_player(12, espn=None, gsis=None, name='Ann Smith')
        self.run_backfill([entry('5012', espn=None, gsis=None, name='Ann Smith', position='QB')])
        self.assertEqual(self.links(), [])

    def test_dry_run_writes_nothing_and_creates_no_tables(self):
        self.add_player(13, espn='1313')
        con = sqlite3.connect(self.db)
        con.close()
        crosswalk = nfl_news.parse_sleeper_crosswalk(sleeper_file([entry('5013', espn='1313')]))
        ro = sqlite3.connect(f'file:{self.db}?mode=ro', uri=True)
        ro.row_factory = sqlite3.Row
        try:
            summary = backfill.run(ro, crosswalk, apply=False)
        finally:
            ro.close()
        self.assertEqual(summary['counts'], {'link': 1})
        self.assertEqual(self.links(), [])
        con = sqlite3.connect(self.db)
        tables = [row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        con.close()
        self.assertNotIn('nfl_rotowire_id_decisions', tables)


if __name__ == '__main__':
    unittest.main()
