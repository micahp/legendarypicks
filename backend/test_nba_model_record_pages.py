import datetime as dt
import json

from fastapi import Response

from nba_model_store import (
    LOCK_LEAD,
    MODEL_INFO,
    MODEL_VERSION,
    export_payload,
    export_projection_payload,
    export_record_page,
    grade_forecasts,
    iso_utc,
    lock_forecasts,
    open_db,
    upsert_previews,
)
from routers import nba_model

UTC = dt.timezone.utc


def _lock_game(con, game_id: str, kickoff: str) -> None:
    start = dt.datetime.fromisoformat(kickoff.replace("Z", "+00:00")).astimezone(UTC)
    locked_at = start - LOCK_LEAD
    captured_at = iso_utc(locked_at)
    rows = []
    for model in MODEL_INFO:
        rows.append({
            "game_id": game_id,
            "model": model["id"],
            "season": 2027,
            "scheduled_start_utc": iso_utc(start),
            "home_team": "BOS",
            "away_team": "NYK",
            "model_version": MODEL_VERSION[model["id"]],
            "forecast": {
                "home_win_probability": 0.6,
                "score_forecast_available": model["projects_scores"],
                "projected_home_points": 111.0 if model["projects_scores"] else None,
                "projected_away_points": 105.0 if model["projects_scores"] else None,
            },
            "feature_snapshot": {"cutoff_utc": captured_at, "history_games": 10},
            "source_hash": "fixture-hash-" + game_id,
            "previewed_at_utc": captured_at,
        })
    assert upsert_previews(con, rows, locked_at) == len(MODEL_INFO)
    assert lock_forecasts(con, rows, locked_at)["inserted_games"] == 1


def _verified_result(game_id: str) -> dict:
    return {
        game_id: {
            "completed": True,
            "summary_validated": True,
            "source_event_id": "event-" + game_id,
            "source_hash": "result-hash-" + game_id,
            "source": "test fixture",
            "home_team": "BOS",
            "away_team": "NYK",
            "home_score": 112,
            "away_score": 105,
        }
    }


def test_projection_view_omits_past_game_rows_but_keeps_full_season_summaries(tmp_path, monkeypatch):
    path = tmp_path / "nba-model.sqlite3"
    con = open_db(str(path))
    try:
        _lock_game(con, "old-game", "2026-10-01T23:00:00Z")
        _lock_game(con, "future-game", "2026-11-04T23:00:00Z")
        grade_forecasts(con, _verified_result("old-game"), dt.datetime(2026, 11, 5, tzinfo=UTC))
        reference = export_payload(con, 2027, {}, dt.datetime(2026, 10, 31, 12, tzinfo=UTC))
        projection_view = export_projection_payload(con, 2027, {}, dt.datetime(2026, 10, 31, 12, tzinfo=UTC))
        assert projection_view["records"] == reference["records"]
    finally:
        con.close()

    monkeypatch.setattr(nba_model, "MODEL_DB", str(path))
    response = nba_model.nba_model_locks(Response(), 2027, "projections")
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert [game["game_id"] for game in payload["games"]] == ["future-game"]
    assert payload["records"]["G3"]["locked"] == 2
    assert payload["records"]["G3"]["graded"] == 1
    assert payload["records"]["G3"]["awaiting"] == 1
    assert "feature_snapshot" not in payload["games"][0]["models"]["G3"]


def test_record_api_pages_complete_local_date_groups_and_only_the_selected_model(tmp_path, monkeypatch):
    path = tmp_path / "nba-model.sqlite3"
    con = open_db(str(path))
    try:
        # Two UTC dates fall on the same Chicago game date (October 1).
        _lock_game(con, "sep-30", "2026-10-01T04:00:00Z")
        _lock_game(con, "oct-1-a", "2026-10-02T00:00:00Z")
        _lock_game(con, "oct-1-b", "2026-10-02T04:00:00Z")
        _lock_game(con, "oct-2", "2026-10-03T00:00:00Z")
        _lock_game(con, "oct-3", "2026-10-04T00:00:00Z")
        grade_forecasts(con, _verified_result("oct-3"), dt.datetime(2026, 10, 5, tzinfo=UTC))
    finally:
        con.close()

    monkeypatch.setattr(nba_model, "MODEL_DB", str(path))
    first_response = nba_model.nba_model_record(
        Response(), 2027, "G2", 2, None, "America/Chicago",
    )
    first = json.loads(first_response.body)
    assert first_response.status_code == 200
    assert first["model"] == "G2"
    assert [game["game_id"] for game in first["games"]] == ["oct-3", "oct-2"]
    assert all(list(game["models"]) == ["G2"] for game in first["games"])
    assert first["has_more"] is True
    assert first["next_before"] == "2026-10-02"
    assert first["record"]["locked"] == 5
    assert first["record"]["graded"] == 1

    second_response = nba_model.nba_model_record(
        Response(), 2027, "G2", 2, first["next_before"], "America/Chicago",
    )
    second = json.loads(second_response.body)
    assert [game["game_id"] for game in second["games"]] == ["oct-1-b", "oct-1-a", "sep-30"]
    assert second["has_more"] is False
    assert second["next_before"] is None
    assert {game["models"]["G2"]["grade"] is not None for game in second["games"]} == {False}


def test_record_api_uses_append_only_grade_corrections(tmp_path, monkeypatch):
    path = tmp_path / "nba-model.sqlite3"
    con = open_db(str(path))
    try:
        _lock_game(con, "corrected-game", "2026-10-01T23:00:00Z")
        initial = _verified_result("corrected-game")["corrected-game"]
        initial["observed_at_utc"] = "2026-10-02T00:00:00Z"
        assert grade_forecasts(con, {"corrected-game": initial},
                               dt.datetime(2026, 10, 2, 1, tzinfo=UTC))["graded"] == 3

        corrected = {
            **initial, "away_score": 106, "source_hash": "corrected-final-hash",
            "observed_at_utc": "2026-10-02T01:30:00Z",
        }
        assert grade_forecasts(con, {"corrected-game": corrected},
                               dt.datetime(2026, 10, 2, 2, tzinfo=UTC))["corrected"] == 3
        assert con.execute(
            "SELECT final_away_score FROM nba_model_grades WHERE game_id='corrected-game' AND model='G3'"
        ).fetchone()[0] == 105
    finally:
        con.close()

    monkeypatch.setattr(nba_model, "MODEL_DB", str(path))
    response = nba_model.nba_model_record(Response(), 2027, "G3", 7, None, "America/Chicago")
    payload = json.loads(response.body)
    game = payload["games"][0]

    assert response.status_code == 200
    assert game["game_id"] == "corrected-game"
    assert game["result"]["away_score"] == 106
    assert game["models"]["G3"]["grade"]["away_score"] == 106
    assert payload["record"]["graded"] == 1
    assert payload["record"]["away_points_mae"] == 1.0


def test_record_page_rejects_invalid_cursor_timezone_model_and_date_count(tmp_path):
    path = tmp_path / "nba-model.sqlite3"
    con = open_db(str(path))
    try:
        for kwargs, message in (
            ({"model": "bad-model"}, "unknown NBA model"),
            ({"days": 0}, "days must be between"),
            ({"before": "yesterday"}, "before must be an ISO local date"),
            ({"timezone_name": "Mars/Olympus"}, "unknown timezone"),
        ):
            args = {"season": 2027, "model": "G3", "days": 7, "before": None, "timezone_name": "UTC"}
            args.update(kwargs)
            try:
                export_record_page(con, **args)
            except ValueError as exc:
                assert message in str(exc)
            else:
                raise AssertionError("expected invalid pagination parameters to fail")
    finally:
        con.close()
