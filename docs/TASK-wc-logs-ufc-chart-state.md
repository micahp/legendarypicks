# TASK (Codex): WC player-log ingest (make the chart work for WC) + clean UFC chart state

Repo **/root/legendarypicks**, branch `dev`. Read `docs/DEV-STANDARDS.md` first and follow it.

## STEP 0 — update your own persistent guidance (do this FIRST, one small edit)
Append a short "Operating rules" section to **`/root/legendarypicks/AGENTS.md`** so future sessions
have it:
- **Never start, kill, or restart dev servers or uvicorn.** A preview frontend runs on **:3096** and a
  backend on **:8096**, managed externally. Verify against them; if a page looks stale, just
  re-request it (HMR recompiles). Spawning duplicates on other ports / killing servers corrupts the
  live tunnel — this happened and must not recur. Never run `kill`/`pkill` on node/uvicorn.
- **Follow `docs/DEV-STANDARDS.md`** — especially: a list/board must not download more than it renders
  (summary + lazy-load on open); measure payload size + time before shipping; 200 ≠ done.
- Do not commit or push (Claude owns git).

## STEP 1 — WC player-log ingest (the real fix)
The props chart (`PropChart`) reads `player_game_logs`; we have none for WC, so WC prop charts are
blank. Populate them from ESPN.
- **New script `backend/ingest_wc_logs.py`**, mirroring `backend/ingest_mlb_logs.py` (structure,
  identity resolution, upsert). Use `espn_client`: `espn.games('wc', date)` to enumerate past World Cup
  matches, `espn.summary('wc', game_id)` for each match's boxscore, and parse **per-player** goals,
  assists, shots, shots-on-target from the ESPN soccer summary (`boxscore.players[*].statistics`).
- Upsert into `player_game_logs`: `league='wc'`, `game_date`, `team`, `opponent`, `home_away`,
  `stats` = JSON stat line **using keys `goals`/`assists`/`shots`/`sot`**, `source='espn'`,
  `source_player_key` = the ESPN athlete id (for the UNIQUE key + re-resolution).
- **Resolve `player_id`** to our existing WC players (created during prop ingest, `players` where
  `league='wc'`) by name match — reuse whatever name-normalization the other ingests use; leave
  `player_id` NULL if unresolved (don't fabricate), but aim to resolve the players who actually have
  props so their charts light up.
- **Add the mapping** in `backend/_core.py` `_MARKET_STAT_KEY`:
  `'wc': {'goals':'goals','assists':'assists','shots':'shots','shots_on_target':'sot','shots_on_goal':'sot'}`.
- **Verify:** run the ingest against the dev DB (`LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db`),
  then `curl 'http://127.0.0.1:8096/api/props/history?player_id=<a WC scorer>&market=goals&line=0.5&side=over&league=wc'`
  returns a non-empty `games` array. Confirm the Props board chart draws for a WC goal prop in the browser.

## STEP 2 — UFC: a last-5-fights form strip (ESPN-style), NOT the chart
UFC props are `win_by_ko/submission/decision` — categorical method-of-victory, not a numeric stat, so
the last-N bar chart has nothing to plot. Instead, for UFC show the **fighter's last 5 fights the way
ESPN does**: a compact form strip, most-recent first, each entry = **result (W/L), method (KO/TKO,
SUB, DEC), opponent, and date** (e.g. `W · KO · Whittaker · 06/26`). Color W green / L red; small,
scannable, in the app's dark/emerald language.
- **Data:** source the fight history from ESPN UFC (`mma/ufc`). Check `espn_client` for a fighter/
  athlete results helper first; if none exists, add one (an athlete event-log / results fetch) or
  ingest past UFC events into a small fights/results store and query the last 5 per fighter. Resolve to
  our `players` (`league='ufc'`) by name, like the WC ingest. Keep it lazy (fetch a fighter's last-5
  only when their row/prop is opened — DEV-STANDARDS: don't bulk-load).
- **UI:** in `components/Props/MarketSlateBoard.tsx`, when the league is `ufc` (market not chartable),
  render this form strip in the chart's place — a small reusable component (e.g.
  `components/Props/FightForm.tsx`). For any OTHER non-chartable/empty case (not UFC), fall back to a
  clean "No history yet" note — never an empty/blank chart box.

## Constraints
- Verify against the running :3096/:8096 (STEP 0 rule). Measure any new endpoint's payload/time.
- New files + additive edits; don't break existing ingests or the board's other markets.
- Report: files changed, the WC-history curl result, and the browser check. Do NOT commit/push.

---
## QUEUED NEXT (after this task lands): UFC Predict tab
Add a **Predict** tab to the UFC league page (`pages/leagues/[league].tsx` / `components/Leagues/`,
alongside Rankings + Schedule). Fight pick'em for upcoming UFC cards — pick winners (and likely method),
in the spirit of the existing `/predict` esports pick'em. Reuses the UFC schedule + the fight data from
this task. Full spec to be written when dispatched.
