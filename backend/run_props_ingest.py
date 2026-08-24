#!/usr/bin/env python3
"""Run the registered props providers with shared locks and DB-backed cadence.

Usage:
  LP_DB_PATH=data/picks.dev.db LP_API_BASE=http://127.0.0.1:8096 \
    python run_props_ingest.py
  LP_DB_PATH=data/picks.dev.db python run_props_ingest.py --only rotowire --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import os
import sqlite3
import subprocess
import sys
import time
from typing import Dict, List, Optional, Sequence, TextIO


HERE = os.path.dirname(os.path.abspath(__file__))
LOCK_DIR = "/run/lock"

PROVIDERS = [
    {
        "id": "bovada",
        "cadence_min": 30,
        "timeout_sec": 600,
        "host_lock": "bovada",
        "steps": [["-m", "bovada_scraper", "all", "--ingest"]],
        "needs_api_base": True,
    },
    {
        "id": "underdog",
        "cadence_min": 30,
        "timeout_sec": 300,
        "host_lock": "underdog",
        "steps": [["ingest_underdog_props.py", "ufc"]],
        "needs_api_base": False,
    },
    {
        "id": "rotowire",
        "cadence_min": 360,
        "timeout_sec": 600,
        "host_lock": "rotowire",
        "steps": [
            ["ingest_rotowire_props.py", "nfl"],
            ["ingest_rotowire_props.py", "mls"],
        ],
        "needs_api_base": False,
    },
]

# A cadence equal to the timer interval never fires twice in a row without this.
# `_last_ok` reads `started_at`, so the run at *:34 measures its age from *:04:0X and
# lands a couple of seconds SHORT of 30 minutes. Measured 2026-08-24: bovada was
# cadence-skipped on the *:34 firing with "last ok 30m ago", which halves every
# provider's real cadence to 60 minutes and is invisible because a skip is not an error.
# The grace is deliberately smaller than any timer jitter we schedule against.
CADENCE_GRACE_MIN = 2.0

INGEST_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS ingest_runs (
    id           INTEGER PRIMARY KEY,
    provider     TEXT    NOT NULL,
    db_path      TEXT    NOT NULL,
    started_at   TEXT    NOT NULL,
    finished_at  TEXT,
    status       TEXT    NOT NULL,
    exit_code    INTEGER,
    detail       TEXT
);
CREATE INDEX IF NOT EXISTS ix_ingest_runs_provider
    ON ingest_runs(provider, db_path, started_at DESC);
"""


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso_now() -> str:
    return _utc_now().isoformat()


def _lock_path(prefix: str, name: str) -> str:
    return os.path.join(LOCK_DIR, "{}{}.lock".format(prefix, name))


def _run_lock_path(db_path: str) -> str:
    stem = os.path.splitext(os.path.basename(db_path))[0]
    return _lock_path("legendarypicks-props-", stem)


def _host_lock_path(host_lock: str) -> str:
    return _lock_path("legendarypicks-provider-", host_lock)


def _try_lock(path: str) -> Optional[TextIO]:
    handle = open(path, "a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def _parse_timestamp(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _last_ok(con: sqlite3.Connection, provider_id: str, db_path: str) -> Optional[dt.datetime]:
    row = con.execute(
        """SELECT started_at FROM ingest_runs
 WHERE provider = ? AND db_path = ? AND status = 'ok'
 ORDER BY started_at DESC LIMIT 1""",
        (provider_id, db_path),
    ).fetchone()
    return _parse_timestamp(row[0]) if row else None


def _insert_run(
    con: sqlite3.Connection,
    provider_id: str,
    db_path: str,
    started_at: str,
    status: str,
    finished_at: Optional[str] = None,
    exit_code: Optional[int] = None,
    detail: Optional[str] = None,
) -> int:
    cur = con.execute(
        "INSERT INTO ingest_runs(provider,db_path,started_at,finished_at,status,exit_code,detail) "
        "VALUES(?,?,?,?,?,?,?)",
        (provider_id, db_path, started_at, finished_at, status, exit_code, detail),
    )
    con.commit()
    return int(cur.lastrowid)


def _finish_run(
    con: sqlite3.Connection,
    run_id: int,
    status: str,
    exit_code: Optional[int],
    detail: Optional[str],
) -> None:
    con.execute(
        "UPDATE ingest_runs SET finished_at=?, status=?, exit_code=?, detail=? WHERE id=?",
        (_iso_now(), status, exit_code, detail[-2000:] if detail is not None else None, run_id),
    )
    con.commit()


def _combined_output(stdout: Optional[str], stderr: Optional[str]) -> str:
    return "".join(part for part in (stdout or "", stderr or "") if part)


def _print_step_output(provider_id: str, step_number: int, total_steps: int, output: str) -> None:
    print("--- {} step {} of {} output ---".format(provider_id, step_number, total_steps))
    print(output.rstrip() if output else "(no output)")


def _elapsed(started: float) -> float:
    return time.monotonic() - started


def _report(db_path: str, results: Dict[str, Dict[str, object]]) -> None:
    print("--- props ingest run report ---")
    print("  db: {}".format(db_path))
    for provider in PROVIDERS:
        result = results[provider["id"]]
        print(
            "  {:<10} {:<18} {:>5.1f}s  {}".format(
                provider["id"], result["status"], result["elapsed"], result["tail"]
            ).rstrip()
        )


def _provider_ids() -> List[str]:
    return [provider["id"] for provider in PROVIDERS]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", choices=_provider_ids(), metavar="PROVIDER")
    parser.add_argument("--force", action="store_true", help="ignore provider cadence")
    parser.add_argument("--dry-run", action="store_true", help="run supported providers without writes")
    parser.add_argument("--list", action="store_true", help="print the provider registry and exit")
    return parser


def _print_registry() -> None:
    print("provider   cadence_min  timeout_sec  host_lock  steps")
    for provider in PROVIDERS:
        steps = "; ".join(" ".join(step) for step in provider["steps"])
        print(
            "{:<10} {:>11}  {:>11}  {:<9}  {}".format(
                provider["id"], provider["cadence_min"], provider["timeout_sec"],
                provider["host_lock"], steps,
            )
        )


def _initial_results(only: Optional[str]) -> Dict[str, Dict[str, object]]:
    return {
        provider["id"]: {
            "status": "not_selected" if only and provider["id"] != only else "pending",
            "elapsed": 0.0,
            "tail": "not selected" if only and provider["id"] != only else "not run",
        }
        for provider in PROVIDERS
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    if args.list:
        _print_registry()
        return 0

    configured_db = os.environ.get("LP_DB_PATH")
    if not configured_db:
        print("ERROR: LP_DB_PATH is required", file=sys.stderr)
        return 2
    db_path = os.path.abspath(configured_db)
    if not os.path.isfile(db_path) or not os.access(db_path, os.R_OK | os.W_OK):
        print("ERROR: LP_DB_PATH is not a readable, writable database file: {}".format(db_path),
              file=sys.stderr)
        return 2

    results = _initial_results(args.only)
    try:
        con = sqlite3.connect(db_path, timeout=30)
        con.executescript(INGEST_RUNS_DDL)
        con.commit()
    except sqlite3.Error as exc:
        print("ERROR: cannot open LP_DB_PATH {}: {}".format(db_path, exc), file=sys.stderr)
        return 2

    run_lock = _try_lock(_run_lock_path(db_path))
    if run_lock is None:
        print("props ingest already running for {}; skipping".format(db_path))
        for provider in PROVIDERS:
            if not args.only or args.only == provider["id"]:
                results[provider["id"]] = {
                    "status": "skipped_lock", "elapsed": 0.0, "tail": "run lock held"
                }
        _report(db_path, results)
        con.close()
        return 0

    attempted = 0
    succeeded = 0
    try:
        for provider in PROVIDERS:
            provider_id = provider["id"]
            if args.only and args.only != provider_id:
                continue
            provider_started = time.monotonic()

            if args.dry_run and provider_id == "bovada":
                results[provider_id] = {
                    "status": "skipped_dry_run",
                    "elapsed": _elapsed(provider_started),
                    "tail": "bovada does not support --dry-run",
                }
                print("Skipping bovada: it does not support --dry-run")
                continue

            if not args.force:
                last_ok = _last_ok(con, provider_id, db_path)
                if last_ok is not None:
                    age_min = max(0.0, (_utc_now() - last_ok).total_seconds() / 60.0)
                    if age_min < provider["cadence_min"] - CADENCE_GRACE_MIN:
                        started_at = _iso_now()
                        if not args.dry_run:
                            _insert_run(
                                con, provider_id, db_path, started_at, "skipped_cadence", started_at
                            )
                        tail = "last ok {:.0f}m ago, cadence {}m".format(
                            age_min, provider["cadence_min"]
                        )
                        print("Skipping {}: {}".format(provider_id, tail))
                        results[provider_id] = {
                            "status": "skipped_cadence",
                            "elapsed": _elapsed(provider_started),
                            "tail": tail,
                        }
                        continue

            host_lock = _try_lock(_host_lock_path(provider["host_lock"]))
            if host_lock is None:
                started_at = _iso_now()
                if not args.dry_run:
                    _insert_run(con, provider_id, db_path, started_at, "skipped_lock", started_at)
                print("Skipping {}: host lock {} is held".format(provider_id, provider["host_lock"]))
                results[provider_id] = {
                    "status": "skipped_lock",
                    "elapsed": _elapsed(provider_started),
                    "tail": "host lock held",
                }
                continue

            attempted += 1
            started_at = _iso_now()
            run_id = None
            if not args.dry_run:
                run_id = _insert_run(con, provider_id, db_path, started_at, "running")

            status = "ok"
            exit_code = 0
            detail = None
            tail = "exit 0"
            try:
                if provider["needs_api_base"] and not os.environ.get("LP_API_BASE"):
                    status = "failed"
                    exit_code = 2
                    detail = "LP_API_BASE is required for provider bovada"
                    tail = detail
                    print("ERROR [{}]: {}".format(provider_id, detail))
                else:
                    child_env = os.environ.copy()
                    child_env["LP_DB_PATH"] = db_path
                    for step_number, step in enumerate(provider["steps"], start=1):
                        argv_for_step = [sys.executable] + list(step)
                        if args.dry_run:
                            argv_for_step.append("--dry-run")
                        try:
                            completed = subprocess.run(
                                argv_for_step,
                                cwd=HERE,
                                env=child_env,
                                capture_output=True,
                                text=True,
                                timeout=provider["timeout_sec"],
                            )
                        except subprocess.TimeoutExpired as exc:
                            output = _combined_output(exc.stdout, exc.stderr)
                            _print_step_output(
                                provider_id, step_number, len(provider["steps"]), output
                            )
                            status = "timeout"
                            exit_code = None
                            detail = output or "timed out after {}s".format(provider["timeout_sec"])
                            tail = "timeout on step {} of {}: {}".format(
                                step_number, len(provider["steps"]), " ".join(step)
                            )
                            break

                        output = _combined_output(completed.stdout, completed.stderr)
                        _print_step_output(provider_id, step_number, len(provider["steps"]), output)
                        if completed.returncode != 0:
                            status = "failed"
                            exit_code = completed.returncode
                            detail = output
                            tail = "exit {} on step {} of {}: {}".format(
                                completed.returncode, step_number, len(provider["steps"]),
                                " ".join(step),
                            )
                            break
            finally:
                host_lock.close()

            if status == "ok":
                succeeded += 1
            if run_id is not None:
                _finish_run(con, run_id, status, exit_code, detail)
            results[provider_id] = {
                "status": status,
                "elapsed": _elapsed(provider_started),
                "tail": tail,
            }
    finally:
        run_lock.close()
        con.close()

    _report(db_path, results)
    # A cadence skip means this provider succeeded recently enough that we chose not to
    # ask again. Counting it as "no success" made the unit red whenever the only provider
    # attempted was a broken one: measured 2026-08-24, bovada and rotowire were both
    # cadence-skipped, underdog failed as it always does, and the unit went red having
    # done nothing wrong. Red must mean the run is broken, not that it was quiet.
    healthy = succeeded + sum(
        1 for r in results.values() if r["status"] in ("skipped_cadence", "skipped_lock")
    )
    return 0 if healthy or attempted == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
