from __future__ import annotations

import datetime as dt
import contextlib
import io
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException, Response

from nba_game_model import (MODEL_INFO, _bootstrap_loss,
                            _date_clustered_coverage_bootstrap,
                            _date_clustered_paired_bootstrap, backtest)
from backtest_nba_game_model import print_report
from nba_model_data import TeamGame
from nba_model_runtime import build_preview_rows, refresh_completed_games, require_dev_picks_db
from nba_model_store import (MODEL_VERSION, NBAModelStoreError,
                             grade_forecasts, grade_unlocked_previews, export_payload, lock_previews_late, import_history, latest_live_games,
                             latest_verified_results,
                             open_db, store_live_observation, upsert_previews, lock_forecasts)
from fastapi import HTTPException
from routers import nba_model as nba_model_router

UTC = dt.timezone.utc


def test_benchmark_stdout_reports_confirmation_population_metrics_and_pairs():
    benchmark_path = Path(__file__).resolve().parents[1] / "research" / "nba-game-model" / "benchmark.json"
    report = json.loads(benchmark_path.read_text(encoding="utf-8"))
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        print_report(report, benchmark_path)
    stdout = output.getvalue()

    assert "eligible confirmation regular-season games: 1229" in stdout
    assert "confirm_2026 metrics:" in stdout
    assert "G3: n=1229" in stdout
    assert "confirm_2026 paired comparisons: 164 NBA local game dates" in stdout
    confirm_output = stdout.split("confirm_2026 paired comparisons:", 1)[1].split("report:", 1)[0]
    assert sum("CI95=" in line for line in confirm_output.splitlines()) == 32


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
    for season in range(2017, 2027):
        games.append(_game(season, f"{season}-02-01", f"g{season}"))
    result = backtest(games)
    assert result["eligible_games"] == {
        "train": 5, "validation": 2, "test": 2, "refit_through_2025_26": 10,
    }
    assert all(value["games"] == 2 for value in result["metrics"]["test"].values())
    assert result["metrics"]["test"]["G1"].get("home_points_mae") is None
    assert result["metrics"]["test"]["G3"]["distribution"]
    assert result["protocol"]["confirm_seasons_end_year"] == [2026]
    assert set(result["metrics"]["confirm_2026"]) == set(result["metrics"]["test"])
    for model in result["metrics"]["test"]:
        assert set(result["metrics"]["confirm_2026"][model]) == set(
            result["metrics"]["test"][model]
        )
    assert set(result["metrics"]["confirm_2026"]["G3"]["distribution"]) == set(
        result["metrics"]["test"]["G3"]["distribution"]
    )
    assert all(value["games"] == 1 for value in result["metrics"]["confirm_2026"].values())
    assert result["metrics"]["confirm_2026"]["G3"]["distribution"]["coverage_uncertainty"]
    assert result["uncertainty"]["confirm_2026"]["games"] == 1
    assert result["uncertainty"]["confirm_2026"]["date_clusters"] == 1
    assert len(result["uncertainty"]["confirm_2026"]["comparisons"]) == 32
    confirm_comparisons = [
        (row["metric"], row["candidate"], row["comparator"])
        for row in result["uncertainty"]["confirm_2026"]["comparisons"]
    ]
    test_comparisons = [
        (row["metric"], row["candidate"], row["comparator"])
        for row in result["uncertainty"]["test"]["comparisons"]
    ]
    assert confirm_comparisons == test_comparisons


def test_backtest_rejects_confirmation_before_test_chronologically():
    games = [_game(season, f"{season}-02-01", f"g{season}")
             for season in range(2017, 2025)]
    games.extend((
        _game(2025, "2026-02-01", "test-late"),
        _game(2026, "2026-01-01", "confirm-early"),
    ))
    with pytest.raises(ValueError, match="test games are not strictly before confirmation"):
        backtest(games)


def test_uncertainty_bootstrap_pairs_models_and_resamples_whole_dates():
    def row(game_date: str, ident: str, g1_p: float, g2_p: float) -> dict:
        distribution = {"margin_crps": 8.0, "total_crps": 12.0}
        return {
            "game_id": ident, "season": 2025, "game_date": game_date,
            "home_score": 110, "away_score": 100, "outcome": 1,
            "models": {
                "G1": {"p_home": g1_p, "home_points": None, "away_points": None},
                "G2": {"p_home": g2_p, "home_points": 105.0, "away_points": 102.0},
                "G3": {"p_home": 0.6, "home_points": 106.0, "away_points": 101.0,
                       "distribution_metrics": distribution},
                "B0 Home-rate baseline": {"p_home": 0.54,
                                          "home_points": None, "away_points": None},
                "B1 Training league-points baseline": {
                    "p_home": 0.54, "home_points": 100.0, "away_points": 95.0,
                },
            },
        }

    rows = [
        row("2025-01-01", "a1", 0.9, 0.1),
        row("2025-01-01", "a2", 0.9, 0.1),
        row("2025-01-02", "b1", 0.1, 0.9),
        row("2025-01-02", "b2", 0.1, 0.9),
    ]
    result = _date_clustered_paired_bootstrap(rows, replicates=2000, seed=13)
    assert result == _date_clustered_paired_bootstrap(rows, replicates=2000, seed=13)
    assert result["games"] == 4
    assert result["date_clusters"] == 2
    assert len(result["comparisons"]) == 32
    comparison = next(item for item in result["comparisons"]
                      if item["metric"] == "winner_brier"
                      and item["candidate"] == "G1" and item["comparator"] == "G2")
    assert comparison["delta_candidate_minus_comparator"] == pytest.approx(0.0)
    # With two whole-date clusters, each bootstrap delta can only be -0.8, 0, or +0.8.
    assert comparison["ci95_percentile"] == pytest.approx([-0.8, 0.8])
    assert 0.15 < comparison["p_candidate_better"] < 0.35


def test_g3_coverage_bootstrap_resamples_whole_dates_deterministically():
    rows = []
    for game_date, covered, width in (
        ("2025-01-01", 1, 10.0),
        ("2025-01-02", 0, 20.0),
        ("2025-01-03", 0, 30.0),
    ):
        for game_number in range(2):
            rows.append({
                "game_id": f"{game_date}-{game_number}", "season": 2025,
                "game_date": game_date,
                "models": {"G3": {"distribution_metrics": {
                    "margin_80_covered": covered,
                    "margin_80_width": width,
                    "total_80_covered": covered,
                    "total_80_width": width + 10.0,
                }}},
            })

    result = _date_clustered_coverage_bootstrap(rows, replicates=2000, seed=13)
    assert result == _date_clustered_coverage_bootstrap(rows, replicates=2000, seed=13)
    assert result["margin"]["coverage"] == 1 / 3
    assert result["margin"]["width"] == 20.0
    assert result["margin"]["date_clusters"] == 3
    assert result["margin"]["games"] == 6
    assert result["margin"]["replicates"] == 2000
    assert result["margin"]["seed"] == 13
    assert 0.94 < result["margin"]["p_under_nominal"] < 0.98
    assert 0.02 < result["margin"]["p_over_nominal"] < 0.06
    assert result["margin"]["p_under_nominal"] + result["margin"]["p_over_nominal"] == 1.0
    assert result["margin"]["ci95_percentile"][0] == 0.0
    assert result["margin"]["ci95_percentile"][1] == 1.0
    assert result["total"]["coverage"] == 1 / 3
    assert result["total"]["width"] == 30.0


def test_g2_crps_is_the_absolute_error_of_its_deterministic_point_mass():
    row = {
        "home_score": 110, "away_score": 100,
        "models": {
            "G2": {"home_points": 105.0, "away_points": 102.0},
            "G3": {"distribution_metrics": {"margin_crps": 6.0, "total_crps": 4.0}},
        },
    }
    assert _bootstrap_loss(row, "G2", "margin_crps") == pytest.approx(7.0)
    assert _bootstrap_loss(row, "G2", "total_crps") == pytest.approx(3.0)
    assert _bootstrap_loss(row, "G3", "margin_crps") == pytest.approx(6.0)


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


def test_unlocked_previews_are_graded_apart_from_the_locked_record(tmp_path: Path):
    model = open_db(str(tmp_path / "model.sqlite3"))
    rows = _forecast_rows("2026-10-21T23:00:00Z", "2026-10-21T22:50:00Z")
    try:
        assert upsert_previews(model, rows, dt.datetime(2026, 10, 21, 22, 55, tzinfo=UTC)) == 3
        # Lock window never ran: the preview is the only forecast, and is not a lock.
        before = grade_unlocked_previews(model, {}, dt.datetime(2026, 10, 21, 23, 5, tzinfo=UTC))
        assert before["preview_awaiting_verified_final"] == 3 and before["preview_graded"] == 0
        result = {"NBA001": {
            "completed": True, "summary_validated": True, "source_event_id": "ESPN001",
            "source_hash": "final-hash", "source": "ESPN scoreboard+summary",
            "home_team": "BOS", "away_team": "NYK", "home_score": 112, "away_score": 107,
        }}
        # Not graded before tipoff, even with a final in hand.
        early = grade_unlocked_previews(model, result, dt.datetime(2026, 10, 21, 22, 59, tzinfo=UTC))
        assert early["preview_graded"] == 0
        after = dt.datetime(2026, 10, 22, 2, 0, tzinfo=UTC)
        assert grade_unlocked_previews(model, result, after)["preview_graded"] == 3
        assert grade_unlocked_previews(model, result, after)["preview_already_graded"] == 3
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            model.execute("update nba_model_preview_grades set winner_brier=0")
        model.rollback()
        assert model.execute("select count(*) from nba_model_grades").fetchone()[0] == 0

        payload = export_payload(model, 2027, now=after)
        game = payload["games"][0]
        assert game["status"] == "unlocked" and game["locked_at_utc"] is None
        assert game["result"]["home_score"] == 112
        assert all(m["locked"] is False and m["grade"] for m in game["models"].values())
        for record in payload["records"].values():
            assert record["locked"] == 0 and record["graded"] == 0
            assert record["unlocked"]["previewed"] == 1 and record["unlocked"]["graded"] == 1
            assert record["unlocked"]["winner_brier"] is not None
    finally:
        model.close()


def test_late_lock_uses_the_preview_time_and_is_refused_without_a_pregame_preview(tmp_path: Path):
    model = open_db(str(tmp_path / "model.sqlite3"))
    rows = _forecast_rows("2026-10-21T23:00:00Z", "2026-10-21T22:50:00Z")
    try:
        assert upsert_previews(model, rows, dt.datetime(2026, 10, 21, 22, 55, tzinfo=UTC)) == 3
        with pytest.raises(NBAModelStoreError, match="exactly G1/G2/G3"):
            lock_previews_late(model, ["missing"])
        assert lock_previews_late(model, ["NBA001"]) == {"inserted_games": 1, "existing_games": 0}
        assert lock_previews_late(model, ["NBA001"]) == {"inserted_games": 0, "existing_games": 1}
        locks = model.execute("select lock_protocol,locked_at_utc from nba_model_locks").fetchall()
        assert {(r[0], r[1]) for r in locks} == {("late-preview-v1", "2026-10-21T22:55:00Z")}
    finally:
        model.close()


def test_late_lock_refuses_a_preview_stored_at_or_after_tipoff(tmp_path: Path):
    model = open_db(str(tmp_path / "model.sqlite3"))
    rows = _forecast_rows("2026-10-21T23:00:00Z", "2026-10-21T22:50:00Z")
    try:
        upsert_previews(model, rows, dt.datetime(2026, 10, 21, 22, 55, tzinfo=UTC))
        model.execute("update nba_model_previews set previewed_at_utc='2026-10-21T23:00:00Z'")
        model.commit()
        with pytest.raises(NBAModelStoreError, match="not stored before tipoff"):
            lock_previews_late(model, ["NBA001"])
        assert model.execute("select count(*) from nba_model_locks").fetchone()[0] == 0
    finally:
        model.close()


def test_locked_games_are_not_regraded_as_previews(tmp_path: Path):
    model = open_db(str(tmp_path / "model.sqlite3"))
    rows = _forecast_rows("2026-10-21T23:00:00Z", "2026-10-21T21:28:00Z")
    now = dt.datetime(2026, 10, 21, 21, 30, tzinfo=UTC)
    try:
        upsert_previews(model, rows, now)
        lock_forecasts(model, rows, now)
        result = {"NBA001": {
            "completed": True, "summary_validated": True, "source_event_id": "ESPN001",
            "source_hash": "final-hash", "source": "ESPN scoreboard+summary",
            "home_team": "BOS", "away_team": "NYK", "home_score": 112, "away_score": 107,
        }}
        report = grade_unlocked_previews(model, result, dt.datetime(2026, 10, 22, 2, 0, tzinfo=UTC))
        assert report == {"preview_graded": 0, "preview_already_graded": 0,
                          "preview_awaiting_verified_final": 0}
    finally:
        model.close()


def test_scoreboard_refresh_reads_one_day_at_a_time(monkeypatch):
    from nba_model_runtime import _games_by_day_single
    seen = []
    monkeypatch.setattr("nba_model_runtime.espn_client.games",
                        lambda league, day: seen.append((league, day)) or ([{"game_id": day}] if day != "2026-10-20" else []))
    by_day, raw = _games_by_day_single("nba", "2026-10-19", "2026-10-21")
    assert seen == [("nba", "2026-10-19"), ("nba", "2026-10-20"), ("nba", "2026-10-21")]
    assert raw == 2 and sorted(by_day) == ["2026-10-19", "2026-10-21"]


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
      'BOS','DET',3,102,109,'401909088')""")
    connection.commit()
    connection.close()


def _no_espn(*_args, **_kwargs):
    raise AssertionError("ESPN was asked about a game that nba.com has not called final or that is already stored")


def test_a_game_nba_com_has_not_called_final_costs_espn_nothing(tmp_path: Path):
    picks = tmp_path / "picks.dev.db"
    _fixture_schedule(picks)
    connection = sqlite3.connect(picks)
    connection.execute("UPDATE nba_schedule SET status=1, away_score=NULL, home_score=NULL")
    connection.commit()
    connection.close()
    now = dt.datetime(2026, 10, 21, 1, 0, tzinfo=UTC)
    report = refresh_completed_games(str(picks), str(tmp_path / "model.sqlite3"), now,
                                     games_by_day=_no_espn, summary_fetch=_no_espn)
    assert report["pending"] == 0
    assert report["stored"] == 0


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
    settled = refresh_completed_games(str(picks), str(model_path), now,
                                      games_by_day=_no_espn, summary_fetch=_no_espn)
    assert settled["pending"] == 0
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
