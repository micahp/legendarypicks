# Pre-registration — NHL penalty-opportunity volume on top of ST

Committed **before any fit**. Branch `research/nhl-special-teams-2026-10-19`, worktree
`/root/lp-nhl-special-teams`. Research only. Nothing merges, nothing deploys. Tiered pick
policy untouched (NO-GO). The ST result and its auditability (Step A) are frozen at
`8616b528`; this is a new lever on top of ST, not a revision of it.

## Question

Do penalty-opportunity volume features — penalties drawn and taken per 60 — improve the
already-passing ST candidate's out-of-sample goal forecasts? **Judged against ST, not B5.**

The ST candidate added PP/PK xG/60 *rates* but not PP *opportunity volume*. The brief's step 3
formula is `E[PP goals] = E[PP minutes] × adjusted PP xG/60`, so volume is the missing factor.
This experiment tests whether adding it helps beyond ST.

## Data facts checked before registering

`teams_gamelogs`, situation `all`, seasons 2008–2025, zero nulls on all four penalty columns.

- `penaltiesFor` = penalties **taken** by the team (committed). Correlates 0.684 with the team's
  own PK time (`4on5` iceTime).
- `penaltiesAgainst` = penalties **drawn** by the team (committed by the opponent). Correlates
  0.684 with the team's own PP time (`5on4` iceTime).
- Verified across all 23,107 games: `home.penaltiesFor == away.penaltiesAgainst` in every game.
  So "drawn by a team" and "taken by its opponent" are the same event; a team's own PP
  opportunity is its `penaltiesAgainst`.
- `iceTime` is elapsed situation seconds (`all` averages ~3,657 s ≈ 61 min; `5on4`/`4on5`
  ~296 s ≈ 5 min). Rates use the same convention as the ST features:
  `rate = 60 · Σ(penalties) / Σ(iceTime_seconds)`.

## Population

Identical to the ST experiment and to its Step A artifact: the **9,147** feature-complete
evaluation games, seasons 2019–2025, same `merged` row set, same drop rule (a game missing a
feature in any arm is dropped from all arms). No game added or removed for this experiment.

**2025 is NOT a clean holdout.** It was inspected in the ST experiment and its per-season delta
is already published. It is reported per season here but cannot confirm or falsify on its own.

## Features (window and shrinkage fixed)

For team *t* and game on day *D*, over the last up-to-10 prior team-games with
`game_date < D` (same strictly-before window as ST), requiring ≥5 prior games:

- `drawn_per60 = 60 · Σ(penaltiesAgainst) / Σ(iceTime)` — the team's PP opportunity volume.
- `taken_per60 = 60 · Σ(penaltiesFor) / Σ(iceTime)` — the team's PK opportunity volume.

**Shrinkage: none.** Both variants use raw window-aggregated rates. Penalty counts over 10 games
(~38 drawn, ~38 taken) are not small; no empirical-Bayes shrinkage is applied to either variant.

## Arms (same walk-forward harness, same frozen convention)

Baseline for this experiment: **ST** = the passing candidate
(`[1.0, hx, axga, hpp, apk]` home, `[0.0, ax, hxga, app, hpk]` away), frozen exactly as in
`run_special_teams.py`.

### V1 — ST + penalties drawn per 60 (primary)

- Home row: `[1.0, hx, axga, hpp, apk, home_drawn_per60]`
- Away row: `[0.0, ax, hxga, app, hpk, away_drawn_per60]`
- 1 new coefficient, shared across rows. **Expected sign: positive** (more PP opportunity →
  more goals for the team). Opponent-adjustment is structural: the home row loads on the home
  team's drawn penalties, which are exactly the away team's taken penalties.

### V2 — ST + drawn and taken per 60 (secondary)

- Home row: `[1.0, hx, axga, hpp, apk, home_drawn_per60, home_taken_per60]`
- Away row: `[0.0, ax, hxga, app, hpk, away_drawn_per60, away_taken_per60]`
- 2 new coefficients. **Expected signs: drawn positive, taken negative** (a team shorthanded
  scores less). Note: `taken` and the opponent's `drawn` are mirror events, so V2's two new
  columns are not collinear but are structurally linked; if the coefficients are unstable or
  wrongly signed, that is reported as a fail mode. V2 is exploratory only and carries no gate.

No other change. The 5v5 and ST coefficients are jointly refit as before; the incremental test
is the new penalty coefficients.

## Chronology and scoring

- Walk-forward per evaluation season; fit on strictly prior seasons from 2008; identical graded
  games across ST, V1, V2.
- Same Poisson fit (`PoissonRegressor(alpha=0.01)`, shared intercept, leading 0/1 home flag,
  `lograte` floor 0.05) and same shootout tie resolution as ST.
- Proper scores: **Brier** and **log loss** on home win, **CRPS** on the goal distribution.
- Intervals: **game-clustered paired bootstrap**, 10,000 iterations, seed 20261019, 95% CI on
  `ST − candidate` (positive = candidate better).
- Secondary/descriptive: goal MAE, PIT/KS, fitted penalty coefficients. No gate authority.

## Gate (registered now, before any fit)

The penalty candidate is **kept** only if it beats **ST**:

- **Primary:** Brier AND log loss both improve over ST with 95% game-clustered CIs excluding zero
  in the improving direction.
- **Distribution:** CRPS improves over ST with its CI excluding zero, and PIT/KS does not degrade.
- **Identical population:** n identical across ST/V1/V2; a mismatch invalidates the run.
- **Fail-closed:** if any primary CI includes zero, the answer is **no** and it is recorded as no.
  "Unclear" (favourable sign, interval includes zero) is recorded as no.

## Falsifiers — what "no" and "unclear" mean

- **"No":** any primary or distribution CI includes zero; or the penalty coefficients are
  unstable/wrongly signed across refits; or the population is not identical.
- **"Yes":** Brier, log loss, and CRPS all improve over ST with CIs excluding zero, population
  identical, coefficients stable and correctly signed.
- **"Unclear" → no:** point estimate favourable but interval includes zero, or scores move in
  opposite directions.
- **Sign check:** a negative or unstable `drawn` coefficient, or a positive `taken` coefficient,
  counts against the candidate even if a score improves.

## Five-checkpoint block

| # | Checkpoint | This experiment |
|---|---|---|
| **CP1** | Baseline established | ST is the established baseline here (it already cleared B5); B0–B5 remain documented from the ST run. |
| **CP2** | Candidate validated chronologically | Walk-forward, prior seasons only, paired game-clustered intervals, identical games. |
| **CP3** | Distribution calibrated | CRPS + PIT/KS on identical observations. |
| **CP4** | Prospective confirmation | **Not attempted.** 2025 is not a clean holdout; retrospective only. |
| **CP5** | Production integration | **Not attempted.** Micah's decision only. |

## Integrity and scope

- Same walk-forward harness and frozen convention as ST. No gate or threshold change. No
  retuning, no post-hoc rescue, no promotion. A pass is a research result only; nothing is
  adopted and the decision is Micah's.
- The pre-registration is frozen after this commit. Any later change is disclosed in the report
  and the learnings log, not silently edited.
- Deliberately not done: no tiered-pick-policy change, no production/ingest change, no dev merge
  or deploy, no GSAx revisit, no change to the ST result or its Step A artifact.

## Artifacts to be produced

- `research/nhl/special-teams-penalty-report-2026-10-19.md`
- `research/nhl/special-teams-2026-10-19/run_penalty_volume.py`
- `research/nhl/special-teams-2026-10-19/results_penalty_volume.json`
- `research/nhl/special-teams-2026-10-19/forecasts_penalty.csv`
- appended `research/nhl/LEARNINGS.md`
