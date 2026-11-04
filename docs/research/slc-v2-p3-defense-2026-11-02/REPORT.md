# P3 defensive matchup component: results (SLC v2 Milestone 3), 2026-11-02

Status: research component result. Development seasons 2023 and 2024 only. No 2025 or 2026 result read. No SLC default change. No simulator run. Verdict: **not adopted** as specified. No outcome beats the frozen baseline in both development seasons.

## What P3 predicts

For each defense D and game t, the yards per opportunity allowed to a group, for five outcomes:
- receiving yards per target to WR, TE and RB;
- rushing yards per carry to RB;
- passing yards per attempt to QB.

Opportunity volume (targets, carries, attempts allowed per defense-game) is reported separately and is not forecast here.

Estimate: the league prior-season rate, plus the target offense's prior-season strength adjustment, plus a shrunk defense effect. The defense effect is the mean residual over D's usable earlier games this season, with K = 8 pseudo-games. Each earlier game's residual subtracts its own offense's prior-season strength. Offense strength is the prior-season passing (or rushing) yards per attempt. No in-season information about the opponent enters the adjustment.

Touchdown rates are not evaluated. They are sparse and would need a separate model with K = 40.

The availability lag is 10 hours, as in P2 and P1.

## Results (squared error on yards per opportunity; positive improvement means the component is better)

| Season | Outcome | Targets | League prior | Component MSE | Baseline MSE | Improvement over baseline (95% CI) | Improvement over no opponent adjustment |
|---|---|---:|---:|---:|---:|---|---:|
| 2023 | receiving WR | 544 | 7.918 | 7.852 | 8.160 | +0.308 (-0.094 to +0.708) | +0.301 |
| 2023 | receiving TE | 538 | 7.204 | 14.153 | 13.599 | **-0.554 (-1.100 to -0.003)** | -0.092 |
| 2023 | receiving RB | 539 | 5.553 | 14.660 | 13.932 | **-0.728 (-1.287 to -0.195)** | -0.229 |
| 2023 | rushing RB | 544 | 4.401 | 1.946 | 1.936 | -0.010 (-0.128 to +0.109) | -0.076 |
| 2023 | passing QB | 544 | 7.021 | 3.563 | 3.632 | +0.070 (-0.163 to +0.302) | +0.057 |
| 2024 | receiving WR | 544 | 7.927 | 8.618 | 8.386 | -0.232 (-0.587 to +0.113) | +0.056 |
| 2024 | receiving TE | 542 | 7.263 | 16.458 | 16.614 | +0.158 (-0.566 to +0.893) | +0.443 |
| 2024 | receiving RB | 534 | 5.539 | 16.193 | 16.171 | -0.021 (-0.762 to +0.751) | +0.137 |
| 2024 | rushing RB | 544 | 4.147 | 1.803 | 1.726 | -0.077 (-0.186 to +0.032) | -0.058 |
| 2024 | passing QB | 544 | 7.020 | 3.840 | 3.886 | +0.047 (-0.213 to +0.306) | +0.118 |

Intervals are game-clustered, 10,000 draws, seed 20261102. Bold marks an interval entirely on the wrong side of zero.

## Reading

1. **No outcome beats the baseline in both seasons with an interval above zero.** Receiving WR in 2023 has the largest positive point estimate (+0.308), but its interval includes zero. Every other positive estimate also has an interval that includes zero.
2. **Receiving TE and receiving RB are significantly worse than the baseline in 2023.** The defense effect, shrunk with K = 8, adds error. This is the signal the component should not have produced, and it is reported as a failure.
3. **The opponent adjustment is not consistently helpful.** It helps receiving WR in 2023 (+0.30) and receiving TE in 2024 (+0.44), but it hurts receiving TE and RB in 2023. The sign is not stable across seasons and outcomes, so it is not supported.
4. **Defense-level yards per opportunity carry little signal at this sample size.** Per defense-game, the outcome noise is large relative to the spread between defenses. A single season of defenses has not separated true defensive effects from noise. A larger K, or a pooled multi-season prior, may behave differently. Such a sensitivity was not run, because K was fixed before the run and selecting K on these results would be a forking path.

## Verdict

P3 is **not adopted** as specified (K = 8, opponent adjustment from the prior season). The result is the honest outcome of the pre-run specification. P3 needs a separate, pre-registered test before any reconsideration, using a different K or a multi-season prior, with the 2025 retrospective fold kept untouched until the candidate is frozen.

## Leakage and availability checks

- Only usable earlier games of the same defense in the same season enter the defense effect. The target game is excluded by the usable rule.
- Opponent strength comes from the prior season only.
- Every forecast row carries a manifest entry (`outputs/p3_forecast_manifest.csv`, 5,417 rows), with the cutoff, the games used, the latest used kickoff, the lag check, and the opponent-strength source. Late violations: 0 in every outcome and season.

## Open items

1. A pre-registered P3 variant (new K or multi-season prior) before reconsideration. Not run here.
2. Touchdown rates with a separate, strongly shrunk model (K = 40). Not built here.
3. Opportunity volume forecast. Not built here.

## Outputs

- `p3_defense.py`: the component (usable rule, prior-season opponent strength, shrinkage, residuals).
- `p3_eval.py`: loaders, the five outcomes, the comparators, the manifest.
- `test_p3_defense.py`: 9 passing tests (usable earlier games only, target excluded, prior-season opponent strength, residual subtraction, shrinkage, K for touchdowns, empty defense-games counted, volume reported separately).
- `outputs/p3_results.json`, `outputs/p3_forecast_manifest.csv`.
