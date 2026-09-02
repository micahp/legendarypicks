# Player game-log away markers — non-NFL handoff

## Goal

Make every supported non-NFL player game-log surface prefix the opponent with
`@ ` only when the published venue value explicitly says the player was away.
Home games may keep their existing home treatment. Unknown venue must remain
unknown and must never be rendered as away.

NFL is out of scope for this handoff. Its standalone player page now resolves
home/away from the published `nfl_schedule` rows in `backend/routers/players.py`.

## Measured DEV state

Read-only counts from `backend/data/picks.dev.db` on 2026-08-01:

| League | home | away | null |
|---|---:|---:|---:|
| MLB | 23,917 | 23,692 | 67 |
| NBA | 11,984 | 12,102 | 0 |
| NHL | 24,025 | 23,992 | 0 |
| UFC | 0 | 0 | 78 |
| WC | 1,608 | 1,614 | 0 |

The active player-detail generic row in `pages/player/[id].tsx` currently uses
`g.home ? 'vs' : '@'`, so `null` is falsely labeled away. The props history
reader in `backend/routers/props.py` also converts every non-home value,
including null, to `false`.

## Scope

- Implement and verify MLB, NBA, and NHL player game logs.
- Sweep other active shared game-log renderers, including `PropChart`, for the
  same null-to-away coercion. Fix only occurrences that represent player game
  venue.
- UFC has no home/away concept; preserve it as unknown and do not invent one.
- WC is dormant under `AGENTS.md`; report its current behavior but do not edit
  WC-specific code.
- Do not alter the table layout, columns, spacing, ordering, phase separation,
  or NFL schedule logic.

## Contract

- Backend/API venue is tri-state: `home: true | false | null`.
- Render away only when `home === false`: `@ OPP`.
- Render a known home opponent using the surface's existing home convention.
- Render unknown venue without `@`; do not silently substitute home or away.
- Preserve source nulls through readers. In particular, replace boolean
  expressions such as `home_away == 'home'` when they collapse null to false.
- Use canonical player IDs and existing league rows; no name joins and no data
  reconstruction.

## Acceptance evidence

1. Focused backend tests cover `home`, `away`, and `null` serialization.
2. Frontend/browser checks cover one home and one away row for MLB, NBA, and
   NHL, plus an MLB null row if it is reachable on a player page.
3. Away text includes exactly one `@ ` prefix; known home and null rows do not.
4. Existing table structure and descending/recent ordering are unchanged.
5. Zero page errors and unexpected console errors on managed DEV `:3096` and
   the public tunnel.
6. Report the exact surface sweep and any unresolved coverage honestly.

## Safety

Read `AGENTS.md`, `docs/CONTEXT-2026-08-01.md`, and the honest-data UI guidance
before editing. Preserve concurrent WIP. Do not write a database, restart or
kill managed services, commit, push, deploy, or touch production.
