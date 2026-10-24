# E3 clock: finding and baseline B (2026-10-24)

Scope: 2022 weeks 1-9. The decomposition covers the 15,768 tracking-verified plays. The runoff rows B is evaluated on cover the
16,701 LP plays with a modelled outcome and a runoff. The comparison was run at `108a1afe`
(`scripts/nfl_sequence/clock_compare.py`), fit on weeks 1-5 and tested on weeks 6-9. Weeks 6-9 were examined when the comparison
was run, so none of these results is a holdout test.

## Finding: tracking does not improve clock duration on this sample

Tracking-informed model C adds **0.1 s** to drive-duration error over PBP-only model B. Drive MAE is 20.1 s for C and 20.0 s
for B on 1,007 drives. On per-play runoff, C is worse than B on the common outcomes (W1 distance, seconds):

| outcome | plays | observed median | W1 B | W1 C |
|---|---:|---:|---:|---:|
| run | 2,560 | 38.0 | 0.25 | 0.41 |
| pass complete | 2,008 | 36.0 | 0.29 | 0.44 |
| pass incomplete | 1,051 | 5.0 | 0.06 | 0.31 |
| touchdown | 192 | 6.0 | 0.23 | 0.38 |
| interception | 36 | 9.0 | 1.20 | 1.06 |
| sack | 185 | 40.0 | 0.94 | 0.76 |

C is better only on interceptions and sacks, which are rare. Tracking matches the in-play time (T1b: pass complete 5.4 s
observed and 5.4 s drawn), but the in-play time is a small part of the runoff, so matching it does not move the clock. Game-total
MAE is 56.3 s for B and 56.6 s for C.

## Quarter ends: no model matches the observed share

Share of plays that reach a quarter end: observed 2.5%; A 14.3%; B 4.7%; C 4.5%. B excludes censored quarter-end runoffs, so it
cannot produce the quarter end; A includes them and overshoots by about six times. This is the main limit of B.

## Decision

**B is the E3 baseline.** The reasons, in order: it is as accurate as C on drive and game-total error, and more accurate on the
common per-play outcomes (run, pass complete, pass incomplete, touchdown); it needs only the play-by-play, not tracking; and it is the
simplest of the three. This is adoption as a baseline, not a promotion test: the weeks
it is measured on were examined earlier.

## Unresolvable fields, enumerated

Counts are from the decomposition's own JSON (`e3-clock-decomposition-2026-10-24.json`, commit `4e18cb9f`). "Used by B" says whether B
reads the field.

| field | unresolvable | rule codes | used by B | how B treats it |
|---|---:|---|:-:|---|
| game_clock_delta_s | 391 | R4u1 6 (no same-quarter next play); R4u2 374 (quarter-end, censored); R4u3 11 (negative difference) | yes | censored rows are excluded from the pool; R4u1 and R4u3 have no runoff row |
| in_play_s | 62 | R2u (no terminal frame) | no | not used |
| residual_s | 453 | R5u | no | not used |
| real_snap_to_next_snap_s | 4,587 | R6u | no | not used |
| penalty_clock_stop | 15,768 | R11u (no stoppage duration in any source) | no | the penalty flag is a stoppage context; its clock duration is unresolvable, so B cannot model it |
| timeouts_remaining | 15,768 | R10u (no per-play remaining count) | no | not used |
| two_minute_warning_event | 15,768 | R12u (not identifiable in the play-by-play) | no | not used; the late-half state is observed |

## Artifact

Directory: `docs/evidence/e3/clock-decomposition-v1/`

- `MANIFEST.json`: version 1.0.0, the B definition, the unresolvable list, the file hashes, the provenance, the checks and the
  consumer rules.
- `clock-decomposition.csv` (sha256 `11f8dc2b…`): one row per verified play, byte-identical to the audit branch.
- `clock-decomposition.schema.json`: the columns, with label values read from the data.
- `clock-baseline-B-runoffs.csv` (16,701 rows): the LP runoff rows B is evaluated on, with `b_pool_eligible` marking the draw pool.
- `clock-baseline-B.schema.json`: the schema for that file.

Checks in the manifest: the B pool written to the file equals `clock_compare.fit()`'s pool in memory (true). The decomposition's
game-clock delta equals LP's runoff for the same play on 15,377 of 15,377 resolved rows (0 disagree, 0 missing).

Consumers must verify each file's sha256 before use, leave unresolvable values null, and sample B only from rows with
`b_pool_eligible = 1`.
