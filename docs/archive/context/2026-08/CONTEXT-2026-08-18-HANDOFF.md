# 2026-08-18 handoff — scoreboard past days, the arrows, and auditing the split sweep

Previous: [2026-08-17 summary](/root/legendarypicks/docs/CONTEXT-2026-08-17-SUMMARY.md).
Branch `dev`, **26 commits unpushed**, 8 of them mine. **Nothing deployed to prod.**
Only `backend/data/esports_team_logos.json` is left uncommitted, and it is not mine.

> A `git commit` inside a chained cell printed "committed" and did not commit. Check
> `git log`, not the echo.

---

## §1 The one shape of the day

**"Never ask twice" got implemented as "never ask at all", with nothing to fill the gap.**

It appeared in three places, and it is the thing to check first if the board looks empty again:

| Where | The rule as written | What it actually did |
|---|---|---|
| `/api/{league}/games` | a finished day is never worth a request | past days served **zero games** for every league except NFL |
| `/api/{league}/schedule-dates` | the past is never asked for | the back arrow had **no past dates at all** for any league we had never stored |
| `scoreboard_store.needs_refresh` | an empty slate backs off 3h | a finished empty day got re-asked forever, once per viewer |

The rule is right. What was missing is that **"we already hold it" and "we never captured it" are different states.**
Both now capture once and store the result, so the second view is a SQLite read and the
gap closes permanently. Cost is one request per (league, day) for the life of that day,
not one per viewer.

---

## §2 What was broken, measured

Dev, before:

```
DEV mlb 2026-08-18  src=scoreboard_snapshots  games=15
DEV mlb 2026-08-17  src=unavailable           games=0
DEV mlb 2026-08-16  src=unavailable           games=0
DEV ufc 2026-08-15  src=unavailable           games=0     <- UFC 330
```

Prod, before (and **still**, it is on the old code):

```
prod /api/mlb/games?date=today     60.06s   <- the 60s sleep, not ESPN
prod /api/mlb/games?date=08-15     0 games
prod /api/{lg}/schedule-dates      source=unavailable, available=false
```

That 60 seconds is the answer to "why does the back button take a minute for feedback".
It is not the arrow. Clicking back refetches the board, and prod's serving process
answers its own spent per-host budget with `time.sleep(60)`. The fix (a handler refuses,
only a batch job waits) is on dev and has never been deployed.

Dev, after, verified through a real browser render on the **3096** tunnel:

```
Sat, Aug 15, 2026
UFC
UFC 330: MAKHACHEV VS. MACHADO GARRY · EARLY PRELIMS · 04:30 PM   FINAL ...
UFC 330: MAKHACHEV VS. MACHADO GARRY · PRELIMS · 06:00 PM         FINAL ...
```

Back arrow: `source=local`, ~20ms, 64 past instants for MLB / 46 for UFC.

---

## §3 The mistake I made, and the rule it earns

**I ran two scoreboard backfills at once and took every ESPN host from answering to refusing.**

`paced_http._host_spend` is per PROCESS. The declared `HOST_BUDGET = 60` means nothing
when two processes each spend 60. A backfill was still running in the background when I
started a second in the foreground; within minutes `site.web.api`, `site.api` and
`sports.core.api` all 403'd this box, including the undated endpoints that had been fine
an hour earlier. It recovered on its own a few hours later.

Two things came out of it:

- `ingest_scoreboards.py` now takes an exclusive `flock` and the second run **declines**
  rather than overlapping. Two timers plus a hand-run catch-up is exactly how this happens.
- I skipped rung 3 of the `espn-request-budget` skill. **Load the skill before writing the
  loop, not after the wall.** The backfill was 65 single-day requests; the scoreboard
  endpoint takes a date RANGE, which would have been ~11. That optimisation is still
  unbuilt — see §7.

---

## §4 Auditing the parallel agent's 22-commit sweep

Another agent split 11 files of 1000+ lines into packages while I was editing two of them.
It reported "full sweep 516 tests pass". **The full suite was 1525 passed / 12 failed / 36
errors.** 516 passing is a claim about a subset; it was true and it was not the question.

Clean, verified: no attribution lines, no untracked leftovers, no host/systemd/cron
changes, no schema migrations, no deleted tests, no weakened or removed assertions,
every split package imports.

Four real defects found and fixed (commits `b8cf3a2`, `3b1f50d`), all one shape — **a split
turned a rebindable module global into an import-time copy**:

1. `nfl_mock_draft/db.py` did `from .constants import _DB`. Tests redirect the DB by
   rebinding `nfl_mock_draft._DB`; against a copy that assignment does nothing, so **36
   tests were pointed at a fixture and silently opening the real database**.
2. `_availability_aggregates` was not re-exported at all — the pool-cache test died on
   AttributeError instead of testing the cache.
3. `settlement._mlb_schedule` was missing from the package surface. Worse, the two test
   files patch two spellings of what used to be one object
   (`settlement._mlb_schedule` vs `settlement.mlb_api._mlb_schedule`); only one can win.
   Both now aim at the submodule that owns it.
4. `settlement/settle_game.py` bound `_fetch_mlb_gamepk` and `_fetch_mlb_final` at import,
   so the finality tests' stubs were ignored and the assertion ran against the live MLB
   Stats API. Resolved through the package at call time.

Two more categories, found by script rather than by the suite — **a green suite cannot see
either of these**, because nothing currently imports the broken names:

**Four data paths lost a `dirname`.** A file that moved from `backend/x.py` into
`backend/x/y.py` sits one directory deeper, and these kept one `dirname`:

```
MISS  audit_league_stats/cli.py         -> backend/audit_league_stats/data/picks.db
MISS  ingest_league_narratives/cli.py   -> backend/ingest_league_narratives/data/picks.db
MISS  ingest_league_narratives/editor.py-> backend/ingest_league_narratives/data/news-deletions.log
MISS  bovada_scraper/direct.py          -> backend/bovada_scraper/data/picks.db
```

These are the `LP_DB_PATH`-unset fallbacks, which is exactly how a hand-run CLI invokes
them. **`sqlite3.connect` CREATES a missing file rather than failing**, so the job would
have run against an empty database and reported success. Fixed; no stray databases had
been created yet. `bovada_scraper/config.py`'s backoff-state path had the same bug.

**Thirty module-level names were dropped from four package surfaces**, including
`settlement.DB`, which no submodule defined at all. Restored from their owning submodules
after confirming none of them is ever rebound, so the package alias and the submodule are
the same object (verified with `is`).

Also worth knowing: **two failures were order-dependent, not intrinsic.** `test_nfl_dst`
and `test_nfl_team_games_denominator` pass alone and failed in the full run, because the
mock-draft leak above was writing into the real database. Fixing the leak fixed them.

> If you split a file: the promise is not "the tests I ran still pass". It is
> "every name another module or test can reach is still reachable **and still the same
> object**". Grep for what patches it before you move it.

---

## §5 Dev servers: there are two pairs and one is dead

```
3096 -> 8096   db=/root/legendarypicks/backend/data/picks.dev.db   <- the tunnel, healthy
3106 -> 8106   db=None, schedule-dates times out (http=000)        <- 2.5 days old, hung
```

I first rendered 3106 and saw 500s, 404s and a board that would not step back — none of
which was real. `.env.local` says `API_PROXY_TARGET=8096`, but the 3106 next process has
been up 2d14h and captured whatever it said then.

**Identify a dev server by `db_path` and freshness before believing anything it renders.**
I did not touch either process; killing an externally-managed dev server is not mine to do.
If 3106/8106 is nobody's, it is worth retiring — it is a permanent source of false reports.

---

## §6 State

- **Suite**: **1574 passed / 1 failed on BOTH `picks.db` and `picks.dev.db`**, identical.
  The one failure is the long-standing `test_story_form_season` MLS case, unchanged from
  yesterday. That is down from 1525 passed / 12 failed / 36 errors when the split sweep
  landed. `test_leagues_hub_contract` failed earlier only because it makes a live ESPN
  call and the host was still refusing (see §3); it passes now.
- **Store coverage**: 2026-08-08 through 08-19, but only 2–4 leagues per day. The backfill
  was cut off by the block in §3. Remaining gaps fill themselves one request at a time as
  people view those days, which is bounded and safe — a full backfill is optional.
- **Prod**: untouched, old code, 60s stalls and dead arrows. Deploying needs a container
  rebuild and is **the user's call** — do not do it unprompted.
- `backend/data/esports_team_logos.json` is modified and uncommitted, and is not mine.

## §7 Open

1. **Prod deploy** — the whole scoreboard fix is dev-only. This is the highest-value item
   and the only thing that fixes the minute-long stall the user is actually feeling.
2. **Backfill via date ranges** — `?dates=YYYYMMDD-YYYYMMDD` instead of one request per
   day, per rung 3 of the skill. Verify the range form answers before relying on it; the
   only measurement of it so far was taken during the block and is worthless.
3. **Story generation deserves its own timer.** It currently rides on
   `ingest_scoreboards.py` only because that is where we now learn a game exists. Nothing
   intrinsic ties it to the scoreboard. Also still true from 08-17: story generation
   reaches `site.api.espn.com` through `stakes.py`, a host walled from this box since
   Aug 4, so every preview run spends a request that cannot succeed.
4. **Not started, still queued from the user**: Bovada and Kalshi live games plus game
   detail; the daily RotoWire props dump to a directory at midnight.
