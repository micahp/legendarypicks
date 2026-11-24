# SLC-CEG Phase 4 pre-registration: special teams, tries, penalties, overtime decisions, returns

Written 2026-11-24, before any Phase 4 model is scored. Phases 2 and 3 stay unchanged. Code:
`scripts/nfl_sequence/ceg_special.py`. Regular season only.

## Rule regimes, measured

Kickoff touchback share: 2022 0.597, 2023 0.730, 2024 0.642, 2025 0.207, 2026 0.158 (2,698 to 2,809 kickoffs a season).
Every season is its own kickoff regime. So kickoff components never pool seasons as if they were one population:

- **Arm B (prior regime):** the previous season's distribution, fixed for the whole target season.
- **Arm C (regime-adapted):** walk-forward inside the target season. For a kickoff in week w, the counts from weeks
  before w of the same season, shrunk toward the previous season's distribution with pseudo-count k.

## Components

| id | target | unit | arm B | arm C |
|---|---|---|---|---|
| K1 onside | onside or not | kickoff | league | score state x time bucket (Phase 3 buckets) |
| K2 kickoff result | touchback, kicking-team recovery, return TD, or the receiving team's start yardline (1-99) | non-onside kickoff, no penalty | prior regime | regime-adapted (above) |
| K3 onside recovery | kicking team recovers | onside kickoff | league | league (too few: B only) |
| K4 punt result | touchback, blocked, kicking-team recovery, return TD, or receiving start yardline | punt, no penalty | punt spot in 10-yard bins | 10-yard bin, then 5-yard bin |
| K5 field goal | made, missed, blocked | attempt, no penalty | kick distance in 5-yard bins | 10-yard, then 5-yard, then 1-yard |
| K6 try choice | two-point or extra point | post-touchdown try | league | score margin after the touchdown (from the scoring team: -15 or less ... +15 or more, 9 bins) x time bucket |
| K7 try success | made | extra point; two-point | by kind | by kind (B only) |
| K8a pre-snap foul | none, offense, defense | snap (every play class) | league | down x distance bucket x field zone |
| K8b live foul | none, offense, defense | snap with a play (not no_play) | league | play class x down x distance bucket |
| K9 penalty type | the 15 most common types, then other | penalty | by phase and side | phase and side x play class (pre-snap: none) |
| K10 overtime 4th down | intent | overtime 4th-down snap with a call | v2's rule: field goal at 0.9 when eligible, else run, dropback, punt at the Phase 2 arm C shares | the Phase 2 arm C intent model, unchanged |
| K11 interception return | return yards, censored at the end zone (pick-six) | interception | league | field zone of the catch point |
| K12 fumble return | return yards, censored | fumble lost | league | field zone of the fumble |

Not fitted, documented priors (too rare to evaluate): blocked-kick recovery side and return (41 blocked punts and 97
blocked field goals in 2022 to 2026), safety free kicks (62 safeties), and penalty enforcement, which stays with the rules
core. A penalty enforcement check is reported: for live fouls, the share where the next snap equals the line of
scrimmage moved by the penalty yards.

**Amendment, 2026-11-24, before any Phase 4 score:** the first K8 conditioned on play class with `no_play` counted as
pre-snap. A `no_play` row is a pre-snap foul, so that leaks the label. K8 is split into K8a (pre-snap, by situation, every
snap) and K8b (live, by play class, snaps with a play), in the order a generator draws them.

## Selection, periods, metrics

- k from {1, 3, 10, 30, 100, 300}: train 2022-2023, validate 2024 (kickoffs: walk-forward inside 2024 with the 2023
  prior). Refit through 2024 (kickoffs: 2024 prior, walk-forward inside 2025). Score once on 2025; report 2026 weeks
  1 to 11 as examined (kickoffs: 2025 prior, walk-forward inside 2026).
- Metric: log loss per opportunity, start yardlines and return yards censored where stated; 95% game-bootstrap
  interval for C minus B. K10 is scored on 2022-2025 overtime 4th downs together, because there are few (reported n).
- No result here selects anything in Phases 2 and 3.

## Exit check

For every kickoff, punt, field goal, try and penalty state in a grid (kick spots 1-99, both onside choices, scores and
times), the components return a legal outcome: a start yardline 1-99, a touchback, or a score; 0 refusals.
