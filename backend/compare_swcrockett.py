#!/usr/bin/env python3
"""Compare one swcrockett capture with locked incumbent NFL v1 on eligible games.

Reads the dev database only, in SQLite read-only/query-only mode. Captures marked
post_kickoff never enter the score population. Paired differences are swcrockett
minus v1, so negative values favor swcrockett for these proper scores.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from .swcrockett_import import kickoff_utc
    from .team_codes import normalize
except ImportError:  # direct execution: python3 backend/compare_swcrockett.py
    from swcrockett_import import kickoff_utc
    from team_codes import normalize


DEFAULT_DB = Path("/root/legendarypicks/backend/data/picks.dev.db")
SEED = 20261019
BOOTSTRAP_REPS = 2000
EPSILON = 1e-15


class CompareError(RuntimeError):
    pass


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise CompareError(f"timestamp is not timezone-aware: {value!r}")
    return parsed.astimezone(timezone.utc)


def monday_block(season: int, kickoff: datetime) -> tuple[int, str]:
    monday = kickoff.date() - timedelta(days=kickoff.weekday())
    return season, monday.isoformat() + "T00:00:00Z"


def score_rows(rows: list[dict[str, object]]) -> dict[str, float | int]:
    n = len(rows)
    if not n:
        return {"n": 0}
    out: dict[str, float | int] = {"n": n}
    for label, field in (("swcrockett", "p_sw"), ("v1", "p_v1")):
        brier = 0.0
        logloss = 0.0
        for row in rows:
            p = min(1.0 - EPSILON, max(EPSILON, float(row[field])))
            y = int(row["outcome"])
            brier += (p - y) ** 2
            logloss += log_loss(p, y)
        out[f"{label}_brier"] = brier / n
        out[f"{label}_log_loss"] = logloss / n
    return out


def log_loss(probability: float, outcome: int) -> float:
    p = min(1.0 - EPSILON, max(EPSILON, probability))
    return -(outcome * math.log(p) + (1 - outcome) * math.log1p(-p))


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * q
    lo = math.floor(index)
    hi = math.ceil(index)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)


def bootstrap_differences(rows: list[dict[str, object]]) -> dict[str, object]:
    blocks: dict[tuple[int, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        blocks[row["block"]].append(row)
    keys = sorted(blocks)
    if not keys:
        return {
            "method": "week-block bootstrap, blocks weighted by graded games",
            "block_definition": "(season, Monday-of-week UTC)",
            "reps": BOOTSTRAP_REPS,
            "seed": SEED,
            "blocks": 0,
            "brier_diff_sw_minus_v1_ci95": None,
            "log_loss_diff_sw_minus_v1_ci95": None,
        }

    rng = random.Random(SEED)
    brier_reps: list[float] = []
    logloss_reps: list[float] = []
    for _ in range(BOOTSTRAP_REPS):
        selected = [rng.choice(keys) for _ in keys]
        sample = [row for key in selected for row in blocks[key]]
        n = len(sample)
        brier_reps.append(sum(float(r["brier_diff"]) for r in sample) / n)
        logloss_reps.append(sum(float(r["log_loss_diff"]) for r in sample) / n)
    return {
        "method": "week-block bootstrap, blocks resampled uniformly and observations weighted by graded games",
        "block_definition": "(season, Monday-of-week UTC)",
        "reps": BOOTSTRAP_REPS,
        "seed": SEED,
        "blocks": len(keys),
        "games_per_block": {f"{season}:{monday}": len(blocks[(season, monday)]) for season, monday in keys},
        "brier_diff_sw_minus_v1_ci95": [percentile(brier_reps, 0.025), percentile(brier_reps, 0.975)],
        "log_loss_diff_sw_minus_v1_ci95": [percentile(logloss_reps, 0.025), percentile(logloss_reps, 0.975)],
    }


def compare(capture: dict[str, object], db_path: Path) -> dict[str, object]:
    if db_path.name != "picks.dev.db":
        raise CompareError("refusing a database whose basename is not picks.dev.db")
    if not db_path.is_file():
        raise CompareError(f"dev database not found: {db_path}")
    con = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA query_only=ON")
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"nfl_schedule", "game_projections"} <= tables:
            raise CompareError("dev database lacks nfl_schedule or game_projections")

        games = capture.get("games")
        if not isinstance(games, list):
            raise CompareError("capture has no games list")
        counts: dict[str, int] = defaultdict(int)
        paired: list[dict[str, object]] = []
        exclusions: list[dict[str, str]] = []

        for game in games:
            if not isinstance(game, dict):
                raise CompareError("capture contains a malformed game row")
            counts["source_rows"] += 1
            game_id = str(game.get("game_id", ""))
            season = int(game["season"])
            week = int(game["week"])
            kickoff = parse_utc(str(game["kickoff_utc"]))
            fetched_at = parse_utc(str(game["fetched_at"]))
            is_post_kickoff = fetched_at >= kickoff
            if bool(game.get("post_kickoff")) != is_post_kickoff:
                raise CompareError(f"{game_id}: post_kickoff flag conflicts with fetched_at and kickoff_utc")
            try:
                home, away = normalize("nfl", str(game["home_team"])), normalize("nfl", str(game["away_team"]))
            except ValueError as exc:
                counts["unmapped_team"] += 1
                exclusions.append({"game_id": game_id, "reason": f"unmapped_team: {exc}"})
                continue

            schedule = con.execute(
                "SELECT game_type,week,gameday,gametime,away_team,home_team,away_score,home_score "
                "FROM nfl_schedule WHERE game_id=? AND season=?",
                (game_id, season),
            ).fetchall()
            if len(schedule) != 1:
                counts["missing_schedule"] += 1
                exclusions.append({"game_id": game_id, "reason": "missing_or_duplicate_schedule_row"})
                continue
            sched = schedule[0]
            try:
                sched_away = normalize("nfl", str(sched["away_team"]))
                sched_home = normalize("nfl", str(sched["home_team"]))
            except ValueError as exc:
                counts["unmapped_team"] += 1
                exclusions.append({"game_id": game_id, "reason": f"unmapped_schedule_team: {exc}"})
                continue
            if (
                int(sched["week"]) != week
                or sched["game_type"] != "REG"
                or sched_home != home
                or sched_away != away
            ):
                counts["team_or_week_mismatch"] += 1
                exclusions.append({"game_id": game_id, "reason": "team_or_week_mismatch"})
                continue
            db_kickoff = parse_utc(kickoff_utc(sched["gameday"], sched["gametime"]))
            if db_kickoff != kickoff:
                counts["kickoff_mismatch"] += 1
                exclusions.append({"game_id": game_id, "reason": "kickoff_mismatch"})
                continue

            if bool(game.get("post_kickoff")):
                counts["post_kickoff"] += 1
                exclusions.append({"game_id": game_id, "reason": "post_kickoff"})
                continue

            projection_rows = con.execute(
                "SELECT p_home_win FROM game_projections "
                "WHERE league='nfl' AND game_id=? AND season=? AND week=? AND locked=1 "
                "AND model_version LIKE 'nfl-v1 %' AND locked_at IS NOT NULL",
                (game_id, season, week),
            ).fetchall()
            eligible_projection_rows = []
            for candidate in projection_rows:
                try:
                    locked_at = parse_utc(str(candidate["locked_at"]))
                except (TypeError, ValueError, CompareError):
                    continue
                if locked_at <= kickoff:
                    eligible_projection_rows.append((locked_at, candidate))
            projection = max(eligible_projection_rows, key=lambda item: item[0])[1] if eligible_projection_rows else None
            if projection is None or projection["p_home_win"] is None:
                counts["missing_pre_kickoff_v1"] += 1
                exclusions.append({"game_id": game_id, "reason": "missing_pre_kickoff_v1_lock"})

            home_score, away_score = sched["home_score"], sched["away_score"]
            if home_score is None or away_score is None:
                counts["missing_score"] += 1
                exclusions.append({"game_id": game_id, "reason": "missing_score"})
                continue
            if int(home_score) == int(away_score):
                counts["tie"] += 1
                exclusions.append({"game_id": game_id, "reason": "tie"})
                continue
            if projection is None or projection["p_home_win"] is None:
                continue

            p_sw = float(game["p_home_win"])
            p_v1 = float(projection["p_home_win"])
            if not 0.0 <= p_v1 <= 1.0 or not 0.0 < p_sw < 1.0:
                counts["invalid_probability"] += 1
                exclusions.append({"game_id": game_id, "reason": "invalid_probability"})
                continue
            outcome = int(int(home_score) > int(away_score))
            sw_logloss = log_loss(p_sw, outcome)
            v1_logloss = log_loss(p_v1, outcome)
            paired.append({
                "game_id": game_id,
                "block": monday_block(season, kickoff),
                "outcome": outcome,
                "p_sw": p_sw,
                "p_v1": p_v1,
                "brier_diff": (p_sw - outcome) ** 2 - (p_v1 - outcome) ** 2,
                "log_loss_diff": sw_logloss - v1_logloss,
            })
        counts["matched_graded_games"] = len(paired)
        return {
            "season": capture.get("season"),
            "week": capture.get("week"),
            "source_url": capture.get("prediction_fetch", {}).get("url"),
            "raw_payload_sha256": capture.get("prediction_fetch", {}).get("sha256_raw_payload"),
            "population_counts": dict(sorted(counts.items())),
            "scores": score_rows(paired),
            "paired_per_game_differences": [
                {key: row[key] for key in ("game_id", "block", "brier_diff", "log_loss_diff")}
                for row in paired
            ],
            "bootstrap": bootstrap_differences(paired),
            "exclusions": exclusions,
            "difference_direction": "swcrockett minus incumbent v1; negative favors swcrockett",
            "market_note": "No source quotes/prices; no market score is inferred from this file.",
        }
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)
    try:
        capture = json.loads(args.capture.read_text(encoding="utf-8"))
        result = compare(capture, args.db)
    except (OSError, json.JSONDecodeError, CompareError) as exc:
        print(f"FAIL CLOSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
