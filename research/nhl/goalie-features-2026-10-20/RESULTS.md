# NHL goalie keep-rule walk-forward results

**Run date:** 2026-10-20<br>
**Protocol:** signed `PREREG-GOALIE-KEEP.md`, frozen learner `MODEL-SPEC.md`<br>
**Learner:** scikit-learn 1.9.1; two logistic fits per evaluation fold; one process / one numerical-library thread.

## Frozen input hashes

- `goalie_features.csv`: `a201cf7a4fff942c762d8b01c712f1a14602ef0602b3b0bf19c69cbc80323925`
- `../sbr-odds-archive-2026-10-19/games_2018_2023.jsonl.gz`: `a435454f4ec71b1ba3f612fde03b120438a7721a9a04e36f5aa2230e89ea273b`
- `canonical_games_v1_7cd2fc9a6e84470c.csv (canonical game table)`: `7cd2fc9a6e84470c177b704aa56ba328ad67522698244ce1f182ddcb9e439f52`
- `PREREG-GOALIE-KEEP.md`: `2c13c92743f5edf1135754788e5e9fe3de51c2657efe6ac4ea2d79b72a71e8a6`
- `MODEL-SPEC.md`: `6d34a407ab097de6dbcc7eb5e121cfe59eb3280c1e90ca121ce81ad813444ab9`
- `JOIN-AUDIT.md`: `1f2bd8c9993e9bc648993605c3df553a35463f54d58b9dd3a5fa422e9b13fe81`
- `run_goalie_keep.py`: `550da1fbb06ce2d7d5346376d54953339efe50f5ea7d4d399ce871398d33aedc`

## Denominators and season coverage

There are **4,763 eligible regular-season games** in the combined registered population. This includes **1,254 training-only games from 2018-19**. The separate out-of-fold evaluation denominator is **3,509 games** across four blocks. The final block is the **partial 2022-23 archive slice of 339 games, dated 2022-10-11 through 2022-11-27**; 307 eligible rows in that seven-week slice are included in OOF evaluation. It is not a complete season holdout.

Before metrics, the eligibility audit excludes **107** regular-season games under the six-feature complete-case rule, **one** feature-complete game without both opening prices (`2020020316`), and **one** feature-complete game without both final scores (`2020020371`). These are separate game IDs; none is treated as a pass or loss.

## Fold-level rule selection

| Evaluation block | Prior eligible training rows | OOF games | Selected candidate | Selection basis |
| --- | ---: | ---: | --- | --- |
| 2019-20 | 1254 | 1064 | D | initial fold; no prior OOF games |
| 2020-21 | 2318 | 849 | D | highest prior paired units per eligible game — A: 882 bets, delta=+0.010648 units/game; B: 583 bets, delta=+0.031960 units/game; C: 871 bets, delta=+0.011668 units/game; D: 573 bets, delta=+0.033567 units/game |
| 2021-22 | 3167 | 1289 | D | highest prior paired units per eligible game — A: 1579 bets, delta=-0.019519 units/game; B: 1109 bets, delta=-0.006610 units/game; C: 1556 bets, delta=-0.019773 units/game; D: 1087 bets, delta=-0.006537 units/game |
| 2022-23 | 4456 | 307 | D | highest prior paired units per eligible game — A: 2623 bets, delta=-0.030297 units/game; B: 1897 bets, delta=-0.027121 units/game; C: 2584 bets, delta=-0.028231 units/game; D: 1859 bets, delta=-0.024860 units/game |

## Predictor quality

All predictors are scored on the same 3,509 OOF games against canonical home winner. No AUC is reported.

| Predictor | Brier | Log loss | Δ Brier vs raw market |
| --- | ---: | ---: | ---: |
| Raw no-vig opening market | 0.235522 | 0.664212 | 0.000000 |
| Market-only logistic diagnostic | 0.235791 | 0.664700 | +0.000269 |
| Goalie logistic | 0.250295 | 0.695958 | +0.014774 |

Goalie-model `ΔBrier` 90% season-block interval: **[+0.010330, +0.019367]**.

## Frozen keep-rule policy

| OOF block | Eligible games | Candidate | Bets | Selection rate | Net units | ROI | Market-control bets | Market-control units | Paired units/game vs market control |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2019-20 | 1064 | D | 573 | 53.853% | +35.715 | +6.233% | 0 | +0.000 | +0.033567 |
| 2020-21 | 849 | D | 514 | 60.542% | -48.220 | -9.381% | 0 | +0.000 | -0.056796 |
| 2021-22 | 1289 | D | 772 | 59.891% | -65.893 | -8.535% | 3 | +1.202 | -0.052053 |
| 2022-23 | 307 | D | 143 | 46.580% | -20.614 | -14.415% | 0 | +0.000 | -0.067146 |
| **Aggregate** | **3509** | sequential | **2002** | **57.053%** | **-99.012** | **-4.946%** | **3** | **+1.202** | **-0.028559** |

- Goalie-rule one-unit ROI: [-10.5%, +2.1%] (5,000 resamples; seed 20261020).
- Paired policy delta: -0.028559 units per eligible game; 90% season-block interval [-0.058343, +0.011015].
- Market no-vig control: 3 bets / 3509 games; net units +1.202.
- Market no-vig control ROI: +40.083%.
- Goalie policy total: 2002 bets / 3509 games; net units -99.012.

## Registered stopping decision

**DISCARD keep rule under this preregistration; at least one registered adverse interval criterion is met.**

The verdict applies only to the frozen research candidate and this historical opening-quote archive. Four blocks, including one short partial season, provide coarse uncertainty estimates. This result is not approval to deploy.

## Interpretation and execution notes

This experiment evaluates only the six historical strict-lag goalie features in the signed registration. It provides no evidence about announced-starter inputs, shot-location or shot-type features, or the broader V3 event-simulation goal.

The eight logistic fits completed without convergence warnings. scikit-learn 1.9.1 emitted a `FutureWarning` for the preregistered explicit `penalty="l2"` argument; it did not affect this run's fit. A future scikit-learn upgrade may require an API-only specification update before another run.

The OOF CSV writes probabilities to 12 significant digits. For underround game `2021020906`, the full-precision no-vig control had a numerical tie and the runner's stable home-first ordering selected home (−1.000 unit). Recomputing the control from the rounded CSV probabilities can make the away side appear very slightly higher. This display-rounding tie does not change the reported control count or totals.

CSV line endings were normalized to LF after the run; no cell values were changed.

## Join and source disclosures

See `JOIN-AUDIT.md` for the complete identity reconciliation, venue reversal, exclusions, scoreline differences, and separate training/evaluation denominators. Underround opening pairs retained in the eligible population: 3.

## Per-game out-of-fold predictions

`oof_predictions.csv` contains every one of the 3,509 eligible evaluation rows, including passes, the selected candidate, market-control decision, target, raw and fitted probabilities, and settled units.
