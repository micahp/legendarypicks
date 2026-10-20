# CP4: frozen lock distributions and the prospective grader (2026-10-20)

- **Status: infrastructure only. CP4 is open.** No prospective outcome exists yet, so no cell has a verdict.
  Every number below is either a copy-database fact, a parity check against the replays, or a synthetic test.
  None of it is evidence for the two ADOPT_CANDIDATEs.
- **Branch:** `feat/tennis-cp4-distribution-locks-2026-10-20` (from `dev`). Not merged to `dev`, not deployed, no write to
  the live dev or prod database. Model version written by the lock path: `tennis-counts/2026-10-20`.
- **Entry points:** `run_prospective_grade.py` (grader) and `check_replay_parity.py` (replay parity on real rows).
  Tests: `test_run_prospective_grade.py` here and `backend/test_tennis_count_distributions.py`.

## What is frozen

Each lock created by the sweep after this change also writes `tennis_model_lock_distributions` (one row per cell and side).
Only best-of-three matches with a mapped surface and both players mapped to Sackmann ids get rows.

| cell | side | variant | stored |
| --- | --- | --- | --- |
| aces | home, away | P1 Gamma-Poisson (`tennis_props_rate_backtest`, unchanged) | exact parameters (family, mean, shape, rate, extra mean variance, exposure mean and variance, event rate mean) and the PMF from 0, trimmed where a probability is below 1e-12 (trimmed mass stored) |
| double_faults | home, away | P1 Gamma-Poisson | as aces |
| total_games | match | direct surface plus competitiveness (`tennis_total_games_backtest`, unchanged) | the PMF over its full support (12 to 39), Elo gap, competitiveness bucket, format, surface, model day, histogram source |

The rows are immutable (update and delete triggers). The projection JSON is unchanged, so the Bovada `_frozenOdds` written by
dev stays where it was; the distributions sit in their own table beside it.

**Reconstruction.** `count_pmf_from_parameters` is the only route from a stored count row to a PMF, so the frozen PMF is
rederivable from its parameters. A test reads a stored row and checks that the rederived PMF equals the stored one exactly.

## What is not frozen

- **The 28 existing locks** (2026-10-15 to 2026-10-20) have no distributions. They are counted as
  `locks_no_distribution_frozen` and never backfilled, since that would manufacture a pre-game forecast.
- **ATP Grand Slam matches** are best of five; neither candidate covers them.
- **Matches without a mapped surface or without Sackmann ids** get no rows (skip reasons are counted).
- **Reference distributions** (C0 for counts, `direct_format` for total games) are not frozen. The "clearly beats the
  reference" leg of the RESULTS verdict therefore cannot be computed prospectively, and the grader never emits ADOPT.
- **The point simulator** is not a candidate and is not frozen.
- **Clustered bootstrap intervals** are not computed.

## Verification

**Unit and integration tests (final run, after the merge with `origin/dev`):**

```
$ cd backend && python3 -m pytest -q test_tennis_count_distributions.py test_tennis_bovada_odds.py ...
161 passed in 35.36s
$ cd research/tennis/cp4-2026-10-20 && python3 -m pytest -q test_run_prospective_grade.py
6 passed in 1.91s
```

The distribution tests cover: exact parity with the props and total-games replays row by row on a synthetic
database; freeze round trip; immutability; the look-ahead guard; and the sweep. The sweep cases are a projectable
match (five rows plus `_frozenOdds` present), an unmapped identity (lock written, no rows), a match without a projection
(no lock, no rows), a failing candidate (lock still written, failure counted and logged), an old lock (counted, not
backfilled), and an idempotent schema.

**Replay parity on real rows** (`check_replay_parity.py`, read-only on a copy of `picks.dev.db`, window 2026-04-01 to
2026-06-01, first 12 replay days per tour):

```
count targets checked 3824, max abs diff 0.0
games rows checked 1079, max abs diff 0.0
EXIT=0
```

Output of the committed `check_replay_parity.py` (exit 0, 12 replay days per tour). An earlier scratch run of the same
checks gave identical figures.

The PMF rebuilt at each match's day scores exactly as the replay recorded it, to the last printed digit.
The count-PMF cap is outcome-free, and the replay's own leakage check (zero flags on scored rows) is what makes that
equivalent. The games format is inferred from the event at lock time. The replay derives it from the score, and the two
agree on all 1,079 window records, Grand Slams included.

**Live-path smoke run on a throwaway copy** (not evidence): one WTA match (ESPN 185542, start 2026-10-21 05:00 UTC) locked
at 04:40 UTC from the real projection path. Five rows were written, every PMF sums to 1 within 1e-12, and the lock kept its
`_frozenOdds` key (null, since no matching quote existed). A history walk took 5 to 12 seconds per model day on the copy.

## Grader output on the copy (`run_prospective_grade.py`)

The copy holds the 28 existing locks and no distribution rows, so nothing is graded:

| cell | n matches | verdict |
| --- | --- | --- |
| ATP aces | 0 | INSUFFICIENT_PROSPECTIVE_DATA |
| ATP double faults | 0 | INSUFFICIENT_PROSPECTIVE_DATA (no settled source) |
| ATP total games | 0 | INSUFFICIENT_PROSPECTIVE_DATA |
| WTA aces | 0 | INSUFFICIENT_PROSPECTIVE_DATA |
| WTA double faults | 0 | INSUFFICIENT_PROSPECTIVE_DATA (no settled source) |
| WTA total games | 0 | INSUFFICIENT_PROSPECTIVE_DATA |

Accounting: 28 locks in total, 0 with a frozen distribution, 28 with none, 0 excluded for timing. A cell below 200 graded
matches prints only its n and the verdict. No metric is printed for it.

## Limits that bind before any cell can be graded

1. **Outcome capture is the blocker, not the freeze.**
   - *Double faults:* no settled source exists anywhere in the pipeline. Scoreboard snapshots do not carry them, and
     `tennis_match_stats_overrides` holds aces only. The double-fault cells cannot be graded until a source is added.
   - *Aces:* the override table holds 9 rows in total, all historical and verified by hand. Aces can only be graded for a
     new match if someone verifies and records it.
   - *Total games:* read from the final scoreboard payload's set games, as `grade_tennis_model` reads them. The payload
     does not show the format, so a match tiebreak in place of a third set would not be detected.
   - *Sackmann* (the replay source) ends at 2026-06-01 for ATP and 2026-06-02 for WTA in this copy, so it cannot grade
     October matches.
2. **The KS gate cannot pass at 200 matches, even for a perfectly calibrated model.** The randomized PIT is exactly uniform
   under calibration, and the expected Kolmogorov distance of a uniform sample of size m is about 0.87 divided by the
   square root of m. At 200 matches (400 player targets) that is about 0.044 against a gate of 0.02. At about 1,000 matches
   (2,000 targets) it is about 0.019. The gate was fixed before any run and is not changed here, since changing it needs
   its own pre-registration. The 100 and 250 match windows in the brief cannot pass it.
3. **Date granularity.** Like the replays, the history is keyed on `tourney_date`, not the match day. A row from the same
   tournament dated earlier is used even if it was played after the match. Live locks only see results already in the
   database, so this is not look-ahead in production. It would be if the sweep were replayed over a database holding
   later results. The guard raises on any source row dated on or after the model day.
4. **Cost.** The history walk runs once per (league, model day) that receives a new lock, and takes 5 to 12 seconds on the
   copy. The sweep runs on the ingest timer, so the first lock of each match day pays this once.
5. **No verdict is produced.** The grader does not emit ADOPT, INSUFFICIENT_DATA as a model verdict, or INCONCLUSIVE. Below
   200 matches it emits INSUFFICIENT_PROSPECTIVE_DATA. At or above 200 it emits CALIBRATION_GATES_PASS or
   CALIBRATION_GATES_FAIL, and the reference leg is recorded as not computed.

## What CP4 still needs

- A settled double-fault source, and a verified aces capture for new matches, both feeding the grader's outcome reader.
- Prospective locks made after this commit reaching the window the brief names. The copy holds none of them.
- A decision, by Micah, on the KS gate at window sizes below about 1,000 matches. The gate is not changed here.
