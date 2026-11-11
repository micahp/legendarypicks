# Legendary Picks model benchmark reference

**As of:** 2026-11-10. **Repository evidence:** slc-v2 at edd3522b, plus the source reports linked below.  
**Purpose:** The single entry point for **which baseline to beat**, what a score means, the strongest measured model for **each target**, and whether the result is eligible to drive an adoption decision. This is a *research scoreboard*, not an assertion that all listed arms are in production or comparable to one another.

> **Non-negotiable:** Never rank Brier scores from different targets, markets, populations, eras, prediction horizons, settlement definitions, or source vintage as though they were head-to-head. A winner Brier of 0.21 and a rare-prop Brier of 0.08 cannot establish which model is better. **No model is “leading” without naming the cohort and comparator.** A smaller point estimate is not necessarily a statistically established win.

## Quick answer: What is leading?

| League / category | Best point estimate on the stated cohort | Control or market on **that cohort** | Status and decision |
| --- | --- | --- | --- |
| **NFL game winner, team forecast** | **nfl-v1 points: 0.2288 Brier**, 255 games, frozen 2025 holdout | EPA v2 0.2291; no-vig closing market **0.2137**; coin flip 0.2500 | **Deployed baseline**; fails to beat market; EPA v2 not adopted. [NFL model card](model-cards/nfl.md) |
| **NFL game winner, longer historical study** | **v1+Elo: 0.2197**, 3,158 games, 2011–2023 retrospective | Recalibrated v1 0.2229; closing market 0.2104 | **Exploratory only**, different sample from 2025 holdout; not evidence of future market edge. [NFL model card](model-cards/nfl.md) |
| **NFL full-game SLC simulator winner** | **SLC v2: 0.2478** Brier, 121 games, 2026 Weeks 1–8 | SLC V1 0.2484; V1.5 0.2489 | **Point-estimate Brier leader, not statistical winner**: V1 has lower log loss (0.6945 vs v2 0.6966). About 15–20 seeds/game; mostly retrospective-exposed. [Matched report](research/SLC-V2-VS-V15-RESULTS-2026-11-04.md) |
| **NBA game winner** | **G3 joint scores: 0.21339**, 2,460-game 2024–2025 untouched test | G1 Elo 0.21465; G2 efficiency 0.21474; constant training home rate 0.24887 | **Historical lowest point estimate**, not conclusively superior to G1; **research only**, no timestamp-valid market comparator. [Phase 1](NBA-GAME-MODEL-PHASE1.md) |
| **NCAAF/FBS game winner** | **G2h: 0.19460**, 2023–2025 research walk-forward, 2,397-game parity population | C2 0.19649; G2 0.21326; base-rate reference approx 0.25 | **Research leader, NOT certified live performance**: production/research row parity and source-history integrity blocked. [Parity decision](DECISION-ncaaf-parity-next-steps-2026-10-20.md) and [FBS learnings](LEARNINGS-fbs.md) |
| **NHL game winner** | **Special-teams xG candidate: 0.243299**, 9,147 retrospective graded games (2019–2025) | Matched 5v5-only model 0.243912 | **Small historical improvement, NOT adopted**: conjunctive goal-CRPS interval crosses zero. Independent historical market marker **0.23554**, *different* 5,131-game cohort; no valid comparison to the 9,147-game result. Prospective B3/B5/B7 not yet winner-graded in documented snapshot. [NHL learnings](LEARNINGS-nhl.md), [NHL card](model-cards/nhl.md) |
| **Tennis match winner (ATP / WTA)** | **Standard Elo: ATP 0.22802 / WTA 0.21596**, historical best-of-three walk-forward | Point simulator ATP 0.23530 / WTA 0.22884, same respective samples (11,777 / 13,066 matches) | **Elo comparator wins this test.** Distinct selected 2,749-match point-history cohort: *calibrated* Elo 0.20691 vs direct point model 0.22336; **never mix these samples**. Live global/surface blend does not have a certified prospective Brier in the cited card. [Tennis card](model-cards/tennis.md), [selected-cohort study](../research/tennis/point-events/2026-10-16/prop_brier_comparison.md) |
| **NFL player prop P(over)** | **Strict forward-Platt: 0.2502**, 20,926 line items / 628 player-games, 2026 W3–5 | Raw v2 **0.2743**; matched no-vig market **0.2469** | **Best disciplined strict candidate shown here; market still ahead** and no independent market increment. Do not substitute earlier leaky 0.1911 or broader, differently selected 0.2486. [NFL card](model-cards/nfl.md), [NFL decisions](RESULTS-nfl-decisions-2026-10-17.md) |
| **Tennis player threshold props** | ATP aces ≥4: **P1 0.20016** vs P0 0.20745; WTA aces ≥4: **P1 0.16275** vs P0 0.16360 | Same 2022–2024 tour/threshold cohorts (ATP 20,788 and WTA 22,506 player-match targets) | **P1 wins these individual thresholds**; other ace/double-fault cutoffs have different base rates; do not pool the Brier numbers as if the events were identical. [Cross-target table](../research/tennis/point-events/2026-10-16/prop_brier_comparison.md) |
| **MLB / MLS / UFC / esports game and prop targets** | **Not verified in this reference** | Require target-specific market and climatology, identical locked cohort | **No claimed leader** until a scored, timestamp-valid, reproducible artifact is supplied |

**Definitions:** “Leader” means the smallest measured loss *within a precisely named comparison*. “Research” does not mean deployed, certified, prospective, or profitable. Check each source's cutoff and preservation caveats before adopting.

## Brier score: what range actually means

For a **binary** event (home winner, over a specified line, yes/no player prop), with predicted event probability p and result y ∈ {0,1}:

**Brier = mean[(p − y)²]**. **Lower is better.** The theoretical range is **0 to 1** per event and on the sample mean.

| Score | What it means, **for balanced binary targets only** |
| ---: | --- |
| **0.00** | Perfect probabilistic predictions on the evaluated outcomes |
| **0.10–0.15** | Far better than a 0.25 constant baseline; requires checking event difficulty, forecast vintage and leakage |
| **0.15–0.20** | Substantial improvement over 0.25 on the same balanced cohort |
| **0.20–0.23** | Often a meaningful region for game-winner research; compare to same-game market/Elo and confidence intervals |
| **0.23–0.25** | Slight-to-modest improvement over a 50/50 reference; may be worse than a stronger incumbent or market |
| **0.25** | Constant 50% forecast. This is a *reference*, not automatically the best simple baseline |
| **Above 0.25** | Worse than constant 50% on the exact same binary targets; does not by itself prove anti-predictive skill |

**Do not turn those rows into universal grades or adoption thresholds.** The proper constant forecast for an event occurring with frequency q is p=q, with theoretical expected Brier **q(1−q)**. Example: if only 5% of players reach a rare threshold, that climatology scores 0.0475 in expectation. A Brier of 0.10 on that rare prop is *bad*, despite looking “excellent” on a generic 0.25 scale.

Examples: a 90% prediction of the **correct** outcome incurs 0.01; 90% on the **wrong** outcome incurs 0.81; a 50/50 prediction incurs 0.25. For comparisons, calculate:

**Brier skill score = 1 − (candidate Brier / matched reference Brier).** Positive means the candidate beats that particular reference. Specify whether the reference is climatology, incumbent, or de-vigged market.

**Multiclass:** For K exclusive outcomes, the unnormalized multiclass sum-of-squared-probability-errors Brier has range **0–2**, not 0–1, and depends on the number and probabilities of classes. **Never place NFL joint play-transition Brier ~0.81 alongside binary winner/prop Brier ~0.25 in the same ranking.** Different class vocabularies, conditioning, weights, and normalization also prohibit comparison without a shared scoring contract.

## Correct baseline and metric for each model task

| Task | Primary scoring | Required comparators | Unit / contract |
| --- | --- | --- | --- |
| Binary game winner | **Brier + log loss** | Constant **training-only** home-rate; 0.5 check; same-game incumbent/Elo; **as-of**, de-vigged market when valid | One **game** per grade; record ties/OT rule, kickoff and forecast lock |
| ATS, game total O/U, team/player prop at a line | **Binary Brier + log loss**, calibration | Pre-line event base rate / no-skill policy; **same line, book, side, settlement**, de-vigged market; incumbent | One **settled contract** (correlated quotes clustered by game/player-game); never use the postgame-selected starter |
| Team points / margin / total points or goals | **CRPS** for predictive distribution; **MAE** for point mean/median; intervals and tails | Same-target historical distribution or point baseline; pregame market **line/total** for MAE where legitimate | **Points/goals units**, same league and scoring rule. **There is no Brier for a raw continuous point forecast**; first define a binary threshold to use Brier |
| Player counts/yards (carries, targets, attempts, shots, aces) | **Discrete/continuous CRPS**, MAE, bias, 80% coverage; threshold Brier when pricing a specific line | Player trailing history, league+position rate, role-conditioned forecast, actual offered line/market | Player-game, availability-conditioned or unconditional population explicitly named; cluster quote-level lines by player-game |
| NFL play intent / play-call policy | Multiclass log loss + appropriately normalized Brier; accuracy diagnostic | League **same situation/intent** cell, historical team, current team, blended | Observed **pre-play** situation, not the simulator's generated mixture |
| NFL play transition (event+yards+conversion+TD) | Multiclass log loss/Brier + yard CRPS and first-down Brier | League situation cell, historical team, current-only, blended, simple offense/defense | Identical event vocabulary/support and observed-play cohort; results do **not** directly imply game-winner improvement |
| NHL goal/SOG distributions | Goal/SOG CRPS, winner Brier, count errors | Team historical scoring/shot rates; matched pregame market if accessible | Match length, OT, shootout and official/statistical goal definitions must match |

**Test at two levels:** (1) isolate the component using real observed situations; (2) if it earns a small simulator run, score full-game winners, points, distributions, workloads and legal-state coverage on identical game/seed inputs. One gate does not replace the other.

## More precise leaders: continuous scores, points, and workload

There is no universal “points Brier.” These are **different target scales** and should stay in separate leaderboards.

| League / target | Point-estimate leader and score | Same-cohort controls / meaning | Evidence |
| --- | --- | --- | --- |
| **NFL points forecast v1 (2025, n=255)** | v1 expected-margin MAE **10.67 points**; total MAE **10.61** | Closing spread MAE **9.97**; closing total **10.17**. **Market wins** these comparisons, and closing lines are not the same as an early pregame lock | [NFL model card](model-cards/nfl.md) |
| **NFL SLC team-points CRPS (2026 W1–8, n=121)** | Home points: **V1 5.33**; away points: **V2 5.94** | V1.5 **5.38 / 6.03** home/away; V2 **5.47 / 5.94**; V1 **5.33 / 6.11**. **No single universal winner.** Thin, retrospective-exposed 15–20-seed estimates | [SLC matched report](research/SLC-V2-VS-V15-RESULTS-2026-11-04.md) |
| **NBA team-score MAE (2024–2025 holdout, n=2,460)** | **G2 efficiency**, home **9.736**, away **9.745**, spread **11.191**, total **15.797** points | G3 similar (9.741 / 9.749 / 11.194 / 15.805), G2/G3 improvements over fixed-points baseline; no justified G2-vs-G3 superiority | [NBA Phase 1](NBA-GAME-MODEL-PHASE1.md) |
| **NBA margin / total CRPS** | **G3**, margin CRPS **7.996**, total CRPS **11.142** (same 2024–2025 test) | A forecast *distribution* score, unlike a winner-Brier or points-MAE | [NBA Phase 1](NBA-GAME-MODEL-PHASE1.md) |
| **NHL team goals CRPS** | Historical special-teams xG candidate **0.958671** vs 5v5-only **0.960078**, 9,147 games | Difference has insufficient CRPS uncertainty evidence; **not adopted**. Compare only NHL goals to NHL goals | [NHL learnings](LEARNINGS-nhl.md) |
| **Tennis total games CRPS, 2023–2026 best-of-three** | Direct format+surface+competitiveness: ATP **3.359** (n=11,766); WTA **3.231** (n=13,062) | Point simulator ATP **3.533**, WTA **3.557**, both worse. Total-games MAE direct **5.045 ATP / 4.865 WTA** | [Total-games backtest](TENNIS-TOTAL-GAMES-BACKTEST-2026-10-16.md) |
| **NFL SLC player workload (2026 W1–8, n=121 games)** | **V1.5** lowest reported MAE: carries **3.53**, targets **2.21**, receptions **1.65**, rushing yards **20.07**, receiving yards **21.01** (on players recording the respective stat) | V1 and V2 worse on all five point estimates; workload **does not** imply winner Brier superiority | [SLC matched report](research/SLC-V2-VS-V15-RESULTS-2026-11-04.md) |
| **NCAAF player distributions** | **No adopted leader.** 2025 positive-usage audit: candidate pass attempts CRPS **4.155** vs trailing-five **3.153**; rushing distribution **1.640 vs 1.537** | **Trailing-five wins these tests.** Reject former all-row adoption claims until participation is modeled | [FBS props decision](DECISION-forecast-first-leagues-market-first-props-2026-10-20.md) |

For each future continuous forecast, store both the **point** estimate's MAE and the **distribution**'s CRPS, mean bias, dispersion, 80% interval coverage and relevant tail calibration. Being closer on mean points does not prove the simulated tail is realistic.

## NFL transition and individual-rule baseline: know precisely what failed

The latest [transition-strength walk-forward](research/slc-transition-walk-forward-2026-11-10/README.md) evaluates **observed play categories**, not 2026 full-game predictions. Same supported rows for each arm:

| Target year | League category log loss / multiclass Brier | Historical team | Best current/blend candidate | Decision |
| --- | --- | --- | --- | --- |
| 2025, 32,732 plays | **1.9920 / 0.8135** | 2.0576 / 0.8254 | Blend N0=4: 2.0230 / 0.8196 | **League wins** |
| 2026, 12,478 plays | **1.9811 / 0.8103** | 2.0450 / 0.8217 | Approx current-only: 2.0063 / 0.8155 | **League wins** |

**Limitations:** The “current-only” arm was implemented using N0=1e-9 and a neutral profile, not an independent estimator. Week 1 incorrectly used historical team strength for current-only. The audit froze by **week**, not the V1.5 90-minute target-game cutoff, and it does not prove historical source acquisition dates. No end-to-end V1.5 winner Brier comparison exists for this candidate. **Do not promote the joint transition model on these results.**

**Individual components sometimes help:** the [conditional-outcome audit](research/slc-v2-conditional-outcome-audit-2026-11-10/README.md) records offense-only 2025 fourth-down policy log loss **0.4855 vs league 0.4892**, Brier **0.2803 vs 0.2829**. The 2025 third-and-1/2 offense-only Brier gain was roughly **0.00049**, and offense-specific sack-yard CRPS gained roughly **0.00094** overall (2025), **0.00804** (2026). These are narrow, exploratory effects, **not independently promoted rules**. Earlier [temporal-window play-calling](research/TEMPORAL-WINDOW-2026-11-02/RESULTS.md) shows current-season blends improve play-call sequence likelihood against historical-only and league controls on their own population. **Do not remove proven useful play-call conditioning because outcome-category multipliers failed.**

For fourth down, distinguish **P(action | reached real fourth down)** from **how often a simulator reaches fourth-and-short**. One can be calibrated while the other is wrong.

## Prop benchmark cautions

- **NFL strict valid comparator:** forward Platt **0.2502** versus market **0.2469**, 20,926 quote rows / 628 player-games (W3–5); compare only exact same lines and as-of snapshots. Broader corrected-pregame selection scored v2-Platt **0.2486**, market **0.2463** on about 32,758 items, but **is a distinct cohort**. See [NFL decisions](RESULTS-nfl-decisions-2026-10-17.md) and [NFL learnings](LEARNINGS-nfl.md).
- **Discard leaky number:** NFL served-hit-rate “Brier **0.1911**” included the target game in its own history. It **is not a valid baseline**. Earlier prop audits also selected QBs by their *postgame* attempts; use pregame selection only. [Prop baseline audit](RESULTS-nfl-prop-baseline-2026-10-16.md).
- **Market gap:** A model better than an older in-house model but still worse than the contemporaneous de-vigged market has **not** demonstrated independent market edge. Test market + candidate versus market-only for claims of incremental information. Grades are not profit and do not substitute for EV, settlement, liquidity and CLV.
- **Tennis props:** threshold-by-threshold scores are meaningful only for the same tour, cutoff and population. ATP aces ≥10 P1 Brier **0.11105** and WTA aces ≥10 **0.02498** do **not** mean WTA is a more capable model: the event base rates differ. [Tennis cross-target](../research/tennis/point-events/2026-10-16/prop_brier_comparison.md).

## Evidence tiers and promotion rules

1. **Tier 0, illustrative:** simulated/self-reported/external author markers without identical verified target and population. Never an adoption benchmark.
2. **Tier 1, development:** historical reconstruction, exposed holdout, retrospectively chosen feature/threshold, missing timestamps or model/source parity. Good for debugging; label it.
3. **Tier 2, held-out:** frozen chronological forecasts, model/code/input hashes, independent untouched test, fixed grading contract, uncertainty and complete coverage. May justify more testing.
4. **Tier 3, prospective:** immutable pre-event lock and as-of source evidence, genuinely unseen outcomes, live pipeline parity, adequate game/player-game clusters, independent settlement and calibrated market comparison. Needed for durable live-performance claims.

**Promotion gate:**
- Beat the appropriate **same-population** low-cost model and incumbent on primary metric(s) **and** show game/player-game/market-clustered paired uncertainty. If two candidates differ only within noise, record *tie*, not a promoted leader.
- For **game-winner forecasts**, lower both Brier and log loss, with predeclared uncertainty and validity gates. For points, check CRPS **and** mean error, tails/coverage and legal outcome support; do not optimize one mean alone.
- Market superiority is required for claims of **market increment**, not merely for publishing a correctly labeled research forecast.
- Check cutoffs: 90 minutes pre-kickoff and 10-hour game-result lag for the V1.5/SLC research protocol; never treat a pregame-looking retrospective source with unverifiable revision time as truly prospective.
- Across sportsbook props, do not count thousands of correlated lines as thousands of independent samples. Bootstrap **player-games** (or games/market blocks as appropriate). Treat in-play quotes, duplicate/missing lines, voids and ambiguous starting-player selection as explicit exclusions.
- Preserve failures, raw baselines, hashes and eligibility counts; never silently update a frozen benchmark after seeing a challenger.

## Template: add or revise an entry after *every* scored model run

Add a versioned, linked row to the relevant section. Do not overwrite an old cohort as if it never existed. Required fields:

| Field | Required value |
| --- | --- |
| Evaluation key | league / target / market+line / settlement / season+weeks / cohort hash |
| Model | model ID + git SHA + config/parameters + input/source SHA |
| Forecast time | as-of UTC / kickoff or start UTC / availability and revision guarantees |
| Eligibility | all candidates/graded/excluded / underlying **independent** cluster count |
| Scores | Brier/log loss (binary); CRPS/MAE (continuous); calibration/coverage/tails |
| Comparators | constant and league baseline / prior incumbent / independent **matched** no-vig market where eligible |
| Inference | paired difference, game/player-game clustered 95% CI, any multiple-testing correction |
| Status | tier, adoption/decline decision, limitations, read-only reproduction path |
| Supersession | link to prior result and exact reason new result changes that result |

**When starting any model work:** first identify the precise target and its current incumbent here, read the linked full report, recheck that the snapshot is still current, and write down the predeclared comparator and cutoff. If no supported benchmark exists, **say “none verified”** and build an honest simple baseline before training the challenger. Update this file only after source-backed scores are reproducible; otherwise add an explicitly pending note.
