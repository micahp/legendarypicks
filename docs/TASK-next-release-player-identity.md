# TASK: next-release player identity (v0.8.1 or v0.9.0)

Full detail for the "NEXT RELEASE — player identity" section of `ROADMAP.md`.
Scope, in order. Each step is independently shippable; do not skip ahead.

## Why this exists

Every props/roster ingest path resolves players by NAME every run. That is
O(players) string work per source per day, and it silently diverges: a name
spelling change on the publisher side mints an unresolved row even though the
player is the same person. The Underdog path already proves the fix — it keys
`player_source_ids` on the publisher's own player UUID and never re-resolves by
name once bound.

## Step 1 — Declare the natural key on `players` (DONE 2026-08-18)

Both databases already carry `UNIQUE(espn_id, league)` on `players`, and there
are 0 duplicate `(league, espn_id)` groups on either. The migration has no
conflicts to resolve. This step is complete; it is listed for the record so the
release does not re-litigate it.

## Step 2 — Populate `player_source_ids` so Bovada/RotoWire/Underdog stop resolving by name

Current state (dev, 2026-08-18): 10 rows, all `underdog/ufc`. The Underdog
ingest (`backend/ingest_underdog_props.py`) writes source keys on bind via
`bind_player_source_key` and resolves via `SELECT player_id FROM
player_source_ids WHERE source=? AND league=? AND source_player_key=?` FIRST,
falling back to name only when the key is unmapped.

Work:
- [ ] Bovada: thread the publisher's player identifier (when present) through
      `bovada_scraper` → `_resolve_player_for_ingest` → `player_source_ids`.
      Bovada's coupon API does not expose a stable per-player id today — if that
      is still true, the source key is the normalized name (still a win: the
      name-to-id map is then persisted instead of re-searched).
- [ ] RotoWire/PrizePicks relay: same, keyed on whatever stable id the relay
      publishes (the monitor already reads the payload; add the key capture).
- [ ] Backfill: one-off script to populate `player_source_ids` from existing
      resolved props (source, league, normalized name → player_id where the
      resolution is unambiguous).
- [ ] Resolver fast path: `_resolve_player_for_ingest` checks
      `player_source_ids` before the name index.

Acceptance: after a Bovada run, `player_source_ids` row count grows; a second
run with identical names does zero name-index lookups for already-bound players.

## Step 3 — Convert promotion from row-copy to re-running the ingest against prod

The 2026-08-17 tennis spine promotion already worked this way: re-run the
ingest against prod instead of copying rows. The runbook (`RUNBOOK-prod-promotion.md`)
currently documents a data-copy step; replace it with "re-run the ingest with
`LP_DB_PATH` pointed at prod" and keep the verification gates.

## Step 4 — Reconcile the ids that have already diverged

Only after 2–3 are live. Use the mapping artifacts recorded under the guardrail
(`unresolved_players`, `_STALE_TEAM_TAGS`, `_MINTED_PLAYERS`) to find players
that were minted under the wrong id and fold them onto the canonical row. This
is the risky step; do it against a copy, review the diff, apply.

## Notes

- Tournament (lcup) props ride along: their players stay resolvable against the
  league that rosters them (see roadmap item 4, IDENTITY half).
- Never print source keys in logs; the review queue is `unresolved_players`.
