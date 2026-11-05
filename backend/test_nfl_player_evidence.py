import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone

import ingest_nfl_player_news as ingest
import nfl_player_evidence as evidence


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.path = handle.name
        handle.close()
        self.addCleanup(os.unlink, self.path)
        self.con = sqlite3.connect(self.path)
        self.con.row_factory = sqlite3.Row
        ingest.ensure_schema(self.con)
        self.con.execute('CREATE TABLE player_projections(run_id TEXT, player_id INTEGER, season INTEGER, week INTEGER, '
                         'game_id TEXT, team TEXT, stat TEXT, mean REAL, median REAL, p10 REAL, p90 REAL, scenario TEXT, '
                         'model_version TEXT, source TEXT, p_plays REAL, as_of TEXT, league TEXT)')
        self.con.execute('CREATE TABLE player_game_availability(league TEXT, season INTEGER, week INTEGER, game_id TEXT, '
                         'team TEXT, player_id INTEGER, played INTEGER, report_status TEXT, reason TEXT, source TEXT, '
                         'built_at TEXT, off_snaps INTEGER, off_pct REAL, def_snaps INTEGER, def_pct REAL, st_snaps INTEGER)')
        self.con.execute('CREATE TABLE external_projections(source TEXT, player TEXT, team TEXT, stat TEXT)')
        self.con.execute("INSERT INTO external_projections VALUES ('cbs', 'Joe Fagnano', 'BAL', 'pass_yds')")
        self.con.commit()

    def tearDown(self):
        self.con.close()

    def version(self, update_id, first_seen, headline, player_id=100):
        self.con.execute(
            """INSERT INTO nfl_player_news_updates(update_id, content_sha256, rotowire_player_id, player_id, match, team,
                 first_name, last_name, position, injury_status, injury_type, injury_location, return_date, headline, notes,
                 analysis, link, published_utc, published_raw, first_seen_utc, poll_id)
               VALUES (?, ?, '4000', ?, 'crosswalk', 'BAL', 'Tyler', 'Huntley', 'QB', 'OUT', '', '', '', ?, 'n', 'a',
                 'https://www.rotowire.com/x', '2026-11-03T17:00:00+00:00', '2026-11-03T09:00:00-08:00', ?, 1)""",
            (update_id, f'sha-{headline}', player_id, headline, first_seen))
        self.con.commit()

    def cutoff(self):
        return datetime(2026, 11, 5, 23, 45, tzinfo=timezone.utc)

    def test_news_is_the_version_known_at_the_cutoff_not_a_later_edit(self):
        self.version(1, '2026-11-05T10:00:00+00:00', 'Before edit')
        self.version(1, '2026-11-05T20:00:00+00:00', 'After edit')
        self.version(2, '2026-11-05T23:50:00+00:00', 'Captured after cutoff')
        rows = evidence.news_for_player(self.con, 100, '2026-11-05T23:45:00+00:00', 10)
        self.assertEqual([(1, 'After edit')], [(r['id'], r['headline']) for r in rows])

    def test_earlier_cutoff_returns_the_earlier_version(self):
        self.version(1, '2026-11-05T10:00:00+00:00', 'Before edit')
        self.version(1, '2026-11-05T20:00:00+00:00', 'After edit')
        rows = evidence.news_for_player(self.con, 100, '2026-11-05T12:00:00+00:00', 10)
        self.assertEqual(['Before edit'], [r['headline'] for r in rows])

    def test_publisher_time_and_capture_time_are_both_returned(self):
        self.version(1, '2026-11-05T10:00:00+00:00', 'Stamped')
        row = evidence.news_for_player(self.con, 100, '2026-11-05T23:45:00+00:00', 10)[0]
        self.assertEqual('2026-11-03T09:00:00-08:00', row['published'])
        self.assertEqual('2026-11-05T10:00:00+00:00', row['captured_at_utc'])
        self.assertEqual('https://www.rotowire.com/x', row['url'])

    def test_teammate_claim_appears_under_the_teammate_and_not_as_the_teammates_article(self):
        self.version(1, '2026-11-05T10:00:00+00:00', 'Huntley injury update', player_id=100)
        self.con.execute("INSERT INTO nfl_player_news_claims(update_id, content_sha256, claim_index, extractor, "
                         "subject_player_id, update_player_id, attribution, claim_class, field, span, poll_id) "
                         "VALUES (1, 'sha-Huntley injury update', 0, 'claims-v1', 101, 100, 'named_in_other_update', "
                         "'starter_named', 'notes', 'Minter named Joe Fagnano Week 9 starter.', 1)")
        self.con.commit()
        result = evidence.player_evidence(self.con, 101, self.cutoff())
        self.assertEqual([1], [a['id'] for a in result['news']])
        self.assertTrue(result['news'][0]['about_player'])
        self.assertEqual(100, result['news'][0]['player_id'])
        self.assertEqual(['starter_named'], [c['claim_class'] for c in result['starter_claims']])
        huntley = evidence.player_evidence(self.con, 100, self.cutoff())
        self.assertEqual(100, huntley['news'][0]['player_id'])

    def test_projections_and_availability_use_the_latest_build_at_or_before_the_cutoff(self):
        self.con.executemany("INSERT INTO player_projections(run_id, player_id, season, week, game_id, team, stat, mean, "
                             "as_of, source, league) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                             [('r1', 101, 2026, 9, 'g9', 'BAL', 'pass_yds', 200.0, '2026-11-05T12:00:00+00:00', 'lp', 'nfl'),
                              ('r2', 101, 2026, 9, 'g9', 'BAL', 'pass_yds', 210.0, '2026-11-05T22:00:00+00:00', 'lp', 'nfl'),
                              ('r3', 101, 2026, 9, 'g9', 'BAL', 'pass_yds', 999.0, '2026-11-06T06:00:00+00:00', 'lp', 'nfl')])
        self.con.executemany("INSERT INTO player_game_availability(league, season, week, game_id, team, player_id, played, "
                             "report_status, reason, source, built_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                             [('nfl', 2026, 9, 'g9', 'BAL', 101, 0, 'Questionable', '', 'nflverse',
                               '2026-11-05T12:00:00+00:00'),
                              ('nfl', 2026, 9, 'g9', 'BAL', 101, 1, 'Active', '', 'nflverse',
                               '2026-11-06T06:00:00+00:00')])
        self.con.commit()
        result = evidence.player_evidence(self.con, 101, self.cutoff())
        self.assertEqual('2026-11-05T22:00:00+00:00', result['projections']['as_of'])
        self.assertEqual([210.0], [r['mean'] for r in result['projections']['rows']])
        self.assertEqual(['Questionable'], [r['report_status'] for r in result['availability']])

    def test_external_projections_are_counted_as_not_joinable(self):
        result = evidence.player_evidence(self.con, 101, self.cutoff())
        self.assertEqual(1, result['external_projections_not_joinable_rows'])

    def test_unlinked_player_is_unavailable_not_no_news(self):
        self.con.execute('CREATE TABLE IF NOT EXISTS player_source_ids(id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, '
                         'league TEXT, source_player_key TEXT, player_id INTEGER, first_seen TEXT, last_seen TEXT)')
        self.con.commit()
        now = datetime(2026, 11, 5, 20, 0, tzinfo=timezone.utc)
        self.con.execute("INSERT INTO nfl_player_news_polls(polled_at_utc, feed_min_id, feed_max_id, feed_count, "
                         "new_updates, changed_updates, new_claims, claim_counts, matched, unmatched, boundary_gap_count, "
                         "internal_gap_count, gap_ids) VALUES ('2026-11-05T19:59:00+00:00',1,2,2,0,0,0,'{}',0,0,0,0,'[]')")
        self.con.commit()
        result = evidence.fantasy_news_response(self.con, {'id': 555, 'name': 'Unlinked Player'}, 10, now)
        self.assertEqual('unavailable', result['data_status'])
        self.assertIn('not linked', result['message'])

    def test_no_poll_means_unavailable_and_a_stale_poll_is_marked(self):
        now = datetime(2026, 11, 5, 20, 0, tzinfo=timezone.utc)
        self.assertEqual('missing', evidence.freshness(self.con, now)['status'])
        self.con.execute("INSERT INTO nfl_player_news_polls(polled_at_utc, feed_min_id, feed_max_id, feed_count, "
                         "new_updates, changed_updates, new_claims, claim_counts, matched, unmatched, boundary_gap_count, "
                         "internal_gap_count, gap_ids) VALUES ('2026-11-05T18:00:00+00:00',1,2,2,0,0,0,'{}',0,0,0,0,'[]')")
        self.assertEqual('stale', evidence.freshness(self.con, now)['status'])


if __name__ == '__main__':
    unittest.main()
