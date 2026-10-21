# CP4 prospective grade: first run, gates, and what is frozen (2026-10-21)

- **Status: CP4 is open. No cell has evidence.** The grader ran on the live dev database, read-only, at 03:55 CDT on
  2026-10-21 and graded 0 matches in all six cells. A cell with fewer than 200 graded matches is not evidence. The grader
  prints its n and the verdict INSUFFICIENT_PROSPECTIVE_DATA for it, and nothing else.
- **Branch:** `feat/tennis-cp4-grading`, from `dev` at 379c24e0. Not pushed, not deployed, nothing written to the live dev
  or prod database. The lock path is dev's (model version `tennis-counts/2026-10-20`); this work does not change it.
- **Files:** `run_prospective_grade.py` (this directory, read-only), `check_replay_parity.py` (this directory),
  `backend/cp4_evidence_assembly.py`, tests in `backend/test_tennis_prospective_grade.py`.

## Run

```
python3 research/tennis/cp4-2026-10-20/run_prospective_grade.py --db /root/legendarypicks/backend/data/picks.dev.db
```

The database is opened with `mode=ro`.

| cell | graded matches (n) | verdict |
| --- | ---: | --- |
| ATP aces | 0 | INSUFFICIENT_PROSPECTIVE_DATA |
| ATP double faults | 0 | INSUFFICIENT_PROSPECTIVE_DATA |
| ATP total games | 0 | INSUFFICIENT_PROSPECTIVE_DATA |
| WTA aces | 0 | INSUFFICIENT_PROSPECTIVE_DATA |
| WTA double faults | 0 | INSUFFICIENT_PROSPECTIVE_DATA |
| WTA total games | 0 | INSUFFICIENT_PROSPECTIVE_DATA |

Accounting: 31 locks in `tennis_model_locks`; 0 with a frozen distribution; 31 with none; 0 excluded for timing; 0 for a
frozen-at mismatch; 0 distribution rows without a lock.

Source tables on dev: `tennis_model_locks`, `scoreboard_snapshots` and `tennis_model_lock_distributions` are present. The
distribution table has 0 rows. `research_player_match_outcomes` is absent.

Why the counts are zero:

- All 31 locks were made before the freeze merge (379c24e0, 03:44 CDT). The lock sweep freezes distributions only for
  locks it creates, so none of these has a frozen row. The next new tennis lock on dev is the first candidate.
- Aces and double faults also need verified outcomes, which are not on dev (see below).

## Gates

Fixed in `research/tennis/counts-2026-10-20/RESULTS.md` (pre-registered, not changed here):

| gate | rule |
| --- | --- |
| PIT uniformity | KS <= 0.02 |
| PIT tails | share below 0.05 and share above 0.95 each in [0.04, 0.06] |
| Coverage | observed 50, 80 and 90% coverage each >= nominal - 0.02 |
| Upper tail | share above predicted p95 <= 0.06; share above predicted p99 <= 0.015 |
| Threshold reliability | at each book-style line, abs(observed - predicted P(over)) <= 0.02 |

At 200 or more graded matches the grader emits CALIBRATION_GATES_PASS or CALIBRATION_GATES_FAIL. It does not emit
ADOPT_CANDIDATE, INCONCLUSIVE or NOT_ADOPTED. Those need the reference and runner-up legs, and neither distribution is
frozen. The clustered bootstrap is not computed.

## What is frozen, and what is not

Frozen by dev's lock path, for locks created after the merge, only where the match is best of three with a mapped surface
and both players mapped to Sackmann ids:

- Aces and double faults: P1 Gamma-Poisson, one row per side. Stored parameters (including `model_day`) and the PMF from its
  support start, trimmed where a probability is below 1e-12, with the trimmed mass stored.
- Total games: direct surface plus competitiveness, one row per match, with the PMF over its full support and the
  parameters (including `model_day`).

Not frozen:

- The reference (C0 for counts, direct format for total games), the runner-up, and the point simulator.
- The 31 existing locks. They are counted, never backfilled.
- ATP Grand Slam matches (best of five) and matches without a mapped surface or Sackmann identity.

Observed outcomes:

- Total games: the final scoreboard snapshot (state post, completed or Final), with set games summed. This is the reading
  `grade_tennis_model` uses.
- Aces and double faults: `research_player_match_outcomes`, verified tiers only, `eligible_cp4 = 1` for both sides. That
  table is in the research database, not on dev. `backend/cp4_evidence_assembly.py` copies it into an evaluation copy,
  which the grader then reads. No collector schedule was found: `systemctl list-timers --all` lists no research collector,
  and the root crontab has no entry for one (checked 03:54 CDT). Until a collector runs and its outcomes are assembled, aces
  and double faults cannot be graded.

## Look-ahead guard

- Lock path (dev): `replay_rows` raises `LookAheadError` if a source row is dated on or after the model day. History is
  built from rows strictly before the model day, and the model day is the match's UTC date.
- Grader: `check_no_look_ahead` reads `model_day` from every frozen parameter set. It fails if the value is missing, or if
  it is after the match's UTC date. The cutoff bounds the source rows from above, so a cutoff no later than the match date
  means every source row is earlier than the match.
- Locks made at or after the match start are excluded before this check, and counted.

## Measured findings

1. **The history behind every lock stops in June.** On dev, `tennis_atp_matches` ends at tourney_date 2026-06-01 and
   `tennis_wta_matches` at 2026-06-02. The lock path builds its history only from those tables. So each October lock is
   pre-match (no look-ahead), but it uses state about four and a half months old. The replay window also ended in May, so
   this matches the scored protocol. It is still a staleness that any CP4 reading has to carry.

2. **The KS gate cannot pass at the 200-match floor, even for a perfectly calibrated model.** Simulated with uniform PIT
   values (300 replications per size, seed 7):

   | targets in the KS sample | what it is | mean KS | 95th percentile | share of replications with KS <= 0.02 |
   | --- | --- | ---: | ---: | ---: |
   | 200 | total games at 200 matches (one target per match) | 0.061 | 0.098 | 0.000 |
   | 400 | counts at 200 matches (two players per match) | 0.043 | 0.072 | 0.010 |
   | 2000 | counts at 1000 matches | 0.019 | 0.032 | 0.620 |

   The KS gate was fixed before any run and is not changed here. Whether to change it at small n is Micah's decision, and a
   change needs its own pre-registration.

3. **Replay parity holds on dev's lock path.** `check_replay_parity.py` on the live dev database, read-only, first 3 replay
   days per tour, window 2026-04-01 to 2026-06-01:

   ```
   count targets checked 2152, max abs diff 0.0
   games rows checked 538, max abs diff 0.0
   ```

   The earlier run on the feat branch's code (12 days) gave 3824 and 1079 with the same zero differences. It is not
   repeated here.

4. **A pre-merge evaluation copy holds rows this grader does not use.** `/root/picks.tennis-cp4.db` (written 23:01 CDT on
   2026-10-20) holds 5 distribution rows under `tennis-counts/2026-10-20` for WTA ESPN 185542, locked 04:01:26 UTC with a
   05:00 UTC start. Those rows came from the feat branch's freeze, which ran without dev's gate. The copy was inspected
   read-only and not graded. It is not evidence.

## Verification

- `backend/test_tennis_prospective_grade.py`: 21 tests, all pass. They cover the PIT and coverage math on a known
  distribution (hand values), the upper-tail shares on an exact dyadic PMF, the 200-match refusal boundary, the look-ahead
  guard, locks after the start, a missing lock or research table, an orphan distribution row, and an end-to-end total-games
  grade. Three deliberate mutations of the grader (the guard, the prospective filter, the refusal boundary) each made tests
  fail.
- `backend/test_tennis_count_distributions.py` (16 tests) and `backend/test_tennis_model_api_parity.py` (8 tests, pytest
  style, so `unittest` collects none of them): all pass under pytest. The three files together: 45 passed.
- The lock path (`tennis_count_distributions.py`, `tennis_lock_sweep.py`, `scoreboard_store.py`,
  `tennis_daily_projections.py`) and both existing test files are byte-identical to `dev`. This branch only adds files.

## Provenance from `feat/tennis-cp4-distribution-locks-2026-10-20`

- Cherry-picked with `-x`, in order: 8fefcbd7, 1b4c81f4 (this file, rewritten here), 0b8c203c, dacee9ff, efb0481f, 95b50994,
  18c5aece, 14c28ce3, f997e330, 04bf2e11, e1231b54, 5110cc2b, 5347c5ac, 6f834f07, 940b4383, b60796a5.
- Partly ported: 910259f2, only `backend/cp4_evidence_assembly.py`.
- Not ported:
  - 982b9b9f and be3a9a47: the lock path, which dev's gated version replaces.
  - `prospective_lock_stage.py` from 910259f2: it runs the lock sweep on a copy. Dev's sweep now freezes only in a database
    named `picks.dev.db`, so on a copy it would freeze nothing.
  - 705be6a2: a docs commit. Its first-lock record describes the ungated freeze, and its statement that the live database has
    29 locks and no distribution table is out of date.
- Changes made here: a missing table counts as zero; the look-ahead guard; the orphan-row count and the source-table
  presence in the output; the grader test moved from `research/` to `backend/`; test fixtures carry `model_day`.

## What CP4 still needs

1. Frozen rows. None exist yet. The first one comes with the next new tennis lock on dev.
2. Verified aces and double faults. That needs a scheduled collector and an assembly step into the evaluation copy. Neither
   exists.
3. Micah's decisions: the KS gate at small n (finding 2), and whether a history that stops in June is acceptable for CP4
   (finding 1).
4. A frozen reference (C0 for counts, direct format for total games) and runner-up. Without them the grader cannot emit the
   selection verdicts prospectively.
