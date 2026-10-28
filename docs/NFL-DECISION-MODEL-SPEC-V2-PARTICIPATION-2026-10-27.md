# Decision model, version 2: participation categories (frozen specification, 2026-10-27)

Status: frozen before any version 2 result is computed. Version 1 (`NFL-DECISION-MODEL-SPEC-2026-10-27.md`) is unchanged and
its 2026 result stands. This version is not tested on 2026, because the 2026 season has no participation data on disk.

## 1. Question

Does adding per-play participation categories (formation, personnel, coverage, pressure, and time to throw) to a team
prior improve how well the prior reproduces observed team behaviour, compared with the same team prior without them?

## 2. Data

Participation release, seasons 2016 to 2025 (`pbp_participation_<season>.parquet`), joined to play-by-play on the legacy
game ID and `play_id`. Charting and play-by-play categories from version 1 are reused unchanged, so every category set is
scored on the same plays.

Scrimmage universe: regular-season pass and run plays, with down, distance and yard line, as in version 1. A play joins
participation or it is excluded from the participation categories and counted.

## 3. Categories added

Each category is scored on the plays where it is defined.

| Category | Plays | Definition | Roles |
|---|---|---|---|
| P1. Formation | All scrimmage plays with a participation formation | `offense_formation` | shotgun, under center, pistol, other |
| P2. Personnel | All scrimmage plays with a personnel code | `offense_personnel`, six most frequent codes in 2016 to 2022, rest as other | six codes, other |
| P3. Coverage | Pass plays with a charted coverage type | `defense_coverage_type` | cover 1, cover 2, cover 3, cover 4, 2-man, other |
| P4. Man or zone | Pass plays with a charted man or zone label | `defense_man_zone_type` | man, zone |
| P5. Time to throw | Pass plays with a time to throw | `time_to_throw` bins at the terciles of pass plays in 2016 to 2022 | low, mid, high |
| P6. Pressure | Pass plays with `was_pressure` | `was_pressure` | yes, no |

Behavioural note. P5 and P6 describe how the play was executed, not the pre-snap decision. The QB's release timing is a
decision made during the play, and pressure is the outcome of protection. They are scored as behaviour, with a separate
headline (section 7). They are never used as pregame conditioning, because a same-play measurement would leak the play.

Terciles for P5 are computed once, from pass plays in 2016 to 2022 only, and then frozen. The cut points are written into
the run record with their hash before any validation result is produced.

## 4. Priors and situations

The prior, situation cells, shrinkage form and league baseline are exactly those of version 1 (sections 3 and 4 of its spec).
Version 2 adds the participation categories to the same prior machinery. The team prior for a participation category is
conditioned on the same 24 situation cells.

## 5. Windows

- **Development, 2016 to 2023.** Fit on 2016 to 2022. Choose the shrinkage weight k from {5, 20, 80} on 2023 by lowest
  mean total-variation distance over the participation categories. Ties go to the smaller k.
- **Validation, 2024.** Refit on 2016 to 2023 with the chosen k. Score once. This is the primary test of version 2.
- **Examined second look, 2025.** Refit on 2016 to 2024 with the same k. Score once. 2025 was used as training and
  validation data for version 1, so this result is labelled as a second look and cannot establish adoption on its own.
- **2026.** Not used. There is no participation data for 2026.

No window is chosen after a result. Each window is fixed here.

## 6. Comparison

For each window, two priors are scored on the same plays and categories:

- **Version 1 categories only:** the version 1 prior over categories A to N, as in the version 1 spec.
- **Version 2:** the same prior over categories A to N plus P1 to P6.

Headline (behaviour): mean total-variation distance over A to N and P1 to P4 (decision categories). Behaviour headline: mean
over P5 and P6, reported separately. Both use team priors and league priors on the same plays.

Uncertainty: 2,000 bootstrap resamples of games, seed 20261027. The paired interval is for version 2 minus version 1 on the
decision headline.

## 7. Decision rule

- Version 2 adds information only if, on the 2024 validation window, its decision headline is lower than version 1's and
  the paired 95% interval excludes zero. Otherwise the report says participation categories show no support on 2024.
- 2025 is reported as a second look and cannot establish adoption alone. Agreement on 2025 without 2024 support is
  reported as inconsistent.
- The behaviour headline is reported in both windows, with its interval, and is not used to decide adoption.
- Nulls are reported as nulls.

## 8. What this does not show

- It does not test movement, positions, or outcomes.
- It does not test 2026.
- Pressure and time to throw are behaviour categories. A result on them describes how plays were executed, not how a
  decision was made.
