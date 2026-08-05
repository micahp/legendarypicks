#!/usr/bin/env python3
"""Each repair rule deletes only rows no reader can reach, and says why.

The repair runs against the LEGACY table -- that is its whole purpose -- so the
fixture builds the name-keyed shape with a nullable `player_id`, not
`PLAYER_STATS_TABLE_SQL`.
"""

import os
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import repair_player_stats_identity as repair  # noqa: E402

LEGACY_SCHEMA = """
CREATE TABLE players(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, team TEXT, league TEXT NOT NULL
);
CREATE TABLE player_stats(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  player_id INTEGER,
  player_name TEXT NOT NULL,
  name_norm TEXT,
  league TEXT NOT NULL,
  team TEXT,
  stat_type TEXT DEFAULT 'batting',
  season INTEGER,
  games INTEGER,
  goals INTEGER,
  pts REAL,
  source TEXT,
  UNIQUE(name_norm, league, season, stat_type)
);
"""


def insert(con, **row):
    row.setdefault("player_name", "Someone")
    row.setdefault("name_norm", row["player_name"].lower())
    row.setdefault("team", "TST")
    row.setdefault("games", 10)
    columns = ",".join(row)
    con.execute(
        f"INSERT INTO player_stats({columns}) "
        f"VALUES ({','.join('?' for _ in row)})",
        list(row.values()),
    )


class RepairRuleTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(
            prefix="repair-identity-", suffix=".db", delete=False
        )
        self.path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))
        self.con = sqlite3.connect(self.path)
        self.con.row_factory = sqlite3.Row
        self.addCleanup(self.con.close)
        self.con.executescript(LEGACY_SCHEMA)
        self.con.executemany(
            "INSERT INTO players(id,name,team,league) VALUES(?,?,?,?)",
            [
                (1, "Kept Skater", "WPG", "nhl"),
                (2, "Moved Skater", "DET", "nhl"),
                (3, "Kept Batter", "ATH", "mlb"),
            ],
        )
        self.con.commit()

    def rows(self):
        return [
            tuple(row)
            for row in self.con.execute(
                """SELECT player_id,league,season,stat_type,source,games
                   FROM player_stats ORDER BY league,season,player_id"""
            )
        ]

    def run_repair(self):
        return repair.main(["--db", self.path, "--apply"])

    def test_non_canonical_stat_type_is_unreachable_and_goes(self):
        """`nba/batting` is a retired rollup's output; the readers pin `season`."""
        insert(self.con, player_id=1, league="nba", season=2026,
               stat_type="batting", source="derived", player_name="Rollup Ghost")
        insert(self.con, player_id=1, league="nba", season=2026,
               stat_type="season", source="espn_web", player_name="Kept Guard")
        self.con.commit()

        self.assertEqual(self.run_repair(), 0)
        self.assertEqual(self.rows(), [(1, "nba", 2026, "season", "espn_web", 10)])

    def test_a_source_that_does_not_own_the_season_goes(self):
        """`mlb_statsapi` competes with statcast, and the predicate pins statcast."""
        insert(self.con, player_id=3, league="mlb", season=2026,
               stat_type="batting", source="mlb_statsapi", player_name="Competing Row")
        insert(self.con, player_id=3, league="mlb", season=2026,
               stat_type="batting", source="statcast", player_name="Kept Batter")
        self.con.commit()

        self.assertEqual(self.run_repair(), 0)
        self.assertEqual(
            self.rows(), [(3, "mlb", 2026, "batting", "statcast", 10)]
        )

    def test_a_row_with_no_player_is_queued_before_it_is_deleted(self):
        """Absence has to be recorded somewhere, or it reads as never happened."""
        insert(self.con, player_id=None, league="nhl", season=2026,
               stat_type="season", source="nhle.com", player_name="CJ Suess",
               team="WPG", games=2)
        insert(self.con, player_id=1, league="nhl", season=2026,
               stat_type="season", source="nhle.com", player_name="Kept Skater")
        self.con.commit()

        self.assertEqual(self.run_repair(), 0)
        self.assertEqual(self.rows(), [(1, "nhl", 2026, "season", "nhle.com", 10)])
        queued = self.con.execute(
            """SELECT raw_name,team,reason FROM unresolved_players
               WHERE league='nhl'"""
        ).fetchall()
        self.assertEqual(
            [tuple(row) for row in queued],
            [("CJ Suess", "WPG", "stranded_stats_row_without_identity")],
        )

    def test_legacy_season_key_duplicates_go_and_orphans_move(self):
        """The 8-digit row loses -- `publish_player_stats` can never reach it.

        A legacy row whose player has no ESPN-keyed row is the 84 on prod that
        no later ingest saw again (Jonathan Toews' 82 games). Deleting those
        would drop a real season, so they are re-keyed instead.
        """
        insert(self.con, player_id=1, league="nhl", season=20252026,
               stat_type="season", source="nhle.com", player_name="Kept Skater",
               games=40)
        insert(self.con, player_id=1, league="nhl", season=2026,
               stat_type="season", source="nhle.com", player_name="Kept Skater 2026",
               games=82)
        insert(self.con, player_id=2, league="nhl", season=20252026,
               stat_type="season", source="nhle.com", player_name="Moved Skater",
               games=72)
        self.con.commit()

        self.assertEqual(self.run_repair(), 0)
        self.assertEqual(
            self.rows(),
            [
                (1, "nhl", 2026, "season", "nhle.com", 82),
                (2, "nhl", 2026, "season", "nhle.com", 72),
            ],
        )

    def test_duplicate_owner_keeps_the_row_the_writer_would_produce(self):
        """Both shapes settle the same way, and the loser is never the fresh row.

        `mlbam_680869` beside `kept batter` is the placeholder shape (71 of these
        on prod); `k pt batter` beside `kept batter` is the normalizer shape (157
        on dev, from an NFKD/ascii-fold that changed underneath written rows).
        """
        for name_norm, games in (
            ("mlbam_680869", 40), ("k pt batter", 41), ("kept batter", 66),
        ):
            insert(self.con, player_id=3, league="mlb", season=2026,
                   stat_type="batting", source="statcast",
                   player_name="Kept Batter", name_norm=name_norm, games=games)
        self.con.commit()

        self.assertEqual(self.run_repair(), 0)
        self.assertEqual(
            [
                tuple(row)
                for row in self.con.execute(
                    "SELECT name_norm,games FROM player_stats"
                )
            ],
            [("kept batter", 66)],
        )

    def test_a_duplicate_group_the_rule_does_not_explain_is_refused(self):
        """No survivor is what the writer would produce, so there is no rule."""
        for name_norm in ("mlbam_1", "mlbam_2"):
            insert(self.con, player_id=3, league="mlb", season=2026,
                   stat_type="batting", source="statcast",
                   player_name="Kept Batter", name_norm=name_norm)
        self.con.commit()

        with self.assertRaisesRegex(RuntimeError, "REFUSING.*duplicate group"):
            self.run_repair()
        self.assertEqual(
            self.con.execute("SELECT COUNT(*) FROM player_stats").fetchone()[0], 2
        )

    def test_a_drifted_display_name_is_resynced_not_deleted(self):
        """`player_name` is a copy of `players.name`; the truth is not in doubt."""
        insert(self.con, player_id=3, league="mlb", season=2026,
               stat_type="batting", source="statcast",
               player_name="mlbam_699127", name_norm="mlbam_699127", games=12)
        self.con.commit()

        self.assertEqual(self.run_repair(), 0)
        self.assertEqual(
            [
                tuple(row)
                for row in self.con.execute(
                    "SELECT player_name,name_norm,games FROM player_stats"
                )
            ],
            [("Kept Batter", "kept batter", 12)],
        )

    def test_it_rolls_back_when_a_served_player_would_disappear(self):
        """The safety net, proved by breaking R4 rather than by trusting it.

        `_split_legacy` is what keeps the 84 orphans alive. Force it to treat
        every legacy row as a deletable duplicate and the served population
        shrinks -- which is exactly the condition the repair refuses to commit.
        """
        insert(self.con, player_id=2, league="nhl", season=20252026,
               stat_type="season", source="nhle.com", player_name="Moved Skater",
               games=72)
        self.con.commit()

        original = repair._split_legacy
        repair._split_legacy = lambda matched, rekey, survivors: ([], matched)
        self.addCleanup(lambda: setattr(repair, "_split_legacy", original))

        with self.assertRaisesRegex(RuntimeError, "REFUSING"):
            self.run_repair()
        self.assertEqual(
            self.rows(), [(2, "nhl", 20252026, "season", "nhle.com", 72)]
        )


if __name__ == "__main__":
    unittest.main()
