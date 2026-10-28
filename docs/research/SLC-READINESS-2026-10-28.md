# SLC readiness, 2026-10-28

Model: SLC v1 (`slc_v1_incomplete`). Branch `research/slc-model-2026-10-28`. Coaching and physical movement are excluded.
Nothing is merged or deployed. The 10,000-seed batch has not been run.

Two readiness results are kept apart. The engine answers whether SLC completes games. The evaluation answers whether a game
can be scored as a genuine pregame prediction. They do not imply each other.

## Engine readiness: partial

Measured on exploratory replays (2024 inputs, 2010-2023 play-call fit). Nothing here is a predictive result.

| Check | Result |
|---|---|
| Games run | 9 games: one game with 40 seeds, eight games with 10 seeds each (120 seeds) |
| Errors | 0 |
| Completed games | 120 of 120 (118 in regulation, 2 in overtime) |
| Unsupported rules recorded | 0 |
| Valid full games | 0, by design: every input is exploratory, so the engine records `pregame_statistical_game` |
| Same seed, single runner and batch runner | Agree on seed 1 of 2024 ARI-SF: 14-28, 149 decisions, `complete_regulation` |
| Play-call decisions | 17,609 decisions; 58.4% dropbacks of scrimmage plays; 9.1% kick decisions on the labelled fallback |
| Scoring against the 2024 regular season | 38 points per game (about 19 per team) against 45.8 actual (22.9 per team). A real gap; scoring frequency is not calibrated |
| `NoneType <=` TypeError (week 8 S0 seeds) | Not reproduced in 120 seeds on 9 games. Those seeds belong to other 2026 games and were not rerun |

Not yet connected: team offense and defense splits, playbooks, QB and role decisions, pre-event participant selection, and
the historical-splits model. These are listed in `SLC-INTEGRATION-LEDGER-2026-10-28.md`. Kick decisions still use the
historical share. The provisional post-score kickoff rule at Q1 and Q3 expiry still needs checking against the 2026 rulebook.

## Evaluation readiness: not ready

Cutoff-aware play-call fits, one per evaluation season:

| Evaluation season | Fit window | Artifact | Status |
|---|---|---|---|
| 2024 | 2010-2023 | `docs/research/SLC-PLAYCALL-ARTIFACT-FIT-2010-2023-v1.json` (sha256 `962bae5b...`) | Built, hash verified |
| 2025 | 2010-2024 | `docs/research/SLC-PLAYCALL-ARTIFACT-FIT-2010-2024-v1.json` (sha256 `07929a45...`) | Built, hash verified |
| 2026 | 2010-2025 | `docs/research/SLC-PLAYCALL-ARTIFACT-v1.json` (sha256 `27c02afd...`) | Committed, unchanged |

Input availability, 2026 Weeks 1-8, from `SLC-EVALUATION-ELIGIBILITY-2026-W1-8-2026-10-28.json`:

| Category | Games | Meaning |
|---|---|---|
| `backtest` | 0 | Every input has a verified availability time. None does yet |
| `exploratory_replay` | 28 (weeks 7 and 8) | Built and labelled `evaluation.verified=false`. Usable for replay, not for prediction scoring |
| `ineligible` | 93 (weeks 1-6) | Refused. The strict build refuses all 107 games of weeks 1-7 for no schedule version observed by the cutoff. The labelled build refuses all 93 weeks 1-6 games for no pregame QB1 in the depth data |

Why the inputs are not verified:

- **Schedule.** Every 2026 schedule row was first observed on 2026-10-27 22:39:53, a bulk import. A row observed then cannot be
  shown to have been public before an earlier kickoff. Week 8 kicks off after that time, so its observation is a
  pre-kickoff import, but still not a capture time. It fails the rule.
- **Depth charts.** `snapshot_at` is the nflverse artifact date (2026-07-27, 07-28, 10-05, 10-19). The loader stamps
  `ingested_at` when it imports, and neither is a publication time. The preseason snapshot has no starter QB1: its QB rows
  are ranked 2, 3 and 4. The first snapshot with a QB1 for all 32 teams is 2026-10-19, after Weeks 1-6.
- **2025.** No schedule versions and no depth rows exist for 2025. A 2025 pregame snapshot cannot be built from this database.
- **2024.** Historical depth is present (`nfl_hist_depth_charts`), but the schedule has no versions, so 2024 games use the
  current row. Eight of ten sampled 2024 games built; two were refused by existing checks (week 1 has no earlier depth week,
  and a team has no single RB1).

Usable pregame provenance, found in other sources:

- `nfl_line_snapshots` holds 2026 market captures with a capture time before kickoff for games in weeks 5 to 7. Week 8 has no
  captures yet. These timestamps are real capture times. They establish that a game was on the board and what
  the line was, but not its depth or roster. They are usable as a market comparison, not as a roster input.
- The ESPN cache holds no 2026 scoreboards, and `http-spend.jsonl` records fetch times without response content. Neither can
  prove what a scoreboard showed before kickoff.

## Holdout policy (changed 2026-10-28)

- A 2026 read needs an explicit game cutoff (`holdout.refuse_unless_cutoff`). An unbounded 2026 read or fit is refused.
- A snapshot backtest needs a verified availability time for every input, and refuses otherwise, listing each unverified
  input. `VERIFIED_CAPTURE_SOURCES` is empty: no source qualifies yet.
- Post-cutoff rows are excluded: a schedule version observed after the cutoff, and a depth row published after it.
- A cutoff on or after the game day is refused.
- Tests: `test_pregame_provenance.py`, `test_holdout_2026.py`, `test_slc_engine.py` and `test_pregame_snapshot.py` pass (40 tests).
  The full research suite runs 472 tests. One pre-existing error, `test_e3_observed_distributions`, is an import-path problem that appears only when
  the suite runs from the package directory. It is not caused by these changes.

## Open items, in order

1. A verified capture-time source for 2026 schedule and depth. Without it, no 2026 game is a backtest. Candidates to check: the
   publisher's own dated release files, or live captures taken before kickoff from now on. Week 8 kicks off after today's
   cutoff, so captures taken before its kickoff would make it prospective.
2. Week 8 prospective forecasts: only `exploratory_replay` inputs are available, so they cannot be scored as predictions until
   item 1 is met.
3. Static reference inputs. The reference loads kick, blocked-kick and safety pools that may not all be cut by the game's
   cutoff. For 2024 and 2025 evaluations these may include later-season outcomes. This is not yet verified, so every 2024 and
   2025 result is labelled exploratory.
4. Scoring calibration: about 38 simulated points per game against 45.8 actual in 2024.
5. Model comparisons against the existing NFL models on the same games, which need item 1 and a set of eligible games first.
