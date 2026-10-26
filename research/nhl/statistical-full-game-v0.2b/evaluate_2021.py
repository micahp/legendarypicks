#!/usr/bin/env python3
"""Run the frozen paired 2021 NHL v0.2b development evaluation.

The evaluator constructs archive-only pregame inputs in date order, generates
all forecasts for a target date before opening that date's boxscores for history,
and writes resumable per-game diagnostics outside the repository by default.
"""

from __future__ import annotations

import argparse
import bisect
import collections
import copy
import functools
import hashlib
import importlib.util
import json
import math
import os
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUTPUT_VERSION = "nhl-statistical-full-game-v0.2b-2021-development-v1"
PREREG_COMMIT = "c9e38b4d"
MC_DRAWS = 12
BOOTSTRAP_REPETITIONS = 2000
BOOTSTRAP_SEED = 202610250004
V01_DRAWS = 10_000
V01_SEED = 202611000001
RATE_DRAWS = 10_000
RATE_SEED_BASE = 202612000001
V01_ENERGY_PAIRS = 200_000
V01_ENERGY_SEED = 202614000001
RATE_ENERGY_PAIRS = 20_000
RATE_ENERGY_SEED_BASE = 202615000001
V01_HALF_ENERGY_PAIRS = 100_000
V01_HALF_ENERGY_SEEDS = (202616000001, 202617000001)
RATE_HALF_ENERGY_PAIRS = 20_000
RATE_HALF_ENERGY_SEED_BASES = (202618000001, 202619000001)
MEMORY_FLOOR_BYTES = int(1.5 * 1024**3)
COUNT_FAMILIES = ("faceoff", "shot", "giveaway", "takeaway", "penalty", "hit", "stoppage")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _available_ram() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise RuntimeError("cannot read MemAvailable from /proc/meminfo")


def _json_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                  ensure_ascii=False).encode()).hexdigest()


@functools.lru_cache(maxsize=1024)
def _poisson_cdf(mean: float) -> tuple[float, ...]:
    if not math.isfinite(mean) or mean < 0:
        raise ValueError(f"invalid Poisson mean {mean}")
    if mean == 0:
        return (1.0,)
    probability = math.exp(-mean)
    cumulative = probability
    values = [cumulative]
    count = 0
    while cumulative < 1.0 - 1e-15:
        count += 1
        probability *= mean / count
        cumulative = min(1.0, cumulative + probability)
        values.append(cumulative)
        if count > 10_000:
            raise ValueError(f"Poisson CDF did not converge for mean {mean}")
    values[-1] = 1.0
    return tuple(values)


def _poisson(rng: random.Random, mean: float) -> int:
    cdf = _poisson_cdf(float(mean))
    return bisect.bisect_left(cdf, rng.random())


def _rate_reference(inputs: Any, seed: int, draws: int) -> list[dict[str, Any]]:
    """Independent Poisson team-goal/SOG reference; not a game-process simulator."""
    rng = random.Random(seed)
    result = []
    for _ in range(draws):
        home_reg_ot = _poisson(rng, inputs.mu_home)
        away_reg_ot = _poisson(rng, inputs.mu_away)
        home_final, away_final = home_reg_ot, away_reg_ot
        if home_final == away_final:
            if rng.random() < .5:
                home_final += 1
            else:
                away_final += 1
        result.append({
            "reg_home": home_reg_ot, "reg_away": away_reg_ot,
            "final_home": home_final, "final_away": away_final,
            "sog_home": _poisson(rng, float(inputs.snapshot["team_expected_sog"]["home"])),
            "sog_away": _poisson(rng, float(inputs.snapshot["team_expected_sog"]["away"])),
            "attempts": None, "penalties": None, "overtime": None, "shootout": None,
            "family_counts": {}, "strength_counts": {}, "diagnostics": {},
        })
    return result


def _v01_samples(corpus: Any, draws: int, seed: int) -> list[dict[str, Any]]:
    reg_refs = {period: [(game, game.periods[("REG", period)])
                         for game in corpus.games.values()
                         if corpus.games[game.game_id].eligible and ("REG", period) in game.periods]
                for period in (1, 2, 3)}
    ot_refs = [(game, game.periods[("OT", 4)]) for game in corpus.games.values()
               if game.eligible and ("OT", 4) in game.periods]
    if any(not values for values in reg_refs.values()) or not ot_refs:
        raise ValueError("v0.1 training pool lacks required REG/OT templates")
    rng = random.Random(seed)
    output = []
    for _ in range(draws):
        draw = _V01._aggregate_game(rng, corpus, reg_refs, ot_refs)
        event_counts = draw["event_counts"]
        family_counts = collections.Counter()
        for event_type, count in event_counts.items():
            family = _SIM._transition_family(str(event_type))
            if family is not None:
                family_counts[family] += int(count)
        attempts = sum(int(event_counts.get(key, 0)) for key in
                       ("goal", "shot-on-goal", "missed-shot", "blocked-shot", "failed-shot-attempt"))
        output.append({
            "reg_home": int(draw["reg_ot_score"]["home"]),
            "reg_away": int(draw["reg_ot_score"]["away"]),
            "final_home": int(draw["final_score"]["home"]),
            "final_away": int(draw["final_score"]["away"]),
            "sog_home": int(draw["home_sog_events"]),
            "sog_away": int(draw["away_sog_events"]),
            "attempts": attempts,
            "penalties": int(event_counts.get("penalty", 0)),
            "overtime": int(any(ref["period_type"] == "OT" for ref in draw["donor_refs"])),
            "shootout": int(draw["shootout_winner"] is not None),
            "family_counts": dict(family_counts), "strength_counts": {}, "diagnostics": {},
        })
    return output


def _candidate_sample(game: dict[str, Any], sim: Any) -> dict[str, Any]:
    summary = game["summary"]
    team = summary["team_totals"]
    event_counts = collections.Counter(event["event_type"] for event in game["events"]
                                       if event["period_type"] in {"REG", "OT"})
    family_counts = collections.Counter()
    strength_counts = collections.Counter()
    for event in game["events"]:
        if event["period_type"] not in {"REG", "OT"}:
            continue
        family = sim._transition_family(str(event["event_type"]))
        if family is not None:
            family_counts[family] += 1
        strength = event.get("strength")
        if strength:
            strength_counts[str(strength)] += 1
    diagnostics = summary.get("event_transition_diagnostics") or {}
    return {
        "reg_home": int(summary["regulation_overtime_score"]["home"]),
        "reg_away": int(summary["regulation_overtime_score"]["away"]),
        "final_home": int(summary["official_final_score"]["home"]),
        "final_away": int(summary["official_final_score"]["away"]),
        "sog_home": int(summary["sog_event_counts"]["home"]),
        "sog_away": int(summary["sog_event_counts"]["away"]),
        "attempts": int(sum(row["shot_attempts"] for row in team.values())),
        "penalties": int(sum(row["penalties"] for row in team.values())),
        "overtime": int(any(event["period_type"] == "OT" for event in game["events"])),
        "shootout": int(summary["shootout_winner"] is not None),
        "family_counts": dict(family_counts), "strength_counts": dict(strength_counts),
        "diagnostics": {
            "family_fallback_levels": diagnostics.get("family_fallback_levels", {}),
            "owner_fallback_levels": diagnostics.get("owner_fallback_levels", {}),
            "unsupported_penalty_omissions": int(summary.get("unsupported_penalty_omissions", 0)),
            "donor_quarantine": game.get("provenance", {}).get("donor_period_quarantine", {}),
            "accepted_shift_rows_quarantined": sum(int(block.get("shift_rows_quarantined", 0))
                for block in game.get("provenance", {}).get("sampled_period_templates", [])),
        },
    }


def _observed_sample(game: Any, pbp: dict[str, Any], sim: Any) -> dict[str, Any]:
    family_counts = collections.Counter()
    strength_counts = collections.Counter()
    attempts = penalties = 0
    attempt_events = {"goal", "shot-on-goal", "missed-shot", "blocked-shot", "failed-shot-attempt"}
    for event in pbp.get("plays", []):
        descriptor = event.get("periodDescriptor") or {}
        period_type = descriptor.get("periodType")
        if period_type not in {"REG", "OT"}:
            continue
        event_type = str(event.get("typeDescKey") or "")
        family = sim._transition_family(event_type)
        if family is not None:
            family_counts[family] += 1
        attempts += int(event_type in attempt_events)
        penalties += int(event_type == "penalty")
        code = str(event.get("situationCode") or "")
        if len(code) == 4 and code.isdigit():
            away_skaters, home_skaters = int(code[1]), int(code[2])
            strength_counts[f"{home_skaters}v{away_skaters}"] += 1
    return {
        "reg_home": int(game.reg_ot_score["home"]),
        "reg_away": int(game.reg_ot_score["away"]),
        "final_home": int(game.home_score), "final_away": int(game.away_score),
        "sog_home": int(game.home_sog), "sog_away": int(game.away_sog),
        "attempts": attempts, "penalties": penalties,
        "overtime": int(game.source_last_period_type in {"OT", "SO"}),
        "shootout": int(game.source_last_period_type == "SO"),
        "family_counts": dict(family_counts), "strength_counts": dict(strength_counts),
        "winner_home": int(game.home_score > game.away_score),
    }


def _metrics(samples: list[dict[str, Any]], observed: dict[str, Any], *,
             pair_draws: int, pair_seed: int, exact_pair: bool) -> dict[str, float]:
    if not samples:
        raise ValueError("metric distribution is empty")
    reg_h = _SIM.v01.EmpiricalDistribution([x["reg_home"] for x in samples])
    reg_a = _SIM.v01.EmpiricalDistribution([x["reg_away"] for x in samples])
    final_h = _SIM.v01.EmpiricalDistribution([x["final_home"] for x in samples])
    final_a = _SIM.v01.EmpiricalDistribution([x["final_away"] for x in samples])
    sog_h = _SIM.v01.EmpiricalDistribution([x["sog_home"] for x in samples])
    sog_a = _SIM.v01.EmpiricalDistribution([x["sog_away"] for x in samples])
    scores = [(x["final_home"], x["final_away"]) for x in samples]
    first_energy = math.fsum(math.hypot(h - observed["final_home"], a - observed["final_away"])
                             for h, a in scores) / len(scores)
    if exact_pair:
        pair = math.fsum(math.hypot(x[0] - y[0], x[1] - y[1])
                         for x in scores for y in scores) / (len(scores) * len(scores))
    else:
        if pair_draws < 1:
            raise ValueError("energy pair Monte Carlo draw count must be positive")
        rng = random.Random(pair_seed)
        total = 0.0
        n = len(scores)
        for _ in range(pair_draws):
            x = scores[rng.randrange(n)]
            y = scores[rng.randrange(n)]
            total += math.hypot(x[0] - y[0], x[1] - y[1])
        pair = total / pair_draws
    home_win_probability = sum(x["final_home"] > x["final_away"] for x in samples) / len(samples)
    return {
        "regulation_overtime_goal_crps_per_team": .5 * (
            reg_h.crps(observed["reg_home"]) + reg_a.crps(observed["reg_away"])),
        "official_final_score_crps_per_team": .5 * (
            final_h.crps(observed["final_home"]) + final_a.crps(observed["final_away"])),
        "final_score_energy": first_energy - .5 * pair,
        "winner_brier": (home_win_probability - observed["winner_home"]) ** 2,
        "sog_crps_per_team": .5 * (
            sog_h.crps(observed["sog_home"]) + sog_a.crps(observed["sog_away"])),
    }


def _pair_energy(scores: list[tuple[int, int]], draws: int, seed: int) -> float:
    if not scores or draws < 1:
        raise ValueError("energy pair estimator requires samples and positive draw count")
    rng = random.Random(seed)
    total = 0.0
    for _ in range(draws):
        left = scores[rng.randrange(len(scores))]
        right = scores[rng.randrange(len(scores))]
        total += math.hypot(left[0] - right[0], left[1] - right[1])
    return total / draws


def _sample_fields(sample: dict[str, Any]) -> dict[str, list[int]]:
    fields: dict[str, list[int]] = {
        "regulation_overtime_goals_by_team": [int(sample["reg_home"]), int(sample["reg_away"])],
        "official_final_score_by_team": [int(sample["final_home"]), int(sample["final_away"])],
        "sog_by_team": [int(sample["sog_home"]), int(sample["sog_away"])],
        "score_margin_home_minus_away": [int(sample["final_home"] - sample["final_away"])],
    }
    for name in ("attempts", "penalties", "overtime", "shootout"):
        if sample.get(name) is not None:
            fields[f"{name}_per_game"] = [int(sample[name])]
    family_counts = sample.get("family_counts") or {}
    if family_counts:
        for family in COUNT_FAMILIES:
            fields[f"event_family|{family}"] = [int(family_counts.get(family, 0))]
    strength_counts = sample.get("strength_counts") or {}
    if strength_counts:
        for home_skaters in range(3, 7):
            for away_skaters in range(3, 7):
                strength = f"{home_skaters}v{away_skaters}"
                fields[f"manpower_event_count|{strength}"] = [int(strength_counts.get(strength, 0))]
    return fields


def _histogram(samples: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    result: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for sample in samples:
        for field, values in _sample_fields(sample).items():
            for value in values:
                result[field][str(value)] += 1
    return {key: dict(sorted(counts.items(), key=lambda item: float(item[0])))
            for key, counts in sorted(result.items())}


class CountDistribution:
    def __init__(self) -> None:
        self.hist: collections.Counter[float] = collections.Counter()
        self.total = 0
        self.sum = 0.0
        self.sum_sq = 0.0

    def add(self, value: float, n: int = 1) -> None:
        value = float(value)
        self.hist[value] += n
        self.total += n
        self.sum += value * n
        self.sum_sq += value * value * n

    def summary(self) -> dict[str, float | int]:
        if self.total == 0:
            raise ValueError("cannot summarize empty count distribution")
        keys = sorted(self.hist)

        def quantile(q: float) -> float:
            rank = max(1, math.ceil(q * self.total))
            count = 0
            for value in keys:
                count += self.hist[value]
                if count >= rank:
                    return value
            return keys[-1]

        mean = self.sum / self.total
        return {"n": self.total, "mean": mean,
                "variance": max(0.0, self.sum_sq / self.total - mean * mean),
                "p10": quantile(.10), "p50": quantile(.50), "p90": quantile(.90)}


def _merge_histograms(target: dict[str, CountDistribution], source: dict[str, dict[str, int]],
                      multiplier: int = 1) -> None:
    for field, counts in source.items():
        dist = target.setdefault(field, CountDistribution())
        for value, count in counts.items():
            dist.add(float(value), int(count) * multiplier)


def _bootstrap_ci(values: list[float], seed: int) -> list[float]:
    if not values:
        raise ValueError("empty bootstrap values")
    rng = random.Random(seed)
    n = len(values)
    means = [math.fsum(values[rng.randrange(n)] for _ in range(n)) / n
             for _ in range(BOOTSTRAP_REPETITIONS)]
    means.sort()
    return [means[int(.025 * (len(means) - 1))], means[int(.975 * (len(means) - 1))]]


def _bootstrap_difference(candidate: list[float], comparator: list[float], seed: int) -> list[float]:
    if len(candidate) != len(comparator) or not candidate:
        raise ValueError("paired bootstrap arrays differ or are empty")
    differences = [left - right for left, right in zip(candidate, comparator)]
    return _bootstrap_ci(differences, seed)


def _summarize_metrics(records: list[dict[str, Any]], model_names: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    metric_names = ("regulation_overtime_goal_crps_per_team", "official_final_score_crps_per_team",
                    "final_score_energy", "winner_brier", "sog_crps_per_team")
    per_model: dict[str, Any] = {}
    metric_rows: dict[str, dict[str, dict[str, float]]] = {}
    for model in model_names:
        available = [record for record in records if model in record.get("metrics", {})]
        metric_rows[model] = {}
        for metric in metric_names:
            values = [float(record["metrics"][model][metric]) for record in available]
            if not values:
                continue
            metric_rows[model][metric] = {str(record["game_index"]): float(record["metrics"][model][metric])
                                          for record in available}
            per_model.setdefault(model, {})[metric] = {
                "mean": statistics.fmean(values), "ci95_game_bootstrap": _bootstrap_ci(values,
                    BOOTSTRAP_SEED),
                "n_games": len(values), "eligible_games": len(records),
                "coverage": len(values) / len(records),
                "complete_eligible_population": len(values) == len(records),
            }

    comparators = {"B0_alpha2": ["v0.1", "historical_rate"],
                   "B1": ["B0_alpha2", "v0.1", "historical_rate"],
                   "B2": ["B0_alpha2", "v0.1", "historical_rate"]}
    differences: dict[str, Any] = {}
    for model, refs in comparators.items():
        for ref in refs:
            common = [record for record in records
                      if model in record.get("metrics", {}) and ref in record.get("metrics", {})]
            pair_name = f"{model}_minus_{ref}"
            differences[pair_name] = {"n_paired_games": len(common),
                "eligible_games": len(records), "complete_eligible_population": len(common) == len(records),
                "metrics": {}}
            for metric in metric_names:
                left = [float(record["metrics"][model][metric]) for record in common]
                right = [float(record["metrics"][ref][metric]) for record in common]
                if not left:
                    continue
                differences[pair_name]["metrics"][metric] = {
                    "mean_paired_difference": statistics.fmean(a - b for a, b in zip(left, right)),
                    "ci95_paired_game_bootstrap": _bootstrap_difference(left, right,
                        BOOTSTRAP_SEED),
                    "negative_favors_candidate": True,
                }
    return per_model, differences


def _load_checkpoint(path: Path, expected_meta: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    data = path.read_bytes()
    lines = data.splitlines(keepends=True)
    parsed: list[dict[str, Any]] = []
    valid_bytes = 0
    for index, line in enumerate(lines):
        try:
            parsed.append(json.loads(line))
            valid_bytes += len(line)
        except json.JSONDecodeError:
            if index != len(lines) - 1:
                raise ValueError(f"checkpoint has malformed non-final row {index + 1}")
            break
    if valid_bytes != len(data):
        path.write_bytes(data[:valid_bytes])
    if not parsed or parsed[0].get("kind") != "meta" or parsed[0].get("meta") != expected_meta:
        raise ValueError("checkpoint metadata does not match frozen evaluation configuration")
    results = {}
    for row in parsed[1:]:
        key = str(row["game_key"])
        if key in results:
            raise ValueError(f"duplicate target in evaluation checkpoint: {key}")
        results[key] = row
    return results


def _append_checkpoint(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path,
                        default=Path("/tmp/nhl-v02b-2021-eval-12draws.jsonl"))
    parser.add_argument("--output", type=Path,
                        default=HERE / "results/2021-paired-evaluation-v1.json")
    parser.add_argument("--progress-every", type=int, default=4)
    args = parser.parse_args()
    if args.progress_every < 1:
        parser.error("--progress-every must be positive")
    if _available_ram() < MEMORY_FLOOR_BYTES:
        raise RuntimeError("available RAM is below the preregistered 1.5 GiB floor")

    _SIM = _load("nhl_eval_v02b", HERE / "nhl_game_state_sim.py")
    global _V01
    _V01 = _SIM.v01
    _B0 = _load("nhl_eval_alpha2", ROOT / "research/nhl/statistical-full-game-v0.2/nhl_team_player_sim.py")
    adapter = _load("nhl_eval_historical_adapter", HERE / "historical_adapter.py")
    started = time.monotonic()
    source_start = time.monotonic()
    seasons = tuple(_SIM.v01.TRAIN_SEASONS) + tuple(_SIM.v01.DEVELOPMENT_SEASONS)
    all_corpus = _SIM.v01.load_corpus(_SIM.v01.DEFAULT_DATA_ROOT, seasons)
    manifest = adapter.load_boxscore_manifest(_SIM.v01)
    targets = sorted((game for game in all_corpus.games.values()
                      if game.start_season == 2021 and _SIM.v01._eligible_game(game)),
                     key=lambda game: (manifest[str(game.game_id)]["game_date"],
                                       game.game_id))
    if len(targets) != 1292:
        raise ValueError(f"eligible 2021 target count changed: {len(targets)}")
    train_corpus = copy.copy(all_corpus)
    train_corpus.games = {key: game for key, game in all_corpus.games.items()
                          if game.start_season in _SIM.v01.TRAIN_SEASONS and
                          _SIM.v01._eligible_game(game)}
    expected_training = sum(all_corpus.eligible_by_season[y] for y in _SIM.v01.TRAIN_SEASONS)
    if len(train_corpus.games) != expected_training:
        raise ValueError("training donor corpus failed frozen 2019/2020 eligibility")
    shift_manifest = _SIM.load_shift_manifest()
    b0_quality = _B0.fit_shot_quality(train_corpus)
    b1_quality = _SIM.fit_shot_quality(train_corpus)
    transition_model = _SIM.fit_event_transition_model(train_corpus)
    v01_draws = _v01_samples(train_corpus, V01_DRAWS, V01_SEED)
    source_prep_seconds = time.monotonic() - source_start
    v01_histogram = _histogram(v01_draws)
    v01_scores = [(sample["final_home"], sample["final_away"]) for sample in v01_draws]
    v01_pair = _pair_energy(v01_scores, V01_ENERGY_PAIRS, V01_ENERGY_SEED)
    v01_halves = [v01_draws[:V01_DRAWS // 2], v01_draws[V01_DRAWS // 2:]]
    v01_half_pairs = [_pair_energy(
        [(sample["final_home"], sample["final_away"]) for sample in half],
        V01_HALF_ENERGY_PAIRS, V01_HALF_ENERGY_SEEDS[index])
        for index, half in enumerate(v01_halves)]
    v01_distributions = {name: _V01.EmpiricalDistribution([sample[key] for sample in v01_draws])
        for name, key in (("reg_home", "reg_home"), ("reg_away", "reg_away"),
                          ("final_home", "final_home"), ("final_away", "final_away"),
                          ("sog_home", "sog_home"), ("sog_away", "sog_away"))}
    v01_half_distributions = [{name: _V01.EmpiricalDistribution([sample[key] for sample in half])
        for name, key in (("reg_home", "reg_home"), ("reg_away", "reg_away"),
                          ("final_home", "final_home"), ("final_away", "final_away"),
                          ("sog_home", "sog_home"), ("sog_away", "sog_away"))}
        for half in v01_halves]

    expected_meta = {"output_version": OUTPUT_VERSION, "prereg_commit": PREREG_COMMIT,
        "eligible_target_games": len(targets), "mc_draws_per_candidate": MC_DRAWS,
        "v01_draws": V01_DRAWS, "historical_rate_draws_per_target": RATE_DRAWS,
        "bootstrap_repetitions": BOOTSTRAP_REPETITIONS,
        "pbp_manifest_sha256": _SIM.v01.EXPECTED_MANIFEST_SHA256,
        "boxscore_manifest_sha256": _SIM.v01.EXPECTED_BOXSCORE_MANIFEST_SHA256,
        "shift_manifest_sha256": _SIM.SHIFT_MANIFEST_SHA256,
        "seed_mapping": "Amendment 5",
        "seed_configuration": {"candidate_base": 202610250001, "candidate_game_stride": 100,
            "v01": V01_SEED, "historical_rate_base": RATE_SEED_BASE,
            "historical_rate_game_stride": 100, "game_bootstrap": BOOTSTRAP_SEED,
            "v01_energy": V01_ENERGY_SEED, "historical_rate_energy_base": RATE_ENERGY_SEED_BASE,
            "v01_half_energy": list(V01_HALF_ENERGY_SEEDS),
            "historical_rate_half_energy_bases": list(RATE_HALF_ENERGY_SEED_BASES)},
        "source_sha256": {
            "evaluator": _SIM.sha256_file(Path(__file__).resolve()),
            "candidate_simulator": _SIM.sha256_file(HERE / "nhl_game_state_sim.py"),
            "game_state_rules": _SIM.sha256_file(HERE / "game_state.py"),
            "historical_adapter": _SIM.sha256_file(HERE / "historical_adapter.py"),
            "alpha2_simulator": _SIM.sha256_file(ROOT / "research/nhl/statistical-full-game-v0.2/nhl_team_player_sim.py"),
            "v01_simulator": _SIM.sha256_file(Path(_V01.__file__).resolve())},
        "database_used_for_2021_inputs": False}
    checkpoint = _load_checkpoint(args.checkpoint, expected_meta)
    if not checkpoint and args.checkpoint.exists() and args.checkpoint.stat().st_size == 0:
        args.checkpoint.unlink()
    if not args.checkpoint.exists():
        args.checkpoint.parent.mkdir(parents=True, exist_ok=True)
        args.checkpoint.write_text(json.dumps({"kind": "meta", "meta": expected_meta},
                                              sort_keys=True) + "\n", encoding="utf-8")

    game_index = {str(game.game_id): index for index, game in enumerate(targets)}
    target_days = adapter.eligible_history_days(all_corpus, manifest, seasons)
    history = adapter.ForwardOnlyHistory()
    processed = 0

    for game_date, games in target_days.items():
        dev_games = [game for game in games if game.start_season == 2021]
        day_prepared: list[tuple[Any, dict[str, Any], Any | None, str | None]] = []
        # Snapshot construction for the whole date precedes any same-day result update.
        for game in dev_games:
            row = manifest[str(game.game_id)]
            try:
                inputs = history.make_inputs(sim=_SIM, game_key=str(game.game_id), game_date=game_date,
                    home=str(row["canonical_home_team"]), away=str(row["canonical_away_team"]))
                input_error = None
            except Exception as exc:
                inputs = None
                input_error = f"{type(exc).__name__}: {exc}"
            day_prepared.append((game, row, inputs, input_error))

        pending: list[tuple[Any, dict[str, Any], Any | None, dict[str, Any],
                            dict[str, list[dict[str, Any]]], list[dict[str, Any]] | None]] = []
        # Phase 1: generate every forecast for the date without reading any target
        # outcome or target boxscore body.
        for game, row, inputs, input_error in day_prepared:
            game_key = str(game.game_id)
            index = game_index[game_key]
            if _available_ram() < MEMORY_FLOOR_BYTES:
                raise RuntimeError(f"available RAM fell below 1.5 GiB at target {game_key}")
            if game_key in checkpoint:
                record = checkpoint[game_key]
                if record["game_date"] != game_date:
                    raise ValueError(f"checkpoint game-date mismatch for {game_key}")
                if inputs is not None and record.get("input_sha256") != _json_sha(inputs.snapshot):
                    raise ValueError(f"checkpoint pregame input changed for {game_key}")
                if inputs is None and record.get("input_error") != input_error:
                    raise ValueError(f"checkpoint input failure changed for {game_key}")
                processed += 1
                continue

            record: dict[str, Any] = {"game_key": game_key, "game_index": index,
                "game_date": game_date, "home_team": row["canonical_home_team"],
                "away_team": row["canonical_away_team"], "input_error": input_error,
                "input_sha256": _json_sha(inputs.snapshot) if inputs is not None else None,
                "metrics": {}, "split_half_metrics": {}, "prediction_histograms": {},
                "candidate_draws": {"v0.1": V01_DRAWS}, "candidate_diagnostics": {},
                "failures": {}, "runtime_seconds": {}}
            candidate_samples: dict[str, list[dict[str, Any]]] = {}
            rate_samples = None
            if inputs is None:
                reason = str(input_error)
                for name in ("B0_alpha2", "B1", "B2", "historical_rate"):
                    record["failures"][name] = reason
            else:
                model_specs = (("B0_alpha2", _B0, b0_quality, None),
                               ("B1", _SIM, b1_quality, None),
                               ("B2", _SIM, b1_quality, transition_model))
                for name, module, quality, transitions in model_specs:
                    samples = []
                    diagnostics = collections.Counter()
                    errors = []
                    elapsed_start = time.monotonic()
                    for draw in range(MC_DRAWS):
                        seed = 202610250001 + 100 * index + draw
                        try:
                            if name == "B0_alpha2":
                                generated = module.generate_game(train_corpus, inputs, seed,
                                                                shift_manifest, quality)
                            else:
                                generated = module.generate_game(train_corpus, inputs, seed,
                                    shift_manifest, quality, transitions)
                            sample = _candidate_sample(generated, _SIM)
                            samples.append(sample)
                            diag = sample["diagnostics"]
                            diagnostics["unsupported_penalty_omissions"] += diag["unsupported_penalty_omissions"]
                            diagnostics["accepted_shift_rows_quarantined"] += diag["accepted_shift_rows_quarantined"]
                            for key, value in (diag.get("family_fallback_levels") or {}).items():
                                diagnostics[f"family_fallback|{key}"] += int(value)
                            for key, value in (diag.get("owner_fallback_levels") or {}).items():
                                diagnostics[f"owner_fallback|{key}"] += int(value)
                            for key, value in ((diag.get("donor_quarantine") or {}).get("reason_counts") or {}).items():
                                diagnostics[f"donor_quarantine|{key}"] += int(value)
                        except Exception as exc:
                            errors.append(f"draw={draw} {type(exc).__name__}: {exc}")
                    record["runtime_seconds"][name] = round(time.monotonic() - elapsed_start, 3)
                    record["candidate_draws"][name] = len(samples)
                    record["candidate_diagnostics"][name] = dict(sorted(diagnostics.items()))
                    if errors:
                        record["failures"][name] = errors
                    candidate_samples[name] = samples

                rate_seed = RATE_SEED_BASE + 100 * index
                rate_start = time.monotonic()
                rate_samples = _rate_reference(inputs, rate_seed, RATE_DRAWS)
                record["runtime_seconds"]["historical_rate"] = round(time.monotonic() - rate_start, 3)
                record["candidate_draws"]["historical_rate"] = RATE_DRAWS
            pending.append((game, row, inputs, record, candidate_samples, rate_samples))

        # Phase 2: only after every same-day forecast has been generated, open
        # target PBP labels and score the frozen predictions.
        for game, row, inputs, record, candidate_samples, rate_samples in pending:
            game_key = str(game.game_id)
            index = game_index[game_key]
            observed_pbp = _SIM.read_verified_pbp_game(game, all_corpus.data_root / "raw" / "pbp")
            observed = _observed_sample(game, observed_pbp, _SIM)
            record["observed"] = observed
            for name, samples in candidate_samples.items():
                if len(samples) == MC_DRAWS and not record["failures"].get(name):
                    record["metrics"][name] = _metrics(samples, observed, pair_draws=0,
                        pair_seed=0, exact_pair=True)
                    first = _metrics(samples[:MC_DRAWS // 2], observed,
                        pair_draws=0, pair_seed=0, exact_pair=True)
                    second = _metrics(samples[MC_DRAWS // 2:], observed,
                        pair_draws=0, pair_seed=0, exact_pair=True)
                    record["split_half_metrics"][name] = {key: [first[key], second[key]]
                                                           for key in first}
                    record["prediction_histograms"][name] = _histogram(samples)
                elif name not in record["failures"]:
                    record["failures"][name] = [f"only {len(samples)}/{MC_DRAWS} draws completed"]
            if rate_samples is not None:
                rate_energy_seed = RATE_ENERGY_SEED_BASE + 100 * index
                record["metrics"]["historical_rate"] = _metrics(rate_samples, observed,
                    pair_draws=RATE_ENERGY_PAIRS, pair_seed=rate_energy_seed, exact_pair=False)
                rate_halves = [rate_samples[:RATE_DRAWS // 2], rate_samples[RATE_DRAWS // 2:]]
                split_metrics = []
                for half_index, half in enumerate(rate_halves):
                    pair_seed = RATE_HALF_ENERGY_SEED_BASES[half_index] + 100 * index
                    split_metrics.append(_metrics(half, observed, pair_draws=RATE_HALF_ENERGY_PAIRS,
                                                  pair_seed=pair_seed, exact_pair=False))
                record["split_half_metrics"]["historical_rate"] = {
                    key: [split_metrics[0][key], split_metrics[1][key]] for key in split_metrics[0]}
                record["prediction_histograms"]["historical_rate"] = _histogram(rate_samples)

            v01_first = math.fsum(math.hypot(x["final_home"] - observed["final_home"],
                x["final_away"] - observed["final_away"]) for x in v01_draws) / V01_DRAWS
            v01_hwin = sum(x["final_home"] > x["final_away"] for x in v01_draws) / V01_DRAWS
            record["metrics"]["v0.1"] = {
                "regulation_overtime_goal_crps_per_team": .5 * (
                    v01_distributions["reg_home"].crps(observed["reg_home"]) +
                    v01_distributions["reg_away"].crps(observed["reg_away"])),
                "official_final_score_crps_per_team": .5 * (
                    v01_distributions["final_home"].crps(observed["final_home"]) +
                    v01_distributions["final_away"].crps(observed["final_away"])),
                "final_score_energy": v01_first - .5 * v01_pair,
                "winner_brier": (v01_hwin - observed["winner_home"]) ** 2,
                "sog_crps_per_team": .5 * (
                    v01_distributions["sog_home"].crps(observed["sog_home"]) +
                    v01_distributions["sog_away"].crps(observed["sog_away"])),
            }
            v01_half_metrics = []
            for half_index, half in enumerate(v01_halves):
                half_first = math.fsum(math.hypot(x["final_home"] - observed["final_home"],
                    x["final_away"] - observed["final_away"]) for x in half) / len(half)
                half_hwin = sum(x["final_home"] > x["final_away"] for x in half) / len(half)
                dists = v01_half_distributions[half_index]
                v01_half_metrics.append({
                    "regulation_overtime_goal_crps_per_team": .5 * (
                        dists["reg_home"].crps(observed["reg_home"]) +
                        dists["reg_away"].crps(observed["reg_away"])),
                    "official_final_score_crps_per_team": .5 * (
                        dists["final_home"].crps(observed["final_home"]) +
                        dists["final_away"].crps(observed["final_away"])),
                    "final_score_energy": half_first - .5 * v01_half_pairs[half_index],
                    "winner_brier": (half_hwin - observed["winner_home"]) ** 2,
                    "sog_crps_per_team": .5 * (
                        dists["sog_home"].crps(observed["sog_home"]) +
                        dists["sog_away"].crps(observed["sog_away"])),
                })
            record["split_half_metrics"]["v0.1"] = {
                key: [v01_half_metrics[0][key], v01_half_metrics[1][key]]
                for key in v01_half_metrics[0]}
            record["prediction_histograms"]["v0.1"] = None
            checkpoint[game_key] = record
            _append_checkpoint(args.checkpoint, record)
            processed += 1
            if processed % args.progress_every == 0 or processed == len(targets):
                print(json.dumps({"completed_targets": processed, "target_total": len(targets),
                    "elapsed_seconds": round(time.monotonic() - started, 1),
                    "available_ram_gib": round(_available_ram() / 1024**3, 2),
                    "metrics_emitted": False}, sort_keys=True), flush=True)

        # Release target-day labels and player records only after every target on
        # the calendar day has its pregame inputs and predictions.
        for game in games:
            row = manifest[str(game.game_id)]
            boxscore = adapter.read_verified_boxscore(game, row, _SIM.v01.DEFAULT_BOXSCORE_ROOT)
            history.add_game(game, row, boxscore)

    if len(checkpoint) != len(targets):
        raise RuntimeError(f"checkpoint contains {len(checkpoint)} target rows; expected {len(targets)}")
    all_records = sorted(checkpoint.values(), key=lambda x: x["game_index"])
    models = ["B0_alpha2", "B1", "B2", "v0.1", "historical_rate"]
    model_summaries, paired = _summarize_metrics(all_records, models)
    observed_hists: dict[str, CountDistribution] = {}
    predicted_hists: dict[str, dict[str, CountDistribution]] = {model: {} for model in models}
    for record in all_records:
        _merge_histograms(observed_hists, _histogram([record["observed"]]))
        for model, histogram in record.get("prediction_histograms", {}).items():
            if model == "v0.1":
                continue
            _merge_histograms(predicted_hists[model], histogram)
    # v0.1 is the same league distribution for each eligible target.
    _merge_histograms(predicted_hists["v0.1"], v01_histogram, multiplier=len(all_records))
    count_calibration = {}
    all_fields = set(observed_hists)
    for values in predicted_hists.values():
        all_fields.update(values)
    for field in sorted(all_fields):
        count_calibration[field] = {"observed": observed_hists[field].summary()
            if field in observed_hists and observed_hists[field].total else None,
            "predicted": {model: (predicted_hists[model][field].summary()
                if field in predicted_hists[model] and predicted_hists[model][field].total else None)
                for model in models}}

    split_half_sensitivity = {}
    metric_names = ("regulation_overtime_goal_crps_per_team", "official_final_score_crps_per_team",
                    "final_score_energy", "winner_brier", "sog_crps_per_team")
    for model in models:
        split_half_sensitivity[model] = {}
        for metric in metric_names:
            first = [row["split_half_metrics"][model][metric][0] for row in all_records
                     if model in row.get("split_half_metrics", {})]
            second = [row["split_half_metrics"][model][metric][1] for row in all_records
                      if model in row.get("split_half_metrics", {})]
            if first:
                split_half_sensitivity[model][metric] = {
                    "first_half_mean": statistics.fmean(first),
                    "second_half_mean": statistics.fmean(second),
                    "absolute_mean_difference": abs(statistics.fmean(first) - statistics.fmean(second)),
                    "n_games": len(first),
                }

    diagnostics = {model: collections.Counter() for model in ("B0_alpha2", "B1", "B2")}
    for record in all_records:
        for model, values in record.get("candidate_diagnostics", {}).items():
            diagnostics[model].update(values)
    coverage = {model: {"complete_predictions": sum(model in record.get("metrics", {})
                    for record in all_records), "eligible_games": len(all_records),
                    "failed_predictions": sum(model not in record.get("metrics", {})
                    for record in all_records), "complete": all(model in record.get("metrics", {})
                    for record in all_records)} for model in models}
    failure_counts: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for record in all_records:
        for model, raw_reasons in record.get("failures", {}).items():
            reasons = raw_reasons if isinstance(raw_reasons, list) else [raw_reasons]
            for reason in reasons:
                reason = str(reason)
                if reason.startswith("draw="):
                    pieces = reason.split()
                    key = pieces[1] if len(pieces) > 1 else "simulation_exception"
                else:
                    key = reason.split(":", 1)[0]
                failure_counts[model][key] += 1
    failure_summary = {model: dict(sorted(counter.items()))
                       for model, counter in failure_counts.items()}
    runtime_by_model: collections.Counter[str] = collections.Counter()
    for record in all_records:
        runtime_by_model.update({key: float(value)
                                 for key, value in record.get("runtime_seconds", {}).items()})
    result = {
        "schema_version": OUTPUT_VERSION,
        "preregistration_commit": PREREG_COMMIT,
        "execution_configuration": expected_meta,
        "candidate_selection_performed": False,
        "gate_changed": False,
        "database_policy": {
            "2021_backtest_uses_LP_database": False,
            "historical_reason": "available LP NHL player/team tables begin in 2025/26; using later rows for 2021 would leak future information",
            "historical_evaluation_sources": "verified GameCenter PBP and box-score archive with strict forward-only historical snapshots",
            "prospective_mode_uses_ingested_LP_data": {
                "database_path": str(_SIM.DEFAULT_DB),
                "access": "SQLite mode=ro; one explicitly pinned DB path per run; development and production DBs are never pooled",
                "roster": "roster_snapshots and roster_memberships; choose the latest snapshot captured and published at or before the matchup cutoff, then active NHL-native player IDs",
                "player_rates": "prior-season player_stats plus regular-season player_game_logs with game_date strictly before the target date and ingested_at at or before the matchup cutoff; join on canonical player_id, preserve NHL source_player_key",
                "team_sog": "team_game_results joined to team_game_stats by league, native game_id, and team; reciprocal opponent rows; completed games strictly before target date; both result ingests and stat captures before cutoff; current and immediately prior NHL ending-year season keys",
                "team_goal_prior": "existing frozen B3 team-goal model and forecast ledger, requiring target date, forecast generation time, and feature snapshot time to precede the matchup cutoff",
                "team_goal_result_rows": "team_game_results score_for/score_against are available in the DB but remain diagnostic-only under preregistration Amendment 3; they are not blended into prospective goal means",
                "player_and_goalie_rates": "pregame roster projection, individual shot/goal/usage and goalie save evidence from eligible prior-season aggregates and cutoff-valid current-season logs; starting goalie remains uncertain unless independently verified before puck drop"
            },
            "historical_database_audit": "read-only source inventory is documented in the preregistration; current prospective tables are not historical 2021 features"},
        "evaluation_population": {"eligible_2021_targets": len(all_records),
            "target_game_ids_sha256": _json_sha([row["game_key"] for row in all_records]),
            "all_target_rows_retained": len(all_records) == 1292,
            "target_label_source": "verified v0.1 GameCenter PBP/independent-boxscore corpus"},
        "frozen_draws": {"B0_B1_B2_per_game": MC_DRAWS, "v0.1": V01_DRAWS,
            "historical_rate_per_game": RATE_DRAWS, "game_bootstrap_repetitions": BOOTSTRAP_REPETITIONS},
        "training_population": {"2019_2020_eligible_games": len(train_corpus.games),
            "training_seasons": list(_SIM.v01.TRAIN_SEASONS),
            "2021_transition_training": False},
        "runtime": {"source_preparation_and_fit_seconds": round(source_prep_seconds, 3),
            "candidate_and_reference_generation_seconds": {key: round(value, 3)
                for key, value in sorted(runtime_by_model.items())},
            "total_wall_seconds": round(time.monotonic() - started, 3),
            "available_ram_gib_at_end": round(_available_ram() / 1024**3, 3)},
        "coverage": coverage,
        "failures": failure_summary,
        "metrics": model_summaries,
        "paired_differences": paired,
        "split_half_monte_carlo_sensitivity": split_half_sensitivity,
        "count_calibration": count_calibration,
        "candidate_diagnostics": {model: dict(sorted(values.items())) for model, values in diagnostics.items()},
        "historical_rate_baseline_definition": "independent Poisson reg+OT team goals and SOG from forward-only shrunk rates; tied sampled score receives a fair official shootout bonus; this is a score-rate reference, not an event simulator",
        "uncertainty": "95% intervals resample target games. Split-half differences diagnose finite Monte Carlo variability separately; development metrics are not independent adoption evidence.",
        "limitations": [
            "Twelve candidate draws per game leave visible Monte Carlo sensitivity; the paired intervals describe game resampling conditional on those frozen draws.",
            "The 2021 population is development-only; 2022 remains exposed and excluded.",
            "Missing projected rosters or failed candidate draws are retained as explicit failures; metric rows report coverage and are incomplete when any target lacks a prediction.",
            "B1 and B2 retain donor event counts, clock slots, and shifts; B2 does not learn event-arrival intensity.",
            "The historical-rate baseline does not simulate event timing, manpower, penalties, shifts, or player participation.",
            "The current 2026/27 ingested LP data supports prospective inputs only, not the historical 2021 adapter.",
        ],
        "per_game": [{"game_key": record["game_key"], "game_index": record["game_index"],
            "game_date": record["game_date"], "home_team": record["home_team"],
            "away_team": record["away_team"], "input_error": record["input_error"],
            "metrics": record["metrics"], "split_half_metrics": record["split_half_metrics"],
            "failures": record["failures"], "candidate_draws": record["candidate_draws"],
            "runtime_seconds": record["runtime_seconds"]} for record in all_records],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "eligible_targets": len(all_records),
        "coverage": coverage, "total_wall_seconds": result["runtime"]["total_wall_seconds"],
        "metrics_emitted": True}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
