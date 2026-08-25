import sqlite3

import pytest

from cleanup_empty_mlb_team_game_stats import cleanup


def _database():
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE team_game_stats(
          league TEXT, game_id TEXT, captured_at TEXT, team_abbrev TEXT,
          home_away TEXT, hits INTEGER, stats TEXT, run_id TEXT, source TEXT
        );
        INSERT INTO team_game_stats VALUES
          ('mlb','1','now','NYY','home',NULL,NULL,NULL,NULL),
          ('mlb','1','now','BOS','away',NULL,'{}','',''),
          ('nba','2','now','NYK','home',42,'{"points":42}','run','espn');
    """)
    return con


def test_cleanup_is_dry_by_default_and_apply_removes_only_empty_mlb_rows():
    con = _database()
    assert cleanup(con) == {
        "mlb_rows": 2, "empty_rows": 2, "nonempty_rows": 0, "deleted": 0,
    }
    assert con.execute("SELECT COUNT(*) FROM team_game_stats").fetchone()[0] == 3
    assert cleanup(con, apply=True)["deleted"] == 2
    assert [tuple(row) for row in con.execute(
        "SELECT league,game_id,hits FROM team_game_stats"
    )] == [("nba", "2", 42)]


def test_cleanup_refuses_the_whole_operation_when_any_mlb_value_exists():
    con = _database()
    con.execute(
        "UPDATE team_game_stats SET hits=7 WHERE league='mlb' AND team_abbrev='NYY'"
    )
    with pytest.raises(ValueError, match="nonempty rows exist"):
        cleanup(con, apply=True)
    assert con.execute(
        "SELECT COUNT(*) FROM team_game_stats WHERE league='mlb'"
    ).fetchone()[0] == 2
