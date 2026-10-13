# CONTEXT HANDOFF — 2026-07-15 (LP: team stats for 4 leagues DONE + live; MLB changes delegated)

Read first on a fresh context. Supersedes CONTEXT-2026-07-14-HANDOFF.md (that task is DONE).

## TL;DR of this session
1. **Finished "team stats for all 4 leagues"** (the 2026-07-14 active task) — DONE, verified, live.
2. **Fixed 2 frontend bugs** the user hit (sub-view flicker + Stats-tab reverting to Schedule).
3. **Delegated MLB recent-changes to reasonix** (in progress).
4. **Wrote the World Cup props spec.**

## 1. Team stats for 4 leagues — DONE (committed to `dev`)
- Diagnosed that the handoff's "just run the backfill" was WRONG: the new rigorous
  `team_stats_contract.py` (Codex's) is fail-closed and needs a completed-season per-game ingest
  that **did not exist**. Built it: **`backend/backfill_team_parity.py`** — enumerates every
  completed regular-season game via ESPN team schedules, writes reciprocal `team_game_results` +
  paired `team_game_stats` (only games with complete paired stats), + a `team_stats_coverage`
  manifest (expected==fetched, internally consistent).
- User chose **full parity** over a cheaper season-aggregate path (~180 calls, would've left
  NHL possession + NFL opp-yards empty). Ran the per-game ingest:
  **NBA 1227 games/30 teams, NHL 1311/32, NFL 272/32, all status=complete, 0 unpaired.**
- **All 4 leagues now `supported=True` / `measured`** via `/api/{league}/team-aggregates`
  (mlb was already supported off `team_game_results`).
- Schema migration was **additive** (ALTER add `season,status` on results; `run_id`+6 NFL cols on
  stats; unique index; 3 new tables) — **MLB preserved**. Dev DB backed up first:
  `backend/data/picks.dev.db.bak-preteamstats-20260714T203653Z` (integrity ok).
- Frontend: generalized the teams table (was hardcoded MLB RF/RA/Run-Diff) to render per-league
  category tabs + columns from the aggregate response; flipped `supportsTeamStats` to all 4 leagues;
  added `formatTeamMetric` (team cols use number/decimal/percent; percents are 0–1 ratios).
- Commits on `dev`: `9d26772` (parity ingest + tests), `33db392` (merge feat/leagues-hub→dev),
  `5ea84e5` (surface team stats all 4 + flicker fix), `f51debc` (tab-revert fix). **`dev` HEAD = f51debc, clean.**

## 2. The two bugs fixed (both in `pages/leagues/[league].tsx`)
- **Flicker** (`5ea84e5`): the team-aggregates capability fetch had `subView`/`router` in deps and
  nulled data every run → every Players/Teams click hid+reshowed the toggle. Fixed: fetch runs once
  per league/tab, keeps data across refetch, reads sub-view via `subViewRef`.
- **Tab revert / "went to Schedule"** (`f51debc`): the player-leaders effect, after its async fetch,
  wrote default category/stat into the URL by spreading a **stale `{...router.query}`** — clobbering
  the `tab` the click just set → tab-sync effect reverted the tab, unmounting the Stats section.
  Fixed: `queryRef` (always-fresh router.query) for async URL writes; only write while `tab==='stats'`.
  Same hardening on the team-agg error path. **Verified headless: 0/8 bad samples.**

## 3. LIVE / infra state (FINAL — leagues-hub worktree torn down)
- **`lp-leagues-hub` worktree REMOVED** (was a stale preview lacking the Predict/Pick Desk work).
  `:3095`/`:8095` stopped. The old `:3095` tunnel is dead.
- **Complete preview now on `/root/lp-pick-desk`** (FF'd to dev `a537158` == full app):
  **Tunnel → https://pride-alternative-costume-act.trycloudflare.com** → `:3096` (frontend, proxy
  `API_PROXY_TARGET=:8096`) + `:8096` backend (dev DB + esports keys). Serves EVERYTHING: `/predict`
  (Pick Desk), `/leagues` (team stats all 4), MLB "What changed". cloudflared pid ~1066881,
  log `/tmp/cf-3096.log`; backend log `/tmp/pd-backend-8096.log`, frontend `/tmp/pd-frontend-3096.log`.
- Prod containers `:3100/:8100` UNTOUCHED (prod backend still lacks the team-aggregates endpoint —
  team stats are NOT on prod yet; only on `dev` + the dev preview).
- `dev` HEAD = **`a537158`** (team stats + frontend fixes + MLB changes + WC props spec), clean.
- **reasonix** tmux agent: was working in `/root/lp-leagues-hub` (now removed); user stopped it and
  its MLB change is done+merged. To delegate again, use a fresh worktree via
  `scripts/hermes-worktree.sh up <task>` and drive it with `tmux send-keys -t reasonix …`.

## 4. Delegated to reasonix (IN PROGRESS) — MLB recent-changes
- Task file: **`/root/lp-leagues-hub/HERMES-TASK-MLB-CHANGES.md`** (scope-locked to
  `backend/routers/players.py`). Root cause: `_CHANGE_METRICS` has nba/nfl/nhl but no `mlb`, so
  `_change_evidence` returns nothing → no "What changed" panel for MLB.
- **Data constraint** (in the task file): MLB `player_game_logs.stats` only has batting counting keys
  `2B,3B,BB,H,HR,K,PA,TB`. No pitching logs, no Statcast keys. So only **batting** categories
  (`production`, `discipline`) can get change evidence; pitching/Statcast categories can't.
- **VERIFIED (2026-07-15, independent review of the diff):** reasonix added `_CHANGE_METRICS["mlb"]`
  = production→HR/Game (`raw_keys ("HR",)`), discipline→K% via a new guarded `"rate"` spec
  (`numerators ["K"], denominators ["PA"], pct`). It also added a **guarded** `rate_def` branch in
  `_window_value` (`if rate_def:` … else falls through to the original path) — so nba/nhl/nfl are
  untouched, NO regression. players.py is syntactically valid and the endpoint served `200 OK` for
  mlb production per the backend log. It did NOT touch `[league].tsx`. **Change is good.**
- **COMPLETE (user stopped reasonix mid-verify; I finished it):** reasonix had left `:8095` in a bad
  state (500-ing → the `:3095` preview's stats were down). Root cause was the stale process, NOT the
  code — a clean backend restart returned 200. Verified live: `/api/mlb/leaders?type=batting&category=
  production` → HR/Game, 3 changes; `discipline` → K%, 3 changes; nba/nhl/nfl unchanged (3 each, no
  regression). MLB "What changed" panel renders on the page (screenshot confirmed).
  Committed `players.py` only as `8fed102` on `feat/leagues-hub`, then **merged → `dev`** (`9c79437`,
  clean, players.py-only diff). **`dev` HEAD is now `9c79437` and contains EVERYTHING** (team stats +
  both frontend fixes + MLB recent-changes).
- Note: `:8095` backend was relaunched by me (log `/tmp/be8095-new.log`, dev DB + esports keys). The
  `:3095` tunnel now serves the full, healthy hub.

## 5. World Cup props — SPEC written (not started)
- **`docs/SPEC-world-cup-props-2026-07-15.md`** (on `dev`). Props today = Bovada scraper →
  props/prop_games/prop_results, **MLB-only**. WC needs: WC odds source (extend Bovada), `league='wc'`
  prop_games from ESPN WC events, soccer player identity (no roster today), soccer markets +
  settlement (no soccer box-score ingest today). Recommended Phase 1 = **display-only WC lines**
  (goals/shots-on-target/assists), settlement in Phase 2. Open decisions listed in the doc.

## 6. Git reconciliation — DONE
- Everything merged to `dev` @ `a537158` (clean): team stats + both frontend fixes + MLB changes +
  WC props spec. `feat/leagues-hub` merged in (`9c79437`); `lp-leagues-hub` worktree removed.
- `feat/pick-desk` FF'd to dev; lp-pick-desk is the complete preview host (`:3096` + tunnel).
- Branch `feat/leagues-hub` still exists (merged, harmless) — delete if you want a tidy branch list.

## 7. Pre-existing bugs noted (NOT mine, not fixed — flag to user if touching leagues UI)
- Footer says "Not affiliated with the NBA" on NHL/NFL/etc. pages (should match league).
- Standings tab shows **WIN% 0.0%** for every team, and L10 "0 PTS". Codex's standings work.

## Key files
- Ingest: `backend/backfill_team_parity.py` (rerun: `LP_DB_PATH=…/picks.dev.db venv/bin/python
  backfill_team_parity.py --leagues nba,nhl,nfl --delay 0.1`).
- Contract: `backend/team_stats_contract.py` (fail-closed; MLB special-cased, others manifest-gated).
- Frontend: `pages/leagues/[league].tsx` (team table + both bug fixes).
- Tests: `backend/test_backfill_team_stats_fixture.py` etc. — 37 pass (fixed 2 diagnosed failures).
