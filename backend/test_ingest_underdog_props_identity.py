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
from prop_game_merge import dangling_source_mappings, fold_prop_game


def create_schema(path):
    with sqlite3.connect(path) as con:
        con.executescript("""
            CREATE TABLE players(
              id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
              team TEXT, league TEXT NOT NULL, espn_id TEXT, active INTEGER DEFAULT 1,
              updated_at TEXT
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

    def test_a_fight_with_a_line_for_only_one_fighter_is_ingested(self):
        alpha_id = self.player("Alpha Fighter")

        summary = underdog.direct_ingest(board()[:1])

        self.assertEqual(summary["written_props"], 1)
        self.assertEqual(summary["eligible_games"], 1)
        self.assertEqual(
            self.con.execute("SELECT player_id FROM props").fetchone()["player_id"],
            alpha_id,
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

        # Another module in a full-suite run restores LP_DB_PATH to *absent*, so
        # reading it unconditionally raises KeyError and this test's result then
        # depends on collection order rather than on the code under test.
        old_path = os.environ.get("LP_DB_PATH")
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
            if old_path is None:
                os.environ.pop("LP_DB_PATH", None)
            else:
                os.environ["LP_DB_PATH"] = old_path
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM prop_games"), 1)

    def test_august_22_reviewed_identities_bind_all_four_rejected_fights(self):
        current_card_reviews = reviewed.REVIEWS[1:]
        player_ids = {}
        for review in current_card_reviews:
            player_ids[review["canonical_name"]] = self.player(review["existing_name"])

        applied = reviewed.apply_reviews(self.con, current_card_reviews)
        self.con.commit()

        self.assertEqual(applied, [player_ids[review["canonical_name"]] for review in current_card_reviews])
        for review in current_card_reviews:
            player_id = player_ids[review["canonical_name"]]
            self.assertEqual(
                self.con.execute("SELECT name FROM players WHERE id=?", (player_id,)).fetchone()["name"],
                review["canonical_name"],
            )
            self.assertEqual(
                self.con.execute(
                    "SELECT player_id FROM player_source_ids WHERE source='underdog' "
                    "AND league='ufc' AND source_player_key=?",
                    (review["source_player_key"],),
                ).fetchone()["player_id"],
                player_id,
            )

    def test_reviewed_espn_identity_can_publish_a_missing_current_card_fighter(self):
        review = next(item for item in reviewed.REVIEWS if item.get("espn_id"))

        player_id = reviewed.apply_review(self.con, review)
        self.con.commit()

        row = self.con.execute(
            "SELECT name,league,espn_id FROM players WHERE id=?", (player_id,)
        ).fetchone()
        self.assertEqual(
            (row["name"], row["league"], row["espn_id"]),
            (review["canonical_name"], "ufc", review["espn_id"]),
        )
        self.assertEqual(
            self.con.execute(
                "SELECT player_id FROM player_source_ids WHERE source='underdog' "
                "AND league='ufc' AND source_player_key=?",
                (review["source_player_key"],),
            ).fetchone()["player_id"],
            player_id,
        )


class FoldedGameKeepsItsSourceMapping(unittest.TestCase):
    """A fold moves the mapping too, and a mapping left behind self-heals.

    Written 2026-08-19, after the UFC timer failed every 30 minutes for two hours
    with `source game key 291703 conflicts with canonical fighters`. The fighters
    matched fine. Game 1235 had been folded into 1234 by a pass that repointed
    `props` and forgot `prop_game_source_ids`, so the guard compared the board
    against a row that no longer existed and read absence as a changed identity.
    """

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

    def test_fold_carries_the_source_mapping_onto_the_surviving_game(self):
        self.player("Alpha Fighter")
        self.player("Bravo Fighter")
        underdog.direct_ingest(board())
        loser = self.scalar("SELECT game_id FROM prop_game_source_ids WHERE source_game_key='g-1'")
        winner = self.con.execute(
            "INSERT INTO prop_games(league,date,home,away) VALUES('ufc','2026-08-16','A','B')"
        ).lastrowid
        self.con.commit()

        self.assertEqual(fold_prop_game(self.con, loser, winner), winner)
        self.con.commit()

        self.assertEqual(
            self.scalar("SELECT game_id FROM prop_game_source_ids WHERE source_game_key='g-1'"),
            winner,
        )
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM props WHERE game_id=?", (winner,)), 2)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM prop_games WHERE id=?", (loser,)), 0)
        self.assertEqual(len(dangling_source_mappings(self.con)), 0)

    def test_a_mapping_left_pointing_at_a_deleted_game_re_resolves_instead_of_raising(self):
        self.player("Alpha Fighter")
        self.player("Bravo Fighter")
        underdog.direct_ingest(board())
        stranded = self.scalar("SELECT game_id FROM prop_game_source_ids WHERE source_game_key='g-1'")
        survivor = self.con.execute(
            "INSERT INTO prop_games(league,date,home,away) VALUES('ufc','2026-08-16','A','B')"
        ).lastrowid
        # The old fold, reproduced exactly: props move, the mapping is forgotten.
        self.con.execute("UPDATE props SET game_id=? WHERE game_id=?", (survivor, stranded))
        self.con.execute("DELETE FROM prop_games WHERE id=?", (stranded,))
        self.con.commit()
        self.assertEqual(len(dangling_source_mappings(self.con)), 1)

        summary = underdog.direct_ingest(board())

        self.assertEqual(summary["written_props"], 2)
        self.assertEqual(
            self.scalar("SELECT game_id FROM prop_game_source_ids WHERE source_game_key='g-1'"),
            survivor,
        )
        self.assertEqual(len(dangling_source_mappings(self.con)), 0)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM prop_games"), 1)

    def test_a_publisher_one_day_off_resolves_onto_the_existing_fight(self):
        """Underdog files Wint vs Chatman on 08-22, ESPN on 08-23. One fight."""
        alpha_id = self.player("Alpha Fighter")
        bravo_id = self.player("Bravo Fighter")
        espn_game = self.con.execute(
            "INSERT INTO prop_games(league,date,home,away,espn_event_id) "
            "VALUES('ufc','2026-08-17','Alpha Fighter','Bravo Fighter','401911625')"
        ).lastrowid
        for player_id in (alpha_id, bravo_id):
            self.con.execute(
                "INSERT INTO props(game_id,player_id,market,line,side,source,captured_at) "
                "VALUES(?,?,'win_by_decision',0.5,'over','bovada','2026-08-15T00:00:00Z')",
                (espn_game, player_id),
            )
        self.con.commit()

        underdog.direct_ingest(board())  # board() dates the same fight 2026-08-16

        self.assertEqual(self.scalar("SELECT COUNT(*) FROM prop_games"), 1)
        self.assertEqual(
            self.scalar("SELECT game_id FROM prop_game_source_ids WHERE source_game_key='g-1'"),
            espn_game,
        )

    def test_a_live_game_with_different_fighters_still_refuses(self):
        self.player("Alpha Fighter")
        self.player("Bravo Fighter")
        underdog.direct_ingest(board())
        other = self.con.execute(
            "INSERT INTO prop_games(league,date,home,away) VALUES('ufc','2026-08-16','X','Y')"
        ).lastrowid
        self.con.execute(
            "UPDATE prop_game_source_ids SET game_id=? WHERE source_game_key='g-1'", (other,)
        )
        self.con.commit()

        with self.assertRaises(underdog.SourceIdentityConflict):
            underdog.direct_ingest(board())


if __name__ == "__main__":
    unittest.main()
