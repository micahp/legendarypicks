# MLB identity rebuild — rescued WIP, 2 of 4 tests failing

Recovered 2026-08-04 from `/root/lp-v0613-backend-data`, where all three files sat
**untracked** on a merged branch whose worktree was about to be deleted. 1,407 lines
that would have gone with it. This is the second time uncommitted work has been found
running or sitting in a delegated worktree; `git status` after any delegated session.

## What it is

A hash-bound, three-stage MLB identity rebuild:

- `plan_mlb_identity_rebuild.py` — **read-only, no apply mode.** Opens both databases
  read-only and emits a hash-bound plan. A crosswalk change is proposed only when the
  candidate name has one exact official MLB People match *and* a second, already-clean
  reference spine independently carries the same name/MLBAM pair.
- `apply_mlb_identity_rebuild_copy.py` — applies a plan **to an isolated copy only**,
  guarded by `RebuildInvariantError` on any copy/plan/schema/data invariant failure.
- `test_mlb_identity_rebuild.py` — 4 tests.

The shape is right: refuses rather than guesses, corroborates against a second source,
never touches the database it read. It is the closest thing this repo has to a fix for
the MLB spine gap — `players.team` 89% blank, `players.position` **100%** blank across
all 2,750 MLB players (`docs/LEAGUE-STAT-GAPS.md`).

## Why it is not wired up

**It does not pass its own tests.** As rescued:

```
FAILED test_copy_transaction_preserves_props_and_routes_logs_by_key
    assert changes["props_repointed"] == 1   ->  0 != 1
FAILED test_plan_requires_official_and_clean_reference_agreement
2 failed, 2 passed
```

Whoever picks this up starts by reading those two tests, not the scripts. They are the
author's own statement of what the tool was supposed to do and the record of where they
stopped. Do not run either script against `picks.db` until both are green — the planner
is read-only so it is safe to explore with, the applier is not something to trust on a
failing suite.

Run: `backend/venv/bin/python -m pytest backend/scripts/test_mlb_identity_rebuild.py -q`
