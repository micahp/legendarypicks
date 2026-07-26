# Production player-history refresh

Production treats the current prop slate and player history as different data
lifecycles:

- `prop_games`, `props`, and the active player roster may stay scoped to the
  current or next event.
- `player_game_logs` is durable history. It should accumulate by stable source
  identity and must not be replaced when the slate rolls over.

One systemd timer runs `backend/run_history_refresh.py --apply`. The coordinator
runs qualified league adapters sequentially, reports each failure independently,
and exits non-zero if any adapter fails. A league does not need its own timer;
it needs a safe adapter before being added to the coordinator.

## Adapter contract

Every scheduled adapter must:

1. use a finite source window and bounded retries;
2. fetch the entire source plan before opening production writable;
3. resolve only to an existing stable player identity, or queue the identity as
   unresolved rather than guessing;
4. preserve existing JSON keys and make additive/idempotent changes;
5. create and integrity-check a timestamped production backup before mutations;
6. apply one short `BEGIN IMMEDIATE` transaction in SQLite `journal_mode=delete`;
7. fail closed on incomplete sources, identity conflicts, or unexpected counts.

The service also uses a non-overlap lock, low CPU/I/O priority, and memory
pressure/hard limits to protect the live application.

## Qualified adapters

- UFC: bounded current-card work set; retains historical fights for those
  fighters and naturally follows the roster when the next card replaces it.
- MLB batting: checks the official final-game schedule and ingests at most one
  missing day per run with sequential Statcast fetching. New rows use MLB game
  IDs as their natural-key `game_no`, which supports doubleheaders.

## Descheduled

- World Cup: **technically qualified but deliberately not scheduled.** The
  adapter works — tournament-window source scan on first use, scoped to players
  that appeared in a production prop slate, with a durable cursor that makes
  later runs no-ops. It is off the schedule because the World Cup is out of
  season until **2030**, so running it four times a day spent production writes
  and box resources on a dormant league. Re-listing it in `DEFAULT_JOBS` is a
  one-line change when the tournament returns. See `AGENTS.md` section 0.

## Not yet qualified

- MLB pitching: the existing range fetch can parallelize internally, and the
  schema lacks a batting/pitching role dimension for two-way-player collisions.
- NBA: the current ingester performs network requests while daily write
  transactions are open and can create duplicate player identities.
- NFL: the current ingester builds and writes a full season without the guarded
  backup/plan/apply split. It is currently complete and out of season.
- NHL: the current ingester performs many player requests while writable and
  only requests regular-season game type 2, so 2026 playoff history is absent.

These adapters must be hardened to the contract above before being scheduled.

## Installed units

- `legendarypicks-history-prod.service`
- `legendarypicks-history-prod.timer`

The timer runs at 05:17, 11:17, 17:17, and 23:17 local time with up to five
minutes of randomized delay. The superseded
`legendarypicks-ufc-fight-stats-prod.timer` remains installed but disabled.
