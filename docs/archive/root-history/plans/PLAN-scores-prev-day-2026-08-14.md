# PLAN — "previous day on /scores shows today again" + the 500 behind it

**For:** the next agent. **Reported by Micah 2026-08-14 on dev.** Nothing here is fixed yet.
**Branch:** cut a fresh worktree off `dev`. Do NOT work in `/root/legendarypicks` directly.

---

## 0. Read this first — there are TWO defects and they are probably related

**Defect A (Micah's report, PRIMARY):** on `/scores`, clicking `‹` (previous day) shows
today's games again instead of the previous day's.

**Defect B (I confirmed this one, 2026-08-14):** `GET /api/{league}/games?date=X` returns
**HTTP 500** for any date outside the backend's short in-process TTL cache.

Measured on production (`:8100`) at 12:2x:

| date | result |
|---|---|
| 2026-08-13 → 08-10 | 200 (in TTL cache) |
| 2026-08-09 and older | **500** |

The traceback in `docker compose logs backend-1`:

```
urllib.error.HTTPError: HTTP Error 403: Forbidden
```

**Cause of B:** `backend/routers/games.py`, in `get_games`:

```python
try:
    games = espn.games(league, date)
except ValueError as e:
    raise HTTPException(404, str(e))
```

The scoreboard is a **live ESPN read on every request**. Only `ValueError` is handled.
An `HTTPError` propagates and FastAPI renders it as a 500.

**Why ESPN is 403ing:** I exhausted the per-host request budget on 2026-08-14 (linker runs,
team-vocabulary probes, settlement). The block is a COUNT per host and outlives a short
backoff. It will lift on its own. **Do not "fix" B by hammering ESPN to test it** — stub the
client instead (see §3). Read `.claude/skills/espn-request-budget/SKILL.md` before ANY
fetch loop; that skill is the thing I failed to load, and this outage is the result.

**Why B probably causes A:** `services/sports.ts::getGamesByLocalDate` fetches a **two-day
window** (the local date plus its timezone neighbour) and, when not called with
`{strict:true}`, **swallows per-date failures and returns `[]` for the failed date**:

```ts
} catch (err) {
  if (opts?.strict) throw err
  return { d, games: [] as Game[] }
}
```

`pages/scores.tsx` calls it WITHOUT `strict`. So on a past date: the past date 500s and is
silently dropped, the neighbour date may succeed, and the page paints whatever survived —
which can be today's slate. That matches the symptom exactly. **Verify this before fixing
it; do not take my word for it.**

---

## 1. Reproduce A first, and prove the mechanism

Use a real browser. `curl` cannot see this — the page is client-rendered.

```bash
cd /root/legendarypicks
node -e '
const { chromium } = require("./node_modules/playwright");
(async () => {
  const b = await chromium.launch(); const p = await b.newPage();
  p.on("response", async r => { if (r.status() >= 400) console.log("HTTP", r.status(), r.url()); });
  await p.goto("http://127.0.0.1:3096/scores", { waitUntil: "networkidle" });
  await p.click("[aria-label=\"Previous day\"]");
  await p.waitForTimeout(4000);
  console.log((await p.innerText("body")).slice(0, 1200));
  await b.close();
})();'
```

Answer these, with evidence, before changing a line:

1. After the click, what date does the header show, and which `/api/.../games?date=` calls
   fire, with what statuses?
2. Are the rendered games actually today's, or is the board empty and the *header* wrong?
   These are different bugs and the fix differs.
3. Does it still reproduce when the backend returns 200 for that date? Stub ESPN (§3) so a
   past date succeeds, then retry. **If A disappears when B is fixed, A is a symptom of B**
   and the ranked hypotheses below mostly evaporate.

## 2. Ranked hypotheses for A — measure, do not assume

- **H1 (most likely): A is a symptom of B.** Past-date fetch 500s → swallowed → the
  surviving neighbour-date games (today's) render. Test by fixing B first.
- **H2: field-name mismatch in the local-day filter.** `getGamesByLocalDate` computes
  `localDayOf(g.startTime)`, but the backend serves the field as `date`
  (payload keys are `game_id, date, state, completed, status, home, away, …`). If the
  mapping in `getGamesByDate` does not populate `startTime`, `day` is `null` and the filter
  falls through to `d === localDate` — the *bucket* rather than the game's real local day.
  Check whether `startTime` is actually populated; this is a one-line check and a real trap.
- **H3: `pages/scores.tsx` state.** `shiftDay(-1)` reads correct on its own, and the
  `router.query.date` effect only assigns when the query param matches `YYYY-MM-DD`, so
  neither obviously resets to today — but confirm with a render, since the effect array is
  `[router.query.date, router.query.league]` and `date` is not in it.

## 3. Fix B — and this is the part that must not regress

Two changes, both in `backend/routers/games.py`:

1. **Never 500 when the publisher refuses.** Catch the non-`ValueError` case around
   `espn.games(...)` and degrade instead of raising.
2. **Fall back to our own database.** We hold these games. On production,
   `team_game_results` had **all 8 MLB games for 2026-07-20** while that exact date was
   returning 500. Serve them (`league, game_date, team, opponent, home_away, score_for,
   score_against, status`); the shape needs `game_id, date, state, completed, status,
   home{abbrev,score}, away{abbrev,score}` at minimum. If the DB has nothing either,
   return `[]` — the UI already renders an honest empty state. **A 500 takes down every
   league page at once; "no games" is wrong about at most one day.**

I started this edit and reverted it because it called a `_games_from_db` helper I had not
written yet — do not go looking for it, it does not exist. `git log` has no trace; the tree
is clean.

Note the existing comment above that block ("DB-first, no ESPN on the request path") is
true only of the **final score**, not the schedule. Fix the comment too or it will mislead
the next person exactly as it misled me.

## 4. The gate — this is the actual ask

Micah's words: *"we have to have a way of making sure we never deploy something with this
defect again."* A fix without this is not done.

**Add a test that stubs the ESPN client to raise `urllib.error.HTTPError(403)` and asserts
`/api/{league}/games` does NOT return 5xx** — for a past date, today, and a future date.
Every existing test mocks ESPN *succeeding*, which is why a total publisher outage was
never exercised. Do the same for `/api/coverage`, `/api/{league}/schedule-dates` and
`/api/{league}/strength` — the browser showed all four 500ing together.

Assert the **status code and the shape**, not just "no exception". A 200 with a fabricated
game is worse than a 500.

**Second gate, higher value:** a page-level check that the previous-day arrow changes the
rendered slate. A backend test would not have caught A. Something that renders `/scores`,
clicks `‹`, and asserts the game set differs from today's. If that is too slow for the
suite, make it a `verify-gates.sh` entry — but per
`.claude/skills/fail-loudly` and the presence-is-not-integrity memory, **it must fail
closed**: if it cannot render, that is FAIL, not skip.

## 5. Scope

**You may touch:** `backend/routers/games.py`, `services/sports.ts`, `pages/scores.tsx`,
new test files, `verify-gates.sh`.

**Do NOT touch:** `backend/settlement.py`, `backend/link_prop_games.py`,
`backend/core_*.py`, `backend/pregenerate_game_stories.py`, `scripts/game-recaps.sh`,
`scripts/run_pipeline.py` — all changed today and all merged; leave them alone.
No `/etc`, systemd, cron. No `git push`. No writes to `backend/data/picks.db` (PROD) —
read-only with `mode=ro` if you need to check coverage.

## 6. Environment

- Dev DB: `LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db`. Copy it with
  `sqlite3 .backup`, **never `cp`** — a raw `cp` of a live SQLite file produced a copy that
  failed integrity today.
- Set `LP_ESPN_CACHE_DIR` for anything that fetches.
- Dev is `3096`/`8096` and is **externally managed — do not restart it**.
- Full suite on canonical dev is currently **1429 passed, 0 failed**. Any failure you see
  beyond that is yours.

## 7. Ping when ready — do not wait to be asked

`tmux send-keys -t money:0.0 'agent: scores prev-day — <one line status>'` then a separate
`Enter`. Ping when you have the §1 answers even if you have not fixed anything yet: the
reproduction is the valuable part and Micah wants to know what it actually is before a fix
lands.
