import json
import sqlite3

import settlement
from ingest_wc_logs import WCPlayerResolver, _roster_players
from repair_world_cup_results import repair


def _database():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE prop_games(
          id INTEGER PRIMARY KEY, league TEXT, home TEXT, away TEXT, date TEXT,
          espn_event_id TEXT, final_home INTEGER, final_away INTEGER,
          start_time TEXT
        );
        CREATE TABLE players(
          id INTEGER PRIMARY KEY, name TEXT, team TEXT, espn_id TEXT
        );
        CREATE TABLE props(
          id INTEGER PRIMARY KEY, game_id INTEGER, market TEXT, line REAL,
          side TEXT, player_id INTEGER
        );
        CREATE TABLE prop_results(
          prop_id INTEGER PRIMARY KEY, actual_value REAL, hit INTEGER,
          settled_at TEXT
        );
        CREATE TABLE player_game_logs(
          id INTEGER PRIMARY KEY, player_id INTEGER, league TEXT, game_id TEXT,
          stats TEXT
        );
        INSERT INTO prop_games VALUES
          (1, 'wc', 'France', 'England', '2026-07-18', '760516',
           NULL, NULL, '2026-07-18T19:00:00Z');
        INSERT INTO players VALUES
          (10, 'Kylian Mbappé', 'FRA', '231388'),
          (11, 'Unused Reserve', 'ENG', '999');
        INSERT INTO props VALUES
          (1, 1, 'goals', 0.5, 'over', 10),
          (2, 1, 'shots_on_target', 4.0, 'over', 10),
          (3, 1, 'shots', 1.0, 'over', 11);
        INSERT INTO prop_results VALUES
          (1, NULL, NULL, '2026-07-20T00:00:00Z'),
          (2, NULL, NULL, '2026-07-20T00:00:00Z'),
          (3, NULL, NULL, '2026-07-20T00:00:00Z');
    """)
    con.execute(
        "INSERT INTO player_game_logs VALUES (1,10,'wc','760516',?)",
        (json.dumps({"goals": 2, "assists": 1, "shots": 8, "sot": 4}),),
    )
    con.commit()
    return con


def test_wc_repair_grades_logs_and_keeps_missing_logs_unresolved():
    con = _database()
    dry = repair(con, apply=False)
    assert dry == {
        "legacy_null_rows": 3, "gradeable": 2, "retained_voids": 0,
        "other_unresolved": 1, "updated": 0, "errors": 0,
    }
    assert con.execute(
        "SELECT COUNT(*) FROM prop_results WHERE actual_value IS NOT NULL"
    ).fetchone()[0] == 0

    applied = repair(con, apply=True)
    assert applied["updated"] == 2
    rows = con.execute(
        "SELECT prop_id,actual_value,hit FROM prop_results ORDER BY prop_id"
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        (1, 2.0, 1), (2, 4.0, None), (3, None, None),
    ]


def test_wc_normal_settlement_uses_completed_logs_without_live_data():
    con = _database()
    con.execute("DELETE FROM prop_results")
    con.commit()
    result = settlement.settle_game(con, 1)
    assert result == {
        "settled": 2, "void": 0, "unmappable": 0, "pending": 1, "errors": 0,
    }


def test_wc_explicit_dnp_log_persists_an_evidence_backed_void():
    con = _database()
    con.execute("DELETE FROM prop_results")
    con.execute(
        "INSERT INTO player_game_logs VALUES (2,11,'wc','760516',?)",
        (json.dumps({"did_not_play": 1}),),
    )
    con.commit()

    result = settlement.settle_game(con, 1)

    assert result == {
        "settled": 2, "void": 1, "unmappable": 0, "pending": 0, "errors": 0,
    }
    assert tuple(con.execute(
        "SELECT actual_value,hit FROM prop_results WHERE prop_id=3"
    ).fetchone()) == (None, None)


def test_wc_ingest_retains_publisher_appearance_zero_as_dnp_evidence():
    summary = {"rosters": [{"team": {"abbreviation": "ENG"},
                             "homeAway": "away", "roster": [{
        "athlete": {"id": "999", "displayName": "Unused Reserve"},
        "stats": [{"name": "appearances", "value": 0}],
    }]}]}
    assert list(_roster_players(summary)) == [
        ("999", "Unused Reserve", "ENG", "away", {"did_not_play": 1})
    ]


def test_wc_resolver_prefers_the_stable_publisher_identity():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute(
        "CREATE TABLE players(id INTEGER,name TEXT,team TEXT,league TEXT,espn_id TEXT)"
    )
    con.execute(
        "INSERT INTO players VALUES(10,'Kylian Mbappé','FRA','wc','231388')"
    )
    resolver = WCPlayerResolver(con)
    assert resolver.resolve("Publisher Renamed Him", "FRA", "231388") == 10
