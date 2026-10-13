import sqlite3

import ingest_soccer_logs as soccer

NOW = "2026-10-02T20:00:00+00:00"


def db():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE prop_games(id INTEGER PRIMARY KEY, league TEXT, date TEXT,"
                " espn_event_id TEXT, start_time TEXT)")
    con.execute("CREATE TABLE scoreboard_snapshots(league TEXT, game_date TEXT, game_id TEXT,"
                " state TEXT, start_time TEXT, payload TEXT DEFAULT '{}')")
    return con


def test_priced_matches_that_have_not_kicked_off_are_named():
    con = db()
    con.executemany("INSERT INTO prop_games(league,date,espn_event_id,start_time) VALUES(?,?,?,?)", [
        ("mls", "2026-10-10", "761850", "2026-10-10T23:30:00+00:00"),   # future
        ("mls", "2026-10-06", "761660", "2026-10-07T00:30:00+00:00"),   # future, local date earlier
        ("mls", "2026-09-30", "761833", "2026-09-30T23:30:00+00:00"),   # played
        ("mls", "2026-10-12", "761900", None),                          # no time, future date
        ("nfl", "2026-10-10", "999", "2026-10-10T23:30:00+00:00"),      # other league
    ])
    assert soccer._not_started(con, "mls", NOW) == {"761850", "761660", "761900"}


def test_the_scoreboard_capture_also_names_unplayed_matches():
    con = db()
    con.executemany("INSERT INTO scoreboard_snapshots(league,game_date,game_id,state,start_time)"
                    " VALUES(?,?,?,?,?)", [
        ("mls", "2026-10-03", "761700", "pre", "2026-10-03T23:00:00+00:00"),
        ("mls", "2026-10-01", "761798", "post", "2026-10-02T01:30:00+00:00"),
    ])
    assert soccer._not_started(con, "mls", NOW) == {"761700"}


def test_a_missing_table_falls_back_to_fetching_rather_than_skipping():
    con = sqlite3.connect(":memory:")
    assert soccer._not_started(con, "mls", NOW) == set()


def test_scoreboard_final_leads_and_waiting_only_breaks_ties_within_it():
    waiting = {"900": "2026-10-10", "500": "2026-09-27"}   # 900 priced but unplayed
    final = {"500", "761833"}                               # RBNY v STL final, no props
    order = soccer._fetch_order(waiting, ["100", "500", "761833", "900"], final)
    assert order[:2] == ["500", "761833"]   # final first: waited-on, then the rest
    assert order[2] == "900"                 # priced but not final
    assert order[3] == "100"


def test_without_a_scoreboard_the_old_order_is_unchanged():
    waiting = {"500": "2026-09-27"}
    assert soccer._fetch_order(waiting, ["100", "500"]) == soccer._fetch_order(waiting, ["100", "500"], None)


def test_the_scoreboard_names_finished_matches_and_refuses_postponed_ones():
    con = db()
    con.executemany("INSERT INTO scoreboard_snapshots VALUES(?,?,?,?,?,?)", [
        ("mls", "2026-09-30", "761833", "post", "2026-09-30T23:30:00+00:00", '{"status_detail": "FT"}'),
        ("mls", "2026-09-29", "761834", "post", "2026-09-29T23:30:00+00:00", '{"status_detail": "FT-Pens"}'),
        # The real 09-26 row: post, FT, 0-0, and ESPN's detail says it never happened.
        ("mls", "2026-09-26", "761900", "post", "2026-09-26T23:30:00+00:00", '{"status_detail": "Postponed"}'),
        # Where ESPN's completed flag is stored it wins over the detail text.
        ("mls", "2026-09-25", "761901", "post", "2026-09-25T23:30:00+00:00", '{"completed": false, "status_detail": "FT"}'),
        ("mls", "2026-10-03", "761700", "pre", "2026-10-03T23:00:00+00:00", '{}'),
        ("mls", "2026-10-02", "761701", "in", "2026-10-02T19:00:00+00:00", '{}'),
    ])
    assert soccer._finished_on_scoreboard(con, "mls") == {"761833", "761834"}
