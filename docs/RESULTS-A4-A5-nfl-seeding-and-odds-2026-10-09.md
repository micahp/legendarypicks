# A4 and A5 results: NFL seeding, validation and playoff odds (version 1)

Written 2026-10-09. Rules in `SPEC-nfl-team-ratings-playoff-odds-2026-10-09.md` sections 5 and 6.
Model: the version 1 scores-only ratings, frozen configuration (half-life 6, cap 14, sigma 13.295),
as in `RESULTS-A3-nfl-backtest-2026-10-09.md`.

## A4: seeding and tiebreakers

Implemented: `backend/nfl_standings.py`, `backend/nfl_seeding.py`, `backend/nfl_bracket_check.py`.
Tests: 10 standings, 5 seeding, 4 bracket-check tests. All pass. A mutation that removed the
head-to-head criterion fails the seeding test.

**Validation, and what it does and does not show.** Published seed numbers are not in the database.
So the check is a consequence test: seeds computed from regular-season results alone must produce
the wild-card pairings (2v7, 3v6, 4v5) and the divisional pairings (1 seed against the lowest
remaining seed, the other two together, from the actual wild-card winners) that were played.

| Season | AFC seeds 1-7 | NFC seeds 1-7 | Wild-card pairs | Divisional pairs | Coin flips |
|---|---|---|---|---|---|
| 2024 | KC BUF BAL HOU LAC PIT DEN | DET PHI TB LAR MIN WSH GB | match | match | 0 |
| 2025 | DEN NE JAX PIT HOU BUF LAC | SEA CHI PHI CAR LAR SF GB | match | match | 0 |

The 2024 seeds agree with my recollection of that season's final standings. That recollection is not
a source. The spec's requirement was 28 of 28 against published seeds; this check is weaker, because
two different seedings can produce the same pairings.

**Known deviations (marked in `nfl_seeding.py`, to verify against the NFL Record & Fact Book):**
- The multi-team tiebreaker is simplified. The official procedure eliminates teams one at a time.
- The wild-card step that first reduces a tied group to the highest-ranked team of each division is
  not implemented.
- The Fact Book version is not cited yet.

## A5: simulation and playoff odds

Implemented: `backend/nfl_sim.py`, `backend/nfl_sim_backtest.py`. Tests: 13 simulation tests, including
a regression test for a bug found and fixed in this session (commit `f9267eb`: a scored game after
the last complete week was silently dropped from the simulation).

### Sanity checks (spec 6.3), current 2026 state, 20,000 runs, cold

- Sum of `p_playoffs` over all teams: 14.000 (required 14, within 0.01). Pass.
- For each conference and seed k, `p_seed_k` sums to 1.000. Pass.
- Stability: a second seed (20,000 runs) moves no team's `p_playoffs` by more than 0.0085
  (largest: CLE). The spec limit is 0.015. Pass.
- Runtime: about 115 seconds for 20,000 cold runs on this box. The spec limit is 5 minutes. Pass.
- Coin flips needed inside the tiebreakers: 7 in one run and 4 in the other. They are counted and
  reported, not hidden.

### Current odds, 2026, through the state of the data (weeks 1-4 complete, plus TB at DAL)

| Team | Conf | P(playoffs) | P(division) | P(bye) | Mean wins | 10th-90th pct wins |
|---|---|---|---|---|---|---|
| JAX | AFC | 0.993 | 0.959 | 0.514 | 13.2 | 11-15 |
| SF | NFC | 0.992 | 0.866 | 0.544 | 13.4 | 11-15 |
| MIN | NFC | 0.967 | 0.584 | 0.238 | 12.3 | 10-14 |
| KC | AFC | 0.953 | 0.759 | 0.293 | 12.2 | 10-14 |
| CHI | NFC | 0.946 | 0.396 | 0.141 | 11.9 | 10-14 |
| BUF | AFC | 0.767 | 0.528 | 0.052 | 10.5 | 8-13 |
| NYG | NFC | 0.715 | 0.663 | 0.015 | 9.6 | 7-12 |

The full table of 32 teams is in `backend/data/sim_2026_cold_seed1.json` (not committed).
This is a model's view from ratings built on the data so far. It is not a forecast I would bet on
without the market comparison.

### Backtest, hot versus cold (spec 5.1: keep whichever grades better)

Grading: mean Brier of `p_playoffs` against actual playoff membership, over 13 cutoffs (after week
5 through after week 17), 2,000 runs per cutoff. Naive baseline (14 of 32 teams everywhere): 0.246.

| Season | Role | Cold (k = 0) | Hot (k = 0.05) | Better |
|---|---|---|---|---|
| 2024 | tuning | 0.0620 | 0.0631 | cold |
| 2025 | second look | 0.1244 | 0.1215 | hot |

The rule chose cold on 2024. On 2025 hot is slightly better. Both differences are about 0.003 Brier,
the 2024 and 2025 gaps point in opposite directions, and the per-cutoff differences are small. The
honest reading: no reliable preference between hot and cold has been shown. The frozen choice is cold,
as the rule requires, and it should be revisited with more seasons.

Both seasons beat the naive baseline by a wide margin. 2025 is much harder to forecast than 2024 in
the middle of the season: cutoff Brier was 0.15 to 0.19 in 2025 at weeks 5 to 11, against 0.06 to 0.10
in 2024 over the same weeks.

## What is not done, and what the numbers do not show

- **k was not tuned to the rating spread.** Spec 5.1 says to tune k so simulated rating spread matches
  real week-to-week rating changes in 2024-2025. Only k = 0 and k = 0.05 were compared.
- **The 2025 result is a second look.** Version 1 was already scored on 2025 in A3. The
  simulation comparison reuses 2025 and is not a clean holdout.
- **Seeding is validated by consequence, not by published seeds** (see A4).
- **Odds are only as good as the ratings.** Version 1 uses scores only. The market is better (A3),
  and the simulation inherits that gap.
- **The weekly job, the `playoff_odds` writes, grading, and the movers JSON are A6.** Nothing in A5
  writes to the database yet.
