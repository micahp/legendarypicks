# Learnings log — NHL research

Appended as work progresses. Nulls and wins included deliberately. Nothing here revisits the
tiered pick policy, which remains NO-GO. Live focus is NFL; NHL entries are research-only
unless stated. This file is created on the special-teams branch; the starter-feed branch keeps
its own `LEARNINGS.md` (`DROP`, `84985d14`) until branches converge.

## 2026-10-19 — Special teams: PP/PK xG/60 over 5v5-only (YES, passes gate)

Full write-up: `research/nhl/special-teams-feasibility-2026-10-19.md`.
Pre-registration: `research/nhl/special-teams-preregistration-2026-10-19.md` (`854ad6f2`,
committed before any fit).

- **The candidate passes the pre-registered gate.** Adding opponent-adjusted, 5v5-separate
  PP/PK xG/60 rates to the 5v5-only Poisson improves Brier, log loss, and CRPS on the identical
  9,147 evaluation games (2019–2025), with game-clustered 95% CIs excluding zero in the
  improving direction:
  - Brier 0.24391 → 0.24330, Δ +0.000613 [0.000314, 0.000901]
  - Log loss 0.68083 → 0.67958, Δ +0.001255 [0.000649, 0.001840]
  - CRPS 0.96008 → 0.95867, Δ +0.001407 [0.000799, 0.002016]
- **The ST coefficients are stable and correctly signed in every refit.** PP-offense coefficient
  0.0349–0.0490, opponent-PK coefficient 0.0439–0.0598, both positive across all seven
  evaluation seasons. More PP xG raises own expected goals; a weaker opponent PK raises the
  opponent's expected goals. This is the goaltending-independent sign, unlike the goalie work.
- **The baseline ladder is monotonic:** B0 0.2500 → B1 0.2489 → B4 0.2456 → B5 0.2439 → ST
  0.2433 (Brier). B5 is the "5v5-only Poisson" the brief's status table describes.
- **Verified against ground truth, not against the code that produced it.** One game's ST feature
  matches a separate DB recomputation exactly; all 92,008 ST values were recomputed with a
  second code path and **0 mismatched**; every source game is strictly before its game date.
  The B5 refit matches the published fit cache to the third decimal (the 114 dropped games
  explain the residual).
- **CP1–CP3 pass; CP4–CP5 not attempted.** This is a retrospective result. It is not a validated
  model and does not ship. A positive retrospective result still has to survive prospective
  confirmation and Micah's integration decision.
- **Caveats, stated plainly:** the edge is small; 2025 is negative on Brier and log loss and 2024
  is negative on CRPS, so the sign is not universal; the 5v5 coefficients are jointly refit, so
  the gain is not a clean decomposition of the two ST coefficients alone; "opponent-adjusted" is
  achieved through the regression, not a feature-level adjustment; penalty-opportunity volume is
  not included (the brief's step 3 also calls for it).
- Deliberately not done: no tiered-pick-policy change (NO-GO), no production or ingest change,
  no dev merge or deploy, no GSAx revisit, no post-hoc re-tuning. The pre-registration's "three
  parameters" wording was inaccurate (B5 is four: intercept, home flag, offense, defense);
  disclosed in the report, convention unchanged.
- **Next if pursued:** add penalty-opportunity volume (penalties drawn/taken per 60) as a second
  candidate; test a per-game ST variant; then CP4 with frozen prospective forecasts. Do not
  promote on the retrospective result alone.
