import sqlite3

import espn_client
import settlement


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
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          player_id INTEGER, league TEXT, season INTEGER, game_no TEXT,
          game_id TEXT, game_date TEXT, team TEXT, opponent TEXT,
          home_away TEXT, stats TEXT NOT NULL, source TEXT,
          source_player_key TEXT, ingested_at TEXT, game_type TEXT,
          UNIQUE(league, source_player_key, season, game_no)
        );
        CREATE TABLE settlement_attempts(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          prop_id INTEGER NOT NULL,
          game_id INTEGER NOT NULL,
          attempted_at TEXT NOT NULL,
          stage TEXT NOT NULL,
          terminal TEXT NOT NULL,
          reason TEXT,
          actual_value REAL,
          hit INTEGER
        );
        INSERT INTO prop_games VALUES
          (1, 'ncaaf', 'NCSU', 'UNC', '2026-08-29', '401858202', 21, 17,
           '2026-08-29T19:30:00Z');
        INSERT INTO players VALUES
          (10, 'College Quarterback', 'NCSU', '1001'),
          (11, 'College Running Back', 'NCSU', '1002'),
          (12, 'College Kicker', 'NCSU', '1003'),
          (13, 'Zero Receiver', 'NCSU', '1004'),
          (14, 'Unproven Bench Player', 'NCSU', '1005');
        INSERT INTO props VALUES
          (1, 1, 'pass_attempts', 24.5, 'over', 10),
          (2, 1, 'pass_completions', 13.5, 'over', 10),
          (3, 1, 'passing_yards', 249.5, 'over', 10),
          (4, 1, 'passing_touchdowns', 1.5, 'over', 10),
          (5, 1, 'interceptions_thrown', 0.5, 'over', 10),
          (6, 1, 'rushing_yards', 19.5, 'over', 10),
          (7, 1, 'rushing_touchdowns', 0.5, 'over', 10),
          (8, 1, 'passing_rushing_yards', 269.5, 'over', 10),
          (9, 1, 'receiving_yards', 29.5, 'over', 11),
          (10, 1, 'receptions', 2.5, 'over', 11),
          (11, 1, 'rush_attempts', 9.5, 'over', 11),
          (12, 1, 'rushing_receiving_yards', 89.5, 'over', 11),
          (13, 1, 'rushing_receiving_touchdowns', 1.5, 'over', 11),
          (14, 1, 'total_touchdowns', 1.5, 'over', 11),
          (15, 1, 'field_goals_made', 1.5, 'over', 12),
          (16, 1, 'extra_points_made', 2.5, 'over', 12),
          (17, 1, 'kicking_points', 8.5, 'over', 12),
          (18, 1, 'receiving_yards', 0.5, 'under', 13),
          (19, 1, 'receiving_yards', 0.5, 'under', 14);
    """)
    return con


def _cfbd_line(espn_id, stats, player_id=None):
    return (player_id, "ncaaf", 2026, "401858202", "401858202", "2026-08-29",
            "NCSU", "UNC", "home", stats, "cfbd", espn_id, None, "REG")


def _athlete(espn_id, name, stats):
    return {"athlete": {"id": espn_id, "displayName": name}, "stats": stats}


def _boxscore():
    # The boxscore uses NCST while our identity spine uses NCSU. Stable ESPN
    # athlete ids, not a guessed abbreviation alias, own the join.
    return {"players": [{
        "team": {"abbreviation": "NCST"},
        "statistics": [
            {"name": "passing", "labels": ["C/ATT", "YDS", "AVG", "TD", "INT"],
             "athletes": [_athlete("1001", "College Quarterback", ["14/25", "250", "10", "2", "1"])]},
            {"name": "rushing", "labels": ["CAR", "YDS", "AVG", "TD"],
             "athletes": [
                 _athlete("1001", "College Quarterback", ["5", "20", "4", "1"]),
                 _athlete("1002", "College Running Back", ["10", "60", "6", "1"]),
                 _athlete("1004", "Zero Receiver", ["1", "4", "4", "0"]),
             ]},
            {"name": "receiving", "labels": ["REC", "YDS", "AVG", "TD"],
             "athletes": [_athlete("1002", "College Running Back", ["3", "30", "10", "1"])]},
            {"name": "kicking", "labels": ["FG", "PCT", "LONG", "XP", "PTS"],
             "athletes": [_athlete("1003", "College Kicker", ["2/2", "100", "45", "3/3", "9"])]},
        ],
    }]}


def test_total_passing_touchdowns_alias_resolves_and_settles(monkeypatch):
    """Bovada's total_passing_touchdowns grades as the passing TD market."""
    from settlement.market_mapping import resolve_market

    assert resolve_market("ncaaf", "total_passing_touchdowns") == ("passing", "TD")

    con = _database()
    monkeypatch.setattr(espn_client, "boxscore", lambda *_args: _boxscore())
    con.execute("INSERT INTO props VALUES (20, 1, 'total_passing_touchdowns', 1.5, 'over', 10)")

    assert settlement.settle_game(con, 1)["settled"] == 19
    row = con.execute(
        "SELECT actual_value, hit FROM prop_results WHERE prop_id=20").fetchone()
    assert tuple(row) == (2.0, 1)


def test_all_ingested_ncaaf_markets_settle_from_published_boxscore(monkeypatch):
    con = _database()
    monkeypatch.setattr(espn_client, "boxscore", lambda *_args: _boxscore())

    assert settlement.settle_game(con, 1) == {
        "settled": 18, "void": 0, "unmappable": 0, "pending": 1, "errors": 0,
    }
    rows = con.execute(
        "SELECT prop_id, actual_value, hit FROM prop_results ORDER BY prop_id"
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        (1, 25.0, 1), (2, 14.0, 1), (3, 250.0, 1), (4, 2.0, 1),
        (5, 1.0, 1), (6, 20.0, 1), (7, 1.0, 1), (8, 270.0, 1),
        (9, 30.0, 1), (10, 3.0, 1), (11, 10.0, 1), (12, 90.0, 1),
        (13, 2.0, 1), (14, 2.0, 1), (15, 2.0, 1), (16, 3.0, 1),
        (17, 9.0, 1), (18, 0.0, 1),
    ]


def _add_cfbd_line(con, espn_id, stats):
    con.execute(
        "INSERT INTO player_game_logs(player_id, league, season, game_no, "
        "game_id, game_date, team, opponent, home_away, stats, source, "
        "source_player_key, ingested_at, game_type) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        _cfbd_line(espn_id, stats))


def _attempts(con, prop_id):
    return con.execute(
        "SELECT stage, terminal, reason FROM settlement_attempts "
        "WHERE prop_id=? ORDER BY id", (prop_id,)).fetchall()


def test_cfbd_line_settles_without_a_request(monkeypatch):
    """A full CFBD stat line grades the prop with no ESPN call at all."""
    con = _database()
    _add_cfbd_line(con, "1001",
                   '{"att":30,"pass_yds":280,"pass_td":2,"intc":1,'
                   '"rush_yds":10,"rush_td":0}')

    def _refuse(*_args):
        raise AssertionError("ESPN must not be called when the CFBD line answers")

    monkeypatch.setattr(espn_client, "boxscore", _refuse)
    # Only props the CFBD line covers are on the game: (3) passing_yards,
    # (4) passing_touchdowns, (1) pass_attempts, (5) interceptions_thrown,
    # (6) rushing_yards, (8) passing_rushing_yards. Remove the rest.
    con.execute("DELETE FROM props WHERE id NOT IN (1,3,4,5,6,8)")

    result = settlement.settle_game(con, 1)
    assert result == {"settled": 6, "void": 0, "unmappable": 0,
                      "pending": 0, "errors": 0}
    values = dict(con.execute(
        "SELECT prop_id, actual_value FROM prop_results").fetchall())
    assert values[3] == 280.0 and values[4] == 2.0 and values[1] == 30.0
    assert values[5] == 1.0 and values[6] == 10.0 and values[8] == 290.0
    stages = {tuple(r) for r in con.execute(
        "SELECT stage, terminal, reason FROM settlement_attempts")}
    assert stages == {("cfbd", "settled", "cfbd_line")}


def test_total_passing_touchdowns_alias_grades_from_cfbd(monkeypatch):
    con = _database()
    _add_cfbd_line(con, "1001",
                   '{"att":30,"pass_yds":280,"pass_td":2,"intc":1}')
    con.execute("DELETE FROM props WHERE id != 4")
    con.execute("UPDATE props SET market='total_passing_touchdowns' WHERE id=4")

    def _refuse(*_args):
        raise AssertionError("the alias must reach the CFBD line directly")

    monkeypatch.setattr(espn_client, "boxscore", _refuse)
    assert settlement.settle_game(con, 1)["settled"] == 1
    assert con.execute(
        "SELECT actual_value FROM prop_results WHERE prop_id=4").fetchone()[0] == 2.0


def test_cfbd_row_missing_stat_falls_back_to_espn(monkeypatch):
    """A row without the market's key is not evidence of zero: ESPN decides."""
    con = _database()
    _add_cfbd_line(con, "1002", '{"rush_yds":60,"rush_td":1}')
    monkeypatch.setattr(espn_client, "boxscore", lambda *_args: _boxscore())
    con.execute("DELETE FROM props WHERE id != 9")  # receiving_yards for 1002

    assert settlement.settle_game(con, 1) == {
        "settled": 1, "void": 0, "unmappable": 0, "pending": 0, "errors": 0}
    # 1002 appears in the boxscore's receiving group with 3/30, so the
    # extractor finds 30 directly — no invented zero involved.
    assert con.execute(
        "SELECT actual_value FROM prop_results WHERE prop_id=9").fetchone()[0] == 30.0
    stages = [tuple(r) for r in _attempts(con, 9)]
    assert stages == [("espn_fallback", "settled",
                       "cfbd_row_missing_stat+espn_boxscore")]


def test_athlete_absent_from_boxscore_stays_pending_with_reason(monkeypatch):
    con = _database()
    monkeypatch.setattr(espn_client, "boxscore", lambda *_args: _boxscore())
    con.execute("DELETE FROM props WHERE id != 19")  # bench player, no CFBD row

    assert settlement.settle_game(con, 1) == {
        "settled": 0, "void": 0, "unmappable": 0, "pending": 1, "errors": 0}
    assert [tuple(r) for r in _attempts(con, 19)] == [
        ("espn_fallback", "pending",
         "no_cfbd_row+athlete_absent_from_boxscore")]


def test_markets_cfbd_does_not_publish_stay_on_the_fallback(monkeypatch):
    """No kicking group, no completions, no carries, no return-TD components:
    those markets never grade from the stored line even when the row exists."""
    con = _database()
    _add_cfbd_line(con, "1002",
                   '{"att":2,"pass_yds":8,"rush_yds":60,"rush_td":1,'
                   '"rec":3,"rec_yds":30,"rec_td":1}')
    monkeypatch.setattr(espn_client, "boxscore", lambda *_args: _boxscore())
    con.execute("DELETE FROM props WHERE id NOT IN (11,14)")  # rush_attempts, total_touchdowns

    assert settlement.settle_game(con, 1) == {
        "settled": 2, "void": 0, "unmappable": 0, "pending": 0, "errors": 0}
    # Both graded by the boxscore extractor, not by summing the line.
    stages = {tuple(r) for r in con.execute(
        "SELECT stage, terminal FROM settlement_attempts")}
    assert ("cfbd", "settled") not in stages


def test_repeat_pending_attempt_writes_nothing_new(monkeypatch):
    """Durable reasons must not grow a row per pass for an unchanged state."""
    con = _database()
    monkeypatch.setattr(espn_client, "boxscore", lambda *_args: _boxscore())
    con.execute("DELETE FROM props WHERE id != 19")

    settlement.settle_game(con, 1)
    first = con.execute("SELECT COUNT(*) FROM settlement_attempts").fetchone()[0]
    settlement.settle_game(con, 1)
    assert con.execute(
        "SELECT COUNT(*) FROM settlement_attempts").fetchone()[0] == first

