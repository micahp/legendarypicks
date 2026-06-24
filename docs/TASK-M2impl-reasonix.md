# TASK — M2-impl DESIGN: schema migration to the game→team→player spine

**For:** reasonix
**Scope:** READ-ONLY design doc. **Do NOT execute the migration** — produce the plan.
**Output:** `docs/STORAGE-MIGRATION-DESIGN.md`
**Why now:** M5 (hermes, in progress) and M6 (odds-capture, designed) are being built
*incrementally on the current schema* to ship value now. Your job is the plan for
eventually folding them into the new spine designed in
`docs/OFFSEASON-DATA-DESIGN.md` §3, so the incremental tables aren't throwaway.

## Deliverable — a migration design doc covering:
1. **Target shape** (from OFFSEASON-DATA-DESIGN.md §3): the `games → team_game_stats
   → game_player_stats → players` spine with props/markets as children via FKs.
   Restate it crisply as the migration *target*.
2. **Current schema map** — read the live DDL for every table in `backend/data/picks.db`
   (use `sqlite3 .schema`, bounded; do NOT dump data). Enumerate what moves where.
3. **Absorption plan for the new incremental tables:**
   - `team_game_stats` (M5, hermes) → folds into `team_game_stats` on the new spine.
   - `prop_odds_snapshots` + `props.odds` (M6) → where odds live on the new spine.
   - existing `props` / `prop_results` → how they reattach as children.
4. **Migration steps** — ordered, each reversible: (a) create new tables alongside
   old, (b) backfill from old via INSERT…SELECT (identity by ID), (c) dual-write,
   (d) cutover reads, (e) retire old. Each step with a verify check + rollback.
5. **Identity discipline** — every join on IDs; call out any name-string joins in
   the current schema that must be eliminated (AGENTS §7).
6. **Risk register** — what can corrupt the LIVE DB, and the mitigation per step.

## GUARDRAILS (non-negotiable)
- **READ-ONLY.** No DDL, no DML, no writes to any DB or code. Doc only.
- **No destructive DB op, no machine-wide greps/strings-on-DB/unbounded loops**
  (locked the CEO out of SSH before). `sqlite3 .schema` on the single DB file only.
- **Curl/verify any claim about endpoint shape** before asserting it.
- **Write progress to `logs/AGENT-M2impl-reasonix.md`** as you go; if you pass ~70%
  context, STOP and write a complete handoff.
- Do NOT commit/push/deploy.

## Done criteria
- `docs/STORAGE-MIGRATION-DESIGN.md` exists, with the 6 sections above.
- Current-schema claims are real (read from live DDL, not guessed).
- Migration steps are ordered + each reversible with a verify check.
