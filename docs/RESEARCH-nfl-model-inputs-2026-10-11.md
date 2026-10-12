# NFL model inputs: what to research next

Recorded 2026-10-11 from Micah's discussion after the
[north star rewrite](STRATEGY-forecasting-north-star-2026-10-10.md). Nothing here has been run yet; it
is the research agenda and the rules for judging it.

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

Where we stand: our best own-data stack (QB, availability, EPA by unit) improves v1 by 0.0021 Brier pooled
2011 to 2023, about what EPA alone gave (0.0019)
([backfill and features](RESULTS-nfl-backfill-features-2026-10-11.md)). Weeks 1 to 4 carry about twice
the gap of later weeks ([features plan](PLAN-nfl-features-2026-10-11.md)).

## Levers not yet pulled properly

1. **Offseason carryover.** v1 starts each season from the previous season's final fit. The amount of
   regression toward average between seasons has not been tuned or compared with 538's one-third rule.
   Early weeks are where we lose most, so this is the cheapest likely gain and the first to test.
2. **Preseason market priors.** 538 blended preseason win totals into starting ratings. This uses the
   market's season view, not the line for the game being forecast, but it is still market input: best
   forecast scoreboard only.
3. **EPA per play, by unit, with shrinkage.** Today's "EPA by unit" is v2 (`nfl_epa_model`: pass and rush,
   offense and defense, previous-season prior) entered as a stack column of its EPA-points margin. Still
   open: per-play rates with explicit volume (pace) kept separate, success rate, and shrinkage by sample
   size. Check v2's construction before treating any of these as tested.
4. **Margin spread by game.** v1 uses one margin standard deviation (13.295) for every game. Letting it
   vary with matchup and week can improve Brier without changing ratings.
5. **QB relative to the team baseline.** The expected starter's effect against the QB production already
   in the team rating, not a standalone QB value.

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

## Open items

- Done 2026-10-11: `qb_hit`, `qb_scramble`, `qb_dropback` and `no_huddle` in `nfl_pbp` for 2010 to 2026 ([results](RESULTS-nfl-pbp-qb-columns-2026-10-11.md)).
- Check participation and Next Gen Stats season coverage at the publisher before deciding to ingest.
- Run lever 1 (offseason carryover) first; run inventory and stability (steps 1 and 2) for matchup stats
  alongside it. Both read-only on the dev DB.
