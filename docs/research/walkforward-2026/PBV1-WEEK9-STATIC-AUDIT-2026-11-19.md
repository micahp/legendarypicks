# 2026 Week 9 PBV1 input/first-entry audit (no Monte Carlo)

**Date:** 2026-11-19. **Scope:** 15 Week 9 snapshots from commit `30f77e4a` (30 teams) plus the frozen `field_v4_2022_2025.json` at commit `f2f346b7`. No simulation seeds were run for this audit.

## What was calculated

For a team's *first* offensive snap, **conditional on personnel grouping `11`**, the participation field starts with an empty lineup and selects exactly one RB-class player. The actual `participation_field.Field.rate()` formula in `slc-v2` is:

`rate(player, team, 11) = (historical_team_group_appearances + 20 * position_prior(RB,11)) / (historical_team_group_plays + 20)`

Within the eligible RB-class roster, a player has exact conditional first-entry probability `max(rate, 1e-9) / sum(max(rate_j, 1e-9))`. RB-class includes roster `RB` and `FB`; `Out` and `Doubtful` are excluded while `Questionable` and `unlisted` remain eligible. `RB1` means the roster's `RB`, `pos_rank=1` player, **not the player who ended up leading the actual game in carries**. This is **only the initial-entry draw in grouping 11**, not a predicted game-long snap share, game outcome, or PBV1 impact.

The source field includes 2022–2025 data with recency weighting. Exact output for all 30 teams: [CSV](pbv1-week9-static-audit-2026-11-19.csv).

## Findings

- The 15 snapshots contain **145 distinct rostered RB/FB identities** across 30 teams. **7 are listed Out, 1 Doubtful, 9 Questionable**, leaving **137 eligible** RB/FB candidates. All 30 teams have at least two eligible candidates.
- There are **29 eligible depth-chart RB1s**. NYG's Cam Skattebo is `Doubtful` and excluded from this entry draw. Across the eligible RB1s, the **unweighted average conditional grouping-11 first-entry probability is 59.1%**.
- **9 of 29** eligible RB1s have first-entry probability below 50%; **5** are below 20%.
- **4 RB1s have zero appearances with their current team in the 2022–2025 grouping-11 field**, so their initial-entry rates are entirely the small positional prior. They are **ARI Tyler Allgeier (0.5%); DEN Jonah Coleman (0.2%); WSH Rachaad White (0.3%); KC Kenneth Walker III (1.9%)**. This is direct evidence of team-history staleness suppressing some 2026 starter selections.
- The two injury-report payloads (Thursday and the shared rest-of-week copy) are league-wide. All 15 snapshot evaluations have `verified=false` due to their indicated schedule/depth source-time evidence, so this is an **input/model audit**, not a strictly verified prospective experiment.

## Focused examples

| Team | Pre-game depth RB1 | First entry with 2022–25 field (group 11) | 2026 weeks 1–7 snap share, approximate | Highest prior candidate |
|---|---|---:|---:|---|
| DEN | Jonah Coleman (unlisted) | 0.2% | 13.5% | RJ Harvey |
| WSH | Rachaad White (unlisted) | 0.3% | 44.4% | Jeremy McNichols |
| ARI | Tyler Allgeier (unlisted) | 0.5% | 50.2% | James Conner |
| KC | Kenneth Walker III (unlisted) | 1.9% | 74.7% | Brashard Smith |
| MIA | Ollie Gordon II (unlisted) | 10.7% | 54.5% | De'Von Achane |
| NO | Alvin Kamara (unlisted) | 80.5% | 28.1% | Alvin Kamara |
| GB | Josh Jacobs (unlisted) | 72.6% | 7.7% | Josh Jacobs |
| NYG | Cam Skattebo (Doubtful) | 0.0% | 54.5% | Tyrone Tracy Jr. |

The 2026 snap-share column is **not** the field's entry probability. It is a separate observational usage signal (see below). It directly illustrates that the older team/player rate can be badly misaligned with 2026 roles in both directions. In particular, NO's **Alvin Kamara** gets 80.5% of the historical group-11 first-slot weight, despite approximately 28.1% of observed team offensive snaps through Week 7. This may contribute to the NO workload anomaly seen in the one-seed Week 10 experiment, but does not prove that it did.

## 2026 snap data caveat

The repository's `league_snap_share_nfl_2026_weekly.csv` at `f2f346b7` contains Weeks **1, 2, 3, 4, 5, 6, 7**, **not Week 8**. For reference only, we estimated current team offensive play totals per week as the median `off_snaps / off_pct` among rows with `off_snaps >= 10` and `off_pct >= 0.10`, and divided player offensive snaps across the available weeks by those team totals. The CSV's optional `rb1_first_entry_2026_proxy_not_HE` uses this early-season share for players with nonzero recorded snaps and otherwise retains the historical field rate. **This heuristic is not the implemented HS or HE arm, nor a Week 9 forecast.** The read-only audit used no current target-game snaps.

## Interpretation and next engineering action

**The one-seed campaign's observed carries are not evidence of PBV1 performance.** But the above effect is deterministic and does not require seeds. The historical participation-field `appearances[(player,current_team,group)]` feature can nearly eliminate a 2026 depth-chart RB1 who joined a new team, despite an 11-personnel RB slot existing.

Before spending CPU on additional Week 9 arms, test an alternative **cross-team fallback for player history** and **cutoff-safe 2026 snap usage** against this exact conditional entry probability. Do not simply force RB1 into the lineup: preserve role uncertainty, inactive lists, trades, and qualified backups. Grade player-time/snap and carry distributions across weeks with actual games later, not just rank1, and use matched frozen seeds for simulations.

**Not established:** final player usage accuracy; full-game Brier; actual Week 9 participation; effect of PBV1 on this issue; whether rank1 is the true game-day lead; prospective injury verification. No claim of model improvement or new sim runs is made.
