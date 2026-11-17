# Forced goal-line fumble transitions by model arm

Date: 2026-11-17. Code: commit 2f739afa (PR #49 branch). Regression tests: scripts/nfl_sequence/test_forced_arms.py (commit c72b1295, local).

## Question

When a fumble leaves the ball past the offense goal line, what does each model arm do?

## Method

Each scenario is one source row. Two stages run for each arm:

1. Classification. The arm's classifier (`e1_drive.classify`) reads the row. The `separate_sack_fumbles` flag is off for the legacy arm and on for the conditional arms.
2. Drive loop. The event that the classifier produced, or the raw event when the pool would exclude the row, runs as one play through `e1_drive.simulate`. The arm sets `own_end_zone`, `geometry_filter`, and the recovery model.

No seeds were drawn. The sampler uses a fixed first-cell choice.

## Arms

| Arm | Pass-label mode | Sack-fumble event | Own end zone | Geometry filter | Recovery model |
|---|---|---|---|---|---|
| V1 legacy | legacy | no (sack-fumble reads as `fumble_lost`) | refuse | off | none |
| V1.6 frozen | conditional | yes | refuse | off | none |
| V1.7 penalty-free | conditional | yes | resolve | on | none |
| V1.7 with recovery | conditional | yes | resolve | on | model (seed 61) |

V1.5 is not configured separately in this repository, so it was not run. V2 is not in this repository. Its reducer was read on the fast host: it has no sack-fumble event, and it has no own-end-zone check on turnovers. It matches the V1 legacy path in code. V2 was not run.

## Forced results

| Scenario | V1 legacy | V1.6 frozen | V1.7 penalty-free | V1.7 with recovery |
|---|---|---|---|---|
| Run fumble lost, own 1, into own end zone | silent turnover at the next-snap spot | silent turnover | named block (no legal row) | touchdown (real model, seed 61; forced harness only, not in the test file) |
| Sack fumble lost, own 1, into own end zone | silent turnover (classified as a generic fumble) | refused (illegal state) | named block | safety (fixed stub outcome) |
| Pass fumble lost, own 8, into own end zone | silent turnover | silent turnover | named block | touchdown (fixed stub outcome) |
| Fumble lost in the field (control) | turnover | turnover | turnover | turnover |
| Fumble-return touchdown source row | excluded | excluded | excluded | excluded |

## What the code shows

- The generic `fumble_lost` branch in `reducer.apply_play` has no goal-line check. Run, pass, and sack events are checked. A generic fumble past the own goal line passes through as an ordinary turnover. This is a defect in V1 and in frozen V1.6. It is recorded here and pinned by a test. V1.6 is not changed.
- In V1.6 the sack-fumble path is refused. In V1 the same sack-fumble is silently converted.
- In V1.7 the geometry filter removes these rows from the pool, or the recovery model resolves them.

## Reachable rows in the V1.6 source pool

The V1.6 pool came from the historical file `slc-history-v17.sqlite` (nfl_pbp seasons 2022 to 2026, week 9). The file is on the fast host. Its build database is not on the host, so this count cannot be rebuilt from the same source.

- 1,134 rows have the fumble-lost flag.
- 74 of them are flagged as touchdowns. The classifier excludes all 74 in every arm.
- Among non-touchdown fumble rows, 15 sack-fumble rows could cross the own goal line when applied at a simulated spot from 80 to 99. V1.6 refuses them. V1 converts them silently.
- Zero non-sack fumble rows could cross the goal line from a source spot of 80 or more. The generic silent path therefore has no reachable row in this pool. It is latent, and it would become active if the pool changed.
- Five touchdown fumble rows end exactly on the goal line (destination 100). All five are excluded.

## Implications

1. Frozen V1 and V1.6 do not resolve own-end-zone fumbles. V1 hides the sack case as an ordinary turnover. V1.6 refuses it. Neither result is a football outcome.
2. The completion rate of an arm can rise when its pool excludes hard rows. Those rows are the fumble-return touchdowns and the own-end-zone fumbles. A higher completion rate for an earlier arm does not show better handling of these plays.
3. The 74 excluded fumble touchdowns are a separate gap. A model that cannot sample those outcomes does not model the full turnover distribution. This is the next follow-up. It is not fixed in this note.
4. Fifteen sack rows and zero generic rows are enough for regression tests. They are not enough for a calibrated rate.

## Limits

- The forced runs test code paths. They do not measure how often each path occurs.
- The V1.6 counts use a history file built with an older classifier. The current code fails that file's classifier-identity check. The counts are from the file as it stands.
- The recovery stub in the V1.7 arm is a fixed model, not the fitted model.
