# SLC-CEG Phase 2 pre-registration: scrimmage components, arms B, C and C-FTN

Written 2026-11-24, before any Phase 2 model is scored on 2025. Code: `scripts/nfl_sequence/ceg_phase2.py`.

## Event chain (scrimmage)

```text
play_decisions:  intent in {designed_run, dropback, punt, field_goal, kneel, spike}
dropbacks:       sack | scramble | attempt            (no_attempt dropbacks are counted, then left out: 0 in 2022-2025)
pass_attempts:   throwaway | targeted                 (FTN label; plays with no FTN row are left out and counted)
targeted:        air yards (integer)  ->  complete | incomplete | interception given the air-yards bucket
completions:     yards after catch given the air-yards bucket, right-censored at the goal line (yardline_100 - air yards)
designed_runs, scrambles, sacks:  yards gained, right-censored at the goal line (touchdown = gain >= yardline_100)
fumbles:         fumble given the event; lost given a fumble (recovering team unknown: left out of "lost" and counted)
```

## Arms

- **B, league level.** Each component conditions only on its chain parents (the event at its node and the air-yards
  bucket where the chain has one) and on the field for legality (gains are censored at the goal line; a field goal is
  legal only where yardline_100 <= 50). No down, distance, score or clock.
- **C, situation conditioned, league level.** B plus a fixed hierarchy of situation cells, each shrunk toward its parent
  with pseudo-count k:
  intent, dropback, throwaway, outcome, fumble: league -> down -> down x distance bucket -> down x distance x field zone
  -> down x distance x field zone x score state x half-time state.
  yards (hazard of each integer gain): league -> field zone -> field zone x down -> field zone x down x distance bucket.
  Buckets: distance 1-2, 3-5, 6-9, 10+; field zone 1-5, 6-10, 11-20, 21-40, 41-60, 61-80, 81-99; score state trailing 9+,
  within 8, leading 9+; half-time state more than 2:00 left, 2:00 or less.
- **C-FTN (challenger).** C plus one charted context per component, on plays with an FTN row:
  dropback outcome + pass rushers (4 or fewer, 5, 6 or more) and play action; targeted outcome + play action and screen;
  designed-run yards + defenders in the box (6 or fewer, 7, 8 or more). First scored with the observed context, then
  as a composition with generated context: P(y | s) = sum over ctx of P(ctx | s) P(y | s, ctx), with P(ctx | s) a C-style
  model. Compared with C on the identical FTN-covered plays.

## Yardage form

Discrete hazard on integer gains, no cap or floor: support is every observed gain (2022 to 2026: -34 to +98). For a play
at yardline_100 = L, a gain below L is exact; a touchdown is right-censored (gain >= L); a gain that ends at the own goal
line is scored as the mass at or below L - 100. The log score of a touchdown is log P(gain >= L).

## Periods and selection

- Tune k from {1, 3, 10, 30, 100, 300} per component on train 2022-2023, validate 2024.
- Refit 2022-2024 with the chosen k. Score once on 2025 (confirmation). Report 2026 weeks 1 to 11 as examined.
- Metric: mean log loss per opportunity; 95% interval for C minus B, and for C-FTN minus C, by a bootstrap over games
  (1,000 resamples).
- Regular season only. Penalty plays stay in their own views; a component is scored on plays without a penalty.
- A component of C counts as better than B only if the 2025 interval is below zero. C-FTN counts as better than C only
  if its 2025 interval is below zero on the FTN-covered plays, both observed and generated.

## Exit checks for the generator

The generator built from the fitted components must, for every state in a grid (down 1-4, distance 1 to 30 and goal to
go, yardline 1 to 99, score states, both half-time states) and for every week 11 v1 and v1.5 failure cell, return a play
that passes `ceg_contract.validate`, with no refusal.
