# NFL prop projection backtest, 2026 Weeks 2–9

## Results and interpretation (audited November 13, 2026)

**Headline:** the **raw Spec B v2 probabilities do not beat the de-vigged sportsbook market** on this eight-week retrospective sample. A new quote-timestamp audit excluded 16.1% of selected lines as not strictly pre-kickoff, and a matched Weeks 3–9 comparison reduces the apparent forward Platt advantage from 0.001890 to 0.001055 Brier (44.2%). Forward-only Platt recalibration materially reduces raw-model Brier error and beats the market on the *same graded lines* in each of Weeks 6–9. The calibrated edge is small in the pooled Weeks 3–9 comparison and is **not yet validated as a deployable betting edge**. The 38 original book/stat disagreements are now fully explained by one weekly receiving-stat ingestion defect affecting two lateral plays; the separately saved corrected-history what-if closes all 38 without changing the graded population.

The audit covers **65,448** eligible book/line observations across **117** games and **360** distinct players, representing **3,805** player-game-market point estimates. These are not 65,448 independent bets: multiple thresholds and sportsbooks repeatedly score the same realized player stat. Three of the 120 games in the finalized-roster universe have no eligible graded props. The finished gamebook roster labels were checked *after* projections, never fed into them.

### Probability accuracy: smaller Brier is better

| Week | Quoted lines | Raw Spec B v2 | Forward Platt | De-vigged market | 50% reference | Recorded-settlement disagreements |
|---|---:|---:|---:|---:|---:|---:|
| 2 | 8,200 | 0.26954 | — | 0.24538 | 0.25000 | 0 |
| 3 | 7,862 | 0.28286 | 0.25004 | 0.24625 | 0.25000 | 23 |
| 4 | 8,995 | 0.28535 | 0.24788 | 0.24686 | 0.25000 | 15 |
| 5 | 7,701 | 0.25808 | 0.24624 | 0.24574 | 0.25000 | 0 |
| 6 | 7,069 | 0.26347 | **0.24230** | 0.24572 | 0.25000 | 0 |
| 7 | 8,737 | 0.24641 | **0.23848** | 0.24544 | 0.25000 | 0 |
| 8 | 8,541 | 0.26532 | **0.24510** | 0.24535 | 0.25000 | 0 |
| 9 | 8,343 | 0.25035 | **0.23759** | 0.24524 | 0.25000 | 0 |

These are **line-count-weighted** comparisons, not averages of weekly scores:

- **All Weeks 2–9 (65,448 quoted lines):** raw Spec B v2 **0.26522**, de-vigged market **0.24575**, constant 50% **0.25000**. The raw model loses to the market in **all eight weeks**. No pooled Platt score is attributed to this entire span because Week 2 had no fitted map.
- **Weeks 3–9, matched 57,248 lines:** forward Platt **0.24392**, de-vigged market **0.24581**, raw Spec B v2 **0.26460**, constant 50% **0.25000**. Platt improves on the market by **0.00189 Brier points** on these lines, and beats it in **four of seven weeks** (Weeks 6–9). This is a descriptive difference, **not** a significance estimate or evidence of positive expected betting returns.
- The strongest observed calibrated weeks are **Week 7 (0.23848 versus 0.24544 market)** and **Week 9 (0.23759 versus 0.24524 market)**. Week 8's margin is only **0.00025**.

The Platt maps' logit slopes are far below one: **0.197** for Week 3 and **0.346** for Week 9. This means the fitted layer is **aggressively compressing the model's extreme probabilities**, not making small adjustments. For example, under the Week 9 map a raw 10% probability becomes approximately **36%**, and a raw 90% becomes approximately **72%**. Thus the large raw-to-calibrated improvement principally indicates **raw probability overconfidence/miscalibration**; it does not by itself show the raw model distinguishes outcomes well. Test calibrated predictions against a constant base-rate model, the market, and a clustered per-player-game calibration analysis before promoting them.

### Quote provenance: timestamp audit and population-matched comparison

The [executed quote provenance audit](prop-quote-provenance-audit.json)
checks both selected sportsbook sides against the stored kickoff for each
graded line. **54,907/65,448 lines (83.9%)** have both stored side
timestamps strictly before `prop_games.start_time`; **10,541 (16.1%)**
have at least one selected side captured at or after kickoff. This is
a significant **selection/provenance defect** in the original market
benchmark, not evidence that 16% of bets were actually placed live.
The source may overwrite odds in place, so an older valid quote
cannot necessarily be recovered from the latest database row.

The [timestamp-filtered Brier artifact](impact-prekickoff-only-subset.json)
was originally summarized by comparing a **Platt denominator that
excludes Week 2** against a **market denominator that includes Week 2**.
Those are not the same observations. The corrected,
[population-matched comparison](impact-prekickoff-matched-population.json)
uses **Weeks 3–9 on both sides**:

| Matched Weeks 3–9 population | Graded lines | Forward Platt Brier | De-vigged market Brier | Advantage (market minus Platt) |
|---|---:|---:|---:|---:|
| All selected quotes | 57,248 | 0.243917 | 0.245807 | +0.001890 |
| Both quote sides timestamped before stored kickoff | 47,830 | 0.245320 | 0.246375 | +0.001055 |

The positive advantage therefore **shrinks by 44.2%**, rather than
42% from the earlier mixed-denominator presentation. The
timestamp-eligible subset favors Platt in **Weeks 6, 7, and 9**;
Week 8 becomes a very small market win. The raw Spec B v2 model
still trails the market. None of these differences establishes
profitability or statistical significance given correlated alternate
lines, repeated books, and the selective sample.

**Important limits:** This filters the *existing* reconstructed
predictions and their existing forward Platt maps; it does **not**
refit each historical map using only the timestamp-eligible training
population. Neither the sportsbook kickoff timestamps nor the
underlying append-only pre-kickoff quote histories have been fully
verified independently. The uncorrected source-stat settlement issue
is still in the original line-level benchmark; a separate
corrected-history what-if is documented below. These two studies
must not be silently mixed into a new `valid_pregame` score.

### Corrected-history counterfactual (not the frozen baseline)

The [settlement root-cause audit](SETTLEMENT-DISAGREEMENT-AUDIT-2026-WEEKS2-9.md)
proves that the 38 mismatched quote lines cover only **two** player-games:
Deebo Samuel Sr. in Week 3 (80 receiving yards and a receiving touchdown
credited after a lateral, with zero targets) and David Montgomery in Week 4
(19 receiving yards after a lateral, also with zero targets). The weekly
ingester gated every receiving key on a nonzero target count and stored
both players as having zero receiving yards. The sportsbook's recorded
results were correct; our imported stat line was not. A similar **2025
Week 16 Isaiah Bond** observation was found in the prior-season history.

An independent, read-only **full in-memory corrected-history what-if**
was committed under [impact-corrected-history](impact-corrected-history/).
It updates only those two 2026 history rows and re-fits the forward
Platt calibration from prior weeks. It is **not** a permanent DB
repair, grader change, or original-baseline overwrite.

| Comparison | Original committed | Two-row corrected-history what-if |
|---|---:|---:|
| Graded lines, Weeks 2–9 | 65,448 | **65,448** |
| Recorded book/stat disagreements | 38 | **0** |
| Raw Spec B v2 pooled Brier, Weeks 2–9 | 0.265222 | **0.265350** |
| De-vigged market pooled Brier, Weeks 2–9 | 0.245754 | **0.245759** |
| Forward Platt Brier, matched Weeks 3–9 | 0.243917 | **0.243935** |
| De-vigged market Brier, matched Weeks 3–9 | 0.245807 | **0.245813** |
| Platt advantage, market minus Platt | 0.001890 | **0.001878** |

The raw model still trails the market in **every** week, while forward
Platt still wins on this selected set in Weeks **6–9**. Correcting the
ingested stats makes the raw score slightly **worse**, because the
incorrect zero-yard result had given its low-probability overs free
correct unders. The calibrated market comparison also weakens
slightly, **not** strengthens.

The corrected-history file is an evaluated counterfactual, not yet
a versioned clean production source. The 2025 case also needs the same
ingest repair. Preserve original and corrected runs side by side until
the reproducible ingester repair, source-row audit and 2025/2026
re-ingestion are reviewed.

The [point-calibration follow-up](POINT-CALIBRATION-2026-WEEKS2-9.md)
now also includes corrected-history coefficients and forward errors:
the candidate reception adjustment remains **+0.6249**; a uniform
receiving-yard increase remains worse on MAE. Do **not** treat the
zero-disagreement counterfactual as proof of valid pre-kickoff
market prices. That is a distinct unresolved provenance gate.

### Point projections, distribution coverage and Marcel-lite

I separately inspected the **3,805-row** player-game-market CSV, rather
than multiplying the same outcome by every alternate line/book. Marcel-lite
has an estimate on **2,549** of these rows (Weeks 4–9); all 2,549 also have
Spec B v2 estimates. The following MAE figures compare **identical paired
rows within each market**, so the units remain meaningful:

| Market | All point rows | Paired rows | Spec B v2 MAE on paired rows | Marcel-lite MAE on paired rows | Spec B mean bias (projection minus actual, all rows) | Observed coverage of Spec B 10th–90th percentile band |
|---|---:|---:|---:|---:|---:|---:|
| Passing yards | 203 | 142 | **59.78 yards** | 62.83 yards | -6.68 yards | 89.7% |
| Pass attempts | 203 | 142 | **6.31 attempts** | 7.23 attempts | -0.98 attempts | 89.2% |
| Pass completions | 203 | 142 | **4.61 completions** | 5.01 completions | -0.35 completions | 89.2% |
| Passing TDs | 203 | 142 | **0.873 TD** | 0.942 TD | -0.034 TD | 97.0% |
| Receiving yards | 1,517 | 1,003 | **20.41 yards** | 21.85 yards | -7.53 yards | 82.5% |
| Receptions | 1,476 | 978 | **1.547 receptions** | 1.575 receptions | -0.667 receptions | 87.8% |

**Interpretation:**

- **Point-estimate direction is promising, but not settled:** Spec B v2 has
  lower MAE than Marcel-lite in **all six observed markets** on the paired
  population. Some advantages, particularly receptions and TDs, are small.
  These results do **not** imply calibrated prop probabilities or profitable
  bets; the raw probability Brier remains worse than the market every week.
- **Systematic negative bias:** the model's mean projections are below
  realized outcomes on average in **all six markets**, notably **7.53
  receiving yards** and **0.667 receptions** per eligible observation.
  Because the sample includes only graded player-game participants and
  is selected by available props, do not generalize the bias to all
  NFL roster players.
- **Intervals tend to over-cover:** observed inclusion in the nominal 80%
  central bands is **86.4% overall**, with especially high **97.0%**
  for discrete passing-touchdown outcomes. Discrete/inclusive quantile
  endpoints can naturally over-cover, so this is a coverage diagnostic,
  not proof that every distribution is too wide. Together with the raw
  Brier result, it argues for inspecting distribution shape and
  market-relative calibration rather than only moving projected means.

There is no meaningful single yard-like unit for the pooled MAE because
yards, attempts, catches and TDs are mixed. The market-level paired
values above supersede any unstratified comparison. Only six market
families had point rows in the committed CSV; the engine's supported
targets market has no observations here.

### Settlement and data-provenance audit

The independent grader.collect() eligibility re-derivation matched grader.grade()'s **65,448** selected rows exactly, and the subsequent rerun reproduced the Brier and MAE metrics. **This verifies population consistency and deterministic scoring; it does not verify every underlying sportsbook settlement or quote's timestamp.**

The recorded book result differs from the stat-log actual > line result for **38 of 65,448** lines (**0.058%**): **23/7,862** in Week 3 (**0.293%** of that week's lines) and **15/8,995** in Week 4 (**0.167%**), with **zero** in Weeks 2 and 5–9. The clustering is a reason to investigate common sources, games, markets, and stat revisions, and that investigation is now done: see **`SETTLEMENT-DISAGREEMENT-AUDIT-2026-WEEKS2-9.md`**, with the 38-row evidence export in `settlement-disagreements-2026-weeks2-9.csv`. All 38 lines are two player-games (Deebo Samuel Sr., Week 3; David Montgomery, Week 4), and both are the same defect: a post-catch lateral that the NFL credits as receiving yards with zero targets and zero receptions, which the weekly ingest drops because its receiving key group is gated on `targets`. The sportsbook settlements are correct and the stat-log value is wrong; a what-if with only those two in-memory rows corrected takes the disagreement count from 38 to 0 and leaves the graded population unchanged. The grader continues to use the player-game stat line as truth; it does not silently rewrite outcomes from recorded book settlements.

Two additional reproducibility limitations are visible in the current runner and must be resolved before interpreting this as a clean pregame market benchmark:

1. **grader.collect()** chooses the latest observed quote separately for each over and under side, **without checking captured_at against scheduled kickoff**. The summary describes the quotes as pregame, but that cutoff is not established by the source selection code or the committed line-level CSV. That audit has now been run (`prop-quote-provenance-audit.json`, `prop-quote-timestamp-exceptions.csv`): **10,541 of 65,448 lines (16.11%) have at least one selected side captured at or after the stored kickoff**, leaving 54,907 lines with both sides recorded pre-kickoff. **The Brier comparisons above describe the selected historical quotes, not independently verified pre-kickoff prices.** Re-scoring on the pre-kickoff subset only (`impact-prekickoff-only-subset.json`) moves forward Platt from 0.24392 to **0.24532** against a market of **0.24639**, so the apparent edge shrinks from 0.00184 to **0.00107** — it survives directionally but loses about 42% of its size.
2. When building the line-level CSV, the runner wrote **gamebook_url** from a **roster** local variable left over from an earlier loop, rather than the matching graded player's roster. **Fixed in the runner (9c0c9e7f) for future regeneration; the committed CSV still carries the old URLs.** Thus the URL field in the current line-level output is **not reliable for row-level gamebook attribution**. The roster membership check itself uses the correct lookup in the earlier loop, and this URL issue does **not** enter the stored Brier or MAE calculations. Do not use the exported per-line URLs as documentary evidence without fixing the runner and regenerating the artifact.

### Decision

**Keep the frozen raw model and the forward Platt layer separately versioned.** The current evidence supports further research into calibration, not a claim that the raw model beats sportsbooks or that these retrospective reconstructions were available before kickoff. The next evidence gates are (a) the permanent, narrowly verified weekly-ingest repair with both 2025 and 2026 affected rows restored, rather than only the in-memory what-if, (b) confirmed pre-kickoff time alignment for both sides of every quoted price, (c) regenerated row-level gamebook URLs, and (d) per-market calibration with clustered uncertainty and an untouched future holdout. The 38-row root cause is **closed analytically**, but the underlying historical database and frozen artifact have deliberately not been rewritten. Do not overwrite this run's scores to force the settlement check to zero.


## Follow-up: forward point calibration

[Research-only Weeks 2–9 point calibration](POINT-CALIBRATION-2026-WEEKS2-9.md) tested additive-mean, additive-median and multiplicative corrections market by market. A forward-shrunk receptions correction of **+0.625 receptions** through Week 9 improves subsequent-week MAE in the historical walk-forward comparison, while adding **+7.064 receiving yards** worsens MAE. The frozen model and prop-probability Platt calibration are unchanged; the candidate requires a fresh holdout before deployment.

## Scope

This replays the frozen Spec B v2 player projection engine in a walk-forward
evaluation over completed 2026 regular-season games in Weeks 2–9. Marcel-lite is
reported as the point-estimate benchmark. The forward Platt map is fit separately
for each target week, using only eligible sportsbook prop outcomes from earlier
weeks in 2026; a week without at least 200 earlier items stays uncalibrated.

The replay uses player-game logs only through the target game's week boundary.
Target-game injury and availability status is left empty, because there is no
verified pregame archive for each historical week. Model projections are
conditional on the target player having a recorded game log. Official GSIS
gamebooks are joined after the projection by game, team, and GSIS ID to verify
that graded players were listed active. Final roster status is not a feature or
input to the projections.

## Outputs

- `walk-forward-prop-projections.csv`: one row per eligible prop line and book,
  including the raw Spec B probability, forward-calibrated probability where a
  prior-week map exists, market probability, point projections, distribution
  quantiles, actual, and gamebook reference.
- `player-game-market-projections.csv`: deduplicated player-game-market point
  projections and errors, so alternate lines and books do not multiply MAE.
- `weekly-prop-projection-metrics.csv`: per-week sample counts, Brier scores,
  and point MAE.
- `prop-projection-backtest-summary.json`: run inputs, hashes, calibration maps,
  coverage, and limitations.
- `run_prop_projection_backtest.py`: reproducible read-only runner.

The forecast probabilities cover the model's existing receiving markets and
pregame-lead quarterback passing markets only. Rushing and joint-stat markets
do not receive probabilities unless the frozen model has a supported
distribution. The outcome set excludes inactive and did-not-play players, plus
players without a target-week game-log row; their props are not assumed to have
settled at zero. The roster CSV and this backtest therefore answer different
questions: the gamebooks establish final eligibility, while this score is
conditional on a stat-log participant. No claim of pregame forecast capture or
betting profitability follows from a retrospective reconstruction.

## Rebuild

An independent settlement audit recomputes eligibility straight from
`grader.collect()` for Weeks 2–9 only and re-checks every graded prop against
the recorded sportsbook settlement without rerunning simulation draws. The
runner aborts if the audit's eligible count differs from the grader population;
for this run the population matched and the audit found 38 rows where the
book's recorded settlement disagrees with the graded stat line, all in Week 3
(23) and Week 4 (15).

Run from the repository root. The database is opened with SQLite `mode=ro`; the
script does not write projection, calibration, or grading rows to it.

```sh
python docs/research/nfl-injury-history-2026-weeks2-9/run_prop_projection_backtest.py \
  --db backend/data/picks.dev.db \
  --out-dir docs/research/nfl-injury-history-2026-weeks2-9
```
