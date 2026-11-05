import contextlib
import io
import json
import os
import sqlite3
import tempfile
import unittest

import ingest_nfl_player_news as ingest


def update_xml(update_id, rotowire_id, first='Ann', last='Smith', team='BAL', position='QB',
               published='2026-11-03T09:00:00-08:00', headline=None):
    return f"""
    <Update Id="{update_id}">
      <DateTime>{published}</DateTime>
      <Headline>{headline or f'Headline {update_id}'}</Headline>
      <Notes>Notes {update_id}</Notes>
      <Analysis>Analysis {update_id}</Analysis>
      <Injury Status="" Type="" Location="" ReturnDate="" />
      <Player Id="{rotowire_id}">
        <FirstName>{first}</FirstName><LastName>{last}</LastName>
        <Position>{position}</Position>
        <Link>https://www.rotowire.com/football/player/{last.lower()}-{rotowire_id}</Link>
      </Player>
      <Team Code="{team}" />
    </Update>
    """


def feed_xml(updates, date='2026-11-05'):
    return (f"<News><League>NFL</League><Date>{date}</Date><Updates>" + ''.join(updates)
            + '</Updates></News>')


def filler(first_id, count):
    """Updates for players with no crosswalk row. The parser needs at least 20 updates per feed."""
    return [update_xml(uid, 9000 + uid, first='Filler', last=f'Player{uid}') for uid in range(first_id, first_id + count)]


class PollTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.db = os.path.join(self._dir.name, 'poll.db')
        self.xml = os.path.join(self._dir.name, 'feed.xml')
        con = sqlite3.connect(self.db)
        con.execute('CREATE TABLE player_source_ids(id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, league TEXT, '
                    'source_player_key TEXT, player_id INTEGER, first_seen TEXT, last_seen TEXT)')
        con.execute('CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, league TEXT, team TEXT, position TEXT)')
        con.execute("INSERT INTO players VALUES (99, 'Ann Smith', 'nfl', 'BAL', 'QB')")
        con.commit()
        con.close()

    def tearDown(self):
        self._dir.cleanup()

    def crosswalk(self, *rows):
        con = sqlite3.connect(self.db)
        for key, player_id, league in rows:
            con.execute("INSERT INTO player_source_ids(source, league, source_player_key, player_id) "
                        "VALUES ('rotowire', ?, ?, ?)", (league, key, player_id))
        con.commit()
        con.close()

    def poll(self, updates, date='2026-11-05'):
        with open(self.xml, 'w') as handle:
            handle.write(feed_xml(updates, date))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = ingest.main(['--db', self.db, '--feed-file', self.xml])
        return code, out.getvalue()

    def query(self, sql, args=()):
        con = sqlite3.connect(self.db)
        try:
            return con.execute(sql, args).fetchall()
        finally:
            con.close()

    def test_matched_update_is_stored_under_the_crosswalk_player(self):
        self.crosswalk(('2001', 77, 'nfl'))
        code, out = self.poll([update_xml(1000, 2001, first='Joe', last='Fagnano', team='BAL', position='QB')]
                              + filler(1001, 20))
        self.assertEqual(code, 0)
        self.assertEqual(self.query('SELECT player_id, match FROM nfl_player_news_updates WHERE update_id=1000'),
                         [(77, 'crosswalk')])
        self.assertEqual(self.query("SELECT COUNT(*) FROM unresolved_players WHERE source_player_key='2001'"), [(0,)])
        self.assertIn('players matched 1 of 21', out)

    def test_unmatched_update_is_kept_without_a_player_and_queued_for_review(self):
        # The name matches players row 99, but no crosswalk row links this RotoWire id to it. Nothing joins on names.
        code, out = self.poll([update_xml(1000, 2002)] + filler(1001, 20))
        self.assertEqual(code, 0)
        self.assertEqual(self.query('SELECT player_id, match FROM nfl_player_news_updates WHERE update_id=1000'),
                         [(None, 'no_crosswalk_row')])
        self.assertEqual(self.query("SELECT raw_name, count, reason FROM unresolved_players "
                                    "WHERE source_player_key='2002'"), [('Ann Smith', 1, 'no_crosswalk_row')])
        self.assertEqual(self.query('SELECT COUNT(*) FROM players'), [(1,)])
        self.assertIn('players matched 0 of 21, unmatched 21 queued for review', out)

    def test_ambiguous_crosswalk_is_not_matched(self):
        self.crosswalk(('2003', 77, 'nfl'), ('2003', 78, 'nfl'))
        code, _ = self.poll([update_xml(1000, 2003)] + filler(1001, 20))
        self.assertEqual(code, 0)
        self.assertEqual(self.query('SELECT player_id, match FROM nfl_player_news_updates WHERE update_id=1000'),
                         [(None, 'ambiguous_crosswalk')])

    def test_crosswalk_rows_for_other_leagues_do_not_match(self):
        self.crosswalk(('2004', 26726, 'mlb'))
        code, _ = self.poll([update_xml(1000, 2004)] + filler(1001, 20))
        self.assertEqual(code, 0)
        self.assertEqual(self.query('SELECT player_id, match FROM nfl_player_news_updates WHERE update_id=1000'),
                         [(None, 'no_crosswalk_row')])

    def test_review_row_clears_when_the_crosswalk_catches_up(self):
        self.poll([update_xml(1000, 2002)] + filler(1001, 20))
        self.assertEqual(self.query("SELECT COUNT(*) FROM unresolved_players WHERE source_player_key='2002'"), [(1,)])
        self.crosswalk(('2002', 99, 'nfl'))
        code, _ = self.poll([update_xml(1000, 2002)] + filler(1001, 20))
        self.assertEqual(code, 0)
        self.assertEqual(self.query('SELECT player_id, match FROM nfl_player_news_updates WHERE update_id=1000'),
                         [(99, 'crosswalk')])
        self.assertEqual(self.query("SELECT COUNT(*) FROM unresolved_players WHERE source_player_key='2002'"), [(0,)])

    def test_adjacent_polls_have_no_gap(self):
        self.poll(filler(1000, 25))
        self.poll(filler(1025, 25))
        self.assertEqual(self.query('SELECT boundary_gap_count, internal_gap_count, gap_ids FROM nfl_player_news_polls '
                                    'WHERE id=2'), [(0, 0, '[]')])

    def test_gap_between_polls_is_recorded(self):
        self.poll(filler(1000, 25))
        code, out = self.poll(filler(1030, 25))
        self.assertEqual(code, 0)
        rows = self.query('SELECT previous_max_id, boundary_gap_count, internal_gap_count, gap_ids '
                          'FROM nfl_player_news_polls WHERE id=2')
        self.assertEqual(rows, [(1024, 5, 0, json.dumps(list(range(1025, 1030))))])
        self.assertIn('id gaps 5 since the previous poll and 0 inside this feed', out)

    def test_gap_inside_one_feed_is_recorded(self):
        updates = filler(1000, 25)
        del updates[10]  # update 1010 is missing from the feed
        code, _ = self.poll(updates)
        self.assertEqual(code, 0)
        self.assertEqual(self.query('SELECT internal_gap_count, gap_ids FROM nfl_player_news_polls WHERE id=1'),
                         [(1, '[1010]')])

    def test_repoll_of_the_same_feed_changes_nothing(self):
        self.poll(filler(1000, 25))
        before = self.query('SELECT COUNT(*) FROM nfl_player_news_updates')
        code, out = self.poll(filler(1000, 25))
        self.assertEqual(code, 0)
        self.assertEqual(self.query('SELECT COUNT(*) FROM nfl_player_news_updates'), before)
        self.assertEqual(self.query('SELECT new_updates, changed_updates FROM nfl_player_news_polls WHERE id=2'),
                         [(0, 0)])

    def test_edited_update_is_kept_as_a_second_version(self):
        self.poll([update_xml(1000, 2001, headline='Old headline')] + filler(1001, 20))
        code, _ = self.poll([update_xml(1000, 2001, headline='New headline')] + filler(1001, 20))
        self.assertEqual(code, 0)
        self.assertEqual(self.query('SELECT headline FROM nfl_player_news_updates WHERE update_id=1000 '
                                    'ORDER BY first_seen_utc'), [('Old headline',), ('New headline',)])
        self.assertEqual(self.query('SELECT new_updates, changed_updates FROM nfl_player_news_polls WHERE id=2'),
                         [(0, 1)])

    def test_naive_publish_time_is_refused_and_nothing_is_written(self):
        code, _ = self.poll([update_xml(1000, 2001, published='2026-11-03T09:00:00')] + filler(1001, 20))
        self.assertEqual(code, 1)
        tables = [row[0] for row in self.query("SELECT name FROM sqlite_master WHERE type='table'")]
        self.assertNotIn('nfl_player_news_polls', tables)

    def test_feed_with_too_few_updates_is_refused(self):
        code, _ = self.poll(filler(1000, 5))
        self.assertEqual(code, 1)

    def test_update_row_records_its_publish_time_in_utc(self):
        self.crosswalk(('2001', 77, 'nfl'))
        self.poll([update_xml(1000, 2001, published='2026-11-03T09:00:00-08:00')] + filler(1001, 20))
        self.assertEqual(self.query('SELECT published_utc, published_raw FROM nfl_player_news_updates WHERE update_id=1000'),
                         [('2026-11-03T17:00:00+00:00', '2026-11-03T09:00:00-08:00')])


if __name__ == '__main__':
    unittest.main()
