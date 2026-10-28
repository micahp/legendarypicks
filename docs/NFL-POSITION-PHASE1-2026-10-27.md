# Position data, Phase 1: identity and starting-quarterback validation (2026-10-27)

Status: research, read-only. This is Phase 1 of `NFL-POSITION-DATA-PLAN-2026-10-27.md`. Script:
`scripts/nfl_sequence/splits/position_phase1.py`. No production table is changed.

## What was checked

1. **Identity.** Every player ID in the 2024 and 2025 weekly stats, and every gsis ID in the depth charts, was matched to
   the players table (24,861 players).
2. **QB1 against the actual starter.** The actual starter is the quarterback with the most attempts in a team-week
   (regular season). The depth chart's QB1 is compared with that starter:
   - 2024, week-level chart (no timestamp). Tests identity only.
   - 2025, timestamped snapshots. The chart as it stood at kickoff, meaning the latest snapshot before the scheduled kickoff.

## Results

| Check | Result |
|---|---|
| Stats player IDs matched to players, 2024 and 2025 | 100.00% |
| Depth-chart gsis IDs matched to players, 2024 and 2025 | 100.00% |
| Team-weeks with an actual starter, 2024 and 2025 | 544 each (ties in attempts: 1 and 2) |
| 2024 QB1 (week-level chart) agrees with the starter | 449 of 538 (83.5%) |
| 2025 QB1 at kickoff agrees with the starter | 485 of 544 (89.2%) |
| 2025 team-weeks with no snapshot before kickoff | 0 |

## Why the chart and the starter disagree

Each disagreement was classified by whether the chart's QB1 recorded any attempts that week, and by whether he was on the
injury report.

| Season | Disagreements | Chart QB1 did not play | of which on injury report | Chart QB1 played (rotation or mid-game change) |
|---|---:|---:|---:|---:|
| 2024 (week-level chart) | 89 | 72 | 50 | 17 |
| 2025 (chart at kickoff) | 59 | 47 | 47 | 12 |

- **2025.** Every team-week where the chart's QB1 did not play is on the injury report. The 2025 kickoff chart therefore
  fails only where the injury report already shows a problem, and the other 12 disagreements are rotations or
  mid-game changes.
- **2024.** 22 of the 72 "did not play" cases have no injury-report entry. They are not explained by this check (possibly
  inactive or a late change). They are listed as unexplained, not resolved.

## Caveats

- The starter is a proxy: the quarterback with the most attempts. A quarterback who starts and leaves early can be the
  proxy's error, not the chart's. The 12 and 17 "played" cases are where that proxy and the chart disagree.
- The 2024 chart has no timestamp, so its agreement says nothing about what was known before kickoff. Only the 2025
  kickoff test addresses timing, and its snapshots were all present.
- Ties in attempts are counted, not resolved (1 team-week in 2024, 2 in 2025).

## Reading for the position plan

- Identity is clean. The gsis match rate is 100% in both seasons, so the join key can be used as planned.
- The 2025 kickoff chart is a usable QB1 signal. It agrees with the starter in 89.2% of team-weeks, and every
  disagreement where the chart's QB1 did not play is on the injury report.
- The 2024 week-level chart agrees less often (83.5%), and 22 of its misses have no explanation here. It is a sensitivity
  tier, as the plan says.
