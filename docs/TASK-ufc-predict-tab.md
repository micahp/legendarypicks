# TASK (Codex): UFC "Predict" tab — fight pick'em on the UFC league page

Repo **/root/legendarypicks**, branch `dev`. Read `docs/DEV-STANDARDS.md` and `AGENTS.md` first, follow both.

## OPERATING RULES (read before anything)
- **Dev servers are externally managed and already running: frontend `:3096`, backend `:8096`.**
  **NEVER start / kill / restart a dev server or uvicorn. Never run `kill`/`pkill` on node or python.**
  Verify against the running services; if a page looks stale, just re-request it (HMR recompiles).
- **Follow `docs/DEV-STANDARDS.md`:** lazy-load, a list must not download more than it renders,
  **measure every new endpoint's payload size + time**, and **HTTP 200 is not proof it works** — verify
  real data in the response and in the browser.
- **Do NOT commit or push. Claude owns git.** Report files changed + verification output when done.

## GOAL
Add a **Predict** tab to the UFC league page (`/leagues/ufc`), alongside the existing **Rankings** and
**Schedule** tabs. It is a **fight pick'em** for the upcoming UFC card — the user picks the **winner** of
each fight (and, secondarily, the **likely method**: KO/TKO, SUB, or DEC). It mirrors the existing esports
pick'em at `/predict` in spirit and mechanics (anonymous device-id picks, crowd reveal after picking,
a win/loss record + streak). Winner is the graded, record-driving pick; method is a secondary bonus call.

## REFERENCE — mirror these, do NOT edit them
- **`backend/routers/esports/picks.py`** — the pick'em backend to mirror: `esports_picks` table,
  `POST/DELETE /api/esports/picks`, `GET /api/esports/picks/me`, `GET /api/esports/crowd`,
  `settle_finished()` lazy grading, and the **crowd-disagreement scoring** (a pick almost nobody made
  pays ~2, a near-unanimous "lock" pays ~1, wrong pays 0, void doesn't touch the record). Reuse the SAME
  scoring semantics for UFC. **Do not modify esports code or the `esports_picks` table.**
- **`pages/predict.tsx`** — the frontend pick'em pattern to mirror: device id via `lib/deviceId.ts`
  `getDeviceId()` sent as the `X-Device-Id` header, load upcoming + my picks, submit a pick, reveal crowd
  after picking, render record/streak. Reuse the app's dark/emerald visual language.
- **Upcoming fights source:** `GET /api/ufc/games?date=YYYY-MM-DD` already returns a card's fights with
  `game_id`, `date`, `state` (`pre`/`in`/`post`), `home`/`away` = `{id,name,abbrev,record,winner}`,
  `event`, `card_segment`. Post-fight, the winner side has `winner: true`. Method for a finished fight
  comes from the v0.5.1 helper `espn.ufc_fight_history` / `espn._ufc_method` (`KO/TKO`, `SUB`, `DEC`).

## BACKEND (new file + one registration edit)
Create **`backend/routers/ufc_picks.py`**, structurally mirroring `routers/esports/picks.py`:
- **Table `ufc_picks`** (create-if-not-exists in an `_init_db()` like esports):
  `id`, `device_id TEXT NOT NULL`, `fight_key TEXT NOT NULL` (= ESPN `game_id`), `pick_side TEXT CHECK
  (pick_side IN ('home','away'))`, `pick_method TEXT` (nullable: `'KO/TKO'|'SUB'|'DEC'`),
  `created_at INTEGER`, `lock_at INTEGER`, `settled_at INTEGER`, `result TEXT`, `method_result TEXT`
  (nullable bonus flag), `points REAL`, `crowd_share_at_lock REAL`, `UNIQUE(device_id, fight_key)`.
  Also snapshot the picked fighter's name/opponent for display (either extra columns or resolve on read).
- **Endpoints** (all read `X-Device-Id`, return the same JSON shapes as esports where analogous):
  - `GET  /api/ufc/upcoming` — the **next upcoming UFC card's** scheduled fights (`state='pre'`). Scan
    forward from today with `espn.games('ufc', date)` until you hit the first date that has fights; cap the
    scan window (e.g. 21 days) so it never loops. Return a compact list (fight_key, date, event,
    card_segment, home/away name+record+id, lock time = fight start). **Do not dump full boxscores.**
  - `POST /api/ufc/picks` — body `{fightKey, side('home'|'away'), method?('KO/TKO'|'SUB'|'DEC')}`;
    INSERT OR REPLACE an unsettled pick; reject once the fight is locked/started.
  - `DELETE /api/ufc/picks?fightKey=...` — remove an unsettled pick.
  - `GET  /api/ufc/picks/me` — this device's picks + `record {wins,losses,voids,streak}`; call a lazy
    `settle_finished()` first.
  - `GET  /api/ufc/crowd?fightKey=...` — `{countHome,countAway,total,shareHome}` for the crowd reveal.
  - `settle_finished()` — for finished fights (`/api/ufc/games` post-state `winner`), set winner
    `result` (win/loss) and crowd-disagreement `points` exactly like esports; set `method_result` as a
    best-effort bonus from ESPN's finished method (null if unavailable — never penalize a missing method).
- **Register it:** in `backend/sports_service.py`, add `ufc_picks` to the `from routers import ...` line
  and add `app.include_router(ufc_picks.router)`. This is the ONLY backend edit outside the new file.

## FRONTEND (new component + hook + three small wiring edits)
- **New `components/Leagues/PredictTab.tsx`** — the fight pick'em tab. Per fight: two winner buttons
  (home/away fighter, with record), a small method selector (KO/TKO · SUB · DEC, optional), and — once the
  user has picked — the crowd split for that fight. Header shows the device's record + streak. Lock/disable
  a fight once it has started. "No upcoming UFC card" empty state when `/api/ufc/upcoming` is empty.
  Mirror `pages/predict.tsx` for device-id + fetch/submit patterns; match the app's dark/emerald system,
  `tabular-nums`, existing tab styling.
- **New `components/Leagues/hooks/useUfcPredictData.ts`** — mirror `useUfcRankingsData.ts`: gated on
  `isUFC` + `activeTab === 'predict'`; loads `/api/ufc/upcoming` + `/api/ufc/picks/me`, exposes submit +
  crowd fetch. Lazy: only fetch when the Predict tab is active.
- **Wiring (small, surgical):**
  1. `components/Leagues/types.ts` — add `'predict'` to the `HubTab` union.
  2. `components/Leagues/hooks/useLeagueRouteState.ts` — UFC `validTabs` becomes
     `['rankings', 'schedule', 'predict']`.
  3. `pages/leagues/[league].tsx` — add `'predict'` to `TAB_LABELS` (label `'Predict'`) and render
     `{route.activeTab === 'predict' && <PredictTab ... />}` wired to the new hook, exactly like the
     `rankings` branch.

## CONSTRAINTS (scope lock)
- **Touch ONLY:** new `backend/routers/ufc_picks.py`, new `components/Leagues/PredictTab.tsx`, new
  `components/Leagues/hooks/useUfcPredictData.ts`, and the small edits to `backend/sports_service.py`,
  `components/Leagues/types.ts`, `components/Leagues/hooks/useLeagueRouteState.ts`,
  `pages/leagues/[league].tsx`. **Do not edit** esports code, props code, `espn_client.py`, or any shared
  util. Additive only; don't change existing tabs' behavior.
- Non-UFC league pages must be unaffected (Predict tab is UFC-only).

## VERIFY (against the running :3096 / :8096 — do not restart anything)
1. `curl -s -w '\n%{size_download}b %{time_total}s\n' http://127.0.0.1:8096/api/ufc/upcoming` — non-empty
   list of the next card's fights; note payload + time.
2. `POST` a pick with a real `fightKey` from step 1 + a device id header, then `GET /api/ufc/picks/me`
   with the same header shows it back; `GET /api/ufc/crowd?fightKey=...` returns counts.
3. In the browser on `/leagues/ufc`: the **Predict** tab appears next to Rankings/Schedule, lists the
   upcoming card, a pick registers + reveals the crowd, and the record updates. Confirm other leagues'
   pages (`/leagues/nba` etc.) are unchanged and `/leagues/ufc` Rankings + Schedule still work.
4. Report: files changed, the two curl payload/time numbers, and the browser check. Do NOT commit/push.
