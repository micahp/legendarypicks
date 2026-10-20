# STATE — changes since `46401af1`

Commit `7faef8bb` (on top of `46401af1`; WIP checkpoint `26c02a30`).
Branch `research/fbs-direct-props-2026-10-20`. Research output only — Phases 4/5/6 status unchanged.

Addresses the four defects in `HERMES-FBS-PROPS-CI-2026-10-20.md`:

| # | Defect | What changed | Where |
|---|---|---|---|
| 1 | No CI on CRPS delta | Paired `delta = CRPS_model − CRPS_baseline` for BOTH baselines, bootstrap **clustered on `game_id`** (10,000 resamples, seed 20261020), 90% CI + week-blocks 1–6 / 7–12 / 13+. Verdict rewritten under one signed rule (ADOPT iff ci90_hi < 0 vs both baselines AND every block delta < 0). **888 clusters per market.** | `verdict_2025_clustered.csv`, `RESULTS.md` |
| 2 | cov50/80/90 not reproducible | `predictions_<market>.csv` now store continuous `q05,q10,q25,q50,q75,q90,q95,q99` and per-row `crps_model,crps_baseA,crps_baseB`. cov50=[q25,q75], cov80=[q10,q90], cov90=[q05,q95]. Every headline number recomputes exactly from the CSVs alone. | `predictions_*.csv`, `REPRODUCE.md` |
| 3 | ADOPT for under-dispersed | `r` (count) / `eff_sd` (yards) re-fit by **CRPS minimisation on 2018–2024 only**; 2025 never used in fitting. Before/after reported. | `spread_before_after.csv`, `params.json` |
| 4 | Unstated 2026 board population | Every 2026 prop reconciled; per-filter row drops given. 475/3792/709/5161 → 393/2641/585/3575 scored. | `population_2026.csv` |

## Defect 3 — honest outcome (this is the one with a caveat)

Spread re-fit direction varied by market; the CRPS-minimum is reported as-is:

| market | r / eff_sd | cov90 before → after | CRPS before → after | sd_ratio after |
|---|---|---|---|---|
| pass_attempts | 2.231 → **3.0** (narrower) | 0.8722 → 0.8602 | 2.8332 → 2.8262 | 0.486 |
| passing_yards | eff_sd mult = 1.0 (no change) | 0.9321 → 0.9321 | 20.8795 → 20.8795 | 0.761 |
| rush_attempts  | 2.197 → **2.0** (wider) | 0.9072 → 0.9111 | 1.3785 → 1.3792 | 0.626 |
| rushing_yards | eff_sd mult = 1.0 (no change) | 0.9065 → 0.9065 | 7.6625 → 7.6625 | 0.749 |

- 3 of 4 markets land at/above nominal cov90 after the fix.
- **pass_attempts stays marginally under nominal (0.860).** Within the NB family the CRPS-optimal
  spread and nominal coverage conflict here; the CRPS cost of forcing wider is not paid, so this
  market's *calibration* remains a documented limitation even though its CRPS-delta CI is decisively
  negative. `sd_ratio < 1` on the yards markets coexists with nominal cov90 because pooled residual
  SD includes between-player mean error; coverage (not `sd_ratio`) is the calibration check.
- Verdicts stay CRPS-ranking verdicts; no market/ROI/edge claim is made.

## Verified reproducible (defect 2 spot-check, from the CSVs alone)

pass_attempts: cov90 0.860249, cov50 0.750524, cov80 0.832211, crps_model 2.826241,
crps_baseA 3.150663, crps_baseB 4.842206 — all recompute exactly. Clustered delta baseA
−0.3244 [−0.3448, −0.3036] recomputes from `game_id` clusters.
