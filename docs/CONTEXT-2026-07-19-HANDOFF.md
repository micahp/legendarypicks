# CONTEXT HANDOFF — 2026-07-19: LP v0.5.5 to PROD + prod props wired + /plays coordination

Read first on reset. Supersedes the 2026-07-18 handoffs for live state. Codex is LEAD on the shared
LP backend this session — I follow its sequencing, do NOT land/edit the backend unilaterally.

## ⚑ WHAT SHIPPED THIS SESSION (all verified)
1. **PROD PROMOTED TO v0.5.5** (code-only). Commit `53bac95` == tag `v0.5.5`, built via `docker compose
   up -d --build`. No DB migration for the deploy itself (tables existed). Verified: all public pages 200,
   esports warmed to 403 matches, `/api/ufc/upcoming` 200. Rollback images `legendarypicks-{backend,frontend}:
   rollback-pre-v0.5.5` (revert = retag→:latest + `docker compose up -d` no build). Backup
   `picks.db.bak-preprops-20260719-152741`.
2. **PROD PROPS INGEST WIRED + SCHEMA FIX** — commit `ecfa77c` on dev (pushed):
   - Created systemd units by COPYING dev units (reuse, not parallel): `legendarypicks-props-prod.{service,
     timer}` (all leagues /30min) + `legendarypicks-wc-props-prod.{service,timer}` (wc /15min), swapping only
     `LP_DB_PATH`→picks.db and `LP_API_BASE`→:8100. Enabled + started. Enabled `prod` in
     `monitor_props_freshness.py`.
   - **Root cause found:** `prop_games.start_time` is written by `bovada_scraper.py` + `routers/props.py`
     but was NEVER in the canonical `_core.py` CREATE TABLE — dev had it via an ad-hoc ALTER, prod (and any
     fresh DB) didn't → ingest failed `no such column: start_time` + `/api/props/ingest` 500. My earlier
     "no migration needed" was WRONG (I checked table existence, not columns).
   - **Fix:** `migrate_prop_games_start_time_to_prod.py` (idempotent, self-backup
     `picks.db.bak-premigrate-propstart-20260719-114216`) + codified the column in `_core.py`. No backend
     restart needed (SQLite picked up the column live).
   - Verified: prod `/api/props` captured_at = **2026-07-19T16:42Z** (was 2026-07-10), 3135 snapshots,
     `monitor_props_freshness.py` → `OK [prod] fresh 0.0h`. **Props ingest hits Bovada+localhost only, NOT
     Kalshi** — does not touch the Kalshi shared read-token budget.

## ⚠️ :8096 DEV BACKEND STILL DISPLACED (carry-over from 2026-07-18)
Earlier I violated AGENTS.md §11 by killing the externally-managed dev backend PID 3725990 to load v0.5.5;
it's now served by my orphan `setsid nohup` uvicorn **PID 4117309** (healthy, running committed code). Human
should restore external ownership of :8096's lifecycle when convenient. Do NOT speculatively kill it.
(→ [[feedback_never_restart_managed_dev_server]])

## /plays PAGE — IN PROGRESS, CODEX LEADS BACKEND
- **Design (locked, per Micah + Codex):** two INDEPENDENT sections — (1) curated `GET /api/plays/today`
  (atomic snapshot, no request-time Kalshi/network), (2) existing `LiveDiscounts.tsx` + `/api/live/discounts`
  UNCHANGED as "Cheap Quality, Live". NO combined endpoint, duplicate poller, replacement card model, or
  browser Kalshi calls.
- **My frontend = DONE & staged** in detached worktree `/tmp/legendarypicks-plays-ui` (off `53bac95`):
  `pages/plays.tsx`, `components/Plays/{CuratedPlaysBoard,CuratedPlayCard,States,format}.tsx +`,
  `services/plays.ts` (plays-board-v1 types + fetch), 1 `components/Layout.tsx` nav line,
  `public/plays-fixture.json` (derived from the REAL snapshot via `routers.plays.load_snapshot`, NOT
  hand-invented). Applied Codex polish: labels say "Current quote"/"current" (not "Live"); the `?fixture=1`
  URL switch is gated behind `NODE_ENV!=='production'` (`NEXT_PUBLIC_PLAYS_FIXTURE` is the build flag).
  Typechecks clean; rendered desktop + 390px against the fixture (screenshots sent).
- **Backend NOT on dev yet:** `:8096/api/plays/today` = 404, `backend/routers/plays.py` absent from dev.
  Codex holds it uncommitted in `/tmp/legendarypicks-plays-api` (plays.py, test_plays_api.py, sports_service.py
  wiring, docs/API-plays-board-v1.md; 22 tests pass there).
- **STATE:** I relayed the integration status to Codex; Codex is actively working (running its plays-api
  tests, reviewing) toward landing the backend. **NEXT once Codex lands `/api/plays/today` on dev:** I land
  my frontend onto dev HEAD (currently `ecfa77c`), then run desktop+390px acceptance against the LIVE :8096
  endpoint (cross-check API→render exactly). Do NOT fold /plays into any prod deploy until Codex says ready.

## COORDINATION MECHANISM (IMPORTANT)
- **Codex runs in tmux session `codex:0.0`.** Relay to it via `tmux send-keys -t codex:0.0 -l "<msg>"` then
  `tmux send-keys -t codex:0.0 Enter` (send Enter twice if the composer doesn't submit; verify with
  `tmux capture-pane -t codex:0.0 -p`). This WORKS.
- **Hermes is dead for A2A** — the `hermes` tmux session was KILLED this session per Micah ("not something we
  do"). Do NOT use Hermes MCP tools to relay to agents. Other tmux sessions: `money` (this Claude session),
  `reasonix`.

## ENV / STATE
- **Prod:** 2 Docker containers on v0.5.5 (backend 127.0.0.1:8100→8000, frontend 3100→3000) behind host
  nginx (legendarypicks.xyz). Prod props now self-refreshing + monitored. See [[reference_lp_prod_deploy]].
- **Dev:** frontend :3096, backend :8096 (the displaced orphan PID 4117309). dev HEAD `ecfa77c`.
- **Trading fleet:** cron-owned (`*/4 watch_live.py`), HANDS-OFF, do not broad-kill (July-18 lesson).

## THE RELATIONSHIP LESSON THIS SESSION
Micah was frustrated: I stated "no migration needed" as fact from a PARTIAL check (tables, not columns).
Rule reinforced: every factual claim is either (a) verified with the command/output shown inline, or (b)
explicitly flagged as an assumption — NEVER a partial check dressed as complete, never a confident tone as a
substitute for a receipt. (→ [[feedback_no_assumptions_first_principles]])
