# HANDOFF — Props page: default to today + date navigation

Onboard: ORIENTATION.md → AGENTS.md → this file. Do NOT push/deploy (CEO owns git + live).

## Problem
The Props page shows props from previous days. The Lines tab and the Slate tab both render
**every** prop in the DB regardless of date, so stale lines from prior days pile up. It should
**default to today's slate** and let the user step back (and forward) by date, like the Scoreboard
(`pages/scores.tsx`) already does.

## Root cause (already located — don't re-investigate)
- `pages/props.tsx`: `LinesTab` fetches `/api/props?limit=100&...` and `SlateTab` fetches
  `/api/props/slate?...` — **neither passes a `date`**, so the backend returns all rows.
- Backend `backend/sports_service.py`:
  - `/api/props/slate` (`props_slate`) ALREADY supports `date` and filters by **game date**
    (`pg.date = ?`). Correct semantic. No change except confirm.
  - `/api/props` (`list_props`) supports `date` but filters by **`p.captured_at`** (scrape time),
    which is the wrong/ inconsistent semantic. Change it to filter by **game date** to match slate
    (a prop for tonight's game scraped earlier still belongs to today).

## The change

### A. Backend — `backend/sports_service.py`, `list_props` (`/api/props`)
- Add `JOIN prop_games pg ON pg.id = p.game_id` to the query.
- Replace the existing `captured_at`-based `date` filter with a **game-date** filter:
  when `date` is provided → `AND pg.date = ?` (param = the `YYYY-MM-DD`).
- Keep `ORDER BY p.captured_at DESC` and the existing player/market/league filters.
- Edge: props with `game_id IS NULL` can't be dated to a slate — with a `date` filter active they
  fall out via the inner JOIN (acceptable). Leave the no-date behavior (all props) unchanged.

### B. Frontend — `pages/props.tsx`
- Add **page-level `date` state**, default today: `new Date().toLocaleDateString('en-CA')`.
  Mirror `pages/scores.tsx` exactly for the mechanics (it's the proven pattern):
  - noon-anchored `shiftDay(delta)` (`new Date(date + 'T12:00:00')` to dodge TZ rollover),
  - `goToday()`, `isToday`,
  - optional deep-link: read `?date=YYYY-MM-DD` from the router on mount.
- Add a **`‹ date ›` navigator** component — copy the markup/classes from `scores.tsx`
  (the `<` button, the weekday/month/day label, the "Jump to today" link, the `>` button;
  lines ~138–166 there). Keep the existing dark styling.
- **Show the date nav only on the `lines` and `slate` tabs** (the date-scoped views). Do NOT show it
  on `performance` / `matchups` / `model` — those are player-centric / cross-time analytics, not a
  single-day slate.
- Pass `date` into `LinesTab` and `SlateTab`; in each, add `params.set('date', date)` to the fetch
  and include `date` in the `useEffect` deps so they refetch when it changes.
- Result: on load → only today's props; back arrow → prior day; "Jump to today" → today.
- The existing empty states ("No props found…", "No games on the board…") already cover empty/past
  days — no new copy needed.

## Constraints (AGENTS.md)
- Backend scripts run ONLY as `cd /root/legendarypicks/backend && venv/bin/python <script>` (not host
  python, not the container) — but this task is API + UI, no ingest script needed.
- `next build` MUST compile before you hand it back. Verify the Props page **renders real data** (not
  just HTTP 200) for BOTH today and a chosen past date that has props.
- Never hardcode the API host in `services/` — base stays relative `/api`.
- **Do NOT commit, push, or deploy.** Make the edits, build, write what you changed + how you verified
  to a short note, and hand back. CEO commits and deploys.

## Acceptance
1. Props Lines + Slate default to **today**; previous-day props no longer show by default.
2. A working back/forward date navigator on Lines + Slate; "Jump to today" returns to today.
3. `/api/props` filters by game date (consistent with `/api/props/slate`).
4. `next build` compiles; both tabs render real data for today and for a past date with props.

## Gherkin (seed — extend)
```gherkin
Scenario: Props default to today
  Given props exist for today's games and for prior days
  When I open the Props page
  Then only props for today's games are shown

Scenario: Step back a day
  Given I am on the Props Lines tab
  When I click the previous-day arrow
  Then I see props for the prior day

Scenario: Jump back to today
  Given I navigated to a past day on the Slate tab
  When I click "Jump to today"
  Then today's slate is shown

Scenario: Analytics tabs are not date-scoped
  When I open the Performance tab
  Then the date navigator is not shown
```
