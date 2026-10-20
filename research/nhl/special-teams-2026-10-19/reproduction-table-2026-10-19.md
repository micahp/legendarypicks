# Reproduction table — NHL special teams — 2026-10-19

Branch `research/nhl-special-teams-2026-10-19`, base HEAD `44d3ca07`. This closes the
reproducibility brief `BRIEF-NHL-ST-REPRODUCIBLE-2026-10-19.md`.

**Result: REPRODUCTION PASS.** Every reported score is recomputable from a committed per-game
CSV with no model fit. All non-PIT statistics match the stored results to **0.00e+00**; PIT/KS
match to within the 4-decimal rounding used in the result docs (max absolute difference
**4.45e-05**, tolerance 5e-5). The reproduced numbers **do not change the verdict**.

## How it is reproduced

1. `forecasts_all_arms.csv` — 36,588 rows = 9,147 games × 4 arms (`b5, st, v1, v2`). Columns:
   `game_id, season, game_date, home_team, away_team, model_variant, p_home, mu_h, mu_a,
   home_win, home_goals, away_goals`. Emitted by `emit_forecasts.py` from the stored artifacts
   only; **no refit**.
2. `verify_from_csv.py` — reads only that CSV. Recomputes Brier, log loss, CRPS, MAE, PIT and KS
   from `p_home`/`mu_h`/`mu_a` and the actual results, plus the game-clustered paired bootstrap
   CIs. No model fit, no DuckDB. Output committed as `verify_from_csv.out.txt`.
3. `verify_leakage_all_arms.py` — independent leakage audit; output committed as
   `verify_leakage_all_arms.out.txt`.

## Reproduction table — ST experiment (B5 → ST)

Reported in `results_special_teams.json` / `special-teams-feasibility-2026-10-19.md`.

| statistic | reported | recomputed from CSV | absdiff |
|---|---:|---:|---:|
| b5 Brier | 0.243911517790283 | 0.243911517790283 | 0.00e+00 |
| st Brier | 0.243298726052807 | 0.243298726052807 | 0.00e+00 |
| Δ Brier (b5−st) | 0.000612791737475221 | 0.000612791737475221 | 0.00e+00 |
| Brier CI low / high | 0.000313582782028163 / 0.000901196074923893 | same | 0.00e+00 |
| b5 log loss | 0.680833396964885 | 0.680833396964885 | 0.00e+00 |
| st log loss | 0.679577986935514 | 0.679577986935514 | 0.00e+00 |
| Δ log loss | 0.00125541002937173 | 0.00125541002937173 | 0.00e+00 |
| log-loss CI low / high | 0.000648715489896060 / 0.00183995099787497 | same | 0.00e+00 |
| b5 CRPS | 0.960077840116014 | 0.960077840116014 | 0.00e+00 |
| st CRPS | 0.958670640204569 | 0.958670640204569 | 0.00e+00 |
| Δ CRPS | 0.00140719991144502 | 0.00140719991144502 | 0.00e+00 |
| CRPS CI low / high | 0.000799417669963139 / 0.00201555524517365 | same | 0.00e+00 |
| b5 / st MAE | 1.3826181378657 / 1.38225270606013 | same | 0.00e+00 |

## Reproduction table — penalty experiment (ST → V1, V2)

Reported in `results_penalty_volume.json` / `special-teams-penalty-report-2026-10-19.md`.

| statistic | reported | recomputed from CSV | absdiff |
|---|---:|---:|---:|
| V1 Brier | 0.243003188845701 | 0.243003188845701 | 0.00e+00 |
| V1 Δ Brier (st−v1) | 0.000295537207106443 | 0.000295537207106443 | 0.00e+00 |
| V1 Brier CI low / high | 0.000124598249619274 / 0.000462655756536686 | same | 0.00e+00 |
| V1 log loss | 0.678966541985251 | 0.678966541985251 | 0.00e+00 |
| V1 Δ log loss | 0.000611444950262288 | 0.000611444950262288 | 0.00e+00 |
| V1 log-loss CI low / high | 0.000264509431707938 / 0.000952164616763415 | same | 0.00e+00 |
| V1 CRPS | 0.958754528879680 | 0.958754528879680 | 0.00e+00 |
| V1 Δ CRPS | −0.0000838886751111534 | −0.0000838886751111534 | 0.00e+00 |
| V1 CRPS CI low / high | −0.000466552364028564 / 0.000293061887634418 | same | 0.00e+00 |
| V2 Brier | 0.243007425119528 | 0.243007425119528 | 0.00e+00 |
| V2 Δ Brier | 0.000291300933279186 | 0.000291300933279186 | 0.00e+00 |
| V2 Brier CI low / high | 0.000120926560994869 / 0.000458532418882352 | same | 0.00e+00 |
| V2 log loss | 0.678975446496090 | 0.678975446496090 | 0.00e+00 |
| V2 Δ log loss | 0.000602540439423301 | 0.000602540439423301 | 0.00e+00 |
| V2 log-loss CI low / high | 0.000256181095139917 / 0.000942561830540992 | same | 0.00e+00 |
| V2 CRPS | 0.958791872015834 | 0.958791872015834 | 0.00e+00 |
| V2 Δ CRPS | −0.000121231811265298 | −0.000121231811265298 | 0.00e+00 |
| V2 CRPS CI low / high | −0.000505401964700955 / 0.000256254973753298 | same | 0.00e+00 |

## PIT / KS — reported to 4 dp, recomputed from CSV

| arm | KS home | KS away | mean home | mean away |
|---|---:|---:|---:|---:|
| b5 | 0.0514 | 0.0705 | 0.5105 | 0.5213 |
| st | 0.0438 | 0.0606 | 0.5069 | 0.5179 |
| v1 | 0.0440 | 0.0607 | 0.5098 | 0.5206 |
| v2 | 0.0440 | 0.0606 | 0.5098 | 0.5206 |

Max absolute difference across all PIT/KS values: **4.45e-05** (v2 KS away), i.e. within the
4-decimal rounding of the docs. No PIT mismatch exceeds 5e-5.

## Leakage audit

`verify_leakage_all_arms.py`, independent recompute from the raw DuckDB against
`features_all_arms.csv`:

- **73,176 checks** (36,588 ST PP/PK + 36,588 penalty drawn/taken), **0 mismatches**.
- **0 source-date violations** — every source game's `game_date` is strictly before its target
  game's `game_date`. No game's features use information from that game or later.
- Full output: `verify_leakage_all_arms.out.txt`.

## Verdict restated (conjunctive keep rule, applied to reproduced numbers)

The keep rule requires Brier **and** log loss **and** CRPS to improve over ST with CIs excluding
zero. From the reproduced numbers:

| arm | Brier Δ | log loss Δ | CRPS Δ | keep rule |
|---|---:|---:|---:|---|
| V1 | +0.000295537 [+0.000124598, +0.000462656] ✓ | +0.000611445 [+0.000264509, +0.000952165] ✓ | −0.000083889 [−0.000466552, +0.000293062] ✗ | **FAIL** |
| V2 | +0.000291301 [+0.000120927, +0.000458532] ✓ | +0.000602540 [+0.000256181, +0.000942562] ✓ | −0.000121232 [−0.000505402, +0.000256255] ✗ | **FAIL** |

**Verdict unchanged: penalty-opportunity volume fails the conjunctive keep rule. Not kept.**
The reproduced numbers match the reported numbers exactly, so the verdict does not change. The
2025-negative caveat stands; 2025 is not a holdout.
