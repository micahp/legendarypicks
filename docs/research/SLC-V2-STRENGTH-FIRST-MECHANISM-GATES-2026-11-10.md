# SLC-v2 strength-first: three mechanism gates and independent penalty test plan

**Date:** 2026-11-10  
**Decision:** Owner elects to finish and evaluate the team-strength model **before** penalty simulation or penalty-model fitting.  
**Status:** Testing instructions; no simulations run, no production adoption authorized.  
**Scope:** SLC-v2 baseline, C, D1 and opt-in joint transition strength; yardage/chain conversion, fourth-down decisions, sacks/turnovers.  
**Companion:** [Historical penalty and mechanism protocol](SLC-V2-HISTORICAL-PENALTY-MECHANISM-FORWARD-TEST-PROTOCOL-2026-11-10.md) covers the **deferred** penalty component.

## 0. Hard ordering and independence

1. Finish three **no-penalty** offline diagnostics: (A) conditional yardage / first downs, (B) fourth-down situations versus choices, (C) sacks / turnovers, including the entire probability-weighting path.
2. Repair source eligibility consistently: use the verified 2026 source penalty overlay for BOTH old baseline and strength candidate, **excluding confirmed penalties and unknown labels from clean-play fitting/testing**. Do **not** generate, assign, enforce, or fit a penalty event in this phase. The 2026 database remains read-only; do not silently equate NULL with 0.
3. Fix and unit-test opt-in transition-strength execution; test it on held-out **observed play situations** against the simple league cell baseline and old team reweights. Do not adopt a new strength layer unless it improves out-of-sample calibration with adequate group-level support.
4. Only then run the minimum controlled full-game strength ablation (no new 10K production batch yet).
5. **After** results are frozen, start the independent penalty study: P-only vs the same no-strength control, holding workload and other football layers fixed. Test S+P interaction **last**, after separate S-only and P-only findings. Never combine changes and attribute their gains to one mechanism.

Definitions: B = original workload/config family (Default V2, V2+C, or V2+D1); S = optional new joint transition/team strength layer **replacing**, not stacking with, old event-only team outcomes; P = future explicit penalty simulator. The same data eligibility policy, cutoff and snapshot must apply on both sides of each paired comparison. Initial historical Brier/log-loss scores remain immutable and distinct from the new corrected-input controls.

| Evaluation stage | Arms per workload family | Purpose |
|---|---|---|
| Stage 1, **now** | B(no P, old outcome layer) vs B+S(no P, replaced team outcome layer) | Strength-only effect |
| Stage 2, **later** | B(no S, no P) vs B+P(no S) | Penalty-only effect |
| Stage 3, **last** | B+S+P vs B+S, B+P and B | Interaction / additive effects |

Apply each stage to Default V2, C and D1 separately when sample size/resources allow. Do not call a result from B+S+P an isolated strength or penalty improvement. Preserve frozen three-game Week 9 winner scores: Default V2 Brier/log loss 0.19430/0.57764; C 0.17793/0.54415; D1 0.19865/0.58641. These scores have only **three independent games**, so are descriptive rather than promotion evidence.

## 1. Evidence already on the branch

- [2025/2026 conditional outcome audit](slc-v2-conditional-outcome-audit-2026-11-10/README.md): 2025, 272 games and 33,490 event-scored plays. League situation-cell event log loss **0.5404**, offense-only **0.5456**, defense-only **0.5462**, and offense/defense matchup **0.5517**. The existing strength multipliers make the **overall event** score worse.
- [2026 penalty source/overlay and sack audit](slc-v2-penalty-opportunities-2026-11-10/README.md): on 15,061 source-confirmed nonpenalty test rows, league log loss **0.518545**, corrected matchup **0.531319**; old NULL-status-input matchup **0.531340**. Correcting labels alone did not fix broad event scores. This is **not** a test of simulated penalties.
- From 2025 held-out completion rows for **weak offense against strong defense** (n=781): observed 10.469 yards/completion; league-cell expected 10.979 (bias +0.511); offense-only expected 10.649 (bias +0.181), but league-cell still had better CRPS (**4.480** vs **4.502**). Do not substitute improvement in mean bias for improvement in distribution scoring.
- Minnesota's 2026 pregame seven-game sample: **0.857 fourth-down go attempts/game**, versus **1.885** per D1 simulated game. D1 generated **1.786 fourth-and-1/2 decisions/game** versus **8/7 = 1.143** observed. Given fourth-and-1/2, D1 went **10,987 / 17,845 = 61.6%**; Minnesota went **5/8 = 62.5%** (tiny seven-game sample). This suggests an **upstream state-distribution** problem is plausible even where conditional choices agree.
- 2026 corrected historical observed-context sack rate: **6.622% league**, predicted **6.512% matchup**. Minnesota offense 9.95% observed vs 7.52% predicted on 211 dropbacks; Minnesota defense **11.42% forced** vs **6.84% predicted** on 219 opponent dropbacks. Team effects are underexpressed despite a good league mean.
- Frozen 10K BUF-MIN: about 3.67% simulated Minnesota sack rate and 1.80% simulated Buffalo sack rate. **Important provenance split:** the first 1,000 seeds (all valid) have a clean source/config hash; the remaining 9,000 seeds (8,991 valid) have a dirty producer and different configuration/reference/snapshot/artifact hashes. The dirty code cannot be reconstructed. Retain and report both groups separately; do not treat 9,991 results as one identical configuration. No replay from those artifacts can attribute each stage's probability weight.

## 2. Test A: conditional yardage and chain advancement, without game simulation

**Hypothesis:** For a weak offense facing a strong defense, sampled outcomes gain too many yards and reach the line to gain too often, even when the intent and pre-play situation are fixed.

**Unit of evaluation:** each actual held-out NFL run/dropback, using the **observed** offense, defense, intended play class, down, yards-to-go, yard line, quarter, score differential and frozen pregame evidence. Target-season results and post-cutoff changes cannot enter predictions.

**Models to score side by side:**
- A0 = league situation/event historical sample distribution;
- A1 = existing event-type team offense/defense multiplicative reweighting;
- A2 = new opt-in joint event+yard bucket+first-down+TD transition strength (after runtime/unit gates);
- A3 = simple offense-only/defense-only conditional-yardage shrinkage as controls;
- optionally a continuous opponent-adjusted hierarchical baseline, fitted on training seasons only.

**Metrics:**
- Per-play event log loss/Brier, conditional completion/run/sack yard CRPS, mean bias, negative/zero/4+/10+/20+ yard probabilities;
- offensive success by down, **probability of getting required yards** and offensive TD on third/fourth down, by yards-to-go (1–2, 3–5, 6–9, 10+);
- per-team and **3x3** offense strength x defense strength bins; score every bin with counts, effective sample support, confidence intervals and fallback fraction.
- Train strength buckets exclusively on historical, opponent-adjusted pregame efficiency/success (never on the target game). Use strong/mid/weak for **evaluation**, with uncertainty/shrinkage; avoid using a team's future season-end ranking as a feature.

**Decomposition:** separate the choice of run/dropback, event type conditional on intent, yards conditional on event, touchdown, first-down result. If A2 scores event classes better but yard CRPS worse, report that explicitly. Break down chain-advancement error on real observed situations before concluding it causes full-drive inflation.

**Gate:** compare A2 to A0/A1 on untouched 2025 and corrected-input 2026 walk-forward cohorts; report game-clustered paired uncertainty and reliability, both overall and weak-vs-strong. A2 must not get promoted solely because Minnesota or Arizona scores look better in individual replay games.

## 3. Test B: fourth-down **decision policy** versus **situations reached**

**Hypothesis B1 (policy):** SLC calls go/punt/FG at the wrong rate when given the same fourth-down situation as a real coach.

**Offline policy test:** feed each of the 3,580 observed 2025 fourth downs to the frozen SLC policy **without generating a game**. Group by down-distance, field position, score differential, quarter/time, team and opponent. Score the probability of go/punt/FG with multiclass log loss, Brier and reliability. Compare historical situation-cell (2025 log loss **0.4892**) against offense-only policy (**0.4855**) and any newly calibrated policy. Run a later corrected 2026 cohort with cutoff eligibility.

**Hypothesis B2 (upstream state distribution):** SLC's excessive first downs or distorted yardage push it into too many fourth-and-short situations and produce the go-count discrepancy even if its conditional decision policy is reasonable.

**Decompose expected go attempts per game:**

  expected_go/game = sum_over_contexts( fourth_down_opportunities_per_game(context) * P(go | context) ).

Report four results using the same context bins: (i) observed opportunity mix x observed conditional policy, (ii) observed mix x SLC policy, (iii) SLC mix x observed conditional policy, and (iv) SLC mix x SLC policy. The paired differences attribute the **conditional-policy component**, the **generated-state component**, and any interaction; do not double count them. Score clock and team-strength stratification explicitly. Where observed team bins have low support (e.g., Minnesota's eight fourth-and-1/2 decisions in seven games), shrink to league or opponent-adjusted cells and report support.

**Next action:** decide **whether** fourth-down policy needs changing. If conditional decisions are well calibrated, prioritize earlier down/yardage transitions instead of changing go-for-it preferences.

## 4. Test C: sacks and turnovers, full probability funnel on **observed** situations

**Hypothesis C1:** offense/defense mismatch underweights strong pass-rush and weak-protection teams despite league-wide sack calibration.

**Hypothesis C2:** subsequent formation/coverage/label/player modifiers, sparse fallbacks, or sampling normalization shrink the sack probability further (as indicated by BUF-MIN simulation rates).

**Do not run 10K seeds to test this.** Instrument a deterministic/no-draw scoring function for SLC's existing weighted event sampler and feed historical **observed pre-dropback situations**. For every eligible dropback record:

1. Base sack/interception/incompletion/completion event probabilities from the historical cell or explicit backoff source;
2. After **each** existing multiplier, its support, before/after unnormalized weights, normalization and resulting probabilities (formation, coverage, streak, decision labels, offense/defense effect, player outcomes);
3. After the applicable QB/scramble and receiver/target filtering, with their actually supported effect (do not credit a modifier applied only **after** selecting the event with an event-rate change);
4. Exact final normalized P(sack), P(interception), P(completion), P(incompletion), and chosen row-dependent sack-yard distribution;
5. Named fallback and all-weights-zero behavior; what proportion of contexts invoke them.

Run stages with each component removed, but ensure the final probabilities are normalized at every stage and preserve data cutoffs. Compare against observed sacks, interceptions, fumbles and retained turnovers by offense/defense. Include Buffalo/Minnesota and all 3x3 strength bins, with per-team shrinkage and confidence intervals. Stratify passing situation, protection/pressure if data are reliably available, and time/score. **Fumbles are not identical to fumbles lost** and may require different opportunity denominators.

Important pregame benchmark: Minnesota defense forced 8 interceptions in 228 opponent attempts (**3.51%**) while D1 BUF simulation gives Buffalo about **1.33% interceptions per pass attempt**; these are different game-state distributions, not a matched-context audit. Minnesota's offense 3 interceptions / 216 attempts (**1.39%**) versus simulated **1.26%** is less obviously miscalibrated. Keep targeted and overall results distinct.

**Gate:** held-out proper scoring of sack/interception/fumble event probabilities must exceed the league and existing team baselines with game-clustered uncertainty. Any reduction in full-game sack rates must be attributed to either a model probability change **or** the generated game-state mixture, not guessed from averages. Do not enable the old 'restore_sack_mass' intervention without proving improvement after all event weights.

## 5. Strength architecture and validation

The strength model is **not** a single overall EPA or win-rating multiplier. Fit shrinkage-based offensive and defensive capability profiles for pass/run success, yards conditioned on outcome, down conversion, pressure/sacks, turnovers and red-zone achievement. Use the existing historical play pool and legal transitions. Rate and strength groups come from **pregame evidence** and should recognize strong/mid/weak separately for offense and defense.

The opt-in transition model (commit 17be149e, hotfix ff231071) is only one candidate. It is **not** adopted. Require:
- deterministic unit/CLI sampling tests for ratio-key lookup, backoff and no-team-support behavior; cutoff/unknown-penalty guards; disabled-feature seed equivalence; run/pass/sack/TD legality;
- the current 2026 clean-play overlay applied identically to both old and candidate arms;
- actual historical observed-context test scoring; log loss/Brier for events and conversions and CRPS for gains;
- game-level bootstrap intervals, per-team context calibration and effective-support/fallback tables; explicit separate training/validation/holdout years;
- a *small*, paired, no-penalty end-to-end strength-only integration comparison on held-out matches only after these checks pass. Keep existing Default V2/C/D1 results as historical records, not silently regrade mixed-provenance outputs as homogeneous.

Predeclare advancement before viewing new game outcomes. A better short sample mean score is not enough; look for calibrated events, realistic first downs and fourth-down opportunity counts, the right sack/turnover tails, score bands and no regression to player workload or football-state validity.

## 6. Penalties after strength, independently

The 1,300,819-row 1999–2026 source extract and 2026 penalty overlay remain valuable **read-only data assets**. But do **not** fit penalty propensity, classify accepted/declined/offsetting fouls, build enforcement rules, or enable penalty RNG in the immediate strength workstream. Those tasks move to the **post-strength** phase.

When penalty research resumes:
- First, independently fit team offensive/defensive penalty rates and legal enforcement, validating against the full historical corpus with known-status coverage;
- Then do **P-only** against the same cutoff/data-cleaned B controls, with strength disabled and workload fixed; compare Default V2, C and D1 separately;
- Last, do S+P to measure combined effects and interactions. A corrected historical penalty *column* is not penalty simulation, and must not be credited as one.
- Player-specific penalty propensities after transfers remain optional and should not block team-level strength adoption.

## 7. Required agent deliverables before requesting another simulation

1. **Mechanism scoreboard** (2025 test, corrected 2026 walk-forward sensitivity): models A0/A1/A2/A3; events Brier/log loss, gains CRPS, third-down probability, and complete 3x3 strength bins.
2. **Fourth-down two-factor decomposition** (observed vs simulated contexts, conditional policy, and interaction), including its supports and explicit observed sample sizes.
3. **Sack/turnover probability funnel** (before/after every multiplier, named fallbacks and normalized probabilities) on recorded observed plays, plus team and 3x3 calibration.
4. **TDD and provenance:** unit/integration tests, release hashes, evidence cutoffs, original 10K config split noted, immutable baselines preserved, no dirty/clean amalgam, no altered input database.
5. **Decision memo:** which of yardage/chain advancement, fourth-down policy/state mix or sacks/turnovers shows demonstrable out-of-sample error; what strength changes, if any, beat league context baselines. Propose a bounded paired game test only then.

**Do not:** run a new 10K, switch on penalties, rewrite 2026 database values, promote the transition-strength prototype, or modify production defaults as part of these audits.
