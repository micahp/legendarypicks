# P2 player usage component: results (SLC v2 Milestone 3), 2026-11-02

Status: research component result. Development seasons 2023 and 2024 only. No 2025 or 2026 result read. No SLC default change. No simulator run.

## What P2 predicts

For each player-game target share (regular season, `target_share` from the published weekly logs, `nflverse_weekly`), the component predicts the share from the player's usable earlier games of the same season. A usable game is one whose kickoff plus a 10-hour availability lag is at or before the forecast's final-horizon cutoff (kickoff minus one hour). The lag is an assumption, because the publisher does not state when weekly logs appear (see the availability matrix).

Estimate: the observed mean target share over usable games, shrunk toward a prior with K = 4 pseudo-games. The prior is the player's own prior-season mean when they had at least 4 prior-season games, otherwise the prior-season mean of their position group.

## Results (squared error per target share; negative means the component is better)

| Season | Targets | Games | Targets with usable in-season history | Component MSE | Baseline (position mean) MSE | Improvement over baseline (95% CI) | Prior-only MSE | Improvement over prior-only (95% CI) |
|---|---:|---:|---:|---:|---:|---|---:|---|
| 2023 | 17,788 | 272 | 15,846 | 0.001285 | 0.002443 | +0.001159 (+0.001074 to +0.001244) | 0.001678 | +0.000394 (+0.000356 to +0.000433) |
| 2024 | 18,112 | 272 | 16,116 | 0.001352 | 0.002487 | +0.001135 (+0.001056 to +0.001214) | 0.001811 | +0.000460 (+0.000413 to +0.000508) |

Intervals: game-clustered, 10,000 draws, seed 20261102.

## Reading

1. The component beats the frozen baseline (position-group prior-season mean, no player information) by about 47% in squared error in both seasons. This is a weak comparator.
2. The stronger comparator is the prior-only estimate: the same prior with no in-season games. The component still improves on it by about 0.0004 to 0.0005 (roughly 23% to 25% lower squared error), with intervals well above zero. The gain from updating with this season's usable games is real, not an artefact of the weak baseline.
3. About 11% of targets have no usable in-season game (week 1 and early-season cases). For those the component is the prior, so they add no information and are kept, not dropped.
4. Null target shares: none in the development seasons. A null would be counted in the feature output, not read as zero.

## Leakage and availability checks

- The target game is never an input: it is after the cutoff, and the usable rule excludes it.
- Every forecast row carries a manifest entry (`outputs/p2_forecast_manifest.csv`, 35,900 rows). The manifest records the games used, the latest used kickoff, the lag, the cutoff, and the check that the latest used kickoff plus the lag is at or before the cutoff. All 35,900 rows pass.
- Logs without a kickoff: 2,528, all postseason rows (the evaluation asserts that no regular-season game lacks a kickoff).

## What is not in P2

- Snap share (`off_pct`) is not evaluated here. It is published in the same logs and is planned as a second P2 target.
- Carry share is not evaluated here.
- Injury and availability states are not used (owner ruling C).
- Named-player participation for a specific week is not a pregame input until the eligibility mechanism passes (owner ruling E).

## Outputs

- `p2_usage.py`: the component (usable rule, shrinkage, prior choice, loader).
- `p2_eval.py`: the development evaluation and manifest.
- `test_p2_usage.py`: 13 passing tests (lag boundary, shrinkage, leakage, prior choice, null handling, real-log joins).
- `outputs/p2_results.json`, `outputs/p2_forecast_manifest.csv`, `outputs/p2_examples.json` (12 WR, TE and RB examples with usable history).
