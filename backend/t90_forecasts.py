#!/usr/bin/env python3
"""Generate the T-90 forecast snapshot: a fresh forecast for each game shortly before its
cutoff, stored apart from the research ledger.

The research ledger is append-only and its reader allows exactly one row per game and model,
so a second forecast for the same game cannot live there. This module writes to its own
immutable table instead, linked back to the ledger row it supersedes for that decision.

Each snapshot is self-contained: it carries the three-model forecast, the score distribution
derived from it, the feature cutoff and source hashes, the generation time, the cutoff it is
aimed at, and the protocol version. Nothing here writes to the research ledger.

Defaults to dry-run. Use --apply to write snapshots.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import sqlite3
import sys
import types
from pathlib import Path

# ---------------------------------------------------------------------------
# sklearn is only needed for fit_frozen() (training), not for forecast(). The
# frozen artifact already carries fitted coefficients.
# ---------------------------------------------------------------------------
_sklearn_stub = types.ModuleType("sklearn")
_lm_stub = types.ModuleType("sklearn.linear_model")


class _DummyPoissonRegressor:
    def __init__(self, *args, **kwargs):
        pass

    def fit(self, X, y):
        return self


_lm_stub.PoissonRegressor = _DummyPoissonRegressor
_sklearn_stub.linear_model = _lm_stub
sys.modules.setdefault("sklearn", _sklearn_stub)
sys.modules.setdefault("sklearn.linear_model", _lm_stub)

RESEARCH_DIR = Path("/root/legendarypicks/research/nhl/prospective-2026-27")
_spec = importlib.util.spec_from_file_location("run_pipeline", RESEARCH_DIR / "run_pipeline.py")
run_pipeline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_pipeline)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import capture_nhl_game_lines as capture  # noqa: E402
from nhl_model_store import (  # noqa: E402
    DEFAULT_DB, LOCK_LEAD, MODEL_KEYS, NHLModelError, T90_FEATURE_MAX_AGE, T90_GENERATE_LEAD,
    T90_PROTOCOL_VERSION, T90_QUOTE_MAX_AGE, ensure_schema, iso_utc, lock_feed, parse_time,
    sha256_json,
)

# The score distribution is a deterministic expansion of the frozen expected goals and the
# frozen tie-break parameter. No outcome and no market input, so it can be derived inline and
# stored inside the snapshot rather than appended to the research distribution ledger.
DISTRIBUTION_KEYS = (
    "score_distribution_goal_support",
    "home_goal_marginal_probabilities",
    "away_goal_marginal_probabilities",
    "joint_score_probability_matrix_home_rows_away_columns",
)


def target_lock_utc(scheduled_start_utc: str) -> dt.datetime:
    """The cutoff a game is locked at: 90 minutes before puck drop."""
    return parse_time(scheduled_start_utc) - LOCK_LEAD


def as_instant(value) -> dt.datetime | None:
    """A feature source date or timestamp as an aware instant.

    The pipeline's `feature_max_source_dates` are plain dates, not timestamps, so they cannot
    go through the store's `parse_time`. A date means midnight UTC on that day.
    """
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def as_date(value) -> dt.date | None:
    """A feature source date as a date. Staleness is judged in whole days, not instants."""
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def source_ledger_rows(ledger_path: str | None = None) -> dict[tuple, dict]:
    """The research ledger's own row for each game and model, used only as the link back."""
    path = ledger_path or str(run_pipeline.LEDGER)
    rows = run_pipeline.read_jsonl(path)
    return {(int(r["game_id"]), str(r["model_name"])): r for r in rows}


def plan(con: sqlite3.Connection, games: list[dict], now: dt.datetime,
         protocol: str = T90_PROTOCOL_VERSION) -> list[dict]:
    """Games whose snapshot is due and not yet taken.

    A game is due once it is inside the generation lead of its cutoff and has not started. A
    snapshot already present is never regenerated, so a retry is idempotent and a late run
    cannot overwrite the frozen forecast.
    """
    taken = {(row[0], row[1]) for row in con.execute(
        "SELECT game_id, model_key FROM nhl_t90_forecasts WHERE protocol_version=?", (protocol,))}
    due = []
    for game in games:
        gid = int(game["game_id"])
        start = parse_time(game["start_time_utc"])
        if now >= start:
            continue  # already under way: the window has passed
        target = target_lock_utc(game["start_time_utc"])
        if now < target - T90_GENERATE_LEAD:
            continue  # too early; the odds and features would move again
        if all((str(gid), model_key) in taken for model_key in MODEL_KEYS):
            continue
        due.append({"game": game, "game_id": gid, "target_lock_utc": target,
                    "scheduled_start_utc": start})
    return due


def record_failure(con: sqlite3.Connection, game_id, model_key: str, model_version: str,
                   stage: str, reason: str, detail: str | None, observed_at: dt.datetime,
                   target_lock: dt.datetime, protocol: str = T90_PROTOCOL_VERSION) -> bool:
    """Log what stopped a snapshot or its quote. Append-only, one row per stage per model.

    Returns True when this call was the one that recorded it, so a repeated failure does not
    inflate the report.
    """
    before = con.total_changes
    con.execute("""INSERT OR IGNORE INTO nhl_t90_failures
        (game_id,model_key,model_version,protocol_version,stage,reason,detail,observed_at_utc,target_lock_utc)
        VALUES (?,?,?,?,?,?,?,?,?)""",
                (str(game_id), model_key, model_version, protocol, stage, reason, detail,
                 iso_utc(observed_at), iso_utc(target_lock)))
    return con.total_changes > before


def freeze_snapshot(con: sqlite3.Connection, game: dict, rows: list[dict], *, generated_at: dt.datetime,
                    source_rows: dict, protocol: str = T90_PROTOCOL_VERSION) -> int:
    """Store one immutable snapshot row per model for this game. Returns the row count.

    The snapshot is self-contained, so nothing downstream has to reach back into the research
    ledger to price or grade it. Writing is guarded: a snapshot that already exists is left
    alone rather than replaced.
    """
    if not rows:
        raise NHLModelError("no forecast rows to freeze for game %s" % game.get("game_id"))
    gid = str(game["game_id"])
    start = parse_time(game["start_time_utc"])
    target = target_lock_utc(game["start_time_utc"])
    lead_seconds = int((target - generated_at).total_seconds())
    feature_snapshot = rows[0]["feature_snapshot"]
    feature_source_sha256 = sha256_json({
        "xg_source_hashes": feature_snapshot.get("xg_source_hashes"),
        "schedule_source": feature_snapshot.get("schedule_source"),
        "model_artifact_sha256": feature_snapshot.get("model_artifact_sha256"),
    })
    max_source_dates = [v for v in (feature_snapshot.get("feature_max_source_dates") or {}).values() if v]
    feature_cutoff = max(max_source_dates) if max_source_dates else None
    tie_home = float(json.loads(run_pipeline.MODEL_PATH.read_text())["historical_home_shootout_win_rate"])
    written = 0
    for row in rows:
        model_key = str(row["model_name"])
        version = str(row["model_version"])
        source = source_rows.get((int(gid), model_key))
        details = run_pipeline.score_markets(
            float(row["home_expected_goals"]), float(row["away_expected_goals"]), tie_home)
        forecast = dict(row)
        forecast.update({key: details[key] for key in DISTRIBUTION_KEYS})
        forecast["score_distribution_source"] = {
            "derivation": "derived inline from the frozen snapshot's expected goals and frozen "
                          "tie-break parameter; no outcome or market input",
            "model_artifact_sha256": row.get("model_artifact_sha256"),
        }
        payload = {
            "game_id": int(gid),
            "game_date": row["game_date"],
            "scheduled_start_utc": row["scheduled_start_utc"],
            "home_team": row["home_team"],
            "away_team": row["away_team"],
            "forecasted_at_utc": iso_utc(generated_at),
            "features_as_of_utc": feature_snapshot.get("as_of_utc"),
            "feature_snapshot": feature_snapshot,
            "models": {model_key: forecast},
        }
        con.execute("""INSERT INTO nhl_t90_forecasts
            (game_id,model_key,model_version,protocol_version,season,game_date,scheduled_start_utc,
             target_lock_utc,home_team,away_team,source_forecast_id,source_ledger_sha256,
             feature_cutoff_utc,features_as_of_utc,generated_at_utc,lead_seconds,
             feature_source_sha256,model_artifact_sha256,snapshot_sha256,snapshot_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (gid, model_key, version, protocol, int(row.get("season") or 0), row["game_date"],
                     row["scheduled_start_utc"], iso_utc(target), row["home_team"], row["away_team"],
                     str((source or {}).get("forecast_id") or ""),
                     sha256_json(source) if source else "",
                     feature_cutoff or "", iso_utc(generated_at), iso_utc(generated_at),
                     lead_seconds, feature_source_sha256, str(row.get("model_artifact_sha256") or ""),
                     sha256_json(payload), json.dumps(payload, sort_keys=True, separators=(",", ":"))))
        written += 1
    return written


def t90_payload(con: sqlite3.Connection, season: int, protocol: str = T90_PROTOCOL_VERSION,
                game_ids: list[str] | None = None) -> dict:
    """The stored snapshots as a forecast feed, so the lock path needs no special case."""
    grouped: dict[str, dict] = {}
    model_versions: dict[str, str] = {}
    sql = ("SELECT * FROM nhl_t90_forecasts WHERE season=? AND protocol_version=? "
           "ORDER BY scheduled_start_utc,game_id,model_key")
    params: list = [int(season), protocol]
    if game_ids is not None:
        sql = ("SELECT * FROM nhl_t90_forecasts WHERE protocol_version=? AND game_id IN (%s) "
               "ORDER BY scheduled_start_utc,game_id,model_key"
               % ",".join("?" for _ in game_ids))
        params = [protocol] + [str(g) for g in game_ids]
    for row in con.execute(sql, params):
        payload = json.loads(row["snapshot_json"])
        gid = str(row["game_id"])
        game = grouped.get(gid)
        if game is None:
            game = {key: payload[key] for key in
                    ("game_id", "game_date", "scheduled_start_utc", "home_team", "away_team",
                     "forecasted_at_utc", "features_as_of_utc", "feature_snapshot")}
            game["models"] = {}
            game["_protocol_version"] = row["protocol_version"]
            game["_target_lock_utc"] = row["target_lock_utc"]
            game["_lead_seconds"] = row["lead_seconds"]
            game["_snapshot_sha256"] = row["snapshot_sha256"]
            grouped[gid] = game
        game["models"].update(payload["models"])
        model_versions[row["model_version"]] = row["model_version"]
    return {"model_version": next(iter(model_versions), ""), "games": list(grouped.values())}


def generate(db_path: str = DEFAULT_DB, now: dt.datetime | None = None, *, horizon_hours: float = 24,
             apply: bool = False, log=print) -> dict:
    """Take the due snapshots. Returns a report; writes only when apply is true."""
    now = now or dt.datetime.now(dt.timezone.utc)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    report = {"due": 0, "snapshots": 0, "already": 0, "failed": 0, "not_due": 0}
    try:
        ensure_schema(con)
        games, schedule_meta = run_pipeline.live_schedule(now, horizon_hours)
        due = plan(con, games, now)
        report["due"] = len(due)
        report["not_due"] = len(games) - len(due)
        if not due:
            return report
        if not apply:
            for item in due:
                log("  DUE: %s @ %s at %s (cutoff %s)" % (
                    item["game"]["away_team"], item["game"]["home_team"],
                    iso_utc(item["scheduled_start_utc"]), iso_utc(item["target_lock_utc"])))
            return report
        model = json.loads(run_pipeline.MODEL_PATH.read_text())
        sources = source_ledger_rows()
        target_games = [item["game"] for item in due]
        # One feature context for the whole batch: every game in it is read as of the same
        # instant, so no game sees features another game's fetch advanced.
        asof = dt.datetime.now(dt.timezone.utc)
        context = run_pipeline.feature_context(asof, target_games, schedule_meta)
        generated_at = dt.datetime.now(dt.timezone.utc)
        rows = run_pipeline.build_forecasts(target_games, generated_at, model, context, schedule_meta)
        by_game: dict[int, list[dict]] = {}
        for row in rows:
            by_game.setdefault(int(row["game_id"]), []).append(row)
        for item in due:
            gid = item["game_id"]
            game_rows = by_game.get(gid) or []
            feature_snapshot = game_rows[0]["feature_snapshot"] if game_rows else {}
            max_dates = [v for v in (feature_snapshot.get("feature_max_source_dates") or {}).values() if v]
            cutoff = as_date(max(max_dates)) if max_dates else None
            # Stale inputs are an explicit failure, not a snapshot quietly built on old data.
            # Judged in whole days against today: the pipeline reports dates, and a team's last
            # game is legitimately a few days back.
            if cutoff is None or now.date() - cutoff > T90_FEATURE_MAX_AGE:
                for model_key in sorted(MODEL_KEYS):
                    if record_failure(con, gid, model_key, model["model_version"], "generation",
                                      "features_stale",
                                      "latest feature source date %s" % (cutoff or "missing"),
                                      now, item["target_lock_utc"]):
                        report["failed"] += 1
                continue
            try:
                written = freeze_snapshot(con, item["game"], game_rows, generated_at=generated_at,
                                          source_rows=sources)
                con.commit()
                report["snapshots"] += written
            except sqlite3.IntegrityError:
                con.rollback()
                report["already"] += 1
            except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
                con.rollback()
                for model_key in sorted(MODEL_KEYS):
                    if record_failure(con, gid, model_key, model["model_version"], "generation",
                                      "generation_failed", str(exc)[:400], now,
                                      item["target_lock_utc"]):
                        report["failed"] += 1
                con.commit()
        return report
    finally:
        con.close()


def lock_t90(db_path: str = DEFAULT_DB, now: dt.datetime | None = None, *, feed_path: str | None = None,
             fetch=None, apply: bool = False, horizon_hours: float = 24, log=print,
             games: list[dict] | None = None) -> dict:
    """Lock each T-90 snapshot at its cutoff against a quote captured as close to it as possible.

    A game inside its window with no snapshot is recorded as a generation failure and is not
    locked from the older forecast, so a noon forecast is never presented as a T-90 one.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    report = {"window": 0, "due": 0, "locked": 0, "pick_rows": 0, "missing_picks": 0,
              "missing_snapshot": 0, "quote": None}
    try:
        ensure_schema(con)
        if feed_path is not None and fetch is not None:
            # Capture at the cutoff rather than inheriting whatever the read path last fetched.
            report["quote"] = capture.refresh_lines(db_path, feed_path, fetch, now, log=log,
                                                    max_age=T90_QUOTE_MAX_AGE)
        games, _meta = run_pipeline.live_schedule(now, horizon_hours) if games is None else (games, {})
        expected_version = str(json.loads(run_pipeline.MODEL_PATH.read_text())["model_version"])
        taken = {(str(r["game_id"]), r["model_key"]) for r in con.execute(
            "SELECT game_id, model_key FROM nhl_t90_forecasts WHERE protocol_version=?",
            (T90_PROTOCOL_VERSION,))}
        due = []
        for game in games:
            gid = str(game["game_id"])
            start = parse_time(game["start_time_utc"])
            target = target_lock_utc(game["start_time_utc"])
            if not (target <= now < start):
                continue  # before the cutoff, or already under way
            report["window"] += 1
            missing = sorted(m for m in MODEL_KEYS if (gid, m) not in taken)
            if missing:
                for model_key in missing:
                    if record_failure(con, gid, model_key, expected_version, "generation",
                                      "snapshot_missing", "no T-90 snapshot at the cutoff",
                                      now, target):
                        report["missing_snapshot"] += 1
                continue
            due.append(game)
        con.commit()
        report["due"] = len(due)
        if not due:
            return report
        if not apply:
            return report
        payload = t90_payload(con, 0, game_ids=[str(g["game_id"]) for g in due])
        locked = lock_feed(con, payload, now)
        report["locked"] = locked["locked_rows"]
        report["pick_rows"] = locked["pick_rows"]
        report["missing_picks"] = locked["missing_picks"]
        return report
    finally:
        con.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--horizon-hours", type=float, default=24)
    parser.add_argument("--apply", action="store_true", help="Write snapshots (default: dry-run)")
    parser.add_argument("--lock", action="store_true",
                        help="Lock the snapshots at their cutoff instead of generating them")
    parser.add_argument("--feed", default=None, help="Feed path for the quote refresh (with --lock)")
    parser.add_argument("--refresh", action="store_true", help="Capture fresh Bovada odds (with --lock)")
    args = parser.parse_args(argv)
    now = dt.datetime.now(dt.timezone.utc)
    if args.lock:
        fetch = None
        if args.refresh:
            fetch = capture.fetch_events
        report = lock_t90(args.db, now, feed_path=args.feed, fetch=fetch, apply=args.apply,
                          horizon_hours=args.horizon_hours)
        quote = report["quote"]
        print("%s lock at %s: %d in window, %d due, %d locked, %d picks, %d missing picks, "
              "%d missing snapshots, quote %s" % (
                  "applied" if args.apply else "dry-run", iso_utc(now), report["window"],
                  report["due"], report["locked"], report["pick_rows"], report["missing_picks"],
                  report["missing_snapshot"],
                  "not attempted" if quote is None else quote.get("reason")))
        return 0
    report = generate(args.db, now, horizon_hours=args.horizon_hours, apply=args.apply)
    print("%s at %s: %d due, %d snapshots written, %d already present, %d failed, %d not due" % (
        "applied" if args.apply else "dry-run", iso_utc(now), report["due"], report["snapshots"],
        report["already"], report["failed"], report["not_due"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
