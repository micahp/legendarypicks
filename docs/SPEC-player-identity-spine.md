# SPEC → DeepSeek: Player Identity Spine (cross-source ID crosswalk)

Read AGENTS.md first (guiding principle: ground truth + the whole population, not a sample; build
before commit; verify render not 200). Do this **phase by phase, each in its own fresh subprocess** —
it's foundational, don't do it all in one context. Don't touch `scores.tsx` / `GameCard.tsx`.

## Problem (root cause of all the coverage gaps)
Everything joins by **name**: `player_stats.player_name`, `props→players.name`, roster names. Sources
spell players differently (Bovada "Bobby Witt Jr." vs Statcast "Bobby Witt"; accents; "A.J."/"AJ";
nicknames), so name joins silently drop mismatches → roster coverage is 52/55/15/2% (MLB/NBA/NFL/NHL).
This is an **identity problem, not a stats problem.** Fix it once with a cross-source ID spine.

## Goal
One canonical player per real human, with every source's native ID, so all data joins on a stable
integer key — deterministic, no silent leaks. Target: roster-based coverage ≥95% per league, and an
explicit review queue for anything unresolved (never silently dropped).

## Current schema (what exists)
- `players(id, name, team, league, espn_id)` — surrogate `id` exists; `espn_id` unused (0 populated).
- `props(id, game_id, player_id, market, line, side, source, captured_at)` — ALREADY keys on
  `players.id` via `player_id`. Good — props is already on the spine.
- `player_stats(... player_name, league, stat_type, <league stat cols> ...)` — joins by NAME. This is
  the leak.

## Phase 1 — schema (additive, no breakage)
Extend the canonical `players` table into the spine:
- Add nullable source-ID columns: `mlbam_id` (Statcast), `nfl_gsis_id`, `nhl_id`, `nba_id`
  (keep `espn_id`). Add `active INTEGER`, `position TEXT`, `updated_at`.
- Add `player_id INTEGER` (FK → players.id) to **`player_stats`** (nullable for now).
- Create `unresolved_players(source, raw_name, league, team, first_seen, count)` — the review queue.
- Create `name_alias(player_id, alias_norm)` for known aliases/nicknames → player_id.
Ship Phase 1 alone (migrations only), build green, before touching data.

## Phase 2 — populate the spine from ID-bearing published sources (NOT name guessing)
One canonical `players` row per rostered player per league, filled with whatever native IDs the source
gives. Use the published crosswalks — they map IDs across systems for free:
- **NFL:** nflverse `load_players()` / `import_players()` (gsis ↔ espn ↔ pfr…). Gives `nfl_gsis_id` +
  `espn_id` + name + team + position for the full league.
- **MLB:** Chadwick Bureau register (the same table `pybaseball.playerid_lookup` uses) →
  `mlbam_id` + name + team. Pull the register ONCE (bulk), not per-player.
- **NBA:** hoopR / nba_api player list → `nba_id` (+ espn where available).
- **NHL:** `api-web.nhle.com/v1/roster/{TEAM}/current` over all 32 teams → `nhl_id` + name (you already
  built this in 4a3a0d1 — reuse it as the roster source).
- Cross-link to `espn_id` via ESPN rosters where a source lacks it.
Upsert by (best available source id); dedupe. This is the full-roster universe.

## Phase 3 — backfill `player_stats.player_id`
For every existing `player_stats` row: set `player_id` by matching on the **source id** the ingest used
(mlbam/nfl/nhl/nba) → `players`. For residual rows with no id, fall back to normalized name+team+league.
Anything still unmatched → log to `unresolved_players`. Report match rate.

## Phase 4 — repoint reads + writes to `player_id`
- Stats endpoints (`_get_*_stats`) join `player_stats` to `players` by **`player_id`**, not name.
- Each ingest (`ingest_statcast/hoopR/nfl/nhl`) writes `player_id` (resolved via the spine) on every row.
- Keep `player_name` as a denormalized convenience column, but it is NOT a join key anymore.

## Phase 5 — harden Bovada → player_id resolution at ingest (`ingest_props.py`)
Bovada has no public ID. Resolve its names to `players.id` ONCE at ingest:
1. Deterministic: normalized-name (unaccent, casefold, strip suffixes jr/sr/ii/iii, normalize initials)
   + **team** + league match against the spine.
2. Check `name_alias`.
3. Low/no confidence → write to `unresolved_players` (do NOT silently create a names-only player).
Normalization helper must be shared by ALL ingests + the resolver (one function, one source of truth).

## Phase 6 — coverage as a monitored gate
Add a `scripts/coverage_report.py`: for each league, % of ESPN-rostered players present in the spine AND
in `player_stats` (by player_id). Print per-team + league totals. This is the SLO check.

## Verification (required, paste numbers)
- Roster-based coverage ≥95% per league (run Phase 6 report).
- `bobby witt jr.`, `shohei ohtani` (batting+pitching), a non-star NHL player all resolve via player_id.
- `unresolved_players` reviewed — residue is genuinely unrostered/retired, not spelling misses.
- `docker compose build frontend` → "Compiled successfully"; pages still render real data (not just 200).

## Deliverable
Per-phase commits (build-verified each), before/after coverage table in
`docs/HANDOFF-deepseek-to-claude-other-leagues-2026-06-15.md`, ping after each phase lands.
