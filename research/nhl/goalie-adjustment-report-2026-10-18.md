# Report — NHL goalie adjustment (build-order step 2), 2026-10-18

Research only. Branch `research/nhl-goalie-adjustment-2026-10-18`, fresh worktree
`/root/lp-goalie-research` off `origin/dev` @ `f6ccd943`. Not pushed. The tiered pick policy
was NOT revisited and remains NO-GO.

**Headline: G2 is rejected under the pre-registered, fail-closed gates.** The regressed-GSAx
goalie adjustment improves the goal distribution (CRPS, PIT) but does **not** beat the
league-average-goalie baseline on the game outcome under Brier or log loss — the paired,
game-clustered intervals include zero on both. That is a real null, reported as one.

## 1. Data audit — what exists, what does not, what it permits

Full audit: `research/nhl/goalie-data-audit-2026-10-18.md` (committed `857033bb`).

- **Exists:** located shot-level data — `shots`, 2,079,359 rows, seasons 2007–2025, with
  coordinates, angle, distance, shot type, `xGoal`, and `goalieIdForShot`. Goalie-season
  (`goalies_seasons`, 8,510 rows) and goalie-game (`goalies_gamelogs`, 231,540 rows) aggregates
  2008–2025. Game outcome `homeTeamWon` (shootout included) is populated.
- **Does not exist:** any pre-puck-drop starter signal. The only starter flag is
  2025-postseason-only and post-hoc. Consequence: the expected starter had to be estimated
  statistically (pre-registered heuristic), and the post-confirmation forecast is a
  retrospective recomputation using the observed starter.
- Also missing: `homeTeamScore`/`roadTeamScore` (null everywhere; final score reconstructed
  from `SUM(goal)` per side). The `shots`→gamelog join is `game_id − 20000 == gameId % 10000`,
  verified across all seasons; goalie IDs match `playerId` exactly.

## 2. Pre-registered spec and gates (committed before results)

`research/nhl/goalie-adjustment-pre-registration-2026-10-18.md`, committed as `f64757a4`
**before** the first fit. Frozen: G1 form (rolling-10 multiplicative Poisson, w=5 shrinkage,
league-level home/away split, no goalie term); G2 form (G1 × exp(κ·goalie_score)); empirical-Bayes
shrinkage (k=1500 shots toward the trailing-3-season league mean of (xG−GA)/shot);
"shot difficulty" enters through the xG denominator (no separate raw-SV% term); expected-starter
heuristic (most recent prior start for the team this season; on a back-to-back, the other goalie
with a prior start); windows train 2008–2022 / validation 2023 / test 2024–2025; sample gate
≥2,500 games and goalie-starts; primary gate Brier **and** log loss with game-clustered paired
CIs excluding zero; distribution gate CRPS improvement and PIT non-degradation; fail-closed.

Two disclosed protocol items (also in the learnings log):
1. The first implementation predicted the starter from prior *appearances*; the pre-reg says
   *starts*. Corrected to starts and re-run before any result was reported. The correction did
   not change the verdict (test Brier diff −0.000167 vs −0.000207; both nulls).
2. The pre-reg's gate-5 prose is internally contradictory about the sign of GSAx: it defines
   GSAx = xG against − goals against (positive = above-average goalie) but then says an
   above-average goalie has *negative* GSAx/shot and derives κ > 0. Under the document's own
   formula the goaltending direction is κ < 0. The frozen document was not edited after
   results; both readings are recorded in the diagnostic below.

## 3. G1 vs G2 on both proper scores, with game-clustered paired intervals

Test window = seasons 2024 and 2025 (2024-25 + 2025-26), 2,624 games, 5,248 goalie-starts
(sample gate passes: ≥2,500 of each). Differences are G1 − G2 (positive = G2 better),
cluster = game, 10,000-iteration cluster bootstrap, 95% CI.

| Score | G1 | G2 | diff | 95% CI | Gate |
|---|---:|---:|---:|---|---|
| Brier | 0.26657 | 0.26673 | −0.000167 | [−0.000573, +0.000230] | **FAIL** (CI ∋ 0) |
| Log loss | 0.72935 | 0.72961 | −0.000258 | [−0.001129, +0.000590] | **FAIL** (CI ∋ 0) |

Validation season 2023 (1,312 games) is worse still: Brier diff −0.001423 [−0.002000,
−0.000849] and log-loss diff −0.003030 [−0.004275, −0.001788] — G2 significantly **worse**
than G1 there. Point estimates also favour G1 on the test window. Both primary gates fail;
the point direction is not even favourable.

## 4. CRPS / PIT / calibration for the goal distributions

Per-team Poisson goal forecasts (pre-confirmation), identical observations for both models:

| Metric | G1 | G2 | Verdict |
|---|---:|---:|---|
| CRPS (mean, goals) | 1.39171 | 1.38721 | **improves** (−0.0045) |
| PIT KS, home goals | 0.0285 | 0.0234 | improves (does not degrade) |
| PIT KS, away goals | 0.0246 | 0.0225 | improves (does not degrade) |

The distribution gate passes: CRPS improves and PIT uniformity improves on both sides.
Zero-mass handling: discrete midpoint PIT (`F(y−1) + 0.5·p(y)`), per the zero-heavy-goals
rule — coverage alone was never used as calibration evidence. This is the honest ceiling of
the feature without a real starter feed: the goalie rating sharpens the goal distribution but
cannot move game outcomes.

## 5. GSAx coefficient diagnostic

- Fitted κ = **−4.72** (Poisson offset GLM on 2008–2022).
- Sign: under the pre-registered formula (GSAx = xG against − goals against; above-average
  goalie ⇒ positive score), goaltending requires κ < 0 — **satisfied**. The pre-reg-as-written
  check (κ > 0, derived from its contradictory prose) is recorded as failed rather than hidden.
  The fitted sign is the goaltending direction, not team defence.
- Magnitude: regressed score quantiles (test window) q05 = −0.0042, q95 = +0.0069 ⇒ GA-rate
  multiplier 1.020 at q05 and 0.968 at q95 — a **±2–3% GA swing**, well inside the pre-registered
  ±15% plausibility band. Consistent with hockey literature: goaltending is a real but modest
  lever on team goals-against.

## 6. Pre- vs post-confirmation forecast movement

As-of times recorded (`results.json.run_utc` = `2026-10-18T23:54:03Z`; both variants
retrospective reconstructions from the same run, explicitly labelled non-prospective):

- Starter-prediction accuracy of the pre-registered heuristic: **49.7%** (test window).
- Raw same-starter repeat rate in this data: **52.5%** (25.4% on back-to-backs, 57.4% at 2
  days' rest, ~61–65% at 3–4+ days). NHL teams rotate goalies heavily; the naive heuristic is
  close to coin-flip.
- Once the starter is observed: win probability moves |Δp| = **0.0071** on average, max
  **0.0573**; expected GA rates move ~+0.004 (home) / −0.0015 (away) goals. The movement is a
  finding, not noise: with a ~50% starter hit rate, pre-confirmation forecasts carry roughly
  as much wrong-goalie noise as goalie signal, which is why the outcome gates fail while the
  distribution improves.

## 7. Branch, commits, pushed or not

- Worktree `/root/lp-goalie-research`, branch `research/nhl-goalie-adjustment-2026-10-18`
  (off `origin/dev` @ `f6ccd943`).
- Commits (in order): `857033bb` data audit → `f64757a4` pre-registration (before fitting) →
  model code, ledger builder, results (`results.json`, `ts.parquet`), learnings log, this
  report. Every pre-registration artifact preserved; prospective ledger untouched.
- **Not pushed.** Research stays on the branch until CP5; nothing here seeks production
  integration.

## 8. What was deliberately not done

- **The tiered pick policy was not revisited.** It is NO-GO and stays NO-GO; this research
  targeted the underlying goal distributions only.
- No production code changed; no dev merge; no push; no prospective ledger writes.
- No secondary features (rest/workload) were added: the pre-registration gates their
  inclusion on validation improvement, and validation showed G2 significantly worse, so the
  gate said no.
- The pre-registration document was not edited after results — the sign-prose defect is
  disclosed in the report and learnings log instead.
- No attempts to rescue the null by re-tuning: shrinkage k, window, and features stayed as
  frozen. A different result would require a new pre-registration.
