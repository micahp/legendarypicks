import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import extend_snap_counts_observed as extension


class ExtendSnapCountsTest(unittest.TestCase):
    def test_zero_or_missing_rows_do_not_become_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / 'base.json'
            base.write_text(json.dumps({'schema': 'lp.nfl.snap-counts.v1', 'season': 2026,
                                        'team_snaps': [['SEA', 7, 60]], 'player_snaps': [], 'active': []}))
            db, out = root / 'db.sqlite', root / 'out.json'
            with sqlite3.connect(db) as con:
                con.executescript('CREATE TABLE players (id INTEGER, nfl_gsis_id TEXT, position TEXT);'
                                  'CREATE TABLE nfl_snap_counts (player_id INTEGER, team TEXT, week INTEGER, '
                                  'season INTEGER, off_snaps INTEGER, off_pct REAL);'
                                  "INSERT INTO players VALUES (1, 'p', 'RB'), (2, 'q', 'RB');"
                                  "INSERT INTO nfl_snap_counts VALUES (1, 'SEA', 8, 2026, 30, .5),"
                                  "(2, 'SEA', 8, 2026, 0, 0);")
            argv = ['extend', '--base', str(base), '--base-sha256', hashlib.sha256(base.read_bytes()).hexdigest(),
                    '--db', str(db), '--season', '2026', '--week', '8', '--out', str(out)]
            with patch.object(sys, 'argv', argv):
                extension.main()
            data = json.loads(out.read_text())
            self.assertEqual(data['active'], [])
            self.assertEqual(data['player_snaps'], [['SEA', 8, 'p', 'RB', 30.0]])
            self.assertEqual(data['team_snaps'], [['SEA', 7, 60], ['SEA', 8, 60.0]])
            self.assertIn('unknown', data['exploratory_append']['active_membership'])

if __name__ == '__main__':
    unittest.main()
