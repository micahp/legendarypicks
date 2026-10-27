# Game-info attendance contract (proposed v2, not implemented)

Status: proposal for review. Nothing is implemented, and no snapshot is changed. The frozen Week 8 game-info snapshot
(`gameinfo-2026-w08-20261027T185659Z-039a4748a3.json`) and the current `game_info_snapshot.py` stay as they are.

## What the current contract contains

The v1 game-info snapshot carries `venue.listed_capacity` (the 2026 venue snapshot's listed seating figure). It has no
attendance count, no attendance percentage and no expected-attendance estimate. The snapshot is attached to simulation
output with `used_by_model: false`.

## Definitions

Each field has one definition, one time basis and one permitted use. "Pregame" means knowable at the forecast cutoff.

| Field | Type, nullable | Definition | Time basis | Permitted use |
|---|---|---|---|---|
| `venue.listed_capacity` (v1, unchanged) | integer, yes | The 2026 venue snapshot's listed seating figure. Undated | Snapshot time | Reference display only. Not a historical value |
| `venue.capacity_historical` | integer, yes | Reconciled dated seating capacity for the building and season (status `ok` or `flagged`, see the reconciliation report) | Publication date of the figure. Not stored yet, so pregame use is blocked | Historical context. Pregame only after `published_at` is recorded and the figure is known before the cutoff |
| `venue.event_capacity` | integer, yes | Authorized capacity for a specific event configuration, such as the EverBank 2026 renovation season | Announcement date. Not stored yet | Historical and pregame context once the announcement date is recorded. Populated for no game yet: the EverBank 2026 value is verified but excluded from lookups |
| `venue.standing_room` | integer, yes | Standing-room tickets included in `event_capacity` | As `event_capacity` | Context only |
| `attendance.expected` | integer, yes, default null | Estimate of attendance made before kickoff from observations before the cutoff only | Cutoff-safe by construction | Future experimental pregame feature. Null until an estimator is validated (below) |
| `attendance.reported` | integer, yes | Announced attendance after the game (ESPN scoreboard, post-game) | Post-game | Retrospective research and labels. Never a pregame input |
| `attendance.status` | enum | `reported`, `reported_zero`, `suspect`, `missing`, `not_collected` (see below) | Post-game | Retrospective |
| `attendance.pct_reported_capacity` | number, yes | `attendance.reported` divided by `capacity_historical`, only when that capacity is `ok` or `flagged` | Post-game | Retrospective research. Values above 1 are kept and flagged, not removed |
| `attendance.turnstile` | integer, yes | Entrants counted at the gates, if independently measured | Post-game | Not collected anywhere. Always null in v2 |

`attendance.reported` is not turnstile attendance. It is announced attendance, which may count tickets distributed rather
than people who entered. `pct_reported_capacity` is therefore reported occupancy, not a measure of crowd density or noise.

## Status values

| Status | Meaning |
|---|---|
| `reported` | The source gives a positive count, and the game is not flagged suspect |
| `reported_zero` | The source gives 0. Recorded as 0, never as null. Whether it is a verified zero crowd is not checked per game (2020: 153 games) |
| `suspect` | Flagged in the database. The value is dropped from `attendance.reported` and kept in the audit column |
| `missing` | No count in a season where the source collects one. Null |
| `not_collected` | No source row for the season (2010 to 2014 and 2026). Null, and not a missing value |

## Cutoff and leakage rules

1. `attendance.expected` may use only observations from games completed before the cutoff. The cutoff is the frozen forecast
   time in a 2026 snapshot, and kickoff minus 24 hours for a historical test (contract v1, section 3).
2. Post-game attendance, actual weather and the 2026 holdout must never reach a pregame field.
3. A value with no known publication or observation time is not used in a strict test. It is reported as a sensitivity case.
4. Market prices, spreads and totals are not inputs. The contract v1 rule stands.

## Expected attendance: what would have to be true before it is used

- It is a backtest-only estimator until it is fitted on one window and scored on later seasons. Its evaluation contract:
  - A count (attendance itself) is a numeric forecast. Score it with MAE and CRPS of its predictive distribution. Brier does
    not apply to a count.
  - A defined binary event (for example attendance at or above 95% of the dated capacity, or any other threshold fixed
    before the run) is scored as a probability of that event, with Brier, log loss and calibration. Each event is named in
    advance, and the threshold is not tuned on the evaluation seasons.
  - Every score is reported with its window, its sample size and an interval. The 2026 season is not used to choose it.
- Its baseline is the building's own recent reported attendance before the cutoff (for example the mean of the last eight
  home games before the cutoff, with a minimum count). It must beat the constant league-wide baseline.
- It cannot be used for a building whose capacity status is `contradicted` or `unresolved` unless the question is explicitly
  about reported attendance, not capacity.

Until those checks pass, `attendance.expected` stays null in every snapshot.

## Versioning

- A v2 snapshot is a new snapshot with a new ID. Every v1 snapshot keeps its ID and its content.
- No backfill: reported attendance is not written into any existing snapshot, including the Week 8 snapshots of
  2026-10-27.
- Schema, validation and tests are required before any v2 snapshot is written. None is written in this pass.
