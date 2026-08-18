# TASK: route every ESPN call through `paced_http`

For the reasonix pane. Written 2026-08-18.

## Why this, and why now

`paced_http.record_spend` was added today (`23a68fc`). It writes one line per request to
`backend/data/http-spend.jsonl`: host, endpoint family, status, process, pid, cache hit.

Its whole purpose is to answer one question with data instead of recollection:

> **Does a 403 from ESPN correlate with a request count, or with a time of day, or with
> nothing?**

That answer decides whether we build a shared request budget at all. See
`docs/DESIGN-request-budget.md` §1: there are two different limits both called "100", one
certain (a 100-event cap per response) and one inferred (a ~100-request wall per host), and
they imply completely different work.

**The log can only see calls that go through `paced_http`. 17 modules bypass it and call an
ESPN host with raw `urllib`/`requests`.** Several run on active timers. So the log
undercounts right now, and an undercounted log will produce a confidently wrong answer to
the question above. Closing the bypass doors is a prerequisite for the measurement being
worth anything, not a cleanup task.

This does **not** change any policy or any budget. It changes which client issues the call.

## The 17 files

Measured 2026-08-18: makes a raw HTTP call AND references an `espn.com` host.

```
backfill_nfl_postseason.py            ingest_nfl_published_fantasy.py
backfill_team_stats.py                ingest_soccer_logs.py
fetch_identity_names.py               nfl_transactions_sync.py      <- on 2 timers
game_types.py                         reconcile_core.py
ingest_league_news/fetch.py  <- 4 timers   relink_prop_games_by_start_time.py
ingest_nba_stats.py                   routers/players/news.py       <- SERVING PATH
ingest_ncaaf_logs.py                  wc_context.py
ingest_nfl_adp.py            <- 2 timers   test_nfl_news.py
ingest_nfl_projections.py
```

Start with the ones on timers, since those are the ones distorting the log every hour:
`ingest_league_news/fetch.py`, `ingest_nfl_adp.py`, `nfl_transactions_sync.py`.

**`routers/players/news.py` is different and needs care.** It is a request handler, so it
must inherit the serving posture, not a batch one: no pacing, no retry ladder, and
`on_exhausted="refuse"` so a page load can never sit through a cooldown. `espn_client`
already carries exactly that configuration, so route it through `espn_client` rather than
constructing a `Fetcher`.

## Before you start: commit the range-backfill work

The date-range backfill is finished and verified but **uncommitted**, and it lives in
`backend/espn_client/__init__.py`, `backend/espn_client/scoreboard.py`,
`backend/ingest_scoreboards.py` and the untracked
`backend/test_scoreboard_range_backfill.py`.

Commit those four files as their own commit first, so this task starts from a clean tree.
That work is not part of this task and must not be folded into it. Do not push.

While committing it, confirm `espn_client/__init__.py` re-exports `scoreboard_raw_range`,
`games_by_day`, `_ny_date` and `_slate_day`. Four names were silently dropped from package
surfaces during the 2026-08-18 split sweep and thirty had to be restored; do not add to that.

## Scope lock

**Change only the 17 files listed above, plus their existing tests.**

Everything else is off limits *for this task*: `paced_http.py`, `espn_client/*`,
`scoreboard_store.py`, `league_activity.py`, `ingest_scoreboards.py`, `spend_report.py`,
`.gitignore`, any systemd unit, anything under `/etc`, cron, and any database. Do not add a
dependency. Do not change any budget, interval, retry ladder or cache TTL.

Note that none of the 17 files to convert are in that list, so once the range work above is
committed there is no conflict. `ingest_league_news/fetch.py` IS in scope; the rest of
`ingest_league_news/` is not.

## How

For each file, replace the raw call with the shared client. A batch job:

```python
import paced_http
_FETCH = paced_http.Fetcher(min_interval=..., headers=..., timeout=...)
data = _FETCH.json(url)          # or .fetch(url) / .text(url)
```

Preserve the existing behaviour exactly: same URL, same headers, same timeout, same retry
posture, same error handling. If a module currently swallows an error, keep swallowing it.
**This is a routing change, not a behaviour change.** If routing a file honestly requires a
behaviour change, stop and say so in your report instead of making it.

Some of these use `requests` and some use `urllib`. `Fetcher.json()` json-decodes,
`Fetcher.text()` returns a string. Pick the one matching what the call site already does.

## Verify

1. **The log sees them.** For at least three converted modules, run the module (or the
   function, with a stubbed response) and show that a new line appears in the spend log
   naming that process. A conversion nobody proved is logged has not been done.
2. **No new ESPN spend.** Do not run real ingests to test this. Stub the HTTP layer. If you
   genuinely cannot test one without a live call, declare the request count first and keep
   it under 3 for the whole task, per `.claude/skills/espn-request-budget`.
3. **Both databases.** Report both numbers, not one:

```
venv/bin/python -m pytest -q
LP_DB_PATH=data/picks.dev.db venv/bin/python -m pytest -q
```

Baseline as of `23a68fc`: **1598 passed, 1 failed** on each, the failure being the
long-standing `test_story_form_season` MLS case.

4. **Report the count you actually converted**, and list any file you could not convert with
   the reason. 17 is the target; a smaller number honestly reported beats 17 claimed.

## Out of scope, deliberately

- Do not build a shared or cross-process budget. That is gated on the data this enables, and
  the last attempt was reverted. Read `docs/DESIGN-request-budget.md` before forming an
  opinion about it.
- Do not serialise the timers or touch systemd.
- Do not change `HOST_BUDGET`, and never set a host budget to 0.
