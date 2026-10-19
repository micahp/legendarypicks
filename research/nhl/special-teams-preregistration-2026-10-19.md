# Pre-registration — NHL special teams: does PP/PK xG/60 add over 5v5-only?

Committed **before any fit**. Branch `research/nhl-special-teams-2026-10-19`, worktree
`/root/lp-nhl-special-teams` (off `origin/dev` @ `c4bd3c9f`). Research only. Nothing merges,
nothing deploys. The tiered pick policy is untouched and remains NO-GO.

## Question

Do opponent-adjusted, 5v5-separate **power-play and penalty-kill xG/60 rates** improve
out-of-sample goal forecasts over the current 5v5-only input, on identical games?

This is the NHL brief's build-order step 3. The brief's own status table says the B5 5v5 xG
Poisson features "do not yet include power-play or penalty-kill xG" (BRIEF, build order §3 and
baseline ladder B5). The goalie-adjustment experiment already tested a *different* lever
(GSAx) and returned a null; this experiment is about special teams, not goaltending.

## Data present locally (checked before registering)

All data needed is present in `/root/nhl_database_2025-26-playoffs.duckdb`:

- `teams_gamelogs`, 46,444 team-games per situation, seasons 2008–2025.
- Situations: `all`, `5on5`, `5on4` (power play), `4on5` (penalty kill), `other`.
- Relevant columns: `scoreVenueAdjustedxGoalsFor`, `scoreVenueAdjustedxGoalsAgainst`,
  `xGoalsFor`, `xGoalsAgainst`, `shotAttemptsFor`, `shotAttemptsAgainst`, `iceTime`,
  `goalsFor`, `goalsAgainst`, `penaltiesFor`, `penalityMinutesFor`.
- Null check: `scoreVenueAdjustedxGoalsFor/Against` and `iceTime` have **zero** nulls in
  every situation. `5on4` and `4on5` each have 46,444 rows, same as `5on5`.

No "data absent" stop condition. The stop condition in the task ("if the data for PP/PK xG is
not present locally, say so and stop") does **not** trigger.

## Population (stated up front, identical across arms)

- Source of truth: the canonical game table and pregame rolling feature table already used by
  the NHL model work:
  `/root/legendarypicks/research/nhl/kalshi-playoff-audit-2025-26/canonical_games_v1_*.csv`
  and `pregame_rolling_features_v1_*.csv` (read-only; both 23,222 rows).
- A game enters the sample only when `required_features_complete = true` **and** the newly
  built special-teams features are non-null for both teams. Identical row set for every arm;
  no arm drops a game the others keep.
- Evaluation seasons: **2019–2025** (matching the existing B5 replay's `EVAL_SEASONS`), regular
  season and playoffs, so the baseline is directly comparable to the prior published B5 replay.
- Training: strictly prior seasons only. For evaluation season *s*, fit on all complete games
  with season `< s`, from 2008. This is the same walk-forward split the existing replay uses.
- n by season (feature-complete games already on disk; ST features are derived from the same
  complete team-games, so the final counts should match):

| season | n (feature-complete) |
|---:|---:|
| 2019 | 1,212 |
| 2020 | 952 |
| 2021 | 1,396 |
| 2022 | 1,400 |
| 2023 | 1,400 |
| 2024 | 1,393 |
| 2025 | 1,394 |
| **2019–2025 total** | **9,147** |

### Data as-of rule

Every feature for a game on day *D* uses only team-games with `game_date < D`. Same-date games
are excluded (the existing builder's `rolling_mean_before` rule). No season-to-date total that
includes the game being scored is used. The 5v5 features already obey this; the new ST features
will be built with the identical strictly-before-game rolling window and the same source-date
audit fields (`home_max_feature_source_date`, `home_feature_source_game_ids`).

## Arms (identical games, same fit/predict convention)

### Baseline — B5, "5v5-only Poisson" (frozen, unchanged)

This is the existing frozen production convention in `run_pipeline.py` / `run_backtest.py`:
one shared intercept and two shared coefficients fit by `PoissonRegressor(alpha=0.01)`.

- home goals: `exp(a + b_off·log(home_rolling10_5v5_score_venue_xgf) + b_def·log(away_rolling10_5v5_score_venue_xga))`
- away goals: `exp(0 + b_off·log(away_rolling10_5v5_score_venue_xgf) + b_def·log(home_rolling10_5v5_score_venue_xga))`

The intercept is the home advantage; home and away share `b_off`/`b_def`. Three parameters.
This is exactly the arm already published as `B5_xg_poisson`; call it what it is.

### Candidate — B5 + special-teams xG/60

Adds **four** features to the same fit, using the same frozen convention:

- home goals add: `log(home_rolling10_5on4_score_venue_xgf_per60)` and
  `log(away_rolling10_4on5_score_venue_xga_per60)`
- away goals add: `log(away_rolling10_5on4_score_venue_xgf_per60)` and
  `log(home_rolling10_4on5_score_venue_xga_per60)`

where the new rolling features are **window-aggregated per-60 rates** over the last up-to-10
prior team-games:

- `home_rolling10_5on4_score_venue_xgf_per60 = 60 · Σ(scoreVenueAdjustedxGoalsFor | 5on4) / Σ(iceTime | 5on4)`
- `home_rolling10_4on5_score_venue_xga_per60 = 60 · Σ(scoreVenueAdjustedxGoalsAgainst | 4on5) / Σ(iceTime | 4on5)`

and symmetrically for the away team. "Opponent-adjusted" is operationalised through the
regression: the home-goal rate loads on the home team's PP offense **and** the away team's PK
defense, so the fitted rate already conditions on the opponent's special-teams strength. No
separate iterative opponent-adjustment of the feature itself is done in the primary candidate
(that is a possible follow-up, not this test).

Five parameters total (intercept, 5v5 off, 5v5 def, ST off, ST def). The only change from B5
is the two special-teams coefficients — one lever, one experiment.

## Chronology rule

- Refit per evaluation season on strictly prior seasons. No future information leaks into a
  coefficient.
- Same fit/predict convention as B5 (single shared intercept; `alpha=0.01`; identical
  `lograte` floor of 0.05; identical Poisson score derivation).
- Score every arm on the **identical** set of evaluation games; a game with a missing feature
  in any arm is dropped from all arms.

## Proper scores and intervals (registered now)

Primary outcome scores, computed on the same games for B5 and the candidate:

1. **Brier** on home-win probability (home win = 1).
2. **Log loss** on home-win probability.
3. **CRPS** on the per-team goal distribution (home goals and away goals), from the independent
   Poisson joint matrix already used by the replay. Discrete midpoint convention for zero mass.

Intervals: **game-clustered paired bootstrap**, 10,000 iterations, resampling by game (cluster),
95% CI on `baseline − candidate` (positive = candidate better/lower score). Clustering by game
is required because both teams in a game and repeated matchups are not independent.

Secondary / descriptive only: goal MAE, PIT/KS uniformity for the goal distributions, and the
fitted special-teams coefficients with their sign. These do not carry the gate.

## Fail-closed gate (registered now, before any fit)

The candidate is **rejected** unless it clears the gate:

- **Primary gate (win probability):** Brier AND log loss both improve, with 95% game-clustered
  paired CIs excluding zero in the improving direction.
- **Distribution gate (goals):** CRPS improves with its 95% CI excluding zero in the improving
  direction, and PIT/KS does not degrade materially on either side.
- **Identical population:** n is identical across arms; a mismatch invalidates the run.
- **Chronology:** no feature computed with information from the game being scored; audited via
  the max source date per row.
- **Fail-closed:** if any primary CI includes zero, the candidate fails. There is no
  "close enough", no re-tuning, no second shrinkage constant.

### Falsifiers — what "no" and "unclear" mean

Written before the run:

- **"No" (candidate fails):** any primary or distribution CI includes zero. The task's rule is
  explicit: *if the CI includes zero, the answer is no and it is recorded as no.* A point
  estimate that favours the candidate but whose interval includes zero is **not** evidence; it
  is "unclear", and "unclear" is recorded as **no**.
- **"Yes" (candidate passes):** Brier, log loss, and CRPS all improve with CIs excluding zero in
  the improving direction, on the identical population, with the chronology audit clean.
- **"Unclear" (recorded as no):** sign favourable but interval includes zero, or scores move in
  opposite directions, or the population is not identical across arms.
- **Direction check:** a positive coefficient on PP offense and on PK defense would be the
  expected goaltending-independent sign (more PP xG ⇒ more goals for; more PK xG against ⇒ more
  goals against). A fitted sign opposite to that is reported, not hidden, and counts against the
  candidate as evidence of overfit even if a score improves.

## Five-checkpoint block (from MODEL-CHECKPOINTS.md)

| # | Checkpoint | This experiment |
|---|---|---|
| **CP1** | Baseline established | B0 constant 50%, B1 training home rate, B4 rolling-goals Poisson, and **B5 5v5-only xG Poisson** all scored on the same 9,147 evaluation games. Floor, not a leaderboard. |
| **CP2** | Candidate validated chronologically | Walk-forward per season on prior seasons only; paired, game-clustered intervals; identical population. Passes only if the gate above clears. |
| **CP3** | Distribution calibrated | CRPS plus PIT/reliability on identical observations; per-game PMFs preserved. Point accuracy is not calibration. |
| **CP4** | Prospective confirmation | **Not attempted.** This is retrospective. CP4 cannot be passed retrospectively. |
| **CP5** | Production integration approved | **Not attempted.** Micah's decision only. Nothing merges. |

CP1–CP3 are in scope here. CP4–CP5 are explicitly not. A failed gate is still a completed
experiment and will be documented as one, numbers and all.

## What would change my mind / what I will not do

- I will **not** re-run with different shrinkage, different windows, or a different feature set
  to rescue a null. A different candidate needs a new pre-registration.
- I will **not** delete or hide the pre-registration if the candidate fails.
- I will **not** touch the tiered pick policy (NO-GO), production code, or the prospective
  ledger.
- If the special-teams coefficients are unstable across refits or flip sign, that is reported as
  a fail mode, not tuned away.
- The pre-registration document is frozen after this commit. Any later change is disclosed in
  the feasibility report and the learnings log, not silently edited.

## Exact artifacts to be produced

- `research/nhl/special-teams-feasibility-2026-10-19.md` — the report.
- `research/nhl/special-teams-2026-10-19/` — the run script and JSON results next to it.
- `research/nhl/LEARNINGS.md` — appended entry.
