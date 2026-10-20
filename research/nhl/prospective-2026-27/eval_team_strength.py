#!/usr/bin/env python3
"""Walk-forward evaluation of the v2 team attack/defence score model.

Reproduces the per-season table and pooled Brier in RESULTS.md. For each evaluated season the
model is fitted on every canonical season before it and scored on that season; the reference is
the frozen B5 xG Poisson probability from the frozen model artifact. The model input is the
hash-checked canonical game file only; the B5 reference reads the hash-checked rolling-feature
file because B5's inputs are the rolling xG columns.

Population. The pooled number covers seasons 2019 through 2025 on the 9,147 games whose rolling
5v5 xG features are complete, because the frozen B5 reference cannot be scored without them.
The canonical file holds 9,157 games in those seasons (10 lack complete rolling features) and
23,222 in total for 2008-2025. The six seasons in the RESULTS.md table (2020-2025) are 7,935 of
those 9,147 complete games, or 7,945 canonical; 2019 (1,212 games) was omitted from the
published table, which is why the table's six rows summed to less than the stated 9,147. The
scored count is printed on every run so it can be checked.

Run from the repository root:

    python3 research/nhl/prospective-2026-27/eval_team_strength.py
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
AUDIT = HERE.parent / "kalshi-playoff-audit-2025-26"
CANONICAL = AUDIT / "canonical_games_v1_7cd2fc9a6e84470c.csv"
FEATURES = AUDIT / "pregame_rolling_features_v1_62dcceb77085bc59.csv"
MODEL = HERE / "frozen_models_2026-27_v2.json"

import sys

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import team_strength  # noqa: E402

_SIGMA_CAP = 20


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def poisson_win_prob(home_mu: float, away_mu: float, tie_home: float) -> float:
    vals = np.arange(_SIGMA_CAP + 1)

    def pmf(mu: float) -> np.ndarray:
        mu = max(1e-9, float(mu))
        logp = vals * math.log(mu) - mu - np.array([math.lgamma(int(v) + 1) for v in vals])
        p = np.exp(logp)
        return p / p.sum()

    h, a = pmf(home_mu), pmf(away_mu)
    p_home = float(sum(h[i] * a[:i].sum() for i in range(_SIGMA_CAP + 1)))
    p_tie = float(np.dot(h, a))
    return min(1 - 1e-8, max(1e-8, p_home + p_tie * tie_home))


def load_features(path: Path) -> dict[int, dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return {int(r["game_id"]): r for r in csv.DictReader(f)}


def b5_design(r: dict) -> tuple[list[float], list[float]] | None:
    """The frozen B5 xG design rows, or None when the rolling features are incomplete."""
    try:
        return (
            [1.0, math.log(max(float(r["home_rolling10_5v5_score_venue_xgf"]), 0.05)),
             math.log(max(float(r["away_rolling10_5v5_score_venue_xga"]), 0.05))],
            [0.0, math.log(max(float(r["away_rolling10_5v5_score_venue_xgf"]), 0.05)),
             math.log(max(float(r["home_rolling10_5v5_score_venue_xga"]), 0.05))],
        )
    except (TypeError, ValueError):
        return None


def evaluate(first_season: int, last_season: int, model: dict, games: list[dict], features: dict[int, dict]) -> list[dict]:
    tie_home = float(model["historical_home_shootout_win_rate"])
    params = model["poisson_models"]["xg"]
    intercept, coef = float(params["intercept"]), [float(v) for v in params["coef"]]
    # game_id is not stored on the canonical games; join by the canonical (date, home, away) key.
    features_game_ids = {}
    for gid, r in features.items():
        features_game_ids[(r["game_date"], r["home_team"], r["away_team"])] = gid
    rows = []
    for season in range(first_season, last_season + 1):
        train = [g for g in games if g["season"] < season]
        test = [g for g in games if g["season"] == season]
        if not train or not test:
            continue
        fitted = team_strength.TeamStrength(train)
        v2_probs, frozen_probs, v2_margins, frozen_margins, outcomes = [], [], [], [], []
        for g in test:
            gid = features_game_ids[(g["date"], g["home"], g["away"])]
            rows_feat = b5_design(features[gid])
            if rows_feat is None:
                continue
            v2_mus = fitted.mus(g["home"], g["away"], g["neutral"])
            v2_probs.append(poisson_win_prob(v2_mus[0], v2_mus[1], tie_home))
            v2_margins.append(v2_mus[0] - v2_mus[1])
            fmus = [math.exp(intercept + float(np.dot(coef, row))) for row in rows_feat]
            frozen_probs.append(poisson_win_prob(fmus[0], fmus[1], tie_home))
            frozen_margins.append(fmus[0] - fmus[1])
            outcomes.append(int(g["hg"] > g["ag"]))
        y = np.asarray(outcomes, dtype=float)
        rows.append({
            "season": season,
            "n_test": len(test),
            "n": len(outcomes),
            "frozen_brier": float(np.mean((np.asarray(frozen_probs) - y) ** 2)),
            "v2_brier": float(np.mean((np.asarray(v2_probs) - y) ** 2)),
            "frozen_margin_sd": float(np.std(frozen_margins, ddof=0)),
            "v2_margin_sd": float(np.std(v2_margins, ddof=0)),
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-season", type=int, default=2019)
    parser.add_argument("--last-season", type=int, default=2025)
    args = parser.parse_args()

    model = json.loads(MODEL.read_text())
    body = {k: v for k, v in model.items() if k != "model_sha256"}
    expected = hashlib.sha256((json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()).hexdigest()
    if model.get("model_sha256") != expected:
        raise SystemExit(f"frozen artifact self-hash mismatch: stored {model.get('model_sha256')} != {expected}")
    if sha_file(CANONICAL) != model["input_hashes"]["canonical_games_sha256"]:
        raise SystemExit("canonical game file hash does not match the frozen artifact")

    games = team_strength.load_games(str(CANONICAL))
    features = load_features(FEATURES)
    table = evaluate(args.first_season, args.last_season, model, games, features)
    print(f"walk-forward v2 team attack/defence vs frozen B5; canonical={CANONICAL.name}")
    print(f"{'season':>6} {'n':>6} {'canon':>6} {'frozen':>8} {'v2':>8} {'froz_sd':>8} {'v2_sd':>8}")
    for row in table:
        print(f"{row['season']:>6} {row['n']:>6} {row['n_test']:>6} {row['frozen_brier']:>8.4f} {row['v2_brier']:>8.4f} "
              f"{row['frozen_margin_sd']:>8.2f} {row['v2_margin_sd']:>8.2f}")
    total_n = sum(r["n"] for r in table)
    pooled_frozen = float(sum(r["frozen_brier"] * r["n"] for r in table) / total_n)
    pooled_v2 = float(sum(r["v2_brier"] * r["n"] for r in table) / total_n)
    print(f"{'pooled':>6} {total_n:>6} {pooled_frozen:>8.4f} {pooled_v2:>8.4f}")
    print(f"population: seasons {args.first_season}-{args.last_season}, {total_n} games with complete rolling xG features")
    print(f"headline: pooled Brier v2 {pooled_v2:.4f} vs frozen {pooled_frozen:.4f} over {total_n} games")


if __name__ == "__main__":
    main()
