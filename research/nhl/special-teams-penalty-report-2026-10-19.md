# Penalty-opportunity volume on top of ST — 2026-10-19

Research only. Branch `research/nhl-special-teams-2026-10-19`, worktree
`/root/lp-nhl-special-teams`. Pre-registration committed **before any fit** at `675ca38b`
(`research/nhl/special-teams-penalty-preregistration-2026-10-19.md`). Nothing merges, nothing
deploys. Tiered pick policy untouched (NO-GO).

**Headline: B FAILS the pre-registered keep rule.** Penalty-opportunity volume improves the
win-probability scores over ST — Brier and log loss both improve with game-clustered 95% CIs
excluding zero — but it does **not** improve the goal distribution: CRPS is very slightly
*worse* than ST with a CI that includes zero, and PIT/KS degrades marginally. The registered
keep rule is conjunctive (Brier **and** log loss **and** CRPS), so the candidate is **not kept**.
The answer is **no**, recorded as no. Nothing is adopted; the decision is Micah's.

**Reproduction:** every score below is recomputable from the committed per-game CSV
`forecasts_all_arms.csv` with no model fit; all non-PIT statistics match to 0.00e+00 and PIT/KS
to within 4-decimal rounding. See `reproduction-table-2026-10-19.md` and
`verify_from_csv.out.txt`. The reproduced numbers do not change this verdict.

## Population

Identical to the ST experiment and to its Step A artifact. `merged = 23,002`,
`dropped_no_st = 114`, `dropped_no_pen = 0`, `eval = 9,147` games (2019–2025). No game added or
removed for this experiment. **2025 is NOT a clean holdout** — it was inspected in the ST run and
its per-season delta is already published; per-season values are reported but cannot confirm or
falsify on their own.

## Results — V1 (primary): ST + penalties drawn per 60

Delta convention: `ST loss − candidate loss`; positive = candidate better. Cluster = game,
10,000-iteration bootstrap, 95% CI.

| Score | ST | V1 | Δ (ST−V1) | 95% CI | Gate |
|---|---:|---:|---:|---|---|
| Brier | 0.243298726 | 0.243003189 | +0.000295537 | [+0.000124598, +0.000462656] | **PASS** (improves, CI excludes 0) |
| Log loss | 0.679577987 | 0.678966542 | +0.000611445 | [+0.000264509, +0.000952165] | **PASS** (improves, CI excludes 0) |
| CRPS | 0.958670640 | 0.958754529 | −0.000083889 | [−0.000466552, +0.000293062] | **FAIL** (CI ∋ 0, point worse) |

PIT/KS: ST home 0.0438 / away 0.0606; V1 home 0.0440 / away 0.0607 — **marginal degradation**.
The distribution gate therefore fails on both its clauses (CRPS not improved, PIT/KS degraded).

## Results — V2 (exploratory): ST + drawn and taken per 60

| Score | ST | V2 | Δ (ST−V2) | 95% CI | Gate |
|---|---:|---:|---:|---|---|
| Brier | 0.243298726 | 0.243007425 | +0.000291301 | [+0.000120927, +0.000458532] | PASS |
| Log loss | 0.679577987 | 0.678975446 | +0.000602540 | [+0.000256181, +0.000942562] | PASS |
| CRPS | 0.958670640 | 0.958791872 | −0.000121232 | [−0.000505402, +0.000256255] | FAIL |

V2 carries no gate authority and fails the same distribution clause. Its second penalty
coefficient (taken per 60) is **wrongly signed and unstable** — expected negative, fitted
`+0.0174, +0.0010, +0.0020, +0.0012, +0.0021, −0.0054, −0.0142` across 2019–2025. The prereg's
sign check counts this against V2 independently of any score movement. V2 is rejected.

## Fitted coefficients (V1, by season)

The drawn-per-60 coefficient is stable and correctly signed in all seven refits:
`+0.1023, +0.0982, +0.0882, +0.0842, +0.0822, +0.0839, +0.0786` (2019→2025). More PP
opportunity raises own expected goals, as registered. The 5v5 and ST coefficients shift slightly
because they are jointly refit, exactly as disclosed for the ST experiment.

## Verdict against the registered gate

- **Primary (Brier AND log loss):** passes — both improve, CIs exclude zero.
- **Distribution (CRPS improves AND PIT/KS does not degrade):** fails — CRPS is slightly worse
  (CI ∋ 0), PIT/KS degrades.
- **Conjunctive keep rule:** **not kept.** Recorded as **no**.

This is a partial result, and the honest reading is that penalty-opportunity volume carries a
small win-probability signal — more PP opportunity shifts the joint distribution enough to
improve Brier and log loss — but it does not sharpen the per-team goal marginals, which is what
CRPS and PIT measure. The goal distribution was already the strong part of the ST candidate
(CRPS 0.96008 → 0.95867 there); the volume lever adds nothing on that axis. The registered gate
required all three, so the answer is no.

## Reproduction / auditability (Step A, already pushed at 8616b528)

`audit_special_teams.py` recomputed Brier, log loss, CRPS and the clustered CIs from
`forecasts_st.csv` **without refitting** and matched the published ST metrics to `0.00e+00`.
Full verifier stdout is committed as `verify_special_teams.out.txt` (92,008 feature checks,
0 mismatches). This experiment additionally emits `forecasts_penalty.csv` (one row per graded
game, `p_st, p_v1, p_v2`, distribution means, outcome) so the penalty scores are auditable the
same way.

## What was deliberately not done

- No gate, threshold, or population change. No retuning, no post-hoc rescue.
- No production/ingest/schema change, no dev merge, no deploy, no promotion.
- Tiered pick policy not touched (still NO-GO).
- No GSAx revisit; the starter-feed DROP stands.
- CP4/CP5 not attempted. This is retrospective; a positive retrospective result would still not
  ship, and this one did not pass its own gate.

## Provenance

- ST experiment and Step A: `research/nhl/special-teams-feasibility-2026-10-19.md`,
  `forecasts_st.csv`, `verify_special_teams.out.txt` (`8616b528`).
- Pre-registration: `research/nhl/special-teams-penalty-preregistration-2026-10-19.md` (`675ca38b`).
- Runner: `research/nhl/special-teams-2026-10-19/run_penalty_volume.py`.
- Results: `research/nhl/special-teams-2026-10-19/results_penalty_volume.json`,
  `forecasts_penalty.csv`.
