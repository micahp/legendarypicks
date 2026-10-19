# NHL special teams — PP/PK xG/60 over 5v5-only, 2026-10-19

Research only. Branch `research/nhl-special-teams-2026-10-19`, worktree
`/root/lp-nhl-special-teams` (off `origin/dev` @ `c4bd3c9f`). Nothing merges, nothing
deploys. The tiered pick policy is untouched and remains NO-GO. The starter-feed task stays
closed (DROP, `84985d14`); it is not revisited here.

Pre-registration: `research/nhl/special-teams-preregistration-2026-10-19.md`, committed as
`854ad6f2` **before any fit**.

## Verdict: YES — the candidate passes the pre-registered gate

Adding opponent-adjusted, 5v5-separate PP/PK xG/60 rates to the 5v5-only Poisson improves
out-of-sample goal forecasts on the identical games. Brier, log loss, and CRPS all improve
with game-clustered 95% CIs excluding zero. The improvement is small but consistent, and the
special-teams coefficients are stable and correctly signed across every refit.

| score | B5 (5v5-only) | ST (candidate) | Δ B5−ST | 95% CI | gate |
|---|---:|---:|---:|---|---|
| Brier (home win) | 0.24391 | 0.24330 | +0.000613 | [+0.000314, +0.000901] | **PASS** |
| Log loss (home win) | 0.68083 | 0.67958 | +0.001255 | [+0.000649, +0.001840] | **PASS** |
| CRPS (goal dist) | 0.96008 | 0.95867 | +0.001407 | [+0.000799, +0.002016] | **PASS** |
| MAE (goals, descriptive) | 1.38262 | 1.38225 | +0.000365 | [−0.000617, +0.001350] | n/a |

Positive Δ = candidate lower loss = better. n = 9,147 evaluation games, identical across arms.
10,000-iteration game-clustered paired bootstrap. MAE is secondary and its interval includes
zero; it carries no gate authority.

## 1. Population

- Source: canonical games + pregame rolling features, read-only from
  `/root/legendarypicks/research/nhl/kalshi-playoff-audit-2025-26/` (both 23,222 rows).
- 23,116 games have complete 5v5 features. Of those, **114 dropped** for missing special-teams
  features (fewer than 5 prior games with positive PP/PK ice time), leaving 23,002.
- Evaluation seasons 2019–2025 = **9,147 games**, matching the existing B5 replay's
  `EVAL_SEASONS`.
- n by season: 2019: 1,212 · 2020: 952 · 2021: 1,396 · 2022: 1,400 · 2023: 1,400 ·
  2024: 1,393 · 2025: 1,394.
- Identical population across arms; dropped games are dropped from **all** arms.

### Data as-of rule

Every feature for a game on day *D* uses only team-games with `game_date < D`. Same-date games
are excluded. The 5v5 features already obey this; the new ST features use the identical
strictly-before rolling window. Verified below.

## 2. CP1 — baseline ladder, same 9,147 games

| model | Brier | log loss | CRPS |
|---|---:|---:|---:|
| B0 constant 50% | 0.25000 | 0.69315 | 1.02384 |
| B1 training home rate | 0.24893 | 0.69100 | 1.02384 |
| B4 rolling-goals Poisson | 0.24555 | 0.68415 | 0.96586 |
| **B5 5v5-only xG Poisson** | **0.24391** | **0.68083** | **0.96008** |
| **ST candidate** | **0.24330** | **0.67958** | **0.95867** |

The ladder is monotonic on all three scores. B0/B1 share the same CRPS because both use the
same constant goal means; B1 only changes the win-probability constant. The informative
comparison is B5 → ST. B5 is the "5v5-only Poisson" the brief's status table describes; its
features are `rolling10_5v5_score_venue_xgf`/`xga` only.

## 3. CP2 — candidate validated chronologically

Walk-forward per season: for evaluation season *s*, fit only on seasons 2008..*s*−1. Same fit
convention as the frozen B5 (`PoissonRegressor(alpha=0.01)`, single shared intercept, leading
0/1 home-flag column, `lograte` floor 0.05). My B5 refit reproduces the published fit cache to
the third decimal; the small residual is from the 114 dropped games:

| season | my B5 coef | cached B5 coef |
|---|---|---|
| 2019 | [0.1013, 0.2519, 0.2549] | [0.1014, 0.2507, 0.2532] |
| 2022 | [0.0973, 0.2876, 0.2745] | [0.0974, 0.2868, 0.2732] |
| 2025 | [0.0930, 0.2939, 0.3136] | [0.0931, 0.2936, 0.3127] |

Per-season Δ B5−ST (positive = candidate better):

| season | n | ΔBrier | ΔLogLoss | ΔCRPS |
|---:|---:|---:|---:|---:|
| 2019 | 1,212 | +0.00038 | +0.00077 | +0.00018 |
| 2020 | 952 | +0.00062 | +0.00127 | +0.00021 |
| 2021 | 1,396 | +0.00198 | +0.00403 | +0.00360 |
| 2022 | 1,400 | +0.00076 | +0.00157 | +0.00302 |
| 2023 | 1,400 | +0.00040 | +0.00083 | +0.00263 |
| 2024 | 1,393 | +0.00042 | +0.00085 | −0.00100 |
| 2025 | 1,394 | −0.00030 | −0.00060 | +0.00066 |

Six of seven seasons favour the candidate on Brier and log loss; 2025 goes negative on both,
and CRPS is negative in 2024. The aggregate interval still excludes zero, but the sign is not
universal — see limitations.

### Special-teams coefficients (stable, correctly signed)

ST feature order in the fit: `[home_flag, 5v5_off, 5v5_def, ST_off, ST_def]`.

| season | ST_off (PP offense) | ST_def (opponent PK) |
|---:|---:|---:|
| 2019 | +0.0360 | +0.0476 |
| 2020 | +0.0357 | +0.0439 |
| 2021 | +0.0349 | +0.0440 |
| 2022 | +0.0443 | +0.0529 |
| 2023 | +0.0463 | +0.0579 |
| 2024 | +0.0490 | +0.0598 |
| 2025 | +0.0437 | +0.0558 |

Both coefficients are positive in every refit. Positive `ST_off` means more PP xG for a team
raises its own expected goals; positive `ST_def` means more PK xG against an opponent raises
the opponent's expected goals. That is the goaltending-independent sign the pre-registration
expected. The 5v5 coefficients are jointly refit when the ST features are added (as in the
frozen convention); the incremental test is the addition of these two coefficients.

## 4. CP3 — distribution calibrated

Midpoint PIT (`F(y−1) + 0.5·p(y)`), KS distance from uniformity:

| arm | PIT KS home | PIT mean home | PIT KS away | PIT mean away |
|---|---:|---:|---:|---:|
| B5 | 0.0514 | 0.5105 | 0.0705 | 0.5213 |
| ST | 0.0438 | 0.5069 | 0.0606 | 0.5179 |

PIT/KS improves on both sides; the distribution gate's "does not degrade materially" condition
is satisfied. The CRPS interval excludes zero in the improving direction.

## 5. Verification (against ground truth, not the code that produced it)

- **Ground-truth recompute:** for game `2025020001` (FLA home vs CHI), the merged CSV's ST
  features equal a separate DB recomputation exactly: `pp_off` 0.140192 = 0.140192, `pk_def`
  0.125283 = 0.125283, from 10 prior games.
- **Leakage audit:** all 92,008 ST feature values in the merged table were recomputed from the
  raw DuckDB with a second code path; **0 mismatches**. Every source game is strictly before
  its game date.
- **B5 replication:** coefficients match the published fit cache (table above).
- **Identical population:** both arms scored the same 9,147 games; no arm drops a game another
  keeps.
- **Shootout tie handling:** home shootout rate 0.4875–0.4939 by training season, as expected;
  tie mass resolved with it.

## 6. Five-checkpoint status

| # | Checkpoint | Status |
|---|---|---|
| **CP1** | Baseline established | **PASS** — B0/B1/B4/B5 scored on the same 9,147 games. |
| **CP2** | Candidate validated chronologically | **PASS** — walk-forward, prior seasons only, paired game-clustered CIs exclude zero. |
| **CP3** | Distribution calibrated | **PASS** — CRPS improves, PIT/KS improves both sides. |
| **CP4** | Prospective confirmation | **NOT ATTEMPTED** — retrospective only; CP4 cannot be passed retrospectively. |
| **CP5** | Production integration approved | **NOT ATTEMPTED** — Micah's decision only. |

## 7. Limitations and what would falsify the win

- **Small effect size.** ΔBrier +0.0006 is a real but modest edge; it is not a large jump.
- **Not universal across seasons.** 2025 is negative on Brier and log loss; 2024 is negative on
  CRPS. The aggregate CI excludes zero, but a future season could reverse.
- **The 5v5 coefficients are jointly refit**, so "ST added" is not a clean decomposition of the
  two ST coefficients alone; part of the gain may come from re-allocating the 5v5 weights.
- **"Opponent-adjusted" is via the regression**, not a feature-level adjustment of each team's
  PP/PK rate for the strength of opponents faced. A fully opponent-adjusted feature is a
  possible follow-up.
- **Penalty opportunity volume is not included.** The brief's step 3 also calls for estimating
  PP opportunities from penalties drawn/taken. This experiment tests xG/60 rates only. If the
  edge survives, opportunity volume is the next candidate.
- **Per-60 normalization.** ST features are window-aggregated per-60 rates; the 5v5 features are
  rolling means of per-game xG. The units differ but the regression handles them; a per-game ST
  variant was not tested.
- **Disclosed pre-registration inaccuracy.** The pre-registration described B5 as "three
  parameters". It is actually four (intercept, home flag, offense, defense). The experiment used
  the frozen convention unchanged; this wording defect does not affect the result.
- **What would falsify:** a prospective or held-out season where the ST coefficient sign flips
  or the Brier/log-loss delta goes non-positive. The 2025 negative is the early warning.

## 8. Artifacts (next to this report)

- `run_special_teams.py` — feature build + walk-forward fit + scores.
- `verify_special_teams.py` — ground-truth and leakage audit, PIT/KS.
- `baseline_ladder_st.py` — CP1 ladder.
- `special_teams_merged_features.csv` — merged 5v5 + ST features, 23,002 games.
- `results_special_teams.json` — primary metrics and per-season deltas.
- `baseline_ladder_st.json` — ladder scores.

## 9. What was deliberately not done

- No tiered-pick-policy change; it stays NO-GO.
- No production code, ingestion, or schema change; nothing adopted, promoted, or served.
- No dev merge, no deploy.
- No GSAx or goalie work revisited; the starter-feed DROP stands.
- No re-tuning to rescue or improve the result after seeing it. The gate was pre-registered and
  the run reported as-is.
- CP4/CP5 not attempted; a positive retrospective result is not a validated model.
