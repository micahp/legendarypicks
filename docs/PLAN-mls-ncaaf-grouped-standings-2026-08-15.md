# PLAN — MLS + NCAAF grouped standings contract (2026-08-15)

## Scope and boundary

Repair only the public standings contract for `/leagues/mls` and
`/leagues/ncaaf`. The implementation lives in the isolated
`feat/mls-ncaaf-standings` worktree. It must not write a database, run an
ingest, resume the legacy Ralph task, restart a service, push, or merge into
managed `dev` without a separate authorization.

The current public regression is concrete: both routes call
`/api/{league}/standings`, but the backend sends MLS and NCAAF through the flat
`team_strength` contract. The frontend correctly recognizes a grouped response,
but consequently falls back to a generic W/L table. See `TASK-league-mls.md`
and `TASK-league-ncaaf.md` for the dated public feature matrix.

## Published source contract

Use the existing ESPN Core standings path through `espn_client.group_standings`:

`https://site.web.api.espn.com/apis/v2/sports/{soccer/usa.1|football/college-football}/standings`

This is the publisher's current standings payload. Copy its group names and
stat fields; do not calculate record, draws, goals, points, rank, or a
conference membership list from local results.

Measured 2026-08-15:

| League | Publisher shape | Reader contract |
|---|---|---|
| MLS | Eastern and Western Conference; 15 rows each | `P/W/D/L/GF/GA/GD/Pts`, including published draws and points |
| NCAAF | Conference children; Sun Belt contains published East/West leaf divisions | `#/Team/GP/W/L` only when each value is published; unavailable values render `—` |

The publisher's preseason NCAAF entries publish `wins: 0` but omit some of
`rank`, `gamesPlayed`, and `losses`. `0` is valid only where ESPN sent zero;
an absent field remains `null` through the API and a dash in the UI.

## Implementation steps

1. Make `group_standings` transform any leaf standings group, descending through
   container groups with no entries. Preserve the publisher's leaf name (for
   example, `Sun Belt - East`); omit only empty containers, never a populated
   publisher group.
2. Preserve nullable publisher fields in the grouped row contract. Do not use
   `int(value or 0)` for an absent standings value.
3. Route only `mls` and `ncaaf` through this grouped transformer in
   `GET /api/{league}/standings`; leave the World Cup phase gate and every other
   league's flat strength contract unchanged.
4. Make grouped standings cells render `—` for null rank/record fields. MLS
   retains its soccer table; NCAAF retains its football-only table and never
   shows soccer columns.
5. Add deterministic tests for nested source groups, nullable fields, route
   selection, MLS draws/points, and NCAAF unavailable fields.

## Acceptance evidence

- Unit tests prove no missing source value becomes zero and nested NCAAF groups
  remain visible.
- Route tests prove MLS/NCAAF return grouped arrays and a non-target league
  remains on `team_strength`.
- Frontend tests prove MLS exposes `D`/`Pts` and NCAAF renders `—` rather than
  `0` for missing publisher fields.
- Candidate browser checks through a separately authorized running service must
  show MLS conference draw columns and NCAAF conference/leaf-group headings.

No historical coverage row, logs, or local database count is a substitute for
these source-contract and rendered-route checks.
