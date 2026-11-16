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


def test_page_view_previews_a_due_match_and_leaves_locking_to_the_timer(tmp_path, monkeypatch):
    path = str(tmp_path / "tennis.sqlite3")
    con = _database(path)
    _snapshot(con)
    con.commit()
    con.close()
    candidate = {"probability": 0.7, "projectedWinner": "Home Player", "modelVersion": "page-v1"}
    _patch_route(monkeypatch, path, candidates={"match-1": candidate})

    payload = misc.tennis_model("2026-10-17", tour="atp")

    match, = payload["matches"]
    assert match["lockStatus"] == "preview"
    assert match["lockedAt"] is None
    assert match["projection"] == candidate
    con = _database(path)
    assert con.execute("SELECT COUNT(*) FROM tennis_model_locks").fetchone()[0] == 0
    con.close()


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
    assert match["frozenOddsStatus"] == "captured"
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
    assert match["frozenOddsStatus"] is None
    assert match["grades"] is None
    assert payload["accuracy"] == {"winnerBrier": None, "brierN": 0}


def test_scheduled_sweep_freezes_bovada_odds_without_rewriting_later(tmp_path, monkeypatch):
    from tennis_lock_sweep import sweep
    import tennis_lock_sweep as scheduled

    db_path = str(tmp_path / "tennis.sqlite3")
    con = _database(db_path)
    con.executescript("""
      CREATE TABLE players (id INTEGER PRIMARY KEY, league TEXT, espn_id TEXT);
      CREATE TABLE prop_games (id INTEGER PRIMARY KEY, league TEXT, espn_event_id TEXT);
      CREATE TABLE props (
        id INTEGER PRIMARY KEY, game_id INTEGER, player_id INTEGER,
        market TEXT, line REAL, side TEXT, source TEXT,
        odds INTEGER, odds_captured_at TEXT
      );
      INSERT INTO players VALUES(100, 'atp', '501'), (200, 'atp', '502');
      INSERT INTO prop_games VALUES(1, 'atp', 'match-1');
    """)
    quote_time = (NOW - dt.timedelta(minutes=10)).isoformat()
    con.executemany(
        "INSERT INTO props(game_id,player_id,market,line,side,source,odds,odds_captured_at) "
        "VALUES (1,?,'match_winner',0.5,'over','bovada',?,?)",
        [(100, -150, quote_time), (200, 130, quote_time)],
    )
    match = {
        "gameId": "match-1", "tour": "atp", "startTime": START,
        "homeAthleteId": "501", "awayAthleteId": "502",
    }
    candidate = {"probability": 0.7, "projectedWinner": "Home Player", "modelVersion": "page-v1"}
    monkeypatch.setattr(scheduled, "due_matches", lambda *args: {("atp", "2026-10-17"): [match]})
    monkeypatch.setattr(scheduled, "stored_candidates", lambda *args: {"match-1": candidate})
    monkeypatch.setattr(scheduled, "needs_projection_refresh", lambda *args: False)

    first = sweep(con, NOW)
    assert first["locked"] == 1
    assert first["quotes_frozen"] == 1
    saved = con.execute("SELECT projection FROM tennis_model_locks WHERE game_id='match-1'").fetchone()[0]
    frozen = json.loads(saved)
    assert frozen["_frozenOdds"]["matchWinner"] == {"home": -150, "away": 130}
    assert frozen["_frozenOdds"]["capturedAt"] == quote_time
    assert candidate.get("_frozenOdds") is None

    # A later market refresh must never rewrite an already-locked forecast.
    con.execute("UPDATE props SET odds=-110, odds_captured_at=? WHERE player_id=100",
                ((NOW + dt.timedelta(minutes=5)).isoformat(),))
    second = sweep(con, NOW + dt.timedelta(minutes=10))
    assert second["already_locked"] == 1
    assert con.execute("SELECT projection FROM tennis_model_locks WHERE game_id='match-1'").fetchone()[0] == saved
    con.close()


def test_scheduled_sweep_marks_unavailable_quote_without_fabricating_prices(tmp_path, monkeypatch):
    from tennis_lock_sweep import sweep
    import tennis_lock_sweep as scheduled

    db_path = str(tmp_path / "tennis.sqlite3")
    con = _database(db_path)
    con.executescript("""
      CREATE TABLE players (id INTEGER PRIMARY KEY, league TEXT, espn_id TEXT);
      CREATE TABLE prop_games (id INTEGER PRIMARY KEY, league TEXT, espn_event_id TEXT);
      CREATE TABLE props (
        id INTEGER PRIMARY KEY, game_id INTEGER, player_id INTEGER,
        market TEXT, line REAL, side TEXT, source TEXT,
        odds INTEGER, odds_captured_at TEXT
      );
    """)
    match = {
        "gameId": "match-2", "tour": "atp", "startTime": START,
        "homeAthleteId": "501", "awayAthleteId": "502",
    }
    candidate = {"probability": 0.65, "projectedWinner": "Home Player", "modelVersion": "page-v1"}
    monkeypatch.setattr(scheduled, "due_matches", lambda *args: {("atp", "2026-10-17"): [match]})
    monkeypatch.setattr(scheduled, "stored_candidates", lambda *args: {"match-2": candidate})
    monkeypatch.setattr(scheduled, "needs_projection_refresh", lambda *args: False)
    report = sweep(con, NOW)
    stored = json.loads(con.execute(
        "SELECT projection FROM tennis_model_locks WHERE game_id='match-2'"
    ).fetchone()[0])
    assert report["locked"] == 1
    assert report["quotes_unavailable"] == 1
    assert "_frozenOdds" in stored and stored["_frozenOdds"] is None
    con.close()


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
    assert match["frozenOddsStatus"] == "legacy"

    independent_quote = {
        "matchWinner": {"home": -135, "away": 115},
        "totalGames": None, "capturedAt": "2026-10-17T09:00:00+00:00",
    }
    record["payload"]["frozen_bovada_odds"] = independent_quote
    assert misc._apply_tennis_v2_winner(match, record)
    assert match["frozenOdds"] == independent_quote
    assert match["frozenOddsStatus"] == "captured"


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
