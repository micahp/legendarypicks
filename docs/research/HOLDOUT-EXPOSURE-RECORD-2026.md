# 2026 holdout exposure record

Rule (user, 2026-10-28): 2026 is the holdout for every model. No 2026 game outcome, player stat, tracking row, simulation
output or mixed-season artifact may be used for fitting, tuning, selection or evaluation. No 2026 projection is run as part
of the integration work. Any future forward projection needs an explicit prospective protocol first.

This record lists each 2026 access that the work can identify. Entries are not removed when a later check passes.

## 1. This session (2026-10-28, research/lp-event-phase1-2026-10-28)

| # | what | read or produced | exact location | status |
|---|---|---|---|---|
| 1 | Schedule listing of 2026 regular-season games for the remaining-game list | read: game id, week, date, time, teams (165 dated after 2026-10-28, of 272). No score column was selected. The schema print showed column names only. | `nfl_schedule` in `/root/legendarypicks/backend/data/picks.dev.db` | schedule metadata, not outcomes |
| 2 | One-seed forward projection, `2026_08_CAR_GB`, as of 2026-10-28T13:45:52Z | produced: 1 valid simulated game. Read: the 2026 schedule row, the 2026 depth-chart rows at the cutoff, and the 2022 to 2025 reference. The v1 comparison was disabled for this run. | `/tmp/claude-0/-root/4a715766-ff4b-4980-99e5-dc209eaac7d4/scratchpad/smoke/2026_08_CAR_GB.json` and `.seeds.jsonl` | 2026 simulation output, not evaluated. Kept as infrastructure evidence only. |
| 3 | Resume check on the same game at the same cutoff, to 2 seeds | produced: seed 2 and its ledger row | same folder | same as 2 |
| 4 | 100-seed timing run on `2026_08_CAR_GB` | produced: 99 valid games, 1 blocked before regulation. Output not opened after the run. | `/tmp/claude-0/-root/4a715766-ff4b-4980-99e5-dc209eaac7d4/scratchpad/timing/timing_100.json` | 2026 simulation output, not evaluated. Run before the integration instruction, and it should have been refused. Recorded here. |
| 5 | `json.load` of the whole `data/playbooks/NE-2025.json` (Gridiron repo) to list its keys | read into memory: the full file, including a `pregame_2026_comparison` block. Printed: top-level keys, section keys, and a count of the string "2026" (11,315). No 2026 value was printed. | `/root/gridiron-playbooks-research/data/playbooks/NE-2025.json` | exposure to the block's content in memory. Not used. |
| 6 | Committed 2026 fixture `docs/fixtures/pregame/game-kc-sea-seed1-full-depth.json` (week 7 KC at SEA; a pregame snapshot and a simulated game record) | read into memory on every full-suite run this session, through `test_run_pinned_validity.py` and `test_pregame_snapshot.py`, until the tests were skipped | `docs/fixtures/pregame/` on this branch | a 2026 simulation output sitting in the repository. Its tests are now skipped. The file is not moved or deleted; that needs your decision. |
| 7 | Splits-branch results folder (`/tmp/claude-0/-root/4a715766-ff4b-4980-99e5-dc209eaac7d4/scratchpad/nfl-splits/results/`) | checked by name, size and timestamp only. `test2026.json` exists (2026-10-27 19:11). | that folder | not opened. See section 2. |
| 8 | Code reads of 2026 paths (`grep`, `git show` of `decision_model.py` and spec headings) | code and documentation only | `scripts/nfl_sequence/`, `origin/research/nfl-historical-splits-2026-10-27` | no 2026 data |
| 9 | Full `json.load` of the 14 tracked Gridiron playbooks at HEAD (`data/playbooks/<TEAM>-2025.json`), to compare each with a 2025-only rebuild and remove the 2026 keys. The `pregame_2026_comparison` block and the `pbp_2026_pre_game` source record were loaded into memory. Only key paths were printed: 0 differing paths for all 14 after the 2026 keys were removed. | in memory; no 2026 value printed or used | `/root/gridiron-playbooks-research/data/playbooks/` (HEAD, `research/nfl-team-season-playbooks-2026-10-27`) | exposure to block content in memory, not used. The block is removed from the working tree (uncommitted). |
| 10 | Scan of the staged 2025-only rebuild for strings containing "2026": paths and counts only. Found `old_game_id` values (2025-season games from 2025-09-04 to 2026-01-04), a `provenance_categories` label, and 56 `play_id` values equal to 2026 (play numbers). Every `season` field is 2025. The rebuild wrapper (`pipeline/build_2025_playbooks.py`) opens only the 2025 play-by-play and 2025 participation files. | staged rebuild in `/tmp/claude-0/-root/4a715766-ff4b-4980-99e5-dc209eaac7d4/scratchpad/playbooks-2025-staging` and the 32 installed `data/playbooks/*-2025.json` | Gridiron repo, uncommitted | 2025 data only. Recorded so the scan can be reproduced. |
| 11 | hermes2 (Gridiron agent, tmux `hermes2:0.0`) reports, in its own pane output, that its session opened 2026 aggregate report rows in `data/playbooks/research-2026-10-27-rev3/BUILD-REPORT.md` (2026-10-28 06:56 UTC), listed `bdb2026-prediction` and read its `SHA256SUMS.txt` (06:52 UTC), read 2023 training-file headers (06:59 UTC), and re-surfaced the same report rows at 12:58 UTC. Its pane also shows unrelated 2025 overtime excerpts surfaced by a broad search. | I read the pane capture that contains hermes2's own description. Its text says it did not repeat the row values; I did not see them. | hermes2's tmux pane (`hermes2:0.0`) | hermes2's own exposure list is still outstanding. This entry records what its pane reports, not an independent audit. |

No 2026 outcome was used in any fit, tuning, selection or evaluation in this session. Entries 2 to 4 produced 2026 simulation
output; none of it has been scored.

## 2. Earlier work, identified but not re-verified here

- Splits branch (`origin/research/nfl-historical-splits-2026-10-27`): `scripts/nfl_sequence/splits/decision_model.py` has a
  `test2026` stage that loads 2026 weeks 1 to 7 and writes `test2026.json`, and it refuses to run a second time. The file
  exists, so the one-time 2026 test of decision model v1 has been run. The spec calls it "the one test on 2026". The holdout
  for decision model v1 is spent. Its results are not used here.
- The same results folder holds `game_winner_comparison.json`, `gwc_run.log` and `s1_s2.json`, all dated 2026-10-27. Not opened.
  They may contain 2026 results and need the same audit.
- Code paths that read 2026 and may have run in earlier sessions. Whether they ran is not recorded on this branch.
  - the regime kickoff load (`KICKOFF_SEASONS` included 2026 until 2026-10-28)
  - `_baseline_v1` for a 2026 target (fit v1 on 2026 results and read 2026 game projections until 2026-10-28)
  - `run_pinned_validity.py` with its default `--target-season 2026` (the KC-SEA pinned validity runs)
  - `build_overtime_choice_model.py` (scores 2026 toss choices; it has not been run here)
  - `pregame_context.py` and `contextual_pool.py` with a 2026 cutoff (2026 prior-week scores)
  - `measure_kick_outcomes.py` section 2 (field goals across all seasons, until 2026-10-28)
- Part B and hermes2 exposure: recorded in `docs/research/PART-B-EVALUATION-DECISION-RECORD-2026-10-28.md`, section 8. Hermes2's own
  list is still outstanding.
- Week 8 frozen runs in `docs/research/nfl-availability/2026/`: not read in this session.

## 3. Guards added on 2026-10-28

Every path below now refuses a 2026 season before it reads any table:

- `holdout.py`: `HOLDOUT_SEASON` and `refuse_if_holdout`.
- `e1_drive.load` (2026 cutoff) and `e1_drive.load_seasons` (any season list containing 2026).
- `pregame_context._require_matchup`.
- `contextual_pool.build_source_ratings` (before any query).
- `pregame_snapshot.build` (after the schedule row is read, and before the snapshot is built).
- `replay_evaluation.forecast_from_batch` (scores a 2026 payload).
- `simulate_pregame_batch._baseline_v1` returns `unavailable` for 2026.
- `run_pinned_validity.py --target-season` refuses 2026 at parse time. Its default is now 2025.
- `build_overtime_choice_model.py` refuses before it reads its source CSV.
- `measure_kick_outcomes.py` section 2 is bounded to 2022 to 2025.

Tests: `scripts/nfl_sequence/test_holdout_2026.py` (negative tests for each guard, including a subprocess run of each command
line). Three tests that read committed 2026 fixtures are skipped, with the reason on each skip.

Synthetic fixtures in `test_pregame_context.py`, `test_pregame_snapshot.py` and `test_pregame_batch.py` moved from 2026 to
2025. The prior-season rows in `test_pregame_context.py` moved to 2024. These are temp-database fixtures, not real rows.

## 4. Decisions needed (not taken)

1. Quarantine or delete the committed 2026 fixture `docs/fixtures/pregame/game-kc-sea-seed1-full-depth.json` and the 2026 block
   in the Gridiron playbook JSON files. Neither is moved or deleted here.
2. Audit the splits results folder files (section 2) before any use of that folder.
3. Whether any earlier run read the paths listed in section 2. Check the run logs; this record cannot settle it.
4. Whether any model may use 2026 results from before a cutoff. Under the current rule, no.
