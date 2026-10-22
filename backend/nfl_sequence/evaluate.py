"""Held-out evaluation of nfl-seq v0.1 against historical seasons and simple baselines. Offline.

Reports separately, never blended into one score:
- scoring: game-level points and winner accuracy from seeded trials, with coverage and calibration of
  the game-level win probability;
- event validity: every trial's script is checked by validate_script, and the reducer's exceptions
  are counted; plausibility compares simulated play mix and rates with the held-out seasons;
- calibration: play-level call and pass-class probabilities on the held-out plays;
- reconstruction: one-step replay of the recorded plays through the reducer (historical, not
  prediction);
- unsupported mechanics: what the engine does not model, with its measured size in the data.

Baselines: league-average constant (training means), the coarse-state transition model, and the
unconditional frequency model. All three share the reducer, the clock and the playbook seam, so only
the decision layer differs.

Usage (from backend/, with pyarrow available):
  python -m nfl_sequence.evaluate --source-dir <dir> --model-dir <dir> --test-seasons 2022-2023 \
      [--trials 100] [--schedule-db <sqlite>] --out <json>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import time
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .model import StatModel
from .nflverse import game_finals, iter_observations, read_season
from .reconstruct import replay
from .simulate import MODEL_VERSION, Simulator, derive_seed, script
from .train import parse_seasons

VARIANT_NAMES = ("main", "state_transition", "frequency")
CALL_TYPES = ("run", "pass", "punt", "field_goal", "kneel", "spike")
ECE_BINS = 10


def snapshot_hash(game_id: str, season: int, home: str, away: str) -> str:
    """Pregame identity only. It contains nothing that depends on the game's result."""
    return hashlib.sha256(("pregame|%s|%d|%s|%s|%s" % (game_id, season, home, away, MODEL_VERSION)).encode("utf-8")).hexdigest()[:16]


def _scrimmage_call(row: Dict[str, Any]) -> Optional[str]:
    if row["play_type"] is None or row["penalty"] == 1 or row["two_point_attempt"] == 1:
        return None
    if row["play_deleted"] == 1 or row["aborted_play"] == 1 or row["posteam"] is None:
        return None
    if row["down"] is None:
        return None
    if row["play_type"] == "run":
        return "pass" if row["qb_scramble"] == 1 else "run"
    return {"pass": "pass", "punt": "punt", "field_goal": "field_goal", "qb_kneel": "kneel", "qb_spike": "spike"}.get(row["play_type"])


def actual_game_table(rows: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Per-game actuals from the held-out rows: finals plus the same play-mix measures the sims report."""
    finals = game_finals(rows)
    games: Dict[str, Dict[str, Any]] = {}
    for game_id, final in finals.items():
        games[game_id] = dict(final, calls=Counter(), turnovers=0, sacks=0, drives=set(), penalties=0, two_point=0, overtime=False)
    for row in rows:
        game = games.get(row["game_id"])
        if game is None:
            continue
        call = _scrimmage_call(row)
        if call is not None:
            game["calls"][call] += 1
            if row["interception"] == 1 or row["fumble_lost"] == 1:
                game["turnovers"] += 1
            if row["sack"] == 1:
                game["sacks"] += 1
        if row["posteam"] is not None and row["drive"] is not None:
            game["drives"].add(int(row["drive"]))
        if row["penalty"] == 1:
            game["penalties"] += 1
        if row["two_point_attempt"] == 1:
            game["two_point"] += 1
        if int(row["qtr"] or 0) == 5:
            game["overtime"] = True
    for game in games.values():
        game["plays"] = sum(game["calls"].values())
        game["drives"] = len(game["drives"])
    return games


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    index = max(0, min(len(sorted_values) - 1, math.ceil(q * len(sorted_values)) - 1))
    return sorted_values[index]


def _log_loss(p: float) -> float:
    return -math.log(min(max(p, 1e-6), 1 - 1e-6))


def score_metrics(games: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Game-level scoring from per-game records. Each record has actual and simulated fields."""
    n = len(games)
    out: Dict[str, Any] = {"games": n}
    if n == 0:
        return out
    out["mae_home"] = sum(abs(g["sim_home"] - g["home"]) for g in games) / n
    out["mae_away"] = sum(abs(g["sim_away"] - g["away"]) for g in games) / n
    out["mae_total"] = sum(abs(g["sim_total"] - (g["home"] + g["away"])) for g in games) / n
    out["mae_margin"] = sum(abs(g["sim_margin"] - (g["home"] - g["away"])) for g in games) / n
    out["bias_total"] = sum(g["sim_total"] - (g["home"] + g["away"]) for g in games) / n
    out["rmse_total"] = math.sqrt(sum((g["sim_total"] - (g["home"] + g["away"])) ** 2 for g in games) / n)
    covered_total = [g for g in games if g.get("p10_total") is not None]
    if covered_total:
        out["coverage80_total"] = sum(1 for g in covered_total if g["p10_total"] <= g["home"] + g["away"] <= g["p90_total"]) / len(covered_total)
        out["coverage80_margin"] = sum(1 for g in covered_total if g["p10_margin"] <= g["home"] - g["away"] <= g["p90_margin"]) / len(covered_total)
    decisive = [g for g in games if g["home"] != g["away"]]
    out["ties"] = n - len(decisive)
    if decisive:
        correct = 0
        brier = 0.0
        loss = 0.0
        for g in decisive:
            p = g["p_home_decisive"]
            won = 1.0 if g["home"] > g["away"] else 0.0
            correct += int((p > 0.5) == bool(won))
            brier += (p - won) ** 2
            loss += _log_loss(p if won else 1 - p)
        out["winner_accuracy"] = correct / len(decisive)
        out["brier_home_win"] = brier / len(decisive)
        out["log_loss_home_win"] = loss / len(decisive)
        out["reliability"] = _reliability([(g["p_home_decisive"], 1.0 if g["home"] > g["away"] else 0.0) for g in decisive])
    return out


def _reliability(pairs: Sequence[Tuple[float, float]], bins: int = 5) -> List[Dict[str, Any]]:
    table = []
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        members = [(p, y) for p, y in pairs if (low <= p < high) or (index == bins - 1 and p == 1.0)]
        if not members:
            table.append({"range": [low, high], "n": 0, "predicted": None, "observed": None})
            continue
        table.append(
            {
                "range": [round(low, 2), round(high, 2)],
                "n": len(members),
                "predicted": sum(p for p, _ in members) / len(members),
                "observed": sum(y for _, y in members) / len(members),
            }
        )
    return table


def _ece(pairs: Sequence[Tuple[float, bool]]) -> Dict[str, Any]:
    """Expected calibration error over the top-probability of each prediction."""
    bins: List[List[Tuple[float, bool]]] = [[] for _ in range(ECE_BINS)]
    for confidence, correct in pairs:
        index = min(ECE_BINS - 1, int(confidence * ECE_BINS))
        bins[index].append((confidence, correct))
    total = len(pairs)
    ece = 0.0
    for members in bins:
        if members:
            conf = sum(c for c, _ in members) / len(members)
            acc = sum(1 for _, ok in members if ok) / len(members)
            ece += len(members) / total * abs(conf - acc)
    return {"ece": ece, "n": total}


def play_calibration(model: StatModel, observations: Sequence[Tuple[str, Dict[str, str], str]]) -> Dict[str, Any]:
    """Log loss, top-1 accuracy and ECE for calls and pass classes on held-out plays."""
    call_loss, call_hits, call_conf = 0.0, 0, []
    pass_loss, pass_hits, pass_conf, pass_n = 0.0, 0, [], 0
    call_n = 0
    for name, ctx, value in observations:
        if name == "call":
            dist = model["call"].probabilities(ctx)
            call_loss += _log_loss(dist.get(value, 0.0))
            top = max(dist, key=dist.get)
            call_hits += top == value
            call_conf.append((dist[top], top == value))
            call_n += 1
        elif name == "pass_class":
            dist = model["pass_class"].probabilities(ctx)
            pass_loss += _log_loss(dist.get(value, 0.0))
            top = max(dist, key=dist.get)
            pass_hits += top == value
            pass_conf.append((dist[top], top == value))
            pass_n += 1
    return {
        "call": {"n": call_n, "log_loss": call_loss / call_n, "accuracy": call_hits / call_n, **_ece(call_conf)},
        "pass_class": {"n": pass_n, "log_loss": pass_loss / pass_n, "accuracy": pass_hits / pass_n, **_ece(pass_conf)},
    }


def simulate_games(model: StatModel, games: Dict[str, Dict[str, Any]], trials: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Run every trial for every game. Returns one record per game plus aggregate validity counters."""
    records: List[Dict[str, Any]] = []
    validity = Counter()
    play_totals = Counter()
    plays_per_game: List[float] = []
    drives_per_game: List[float] = []
    turnovers_per_game: List[float] = []
    sacks_per_game: List[float] = []
    points_per_game: List[float] = []
    for game_id in sorted(games):
        game = games[game_id]
        sim = Simulator(
            model,
            game_id=game_id,
            home_team=game["home_team"],
            away_team=game["away_team"],
            season=game["season"],
            snapshot_hash=snapshot_hash(game_id, game["season"], game["home_team"], game["away_team"]),
        )
        homes, aways, p_home_hits = [], [], 0
        game_plays, game_drives, game_turnovers, game_sacks = [], [], [], []
        for trial in range(trials):
            seed = derive_seed(sim.game_key, sim.snapshot_hash, MODEL_VERSION, trial)
            try:
                doc = script(sim.start(seed).advance())
            except Exception as error:  # counted and reported; a game with no completed trial raises below
                validity["run_exception:%s" % type(error).__name__] += 1
                continue
            validity["trials"] += 1
            validity["valid_full_game" if doc["valid_full_game"] else "invalid_full_game"] += 1
            validity["validation_problems"] += len(doc["validation_problems"])
            summary = doc["summary"]
            homes.append(doc["final_score"]["home"])
            aways.append(doc["final_score"]["away"])
            p_home_hits += doc["final_score"]["home"] > doc["final_score"]["away"]
            game_plays.append(sum(summary["calls"].values()))  # scrimmage calls, matching the actual side
            game_drives.append(summary["drives"])
            game_turnovers.append(summary["interceptions"] + summary["fumbles_lost"])
            game_sacks.append(summary["sacks"])
            points_per_game.append(doc["final_score"]["home"] + doc["final_score"]["away"])
            for call, count in summary["calls"].items():
                play_totals[call] += count
        if not homes:
            raise RuntimeError("no trial completed for game %s" % game_id)
        totals = sorted(h + a for h, a in zip(homes, aways))
        margins = sorted(h - a for h, a in zip(homes, aways))
        decisive_home = sum(1 for h, a in zip(homes, aways) if h > a)
        decisive_away = sum(1 for h, a in zip(homes, aways) if a > h)
        records.append(
            {
                "game_id": game_id,
                "home": game["home"],
                "away": game["away"],
                "sim_home": sum(homes) / len(homes),
                "sim_away": sum(aways) / len(aways),
                "sim_total": sum(totals) / len(totals),
                "sim_margin": sum(margins) / len(margins),
                "p10_total": _quantile(totals, 0.1),
                "p90_total": _quantile(totals, 0.9),
                "p10_margin": _quantile(margins, 0.1),
                "p90_margin": _quantile(margins, 0.9),
                # Laplace-smoothed so a finite trial count never reports certainty.
                "p_home_decisive": (decisive_home + 1) / (decisive_home + decisive_away + 2),
                "p_home": p_home_hits / len(homes),
            }
        )
        plays_per_game.append(sum(game_plays) / len(game_plays))
        drives_per_game.append(sum(game_drives) / len(game_drives))
        turnovers_per_game.append(sum(game_turnovers) / len(game_turnovers))
        sacks_per_game.append(sum(game_sacks) / len(game_sacks))
    n = max(1, validity["trials"])
    aggregate = {
        "trials": validity["trials"],
        "valid_full_game_rate": validity["valid_full_game"] / n,
        "validation_problems": validity["validation_problems"],
        "run_exceptions": {k.split(":", 1)[1]: v for k, v in validity.items() if k.startswith("run_exception:")},
        "scrimmage_plays_per_game": sum(plays_per_game) / len(plays_per_game),
        "drives_per_game": sum(drives_per_game) / len(drives_per_game),
        "turnovers_per_game": sum(turnovers_per_game) / len(turnovers_per_game),
        "sacks_per_game": sum(sacks_per_game) / len(sacks_per_game),
        "points_per_game_total": sum(points_per_game) / len(points_per_game),
        "call_share": {call: play_totals[call] / max(1, sum(play_totals[c] for c in CALL_TYPES)) for call in CALL_TYPES},
    }
    return records, aggregate


def constant_records(games: Dict[str, Dict[str, Any]], finals: Dict[str, Any]) -> List[Dict[str, Any]]:
    """League-average baseline: training means for every game and training home-win share."""
    decisive = finals["home_wins"] + finals["away_wins"]
    p_home = finals["home_wins"] / decisive
    records = []
    for game_id in sorted(games):
        game = games[game_id]
        mean_home, mean_away = finals["home_mean"], finals["away_mean"]
        records.append(
            {
                "game_id": game_id,
                "home": game["home"],
                "away": game["away"],
                "sim_home": mean_home,
                "sim_away": mean_away,
                "sim_total": mean_home + mean_away,
                "sim_margin": mean_home - mean_away,
                "p_home_decisive": p_home,
                "p_home": p_home,
            }
        )
    return records


def reconcile_schedule(db_path: str, seasons: Sequence[int], games: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Compare finals derived from play-by-play with the published schedule table. Read-only."""
    con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    try:
        published = {}
        for game_id, home, away, season in con.execute(
            "SELECT game_id, home_score, away_score, season FROM nfl_schedule WHERE game_type = 'REG'"
        ):
            if season in seasons:
                published[game_id] = (home, away)
    finally:
        con.close()
    mismatched = [gid for gid, g in games.items() if gid in published and (g["home"], g["away"]) != tuple(int(x) for x in published[gid])]
    missing = [gid for gid in games if gid not in published]
    return {"games_checked": len(games), "published_games": len(published), "score_mismatches": len(mismatched), "missing_from_schedule": len(missing), "mismatch_examples": mismatched[:5]}


def unsupported_measured(games: Dict[str, Dict[str, Any]], observations: int, penalty_rows: int, two_point_rows: int) -> Dict[str, Any]:
    plays = sum(g["plays"] for g in games.values())
    overtime_games = sum(1 for g in games.values() if g["overtime"])
    return {
        "penalties": {"penalty_rows": penalty_rows, "share_of_scrimmage_rows": penalty_rows / max(1, plays + penalty_rows), "modelled": False},
        "two_point_attempts": {"rows": two_point_rows, "modelled": False, "approximation": "not generated; extra point only"},
        "overtime": {"games": overtime_games, "share_of_games": overtime_games / max(1, len(games)), "modelled": "approximation"},
        "timeouts": {"modelled": False, "approximation": "held at 3 for each side in the public state"},
        "participants": {"modelled": False, "approximation": "null; no roster input in v0.1"},
        "calibration_observations": observations,
    }


def run_evaluation(source_dir: str, model_dir: str, test_seasons: Sequence[int], trials: int, schedule_db: Optional[str]) -> Dict[str, Any]:
    started = time.time()
    with open(os.path.join(model_dir, "manifest.json")) as handle:
        train_manifest = json.load(handle)
    finals = train_manifest["finals"]
    models = {name: StatModel.load(os.path.join(model_dir, "nfl-seq-v0.1-%s.json" % name)) for name in VARIANT_NAMES}

    all_rows: List[Dict[str, Any]] = []
    reconstruction: Dict[str, Any] = {}
    skips: Counter = Counter()
    observations: List[Tuple[str, Dict[str, str], str]] = []
    penalty_rows = 0
    two_point_rows = 0
    for season in test_seasons:
        rows = read_season(os.path.join(source_dir, "play_by_play_%d.parquet" % season))
        all_rows.extend(rows)
        counts, examples = replay(rows)
        reconstruction[str(season)] = {"counts": dict(sorted(counts.items())), "examples": examples}
        observations.extend(iter_observations(rows, skips))
        penalty_rows += sum(1 for r in rows if r["penalty"] == 1)
        two_point_rows += sum(1 for r in rows if r["two_point_attempt"] == 1)

    games = actual_game_table(all_rows)
    actual = {
        "games": len(games),
        "scrimmage_plays_per_game": sum(g["plays"] for g in games.values()) / len(games),
        "drives_per_game": sum(g["drives"] for g in games.values()) / len(games),
        "turnovers_per_game": sum(g["turnovers"] for g in games.values()) / len(games),
        "sacks_per_game": sum(g["sacks"] for g in games.values()) / len(games),
        "points_per_game_total": sum(g["home"] + g["away"] for g in games.values()) / len(games),
        "call_share": {c: sum(g["calls"][c] for g in games.values()) / max(1, sum(sum(g["calls"].values()) for g in games.values())) for c in CALL_TYPES},
    }

    variants: Dict[str, Any] = {}
    for name in VARIANT_NAMES:
        records, aggregate = simulate_games(models[name], games, trials)
        variants[name] = {
            "scoring": score_metrics(records),
            "event_validity": aggregate,
            "calibration": play_calibration(models[name], observations),
        }
    variants["constant_league_average"] = {"scoring": score_metrics(constant_records(games, finals))}

    report = {
        "model_version": MODEL_VERSION,
        "test_seasons": list(test_seasons),
        "train_seasons": train_manifest["train_seasons"],
        "trials_per_game": trials,
        "actual": actual,
        "variants": variants,
        "reconstruction": reconstruction,
        "unsupported_mechanics": unsupported_measured(games, len(observations), penalty_rows, two_point_rows),
        "skips_test_rows": dict(sorted(skips.items())),
        "elapsed_seconds": round(time.time() - started, 1),
    }
    if schedule_db:
        report["schedule_reconciliation"] = reconcile_schedule(schedule_db, test_seasons, games)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--test-seasons", required=True)
    parser.add_argument("--trials", type=int, default=100)
    parser.add_argument("--schedule-db")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = run_evaluation(args.source_dir, args.model_dir, parse_seasons(args.test_seasons), args.trials, args.schedule_db)
    with open(args.out, "w") as handle:
        json.dump(report, handle, indent=2, sort_keys=True, default=str)
    print(json.dumps({"out": args.out, "elapsed_seconds": report["elapsed_seconds"]}, indent=2))


if __name__ == "__main__":
    main()
