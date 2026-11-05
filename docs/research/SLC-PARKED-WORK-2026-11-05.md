# Parked work (draft)

Plan for the work that is not finished, kept here so it can be picked up later. Nothing in this PR is for merge.
Done work is pushed to slc-v2.

## NFL, SLC v2

- Ablation (A control, B lineups, C snap counts, D kicker table): 255 of 484 batches done at 02:44 UTC, 0 failed. When it
  completes: score the four arms, write up on slc-v2, log exposure row 27, push.
- 2025 realism run: armed to start after the ablation. Status and checks: docs/research/SLC-2025-REPLAY-RUN-PREP-2026-11-05.md
  on slc-v2.
- Gate scorer: not built. Metrics 1 to 13 against the extended realism draft (pi's file, not reviewed in this repo).
- Injury designations: excluded from the replays by default. Restoring them needs a timestamped source.
- Thursday JAX-BAL: the pregame capture must be taken before 23:45 UTC on 2026-11-05. The published depth chart still lists
  Huntley first, and Fagnano was announced as the starter. The fast host's database is one week-8 game short.
- Readiness manifest: it says injury reports are not used, but the code uses them when rows exist. Correct the manifest.

## Team codes, non-NFL (parked)

- Commit ef9e8346 (app-wide team-code interface) is in slc-v2's history and touches 46 non-NFL files. Option: revert the
  non-NFL usage on slc-v2 and carry that work here as a draft.
- NHL split codes (NJ and NJD, LA and LAK, and others): migration and the canonical vocabulary decision.
- ESPN projections backfill for the LAR and WSH rows: needs ESPN calls and database writes. Not planned.
- FCS codes (101) and GDL: registration decision.
- Esports and World Cup codes: outside the registry.

## Fantasy projections: ESPN vs Yahoo

- Question: are ESPN and Yahoo fantasy projections the same?
- Not testable yet. The repo has no Yahoo projection data, code or credentials. ESPN weekly projections are stored
  (espn-weekly, 15,540 rows, 2025 and 2026).
- Plan once a Yahoo export or API access exists: match players and weeks, compare the stat projections (carries, targets,
  receptions, yards, touchdowns), and report the differences and coverage. Use the stored ESPN rows only, with no new ESPN
  requests. The owner does not want ESPN used for fantasy work.

## Owner decisions open

1. Injury designations in the replays (current default: excluded).
2. Non-NFL split: revert on slc-v2 and carry here, or leave as is.
3. NHL vocabulary and migration.
4. FCS and GDL registration.
5. Yahoo data source for the projection comparison.
