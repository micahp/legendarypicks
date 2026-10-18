"""Focused API tests for Tennis model score and lock provenance fields."""
import datetime as dt
import json
import sqlite3

import pytest

import tennis_daily_projections as projections
import tennis_bovada_odds
from routers.games import misc


NOW = dt.datetime(2026, 10, 17, 12, 0, tzinfo=dt.timezone.utc)
START = (NOW + dt.timedelta(minutes=30)).isoformat()


def _snapshot(con, *, game_id="match-1", state="pre", start_time=START):
    payload = {
        "event": "Test Open", "round": "Final", "status": "Final" if state == "post" else "Scheduled",
        "home": {"name": "Home Player", "score": "2" if state == "post" else None,
                 "sets": [6, 6] if state == "post" else [], "athlete_id": None},
        "away": {"name": "Away Player", "score": "0" if state == "post" else None,
                 "sets": [4, 4] if state == "post" else [], "athlete_id": None},
    }
    con.execute(
        "INSERT INTO scoreboard_snapshots VALUES(?,?,?,?,?,?,?,?)",
        ("atp", "2026-10-17", game_id, json.dumps(payload), state, start_time,
         NOW.isoformat(), "test-publisher"),
    )


def _database(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript("""
      CREATE TABLE IF NOT EXISTS scoreboard_snapshots(
        league TEXT, game_date TEXT, game_id TEXT, payload TEXT, state TEXT,
        start_time TEXT, fetched_at TEXT, source TEXT,
        PRIMARY KEY(league, game_date, game_id)
      );
      CREATE TABLE IF NOT EXISTS tennis_model_grades(
        league TEXT, game_id TEXT, winner TEXT, total_games_error REAL,
        PRIMARY KEY(league, game_id)
      );
      CREATE TABLE IF NOT EXISTS tennis_match_stats_overrides(
        league TEXT, game_date TEXT, game_id TEXT, home_aces INTEGER,
        away_aces INTEGER, source_url TEXT
      );
      CREATE TABLE IF NOT EXISTS tennis_model_locks(
        league TEXT NOT NULL, game_date TEXT NOT NULL, game_id TEXT NOT NULL,
        start_time TEXT NOT NULL, locked_at TEXT NOT NULL, projection TEXT NOT NULL,
        model_version TEXT, PRIMARY KEY(league, game_id)
      );
    """)
    return con


def _patch_route(monkeypatch, path, *, candidates=None):
    real_datetime = dt.datetime

    class FrozenDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz else NOW.replace(tzinfo=None)

    monkeypatch.setattr(misc.dt, "datetime", FrozenDateTime)
    monkeypatch.setattr(misc, "_db", lambda: _database(path))
    monkeypatch.setattr(tennis_bovada_odds, "bovada_odds", lambda *args: {
        "matchWinner": {"home": -150, "away": 130},
        "totalGames": {"line": 22.5, "over": -110, "under": -110},
        "capturedAt": "2026-10-17T11:45:00Z",
    })
    monkeypatch.setattr(projections, "stored_candidates", lambda *args: candidates)
    monkeypatch.setattr(projections, "needs_projection_refresh", lambda *args: False)
    monkeypatch.setattr(projections, "project_day", lambda *args: (_ for _ in ()).throw(AssertionError("unexpected recompute")))
    monkeypatch.setattr(projections, "store_candidates", lambda *args: None)


def test_lock_freezes_quote_as_provenance_and_reports_locked_status(tmp_path, monkeypatch):
    path = str(tmp_path / "tennis.sqlite3")
    con = _database(path)
    _snapshot(con)
    con.commit()
    con.close()
    candidate = {"probability": 0.7, "projectedWinner": "Home Player", "modelVersion": "page-v1"}
    _patch_route(monkeypatch, path, candidates={"match-1": candidate})

    payload = misc.tennis_model("2026-10-17", tour="atp")

    match, = payload["matches"]
    assert match["lockStatus"] == "locked"
    assert match["lockedAt"] == NOW.isoformat()
    assert match["frozenOdds"]["matchWinner"]["home"] == -150
    assert match["projection"] == candidate
    con = _database(path)
    stored = json.loads(con.execute(
        "SELECT projection FROM tennis_model_locks WHERE game_id='match-1'"
    ).fetchone()[0])
    con.close()
    assert stored["_frozenOdds"]["capturedAt"] == "2026-10-17T11:45:00Z"


def test_settled_locked_match_returns_winner_brier_from_frozen_probability(tmp_path, monkeypatch):
    path = str(tmp_path / "tennis.sqlite3")
    con = _database(path)
    _snapshot(con, state="post", start_time=(NOW - dt.timedelta(hours=2)).isoformat())
    frozen_odds = {"matchWinner": {"home": -140, "away": 120}, "totalGames": None,
                   "capturedAt": "2026-10-17T09:30:00Z"}
    con.execute(
        "INSERT INTO tennis_model_locks VALUES(?,?,?,?,?,?,?)",
        ("atp", "2026-10-17", "match-1", (NOW - dt.timedelta(hours=2)).isoformat(),
         (NOW - dt.timedelta(hours=3)).isoformat(),
         json.dumps({"probability": 0.7, "projectedWinner": "Home Player", "_frozenOdds": frozen_odds}),
         "page-v1"),
    )
    con.execute("INSERT INTO tennis_model_grades VALUES('atp','match-1','correct',1.0)")
    con.commit()
    con.close()
    _patch_route(monkeypatch, path)

    payload = misc.tennis_model("2026-10-17", tour="atp")
    match, = payload["matches"]

    assert match["grades"]["winnerBrier"] == pytest.approx(0.09)
    assert match["frozenOdds"] == frozen_odds
    assert match["lockStatus"] == "locked"
    assert payload["accuracy"] == {"winnerBrier": pytest.approx(0.09), "brierN": 1}


def test_past_match_without_lock_is_explicitly_missed(tmp_path, monkeypatch):
    path = str(tmp_path / "tennis.sqlite3")
    con = _database(path)
    _snapshot(con, state="post", start_time=(NOW - dt.timedelta(hours=2)).isoformat())
    con.commit()
    con.close()
    _patch_route(monkeypatch, path)

    payload = misc.tennis_model("2026-10-17", tour="atp")
    match, = payload["matches"]

    assert match["projection"] is None
    assert match["lockStatus"] == "missed"
    assert match["grades"] is None
    assert payload["accuracy"] == {"winnerBrier": None, "brierN": 0}


def test_winner_brier_rejects_missing_or_invalid_outcomes():
    assert misc._winner_brier(0.7, "correct") == pytest.approx(0.09)
    assert misc._winner_brier(0.7, "incorrect") == pytest.approx(0.49)
    assert misc._winner_brier(0.7, None) is None
    assert misc._winner_brier(1.2, "correct") is None


def test_v2_ledger_lock_does_not_borrow_regular_model_market_quote():
    match = {
        "home": "Home Player", "away": "Away Player",
        "identity": {
            "home": {"sackmann_player_id": "home-id"},
            "away": {"sackmann_player_id": "away-id"},
        },
        "projection": {"probability": 0.6}, "lockedAt": "page-lock",
        "frozenOdds": {"matchWinner": {"home": -120, "away": 105}},
        "grades": None,
    }
    record = {
        "locked_at": "v2-lock",
        "actual_winner": None,
        "payload": {
            "identity": {"home_sackmann_id": "home-id", "away_sackmann_id": "away-id"},
            "match_winner_home_probability": {"elo_informed_v2": 0.7},
            "home_player": "Home Player", "away_player": "Away Player",
            "model_version": "elo-informed-v2",
        },
    }

    assert misc._apply_tennis_v2_winner(match, record)
    assert match["lockedAt"] == "v2-lock"
    assert match["frozenOdds"] is None


def test_v2_accuracy_scores_the_locked_winner_confidence_against_final_winner():
    records = {
        "correct": {
            "payload": {"home_player": "Home", "away_player": "Away",
                        "match_winner_home_probability": {"elo_informed_v2": 0.7}},
            "actual_winner": "Home",
        },
        "incorrect": {
            "payload": {"home_player": "Home", "away_player": "Away",
                        "match_winner_home_probability": {"elo_informed_v2": 0.4}},
            "actual_winner": "Home",
        },
        "ungraded": {
            "payload": {"home_player": "Home", "away_player": "Away",
                        "match_winner_home_probability": {"elo_informed_v2": 0.8}},
            "actual_winner": None,
        },
    }

    assert misc._tennis_v2_winner_accuracy(records) == pytest.approx([0.09, 0.36])
