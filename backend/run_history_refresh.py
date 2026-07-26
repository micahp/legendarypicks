#!/usr/bin/env python3
"""Run production-safe player-history refreshes one league at a time.

Only refreshers that fetch their complete bounded source plan before opening a
short SQLite transaction belong here. A failure in one league is reported and
does not prevent the remaining independent leagues from being attempted.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Sequence

import history_refresh_common as common
import run_mlb_daily_history_ingest as mlb
import run_ufc_current_card_ingest as ufc


HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(HERE, "data", "picks.db")
JobRunner = Callable[[str, bool, Callable[[str], None]], dict]


@dataclass(frozen=True)
class RefreshJob:
    league: str
    runner: JobRunner


def _run_ufc(
    db_path: str, apply: bool, emit: Callable[[str], None]
) -> dict:
    return ufc.run(db_path, apply=apply, emit=emit)


def _run_mlb(
    db_path: str, apply: bool, emit: Callable[[str], None]
) -> dict:
    return mlb.run(db_path, apply=apply, emit=emit)


DEFAULT_JOBS = (
    RefreshJob("ufc", _run_ufc),
    RefreshJob("mlb", _run_mlb),
)

DEFERRED = {
    "wc": (
        "not scheduled: the World Cup is out of season until 2030. Refreshing it "
        "four times a day spent production writes and box resources on a dormant "
        "league. See AGENTS.md section 0 -- wc code is dormant, not active"
    ),
    "mlb_pitching": (
        "not scheduled: the existing multi-day Statcast pitcher path can "
        "parallelize and collides with batting natural keys"
    ),
    "nba": (
        "not scheduled: the existing ingester performs source requests while "
        "holding daily write transactions and can create duplicate identities"
    ),
    "nfl": (
        "not scheduled: the existing full-season writer still needs a verified "
        "backup and short-transaction apply phase before in-season use"
    ),
    "nhl": (
        "not scheduled: the existing ingester holds a writer during player "
        "requests and only covers regular-season gameType 2, not playoffs"
    ),
}


def run(
    db_path: str,
    apply: bool,
    emit: Callable[[str], None] = print,
    jobs: Optional[Sequence[RefreshJob]] = None,
) -> dict:
    db_path = os.path.abspath(db_path)
    if not os.path.isfile(db_path) or os.path.getsize(db_path) <= 0:
        raise RuntimeError("database is missing or empty: {}".format(db_path))
    integrity = common.integrity_check(db_path)
    if integrity != "ok":
        raise RuntimeError(
            "production integrity_check returned {}".format(integrity)
        )

    selected_jobs = tuple(jobs) if jobs is not None else DEFAULT_JOBS
    mode = "apply" if apply else "dry run"
    emit(
        "History refresh {} starting: {} sequential jobs".format(
            mode, len(selected_jobs)
        )
    )
    results: Dict[str, dict] = {}
    failures: Dict[str, dict] = {}
    for job in selected_jobs:
        emit("=== {} history refresh ===".format(job.league.upper()))
        try:
            results[job.league] = job.runner(db_path, apply, emit)
        except Exception as exc:
            failure = {
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            failures[job.league] = failure
            emit(
                "{} FAILED: {}: {}".format(
                    job.league.upper(),
                    failure["error_type"],
                    failure["error"],
                )
            )

    for league in sorted(DEFERRED):
        emit("{} {}".format(league.upper(), DEFERRED[league]))
    emit(
        "History refresh finished: {} succeeded, {} failed".format(
            len(results), len(failures)
        )
    )
    return {
        "ok": not failures,
        "mode": mode,
        "results": results,
        "failures": failures,
        "deferred": dict(DEFERRED),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--db", default=os.environ.get("LP_DB_PATH") or DEFAULT_DB
    )
    parser.add_argument(
        "--league",
        action="append",
        choices=[job.league for job in DEFAULT_JOBS],
        help="run only this qualified league; repeat to select more",
    )
    args = parser.parse_args(argv)
    jobs = None
    if args.league:
        selected = set(args.league)
        jobs = [job for job in DEFAULT_JOBS if job.league in selected]
    try:
        result = run(args.db, apply=args.apply, jobs=jobs)
    except Exception as exc:
        print("ERROR: {}: {}".format(type(exc).__name__, exc))
        return 2
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
