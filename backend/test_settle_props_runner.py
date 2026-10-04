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


def _aged_database(path, age_hours):
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE prop_games(
          id INTEGER PRIMARY KEY, league TEXT, home TEXT, away TEXT, date TEXT,
          espn_event_id TEXT, final_home REAL, final_away REAL, start_time TEXT
        );
        CREATE TABLE props(id INTEGER PRIMARY KEY, game_id INTEGER);
        CREATE TABLE prop_results(
          prop_id INTEGER PRIMARY KEY, actual_value REAL, hit INTEGER,
          settled_at TEXT
        );
    """)
    start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=age_hours)
    con.execute(
        "INSERT INTO prop_games VALUES(1,'nfl','Home','Away',?,?,1,0,?)",
        (start.date().isoformat(), "event-1", start.isoformat()),
    )
    con.execute("INSERT INTO props VALUES(1,1)")
    con.commit()
    con.close()


def _result():
    return {"settled": 1, "void": 0, "unmappable": 0,
            "pending": 0, "errors": 0}


def test_game_71_hours_old_is_attempted(tmp_path, monkeypatch):
    path = tmp_path / "inside.db"
    _aged_database(path, 71)
    calls = []
    monkeypatch.setattr(settle_props, "DB", str(path))
    monkeypatch.setattr(
        settle_props, "settle_game",
        lambda _con, game_id: calls.append(game_id) or _result(),
    )

    settle_props._main(league="nfl")

    assert calls == [1]


def test_game_73_hours_old_is_flagged_manual_once(tmp_path, monkeypatch):
    path = tmp_path / "expired.db"
    _aged_database(path, 73)
    calls = []
    monkeypatch.setattr(settle_props, "DB", str(path))
    monkeypatch.setattr(
        settle_props, "settle_game",
        lambda _con, game_id: calls.append(game_id) or _result(),
    )

    settle_props._main(league="nfl")
    settle_props._main(league="nfl")

    con = sqlite3.connect(path)
    rows = con.execute(
        "SELECT stage,terminal,reason,actual_value,hit "
        "FROM settlement_attempts WHERE prop_id=1"
    ).fetchall()
    con.close()
    assert calls == []
    assert rows == [("manual", "manual", "window_expired:none", None, None)]


def test_window_hours_zero_attempts_expired_game(tmp_path, monkeypatch):
    path = tmp_path / "backfill.db"
    _aged_database(path, 73)
    calls = []
    monkeypatch.setattr(settle_props, "DB", str(path))
    monkeypatch.setattr(
        settle_props, "settle_game",
        lambda _con, game_id: calls.append(game_id) or _result(),
    )

    settle_props._main(league="nfl", window_hours=0)

    assert calls == [1]
