# Goal: v0.6.13 Whole-App Release Compliance

Set 2026-07-31 via Reasonix `/goal` (Ralph loop). Source plan:
`docs/PLAN-v0.6.13-hermes-goal-loop.md` and
`/root/CODEX-V0.6.13-RECUT-PLAN-2026-07-29.md`.

## Outcome

Bring the Legendary Picks app at `/root/legendarypicks` to v0.6.13 whole-app
release compliance — every Phase 5-6 gate green — and stop at the Phase 7
authorization gate (tag move / prod migration / deploy) without crossing it.

## Verify (evidence required before "done")

- backend test suite green from `backend/` (incl. 10/12/14-team draft
  round-trips, projection/rank gates);
- production Next build succeeds;
- mock-draft table shows `RK | PLAYER | BYE | ADP | PROJ | AVAILABLE` sorted by
  RK (ESPN PPR rank), nulls last, honest `—`;
- player card shows `PROJ 2026` above `2025` from separate API fields;
- MLB/NHL leader responses unique by canonical player_id, identity agrees with
  `/api/player/{id}`;
- NBA/NFL/NHL Team Stats supported and non-empty with proof-backed data;
- 2026 schedule: 272 games / 32 teams / one bye per team, `2025` unchanged;
- zero unexpected console or page errors across the acceptance matrix.

## Constraints (do not break)

- ZERO production DB writes, migrations, restarts, or image builds until
  explicit authorization;
- fail-closed ingests: no partial replacement on network/schema failure,
  previous good snapshot survives a bad refresh;
- no null-to-zero coercion; missing values render `—`;
- protected tables (props, prop_results, prop_games) unchanged;
- no DEV DB copied wholesale.

## Boundaries

- work in a clean worktree from `dev` (e.g. `/root/lp-v0613-recut`);
- all DB work on a disposable clone of a production-shaped DB
  (`LP_DB_PATH=/tmp/lp-v0613-rehearsal.db`), never the live prod DB;
- apply the skills: published-first (published value > derived), honest-data-ui,
  build-league-data-pipelines.

## Stop when

- the Phase 7 authorization gate is reached (tag move, prod migration, deploy)
  — stop and report; or
- a decision/input is needed (e.g. installing ponytail from GitHub, prod
  access) — stop and ask.
