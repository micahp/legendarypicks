# NFL Spec B v2 point calibration, 2026 Weeks 2–9 (research candidate)

## Decision and exact next-period values

**Advance only the additive mean correction for receptions as a research
candidate**, not as a silent replacement of the frozen Spec B v2 engine.
The fit through Week 9 gives **+0.624895 receptions** to an eligible
receptions point estimate, with a floor at zero. Refit the offset before
each later target week using **only earlier graded weeks** and report the
number of independent player-game-market training rows. This candidate
has not been validated on an untouched later week, nor on every roster
player or a verified pregame population.

**Do not add +7.53 receiving yards.** That number was the raw bias
across selected outcomes, not an error-minimizing adjustment. On
forward-held weeks, a positive mean-offset correction for receiving
yards **increased** MAE. The receiving-yards residual distribution is
right-skewed: its through-Week-9 mean residual was +7.53 yards, but its
median was only about +0.78 yards. A few large receiving games can
create a positive mean bias without a universal upward adjustment being
helpful for absolute error.

These are the frozen through-Week-9 *candidate* adjustments using 100
pseudo-observations shrinking to the identity map. The historical
forward-week evidence determined the current proposed policy; that
selection means a separate future holdout is still required.

| Market | Through-W9 candidate add-mean offset | Forward W3–W9 raw MAE | Forward add-mean MAE | MAE gain (raw minus candidate) | Game-clustered approximate 95% interval for gain | Proposed action |
|---|---:|---:|---:|---:|---:|---|
| Receptions | **+0.625 receptions** | 1.561 | **1.518** | **+0.0429** | **+0.0154 to +0.0705** | **Research candidate** |
| Passing yards | +4.475 yards | 57.857 | 57.449 | +0.4077 | -0.3260 to +1.1414 | Keep raw pending new holdout |
| Receiving yards | +7.064 yards | **20.124** | 20.563 | **-0.4391** | -0.7518 to -0.1263 | **Keep raw** |
| Pass attempts | +0.654 attempts | **6.393** | 6.426 | -0.0330 | -0.1624 to +0.0963 | Keep raw |
| Pass completions | +0.232 completions | 4.625 | 4.623 | +0.0019 | -0.0614 to +0.0653 | Keep raw |
| Passing TDs | +0.0226 touchdowns | **0.8920** | 0.8946 | -0.0026 | -0.0069 to +0.0018 | Keep raw |

The approximate uncertainty intervals cluster by **game**, not by
alternate line. They are descriptive normal approximations; they do
not correct for trying three candidate adjustment methods and then
choosing one based on the same evaluation weeks.

## Retest after restoring lateral receiving history (2026 Week 3–4)

The settlement root-cause audit found that the weekly ingest dropped **80
receiving yards and one receiving TD** for Deebo Samuel Sr. in Week 3 and
**19 receiving yards** for David Montgomery in Week 4, because their
post-catch laterals produced nonzero receiving yards with zero targets.
The counterfactual [corrected-history](impact-corrected-history/) replay
changes two in-memory player-history rows, **not** the underlying database.
The additional [corrected point-calibration study](point-projection-calibration-corrected-history.json)
refits using that counterfactual's 3,805 player-game-market source rows.

| Market | Original W3–W9 raw MAE | Corrected-history raw MAE | Corrected-history add-mean MAE | Corrected through-W9 add-mean offset | Decision |
|---|---:|---:|---:|---:|---|
| Receptions | 1.56073 | 1.56073 | **1.51778** | **+0.624895 receptions** | Research candidate unchanged |
| Receiving yards | 20.12425 | 20.12718 | **20.57039** | +7.11712 yards | **Reject blanket offset** |
| Passing yards | 57.85656 | 57.85656 | 57.44888 | +4.47499 yards | Still inconclusive |
| Pass attempts | 6.39306 | 6.39306 | 6.42609 | +0.65373 attempts | Raw remains better |
| Pass completions | 4.62494 | 4.62494 | 4.62301 | +0.23250 completions | Negligible improvement |
| Passing TDs | 0.89200 | 0.89200 | 0.89458 | +0.02259 TDs | Raw remains better |

The corrected-history receiving-yard mean-offset MAE gain is **−0.4432
yards**, with an approximate game-clustered 95% interval of **−0.7626
to −0.1239**. Receptions retain a gain of **+0.04294 catches** with
an interval of **+0.01537 to +0.07052**. These are retrospective
research diagnostics, not a future independent holdout.

**Interpretation:** the receiving-yards problem was not a general
missing +7.53 yards of offense. Two specific stat lines were wrong;
fixing their history barely changes the global calibration result.
The **2025 Week 16 Isaiah Bond** zero-target lateral is also missing
receiving yards in the *previous-season* history, and the current 2026
corrected-history counterfactual did **not** patch that season.
Therefore this is not yet the final calibration basis. The priority
remains the verified ingester repair and 2025/2026 source backfill,
then a genuinely untouched forward-week assessment.

## Conservation and serving constraints

**Do not literally add 0.625 receptions to every player on a roster.**
The fitted outcome population is a selected, conditional-on-participating
prop subset, and blindly giving every candidate receiver an extra
0.625 catches can exceed the team's projected pass completions and
break the sum of player target shares. This is a **point-level audit
transform**, not an instruction to alter the simulator's team volume
or 4,000 correlated player draws. A deployable candidate must preserve
team totals and pass attempts, including QB attempts, completions,
receiver targets and catches. It also needs to work for players with
no previously available graded sportsbook prop. Retain separate
raw-v2 and candidate labels; never mix corrected means with uncorrected
probability distributions.

## Why a constant bias fix is insufficient

A player projected for 8 receiving yards and a player projected for
80 yards should not automatically receive the same +7.53-yard bump.
The receiving-yards sample overrepresents realized game-log participants
with available props, and the distribution is highly skewed. A mean
error correction can improve **RMSE** while hurting **MAE**. On the
W3–W9 receiving-yards rows, add-mean changed RMSE from **29.03** to
**28.05** yards, but changed MAE from **20.12** to **20.56** yards.
These are different forecast objectives; we cannot pick the one that
looks better after seeing the held-out outcomes and call the model
validated.

Similarly, the fact that nominal 80% projection bands contained 86.4%
of actuals does not justify scaling *every* interval down to exactly
80%. Inclusive bands for counts and zero-inflated/skewed markets
naturally over-cover. Point-estimate adjustments must not be quietly
applied to the underlying 4,000 draws or to the **separately versioned**
forward Platt prop-probability model without re-scoring Brier,
calibration and paired market comparisons on a new holdout.

## Reproduction and boundaries

- Source: `player-game-market-projections.csv`, **3,805 distinct
  player-game-market rows** across 2026 Weeks 2–9.
- Code: `calibrate_player_projection_points.py`.
- Computed comparison: `point-projection-calibration-study.json`.
- Methods tried: untouched raw; forward shrinkage of mean residual;
  forward shrinkage of median residual; forward multiplicative
  total-mean correction capped to factors 0.75–1.40. Shrinkage is
  `n/(n+100)` on independent training rows within the same market.
- Each Week 3–9 forecast is made from that market's **prior weeks
  only**. Week 2 has zero available preceding 2026 rows and is
  reported as a raw/no-map baseline.
- Outcomes still condition on the player having a recorded game log,
  and final roster labels were applied *after* forecasting.
- The quoted sportsbook benchmark in the main backtest remains
  **provisional** until two-sided quote timestamps are checked against
  kickoff. The 38 recorded-settlement discrepancies have now been
  reconciled to two zero-target lateral plays and one weekly-ingest bug;
  a corrected-history replay closes them, but the underlying database
  remains unmodified.
  In-place sportsbook quote updates can make historical pre-kickoff
  reconstruction impossible without archived observations.
- The existing bad per-row `gamebook_url` export was fixed in
  `run_prop_projection_backtest.py` for **future regeneration**; the
  already-committed 65,448-line CSV has **not** been silently rewritten.

Run without a database:

```sh
python docs/research/nfl-injury-history-2026-weeks2-9/calibrate_player_projection_points.py
python -m unittest discover -s docs/research/nfl-injury-history-2026-weeks2-9 \
  -p test_calibrate_player_projection_points.py
```

## Quote and settlement provenance

The correct price baseline is the **latest observed paired over/under
quote from append-only evidence where both prices were captured before
the scheduled kickoff instant**. The source's current latest row alone
is insufficient when the ingest updates stored odds in place.
Use the matching gamebook for each game from
`official-gamebooks-source-manifest.csv`. Do not backdate current
rows, manufacture a missing archived quote, or silently recompute the
existing Brier scores.

The read-only `audit_prop_quote_provenance.py` now crosswalks the
existing 65,448 graded rows back to stored quote sides and their
`odds_captured_at` values, flags either side captured at/after
`prop_games.start_time`, and emits a row-level settlement mismatch
file. It is **an executable audit, not yet an executed result**:
the underlying 4 GB API SQLite database is not available in the
GitHub file connector. Timestamp classifications from the currently
stored rows are not proof that the historical price was captured before
kickoff when the source overwrote old prices.

```sh
python docs/research/nfl-injury-history-2026-weeks2-9/audit_prop_quote_provenance.py \
  --db backend/data/picks.dev.db
```

This creates `prop-quote-provenance-audit.json`,
`recorded-settlement-disagreements.csv`, and
`prop-quote-timestamp-exceptions.csv` on the executing host.
The 38 disagreements have been independently reconciled in
`SETTLEMENT-DISAGREEMENT-AUDIT-2026-WEEKS2-9.md`; this quote audit
remains useful for **timestamp provenance**, not as a replacement
for that completed root-cause analysis.

**Promotion gates:** evaluate the receptions candidate on a later
untouched period, compare with raw on the same independent
player-game-market outcomes, inspect bias/MAE by high- and low-usage
players and coverage by market, then re-grade probabilities from
fully recomputed distributions before changing any serving model.
