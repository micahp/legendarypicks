import datetime as dt
import json
import sqlite3

from ingest_ufc_fight_stats import ufcstats_pipeline as pipe


def _con(with_scoreboard=True):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, league TEXT, espn_id TEXT);
        CREATE TABLE prop_games(id INTEGER PRIMARY KEY, league TEXT, date TEXT, home TEXT,
                                away TEXT, espn_event_id TEXT);
        CREATE TABLE props(id INTEGER PRIMARY KEY, game_id INTEGER, player_id INTEGER,
                           market TEXT);
    """)
    # 2026-10-06 as published: a DWCS Tuesday fight and a Saturday Fight Night fight.
    con.executemany("INSERT INTO players VALUES (?,?,?,?)", [
        (1, "Ryuho Miyaguchi", "ufc", "a1"), (2, "Mateus Soares", "ufc", "a2"),
        (3, "Brendan Allen", "ufc", "a3"), (4, "Christian Duncan", "ufc", "a4")])
    con.executemany("INSERT INTO prop_games VALUES (?,?,?,?,?,?)", [
        (12229, "ufc", "2026-10-06", "Ryuho Miyaguchi", "Mateus Soares", "401928605"),
        (12226, "ufc", "2026-10-11", "Brendan Allen", "Christian Duncan", "401916276")])
    market = pipe.NUMERIC_PROP_MARKETS[0]
    con.executemany("INSERT INTO props(game_id, player_id, market) VALUES (?,?,?)", [
        (12229, 1, market), (12229, 2, market), (12226, 3, market), (12226, 4, market)])
    if with_scoreboard:
        con.execute("CREATE TABLE scoreboard_snapshots(league TEXT, game_date TEXT,"
                    " game_id TEXT, payload TEXT)")
        con.executemany("INSERT INTO scoreboard_snapshots VALUES ('ufc', ?, ?, ?)", [
            ("2026-10-06", "401928605",
             json.dumps({"event": "Dana White's Contender Series: Season 10, Week 9"})),
            ("2026-10-11", "401916276",
             json.dumps({"event": "UFC Fight Night: Allen vs. Duncan"}))])
    return con


def _names(con):
    targets = pipe._load_prop_targets(con, dt.date(2026, 10, 6), {}, 0, 7,
                                      pipe.NUMERIC_PROP_MARKETS)
    return sorted(t.name for t in targets)


def test_a_contender_series_fighter_is_not_a_ufcstats_target():
    assert _names(_con()) == ["Brendan Allen", "Christian Duncan"]


def test_without_the_scoreboard_nothing_is_excluded():
    assert _names(_con(with_scoreboard=False)) == [
        "Brendan Allen", "Christian Duncan", "Mateus Soares", "Ryuho Miyaguchi"]
