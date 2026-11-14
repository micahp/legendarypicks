# NFL prop projection backtest, 2026 Weeks 2–9

## Results and interpretation (audited November 13, 2026)

**Headline:** the **raw Spec B v2 probabilities do not beat the de-vigged sportsbook market** on this eight-week retrospective sample. Forward-only Platt recalibration materially reduces raw-model Brier error and beats the market on the *same graded lines* in each of Weeks 6–9. The calibrated edge is small in the pooled Weeks 3–9 comparison and is **not yet validated as a deployable betting edge**. Recorded book settlements disagree with the stat-log grader on 38 quoted lines; the individual causes have not been resolved.

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

### Point projections and Marcel-lite

On the **2,793** player-game-market observations in Weeks 4–9 where both methods have an estimate, raw Spec B v2's aggregated absolute error is **12.37** versus **13.47** for Marcel-lite, using player-game-market rather than alternate-line weighting. However, this aggregate pools **incompatible units** (e.g. passing yards, receiving yards, receptions, attempts, touchdowns), so it is only a bookkeeping summary, **not a meaningful single MAE unit**. Marcel-lite has no comparison value for Weeks 2–3. A credible point-forecast verdict needs per-market MAE, appropriate units, and paired comparisons on identical populations. The current output does not provide that stratified conclusion.

### Settlement and data-provenance audit

The independent grader.collect() eligibility re-derivation matched grader.grade()'s **65,448** selected rows exactly, and the subsequent rerun reproduced the Brier and MAE metrics. **This verifies population consistency and deterministic scoring; it does not verify every underlying sportsbook settlement or quote's timestamp.**

The recorded book result differs from the stat-log actual > line result for **38 of 65,448** lines (**0.058%**): **23/7,862** in Week 3 (**0.293%** of that week's lines) and **15/8,995** in Week 4 (**0.167%**), with **zero** in Weeks 2 and 5–9. The clustering is a reason to investigate common sources, games, markets, and stat revisions; it **does not establish** that stat corrections caused the differences. The committed summary and metrics currently contain counts only. They do **not** contain a 38-row evidence export or verified root-cause labels. The grader continues to use the player-game stat line as truth; it does not silently rewrite outcomes from recorded book settlements.

Two additional reproducibility limitations are visible in the current runner and must be resolved before interpreting this as a clean pregame market benchmark:

1. **grader.collect()** chooses the latest observed quote separately for each over and under side, **without checking captured_at against scheduled kickoff**. The summary describes the quotes as pregame, but that cutoff is not established by the source selection code or the committed line-level CSV. The cutoff and synchronization of two-sided quotes need an explicit audit. **The Brier comparisons above describe the selected historical quotes, not independently verified pre-kickoff prices.**
2. When building the line-level CSV, the runner writes **gamebook_url** from a **roster** local variable left over from an earlier loop, rather than the matching graded player's roster. Thus the URL field in the current line-level output is **not reliable for row-level gamebook attribution**. The roster membership check itself uses the correct lookup in the earlier loop, and this URL issue does **not** enter the stored Brier or MAE calculations. Do not use the exported per-line URLs as documentary evidence without fixing the runner and regenerating the artifact.

### Decision

**Keep the frozen raw model and the forward Platt layer separately versioned.** The current evidence supports further research into calibration, not a claim that the raw model beats sportsbooks or that these retrospective reconstructions were available before kickoff. The next evidence gates are (a) exact 38-row settlement reconciliation against actual stat definitions and the official gamebooks, (b) confirmed pre-kickoff time alignment for two-sided market prices, (c) refreshed row-level source URLs, and (d) per-market and clustered uncertainty analysis, including a clean future holdout. Do not overwrite this run's scores to force the settlement check to zero.

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
