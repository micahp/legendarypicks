#!/usr/bin/env python3
"""Rank normalized archived SLC seeds against season-held-out NFL game references."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import subprocess
from pathlib import Path

from slc_realism_ranker import (DEFAULT_WEIGHTS, NUMERICAL_BACKEND, fit_reference_model, load_jsonl,
                                rank_candidates, write_outputs)


WEIGHT_SENSITIVITY = {
    "drives_heavier": {"drives": 0.40, "decisions": 0.20, "workloads": 0.20, "game": 0.20},
    "decisions_heavier": {"drives": 0.25, "decisions": 0.35, "workloads": 0.20, "game": 0.20},
    "workloads_heavier": {"drives": 0.25, "decisions": 0.20, "workloads": 0.35, "game": 0.20},
    "game_heavier": {"drives": 0.25, "decisions": 0.20, "workloads": 0.20, "game": 0.35},
}


def _analysis_provenance() -> dict:
    root = Path(__file__).resolve().parents[2]
    files = {
        "scripts/nfl_sequence/build_slc_realism_inputs.py",
        "scripts/nfl_sequence/slc_realism_ranker.py",
        "scripts/nfl_sequence/run_slc_realism_ranking.py",
        "scripts/nfl_sequence/validate_slc_seed_replays.py",
        "scripts/nfl_sequence/replay_slc_seed_set.py",
    }
    hashes = {}
    for relative in sorted(files):
        digest = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        hashes[relative] = digest
    try:
        branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=root, text=True).strip()
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip())
    except (OSError, subprocess.CalledProcessError):
        branch, commit, dirty = None, None, None
    return {"branch": branch, "base_commit": commit, "worktree_dirty": dirty,
            "analysis_files_sha256": hashes}


def _rank_map(rows: list[dict], score_key: str) -> dict[int, int]:
    ordered = sorted(rows, key=lambda row: (-float(row[score_key]), int(row["seed"])))
    return {int(row["seed"]): index + 1 for index, row in enumerate(ordered)}


def _spearman(left: dict[int, int], right: dict[int, int]) -> float:
    keys = sorted(set(left) & set(right))
    if len(keys) < 2:
        return 0.0
    a = [float(left[key]) for key in keys]
    b = [float(right[key]) for key in keys]
    mean_a, mean_b = statistics.mean(a), statistics.mean(b)
    numerator = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    denominator = math.sqrt(sum((x - mean_a) ** 2 for x in a) * sum((y - mean_b) ** 2 for y in b))
    return numerator / denominator if denominator else 1.0


def sensitivity(rows: list[dict], top_n: int = 150) -> dict:
    base = _rank_map(rows, "realism_score")
    base_top = {seed for seed, rank in base.items() if rank <= top_n}
    result = {}
    for label, weights in WEIGHT_SENSITIVITY.items():
        key = f"sensitivity_{label}"
        for row in rows:
            row[key] = sum(float(row["component_scores"][group]) * weight
                           for group, weight in weights.items())
        alt = _rank_map(rows, key)
        alt_top = {seed for seed, rank in alt.items() if rank <= top_n}
        result[label] = {
            "weights": weights,
            "spearman_vs_default": round(_spearman(base, alt), 6),
            "top_n_overlap": len(base_top & alt_top),
            "top_n": top_n,
        }
        for row in rows:
            row.pop(key, None)
    return result


def _summary(values: list[float]) -> dict:
    values = sorted(values)
    if not values:
        return {"n": 0}
    q = lambda p: values[min(len(values) - 1, int((len(values) - 1) * p))]
    return {"n": len(values), "min": values[0], "p10": q(0.10), "median": statistics.median(values),
            "mean": statistics.mean(values), "p90": q(0.90), "max": values[-1]}


def run(seed_file: Path, historical_file: Path, provenance_file: Path, out_dir: Path,
        top_n: int, marketing_n: int, neighbors: int, workers: int = 1) -> list[dict]:
    candidates = load_jsonl(seed_file)
    historical = load_jsonl(historical_file)
    reference_model = fit_reference_model(historical, k=neighbors, workers=workers)
    ranked = rank_candidates(candidates, historical, k=neighbors, reference_model=reference_model,
                             workers=workers)
    sensitivity_report = sensitivity(ranked, top_n)
    write_outputs(ranked, out_dir, top_n=top_n, marketing_n=marketing_n)

    feature_validation = {}
    # Validation is grouped by held-out season. Each held-out game was compared only with other seasons.
    for group in DEFAULT_WEIGHTS:
        _distances = reference_model["calibration"][group]
        by_season = reference_model["validation"][group]
        feature_validation[group] = {"heldout_distances_by_season": by_season,
                                     "heldout_distance_distribution": _summary(_distances)}

    component_distributions = {
        group: _summary([float(row["component_scores"][group]) for row in ranked])
        for group in DEFAULT_WEIGHTS
    }
    scoreable = [row for row in ranked if row["gate"]["scoreable"]]
    renderable_before_replay = [row for row in ranked if row["gate"]["renderable"]]
    provenance = json.loads(provenance_file.read_text())
    validation = {
        "schema": "lp.nfl.slc-realism-ranking-validation.v1",
        "weights": DEFAULT_WEIGHTS,
        "nearest_neighbors": neighbors,
        "ranking_workers": workers,
        "calibration_workers": workers,
        "candidate_distance_backend": NUMERICAL_BACKEND,
        "historical_games": len(historical),
        "seeds": len(ranked),
        "scoreable_seeds": len(scoreable),
        "renderable_before_replay": len(renderable_before_replay),
        "component_score_distributions": component_distributions,
        "historical_heldout_validation": feature_validation,
        "weight_sensitivity": sensitivity_report,
        "historical_score_proxy": provenance.get("historical_score_limit"),
        "team_conditioning": provenance.get("team_conditioning"),
        "claim_limit": "Historical typicality score ranks resemblance; it is not a probability forecast or the likelihood of an exact future game.",
        "analysis_source": _analysis_provenance(),
    }
    (out_dir / "ranking-validation.json").write_text(json.dumps(validation, indent=2, sort_keys=True) + "\n")
    _write_report(ranked, validation, provenance, out_dir)
    return ranked


def _write_report(ranked: list[dict], validation: dict, provenance: dict, out_dir: Path) -> None:
    scoreable = [row for row in ranked if row["gate"]["scoreable"]]
    eligible = sorted(scoreable, key=lambda row: (-row["realism_score"], row["seed"]))
    top = eligible[:10]
    lines = [
        "# MIN–DET Realism Based Seed Ranking",
        "",
        f"Run: `{provenance.get('run')}` · source commit `{provenance.get('source_commit')}`.",
        "",
        f"Scored {len(ranked):,} archived seeds against {validation['historical_games']:,} historical regular-season games from 2022–2025.",
        "Historical comparison uses leave-one-season-out nearest neighbors; each held-out game is compared with other seasons only.",
        "",
        "## Method",
        "",
        "Robust median/IQR scaling is applied within four explicit groups. Each group uses the mean distance to its 20 nearest historical game rows, with the team and exact-opponent cohorts shrunk toward the league-wide neighbors by cohort size. Group distances are converted to 0–100 typicality scores using the held-out historical distance distribution.",
        f"Candidate distances used the `{NUMERICAL_BACKEND['name']}` backend (version {NUMERICAL_BACKEND['version'] or 'stdlib'}); the NumPy path applies the same clipping, group masks, neighbor means, and cohort shrinkage as the standard-library implementation.",
        "",
        "| Group | Weight |",
        "|---|---:|",
        *[f"| {name} | {weight:.0%} |" for name, weight in DEFAULT_WEIGHTS.items()],
        "",
        "The four score contributions are emitted for every seed in `seed-realism-rankings.csv`. The ranking never uses the SLC 10K mean as its realism reference. Marketing interest is scored after realism and replay gates.",
        "",
        "Visual interest is a separate 0–100 heuristic from close margin, comeback, defensive-game and bounded star flags, turnover count, and fourth-quarter scoring. It never changes the realism score; the scenario label describes why a seed was selected.",
        "",
        "## Historical and model limits",
        "",
        "The pinned reference contains 1,087 regular-season games (2022–2025). Team/opponent conditioning is weak for the exact DET–MIN pair and is shrunk accordingly. The historical PBP snapshot has no authoritative final-score or extra-point-result fields; the score group therefore uses a documented score proxy (touchdowns, field goals, and recorded extra-point attempts). The score proxy is not an exact scoreboard reconstruction.",
        "",
        "The frozen matchup comparison also documents model-level differences: simulated punt terminals average 2.66 for DET and 2.78 for MIN versus historical 3.09 and 3.75; Jahmyr Gibbs averages 31.99 carries of Detroit’s 36.83 team carries (86.9%). Seed ranking cannot correct these calibration issues. See `docs/research/slc-week8-2026/reviews/2026_08_MIN_DET_drive_distribution_comparison_2022-2025_final/report.md` and `docs/research/slc-week8-2026/reviews/2026_08_MIN_DET_realism_review_2026-10-31.md`.",
        "",
        "Stage A archived sidecars provide boxscores, drive summaries, player workload, quarter points, and aggregate play-call decisions, but not complete per-play traces. Replay is required before any seed enters the marketing shortlist. Four-down conversion choices and full score-clock decisions remain replay-stage features.",
        "",
        "Rare outcomes are not hard-rejected for rarity. Hard gates cover run status, full-game validity, accounting reconciliation, unsupported sequences, replay equivalence, and renderability. Score-only overtime is retained for statistical scoring but excluded from full-game visualization unless its sequence is present and supported.",
        "",
        "## Stage A summary",
        "",
        f"- Seeds read: {len(ranked):,}",
        f"- Scoreable seeds: {validation['scoreable_seeds']:,}",
        f"- Stage A top replay candidates: {min(150, len(eligible)):,}",
        f"- Realism score median: {_summary([r['realism_score'] for r in scoreable]).get('median', 0):.2f}",
        "- Held-out historical distance and weight sensitivity results: `ranking-validation.json`.",
        "",
        "## Highest Stage A scores",
        "",
        "| Rank | Seed | Score | Drives | Decisions | Workloads | Game | Replay |",
        "|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for index, row in enumerate(top, 1):
        parts = row["score_contributions"]
        lines.append(f"| {index} | {row['seed']} | {row['realism_score']:.2f} | {parts['drives']:.2f} | {parts['decisions']:.2f} | {parts['workloads']:.2f} | {parts['game']:.2f} | {row['replay_status']} |")
    lines.extend(["", "Scores are historical resemblance ranks for examples produced by this simulator. They do not show that the simulator is calibrated or that a seed is a likely future game.", ""])
    (out_dir / "research-report.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-features", type=Path, required=True)
    parser.add_argument("--historical-features", type=Path, required=True)
    parser.add_argument("--input-provenance", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--top-n", type=int, default=150)
    parser.add_argument("--marketing-n", type=int, default=15)
    parser.add_argument("--neighbors", type=int, default=20)
    parser.add_argument("--workers", type=int, default=max(1, os.cpu_count() or 1))
    args = parser.parse_args(argv)
    run(args.seed_features, args.historical_features, args.input_provenance, args.out_dir,
        args.top_n, args.marketing_n, args.neighbors, args.workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
