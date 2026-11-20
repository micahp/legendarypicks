import json
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import demo_postgame


class OfflineDemoTests(unittest.TestCase):
    def test_fixture_replay_is_reproducible_and_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            argv = ['demo_postgame.py', '--output', directory]
            with patch('sys.argv', argv), patch('socket.socket', side_effect=AssertionError('network')), \
                    patch('sqlite3.connect', side_effect=AssertionError('database')):
                demo_postgame.main()
                first = {p.name: p.read_bytes() for p in Path(directory).iterdir()}
                demo_postgame.main()
                second = {p.name: p.read_bytes() for p in Path(directory).iterdir()}
        self.assertEqual(first, second)
        self.assertTrue({'demo.html', 'evidence_manifest.json', 'show_rundowns.jsonl'} <= first.keys())
        page = first['demo.html'].decode()
        for text in ('Morning', 'Pregame', 'Live', 'Postgame', 'local-only', 'Clip unavailable', 'favorite-team'):
            self.assertIn(text, page)
        json.loads(first['evidence_manifest.json'])

    def test_read_only_mode_requires_separate_output_directory(self):
        argv = ['demo_postgame.py', '--db', '/tmp/example.sqlite', '--league', 'nba', '--game-id', '1']
        with patch('sys.argv', argv), self.assertRaises(SystemExit):
            demo_postgame.main()


if __name__ == '__main__':
    unittest.main()
