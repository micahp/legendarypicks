# NHL v2 score model — team attack/defence

Status: implemented, measured, **not yet merged to dev**. Changes the B7 score distribution
only; B3 and B5 stay frozen so the comparison is preserved.

## Why

The v1 arm projects a margin with a standard deviation of **0.25 goals** against an observed
**2.6**, and a total with sd **0.18** against **2.08**. It cannot separate teams, so every game
looks like a coin flip and rule 1 of the pick hierarchy fires on roughly half the slate.

Measured on 9,147 graded games (2019-20 → 2025-26):

| | v1 frozen | market (SBR no-vig close) |
| --- | --- | --- |
| Brier, home winner | 0.2463 | 0.2355 |

A coin flip is 0.2500. The v1 model is 0.0037 better than a coin flip and 0.0108 behind the
closing line.

## What v2 does

`team_strength.py` fits a ridge Poisson over two rows per game:

```
log mu_home = b0 + home_adv*(not neutral) + attack[home] - defence[away]
log mu_away = b0                + attack[away] - defence[home]
```

Fitted on the hash-checked canonical game file (23,222 games, 2008-09 → 2026-27), with a
400-day recency half-life and ridge 20. Deterministic: the only input is the canonical CSV.

## Results

Walk-forward (fit on every season before the evaluated one), measured on the same 9,147 games
with the frozen b5 probability as the reference:

| season | frozen Brier | v2 Brier | frozen margin sd | v2 margin sd |
| --- | --- | --- | --- | --- |
| 2020 | 0.2468 | 0.2394 | 0.23 | 0.63 |
| 2021 | 0.2454 | 0.2389 | 0.24 | 0.64 |
| 2022 | 0.2461 | 0.2449 | 0.29 | 0.72 |
| 2023 | 0.2455 | 0.2397 | 0.26 | 0.69 |
| 2024 | 0.2442 | 0.2426 | 0.27 | 0.68 |
| 2025 | 0.2498 | 0.2561 | 0.25 | 0.67 |

Pooled: **frozen 0.2463, v2 0.2436**. v2 wins five of six seasons and loses 2025-26.

On tonight's 46-game slate the change is visible:

| game | v1 margin | v2 margin |
| --- | --- | --- |
| ANA @ NYI | +0.22 | +0.55 |
| ANA @ NYR | +0.17 | +0.84 |
| SJS @ TOR | +0.28 | +1.14 |
| TBL @ VGK | +0.11 | +0.06 |

## What this does not do

It does not beat the market. The closest matched comparison available is the goals+xG blend on
the 5,660 games that overlap the SBR archive: **0.2445 against the market's 0.2395**. The
goals-only arm used here was not separately matched to SBR, and its pooled score is in the same
range. So **no pick from this model should be treated as an edge.** The puck-line threshold in
the pick rule is a heuristic; it is not supported by a probability that beats a closing line.

## Wiring

`run_pipeline.py` uses `team_strength` for `B7_elo_xg_poisson` only, and reads
`frozen_models_2026-27_v2.json`, which inherits the v1 artifact and records the supersession in
`specification.B7_elo_xg_poisson`. New forecasts carry model_version
`nhl-prospective-2026-27-v2`; existing v1 rows keep their version.

`test_nhl_t90.py` has two failures that predate this change (verified by running the unmodified
HEAD): the T-90 fixtures expect `pick_rows=0, unpriced=3` and now see `3, 0`. Not caused by v2;
needs its own look.
