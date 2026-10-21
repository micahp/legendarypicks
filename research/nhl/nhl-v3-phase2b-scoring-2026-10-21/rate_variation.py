#!/usr/bin/env python3
"""Measure the frozen NHL V3 team-rate bucket structure and tempo covariance.

Reproduction uses the committed Phase 2B traces plus hash-pinned 2021 PBP and
official team-SOG inputs. It does not fit or modify a candidate or rerun Monte
Carlo simulations.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PHASE1 = REPO / "research/nhl/nhl-v3-phase1-replay-2026-10-21"
PHASE2A = REPO / "research/nhl/nhl-v3-phase2a-stochastic-2026-10-21"
for _path in (PHASE1, PHASE2A):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import run_phase2a as phase2a  # noqa: E402
import stochastic_model as model  # noqa: E402
from replay_model import SHOT_EVENTS, parse_situation_code  # noqa: E402

TRACE_PATH = HERE / "underdispersion-traces.json.gz"
RESULTS_PATH = HERE / "RESULTS.json"
UNDERDISPERSION_PATH = HERE / "underdispersion.json"
MODEL_PATH = PHASE2A / "FITTED-MODEL.json"
OUTPUT_JSON = HERE / "rate_variation.json"
OUTPUT_MD = HERE / "RATE-VARIATION.md"
SOURCE_OFFICIAL = REPO / "research/nhl/official-outcome-backfill-2026-10-20"
BOOTSTRAP_SEED = 20261023
DEFAULT_BOOTSTRAP_REPLICATES = 2000
SIDES = ("home", "away")
ATTACK_LEVELS = ("LOW", "AVERAGE", "HIGH")
DEFENSE_LEVELS = ("STRONG", "AVERAGE", "WEAK")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def accepted_attempt(event, side: str | None) -> bool:
    return (event.event_type in SHOT_EVENTS and event.ordinary_shot_eligible is True and
            side in SIDES and event.quality.event == "ACCEPT" and
            event.quality.team_count == "ACCEPT")


def team_variance(values: np.ndarray, teams: np.ndarray) -> tuple[float, dict[int, float], dict[int, int]]:
    unique = np.unique(teams)
    means: dict[int, float] = {}
    counts: dict[int, int] = {}
    for team in unique:
        selected = values[teams == team]
        means[int(team)] = float(np.mean(selected))
        counts[int(team)] = int(len(selected))
    overall = float(np.mean(values))
    between = sum(counts[t] * (means[t] - overall) ** 2 for t in means) / len(values)
    return float(between), means, counts


def weighted_sse(y: np.ndarray, x: np.ndarray, weights: np.ndarray) -> float:
    keep = weights > 0
    y, x, weights = y[keep], x[keep], weights[keep]
    design = np.column_stack((np.ones(len(y)), x))
    root_w = np.sqrt(weights)
    beta, *_ = np.linalg.lstsq(design * root_w[:, None], y * root_w, rcond=None)
    residual = y - design @ beta
    return float(np.sum(weights * residual * residual))


def explain_between_team_variance(
        outcome: np.ndarray, team_indices: np.ndarray, attack: np.ndarray,
        defense: np.ndarray, is_home: np.ndarray, team_count: int) -> dict:
    """Shapley split of team-mean forecast variation by bucket mix and site share."""
    n = np.bincount(team_indices, minlength=team_count).astype(float)
    sums = np.bincount(team_indices, weights=outcome, minlength=team_count)
    means = np.divide(sums, n, out=np.zeros(team_count), where=n > 0)

    attack_low = np.bincount(team_indices, weights=(attack == "LOW"), minlength=team_count)
    attack_high = np.bincount(team_indices, weights=(attack == "HIGH"), minlength=team_count)
    defense_strong = np.bincount(team_indices, weights=(defense == "STRONG"), minlength=team_count)
    defense_weak = np.bincount(team_indices, weights=(defense == "WEAK"), minlength=team_count)
    home = np.bincount(team_indices, weights=is_home.astype(float), minlength=team_count)
    bucket_x = np.column_stack((attack_low, attack_high, defense_strong, defense_weak))
    bucket_x = np.divide(bucket_x, n[:, None], out=np.zeros_like(bucket_x), where=n[:, None] > 0)
    site_x = np.divide(home, n, out=np.zeros(team_count), where=n > 0)[:, None]
    full_x = np.column_stack((bucket_x, site_x))

    null_sse = weighted_sse(means, np.empty((team_count, 0)), n)
    bucket_sse = weighted_sse(means, bucket_x, n)
    site_sse = weighted_sse(means, site_x, n)
    full_sse = weighted_sse(means, full_x, n)
    total = float(np.sum(n))
    bucket_ss = 0.5 * ((null_sse - bucket_sse) + (site_sse - full_sse))
    site_ss = 0.5 * ((null_sse - site_sse) + (bucket_sse - full_sse))
    between = null_sse / total
    bucket_component = bucket_ss / total
    site_component = site_ss / total
    explained = (null_sse - full_sse) / total
    return {
        "between_team_variance": between,
        "bucket_membership_component": float(bucket_component),
        "home_away_assignment_component": float(site_component),
        "combined_explained_component": float(explained),
        "unallocated_component": float(max(0.0, between - explained)),
        "bucket_and_site_explained_fraction": float(explained / between) if between else 0.0,
    }


def covariance_stats(pairs: np.ndarray) -> dict[str, float]:
    flat = pairs.reshape(-1, 2)
    means = np.mean(flat, axis=0)
    variances = np.var(flat, axis=0)
    covariance = float(np.mean((flat[:, 0] - means[0]) * (flat[:, 1] - means[1])))
    correlation = covariance / math.sqrt(float(variances[0] * variances[1]))
    return {
        "mean_home": float(means[0]), "mean_away": float(means[1]),
        "variance_home": float(variances[0]), "variance_away": float(variances[1]),
        "covariance": covariance, "correlation": float(correlation),
    }


def tempo_covariance(pairs: np.ndarray, cv: float) -> dict[str, float]:
    """Exact moments after an independent mean-one common multiplier per game."""
    base = covariance_stats(pairs)
    c2 = cv * cv
    covariance = ((1.0 + c2) * base["covariance"] +
                  c2 * base["mean_home"] * base["mean_away"])
    variance_home = ((1.0 + c2) * base["variance_home"] + c2 * base["mean_home"] ** 2)
    variance_away = ((1.0 + c2) * base["variance_away"] + c2 * base["mean_away"] ** 2)
    return {
        "tempo_sd_cv": cv,
        "added_covariance": covariance - base["covariance"],
        "covariance_after_shared_tempo": float(covariance),
        "correlation_after_shared_tempo": float(
            covariance / math.sqrt(variance_home * variance_away)),
    }


def percentile(values: list[float]) -> list[float]:
    return [float(v) for v in np.quantile(np.asarray(values), [0.025, 0.975])]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-replicates", type=int, default=DEFAULT_BOOTSTRAP_REPLICATES)
    args = parser.parse_args()
    if args.bootstrap_replicates < 100:
        raise ValueError("BOOTSTRAP_REPLICATES_MUST_BE_AT_LEAST_100")
    started = time.monotonic()

    results = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    prior = json.loads(UNDERDISPERSION_PATH.read_text(encoding="utf-8"))
    with gzip.open(TRACE_PATH, "rt", encoding="utf-8") as handle:
        snapshot = json.load(handle)
    model_sha = sha256(MODEL_PATH)
    if results["frozen_phase2a_hashes"]["fitted_model_sha256"] != model_sha:
        raise ValueError("FROZEN_PHASE2A_MODEL_HASH_MISMATCH")
    if sha256(TRACE_PATH) != prior["input_snapshot"]["sha256"]:
        raise ValueError("UNDERDISPERSION_TRACE_HASH_MISMATCH")
    if snapshot["metadata"]["base_commit"] != prior["base_commit"]:
        raise ValueError("TRACE_PHASE2B_BASE_MISMATCH")
    if snapshot["metadata"]["phase2a_hashes"] != results["frozen_phase2a_hashes"]:
        raise ValueError("TRACE_PHASE2A_HASHES_MISMATCH")
    games = snapshot["games"]
    if len(games) != 1312 or len({row["game_id"] for row in games}) != 1312:
        raise ValueError("2021_TRACE_POPULATION_MISMATCH")

    command = results["command"]
    label_path = Path(command["labels"])
    bundle = phase2a.load_bundle(
        artifact_dir=Path(command["artifacts"]), official_dir=SOURCE_OFFICIAL,
        label_path=label_path)
    selected = {gid: definition for gid, definition in bundle.games.items()
                if definition.season == 2021}
    if len(selected) != 1312 or set(selected) != {row["game_id"] for row in games}:
        raise ValueError("2021_PINNED_SOURCE_POPULATION_MISMATCH")
    params = model.FittedParameters.from_json(json.loads(MODEL_PATH.read_text(encoding="utf-8")))
    snapshots = phase2a._team_history_snapshots(bundle)
    quality = {
        gid: phase2a._pregame_quality_groups(snapshots[gid], params.sog_reference)
        for gid in selected
    }

    trace_by_id = {row["game_id"]: row for row in games}
    team_ids = sorted({team_id for g in games for team_id in g["team_ids"].values()})
    if len(team_ids) != 32:
        raise ValueError(f"2021_TEAM_COUNT_MISMATCH {len(team_ids)}")
    team_index = {team_id: i for i, team_id in enumerate(team_ids)}
    team_game_rows = []
    key_counts: Counter[tuple[str, ...]] = Counter()
    attempt_counts: dict[str, Counter[str]] = defaultdict(Counter)
    source_event_rows_2021 = 0

    for gid, events in phase2a.iter_game_event_groups(bundle, game_ids=set(selected)):
        definition = selected[gid]
        source_event_rows_2021 += len(events)
        current_attempts = attempt_counts[gid]
        manpower = parse_situation_code("1551")
        period_key = None
        previous_elapsed = 0
        score = {"home": 0, "away": 0}
        for event in events:
            side = phase2a._event_side(definition, event)
            ordinary = event.period_type in {"REG", "OT"}
            accepted_ordinary = (ordinary and event.quality.event == "ACCEPT" and
                                 event.quality.period_number == "ACCEPT")
            if accepted_ordinary:
                this_period = (event.period_type, event.period_number)
                duration = phase2a._period_duration(event.period_type)
                if period_key != this_period:
                    period_key = this_period
                    previous_elapsed = 0
                    manpower = parse_situation_code("1551")
                elapsed = max(previous_elapsed, phase2a._event_elapsed(event, duration))
                parsed = parse_situation_code(event.situation_code)
                if parsed is not None:
                    manpower = parsed
                if accepted_attempt(event, side):
                    period = model.period_level(event.period_type, event.period_number)
                    strength = model.strength_level(manpower, side)
                    opponent = "away" if side == "home" else "home"
                    key = model.state_key(
                        snapshots[gid], params, side=side, period=period, strength=strength,
                        score_difference=score[side] - score[opponent],
                        remaining=duration - elapsed)
                    key_counts[key] += 1
                    current_attempts[side] += 1
                previous_elapsed = elapsed
            if phase2a._accepted_team_goal(event, side):
                score[side] += 1

        trace = trace_by_id[gid]
        for side_idx, side in enumerate(SIDES):
            if current_attempts[side] != trace["observed"]["attempts"][side]:
                raise ValueError(f"SOURCE_TRACE_ATTEMPT_COUNT_MISMATCH {gid}/{side}")
            team_id = int(trace["team_ids"][side])
            attack, defense = quality[gid][side]
            team_game_rows.append({
                "game_id": gid, "team_id": team_id, "team_index": team_index[team_id],
                "side": side, "is_home": side == "home", "attack": attack, "defense": defense,
                "observed_attempts": float(trace["observed"]["attempts"][side]),
                "predicted_attempts": float(np.mean(np.asarray(trace["phase2a"]["attempts"])[:, side_idx])),
                "observed_sog": float(trace["observed"]["official_sog"][side]),
                "predicted_sog": float(np.mean(np.asarray(trace["phase2a"]["sog"])[:, side_idx])),
                "sog_eligible": bool(trace["sog_eligible"]),
            })

    if set(attempt_counts) != set(selected):
        raise ValueError("PINNED_2021_EVENT_SCAN_COVERAGE_MISMATCH")
    expected_event_rows = snapshot["metadata"]["source_event_rows_verified"]
    if expected_event_rows != 1510104:
        raise ValueError("PINNED_FULL_SOURCE_EVENT_COUNT_MISMATCH")

    attack_by_team: dict[int, Counter[str]] = defaultdict(Counter)
    defense_totals: Counter[str] = Counter()
    for row in team_game_rows:
        attack_by_team[row["team_id"]][row["attack"]] += 1
        defense_totals[row["defense"]] += 1
    modal_attack = {}
    attack_team_counts = Counter()
    for team_id in team_ids:
        counts = attack_by_team[team_id]
        # Ties use the stable model category ordering.
        mode = max(ATTACK_LEVELS, key=lambda level: (counts[level], -ATTACK_LEVELS.index(level)))
        modal_attack[team_id] = mode
        attack_team_counts[mode] += 1

    outcome_results = {}
    bootstrap_rng = np.random.default_rng(BOOTSTRAP_SEED)
    for outcome, observed_key, predicted_key in (
            ("attempts", "observed_attempts", "predicted_attempts"),
            ("sog", "observed_sog", "predicted_sog")):
        eligible_rows = [r for r in team_game_rows if outcome == "attempts" or r["sog_eligible"]]
        y = np.asarray([r[observed_key] for r in eligible_rows], dtype=float)
        mu = np.asarray([r[predicted_key] for r in eligible_rows], dtype=float)
        teams = np.asarray([r["team_id"] for r in eligible_rows], dtype=int)
        indices = np.asarray([r["team_index"] for r in eligible_rows], dtype=int)
        attack = np.asarray([r["attack"] for r in eligible_rows], dtype=object)
        defense = np.asarray([r["defense"] for r in eligible_rows], dtype=object)
        home = np.asarray([r["is_home"] for r in eligible_rows], dtype=bool)
        observed_between, obs_means, obs_counts = team_variance(y, teams)
        predicted_between, pred_means, pred_counts = team_variance(mu, teams)
        verified = prior["variance_decomposition"][outcome]
        if abs(observed_between - verified["observed"]["between_team_variance"]) > 1e-8:
            raise ValueError(f"OBSERVED_TEAM_VARIANCE_REPRODUCTION_MISMATCH {outcome}")
        if abs(predicted_between - verified["predicted"]["between_team_mean_variance"]) > 1e-8:
            raise ValueError(f"PREDICTED_TEAM_VARIANCE_REPRODUCTION_MISMATCH {outcome}")
        pred_split = explain_between_team_variance(mu, indices, attack, defense, home, len(team_ids))
        obs_split = explain_between_team_variance(y, indices, attack, defense, home, len(team_ids))

        # Game-ID bootstrap; each sampled game contributes both teams together.
        selected_games = sorted({r["game_id"] for r in eligible_rows})
        rows_by_game = {gid: [r for r in eligible_rows if r["game_id"] == gid]
                        for gid in selected_games}
        bootstrap = defaultdict(list)
        n_games = len(selected_games)
        for _ in range(args.bootstrap_replicates):
            sampled_ids = bootstrap_rng.choice(selected_games, size=n_games, replace=True)
            sample_rows = [row for gid in sampled_ids for row in rows_by_game[str(gid)]]
            by_team_pred = np.asarray([r[predicted_key] for r in sample_rows], dtype=float)
            by_team_obs = np.asarray([r[observed_key] for r in sample_rows], dtype=float)
            team_idx = np.asarray([r["team_index"] for r in sample_rows], dtype=int)
            att = np.asarray([r["attack"] for r in sample_rows], dtype=object)
            defe = np.asarray([r["defense"] for r in sample_rows], dtype=object)
            site = np.asarray([r["is_home"] for r in sample_rows], dtype=bool)
            sim_between, _, _ = team_variance(by_team_pred, np.asarray([r["team_id"] for r in sample_rows]))
            obs_bt, _, _ = team_variance(by_team_obs, np.asarray([r["team_id"] for r in sample_rows]))
            sim_features = explain_between_team_variance(
                by_team_pred, team_idx, att, defe, site, len(team_ids))
            obs_features = explain_between_team_variance(
                by_team_obs, team_idx, att, defe, site, len(team_ids))
            bootstrap["predicted_between"].append(sim_between)
            bootstrap["observed_between"].append(obs_bt)
            bootstrap["between_gap"].append(obs_bt - sim_between)
            bootstrap["predicted_bucket"].append(sim_features["bucket_membership_component"])
            bootstrap["predicted_site"].append(sim_features["home_away_assignment_component"])
            bootstrap["observed_explained"].append(obs_features["combined_explained_component"])
            bootstrap["observed_unallocated"].append(obs_features["unallocated_component"])
        outcome_results[outcome] = {
            "team_games": len(eligible_rows), "games": n_games, "teams": len(set(teams)),
            "observed_between_team_variance": observed_between,
            "predicted_between_team_mean_variance": predicted_between,
            "observed_minus_predicted_between_team_variance": observed_between - predicted_between,
            "approx_missing_additive_log_scale_sd": math.sqrt(max(0.0, observed_between - predicted_between)) /
                float(np.mean(y)),
            "observed_feature_projection": obs_split,
            "predicted_feature_projection": pred_split,
            "cluster_bootstrap_95_ci": {
                key: percentile(values) for key, values in bootstrap.items()},
            "team_observed_means": {str(k): obs_means[k] for k in sorted(obs_means)},
            "team_predicted_means": {str(k): pred_means[k] for k in sorted(pred_means)},
            "team_game_counts": {str(k): obs_counts[k] for k in sorted(obs_counts)},
            "selection_status": "2021 development fold; descriptive-after-selection",
        }

    attempt_pairs_obs = np.asarray([[g["observed"]["attempts"][s] for s in SIDES] for g in games], dtype=float)
    attempt_pairs_sim = np.asarray([g["phase2a"]["attempts"] for g in games], dtype=float)
    sog_games = [g for g in games if g["sog_eligible"]]
    sog_pairs_obs = np.asarray([[g["observed"]["official_sog"][s] for s in SIDES]
                                for g in sog_games], dtype=float)
    sog_pairs_sim = np.asarray([g["phase2a"]["sog"] for g in sog_games], dtype=float)

    paired = {}
    for name, obs_pairs, sim_pairs, under_key in (
            ("attempts", attempt_pairs_obs, attempt_pairs_sim, "attempts"),
            ("sog", sog_pairs_obs, sog_pairs_sim, "sog")):
        observed = covariance_stats(obs_pairs)
        generated = covariance_stats(sim_pairs)
        prior_pair = prior["paired_home_away_count_covariance"][under_key]
        if (abs(observed["covariance"] - prior_pair["observed_covariance"]) > 1e-8 or
                abs(generated["covariance"] - prior_pair["generated_mixture_covariance"]) > 1e-8):
            raise ValueError(f"PAIRED_COVARIANCE_REPRODUCTION_MISMATCH {name}")
        rows_by_game = [sim_pairs[i] for i in range(len(sim_pairs))]
        boot_tempo = defaultdict(list)
        for _ in range(args.bootstrap_replicates):
            selected_indices = bootstrap_rng.integers(0, len(rows_by_game), size=len(rows_by_game))
            sampled_pairs = sim_pairs[selected_indices]
            for cv in (0.05, 0.10, 0.15):
                tempo = tempo_covariance(sampled_pairs, cv)
                boot_tempo[cv].append(tempo["covariance_after_shared_tempo"])
        paired[name] = {
            "games": len(obs_pairs), "observed": observed, "generated": generated,
            "cluster_bootstrap_95_ci": {
                "observed_covariance": prior_pair["cluster_bootstrap_95_ci"]["covariance"]["observed"],
                "generated_covariance": prior_pair["cluster_bootstrap_95_ci"]["covariance"]["generated"],
                "shared_tempo_covariance_by_sd": {
                    str(cv): percentile(boot_tempo[cv]) for cv in (0.05, 0.10, 0.15)},
            },
            "shared_positive_game_tempo": [
                tempo_covariance(sim_pairs, cv) for cv in (0.05, 0.10, 0.15)],
            "independence_formula": "Cov(T*H,T*A)=(1+sd^2)Cov(H,A)+sd^2*E[H]*E[A], E[T]=1, Var(T)=sd^2, T independent of the generated pair",
        }

    all_event_attempts = sum(attempt_counts[gid][side] for gid in attempt_counts for side in SIDES)
    attack_game_totals = {level: sum(c[level] for c in attack_by_team.values()) for level in ATTACK_LEVELS}
    defense_game_totals = {level: int(defense_totals[level]) for level in DEFENSE_LEVELS}
    cells_by_period = Counter(key[0] for key in key_counts)
    reachable_levels = {
        "period": sorted({key[0] for key in key_counts}),
        "strength": sorted({key[1] for key in key_counts}),
        "score_level": sorted({key[2] for key in key_counts}),
        "time_level": sorted({key[3] for key in key_counts}),
        "game_time_level": sorted({key[4] for key in key_counts}),
        "home_away": sorted({key[5] for key in key_counts}),
        "attack_bucket": sorted({key[6] for key in key_counts}),
        "defense_bucket": sorted({key[7] for key in key_counts}),
    }
    team_bucket_rows = {}
    for team_id in team_ids:
        counts = attack_by_team[team_id]
        team_bucket_rows[str(team_id)] = {
            "modal_attack_bucket": modal_attack[team_id],
            "team_games_by_attack_bucket": {level: int(counts[level]) for level in ATTACK_LEVELS},
        }

    attempt_gap = outcome_results["attempts"]["observed_minus_predicted_between_team_variance"]
    sog_gap = outcome_results["sog"]["observed_minus_predicted_between_team_variance"]
    payload = {
        "diagnostic_only": True,
        "candidate_selected": False,
        "gate_changed": False,
        "frozen_phase2a_modified": False,
        "population": {
            "season_split": "2021 development population only; 2022 was already exposed and is excluded",
            "games": len(games), "teams": len(team_ids), "sog_eligible_games": len(sog_games),
            "team_games_attempts": 2 * len(games), "team_games_sog": 2 * len(sog_games),
            "game_cluster_bootstrap_keeps_both_teams": True,
            "bootstrap_replicates": args.bootstrap_replicates,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "finite_monte_carlo_draws_held_fixed": True,
        },
        "provenance": {
            "branch_base_commit": "ad79a135e7488e0f9700cdc60066d0143148bec8",
            "phase2a_base_commit": "19bb60cf8997abe1368b732983a4ed2ac1904cd3",
            "phase2b_evaluation_base_commit": prior["base_commit"],
            "phase2b_results_sha256": sha256(RESULTS_PATH),
            "underdispersion_trace_path": TRACE_PATH.relative_to(REPO).as_posix(),
            "underdispersion_trace_sha256": sha256(TRACE_PATH),
            "phase2a_fitted_model_path": MODEL_PATH.relative_to(REPO).as_posix(),
            "phase2a_fitted_model_sha256": model_sha,
            "source_pins": results["source_pins"],
            "source_event_rows_verified_full_source": expected_event_rows,
            "source_event_rows_in_2021_games": source_event_rows_2021,
            "source_eligible_2021_attempt_events": all_event_attempts,
            "analysis_script_sha256": sha256(Path(__file__).resolve()),
            "reproduction_command": "/root/legendarypicks/backend/venv/bin/python research/nhl/nhl-v3-phase2b-scoring-2026-10-21/rate_variation.py --bootstrap-replicates 2000",
            "analysis_runtime_seconds": time.monotonic() - started,
        },
        "rate_path": {
            "quality_reference_sog_per_team_game": params.sog_reference,
            "attack_bucket_rules": {
                "LOW": "prior-10 attack SOG/game / reference <= 0.90",
                "AVERAGE": "0.90 < prior-10 attack SOG/game / reference < 1.10",
                "HIGH": "prior-10 attack SOG/game / reference >= 1.10",
                "no_prior_sample": "AVERAGE",
            },
            "defense_bucket_rules": {
                "STRONG": "prior-10 opponent SOG allowed/game / reference <= 0.90",
                "AVERAGE": "0.90 < prior-10 opponent SOG allowed/game / reference < 1.10",
                "WEAK": "prior-10 opponent SOG allowed/game / reference >= 1.10",
                "no_prior_sample": "AVERAGE",
            },
            "attack_bucket_team_game_counts": {k: int(attack_game_totals[k]) for k in ATTACK_LEVELS},
            "attack_bucket_team_counts_by_modal_2021_assignment": {
                k: int(attack_team_counts[k]) for k in ATTACK_LEVELS},
            "opponent_defense_bucket_team_game_counts": defense_game_totals,
            "per_team_attack_bucket_assignments": team_bucket_rows,
            "reachable_state_key_dimensions": [
                "period", "strength", "score_level", "time_level", "game_time_level",
                "HOME/AWAY", "attack_bucket", "defense_bucket"],
            "reachable_state_key_distinct_cells": len(key_counts),
            "reachable_state_key_occurrences_at_accepted_attempts": all_event_attempts,
            "reachable_state_key_cells": [
                {
                    "period": key[0], "strength": key[1], "score_level": key[2],
                    "time_level": key[3], "game_time_level": key[4],
                    "home_away": key[5], "attack_bucket": key[6],
                    "defense_bucket": key[7], "accepted_attempt_occurrences": int(count),
                }
                for key, count in sorted(key_counts.items())],
            "reachable_levels": reachable_levels,
            "distinct_cells_by_period": {key: cells_by_period[key] for key in sorted(cells_by_period)},
            "continuous_team_term": {
                "present": False,
                "evidence": [
                    "stochastic_model.py:158-208: quality_level maps rolling values to categories; state_key returns categorical levels and no team ID or continuous team feature.",
                    "stochastic_model.py:229-238: shot_rate applies exp(linear categorical rate dimensions) to that key.",
                ],
            },
        },
        "between_team_variance": outcome_results,
        "shared_tempo": paired,
        "interpretation": {
            "attempt_residual_variance_units": attempt_gap,
            "attempt_approx_additive_log_scale_sd": outcome_results["attempts"]["approx_missing_additive_log_scale_sd"],
            "sog_residual_variance_units": sog_gap,
            "sog_approx_additive_log_scale_sd": outcome_results["sog"]["approx_missing_additive_log_scale_sd"],
            "categorical_ceiling_note": "The 1.966 attempt / 0.694 SOG predicted between-team variances are the frozen simulator's measured 2021 forecast dispersion, not a mathematical ceiling over all possible bucket coefficients. A same-fold descriptive projection of observed team means on attack-bucket and opponent-defense-bucket frequencies plus home share explains 16.691 of 18.844 attempt variance and 6.971 of 7.157 SOG variance; 2.152 and 0.186 remain unallocated. This is descriptive-after-selection, not predictive validation. It indicates the 16.877/6.463 frozen forecast gaps are not proven unreachable under categorical features; the fitted rate effects or other model structure may be too weak or misaligned. Within-bucket differences cannot be represented by the current state key. Residuals also include omitted team, schedule, state-path, and Monte Carlo effects; they are not a causal attribution.",
            "shared_tempo_note": "A common positive multiplier induces positive dependence. The generator uses a total exponential event clock and chooses the shooter by rate share, mathematically equivalent to independent team Poisson clocks; it has no latent common tempo and no fixed total-attempt constraint.",
        },
    }
    payload["provenance"]["analysis_runtime_seconds"] = time.monotonic() - started
    OUTPUT_JSON.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    write_report(payload)


def write_report(data: dict) -> None:
    path = data["rate_path"]
    attempt = data["between_team_variance"]["attempts"]
    sog = data["between_team_variance"]["sog"]
    lines = [
        "# NHL V3 rate variation diagnostic",
        "",
        "Diagnostic only. This report does not select a candidate, change a gate, or alter the frozen simulator.",
        "The analysis uses the 2021 development population (1,312 games); 2022 is excluded because it has already been exposed.",
        "All confidence intervals use a game-ID cluster bootstrap, keeping both teams together. The 16 stored Monte Carlo draws per game are held fixed.",
        "",
        "## Rate-path bucket audit",
        "",
        f"The frozen `quality_level` reference is {path['quality_reference_sog_per_team_game']:.6f} SOG per team-game. Attack cuts are LOW at or below 0.90×, AVERAGE above 0.90× and below 1.10×, and HIGH at or above 1.10×. Defense reverses the direction: STRONG at or below 0.90× allowed, AVERAGE above 0.90× and below 1.10×, WEAK at or above 1.10×. Teams without a prior sample map to AVERAGE.",
        "",
        f"There are {path['reachable_state_key_distinct_cells']} distinct realized eight-part rate keys across {path['reachable_state_key_occurrences_at_accepted_attempts']:,} accepted 2021 attempts. Team attack bucket counts by each club's modal pregame assignment are " + ", ".join(f"{k} {v}" for k, v in path["attack_bucket_team_counts_by_modal_2021_assignment"].items()) + ". The JSON also contains every team's assignment frequency and the team-game counts in each bucket.",
        "",
        "`state_key` contains only categorical quality levels, and `shot_rate` exponentiates a linear predictor over those dimensions. There is no continuous team-level term in the frozen rate path (`stochastic_model.py:158-208,229-238`). The current forecasts therefore cannot distinguish teams that share the same attack and opponent-defense bucket values under the same state.",
        "",
        "## Between-team variance",
        "",
        "| Outcome | Observed between-team variance | Frozen forecast between-team variance | Gap | Approx. additive log-scale SD for gap |",
        "|---|---:|---:|---:|---:|",
        f"| Attempts | {attempt['observed_between_team_variance']:.3f} | {attempt['predicted_between_team_mean_variance']:.3f} | {attempt['observed_minus_predicted_between_team_variance']:.3f} | {attempt['approx_missing_additive_log_scale_sd']:.4f} |",
        f"| SOG | {sog['observed_between_team_variance']:.3f} | {sog['predicted_between_team_mean_variance']:.3f} | {sog['observed_minus_predicted_between_team_variance']:.3f} | {sog['approx_missing_additive_log_scale_sd']:.4f} |",
        "",
        f"For frozen forecast means, the bucket-frequency versus home-share descriptive Shapley split is {attempt['predicted_feature_projection']['bucket_membership_component']:.3f} vs {attempt['predicted_feature_projection']['home_away_assignment_component']:.3f} variance units for attempts, with {attempt['predicted_feature_projection']['unallocated_component']:.3f} unallocated; for SOG it is {sog['predicted_feature_projection']['bucket_membership_component']:.3f} vs {sog['predicted_feature_projection']['home_away_assignment_component']:.3f}, with {sog['predicted_feature_projection']['unallocated_component']:.3f} unallocated.",
        f"As a descriptive same-fold ceiling check, bucket frequencies plus site explain {attempt['observed_feature_projection']['combined_explained_component']:.3f} of observed attempt team-mean variance (95% interval {attempt['cluster_bootstrap_95_ci']['observed_explained'][0]:.3f} to {attempt['cluster_bootstrap_95_ci']['observed_explained'][1]:.3f}); {attempt['observed_feature_projection']['unallocated_component']:.3f} is unallocated. For SOG these values are {sog['observed_feature_projection']['combined_explained_component']:.3f} (95% interval {sog['cluster_bootstrap_95_ci']['observed_explained'][0]:.3f} to {sog['cluster_bootstrap_95_ci']['observed_explained'][1]:.3f}) and {sog['observed_feature_projection']['unallocated_component']:.3f}. This fit uses the same 2021 outcomes and is descriptive-after-selection; it does not show that the frozen model can realize this relationship out of sample.",
        "",
        f"The variance gaps have game-cluster bootstrap 95% intervals: attempts {attempt['cluster_bootstrap_95_ci']['between_gap']}, SOG {sog['cluster_bootstrap_95_ci']['between_gap']}. The approximate log-scale SD is sqrt(gap variance) divided by the observed mean count; it is a sizing diagnostic, not a fitted latent term.",
        "",
        "The 16.877 attempt and 6.463 SOG forecast gaps are the residuals relative to the current frozen forecasts. They are not proven variance that a continuous term must supply: the 2021 descriptive bucket projection explains most observed team-mean dispersion. The state key still cannot distinguish teams within the same buckets, but this measurement points to weak or misaligned fitted category effects and other generator structure as possibilities. No new term is implemented.",
        "",
        "## Home-away dependence and shared tempo sensitivity",
        "",
        f"Observed attempt covariance/correlation is {data['shared_tempo']['attempts']['observed']['covariance']:.3f}/{data['shared_tempo']['attempts']['observed']['correlation']:.3f}; the generated mixture is {data['shared_tempo']['attempts']['generated']['covariance']:.3f}/{data['shared_tempo']['attempts']['generated']['correlation']:.3f}. For SOG the corresponding values are {data['shared_tempo']['sog']['observed']['covariance']:.3f}/{data['shared_tempo']['sog']['observed']['correlation']:.3f} and {data['shared_tempo']['sog']['generated']['covariance']:.3f}/{data['shared_tempo']['sog']['generated']['correlation']:.3f}.",
        "",
        "Regulation and OT calculate a total exponential shot-arrival clock, then choose the shooting side in proportion to its rate (`stochastic_model.py:483-488,561-566`; side allocation at `:416-426`). This is equivalent to independent team Poisson clocks. There is no shared latent tempo and no fixed cap on combined attempts. A shared positive game multiplier adds positive covariance; the arithmetic below shows that even modest variation moves the forecast toward positive dependence, opposite the observed negative covariance.",
        "",
        "| Outcome | Shared multiplier SD/CV | Added covariance | Generated covariance after multiplier | 95% game-cluster interval |",
        "|---|---:|---:|---:|---:|",
    ]
    for outcome in ("attempts", "sog"):
        item = data["shared_tempo"][outcome]
        intervals = item["cluster_bootstrap_95_ci"]["shared_tempo_covariance_by_sd"]
        for row in item["shared_positive_game_tempo"]:
            cv = row["tempo_sd_cv"]
            lines.append(f"| {outcome} | {cv:.2f} | {row['added_covariance']:+.3f} | {row['covariance_after_shared_tempo']:+.3f} | [{intervals[str(cv)][0]:+.3f}, {intervals[str(cv)][1]:+.3f}] |")
    lines += [
        "",
        "## Reproduction and scope",
        "",
        f"Command: `{data['provenance']['reproduction_command']}`",
        f"Analysis script SHA-256: `{data['provenance']['analysis_script_sha256']}`",
        f"Pinned source scan covers {data['provenance']['source_event_rows_verified_full_source']:,} full-population event rows and {data['provenance']['source_eligible_2021_attempt_events']:,} eligible 2021 attempts. Exact source pins, per-team values, intervals, and reproduction checks are in `rate_variation.json`.",
        "",
        "No model, gate, promotion rule, Phase 2A result, or 2022 result was changed or tuned.",
        "",
    ]
    OUTPUT_MD.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
