import contextlib
import io
import json
import os
import sqlite3
import tempfile
import unittest

import ingest_nfl_player_news as ingest


def update_xml(update_id, rotowire_id, first='Ann', last='Smith', team='BAL', position='QB',
               published='2026-11-03T09:00:00-08:00', headline=None, notes=None, analysis=None):
    return f"""
    <Update Id="{update_id}">
      <DateTime>{published}</DateTime>
      <Headline>{headline or f'Headline {update_id}'}</Headline>
      <Notes>{notes or f'Notes {update_id}'}</Notes>
      <Analysis>{analysis or f'Analysis {update_id}'}</Analysis>
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

    def add_roster(self):
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO players VALUES (100, 'Tyler Huntley', 'nfl', 'BAL', 'QB')")
        con.execute("INSERT INTO players VALUES (101, 'Joe Fagnano', 'nfl', 'BAL', 'QB')")
        con.commit()
        con.close()

    def claims(self):
        return self.query('SELECT update_id, subject_player_id, update_player_id, attribution, claim_class, field '
                          'FROM nfl_player_news_claims ORDER BY update_id, claim_class')

    def test_starter_claim_about_a_teammate_is_linked_to_that_teammate(self):
        self.add_roster()
        self.crosswalk(('2001', 100, 'nfl'))
        code, _ = self.poll([update_xml(1000, 2001, first='Tyler', last='Huntley', headline='Injury update',
                                        notes='Coach Jesse Minter named Joe Fagnano Week 9 starter.')]
                            + filler(1001, 20))
        self.assertEqual(code, 0)
        # The article stays with Huntley. The claim is about Fagnano.
        self.assertEqual(self.query('SELECT player_id FROM nfl_player_news_updates WHERE update_id=1000'), [(100,)])
        self.assertEqual(self.claims(), [(1000, 101, 100, 'named_in_other_update', 'starter_named', 'notes')])

    def test_starter_claim_about_the_update_player_is_own(self):
        self.add_roster()
        self.crosswalk(('2002', 101, 'nfl'))
        self.poll([update_xml(1000, 2002, first='Joe', last='Fagnano', headline='Named Week 9 starter')]
                  + filler(1001, 20))
        self.assertEqual(self.claims(), [(1000, 101, 101, 'own', 'starter_named', 'headline')])

    def test_sentence_naming_two_players_makes_no_claim_and_is_counted(self):
        self.add_roster()
        self.crosswalk(('2001', 100, 'nfl'))
        self.poll([update_xml(1000, 2001, first='Tyler', last='Huntley', headline='Injury update',
                              notes='Minter named Joe Fagnano the starter ahead of Tyler Huntley.')]
                  + filler(1001, 20))
        self.assertEqual(self.claims(), [])
        counts = self.query('SELECT claim_counts FROM nfl_player_news_polls WHERE id=1')[0][0]
        self.assertEqual(json.loads(counts), {'multi_player_sentence': 1})

    def test_claims_are_stored_once_per_version(self):
        self.add_roster()
        self.crosswalk(('2001', 100, 'nfl'))
        updates = [update_xml(1000, 2001, first='Tyler', last='Huntley', headline='Injury update',
                              notes='Coach Jesse Minter named Joe Fagnano Week 9 starter.')] + filler(1001, 20)
        self.poll(updates)
        self.poll(updates)
        self.assertEqual(len(self.claims()), 1)
        self.assertEqual(self.query('SELECT new_claims FROM nfl_player_news_polls WHERE id=2'), [(0,)])

    def test_stale_check_reports_a_missing_or_old_poll(self):
        from datetime import datetime, timedelta, timezone
        con = sqlite3.connect(self.db)
        ingest.ensure_schema(con)
        con.commit()
        ok, message = ingest.check_stale(con, 30, datetime.now(timezone.utc))
        self.assertFalse(ok)
        self.assertIn('no poll', message)
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        con.execute("INSERT INTO nfl_player_news_polls(polled_at_utc, feed_min_id, feed_max_id, feed_count, new_updates, "
                    "changed_updates, new_claims, claim_counts, matched, unmatched, boundary_gap_count, internal_gap_count, "
                    "gap_ids) VALUES (?,1,2,2,0,0,0,'{}',0,0,0,0,'[]')", (old,))
        con.commit()
        ok, message = ingest.check_stale(con, 30, datetime.now(timezone.utc))
        con.close()
        self.assertFalse(ok)
        self.assertIn('older than 30', message)


    def test_every_poll_keeps_its_untouched_payload_with_its_sha256(self):
        import gzip
        import hashlib
        updates = filler(1000, 25)
        self.poll(updates)
        self.poll(updates)
        with open(self.xml, 'rb') as handle:
            raw = handle.read()
        rows = self.query('SELECT poll_id, payload_sha256, payload_bytes, payload_gzip, source_url '
                          'FROM nfl_player_news_raw_polls ORDER BY poll_id')
        self.assertEqual([1, 2], [row[0] for row in rows])
        for poll_id, digest, size, blob, url in rows:
            self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)
            self.assertEqual(len(raw), size)
            self.assertEqual(raw, gzip.decompress(blob))
            self.assertTrue(url.startswith('https://'))

    def test_a_raw_row_is_never_rewritten_by_a_later_poll(self):
        self.poll(filler(1000, 25))
        before = self.query('SELECT poll_id, payload_sha256 FROM nfl_player_news_raw_polls')
        self.poll(filler(1025, 25))
        after = self.query('SELECT poll_id, payload_sha256 FROM nfl_player_news_raw_polls ORDER BY poll_id')
        self.assertEqual(before, after[:1])
        self.assertEqual(2, len(after))

    def test_adjacent_polls_have_no_gap(self):
        self.poll(filler(1000, 25))
        self.poll(filler(1025, 25))
        self.assertEqual(self.query('SELECT boundary_gap_count, internal_gap_count, gap_ids FROM nfl_player_news_polls '
                                    'WHERE id=2'), [(0, 0, '[]')])

    def test_gap_between_polls_is_recorded(self):
        self.poll(filler(1000, 25))
        code, out = self.poll(filler(1030, 25))
        self.assertEqual(code, 3)  # ids missing: stored, and the run is flagged
        rows = self.query('SELECT previous_max_id, boundary_gap_count, internal_gap_count, gap_ids '
                          'FROM nfl_player_news_polls WHERE id=2')
        self.assertEqual(rows, [(1024, 5, 0, json.dumps(list(range(1025, 1030))))])
        self.assertIn('id gaps 5 since the previous poll and 0 inside this feed', out)

    def test_gap_inside_one_feed_is_recorded(self):
        updates = filler(1000, 25)
        del updates[10]  # update 1010 is missing from the feed
        code, _ = self.poll(updates)
        self.assertEqual(code, 3)
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
