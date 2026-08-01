# Player-detail preservation failure — 2026-08-01

## Outcome

The managed worktree was returned safely to `dev`, but the player-detail work was
incorrectly reported as complete while later task-owned changes remained only in
`stash@{0}`. The files were preserved, so no source was lost, but active `dev`
did not contain the completed game-log labels, published-schedule venue markers,
phase-separated NFL logs, or the same-name ESPN news repair.

The recovery is isolated on `fix/recover-player-detail-wip`. The preservation
stash remains intact and still contains unrelated Props and esports work.

## What failed

1. A broad tracked-file stash was used to protect a dirty managed worktree before
   restoring its designated branch.
2. Two narrow slices were reconstructed and merged afterward.
3. The remaining task-owned stash hunks were not reconciled against the resulting
   `dev` history.
4. The handoff treated "preserved in a stash" as equivalent to "present and
   verified on dev."
5. The follow-up audit repeated that error by checking the new projection overlay
   rather than every player-detail surface changed during the session.

The safe checkout was not the defect. The defect was declaring completion without
a zero-unexplained-diff reconciliation of the preservation stash.

## Required preservation and recovery gate

A preservation stash is containment only. It is never completion evidence.

Before switching the managed worktree:

1. Record every tracked and untracked path.
2. Classify each path or hunk by task and owner; do not assume one file has one
   owner.
3. Move colliding untracked files to a named preservation directory with a
   manifest.
4. Prefer task-specific commits in isolated worktrees. Use a broad stash only
   when immediate containment is necessary.

Before claiming the task recovered or complete:

1. Diff the stash against its first parent to enumerate every preserved hunk.
2. Map every task-owned hunk to a recovered commit or an explicit exclusion.
3. Reconcile that map against the current candidate. Zero task-owned hunks may be
   unexplained.
4. Keep the stash until every unrelated owner confirms recovery.
5. Run an acceptance matrix over every changed user-visible surface, not only the
   motivating feature or newest component test.

For this incident the acceptance matrix includes both NFL game-log surfaces,
`Comp`/`Att`/`Car` labels, away-only `@` markers from the published schedule,
regular/postseason/preseason separation, the standalone ESPN News tab, the orange
league-rank card, and the mock-draft projection overlay.

## Recovery scope

Recovered task files:

- `backend/routers/players.py`
- `backend/test_nfl_news.py`
- `backend/test_players_profile_api.py`
- `components/Leagues/PlayerGameLog.tsx`
- `components/Leagues/StatRankCard.tsx`
- `pages/player/[id].tsx`

The separately authored caches are retained in
`backend/routers/nfl_offseason.py` and `backend/routers/nfl_mock_draft.py` at the
user's direction. Props, esports, and other stash paths remain excluded and
preserved.
