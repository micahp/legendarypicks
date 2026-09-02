#!/usr/bin/env python3
"""Fixture tests for the MLS RotoWire → canonical published-props boundary."""
import os
import sqlite3
import tempfile
import unittest


_IMPORT_TMP = tempfile.TemporaryDirectory()
os.environ["LP_DB_PATH"] = os.path.join(_IMPORT_TMP.name, "import-only.db")

import ingest_rotowire_mls_props as rotowire


def create_schema(path):
    with sqlite3.connect(path) as con:
        con.executescript("""
            CREATE TABLE players(
              id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
              team TEXT, league TEXT NOT NULL, position TEXT
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


def source_board(extra_player=False, unsupported=False):
    entities = [
        {"entityID": 101, "eventID": 77, "sport": "Soccer", "name": "Alex Forward",
         "team": "Austin FC", "pos": "F", "link": "https://www.rotowire.com/soccer/player/alex-forward-1001"},
        {"entityID": 102, "eventID": 77, "sport": "Soccer", "name": "Drew Keeper",
         "team": "FC Dallas", "pos": "G", "link": "https://www.rotowire.com/soccer/player/drew-keeper-1002"},
    ]
    props = [
        {"marketID": 1, "entities": [101], "lines": [
            {"book": "prizepicks", "line": 2.5, "over": "More", "under": "Less"},
        ]},
        {"marketID": 2, "entities": [102], "lines": [
            {"book": "prizepicks", "line": 3.5, "over": "More", "under": "Less"},
        ]},
    ]
    if extra_player:
        entities.append({"entityID": 103, "eventID": 77, "sport": "Soccer", "name": "Missing Mid",
                         "team": "Austin FC", "pos": "M", "link": "https://www.rotowire.com/soccer/player/missing-mid-1003"})
        props.append({"marketID": 1, "entities": [103], "lines": [
            {"book": "prizepicks", "line": 1.5, "over": "More", "under": "Less"},
        ]})
    if unsupported:
        props.append({"marketID": 3, "entities": [101], "lines": [
            {"book": "prizepicks", "line": 1.5, "over": "More", "under": "Less"},
        ]})
    return {
        "markets": [{"marketID": 1, "marketName": "Shots"}, {"marketID": 2, "marketName": "Saves"},
                    {"marketID": 3, "marketName": "Chances Created"}],
        "entities": entities,
        "events": [{"eventID": 77, "homeTeam": "Austin FC", "awayTeam": "FC Dallas",
                    "eventTime": 1786926600}],  # 2026-08-16T22:30:00Z
        "props": props,
    }


FIXTURE = [{
    "game_id": "401", "date": "2026-08-17T00:30:00Z",
    "home": {"abbrev": "ATX", "name": "Austin FC"},
    "away": {"abbrev": "DAL", "name": "FC Dallas"},
}]


class RotoWireMlsPublisherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "rotowire.db")
        create_schema(self.db_path)
        self.old_db = rotowire.DB
        rotowire.DB = self.db_path
        self.con = sqlite3.connect(self.db_path)
        self.con.row_factory = sqlite3.Row

    def tearDown(self):
        self.con.close()
        rotowire.DB = self.old_db
        self.tmp.cleanup()

    def player(self, name, team, position):
        player_id = self.con.execute(
            "INSERT INTO players(name,team,league,position) VALUES(?,?,?,?)",
            (name, team, "mls", position),
        ).lastrowid
        self.con.commit()
        return player_id

    def scalar(self, sql, params=()):
        return self.con.execute(sql, params).fetchone()[0]

    def parsed(self, **kwargs):
        events, counts = rotowire.parse_board(source_board(**kwargs))
        self.assertEqual(len(events), 1)
        return events, counts

    def test_exact_fixture_and_source_ids_publish_thresholds_without_prices(self):
        alex_id = self.player("Alex Forward", "ATX", "F")
        drew_id = self.player("Drew Keeper", "DAL", "G")
        events, _ = self.parsed()

        first = rotowire.direct_ingest(events, FIXTURE)
        second = rotowire.direct_ingest(events, FIXTURE)

        self.assertEqual(first["written_props"], 4)
        self.assertEqual(second["written_props"], 4)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM players"), 2)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM prop_games"), 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM props"), 4)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM props WHERE odds IS NOT NULL"), 0)
        mappings = self.con.execute(
            "SELECT source_player_key,player_id FROM player_source_ids ORDER BY source_player_key"
        ).fetchall()
        self.assertEqual([(row["source_player_key"], row["player_id"]) for row in mappings], [
            ("rotowire-profile:1001", alex_id), ("rotowire-profile:1002", drew_id),
        ])
        self.assertEqual(self.scalar("SELECT espn_event_id FROM prop_games"), "401")

    def test_missing_spine_identity_rejects_the_entire_mls_fixture(self):
        self.player("Alex Forward", "ATX", "F")
        self.player("Drew Keeper", "DAL", "G")
        events, _ = self.parsed(extra_player=True)

        summary = rotowire.direct_ingest(events, FIXTURE)

        self.assertEqual(summary["written_props"], 0)
        self.assertEqual(summary["rejected_event_count"], 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM prop_games"), 0)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM props"), 0)
        unresolved = self.con.execute(
            "SELECT source_player_key,raw_name,reason FROM unresolved_players"
        ).fetchone()
        self.assertEqual(
            (unresolved["source_player_key"], unresolved["raw_name"], unresolved["reason"]),
            ("rotowire-profile:1003", "Missing Mid", "source_id_not_in_spine"),
        )

    def test_non_matching_fixture_writes_no_mls_rows(self):
        self.player("Alex Forward", "ATX", "F")
        self.player("Drew Keeper", "DAL", "G")
        events, _ = self.parsed()
        no_match = [dict(FIXTURE[0], date="2026-08-17T00:31:00Z")]

        summary = rotowire.direct_ingest(events, no_match)

        self.assertEqual(summary["candidate_event_count"], 0)
        self.assertEqual(summary["written_props"], 0)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM prop_games"), 0)

    def test_new_source_market_is_counted_but_not_published_until_mapped(self):
        events, counts = self.parsed(unsupported=True)

        self.assertEqual(len(events[0]["props"]), 2)
        self.assertEqual(counts["unsupported_props"], 1)
        self.assertEqual(counts["market:shots"], 1)

    def test_conflicting_source_key_refuses_to_repoint_player(self):
        alex_id = self.player("Alex Forward", "ATX", "F")
        drew_id = self.player("Drew Keeper", "DAL", "G")
        rotowire.ensure_source_identity_schema(self.con)
        rotowire.bind_player_source_key(self.con, "rotowire-profile:1001", alex_id, "2026-08-15T00:00:00Z")
        self.con.commit()

        with self.assertRaises(rotowire.SourceIdentityConflict):
            rotowire.bind_player_source_key(self.con, "rotowire-profile:1001", drew_id, "2026-08-15T00:01:00Z")
