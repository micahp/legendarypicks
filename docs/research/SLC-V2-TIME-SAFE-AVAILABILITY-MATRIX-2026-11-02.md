# Time-safe feature availability matrix (SLC v2, Milestone 2 and 3), 2026-11-02

Status: classification of every candidate source before weekly features are built. Research only. Owner rulings C and D apply. Four classes, per the owner's ruling D:

- **A. Available before cutoff, verified**: publication or capture evidence in hand.
- **H. Historical label only**: may train or score, never supply a pregame input.
- **U. Unknown historical availability**: not used for pregame inputs unless an explicit, stated lag is applied and reported as an assumption.
- **N. Unavailable**: no historical source on this box.

Conditional rows state the condition in the availability column.

## Publisher evidence used

| Source | Publisher text (nflreadr reference page) | Result |
|---|---|---|
| Play-by-play (`load_pbp`) | No publication or update timing stated. The only timing text is a sample console line. | Timing unverified. Class U. |
| Participation (`load_participation`) | "2023 onward (FTN data): The data is provided after all post-season games are completed." The timing sentence is written under the FTN heading on that page. | Participation for 2023 and later is published after the postseason. Class H within season; prior-season use after that postseason. |
| Snap counts (`load_snap_counts`) | No update timing stated. Source is Pro Football Reference. | Timing unverified. Class U. |

Caveat on the participation row: the publisher places the timing sentence under the FTN heading. The owner's ruling says participation for 2023 onward is published after the postseason. Both readings are treated the same way here, and the mismatch is recorded as an open item.

## Matrix

| Field or source | Years in box | Class | Availability rule | Lag or fallback |
|---|---|---|---|---|
| Schedule structure (teams, week, kickoff) | 2010 to 2026 | A (conditional) | Schedule rows exist for unplayed games (2026 has the full REG count, 272). Kickoff may move. | Use the scheduled kickoff; record the kickoff used. |
| Head coach on the target game's schedule row | 2010 to 2026 | H | Not used as a pregame input (owner ruling P1). | Use the carried identity below. |
| Head coach carried from earlier games | 2010 to 2026 | A | The coach names on earlier, completed games were known before the cutoff. | Season opener: last coach of the prior season. Mid-offseason changes not handled. |
| Coordinators and play caller | none | N | No source on this box. | Team tendencies only. |
| Play-by-play results (2022 to 2025) | 2022 to 2025 | U | Timing unverified (publisher silent). | Assumed usable 10 hours after scheduled kickoff. Sensitivity with a longer lag reported. |
| Player game logs, weekly stats including snaps, carries, targets (`nflverse_weekly`) | 2019 to 2025 | U | Same class as play-by-play. Published weekly stats copied, not recomputed. | Same lag as play-by-play. |
| Participation: personnel, formation, route, coverage, pressure, time to throw | 2016 to 2025 | H within season; prior-season conditional | 2023 onward after the postseason (publisher text). 2016 to 2022 timing not stated. | Prior season only, from the postseason end. 2022 participation is class U. |
| FTN charting (box score tendencies, box counts) | 2022 to 2025 | H within season; prior-season conditional | Same publisher text as participation for 2023 onward. | Prior season only. 2022 is class U. |
| Snap counts, PFR (`nfl_hist_snap_counts`) | 2013 to 2025 | U | Timing unverified (publisher silent). | Training label only until verified. |
| Injury reports, historical (`nfl_hist_injuries`) | 2009 to 2025 | Conditional A | `date_modified` is the last modification. The state at a cutoff is recoverable only when `date_modified` is at or before the cutoff. | Otherwise excluded and counted (owner ruling C). |
| Depth charts 2025 (dated snapshots) | 2025 to 2026 | A (conditional) | Latest snapshot `dt` at or before the cutoff, per team. `dt` semantics unverified. | Staleness recorded (owner ruling B). |
| Depth charts 2010 to 2024 (season and week) | 2010 to 2024 | U | No publication time stored. | Not used for pregame inputs. |
| Coach tendencies (SportsDataverse season aggregates) | 2002 to 2026 | H | Aggregates include the whole season. | Training label only. |
| Coach careers (SportsDataverse) | 2002 to 2026 | H | Totals over all published seasons. | Not a pregame input. |
| Team defense allowed, per target (derived from play-by-play) | 2022 to 2025 | U (inherits play-by-play) | Derived from play-by-play. | Same lag as play-by-play. |
| Player identity crosswalk (`players.csv`) | all | A (identity reference) | Static crosswalk. | Not a feature. |
| Market lines (pregame) | 2026 only in this table | N for history | Captured after kickoff for most rows. | Not used. |
| Roster snapshots | NFL 2026 only | N for history | No NFL history in the table. | Not used. |
| Separation (NGS) | none | N | No source on this box. | Deferred (owner ruling). |

## Forecast horizons

- Early horizon: Tuesday 12:00 Eastern before the game day.
- Final horizon: kickoff minus one hour.

Both horizons use the same rules above. Lags are applied against each horizon's cutoff.

## Provenance rule for every forecast

A forecast carries a manifest. The manifest lists each source used, its class, the availability time it was assumed under, and the check that the availability time is at or before the cutoff. A source that fails the check is excluded and counted.

## Open items

1. Verify the play-by-play publication timing, or keep the 10-hour lag as a stated assumption and report the sensitivity.
2. Confirm the participation and FTN timing text, since the publisher places it under the FTN heading.
3. Verify the depth-chart `dt` semantics (carried over from the adapter report).
4. Snap-count publication timing is unverified.
