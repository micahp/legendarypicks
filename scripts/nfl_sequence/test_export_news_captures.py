import gzip
import hashlib
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone

import export_news_captures as export
import news_evidence


def feed_bytes(ids):
    updates = ''.join(
        f'<Update Id="{uid}"><DateTime>2026-11-03T09:00:00-08:00</DateTime><Headline>H{uid}</Headline>'
        f'<Notes>N{uid}</Notes><Analysis>A{uid}</Analysis><Injury Status="" Type="" Location="" ReturnDate="" />'
        f'<Player Id="{2000 + uid}"><FirstName>F{uid}</FirstName><LastName>L{uid}</LastName><Position>QB</Position>'
        f'<Link>https://www.rotowire.com/football/player/x-{uid}</Link></Player><Team Code="BAL" /></Update>'
        for uid in ids)
    return ('<News><League>NFL</League><Date>2026-11-05</Date><Updates>' + updates + '</Updates></News>').encode()


class ExportTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.db = os.path.join(self._dir.name, 'store.db')
        self.out = os.path.join(self._dir.name, 'captures')
        con = sqlite3.connect(self.db)
        con.execute('CREATE TABLE nfl_player_news_raw_polls(poll_id INTEGER PRIMARY KEY, polled_at_utc TEXT NOT NULL, '
                    'source_url TEXT NOT NULL, feed_date TEXT, payload_sha256 TEXT NOT NULL, payload_bytes INTEGER NOT NULL, '
                    'payload_gzip BLOB NOT NULL)')
        self.stored = {}
        for poll_id, polled, ids in ((1, '2026-11-05T20:00:00+00:00', range(1000, 1025)),
                                     (2, '2026-11-05T23:30:00+00:00', range(1000, 1026)),
                                     (3, '2026-11-05T23:45:00+00:00', range(1000, 1027))):
            raw = feed_bytes(ids)
            self.stored[poll_id] = raw
            con.execute('INSERT INTO nfl_player_news_raw_polls VALUES (?,?,?,?,?,?,?)',
                        (poll_id, polled, 'https://feed.example/nfl', '2026-11-05',
                         hashlib.sha256(raw).hexdigest(), len(raw), gzip.compress(raw)))
        con.commit()
        con.close()
        self.cutoff = datetime(2026, 11, 5, 23, 45, tzinfo=timezone.utc)

    def tearDown(self):
        self._dir.cleanup()

    def test_only_payloads_acquired_strictly_before_the_cutoff_are_exported(self):
        exported = export.export(self.db, self.cutoff, self.out)
        self.assertEqual([1, 2], [item['poll_id'] for item in exported])

    def test_exported_directory_reads_back_through_the_evidence_reader(self):
        export.export(self.db, self.cutoff, self.out)
        before, after = news_evidence.read_captures(self.out, self.cutoff)
        self.assertEqual(2, len(before))
        self.assertEqual(0, after)
        self.assertEqual(self.stored[2], before[1][1])

    def test_a_payload_that_does_not_match_its_stored_hash_stops_the_export(self):
        con = sqlite3.connect(self.db)
        con.execute("UPDATE nfl_player_news_raw_polls SET payload_sha256='0' WHERE poll_id=2")
        con.commit()
        con.close()
        with self.assertRaises(ValueError):
            export.export(self.db, self.cutoff, self.out)

    def test_an_existing_manifest_is_never_appended_to(self):
        export.export(self.db, self.cutoff, self.out)
        with self.assertRaises(ValueError):
            export.export(self.db, self.cutoff, self.out)


if __name__ == '__main__':
    unittest.main()
