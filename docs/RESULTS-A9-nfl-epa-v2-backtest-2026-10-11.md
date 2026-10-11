# RESULTS A9: NFL v2 (pure EPA) backtest

Run 2026-10-11 on the dev DB. Model: `backend/nfl_epa_model.py`. Harness and the pre-registered
rules: `backend/nfl_epa_backtest.py` (docstring committed in `4489d87` before any run). Spec:
`docs/SPEC-nfl-team-ratings-playoff-odds-2026-10-09.md` section 9 (version 2).

## Verdict

**v2 did not beat v1.** On the 2024 grid it trailed v1 in all 9 settings. On the 2025 second look
it is tied: Brier +0.0003 against v1, 95% interval -0.0083 to +0.0087. Per the spec, v1 stays
adopted and v2 stays a shadow model, graded by the weekly locks (spec 9.4 part 2).

## Method (as pre-registered)

- Ratings for a game use plays from earlier weeks of that season only; prior = last season's final
  fit shrunk one third. 2024 has no prior (2023 not loaded).
- EPA to points (`a`, `b`, `h`) and sigma are refit before each graded week from earlier games
  only: the previous season's walk-forward predictions plus this season's earlier weeks.
  Graded only while that pool has 100 or more games, so 2024 grades 149 games (its early weeks
  are not graded). v1 is scored on the identical games.
- v1 comparator: frozen configuration (half_life 6, cap 14, no points cap), sigma 13.295.
- Grid on 2024 only: half_life {3, 6, 12} x lam {50, 150, 450}. Selection: 2024 Brier to three
  decimals, then fewer non-default parameters (defaults half_life 6, lam 150). 2025 run once.

## 2024 tuning grid (149 graded games; v1 Brier 0.1995, log loss 0.5869, margin MAE 9.798, total MAE 10.779; line margin MAE 9.164, total 10.114)

| half_life | lam | Brier v2 | log loss v2 | margin MAE v2 | total MAE v2 |
|---|---|---|---|---|---|
| 3 | 50 | 0.2081 | 0.6055 | 9.986 | 10.713 |
| 3 | 150 | 0.2073 | 0.6039 | 9.975 | 10.804 |
| 3 | 450 | 0.2081 | 0.6056 | 9.988 | 10.864 |
| 6 | 50 | 0.2052 | 0.5994 | 9.965 | 10.490 |
| 6 | 150 | 0.2031 | 0.5949 | 9.937 | 10.590 |
| 6 | 450 | 0.2028 | 0.5944 | 9.936 | 10.680 |
| 12 | 50 | 0.2044 | 0.5977 | 9.960 | 10.376 |
| 12 | 150 | 0.2017 | 0.5919 | 9.921 | 10.471 |
| **12** | **450** | **0.2008** | **0.5901** | **9.917** | **10.574** |

Chosen: half_life 12, lam 450. It is at the edge of the grid on both axes, so a longer half-life or
stronger prior might do better; that would be a new experiment.

## 2025 second look, run once with the frozen choice (255 games, 1 tie excluded)

| | v2 | v1 | line |
|---|---|---|---|
| Brier | 0.2291 | 0.2288 | |
| Log loss | 0.6504 | 0.6496 | |
| Margin MAE | 10.671 | 10.671 | 9.971 |
| Total MAE | 10.496 | 10.614 | 10.175 |

Paired Brier difference (v2 minus v1): +0.0003, 95% interval [-0.0083, +0.0087]. Not shown better.
This is a second look, not a clean holdout: 2025 was already v1's holdout.

## What this does and does not say

- v2's totals are slightly more accurate than v1's in both seasons; neither beats the market line
  on margin or total.
- The in-sample 2025 Brier quoted when the first lock was made (0.2262) was calibrated on the games
  it scored and is not evidence; 0.2291 above is the honest figure.
- The week-5 locks use half_life 6, lam 150 (untuned defaults), not the frozen 12 / 450. Their
  version string says `NOT-ADOPTED untuned`. From week 6, `lock_nfl_epa.py` locks with the frozen choice through the shared lock path.
- Neither version knows who is playing. Availability is a later layer (spec 9.5, SPEC B).

## Records

`model_runs`, dev DB: 9 rows `nfl-epa-v2-tune-2024-*` (status `tuning`) and
`nfl-epa-v2-secondlook-2025-hl12-lam450` (status `holdout`), written by the backtest itself
(`--record`), once per run id. (The first recording, the same morning, copied the printed numbers
by hand; those rows were deleted and re-recorded from the run. The values are identical.)

Reproduce:

    cd backend
    LP_DB_PATH=<dev db> venv/bin/python nfl_epa_backtest.py --stage tune2024 [--record]
    LP_DB_PATH=<dev db> venv/bin/python nfl_epa_backtest.py --stage holdout2025 --half-life 12 --lam 450 [--record]
