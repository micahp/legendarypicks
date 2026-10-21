#!/usr/bin/env python3
"""Reproduce the Phase 2A under-dispersion diagnostics from pinned inputs.

The snapshot command reuses exact seeded Phase 2B simulation traces and rescans
the hash-pinned 2021 event ledger.  The analysis command operates only on the
committed, compact trace snapshot and Phase 2B RESULTS.json.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import io
import json
import math
import pickle
from pathlib import Path
import statistics
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
import stochastic_model as phase2a_model  # noqa: E402
from replay_model import SHOT_EVENTS, parse_situation_code  # noqa: E402

RESULTS = HERE / "RESULTS.json"
SNAPSHOT = HERE / "underdispersion-traces.json.gz"
OUTPUT_JSON = HERE / "underdispersion.json"
OUTPUT_MD = HERE / "UNDERDISPERSION.md"
CACHE_DIR = Path("/tmp/nhl-v3-phase2b-cache-7d5a1e6d4487a74a")
BASE_COMMIT = "dd36b4ae45d7e7050316f730a5e84629b93ce9a7"
PHASE2A_BASE_COMMIT = "19bb60cf8997abe1368b732983a4ed2ac1904cd3"
SIM_SEED = 20261021
SIMS = 16
BOOTSTRAP_SEED = 20261022
BOOTSTRAP_REPLICATES = 2000
PHASE2A_CACHE = "phase-2a-matched-reference-7d5a1e6d4487a74a.pickle"
C_CACHE = "c-v2-goal-prior-7d5a1e6d4487a74a.pickle"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_results() -> dict:
    result = json.loads(RESULTS.read_text(encoding="utf-8"))
    if result["base_commit"] != PHASE2A_BASE_COMMIT:
        raise ValueError("PHASE2B_RESULTS_PHASE2A_PARENT_MISMATCH")
    if result["branch"] != "research/nhl-v3-phase2b-scoring-2026-10-21":
        raise ValueError("PHASE2B_RESULTS_BRANCH_MISMATCH")
    if result["seed"] != SIM_SEED or result["simulations_per_game"] != SIMS:
        raise ValueError("PHASE2B_RESULTS_SEED_OR_SIM_COUNT_MISMATCH")
    if result["development"]["games"] != 1312:
        raise ValueError("PHASE2B_DEVELOPMENT_POPULATION_MISMATCH")
    return result


def _accepted_attempt(event, side: str | None) -> bool:
    return (event.event_type in SHOT_EVENTS and event.ordinary_shot_eligible is True and
            side in {"home", "away"} and event.quality.event == "ACCEPT" and
            event.quality.team_count == "ACCEPT")


def scan_actual_events(result: dict) -> tuple[dict[str, dict], dict]:
    """Load pinned inputs and rescan all PBP rows, retaining the 2021 fold."""
    command = result["command"]
    bundle = phase2a.load_bundle(
        artifact_dir=Path(command["artifacts"]), official_dir=Path(command["official"]),
        label_path=Path(command["labels"]))
    games = {gid: definition for gid, definition in bundle.games.items()
             if definition.season == 2021}
    if len(games) != 1312:
        raise ValueError(f"PINNED_2021_GAME_COUNT_MISMATCH {len(games)}")
    actual = {gid: {
        "attempts": Counter(), "pbp_sog": Counter(), "goals": Counter(),
        "attempts_by_strength": Counter(), "goals_by_strength": Counter(),
        "penalties": 0, "overtime": False, "shootout": False,
    } for gid in games}
    for gid, events in phase2a.iter_game_event_groups(bundle, game_ids=set(games)):
        definition = games[gid]
        current = actual[gid]
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
                key = (event.period_type, event.period_number)
                duration = phase2a._period_duration(event.period_type)
                if period_key != key:
                    period_key = key
                    previous_elapsed = 0
                    manpower = parse_situation_code("1551")
                elapsed = max(previous_elapsed, phase2a._event_elapsed(event, duration))
                parsed = parse_situation_code(event.situation_code)
                if parsed is not None:
                    manpower = parsed
                if event.period_type == "OT":
                    current["overtime"] = True
                if event.event_type == "penalty":
                    current["penalties"] += 1
                if _accepted_attempt(event, side):
                    label = phase2a._attempt_label(event.event_type)
                    current["attempts"][side] += 1
                    if label in {"SAVED", "GOAL"}:
                        current["pbp_sog"][side] += 1
                    strength = phase2a_model.strength_level(manpower, side)
                    current["attempts_by_strength"][strength] += 1
                    if label == "GOAL":
                        current["goals_by_strength"][strength] += 1
                previous_elapsed = elapsed
            if event.period_type == "SO":
                current["shootout"] = True
            if phase2a._accepted_team_goal(event, side):
                score[side] += 1
                current["goals"][side] += 1
    for gid, row in actual.items():
        definition = games[gid]
        row["team_ids"] = {"home": definition.home_team_id, "away": definition.away_team_id}
        row["official_sog"] = {"home": definition.official_home_sog,
                               "away": definition.official_away_sog}
        row["sog_eligible"] = definition.sog_disposition == "ACCEPT"
        row["official_margin"] = definition.official_home_score - definition.official_away_score
        row["attempts"] = {side: int(row["attempts"].get(side, 0)) for side in ("home", "away")}
        row["pbp_sog"] = {side: int(row["pbp_sog"].get(side, 0)) for side in ("home", "away")}
        row["goals"] = {side: int(row["goals"].get(side, 0)) for side in ("home", "away")}
        row["attempts_by_strength"] = dict(row["attempts_by_strength"])
        row["goals_by_strength"] = dict(row["goals_by_strength"])
    source_pins = result["source_pins"]
    return actual, {
        "base_commit": BASE_COMMIT,
        "source_pins": source_pins,
        "phase2a_hashes": result["frozen_phase2a_hashes"],
        "seed": SIM_SEED,
        "simulations_per_game": SIMS,
        "games": len(games),
    }


def build_snapshot(cache_dir: Path, *, rescan_source: bool = False) -> dict:
    """Build compact per-game input arrays; never runs a simulation."""
    start = time.monotonic()
    result = read_results()
    cache_paths = {"phase2a": cache_dir / PHASE2A_CACHE, "candidate_c": cache_dir / C_CACHE}
    cache_data = {}
    for label, path in cache_paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"REQUIRED_SEEDED_TRACE_CACHE_MISSING {path}")
        with path.open("rb") as handle:
            loaded = pickle.load(handle)
        if (loaded.get("run_fingerprint") != "7d5a1e6d4487a74a317b9c1697db659a0e66e12f5755c937f91fb32e618e76f9" or
                loaded.get("metrics", {}).get("sims_per_game") != SIMS or
                loaded.get("metrics", {}).get("games") != 1312 or
                loaded.get("metrics", {}).get("simulation_accounting_failures") != 0):
            raise ValueError(f"SEEDED_TRACE_CACHE_VALIDATION_FAILED {label}")
        cache_data[label] = loaded
    expected_name = {"phase2a": "Phase 2A matched reference", "candidate_c": "C v2 goal prior"}
    for label, loaded in cache_data.items():
        if loaded.get("name") != expected_name[label]:
            raise ValueError(f"SEEDED_TRACE_CACHE_VARIANT_MISMATCH {label}/{loaded.get('name')}")
    actual_cache = cache_dir / "underdispersion-actual-2021-7d5a1e6d4487a74a.json.gz"
    if actual_cache.is_file() and not rescan_source:
        with gzip.open(actual_cache, "rt", encoding="utf-8") as handle:
            cached_actual = json.load(handle)
        actual, source_meta = cached_actual["actual"], cached_actual["metadata"]
        if source_meta.get("source_pins") != result["source_pins"]:
            raise ValueError("ACTUAL_EVENT_SNAPSHOT_SOURCE_PIN_MISMATCH")
    else:
        scan_started = time.monotonic()
        actual, source_meta = scan_actual_events(result)
        source_meta["event_scan_seconds"] = time.monotonic() - scan_started
        with gzip.open(actual_cache, "wt", encoding="utf-8", compresslevel=6) as handle:
            json.dump({"actual": actual, "metadata": source_meta}, handle,
                      sort_keys=True, separators=(",", ":"))
    expected_observed = result["development"]["candidate_results"]["Phase 2A"]["simulation_components"]["observed_event_totals"]
    observed_checks = {
        "accepted_attempts_by_side": {side: sum(row["attempts"][side] for row in actual.values())
                                       for side in ("home", "away")},
        "accepted_pbp_sog_by_side": {side: sum(row["pbp_sog"][side] for row in actual.values())
                                     for side in ("home", "away")},
        "accepted_reg_ot_goals_by_side": {side: sum(row["goals"][side] for row in actual.values())
                                           for side in ("home", "away")},
        "accepted_penalty_events": sum(row["penalties"] for row in actual.values()),
        "overtime_games": sum(bool(row["overtime"]) for row in actual.values()),
        "shootout_games": sum(bool(row["shootout"]) for row in actual.values()),
    }
    if any(expected_observed.get(key) != value for key, value in observed_checks.items()):
        raise ValueError("RESCANNED_PBP_COMPONENT_TOTALS_DISAGREE_WITH_PHASE2B_RESULTS")
    phase2a_traces = cache_data["phase2a"]["traces"]
    c_traces = cache_data["candidate_c"]["traces"]
    expected_ids = set(actual)
    if set(phase2a_traces) != expected_ids or set(c_traces) != expected_ids:
        raise ValueError("SEEDED_TRACE_CACHE_GAME_ID_MISMATCH")
    paired = {row["game_id"]: row for row in
              result["development"]["candidate_results"]["Phase 2A"]["per_game_predictions"]}
    if len(paired) != 1312:
        raise ValueError("PHASE2B_PAIRED_ROW_COUNT_MISMATCH")
    rows = []
    for gid in sorted(actual):
        observation = actual[gid]
        a = phase2a_traces[gid]
        c = c_traces[gid]
        if len(a) != SIMS or len(c) != SIMS:
            raise ValueError(f"SEEDED_TRACE_SIM_COUNT_MISMATCH {gid}")
        if (sum(t["goals"]["home"] for t in a) / SIMS !=
                paired[gid]["predicted_home_reg_ot_goals_mean"] or
                sum(t["goals"]["away"] for t in a) / SIMS !=
                paired[gid]["predicted_away_reg_ot_goals_mean"]):
            raise ValueError(f"PHASE2A_TRACE_AND_RESULTS_GOAL_MEANS_DISAGREE {gid}")
        if (observation["goals"]["home"] != paired[gid]["actual_home_reg_ot_goals"] or
                observation["goals"]["away"] != paired[gid]["actual_away_reg_ot_goals"]):
            raise ValueError(f"RESCANNED_PBP_GOALS_AND_RESULTS_DISAGREE {gid}")
        rows.append({
            "game_id": gid,
            "team_ids": observation["team_ids"],
            "sog_eligible": observation["sog_eligible"],
            "observed": {key: observation[key] for key in (
                "attempts", "pbp_sog", "official_sog", "goals", "penalties",
                "overtime", "shootout", "official_margin", "attempts_by_strength",
                "goals_by_strength")},
            "phase2a": {
                "attempts": [[t["attempts"].get("home", 0), t["attempts"].get("away", 0)] for t in a],
                "sog": [[t["sog"].get("home", 0), t["sog"].get("away", 0)] for t in a],
                "goals": [[t["goals"].get("home", 0), t["goals"].get("away", 0)] for t in a],
                "penalties": [t["penalties"] for t in a],
                "overtime": [int(t["has_overtime"]) for t in a],
                "shootout": [int(t["has_shootout"]) for t in a],
                "margin": [t["margin"] for t in a],
            },
            "candidate_c_goals": [[t["goals"].get("home", 0), t["goals"].get("away", 0)] for t in c],
        })
    build_seconds = time.monotonic() - start
    snapshot = {
        "metadata": {
            **source_meta,
            "cache_fingerprint": "7d5a1e6d4487a74a317b9c1697db659a0e66e12f5755c937f91fb32e618e76f9",
            "cache_files": {key: {"basename": path.name, "sha256": sha256(path)}
                            for key, path in cache_paths.items()},
            "cached_simulations_reused": 2 * 1312 * SIMS,
            "monte_carlo_rerun": False,
            "source_event_rows_verified": 1510104,
            "event_scan_seconds": source_meta.get("event_scan_seconds"),
            "snapshot_build_seconds": build_seconds,
        },
        "games": rows,
    }
    with SNAPSHOT.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0, compresslevel=9) as zipped:
            with io.TextIOWrapper(zipped, encoding="utf-8") as text:
                json.dump(snapshot, text, sort_keys=True, separators=(",", ":"))
    return {"snapshot_sha256": sha256(SNAPSHOT), "snapshot_bytes": SNAPSHOT.stat().st_size,
            "snapshot_build_seconds": build_seconds, "games": len(rows)}


def _team_parts(values: np.ndarray, teams: np.ndarray) -> tuple[float, float]:
    overall = float(np.mean(values))
    _, inverse, counts = np.unique(teams, return_inverse=True, return_counts=True)
    sums = np.bincount(inverse, weights=values)
    means = sums / counts
    between = float(np.sum(counts * (means - overall) ** 2) / len(values))
    within = float(np.sum((values - means[inverse]) ** 2) / len(values))
    return between, within


def _decomposition(y: np.ndarray, mu: np.ndarray, var: np.ndarray,
                   teams: np.ndarray) -> dict:
    obs_between, obs_within = _team_parts(y, teams)
    pred_between, pred_within_means = _team_parts(mu, teams)
    noise = float(np.mean(var))
    pred_total = pred_between + pred_within_means + noise
    return {
        "n_team_games": int(len(y)),
        "observed": {"mean": float(np.mean(y)), "variance": float(np.var(y)),
                     "sd": float(np.std(y)), "between_team_variance": obs_between,
                     "within_team_game_variance": obs_within},
        "predicted": {"mean": float(np.mean(mu)), "variance": pred_total,
                      "sd": math.sqrt(max(0.0, pred_total)),
                      "between_team_mean_variance": pred_between,
                      "within_team_forecast_mean_variance": pred_within_means,
                      "within_game_predictive_variance": noise,
                      "within_game_predictive_sd": math.sqrt(max(0.0, noise)),
                      "observed_within_minus_predicted_within_total":
                          obs_within - pred_within_means - noise},
    }


def _nb_moments(y: np.ndarray, mu: np.ndarray, var: np.ndarray) -> tuple[float, float, float]:
    """Return observed NB2 alpha, simulator implied alpha, extra alpha vs simulator."""
    c = float(np.sum(y) / np.sum(mu))
    scaled_mu = c * mu
    denominator = float(np.sum(scaled_mu * scaled_mu))
    if denominator <= 0:
        raise ValueError("NB2_ZERO_MEAN_DENOMINATOR")
    residual_ss = float(np.sum((y - scaled_mu) ** 2))
    alpha_obs = max(0.0, (residual_ss - float(np.sum(scaled_mu))) / denominator)
    alpha_gen = float(np.sum(var - mu) / np.sum(mu * mu))
    extra = max(0.0, (residual_ss - c * float(np.sum(var))) / denominator)
    return alpha_obs, alpha_gen, extra


def _within_team_nb_alpha(y: np.ndarray, mu: np.ndarray, var: np.ndarray,
                          teams: np.ndarray) -> tuple[float, float]:
    """NB2 extra alpha after removing team means and forecast-mean movement."""
    _, within = _team_parts(y, teams)
    _, forecast_within = _team_parts(mu, teams)
    denominator = float(np.mean(mu * mu))
    if denominator <= 0:
        raise ValueError("WITHIN_TEAM_NB2_ZERO_MEAN_DENOMINATOR")
    extra = (within - forecast_within - float(np.mean(var))) / denominator
    generator = float(np.mean(var - mu)) / denominator
    return generator + extra, extra


def _fixed_effect_slope(y: np.ndarray, penalties: np.ndarray,
                        teams: np.ndarray) -> tuple[float, float]:
    _, inverse, counts = np.unique(teams, return_inverse=True, return_counts=True)
    ymeans = np.bincount(inverse, weights=y) / counts
    pmeans = np.bincount(inverse, weights=penalties) / counts
    yr = y - ymeans[inverse]
    pr = penalties - pmeans[inverse]
    denominator = float(np.sum(pr * pr))
    beta = float(np.sum(pr * yr) / denominator) if denominator else 0.0
    r2 = float((beta * beta * denominator) / np.sum(yr * yr)) if np.sum(yr * yr) else 0.0
    return beta, r2


def _nb_crps(y: int, mean: float, alpha: float) -> float:
    """Exact discrete CRPS for a Poisson/NB2 distribution, summed to tiny tail."""
    mean = max(float(mean), 1e-12)
    alpha = max(float(alpha), 0.0)
    if alpha == 0.0:
        probability = math.exp(-mean)
        probabilities = [probability]
        k = 0
        while 1.0 - sum(probabilities) > 1e-13 and k < 1000:
            k += 1
            probability *= mean / k
            probabilities.append(probability)
    else:
        size = 1.0 / alpha
        success = size / (size + mean)
        probability = success ** size
        probabilities = [probability]
        k = 0
        while 1.0 - sum(probabilities) > 1e-13 and k < 1000:
            k += 1
            probability *= ((k - 1 + size) / k) * (1.0 - success)
            probabilities.append(probability)
    total = sum(probabilities)
    probabilities = [p / total for p in probabilities]
    cdf = 0.0
    score = 0.0
    for k, probability in enumerate(probabilities):
        cdf += probability
        score += (cdf - (1.0 if y <= k else 0.0)) ** 2
    tail = max(0.0, 1.0 - cdf)
    score += tail * tail / max(1e-12, 1.0 - cdf) if tail > 1e-12 else 0.0
    return score


def _empirical_crps(samples: np.ndarray, y: int) -> float:
    ordered = np.sort(samples.astype(float))
    n = len(ordered)
    first = float(np.mean(np.abs(ordered - y)))
    pair_half = float(np.sum((2 * np.arange(n) - n + 1) * ordered) / (n * n))
    return first - pair_half


def _rows_arrays(games: list[dict], outcome: str, *, sog_only: bool = False):
    selected = [g for g in games if not sog_only or g["sog_eligible"]]
    y, mu, v, teams, draw_arrays = [], [], [], [], []
    for game in selected:
        sim = np.asarray(game["phase2a"][outcome], dtype=float)
        observed_key = {"attempts": "attempts", "sog": "official_sog", "goals": "goals"}[outcome]
        observed = game["observed"][observed_key]
        for side_idx, side in enumerate(("home", "away")):
            values = sim[:, side_idx]
            y.append(observed[side])
            mu.append(float(np.mean(values)))
            v.append(float(np.var(values)))
            teams.append(game["team_ids"][side])
            draw_arrays.append(values)
    return (np.asarray(y, dtype=float), np.asarray(mu), np.asarray(v),
            np.asarray(teams), np.asarray(draw_arrays, dtype=float), selected)


def _margin_arrays(games: list[dict]):
    observed = np.asarray([g["observed"]["official_margin"] for g in games], dtype=float)
    draws = np.asarray([g["phase2a"]["margin"] for g in games], dtype=float)
    return observed, np.mean(draws, axis=1), np.var(draws, axis=1), draws


def analyze(snapshot_path: Path, bootstrap_reps: int = BOOTSTRAP_REPLICATES) -> dict:
    started = time.monotonic()
    result = read_results()
    with gzip.open(snapshot_path, "rt", encoding="utf-8") as handle:
        snapshot = json.load(handle)
    meta = snapshot["metadata"]
    if meta["base_commit"] != BASE_COMMIT or meta["seed"] != SIM_SEED or meta["simulations_per_game"] != SIMS:
        raise ValueError("UNDERDISPERSION_SNAPSHOT_PROVENANCE_MISMATCH")
    if meta["source_pins"] != result["source_pins"] or meta["phase2a_hashes"] != result["frozen_phase2a_hashes"]:
        raise ValueError("UNDERDISPERSION_SNAPSHOT_SOURCE_PIN_MISMATCH")
    games = snapshot["games"]
    if len(games) != 1312 or len({g["game_id"] for g in games}) != 1312:
        raise ValueError("UNDERDISPERSION_SNAPSHOT_POPULATION_MISMATCH")
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    decompositions = {}
    arrays = {}
    for outcome in ("attempts", "sog", "goals"):
        y, mu, v, teams, draws, selected = _rows_arrays(games, outcome, sog_only=(outcome == "sog"))
        arrays[outcome] = (y, mu, v, teams, draws, selected)
        decomp = _decomposition(y, mu, v, teams)
        n_games = len(selected)
        boots = {key: [] for key in ("observed_variance", "predicted_variance", "within_gap",
                                     "observed_between", "observed_within", "predicted_between",
                                     "predicted_within_mean", "predicted_within_game",
                                     "between_team_gap", "total_variance_gap")}
        alphas = {key: [] for key in ("observed_nb2_alpha", "simulator_nb2_alpha", "extra_nb2_alpha")}
        within_alphas = {key: [] for key in ("effective_nb2_alpha", "extra_nb2_alpha")}
        for _ in range(bootstrap_reps):
            sampled = rng.integers(0, n_games, size=n_games)
            idx = np.column_stack((2 * sampled, 2 * sampled + 1)).ravel()
            boot = _decomposition(y[idx], mu[idx], v[idx], teams[idx])
            pobs, ppred = boot["observed"], boot["predicted"]
            boots["observed_variance"].append(pobs["variance"])
            boots["predicted_variance"].append(ppred["variance"])
            boots["within_gap"].append(ppred["observed_within_minus_predicted_within_total"])
            boots["observed_between"].append(pobs["between_team_variance"])
            boots["observed_within"].append(pobs["within_team_game_variance"])
            boots["predicted_between"].append(ppred["between_team_mean_variance"])
            boots["predicted_within_mean"].append(ppred["within_team_forecast_mean_variance"])
            boots["predicted_within_game"].append(ppred["within_game_predictive_variance"])
            boots["between_team_gap"].append(pobs["between_team_variance"] -
                                             ppred["between_team_mean_variance"])
            boots["total_variance_gap"].append(pobs["variance"] - ppred["variance"])
            aobs, agen, aextra = _nb_moments(y[idx], mu[idx], v[idx])
            alphas["observed_nb2_alpha"].append(aobs)
            alphas["simulator_nb2_alpha"].append(agen)
            alphas["extra_nb2_alpha"].append(aextra)
            effective_fe, extra_fe = _within_team_nb_alpha(y[idx], mu[idx], v[idx], teams[idx])
            within_alphas["effective_nb2_alpha"].append(effective_fe)
            within_alphas["extra_nb2_alpha"].append(extra_fe)
        for key, values in boots.items():
            decomp.setdefault("cluster_bootstrap_95_ci", {})[key] = [
                float(x) for x in np.quantile(values, [0.025, 0.975])]
        decompositions[outcome] = decomp
        point_alpha = _nb_moments(y, mu, v)
        decompositions[outcome]["negative_binomial"] = {
            "definition": "NB2 variance = c*mu + alpha*(c*mu)^2; c globally matches observed mean to frozen Phase 2A forecast mean",
            "observed_nb2_alpha": point_alpha[0],
            "simulator_implied_nb2_alpha_signed": point_alpha[1],
            "extra_nb2_alpha_over_simulator": point_alpha[2],
            "cluster_bootstrap_95_ci": {
                key: [float(x) for x in np.quantile(values, [0.025, 0.975])]
                for key, values in alphas.items()},
        }
        effective_fe, extra_fe = _within_team_nb_alpha(y, mu, v, teams)
        decompositions[outcome]["within_team_negative_binomial"] = {
            "definition": "NB2 Var=mu+alpha*mu^2. Effective alpha=(observed within-team variance - forecast-mean within-team variance - mean(mu))/mean(mu^2). Extra alpha over generator=(observed within-team variance - forecast-mean within-team variance - mean(simulator variance))/mean(mu^2). No level rescaling.",
            "effective_observed_nb2_alpha_signed": effective_fe,
            "simulator_implied_nb2_alpha_signed": point_alpha[1],
            "extra_nb2_alpha_over_simulator_signed": extra_fe,
            "cluster_bootstrap_95_ci": {
                key: [float(x) for x in np.quantile(values, [0.025, 0.975])]
                for key, values in within_alphas.items()},
        }

    # Penalty projection: team fixed effects, game-cluster bootstrap, and a
    # descriptive variance attribution from observed vs generated penalty spread.
    penalty_results = {}
    penalty_obs = np.asarray([g["observed"]["penalties"] for g in games], dtype=float)
    penalty_draws = np.asarray([g["phase2a"]["penalties"] for g in games], dtype=float)
    for outcome in ("attempts", "sog"):
        y, mu, v, teams, draws, selected = arrays[outcome]
        selected_games = [int(g["game_id"] in {x["game_id"] for x in selected}) for g in games]
        game_indices = np.asarray([i for i, flag in enumerate(selected_games) if flag], dtype=int)
        pgame = penalty_obs[game_indices]
        pdraw = penalty_draws[game_indices]
        team_game = np.asarray([g["team_ids"][side] for g in selected for side in ("home", "away")])
        p_team = np.repeat(pgame, 2)
        beta, r2 = _fixed_effect_slope(y, p_team, team_game)
        generated_penalty_mean = float(np.mean(pdraw))
        missing_rate = float(np.mean(pgame) - generated_penalty_mean)
        # Fixed-effect residual variance directly (the slope helper's R2 is not variance).
        def residual_variance(values, labels):
            _, inverse, counts = np.unique(labels, return_inverse=True, return_counts=True)
            means = np.bincount(inverse, weights=values) / counts
            return float(np.mean((values - means[inverse]) ** 2))
        obs_penalty_resid_var = residual_variance(p_team, team_game)
        sim_penalty_values = np.repeat(pdraw[:, :, None], 2, axis=2).reshape(-1)
        sim_penalty_teams = np.tile(team_game.reshape(-1, 2)[:, None, :], (1, SIMS, 1)).reshape(-1)
        sim_penalty_resid_var = residual_variance(sim_penalty_values, sim_penalty_teams)
        penalty_variance_increment = beta * beta * max(0.0, obs_penalty_resid_var - sim_penalty_resid_var)
        observed_within = decompositions[outcome]["observed"]["within_team_game_variance"]
        predicted_within = (decompositions[outcome]["predicted"]["within_team_forecast_mean_variance"] +
                            decompositions[outcome]["predicted"]["within_game_predictive_variance"])
        remaining_gap = observed_within - predicted_within
        boots = []
        for _ in range(bootstrap_reps):
            sampled = rng.integers(0, len(game_indices), size=len(game_indices))
            game_idx = game_indices[sampled]
            row_idx = np.column_stack((2 * sampled, 2 * sampled + 1)).ravel()
            bt, br2 = _fixed_effect_slope(y[row_idx], np.repeat(penalty_obs[game_idx], 2), teams[row_idx])
            bpobs = np.repeat(penalty_obs[game_idx], 2)
            blabels = teams[row_idx]
            bobsvar = residual_variance(bpobs, blabels)
            bdraws = penalty_draws[game_idx]
            bvals = np.repeat(bdraws[:, :, None], 2, axis=2).reshape(-1)
            blabels_sim = np.tile(blabels.reshape(-1, 2)[:, None, :], (1, SIMS, 1)).reshape(-1)
            bsimvar = residual_variance(bvals, blabels_sim)
            boots.append((bt, br2, bt * (float(np.mean(penalty_obs[game_idx])) -
                                           float(np.mean(penalty_draws[game_idx]))),
                           bt * bt * max(0.0, bobsvar - bsimvar)))
        boots = np.asarray(boots, dtype=float)
        penalty_results[outcome] = {
            "team_fixed_effect_linear_projection_beta_per_extra_accepted_penalty": beta,
            "within_team_partial_r_squared": r2,
            "observed_penalty_rate_per_game": float(np.mean(pgame)),
            "generated_penalty_rate_per_game": generated_penalty_mean,
            "penalty_mean_gap": missing_rate,
            "projected_attempt_or_sog_change_per_team_game_from_mean_gap": beta * missing_rate,
            "observed_penalty_within_team_variance": obs_penalty_resid_var,
            "generated_penalty_within_team_variance": sim_penalty_resid_var,
            "projected_variance_increment_from_penalty_spread_gap": penalty_variance_increment,
            "observed_minus_predicted_within_team_count_variance": remaining_gap,
            "fraction_of_within_team_variance_gap_projected":
                penalty_variance_increment / remaining_gap if remaining_gap > 0 else None,
            "cluster_bootstrap_95_ci": {
                name: [float(x) for x in np.quantile(boots[:, index], [0.025, 0.975])]
                for name, index in (("beta", 0), ("partial_r_squared", 1),
                                    ("projected_mean_count_change", 2),
                                    ("projected_variance_increment", 3))},
            "interpretation": "Associational linear projection after team fixed effects; not a causal estimate of penalty mechanics.",
        }

    # Variance-only sensitivity: one full-sample NB2 alpha fitted from Phase 2A
    # predictions, held fixed for both empirical forecast scenarios.
    goal_y, goal_mu, goal_v, goal_teams, phase2a_goal_draws, _ = arrays["goals"]
    goal_alpha = max(0.0, float(np.sum((goal_y - goal_mu) ** 2 - goal_mu) /
                                np.sum(goal_mu ** 2)))
    c_rows = np.asarray([g["candidate_c_goals"] for g in games], dtype=float).reshape(-1, SIMS, 2)
    c_draws = np.concatenate((c_rows[:, :, 0], c_rows[:, :, 1]), axis=0)
    baseline_scores, candidate_scores, recal_base, recal_c = [], [], [], []
    for i, game in enumerate(games):
        y_pair = [game["observed"]["goals"][side] for side in ("home", "away")]
        a = np.asarray(game["phase2a"]["goals"], dtype=float)
        c = np.asarray(game["candidate_c_goals"], dtype=float)
        for side_idx in (0, 1):
            yvalue = int(y_pair[side_idx])
            baseline_scores.append(_empirical_crps(a[:, side_idx], yvalue))
            candidate_scores.append(_empirical_crps(c[:, side_idx], yvalue))
            recal_base.append(_nb_crps(yvalue, float(np.mean(a[:, side_idx])), goal_alpha))
            recal_c.append(_nb_crps(yvalue, float(np.mean(c[:, side_idx])), goal_alpha))
    baseline_scores = np.asarray(baseline_scores).reshape(-1, 2)
    candidate_scores = np.asarray(candidate_scores).reshape(-1, 2)
    recal_base = np.asarray(recal_base).reshape(-1, 2)
    recal_c = np.asarray(recal_c).reshape(-1, 2)
    raw_gain_by_game = np.mean(baseline_scores - candidate_scores, axis=1)
    recal_gain_by_game = np.mean(recal_base - recal_c, axis=1)
    # Use the same game-cluster draws for both score comparisons.
    raw_gain_boot, recal_gain_boot = [], []
    for _ in range(bootstrap_reps):
        ix = rng.integers(0, len(games), size=len(games))
        raw_gain_boot.append(float(np.mean(raw_gain_by_game[ix])))
        recal_gain_boot.append(float(np.mean(recal_gain_by_game[ix])))
    raw_gain, recal_gain = float(np.mean(raw_gain_by_game)), float(np.mean(recal_gain_by_game))
    phase2a_report = result["development"]["candidate_results"]["Phase 2A"]["simulation_metrics"]
    c_report = result["development"]["candidate_results"]["C v2 goal prior"]["simulation_metrics"]
    if abs(float(np.mean(baseline_scores)) - phase2a_report["reg_ot_team_goal_crps"]) > 1e-9:
        raise ValueError("RECOMPUTED_PHASE2A_GOAL_CRPS_MISMATCH")
    if abs(float(np.mean(candidate_scores)) - c_report["reg_ot_team_goal_crps"]) > 1e-9:
        raise ValueError("RECOMPUTED_C_GOAL_CRPS_MISMATCH")
    goal_sensitivity = {
        "label": "descriptive-after-selection; not a candidate and not a tuning result",
        "common_nb2_alpha_fitted_from_phase2a_2021_outcomes_at_fixed_forecast_means": goal_alpha,
        "alpha_estimation": "max(0, sum((observed - frozen Phase 2A mean)^2 - frozen Phase 2A mean) / sum(frozen Phase 2A mean^2)); preserves every stored per-team-game mean and can absorb mean error into dispersion",
        "raw_phase2a_goal_crps": float(np.mean(baseline_scores)),
        "raw_candidate_c_goal_crps": float(np.mean(candidate_scores)),
        "raw_c_gain_vs_phase2a": raw_gain,
        "raw_c_gain_cluster_bootstrap_95_ci": [float(x) for x in np.quantile(raw_gain_boot, [0.025, 0.975])],
        "nb2_recalibrated_phase2a_goal_crps": float(np.mean(recal_base)),
        "nb2_recalibrated_candidate_c_goal_crps": float(np.mean(recal_c)),
        "nb2_recalibrated_c_gain_vs_phase2a": recal_gain,
        "nb2_recalibrated_c_gain_cluster_bootstrap_95_ci_alpha_fixed":
            [float(x) for x in np.quantile(recal_gain_boot, [0.025, 0.975])],
        "change_in_c_gain_after_recalibration": recal_gain - raw_gain,
        "bootstrap_note": "Games resampled as clusters; the full-sample mean-preserving NB2 alpha is fixed, so the interval omits alpha-estimation uncertainty.",
    }

    # Final score margin: report both population variation and the actual
    # predictive mixture, avoiding a comparison of observed spread to only the
    # within-game simulation variance.
    margin_y, margin_mu, margin_v, margin_draws = _margin_arrays(games)
    margin = {
        "games": len(games),
        "observed_mean": float(np.mean(margin_y)),
        "observed_variance": float(np.var(margin_y)),
        "predicted_mean": float(np.mean(margin_mu)),
        "predicted_between_game_forecast_mean_variance": float(np.var(margin_mu)),
        "predicted_mean_within_game_variance": float(np.mean(margin_v)),
        "predicted_marginal_variance": float(np.var(margin_mu) + np.mean(margin_v)),
        "observed_sd": float(np.std(margin_y)),
        "predicted_marginal_sd": math.sqrt(float(np.var(margin_mu) + np.mean(margin_v))),
        "mean_absolute_margin_error": float(np.mean(np.abs(margin_y - margin_mu))),
    }
    margin_boot = {key: [] for key in ("observed_mean", "predicted_mean",
                                       "observed_variance", "predicted_marginal_variance")}
    for _ in range(bootstrap_reps):
        ix = rng.integers(0, len(games), size=len(games))
        margin_boot["observed_mean"].append(float(np.mean(margin_y[ix])))
        margin_boot["predicted_mean"].append(float(np.mean(margin_mu[ix])))
        margin_boot["observed_variance"].append(float(np.var(margin_y[ix])))
        margin_boot["predicted_marginal_variance"].append(float(
            np.var(margin_mu[ix]) + np.mean(margin_v[ix])))
    margin["cluster_bootstrap_95_ci"] = {
        key: [float(x) for x in np.quantile(values, [0.025, 0.975])]
        for key, values in margin_boot.items()}

    # Paired game-cluster intervals for conversion, penalty rates, and OT/SO
    # frequencies. The generated ratios use all cached draws within each game.
    obs_sog_pbp = np.asarray([sum(g["observed"]["pbp_sog"].values()) for g in games], dtype=float)
    obs_attempt_totals = np.asarray([sum(g["observed"]["attempts"].values()) for g in games], dtype=float)
    obs_goal_totals = np.asarray([sum(g["observed"]["goals"].values()) for g in games], dtype=float)
    sim_attempt_totals = np.asarray([sum(sum(pair) for pair in g["phase2a"]["attempts"]) for g in games], dtype=float)
    sim_sog_totals = np.asarray([sum(sum(pair) for pair in g["phase2a"]["sog"]) for g in games], dtype=float)
    sim_goal_totals = np.asarray([sum(sum(pair) for pair in g["phase2a"]["goals"]) for g in games], dtype=float)
    obs_penalties = np.asarray([g["observed"]["penalties"] for g in games], dtype=float)
    sim_penalty_means = np.asarray([np.mean(g["phase2a"]["penalties"]) for g in games], dtype=float)
    obs_ot = np.asarray([g["observed"]["overtime"] for g in games], dtype=float)
    obs_so = np.asarray([g["observed"]["shootout"] for g in games], dtype=float)
    sim_ot_means = np.asarray([np.mean(g["phase2a"]["overtime"]) for g in games], dtype=float)
    sim_so_means = np.asarray([np.mean(g["phase2a"]["shootout"]) for g in games], dtype=float)
    conversion_boot, sog_rate_boot, penalty_gap_boot, ot_gap_boot, so_gap_boot = [], [], [], [], []
    for _ in range(bootstrap_reps):
        ix = rng.integers(0, len(games), size=len(games))
        conversion_boot.append((float(np.sum(obs_goal_totals[ix]) / np.sum(obs_sog_pbp[ix])),
                               float(np.sum(sim_goal_totals[ix]) / np.sum(sim_sog_totals[ix]))))
        sog_rate_boot.append((float(np.sum(obs_sog_pbp[ix]) / np.sum(obs_attempt_totals[ix])),
                              float(np.sum(sim_sog_totals[ix]) / np.sum(sim_attempt_totals[ix]))))
        penalty_gap_boot.append(float(np.mean(obs_penalties[ix] - sim_penalty_means[ix])))
        ot_gap_boot.append(float(np.mean(obs_ot[ix] - sim_ot_means[ix])))
        so_gap_boot.append(float(np.mean(obs_so[ix] - sim_so_means[ix])))
    conversion_boot = np.asarray(conversion_boot, dtype=float)
    sog_rate_boot = np.asarray(sog_rate_boot, dtype=float)
    paired_count_covariance = {}
    for outcome in ("attempts", "sog", "goals"):
        eligible = [g for g in games if outcome != "sog" or g["sog_eligible"]]
        observed_key = {"attempts": "attempts", "sog": "official_sog", "goals": "goals"}[outcome]
        observed_pairs = np.asarray([[g["observed"][observed_key]["home"],
                                      g["observed"][observed_key]["away"]]
                                     for g in eligible], dtype=float)
        simulated_pairs = np.asarray([g["phase2a"][outcome] for g in eligible], dtype=float)
        predicted_pairs = simulated_pairs.reshape(-1, 2)
        covariance_boot = {key: {"observed": [], "generated": []}
                           for key in ("covariance", "correlation")}
        for _ in range(bootstrap_reps):
            ix = rng.integers(0, len(eligible), size=len(eligible))
            obs_sample = observed_pairs[ix]
            sim_sample = simulated_pairs[ix].reshape(-1, 2)
            covariance_boot["covariance"]["observed"].append(float(np.cov(obs_sample.T, ddof=0)[0, 1]))
            covariance_boot["covariance"]["generated"].append(float(np.cov(sim_sample.T, ddof=0)[0, 1]))
            covariance_boot["correlation"]["observed"].append(float(np.corrcoef(obs_sample.T)[0, 1]))
            covariance_boot["correlation"]["generated"].append(float(np.corrcoef(sim_sample.T)[0, 1]))
        paired_count_covariance[outcome] = {
            "n_games": len(eligible),
            "observed_covariance": float(np.cov(observed_pairs.T, ddof=0)[0, 1]),
            "generated_mixture_covariance": float(np.cov(predicted_pairs.T, ddof=0)[0, 1]),
            "observed_correlation": float(np.corrcoef(observed_pairs.T)[0, 1]),
            "generated_mixture_correlation": float(np.corrcoef(predicted_pairs.T)[0, 1]),
            "cluster_bootstrap_95_ci": {
                metric: {population: [float(x) for x in np.quantile(values, [0.025, 0.975])]
                         for population, values in populations.items()}
                for metric, populations in covariance_boot.items()},
        }
    component_diagnostics = {
        "shot_stage_probabilities": {
            "observed_pbp_sog_per_attempt": float(np.sum(obs_sog_pbp) / np.sum(obs_attempt_totals)),
            "generated_sog_per_attempt": float(np.sum(sim_sog_totals) / np.sum(sim_attempt_totals)),
            "observed_pbp_attempts": int(np.sum(obs_attempt_totals)),
            "generated_attempts_across_draws": int(np.sum(sim_attempt_totals)),
            "cluster_bootstrap_95_ci": {
                "observed": [float(x) for x in np.quantile(sog_rate_boot[:, 0], [0.025, 0.975])],
                "generated": [float(x) for x in np.quantile(sog_rate_boot[:, 1], [0.025, 0.975])]},
        },
        "shooting_percentage": {
            "observed_pbp_goals_per_pbp_sog": float(np.sum(obs_goal_totals) / np.sum(obs_sog_pbp)),
            "generated_goals_per_generated_sog": float(np.sum(sim_goal_totals) / np.sum(sim_sog_totals)),
            "observed_pbp_sog_events": int(np.sum(obs_sog_pbp)),
            "generated_sog_events_across_draws": int(np.sum(sim_sog_totals)),
            "cluster_bootstrap_95_ci": {
                "observed": [float(x) for x in np.quantile(conversion_boot[:, 0], [0.025, 0.975])],
                "generated": [float(x) for x in np.quantile(conversion_boot[:, 1], [0.025, 0.975])]},
            "model_expected_goal_probability_at_observed_locations":
                result["development"]["event_level_diagnostics"]["Phase 2A"]["predicted_goal_per_sog_at_observed_locations"],
            "observed_goal_probability_at_observed_locations":
                result["development"]["event_level_diagnostics"]["Phase 2A"]["observed_goal_per_sog"],
            "observed_location_probability_is_event_weighted_and_has_no_cluster_interval_in_phase2b_artifact": True,
        },
        "game_state_rates": {
            "penalties_per_game": {"observed": float(np.mean(obs_penalties)),
                                   "generated": float(np.mean(sim_penalty_means)),
                                   "observed_minus_generated": float(np.mean(obs_penalties - sim_penalty_means)),
                                   "difference_cluster_bootstrap_95_ci":
                                       [float(x) for x in np.quantile(penalty_gap_boot, [0.025, 0.975])]},
            "overtime_game_probability": {"observed": float(np.mean(obs_ot)),
                                          "generated": float(np.mean(sim_ot_means)),
                                          "observed_minus_generated": float(np.mean(obs_ot - sim_ot_means)),
                                          "difference_cluster_bootstrap_95_ci":
                                              [float(x) for x in np.quantile(ot_gap_boot, [0.025, 0.975])]},
            "shootout_game_probability": {"observed": float(np.mean(obs_so)),
                                          "generated": float(np.mean(sim_so_means)),
                                          "observed_minus_generated": float(np.mean(obs_so - sim_so_means)),
                                          "difference_cluster_bootstrap_95_ci":
                                              [float(x) for x in np.quantile(so_gap_boot, [0.025, 0.975])]},
        },
    }

    phase2a_metrics = result["development"]["candidate_results"]["Phase 2A"]["simulation_metrics"]
    c_metrics = result["development"]["candidate_results"]["C v2 goal prior"]["simulation_metrics"]
    c_vs_phase2a = result["development"]["candidate_results"]["C v2 goal prior"]["paired_comparisons"]["Phase 2A"]["paired_comparisons"]
    phase2a_components = result["development"]["candidate_results"]["Phase 2A"]["simulation_components"]
    predicted_totals = phase2a_components["predicted_mean_per_game_totals"]
    observed_totals = phase2a_components["observed_event_totals"]
    structural_conditional_rates = {
        "observed_ot_goals_per_ot_game": phase2a_components["goals_by_period_observed"]["OT"] /
            observed_totals["overtime_games"],
        "generated_ot_goals_per_ot_game": phase2a_components["goals_by_period_predicted_per_game"]["OT"] * 1312 /
            predicted_totals["overtime_games"],
        "observed_shootouts_per_ot_game": observed_totals["shootout_games"] /
            observed_totals["overtime_games"],
        "generated_shootouts_per_ot_game": predicted_totals["shootout_games"] /
            predicted_totals["overtime_games"],
    }
    strength_composition = {}
    for strength in ("EVEN", "ADVANTAGE", "DISADVANTAGE", "EMPTY_NET"):
        observed_attempts = phase2a_components["strength_attempts_observed"].get(strength, 0) / 1312
        generated_attempts = phase2a_components["strength_attempts_predicted_per_game"].get(strength, 0.0)
        observed_goals = phase2a_components["strength_goals_observed"].get(strength, 0) / 1312
        generated_goals = phase2a_components["strength_goals_predicted_per_game"].get(strength, 0.0)
        strength_composition[strength] = {
            "observed_attempts_per_game": observed_attempts,
            "generated_attempts_per_game": generated_attempts,
            "attempt_gap_generated_minus_observed": generated_attempts - observed_attempts,
            "observed_goals_per_game": observed_goals,
            "generated_goals_per_game": generated_goals,
            "goal_gap_generated_minus_observed": generated_goals - observed_goals,
        }
    stored_candidate_comparison = {
        "label": "historical Phase 2B results on the 2021 selection fold; included for context only",
        "phase2a": {key: phase2a_metrics[key] for key in (
            "reg_ot_team_goal_crps", "final_score_energy_score", "winner_brier", "team_sog_crps")},
        "candidate_c": {key: c_metrics[key] for key in (
            "reg_ot_team_goal_crps", "final_score_energy_score", "winner_brier", "team_sog_crps")},
        "paired_c_minus_phase2a_baseline_minus_candidate": {
            key: c_vs_phase2a[name]
            for key, name in (("goal_crps", "team_goal_crps_baseline_minus_candidate"),
                              ("final_score_energy", "final_score_energy_baseline_minus_candidate"),
                              ("winner_brier", "winner_brier_baseline_minus_candidate"),
                              ("team_sog_crps", "team_sog_crps_baseline_minus_candidate"))},
    }

    # Recompute the key forecast means and conditional variances against the
    # already committed Phase 2B diagnostics to catch stale/mismatched traces.
    crosschecks = {}
    for outcome, key in (("attempts", "attempts"), ("sog", "sog"), ("goals", "goals")):
        diag = result["development"]["baseline_diagnostics"][key]
        y, mu, v, _, _, _ = arrays[outcome]
        crosschecks[outcome] = {
            "observed_mean_matches_results": abs(float(np.mean(y)) - diag["observed_mean"]) < 1e-10,
            "predicted_mean_matches_results": abs(float(np.mean(mu)) - diag["predicted_mean"]) < 1e-10,
            "mean_within_game_variance_matches_results": abs(float(np.mean(v)) -
                diag["mean_within_game_predictive_variance"]) < 1e-10,
        }
        if not all(crosschecks[outcome].values()):
            raise ValueError(f"PHASE2B_BASELINE_DIAGNOSTIC_CROSSCHECK_FAILED {outcome}")

    try:
        snapshot_display_path = str(snapshot_path.resolve().relative_to(REPO.resolve()))
    except ValueError:
        snapshot_display_path = str(snapshot_path)
    output = {
        "base_commit": BASE_COMMIT,
        "decision": {"diagnostic_only": True, "candidate_selected": False,
                     "gate_changed": False, "frozen_phase2a_modified": False,
                     "2022_used_for_tuning": False},
        "phase2b_results_sha256": sha256(RESULTS),
        "analysis_script_sha256": sha256(Path(__file__).resolve()),
        "frozen_phase2a_hashes": result["frozen_phase2a_hashes"],
        "seed": SIM_SEED,
        "simulations_per_game": SIMS,
        "development_games": 1312,
        "sog_eligible_games": sum(g["sog_eligible"] for g in games),
        "input_snapshot": {"path": snapshot_display_path,
                           "sha256": sha256(snapshot_path), "bytes": snapshot_path.stat().st_size},
        "source_pins": meta["source_pins"],
        "cache": meta,
        "commands": {
            "build_snapshot": "/root/legendarypicks/backend/venv/bin/python research/nhl/nhl-v3-phase2b-scoring-2026-10-21/underdispersion.py --build-snapshot --rescan-source --cache-dir /tmp/nhl-v3-phase2b-cache-7d5a1e6d4487a74a",
            "recompute_diagnostics_from_committed_snapshot": "/root/legendarypicks/backend/venv/bin/python research/nhl/nhl-v3-phase2b-scoring-2026-10-21/underdispersion.py --analyze --bootstrap-replicates 2000",
        },
        "bootstrap": {"method": "percentile cluster bootstrap resampling game IDs with both teams kept together",
                      "replicates": bootstrap_reps, "seed": BOOTSTRAP_SEED},
        "variance_decomposition": decompositions,
        "penalty_projection": penalty_results,
        "goal_variance_only_sensitivity": goal_sensitivity,
        "final_score_margin": margin,
        "scoring_and_game_state_diagnostics": component_diagnostics,
        "paired_home_away_count_covariance": paired_count_covariance,
        "structural_conditional_rates": structural_conditional_rates,
        "strength_composition": strength_composition,
        "stored_candidate_comparison": stored_candidate_comparison,
        "reproduction_crosschecks": crosschecks,
        "analysis_runtime_seconds": time.monotonic() - started,
    }
    return output


def _pct(value: float) -> str:
    return f"{100.0 * value:.1f}%"


def render_report(data: dict, result: dict) -> str:
    d = data["variance_decomposition"]
    baseline = result["development"]["baseline_diagnostics"]
    comp = result["development"]["candidate_results"]["Phase 2A"]["simulation_components"]
    c = data["goal_variance_only_sensitivity"]
    p = data["penalty_projection"]
    lines = [
        "# NHL V3 under-dispersion and structural diagnosis",
        "",
        "Diagnostic only. This report selects no candidate, changes no gate, does not tune on 2022, and leaves frozen Phase 2A files unchanged. All metrics use the 2021 development population (1,312 games; 16 seeded simulations/game). Actual target-game locations and states are used only in retrospective diagnostics; no target-game starting-goalie identity enters the forecasts.",
        "",
        "## Count spread and calibration",
        "",
        "The original Phase 2B diagnostic compared pooled observed variance with mean within-game simulation variance. That omits the variation in forecast means across games. The decomposition below separates team means, within-team forecast-mean variation, and within-game predictive variance. The within-team gap therefore compares observed game variation around team rates with forecast-mean movement plus stochastic simulation spread.",
        "",
        "| Count | Observed mean / SD | Forecast mean / marginal SD | Between-team variance (obs / forecast means; gap, 95% clustered CI) | Within-team game variance (obs / forecast means + simulation; residual gap, 95% clustered CI) |",
        "|---|---:|---:|---:|---:|",
    ]
    for key, label in (("attempts", "Attempts"), ("sog", "Official SOG"), ("goals", "Goals")):
        x = d[key]
        obs, pred = x["observed"], x["predicted"]
        ci = x["cluster_bootstrap_95_ci"]["within_gap"]
        between_gap = obs["between_team_variance"] - pred["between_team_mean_variance"]
        between_ci = x["cluster_bootstrap_95_ci"]["between_team_gap"]
        lines.append(f"| {label} | {obs['mean']:.3f} / {obs['sd']:.3f} | {pred['mean']:.3f} / {pred['sd']:.3f} | {obs['between_team_variance']:.3f} / {pred['between_team_mean_variance']:.3f}; {between_gap:+.3f} [{between_ci[0]:+.3f}, {between_ci[1]:+.3f}] | {obs['within_team_game_variance']:.3f} / {pred['within_team_forecast_mean_variance'] + pred['within_game_predictive_variance']:.3f}; {pred['observed_within_minus_predicted_within_total']:+.3f} [{ci[0]:+.3f}, {ci[1]:+.3f}] |")
    lines += [
        "",
        "The forecast marginal SD includes game-to-game changes in expected counts as well as each game's simulated spread. The two variance columns show that V3 captures little observed team-to-team rate variation for attempts (forecast 1.97 vs observed 18.84) or SOG (0.69 vs 7.16), and it also misses within-team game spread. The within-team residual gap removes forecast-mean movement and compares observed variation with simulation variance. SOG covers 1,292 games (official SOG disposition ACCEPT); attempts and goals cover all 1,312.",
        "",
        "| Count | Effective within-team NB2 alpha (95% clustered CI) | Generator-implied NB2 alpha | Extra alpha beyond generator (95% clustered CI) | 50/80/90% coverage |",
        "|---|---:|---:|---:|---:|",
    ]
    for key, label in (("attempts", "Attempts"), ("sog", "Official SOG"), ("goals", "Goals")):
        x = d[key]
        nb = x["within_team_negative_binomial"]
        obs_ci = nb["cluster_bootstrap_95_ci"]["effective_nb2_alpha"]
        extra_ci = nb["cluster_bootstrap_95_ci"]["extra_nb2_alpha"]
        cov = baseline[key]["central_interval_coverage"]
        covs = "/".join(_pct(cov[k]["observed"]) for k in ("50", "80", "90"))
        lines.append(f"| {label} | {nb['effective_observed_nb2_alpha_signed']:+.5f} [{obs_ci[0]:+.5f}, {obs_ci[1]:+.5f}] | {nb['simulator_implied_nb2_alpha_signed']:+.5f} | {nb['extra_nb2_alpha_over_simulator_signed']:+.5f} [{extra_ci[0]:+.5f}, {extra_ci[1]:+.5f}] | {covs} |")
    lines += [
        "",
        "The NB2 column uses a team fixed-effect variance decomposition. For NB2 Var=mu+alpha*mu^2, effective alpha subtracts forecast-mean movement and the Poisson mean from observed within-team variance; extra alpha over the generator instead subtracts the simulator's conditional variance. Alpha is signed for diagnosis, not constrained into a fitted replacement model. A single observed count per team-game cannot distinguish latent tempo variation from omitted predictors or misspecified means; cluster intervals account for paired teams within a game. The separate uncentered residual moment is retained in JSON as a sensitivity check and is confounded by mean misspecification.",
        "",
        "## Where the scoring difference enters",
        "",
    ]
    conv = result["development"]["baseline_diagnostics"]["shooting_percentage"]
    events = result["development"]["event_level_diagnostics"]["Phase 2A"]
    lines += [
        f"Accepted PBP conversion was {conv['observed_pbp_goal_per_pbp_sog']:.4%} goals per on-target event. V3 generated {conv['predicted_generated_goal_per_generated_sog']:.4%}; evaluated at the actual accepted shot locations and states, its conditional conversion was {events['predicted_goal_per_sog_at_observed_locations']:.4%}, versus observed {events['observed_goal_per_sog']:.4%}. This points away from a simple globally too-high per-shot probability: the generator's mixture of shot opportunities, strengths, and states changes the aggregate conversion. The observed-location estimate is slightly low, while the generated mixture is high.",
        "",
        "| Stage | Observed / generated | 95% game-cluster interval |",
        "|---|---:|---:|",
    ]
    stage = data["scoring_and_game_state_diagnostics"]["shot_stage_probabilities"]
    shotpct = data["scoring_and_game_state_diagnostics"]["shooting_percentage"]
    lines.append(f"| SOG per attempt | {stage['observed_pbp_sog_per_attempt']:.4%} / {stage['generated_sog_per_attempt']:.4%} | observed [{stage['cluster_bootstrap_95_ci']['observed'][0]:.4%}, {stage['cluster_bootstrap_95_ci']['observed'][1]:.4%}]; generated [{stage['cluster_bootstrap_95_ci']['generated'][0]:.4%}, {stage['cluster_bootstrap_95_ci']['generated'][1]:.4%}] |")
    lines.append(f"| Goals per on-target event | {shotpct['observed_pbp_goals_per_pbp_sog']:.4%} / {shotpct['generated_goals_per_generated_sog']:.4%} | observed [{shotpct['cluster_bootstrap_95_ci']['observed'][0]:.4%}, {shotpct['cluster_bootstrap_95_ci']['observed'][1]:.4%}]; generated [{shotpct['cluster_bootstrap_95_ci']['generated'][0]:.4%}, {shotpct['cluster_bootstrap_95_ci']['generated'][1]:.4%}] |")
    lines += [
        "",
        f"The attempt-to-SOG step is lower in the generated mixture ({stage['generated_sog_per_attempt']:.4%} vs {stage['observed_pbp_sog_per_attempt']:.4%}); the larger scoring divergence is goals per generated SOG. The generated joint distance-angle-shot-type distribution has total-variation distance {comp['location_composition']['joint_distance_angle_type_total_variation']:.4f} from observed accepted events. The mismatch between 9.268% expected goal probability at observed locations and 11.045% in the generated mixture shows that the sampled opportunity/state mixture compounds across a game.",
        "",
        "| Strength | Attempts observed / generated per game | Goals observed / generated per game | Goal error, generated - observed |",
        "|---|---:|---:|---:|",
    ]
    for strength in ("EVEN", "ADVANTAGE", "DISADVANTAGE", "EMPTY_NET"):
        x = data["strength_composition"][strength]
        lines.append(f"| {strength} | {x['observed_attempts_per_game']:.3f} / {x['generated_attempts_per_game']:.3f} | {x['observed_goals_per_game']:.3f} / {x['generated_goals_per_game']:.3f} | {x['goal_gap_generated_minus_observed']:+.3f} |")
    lines += [
        "",
        "Even-strength goals are the largest component error (+1.177/game). The missing empty-net category (-0.363) and advantage-goal shortfall (-0.167) offset part of it; disadvantage goals are close. Penalty under-generation shifts some attempts away from advantage and toward EVEN, but these component differences do not identify a causal allocation.",
        "",
        "| Game-state count | Observed / generated | Difference (observed - generated; 95% clustered CI) |",
        "|---|---:|---:|",
    ]
    states = data["scoring_and_game_state_diagnostics"]["game_state_rates"]
    for key, label in (("penalties_per_game", "Accepted penalties per game"),
                       ("overtime_game_probability", "Games reaching OT"),
                       ("shootout_game_probability", "Games reaching shootout")):
        x = states[key]
        observed, generated = x["observed"], x["generated"]
        if key != "penalties_per_game":
            observed *= 1312
            generated *= 1312
        ci = x["difference_cluster_bootstrap_95_ci"]
        scale = 1312 if key != "penalties_per_game" else 1
        lines.append(f"| {label} | {observed:.1f} / {generated:.1f} | {x['observed_minus_generated'] * scale:+.1f} [{ci[0] * scale:+.1f}, {ci[1] * scale:+.1f}] |")
    conditional_rates = data["structural_conditional_rates"]
    lines += [
        "",
        f"Conditional on OT, generated goals were {conditional_rates['generated_ot_goals_per_ot_game']:.3f} per game reaching OT, close to {conditional_rates['observed_ot_goals_per_ot_game']:.3f} observed. Shootouts followed {conditional_rates['generated_shootouts_per_ot_game']:.1%} of generated OT games and {conditional_rates['observed_shootouts_per_ot_game']:.1%} of observed OT games. The lower totals therefore mostly track fewer OT entries, not missing OT or shootout branches.",
        "",
        "| Team-pair count | Observed home-away covariance / correlation | Generated-mixture covariance / correlation |",
        "|---|---:|---:|",
    ]
    for key, label in (("attempts", "Attempts"), ("sog", "Official SOG"), ("goals", "Goals")):
        pair = data["paired_home_away_count_covariance"][key]
        cov_ci = pair["cluster_bootstrap_95_ci"]["covariance"]
        lines.append(f"| {label} | {pair['observed_covariance']:+.3f} / {pair['observed_correlation']:+.3f} (covariance CI [{cov_ci['observed'][0]:+.3f}, {cov_ci['observed'][1]:+.3f}]) | {pair['generated_mixture_covariance']:+.3f} / {pair['generated_mixture_correlation']:+.3f} (covariance CI [{cov_ci['generated'][0]:+.3f}, {cov_ci['generated'][1]:+.3f}]) |")
    lines += [
        "",
        "Observed opponent shot counts are much more negatively associated than the generator's paired draws. A single shared positive game-tempo multiplier could therefore move dependence in the wrong direction; Phase 2C should separate total-game pace from within-game team shot share.",
        "",
        "## Penalty association and possible spread contribution",
        "",
        "The projection below uses accepted penalty events per game and team fixed effects. It is associational: game pace, score state, and penalties affect one another, so it is not a causal effect. The variance increment is the linear projection of the difference in observed versus generated within-team penalty spread onto counts.",
        "",
        "| Count | Slope per additional penalty (95% CI) | Partial R² | Projected count change from +2.500 penalties/game | Variance increment (95% CI) | Fraction of within-team spread gap |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for key, label in (("attempts", "Attempts"), ("sog", "Official SOG")):
        x = p[key]
        beta_ci = x["cluster_bootstrap_95_ci"]["beta"]
        increment_ci = x["cluster_bootstrap_95_ci"]["projected_variance_increment"]
        frac = x["fraction_of_within_team_variance_gap_projected"]
        lines.append(f"| {label} | {x['team_fixed_effect_linear_projection_beta_per_extra_accepted_penalty']:+.4f} [{beta_ci[0]:+.4f}, {beta_ci[1]:+.4f}] | {x['within_team_partial_r_squared']:.4f} | {x['projected_attempt_or_sog_change_per_team_game_from_mean_gap']:+.3f} | {x['projected_variance_increment_from_penalty_spread_gap']:.3f} [{increment_ci[0]:.3f}, {increment_ci[1]:.3f}] | {'n/a' if frac is None else f'{frac:.1%}'} |")
    lines += [
        "",
        "These estimates quantify association and cannot establish how many missing attempts or SOG are caused by the penalty process. Their intervals and raw inputs are in `underdispersion.json`.",
        "",
        "On this projection, the 2.5/game penalty-rate gap accounts for effectively 0.000 attempt variance units and 0.011 SOG variance units (0.2% of the SOG within-team gap); the slopes' intervals include zero. It does not explain the shot-volume under-dispersion, though it remains relevant to strength allocation and scoring.",
        "",
        "## Scoring and final margin",
        "",
        f"Goal central coverage is {baseline['goals']['central_interval_coverage']['50']['observed']:.3f}/{baseline['goals']['central_interval_coverage']['80']['observed']:.3f}/{baseline['goals']['central_interval_coverage']['90']['observed']:.3f}: the 50% interval is a little wide, while 80% and 90% are close to nominal. Forecast within-team goal variation (3.304) exceeds observed (2.975), so goals do not need extra spread in this fold; the forecast mean remains high by 0.328 goals/team-game. This coverage does not establish shot-process calibration. Final-score margin observed mean/variance is {data['final_score_margin']['observed_mean']:.3f}/{data['final_score_margin']['observed_variance']:.3f}; generated mean/full marginal variance are {data['final_score_margin']['predicted_mean']:.3f}/{data['final_score_margin']['predicted_marginal_variance']:.3f}, with within-game variance {data['final_score_margin']['predicted_mean_within_game_variance']:.3f}. Clustered intervals are in `underdispersion.json`.",
        "",
        "## Structural omission inventory",
        "",
        "The rank is by relevance to the +1.177/game generated EVEN-goal excess. Direct component gaps are not causal decompositions; positive and negative errors offset.",
        "",
        "| Rank | Component and measured gap | Classification and frozen-code location | Relation to EVEN-goal excess |",
        "|---:|---|---|---|",
        "| 1 | EVEN goals: generated 5.565 vs observed 4.389/game (+1.177) | Scoring mixture error, not a category absence. | Largest measured scoring error. The per-shot model at observed locations is low, so altered simulated composition/state and its compounding matter. |",
        "| 2 | Empty-net goals: generated 0.000 vs observed 0.363/game; empty-net attempts 0 vs 0.695/game | Hard structural absence: generator `_GameBuilder._strength` in `stochastic_model.py:411-414` only returns EVEN or advantage/disadvantage; no goalie-pull state. Replay classification can identify EMPTY_NET at `stochastic_model.py:146-155`. | Missing goals offset the EVEN overprediction in total goals; they do not explain it. |",
        "| 3 | Accepted penalties: generated 4.890 vs observed 7.390/game (−2.500) | Fitted-rate shortfall plus structural restriction: `simulate_game` at `stochastic_model.py:491-545` permits one minor at a time, suppresses calls in the final 120 seconds of a period, and ends penalties with the simplified even-strength reset. | Observed advantage attempts/goals exceed generated; the missing special-teams share is consistent with excess EVEN exposure. Projection above is noncausal. |",
        "| 4 | OT goals: generated 0.102 vs observed 0.142/game (−0.040); OT game frequency 212.1 vs 288 expected/games | No hard absence: `simulate_game` at `stochastic_model.py:551-580` has 5-minute sudden-death OT. Frequency is short, largely downstream of the simulated regulation score/tie rate; per-OT goal rates are similar. | OT goals are classified EVEN and their shortfall slightly offsets EVEN excess. |",
        "| 5 | Shootout games: 77.8 expected vs 102 observed | No hard absence: `_simulate_shootout` at `stochastic_model.py:626-678` generates shootouts after a tied OT. Conditional on generated/observed OT, the shootout rates are similar; lower count follows fewer OT entries. | Affects final winner/final-score convention, not reg+OT goal CRPS. |",
        "| 6 | Evaluation window: both observed and forecast populations are the same 1,312 2021 development games; 2022 is not used here | No evaluation-window mismatch. | Cannot explain the measured error. |",
        "",
        "The generator has exponential event times (`stochastic_model.py:488`, and `:566` in OT) with deterministic fitted rates and no shared game-level latent tempo. Team-to-team rate dispersion is also underpredicted, so a game-level random effect alone would not address all the missing spread. Penalties explain the special-teams exposure shift, but the fixed-effect projection accounts for almost none of total attempt/SOG variance shortfall.",
        "",
        "## Stored-prediction variance-only sensitivity (descriptive-after-selection)",
        "",
        "| Stored 2021 metric | Phase 2A | C v2 goal prior | C paired delta, baseline minus candidate (95% CI) |",
        "|---|---:|---:|---:|",
    ]
    stored = data["stored_candidate_comparison"]
    for key, label in (("reg_ot_team_goal_crps", "Goal CRPS"),
                       ("final_score_energy_score", "Final-score energy"),
                       ("winner_brier", "Winner Brier"), ("team_sog_crps", "Team SOG CRPS")):
        delta_key = {"reg_ot_team_goal_crps": "goal_crps",
                     "final_score_energy_score": "final_score_energy",
                     "winner_brier": "winner_brier", "team_sog_crps": "team_sog_crps"}[key]
        delta = stored["paired_c_minus_phase2a_baseline_minus_candidate"][delta_key]
        ci = delta["paired_game_bootstrap_ci95"]
        lines.append(f"| {label} | {stored['phase2a'][key]:.4f} | {stored['candidate_c'][key]:.4f} | {delta['mean_delta']:+.4f} [{ci[0]:+.4f}, {ci[1]:+.4f}] |")
    lines += [
        "",
        f"A common NB2 alpha was estimated by moments while holding each stored per-team-game forecast mean fixed; it landed at {c['common_nb2_alpha_fitted_from_phase2a_2021_outcomes_at_fixed_forecast_means']:.4f} (the Poisson boundary). Replacing the empirical 16-draw goal distributions with that Poisson/NB2 distribution keeps forecast means unchanged and expands the generator's below-Poisson conditional spread, but does not improve the pooled goal-variance diagnosis: the full generated marginal goal variance is already 3.315 against 3.154 observed, and 50% intervals cover 62.3%. This is descriptive-after-selection, not a candidate or adoption result. Raw C goal-CRPS gain was {c['raw_c_gain_vs_phase2a']:.4f} (original Phase 2B paired 95% CI +0.0357 to +0.0697); Poisson recalibration yielded {c['nb2_recalibrated_c_gain_vs_phase2a']:.4f} (fixed-alpha clustered interval {c['nb2_recalibrated_c_gain_cluster_bootstrap_95_ci_alpha_fixed'][0]:.4f} to {c['nb2_recalibrated_c_gain_cluster_bootstrap_95_ci_alpha_fixed'][1]:.4f}), a change of {c['change_in_c_gain_after_recalibration']:+.4f}. The bootstrap holds alpha fixed, and all these scores reuse the 2021 selection population; neither supports adoption.",
        "",
        "## Reproduction and runtime",
        "",
        "The seeded simulator was not rerun. The exact Phase 2A and C cache traces were reused after checking cache fingerprint, candidate name, 1,312 games, 16 simulations/game, and zero accounting failures. The 1,510,104-row pinned event ledger was rescanned and reconciled to Phase 2B per-game goals; the compact trace snapshot is committed so the calculations and bootstrap can be rerun without the transient cache.",
        "",
        "```sh",
        "/root/legendarypicks/backend/venv/bin/python research/nhl/nhl-v3-phase2b-scoring-2026-10-21/underdispersion.py --build-snapshot --rescan-source --cache-dir /tmp/nhl-v3-phase2b-cache-7d5a1e6d4487a74a",
        "/root/legendarypicks/backend/venv/bin/python research/nhl/nhl-v3-phase2b-scoring-2026-10-21/underdispersion.py --analyze --bootstrap-replicates 2000",
        "```",
        "",
        f"The fresh pinned event-ledger scan took {data['cache']['event_scan_seconds']:.2f} seconds; full snapshot-build command took {data['cache']['snapshot_build_seconds']:.2f} seconds; analysis/bootstrap took {data['analysis_runtime_seconds']:.2f} seconds. Bootstrap: {data['bootstrap']['replicates']} game-cluster resamples, seed {data['bootstrap']['seed']}.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-snapshot", action="store_true")
    parser.add_argument("--analyze", action="store_true")
    parser.add_argument("--rescan-source", action="store_true",
                        help="force a fresh full pinned event-ledger scan when building the snapshot")
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    parser.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    parser.add_argument("--bootstrap-replicates", type=int, default=BOOTSTRAP_REPLICATES)
    args = parser.parse_args()
    if args.build_snapshot == args.analyze:
        parser.error("select exactly one of --build-snapshot or --analyze")
    if args.build_snapshot:
        print(json.dumps(build_snapshot(args.cache_dir, rescan_source=args.rescan_source),
                         sort_keys=True, indent=2))
        return
    data = analyze(args.snapshot, args.bootstrap_replicates)
    OUTPUT_JSON.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    OUTPUT_MD.write_text(render_report(data, read_results()), encoding="utf-8")
    print(json.dumps({"json": str(OUTPUT_JSON), "report": str(OUTPUT_MD),
                      "analysis_runtime_seconds": data["analysis_runtime_seconds"],
                      "snapshot_sha256": data["input_snapshot"]["sha256"]}, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
