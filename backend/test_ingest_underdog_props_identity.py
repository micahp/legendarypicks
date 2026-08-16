#!/usr/bin/env python3
"""Identity and idempotency contracts for the Underdog UFC ingest."""
import os
import sqlite3
import tempfile
import unittest


_IMPORT_TMP = tempfile.TemporaryDirectory()
os.environ["LP_DB_PATH"] = os.path.join(_IMPORT_TMP.name, "import-only.db")

import ingest_underdog_props as underdog
import apply_reviewed_ufc_identity as reviewed
import bovada_scraper


def create_schema(path):
    with sqlite3.connect(path) as con:
        con.executescript("""
            CREATE TABLE players(
              id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
              team TEXT, league TEXT NOT NULL
            );
            CREATE TABLE prop_games(
              id INTEGER PRIMARY KEY AUTOINCREMENT, league TEXT NOT NULL,
              date TEXT NOT NULL, home TEXT, away TEXT, espn_event_id TEXT,
              start_time TEXT
            );
            CREATE TABLE props(
              id INTEGER PRIMARY KEY AUTOINCREMENT, game_id INTEGER,
              player_id INTEGER, market TEXT NOT NULL, line REAL NOT NULL,
              side TEXT NOT NULL, source TEXT, captured_at TEXT NOT NULL,
              odds INTEGER, odds_captured_at TEXT
            );
            CREATE TABLE unresolved_players(
              id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
              raw_name TEXT NOT NULL, league TEXT NOT NULL, team TEXT,
              first_seen TEXT NOT NULL, count INTEGER DEFAULT 1
            );
            CREATE TABLE name_alias(
              id INTEGER PRIMARY KEY AUTOINCREMENT, player_id INTEGER NOT NULL,
              alias_norm TEXT NOT NULL
            );
        """)


def board(player_a="Alpha Fighter", player_b="Bravo Fighter", key_a="u-a", key_b="u-b"):
    shared = {
        "source_game_key": "g-1", "date": "2026-08-16",
        "home": player_a, "away": player_b, "start_time": "2026-08-16T01:00:00Z",
        "market": "significant_strikes", "line": 40.5, "odds": -115,
    }
    return [
        dict(shared, source_player_key=key_a, player_name=player_a, side="over"),
        dict(shared, source_player_key=key_b, player_name=player_b, side="under"),
    ]


class UnderdogIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "underdog.db")
        create_schema(self.db_path)
        self.old_db = underdog.DB
        underdog.DB = self.db_path
        self.con = sqlite3.connect(self.db_path)
        self.con.row_factory = sqlite3.Row

    def tearDown(self):
        self.con.close()
        underdog.DB = self.old_db
        self.tmp.cleanup()

    def player(self, name):
        player_id = self.con.execute(
            "INSERT INTO players(name,league) VALUES(?,'ufc')", (name,)
        ).lastrowid
        self.con.commit()
        return player_id

    def scalar(self, sql, params=()):
        return self.con.execute(sql, params).fetchone()[0]

    def test_exact_names_bind_native_ids_and_upsert_without_new_players(self):
        alpha_id = self.player("Alpha Fighter")
        bravo_id = self.player("Bravo Fighter")
        before_players = self.scalar("SELECT COUNT(*) FROM players")

        first = underdog.direct_ingest(board())
        second = underdog.direct_ingest(board())

        self.assertEqual(first["written_props"], 2)
        self.assertEqual(second["written_props"], 2)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM players"), before_players)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM props"), 2)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM prop_games"), 1)
        keys = self.con.execute(
            "SELECT source_player_key,player_id FROM player_source_ids ORDER BY source_player_key"
        ).fetchall()
        self.assertEqual([(row["source_player_key"], row["player_id"]) for row in keys], [
            ("u-a", alpha_id), ("u-b", bravo_id),
        ])
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM prop_game_source_ids"), 1)

    def test_missing_native_id_is_queued_and_entire_fight_is_rejected(self):
        self.player("Alpha Fighter")
        before_players = self.scalar("SELECT COUNT(*) FROM players")

        summary = underdog.direct_ingest(board(player_b="Unknown Fighter", key_b="u-missing"))

        self.assertEqual(summary["written_props"], 0)
        self.assertEqual(summary["skipped_games"], 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM players"), before_players)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM props"), 0)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM prop_games"), 0)
        unresolved = self.con.execute(
            "SELECT source_player_key,raw_name,reason FROM unresolved_players"
        ).fetchone()
        self.assertEqual(
            (unresolved["source_player_key"], unresolved["raw_name"], unresolved["reason"]),
            ("u-missing", "Unknown Fighter", "source_id_not_in_spine"),
        )

    def test_reviewed_alias_can_bind_a_source_id_but_fuzzy_matching_cannot(self):
        kaua_id = self.player("Kaua Fernandes")
        self.player("Jalin Turner")
        self.con.execute(
            "INSERT INTO name_alias(player_id,alias_norm) VALUES(?,?)",
            (kaua_id, underdog.normalize_name("Kaue Fernandes")),
        )
        self.con.commit()

        summary = underdog.direct_ingest(board("Kaue Fernandes", "Jalin Turner"))

        self.assertEqual(summary["written_props"], 2)
        mapped = self.con.execute(
            "SELECT player_id FROM player_source_ids WHERE source_player_key='u-a'"
        ).fetchone()["player_id"]
        self.assertEqual(mapped, kaua_id)

    def test_conflicting_source_key_refuses_to_repoint_a_canonical_fighter(self):
        alpha_id = self.player("Alpha Fighter")
        bravo_id = self.player("Bravo Fighter")
        underdog.ensure_source_identity_schema(self.con)
        underdog.bind_player_source_key(self.con, "u-a", alpha_id, "2026-08-15T00:00:00Z")
        self.con.commit()

        with self.assertRaises(underdog.SourceIdentityConflict):
            underdog.bind_player_source_key(self.con, "u-a", bravo_id, "2026-08-15T00:01:00Z")

    def test_reviewed_identity_corrects_display_name_and_preserves_bovada_alias(self):
        original_id = self.player("Kaua Fernandes")
        turner_id = self.player("Jalin Turner")
        game_id = self.con.execute(
            "INSERT INTO prop_games(league,date,home,away) VALUES('ufc','2026-08-16',?,?)",
            ("Jalin Turner", "Kaua Fernandes"),
        ).lastrowid
        for player_id in (original_id, turner_id):
            self.con.execute(
                "INSERT INTO props(game_id,player_id,market,line,side,source,captured_at) "
                "VALUES(?,?, 'win_by_decision',0.5,'over','bovada','2026-08-15T00:00:00Z')",
                (game_id, player_id),
            )
        self.con.commit()

        reviewed_id = reviewed.apply_review(self.con)
        self.con.commit()

        self.assertEqual(reviewed_id, original_id)
        self.assertEqual(
            self.con.execute("SELECT name FROM players WHERE id=?", (original_id,)).fetchone()["name"],
            "Kauê Fernandes",
        )
        self.assertEqual(
            bovada_scraper._resolve_ufc_player_for_bovada(self.con, "Kaua Fernandes"),
            original_id,
        )
        self.assertEqual(
            self.con.execute("SELECT away FROM prop_games WHERE id=?", (game_id,)).fetchone()["away"],
            "Kauê Fernandes",
        )
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM players"), 2)
        source_key = self.con.execute(
            "SELECT source_player_key FROM player_source_ids WHERE player_id=?", (original_id,)
        ).fetchone()["source_player_key"]
        self.assertEqual(source_key, reviewed.REVIEW["source_player_key"])

        old_path = os.environ["LP_DB_PATH"]
        os.environ["LP_DB_PATH"] = self.db_path
        try:
            bovada_scraper._ufc_direct_ingest([
                {"player_name": "Jalin Turner", "game_desc": "Turner vs Fernandes",
                 "home_team": "Jalin Turner", "away_team": "Kaua Fernandes",
                 "line": 0.5, "side": "over", "market": "win_by_decision",
                 "odds": 100, "start_time": None},
                {"player_name": "Kaua Fernandes", "game_desc": "Turner vs Fernandes",
                 "home_team": "Jalin Turner", "away_team": "Kaua Fernandes",
                 "line": 0.5, "side": "over", "market": "win_by_decision",
                 "odds": 100, "start_time": None},
            ], "2026-08-16")
        finally:
            os.environ["LP_DB_PATH"] = old_path
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM prop_games"), 1)


if __name__ == "__main__":
    unittest.main()
