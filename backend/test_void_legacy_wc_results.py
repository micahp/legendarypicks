import sqlite3

import void_legacy_wc_results as repair


def test_plan_and_apply_touch_only_null_world_cup_results(tmp_path):
    path = tmp_path / "picks.db"
    with sqlite3.connect(path) as c:
        c.executescript("""
          CREATE TABLE prop_games(id INTEGER PRIMARY KEY, league TEXT);
          CREATE TABLE props(id INTEGER PRIMARY KEY, game_id INTEGER);
          CREATE TABLE prop_results(prop_id INTEGER PRIMARY KEY, actual_value REAL, hit INTEGER, settled_at TEXT);
          INSERT INTO prop_games VALUES(1,'wc'),(2,'nfl');
          INSERT INTO props VALUES(11,1),(12,1),(13,2);
          INSERT INTO prop_results VALUES(11,NULL,NULL,'old'),(12,2,1,'good'),(13,NULL,NULL,'other');
        """)
    assert repair.plan(str(path))["candidates"] == 1
    out = repair.apply(str(path))
    assert out["candidates"] == out["voids"] == 1
    with sqlite3.connect(path) as c:
        assert c.execute("SELECT prop_id,reason FROM prop_voids").fetchall() == [(11, repair.VOID_REASON)]
        assert c.execute("SELECT prop_id FROM prop_results ORDER BY prop_id").fetchall() == [(12,), (13,)]
