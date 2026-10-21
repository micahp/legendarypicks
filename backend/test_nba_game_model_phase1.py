from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException, Response

from nba_game_model import MODEL_INFO, backtest
from nba_model_data import TeamGame
from nba_model_runtime import build_preview_rows, refresh_completed_games, require_dev_picks_db
from nba_model_store import (MODEL_VERSION, NBAModelStoreError,
                             grade_forecasts, import_history, latest_live_games,
                             latest_verified_results,
                             open_db, store_live_observation, upsert_previews, lock_forecasts)
from fastapi import HTTPException
from routers import nba_model as nba_model_router

UTC = dt.timezone.utc


def _game(season: int, date: str, ident: str, home: str = "BOS", away: str = "NYK",
          hs: int = 110, aws: int = 104) -> TeamGame:
    return TeamGame(ident, season, date, home, away, hs, aws,
                    88, 20, 10, 13, 87, 19, 9, 14, f"00{season}{ident}")


def _forecast_rows(kickoff: str, previewed: str, game_id: str = "NBA001") -> list[dict]:
    rows = []
    for model in MODEL_INFO:
        rows.append({
            "game_id": game_id, "model": model["id"], "season": 2027,
            "scheduled_start_utc": kickoff, "home_team": "BOS", "away_team": "NYK",
            "model_version": MODEL_VERSION[model["id"]],
            "forecast": {
                "home_win_probability": 0.6,
                "score_forecast_available": model["projects_scores"],
                "projected_home_points": 111.0 if model["projects_scores"] else None,
                "projected_away_points": 105.0 if model["projects_scores"] else None,
            },
            "feature_snapshot": {"cutoff_utc": previewed, "history_games": 10},
            "source_hash": "feature-sha256", "previewed_at_utc": previewed,
        })
    return rows


def test_backtest_uses_one_chronological_eligible_set_for_all_models():
    games = []
    for season in range(2017, 2026):
        games.append(_game(season, f"{season}-02-01", f"g{season}"))
    result = backtest(games)
    assert result["eligible_games"] == {
        "train": 5, "validation": 2, "test": 2, "refit_through_2025_26": 9,
    }
    assert all(value["games"] == 2 for value in result["metrics"]["test"].values())
    assert result["metrics"]["test"]["G1"].get("home_points_mae") is None
    assert result["metrics"]["test"]["G3"]["distribution"]


def test_history_import_is_season_pinned_and_additive(tmp_path: Path):
    model = open_db(str(tmp_path / "model.sqlite3"))
    try:
        games = [{**_game(2017, "2017-10-18", "a").__dict__}]
        hashes = {"team_box_2017.parquet": "a" * 64,
                  "nba_schedule_2017.parquet": "b" * 64}
        assert import_history(model, games, hashes, []) == 1
        assert model.execute("select count(*) from nba_model_history").fetchone()[0] == 1
        # Adding a later season leaves the earlier season's release identity stable.
        later_hashes = {**hashes, "team_box_2018.parquet": "c" * 64,
                        "nba_schedule_2018.parquet": "d" * 64}
        assert import_history(model, [{**_game(2018, "2018-10-18", "b").__dict__}], later_hashes, []) == 1
        assert model.execute("select count(*) from nba_model_history").fetchone()[0] == 2
        with pytest.raises(NBAModelStoreError, match="conflicts"):
            import_history(model, [{**_game(2017, "2017-10-18", "a", hs=99).__dict__}], later_hashes, [])
    finally:
        model.close()


def test_locks_are_t90_only_atomic_immutable_and_grade_only_verified_finals(tmp_path: Path):
    model = open_db(str(tmp_path / "model.sqlite3"))
    kickoff = "2026-10-21T23:00:00Z"
    previewed = "2026-10-21T21:28:00Z"
    now = dt.datetime(2026, 10, 21, 21, 30, tzinfo=UTC)
    try:
        rows = _forecast_rows(kickoff, previewed)
        assert upsert_previews(model, rows, now) == 3
        report = lock_forecasts(model, rows, now)
        assert report["inserted_games"] == 1
        assert model.execute("select count(*) from nba_model_locks").fetchone()[0] == 3
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            model.execute("update nba_model_locks set source_hash='changed'")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            model.execute("delete from nba_model_locks")
        model.rollback()

        absent = grade_forecasts(model, {}, dt.datetime(2026, 10, 21, 23, 1, tzinfo=UTC))
        assert absent["awaiting_verified_final"] == 3
        result = {"NBA001": {
            "completed": True, "summary_validated": True, "source_event_id": "ESPN001",
            "source_hash": "final-hash", "source": "ESPN scoreboard+summary",
            "home_team": "BOS", "away_team": "NYK", "home_score": 112, "away_score": 107,
        }}
        assert grade_forecasts(model, result, dt.datetime(2026, 10, 21, 23, 2, tzinfo=UTC))["graded"] == 3
        assert len(latest_verified_results(model)) == 0  # locks are not final observations
        with pytest.raises(NBAModelStoreError, match="conflicts"):
            grade_forecasts(model, {"NBA001": {**result["NBA001"], "home_score": 113}},
                            dt.datetime(2026, 10, 21, 23, 3, tzinfo=UTC))
    finally:
        model.close()


def test_lock_window_does_not_create_retrospective_forecast(tmp_path: Path):
    model = open_db(str(tmp_path / "model.sqlite3"))
    rows = _forecast_rows("2026-10-21T23:00:00Z", "2026-10-21T21:28:00Z")
    try:
        report = lock_forecasts(model, rows, dt.datetime(2026, 10, 21, 21, 33, tzinfo=UTC))
        assert report["missed_window_games"] == 1
        assert model.execute("select count(*) from nba_model_locks").fetchone()[0] == 0
        assert upsert_previews(model, rows, dt.datetime(2026, 10, 21, 23, 1, tzinfo=UTC)) == 0
    finally:
        model.close()


def test_jobs_require_a_dev_database_path(tmp_path: Path):
    dev = tmp_path / "picks.dev.db"
    dev.touch()
    assert require_dev_picks_db(str(dev)) == str(dev.resolve())
    prod = tmp_path / "picks.db"
    prod.touch()
    with pytest.raises(RuntimeError, match="dev-only"):
        require_dev_picks_db(str(prod))


def test_read_api_is_dev_scoped_and_exposes_the_benchmark(tmp_path: Path, monkeypatch):
    dev = tmp_path / "picks.dev.db"
    dev.touch()
    model = tmp_path / "nba-model.dev.sqlite3"
    monkeypatch.setenv("LP_DB_PATH", str(dev))
    monkeypatch.setenv("NBA_MODEL_DB_PATH", str(model))
    monkeypatch.setattr(nba_model_router, "MODEL_DB", str(model))
    response = nba_model_router.nba_model_locks(Response(), 2027)
    payload = json.loads(response.body)
    assert payload["state"] == "awaiting_history_import"
    assert payload["benchmark"]["metrics"]["test"]["G3"]["winner_brier"] == pytest.approx(0.213386, abs=1e-6)

    prod = tmp_path / "picks.db"
    prod.touch()
    monkeypatch.setenv("LP_DB_PATH", str(prod))
    with pytest.raises(HTTPException) as error:
        nba_model_router.nba_model_locks(Response(), 2027)
    assert error.value.status_code == 404


def _fixture_schedule(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute("""CREATE TABLE nba_schedule (
      game_id TEXT, season INTEGER, season_type TEXT, game_date TEXT, start_utc TEXT,
      away_team TEXT, home_team TEXT, status INTEGER, away_score INTEGER, home_score INTEGER,
      espn TEXT)""")
    connection.execute("""INSERT INTO nba_schedule VALUES(
      '0022600001',2027,'REG','2026-10-20','2026-10-20T23:00:00Z',
      'BOS','DET',1,NULL,NULL,'401909088')""")
    connection.commit()
    connection.close()


def test_live_ingest_requires_scoreboard_summary_schedule_and_box_agreement(tmp_path: Path):
    picks = tmp_path / "picks.dev.db"
    _fixture_schedule(picks)
    model_path = tmp_path / "nba-model.dev.sqlite3"
    now = dt.datetime(2026, 10, 21, 1, 0, tzinfo=UTC)
    event = {
        "game_id": "401909088", "date": "2026-10-21T00:00:00Z", "completed": True,
        "home": {"abbrev": "DET", "score": 109}, "away": {"abbrev": "BOS", "score": 102},
    }
    sides = [
        {"homeAway": "home", "team": {"abbreviation": "DET"}, "score": "109"},
        {"homeAway": "away", "team": {"abbreviation": "BOS"}, "score": "102"},
    ]
    box = [
        {"homeAway": "home", "team": {"abbreviation": "DET"}, "statistics": [
            {"name": "fieldGoalsMade-fieldGoalsAttempted", "displayValue": "40-88"},
            {"name": "freeThrowsMade-freeThrowsAttempted", "displayValue": "15-20"},
            {"name": "offensiveRebounds", "displayValue": "10"},
            {"name": "totalTurnovers", "displayValue": "12"},
        ]},
        {"homeAway": "away", "team": {"abbreviation": "BOS"}, "statistics": [
            {"name": "fieldGoalsMade-fieldGoalsAttempted", "displayValue": "38-85"},
            {"name": "freeThrowsMade-freeThrowsAttempted", "displayValue": "14-18"},
            {"name": "offensiveRebounds", "displayValue": "9"},
            {"name": "totalTurnovers", "displayValue": "11"},
        ]},
    ]
    summary = {"header": {"competitions": [{"status": {"type": {"completed": True}},
                                                    "competitors": sides}]},
               "boxscore": {"teams": box}}

    def scoreboard(_league: str, _start: str, _end: str):
        return {"2026-10-20": [event]}, 1

    report = refresh_completed_games(str(picks), str(model_path), now,
                                     games_by_day=scoreboard,
                                     summary_fetch=lambda _league, _event_id: summary)
    assert report["stored"] == 1
    model = open_db(str(model_path), readonly=True)
    try:
        row = model.execute("select * from nba_model_live_game_observations").fetchone()
        assert row["nba_game_id"] == "0022600001"
        assert row["final_confirmed"] == 1
        assert len(row["source_hash"]) == 64
    finally:
        model.close()

    summary["header"]["competitions"][0]["competitors"][0]["score"] = "108"
    rejected = refresh_completed_games(str(picks), str(tmp_path / "rejected.sqlite3"), now,
                                       games_by_day=scoreboard,
                                       summary_fetch=lambda _league, _event_id: summary)
    assert rejected["stored"] == 0
    assert rejected["rejected"]


def test_pregame_builder_excludes_current_day_results_and_uses_only_prior_games(tmp_path: Path):
    picks = tmp_path / "picks.dev.db"
    _fixture_schedule(picks)
    source = sqlite3.connect(picks)
    source.execute("""INSERT INTO nba_schedule VALUES(
      '0022600005',2027,'REG','2026-10-22','2026-10-22T23:00:00Z',
      'NYK','BOS',1,NULL,NULL,NULL)""")
    source.commit()
    source.close()

    model_path = tmp_path / "nba-model.dev.sqlite3"
    model = open_db(str(model_path))
    try:
        historical = _game(2017, "2017-02-01", "history")
        import_history(model, [historical.__dict__], {
            "team_box_2017.parquet": "a" * 64,
            "nba_schedule_2017.parquet": "b" * 64,
        }, [])
        for ident, date in (("0022600002", "2026-10-21"), ("0022600003", "2026-10-22")):
            store_live_observation(model, {
                "nba_game_id": ident, "season": 2027, "game_date": date,
                "scheduled_start_utc": f"{date}T23:00:00Z", "source_event_id": f"ESPN-{ident}",
                "home_team": "BOS", "away_team": "NYK", "home_score": 110, "away_score": 104,
                "home_stats": {"field_goals_attempted": 88, "free_throws_attempted": 20,
                               "offensive_rebounds": 10, "turnovers": 13},
                "away_stats": {"field_goals_attempted": 87, "free_throws_attempted": 19,
                               "offensive_rebounds": 9, "turnovers": 14},
                "source_hash": f"hash-{ident}", "source": "test ESPN feed",
                "final_confirmed": True, "observed_at_utc": "2026-10-22T01:00:00Z",
            })
        store_live_observation(model, {
            "nba_game_id": "0022600002", "season": 2027, "game_date": "2026-10-21",
            "scheduled_start_utc": "2026-10-21T23:00:00Z", "source_event_id": "ESPN-corrected",
            "home_team": "BOS", "away_team": "NYK", "home_score": 111, "away_score": 104,
            "home_stats": {"field_goals_attempted": 89, "free_throws_attempted": 20,
                           "offensive_rebounds": 10, "turnovers": 13},
            "away_stats": {"field_goals_attempted": 87, "free_throws_attempted": 19,
                           "offensive_rebounds": 9, "turnovers": 14},
            "source_hash": "future-correction", "source": "test ESPN correction",
            "final_confirmed": True, "observed_at_utc": "2026-10-23T01:00:00Z",
        })
        captured = latest_live_games(model, before_utc="2026-10-22T18:00:00Z")
        prior_game = next(row for row in captured if row["schedule_game_id"] == "0022600002")
        assert prior_game["home_score"] == 110
        assert prior_game["source_hash"] == "hash-0022600002"
    finally:
        model.close()

    rows = build_preview_rows(str(picks), str(model_path),
                              dt.datetime(2026, 10, 22, 18, 0, tzinfo=UTC))
    assert len(rows) == 3
    assert {row["model"] for row in rows} == {"G1", "G2", "G3"}
    snapshot = rows[0]["feature_snapshot"]
    assert snapshot["history_date_exclusive"] == "2026-10-22"
    assert snapshot["fitted_through"] == "2026-10-21"
    assert snapshot["history_games"] == 2
    assert snapshot["live_source_hashes"] == ["hash-0022600002"]
