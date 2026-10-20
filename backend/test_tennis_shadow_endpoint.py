"""The tennis endpoint writes the shadow rows inside the lock window, beside the served lock, and nowhere else."""
import datetime as dt
import json
import sqlite3

import pytest

import tennis_bovada_odds
import tennis_daily_projections as projections
import tennis_shadow as shadow
from routers.games import misc

NOW = dt.datetime(2026, 10, 17, 12, 0, tzinfo=dt.timezone.utc)
SERVED_VERSION = "tennis-global-surface-elo-blend-v2"


class FrozenDateTime(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz else NOW.replace(tzinfo=None)


def _open(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript("""
      CREATE TABLE IF NOT EXISTS scoreboard_snapshots(
        league TEXT, game_date TEXT, game_id TEXT, payload TEXT, state TEXT,
        start_time TEXT, fetched_at TEXT, source TEXT, PRIMARY KEY(league, game_date, game_id));
      CREATE TABLE IF NOT EXISTS tennis_model_grades(
        league TEXT, game_id TEXT, winner TEXT, total_games_error REAL, PRIMARY KEY(league, game_id));
      CREATE TABLE IF NOT EXISTS tennis_match_stats_overrides(
        league TEXT, game_date TEXT, game_id TEXT, home_aces INTEGER, away_aces INTEGER, source_url TEXT);
      CREATE TABLE IF NOT EXISTS players(id INTEGER PRIMARY KEY, name TEXT, league TEXT, espn_id TEXT);
      CREATE TABLE IF NOT EXISTS player_source_ids(source TEXT, league TEXT, source_player_key TEXT, player_id INTEGER);
      CREATE TABLE IF NOT EXISTS tennis_wta_matches(
        tourney_id TEXT, tourney_date INTEGER, surface TEXT, winner_id INTEGER, loser_id INTEGER,
        match_num INTEGER, tourney_level TEXT, best_of INTEGER, score TEXT);
    """)
    return con


def _seed(path, *, start):
    con = _open(path)
    payload = {
        "event": "BNB Ningbo Open", "round": "R32", "status": "Scheduled", "tournament_id": "963",
        "home": {"name": "Home Player", "athlete_id": "7001", "score": None, "sets": []},
        "away": {"name": "Away Player", "athlete_id": "7002", "score": None, "sets": []},
    }
    con.execute("INSERT INTO scoreboard_snapshots VALUES('wta','2026-10-17','m-1',?,'pre',?,?,'test')",
                (json.dumps(payload), start.isoformat(), NOW.isoformat()))
    con.execute("INSERT INTO players VALUES(1,'Home Player','wta','7001'), (2,'Away Player','wta','7002')")
    con.execute("INSERT INTO player_source_ids VALUES('sackmann','wta','100001',1), ('sackmann','wta','100002',2)")
    con.executemany("INSERT INTO tennis_wta_matches VALUES('T',?,'Hard',100001,100002,?,'P',3,'6-4 6-4')",
                    [(20250101 + i, i) for i in range(5)])
    con.commit()
    con.close()


def _patch(monkeypatch, path):
    candidate = {
        "probability": 0.6, "projectedWinner": "Home Player", "modelVersion": SERVED_VERSION,
        "_sackmannPlayerIds": {"home": "100001", "away": "100002"},
    }
    monkeypatch.setattr(misc.dt, "datetime", FrozenDateTime)
    monkeypatch.setattr(misc, "_db", lambda: _open(path))
    monkeypatch.setattr(tennis_bovada_odds, "bovada_odds", lambda *args: {})
    monkeypatch.setattr(projections, "stored_candidates", lambda *args: {"m-1": candidate})
    monkeypatch.setattr(projections, "needs_projection_refresh", lambda *args: False)
    monkeypatch.setattr(projections, "project_day", lambda *args: (_ for _ in ()).throw(AssertionError("recompute")))
    monkeypatch.setattr(projections, "store_candidates", lambda *args: None)


def _rows(path, table):
    con = _open(path)
    try:
        return [tuple(row) for row in con.execute(f"SELECT * FROM {table} ORDER BY 1, 2, 3")]
    finally:
        con.close()


def test_window_writes_served_lock_and_two_shadow_rows_once(tmp_path, monkeypatch):
    path = str(tmp_path / "picks.db")
    _seed(path, start=NOW + dt.timedelta(minutes=30))
    _patch(monkeypatch, path)

    response = misc.tennis_model(date="2026-10-17", tour="wta", utc_offset_minutes=0, winner_model="page")
    served = _rows(path, "tennis_model_locks")
    shadow_rows = _rows(path, "tennis_shadow_locks")
    match = response["matches"][0]

    assert [row[6] for row in served] == [SERVED_VERSION]
    assert match["projection"]["modelVersion"] == SERVED_VERSION  # the served pick is unchanged
    assert sorted(row[2] for row in shadow_rows) == sorted(shadow.VERSIONS)
    assert {row[6] for row in shadow_rows} == {"locked"}
    assert {row[5] for row in shadow_rows} == {NOW.isoformat()}
    assert all(json.loads(row[7])["surfaceSource"] == "major_name" for row in shadow_rows)

    misc.tennis_model(date="2026-10-17", tour="wta", utc_offset_minutes=0, winner_model="page")
    assert _rows(path, "tennis_model_locks") == served
    assert _rows(path, "tennis_shadow_locks") == shadow_rows


def test_outside_the_window_no_shadow_rows_are_written(tmp_path, monkeypatch):
    path = str(tmp_path / "picks.db")
    _seed(path, start=NOW + dt.timedelta(hours=3))
    _patch(monkeypatch, path)

    misc.tennis_model(date="2026-10-17", tour="wta", utc_offset_minutes=0, winner_model="page")
    assert _rows(path, "tennis_model_locks") == []
    assert _rows(path, "tennis_shadow_locks") == []
