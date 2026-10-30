# Dated player workload examples

Examples use the cutoff-safe nflverse PBP inputs pinned in `manifest.json`. A single high-volume game is evidence that a workload can occur; it is not an average expectation.

## Running backs

| Role example | Date | Game | Actual usage |
|---|---|---|---|
| Jaylen Warren | 2025-09-21 | PIT–NE | 18 carries, 47 rush yards; 6 targets, 5 catches |
| Jaylen Warren | 2025-11-23 | PIT–CHI | 18 carries, 68 rush yards |
| Jaylen Warren | 2026-10-25 | PIT–NO | 18 carries, 101 rush yards; 4 targets, 3 catches |
| Christian McCaffrey | 2025-11-02 | SF–NYG | 28 carries, 106 rush yards; 6 targets, 5 catches |
| Christian McCaffrey | 2022-12-15 | SF–SEA | 26 carries, 108 rush yards; 8 targets, 6 catches |
| Derrick Henry | 2025-12-27 | BAL–GB | 36 carries, 216 rush yards |
| Derrick Henry | 2022-10-30 | TEN–HOU | 32 carries, 219 rush yards |
| Tyler Allgeier, lower-volume role reference | 2023-01-08 | ATL–TB | 24 carries, 135 rush yards |
| Tyler Allgeier, lower-volume role reference | 2023-10-22 | ATL–TB | 21 carries, 59 rush yards; 3 targets, 3 catches |
| Tyler Allgeier, lower-volume role reference | 2023-01-01 | ATL–ARI | 20 carries, 83 rush yards; 1 target, 1 catch |

Allgeier averaged 8.41 carries over 17 observed 2025 games and 8.71 over seven event-observed 2026 Weeks 1–7 games. His larger historical games coexist with that lower opportunity rate.

## High-target receivers

| Player | Date | Game | Actual usage |
|---|---|---|---|
| DK Metcalf | 2022-11-27 | SEA–LV | 15 targets, 11 catches |
| DK Metcalf | 2023-10-29 | SEA–CLE | 14 targets, 5 catches |
| DK Metcalf | 2026-10-18 | PIT–TB | 15 targets, 11 catches |
| Ja'Marr Chase | 2025-10-16 | CIN–PIT | 23 targets, 16 catches |
| Ja'Marr Chase | 2023-10-08 | CIN–ARI | 19 targets, 15 catches |
| Ja'Marr Chase | 2025-10-26 | CIN–NYJ | 19 targets, 12 catches |

Target share is player targets divided by the team's total pass attempts in that window:

| Player | 2025 holdout | 2026 Weeks 1–7 |
|---|---:|---:|
| DK Metcalf | 99 / 550 = 18.0% | 58 / 265 = 21.9% |
| Ja'Marr Chase | 185 / 640 = 28.9% | 45 / 219 = 20.5% |

The 2026 target counts stop at Week 7; they do not include any Week 8 or later observations.

## Pocket quarterbacks

These are the named players’ highest observed scramble-count games in the artifact, included to show that a low-scramble QB can still have a multi-scramble outlier. Their multi-season averages are much lower (0.41–0.60 scrambles and 1.63–1.69 total carries per game).

| Player | Date | Game | Actual QB rushing breakdown |
|---|---|---|---|
| Kirk Cousins | 2022-10-30 | MIN–ARI | 3 scrambles, 1 designed run; 4 carries, 22 yards |
| Matthew Stafford | 2023-09-17 | LA–SF | 4 scrambles; 4 carries, 17 yards |
| Jared Goff | 2023-11-23 | DET–GB | 3 scrambles; 3 carries, 9 yards |

## Mobile quarterbacks

| Player | Date | Game | Actual QB rushing breakdown |
|---|---|---|---|
| Lamar Jackson | 2024-09-05 | BAL–KC | 10 scrambles, 6 designed runs; 16 carries, 122 yards |
| Jayden Daniels | 2024-09-08 | WAS–TB | 7 scrambles, 8 designed runs, 1 kneel; 16 carries, 88 yards |
| Jalen Hurts | 2022-12-18 | PHI–CHI | 4 scrambles, 11 designed runs, 2 kneels; 17 carries, 61 yards |
| Josh Allen | 2024-01-07 | BUF–MIA | 4 scrambles, 9 designed runs, 2 kneels; 15 carries, 67 yards |

These examples keep scrambles, designed runs, and kneels separate. The event definitions and source limitations are in the accompanying `REVIEW.md` and machine-readable benchmark manifest.
