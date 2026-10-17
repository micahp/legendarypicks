"""Prospective V2 locks and grading must be safe to retry and fail closed."""
import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import tennis_v2_research_ledger as ledger  # noqa: E402


def _forecast():
    return {
        "tour": "atp",
        "game_id": "match-1",
        "locked_at": "2026-10-16T22:04:19+00:00",
        "start_time": "2026-10-17T08:30:00+00:00",
        "model_version": ledger.MODEL_VERSION,
        "home_player": "Home Player",
        "away_player": "Away Player",
        # Omit the direct ESPN IDs to exercise legacy-lock crosswalk resolution.
        "identity": {"home_sackmann_id": "100", "away_sackmann_id": "200"},
        "match_winner_home_probability": {
            "calibrated_elo": 0.61,
            "elo_plus_point_features": 0.62,
            "elo_informed_v2": 0.63,
        },
        "match_structure_probability": {
            "elo_informed_v2": {
                "deciding_set_probability": 0.3,
                "any_tiebreak_probability": 0.4,
            }
        },
        "total_games_pmf": {
            "direct_format_surface_competitiveness": {"20": 0.2, "30": 0.5, "40": 0.3},
            "elo_informed_v2": {"20": 0.3, "30": 0.4, "40": 0.3},
        },
    }


def _final_game(home_id="2375", away_id="3212", status="Final"):
    return {
        "status": status,
        "home": {
            "athlete_id": home_id,
            "name": "Home Player",
            "score": "2",
            "sets": [6, 4, 6],
        },
        "away": {
            "athlete_id": away_id,
            "name": "Away Player",
            "score": "1",
            "sets": [4, 6, 3],
        },
    }


def _source_db(path, game=None, state="post"):
    con = sqlite3.connect(path)
    con.executescript("""
      CREATE TABLE players(id INTEGER, league TEXT, espn_id TEXT);
      CREATE TABLE player_source_ids(
        player_id INTEGER, source TEXT, league TEXT, source_player_key TEXT
      );
      CREATE TABLE scoreboard_snapshots(
        league TEXT, game_id TEXT, payload TEXT, state TEXT, fetched_at TEXT
      );
    """)
    con.executemany("INSERT INTO players VALUES(?,?,?)", [
        (1, "atp", "2375"), (2, "atp", "3212"),
    ])
    con.executemany("INSERT INTO player_source_ids VALUES(?,?,?,?)", [
        (1, "sackmann", "atp", "100"), (2, "sackmann", "atp", "200"),
    ])
    if game is not None:
        con.execute(
            "INSERT INTO scoreboard_snapshots VALUES(?,?,?,?,?)",
            ("atp", "match-1", json.dumps(game), state, "2026-10-17T12:00:00+00:00"),
        )
    con.commit()
    con.close()


def _ledger_db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    ledger._ensure_ledger(con)
    return con


def test_forecast_lock_is_immutable_across_retries():
    con = _ledger_db()
    original = _forecast()
    assert ledger._store_forecast(con, original) == 1
    con.commit()

    retry = dict(original)
    retry["locked_at"] = "2026-10-16T22:34:19+00:00"
    retry["match_winner_home_probability"] = {"elo_informed_v2": 0.99}
    assert ledger._store_forecast(con, retry) == 0

    stored = con.execute(
        "SELECT locked_at,payload,payload_sha256 FROM tennis_v2_research_forecasts"
    ).fetchone()
    assert stored["locked_at"] == original["locked_at"]
    assert json.loads(stored["payload"]) == original
    assert stored["payload_sha256"] == hashlib.sha256(stored["payload"].encode()).hexdigest()


def test_grading_uses_verified_side_identity_and_reruns_idempotently(tmp_path):
    source_path = tmp_path / "source.sqlite3"
    _source_db(source_path, _final_game())
    con = _ledger_db()
    ledger._store_forecast(con, _forecast())
    con.commit()

    first = ledger.grade_finals(con, str(source_path), dt.datetime(2026, 10, 17, tzinfo=dt.timezone.utc))
    second = ledger.grade_finals(con, str(source_path), dt.datetime(2026, 10, 18, tzinfo=dt.timezone.utc))

    assert first == {"graded": 1, "identity_mismatch": 0}
    assert second == {"graded": 0, "identity_mismatch": 0}
    grade = con.execute(
        "SELECT actual_winner,actual_total_games,actual_deciding_set "
        "FROM tennis_v2_research_grades"
    ).fetchone()
    assert tuple(grade) == ("Home Player", 29, 1)


def test_side_order_mismatch_is_not_scored(tmp_path):
    source_path = tmp_path / "source.sqlite3"
    _source_db(source_path, _final_game(home_id="3212", away_id="2375"))
    con = _ledger_db()
    ledger._store_forecast(con, _forecast())
    con.commit()

    result = ledger.grade_finals(con, str(source_path), dt.datetime(2026, 10, 17, tzinfo=dt.timezone.utc))

    assert result == {"graded": 0, "identity_mismatch": 1}
    assert con.execute("SELECT COUNT(*) FROM tennis_v2_research_grades").fetchone()[0] == 0


@pytest.mark.parametrize("status", ["Canceled", "Postponed", "Retired", "Walkover"])
def test_nonstandard_or_void_match_results_are_not_graded(tmp_path, status):
    source_path = tmp_path / "source.sqlite3"
    _source_db(source_path, _final_game(status=status))
    con = _ledger_db()
    ledger._store_forecast(con, _forecast())
    con.commit()

    result = ledger.grade_finals(con, str(source_path), dt.datetime(2026, 10, 17, tzinfo=dt.timezone.utc))

    assert result == {"graded": 0, "identity_mismatch": 0}
    assert con.execute("SELECT COUNT(*) FROM tennis_v2_research_grades").fetchone()[0] == 0


def test_new_lock_stores_source_identity_ids():
    game = {
        "home": {"athlete_id": "2375"},
        "away": {"athlete_id": "3212"},
    }
    identity = ledger._forecast_identity(game, ("100", "200"))
    assert identity == {
        "home_sackmann_id": "100",
        "away_sackmann_id": "200",
        "home_espn_id": "2375",
        "away_espn_id": "3212",
    }
