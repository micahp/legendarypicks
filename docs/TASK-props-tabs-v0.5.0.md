# TASK (Codex): props page tab restructure → v0.5.0

Repo **/root/legendarypicks**, branch `dev` (currently at v0.4.5). Frontend-only (no backend changes
needed — the endpoints already exist).

## ENVIRONMENT RULES — READ FIRST (this broke last time)
- A frontend dev server is ALREADY running on **:3096** (serving this repo) and a backend on **:8096**.
  **Use them for verification.** Do **NOT** start, kill, or restart ANY dev server or uvicorn — last
  run you spawned duplicates on 3097/8095 and killed servers, which corrupted the tunnel. If a page
  looks stale, just re-request it; HMR will recompile. Never run `kill`/`pkill` on node or uvicorn.
- Do NOT commit or push (Claude owns git). Report a diff summary + verify output when done.

## Goal — rename + restore, so the taxonomy is honest
Right now the tab called **Slate** is actually the cross-game props board, and there's no real slate.
Fix the tabs in `pages/props.tsx`:

1. **Rename the current board tab from "Slate" to "Props".** The `MarketSlateBoard` component stays
   exactly as-is — only its tab key/label becomes "Props".
2. **Add a real "Slate" tab = the day's GAMES** (game-based). Render `GET /api/props/slate` (already
   returns games grouped, each with `home/away/date/start_time/league/prop_count/players`). Show the
   games as a list/board grouped by date — matchup, kickoff time, league, prop count — and let the user
   open a game to see its props. **Reuse `components/Game/GameProps.tsx`** for the per-game props if it
   fits (inline expand or a panel); otherwise render the game's `players[]→props` inline. This is
   essentially the game-grouped slate that existed BEFORE the market board (see git history of
   `SlateTab` in `pages/props.tsx` pre-v0.4.5 for the date-grouping pattern).
3. **Retire the "Lines" tab** — remove it from the tab bar and drop the `LinesTab` usage (the market
   board supersedes it). If player-search is worth keeping, fold it into the Props board as a filter;
   otherwise just remove it.

Final tab order: **`Slate · Props · Performance · Matchups · Model`**.

## Keep intact
- `MarketSlateBoard`, `PropChart`, Performance/Matchups/Model tabs, the League pills, the nearest-date
  default, the app's dark/emerald visual language + tabular-nums.

## Verify (against the EXISTING :3096 / :8096 — do not spawn servers)
- `/props` renders: Slate tab shows today's games (MLB + WC + UFC) grouped by date with times; opening a
  game shows its props; Props tab shows the market board; no Lines tab; no console errors; no 390px
  overflow.
- `curl http://127.0.0.1:8096/api/props/slate` already returns the games — the Slate tab consumes that.
