# NFL model inputs: what to research next

**Authoritative current entry point:** [NFL prediction model brief](BRIEF-nfl-prediction-model.md). This file preserves the 2026-10-11 hypotheses and methods.

**Status update, 2026-10-18:** the opening statement that nothing had been run describes the document's creation date, not current status. Preseason-prior and feature results are recorded in the index; the later EPA-plus-success-rate experiment found no established gain, and current team score-distribution results do not support spread or total forecasts. Spec B and prop-calibration measurements now exist on separate branches. Use the brief to distinguish completed, failed and still-unverified work.

Recorded 2026-10-11 from Micah's discussion after the
[north star rewrite](STRATEGY-forecasting-north-star-2026-10-10.md). At the time it was recorded, the
agenda below had not been run; it is preserved as the original research agenda and rules for judging it.

## Decision

- The goal is a better independent model, measured by Brier on identical games against the benchmark
  ladder in the north star. The closing market (0.2105 pooled 2010 to 2025) is the ceiling, not the
  floor.
- Two scoreboards, kept separate:
  - **Independent model**: no market inputs. This is the number on the ladder and the basis of any
    "our model says" claim.
  - **Best forecast**: may blend market information (preseason win totals, even game lines) to show users
    the most accurate probability. Never claimed as beating the market.
- Scale: in the NFL, 0.005 of Brier is a large gain. The pooled 2010 to 2025 interval on the v1 vs market
  gap is about +/-0.003 ([market baseline](RESULTS-market-baseline-2010-2025-2026-10-11.md)), so a change
  that size is detectable over many seasons and not within one.

Where we stood on 2026-10-11: the QB, availability and EPA-by-unit stack improved v1 by 0.0021 Brier pooled
2011 to 2023, about what EPA alone gave (0.0019)
([backfill and features](RESULTS-nfl-backfill-features-2026-10-11.md)). Weeks 1 to 4 carry about twice
the gap of later weeks ([features plan](PLAN-nfl-features-2026-10-11.md)). A later v1+Elo report found a
0.0032 Brier improvement over recalibrated v1 on the same 2011-2023, 3,158-game population and baseline.
That later result supersedes the phrase “best own-data stack”; the 0.0021 remains the measured result
for the specifically named QB/availability/EPA stack.

## Levers not yet pulled properly

1. **Offseason carryover.** v1 starts each season from the previous season's final fit. The amount of
   regression toward average between seasons had not been tuned as of 2026-10-11. A later test of 21
   settings found none met the keep rule on 2024 and 2025; see [carryover results](RESULTS-nfl-ladder-carryover-2026-10-12.md).
2. **Preseason market priors.** 538 blended preseason win totals into starting ratings. This uses the
   market's season view, not the line for the game being forecast, but it is still market input: best
   forecast scoreboard only. A market-derived prior was later tested and kept only for that scoreboard;
   it is not an independent forecast. See the [feature index](INDEX-nfl-model-research-2026-10-12.md).
3. **EPA per play, by unit, with shrinkage.** Today's "EPA by unit" is v2 (`nfl_epa_model`: pass and rush,
   offense and defense, previous-season prior) entered as a stack column of its EPA-points margin. Still
   open: per-play rates with explicit volume (pace) kept separate and shrinkage by sample size. Success
   rate was tested on 2026-10-18 as an EPA addition and did not establish a gain; see the current brief.
   Check v2's construction before treating any other item here as tested.
4. **Margin spread by game.** v1 uses one margin standard deviation (13.295) for every game. A week-bucket
   rating-uncertainty test was later run and not kept; matchup-dependent spread remains untested. See the
   [feature results](RESULTS-nfl-features-vs-market-2026-10-11.md).
5. **QB relative to the team baseline.** The expected starter's effect against the QB production already
   in the team rating, not a standalone QB value. A retrospective QBI expected-starter feature test was
   later run and not kept; it does not establish that the operational, pregame starter pipeline is complete.
   See the [backfill and feature results](RESULTS-nfl-backfill-features-2026-10-11.md).

## Matchup inputs (Micah's hypothesis)

The idea: how a team plays every snap carries information beyond EPA. The Vikings pressure the QB a lot
and blitz a lot; put that against a Raiders QB who cannot move around and does poorly under pressure,
perhaps visible as a high sack rate, and the matchup should say more than either team's average.

What we have (dev DB, measured 2026-10-11):

| Source | Table | Seasons | Relevant fields |
|---|---|---|---|
| FTN charting (CC BY-SA) | `nfl_hist_ftn_charting` | 2022 to 2025, 185,215 plays | `n_blitzers`, `n_pass_rushers`, `is_qb_out_of_pocket`, `is_qb_fault_sack`, `is_play_action`, `is_rpo`, `is_screen_pass`, `is_motion`, `n_defense_box`, `is_drop`, `is_throw_away` |
| nflverse play-by-play | `nfl_pbp` | 2010 to 2026 | `sack`, `shotgun`, `air_yards`, `pass_location`, `run_gap`, `epa`, `success`, `cpoe`, `qb_hit`, `qb_scramble`, `qb_dropback`, `no_huddle` (added 2026-10-11) |

FTN is loaded but untested. Not in the DB: the nflverse participation data (formation, personnel, defenders in the
box, and for some seasons coverage type and pressure) and Next Gen Stats (time to throw). Which seasons
those publishers cover is unverified.

Position-vs-defense pages (for example CBS fantasy points allowed by position) can be computed from our
play-by-play. They mostly serve player props (Spec B). For game outcomes, touchdowns allowed are noisy;
yards and success allowed per play carry steadier signal.

## Method: each step is a filter

1. **Inventory.** What we have, which seasons, row counts reconciled to the publisher's counts.
2. **Stability.** For each stat (blitz rate, pass rushers, pressure, QB-fault sack rate, out-of-pocket
   rate, play action rate), does the first half of a season predict the second half? A stat that does not
   carry over cannot predict next week; drop it.
3. **Predictive over EPA.** Does a stable stat predict next-game points or margin once EPA per play is
   already in the model?
4. **Interactions.** Only then test matchups (blitz-heavy defense against a QB who struggles under
   pressure), walk-forward, on identical games, scored on the ladder.

Risks: stats that are descriptive but not stable; too many features for about 272 games a season, with
only four FTN seasons (roughly 1,100 games), which invites finding matchups in noise. Two beliefs from
memory, to verify on our data rather than cite: defensive pressure rate is fairly stable season to season;
QB performance under pressure is less stable than clean-pocket performance.

## Next: stats research plan

Why the four columns were added to `nfl_pbp` ([results](RESULTS-nfl-pbp-qb-columns-2026-10-11.md)), for the
matchup hypothesis above:

| Column | Role |
|---|---|
| `qb_hit` | Pressure: how often a defense hits the QB, and how often an offense's QB gets hit. |
| `qb_scramble` | Mobility: whether a QB escapes pressure (the Raiders QB who cannot move around). |
| `qb_dropback` | Denominator for per-dropback rates (hit rate, sack rate, scramble rate). |
| `no_huddle` | Pace and tempo. |

Steps, all read-only on the dev DB, each a filter on the next:

1. **Build rates** per team and season, offense and defense: `qb_hit` per dropback, sack rate, scramble
   rate, no-huddle rate (nflverse, 2010 to 2026); blitz rate, pass rushers, QB out of pocket and QB-fault
   sack rate (FTN, 2022 to 2025 only).
2. **Stability.** Does the first half of a season predict the second half? Drop every rate that does not.
3. **Predictive value.** For the survivors, does the rate predict next-game margin or points once EPA per
   play is in the model? FTN covers about 1,100 games, so keep the feature count small; many features on
   few games find matchups in noise.
4. **Interactions.** Only on stats that clear step 3 (for example, a pressure-generating defense against a
   QB who is hit often), walk-forward, on identical games, scored on the benchmark ladder.

Write results to a new `docs/RESULTS-` file. Offseason carryover (lever 1) runs first, alongside steps 1
and 2. Position-vs-defense stats (the CBS idea) are computed from our play-by-play and belong to player
props in [Spec B](SPEC-player-projections-availability-2026-10-09.md), not the game model.

## Open items

- Done 2026-10-11: `qb_hit`, `qb_scramble`, `qb_dropback` and `no_huddle` in `nfl_pbp` for 2010 to 2026 ([results](RESULTS-nfl-pbp-qb-columns-2026-10-11.md)).
- Check participation and Next Gen Stats season coverage at the publisher before deciding to ingest.
- Run lever 1 (offseason carryover) first; run inventory and stability (steps 1 and 2) for matchup stats
  alongside it. Both read-only on the dev DB.
