# TASK P2 — separate humans from fantasy constructs, structurally

**Phase:** P2 · **Effort:** weeks · **DO NOT START BEFORE NOVEMBER.**
NFL drafts run September. An independent architecture audit's verdict on doing this now:

> The realistic failure mode is not "it doesn't work" — it's "half the readers get
> migrated, half don't, and you get an eighth instance of dev/prod-style divergence, this
> time between two code paths in the same database, in the three weeks before the thing
> has to work." Correct engineering for October. The wrong bet for September.

**P1's migration ledger is a hard prerequisite.** This phase moves data across tables; a
partial run with no ledger is the single worst outcome available. Precedent: translating
only `20252026 -> 2026` would have left `20242025` as `MAX(season)` — a two-year-old season
served as current, from a migration that reported success.

---

## The problem this fixes

One shared table, written by 4+ publishers per league, with no schema-level separation of
who wrote what or **what kind of thing a row is**. Not a vocabulary problem — a category
error. `players` holds humans and fantasy constructs side by side, so:

* `roster_sync` blanket-set `active=0` for the NFL league. A D/ST is on no roster, so all
  32 stayed inactive. `ingest_nfl_adp.py` built its team map from `active=1`, got nothing,
  and its fail-closed preflight aborted **every run since** — stopping `injury_status` and
  `last_news_date` for all **6,486** NFL players. Production's draft board showed nobody as
  injured. No error anywhere.

ESPN never confuses the two: constructs exist only in `lm-api-reads.fantasy.espn.com`,
never in `sports.core.api.espn.com`, and it signs their ids **negative**. We stored the
sign and ignored it for months.

## Step 1 — the view. Do this one FIRST and possibly ONLY.

Before moving a single row, add `players_human` as a view over
`players WHERE COALESCE(entity_type,'player')='player'`, and migrate readers to it one at
a time. This gets the **query-time guarantee** — a construct cannot appear where code
assumes a person — with **no data movement, no flag day, and a one-line revert.**

Measure after: if every reader that should be on `players_human` is, and no incident of
this class recurs for a full season, **the physical split may not be worth doing at all.**
Record that decision either way.

## Step 2 — only if Step 1 proves insufficient

Target shape:

* **`players`** — the spine. Canonical id, name, league, publisher crosswalk. Humans only.
* **`espn_core_*`** — `sports.core.api.espn.com`. Real athletes, real positions, positive
  ids. What `roster_sync` and the stats ingests use.
* **`espn_fantasy_*`** — the fantasy API. ADP, ownership, PPR ranks, eligible slots, and
  the constructs that exist nowhere else.

**Most of this already exists.** `nfl_adp` is `espn_fantasy_adp` in all but name — it
already stores ESPN's fantasy position label per player per season (`DEF` 32, `TQB` 32,
`HC` 32) with adp and PPR rank. So the split is substantially **renaming and consolidating
what is there**, not inventing a new shape. Scope it that way and it shrinks a lot.

Order: `espn_fantasy_entities` first (lowest blast radius — `entity_type` already
identifies exactly 97 rows), then `espn_fantasy_adp`, then `espn_core_athletes` last,
behind a view named `players` if that is what avoids a flag-day rewrite.

## What this explicitly does NOT fix — do not oversell it

* **Identity correctness.** The 223 MLB rows with another player's `mlbam_id` came from a
  batter-name fallback reading the pitcher's name off a Statcast row. That is ingest logic.
  A table split changes nothing about it. `G/published-identity` is what catches it.
* **Season-key and game-type vocabularies.** Already solved correctly at the boundary
  (`season_keys.py`, `game_types.py`). Do not entangle them with this.
* **NBA's 269 split identities.** A resolve-by-id-first discipline problem, fixed by
  `merge_nba_identities.py` (written, tested, unapplied) plus ingest discipline — not by
  table topology.

## Non-goals

An ORM. Postgres. Rewriting the gate system. Changing the frontend contract. Touching
leagues with no fantasy layer beyond the `position_group` work already done for MLB.

---

## Frontend

**The API contract must not change, and that is the acceptance test.** Two surfaces key on
the position string directly:

* `components/Leagues/hooks/useNflDraftBoard.ts:10` —
  `POSITIONS = ['all','QB','RB','WR','TE','FLEX','PK','DEF']`
* `components/MockDraft/roster.ts:80` — `addSlot('D/ST', 'DEF', true)`

Also touching D/ST or injury fields: `NflDraftRoom.tsx`, `PlayerDetailOverlay.tsx`,
`MockDraft/columns.tsx`, `MockDraft/ResultsScreen.tsx`, `Leagues/types.ts`,
`Player/types.ts`.

Routers compose the response; where a value is read from is a backend concern. If a
frontend change becomes necessary, the split has leaked into the contract — stop and
reconsider rather than editing components.

## Done means

* every reader that assumes a row is a person selects from `players_human` (or its
  successor), demonstrably — enumerate the readers first, do not discover them during
* `/api/nfl/mock-draft/pool` and the player-detail payloads byte-identical before and after
* every step applied to prod and dev in the same session, through P1's ledger
* `diff_databases.py` clean on SCHEMA and SEASONS
* a written decision on whether Step 2 was needed at all
