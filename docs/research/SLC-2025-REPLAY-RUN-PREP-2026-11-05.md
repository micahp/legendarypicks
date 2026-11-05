# SLC 2025 realism run: preparation status, 2026-11-05

Status: the 2025 run is armed to start when the ablation finishes. It has not started. Nothing here is a forecast.
2025 is a known validation fold, not an untouched test: the playcall artifact's penalty settings were chosen in an
evaluation that looked at 2025.

## Pushed to slc-v2

- 694ffd25: realism export behind `--export-plays` (schema lp-nfl-slc-realism-export-1).
- 2e73f6d0: replay builder uses a streak result only once it is available (kickoff + 10 h <= cutoff, target excluded).
- Next commit: the replay builder excludes game-week injury designations by default (`--include-injury-report` restores them).
- This report.

## Verified

1. Realism export: one game, two seeds, V1, V1.5 and V2, flag off and on, all six runs exit 0. Box scores are identical
   once the realism block is removed. Seed ledgers differ only by the realism block, which is stored inside each seed's box
   score. The V2 lineup summary is present; V1 and V1.5 have none.
2. Streak leak: 134 of the 272 games had at least one game still in progress at their cutoff (kickoff < cutoff < kickoff
   + 10 h). Their streak files changed once the availability rule was applied. The week 1 games show the clearest case:
   same-day games still being played were counted as results.
3. Injury designations: the 2025 play-by-play has no injury field. 1,628 of 48,771 plays mention an injury in their text;
   those are in-game events after kickoff. The injury file has no timestamps. `pre_event.py` applies the injury report to
   player eligibility whenever rows exist, and `eligible_players` excludes Out and Doubtful. The 2026 week 8 readiness
   manifest says the report is "captured but not used"; the code does not match that. For the locked CAR-GB forecast, no Out
   or Doubtful player is on the depth roster, so its eligibility is unchanged.
4. Replay inputs, injury designations excluded: 272 snapshots, 272 streak files, 0 refused. Manifest 0153def0630dddb9f00b,
   identical on this machine and on the fast host at /root/repro/r2025/replay-final-noinjury.

## Superseded inputs (do not use)

- /root/repro/r2025/replay-final: streak results used before they were available.
- /root/repro/r2025/replay-final-streakfix: streak fix, but game-week injury designations included.
- The 2025 smoke test and the flag identity test ran on pre-fix replay sets. They check the pipeline and the export, not the
  2025 numbers.

## 2025 run (armed, not started)

- 816 batches: 272 regular-season games x V1, V1.5, V2; 30 seeds per game; `--export-boxscores --export-plays`.
- Code: slc-v2 at 2e73f6d0, checked out on the fast host at /root/repro/final-2025 (detached, no uncommitted changes).
- Launch: when the ablation prints ARMS_ABL_DONE, estimated about 05:30 UTC. Game-major order. Resumable. Each finished batch
  is gzipped. Disk guard 600 MB.
- First game check: /root/repro/r2025/first-batch-check.txt, written when the first game's three arms finish.
- Estimated duration: about 15 hours.
- Known limits: V1.5 uses past-only 2025 evidence from games finished by the cutoff, and the outcome pool is 2022 to 2024.
  ACT rosters and kicker assignments are published after the season, so they can reflect game-day status (the draft's
  "retrospective roster" label). The seed ledger also carries the realism block, so ledgers are larger for flagged runs.

## Not done

- Ablation write-up and exposure row 27: after the ablation (255 of 484 batches done at 02:44 UTC, 0 failed).
- Gate scorer: not built. Metrics 1 to 13 still need writing against the extended realism draft (pi's file, not reviewed here).
- Thursday JAX-BAL pregame capture and forecast: not started. The capture has to be taken before 23:45 UTC on 2026-11-05.
- ESPN and Yahoo projection comparison: not testable on this box yet. The dev database holds ESPN weekly projections
  (espn-weekly, 15,540 rows, 2025 and 2026) and LP's own models for 2026 (marcel-lite, v2). The repo has no Yahoo projection
  data, code or credentials. A test needs a Yahoo projections export or API access. It would compare the stored ESPN rows,
  with no new ESPN requests.

## Non-NFL work (parked)

The app-wide team-code commit (ef9e8346) is already in slc-v2's history and touches 46 non-NFL files. No further non-NFL work
is planned. A later split would need a revert on slc-v2 and a separate draft PR.

## Decisions needed

1. Injury designations in the replays: excluded by default. Say if you want them restored.
2. Non-NFL split: revert the non-NFL usage on slc-v2 and move it to a draft PR, or leave as is.
3. Thursday capture before 23:45 UTC: go or no-go.
