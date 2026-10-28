# Dev lineage reconciliation for the MLS cutover (2026-10-28)

The running dev checkout (`/root/legendarypicks`, branch `dev`) is what the production roster job executes, from its
working tree. `origin/dev` is the remote. They differ. This record measures the difference and says what the
integration did with each part. The running checkout was not modified.

## Measured state

| Item | Measured value |
|---|---|
| Running checkout HEAD | `79e8e05d` |
| Commits on the running checkout, not on `origin/dev` | 26 |
| Commits on `origin/dev`, not on the running checkout | 2: `382f5ffe` and `1d35e47e` (NFL blocked-kick period and outcome-weight fixes) |
| Uncommitted files in the running checkout that touch identity | 3: `backend/history_refresh_common.py`, `backend/run_mlb_daily_history_ingest.py`, `backend/test_history_refresh_common.py` (the backup-retention edits production runs) |
| Other uncommitted files in the running checkout | 27 paths: NFL, UI, research, data directories, and an untracked `picks.db` at the repo root |

## What the integration did

Integration worktree: `/root/lp-mls-integrate`, branch `integrate/mls-cutover-on-dev`, created from `79e8e05d`, the
commit production builds on. No merge into `origin/dev`, and no change to the running checkout.

1. **Backup retention preserved.** The three identity-relevant uncommitted files were saved as a patch from the running
   checkout and applied to the integration worktree, then committed as `293c570a`. Production keeps running that code,
   and it is now in history.
2. **MLS cutover applied on top, without a merge.** Seventeen commits from `feat/mls-cutover-2026-10-28` (which is based
   on `origin/dev`) were cherry-picked in order. They applied without conflict. The identity, MLS, backup and spine tests
   pass on the result: 166 tests in the first run after the cherry-picks, before the later commits.
3. **Later commits** on the integration branch: membership evidence and fail-closed historical games (`6b5d606a`),
   current-club consumers and the inventory (`0b2c77dc`), and the closure report (see its own section).

## What was not included, and why

- **The two `origin/dev` commits** (`382f5ffe`, `1d35e47e`) are NFL blocked-kick fixes. They do not touch identity code, and
  the MLS work does not depend on them. Whether to take them belongs to the merge to `dev`, which is a separate decision.
- **The 27 other uncommitted files** in the running checkout are not identity work. They stay where they are, unchanged.
- **The untracked `picks.db`** at the repo root is not part of identity. It is left untouched.

## Conditions before any merge into `dev`

1. Decide on the two `origin/dev` NFL commits. Either take them into the integration branch first, or record that they
   stay separate.
2. Decide what happens to the 27 uncommitted paths in the running checkout. They are not part of this change.
3. Merge only with the running checkout's own owner's agreement, because production runs that checkout's working tree.
