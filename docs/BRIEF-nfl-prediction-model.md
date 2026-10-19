# NFL prediction model brief

**Status as of 2026-10-18.** This is the authoritative entry point for NFL prediction surfaces, current evidence, build order and adoption gates. The five earlier NFL documents remain the research record. Their original measurements are retained with their populations and dates; measurements from different samples are not combined into one leaderboard.

## The question

Before kickoff, what can Legendary Picks say about (1) which team wins, (2) the distribution of the final team scores and game margin/total, and (3) a player's statistical outcome and probability of clearing a specific prop line?

These are three prediction surfaces with independent evidence and approval. NFL has a live player-prop product surface and a deployed legacy game-winner baseline. It does **not** yet have an adopted, validated joint home/away score distribution. The current score-distribution research produces a winner probability that beats its constant reference, but its spread and total probabilities are worse than their constants and must not be presented as forecasts. The existence of a live surface is not evidence that its probabilities passed calibration or prospective validation.

## Build order and current position

The surfaces are organized in the order used by the existing NFL research, but their adoption gates are independent. A result on one surface does not pass another.

1. **Game winner. Current position: baseline and chronological research exist; no new candidate is approved.** The operational legacy baseline is `nfl-v1` points. A v1+Elo stack improved the 2011-2023 result on its own historical sample, while the 2026-10-18 success-rate experiment found no incremental gain over EPA. Keep the constant, Elo and market comparisons on identical games before considering any candidate.
2. **Team score distribution. Current position: marginal distributions and line-event probabilities have been evaluated; the joint score-distribution experiment failed.** The 2026-10-18 research object uses independent Normal margin and total marginals. It is not a joint home/away score distribution and can imply negative scores. The earlier nearest-neighbor score-pair sampler failed its pre-registered gate. The current cover and over probabilities are not forecasts.
3. **Player props. Current position: a product surface is live; research models are measured by market, but CP3 has not passed.** This includes passing, rushing and receiving yards, plus count markets such as attempts, completions, receptions, carries and touchdowns. Marcel-lite, Spec B, forward Platt and the rushing-carries candidates are distinct implementations and evaluation cohorts. Keep point error, line probabilities and full-stat distributions separate. Each market needs its own adoption decision.

## Baseline ladder

`✓` means an implementation or scored reference exists, not that it passed a gate. `◐` means partial or not matched to the current evaluation population. `—` means no corresponding implementation or benchmark is established.

| Surface | Constant | Prior-season rate | Elo or equivalent | Incumbent | Market benchmark |
|---|---|---|---|---|---|
| Game winner | ✓ Constant/home-rate references are scored; the 2023-2025 distribution evaluation reports 0.2474. | ◐ `nfl-v1` carries previous-season team ratings, but a standalone prior-season win-rate result is not reported on the same 720-game feature-test population. | ✓ 538 Elo replica and v1+Elo stack exist. The stack's 0.2197 result is from 2011-2023 and is not directly comparable with the 2023-2025 results below. | ✓ `nfl-v1` points is described as the deployed legacy baseline in the model card. Its current CP5 status conflicts with the checkpoint table; see reconciliation. | ✓ De-vigged moneyline results exist. In the 2023-2025 game-distribution evaluation, market Brier was 0.2088 on 719 decisive games. |
| Team score distribution | ✓ Event constants: cover Brier 0.2498 and over Brier 0.2499 in the 2023-2025 evaluation. | ◐ Historical score-pair sampling from earlier games was implemented, but failed its pre-registered evaluation; no separate prior-season-rate distribution is established. | ✓ EPA-derived margin and total means are implemented. This is not a joint score PMF. | ◐ Independent Normal margin and total marginals exist and can be frozen at lock; coherent joint home/away scores have not passed validation. | ◐ Game lines are recorded, but two-sided spread and total prices are absent in the cited evaluation, so no market-implied cover/over probability is available. Winner moneylines are available. |
| Player props | ✓ Constant 0.5 probability reference is reported. | ◐ Spec B uses historical player/team rates, but a standalone prior-season probability baseline is not reported for each current market population. | ◐ Marcel-lite and Spec B are player-history references; there is no literal player-prop Elo. | ✓ A player-prop surface is live. The model card identifies Marcel-lite as the live route, while the checkpoint table calls v2-Platt live; the exact route/version mapping is unresolved. | ✓ De-vigged line probabilities are scored. Results are market- and cohort-specific; do not pool one market's approval into another. |

## Measured status

### Game winner

The 2026-10-18 feature experiment scored M0 EPA control at Brier **0.2243**, M1 EPA plus success rate at **0.2242**, and success-only S at **0.2275** on 720 chronological 2023-2025 games. The paired week-clustered M1-minus-M0 Brier interval was `[-0.00074, +0.00056]`; S-minus-M0 was `[−0.00204, +0.00857]`. Both span zero. This is a null result for adding success rate to the game model, not evidence to tune the feature. The source report also notes that M0 is not the v2 ridge estimator in the model card.

The separately reported game-distribution evaluation has winner Brier **0.2243 vs 0.2474** for the constant on 719 decisive games. The de-vigged market scored 0.2088; model-minus-market was `+0.01542` with a game-clustered interval `[+0.01018, +0.02106]`. These values are from the cited 2023-2025 evaluation and must not be ranked against the model card's 2025-only v1 result or 2011-2023 Elo result as if they shared a population.

The Elo stack scored 0.2197 on 3,158 games in 2011-2023, with a paired difference of `−0.0032` versus recalibrated v1 and interval `[−0.0050, −0.0014]`. That historical result supports keeping Elo in the ladder. A same-population Elo comparison for the newer 720-game feature experiment is not reported here.

Sources: [success-rate and distribution results, commit `0440911`](https://github.com/micahp/legendarypicks/blob/0440911980d5ed3f161fff7da274fc2e9f1554b8/docs/RESULTS-nfl-success-rate-and-distributions-2026-10-18.md), [Elo and era results, commit `c59ab7e`](https://github.com/micahp/legendarypicks/blob/c59ab7ead9777f6cf7b994a7d360780c5e9b6961/docs/RESULTS-nfl-elo-and-era-2026-10-13.md).

### Team score distribution

The 2026-10-18 evaluation reports winner Brier **0.2243 vs 0.2474** constant; spread cover Brier **0.2646 vs 0.2498** constant; and total over Brier **0.2634 vs 0.2499** constant. Spread and total probabilities are worse than their constants. They must never be presented as forecasts. Spread and total prices are not available in this evaluation, so market-implied probabilities were not fabricated.

The current object stores separate Normal margin and total marginals. It is not a joint score distribution, has no score-pair simulation, and can imply negative scores. The earlier nearest-neighbor score-pair sampler was evaluated on 1,519 games from 2020-2025: winner Brier was 0.2355 vs 0.2285 for the Normal reference, cover-calibration SSE was 0.3105 vs 0.2115, and it failed its pre-registered gate. That experiment stopped without retuning.

Sources: [current success-rate and distribution results, commit `0440911`](https://github.com/micahp/legendarypicks/blob/0440911980d5ed3f161fff7da274fc2e9f1554b8/docs/RESULTS-nfl-success-rate-and-distributions-2026-10-18.md), [prior score-pair sampler results](RESULTS-A2-nfl-score-dist-2026-10-11.md).

### Player props

On 24,558 v2-Platt line items from weeks 3-5, Brier was **0.2486** versus **0.2463** for the market; the paired player-game-clustered Platt-minus-market difference was `+0.00227 ± 0.00222`. The map improves raw v2's Brier, but it does not establish a market advantage. The corrected pregame-population raw-v2 passing-yards comparison at the earlier `K_T_ATT=8` setting was `+0.03219 ± 0.01871` Brier versus market. After `K_T_ATT` was changed to 4, the later raw-v2 passing-yards gap was `+0.02935 ± 0.01812`; in the v2-Platt map-applied table the passing-yards gap was `+0.00866 ± 0.00614`. These numbers use different configurations or forecast rows and are not interchangeable. All positive gaps mean the model Brier is higher than the market Brier.

The Spec B simulated p10-p90 bands over-covered the nominal 80% level in the corrected 2026 population:

| Market | Observed p10-p90 coverage | v2-Platt Brier gap vs market, where reported | Current status |
|---|---:|---:|---|
| Receiving yards | 82.7% | `−0.00069 ± 0.00234` | Not approved; distribution CP3 not passed. |
| Receptions | 86.1% | `+0.00602 ± 0.00373` | Not approved; market ahead in the cited comparison. |
| Passing yards | 85.0% | `+0.00866 ± 0.00614` for v2-Platt; raw-v2 gaps are listed above. | Not approved; market ahead in the cited comparisons. |
| Pass attempts | 84.1% | `+0.00113 ± 0.00578` | Not approved; interval spans zero. |
| Pass completions | 88.2% | `+0.00315 ± 0.00729` | Not approved; interval spans zero. |
| Passing touchdowns | 97.4% | `−0.00031 ± 0.01818` | Not approved; interval spans zero. |

The p10-p90 results are for the Spec B predictive distributions; they are not proof that the live route or the Platt map itself has those distributional properties. The Platt candidate calibrates offered-line probabilities and does not create an independent full-stat distribution. Point-MAE gains are also separate: on 2025, carries MAE was 1.153 vs 1.108 for Marcel-lite, a `+0.044` gap with clustered interval `[+0.010, +0.077]`, so carries fail that comparison ([corrected Oct 17 result](RESULTS-nfl-decisions-2026-10-17.md)). The earlier 1.182 vs 1.108 (`+0.074`) result in the model card is an older engine result, explicitly superseded by that report. Targets, rushing yards, rushing touchdowns and receiving touchdowns have point-MAE measurements but no approval follows from them; their line-probability and full-distribution gates must be evaluated separately.

Rushing carries candidates v1-v4 are all `NOT_ADOPTED`. v4 has the best reported CRPS, 1.7710 for 2025 and 1.8015 for 2026, but the recovery audit established that **only B0 reproduces** from the frozen artifacts. v2 misses exact CRPS/MAE reproduction; v1 lacks its 2025 fit and only matches rounded 2026 metrics; v3 and v4 omit required frozen parameters. A candidate that cannot reproduce its own reported scores is not eligible for adoption, regardless of its reported score. See [the recovery report at commit `186d95c`](https://github.com/micahp/legendarypicks/blob/186d95c740cbdba09deb831eb4f20b27e817ea5c/research/nfl/DISCRETE-PROP-EVAL-RECOVERY-20261018.md) and the [universal discrete-prop evaluation contract](https://github.com/micahp/legendarypicks/blob/186d95c740cbdba09deb831eb4f20b27e817ea5c/docs/EVAL-CONTRACT-discrete-props.md).

Sources: [corrected prop decisions, commit `2221161`](https://github.com/micahp/legendarypicks/blob/2221161d2c8a6c74c3622d8e5b4867013183af2b/docs/RESULTS-nfl-decisions-2026-10-17.md), [recovered carries evaluation, commit `186d95c`](https://github.com/micahp/legendarypicks/blob/186d95c740cbdba09deb831eb4f20b27e817ea5c/research/nfl/DISCRETE-PROP-EVAL-RECOVERY-20261018.md).

## Five checkpoints

The definitions below follow the shared [model checkpoint standard](MODEL-CHECKPOINTS.md). A `✓` records that the checkpoint work is present; it does not mean the candidate passed its comparison. **No NFL surface has passed CP4.**

| # | Checkpoint | What must be true to mark it passed |
|---|---|---|
| **CP1** | **Baseline established** | A no-information and at least one simple reference are scored on the same population, with sample size and a stated population definition. Not a leaderboard, a floor. |
| **CP2** | **Candidate validated chronologically** | The candidate is fit only on information available before each forecast, scored walk-forward, compared to the CP1 baselines with a paired, clustered interval, and the population is identical across every model compared. |
| **CP3** | **Distribution calibrated** | The predictive distribution is scored on proper scores (CRPS, log score) **and** calibration (PIT, reliability, zero-event reliability where relevant) on identical observations, with the per-observation PMFs preserved. Point-forecast accuracy is not calibration. |
| **CP4** | **Prospective confirmation** | Frozen, immutable, pre-event forecasts scored against outcomes that were unknown when the forecast was written. Retrospective work cannot pass this checkpoint, no matter how good it looks. |
| **CP5** | **Production integration approved** | An explicit decision by Micah, with the surface named (table, route, page), the presentation constraints stated, and the model version pinned. Research completion is not approval. |

| Surface | CP1: baseline established | CP2: chronological validation | CP3: distribution calibrated | CP4: prospective confirmation | CP5: production integration approved |
|---|---|---|---|---|---|
| Game winner | ✓ Constant and simple references scored. | ✓ Walk-forward results exist; the 2023-2025 success-rate result is null and its matched Elo comparison is not reported. | ✗ No complete calibrated-distribution pass under the shared definition. | ✗ | ✗ in the checkpoint source. The model card separately calls `nfl-v1` a deployed legacy baseline; existing deployment is not silently relabeled as a CP5 pass. |
| Team score distribution | ✓ Constant references scored. | ✓ Chronological scoring exists for the marginals and the historical score-pair experiment. | ✗ Current cover and over probabilities lose to constants; the score-pair sampler failed its gate. | ✗ | ✗ |
| Player props | ✓ Constant, incumbent and market references exist. | ✓ Comparisons exist, but results vary by market and cohort. | ✗ p10-p90 coverage is 82.7%-97.4% against nominal 80%; full calibration and reproducible distribution artifacts are not established across markets. | ✗ | Live product surface, but this is not recorded as a CP5 pass for a validated candidate. CP3 is unmet, and the precise live model/version is unresolved across the source docs. |

The governing checkpoint rules are: a baseline tick is implementation, not a pass; a failed experiment remains documented; CP4 requires immutable pre-event forecasts; and CP5 requires Micah's explicit decision naming the surface and version. The copied checkpoint source preserves the wider league standard without changing its status.

## Independent adoption gates

These gates apply separately. They do not introduce a new numeric cutoff or automatically adopt a candidate.

Approval is per surface and per market: passing approval is not receiving approval, and winner approval is not spread approval.

| Surface | Evidence required before an adoption decision | What does not transfer |
|---|---|---|
| **Game winner** | Chronological predictions on identical games; proper probability score compared with the constant baseline and Elo; paired week-clustered interval; market comparison reported separately. Preserve the prediction-time information set and population. | A winner result does not approve margin, spread, total or player statistics. A lower Brier on a different season/sample is not a comparison. |
| **Team score distribution** | Evaluate margin and total distributions with CRPS, PIT and calibration on identical games. Evaluate spread and total as cover/over probability forecasts against their own constant references and, when two-sided prices exist, market-implied probabilities, not as point-accuracy claims. Report pushes and settlement rules. The distributions must be coherent with the score outputs. | Winner Brier does not approve spread or total probabilities. Margin/total point errors or nominal interval coverage alone do not establish calibrated distributions. |
| **Player props, one market at a time** | For each named market and version, preserve the full stat PMF/CDF and compare point error, line-probability proper score and distribution calibration separately on the same eligible player-game/line population. Use paired player-game-clustered uncertainty and market-specific settlement, line and availability rules. | Approval for passing yards does not approve passing attempts, receiving yards, receptions, carries, rushing yards or touchdowns. One market's result cannot be pooled to approve another. A Platt map at quoted lines does not approve the full-stat distribution. |

For all three surfaces, a candidate must first reproduce its reported results from its frozen source, exact parameter bytes and fingerprinted inputs. Demonstrate the reproduction before an adoption decision; do not accept an aggregate report as proof. The required artifacts are in the league- and market-agnostic [`docs/EVAL-CONTRACT-discrete-props.md`](https://github.com/micahp/legendarypicks/blob/186d95c740cbdba09deb831eb4f20b27e817ea5c/docs/EVAL-CONTRACT-discrete-props.md).

## Presentation constraints

- Keep model identity, event target, evaluation population and time window beside every score. Do not compare different surfaces or cohorts as one leaderboard.
- Do not describe the NFL winner model as market-leading. The cited 2023-2025 market benchmark is better.
- Do not present the current research spread/total probabilities as forecasts. Their Briers are worse than the constant references, and the available data lack two-sided prices for market-implied comparison.
- If live player props are shown, label their model/version, market, line, data cutoff and uncertainty. State that player-prop CP3 has not passed; do not imply calibration, market edge or approval from another market.
- Keep expected points or a point estimate distinct from a full predictive distribution. Do not imply that the current independent margin/total normals are a joint score simulator.
- Do not call a result prospective unless the immutable prediction was recorded before the event. Historical reconstruction does not pass CP4.

## Reconciliation of the five existing documents

| Existing document | Claim or status that is stale, conflicting or easy to misread | Resolution in this brief |
|---|---|---|
| [NFL research index](INDEX-nfl-model-research-2026-10-12.md) | Its branch inventory and “Spec B start” queue are a 2026-10-12 snapshot. It predates the corrected prop results and the 2026-10-18 tests. It distinguishes a kept **market-derived** preseason prior from an independent preseason prior that was tested and not kept; its later shotgun paragraph's shorthand “kept features” can obscure that distinction. A league-wide shotgun-era test later failed, but it is not the proposed team-level shotgun differential. | Keep it as historical inventory; date the completed/null/failed work and mark Spec B implemented. Read the two prior results separately, and keep league-era shotgun separate from team-level shotgun. Do not treat old queue items or branch counts as current. |
| [NFL model-input research](RESEARCH-nfl-model-inputs-2026-10-11.md) | “Nothing here has been run yet” and success rate as an open lever describe the original agenda. Carryover, a market-derived prior, week-bucket uncertainty and a retrospective QBI feature were subsequently tested; their outcomes differ. Its 0.0021 QB/availability/EPA-stack gain was called the “best” own-data stack, but the later v1+Elo report measured a 0.0032 gain on the same 2011-2023, 3,158-game population and recalibrated-v1 baseline. | Preserve each named experiment and its own status. The Elo result supersedes “best” on the matched sample ([backfill/features](RESULTS-nfl-backfill-features-2026-10-11.md), [Elo](RESULTS-nfl-elo-and-era-2026-10-13.md)). Mark success rate completed with no established incremental gain. Keep independent-model and market-assisted scoreboards separate. |
| [NFL feature plan](PLAN-nfl-features-2026-10-11.md) | Its v1/market Briers (0.2244/0.2105, 2010-2025) and its feature-screening keep rule differ in population and purpose from the 2023-2025 branch results and the production approval checkpoints. | Retain the historical figures with their original population and source ([market baseline](RESULTS-market-baseline-2010-2025-2026-10-11.md)). Do not rank 0.2244 against 0.2243 or treat the 2023-2025 constant as market. Treat the plan's feature keep rule as a research-screening rule, not as approval for a surface or release. The success-rate M0/M1 test is a measured null. |
| [NFL model card](model-cards/nfl.md) | It calls v1 points adopted/deployed while the checkpoint source marks game-winner CP5 ✗. It identifies Marcel-lite as the live prop route while the checkpoint table labels the prop surface live under v2-Platt, whose branch verdict is `RESEARCH_CANDIDATE_ONLY`. The card's strict and older prop cohorts differ from the later 24,558-item result; its carries MAE is the earlier 1.182 vs 1.108 (+0.074), later superseded by 1.153 vs 1.108 (+0.044). Its “Next steps” are not current. | Record the legacy v1 deployment and checkpoint status as a mismatch, not a silently resolved approval. Treat props as a live product surface, but do not claim v2-Platt is the served version without a route/version reconciliation. Keep strict, corrected and legacy cohorts labeled separately; identify the carries figure by engine/result date; use this brief instead of the old queue. |
| [NFL model handoff](HANDOFF-nfl-model-2026-10-11.md) | Its week-6 deadline and tasks 4.2, 4.4 and 4.5 are written as future work, though score-pair sampling and Spec B have since been evaluated. Task 4.3 also describes QB adjustment work as future, although a retrospective QBI feature test exists and was not kept. The handoff's “fake scores” note describes the earlier playoff-simulation implementation; the model card later names `placeholder-split-40` as its default. | Keep it as implementation history and label the tasks' current status in place: 4.2 failed its registered gate, 4.3 has a retrospective QBI result but its as-of operational pipeline is not established here, 4.4 was implemented/evaluated, and 4.5 has retrospective probabilities but failed spread/total constants and lacks cited two-sided prices. Treat the 4.1 simulation wording as historical and keep playoff odds distinct from the game-distribution experiment. |

Other headline values in the older docs, including the v1 2025 holdout and v1+Elo 2011-2023 score, are not silently superseded: they use different populations and remain valid only with their original labels. The precise live player-prop version and documented CP5 decision for the legacy winner route remain unresolved; neither is inferred here.

## Reproducibility contract

Before considering any NFL candidate for adoption:

1. Freeze and retain the model source commit, parameter file bytes and checksums, input snapshot fingerprint, population definition, outcome ledger, forecast cutoff and reproduction command.
2. Export the observation-level predictive PMF/CDF over its declared support for every distribution forecast, with outcome and canonical game/player/market identifiers.
3. Re-run the frozen code and frozen parameters on that frozen population. Recompute the originally reported scores within the stated deterministic tolerance, or record the stochastic seeds and variation required by the experiment.
4. If any reported statistic cannot be reproduced, exclude that candidate from adoption consideration. Do not refit, interpolate, substitute a plausible estimate or use its attractive aggregate score as a reason to waive the failure.

This rule follows the v1-v4 carries recovery: only B0 reproduced; the candidate artifacts did not. See the [recovery report](https://github.com/micahp/legendarypicks/blob/186d95c740cbdba09deb831eb4f20b27e817ea5c/research/nfl/DISCRETE-PROP-EVAL-RECOVERY-20261018.md) and the [league- and market-agnostic contract](https://github.com/micahp/legendarypicks/blob/186d95c740cbdba09deb831eb4f20b27e817ea5c/docs/EVAL-CONTRACT-discrete-props.md).
