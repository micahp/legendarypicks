#!/usr/bin/env python3
"""Read-only 2025 holdout scorer for SLC opponent-adjusted capability research.

Example (on fast host with pinned nflverse files):
python3 scripts/nfl_sequence/evaluate_matchup_capability.py \
  --source-dir /root/lp-snapshots/nfl-backfill-2026-10-27/raw/pbp \
  --output /tmp/slc-capability-2025.json

Fit: 2022-2024 REG only. Test: 2025 REG only, never in fit. No future
feature, current-season refit, simulator execution, or DB mutation.
This is a conditional event/yardage-category gate, not game-winner grading.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import e0_single_play as e0
from matchup_capability import CapabilityModel, Play, MODEL_ID

TRAIN_SEASONS = (2022, 2023, 2024)
TEST_SEASON = 2025
REGULAR = "REG"
MODES = ("league", "offense", "defense", "matchup")
OUTCOMES = {
    "pass": ("sack", "sack_fumble_lost", "interception", "fumble_lost",
             "incomplete", "complete_short", "complete_chain",
             "complete_explosive_short", "complete_explosive_chain"),
    "run": ("fumble_lost", "loss", "zero", "short", "chain",
            "explosive_short", "explosive_chain"),
}
REQUIRED = (
    "game_id", "play_id", "season", "season_type", "week", "qtr",
    "posteam", "defteam", "down", "ydstogo", "yardline_100",
    "play_type", "yards_gained", "sack", "interception", "fumble_lost",
    "complete_pass", "qb_scramble", "penalty", "two_point_attempt", "epa",
)
BINARY = {
    "pass": {
        "sack": ("sack", "sack_fumble_lost"),
        "interception": ("interception",),
        "fumble_lost": ("fumble_lost", "sack_fumble_lost"),
        "turnover": ("interception", "fumble_lost", "sack_fumble_lost"),
        "chain_advance": ("complete_chain", "complete_explosive_chain"),
        "explosive_20_plus": ("complete_explosive_short", "complete_explosive_chain"),
    },
    "run": {
        "fumble_lost": ("fumble_lost",),
        "chain_advance": ("chain", "explosive_chain"),
        "explosive_10_plus": ("explosive_short", "explosive_chain"),
        "negative_run": ("loss",),
    },
}
BOOTSTRAP_REPS = 2000


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _equal(value, expected):
    return value is not None and value == expected


def classify_row(row):
    """Return (intent, Play) or None; never coerce unknown penalties to clean.

    Fumble on a sack is retained as a distinct mutually exclusive category,
    avoiding the common mistake of losing either a sack or a turnover.
    Run-yard buckets preserve line-to-gain and explosive distinctions.
    """
    if (row.get("season_type") != REGULAR or row.get("week") is None
            or not (1 <= int(row["week"]) <= 18)
            or row.get("qtr") is None or not (1 <= int(row["qtr"]) <= 4)
            or row.get("penalty") != 0
            or row.get("two_point_attempt") != 0
            or row.get("qb_scramble") != 0
            or row.get("play_type") not in OUTCOMES
            or not row.get("posteam") or not row.get("defteam")
            or row["posteam"] == row["defteam"]):
        return None
    if any(row.get(key) is None for key in (
            "game_id", "play_id", "season", "down", "ydstogo", "yardline_100", "yards_gained")):
        return None
    down, togo, spot = int(row["down"]), float(row["ydstogo"]), float(row["yardline_100"])
    if not (1 <= down <= 4 and 0 < togo <= 99 and 1 <= spot <= 99):
        return None
    intent = row["play_type"]
    gained = float(row["yards_gained"])
    if not math.isfinite(gained):
        return None
    chain = gained >= togo
    if intent == "pass":
        if _equal(row.get("sack"), 1):
            outcome = "sack_fumble_lost" if _equal(row.get("fumble_lost"), 1) else "sack"
        elif _equal(row.get("interception"), 1):
            outcome = "interception"
        elif _equal(row.get("fumble_lost"), 1):
            outcome = "fumble_lost"
        elif _equal(row.get("complete_pass"), 0):
            outcome = "incomplete"
        elif _equal(row.get("complete_pass"), 1):
            if gained >= 20:
                outcome = "complete_explosive_chain" if chain else "complete_explosive_short"
            else:
                outcome = "complete_chain" if chain else "complete_short"
        else:
            return None
    else:
        if _equal(row.get("fumble_lost"), 1):
            outcome = "fumble_lost"
        elif gained < 0:
            outcome = "loss"
        elif gained == 0:
            outcome = "zero"
        elif gained >= 10:
            outcome = "explosive_chain" if chain else "explosive_short"
        else:
            outcome = "chain" if chain else "short"
    situation = e0.pool_key(down, togo, spot)
    context = f"{intent}|" + "|".join(str(part) for part in situation)
    play = Play(season=int(row["season"]), game_id=str(row["game_id"]),
                play_id=int(row["play_id"]), offense=row["posteam"],
                defense=row["defteam"], context=context, outcome=outcome)
    return intent, play


def load_source(path, expected_season):
    """Read only the required columns, validate the source season, preserve exclusions."""
    import pyarrow.parquet as pq

    src = Path(path)
    if not src.is_file():
        raise FileNotFoundError(f"pinned PBP source missing: {src}")
    parquet = pq.ParquetFile(src)
    absent = set(REQUIRED) - set(parquet.schema.names)
    if absent:
        raise ValueError(f"source lacks required columns (fail closed): {sorted(absent)}")
    observations = {"pass": [], "run": []}
    epa_rows = []
    excluded = Counter()
    seen = set()
    for batch in parquet.iter_batches(batch_size=65536, columns=list(REQUIRED)):
        for row in batch.to_pylist():
            if int(row["season"]) != expected_season:
                raise ValueError(f"{src}: unexpected source season {row['season']}")
            result = classify_row(row)
            if result is None:
                excluded["not_clean_eligible_scrimmage"] += 1
                continue
            intent, play = result
            key = (play.game_id, play.play_id)
            if key in seen:
                raise ValueError(f"{src}: duplicate play key {key}")
            seen.add(key)
            observations[intent].append(play)
            epa = row.get("epa")
            if epa is not None and math.isfinite(float(epa)):
                epa_rows.append((play.offense, play.defense, float(epa)))
    return observations, epa_rows, {"path": str(src), "sha256": sha256(src),
                                     "excluded_rows": dict(sorted(excluded.items())),
                                     "included_pass": len(observations["pass"]),
                                     "included_run": len(observations["run"])}


def team_strength_bins(training_epa):
    """Training-only offensive EPA and defensive EPA allowed; never test-season ranks."""
    off_sum, off_n, def_sum, def_n = (Counter() for _ in range(4))
    for offense, defense, epa in training_epa:
        off_sum[offense] += epa
        off_n[offense] += 1
        def_sum[defense] += epa
        def_n[defense] += 1

    def rank(sums, nums, high_is_strong):
        values = {team: sums[team] / n for team, n in nums.items() if n >= 100}
        teams = sorted(values, key=lambda t: (values[t], t))
        # Fixed bottom/top quartiles, not tuned to 2025.
        q = max(1, len(teams) // 4) if teams else 0
        labels = {}
        for i, team in enumerate(teams):
            if high_is_strong:
                labels[team] = "weak" if i < q else "strong" if i >= len(teams) - q else "middle"
            else:
                labels[team] = "strong" if i < q else "weak" if i >= len(teams) - q else "middle"
        return labels

    return rank(off_sum, off_n, True), rank(def_sum, def_n, False)


def score(probs, actual):
    p = max(1e-12, probs[actual])
    return (-math.log(p),
            sum((value - (1.0 if label == actual else 0.0)) ** 2
                for label, value in probs.items()))


def binary_score(records):
    """Binary metrics over the identical set of observed contexts."""
    if not records:
        return {"n": 0}
    n = len(records)
    rate = sum(y for y, p in records) / n
    predicted = sum(p for y, p in records) / n
    return {"n": n, "observed_rate": rate, "predicted_rate": predicted,
            "brier": sum((y - p)**2 for y, p in records) / n,
            "log_loss": sum(-math.log(max(1e-12, p if y else 1-p)) for y, p in records) / n}


def paired_game_interval(by_game, *, reps=BOOTSTRAP_REPS, seed=20261111):
    """Play-weighted log-loss delta with games, not plays, resampled."""
    games = sorted(by_game)
    if len(games) < 2:
        return None
    rng = random.Random(seed)
    estimates = []
    for _ in range(reps):
        draw = [games[rng.randrange(len(games))] for _ in games]
        loss = sum(by_game[g][0] for g in draw)
        size = sum(by_game[g][1] for g in draw)
        estimates.append(loss / size)
    estimates.sort()
    return [estimates[int(0.025 * (reps - 1))],
            estimates[int(0.975 * (reps - 1))]]


def evaluate(train, test, train_epa):
    off_bins, def_bins = team_strength_bins(train_epa)
    report = {}
    for intent in OUTCOMES:
        training, holdout = train[intent], test[intent]
        if not training or not holdout:
            raise ValueError(f"insufficient train/holdout data for {intent}")
        model = CapabilityModel.fit(training, OUTCOMES[intent], target_season=TEST_SEASON)
        accum = {mode: [0.0, 0.0, 0] for mode in MODES}
        binary = {target: {mode: [] for mode in MODES} for target in BINARY[intent]}
        groups = defaultdict(lambda: {mode: [0.0, 0.0, 0] for mode in MODES})
        team_groups = defaultdict(lambda: {mode: [0.0, 0.0, 0] for mode in MODES})
        per_game = defaultdict(lambda: [0.0, 0])
        fallback = Counter()
        for play in holdout:
            fallback["unsupported_context"] += int(play.context not in model.base)
            fallback["unknown_offense"] += int(play.offense not in model.offense)
            fallback["unknown_defense"] += int(play.defense not in model.defense)
            bin_key = off_bins.get(play.offense, "unknown") + "x" + def_bins.get(play.defense, "unknown")
            outcomes = {}
            for mode in MODES:
                probs = model.predict(play.context, play.offense, play.defense, mode=mode)
                outcomes[mode] = probs
                loss, brier = score(probs, play.outcome)
                for total in (accum[mode], groups[bin_key][mode],
                              team_groups[f"offense:{play.offense}"][mode],
                              team_groups[f"defense:{play.defense}"][mode]):
                    total[0] += loss
                    total[1] += brier
                    total[2] += 1
            league_loss = score(outcomes["league"], play.outcome)[0]
            matchup_loss = score(outcomes["matchup"], play.outcome)[0]
            per_game[play.game_id][0] += matchup_loss - league_loss
            per_game[play.game_id][1] += 1
            for target, members in BINARY[intent].items():
                y = int(play.outcome in members)
                for mode in MODES:
                    binary[target][mode].append((y, sum(outcomes[mode][m] for m in members)))

        def fmt(values):
            loss, brier, n = values
            return {"n": n, "log_loss": loss / n if n else None,
                    "multiclass_brier": brier / n if n else None}

        report[intent] = {
            "training": model.manifest,
            "heldout_games": len({p.game_id for p in holdout}),
            "heldout_plays": len(holdout),
            "scoring": {mode: fmt(accum[mode]) for mode in MODES},
            "matchup_minus_league_log_loss": (fmt(accum["matchup"])["log_loss"]
                                                 - fmt(accum["league"])["log_loss"]),
            "matchup_minus_league_ci95": paired_game_interval(per_game),
            "binary_targets": {name: {mode: binary_score(rows) for mode, rows in scores.items()}
                               for name, scores in binary.items()},
            "strength_3x3": {group: {mode: fmt(rows) for mode, rows in arms.items()}
                             for group, arms in sorted(groups.items())},
            "per_team": {name: {mode: fmt(rows) for mode, rows in arms.items()}
                         for name, arms in sorted(team_groups.items())},
            "fallback_counts": dict(sorted(fallback.items())),
            "offense_capability_logit": {team: dict(zip(model.outcomes, values))
                                        for team, values in model.offense.items()},
            "defense_capability_logit": {team: dict(zip(model.outcomes, values))
                                        for team, values in model.defense.items()},
        }
    return report, {"offense": off_bins, "defense": def_bins}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; frozen evidence must not be overwritten")

    all_train = {"pass": [], "run": []}
    all_epa = []
    sources = {}
    for season in (*TRAIN_SEASONS, TEST_SEASON):
        data, epa, info = load_source(args.source_dir / f"play_by_play_{season}.parquet", season)
        sources[str(season)] = info
        if season in TRAIN_SEASONS:
            for intent in OUTCOMES:
                all_train[intent].extend(data[intent])
            all_epa.extend(epa)
        else:
            test = data
    outcomes, strength_bins = evaluate(all_train, test, all_epa)
    result = {
        "status": "UNVALIDATED_RESEARCH_CANDIDATE",
        "evaluation_status": "2025 retrospective chronological test; development-exposed, not pristine",
        "model": MODEL_ID,
        "split": {"fit_seasons": list(TRAIN_SEASONS), "holdout_season": TEST_SEASON,
                  "rules": "REG weeks 1-18, Q1-Q4, source penalty=0 only, no target-season data in fit"},
        "source_files": sources,
        "code_hashes": {
            "matchup_capability.py": sha256(HERE / "matchup_capability.py"),
            "evaluate_matchup_capability.py": sha256(__file__),
        },
        "strength_bins_training_only": strength_bins,
        "conditional_mechanisms": outcomes,
        "interpretation": [
            "Offline observed pre-play situations, not generated game states or winner predictions.",
            "The league context baseline, offense-only, defense-only and joint model are scored on identical observed plays.",
            "Team effects are opponent-adjusted, per outcome and per intent, with L2 regularization.",
            "The 2025 season is never used for fit, hyperparameter selection or strength stratification.",
            "The model currently does not represent penalties, formation/coverage, pass/run decisions, red-zone TD execution or play-clock.",
            "An event-label audit and matched game simulations are prerequisites for adoption.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps({"output": str(args.output), "pass": outcomes["pass"]["scoring"],
                      "run": outcomes["run"]["scoring"]}, sort_keys=True))


if __name__ == "__main__":
    main()
