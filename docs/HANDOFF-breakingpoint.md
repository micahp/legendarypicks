# HANDOFF — scrape breakingpoint.gg for COD match data + player over/under

Onboard: ORIENTATION.md → AGENTS.md → this file. Do NOT commit/push/deploy (CEO owns that).
Recon is already done below — don't re-discover it, build on it.

## Why
1. **COD scoreboard bug:** COD games vanish after they finish. Current source `backend/cdl_client.py`
   reads the official CDL site's live **score strip**, which rolls completed matches off. breakingpoint.gg
   keeps full CDL results, so use it instead — finished matches persist.
2. **Prop page:** breakingpoint.gg has player **over/under L5/L10/L20** hit-rate data. We want to scrape it
   for the prop page (the prop-outcome product). Match data is priority 1; over/under is priority 2.

## Data access (VERIFIED — use this)
- It's a Next.js app. Get the current build id from the homepage, then hit its `_next/data` JSON.
- **All requests need a browser User-Agent** or you get 403:
  `Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36`
- buildId is **dynamic** (changes when they redeploy) — ALWAYS re-extract it per run:
  ```python
  html = GET https://breakingpoint.gg/                      # with browser UA
  buildId = json.loads(<script id="__NEXT_DATA__">...</script>)["buildId"]
  ```
- Matches JSON (VERIFIED 200, ~370KB):
  `GET https://breakingpoint.gg/_next/data/<buildId>/matches.json`
  → `pageProps` with seasons/events and match objects shaped like:
  ```json
  {"id":215002,"status":"upcoming","datetime":"2026-06-26T12:00:00+00:00",
   "team_1_id":4,"team_2_id":6,"team_1_score":null,"team_2_score":null,
   "event_id":109,"round":{"name":"Winners Round 1"},
   "events":{"name":"CDL Major 4 Tournament","division_id":3},
   "team1":{"id":4,"name":"OpTic Texas","logo_darkmode":"...","logo_lightmode":"..."},
   "team2":{"id":6,"name":"Boston Breach",...}}
  ```
  `status` values include `upcoming` (and completed/live variants — confirm the exact strings for finished
  and in-progress matches by inspecting a day that has them). Scores are `team_1_score`/`team_2_score`.
- Backend is Supabase (`dfpiiufxcciujugzjvgx.supabase.co`). The `_next/data` JSON is enough; only fall back
  to the Supabase REST API (anon key is in the JS bundle) if a needed dataset isn't in a `_next/data` page.

## Deliverable 1 (PRIORITY) — COD matches from breakingpoint
- New `backend/breakingpoint_client.py`: `get_cod_matches(date_str=None)` returning the SAME normalized shape
  `cdl_client.get_matches` returns (see its docstring): `game_id, date (ISO Z), state ('pre'|'in'|'post'),
  status, home/away {abbrev, name, score}`. Map breakingpoint `status` → state (completed→post, live/in-
  progress→in, upcoming→pre). `abbrev`: derive a short code from team name (or keep name; the UI shows
  `name` for non-team-sports). Scores from `team_1_score`/`team_2_score` (only when finished/live).
  Date-filter by `datetime`'s UTC date when `date_str` given. Cache ~5 min (mirror cdl_client). Browser UA.
- Wire `sports_service.py` `/api/{league}/games` COD branch to call `breakingpoint_client.get_cod_matches`
  instead of `cdl_client`. Keep `cdl_client` in place as a fallback if breakingpoint fails (try/except).
- **Result to verify:** a COD match that has finished still appears on the scoreboard (state=post, final
  score) — it no longer vanishes. Test: `cd backend && venv/bin/python -c "import breakingpoint_client as b; print(b.get_cod_matches())"`
  and confirm completed matches show with scores.

## Deliverable 2 — player over/under hit-rate data
- Find the player-stats dataset that carries **over/under L5/L10/L20** (try `/_next/data/<buildId>/stats.json`,
  `/players.json`, `/players/<id>.json`, or the `trpcState` queries in a player page's `__NEXT_DATA__`).
- Build `breakingpoint_client.get_player_props()` (or similar) returning per-player, per-prop: the line,
  and hit-rate over the last 5/10/20 maps (over vs under). Store in a new DB table (e.g. `cod_player_props`)
  and expose a read endpoint (e.g. `/api/cod/props`). UI integration is a LATER task — just get the data
  flowing and stored/served for now.

## Constraints (AGENTS.md)
- Backend code runs as `cd /root/legendarypicks/backend && venv/bin/python <script>` (not host py, not container).
- Browser UA on EVERY breakingpoint request. Re-extract buildId each run (it expires).
- Be polite: cache, don't hammer (their data updates slowly).
- **Do NOT commit, push, or deploy.** Build it, test it against real data, write a short note of what you
  changed + how you verified, and hand back. CEO commits/deploys.

## Acceptance
1. `/api/cod/games` returns COD matches INCLUDING finished ones with final scores (the bug is fixed).
2. breakingpoint is the source; cdl_client is a fallback; no crash if breakingpoint is unreachable.
3. (D2) player over/under L5/L10/L20 data is fetched and stored/served from a new endpoint.
