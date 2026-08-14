import json
import sqlite3

import espn_client
import settlement


def _schema(con):
    con.executescript("""
        CREATE TABLE prop_games(
            id INTEGER PRIMARY KEY, league TEXT, home TEXT, away TEXT, date TEXT,
            espn_event_id TEXT, final_home REAL, final_away REAL, start_time TEXT
        );
        CREATE TABLE players(
            id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT, espn_id TEXT
        );
        CREATE TABLE props(
            id INTEGER PRIMARY KEY, game_id INTEGER, player_id INTEGER, market TEXT,
            line REAL, side TEXT
        );
        CREATE TABLE prop_results(
            prop_id INTEGER PRIMARY KEY, actual_value REAL, hit INTEGER, settled_at TEXT
        );
        CREATE TABLE player_game_logs(
            id INTEGER PRIMARY KEY, player_id INTEGER, league TEXT, game_id TEXT,
            source_player_key TEXT, stats TEXT
        );
    """)
    con.row_factory = sqlite3.Row


def _ufc_connection():
    con = sqlite3.connect(":memory:")
    _schema(con)
    con.execute(
        "INSERT INTO prop_games VALUES(1,'ufc','Steve Erceg','Ramazan Temirov',"
        "'2026-07-25','401874315',NULL,NULL,'2026-07-25T17:20:00+00:00')")
    con.executemany(
        "INSERT INTO players VALUES(?,?,?,?,?)",
        [(10, "Ramazan Temirov", "Steve Erceg", "ufc", "4895691"),
         (11, "Steve Erceg", "Ramazan Temirov", "ufc", "4997217"),
         (12, "Missing Fighter", None, "ufc", "999999")])
    props = [
        (100, 1, 10, "win_by_ko", 0.5, "over"),
        (101, 1, 11, "knockouts", 0.5, "over"),
        (102, 1, 10, "win_by_decision", 0.5, "over"),
        (103, 1, 10, "significant_strikes", 26.5, "over"),
        (104, 1, 10, "fight_time", 4.5, "under"),
        (105, 1, 10, "finishes", 0.5, "over"),
        (106, 1, 12, "significant_strikes", 1.5, "over"),
    ]
    con.executemany("INSERT INTO props VALUES(?,?,?,?,?,?)", props)
    winner = {"result": "W", "method": "KO/TKO", "sigStrikesLanded": 27,
              "fight_time": 4.35}
    loser = {"result": "L", "method": "KO/TKO", "sigStrikesLanded": 11,
             "fight_time": 4.35}
    con.executemany(
        "INSERT INTO player_game_logs VALUES(?,?,?,?,?,?)",
        [(1, 10, "ufc", "401874315", "4895691", json.dumps(winner)),
         (2, 11, "ufc", "401874315", "4997217", json.dumps(loser))])
    return con


def _ufc_scoreboard(completed=True):
    return {"events": [{"id": "600059667", "competitions": [{
        "id": "401874315",
        "status": {"type": {"state": "post" if completed else "pre",
                              "completed": completed}},
        "competitors": [
            {"id": "4895691", "order": 2, "winner": True},
            {"id": "4997217", "order": 1, "winner": False},
        ],
    }]}]}


def test_ufc_uses_fight_finality_and_durable_logs(monkeypatch):
    con = _ufc_connection()
    seen = []

    def fake_get(url, ttl=0):
        seen.append(url)
        return _ufc_scoreboard()

    monkeypatch.setattr(espn_client, "_get", fake_get)
    result = settlement.settle_game(con, 1)

    assert result == {"settled": 5, "void": 0, "unmappable": 1,
                      "pending": 1, "errors": 0}
    assert seen == [
        "https://site.web.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard"
        "?dates=20260725"
    ]
    rows = {row["prop_id"]: (row["actual_value"], row["hit"])
            for row in con.execute("SELECT * FROM prop_results")}
    assert rows == {
        100: (1.0, 1),
        101: (0.0, 0),
        102: (0.0, 0),
        103: (27.0, 1),
        104: (4.35, 1),
    }
    # Unsupported and not-yet-ingested props stay retryable; a null placeholder
    # would make settle_props count them as already graded forever.
    assert 105 not in rows
    assert 106 not in rows
    final = con.execute(
        "SELECT final_home, final_away FROM prop_games WHERE id=1").fetchone()
    assert (final["final_home"], final["final_away"]) == (None, None)


def test_ufc_does_not_settle_a_nonfinal_fight(monkeypatch):
    con = _ufc_connection()
    monkeypatch.setattr(espn_client, "_get", lambda *args, **kwargs: _ufc_scoreboard(False))

    result = settlement.settle_game(con, 1)

    assert result["settled"] == 0
    assert result["errors"] == 0
    assert "completed=False" in result["msg"]
    assert con.execute("SELECT COUNT(*) FROM prop_results").fetchone()[0] == 0


def test_ufc_method_markets_require_published_outcome_and_method():
    assert settlement._ufc_actual({"result": "W", "method": "SUB"},
                                  "win_by_submission") == 1.0
    assert settlement._ufc_actual({"result": "W", "method": "SUB"},
                                  "win_by_ko") == 0.0
    assert settlement._ufc_actual({"result": "L"}, "win_by_ko") == 0.0
    assert settlement._ufc_actual({"result": "W"}, "win_by_ko") is None
    assert settlement._ufc_actual({"result": "W", "method": "KO/TKO"},
                                  "finishes") is None


def _mls_summary(completed=True):
    def player(athlete_id, name, stats):
        return {
            "athlete": {"id": athlete_id, "displayName": name},
            "stats": [{"name": key, "value": value} for key, value in stats.items()],
        }

    return {
        "header": {"competitions": [{
            "id": "761469",
            "status": {"type": {"state": "post" if completed else "pre",
                                  "completed": completed}},
            "competitors": [
                {"homeAway": "home", "winner": False, "score": "0",
                 "team": {"abbreviation": "NE"}},
                {"homeAway": "away", "winner": True, "score": "2",
                 "team": {"abbreviation": "HOU"}},
            ],
        }]},
        "boxscore": {"teams": []},
        "rosters": [
            {"team": {"abbreviation": "NE"}, "roster": [
                player("303512", "Jack McGlynn",
                       {"totalGoals": 0.0, "goalAssists": 1.0}),
                player("555", "Stats Missing", {"totalGoals": 0.0}),
            ]},
            {"team": {"abbreviation": "HOU"}, "roster": [
                player("419253", "Agustín Resch",
                       {"totalGoals": 1.0, "goalAssists": 0.0}),
            ]},
        ],
    }


def _mls_connection():
    con = sqlite3.connect(":memory:")
    _schema(con)
    con.execute(
        "INSERT INTO prop_games VALUES(2,'mls','New England Revolution',"
        "'Houston Dynamo','2026-08-08','761469',NULL,NULL,"
        "'2026-08-08T20:30:00+00:00')")
    con.executemany(
        "INSERT INTO players VALUES(?,?,?,?,?)",
        [(20, "Jack McGlynn", "HOU", "mls", "303512"),
         (21, "Agustin Resch", "HOU", "mls", None),
         (22, "Not On Roster", "NE", "mls", None),
         (23, "Stats Missing", "NE", "mls", "555"),
         (24, "Jack McGlynn", "HOU", "mls", "wrong-id")])
    con.executemany(
        "INSERT INTO props VALUES(?,?,?,?,?,?)",
        [(200, 2, 20, "goals", 0.5, "over"),
         (201, 2, 20, "assists", 0.5, "over"),
         (202, 2, 21, "goals", 0.5, "over"),
         (203, 2, 22, "goals", 0.5, "over"),
         (204, 2, 23, "assists", 0.5, "over"),
         (205, 2, 20, "shots", 0.5, "over"),
         (206, 2, 24, "goals", 0.5, "over")])
    return con


def test_mls_uses_roster_stats_not_team_boxscore(monkeypatch):
    con = _mls_connection()
    summary = _mls_summary()
    monkeypatch.setattr(espn_client, "summary", lambda league, event_id: summary)
    monkeypatch.setattr(
        espn_client, "boxscore",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("boxscore called")))

    result = settlement.settle_game(con, 2)

    assert result == {"settled": 3, "void": 2, "unmappable": 1,
                      "pending": 1, "errors": 0}
    rows = {row["prop_id"]: (row["actual_value"], row["hit"])
            for row in con.execute("SELECT * FROM prop_results")}
    assert rows == {
        200: (0.0, 0),
        201: (1.0, 1),
        202: (1.0, 1),
        203: (None, None),
        206: (None, None),
    }
    # A roster row with no published assists and an unsupported market stay
    # retryable; neither is silently converted to a zero/null result.
    assert 204 not in rows
    assert 205 not in rows
    final = con.execute(
        "SELECT final_home, final_away FROM prop_games WHERE id=2").fetchone()
    assert (final["final_home"], final["final_away"]) == (0.0, 2.0)


def test_mls_does_not_settle_before_full_time(monkeypatch):
    con = _mls_connection()
    monkeypatch.setattr(
        espn_client, "summary", lambda league, event_id: _mls_summary(False))

    result = settlement.settle_game(con, 2)

    assert result["settled"] == 0
    assert "completed=False" in result["msg"]
    assert con.execute("SELECT COUNT(*) FROM prop_results").fetchone()[0] == 0
