# CONTEXT SUMMARY — 2026-06-24 — read this FIRST after a context reset

Orchestrator (Claude) handoff. Supersedes `RESUME-2026-06-24.md` (still accurate for M1–M7
detail; this doc only adds what happened after it was written + current branch state).

## 0. Where we are (2026-06-25)
- **Master checklist M1–M7: all scoped design + impl DONE + verified.** Swarm (reasonix +
  hermes on DeepSeek) idle. See `RESUME-2026-06-24.md` §0/§2 for the per-milestone breakdown.
- **Branch `analytics-backbone` is now PUSHED** to `origin/analytics-backbone` (2026-06-25).
  ~11 commits ahead of where it forked from `dev`. **Nothing deployed** — push ≠ deploy; the
  live site (legendarypicks.xyz) only changes on `docker compose up -d --build`.
- PR not opened yet: https://github.com/micahp/legendarypicks/pull/new/analytics-backbone

## 1. The commit the 06-24 resume predates — `4001475` (06-25 08:56)
**feat: dev/prod DB separation.** This is the important one for anyone resuming.
- **Problem:** all 12 sqlite connect sites hardcoded `backend/data/picks.db`, which is
  bind-mounted live into the prod container. This session's M4/M5/M6 work therefore mutated
  PROD directly (the live DB) with no dev isolation.
- **Fix:** every connect site now resolves `os.environ['LP_DB_PATH']` or falls back to the prod
  default. **Unset = prod (deploys unchanged). Set = dev.** Dev DB seeds from the pre-session
  backup at `backend/data/picks.dev.db` (gitignored, isolated inode, self-upgrades on import).
- **Also fixed a latent deploy landmine:** `_init_db()` self-created `team_game_stats` but NOT
  `prop_odds_snapshots` or the `props.odds` columns (hermes had hand-applied those to the live
  file). A fresh deploy to an empty DB would have crashed (no such table/column). `_init_db()`
  now self-creates `prop_odds_snapshots` and idempotently ADDs `odds`/`odds_captured_at` —
  verified a pre-M6 file heals on import and re-runs cleanly.
- Doc: `docs/DB-DEV-PROD-SEPARATION.md` (bind-mount, LP_DB_PATH contract, dev bootstrap,
  guardrails, exactly what this session wrote to prod + why it was left in place).
- **Dev-mode tested + verified (2026-06-24):** `LP_DB_PATH` unset → resolves prod path;
  set → resolves `data/picks.dev.db`; `_init_db()` heals the dev DB (all tables/columns
  present, 10,393 `prop_results` readable). **Prod `picks.db` mtime unchanged during the dev
  test** — isolation holds, the gate never touched prod.

## 2. What's written to PROD right now (left in place intentionally)
Because the work ran before the LP_DB_PATH gate existed, the live `picks.db` already has:
- M4 void rows persisted in `prop_results` (additive, hit=NULL).
- M5 `team_game_stats` table (1152 rows / 480 games).
- M6 `prop_odds_snapshots` table + `props.odds`/`odds_captured_at` columns, hand-applied.
These are additive/non-destructive and the schema now self-heals on deploy, so they were left.
Backup: `backend/data/picks.db.bak-20260624` (verified 10,393 prop_results).

## 3. CEO gates outstanding (Micah's calls — do NOT do without sign-off)
1. **Deploy** — branch is pushed but nothing is live. `docker compose up -d --build` when ready.
   (Open the PR first if you want review.)
2. **M7-impl** — build the EV/CLV/calibration compute + endpoints per `docs/M7-EV-CLV-DESIGN.md`.
3. **M2-impl** — execute the live DB storage migration per `docs/STORAGE-MIGRATION-DESIGN.md`
   (designed, NOT run; the risky one — fresh backup + step-by-step, no batching).
4. **Enable live Bovada odds-capture cron** (~36 req/day, external) — M6 is built but no cron armed.
5. M6 follow-ups: `is_close` flag at game start, market-alias table.

## 4. Standing guardrails (non-negotiable)
- No deploy/destructive DB op without CEO sign-off + fresh backup. No DROP/DELETE.
- Verify every "done" against real data; 200 ≠ working; don't trust agent self-reports.
- For dev work now: `export LP_DB_PATH=backend/data/picks.dev.db` so you never touch prod again.
- Resolve identity by ID, never name strings. No Claude attribution on commits.
