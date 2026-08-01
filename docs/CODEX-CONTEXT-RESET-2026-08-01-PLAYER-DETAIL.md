# Codex context reset — player projections, venue markers, and managed worktree

Date: 2026-08-01
Repository: `/root/legendarypicks`
Managed branch: `dev`
Current committed checkpoint before this document update: `b4ffc81`
Remote checkpoint: `origin/dev` remains `3cc9487` (`v0.6.14`)

## Resume contract

- Read `/root/legendarypicks/AGENTS.md` before acting.
- `/root/legendarypicks` is the managed worktree used by frontend `:3096` and backend `:8096`.
- The managed worktree normally stays on `dev`.
- **Do not use `git switch` in this repository. Use `git checkout` for an authorized branch
  selection.** `git checkout dev` is allowed after conflicting WIP has been preserved.
- Feature work belongs in an isolated worktree created from `dev`.
- Do not use `git checkout -- <path>` to discard file changes without explicit approval.
- Do not run `npm`, `npx`, or `yarn`; call installed binaries directly.
- Managed services are externally owned. Do not start, stop, kill, or restart them.
- Do not push, deploy, move tags, or write production data without explicit authorization.
- Use `apply_patch` for file edits and explicit-path staging.

## Current branch and worktree state

The main worktree was safely returned from `feat/player-game-log-away-markers` to `dev`.
The feature branch still points at `3cc9487`; it was not reset or deleted.

Before the checkout, all tracked WIP was preserved in:

```text
stash@{0}: preserve-main-worktree-before-dev-switch-20260801
```

That stash contains 12 tracked files and must not be dropped until its owners confirm recovery:

- `backend/data/esports_team_logos.json`
- `backend/routers/nfl_mock_draft.py`
- `backend/routers/nfl_offseason.py`
- `backend/routers/players.py`
- `backend/routers/props.py`
- `backend/test_nfl_news.py`
- `backend/test_players_profile_api.py`
- `components/Leagues/PlayerGameLog.tsx`
- `components/Leagues/StatRankCard.tsx`
- `components/Props/PropChart.tsx`
- `pages/player/[id].tsx`
- `pages/props.tsx`

Two colliding untracked Reasonix test files were moved, not deleted, to:

```text
/root/lp-main-worktree-preserve-20260801/
```

The folder contains its own `README.md`. Numerous other untracked artifacts remain in the main
worktree and were intentionally left untouched. After returning to `dev`, the externally managed
esports writer modified `backend/data/esports_team_logos.json` again; do not assume that new diff
belongs to this task.

## Local `dev` history added in this work

```text
b4ffc81 docs: protect managed dev worktree branch
65a8568 fix(nfl): remove stale projection snapshot rows
37660d4 merge: verified player opponent venue markers
18f0b59 fix(player): preserve unknown game venue markers
f9f7555 merge: player overlay projections and season totals
a306386 feat(nfl): add player projections tab and season totals
3cc9487 chore(release): v0.6.14
```

Nothing has been pushed. `origin/dev` and tag `v0.6.14` remain at `3cc9487`.

## NFL player overlay delivered

`components/Leagues/PlayerDetailOverlay.tsx` now has four tabs:

- Overview
- Game log
- News
- Projections

The Projections tab contains ESPN Season Outlook followed by the 2026 projection table. Overview
retains the previous research sections and adds the published prior-season totals table.

The data/API contract includes:

- completion percentage
- sacks
- fumbles and fumbles lost
- passing, rushing, and receiving first downs for published actual totals
- ESPN Total QBR
- passer rating, separately labeled `RTG`
- adjusted QBR in the API contract
- position-specific counting stats and LP full-PPR points

Projection first downs remain null because ESPN's fantasy projection extension IDs were measured as
position-dependent and could not be labeled honestly. Actual first downs use the verified published
prior-season IDs. Total QBR is never substituted with passer rating.

## Projection publication and DEV database state

The authorized DEV ingest was run against:

```text
/root/legendarypicks/backend/data/picks.dev.db
```

Pre-ingest backup:

```text
/root/lp-db-backups/picks.dev.before-overlay-ingest-20260801.db
sha256 1131d7cfbbcd33b83791299d952e269fe898fd95075f4c859bb86f8e7b8b82a7
```

Final verified 2026 publication:

- 11,515 rows
- one projection payload checksum
- 483 rows with LP PPR projections
- 377 ESPN season outlooks
- 1,879 published prior-season actual lines
- 53 Total QBR rows
- 53 passer-rating rows
- one QBR payload checksum
- zero stale Roydell Williams rows
- `PRAGMA quick_check = ok`

The publisher now removes rows from older projection checksums inside the same transaction. This was
added after verification found one inactive stale row, and the ingest was rerun successfully.

Managed backend verification after the main worktree returned to `dev` showed Josh Allen with:

- completion percentage `69.347826`
- 40 sacks
- 177 passing first downs
- Total QBR `65.06`
- passer rating `102.15599822998047`
- 7 fumbles and 3 lost
- a non-null season outlook and projection

## Verified Reasonix venue-marker slice

Reasonix's original dirty worktree also contained unrelated NFL schedule, news, game-log, esports,
and Props-page work. Those files were not committed wholesale. The exact venue-marker slice was
reconstructed on a clean branch, verified before commit, committed as `18f0b59`, and merged through
`37660d4`.

The merged six-file slice:

- preserves `home: true | false | null` in Props history
- renders `@ OPP` only when `home === false`
- renders `vs OPP` only when `home === true`
- leaves unknown venue unmarked
- keeps unknown games out of both Home and Away filters
- adds focused backend and PropChart regression tests

Managed-browser evidence on `:3096` before the checkout:

- MLB: home and away markers correct
- NBA: home and away markers correct
- NHL: home and away markers correct
- reachable MLB null row: neither `@` nor `vs`
- zero page or console errors

The then-recorded public tunnel hostname was DNS-unavailable, so tunnel verification was not counted
as passing evidence.

## Final combined verification

- 83 focused backend tests passed.
- 7 focused frontend tests passed across the player overlay and PropChart.
- Focused ESLint had zero errors; the existing player-page raw `<img>` warning remained.
- Combined-code clone API verification returned the expected outlook, projection, completion rate,
  sacks, first downs, QBR, passer rating, and fumble values.
- `git diff --check` passed for the committed implementation.

## Safe next steps

1. Verify `git -C /root/legendarypicks branch --show-current` prints `dev`.
2. Do not use `git switch`; use `git checkout` only when a branch change is authorized.
3. Do not apply or drop the preservation stash without identifying each WIP owner.
4. Treat candidate, managed DEV, and production as separate states.
5. Do not push or promote this local `dev` history without explicit authorization and a fresh
   whole-app release gate.
