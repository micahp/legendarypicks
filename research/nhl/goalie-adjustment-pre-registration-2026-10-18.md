# Pre-registration — NHL goalie adjustment (build-order step 2, G2 candidate)

Branch `research/nhl-goalie-adjustment-2026-10-18`. Frozen **before any model code runs**.
Written from the Step 0 audit (`goalie-data-audit-2026-10-18.md`), which found located
shot-level data (MoneyPuck-derived `shots`, 2.08M rows, 2007–2025) and **no pre-puck-drop
starter feed** — the expected-starter signal must be estimated and the limitation is carried
through as a stated constraint, not patched over.

## G1 baseline (must exist before G2)

G1 = the league-average-goalie baseline. Goals-against rate for team *i* in game *g* is a
Poisson rate built from rolling team offence/defence form (the B5 xG-Poisson family already in
use) with **no goalie term**. Both teams' GA forecasts in G1 use the same league-average
goalie. G1 is frozen (feature spec + window) before G2's coefficient is fit.

## G2 candidate — pre-registered features

G2 = G1 plus a multiplicative goalie adjustment to each team's goals-against rate:

    GA_rate_i(g) = GA_rate_G1_i(g) × exp(κ · goalie_score_i(g))

`goalie_score_i(g)` is built only from the expected starter's **prior appearances** (strictly
before game *g*; chronological, no same-game data).

1. **Regressed GSAx (primary feature).** Per goalie per prior game, from `shots`:
   `GSAx_g = xGoals_against_g − goals_against_g` (both from `shots.xGoal` / `shots.goal`,
   attributed via `goalieIdForShot`). GSAx already conditions on shot difficulty (location,
   angle, shot type) because it is measured against xG. **Interpretation of "shot difficulty"
   in G2: it enters through the xG denominator — no separate raw-SV% term is added.** This is
   the shot-difficulty adjustment the brief asks for, and it is stated here so it cannot be
   silently swapped.
2. **Empirical-Bayes shrinkage (form fixed now).** Per goalie, before game *g*:
   `regressed_rate = (Σ GSAx_prior + k·league_mean_rate) / (n_prior_shots + k)`
   with `k = 1500` shots (≈ 75 goalie-games at ~20 SOG/game), `league_mean_rate` = league-wide
   (xG−goal)/shot over the prior 3 seasons, recomputed each season. The shrinkage target and
   the constant are stated now and not tuned after results.
3. **Expected starter.** No pre-game lineup feed exists. Starter predicted as: the goalie on
   the team who made the team's most recent prior start, unless he played the previous day
   (back-to-back), in which case the other goalie on the roster with ≥1 prior start that
   season. This is a *predicted* starter, labelled as such. **Post-confirmation variant**: the
   same forecast recomputed using the observed starter for that game (only for the movement
   comparison; the primary scored object is the pre-confirmation forecast).
4. **Workload / fatigue (secondary, only if it improves validation):** rest days since last
   start, prior-start count this season. Declared now; inclusion is a validation-gated choice,
   not a post-hoc add.

## Chronology rule

For every game *g* and every goalie, all inputs to `goalie_score_i(g)` come from games strictly
before *g* in the same or earlier seasons. No aggregate that includes game *g* is touched.
Violation fails the run.

## Pre-registered windows

- **Train:** seasons 2008–2022 (goalie-score construction + G2 coefficient κ).
- **Validation:** season 2023 — used once, for the optional secondary-feature decision and for
  reporting, not for gate passage.
- **Test (gate sample):** seasons 2024–2025, walk-forward chronologically.

## Pre-registered gates (all must pass; fail-closed)

1. **Sample:** ≥ 2,500 games and ≥ 2,500 distinct goalie-starts in the test window.
2. **Primary:** on the test window, G2 beats G1 on **both** Brier score and log loss for the
   game outcome, using a paired difference per game clustered by game (each game contributes
   one paired difference; cluster = game), with a 95% cluster-bootstrap CI excluding zero for
   **each** of the two scores. One-sided improvement required; a CI containing zero fails the
   gate for that score.
3. **Distribution:** the G2 goal distribution improves (lowers) CRPS vs G1 on the same test
   games, **and** PIT uniformity does not degrade: the KS statistic of G2's PIT values must not
   exceed G1's by more than 0.01 (absolute), evaluated per the
   `EVAL-CONTRACT-discrete-props.md` zero-mass rule (goals are zero-heavy; coverage alone is
   not accepted as evidence of calibration).
4. **Fail-closed:** if gate 2 passes on one proper score but not the other, or if gate 3's PIT
   degrades, G2 is **rejected**. A mixed result is reported as a null, not a partial pass.
5. **Sanity (diagnostic, not a gate):** sign and magnitude of κ. Sign convention: GSAx =
   xG against − goals against, so an **above-average** goalie (allows fewer goals than the
   shot difficulty implies) has **negative** GSAx/shot; the league mean is ≈ 0. For the
   adjustment to behave like goaltending and not like team defence, a negative
   `goalie_score` must **reduce** the goals-against rate, i.e. `exp(κ·goalie_score) < 1`,
   which requires **κ > 0**. A fitted κ ≤ 0, or a κ so large that the plausible GSAx/shot
   range swings the GA rate beyond roughly ±15% (a Vezina-calibre goalie vs a replacement
   one), is reported as a diagnostic failure and grounds for manual review even if other
   gates pass — a significant coefficient with a nonsensical sign means the feature is
   picking up team defence, not goaltending.

## Pre-/post-confirmation forecasts

For every game in the test window, record both forecasts with their as-of times:
- **Pre-confirmation**: timestamped at the run that used the predicted starter.
- **Post-confirmation**: timestamped at the run that used the observed starter.
Report the absolute and relative forecast movement (probability delta and GA-rate delta).
Movement size is itself a finding and is reported whether or not gates pass.

## Null-result protocol

If G2 fails any gate, the result is recorded as a null with the numbers, the verdict, and a
learnings entry. Nothing is re-run with different settings, and the tiered pick policy remains
NO-GO — this work is research into the underlying distributions only and does not revisit any
betting policy.

## Commit discipline

The pre-registration text above is committed to the branch **before** the first fit is run.
The fit script, its commit hash, and its output are recorded afterward; any deviation from
this text in the executed code is a reported protocol violation, not a silent correction.
