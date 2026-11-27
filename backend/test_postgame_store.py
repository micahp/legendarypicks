from contextlib import closing
import copy
from pathlib import Path
import sqlite3
import tempfile
import unittest

from postgame_story_engine import generate_recap
from postgame_story_store import save_generation
from test_postgame_story_engine import fixture


class StoreTests(unittest.TestCase):
    def test_history_deduplicates_and_blocked_never_replaces_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'demo.sqlite'
            bundle = fixture(); recap = generate_recap(bundle)
            a = save_generation(path, bundle, recap)
            self.assertEqual(a, save_generation(path, bundle, recap))
            bad = copy.deepcopy(recap); bad['headline'] = 'Wrong winner'
            save_generation(path, bundle, bad)
            with closing(sqlite3.connect(path)) as c, c:
                self.assertEqual(c.execute('select count(*) from game_story_postgame_history').fetchone()[0], 1)
                self.assertEqual(c.execute('select history_id from game_story_postgame_current').fetchone()[0], a)
                with self.assertRaises(sqlite3.IntegrityError):
                    c.execute('delete from game_story_postgame_history')

    def test_never_opens_production_path(self):
        with self.assertRaises(ValueError):
            save_generation('/root/legendarypicks/backend/data/picks.db', fixture(), generate_recap(fixture()))


if __name__ == '__main__':
    unittest.main()
