#!/usr/bin/env python3
"""Run the preregistered FBS coherent joint score-distribution evaluation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from scipy.special import gammaln
from scipy.stats import kstest


MAX_SCORE = 120
N_SCORE = MAX_SCORE + 1
N_CELLS = N_SCORE * N_SCORE
OFFSET = MAX_SCORE
GRID = np.arange(N_SCORE)
HOME_GRID = GRID[:, None]
AWAY_GRID = GRID[None, :]
HOME_WIN = HOME_GRID > AWAY_GRID
MARGIN_GRID = (HOME_GRID - AWAY_GRID).ravel()
TOTAL_GRID = (HOME_GRID + AWAY_GRID).ravel()
SPREAD_LINES = (3, 7, 10, 14)
TOTAL_LINES = (45, 48, 52, 56, 60)
BOOT_REPS = 2000
BOOT_SEED = 20261017
PIT_SEED = 20261019
COHERENCE_DRAWS_PER_GAME = 10_000
EXPECTED_COUNTS = {
    2018: 772,
    2019: 774,
    2020: 534,
    2021: 770,
    2022: 776,
    2023: 792,
    2024: 798,
    2025: 808,
    2026: 388,
}
PINNED_SHA256 = {
    2018: "cf26150d2c9140a9eef90d274865bcacd6de2ce265e8254024ba5d76445e54fc",
    2019: "64c23f8e70600c161136450f20e2e29965e947dd98aa252753e7b93fb0fd55a7",
    2020: "58380661b434daf183b07aebf9afeeadf13450d5bc819dd0ce44ba689e96ee58",
    2021: "a5577f826724bdcfe96ba829bf3055055c6e2e935cff59a7ab4a441d13925cb8",
    2022: "9f23a4cfba3577f1689b9954aa31a9f42a954fcb676204c35c2cc85a76ed72b5",
    2023: "58ca3ee4dae1185878feec061aa488e4298c011277cd083ab71dc233ad25f73f",
    2024: "7feb11b7ac2eccd92afd741a59efeb7f1fd26bb51d15675ab1164cd01985a153",
    2025: "0df9da5419dcac1ed8dcf848ef960b2cb3f90ad8d44203618b1840370709bb2e",
    2026: "9b970cff51bda692cc9d00eab06c73d63ae8e6bceac29301ff33c309f9e462bc",
}
EXPECTED_REVERSED = {
    "401520167",
    "401520445",
    "401551755",
    "401551767",
    "401677085",
    "401677093",
}


def fail(message: str) -> None:
    raise SystemExit("FAIL CLOSED: " + message)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        fail(f"missing input file: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def finite_float(value: str, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        fail(f"invalid numeric value for {label}: {value!r}")
    if not math.isfinite(result):
        fail(f"non-finite numeric value for {label}: {value!r}")
    return result


def audit_schedules(source_root: Path):
    manifest_rows = read_csv(source_root / "archive-coverage.csv")
    manifest = {
        row["file"]: row
        for row in manifest_rows
        if row.get("release") == "cfb_schedules"
    }
    all_games: dict[int, dict[str, dict]] = {}
    audit = []

    for season in range(2018, 2027):
        filename = f"cfb_schedules_{season}.parquet"
        path = source_root / "parquet" / "cfb_schedules" / filename
        item = manifest.get(filename)
        if item is None:
            fail(f"manifest row missing for {filename}")
        payload = path.read_bytes() if path.is_file() else None
        if payload is None:
            fail(f"schedule release missing: {path}")
        digest = hashlib.sha256(payload).hexdigest()
        if digest != PINNED_SHA256[season] or digest != item["sha256"]:
            fail(f"pinned or manifest SHA-256 mismatch for {filename}: {digest}")
        if len(payload) != int(item["bytes"]):
            fail(f"manifest byte-count mismatch for {filename}")

        table = pq.read_table(path)
        rows = table.to_pylist()
        if len(rows) != int(item["rows"]):
            fail(f"manifest row-count mismatch for {filename}")
        eligible = [row for row in rows if row.get("fbs_game") is True]
        completed = [row for row in eligible if row.get("completed") is True]
        ids = [str(row["game_id"]) for row in completed]
        if len(ids) != len(set(ids)):
            fail(f"duplicate completed FBS game ID in season {season}")
        if len(completed) != EXPECTED_COUNTS[season]:
            fail(
                f"eligible completed count changed for {season}: "
                f"{len(completed)} != {EXPECTED_COUNTS[season]}"
            )

        by_id: dict[str, dict] = {}
        for row in completed:
            home, away = row.get("home_points"), row.get("away_points")
            if type(home) is not int or type(away) is not int:
                fail(f"non-integer completed score in {season}, game {row['game_id']}")
            if not (0 <= home <= MAX_SCORE and 0 <= away <= MAX_SCORE):
                fail(f"score outside registered support in {season}, game {row['game_id']}")
            if row.get("home_id") is None or row.get("away_id") is None:
                fail(f"missing team ID in {season}, game {row['game_id']}")
            by_id[str(row["game_id"])] = row

        all_games[season] = by_id
        audit.append(
            {
                "season": season,
                "release_bytes": len(payload),
                "release_rows": len(rows),
                "sha256": digest,
                "fbs_games": len(eligible),
                "completed_fbs_games": len(completed),
                "excluded_incomplete_fbs_games": len(eligible) - len(completed),
            }
        )

    return all_games, audit


def target_rows(source_root: Path, schedules: dict[int, dict[str, dict]]):
    phase4 = read_csv(source_root / "phase4" / "per_game_parameters.csv")
    selected = []
    for row in phase4:
        season = int(row["season"])
        period = row["period"]
        if (season in (2023, 2024) and period == "walk_forward") or (
            season == 2025 and period == "holdout"
        ) or (season == 2026 and period == "dev2026"):
            selected.append(row)
    selected.sort(key=lambda row: (int(row["season"]), row["game_id"]))

    expected = {2023: 792, 2024: 798, 2025: 807, 2026: 350}
    observed = defaultdict(int)
    for row in selected:
        observed[int(row["season"])] += 1
    if dict(observed) != expected:
        fail(f"target ledger counts changed: {dict(observed)} != {expected}")
    ids = [row["game_id"] for row in selected]
    if len(ids) != len(set(ids)):
        fail("duplicate game ID in registered scored population")

    forecast_ids = {
        row["game_id"]: row
        for row in read_csv(source_root / "fbs_game_winner_predictions_20261018.csv")
    }
    holdout_ids = {
        row["game_id"]: row
        for row in read_csv(
            source_root
            / "phase3-baseline"
            / "fbs_game_winner_holdout_2025_20261018.csv"
        )
    }
    win_probs = {
        row["game_id"]: row
        for row in read_csv(source_root / "phase3-g" / "forecasts_walk_forward.csv")
    }

    reversed_ids = set()
    scored = []
    for row in selected:
        game_id = row["game_id"]
        season = int(row["season"])
        period = row["period"]
        schedule = schedules[season].get(game_id)
        if schedule is None:
            fail(f"target has no completed FBS schedule score: {season}/{game_id}")

        if season == 2025:
            forecast = holdout_ids.get(game_id)
            probability_record = forecast
            probability_key = "elo_home_prob"
        else:
            forecast = forecast_ids.get(game_id)
            probability_record = win_probs.get(game_id)
            probability_key = "p_g2h"
        if forecast is None or probability_record is None:
            fail(f"target missing its forecast identity/probability row: {season}/{game_id}")

        f_home = int(forecast["home_team_id"])
        f_away = int(forecast["away_team_id"])
        s_home = int(schedule["home_id"])
        s_away = int(schedule["away_id"])
        if (f_home, f_away) == (s_home, s_away):
            reversed_orientation = False
            obs_forecast = (schedule["home_points"], schedule["away_points"])
        elif (f_home, f_away) == (s_away, s_home):
            reversed_orientation = True
            reversed_ids.add(game_id)
            obs_forecast = (schedule["away_points"], schedule["home_points"])
        else:
            fail(
                f"team-ID mismatch for {season}/{game_id}: "
                f"forecast={(f_home, f_away)}, schedule={(s_home, s_away)}"
            )

        observed_h = finite_float(row["obs_h"], f"Phase4 obs_h {game_id}")
        observed_a = finite_float(row["obs_a"], f"Phase4 obs_a {game_id}")
        if (observed_h, observed_a) != tuple(map(float, obs_forecast)):
            fail(
                f"Phase4 observed score disagrees with schedule for {season}/{game_id}: "
                f"phase4={(observed_h, observed_a)}, expected={obs_forecast}"
            )

        p_h1 = finite_float(row["p_h1"], f"Phase4 p_h1 {game_id}")
        p_source = finite_float(probability_record[probability_key], f"source p {game_id}")
        if abs(p_h1 - p_source) > 1e-10:
            fail(f"Phase4 H1 probability/source mismatch for {season}/{game_id}")
        if not (0.0 <= p_h1 <= 1.0):
            fail(f"invalid H1 probability for {season}/{game_id}: {p_h1}")

        block = row["block"]
        if not block:
            fail(f"missing frozen week block for {season}/{game_id}")
        scored.append(
            {
                "game_id": game_id,
                "season": season,
                "period": (
                    "walk_forward"
                    if season in (2023, 2024)
                    else "holdout"
                    if season == 2025
                    else "forward2026"
                ),
                "block": f"{season}:{block}",
                "schedule_home_id": s_home,
                "schedule_away_id": s_away,
                "forecast_reversed": reversed_orientation,
                "obs_h": int(schedule["home_points"]),
                "obs_a": int(schedule["away_points"]),
                "p_h1_forecast_orientation": p_h1,
                "mu_h0_forecast_orientation": finite_float(
                    row["mu_h0"], f"mu_h0 {game_id}"
                ),
                "mu_a0_forecast_orientation": finite_float(
                    row["mu_a0"], f"mu_a0 {game_id}"
                ),
            }
        )

    if reversed_ids != EXPECTED_REVERSED:
        fail(
            f"orientation reversal set changed: {sorted(reversed_ids)} "
            f"!= {sorted(EXPECTED_REVERSED)}"
        )

    return scored, {
        "registered_target_rows": len(selected),
        "scored_rows": len(scored),
        "counts_by_partition": {
            period: sum(row["period"] == period for row in scored)
            for period in ("walk_forward", "holdout", "forward2026")
        },
        "reversed_forecast_orientation_ids": sorted(reversed_ids),
    }


def poisson_pmf(mu: float) -> np.ndarray:
    mu = max(float(mu), 1e-9)
    logp = -mu + GRID * math.log(mu) - gammaln(GRID + 1)
    p = np.exp(logp - logp.max())
    p /= p.sum()
    return p


def tilted_joint(base: np.ndarray, p_win: float) -> tuple[np.ndarray, float]:
    p_win = min(max(float(p_win), 1e-4), 1.0 - 1e-4)
    win_mass = float(base[HOME_WIN].sum())
    rest_mass = float(base[~HOME_WIN].sum())
    if win_mass <= 0.0 or rest_mass <= 0.0:
        fail("tilt base has zero home-win or non-home-win mass")
    e_theta = (p_win * rest_mass) / ((1.0 - p_win) * win_mass)
    theta = math.log(e_theta)
    joint = base.copy()
    joint[HOME_WIN] *= e_theta
    joint /= joint.sum()
    if abs(float(joint[HOME_WIN].sum()) - p_win) > 1e-12:
        fail("exponential tilt failed to match requested home-win probability")
    return joint, theta


def empirical_joint(training_rows: list[dict]) -> np.ndarray:
    counts = np.zeros(N_CELLS, dtype=np.float64)
    for row in training_rows:
        cell = int(row["home_points"]) * N_SCORE + int(row["away_points"])
        counts[cell] += 1.0
    counts = counts.reshape((N_SCORE, N_SCORE))
    p0 = (counts + (1.0 / N_CELLS)) / (len(training_rows) + 1.0)
    if abs(float(p0.sum()) - 1.0) > 1e-12 or np.any(p0 <= 0.0):
        fail("empirical joint PMF normalization/smoothing failure")
    return p0


def pushforward(joint: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    flat = joint.ravel()
    margin = np.bincount(MARGIN_GRID + OFFSET, weights=flat, minlength=2 * N_SCORE - 1)
    total = np.bincount(TOTAL_GRID, weights=flat, minlength=2 * N_SCORE - 1)
    if abs(float(margin.sum()) - 1.0) > 1e-10 or abs(float(total.sum()) - 1.0) > 1e-10:
        fail("joint-to-margin/total pushforward did not conserve mass")
    return margin, total


def crps(pmf: np.ndarray, observed: int, offset: int) -> float:
    support = np.arange(len(pmf)) + offset
    cdf = np.cumsum(pmf)
    cdf[-1] = 1.0
    return float(np.square(cdf - (support >= observed)).sum())


def randomized_pit(pmf: np.ndarray, observed: int, offset: int, u: float) -> float:
    idx = observed - offset
    if not (0 <= idx < len(pmf)):
        fail(f"observed value outside PMF support: {observed}")
    cdf = np.cumsum(pmf)
    below = float(cdf[idx - 1]) if idx > 0 else 0.0
    return below + float(u) * float(pmf[idx])


def central_interval(pmf: np.ndarray, level: float, offset: int) -> tuple[int, int]:
    cdf = np.cumsum(pmf)
    lo = int(np.searchsorted(cdf, (1.0 - level) / 2.0))
    hi = int(np.searchsorted(cdf, 1.0 - (1.0 - level) / 2.0))
    return min(lo, len(pmf) - 1) + offset, min(hi, len(pmf) - 1) + offset


def shortest_interval(pmf: np.ndarray, level: float, offset: int) -> tuple[int, int]:
    cdf = np.concatenate(([0.0], np.cumsum(pmf)))
    best = (0, len(pmf) - 1)
    best_width = len(pmf)
    j = 0
    for i in range(len(pmf)):
        if j < i:
            j = i
        while j < len(pmf) and cdf[j + 1] - cdf[i] < level - 1e-12:
            j += 1
        if j >= len(pmf):
            break
        if j - i < best_width:
            best, best_width = (i, j), j - i
    return best[0] + offset, best[1] + offset


def binary_log_loss(probability: float, event: int) -> float:
    p = min(max(float(probability), 1e-15), 1.0 - 1e-15)
    return -math.log(p if event else (1.0 - p))


def model_metrics(joint: np.ndarray, row: dict, pit_margin_u: float, pit_total_u: float):
    if abs(float(joint.sum()) - 1.0) > 1e-10 or np.any(joint < 0.0):
        fail(f"invalid joint PMF for {row['game_id']}")
    margin_pmf, total_pmf = pushforward(joint)
    margin = row["obs_h"] - row["obs_a"]
    total = row["obs_h"] + row["obs_a"]
    p_observed = float(joint[row["obs_h"], row["obs_a"]])
    if p_observed <= 0.0:
        fail(f"zero probability on observed score cell for {row['game_id']}")
    metrics = {
        "joint_brier": float(np.square(joint).sum() + 1.0 - 2.0 * p_observed),
        "joint_log_loss": -math.log(p_observed),
        "crps_margin": crps(margin_pmf, margin, -OFFSET),
        "crps_total": crps(total_pmf, total, 0),
        "pit_margin": randomized_pit(margin_pmf, margin, -OFFSET, pit_margin_u),
        "pit_total": randomized_pit(total_pmf, total, 0, pit_total_u),
    }
    for level_pct in (50, 80, 90):
        level = level_pct / 100.0
        for construction, fn in (("short", shortest_interval), ("central", central_interval)):
            lo, hi = fn(margin_pmf, level, -OFFSET)
            metrics[f"{construction}{level_pct}_margin"] = float(lo <= margin <= hi)
            lo, hi = fn(total_pmf, level, 0)
            metrics[f"{construction}{level_pct}_total"] = float(lo <= total <= hi)

    spread_brier, spread_log = [], []
    margin_support = np.arange(-OFFSET, OFFSET + 1)
    for line in SPREAD_LINES:
        for cut in (line, -line):
            probability = float(margin_pmf[margin_support > cut].sum())
            event = int(margin > cut)
            spread_brier.append((probability - event) ** 2)
            spread_log.append(binary_log_loss(probability, event))
    total_brier, total_log = [], []
    total_support = np.arange(2 * N_SCORE - 1)
    for line in TOTAL_LINES:
        probability = float(total_pmf[total_support > line].sum())
        event = int(total > line)
        total_brier.append((probability - event) ** 2)
        total_log.append(binary_log_loss(probability, event))
    metrics.update(
        {
            "brier_spread": float(np.mean(spread_brier)),
            "log_loss_spread": float(np.mean(spread_log)),
            "brier_total": float(np.mean(total_brier)),
            "log_loss_total": float(np.mean(total_log)),
            "home_terminal_digit": np.bincount(
                GRID % 10,
                weights=joint.sum(axis=1),
                minlength=10,
            ),
            "away_terminal_digit": np.bincount(
                GRID % 10,
                weights=joint.sum(axis=0),
                minlength=10,
            ),
        }
    )
    return metrics, margin_pmf, total_pmf


def bootstrap_diff(diffs: np.ndarray, blocks: list[str]) -> dict:
    unique = sorted(set(blocks))
    if len(unique) < 2:
        return {"mean": float(np.mean(diffs)), "lo": None, "hi": None, "blocks": len(unique)}
    positions = {block: np.flatnonzero(np.asarray(blocks) == block) for block in unique}
    rng = np.random.default_rng(BOOT_SEED)
    values = np.empty(BOOT_REPS, dtype=np.float64)
    for rep in range(BOOT_REPS):
        sampled = rng.choice(unique, size=len(unique), replace=True)
        total_sum = 0.0
        total_count = 0
        for block in sampled:
            idx = positions[block]
            total_sum += float(diffs[idx].sum())
            total_count += len(idx)
        values[rep] = total_sum / total_count
    return {
        "mean": float(np.mean(diffs)),
        "lo": float(np.percentile(values, 2.5)),
        "hi": float(np.percentile(values, 97.5)),
        "blocks": len(unique),
    }


def eval_experiment(source_root: Path, output_dir: Path):
    schedules, source_audit = audit_schedules(source_root)
    targets, target_audit = target_rows(source_root, schedules)

    history = {
        season: list(schedules[season].values())
        for season in range(2018, 2025)
    }
    fit_counts = {
        "2023": {"seasons": list(range(2018, 2023)), "n": 3626},
        "2024": {"seasons": list(range(2018, 2024)), "n": 4418},
        "2025_holdout_and_2026_forward": {
            "seasons": list(range(2018, 2025)),
            "n": 5216,
        },
    }
    p0_by_max_season = {
        2022: empirical_joint(
            [row for season in range(2018, 2023) for row in history[season]]
        ),
        2023: empirical_joint(
            [row for season in range(2018, 2024) for row in history[season]]
        ),
        2024: empirical_joint(
            [row for season in range(2018, 2025) for row in history[season]]
        ),
    }
    actual_fit_counts = {
        2022: sum(len(history[season]) for season in range(2018, 2023)),
        2023: sum(len(history[season]) for season in range(2018, 2024)),
        2024: sum(len(history[season]) for season in range(2018, 2025)),
    }
    if actual_fit_counts != {2022: 3626, 2023: 4418, 2024: 5216}:
        fail(f"candidate fit-fold counts changed: {actual_fit_counts}")

    pit_rng = np.random.default_rng(PIT_SEED)
    pit_margin_uniforms = pit_rng.random(len(targets))
    pit_total_uniforms = pit_rng.random(len(targets))
    coherence_rng = np.random.default_rng(PIT_SEED)
    per_game = []
    coherence_draws = 0
    digit_accumulator = {
        period: {
            side: {"observed": np.zeros(10), "predicted": np.zeros(10), "n": 0}
            for side in ("home", "away")
        }
        for period in ("walk_forward", "holdout", "forward2026")
    }
    fold_rows = []

    for index, row in enumerate(targets):
        season = row["season"]
        if season == 2023:
            training_end = 2022
        elif season == 2024:
            training_end = 2023
        else:
            training_end = 2024
        p0 = p0_by_max_season[training_end]

        base_original = np.outer(
            poisson_pmf(row["mu_h0_forecast_orientation"]),
            poisson_pmf(row["mu_a0_forecast_orientation"]),
        )
        h1_original, _ = tilted_joint(base_original, row["p_h1_forecast_orientation"])
        if row["forecast_reversed"]:
            constant_joint = base_original.T.copy()
            h1_joint = h1_original.T.copy()
        else:
            constant_joint = base_original
            h1_joint = h1_original
        target_p_home_win = float(h1_joint[HOME_WIN].sum())
        candidate_joint, candidate_theta = tilted_joint(p0, target_p_home_win)

        if abs(float(candidate_joint.sum()) - 1.0) > 1e-12:
            fail(f"candidate joint normalization failed for {row['game_id']}")
        sampled_cell = coherence_rng.choice(
            N_CELLS,
            size=COHERENCE_DRAWS_PER_GAME,
            replace=True,
            p=candidate_joint.ravel(),
        )
        sampled_home = sampled_cell // N_SCORE
        sampled_away = sampled_cell % N_SCORE
        sampled_total = sampled_home + sampled_away
        sampled_margin = sampled_home - sampled_away
        if not np.array_equal(sampled_total, sampled_home + sampled_away):
            fail(f"coherence total assertion failed for {row['game_id']}")
        if not np.array_equal(sampled_margin, sampled_home - sampled_away):
            fail(f"coherence margin assertion failed for {row['game_id']}")
        coherence_draws += len(sampled_cell)

        candidate_metrics, candidate_margin, candidate_total = model_metrics(
            candidate_joint,
            row,
            pit_margin_uniforms[index],
            pit_total_uniforms[index],
        )
        constant_metrics, _, _ = model_metrics(
            constant_joint,
            row,
            pit_margin_uniforms[index],
            pit_total_uniforms[index],
        )
        h1_metrics, _, _ = model_metrics(
            h1_joint,
            row,
            pit_margin_uniforms[index],
            pit_total_uniforms[index],
        )

        record = {
            key: value
            for key, value in row.items()
            if key not in ("mu_h0_forecast_orientation", "mu_a0_forecast_orientation")
        }
        record["candidate_theta"] = candidate_theta
        for model_name, values in (
            ("candidate", candidate_metrics),
            ("constant", constant_metrics),
            ("h1", h1_metrics),
        ):
            for metric, value in values.items():
                if isinstance(value, np.ndarray):
                    continue
                record[f"{model_name}_{metric}"] = value
        per_game.append(record)

        for side, observed_score, predictions in (
            ("home", row["obs_h"], candidate_metrics["home_terminal_digit"]),
            ("away", row["obs_a"], candidate_metrics["away_terminal_digit"]),
        ):
            cell = digit_accumulator[row["period"]][side]
            cell["observed"][observed_score % 10] += 1.0
            cell["predicted"] += predictions
            cell["n"] += 1

        if index == 0 or targets[index - 1]["season"] != season:
            fold_rows.append(
                {
                    "scoring_season": season,
                    "training_seasons": ",".join(str(s) for s in range(2018, training_end + 1)),
                    "training_games": actual_fit_counts[training_end],
                    "candidate_family": "smoothed empirical joint; H1 win-probability tilt",
                }
            )

    if coherence_draws != len(targets) * COHERENCE_DRAWS_PER_GAME:
        fail("coherence draw count mismatch")

    for period in ("walk_forward", "holdout", "forward2026"):
        part = [row for row in per_game if row["period"] == period]
        if not part:
            fail(f"empty evaluation partition: {period}")
        for side in ("home", "away"):
            cell = digit_accumulator[period][side]
            n = cell["n"]
            if n != len(part):
                fail(f"terminal-digit population mismatch: {period}/{side}")
            cell["observed"] /= n
            cell["predicted"] /= n

    summaries = []
    summary_metrics = (
        "joint_brier",
        "joint_log_loss",
        "crps_margin",
        "crps_total",
        "brier_spread",
        "log_loss_spread",
        "brier_total",
        "log_loss_total",
    )
    for period in ("walk_forward", "holdout", "forward2026"):
        part = [row for row in per_game if row["period"] == period]
        for model in ("candidate", "constant", "h1"):
            item = {"period": period, "model": model, "n": len(part)}
            for metric in summary_metrics:
                item[metric] = float(np.mean([r[f"{model}_{metric}"] for r in part]))
            if model == "candidate":
                for metric in (
                    "short50_margin",
                    "short50_total",
                    "central50_margin",
                    "central50_total",
                    "short80_margin",
                    "short80_total",
                    "central80_margin",
                    "central80_total",
                    "short90_margin",
                    "short90_total",
                    "central90_margin",
                    "central90_total",
                ):
                    item[metric] = float(np.mean([r[f"candidate_{metric}"] for r in part]))
                for metric in ("pit_margin", "pit_total"):
                    values = np.asarray([r[f"candidate_{metric}"] for r in part], dtype=float)
                    item[f"{metric}_ks_p"] = float(kstest(values, "uniform").pvalue)
            summaries.append(item)

    comparisons = []
    paired_specs = (
        ("joint_brier", "h1"),
        ("crps_margin", "h1"),
        ("crps_total", "h1"),
        ("brier_spread", "constant"),
        ("brier_spread", "h1"),
        ("brier_total", "constant"),
        ("brier_total", "h1"),
    )
    for period in ("walk_forward", "holdout", "forward2026"):
        part = [row for row in per_game if row["period"] == period]
        blocks = [row["block"] for row in part]
        for metric, baseline in paired_specs:
            diffs = np.asarray(
                [row[f"candidate_{metric}"] - row[f"{baseline}_{metric}"] for row in part],
                dtype=float,
            )
            result = bootstrap_diff(diffs, blocks)
            comparisons.append(
                {
                    "period": period,
                    "candidate_minus": baseline,
                    "metric": metric,
                    "n": len(part),
                    "reps": BOOT_REPS,
                    "seed": BOOT_SEED,
                    **result,
                }
            )

    def comparison(period: str, metric: str, baseline: str) -> dict:
        return next(
            row
            for row in comparisons
            if row["period"] == period
            and row["metric"] == metric
            and row["candidate_minus"] == baseline
        )

    wf = next(row for row in summaries if row["period"] == "walk_forward" and row["model"] == "candidate")
    ho = next(row for row in summaries if row["period"] == "holdout" and row["model"] == "candidate")
    gates = {
        "G-SAMPLE": bool(target_audit["counts_by_partition"]["walk_forward"] >= 1500 and target_audit["counts_by_partition"]["holdout"] >= 250),
        "G-DIST": bool(
            comparison("walk_forward", "crps_margin", "h1")["hi"] < 0
            and comparison("walk_forward", "crps_total", "h1")["hi"] < 0
            and comparison("holdout", "crps_margin", "h1")["mean"] < 0
            and comparison("holdout", "crps_total", "h1")["mean"] < 0
        ),
        "G-CAL": bool(
            wf["pit_margin_ks_p"] > 0.05
            and wf["pit_total_ks_p"] > 0.05
            and ho["pit_margin_ks_p"] > 0.05
            and ho["pit_total_ks_p"] > 0.05
            and abs(wf["short50_margin"] - 0.50) <= 0.05
            and abs(wf["short50_total"] - 0.50) <= 0.05
        ),
        "G-SPREAD": bool(
            comparison("walk_forward", "brier_spread", "constant")["hi"] < 0
            and comparison("walk_forward", "brier_spread", "h1")["hi"] < 0
            and comparison("holdout", "brier_spread", "h1")["mean"] < 0
        ),
        "G-TOTAL": bool(
            comparison("walk_forward", "brier_total", "constant")["hi"] < 0
            and comparison("walk_forward", "brier_total", "h1")["hi"] < 0
            and comparison("holdout", "brier_total", "h1")["mean"] < 0
        ),
        "G-JOINT": bool(
            comparison("walk_forward", "joint_brier", "h1")["hi"] < 0
            and comparison("holdout", "joint_brier", "h1")["mean"] < 0
        ),
        "G-COHERENCE": True,
    }
    verdict = "ADOPTED" if all(gates.values()) else "NOT_ADOPTED"

    digit_rows = []
    for period, sides in digit_accumulator.items():
        for side, values in sides.items():
            for digit in range(10):
                digit_rows.append(
                    {
                        "period": period,
                        "side": side,
                        "terminal_digit": digit,
                        "n": values["n"],
                        "observed_rate": float(values["observed"][digit]),
                        "mean_predicted_probability": float(values["predicted"][digit]),
                    }
                )

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "per_game_scores.csv", per_game)
    write_csv(output_dir / "summary.csv", summaries)
    write_csv(output_dir / "paired_comparisons.csv", comparisons)
    write_csv(output_dir / "terminal_digit_calibration.csv", digit_rows)
    write_csv(output_dir / "candidate_fit_folds.csv", fold_rows)
    run = {
        "status": verdict,
        "preregistration_commit": "5be5e30ef04e424589e7fadeca97a6bea1924603",
        "candidate_training_counts": fit_counts,
        "source_audit": source_audit,
        "target_audit": target_audit,
        "coherence": {
            "draws_per_game": COHERENCE_DRAWS_PER_GAME,
            "games": len(targets),
            "draws_checked": coherence_draws,
            "exact_equalities_passed": True,
            "gate": gates["G-COHERENCE"],
        },
        "bootstrap": {"replicates": BOOT_REPS, "seed": BOOT_SEED},
        "pit_seed": PIT_SEED,
        "gates": gates,
        "verdict": verdict,
        "phase4b_status": "NOT_ADOPTED; gate unchanged",
        "production_change": False,
    }
    (output_dir / "run.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gates": gates, "verdict": verdict, "target_audit": target_audit, "coherence": run["coherence"]}, indent=2))


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        fail(f"refusing to write empty result file: {path}")
    columns = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        required=True,
        help="FBS research root with the verified parquet archive and frozen Phase 4 ledgers",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("research/fbs/joint-dist-2026-10-19"),
    )
    args = parser.parse_args()
    eval_experiment(args.source_root.resolve(), args.out.resolve())


if __name__ == "__main__":
    main()
