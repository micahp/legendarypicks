import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from postgame_story_facts import load_scoreboard
from postgame_story_engine import generate_recap


class DatabaseAdapterTests(unittest.TestCase):
    def test_loads_one_publisher_final_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'fixture.sqlite'
            with sqlite3.connect(db) as con:
                con.execute('create table scoreboard_snapshots(league text, game_id text, payload text, state text, start_time text, fetched_at text, source text)')
                payload = {'game_id': 'g1', 'completed': True, 'state': 'post', 'status': 'Final',
                           'away': {'abbrev': 'A', 'name': 'A', 'score': 10.0},
                           'home': {'abbrev': 'B', 'name': 'B', 'score': 20.0}}
                con.execute('insert into scoreboard_snapshots values(?,?,?,?,?,?,?)',
                            ('nfl', 'g1', json.dumps(payload), 'post', '2026-11-01T18:00:00Z', '2026-11-01T22:00:00Z', 'espn'))
            before = db.read_bytes()
            facts = load_scoreboard(db, 'nfl', 'g1')
            self.assertEqual(generate_recap(facts)['gate'], 'eligible_score_only')
            self.assertEqual(before, db.read_bytes())
            with self.assertRaises(LookupError):
                load_scoreboard(db, 'nfl', 'missing')


if __name__ == '__main__':
    unittest.main()
