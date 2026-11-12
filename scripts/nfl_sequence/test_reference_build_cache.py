"""Unit tests for persistent, source-verified reference setup caching."""
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reference_build_cache as cache  # noqa: E402


class ReferenceBuildCache(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db = Path(temp.name) / 'historical.sqlite'
        with sqlite3.connect(self.db) as con:
            con.execute('CREATE TABLE nfl_pbp_sample (x INTEGER)')
            con.execute('INSERT INTO nfl_pbp_sample VALUES (1)')
        env = mock.patch.dict(os.environ, {
            'SLC_FIT_CACHE_DIR': str(Path(temp.name) / 'cache')})
        env.start()
        self.addCleanup(env.stop)
        self.calls = 0

    def build(self):
        self.calls += 1
        row = {'event': 'sack', 'source_id': 1}
        return [row], {(1,): [('sack', row, 10, None)]}, {'excluded': 0}, None

    def options(self, cutoff=2026):
        return dict(name='e1_rows_and_pools', db=self.db,
                    settings=(cutoff, True, False),
                    builder=self.build, code_files=(__file__,))

    def test_reuse_warm_entry_and_preserve_row_aliases(self):
        args = self.options()
        cold = cache.memo_db(**args)
        warm = cache.memo_db(**args)
        self.assertEqual(self.calls, 1)
        self.assertEqual(cold, warm)
        self.assertIs(warm[0][0], warm[1][(1,)][0][1])
        warm[0][0]['source_id'] = 100
        another = cache.memo_db(**args)
        self.assertEqual(another[0][0]['source_id'], 1)
        self.assertEqual(self.calls, 1)

    def test_cutoff_and_database_change_invalidate_cache(self):
        cache.memo_db(**self.options())
        cache.memo_db(**self.options(2025))
        self.assertEqual(self.calls, 2)
        with sqlite3.connect(self.db) as con:
            con.execute('INSERT INTO nfl_pbp_sample VALUES (2)')
        cache.memo_db(**self.options())
        self.assertEqual(self.calls, 3)

    def test_source_files_have_identity(self):
        a = cache.file_identity(self.db)
        self.assertEqual(a[0], str(self.db.resolve()))
        with sqlite3.connect(self.db) as con:
            con.execute('INSERT INTO nfl_pbp_sample VALUES (2)')
        self.assertNotEqual(a, cache.file_identity(self.db))

    def test_disabled_cache_runs_builder_each_time(self):
        with mock.patch.dict(os.environ, {'SLC_FIT_CACHE_DIR': ''}):
            cache.memo_db(**self.options())
            cache.memo_db(**self.options())
        self.assertEqual(self.calls, 2)

    def test_concurrent_database_change_fails_closed(self):
        def mutating_build():
            with sqlite3.connect(self.db) as con:
                con.execute('INSERT INTO nfl_pbp_sample VALUES (3)')
            return self.build()

        with self.assertRaisesRegex(RuntimeError, 'changed while loading'):
            cache.memo_db('e1_rows_and_pools', self.db, (2026, True),
                          mutating_build, (__file__,))


if __name__ == '__main__':
    unittest.main()
