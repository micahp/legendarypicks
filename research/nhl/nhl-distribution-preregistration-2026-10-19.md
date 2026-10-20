# Pre-registration — NHL distribution-level model (joint over the final score), 2026-10-19

Branch `research/nhl-distribution-2026-10-19`, worktree `/root/lp-nhl-distribution`, off `dev`
@ `ad674e13`. Research only. Nothing merges, nothing deploys. Step 1 is this document: **no fit,
no score, no gates run.** The tiered pick policy stays NO-GO.

**Estimability: the joint parameterisation can be estimated from data on disk.** There are
23,222 canonical games with recorded home/away goal pairs (2008–2025), 23,116 of them with
complete pregame 5v5 features, and 2,079,359 located shots with per-shot `xGoal`. The model does
**not** require a pre-puck-drop starting-goalie signal (see §1), so the "cannot be estimated"
stop condition does not trigger.

## 1. The starter-goalie question, answered plainly

The distribution model **does not need a pre-puck-drop starting-goalie signal to be estimated.**
A joint over (home goals, away goals) is driven by team attack/defence, pace, home ice and rest
— all estimable from data on disk. A confirmed starter would sharpen the goal-against marginal,
but the measured goalie lever is small: the goalie-adjustment work fitted a GA-rate multiplier of
0.968–1.020 (±2–3% GA), and its distribution gate passed (CRPS improved, PIT improved) with no
real starter feed. The starter-feed task is closed as **DROP** (`84985d14`): no free, reliable,
historical pre-puck-drop feed exists.

Therefore: starter identity / GSAx is **excluded as an input** (§8), the resulting limitation on
goal-against sharpness is stated, and the model proceeds. This is not a claim that goaltending
does not matter — it is a claim that the joint is estimable without it and that the omission is
bounded by the measured ±2–3% GA lever.

## 2. Question

Does a **complete, coherent joint distribution over the final score** beat the independent-Poisson
incumbent and the no-vig closing market on proper scores and calibration, on identical games, with
the dependence structure explicitly modelled?

This is the next stage after the point-forecast levers. The incumbent joint already exists in
`research/nhl/model-call-research-2026/run_backtest.py` (independent Poisson; NB marginals;
Dixon-Coles; common-shock bivariate Poisson as an exploratory candidate). This pre-registration
formalises one candidate, one dependence structure, and the gates, before any fit.

## 3. Data on disk

- **Canonical games:** `canonical_games_v1_7cd2fc9a6e84470c.csv` (23,222 games, 2008–2025),
  with `home_goals_model_target` / `away_goals_model_target` (regulation + OT goals, shootout
  decider excluded), `official_home_score` / `official_away_score` (official final, shootout
  decider included), `official_home_winner`, `last_period_type`, `neutral_site`.
- **Pregame features:** `pregame_rolling_features_v1_62dcceb77085bc59.csv` (23,222 rows;
  rolling 10-game 5v5 score-venue xGF/xGA, shot attempts, all-situation goals, `days_rest`,
  `days_since_previous_game`, feature-source dates and game ids, `required_features_complete`).
- **Located shots:** `shots`, 2,079,359 rows, 2007–2025, with coordinates, angle, distance,
  shot type, `xGoal`, `goalieIdForShot` (MoneyPuck-derived, in
  `/root/nhl_database_2025-26-playoffs.duckdb`).
- **Special teams xG:** the ST work's per-game ST features (PP/PK xG/60). Passed the ST
  conjunctive keep rule but **not adopted**; CRPS worsened. Available as a registered secondary
  input only.
- **Market benchmark (new, wired into these gates):** `docs/NHL-MARKET-BENCHMARK-SBR.md` and
  `research/nhl/sbr-odds-archive-2026-10-19/games_2018_2023.jsonl.gz` (dev `ad674e13`).

## 4. Population — games with a recorded final score

All 23,222 canonical games carry a recorded final score (no game lacks it). Exclusions, as
counts, with the rule stated:

| exclusion | count | rule |
|---|---:|---|
| incomplete 5v5 pregame features (`required_features_complete` false) | 106 | dropped from every arm |
| **primary model population** | **23,116** | complete 5v5 features |
| additionally missing complete ST features (secondary ST-input arm only) | 114 | ST arm only; never dropped from the primary |
| primary ST-input population | 23,002 | complete 5v5 **and** ST features |
| empty `days_rest` | 19 | only matters for the rest/B2B arm; reported, not silently imputed |
| neutral-site games | 0 | none in this data |
| playoff games (`game_type=3`) | 1,614 | reported separately; the market sub-population is regular season |

- **P_model** (CRPS, coverage, model-vs-incumbent): all complete-feature games, regular season and
  playoffs, counted per season. Playoff and regular-season results are reported separately and
  pooled.
- **P_market** (posted-line over/under and the market benchmark): the intersection of P_model with
  the SBR complete games (regular season, 2018-19..2022-23). The final intersection count is
  reported at run time after the team crosswalk; pre-registered counts are in §9.

Every exclusion is a count, not a silent drop. No arm may drop a game another arm keeps.

## 5. Splits and chronology

- **Fit on seasons strictly before the evaluated season.** For evaluation season *s*, fit on all
  complete games with canonical `season < s`, from 2008. No future information enters a coefficient
  or a dependence parameter.
- **Designated evaluation season: 2025-26** (canonical `season = 2025`, 1,312 regular + 82 playoff).
- **Forward only: 2026-27** (canonical `season = 2026` and later). The prospective-2026-27 ledger
  is forward; nothing here writes to it.
- **Inspected development data, stated plainly:** canonical seasons **2008–2024** were used in
  prior NHL research (goalie, ST, model-call). **2025-26 was also inspected** in the ST and goalie
  work, so the designated evaluation season is **development-contaminated** and cannot pass CP4.
  The only genuinely forward data is 2026-27 onward.
- **Market-benchmark seasons: 2018-19..2022-23** (= canonical seasons 2018..2022) are therefore
  development data. The market comparison is a quality check, not confirmation.
- **2022-23 is partial** (339 complete SBR games of ~1,312). It is labelled in every table and
  excluded from the pooled-without-partial robustness figure (the doc's pooled 0.23554 includes it;
  both are reported).

## 6. Parameterisation — the joint over (home goals, away goals)

**Object.** For each game *g*, a joint probability mass function
`P_g(H = h, A = a)` over non-negative integers, with support truncated at `h, a ≤ 15` (mass
outside is negligible; the truncation is reported and renormalised).

**Coherence.** The model is over the **pair**, not over total and margin separately. For every
simulated or evaluated game:

- `total_g = H_g + A_g`
- `margin_g = H_g − A_g`

hold **by construction**, so total and margin are exact deterministic functions of the pair and
every derived market comes from the one object. A separate `total` fit and `margin` fit are
explicitly not used.

**Primary parameterisation: common-shock bivariate Poisson** (Karlis–Ntzoufras 2003). For game *g*
with parameters `(λ1g, λ2g, λ3g)`, `λ3g ≥ 0`:

```
P(H=h, A=a) = exp(−(λ1+λ2+λ3)) · Σ_{k=0}^{min(h,a)}
              λ1^(h−k) λ2^(a−k) λ3^k / ((h−k)! (a−k)! k!)
```

with `E[H] = λ1 + λ3`, `E[A] = λ2 + λ3`, and `Cov(H, A) = λ3`. Marginals are Poisson. The pair
mean structure is set by a log-link Poisson regression on pregame features:

```
E[H_g] = μ_hg = exp(β0 + x_hg · β)
E[A_g] = μ_ag = exp(0    + x_ag · β)
```

matching the frozen convention used across the NHL work (shared intercept, leading home flag,
`PoissonRegressor(alpha=0.01)`), so `λ1 = max(μ_h − λ3, ε)`, `λ2 = max(μ_a − λ3, ε)`. When
`μ_h < λ3` or `μ_a < λ3` the constraint binds; the count of binding games is reported, and if it
is material the shared-Gamma alternative in §7 is used instead.

**Derived objects.** The **statistical** score pair is `(H, A)` (regulation + OT goals, shootout
decider excluded). The **official** pair is deterministic given the statistical pair and the
shootout outcome:

- REG / OT: official = statistical (verified: 17,855 REG and 3,226 OT games have
  `official_total − statistical_total = 0`).
- SO: official total = statistical total + 1; statistical margin = 0, official margin = +1 if the
  home team wins the shootout, −1 if the away team does. (Verified: exactly the 2,141 SO games,
  diff +1 in total; margin diff +1 for 1,054 and −1 for 1,087.)

So the official joint is the statistical joint with the SO tie mass split by the home shootout
rate `so_home`, estimated on training seasons only.

## 7. Dependence structure and estimation

**Structure.** Positive within-game dependence via a shared shock: `Cov(H, A) = λ3 ≥ 0`, i.e. a
high-event game raises both teams' scoring. This is the only free dependence parameter and it
nests the independence incumbent at `λ3 = 0`.

**Estimation.**

- The regression coefficients `β` are fit by Poisson maximum likelihood on training games, the
  same estimator family and `alpha = 0.01` as the frozen candidates.
- `λ3` is estimated by **maximum likelihood on the training goal pairs** at the fitted means
  (a one-dimensional optimisation), and reported with its training profile-likelihood interval.
  The method-of-moments estimate (training residual covariance) is reported as a diagnostic.
- `so_home` is the training-window home shootout win rate. It is recomputed per evaluation season
  on strictly prior seasons.
- Absent a positive, identified `λ3`, the registered fallback is the **shared-Gamma latent
  (bivariate negative-binomial)** model: `u_g ~ Gamma(θ, θ)`,
  `H|u ~ Poisson(μ_h u)`, `A|u ~ Poisson(μ_a u)`, so `Cov(H,A) = μ_h μ_a / θ` and marginals are NB2.
  The fallback is used only if §11·F1 fires, and is disclosed as such.

`λ3` is a single scalar per fit window, not a per-game feature. A game-state-dependent dependence
term is out of scope.

## 8. Inputs — used and excluded

**Used (primary arm):**

| input | source | reason |
|---|---|---|
| 5v5 score-venue-adjusted xGF/xGA, rolling 10 | `pregame_rolling_features` | team attack/defence, shot-quality adjusted |
| shot attempts for/against, rolling 10 | same | pace/volume |
| all-situation goals for/against, rolling 10 | same | finishing context |
| days rest / back-to-back | `days_since_previous_game` ≤ 1 | schedule/fatigue |
| home ice | home-row intercept | venue |
| pregame Elo | chronological replay, k=10, HFA=35 | team-strength reference (variant arm) |

**Used (registered secondary arm only):** special-teams PP/PK xG/60. Included because it is a
pregame signal for goals scored outside 5v5; **not adopted** and not treated as the baseline. The
primary gates are against the independent-Poisson incumbent, not against ST.

**Deliberately excluded:**

| input | reason |
|---|---|
| starting-goalie identity / GSAx | no reliable pre-puck-drop signal; lever is ±2–3% GA (§1). Would sharpen, not enable, estimation. |
| market prices (open or close) | benchmark only; using them as features would make the benchmark circular. Never joined into features. |
| standings points / points% | prior model-call work found no predictive value beyond Elo |
| any postgame or same-game information | leakage. The `max_feature_source_date` audit must show every source game strictly before the target. |

## 9. Market benchmark (SBR) — wired into the gates

Source: `research/nhl/sbr-odds-archive-2026-10-19/games_2018_2023.jsonl.gz`; doc
`docs/NHL-MARKET-BENCHMARK-SBR.md`. 5,132 rows, **5,131 complete** on moneyline open/close,
puck line, and total open/close. One row per game with per-side fields `team, final, ml_open,
ml_close, puck_line, puck_price, ou_open, ou_open_price, ou_close, ou_close_price`.

**Benchmark number.** No-vig closing moneyline Brier pooled over the 5,131 complete games =
**0.23554** (per season: 2018-19 0.24150 · 2019-20 0.24323 · 2020-21 0.23169 · 2021-22 0.22562 ·
2022-23 0.23897). Complete per season: 1,358 / 1,082 / 951 / 1,401 / 339.

**Season mapping.** SBR `2018-19..2022-23` = canonical seasons `2018..2022` (season field is the
start year; canonical season 2018 = 1,358 games and season 2021 = 1,401 both match SBR exactly).

**Join.** SBR team spellings (`SanJose`, `TampaBay`, `SeattleKraken`, …) require a committed
crosswalk to canonical codes; the join key is season + date + both teams. Unmatched games are
excluded and **counted**. The final paired-game count is reported and must equal the market
count in the comparison table (no silent drop). The crosswalk artifact is a deliverable.

**Comparison rules (binding):**

1. The model's moneyline probability is compared against the **no-vig closing** moneyline on the
   **identical games**, as a **paired** difference (market Brier − model Brier), game-clustered
   bootstrap, 2,000 reps, seed `20261019`, 95% CI. Per season and pooled.
2. **Closing price is a benchmark only.** Opening price is used only for a separate
   open-vs-close movement study (does the model agree more with the opener or the close?).
3. **There is no intraday timestamp.** The archive has open and close only. **Never** present a
   closing price as a price the model could have taken earlier, and never claim a bettable
   historical price. Any strategy result must state whether it used open or close.
4. **2022-23 is partial** (339 complete). Labelled in every table; the pooled-without-2022-23
   figure is reported alongside the doc's pooled 0.23554.
5. Market prices are **never** model features.

The market comparison is on development seasons (§5) and therefore cannot pass CP4.

## 10. Gates, declared before any fit

All bootstrap intervals are game-clustered, 2,000 reps, seed `20261019`, 95%, paired where
like-for-like. No accuracy metric, no threshold moved, no gate loosened.

- **G1 — joint proper score.** CRPS on the statistical score pair `(H, A)`, per season and pooled,
  candidate vs the independent-Poisson incumbent **I0** (identical marginal regression, `λ3 = 0`).
  Pass = pooled CRPS improves with the clustered CI excluding zero. The score-pair CRPS is the
  primary joint gate.
- **G2 — PIT and coverage for home, away, total, margin.** Shortest-interval coverage is the
  **primary** statistic (nominal 50% / 80% / 90%); central coverage is a **diagnostic**. Tolerance
  ±0.05 on the shortest-interval coverage. PIT-histogram KS uniformity is a diagnostic. `total` and
  `margin` use the market-settled official basis (`total = H+A+1{SO}`, `margin` SO-resolved by
  `so_home`); the statistical-basis variants are reported as diagnostics. Pass = all four
  quantities within ±0.05 at all three nominal levels.
- **G3 — over/under Brier and log loss at posted lines.** At the totals and puck-line margins
  actually posted in SBR (`ou_close` line and price; `puck_line` and `puck_price`), compute Brier
  and log loss for the model's over/under and cover probabilities against the official final. The
  market's own no-vig price for the same line is the paired benchmark. Pass = reported; the
  model-vs-market paired CI is the evidence.
- **G4 — market benchmark.** Model no-vig-basis moneyline Brier vs the no-vig closing moneyline
  Brier on the identical SBR games, per season and pooled (pooled market = **0.23554**), paired
  clustered CI. Pass = the model is not materially worse; a CI excluding zero with the model worse
  triggers §11·F4.
- **G5 — coherence invariant.** For every evaluated game, `total = H+A` and `margin = H−A` on the
  statistical pair, and the official pair equals the statistical pair with SO mass split by
  `so_home`. A single mismatch is a bug and stops the run.

## 11. Falsifiers — stated in advance

- **F0 (estimability):** if the joint cannot be estimated from data on disk, stop. Not triggered:
  §3 shows the goal pairs and features exist.
- **F1 (dependence not identified):** if the training-profile interval for `λ3` includes 0, or
  `λ3` is not positive in a majority of fit windows, the joint is indistinguishable from
  independence. Switch to the §7 fallback once; if that also fails to identify dependence, **stop**.
- **F2 (joint no better):** if pooled CRPS vs I0 does not improve with a clustered 95% CI excluding
  zero → **no**.
- **F3 (miscalibration):** if shortest-interval coverage deviates by more than ±0.05 at any nominal
  level for home, away, total or margin → **no**.
- **F4 (no market edge):** if the model's moneyline Brier is worse than the no-vig close with the
  paired clustered CI excluding zero in the wrong direction → **no** on the market claim.
- **F5 (incoherent joint):** any G5 mismatch → bug; stop and report, do not tune.
- **"Unclear" is "no":** a favourable point estimate whose interval includes zero is recorded as
  **no**, never as a pass.

A failed gate is a completed experiment: documented with its numbers, not deleted, not re-run with
different settings. A different candidate needs a new pre-registration.

## 12. Five-checkpoint block (MODEL-CHECKPOINTS.md)

| # | Checkpoint | This experiment |
|---|---|---|
| **CP1** | Baseline established | I0 independent Poisson, B5/B7 frozen candidates, and the no-vig market all scored on the same games with sample sizes. |
| **CP2** | Candidate validated chronologically | Walk-forward, prior seasons only, paired clustered intervals, identical games. |
| **CP3** | Distribution calibrated | CRPS + PIT + shortest-interval coverage for home, away, total, margin on identical observations. |
| **CP4** | Prospective confirmation | **Not attempted.** 2025-26 is development-contaminated (§5); only 2026-27 onward is forward. |
| **CP5** | Production integration | **Not attempted.** Micah's decision only. |

## 13. Rules and out of scope

- Prereg committed and pushed **before any fit or score**. Deviation = stop and report.
- No gate loosening, no thresholds moved, no accuracy metrics, no post-hoc rescue, no promotion.
- Nothing adopted, nothing deployed, no production writes; the tiered pick policy stays NO-GO.
- The ST result is not adopted and is not the baseline.
- A pass is a research result only; the decision is Micah's.

## 14. Artifacts to be produced (later steps, not this one)

- This pre-registration (committed and pushed first).
- `research/nhl/sbr-team-crosswalk-2026-10-19.csv` — SBR-name → canonical-code crosswalk.
- The fitted model script, per-game joint artifacts, and a results JSON.
- A results report `research/nhl/nhl-distribution-report-2026-10-19.md`, with the CRPS/coverage/
  posted-line/market tables and the falsifier outcomes.
