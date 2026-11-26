# CONTEXT HANDOFF — 2026-07-18 (LP props/esports sprint via Codex delegation)

Read first on a fresh context. Long session: shipped LP `v0.4.1 → v0.5.0`, delegated heavily to **Codex**
(tmux `codex:0.0`), v0.5.1 built-by-Codex and **awaiting review/commit**. All work is on **dev**; prod
is NOT touched (pre-launch, ~0 traffic).

## ⚑ IMMEDIATE STATE / DO FIRST
- **Codex just finished v0.5.1 — UNCOMMITTED, needs review+verify+commit (I own git).** Uncommitted
  tracked files: `AGENTS.md`, `backend/_core.py`, `backend/espn_client.py`, `backend/routers/games.py`,
  `backend/routers/props.py`, `components/Props/MarketSlateBoard.tsx`, `docs/DEV-STANDARDS.md`,
  `pages/props.tsx` + new files (expect `backend/ingest_wc_logs.py`, `components/Props/FightForm.tsx`).
  Spec: `docs/TASK-wc-logs-ufc-chart-state.md`. **v0.5.1 = WC player-log ingest (ESPN → `player_game_logs`
  so PropChart draws for WC props) + UFC last-5-fights ESPN-style form strip (`FightForm.tsx`, replaces
  the empty chart) + AGENTS.md operating rules.**
  - **Before committing:** VERIFY per DEV-STANDARDS — WC chart actually populates
    (`curl :8096/api/props/history?player_id=<wc scorer>&market=goals&line=0.5&side=over&league=wc` →
    non-empty `games`), UFC FightForm renders on the Props board, measure any new endpoint payload/time,
    `/props` + `/leagues/*` compile clean on the clean :3096. Then commit + tag **v0.5.1**.
- **git:** dev HEAD `873a056` (v0.5.0), tag latest = **v0.5.0**, dev == origin (+0, pushed). Tags
  v0.4.1..v0.5.0 all pushed.

## ENVIRONMENT (critical — one clean pair, tunnel on :3096)
- **Dev backend :8096** — `uvicorn sports_service:app`, env in `scratchpad/be8096.env`
  (`LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db` + keys). Restart: kill pid on :8096, source
  that env, relaunch.
- **Dev frontend :3096** — `next dev -p 3096` run **from the MAIN repo** `/root/legendarypicks`
  (API_PROXY_TARGET=http://127.0.0.1:8096). **Tunnel = https://entertainment-bailey-types-switches.trycloudflare.com**
  (cloudflared → localhost:3096; URL stable this session).
- **Preview shares the main-repo checkout Codex edits** → Codex saves churn HMR. When the preview breaks
  (`__webpack_require__.a is not a function`): kill :3096, `rm -rf .next/cache`, relaunch. This is the
  clean-restart I do after every Codex batch.
- **Prod** = docker compose, backend :8100 / frontend :3100, ~v0.4.0, **41h+ old, stale, unfed.** Do NOT
  deploy piecemeal — deliberate future pass (see below).

## CODEX WORKFLOW (learned this session)
- **Delegate code to Codex to save tokens** (Hermes MCP bridge broken — see [[reference_hermes_delegation_broken]]).
  Pattern: write a scoped `docs/TASK-*.md`, `tmux send-keys` it, it builds+verifies, I commit/tag.
- **Codex won't accept typed input while working** — only **Esc** (preserves files it wrote), then inject
  the message, then Enter. Typing while it works = "not in a mode" spam.
- **It thrashed dev servers** (spawned dupes on 3097/8095, killed :3096 → corrupted tunnel). FIX: every
  spec now front-loads env rules AND `AGENTS.md` (which Codex auto-reads) got an "Operating rules"
  section in v0.5.1: never start/kill/restart dev servers; use the running :3096/:8096; follow
  `docs/DEV-STANDARDS.md`.

## QUEUED NEXT (dispatch to Codex after v0.5.1 is committed)
1. **UFC Predict tab** on the UFC league page (`pages/leagues/[league].tsx` / `components/Leagues/`,
   next to Rankings + Schedule) — fight pick'em (winner + likely method), like `/predict` esports
   pick'em; reuses the UFC schedule + v0.5.1 fight data. Stub in `docs/TASK-wc-logs-ufc-chart-state.md`.
2. **Esports board: group/label by LOCAL day, not UTC** (user's open ask, awaiting go). Symptom: a CoD
   match that ended `2026-07-18 02:08 UTC` (= July 17 9 PM CDT, last night for Micah) shows on "today's"
   board because the board groups by UTC. It ended ~11h ago (genuinely today in UTC, but yesterday
   local). Finished matches also linger ~3 days in Results by design (that part is intended). Fix = local-day grouping.

## TIMERS (systemd, all live)
- `legendarypicks-props.timer` (30m): `bovada_scraper.py all --ingest` → **dev** DB / :8096. (Replaced
  the old wc-only timer.) Feeds mlb/nba/nfl/nhl/wnba (API) + wc/ufc (direct DB). Prod is NOT fed.
- `legendarypicks-props-freshness.timer` (30m): `monitor_props_freshness.py` — alerts + **self-heals**
  (re-triggers ingest) if any env's props are >3h stale. Only `dev` enabled in `ENVS`; **prod commented
  — enable at deploy.** Built because prod silently went 8 days stale.
- CDL Champs Whisper listener = **NOT running** (stopped).

## VERSIONS SHIPPED THIS SESSION (all on dev, pushed)
- v0.4.2 language/foreign esports-hero demotion (Chinese KoG can't outrank English cast; backend
  `foreign`/`language` surfaced) · v0.4.3 props upcoming-slate + game times · v0.4.4 **UFC props**
  (method-of-victory→per-fighter yes/no) + all-leagues ingest routing · v0.4.5 market-first props board
  (`MarketSlateBoard`) + leagues page split into `components/Leagues/` (34/34 harness) + non-WC game
  times · **v0.5.0** props tabs `Slate(games)·Props(board)·Perf·Matchups·Model` (Lines retired) + fast
  lazy slate (`?summary=1` = 4KB/0.1s vs 1.1MB/2.7s; per-game props on open) + `docs/DEV-STANDARDS.md`.

## STANDARDS / DECISIONS (durable — in memory)
- **Perf from the jump** [[feedback_performant_code_from_the_jump]] + `docs/DEV-STANDARDS.md`: a list/board
  must not download more than it renders (summary + lazy-load); measure payload/time; 200 ≠ done. Micah
  had to catch the 1.4MB slate himself — don't repeat.
- **Props display = props.cash/Underdog/PrizePicks market-first + PropChart** (chosen over Bovada
  builder), then split into BOTH a game **Slate** and a market **Props** board.
- **Individual-sport props** [[project_lp_individual_sport_props]]: UFC done, **tennis majors next**
  (missed Wimbledon), Underdog/PrizePicks for projections, historical-stats DB for own projections.
  Game/fight-level props (UFC total-rounds/go-distance, game totals) PARKED (needs nullable-player /
  matchup entity).
- **Prod data must never drop off** [[reference_lp_prod_deploy]]: prod deploy checklist = stand up a
  prod ingest timer + enable prod in the freshness monitor. Prod goes live current+fed+monitored in one
  deliberate pass once the props page settles — NOT now.

## OPEN THREADS
1. Commit v0.5.1 (after verify). 2. Dispatch UFC Predict tab. 3. Esports local-day grouping (get Micah's
go). 4. Eventual: prod deploy (all of v0.4.1→v0.5.x) + prod ingestion + enable prod monitor — deliberate,
when props settles. 5. Tennis majors props (next individual sport). 6. Optional: wire a real push
(Hermes/Telegram) alert on freshness-monitor failure (currently log + self-heal only).
