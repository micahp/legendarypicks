import datetime as dt
import sqlite3

import settle_props


def _database(path):
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE prop_games(
          id INTEGER PRIMARY KEY, league TEXT, home TEXT, away TEXT, date TEXT,
          espn_event_id TEXT, final_home REAL, final_away REAL
        );
        CREATE TABLE props(id INTEGER PRIMARY KEY, game_id INTEGER);
        CREATE TABLE prop_results(
          prop_id INTEGER PRIMARY KEY, actual_value REAL, hit INTEGER,
          settled_at TEXT
        );
    """)
    today = dt.date.today()
    con.executemany(
        "INSERT INTO prop_games VALUES(?,?,?,?,?,?,?,?)",
        [
            (1, "nfl", "Past Home", "Past Away",
             str(today - dt.timedelta(days=1)), "past", 1, 0),
            (2, "nfl", "Future Home", "Future Away",
             str(today + dt.timedelta(days=7)), "future", None, None),
        ],
    )
    con.executemany("INSERT INTO props VALUES(?,?)", [(1, 1), (2, 2)])
    con.commit()
    con.close()


def test_default_run_never_spends_a_request_on_future_games(tmp_path, monkeypatch):
    path = tmp_path / "settlement.db"
    _database(path)
    calls = []
    monkeypatch.setattr(settle_props, "DB", str(path))
    monkeypatch.setattr(
        settle_props, "settle_game",
        lambda _con, game_id: calls.append(game_id) or {
            "settled": 1, "void": 0, "unmappable": 0,
            "pending": 0, "errors": 0,
        },
    )

    settle_props._main(league="nfl")

    assert calls == [1]


def test_max_games_bounds_one_process_working_set(tmp_path, monkeypatch):
    path = tmp_path / "settlement.db"
    _database(path)
    con = sqlite3.connect(path)
    yesterday = str(dt.date.today() - dt.timedelta(days=1))
    con.execute(
        "INSERT INTO prop_games VALUES(3,'nfl','Other Home','Other Away',"
        "?,'other',1,0)",
        (yesterday,),
    )
    con.execute("INSERT INTO props VALUES(3,3)")
    con.commit()
    con.close()
    calls = []
    monkeypatch.setattr(settle_props, "DB", str(path))
    monkeypatch.setattr(
        settle_props, "settle_game",
        lambda _con, game_id: calls.append(game_id) or {
            "settled": 1, "void": 0, "unmappable": 0,
            "pending": 0, "errors": 0,
        },
    )

    settle_props._main(league="nfl", max_games=1)

    assert len(calls) == 1
