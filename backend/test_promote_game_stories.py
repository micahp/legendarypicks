import sqlite3
import tempfile
import unittest
from pathlib import Path

import promote_game_stories as subject


SCHEMA = """CREATE TABLE game_story(
    league TEXT,
    game_id TEXT,
    story TEXT,
    generated_at TEXT,
    has_form INTEGER DEFAULT 0,
    has_stakes INTEGER DEFAULT 0,
    form_suppressed INTEGER DEFAULT 0,
    PRIMARY KEY(league, game_id)
)"""


class StoryPromotionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source_path = Path(self.directory.name) / "source.db"
        self.target_path = Path(self.directory.name) / "target.db"
        for path in (self.source_path, self.target_path):
            with sqlite3.connect(path) as connection:
                connection.execute(SCHEMA)

    def _write(self, path, game_id, story, generated_at):
        with sqlite3.connect(path) as connection:
            connection.execute(
                "INSERT INTO game_story VALUES(?,?,?,?,?,?,?)",
                ("mls", game_id, story, generated_at, 1, 0, 0),
            )

    def _plan(self):
        with subject._connect(str(self.source_path), readonly=True) as source, subject._connect(
            str(self.target_path), readonly=True
        ) as target:
            return subject.plan(source, target, "mls")

    def test_inserts_missing_and_updates_only_newer_source(self):
        self._write(self.source_path, "new", "new story", "2026-08-24 02:00:00")
        self._write(self.source_path, "update", "fresh", "2026-08-24 03:00:00")
        self._write(self.source_path, "older", "old source", "2026-08-24 01:00:00")
        self._write(self.target_path, "update", "stale", "2026-08-24 01:00:00")
        self._write(self.target_path, "older", "new target", "2026-08-24 04:00:00")

        computed = self._plan()
        self.assertEqual([row["game_id"] for row in computed["insert"]], ["new"])
        self.assertEqual([row["game_id"] for row in computed["update"]], ["update"])
        self.assertEqual(computed["target_newer"], 1)
        with subject._connect(str(self.target_path), readonly=False) as target:
            self.assertEqual(subject.apply(target, computed), 2)
        with sqlite3.connect(self.target_path) as target:
            rows = dict(target.execute("SELECT game_id,story FROM game_story"))
        self.assertEqual(rows, {"new": "new story", "update": "fresh", "older": "new target"})

    def test_equal_timestamp_conflict_refuses(self):
        timestamp = "2026-08-24 01:00:00"
        self._write(self.source_path, "g1", "source", timestamp)
        self._write(self.target_path, "g1", "target", timestamp)
        with self.assertRaises(subject.StoryPromotionError):
            self._plan()

    def test_blank_story_refuses(self):
        self._write(self.source_path, "g1", "", "2026-08-24 01:00:00")
        with self.assertRaises(subject.StoryPromotionError):
            self._plan()


if __name__ == "__main__":
    unittest.main()
