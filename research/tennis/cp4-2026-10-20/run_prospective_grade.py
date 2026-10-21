#!/usr/bin/env python3
"""Prospective grade for CP4: frozen lock distributions against settled results.

Only locks that were created before their match started and carry a distribution frozen under
tennis-counts/2026-10-20 are graded. A cell is reported as n alone until it has MIN_MATCHES graded
matches; below that no metric is printed and the verdict is INSUFFICIENT_PROSPECTIVE_DATA.

Metrics, gates and thresholds are the ones fixed in RESULTS.md. The verdict is the five calibration
gates only. Not computed here: the reference-beating and runner-up legs (no reference or runner-up
distribution is frozen, so they cannot be graded prospectively) and the clustered bootstrap.

The grader only reads. Run it on a copy of the database or on the live dev database opened read-only:

  python3 research/tennis/cp4-2026-10-20/run_prospective_grade.py --db /root/picks.tennis-cp4.db
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import random
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "backend"))

import tennis_count_distributions as tcd  # noqa: E402
import tennis_props_rate_backtest as rb  # noqa: E402
import tennis_total_games_backtest as tgb  # noqa: E402

PIT_SEED = 20261020
MIN_MATCHES = 200
KS_MAX = 0.02
TAIL_BAND = (0.04, 0.06)
COVER_SLACK = 0.02
P95_MAX = 0.06
P99_MAX = 0.015
THRESHOLD_TOLERANCE = 0.02
NOMINAL = {"50": 0.50, "80": 0.80, "90": 0.90}
# Book-style lines fixed in RESULTS.md. Over L means at least floor(L) + 1.
LINES = {
    ("atp", "aces"): (4.5, 5.5, 6.5), ("atp", "double_faults"): (1.5, 2.5, 3.5),
    ("atp", "total_games"): (21.5, 22.5, 23.5),
    ("wta", "aces"): (1.5, 2.5, 3.5), ("wta", "double_faults"): (2.5, 3.5, 4.5),
    ("wta", "total_games"): (20.5, 21.5, 22.5),
}
CELLS = ("aces", "double_faults", "total_games")
TERMINAL_STATUS = ("cancel", "postpon", "walkover", "abandon", "default", "retir")
OUTCOME_SOURCE = {
    "aces": "research_player_match_outcomes (verified tiers; eligible_cp4 = 1 only)",
    "double_faults": "research_player_match_outcomes (verified tiers; eligible_cp4 = 1 only)",
    "total_games": "scoreboard_snapshots state=post, set games summed (as grade_tennis_model reads them)",
}
SCOPE = ("calibration gates only; reference and runner-up legs and the clustered bootstrap are not computed, "
         "because no reference or runner-up distribution is frozen")


class LookAheadError(RuntimeError):
    """A frozen forecast was built from history that reaches its match date or later."""


def table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def match_date_utc(start_time: str) -> str:
    """The match date on the UTC clock the lock sweep uses for model_day (the first ten characters of start_time)."""
    start = dt.datetime.fromisoformat(start_time)
    if start.tzinfo is None:
        raise ValueError(f"start_time {start_time!r} has no timezone; the match date cannot be fixed")
    return start.astimezone(dt.timezone.utc).date().isoformat()


def check_no_look_ahead(model_day: Any, match_date: str, where: str) -> None:
    """Frozen history is built from rows dated strictly before model_day, so it is pre-match only when
    model_day is not after the match date. Fails loudly on a missing cutoff, which means the guard
    cannot be applied, and on a cutoff after the match, which lets rows on or after the match in.
    """
    if not model_day:
        raise LookAheadError(f"{where}: frozen parameters carry no model_day; look-ahead cannot be ruled out")
    if dt.date.fromisoformat(str(model_day)) > dt.date.fromisoformat(match_date):
        raise LookAheadError(f"{where}: history cutoff {model_day} is after the match date {match_date}; "
                             "source rows on or after the match could have shaped the forecast")


def load_frozen(con: sqlite3.Connection) -> Dict[str, Any]:
    """Frozen distributions keyed by (league, game_id), for locks made before their match started.

    A missing table is a count of zero, not an error: the distribution table is created by the lock
    sweep, so before the first distribution is frozen every lock is reported as having none.
    """
    accounting = {"locks_total": 0, "locks_with_frozen_distribution": 0,
                  "locks_no_distribution_frozen": 0, "excluded_not_prospective": 0,
                  "excluded_frozen_at_mismatch": 0, "distribution_rows_without_lock": 0,
                  "distribution_table_present": False}
    if not table_exists(con, "tennis_model_locks"):
        return {"locks": {}, "accounting": accounting}
    accounting["locks_total"] = con.execute("SELECT COUNT(*) FROM tennis_model_locks").fetchone()[0]
    if not table_exists(con, "tennis_model_lock_distributions"):
        accounting["locks_no_distribution_frozen"] = accounting["locks_total"]
        return {"locks": {}, "accounting": accounting}
    accounting["distribution_table_present"] = True
    accounting["distribution_rows_without_lock"] = con.execute(
        "SELECT COUNT(*) FROM tennis_model_lock_distributions d WHERE d.model_version=? AND NOT EXISTS "
        "(SELECT 1 FROM tennis_model_locks l WHERE l.league=d.league AND l.game_id=d.game_id)",
        (tcd.MODEL_VERSION,)).fetchone()[0]
    rows = con.execute(
        "SELECT d.league, d.game_id, d.cell, d.side, d.parameters, d.support_start, d.pmf, d.locked_at AS frozen_at, "
        "l.locked_at, l.start_time FROM tennis_model_lock_distributions d "
        "JOIN tennis_model_locks l ON l.league=d.league AND l.game_id=d.game_id "
        "WHERE d.model_version=? ORDER BY d.league, d.game_id, d.cell, d.side",
        (tcd.MODEL_VERSION,),
    ).fetchall()
    locks: Dict[tuple, Optional[Dict[str, Any]]] = {}
    for row in rows:
        key = (row["league"], row["game_id"])
        if key not in locks:
            locked = dt.datetime.fromisoformat(row["locked_at"])
            start = dt.datetime.fromisoformat(row["start_time"])
            if locked >= start:
                accounting["excluded_not_prospective"] += 1
                locks[key] = None
                continue
            if row["frozen_at"] != row["locked_at"]:
                accounting["excluded_frozen_at_mismatch"] += 1
                locks[key] = None
                continue
            locks[key] = {"sides": {}, "match_date": match_date_utc(row["start_time"])}
            accounting["locks_with_frozen_distribution"] += 1
        if locks[key] is None:
            continue
        parameters = json.loads(row["parameters"])
        check_no_look_ahead(parameters.get("model_day"), locks[key]["match_date"],
                            f"{key[0]} {key[1]} {row['cell']}/{row['side']}")
        locks[key]["sides"].setdefault(row["cell"], {})[row["side"]] = {
            "parameters": parameters,
            "support_start": int(row["support_start"]),
            "pmf": json.loads(row["pmf"]),
        }
    accounting["locks_no_distribution_frozen"] = accounting["locks_total"] - len(locks)
    return {"locks": {key: value for key, value in locks.items() if value is not None},
            "accounting": accounting}


def observed_games(con: sqlite3.Connection, league: str, game_id: str) -> Optional[int]:
    """Total games from a completed final scoreboard, or None. Same reading as grade_tennis_model."""
    if not table_exists(con, "scoreboard_snapshots"):
        return None
    row = con.execute(
        "SELECT payload FROM scoreboard_snapshots WHERE league=? AND game_id=? AND state='post' "
        "ORDER BY fetched_at DESC LIMIT 1", (league, game_id)).fetchone()
    if row is None or not row[0]:
        return None
    game = json.loads(row[0])
    status = str(game.get("status") or "").lower()
    # ESPN leaves `completed` null on most final rows, so a final status is also a completed match.
    if game.get("completed") is not True and status != "final":
        return None
    if any(token in status for token in TERMINAL_STATUS):
        return None
    home = (game.get("home") or {}).get("sets") or []
    away = (game.get("away") or {}).get("sets") or []
    if not home or len(home) != len(away):
        return None
    try:
        values = [int(value) for value in home + away]
    except (TypeError, ValueError):
        return None
    return sum(values) if all(value >= 0 for value in values) else None


def observed_player_values(con: sqlite3.Connection, league: str, game_id: str, cell: str) -> Optional[Dict[str, int]]:
    """Verified aces or double faults per side, from the verified outcome table only.

    Returns None unless both sides are present and eligible (Final, verified tier). A missing table
    yields None for every match, so the cell reports zero graded matches.
    """
    if not table_exists(con, "research_player_match_outcomes"):
        return None
    column = "aces" if cell == "aces" else "double_faults"
    rows = con.execute(
        f"SELECT side, {column} FROM research_player_match_outcomes "
        "WHERE tour=? AND espn_game_id=? AND eligible_cp4=1", (league, game_id)).fetchall()
    values = {side: value for side, value in rows if value is not None}
    return values if set(values) == {"home", "away"} else None


def build_targets(con: sqlite3.Connection, frozen: Dict[str, Any], league: str, cell: str) -> Dict[str, Any]:
    """One target per graded player (counts) or per graded match (games), with its frozen PMF.

    Each target's pmf[i] is the probability of value start + i. Counts start at 0, so the RESULTS
    scorers (indexed by value) take the same array; games use their own support tuple.
    """
    targets: List[Dict[str, Any]] = []
    skipped = {"outcome_missing": 0, "outside_support": 0, "no_distribution": 0}
    for (lg, game_id), lock in sorted(frozen["locks"].items()):
        if lg != league:
            continue
        sides = lock["sides"].get(cell) or {}
        if cell == "total_games":
            pairs = [("match", sides.get("match"))]
            observed_by_side = {"match": observed_games(con, league, game_id)}
        else:
            pairs = [("home", sides.get("home")), ("away", sides.get("away"))]
            observed_by_side = observed_player_values(con, league, game_id, cell) or {}
        if any(frozen_side is None for _, frozen_side in pairs):
            skipped["no_distribution"] += 1
            continue
        if any(observed_by_side.get(side) is None for side, _ in pairs):
            skipped["outcome_missing"] += 1
            continue
        for side, frozen_side in pairs:
            start = frozen_side["support_start"]
            pmf = frozen_side["pmf"]
            value = int(observed_by_side[side])
            if not 0 <= value - start < len(pmf):
                skipped["outside_support"] += 1
                continue
            targets.append({
                "game_id": game_id, "side": side, "start": start, "pmf": pmf, "observed": value,
                "support": tuple(range(start, start + len(pmf))) if cell == "total_games" else None,
            })
    return {"targets": targets, "skipped": skipped}


def _mass(target: Dict[str, Any], value: int) -> float:
    index = value - target["start"]
    return target["pmf"][index] if 0 <= index < len(target["pmf"]) else 0.0


def _below(target: Dict[str, Any], value: int) -> float:
    """P(X < value)."""
    return sum(target["pmf"][:min(max(value - target["start"], 0), len(target["pmf"]))])


def _quantile(target: Dict[str, Any], level: float) -> int:
    """Smallest value v with P(X <= v) >= level."""
    total = 0.0
    for index, probability in enumerate(target["pmf"]):
        total += probability
        if total >= level:
            return index + target["start"]
    return target["start"] + len(target["pmf"]) - 1


def _score(target: Dict[str, Any]) -> Dict[str, float]:
    if target["support"] is None:
        full = [0.0] * target["start"] + target["pmf"]
        return rb.score_pmf(full, target["observed"])
    return tgb.pmf_scores(target["pmf"], target["support"], target["observed"])


def metrics_for(targets: List[Dict[str, Any]], league: str, cell: str) -> Dict[str, Any]:
    rng = random.Random(PIT_SEED)
    pits = [_below(target, target["observed"]) + rng.random() * _mass(target, target["observed"])
            for target in targets]
    n = len(pits)
    ordered = sorted(pits)
    ks = max(max((i + 1) / n - x, x - i / n) for i, x in enumerate(ordered))
    deciles = [sum(1 for x in pits if k / 10 <= x < (k + 1) / 10 or (k == 9 and x == 1.0)) / n for k in range(10)]
    low_tail = sum(1 for x in pits if x < 0.05) / n
    high_tail = sum(1 for x in pits if x > 0.95) / n

    scores = [_score(target) for target in targets]
    coverage = {label: sum(score["cover_" + label] for score in scores) / n for label in NOMINAL}
    upper = {}
    for label, level in (("p95", 0.95), ("p99", 0.99)):
        upper[label] = sum(1 for target in targets if target["observed"] > _quantile(target, level)) / n

    thresholds = []
    for line in LINES[(league, cell)]:
        threshold = math.floor(line) + 1
        predicted = sum(1.0 - _below(target, threshold) for target in targets) / n
        observed_over = sum(float(target["observed"] >= threshold) for target in targets) / n
        brier = sum((1.0 - _below(target, threshold) - float(target["observed"] >= threshold)) ** 2
                    for target in targets) / n
        thresholds.append({"line": line, "predicted_over": predicted, "observed_over": observed_over,
                           "gap": observed_over - predicted, "brier": brier})

    gates = {
        "pit_uniformity": ks <= KS_MAX,
        "pit_tails": all(TAIL_BAND[0] <= share <= TAIL_BAND[1] for share in (low_tail, high_tail)),
        "coverage": all(coverage[label] >= NOMINAL[label] - COVER_SLACK for label in NOMINAL),
        "upper_tail": upper["p95"] <= P95_MAX and upper["p99"] <= P99_MAX,
        "threshold_reliability": all(abs(row["gap"]) <= THRESHOLD_TOLERANCE for row in thresholds),
    }
    return {
        "pit": {"ks": ks, "deciles": deciles, "share_below_0.05": low_tail, "share_above_0.95": high_tail},
        "coverage": coverage,
        "upper_tail": {"share_above_p95": upper["p95"], "share_above_p99": upper["p99"]},
        "threshold_reliability": thresholds,
        "crps": sum(score["crps"] for score in scores) / n,
        "log_score": sum(score["log_score"] for score in scores) / n,
        "gates": gates,
        "verdict": "CALIBRATION_GATES_PASS" if all(gates.values()) else "CALIBRATION_GATES_FAIL",
    }


def grade(con: sqlite3.Connection) -> Dict[str, Any]:
    frozen = load_frozen(con)
    report: Dict[str, Any] = {
        "model_version": tcd.MODEL_VERSION, "min_matches": MIN_MATCHES, "scope": SCOPE,
        "source_tables": {name: table_exists(con, name) for name in
                          ("tennis_model_locks", "tennis_model_lock_distributions",
                           "research_player_match_outcomes", "scoreboard_snapshots")},
        "accounting": frozen["accounting"], "cells": {},
    }
    for league in ("atp", "wta"):
        for cell in CELLS:
            built = build_targets(con, frozen, league, cell)
            matches = len({target["game_id"] for target in built["targets"]})
            entry: Dict[str, Any] = {
                "matches_graded": matches, "targets": len(built["targets"]),
                "skipped": built["skipped"], "outcome_source": OUTCOME_SOURCE[cell],
            }
            if matches < MIN_MATCHES:
                entry["verdict"] = "INSUFFICIENT_PROSPECTIVE_DATA"
                entry["note"] = f"{matches} graded matches; {MIN_MATCHES} required; no metrics reported"
            else:
                entry.update(metrics_for(built["targets"], league, cell))
            report["cells"][f"{league}/{cell}"] = entry
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--db", required=True,
                        help="a copy of the database, or the live dev database; opened read-only, never written")
    parser.add_argument("--out", help="also write the JSON report here")
    args = parser.parse_args()
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        report = grade(con)
    finally:
        con.close()
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
