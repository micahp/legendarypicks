# TASK — Rebuild `/scores` on the ESPN model: top events, DB-primary schedule, calendar-aware navigation

**Opened** 2026-08-14 (Micah, after the ESPN outage took every past-date scores page down).
**Status:** not started. Nothing below is built except where §2 says "already exists".
**Prereq:** merge `ec5872e` from `/root/lp-scores-prev-day` first — this task builds on the
DB path it introduced. See `PLAN-scores-prev-day-2026-08-14.md`.

Related: `TASK-deepseek-offpeak-scheduling.md` (the cron-cost half of "stop doing expensive
work on the request path"). Skills that govern this work: `.claude/skills/espn-request-budget`,
`.claude/skills/honest-data-ui`, `.claude/skills/fail-loudly`.

---

## 1. Why — measured, not assumed

The schedule has **no DB path**. Every schedule read is a live ESPN call, and has been since
the service was built (`7668c5e`, June 2025, "Use sportsipy for live data"). Measured on prod
2026-08-14, all cache-warm:

| endpoint | time |
|---|---|
| `/api/mlb/strength` (DB-backed) | **0.10s** |
| `/api/mlb/games?date=2026-08-14` | 0.56s |
| `/api/mlb/games?date=2026-08-13` | 0.61s |
| `/api/mlb/schedule-dates` | 1.11s |

The 5–10× gap between `strength` and everything touching ESPN **is** the finding. Three
things compound it:

1. **Per-request live fetch.** No DB serving of the schedule at all — which is exactly why a
   403 became a 500 rather than a slightly-stale page.
2. **The board fans out to 11 leagues** (`pages/scores.tsx:155`: nba, mlb, nhl, nfl, lcup,
   mls, atp, wta, cod, ufc, wc), each fetching a **two-day window** for timezone reasons
   (`services/sports.ts:305`) — up to **22 upstream calls for one day change**. Parallel, so
   you wait on the slowest, not the sum, but you *spend* all 22 against the host budget.
3. **`schedule-dates` walks up to 8 date ranges per direction, sequentially**, breaking early
   once it finds a game. In-season MLB breaks on the first window — hence 1.1s. An
   out-of-season league cannot break early and walks the whole ladder. NFL and NCAAF in
   August are the worst case, and nobody noticed because those pages look empty anyway.

**The consequence, observed today:** ESPN refused for roughly ten minutes (first 403 ~17:10
UTC, recovered ~17:20). That ten-minute upstream hiccup took **every past-date scores page**
down. A finished game's score never changes. There is no reason to ask ESPN for it twice,
let alone on every page view.

Per `espn-request-budget` §1: the limit is a **request COUNT per host, not a rate**. Pacing
does not help. The only lever is issuing fewer requests. This task is that lever applied to
the highest-traffic surface we have.

## 2. What ESPN does, and what we already have

Micah's spec, from how espn.com actually behaves:

| ESPN behaviour | our state |
|---|---|
| Home scores page is **"Top Events"** — a curated subset, not every game in every league | ❌ we render every game from 11 leagues |
| Top Events has a **"show all" link** out to the full slate | ❌ |
| Top Events has **no date picker** — it is today, full stop | ❌ we put a day navigator on it |
| Prev/next moves to **the next day that league actually has games**, not calendar ±1 | ❌ calendar ±1 |
| **Week-grouped leagues** (NFL, and NCAAF) — one page is a week, not a day | ⚠️ **already built** for NFL, on the league page only |

**Do not rebuild what exists.** Two contracts already do most of the hard part:

- **`docs/API-nfl-schedule-weeks-v1.md`** — `GET /api/nfl/schedule-weeks` and
  `/api/nfl/schedule-week`. Returns ESPN's own phase/week calendar with stable
  `{season_type}:{week}` keys, publisher labels (`Hall of Fame Weekend`, `Preseason Week 1`),
  `default_week_key` and `default_reason` (`current` / `next` / `latest`). Consumed today by
  `pages/leagues/[league].tsx` only. **This is the week-navigation primitive — reuse it.**
  Note its rule: render the supplied label; never reconstruct preseason/postseason labels
  from week numbers.
- **`docs/API-league-schedule-dates-v1.md`** — `GET /api/{league}/schedule-dates` already
  discovers the neighbouring dates that *have* games. **This is the jump-to-next-day-with-games
  primitive.** It does not need inventing; it needs to be made cheap (§3.3) and wired into
  the navigator instead of the `date ± 1` arithmetic in `pages/scores.tsx`.

## 3. The work

Five workstreams. W1 is the one that removes the outage class; do it first.

### W1 — Completed days become DB-primary, not a fallback

`ec5872e` added `_games_from_db()` in `backend/routers/games.py`, which serves completed
games out of `team_game_results` when ESPN raises. It is correct and strict: it requires a
matched home/away pair with reciprocal scores (`home.score_against == away.score_for`) and
**rejects** partial or contradictory pairs rather than rendering them, logging what it
dropped. Day-precision data stays day-precision instead of getting a fabricated kickoff time.

**Change: stop treating it as a fallback.** Route by the date, not by whether ESPN failed.

```
date <  today (league-local)  → DB first. ESPN only if the DB has no rows for that day.
date == today                 → ESPN (live scores), DB fallback as ec5872e already does.
date >  today                 → ESPN (schedules move; see W4).
```

A past date that the DB can answer must issue **zero** ESPN requests. That is the whole point.

Honesty requirements (`honest-data-ui` §1, `fail-loudly`):

- A past day where the DB has **no rows** is `unknown`, not "no games". Say "we have no record
  of this day" — never render an empty board that reads as "nothing was played".
- Keep the `X-LP-Data-Source` response header `ec5872e` introduced (`espn` /
  `team_game_results` / `unavailable`). It is how W5's gate tells the two paths apart.
- Do not backfill a missing day by fanning out to ESPN on the request path. Queue it for the
  refresher (W4).

### W2 — Top Events on `/scores`

Replace the 11-league fan-out with a single **Top Events** view for today.

- **One request**, not 22. Add `GET /api/top-events?date=…` that assembles the slate
  server-side from the DB plus one live pass, so the browser makes one call.
- **Selection must be stated on the surface.** This is a curated subset and the user has to
  know it. Label it *Top events* with a visible, honest rule — not an unexplained ranking.
  Start with the simplest defensible rule and write it down in the contract doc:
  live games first, then games with the most settled props (our actual differentiator),
  then by start time. **Do not** ship an opaque "quality" score.
  Per `a-seed-is-a-ranking-key`: a tie must not fall through to recency by accident — define
  the full ordering including the tiebreak.
- **"Show all" link** to the full slate (the existing full board, kept and reachable).
- **No date picker on Top Events.** It is today. Date navigation lives on the full slate and
  on the per-league pages, where the calendar model in W3/W4 applies.

### W3 — Date navigation jumps to days that have games

On the full slate and league pages, replace `date ± 1` with the `schedule-dates` result.

- `pages/scores.tsx` `shiftDay()` currently does calendar arithmetic. It must instead take
  the next entry from `past_event_starts` / `future_event_starts`.
- The 8-range sequential walk that costs 1.1s must be answered from the DB for past dates and
  from a cached/refreshed calendar for future dates (W4). **`schedule-dates` must not walk
  ESPN on the request path.**
- Out-of-season leagues are the worst case today and must be the cheapest after: if the
  calendar says the league has no future games, that is a one-row answer, not a 370-day walk.
- Preserve `ec5872e`'s strictness — navigation clears stale cards rather than leaving the
  previous day's board on screen, and partial vs full load failure stays distinguishable.

### W4 — Week-grouped leagues, and keeping the calendar fresh

**Week grouping.** NFL — and NCAAF, which is the same shape — navigate by week, not day.
Reuse `/api/nfl/schedule-weeks` (§2). Generalise the contract to
`/api/{league}/schedule-weeks` with `navigation: "week" | "day"` in the response so the
frontend asks the league which model it uses instead of hardcoding a list. Every other league
returns `navigation: "day"` and the existing path.

**Freshness — schedules do change.** This is the real objection to caching, and it is handled
by *who* refreshes, not by refreshing on every page view:

- **Completed days are immutable.** A final score does not change. Never re-fetch.
- **Today and the next N days** get refreshed by a scheduled job that writes to the DB, so
  the request path always reads local. Postponements, moved kickoffs and added games land on
  the next refresh cycle.
- **Beyond that horizon**, refresh daily — a Week 14 kickoff time moving in August is not
  a user-visible problem for a page nobody is looking at.
- Publish the refresh time on the surface when serving from cache, so a stale schedule is
  visible rather than silent (`fail-loudly`).
- Budget the refresher explicitly per `espn-request-budget` §6: **state the per-host request
  count before running it, and print the count actually spent.** Set `host_budget` in the
  function that does the work, not in `main()` — that exact mistake cost a day on 2026-08-04.

### W5 — Prove it, and keep it proved

Numbers to record before and after, measured **through the path that runs** (per
`same-ruler-for-before-and-after` — measure the served endpoint, not a function in isolation):

| measure | today | target |
|---|---|---|
| ESPN requests to load `/scores` for **today** | up to 22 | ≤ 2 |
| ESPN requests to load `/scores` for a **past** day | up to 22 | **0** |
| `/api/{league}/games?date=<past>` p50 | ~0.6s (warm) | < 0.15s (DB path) |
| `/api/{league}/schedule-dates` p50 | 1.1s (in-season, warm) | < 0.15s |
| `/scores` availability while ESPN 403s all past dates | **broken** | **serves** |

Gates:

- An **outage gate** — with the publisher stubbed to raise, past-date scores must still
  serve, and the response must carry `X-LP-Data-Source: team_game_results`. `ec5872e` already
  ships `backend/test_games_publisher_outage.py`; extend it to assert the *primary* path, not
  just the fallback.
- A **request-count gate** — assert that a past-date request issues **zero** calls to any
  ESPN host. This is the assertion that stops the regression, and it must fail loudly.
  Per `a-green-gate-is-a-claim-about-its-surface`: assert the count, not that the page
  returned 200.

## 4. Files

- `backend/routers/games.py` — `get_games`, `get_schedule_dates`, `_games_from_db`,
  `_final_score_from_db`, `_schedule_candidates`, `_cap_schedule_candidates`
- `pages/scores.tsx` — fan-out (`:155`), `shiftDay`/`goToday`, the day navigator
- `services/sports.ts` — `getGamesByLocalDate` (`:305` two-day window), the NFL week calls
  (`:482`, `:492`)
- `pages/leagues/[league].tsx` — existing week navigation to generalise
- `docs/API-nfl-schedule-weeks-v1.md`, `docs/API-league-schedule-dates-v1.md` — contracts to
  extend; write the Top Events contract as `docs/API-top-events-v1.md` in the same style
- New: the schedule refresher job + its systemd timer (schedule it per
  `TASK-deepseek-offpeak-scheduling.md` §4 conventions — pin the timer in **UTC**)

## 5. Order, and what "done" means

1. **W1** — past dates DB-primary. Removes the outage class outright. Ship alone.
2. **W3** — navigation jumps to real game days. Depends on W1 making it cheap.
3. **W4** — week model generalised + the refresher. The freshness answer.
4. **W2** — Top Events. The largest UI change; do it once the data path is cheap.
5. **W5** — gates land *with* each workstream, not after (`fix-gates-before-the-code`:
   commit the expected values first, so any weakening shows up in git).

Done means: measured before/after in this doc through the served endpoint, the outage gate
and the request-count gate green, and a real browser render of `/scores` on a past date with
ESPN blocked — not a 200 from curl.

## 6. Open questions for Micah

1. **Top Events selection rule.** Proposed: live → most settled props → start time. Settled
   props is the honest differentiator (it is the thing we have that ESPN does not), but it
   biases toward MLB, which has by far the most. Acceptable, or weight by league?
2. **How many leagues on Top Events**, and does an empty league disappear or show as empty?
3. **NCAAF is deliberately dark** (ROADMAP, 2026-08-11). Build its week navigation now while
   the NFL work is open, or leave the hook and wire it when NCAAF ships?
