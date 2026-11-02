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
| 12 | Broad repository text searches for SLC layer and gate terms. The returned output included result-bearing 2026 material from research Markdown, CSV/JSON/JSONL files; the output was truncated, so a complete surfaced-path inventory is unavailable. No 2026 table query or simulation was run, and the surfaced values were not used. | `rg` over `docs/research` and `scripts/nfl_sequence` in `/root/lp-slc-player-workload-2026-10-30` | Search output on 2026-11-02 | Accidental exposure to sealed result text; not used for fitting, tuning, selection, or evaluation. Subsequent data queries are explicitly bounded through 2025. |
| 13 | Manager, 2026-11-02, read-only reconciliation under D1 of the ARI-DAL player-tail audit numbers. Opening `pbp_2026.csv.gz` observed rows (2026 REG) to recompute the observed figures; reading the audit review `docs/research/ari-dal-player-tail-audit-v5-2026-10-30/REVIEW.md` for the cited definitions and values. Freeze commit `9bbb2af6` precedes this access. No value is used for fitting, tuning, features, thresholds or arm ranking. Results go only to the D1 reconciliation table. | observed rows and audit text; no simulation output used for any decision |
| 14 | Manager, 2026-11-02, playbook manifest check under Q1. Read the enabled-layer flags, layer hashes, execution counters and top-level key names of four 2026 Week 8 run outputs: `docs/research/slc-week8-recoveries-2026-10-31/LAC_LA/source-yardage-filter-f1c82e55/seed-196/worker.json`, `docs/research/slc-week8-player-workload-10k-2026-10-30/IND_JAX/blocker-replays/original-source-plus-fix-full-stack-serial/seed-4382.json`, `docs/research/slc-week8-player-workload-10k-2026-10-30/IND_JAX/run-header.json`, and `docs/research/SLC-ALL-LAYERS-ENGINE-SMOKE-2026_08_CAR_GB-2026-10-29.json`. No game outcome, boxscore, summary or simulation value was printed or used. The reads happened before this entry was written; the entry is made after them. | configuration and count fields only; not used for fitting, tuning, features, thresholds or arm ranking | Gridiron LP worktree, read-only | Outside D1's reconciliation purpose. No further 2026 output reads for this check. |

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

## 5. 2026-11-02: research playbook publication and inspection (`research/nfl-team-season-playbooks-2026-10-27`)

| # | what | read or produced | exact location | status |
|---|---|---|---|---|
| 15 | Commit `ea4e227` added `data/playbooks/research-2026-10-27-rev2/shotgun_null_plays.csv`. The file has 139 rows with `season` 2026, and 14, 97, 27 and 55 rows for 2022 to 2025. The branch was pushed to origin (`0c1541c..3db3e0a`), so the 2026 rows were public on GitHub until the removal below. | published to a public remote | origin `research/nfl-team-season-playbooks-2026-10-27`; quarantined copy in `/root/gridiron-playbook-builds/quarantine/`, sha256 `200b41f4aa440af1fe398dbf047878a4fb9f23963fe318e026ce216d88a0456a` | exposure; not used for fitting, tuning, selection or evaluation |
| 16 | Removed the file from the tip in `c5dab46` (pushed). Then, on the owner's instruction to remove it from history, the branch was rewritten to drop the file from `ea4e227`, `fbe0829`, `36b17cf` and `3db3e0a`, the removal commit was dropped, and the branch was force-pushed with a lease to `c63c8e9` (old tip `c5dab46`). Old commits may stay reachable by SHA on GitHub until its own cleanup; this record cannot confirm that. | shared research branch rewritten; no other branch touched | origin tip `c63c8e9`; pre-rewrite bundle `/root/gridiron-playbook-builds/quarantine/research-nfl-season-playbooks-pre-rewrite-c5dab46.bundle` (contains the file) | open: the bundle holds the 2026 rows; keep or delete is the owner's decision |
| 17 | Not from this session. `data/playbooks/research-2026-10-27-rev3/shotgun_null_plays.csv` was added by commit `1c35f83` (2026-10-27) and has 128 rows with `season` 2026. It is still in the tracked tree at `c63c8e9`. Commit `1c35f83` is reachable from `origin/main` and from `origin/research/nfl-team-season-playbooks-2026-10-27`, so the rows are on the default branch as well. | tracked on the default branch and on the research branch | `origin/main`; research branch tip `c63c8e9` | removed from `origin/main` by commit `096454b` on 2026-11-02, under the owner's approval; the file is no longer tracked on `main`, but `1c35f83` stays in `main`'s history. Still tracked on the research branch (tip `87e6c31`); the research-branch removal is not approved and is open |
| 18 | Inspection, 2026-11-02, by the research agent. Counted the first field (`season`) of each CSV. Counted `"season"` values and `2026` substrings in the two 2025 reproduction profiles and `gate1_report.json`, and listed key paths only. No 2026 row or play description was displayed. Classification checks ran on 2022 to 2024 rows only. Findings: the 2025 profiles carry season 2025 only (CHI 2,119 and NE 1,984 `season` fields, all 2025). Their `2026` substrings are `old_game_id` dates from 2025-season games and key or path names. `sampling_controls.observed_2026_pre_game` is `{enabled: false, purpose: "descriptive comparison only"}`. | read: season column, counts and key paths; 2026 values not displayed | the CSVs above; `data/playbooks/research-2026-10-28-gate1-reproduction/` | counts only |
| 19 | Rights for the 2025 profiles and the CSV: the user confirmed on 2026-11-02 that the rights were verified. The agent did not re-check. A fetch of FTN's data page returned HTTP 403. nflverse-data's README labels its data CC-BY-4.0. The builder cites CC-BY-SA-4.0 for FTN data with the credit "FTN Data via nflverse". | rights review by the owner | `pipeline/build_playbooks.py` (source fields) | user-confirmed; agent did not re-verify |

Quarantine: the directory is mode 0700 and the copies are mode 0400. Row 16 is an open decision. Row 17 is resolved on
`main` (`096454b`) and open on the research branch.
