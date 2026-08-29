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


def _ufc_scoreboard(completed=True, fight_id="401874315"):
    return {"events": [{"id": "600059667", "competitions": [{
        "id": fight_id,
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

    assert result == {"settled": 6, "void": 0, "unmappable": 0,
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
        105: (1.0, 1),
    }
    # A not-yet-ingested fighter stays retryable; a null placeholder would make
    # settle_props count it as already graded forever.
    assert 106 not in rows
    final = con.execute(
        "SELECT final_home, final_away FROM prop_games WHERE id=1").fetchone()
    assert (final["final_home"], final["final_away"]) == (None, None)


def test_ufc_settlement_reads_provider_separated_ufcstats_logs(monkeypatch):
    con = _ufc_connection()
    con.execute("DELETE FROM player_game_logs")
    con.execute("""CREATE TABLE player_game_logs_ufcstats(
        player_id INTEGER, league TEXT, game_date TEXT,
        source_player_key TEXT, stats TEXT)""")
    winner = {"result": "W", "method": "KO/TKO", "sigStrikesLanded": 27,
              "fight_time": 4.35}
    loser = {"result": "L", "method": "KO/TKO", "sigStrikesLanded": 11,
             "fight_time": 4.35}
    con.executemany(
        "INSERT INTO player_game_logs_ufcstats VALUES(?,?,?,?,?)",
        [(10, "ufc", "2026-07-25", "ufcstats-a", json.dumps(winner)),
         (11, "ufc", "2026-07-25", "ufcstats-b", json.dumps(loser))],
    )
    monkeypatch.setattr(espn_client, "_get", lambda *args, **kwargs: _ufc_scoreboard())

    result = settlement.settle_game(con, 1)

    assert result == {"settled": 6, "void": 0, "unmappable": 0,
                      "pending": 1, "errors": 0}
    assert con.execute("SELECT COUNT(*) FROM prop_results").fetchone()[0] == 6


def test_complete_ufcstats_rows_prove_finality_without_espn(monkeypatch):
    con = _ufc_connection()
    con.execute("DELETE FROM player_game_logs")
    con.execute("DELETE FROM props WHERE player_id=12")
    con.execute("""CREATE TABLE player_game_logs_ufcstats(
        player_id INTEGER, league TEXT, game_date TEXT,
        source_player_key TEXT, stats TEXT)""")
    con.executemany(
        "INSERT INTO player_game_logs_ufcstats VALUES(?,?,?,?,?)",
        [
            (10, "ufc", "2026-07-25", "ufcstats-a", json.dumps({
                "result": "W", "method": "KO/TKO",
                "sigStrikesLanded": 27, "fight_time": 4.35,
            })),
            (11, "ufc", "2026-07-25", "ufcstats-b", json.dumps({
                "result": "L", "method": "KO/TKO",
                "sigStrikesLanded": 11, "fight_time": 4.35,
            })),
        ],
    )
    monkeypatch.setattr(
        espn_client,
        "_get",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("ESPN finality called despite complete UFCStats rows")
        ),
    )

    result = settlement.settle_game(con, 1)

    assert result == {"settled": 6, "void": 0, "unmappable": 0,
                      "pending": 0, "errors": 0}


def test_ufcstats_settlement_accepts_the_adjacent_source_date(monkeypatch):
    con = _ufc_connection()
    con.execute("DELETE FROM player_game_logs")
    con.execute("DELETE FROM props WHERE player_id=12")
    con.execute("""CREATE TABLE player_game_logs_ufcstats(
        player_id INTEGER, league TEXT, game_date TEXT,
        source_player_key TEXT, stats TEXT)""")
    winner = {"result": "W", "method": "KO/TKO", "sigStrikesLanded": 27,
              "fight_time": 4.35}
    loser = {"result": "L", "method": "KO/TKO", "sigStrikesLanded": 11,
             "fight_time": 4.35}
    # The prop slate is July 25 UTC; UFCStats publishes the local event date.
    con.executemany(
        "INSERT INTO player_game_logs_ufcstats VALUES(?,?,?,?,?)",
        [(10, "ufc", "2026-07-24", "ufcstats-a", json.dumps(winner)),
         (11, "ufc", "2026-07-24", "ufcstats-b", json.dumps(loser))],
    )
    monkeypatch.setattr(
        espn_client,
        "_get",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("ESPN finality called for adjacent UFCStats date")
        ),
    )

    result = settlement.settle_game(con, 1)

    assert result == {"settled": 6, "void": 0, "unmappable": 0,
                      "pending": 0, "errors": 0}


def test_ufc_does_not_settle_a_nonfinal_fight(monkeypatch):
    con = _ufc_connection()
    monkeypatch.setattr(espn_client, "_get", lambda *args, **kwargs: _ufc_scoreboard(False))

    result = settlement.settle_game(con, 1)

    assert result["settled"] == 0
    assert result["errors"] == 0
    assert "completed=False" in result["msg"]
    assert con.execute("SELECT COUNT(*) FROM prop_results").fetchone()[0] == 0


def test_ufc_finds_a_next_utc_day_fight_on_the_previous_card_date(monkeypatch):
    """The linker and settler must use the same date window.

    Real UFC 330 fights dated 2026-08-16 in prop_games exist only inside ESPN's
    2026-08-15 scoreboard.  The old finality lookup retried 08-16 alone forever.
    """
    con = _ufc_connection()
    fight_id = "401909737"
    con.execute(
        "UPDATE prop_games SET date='2026-08-16', espn_event_id=? WHERE id=1",
        (fight_id,),
    )
    con.execute("UPDATE player_game_logs SET game_id=?", (fight_id,))
    seen = []

    def fake_get(url, ttl=0):
        seen.append(url)
        if "dates=20260815" in url:
            return _ufc_scoreboard(fight_id=fight_id)
        return {"events": []}

    monkeypatch.setattr(espn_client, "_get", fake_get)

    result = settlement.settle_game(con, 1)

    assert result == {"settled": 6, "void": 0, "unmappable": 0,
                      "pending": 1, "errors": 0}
    assert [url.rsplit("=", 1)[-1] for url in seen] == ["20260816", "20260815"]
    assert con.execute("SELECT COUNT(*) FROM prop_results").fetchone()[0] == 6


def test_ufc_method_markets_require_published_outcome_and_method():
    assert settlement._ufc_actual({"result": "W", "method": "SUB"},
                                  "win_by_submission") == 1.0
    assert settlement._ufc_actual({"result": "W", "method": "SUB"},
                                  "win_by_ko") == 0.0
    assert settlement._ufc_actual({"result": "L"}, "win_by_ko") == 0.0
    assert settlement._ufc_actual({"result": "W"}, "win_by_ko") is None
    assert settlement._ufc_actual({"result": "W", "method": "KO/TKO"},
                                  "finishes") == 1.0
    assert settlement._ufc_actual({"result": "W", "method": "DEC"},
                                  "finishes") == 0.0


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

    # `shots` (prop 205) moved from unmappable to pending on 2026-08-25, when
    # the roster map gained the stat names ESPN actually publishes. That is a
    # semantic upgrade, not a weakened assertion: the market is now understood,
    # and this fixture's roster row simply does not carry `totalShots`, so it is
    # RETRYABLE rather than "we do not know this market". Prop 205 is still
    # asserted absent from prop_results below, exactly as before.
    assert result == {"settled": 3, "void": 0, "unmappable": 0,
                      "pending": 4, "errors": 0}
    rows = {row["prop_id"]: (row["actual_value"], row["hit"])
            for row in con.execute("SELECT * FROM prop_results")}
    assert rows == {
        200: (0.0, 0),
        201: (1.0, 1),
        202: (1.0, 1),
    }
    # Roster absence (including a stale non-null ESPN id), a roster row with no
    # published assists, and an unsupported market stay retryable. None is
    # silently converted to a zero/null terminal result.
    assert 203 not in rows
    assert 204 not in rows
    assert 205 not in rows
    assert 206 not in rows
    final = con.execute(
        "SELECT final_home, final_away FROM prop_games WHERE id=2").fetchone()
    assert (final["final_home"], final["final_away"]) == (0.0, 2.0)


def _mls_new_market_connection():
    """The markets added when MLS went from 2 Bovada markets to 8."""
    con = sqlite3.connect(":memory:")
    _schema(con)
    con.execute(
        "INSERT INTO prop_games VALUES(2,'mls','New England Revolution',"
        "'Houston Dynamo','2026-08-08','761469',NULL,NULL,"
        "'2026-08-08T20:30:00+00:00')")
    con.executemany(
        "INSERT INTO players VALUES(?,?,?,?,?)",
        [(20, "Jack McGlynn", "HOU", "mls", "303512"),
         (21, "Agustin Resch", "HOU", "mls", "419253"),
         (25, "No Espn Id", "HOU", "mls", None)])
    con.executemany(
        "INSERT INTO props VALUES(?,?,?,?,?,?)",
        [(300, 2, 20, "card_shown", 0.5, "over"),        # yellow 1 + red 0 -> shown
         (301, 2, 21, "card_shown", 0.5, "over"),        # no cards -> not shown
         (302, 2, 20, "goal_or_assist", 0.5, "over"),    # 0 goals + 1 assist -> yes
         (303, 2, 21, "first_goal_scorer", 0.5, "over"),  # scored the opener
         (304, 2, 20, "first_goal_scorer", 0.5, "over"),  # did not
         (305, 2, 25, "first_goal_scorer", 0.5, "over")])  # no espn_id -> retryable
    return con


def _mls_summary_with_cards_and_events(with_events=True):
    summary = _mls_summary()
    for group in summary["rosters"]:
        for row in group["roster"]:
            extra = {"yellowCards": 0.0, "redCards": 0.0}
            if row["athlete"]["id"] == "303512":
                extra["yellowCards"] = 1.0
            row["stats"] += [{"name": k, "value": v} for k, v in extra.items()]
    if with_events:
        summary["keyEvents"] = [
            {"type": {"text": "Kickoff"}, "period": {"number": 1},
             "clock": {"value": 0.0}},
            {"type": {"text": "Goal"}, "scoringPlay": True, "shootout": False,
             "period": {"number": 2}, "clock": {"value": 3000.0},
             "participants": [{"athlete": {"id": "303512"}}]},
            {"type": {"text": "Goal"}, "scoringPlay": True, "shootout": False,
             "period": {"number": 1}, "clock": {"value": 1200.0},
             "participants": [{"athlete": {"id": "419253"}}]},
        ]
    return summary


def test_mls_settles_cards_goal_or_assist_and_the_first_goal(monkeypatch):
    """Three markets Bovada prices that no single published stat answers.

    A card is a yellow OR a red; score-or-assist is a sum; and the first goal is about
    ORDER, which a box score does not carry. The first-goal answer comes from keyEvents
    via the same helper the log ingest uses, so the two cannot drift.
    """
    con = _mls_new_market_connection()
    summary = _mls_summary_with_cards_and_events()
    monkeypatch.setattr(espn_client, "summary", lambda league, event_id: summary)

    result = settlement.settle_game(con, 2)

    rows = {row["prop_id"]: (row["actual_value"], row["hit"])
            for row in con.execute("SELECT * FROM prop_results")}
    assert rows == {
        300: (1.0, 1),   # McGlynn took a yellow
        301: (0.0, 0),   # Resch took none
        302: (1.0, 1),   # 0 goals + 1 assist
        303: (1.0, 1),   # Resch scored in the 20th; McGlynn's came in the 50th
        304: (0.0, 0),
    }
    # No espn_id means the events cannot name him. Comparing on name here would be a
    # second identity path, so it stays retryable rather than guessing.
    assert 305 not in rows
    assert result["pending"] >= 1


def test_mls_first_goal_stays_pending_when_espn_published_no_events(monkeypatch):
    """Grading everyone as not-first would invent an answer that looks real."""
    con = _mls_new_market_connection()
    summary = _mls_summary_with_cards_and_events(with_events=False)
    monkeypatch.setattr(espn_client, "summary", lambda league, event_id: summary)

    settlement.settle_game(con, 2)

    graded = {row["prop_id"] for row in con.execute("SELECT * FROM prop_results")}
    assert 303 not in graded
    assert 304 not in graded
    # The markets that do not depend on event order still settle.
    assert {300, 301, 302} <= graded


def test_mls_does_not_settle_before_full_time(monkeypatch):
    con = _mls_connection()
    monkeypatch.setattr(
        espn_client, "summary", lambda league, event_id: _mls_summary(False))

    result = settlement.settle_game(con, 2)

    assert result["settled"] == 0
    assert "completed=False" in result["msg"]
    assert con.execute("SELECT COUNT(*) FROM prop_results").fetchone()[0] == 0


def _lcup_connection():
    """A Leagues Cup fixture with the markets PrizePicks actually prices.

    The stat names below are ESPN's own, verified against a real completed
    Leagues Cup summary (event 401863625) rather than invented: that surface
    publishes fourteen per-player fields under `rosters[].roster[].stats`, and
    `boxscore` carries only `teams`. A fixture naming these fields differently
    would define a world in which the correct mapping is unwritable.
    """
    con = sqlite3.connect(":memory:")
    _schema(con)
    con.execute(
        "INSERT INTO prop_games VALUES(7,'lcup','CF Monterrey','Chicago Fire',"
        "'2026-08-25','401909652',NULL,NULL,'2026-08-26T00:30:00+00:00')")
    con.executemany(
        "INSERT INTO players VALUES(?,?,?,?,?)",
        # A Leagues Cup athlete is owned by a DOMESTIC spine; players.league is
        # never 'lcup'.
        [(70, "Hugo Cuypers", "MTY", "ligamx", "303512")])
    con.executemany(
        "INSERT INTO props VALUES(?,?,?,?,?,?)",
        [(700, 7, 70, "shots", 0.5, "over"),
         (701, 7, 70, "shots_on_target", 1.5, "over"),
         (702, 7, 70, "fouls_committed", 0.5, "over"),
         (703, 7, 70, "goals", 0.5, "over"),
         # Priced by PrizePicks, published by nobody we read. Must stay
         # UNMAPPABLE rather than grade against a near-miss field.
         (704, 7, 70, "tackles", 0.5, "over"),
         (705, 7, 70, "passes_attempted", 10.5, "over")])
    con.commit()
    return con


def _lcup_summary():
    summary = _mls_summary()
    summary["header"]["competitions"][0]["id"] = "401909652"
    summary["rosters"] = [
        {"team": {"abbreviation": "MTY"}, "roster": [
            {"athlete": {"id": "303512", "displayName": "Hugo Cuypers"},
             "stats": [{"name": key, "value": value} for key, value in {
                 "totalShots": 3.0,
                 "shotsOnTarget": 1.0,
                 "foulsCommitted": 2.0,
                 "totalGoals": 0.0,
                 "goalAssists": 0.0,
             }.items()]},
        ]},
    ]
    return summary


def test_a_leagues_cup_fixture_grades_off_the_roster_surface(monkeypatch):
    """Dispatching on `mls` alone left Leagues Cup props ungraded forever.

    settle_game routed only `mls` to the roster settler, so an `lcup` fixture
    fell through to the boxscore path -- and soccer summaries do not populate
    per-player boxscore stats at all.
    """
    con = _lcup_connection()
    summary = _lcup_summary()
    monkeypatch.setattr(espn_client, "summary", lambda league, event_id: summary)
    monkeypatch.setattr(
        espn_client, "boxscore",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("boxscore called")))

    result = settlement.settle_game(con, 7)

    assert result["errors"] == 0
    assert result["settled"] == 4
    # CORRECTED 2026-08-25: tackles and passes attempted were asserted
    # UNMAPPABLE here on the measurement "ESPN publishes neither". That measured
    # the SUMMARY; the CORE api publishes both, and `ingest_soccer_logs --deep`
    # stores them. They are now KNOWN markets whose stored row this fixture does
    # not have, so they are PENDING -- retryable once the deep pass has run.
    #
    # Pending, never zero: 0 tackles is a real result a player can have, so
    # grading one because we did not look would settle a bet on a number nobody
    # measured.
    assert result["unmappable"] == 0
    assert result["pending"] == 2

    rows = {row["prop_id"]: (row["actual_value"], row["hit"])
            for row in con.execute("SELECT * FROM prop_results")}
    assert rows == {
        700: (3.0, 1),   # 3 shots over 0.5
        701: (1.0, 0),   # 1 on target, under 1.5
        702: (2.0, 1),   # 2 fouls over 0.5
        703: (0.0, 0),   # no goal
    }
    # Refused, not graded as a loss. A zero here would be a false settlement.
    assert 704 not in rows
    assert 705 not in rows


def test_a_deep_market_settles_from_the_stored_core_row(monkeypatch):
    """tackles comes from player_game_logs, written by --deep, not the summary."""
    con = _lcup_connection()
    con.execute(
        "INSERT INTO player_game_logs(player_id, league, game_id, stats) "
        "VALUES(?,?,?,?)",
        (70, "lcup", "401909652",
         json.dumps({"tackles": 3, "passes_attempted": 61})))
    con.commit()
    summary = _lcup_summary()
    monkeypatch.setattr(espn_client, "summary", lambda league, event_id: summary)

    result = settlement.settle_game(con, 7)

    rows = {row["prop_id"]: (row["actual_value"], row["hit"])
            for row in con.execute("SELECT * FROM prop_results")}
    # 704 tackles o0.5 -> 3 tackles, hit. 705 passes attempted o10.5 -> 61, hit.
    assert rows[704] == (3.0, 1)
    assert rows[705] == (61.0, 1)
    assert result["unmappable"] == 0
