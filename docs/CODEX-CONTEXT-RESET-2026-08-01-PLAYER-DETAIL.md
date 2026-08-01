# Codex context reset — recovered player detail, player pools, and managed worktree

Date: 2026-08-01
Repository: `/root/legendarypicks`
Managed branch: `dev`
Implementation checkpoint before this document update: `4dbc44c`
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

The main worktree is on `dev`. The verified implementation ends at `4dbc44c`, 19 commits ahead of
`origin/dev`; the document-only commit containing this update is its immediate descendant. The
recovery work was performed in `/root/lp-player-detail-recovery` on
`fix/recover-player-detail-wip` and fast-forwarded into local `dev` only after focused verification.
The feature branch
`feat/player-game-log-away-markers` still points at `3cc9487`; it was not reset or deleted.

Before the checkout, all tracked WIP was preserved in:

```text
stash@{0}: preserve-main-worktree-before-dev-switch-20260801
```

That stash contains 12 tracked files and remains intact. Its task-owned hunks were mapped and
recovered, but the stash must not be dropped because it still serves as containment and includes
externally owned esports WIP:

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
4dbc44c fix(player): lead game log with season postseason
14efc9b fix(player): clarify source and prevent mobile tab wrapping
59311dd fix(nfl): unify player pool ordinals
033cec2 perf(nfl): scope draft cache invalidation to source data
134f556 fix(nfl): keep draft board cache hot in wal mode
82a200e docs: complete preservation recovery map
e9a8b2f fix(props): restore completion label
cc05bdd fix(nfl): open player pool names in overlay
9a261e5 fix(nfl): recover and harden mock draft pool cache
453a8b2 docs: record preservation stash recovery gate
069a9c9 fix(nfl): recover and harden draft board cache
63a3099 fix(player): recover NFL profile detail work
b4ffc81 docs: protect managed dev worktree branch
65a8568 fix(nfl): remove stale projection snapshot rows
37660d4 merge: verified player opponent venue markers
18f0b59 fix(player): preserve unknown game venue markers
f9f7555 merge: player overlay projections and season totals
a306386 feat(nfl): add player projections tab and season totals
3cc9487 chore(release): v0.6.14
```

Nothing has been pushed. `origin/dev` and tag `v0.6.14` remain at `3cc9487`.

## Recovery and preservation outcome

The later player-detail, NFL pool, news, schedule, label, and cache work was found only in
`stash@{0}`, not in active `dev`. It was recovered selectively rather than applying the stash
wholesale. The stash was kept exactly as requested.

The durable prevention rule is recorded in:

```text
docs/RETRO-2026-08-01-PLAYER-DETAIL-PRESERVATION.md
```

Before a preservation stash can be called recovered, require all of the following:

- inspect the stash against its first parent, not only against current `HEAD`;
- classify every hunk by owner and task;
- map every task-owned hunk to an active commit or an explicit intentional rejection;
- require zero unexplained task-owned hunks;
- run the browser acceptance matrix on the exact managed surfaces;
- keep the stash until the ownership map is complete.

## NFL player overlay delivered

`components/Leagues/PlayerDetailOverlay.tsx` now has four tabs:

- Overview
- Game log
- News
- Projections

The Projections tab contains the ESPN-authored Season Outlook followed by the 2026 projection
table. The visible attribution now reads `Source: ESPN`. Overview retains the previous research
sections and adds the published prior-season totals table.

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

## Recovered player-detail and player-pool behavior

The recovery and follow-up commits now provide all of the following on local `dev`:

- Player Pool names open `PlayerDetailOverlay` and keep the user on `/leagues/nfl`.
- Both NFL game-log surfaces use the published NFL schedule for opponents and venue.
- `@` appears only for published away games; home games are unprefixed and unknown venue stays
  unmarked.
- Regular season, postseason, and preseason remain separate instead of being blended.
- Standalone Player Detail orders `2025 POSTSEASON` above `2025 REGULAR SEASON`; every phase heading
  carries the season year.
- Mobile `Game Log` tabs are non-shrinking and non-wrapping on both standalone and overlay surfaces.
- The overlay includes Overview, Game log, News, and Projections, including ESPN news and the
  same-name article correction.
- Game-log labels are `Comp`, `Att`, and `Car`; the orange league-rank card uses `Comp/G`.
- The Props completion label is also `Comp/G`.

The visible player-pool ordinal is now one coherent system. ESPN PPR ranks 37–68 belong to 32 TQB
aggregate entities, which are intentionally excluded from a player-only pool. Previously the row
column showed those gapped ESPN ranks while the footer showed filtered row positions. League and
mock-draft pool tables now display their player-only ordinal under `#`; managed verification showed
50 rows numbered 1 through 50 with footer `1–50 of 772`.

## Player-pool read-path performance

The draft-board and full mock-draft-pool caches written by Hermes were retained and repaired.

The original invalidation token used the SQLite database and WAL mtimes. In WAL mode, opening a
read connection creates a transient zero-byte WAL with a new mtime, so every request looked like a
publication and missed cache. In addition, unrelated Props and esports writes to the shared SQLite
file evicted the NFL cache.

The current two-layer token:

- normalizes transient zero-byte WAL lifecycle;
- memoizes unchanged physical database state;
- fingerprints only the NFL source tables consumed by the draft surfaces;
- ignores unrelated database writes;
- still invalidates for relevant NFL row corrections, non-empty WAL publications, and schema
  changes;
- retains bounded, monotonic-TTL response caches and encoded full-pool responses.

Measured against the current DEV database:

- cold in-process draft-board read: about 0.39 seconds;
- hot in-process read: about 6 milliseconds;
- hot managed `:3096` proxy read: about 26–40 milliseconds;
- 50 returned rows: 37,694 decoded bytes.

The remaining full-page time on `next dev` includes development hydration and the other concurrent
camp endpoints; it is not a 2.88 MB Player Pool transfer. The separate full mock-draft payload still
contains 4,507 players and is protected by its encoded response cache.

## Final combined verification

- Recovery gate: 81 backend tests and 12 frontend tests passed across the recovered player detail,
  news, schedule, labels, caches, overlay, and game-log behavior.
- Performance gate: 26 offseason/draft-board tests and 25 mock-draft tests passed in their required
  separate Python processes.
- Pool ordinal gate: 8 focused frontend tests passed across league rows, mock-draft rows, and the
  pool mapper.
- Final source/mobile/game-log gates: overlay and game-log tests passed; focused ESLint had zero
  errors with only the pre-existing player-page raw `<img>` warning.
- Managed browser verification covered the overlay and standalone Player Detail with zero page or
  console errors, `Source: ESPN`, single-line mobile tabs at 320 px, player ordinals 1–50 matching
  the footer, and postseason-before-regular headings with the year.
- Clone API verification returned the expected outlook, projection, completion rate, sacks, first
  downs, QBR, passer rating, fumble values, regular-season logs, postseason logs, and away markers.
- `git diff --check` passed for every committed implementation slice.

## Safe next steps

1. Verify `git -C /root/legendarypicks branch --show-current` prints `dev`.
2. Do not use `git switch`; use `git checkout` only when a branch change is authorized.
3. Do not apply or drop the preservation stash; its recovery map is complete, but it remains the
   requested containment copy and still includes externally owned WIP.
4. Treat candidate, managed DEV, and production as separate states.
5. Do not push or promote this local `dev` history without explicit authorization and a fresh
   whole-app release gate.
