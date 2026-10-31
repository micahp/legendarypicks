"""Standalone dev store for NBA model history, previews, immutable locks and grades."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import sqlite3
from pathlib import Path
from typing import Any

import pytz
from pytz.exceptions import UnknownTimeZoneError

from nba_game_model import MODEL_INFO

UTC = dt.timezone.utc
LOCK_LEAD = dt.timedelta(minutes=90)
LOCK_WINDOW = dt.timedelta(minutes=2)
PREVIEW_MAX_AGE = dt.timedelta(hours=2)
LOCK_PROTOCOL = "t90-2m-v1"
LATE_LOCK_PROTOCOL = "late-preview-v1"
DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "nba-model.dev.sqlite3")
MODEL_IDS = tuple(model["id"] for model in MODEL_INFO)
MODEL_VERSION = {model["id"]: model["version"] for model in MODEL_INFO}

SCHEMA = """
CREATE TABLE IF NOT EXISTS nba_model_history (
    source_game_id TEXT PRIMARY KEY,
    season INTEGER NOT NULL,
    game_date TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    home_score INTEGER NOT NULL,
    away_score INTEGER NOT NULL,
    home_fga REAL NOT NULL,
    home_fta REAL NOT NULL,
    home_orb REAL NOT NULL,
    home_tov REAL NOT NULL,
    away_fga REAL NOT NULL,
    away_fta REAL NOT NULL,
    away_orb REAL NOT NULL,
    away_tov REAL NOT NULL,
    schedule_game_id TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    imported_at_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS nba_model_history_date ON nba_model_history(game_date, source_game_id);
CREATE TABLE IF NOT EXISTS nba_model_live_game_observations (
    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    nba_game_id TEXT NOT NULL,
    season INTEGER NOT NULL,
    game_date TEXT NOT NULL,
    scheduled_start_utc TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    home_score INTEGER NOT NULL,
    away_score INTEGER NOT NULL,
    home_stats_json TEXT NOT NULL,
    away_stats_json TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    source TEXT NOT NULL,
    final_confirmed INTEGER NOT NULL CHECK (final_confirmed IN (0,1)),
    observed_at_utc TEXT NOT NULL,
    UNIQUE(nba_game_id, source_hash)
);
CREATE INDEX IF NOT EXISTS nba_model_live_date ON nba_model_live_game_observations(game_date, observed_at_utc);
CREATE TABLE IF NOT EXISTS nba_model_previews (
    game_id TEXT NOT NULL,
    model TEXT NOT NULL,
    season INTEGER NOT NULL,
    scheduled_start_utc TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    model_version TEXT NOT NULL,
    forecast_json TEXT NOT NULL,
    feature_snapshot_json TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    previewed_at_utc TEXT NOT NULL,
    PRIMARY KEY(game_id, model)
);
CREATE INDEX IF NOT EXISTS nba_model_previews_start ON nba_model_previews(season, scheduled_start_utc);
CREATE TABLE IF NOT EXISTS nba_model_locks (
    game_id TEXT NOT NULL,
    model TEXT NOT NULL,
    season INTEGER NOT NULL,
    scheduled_start_utc TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    model_version TEXT NOT NULL,
    lock_protocol TEXT NOT NULL,
    locked_at_utc TEXT NOT NULL,
    forecast_json TEXT NOT NULL,
    feature_snapshot_json TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    PRIMARY KEY(game_id, model)
);
CREATE INDEX IF NOT EXISTS nba_model_locks_start ON nba_model_locks(season, scheduled_start_utc);
CREATE TABLE IF NOT EXISTS nba_model_grades (
    game_id TEXT NOT NULL,
    model TEXT NOT NULL,
    season INTEGER NOT NULL,
    result_source TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    final_home_score INTEGER NOT NULL,
    final_away_score INTEGER NOT NULL,
    home_win INTEGER NOT NULL CHECK(home_win IN (0,1)),
    winner_brier REAL NOT NULL,
    winner_log_loss REAL NOT NULL,
    home_points_abs_error REAL,
    away_points_abs_error REAL,
    spread_abs_error REAL,
    total_abs_error REAL,
    source_hash TEXT NOT NULL,
    graded_at_utc TEXT NOT NULL,
    PRIMARY KEY(game_id, model)
);
CREATE TABLE IF NOT EXISTS nba_model_preview_grades (
    game_id TEXT NOT NULL,
    model TEXT NOT NULL,
    season INTEGER NOT NULL,
    previewed_at_utc TEXT NOT NULL,
    result_source TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    final_home_score INTEGER NOT NULL,
    final_away_score INTEGER NOT NULL,
    home_win INTEGER NOT NULL CHECK(home_win IN (0,1)),
    winner_brier REAL NOT NULL,
    winner_log_loss REAL NOT NULL,
    home_points_abs_error REAL,
    away_points_abs_error REAL,
    spread_abs_error REAL,
    total_abs_error REAL,
    source_hash TEXT NOT NULL,
    graded_at_utc TEXT NOT NULL,
    PRIMARY KEY(game_id, model)
);
CREATE TABLE IF NOT EXISTS nba_model_lock_events (
    game_id TEXT NOT NULL,
    model TEXT NOT NULL,
    season INTEGER NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type='missed_t90_window'),
    recorded_at_utc TEXT NOT NULL,
    PRIMARY KEY(game_id, model, event_type)
);
CREATE TABLE IF NOT EXISTS nba_model_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS nba_model_lock_immutable_update
BEFORE UPDATE ON nba_model_locks
BEGIN SELECT RAISE(ABORT, 'NBA locked forecasts are immutable'); END;
CREATE TRIGGER IF NOT EXISTS nba_model_lock_immutable_delete
BEFORE DELETE ON nba_model_locks
BEGIN SELECT RAISE(ABORT, 'NBA locked forecasts are immutable'); END;
CREATE TRIGGER IF NOT EXISTS nba_model_grade_immutable_update
BEFORE UPDATE ON nba_model_grades
BEGIN SELECT RAISE(ABORT, 'NBA forecast grades are immutable'); END;
CREATE TRIGGER IF NOT EXISTS nba_model_grade_immutable_delete
BEFORE DELETE ON nba_model_grades
BEGIN SELECT RAISE(ABORT, 'NBA forecast grades are immutable'); END;
CREATE TRIGGER IF NOT EXISTS nba_model_preview_grade_immutable_update
BEFORE UPDATE ON nba_model_preview_grades
BEGIN SELECT RAISE(ABORT, 'NBA preview grades are immutable'); END;
CREATE TRIGGER IF NOT EXISTS nba_model_preview_grade_immutable_delete
BEFORE DELETE ON nba_model_preview_grades
BEGIN SELECT RAISE(ABORT, 'NBA preview grades are immutable'); END;
CREATE TRIGGER IF NOT EXISTS nba_model_lock_event_immutable_update
BEFORE UPDATE ON nba_model_lock_events
BEGIN SELECT RAISE(ABORT, 'NBA lock events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS nba_model_lock_event_immutable_delete
BEFORE DELETE ON nba_model_lock_events
BEGIN SELECT RAISE(ABORT, 'NBA lock events are immutable'); END;
"""


class NBAModelStoreError(RuntimeError):
    """Invalid forecast, identity, lock timing, or grade input."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def parse_time(value: str | dt.datetime) -> dt.datetime:
    if isinstance(value, dt.datetime):
        parsed = value
    else:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise NBAModelStoreError(f"timestamp must include a timezone: {value!r}")
    return parsed.astimezone(UTC)


def iso_utc(value: dt.datetime) -> str:
    if value.tzinfo is None:
        raise NBAModelStoreError("timestamp must include a timezone")
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def open_db(path: str = DEFAULT_DB, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        connection = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
    else:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        connection.executescript(SCHEMA)
        connection.executescript(TRIGGERS)
        connection.commit()
    connection.row_factory = sqlite3.Row
    return connection


def import_history(con: sqlite3.Connection, games: list[dict[str, Any]],
                   asset_hashes: dict[str, str], coverage: list[dict[str, Any]],
                   now: dt.datetime | None = None) -> int:
    """Install immutable, hash-pinned history into the standalone model DB."""
    now = now or dt.datetime.now(UTC)
    imported_at = iso_utc(now)
    columns = (
        "source_game_id", "season", "game_date", "home_team", "away_team", "home_score",
        "away_score", "home_fga", "home_fta", "home_orb", "home_tov", "away_fga",
        "away_fta", "away_orb", "away_tov", "schedule_game_id", "source_hash",
        "imported_at_utc",
    )
    sql = (f"INSERT OR IGNORE INTO nba_model_history({','.join(columns)}) "
           f"VALUES({','.join('?' for _ in columns)})")
    inserted_rows = 0
    con.execute("BEGIN")
    try:
        for game in games:
            row = dict(game)
            if "source_game_id" not in row and "game_id" in row:
                row["source_game_id"] = row.pop("game_id")
            season_assets = {name: digest for name, digest in asset_hashes.items()
                             if name.endswith(f"_{int(row['season'])}.parquet")}
            if not season_assets:
                raise NBAModelStoreError(
                    f"no pinned source assets for ending-year season {row['season']}"
                )
            row["source_hash"] = hashlib.sha256(
                canonical_json(season_assets).encode()
            ).hexdigest()
            row["imported_at_utc"] = imported_at
            values = tuple(row[key] for key in columns)
            cursor = con.execute(sql, values)
            inserted_rows += int(cursor.rowcount == 1)
            existing = con.execute(
                "SELECT source_hash,home_score,away_score,home_team,away_team FROM nba_model_history "
                "WHERE source_game_id=?", (row["source_game_id"],)
            ).fetchone()
            if (existing is None or existing["source_hash"] != row["source_hash"]
                    or existing["home_score"] != row["home_score"]
                    or existing["away_score"] != row["away_score"]
                    or existing["home_team"] != row["home_team"]
                    or existing["away_team"] != row["away_team"]):
                raise NBAModelStoreError(
                    f"existing history conflicts with pinned release for {row['source_game_id']}"
                )
        meta = {
            "history_source_hash": hashlib.sha256(canonical_json(asset_hashes).encode()).hexdigest(),
            "history_asset_hashes": asset_hashes,
            "history_coverage": coverage,
            "history_games": len(games),
            "history_fitted_through": max(row["game_date"] for row in games),
        }
        for key, value in meta.items():
            con.execute("INSERT INTO nba_model_meta(key,value) VALUES(?,?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, canonical_json(value)))
        con.commit()
    except Exception:
        con.rollback()
        raise
    return inserted_rows


def latest_live_games(con: sqlite3.Connection, before_date: str | None = None,
                      before_utc: str | dt.datetime | None = None) -> list[dict[str, Any]]:
    """Latest verified team box per NBA schedule ID, before date and capture-time cutoffs."""
    where = "g.final_confirmed=1"
    params: list[Any] = []
    if before_date is not None:
        where += " AND g.game_date < ?"
        params.append(before_date)
    newer_cutoff = ""
    if before_utc is not None:
        cutoff = iso_utc(parse_time(before_utc))
        where += " AND g.observed_at_utc <= ?"
        params.append(cutoff)
        newer_cutoff = " AND newer.observed_at_utc <= ?"
        params.append(cutoff)
    rows = con.execute(
        "SELECT g.* FROM nba_model_live_game_observations g WHERE " + where +
        " AND NOT EXISTS (SELECT 1 FROM nba_model_live_game_observations newer "
        "WHERE newer.nba_game_id=g.nba_game_id" + newer_cutoff + " AND "
        "(newer.observed_at_utc>g.observed_at_utc OR "
        "(newer.observed_at_utc=g.observed_at_utc AND newer.observation_id>g.observation_id))) "
        "ORDER BY g.game_date,g.nba_game_id", tuple(params)
    ).fetchall()
    output = []
    for row in rows:
        home_stats, away_stats = json.loads(row["home_stats_json"]), json.loads(row["away_stats_json"])
        output.append({
            "game_id": row["source_event_id"], "season": row["season"],
            "game_date": row["game_date"], "home_team": row["home_team"],
            "away_team": row["away_team"], "home_score": row["home_score"],
            "away_score": row["away_score"],
            "home_fga": home_stats["field_goals_attempted"],
            "home_fta": home_stats["free_throws_attempted"],
            "home_orb": home_stats["offensive_rebounds"],
            "home_tov": home_stats["turnovers"],
            "away_fga": away_stats["field_goals_attempted"],
            "away_fta": away_stats["free_throws_attempted"],
            "away_orb": away_stats["offensive_rebounds"],
            "away_tov": away_stats["turnovers"],
            "schedule_game_id": row["nba_game_id"],
            "source_hash": row["source_hash"],
            "observed_at_utc": row["observed_at_utc"],
        })
    return output


def latest_verified_results(con: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """Return only latest ESPN observations that passed scoreboard and summary validation."""
    rows = con.execute(
        "SELECT g.* FROM nba_model_live_game_observations g WHERE g.final_confirmed=1 "
        "AND NOT EXISTS (SELECT 1 FROM nba_model_live_game_observations newer "
        "WHERE newer.nba_game_id=g.nba_game_id AND "
        "(newer.observed_at_utc>g.observed_at_utc OR "
        "(newer.observed_at_utc=g.observed_at_utc AND newer.observation_id>g.observation_id)))"
    ).fetchall()
    return {row["nba_game_id"]: {
        "completed": True, "summary_validated": True,
        "source_event_id": row["source_event_id"], "source_hash": row["source_hash"],
        "source": row["source"], "home_team": row["home_team"],
        "away_team": row["away_team"], "home_score": row["home_score"],
        "away_score": row["away_score"],
    } for row in rows}


def store_live_observation(con: sqlite3.Connection, row: dict[str, Any]) -> bool:
    """Append a verified final observation; a corrected source payload gets a new row."""
    if row.get("final_confirmed") is not True:
        raise NBAModelStoreError("only completed, summary-validated games may enter model history")
    stats_home = row.get("home_stats")
    stats_away = row.get("away_stats")
    required = {"field_goals_attempted", "free_throws_attempted", "offensive_rebounds", "turnovers"}
    for side, stats in (("home", stats_home), ("away", stats_away)):
        if not isinstance(stats, dict) or not required.issubset(stats):
            raise NBAModelStoreError(f"{side} live boxscore misses efficiency inputs")
        if any(stats[key] is None or float(stats[key]) < 0 for key in required):
            raise NBAModelStoreError(f"{side} live boxscore has invalid efficiency inputs")
    values = (
        row["nba_game_id"], int(row["season"]), row["game_date"],
        iso_utc(parse_time(row["scheduled_start_utc"])), str(row["source_event_id"]),
        row["home_team"], row["away_team"], int(row["home_score"]), int(row["away_score"]),
        canonical_json(stats_home), canonical_json(stats_away), row["source_hash"],
        row["source"], 1, iso_utc(parse_time(row["observed_at_utc"])),
    )
    cursor = con.execute(
        "INSERT OR IGNORE INTO nba_model_live_game_observations"
        "(nba_game_id,season,game_date,scheduled_start_utc,source_event_id,home_team,away_team,"
        "home_score,away_score,home_stats_json,away_stats_json,source_hash,source,final_confirmed,"
        "observed_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", values,
    )
    con.commit()
    return cursor.rowcount == 1


def upsert_previews(con: sqlite3.Connection, rows: list[dict[str, Any]],
                    now: dt.datetime | None = None) -> int:
    now = now or dt.datetime.now(UTC)
    now_text = iso_utc(now)
    inserted = 0
    con.execute("BEGIN")
    try:
        for row in rows:
            kickoff = parse_time(row["scheduled_start_utc"])
            if now >= kickoff:
                continue
            model = row["model"]
            if model not in MODEL_IDS or row["model_version"] != MODEL_VERSION[model]:
                raise NBAModelStoreError(f"unknown/mismatched model version {model}/{row['model_version']}")
            probability = float(row["forecast"]["home_win_probability"])
            if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
                raise NBAModelStoreError("preview home-win probability is outside [0,1]")
            con.execute(
                "INSERT INTO nba_model_previews(game_id,model,season,scheduled_start_utc,home_team,"
                "away_team,model_version,forecast_json,feature_snapshot_json,source_hash,previewed_at_utc)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(game_id,model) DO UPDATE SET "
                "season=excluded.season,scheduled_start_utc=excluded.scheduled_start_utc,"
                "home_team=excluded.home_team,away_team=excluded.away_team,"
                "model_version=excluded.model_version,forecast_json=excluded.forecast_json,"
                "feature_snapshot_json=excluded.feature_snapshot_json,source_hash=excluded.source_hash,"
                "previewed_at_utc=excluded.previewed_at_utc",
                (str(row["game_id"]), model, int(row["season"]), iso_utc(kickoff),
                 row["home_team"], row["away_team"], row["model_version"],
                 canonical_json(row["forecast"]), canonical_json(row["feature_snapshot"]),
                 row["source_hash"], now_text),
            )
            inserted += 1
        con.commit()
    except Exception:
        con.rollback()
        raise
    return inserted


def lock_forecasts(con: sqlite3.Connection, rows: list[dict[str, Any]],
                   now: dt.datetime | None = None) -> dict[str, int]:
    """Atomically lock all three candidates only in the two-minute T-90 window."""
    now = now or dt.datetime.now(UTC)
    report = {"inserted_games": 0, "existing_games": 0, "not_due_games": 0,
              "missed_window_games": 0}
    by_game: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_game.setdefault(str(row["game_id"]), []).append(row)
    con.execute("BEGIN")
    try:
        for game_id, game_rows in by_game.items():
            if {row["model"] for row in game_rows} != set(MODEL_IDS) or len(game_rows) != len(MODEL_IDS):
                raise NBAModelStoreError(f"{game_id}: lock feed must contain exactly G1/G2/G3")
            kickoff = parse_time(game_rows[0]["scheduled_start_utc"])
            cutoff = kickoff - LOCK_LEAD
            if now < cutoff:
                report["not_due_games"] += 1
                continue
            if now >= cutoff + LOCK_WINDOW or now >= kickoff:
                report["missed_window_games"] += 1
                continue
            existing = con.execute("SELECT COUNT(*) FROM nba_model_locks WHERE game_id=?", (game_id,)).fetchone()[0]
            if existing == len(MODEL_IDS):
                report["existing_games"] += 1
                continue
            if existing:
                raise NBAModelStoreError(f"{game_id}: partial immutable lock set exists ({existing})")
            for row in game_rows:
                model = row["model"]
                if model not in MODEL_IDS or row["model_version"] != MODEL_VERSION[model]:
                    raise NBAModelStoreError(f"unknown/mismatched model version {model}/{row['model_version']}")
                previewed = parse_time(row["previewed_at_utc"])
                if now - previewed > PREVIEW_MAX_AGE or previewed > now:
                    raise NBAModelStoreError(f"{game_id}/{model}: preview is stale or from the future")
                if parse_time(row["feature_snapshot"]["cutoff_utc"]) >= kickoff:
                    raise NBAModelStoreError(f"{game_id}/{model}: feature cutoff is not pre-tipoff")
                probability = float(row["forecast"]["home_win_probability"])
                if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
                    raise NBAModelStoreError(f"{game_id}/{model}: invalid home-win probability")
            # All checks have passed; no partial game lock is observable.
            for row in game_rows:
                con.execute(
                    "INSERT INTO nba_model_locks(game_id,model,season,scheduled_start_utc,home_team,"
                    "away_team,model_version,lock_protocol,locked_at_utc,forecast_json,"
                    "feature_snapshot_json,source_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (game_id, row["model"], int(row["season"]), iso_utc(kickoff), row["home_team"],
                     row["away_team"], row["model_version"], LOCK_PROTOCOL, iso_utc(now),
                     canonical_json(row["forecast"]), canonical_json(row["feature_snapshot"]),
                     row["source_hash"]),
                )
            report["inserted_games"] += 1
        con.commit()
    except Exception:
        con.rollback()
        raise
    return report


def lock_previews_late(con: sqlite3.Connection, game_ids: list[str]) -> dict[str, int]:
    """Lock named games from their stored pregame preview after the T-90 window was missed.

    The lock is stamped with the preview's own `previewed_at_utc`, never with the current time,
    so it records when the forecast really existed. Refused unless every candidate has a
    preview stored before tipoff with a pre-tipoff feature cutoff. Protocol is distinct from
    the T-90 lock so the two stay separable in the record.
    """
    report = {"inserted_games": 0, "existing_games": 0}
    con.execute("BEGIN")
    try:
        for game_id in game_ids:
            rows = con.execute("SELECT * FROM nba_model_previews WHERE game_id=? ORDER BY model",
                               (game_id,)).fetchall()
            if {row["model"] for row in rows} != set(MODEL_IDS):
                raise NBAModelStoreError(f"{game_id}: needs previews for exactly G1/G2/G3")
            existing = con.execute("SELECT COUNT(*) FROM nba_model_locks WHERE game_id=?", (game_id,)).fetchone()[0]
            if existing == len(MODEL_IDS):
                report["existing_games"] += 1
                continue
            if existing:
                raise NBAModelStoreError(f"{game_id}: partial immutable lock set exists ({existing})")
            for row in rows:
                kickoff = parse_time(row["scheduled_start_utc"])
                previewed = parse_time(row["previewed_at_utc"])
                if row["model_version"] != MODEL_VERSION[row["model"]]:
                    raise NBAModelStoreError(f"{game_id}/{row['model']}: mismatched model version")
                if previewed >= kickoff:
                    raise NBAModelStoreError(f"{game_id}/{row['model']}: preview was not stored before tipoff")
                if parse_time(json.loads(row["feature_snapshot_json"])["cutoff_utc"]) >= kickoff:
                    raise NBAModelStoreError(f"{game_id}/{row['model']}: feature cutoff is not pre-tipoff")
                probability = float(json.loads(row["forecast_json"])["home_win_probability"])
                if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
                    raise NBAModelStoreError(f"{game_id}/{row['model']}: invalid home-win probability")
            for row in rows:
                con.execute(
                    "INSERT INTO nba_model_locks(game_id,model,season,scheduled_start_utc,home_team,"
                    "away_team,model_version,lock_protocol,locked_at_utc,forecast_json,"
                    "feature_snapshot_json,source_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (game_id, row["model"], row["season"], row["scheduled_start_utc"], row["home_team"],
                     row["away_team"], row["model_version"], LATE_LOCK_PROTOCOL, row["previewed_at_utc"],
                     row["forecast_json"], row["feature_snapshot_json"], row["source_hash"]),
                )
            report["inserted_games"] += 1
        con.commit()
    except Exception:
        con.rollback()
        raise
    return report


def record_missed_windows(con: sqlite3.Connection, now: dt.datetime | None = None) -> int:
    now = now or dt.datetime.now(UTC)
    locked = {(r[0], r[1]) for r in con.execute("SELECT game_id,model FROM nba_model_locks")}
    missed = 0
    con.execute("BEGIN")
    try:
        rows = con.execute("SELECT * FROM nba_model_previews").fetchall()
        for row in rows:
            key = (row["game_id"], row["model"])
            if key in locked or now < parse_time(row["scheduled_start_utc"]):
                continue
            cursor = con.execute(
                "INSERT OR IGNORE INTO nba_model_lock_events(game_id,model,season,event_type,"
                "recorded_at_utc) VALUES(?,?,?,'missed_t90_window',?)",
                (row["game_id"], row["model"], row["season"], iso_utc(now)),
            )
            missed += cursor.rowcount
        con.commit()
    except Exception:
        con.rollback()
        raise
    return missed


def _score_forecast(forecast: dict[str, Any], home_score: int, away_score: int) -> tuple:
    outcome = int(home_score > away_score)
    probability = float(forecast["home_win_probability"])
    brier = (probability - outcome) ** 2
    logloss = -math.log(max(1e-12, probability if outcome else 1.0 - probability))
    home_abs = away_abs = spread_abs = total_abs = None
    if forecast.get("score_forecast_available") is True:
        pred_home, pred_away = float(forecast["projected_home_points"]), float(forecast["projected_away_points"])
        home_abs, away_abs = abs(pred_home - home_score), abs(pred_away - away_score)
        spread_abs = abs((pred_home - pred_away) - (home_score - away_score))
        total_abs = abs((pred_home + pred_away) - (home_score + away_score))
    return outcome, brier, logloss, home_abs, away_abs, spread_abs, total_abs


def grade_forecasts(con: sqlite3.Connection, results: dict[str, dict[str, Any]],
                    now: dt.datetime | None = None) -> dict[str, int]:
    """Append grades only for locked forecasts with a verified, completed source result."""
    now = now or dt.datetime.now(UTC)
    report = {"graded": 0, "already_graded": 0, "awaiting_verified_final": 0}
    con.execute("BEGIN")
    try:
        locks = con.execute("SELECT * FROM nba_model_locks ORDER BY game_id,model").fetchall()
        for lock in locks:
            existing = con.execute(
                "SELECT final_home_score,final_away_score FROM nba_model_grades "
                "WHERE game_id=? AND model=?", (lock["game_id"], lock["model"])
            ).fetchone()
            result = results.get(lock["game_id"])
            if existing:
                if result and (existing["final_home_score"] != result.get("home_score")
                               or existing["final_away_score"] != result.get("away_score")):
                    raise NBAModelStoreError(f"{lock['game_id']}: verified final conflicts with immutable grade")
                report["already_graded"] += 1
                continue
            if (not result or result.get("completed") is not True
                    or result.get("summary_validated") is not True
                    or not result.get("source_event_id")
                    or not result.get("source_hash")):
                report["awaiting_verified_final"] += 1
                continue
            kickoff = parse_time(lock["scheduled_start_utc"])
            if now <= kickoff:
                report["awaiting_verified_final"] += 1
                continue
            if (str(result.get("home_team")) != lock["home_team"]
                    or str(result.get("away_team")) != lock["away_team"]):
                raise NBAModelStoreError(f"{lock['game_id']}: result team identity differs from lock")
            home_score, away_score = int(result["home_score"]), int(result["away_score"])
            outcome, brier, logloss, home_abs, away_abs, spread_abs, total_abs = _score_forecast(
                json.loads(lock["forecast_json"]), home_score, away_score)
            con.execute(
                "INSERT INTO nba_model_grades(game_id,model,season,result_source,source_event_id,"
                "final_home_score,final_away_score,home_win,winner_brier,winner_log_loss,"
                "home_points_abs_error,away_points_abs_error,spread_abs_error,total_abs_error,"
                "source_hash,graded_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (lock["game_id"], lock["model"], lock["season"], result["source"],
                 str(result["source_event_id"]), home_score, away_score, outcome, brier, logloss,
                 home_abs, away_abs, spread_abs, total_abs, result["source_hash"], iso_utc(now)),
            )
            report["graded"] += 1
        con.commit()
    except Exception:
        con.rollback()
        raise
    return report


def grade_unlocked_previews(con: sqlite3.Connection, results: dict[str, dict[str, Any]],
                            now: dt.datetime | None = None) -> dict[str, int]:
    """Grade the last pregame preview of games that never locked.

    A preview stops being rewritten at kickoff (`upsert_previews`), so after tipoff the
    stored row is the final pregame forecast. These grades live in their own table and
    never enter the locked record.
    """
    now = now or dt.datetime.now(UTC)
    report = {"preview_graded": 0, "preview_already_graded": 0, "preview_awaiting_verified_final": 0}
    con.execute("BEGIN")
    try:
        rows = con.execute(
            "SELECT p.* FROM nba_model_previews p LEFT JOIN nba_model_locks l USING(game_id,model) "
            "WHERE l.game_id IS NULL ORDER BY p.game_id,p.model"
        ).fetchall()
        for row in rows:
            if con.execute("SELECT 1 FROM nba_model_preview_grades WHERE game_id=? AND model=?",
                           (row["game_id"], row["model"])).fetchone():
                report["preview_already_graded"] += 1
                continue
            result = results.get(row["game_id"])
            if (now <= parse_time(row["scheduled_start_utc"]) or not result
                    or result.get("completed") is not True
                    or result.get("summary_validated") is not True
                    or not result.get("source_event_id") or not result.get("source_hash")):
                report["preview_awaiting_verified_final"] += 1
                continue
            if (str(result.get("home_team")) != row["home_team"]
                    or str(result.get("away_team")) != row["away_team"]):
                raise NBAModelStoreError(f"{row['game_id']}: result team identity differs from preview")
            home_score, away_score = int(result["home_score"]), int(result["away_score"])
            outcome, brier, logloss, home_abs, away_abs, spread_abs, total_abs = _score_forecast(
                json.loads(row["forecast_json"]), home_score, away_score)
            con.execute(
                "INSERT INTO nba_model_preview_grades(game_id,model,season,previewed_at_utc,"
                "result_source,source_event_id,final_home_score,final_away_score,home_win,"
                "winner_brier,winner_log_loss,home_points_abs_error,away_points_abs_error,"
                "spread_abs_error,total_abs_error,source_hash,graded_at_utc) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (row["game_id"], row["model"], row["season"], row["previewed_at_utc"],
                 result["source"], str(result["source_event_id"]), home_score, away_score, outcome,
                 brier, logloss, home_abs, away_abs, spread_abs, total_abs, result["source_hash"],
                 iso_utc(now)),
            )
            report["preview_graded"] += 1
        con.commit()
    except Exception:
        con.rollback()
        raise
    return report


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _record(rows: list[sqlite3.Row], missed: int) -> dict[str, Any]:
    graded = [row for row in rows if row["winner_brier"] is not None]
    n = len(graded)
    out: dict[str, Any] = {"locked": len(rows), "graded": n, "awaiting": len(rows) - n,
                           "missed": missed, "winner_brier": None, "winner_log_loss": None,
                           "home_points_mae": None, "away_points_mae": None,
                           "spread_mae": None, "total_mae": None}
    if not n:
        return out
    out["winner_brier"] = sum(row["winner_brier"] for row in graded) / n
    out["winner_log_loss"] = sum(row["winner_log_loss"] for row in graded) / n
    for key, column in (("home_points_mae", "home_points_abs_error"),
                        ("away_points_mae", "away_points_abs_error"),
                        ("spread_mae", "spread_abs_error"),
                        ("total_mae", "total_abs_error")):
        values = [row[column] for row in graded if row[column] is not None]
        out[key] = sum(values) / len(values) if values else None
    return out


def _all_record_summaries(con: sqlite3.Connection, season: int, now_text: str) -> dict[str, dict[str, Any]]:
    locked_rows = {
        row["model"]: row for row in con.execute(
            "SELECT l.model,COUNT(*) AS locked,"
            "SUM(CASE WHEN g.winner_brier IS NOT NULL THEN 1 ELSE 0 END) AS graded,"
            "AVG(g.winner_brier) AS winner_brier,AVG(g.winner_log_loss) AS winner_log_loss,"
            "AVG(g.home_points_abs_error) AS home_points_mae,"
            "AVG(g.away_points_abs_error) AS away_points_mae,"
            "AVG(g.spread_abs_error) AS spread_mae,AVG(g.total_abs_error) AS total_mae "
            "FROM nba_model_locks l LEFT JOIN nba_model_grades g USING(game_id,model) "
            "WHERE l.season=? GROUP BY l.model", (season,)
        )
    }
    missed_rows = {
        row["model"]: row["missed"] for row in con.execute(
            "SELECT model,COUNT(*) AS missed FROM nba_model_lock_events "
            "WHERE season=? AND event_type='missed_t90_window' GROUP BY model", (season,)
        )
    }
    unlocked_rows = {
        row["model"]: row for row in con.execute(
            "SELECT p.model,COUNT(*) AS previewed,COUNT(g.winner_brier) AS graded,"
            "AVG(g.winner_brier) AS winner_brier,AVG(g.winner_log_loss) AS winner_log_loss,"
            "AVG(g.home_points_abs_error) AS home_points_mae,"
            "AVG(g.away_points_abs_error) AS away_points_mae,"
            "AVG(g.spread_abs_error) AS spread_mae,AVG(g.total_abs_error) AS total_mae "
            "FROM nba_model_previews p "
            "LEFT JOIN nba_model_locks l USING(game_id,model) "
            "LEFT JOIN nba_model_preview_grades g USING(game_id,model) "
            "WHERE p.season=? AND p.scheduled_start_utc<=? AND l.game_id IS NULL "
            "GROUP BY p.model", (season, now_text)
        )
    } if _table_exists(con, "nba_model_previews") else {}

    labels = {item["id"]: item for item in MODEL_INFO}
    summaries = {}
    for model in MODEL_IDS:
        row = locked_rows.get(model)
        locked = int(row["locked"]) if row else 0
        graded = int(row["graded"] or 0) if row else 0
        unlocked = unlocked_rows.get(model)
        summaries[model] = {
            "label": labels[model]["label"],
            "model_version": labels[model]["version"],
            "projects_scores": labels[model]["projects_scores"],
            "locked": locked,
            "graded": graded,
            "awaiting": locked - graded,
            "missed": int(missed_rows.get(model, 0)),
            "winner_brier": row["winner_brier"] if row else None,
            "winner_log_loss": row["winner_log_loss"] if row else None,
            "home_points_mae": row["home_points_mae"] if row else None,
            "away_points_mae": row["away_points_mae"] if row else None,
            "spread_mae": row["spread_mae"] if row else None,
            "total_mae": row["total_mae"] if row else None,
            "unlocked": {
                "previewed": int(unlocked["previewed"]) if unlocked else 0,
                "graded": int(unlocked["graded"]) if unlocked else 0,
                "awaiting": (int(unlocked["previewed"]) - int(unlocked["graded"])) if unlocked else 0,
                "winner_brier": unlocked["winner_brier"] if unlocked else None,
                "winner_log_loss": unlocked["winner_log_loss"] if unlocked else None,
                "home_points_mae": unlocked["home_points_mae"] if unlocked else None,
                "away_points_mae": unlocked["away_points_mae"] if unlocked else None,
                "spread_mae": unlocked["spread_mae"] if unlocked else None,
                "total_mae": unlocked["total_mae"] if unlocked else None,
            },
        }
    return summaries


def _store_state(con: sqlite3.Connection, season: int) -> str:
    if not _table_exists(con, "nba_model_history"):
        return "awaiting_history_import"
    has_locks = con.execute("SELECT 1 FROM nba_model_locks WHERE season=? LIMIT 1", (season,)).fetchone()
    has_previews = _table_exists(con, "nba_model_previews") and con.execute(
        "SELECT 1 FROM nba_model_previews WHERE season=? LIMIT 1", (season,)
    ).fetchone()
    return "available" if has_locks or has_previews else "awaiting_first_forecast"


def export_projection_payload(con: sqlite3.Connection, season: int,
                              benchmark: dict[str, Any] | None = None,
                              now: dt.datetime | None = None) -> dict[str, Any]:
    """Return upcoming NBA cards and season-wide summaries without historical game rows."""
    now = now or dt.datetime.now(UTC)
    now_text = iso_utc(now)
    locks = con.execute(
        "SELECT l.*,g.result_source,g.final_home_score,g.final_away_score,g.home_win,"
        "g.winner_brier,g.winner_log_loss,g.home_points_abs_error,g.away_points_abs_error,"
        "g.spread_abs_error,g.total_abs_error,g.graded_at_utc "
        "FROM nba_model_locks l LEFT JOIN nba_model_grades g USING(game_id,model) "
        "WHERE l.season=? AND l.scheduled_start_utc>? "
        "ORDER BY l.scheduled_start_utc,l.game_id,l.model", (season, now_text)
    ).fetchall()
    previews = []
    if _table_exists(con, "nba_model_previews"):
        previews = con.execute(
            "SELECT * FROM nba_model_previews WHERE season=? AND scheduled_start_utc>? "
            "ORDER BY scheduled_start_utc,game_id,model", (season, now_text)
        ).fetchall()
    missed_pairs = set()
    if _table_exists(con, "nba_model_lock_events") and _table_exists(con, "nba_model_previews"):
        missed_pairs = {(row["game_id"], row["model"]) for row in con.execute(
            "SELECT DISTINCT p.game_id,p.model FROM nba_model_previews p "
            "JOIN nba_model_lock_events e USING(game_id,model,season) "
            "WHERE p.season=? AND p.scheduled_start_utc>? AND e.event_type='missed_t90_window'",
            (season, now_text),
        )}
    missed_game_ids = {game_id for game_id, _model in missed_pairs}

    games: dict[str, dict[str, Any]] = {}
    for row in locks:
        game = games.setdefault(row["game_id"], {
            "game_id": row["game_id"], "season": row["season"],
            "scheduled_start_utc": row["scheduled_start_utc"],
            "home_team": row["home_team"], "away_team": row["away_team"],
            "status": "locked", "locked_at_utc": row["locked_at_utc"], "models": {},
            "result": None,
        })
        forecast = json.loads(row["forecast_json"])
        forecast.update({"model_version": row["model_version"],
                         "locked_at_utc": row["locked_at_utc"],
                         "lock_protocol": row["lock_protocol"]})
        if row["graded_at_utc"]:
            forecast["grade"] = {
                "home_score": row["final_home_score"], "away_score": row["final_away_score"],
                "home_win": bool(row["home_win"]), "winner_brier": row["winner_brier"],
                "winner_log_loss": row["winner_log_loss"],
            }
            game["status"] = "graded"
            game["result"] = {"home_score": row["final_home_score"],
                              "away_score": row["final_away_score"],
                              "home_win": bool(row["home_win"])}
        else:
            forecast["grade"] = None
        game["models"][row["model"]] = forecast

    locked_game_ids = set(games)
    for row in previews:
        if row["game_id"] in locked_game_ids:
            continue
        game = games.setdefault(row["game_id"], {
            "game_id": row["game_id"], "season": row["season"],
            "scheduled_start_utc": row["scheduled_start_utc"],
            "home_team": row["home_team"], "away_team": row["away_team"],
            "status": "missed" if row["game_id"] in missed_game_ids else "preview",
            "locked_at_utc": None, "models": {}, "result": None,
        })
        if (row["game_id"], row["model"]) in missed_pairs:
            continue
        forecast = json.loads(row["forecast_json"])
        forecast.update({"model_version": row["model_version"],
                         "previewed_at_utc": row["previewed_at_utc"]})
        game["models"][row["model"]] = forecast

    return {
        "league": "nba", "season": season, "state": _store_state(con, season),
        "source": "standalone NBA research model database",
        "default_model": "G3", "models": MODEL_INFO,
        "records": _all_record_summaries(con, season, now_text),
        "games": sorted(games.values(), key=lambda row: (row["scheduled_start_utc"], row["game_id"])),
        "benchmark": benchmark or {}, "lock_protocol": LOCK_PROTOCOL,
    }


def _local_midnight_utc(day: dt.date, timezone: Any) -> dt.datetime:
    local_midnight = timezone.localize(dt.datetime.combine(day, dt.time.min), is_dst=None)
    return local_midnight.astimezone(UTC)


def export_record_page(con: sqlite3.Connection, season: int, model: str, days: int = 7,
                       before: str | None = None, timezone_name: str = "UTC") -> dict[str, Any]:
    """Return one model's locks for the latest `days` local dates with records."""
    if model not in MODEL_IDS:
        raise ValueError(f"unknown NBA model {model!r}")
    if not 1 <= days <= 31:
        raise ValueError("days must be between 1 and 31")
    try:
        timezone = pytz.timezone(timezone_name)
    except UnknownTimeZoneError as exc:
        raise ValueError(f"unknown timezone {timezone_name!r}") from exc

    summaries = _all_record_summaries(con, season, iso_utc(dt.datetime.now(UTC)))
    if before is None:
        latest = con.execute(
            "SELECT MAX(scheduled_start_utc) FROM nba_model_locks WHERE season=? AND model=?",
            (season, model),
        ).fetchone()[0]
        if latest is None:
            return {"season": season, "model": model, "games": [], "record": summaries[model],
                    "has_more": False, "next_before": None}
        latest_day = parse_time(latest).astimezone(timezone).date()
        page_end_day = latest_day + dt.timedelta(days=1)
    else:
        try:
            page_end_day = dt.date.fromisoformat(before)
        except ValueError as exc:
            raise ValueError("before must be an ISO local date") from exc
        if page_end_day.isoformat() != before:
            raise ValueError("before must be an ISO local date")

    page_end_utc = _local_midnight_utc(page_end_day, timezone)
    candidates = con.execute(
        "SELECT scheduled_start_utc,game_id FROM nba_model_locks "
        "WHERE season=? AND model=? AND scheduled_start_utc<? "
        "ORDER BY scheduled_start_utc DESC,game_id DESC", (season, model, iso_utc(page_end_utc))
    )
    selected_days: list[dt.date] = []
    seen_days: set[dt.date] = set()
    for row in candidates:
        game_day = parse_time(row["scheduled_start_utc"]).astimezone(timezone).date()
        if game_day not in seen_days:
            seen_days.add(game_day)
            selected_days.append(game_day)
            if len(selected_days) == days:
                break
    if not selected_days:
        return {"season": season, "model": model, "games": [], "record": summaries[model],
                "has_more": False, "next_before": None}

    oldest_day = selected_days[-1]
    page_start_utc = _local_midnight_utc(oldest_day, timezone)
    rows = con.execute(
        "SELECT l.game_id,l.season,l.scheduled_start_utc,l.home_team,l.away_team,l.model_version,"
        "l.lock_protocol,l.locked_at_utc,l.forecast_json,g.final_home_score,g.final_away_score,"
        "g.home_win,g.graded_at_utc "
        "FROM nba_model_locks l LEFT JOIN nba_model_grades g USING(game_id,model) "
        "WHERE l.season=? AND l.model=? AND l.scheduled_start_utc>=? AND l.scheduled_start_utc<? "
        "ORDER BY l.scheduled_start_utc DESC,l.game_id DESC",
        (season, model, iso_utc(page_start_utc), iso_utc(page_end_utc)),
    ).fetchall()
    games = []
    for row in rows:
        forecast = json.loads(row["forecast_json"])
        forecast.update({"model_version": row["model_version"],
                         "locked_at_utc": row["locked_at_utc"],
                         "lock_protocol": row["lock_protocol"]})
        if row["graded_at_utc"]:
            forecast["grade"] = {
                "home_score": row["final_home_score"], "away_score": row["final_away_score"],
                "home_win": bool(row["home_win"]),
            }
            result = {"home_score": row["final_home_score"],
                      "away_score": row["final_away_score"], "home_win": bool(row["home_win"])}
            status = "graded"
        else:
            forecast["grade"] = None
            result = None
            status = "locked"
        games.append({
            "game_id": row["game_id"], "season": row["season"],
            "scheduled_start_utc": row["scheduled_start_utc"],
            "home_team": row["home_team"], "away_team": row["away_team"],
            "status": status, "locked_at_utc": row["locked_at_utc"],
            "result": result, "models": {model: forecast},
        })

    has_more = con.execute(
        "SELECT 1 FROM nba_model_locks WHERE season=? AND model=? AND scheduled_start_utc<? LIMIT 1",
        (season, model, iso_utc(page_start_utc)),
    ).fetchone() is not None
    return {
        "season": season, "model": model, "games": games,
        "record": summaries[model], "has_more": has_more,
        "next_before": oldest_day.isoformat() if has_more else None,
    }


def export_payload(con: sqlite3.Connection, season: int,
                   benchmark: dict[str, Any] | None = None,
                   now: dt.datetime | None = None) -> dict[str, Any]:
    now = now or dt.datetime.now(UTC)
    model_labels = {row["id"]: row for row in MODEL_INFO}
    locks = con.execute(
        "SELECT l.*,g.result_source,g.source_event_id AS grade_event_id,g.final_home_score,"
        "g.final_away_score,g.home_win,g.winner_brier,g.winner_log_loss,g.home_points_abs_error,"
        "g.away_points_abs_error,g.spread_abs_error,g.total_abs_error,g.graded_at_utc "
        "FROM nba_model_locks l LEFT JOIN nba_model_grades g USING(game_id,model) "
        "WHERE l.season=? ORDER BY l.scheduled_start_utc,l.game_id,l.model", (season,)
    ).fetchall()
    previews = []
    if _table_exists(con, "nba_model_previews"):
        previews = con.execute(
            "SELECT * FROM nba_model_previews WHERE season=? AND scheduled_start_utc>? "
            "ORDER BY scheduled_start_utc,game_id,model", (season, iso_utc(now))
        ).fetchall()
    missed_pairs = {(row[0], row[1]) for row in con.execute(
        "SELECT game_id,model FROM nba_model_lock_events WHERE season=? AND event_type='missed_t90_window'",
        (season,),
    )}
    games: dict[str, dict[str, Any]] = {}
    graded_result = {}
    per_model_rows: dict[str, list[sqlite3.Row]] = {model: [] for model in MODEL_IDS}
    for row in locks:
        game = games.setdefault(row["game_id"], {
            "game_id": row["game_id"], "season": row["season"],
            "scheduled_start_utc": row["scheduled_start_utc"],
            "home_team": row["home_team"], "away_team": row["away_team"],
            "status": "locked", "locked_at_utc": row["locked_at_utc"], "models": {},
            "result": None,
        })
        forecast = json.loads(row["forecast_json"])
        forecast.update({"model_version": row["model_version"],
                         "locked_at_utc": row["locked_at_utc"],
                         "lock_protocol": row["lock_protocol"],
                         "feature_snapshot": json.loads(row["feature_snapshot_json"])})
        if row["graded_at_utc"]:
            forecast["grade"] = {
                "home_score": row["final_home_score"], "away_score": row["final_away_score"],
                "home_win": bool(row["home_win"]), "winner_brier": row["winner_brier"],
                "winner_log_loss": row["winner_log_loss"],
                "home_points_abs_error": row["home_points_abs_error"],
                "away_points_abs_error": row["away_points_abs_error"],
                "spread_abs_error": row["spread_abs_error"], "total_abs_error": row["total_abs_error"],
                "result_source": row["result_source"], "graded_at_utc": row["graded_at_utc"],
            }
            graded_result[row["game_id"]] = forecast["grade"]
        else:
            forecast["grade"] = None
        game["models"][row["model"]] = forecast
        per_model_rows[row["model"]].append(row)
    for game_id, result in graded_result.items():
        games[game_id]["status"] = "graded"
        games[game_id]["result"] = {"home_score": result["home_score"],
                                     "away_score": result["away_score"],
                                     "home_win": result["home_win"]}

    locked_game_ids = set(games)
    for row in previews:
        if row["game_id"] in locked_game_ids:
            continue
        game = games.setdefault(row["game_id"], {
            "game_id": row["game_id"], "season": row["season"],
            "scheduled_start_utc": row["scheduled_start_utc"],
            "home_team": row["home_team"], "away_team": row["away_team"],
            "status": "missed" if row["game_id"] in {g for g, _ in missed_pairs} else "preview",
            "locked_at_utc": None, "models": {}, "result": None,
        })
        model = row["model"]
        if (row["game_id"], model) not in missed_pairs:
            forecast = json.loads(row["forecast_json"])
            forecast.update({"model_version": row["model_version"],
                             "previewed_at_utc": row["previewed_at_utc"],
                             "feature_snapshot": json.loads(row["feature_snapshot_json"])})
            game["models"][model] = forecast
    # Games that started without a lock: the last pregame preview, graded once a verified final
    # exists. Kept out of the locked record, reported beside it.
    unlocked_rows: dict[str, list[sqlite3.Row]] = {model: [] for model in MODEL_IDS}
    if _table_exists(con, "nba_model_previews"):
        past = con.execute(
            "SELECT p.*,g.result_source,g.final_home_score,g.final_away_score,g.home_win,"
            "g.winner_brier,g.winner_log_loss,g.home_points_abs_error,g.away_points_abs_error,"
            "g.spread_abs_error,g.total_abs_error,g.graded_at_utc "
            "FROM nba_model_previews p LEFT JOIN nba_model_locks l USING(game_id,model) "
            "LEFT JOIN nba_model_preview_grades g USING(game_id,model) "
            "WHERE p.season=? AND p.scheduled_start_utc<=? AND l.game_id IS NULL "
            "ORDER BY p.scheduled_start_utc,p.game_id,p.model", (season, iso_utc(now))
        ).fetchall()
        for row in past:
            game = games.setdefault(row["game_id"], {
                "game_id": row["game_id"], "season": row["season"],
                "scheduled_start_utc": row["scheduled_start_utc"],
                "home_team": row["home_team"], "away_team": row["away_team"],
                "status": "unlocked", "locked_at_utc": None, "models": {}, "result": None,
            })
            forecast = json.loads(row["forecast_json"])
            forecast.update({"model_version": row["model_version"],
                             "previewed_at_utc": row["previewed_at_utc"], "locked": False,
                             "feature_snapshot": json.loads(row["feature_snapshot_json"])})
            forecast["grade"] = None
            if row["graded_at_utc"]:
                forecast["grade"] = {
                    "home_score": row["final_home_score"], "away_score": row["final_away_score"],
                    "home_win": bool(row["home_win"]), "winner_brier": row["winner_brier"],
                    "winner_log_loss": row["winner_log_loss"],
                    "home_points_abs_error": row["home_points_abs_error"],
                    "away_points_abs_error": row["away_points_abs_error"],
                    "spread_abs_error": row["spread_abs_error"], "total_abs_error": row["total_abs_error"],
                    "result_source": row["result_source"], "graded_at_utc": row["graded_at_utc"],
                }
                game["result"] = {"home_score": row["final_home_score"],
                                  "away_score": row["final_away_score"],
                                  "home_win": bool(row["home_win"])}
            game["models"][row["model"]] = forecast
            if row["model"] in unlocked_rows:
                unlocked_rows[row["model"]].append(row)
    records = {}
    for model in MODEL_IDS:
        missed = sum(1 for _game, m in missed_pairs if m == model)
        unlocked = _record(unlocked_rows[model], 0)
        unlocked["previewed"] = unlocked.pop("locked")
        unlocked.pop("missed")
        records[model] = {"label": model_labels[model]["label"],
                          "model_version": model_labels[model]["version"],
                          "projects_scores": model_labels[model]["projects_scores"],
                          **_record(per_model_rows[model], missed),
                          "unlocked": unlocked}
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='nba_model_history'").fetchone():
        state = "awaiting_history_import"
    elif not locks and not previews:
        state = "awaiting_first_forecast"
    else:
        state = "available"
    return {
        "league": "nba", "season": season, "state": state,
        "source": "standalone NBA research model database",
        "default_model": "G3", "models": MODEL_INFO, "records": records,
        "games": sorted(games.values(), key=lambda row: (row["scheduled_start_utc"], row["game_id"])),
        "benchmark": benchmark or {},
        "lock_protocol": LOCK_PROTOCOL,
    }
