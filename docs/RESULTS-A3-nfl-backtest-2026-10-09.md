# A3 results: NFL version 1 backtest (scores-only ratings)

Written 2026-10-09 against the rules in `SPEC-nfl-team-ratings-playoff-odds-2026-10-09.md`
section 6.1 (committed as `f3f296c`, `cc2de65`, `d30ea75` before any holdout run).

This documents **version 1 only**: a scores-only Massey-style ridge rating
(`backend/nfl_ratings.py`). Version 2 (EPA) is a different model and gets its own record.

## 1. What was run

| Step | What | Where it is recorded |
|---|---|---|
| Tuning grid | 36 configurations on **2024 only**: half-life {3, 6, 12} x margin cap {14, 21, none} x `cap_points` {none, 14, 21, 28} | `model_runs`, 36 rows, status `tuning` |
| Freeze | Configuration chosen by the pre-registered rule (Brier to 3 decimals, then fewer non-defaults) | spec, commit `d30ea75` |
| Holdout | Frozen configuration evaluated **once** on **2025** | `model_runs`, 1 row, status `holdout`; refuses a second recording |

Frozen configuration: half-life 6 weeks, margin cap 14, `cap_points` off, prior games 4, prior
shrink 1/3, sigma 13.295 (the 2024 residual standard deviation of that configuration).

Walk-forward for every game: weeks 2 to 18, fitted on earlier weeks only. Week 1 has no earlier
data and is not graded. Ties are excluded from grading (0 in 2024, 1 in 2025).

## 2. Results

### Holdout: 2025, frozen configuration, one run (n = 255)

| Measure | Model | Coin (50/50) | Constant 57% home | Market (de-vigged) |
|---|---|---|---|---|
| Brier | **0.2288** | 0.2500 | 0.2497 | 0.2137 |
| Log loss | **0.6496** | 0.6931 | 0.6925 | 0.6125 |

Brier difference, model minus baseline, paired bootstrap 95% interval:
- vs coin: **−0.0212, [−0.0407, −0.0015]**
- vs 57% home: **−0.0209, [−0.0400, −0.0012]**
- vs market: **+0.0151, [+0.0043, +0.0257]**

The model beats both naive baselines. The 57% comparison is only just outside zero, so it is
sensitive to the bootstrap setup. The model is significantly worse than the market.

### Pooled 2024 + 2025 (2024 is tuning data, so this is not a holdout result)

- vs coin: −0.0244, [−0.0379, −0.0111]
- vs 57% home: −0.0250, [−0.0387, −0.0113]

### Margin and total against the lines (report only)

| | Model | Line | Interval or note |
|---|---|---|---|
| Margin MAE, 2025 | 10.67 | 9.97 (spread) | model worse |
| Total MAE, 2025 | 10.61 | 10.17 (total line) | model worse |
| Margin MAE, 2024 (tuning) | 10.49 | 9.65 | model worse |

### Against the spread (report only)

- 2025: 125 covers, 129 misses, 1 push. Cover rate 49.2%.
- 2024 (tuning): 128 covers, 124 misses, 4 pushes. Cover rate 50.8%.

Neither season shows an edge against the spread.

### Calibration, 2025 holdout (bins with at least 20 games; the 0.1 bin has 4 and is flagged)

| Predicted | Games | Actual win rate |
|---|---|---|
| 0.2 | 17 | 0.35 |
| 0.3 | 24 | 0.33 |
| 0.4 | 55 | 0.44 |
| 0.5 | 58 | 0.50 |
| 0.6 | 35 | 0.54 |
| 0.7 | 40 | 0.78 |
| 0.8 | 22 | 0.82 |

The 0.6 bin is overconfident (predicted about 0.6, won 0.54). The 0.7 bin is underconfident (won 0.78). The 0.4, 0.5 and 0.8 bins are close to their predictions.

### Early weeks (report separately, as the spec requires)

- Weeks 2–4, 2024 (tuning, no prior exists for 2024): Brier 0.296 on 48 games. Worse than a coin flip.
- Weeks 2–4, 2025 (holdout): Brier 0.237 on 47 games. Better than a coin flip.

The early-season weakness is real. Version 2 should be judged on early weeks as well as the total.

## 3. The pre-registered questions

1. **Beats 50/50 and 57%, both seasons?** 2025 holdout: yes, both intervals exclude zero, though the 57% margin is thin. 2024 also passes, but 2024 was used for tuning, so that result is not independent.
2. **Behind the market?** Yes, by 0.015 Brier and 0.037 log loss in 2025.
3. **Margin and total against the lines?** Worse in both seasons.
4. **Calibration?** Mixed. The 0.6 bin is overconfident and the 0.7 bin underconfident. The remaining bins with enough games are close to their predictions.
5. **ATS?** No edge.
6. **Which parameters?** Tuning grid: all 36 configurations fall between Brier 0.2217 and 0.2276. The whole range is about 0.006, which is inside the noise. The rule picked half-life 6, cap 14, `cap_points` off (raw Brier 0.2225). The raw best was half-life 12, cap 14, `cap_points` off (raw Brier 0.2217). The rule's three-decimal rounding chose the slightly worse one, and the rule was applied as written, not revised after the result. The prior parameters could not be tuned on 2024 at all, because 2024 has no prior. They stayed at the spec defaults.
7. **Is `h` stable?** Full-season fits: 1.48 in 2024, 1.19 in 2025. Within 2025, the walk-forward values run from 0.31 to 3.77, with a median of 1.88. So `h` is noisy early in a season and fairly stable over a full season. Whether fixing `h` improves Brier was **not tested**. Testing it on 2025 would be a second holdout run.
8. **Does capping raw points help?** On 2024 (tuning), no measurable effect. Paired bootstrap differences against off: cap 14 +0.0006 [−0.0013, +0.0023]; cap 21 −0.0001 [−0.0006, +0.0004]; cap 28 +0.0000 [−0.0000, +0.0001]. Not tested on 2025, because the frozen configuration has it off.
9. **Early-season reliability:** see above.
10. **Ties:** excluded and counted (0 in 2024, 1 in 2025).

## 4. What the results do not show

- **The holdout is spent for version 1.** Any later version that is compared on 2025 has already
  seen 2025 results in this record. A version 2 comparison on 2025 is therefore a second look, not a
  clean holdout. See section 5.
- **Sample size.** About 256 games per season. Brier differences around 0.01 are only just
  detectable, and the tuning grid's whole range is 0.006.
- **Sigma is an in-sample estimate from 2024 residuals.** It is applied unchanged to 2025, as the
  spec requires, but it was not estimated out of sample.
- **The model uses scores only.** No injuries, no starting quarterback, no play-by-play efficiency,
  no rest or travel. The market beats it for that reason, and nothing in these numbers says how much
  of the gap any of those inputs would close.
- **Week 5 of 2026 has pre-freeze locks.** The 14 unplayed week-5 games were locked with cap 21 and
  sigma 13.4, before the freeze. They are recorded under their own run, `legacy-nfl-lock-*`. No
  week-5 game has a locked projection from the frozen configuration.

## 5. Implications for version 2

Version 2 (EPA) will be a new configuration and a new model version. The rules that carry over:

- **Tune on 2024 only, then freeze.** 2024 EPA data needs to be loaded and checked first.
- **The 2025 holdout has been seen by version 1.** A v2 comparison on 2025 is a second look. It can
  be reported, but it cannot be the sole pass condition. The stronger test is prospective.
- **Prospective test (recommended for v2's gate).** Lock v1 and v2 projections for each week before
  kickoff, using `lock_nfl_week.py` with a model version for each. Grade after the games. This
  uses data that did not exist when either model was built, and it is the only comparison in this
  project with no reuse of a holdout. It accumulates one week at a time, so it cannot clear a gate
  before Sunday.
- **Same metrics, same intervals.** Brier, log loss, bootstrap intervals against the coin, the 57%
  baseline, the market, and the lines. Version 2 must beat version 1 on the same games.

## 6. Reproduce

```
cd backend
LP_DB_PATH=<dev db> venv/bin/python nfl_tune_2024.py            # 2024 grid, prints ranking
LP_DB_PATH=<dev db> venv/bin/python record_nfl_backtests.py --tune
LP_DB_PATH=<dev db> venv/bin/python record_nfl_backtests.py --holdout   # one-shot
```

Tests: `test_nfl_backtest.py`, `test_nfl_metrics.py`, `test_nfl_tune_2024.py`,
`test_record_nfl_backtests.py`, `test_nfl_ratings*.py`, `test_nfl_lock.py`, `test_lock_nfl_week.py`,
`test_migrate_nfl_model_tables.py`. The bootstrap is seeded, so the reported intervals reproduce.
