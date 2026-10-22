from __future__ import annotations

import datetime as dt
import json
import sqlite3

from nba_model_runtime import lock_due_forecasts
from nba_model_store import LOCK_PROTOCOL, MODEL_IDS, MODEL_VERSION, open_db

UTC = dt.timezone.utc
TIP = dt.datetime(2026, 10, 21, 18, 0, tzinfo=UTC)
GAME_ID = "0022600001"


def _picks_db(path, *, start: dt.datetime = TIP) -> str:
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE nba_schedule (game_id TEXT, season INTEGER, season_type TEXT, "
        "start_utc TEXT, source TEXT)"
    )
    con.execute(
        "INSERT INTO nba_schedule VALUES(?,2027,'REG',?,'nba.com')",
        (GAME_ID, start.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")),
    )
    con.executemany(
        "INSERT INTO nba_schedule VALUES(?,?,?,?,?)",
        [
            ("other-season", 2026, "REG", "2026-10-21T17:00:00Z", "nba.com"),
            ("other-type", 2027, "PRE", "2026-10-21T17:00:00Z", "nba.com"),
            ("other-source", 2027, "REG", "2026-10-21T17:00:00Z", "espn"),
            ("not-tipped", 2027, "REG", "2026-10-21T19:00:00Z", "nba.com"),
        ],
    )
    con.commit()
    con.close()
    return str(path)


def _seed_locks(model_path, models):
    con = open_db(str(model_path))
    try:
        for model in models:
            con.execute(
                "INSERT INTO nba_model_locks(game_id,model,season,scheduled_start_utc,home_team,"
                "away_team,model_version,lock_protocol,locked_at_utc,forecast_json,"
                "feature_snapshot_json,source_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (GAME_ID, model, 2027, TIP.isoformat().replace("+00:00", "Z"), "BOS", "NYK",
                 MODEL_VERSION[model], LOCK_PROTOCOL, TIP.isoformat().replace("+00:00", "Z"),
                 "{}", "{}", "fixture"),
            )
        con.commit()
    finally:
        con.close()


def _seed_previews(model_path):
    con = open_db(str(model_path))
    try:
        for model in MODEL_IDS:
            con.execute(
                "INSERT INTO nba_model_previews(game_id,model,season,scheduled_start_utc,"
                "home_team,away_team,model_version,forecast_json,feature_snapshot_json,"
                "source_hash,previewed_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (GAME_ID, model, 2027, TIP.isoformat().replace("+00:00", "Z"), "BOS", "NYK",
                 MODEL_VERSION[model], json.dumps({"home_win_probability": 0.6}), "{}",
                 "fixture", (TIP - dt.timedelta(minutes=90)).isoformat().replace("+00:00", "Z")),
            )
        con.commit()
    finally:
        con.close()


def _events(model_path):
    con = sqlite3.connect(model_path)
    try:
        return con.execute(
            "SELECT game_id,model,event_type FROM nba_model_lock_events ORDER BY model"
        ).fetchall()
    finally:
        con.close()


def test_zero_preview_schedule_game_records_three_events_at_tip(tmp_path):
    model_path = tmp_path / "nba-model.dev.sqlite3"
    picks_path = _picks_db(tmp_path / "picks.dev.db")

    report = lock_due_forecasts(str(model_path), TIP, lp_db_path=picks_path)
    repeated = lock_due_forecasts(str(model_path), TIP, lp_db_path=picks_path)

    assert report["missed_window_games"] == 1
    assert report["missed_lock_events"] == 3
    assert repeated["missed_window_games"] == 1
    assert repeated["missed_lock_events"] == 0
    assert _events(str(model_path)) == [(GAME_ID, "G1", "missed_t90_window"),
                                        (GAME_ID, "G2", "missed_t90_window"),
                                        (GAME_ID, "G3", "missed_t90_window")]


def test_partial_lock_set_records_only_the_missing_models(tmp_path):
    model_path = tmp_path / "nba-model.dev.sqlite3"
    picks_path = _picks_db(tmp_path / "picks.dev.db")
    _seed_locks(model_path, ("G1", "G2"))

    report = lock_due_forecasts(str(model_path), TIP, lp_db_path=picks_path)

    assert report["missed_lock_events"] == 1
    assert report["missed_window_games"] == 1
    assert _events(str(model_path)) == [(GAME_ID, "G3", "missed_t90_window")]


def test_full_lock_set_has_no_missed_events_and_sweep_is_idempotent(tmp_path):
    model_path = tmp_path / "nba-model.dev.sqlite3"
    picks_path = _picks_db(tmp_path / "picks.dev.db")
    _seed_locks(model_path, MODEL_IDS)

    first = lock_due_forecasts(str(model_path), TIP, lp_db_path=picks_path)
    second = lock_due_forecasts(str(model_path), TIP, lp_db_path=picks_path)

    assert first["missed_lock_events"] == second["missed_lock_events"] == 0
    assert first["missed_window_games"] == second["missed_window_games"] == 0
    assert _events(str(model_path)) == []


def test_preview_fallback_and_existing_pre_tip_window_count(tmp_path, monkeypatch):
    model_path = tmp_path / "nba-model.dev.sqlite3"
    _seed_previews(model_path)
    monkeypatch.delenv("LP_DB_PATH", raising=False)

    report = lock_due_forecasts(str(model_path), TIP)

    assert report["missed_window_games"] == 1
    assert report["missed_lock_events"] == 3
    assert len(_events(str(model_path))) == 3

    pre_tip_model_path = tmp_path / "nba-model-pre-tip.dev.sqlite3"
    pre_tip_picks_path = _picks_db(tmp_path / "picks.dev.db")
    _seed_previews(pre_tip_model_path)
    after_window = TIP - dt.timedelta(minutes=87)

    pre_tip = lock_due_forecasts(
        str(pre_tip_model_path), after_window, lp_db_path=pre_tip_picks_path
    )

    assert pre_tip["missed_window_games"] == 1
    assert pre_tip["missed_lock_events"] == 0
    assert _events(str(pre_tip_model_path)) == []
