import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import playcall_model as pm  # noqa: E402
import playcall_observations as pco  # noqa: E402
from test_playcall_observations import play  # noqa: E402

REAL_OBSERVATIONS = pco.observations


class EveryPlayScored(dict):
    def get(self, key, default=None):
        return {'posteam_score': 7, 'defteam_score': 3, 'goal_to_go': None}


def scored_observations(db, first_season=pco.FIRST_SEASON, last_season=pco.LAST_SEASON, **kwargs):
    """The real reader with every play scored and no score flags, so the test needs only the synthetic database."""
    return REAL_OBSERVATIONS(db, first_season=first_season, last_season=last_season, scores=lambda season: EveryPlayScored(),
                             flags={})


class Database:
    def __init__(self, rows):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / 'pbp.sqlite3')
        self.con = sqlite3.connect(self.path)
        self.con.execute(f"CREATE TABLE nfl_pbp ({', '.join(pco.COLUMNS)})")
        for row in rows:
            self.insert(row)
        self.con.commit()

    def insert(self, row):
        self.con.execute(f"INSERT INTO nfl_pbp ({', '.join(pco.COLUMNS)}) VALUES ({', '.join('?' for _ in pco.COLUMNS)})",
                         [row[c] for c in pco.COLUMNS])

    def set_distance(self, season, ydstogo):
        self.con.execute('UPDATE nfl_pbp SET ydstogo = ? WHERE season = ?', (ydstogo, season))
        self.con.commit()

    def close(self):
        self.con.close()
        self.tmp.cleanup()


class HistoricalRowsDigest(unittest.TestCase):
    def setUp(self):
        self.db = Database([play(season=2012, game_id='2012_01_AAA_BBB'),
                            play(season=2025, game_id='2025_01_AAA_BBB', play_id=2),
                            play(season=2026, game_id='2026_01_AAA_BBB', play_id=3)])

    def tearDown(self):
        self.db.close()

    def test_a_write_to_the_holdout_season_leaves_the_historical_digest_alone(self):
        before = pco.rows_sha256(self.db.path, 2010, 2025)
        self.db.con.execute("UPDATE nfl_pbp SET yards_gained = 99 WHERE season = 2026")
        self.db.con.commit()
        self.assertEqual(pco.rows_sha256(self.db.path, 2010, 2025), before)

    def test_a_write_to_a_historical_season_changes_the_digest(self):
        before = pco.rows_sha256(self.db.path, 2010, 2025)
        self.db.set_distance(2012, 1)
        self.assertNotEqual(pco.rows_sha256(self.db.path, 2010, 2025), before)

    def test_the_holdout_is_refused_before_any_row_is_read(self):
        with self.assertRaisesRegex(ValueError, 'sealed 2026 holdout'):
            pco.rows_sha256(self.db.path, 2010, 2026)


class FrameCache(unittest.TestCase):
    def setUp(self):
        self.db = Database([play(season=2012, game_id='2012_01_AAA_BBB'),
                            play(season=2025, game_id='2025_01_AAA_BBB', play_id=2),
                            play(season=2026, game_id='2026_01_AAA_BBB', play_id=3)])
        self.cache = Path(tempfile.mkdtemp()) / 'frame.npz'
        patcher = mock.patch.object(pco, 'observations', scored_observations)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.db.close()

    def load(self, last_season=2025):
        return pm.load_frame_cached(self.cache, range(2010, last_season + 1), db=self.db.path)

    def test_a_second_load_reuses_the_cache(self):
        self.assertEqual(self.load().cache_status, 'miss')
        self.assertEqual(self.load().cache_status, 'hit')

    def test_an_unrelated_holdout_write_keeps_the_cache(self):
        self.load()
        self.db.con.execute("UPDATE nfl_pbp SET yards_gained = 99 WHERE season = 2026")
        self.db.con.commit()
        self.assertEqual(self.load().cache_status, 'hit')

    def test_a_historical_write_rebuilds_the_cache_with_the_new_content(self):
        before = self.load()
        self.db.set_distance(2012, 1)
        rebuilt = self.load()
        self.assertEqual(rebuilt.cache_status, 'rebuilt')
        self.assertNotEqual(pm.frame_content_hash(rebuilt), pm.frame_content_hash(before))

    def test_a_different_cutoff_never_reuses_another_cutoffs_frame(self):
        self.assertNotEqual(pm.source_fingerprint(range(2010, 2025), self.db.path, True),
                            pm.source_fingerprint(range(2010, 2026), self.db.path, True))


if __name__ == '__main__':
    unittest.main()
