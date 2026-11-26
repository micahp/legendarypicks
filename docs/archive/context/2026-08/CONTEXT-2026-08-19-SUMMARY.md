# 2026-08-19 DAY SUMMARY

**v0.8.3 shipped to production.** Previous: [2026-08-18 summary](/root/legendarypicks/docs/CONTEXT-2026-08-18-SUMMARY.md).

Written so a killed session loses nothing. §A is what changed, §B is every open item as a
user story with acceptance criteria and the skills to load, §C is what is in flight.

---

## ⏰ IF YOU ARE READING THIS ON 2026-08-20 OR LATER: RUN THIS FIRST

**There is a measurement waiting for you, and it is the only thing here with a deadline of
"as soon as a second day exists".** Four things changed under the ESPN spend log on 08-19, so
today's data is the first clean day and it answers questions yesterday could not.

```
cd /root/legendarypicks/backend
python3 - <<'EOF'
import json, datetime, bisect, statistics, random, collections
rows=[]
for l in open('data/http-spend.jsonl'):
    try: d=json.loads(l)
    except: continue
    if d.get('host')=='site.web.api.espn.com':
        rows.append((datetime.datetime.fromisoformat(d['ts']), d['status'], d.get('proc')))
rows.sort(); ts=[r[0] for r in rows]
def before(t, secs):
    return bisect.bisect_left(ts,t)-bisect.bisect_left(ts,t-datetime.timedelta(seconds=secs))
f=[t for t,s,_ in rows if s==403]; ok=[t for t,s,_ in rows if s==200]
random.seed(7); samp=random.sample(ok, min(2000,len(ok)))
for w,lab in [(60,'60s'),(300,'5min'),(3600,'1h')]:
    print(lab, 'before 403:', statistics.median([before(t,w) for t in f]) if f else 'NO 403s',
              ' before 200:', statistics.median([before(t,w) for t in samp]))
print('403 count:', len(f), 'of', len(rows))
print('by proc:', collections.Counter(p for _,s,p in rows if s==403).most_common(8))
EOF
```

**What to conclude from it:**

| result | means |
|---|---|
| 403s on `site.web.api` dropped sharply | the burst theory is right and `_pace_rate` works. Leave `HOST_RATE` alone. |
| 403s unchanged | per-process pacing is not enough, because the limit is per HOST and five jobs each pace to 50. That is the case for cross-process coordination, and only then. |
| 403s gone entirely | consider whether 50/60s is tighter than needed. Loosen only with a second day of evidence. |

**Also now answerable, and not before today:** `proc` labels were ambiguous until 08-19 (every
`python -m` logged as `__main__.py`). With them fixed, the log will finally name the real
second-biggest ESPN caller, and will identify who is hitting
`sports.core.api.espn.com/v2/sports/basketball/leagues/nba` (180 403s, 30 404s, **30 429s**).
That one is deliberately left untraced: the fixed labels name it for free, which beats
guessing.

### When each change landed, and where it is actually running

**You need these to read tomorrow's spend log.** Four things changed under it on 08-19, so a
drop in 403s cannot be attributed to any one of them without splitting the data by time.
All times are local (CDT), from `git log`.

| time | change | commit | effect on the log |
|---|---|---|---|
| 09:41 | **v0.8.3 image built.** Prod's container has run this image since 09:51 | `68f4e8d` | prod backend has NONE of what follows |
| 12:08 | systemd units repointed at `python -m bovada_scraper` (host edit, not a commit) | | props refresh resumes on both DBs |
| 15:05 | `stakes.py` off the walled host | `2b96b45` | **removes ~2,607 guaranteed-403 requests/day** |
| 15:14 | `_pace_rate` per-host rate limit, 50/60s | `364b492` | caps bursts at the source |
| 15:14 | `_who()` resolves `python -m` to the package | `364b492` | `proc` labels become usable |
| 15:14 | degradation test off a real ESPN host | `2d30bce` | stops writing ~102 fake 403s/day |
| 15:59 | **LLM provider chain** replaces the hardcoded DeepSeek call | `874c8ba` | previews/recaps/narratives alive again |
| 16:18 | `reasoning_effort` capped at `none` | `431bddf` | 4x faster calls, empty answers impossible |
| 16:22 | `legendarypicks-news` run green, exit 0 | | |
| 16:24 | `legendarypicks-news-prod` run green, exit 0 | | |
| 17:51 | **Story grounding fixed**: dates on results, dated player form, `.500` win pct | `88d8a52` | stories stop inventing days and inverting streaks |
| 17:51 | **Prompt eval harness**: saved prompts + saved outputs | `a62bd95` | a prompt change is a diff now |
| 17:56 | ESPN's own headline recorded as a roadmap item, with its coverage | `2fbe37b` | stops us paying an LLM to rewrite a wire recap |
| 18:05 | **UFC timer fixed**: a fold that forgets `prop_game_source_ids` | `f7797ae` | `underdog-ufc-props` green after 2h of 30-min failures |
| 18:11 | `legendarypicks-props-prod` RED again, `EXIT 3`, 1 of 5 mlb POSTs | | the §B14 locked-DB shape, after 9 clean runs |
| 18:20 | **NFL props live**, 1,080 across 29 games, all ESPN-linked | `29a7826` | the §B13 headline gap, closed for NFL |
| 18:32 | **MLS props live**, 362 across 15 games | `5dde0dd` | and four other competitions correctly excluded |
| 18:33 | Roadmap + this file updated against the measurements | `251005c` | |
| 19:0x | **Slate ordered by kickoff**, not by `pg.date` | `19c227d` | a 9:30pm game stops sorting above a 7:00pm one |
| 19:0x | **Every prop_games row now has a start_time** (18 dev, 22 prod) | `ae38a7a` | MLS fixtures stop vanishing from the board |

**So the honest read of tomorrow's data:** requests before roughly 15:05 are the old world,
after roughly 15:15 are the new one. The stakes fix and the rate limiter landed nine minutes
apart and **both** reduce 403s, so a fall in refusals cannot be credited to `_pace_rate` alone.
If you need them separated, `HOST_RATE=0` disables the limiter without touching anything else.

Already visible at 15:30, confirming the process fix is live in the timers: `pytest` and
`ingest_league_news.py` now appear as their own labels, while a residual `__main__.py` count
comes from processes that started before the change and are still running old code in memory.

### ⚠ WHERE THIS IS RUNNING: the timers have it, prod's API does not

This box runs the backend two different ways, and they are now on different code:

```
prod TIMERS      ExecStart=/root/legendarypicks/backend/venv/bin/python -m bovada_scraper ...
                 runs from the REPO working tree  ->  HAS every fix above on its next run
prod BACKEND API docker compose, image built 09:41, container up since 09:51
                 runs the IMAGE  ->  HAS NONE of it, and will not until a rebuild
```

**Prod's API is 23 commits behind `dev`**, including the `stakes.py` fix, the rate limiter and
the UFC outcome guard. Nothing in prod's served responses reflects today's afternoon work.

This is the recurring shape in `feedback_dev_fix_prod_never_ran`: both answer 200, so nothing
surfaces the difference. It also means the spend log mixes paced repo processes with an
unpaced container, which is a second reason not to read tomorrow's numbers as a clean verdict
on `_pace_rate`.

**⛔ Do not tighten `HOST_RATE` off a single day.** The 08-19 analysis establishes the SHAPE of
the limit (a short window, not an hourly count) and does **not** establish the threshold.

Full reasoning: §B7 below, and `docs/DESIGN-request-budget.md` §1b.

---

## §A What shipped today (v0.8.3, live)

Verified on production after deploy, not inferred from a 200.

| defect | before | after |
|---|---|---|
| next-day button | MLB 9 "future" starts, **0 usable**. ATP 0/16, UFC 0/1 | 0 past-leak on every league |
| prod scoreboard timers | **never installed**, store empty | installed, 112 rows on first run |
| "Cheap Quality, Live" | 9 cards of last night at 1c each, above the scoreboard | off `/scores`, and fixed |

**The next-day button.** `_cap_schedule_candidates` only truncated a list and never filtered
by direction, while the local rung feeds it a window that deliberately overruns the anchor
by a day for timezone boundaries. So past instants shipped inside `future_event_starts`.
Three of four leagues had a dead forward arrow.

**The discounts widget, two causes.** It read `espn.games(league)` with no date, and in the
morning the undated board is still last night. And its failure path served the **expired**
cache entry with no age limit, so once `_build` began failing it froze on its last good
answer permanently: every poll re-entered the branch, the timestamp was never refreshed, so
it could never go fresh again. Now reads the date-keyed store, and stale-serve is bounded at
10 minutes. **That is why prod was wrong and dev was not.**

**Why nobody caught these:** all three were verified mid-slate, in the one condition where
they work. They were wrong every morning and right every afternoon. This is now a rule; see
§B0.

---

## §B THE OPEN WORK

### §B0 The rule that applies to all of it

> **Acceptance checks run in the empty window, not the busy one.**

At 09:50 on a weekday nothing is live and every MLB game is `pre`. That is our most common
state. Three separate defects this month survived because every check was run mid-slate.
Any story below that touches a live or time-dependent surface is not done until it has been
looked at when nothing is on.

---

### §B1 Method of victory on every final  ·  ✅ MERGED to `dev` (audited, one defect fixed)

**User story.** As someone scanning yesterday's board, when a fight or match is final and
there is no score, I want to see **how it ended**, so that "FINAL" tells me something.

**Why now.** UFC 330 and the Contender Series cards render `FINAL` plus a winner and nothing
else. Tennis already does this correctly with `WALKOVER`.

**The rule, verbatim from Micah:** if the game is final you show the score, and if there is
no score you show the method of victory.

**The finding that makes it cheap: ESPN already publishes it and we discard it.**
Measured off `ufc/scoreboard` for 2026-08-15:

```
competitions[].details[]  ->  {"id":"20","text":"Unofficial Winner Submission"}
                              {"id":"21","text":"Unofficial Winner Kotko"}   # their KO/TKO
competitions[].format     ->  {"regulation":{"periods":3}}                   # 3 or 5
competitions[].status     ->  {"period":3,"displayClock":"1:24"}
```

**Acceptance criteria**

- A finished UFC fight renders the method in the slot a score would occupy: `SUB · R3 1:24`.
- A decision is derived from `status.period == format.regulation.periods`, and where it
  cannot be determined **nothing is emitted, never a guess**.
- An unrecognised `details` type id is **logged**, not silently dropped.
- **No additional ESPN request.** This is parsing a payload we already fetch.
- Every other league audited for the same gap, reported per league **including the ones that
  are fine**. Likely real: soccer decided on penalties (a 1-1 that ended 4-3 on pens is a
  wrong scoreboard, not a missing label), NHL OT/SO, tennis retirement, MLB suspended.

**Skills to load:** `fail-loudly` (an unmappable method must not become a blank),
`honest-data-ui` (absence is a dash, never a zero), `answer-is-already-here`.

**Spec:** `docs/TASK-scoreboard-outcomes-and-homepage.md` item 1.

---

### §B2 Live sections above the date  ·  ✅ MERGED to `dev`

**User story.** As someone browsing a past date, I want to see that something is live **right
now**, so I do not sit on Saturday's board while a game is on.

**The bug.** The live section renders below the date control and is scoped to the selected
date. A live game is a fact about the present, not about the date being browsed.

**Acceptance criteria**

- The live section sits **above** the date control and ignores the arrows entirely.
- When nothing is live it renders **nothing**: no header, no empty state.
- Verified **in the empty window** (§B0), not only when something is on.
- **The discounts widget is NOT re-added to `/scores`.** It was removed today for cause;
  whether it returns is Micah's call, not the task's.

**Skills to load:** `honest-data-ui`, `fail-loudly`.

**Spec:** same file, item 2.

**One open gap from the audit, your call.** On a past date, if nothing is live the rail stops
polling permanently, so a game starting later is never surfaced. That is a deliberate cost
bound (a quiet morning on a past date costs one today-read), but it is a partial miss of the
user story above. Decide whether the bound or the story wins.

---

### §B3 The homepage leads with props  ·  ✅ MERGED to `dev`

**User story.** As a first-time visitor, I want the homepage to take me to the thing that is
actually differentiated, so I understand what this product is for.

**Micah's reasoning, verbatim:** the homepage sends people first to the scoreboard and second
to predictions, with prop data third. But **props and prop history are the primary value, the
most differentiated and most dopamine-giving surface we have.**

**Acceptance criteria**

- Props is the **primary** call to action; scoreboard and predictions are secondary.
- The nudge leads with the **history**, that we say how the line landed. "Props" alone is a
  noun; the record is the differentiator.
- News, live esports and mock drafts are surfaced. The homepage currently under-sells what
  we have.
- **No number on the homepage we cannot source.** A count comes from a query, and is absent
  rather than zero when unreadable.
- **Screenshot in the report.** A design change described only in prose is not reviewable.

**Skills to load:** `honest-data-ui` (mandatory), `frontend-design`.

**Spec:** same file, item 3.

---

### §B4 Stop discarding ESPN's fields  ·  MINE, NOT STARTED

**This is step 0 of the scoreboard rebuild and the highest-value change on the board.**

**User story.** As a reader, I want a game card to tell me the records, who is pitching, what
network it is on and one line about why the game matters, because that is what a scoreboard
is.

**The finding.** ESPN's site runs on the same scoreboard payload we already fetch, so their
field set is their card contract. Measured 2026-08-19:

```
competition : broadcast, notes, headlines, highlights, leaders, venue, format, neutralSite
competitor  : records, leaders, probables, linescores, statistics, winner, hits, errors
```

Populated on an ordinary Wednesday:

```
headlines : "Pirates and Tigers meet, winner secures 3-game series"
probables : P. Skenes vs J. Jobe
records   : PIT 62-66 (33-32 home)   DET 61-65
broadcast : MLB.TV                    venue: PNC Park
```

**We keep `abbrev, name, nickname, score` and throw the rest away, at zero request cost to
keep it.**

**Acceptance criteria**

- The normalized game carries records, broadcast, probables, linescores, leaders, headlines
  and venue. Additive, so nothing downstream breaks.
- `scoreboard_snapshots` stores them, so past days have them too.
- **A test pins each field against a captured payload**, so it cannot silently regress.
- **Zero new ESPN requests.** If the count changes, the change is wrong.
- **Audit first**: are we spending calls elsewhere (game detail, `summary`, stories,
  settlement) to re-fetch what the scoreboard already handed us? `summary` is called by at
  least 9 modules. Report the overlap before writing the storage code.

**Skills to load:** `published-first` (the value is already published, do not derive it),
`espn-request-budget`, `answer-is-already-here`.

**Spec:** `docs/SPEC-featured-events-scoreboard.md` §1 and §9 step 0.

---

### §B5 Featured Events scoreboard  ·  SPEC WRITTEN, BUILD NOT STARTED

Blocked on §B4, which everything else depends on.

**Spec:** `docs/SPEC-featured-events-scoreboard.md`. §4 is the ranking, §6 is the empty
state, §6b is the visual language, §7 is what may never go on the page.

**Two open questions only Micah can answer**, both about Sleeper, whose scoreboard is its
homepage:

1. Is its ordering live-first, chronological, or curated?
2. **What does it show when nothing is playing?** This decides §6 and it is our most common
   state.

Also undecided: featured count (3, 4 or 6, which decides one row or two), and whether
`/scores` becomes the homepage. Note §B3 pushes the other way, toward props as the landing
surface.

**Skills to load:** `honest-data-ui` (mandatory), `frontend-design`, `fail-loudly`.

---

### §B6 NFL and NCAAF week navigation  ·  HARD DATE: 2026-08-29

**User story.** As a drafter, I want to move through NFL and NCAAF by **week**, because that
is how the sport and my league are organised.

**Why it has a clock.** NCAAF opens Aug 29. This is the only dated item on the board.

`docs/API-nfl-schedule-weeks-v1.md` already serves ESPN's own week calendar and is live on
`pages/leagues/[league].tsx`. **Reuse it; do not rebuild it.**

**Note:** I gated the scoreboard rebuild behind the request-budget question. **That gate is
probably wrong for this item** given the deadline. Decide deliberately.

**Skills to load:** `honest-data-ui`, `published-first` (ESPN publishes the week calendar).

---

### §B7 The request budget  ·  ✅ ANSWERED 2026-08-19. It is a BURST RATE.

**The question §B7 was waiting on is answered, from the spend log, a day early.** Full working
in `docs/DESIGN-request-budget.md` §1b.

Over 27,801 ESPN requests (08-18 19:15 to 08-19 19:37), comparing what preceded each 403 on
`site.web.api.espn.com` against a 2,000-sample of 200s:

```
requests in the 60s   before a 403 : median   63     before a 200 : median   36
requests in the 5min  before a 403 : median  311     before a 200 : median  141
requests in the 1h    before a 403 : median 1238     before a 200 : median 1266   <- FLAT
```

**The hour is flat, the minute is not.** So the limit is a short-window rate, NOT a request
count per host and NOT an hourly budget. Confound tested and ruled out: hot and cold hours run
the same processes against the same paths in the same proportions, and the 403s spread across
all five processes rather than concentrating in one.

**Consequence: do not build the cross-process hourly ledger.** It is the wrong shape and would
not have prevented any of these refusals. A token bucket over ~60s per host needs no durable
shared state.

**The concentration that governs the whole design:**

```
ingest_scoreboards.py       19,856 of 27,801   = 71% of all ESPN traffic
__main__.py                  2,991
pregenerate_game_stories.py  2,513
settle_props.py              1,656
link_prop_games.py             426
uvicorn (serving path)         310
```

**One process is 71% of it**, and it runs every 10 minutes. Pacing that one caller is most of
the available win; a global ledger coordinating six processes is machinery for the other 29%.

**86.1% of our 403s are not rate blocks at all**, they are permanent refusals being retried:
`site.api.espn.com/apis/v2/sports/baseball/mlb` is 2,587 of 2,587 refused, and
`sports.core.api.espn.com/v2/sports/basketball/leagues/nba` is 174 of 232. Per the
permanent-refusal rule, stop asking rather than pace.

**⚠ The instrument pollutes its own log.** 102 logged 403s to a league named `test` never
happened: `test_espn_client_degradation.py:28` mocks `urlopen` to raise a synthetic 403, and
`record_spend` logs it anyway. Excluded from every number above. Small, but the class matters:
a log that records simulated events beside real ones will be read as if all were real.

**Limits:** one day, 25 hourly buckets, 466 usable 403s. This establishes the SHAPE, not the
threshold. Re-run against a second day before putting a number in code.

**Prerequisite now CLOSED:** `TASK-route-espn-through-paced-http.md` is done. Zero ESPN calls
in the backend bypass `paced_http`, verified by AST sweep rather than by the task's file list.
**The task's own list was over-inclusive**: it selected files making a raw call that also
mention an ESPN host, which is co-occurrence, not the call's target. 6 of the 17 never called
ESPN raw at all (nflverse parquet, api.nhle.com, RSS feeds, our own backend, api.deepseek.com,
and one match that was a comment). So "17 modules bypass" was never true; 11 did.

**Skills to load:** `espn-request-budget` (mandatory).

#### What was BUILT off this data, 2026-08-19 (approved and shipped)

**1. `stakes.py` MLB standings pointed at the WALLED host.** Tracing "who calls the gated
endpoint" found a live data defect, not a budget one. `_MLB_STANDINGS` used
`site.api.espn.com`, which 403s this box, so `_mlb` raised on every call and the module's
fail-soft contract turned that into `[]`. **Every MLB game story has been generated with zero
stakes lines since the module was written**, and stakes exists precisely because stories were
starving for context.

```
site.api.espn.com       403      437 bytes   2,607 requests in one day, 403 every one
site.web.api.espn.com   200  261,348 bytes   identical path, AL + NL

after:  NYY are 2nd in the AL East, 5 games back; current playoff seed 4.
        BOS are 3rd in the AL East, 7.5 games back; current playoff seed 5.
```

Still fail-soft, no longer silent: the `except` warns. An unknown abbreviation still returns
`[]` with no warning, because that is legitimately empty rather than broken, and conflating
those two is exactly what hid this for so long.

**2. The spend log could not attribute 11% of its own traffic.** `_PROCESS` was
`basename(argv[0])`, and `python -m pkg` sets `argv[0]` to the package's `__main__.py`, so
**every `-m` invocation collapsed into one label**: 3,043 requests across 395 minutes, with
`python -m pytest` in the same bucket as the ingest packages. The 08-18 split made it worse by
turning two scripts into `-m` targets. Now resolves to the package name, and names `pytest`.

**3. The instrument no longer writes fake data into itself.**
`test_espn_client_degradation.py` mocked `urlopen` to raise a synthetic 403 against a real
ESPN URL, and `record_spend` logged the attempt anyway: 102 refusals a day that never
happened. Repointed at `espn.invalid`.

**4. The rate limiter, `paced_http._pace_rate`.** Per-host sliding window, default
`HOST_RATE=50` per `RATE_WINDOW=60s`, both env-overridable, `HOST_RATE=0` disables it.
Deliberately below the 63 where 403s concentrate and above the 36 that precedes a typical
success.

It reuses `on_exhausted`, so **a batch job waits and a request handler refuses**. That is the
2026-08-18 prod incident (46 sixty-second sleeps in a handler) and a second mechanism that can
sleep is a second chance to make it, so `test_paced_http_rate.py` pins it with a timing
assertion. `espn_client` already defaults to `refuse`; `ingest_scoreboards.py` explicitly opts
into `sleep`.

**⚠ The known limit, stated in the code:** it is process-wide, **not cross-process**. Five
jobs each pacing at 50 can still show the host 250. That is the same per-process-versus-
per-host flaw the count budget has, and it is left open **on purpose**: 71% of traffic is one
job, so pacing each process removes most of the burst without the shared-state machinery whose
last attempt was reverted. Whether the remainder matters is a question for the next day of
data.

#### The next step, and it is a measurement, not a build

**Re-run the §1b analysis tomorrow against a second day.** Three things changed underneath it
in one day (2,607 guaranteed-403 requests removed, the rate limiter added, the log's process
labels fixed), so tomorrow's data is both cleaner and different. Specifically:

- Did 403s on `site.web.api` fall? That is the test of whether the burst theory is right.
- With `proc` now unambiguous, what is the real second-biggest ESPN caller?
- Is 50/60s too tight? Watch for `paced_http` sleeps showing up in job durations.
- **Do not tighten `HOST_RATE` off one day.** The measurement establishes the shape, not the
  threshold.

Still untraced: `sports.core.api.espn.com/v2/sports/basketball/leagues/nba`, 180 403s / 30 404s
/ 30 429s, all attributed to the old ambiguous `__main__.py` label. **The fixed labels will
name it tomorrow**, which is cheaper than guessing now.


### §B8 MLS props: the "error" is a transport blip, the real gap is 7 missing markets

**Repro steps used (Micah's):** tunnel `/props` -> MLS filter -> **Props tab** -> select a
market.

**What actually happens.** The board works: **421 lines** across four markets, rendering hit
rates L5/L10/L20, projection and edge.

```
Assists 421 · Goalscorer 411 · First Goal Scorer 324 · Goal Or Assist 159   source: BOVADA
```

**The blank page is a transport failure, not our code.** On the 4th rapid market switch the
page collapsed from 26,120 characters to 327, with `ERR_HTTP2_PROTOCOL_ERROR` and **no HTTP
status**. Selecting the same market first (20,024 chars) or second (16,379) works. The API
returns 200 with real data for every market on dev:

```
/api/props?league=mls&market=goal_or_assist  ->  200, 17,879 bytes
/api/props?league=mls&market=assists         ->  200, 17,333 bytes
```

A dropped HTTP2 connection under repeated large responses through a trycloudflare tunnel is
consistent with "works on prod, fails on the tunnel". **Do not chase it in application code
until it reproduces on a stable host.**

**The real finding, and Micah called it: the RotoWire work is half done.**
`monitor_rotowire_soccer.py` proved the relay carries seven MLS markets we cannot get
elsewhere (passes attempted, saves, shots, shots on target, tackles, clearances, crosses).
**None of them are in `props`.** We measured the source and never ingested it, so the MLS
research board shows Bovada's four markets and nothing else.

**Acceptance criteria for finishing it**

- The seven relay markets land in `props` for MLS with the same shape as Bovada's, so the
  research board picks them up with no frontend change.
- **Do not overwrite a Bovada line with a relay line, or the reverse.** One column, one
  vocabulary, one publisher: `source` must distinguish them and the board must say which.
- The relay is pulled **pre-lock**. A pick'em board is gone at kickoff, which is the exact
  artifact that produced "PrizePicks carries no MLS" on 08-16.
- Entity resolution is by publisher id where one exists, never by surname alone.
- Report coverage as a fraction of the MLS slate, against Micah's stated 80% target.

**Note:** Codex did some of this work. **Check for prior art before starting**, including
unmerged branches.

**Skills to load:** `published-first`, `fail-loudly`, `answer-is-already-here`.

**Related:** Micah, same session: *"we should probably replace the provider now."* In context
that reads as replacing or supplementing Bovada with the relay for MLS, since the relay
carries 7 markets Bovada does not. **Confirm before acting**, because it could equally mean
the LLM provider returning HTTP 402 (§B9).

---

### §B10 RotoWire daily archive  ·  DONE TODAY, and the shape is now known

**User story.** As the product later, I want every prop RotoWire publishes for every league
they cover, from today onward, so that when we decide to cover a new league we already have
its history.

**Micah's reasoning:** prop history is the differentiator, and it cannot be backfilled. A
line we did not store on the day is gone.

**Shipped 2026-08-19:** `backend/ingest_rotowire_archive.py`, timer at 00:05 local,
`Persistent=true`. Writes to `backend/data/rotowire-archive/`, gitignored. One request a day
to `www.rotowire.com`, not an ESPN host, so it has no bearing on that budget. About 1 MB
gzipped a day, roughly 220 MB a year.

**The shape, measured, which is what Micah asked to see:**

```
top-level : markets, entities, events, props, logos
markets[] : marketID, sport, category, marketName          (107)
entities[]: entityID, eventID, sport, name, team, pos, link, photo   (1,425)
events[]  : eventID, gameID, eventTime, homeTeam, awayTeam, oddsSource, ml, weather   (97)
props[]   : propID, marketID, entities, projection, lines, hitRates  (5,255)
```

**Sports carried:** NFL, MLB, NBA, NHL, CFB, CBB, Soccer, WNBA, **CS2, DOTA2, Valorant, COD**.

Today's props by sport: `MLB 3104, NFL 1055, WNBA 390, Soccer 183, CS2 145, PGA 135,
CFB 109, NHL 81, MMA 24, NBA 18, Valorant 11`.

**Two things worth acting on:**

1. **`props[].hitRates` is prop history, already computed by them.** Before we build our own
   hit-rate surface, read theirs. `published-first` applies directly.
2. **NFL is already at 1,055 props and CFB at 109**, with NCAAF opening Aug 29. The archive
   is capturing the draft window as it happens.

**Still open on this:** we ARCHIVE the payload, we do not yet PARSE it into `props`. The MLS
markets Micah wanted (the ~80% he described, of which Codex did some) are in
`markets[] where sport='Soccer'`, 8 markets. Deciding which to ingest is the next step and
is deliberately separate from archiving.

**Skills to load:** `published-first` (mandatory: they already publish hit rates and
projections), `fail-loudly`.

**Related, already live:** `monitor_rotowire_soccer.py` answers "does this source carry MLS"
from a probe series rather than a single read. Its history shows why that matters:

```
2026-08-17T04:20  fixtures= 3  offers= 35  MLS=0     <- read at the one empty moment
2026-08-19T05:10  fixtures=16  offers=133  MLS=15
```

---

### §B11 The 08-18 split broke jobs OUTSIDE the repo. FIXED, and my audit missed it.

**This is the correction to yesterday's §4.** I said I audited every commit of the split
sweep. I audited ignore rules, package surfaces, tests and data paths. **I never checked
systemd units, shell scripts or cron**, so a whole class of breakage ran unnoticed for a day.

**Callers of files the split deleted, all silently failing since 08-18:**

```
legendarypicks-props.service        bovada_scraper.py           every 30 min, dev
legendarypicks-props-prod.service   bovada_scraper.py           every 30 min, prod
legendarypicks-mlb-capture.service  bovada_scraper.py
scripts/news-collect.sh             ingest_league_narratives.py  exit 2 every run, 4 timers
scripts/run_pipeline.py             bovada_scraper.py
scripts/legendarypicks-pipeline.cron  bovada_scraper.py
ops/.../wc-props.service            bovada_scraper.py           (not installed)
```

**Props stopped refreshing on both databases for a day and nothing surfaced it** except a red
unit nobody was reading. That is very likely what looked like an MLS props bug (§B8): the
board was showing whatever was last written before the split.

**The trap:** a package's `if __name__ == "__main__": main()` guard in `__init__.py` reads
like an entry point and is not one. It fires for `python path/to/__init__.py`, never for
`python -m package`. Both packages needed a real `__main__.py`.

**Two more defects underneath**, unreachable while the callers were broken, found with
`pyflakes` rather than by crashing one at a time:

```
ingest_league_narratives/cli.py       _init_db, variety_resolve  undefined
ingest_league_narratives/generate.py  _deepseek_chat             undefined
ingest_ufc_fight_stats/apply.py       IngestPlan                 undefined in an annotation
```

**Verified after fixing:** props ran clean on dev (`atp 96/96, mlb 1233/1274, wta 84/90, no
problems found`), every installed unit's ExecStart now resolves, and the narratives package
runs end to end.

**Transcript check.** Micah asked whether the split sessions changed anything else outside
the repo. Grepped all 08-18/08-19 hermes request dumps for host-mutating commands
(`systemctl`, `crontab`, writes to `/etc`): **one read-only `crontab -l` and nothing else.**
So the sessions changed no host config; the damage was entirely "deleted a file that host
config pointed at".

**Still red after all of it, and none of it is the split:**

| unit | exit | cause |
|---|---|---|
| `legendarypicks-props-prod` | 3 | "2 of 14 mlb games failed to POST". Partial ingest, failing loudly, correct behaviour. Needs its own look. |
| `legendarypicks-news` | 1 | `discover_topics.py` exit 1, **DeepSeek 402 Insufficient Balance**. Billing. |
| `legendarypicks-news-prod` | 1 | same 402 |

**The gap I first reported as unclosable, then closed (`a9c70e8`).** I said `routers/games/*`
and `routers/players/*` use `from _core import *` so pyflakes cannot check those 16 files, and
left it there. It was closeable: **expand the star import in a throwaway copy using
`dir(_core)`, then pyflakes checks normally.** `_core` itself star-imports four more modules,
so resolve recursively.

It was hiding a live defect:

```
routers/players/projections.py   _NFL_KEY_NORMALIZE   undefined  <- live NameError
reconcile_gap.py:168             Report               undefined in a quoted annotation
```

The split gave `profile.py` that import and missed `projections.py`, so folding legacy 2024
nflverse keys onto canonical 2025 names raised at runtime. **Nothing found it because the star
import disabled the only tool that would have.** Widened to every star import in the backend:
463 files checked, **zero undefined names left anywhere in `backend/`**. The `Report` one
predates the split.

**The rule:** a star import is not a style question, it is a **hole in the only check that
finds dropped names after a split**. Expand it in a copy rather than reporting it as a limit.

**The rule for the next split:** a split can break something that lives entirely outside the
repo. Audit `systemctl list-timers` ExecStart paths, `scripts/*.sh`, cron and Docker, not
just the code.

---

### §B12 ✅ DONE: DeepSeek replaced with a provider chain. Both news reds closed.

**Micah, 2026-08-19:** *"first we should be failing loudly. second we should not be using
DeepSeek anymore because it's not cheap anymore."* Built and verified the same day.

**The damage it fixed:** 2,334 HTTP 402s in seven days, ~2 a minute, `api.deepseek.com` out of
credit since 08-18 19:43. AI previews and recaps, news narratives, conversation cards and WC
context were all dark for 17 hours.

#### What was built (`874c8ba`, `431bddf`)

`_deepseek_chat` is now `_llm_chat`, provider-agnostic, with `_deepseek_chat` kept as an alias
so every caller keeps working. The endpoint is configuration and the provider is a chain:

```
nous        inference-api.nousresearch.com   $0.00005/call   NOUS_PORTAL_KEY
openrouter  openrouter.ai/api/v1             $0.0002 /call   OPENROUTER_API_KEY
```

Nous prefers the static portal key Micah added mid-session and falls back to the hermes
agent's OAuth token. **We only ever READ that token file, freshly per call, never refresh and
never write it**: it is another process's state, and two writers to one token file is how you
get a logged-out agent at 3am.

#### ⭐ The model was a moving target, and that is why it got expensive

We were asking for **`deepseek-v4-pro`, an UNDATED alias.** DeepSeek moved what it points at
without renaming it. OpenRouter's price list is the visible edge of that move:

```
deepseek-v4-pro         in $1.44/M  out $2.88/M   <- the alias we called
deepseek-v4-pro-0813    in $0.66/M  out $1.98/M   <- the dated snapshot, HALF the price
deepseek-v4-flash-0731  in $0.14/M  out $0.28/M   <- what we use now
```

**Never ask for an undated model alias again.** A name without a date is a moving target, and
it moved us onto something twice the price with no announcement and no code change.

#### The candidates were measured, not assumed

Three runs each of a real captured game-story prompt, every claim checked against the
grounding:

| model | verdict |
|---|---|
| **deepseek-v4-flash-0731** | **3/3 clean, nothing invented. Chosen.** |
| nvidia/nemotron-3-ultra-550b | mostly accurate, ~1 error/run, 6.8-17.6s, truncated once |
| nvidia/nemotron-3.5-lightning | **0.6s, 20x faster**, but contradicted itself inside one blurb: Houston "leads the division" AND "sits 13 games back" |
| liquid/lfm-2.5-2.6b:free | worst. Inverted which club led the division, flipped the sign of a run differential, invented a Seattle sweep |

Micah's instinct that Liquid would be faster was right; it is not usable at this accuracy bar,
and the accuracy bar is the product.

#### Re-tested with reasoning DISABLED, which is the fair comparison

The first round ran the alternatives with reasoning on. Once `reasoning_effort=none` turned out
to be the right default, all four were re-run under it. Two verdicts changed:

```
deepseek-v4-flash-0731    7.6s  132 out   0 errors on the facts given (weekday only)
nemotron-3-ultra-550b     2.3s  163 out   1 error: misreads a combined stat (plus weekday)
nemotron-3.5-lightning    1.3s  154 out   several    ("surging Angels" at 50-76; invents
                                                      "AL West batting champion")
liquid/lfm-2.5-2.6b       DISQUALIFIED, HTTP 400:
                          "Reasoning is mandatory for this endpoint and cannot be disabled."
```

**Liquid is out on a hard constraint, not a judgement call:** its endpoint refuses to disable
reasoning, so it can never get the 4x speedup and always carries the empty-answer risk.

**Nemotron ultra improved enormously**, from 12.9s to 2.3s, and is now a genuine contender at
**3x DeepSeek's speed**. It stays the runner-up only on accuracy: it read Christian Walker's
`[0,0,1,7,0]` combined hits+runs+RBIs as "one hit and seven RBI". If latency ever matters more
than a stat misread, switch `LP_LLM_MODEL`; nothing else needs to change.

**A shared defect that is OURS, not the models':** every model named a weekday for the last
meeting and every one was wrong. The game was Tuesday 08-18 (`LAA @ HOU`, HOU lost 3-1 at
home); DeepSeek said Wednesday, Nemotron said Monday. **The grounding lists last-5 results with
no dates at all**, so the model has nothing to name a day from and fills the gap.

Note what is NOT wrong here: "3-1" and "home" are both correct and both derivable from
`L 3-1 vs LAA`. Only the weekday is unsupported. Fix the prompt, either by supplying the dates
or forbidding day names, and it improves whichever model we run.

**A tested hypothesis, recorded so nobody re-runs it:** Micah suggested DeepSeek being
China-hosted might explain the off-by-one day, and the clock fits (at the time of the call it
was already Thursday 06:35 in China, so "yesterday" there would be Wednesday). **Not
supported.** Asked directly, `deepseek-v4-flash-0731` answers *"I do not know, as I don't have
real-time access to the current date"*, and so does nemotron-ultra. They have no clock to be
wrong about. Meanwhile `nemotron-3.5-lightning` confidently answers *"Friday, May 24, 2024"*,
which is the whole phenomenon in one line: a model with no date will produce one anyway.

So it is not a timezone issue. It is a missing field, and the fix is the same either way: put
the dates in the grounding.

**Error counts in the table above should be read with that in mind:** DeepSeek's single "error"
IS the weekday, so on the facts it was actually given, it made none.



**A correction worth keeping:** the first grading pass called far more of this hallucination
than it was. It was done against only the first 900 of 1,442 grounding characters, and the
tail carries last-5 results and season leaders, so `.318`, `36 HR`, `20 HR`, `.281` and the
`3-1` scores are facts. **Grade against the whole prompt or do not grade.**

#### ⭐⭐ Hidden reasoning was eating the entire answer, for the third time

The first run after the swap still failed: `completion_tokens=24000, reasoning_tokens=23999`.
**One token left for the answer out of twenty-four thousand.** This exact failure has now
landed on three different ceilings: 4000 (`discover_topics`, 08-17), 3000 and 24000 (both
08-19). Raising the ceiling has never fixed it, because the thinker spends whatever it is
given.

Our prompts are grounded writing: every fact is handed to the model, and the job is selection
and phrasing, not derivation. Measured on one prompt, all three outputs factually clean:

```
default   12.9s   1,252 out   1,126 reasoning
low       10.7s     653 out     503 reasoning
none       3.0s     142 out       0 reasoning     <- the default now
```

**4x faster, an order of magnitude cheaper, no accuracy cost, and the empty-answer failure
becomes structurally impossible rather than a ceiling we keep raising.** Callers that genuinely
need deliberation pass `reasoning="low"/"high"`; `LP_LLM_REASONING` overrides globally.

#### Fail loudly: the permanent-refusal rule finally applied here

A 401/402/403 is recorded once and the provider is **skipped for a cooldown**, not retried.
That rule was already written for ESPN's 403 and never applied to the LLM path, which is
exactly how one dead account produced 2,334 requests. A 500 is still treated as transient.
Pinned in `test_llm_provider_chain.py`.

#### Two operational facts about Nous, learned the hard way

1. **It answers 403 with Cloudflare error 1010 when there is no User-Agent.** That is a
   browser-signature block and it reads exactly like an auth failure.
2. **It returns HTTP 524 (gateway timeout) on long requests.** Its edge timeout is shorter
   than our 180s. The chain correctly treated it as transient and fell through, but consider
   this before routing heavy batch jobs at it.

#### Verified

```
legendarypicks-news       exit 0   371 new rows,  9 conversation cards, narratives OK 33s
legendarypicks-news-prod  exit 0   397 new rows, 10 conversation cards, discover_topics OK 8s
402s since the swap: 0
suite: 1644 passed / 1 failed on BOTH databases
```

Every narrative integrity check clean: 0 social leaks, 0 cards naming an uncited outlet, 0
cards anchored on background while newer reporting existed.

### §B15 ✅ DONE: the story grounding was missing fields the model then invented

**Micah, 2026-08-19:** *"lets supply the dates in the prompt, test it, then cut the build."*
Done, and testing it turned up two more of the same shape.

**Three defects, one shape: a value we already had was absent from the prompt, so the model
filled the gap rather than leaving it empty. None of these were model defects.**

#### 1. No dates on the last-five results (`88d8a52`)

ESPN publishes `gameDate` on every `lastFiveGames` event and we discarded it. Every model
named a weekday for the last meeting and every one was wrong: DeepSeek said Wednesday,
Nemotron said Monday, **it was Tuesday**.

```
before  L 3-1 vs LAA (MLB); L 3-2 vs SEA (MLB); ...
after   L 3-1 vs LAA (MLB) [Tue Aug 18]; L 3-2 vs SEA (MLB) [Sun Aug 16]; ...
```

**⚠ The trap, and it nearly went in:** ESPN's instant is UTC and the calendar day is not.

```
utc 2026-08-19T00:10Z  ->  local Tue Aug 18   Final          the 3-1 LAA win
utc 2026-08-20T00:10Z  ->  local Wed Aug 19   8:10 PM EDT    tonight
```

Printing the UTC date would have written "Aug 19" on the Tuesday game, **baking the exact
off-by-one in permanently and making it look authoritative**. Reuses the scoreboard's
DST-aware `_ny_date`, which is already how every game in the store is bucketed.

#### 2. ⭐ Player form was read BACKWARDS, which inverts the story's lead claim

The worst of the three. Form was a bare array under a "most recent first" heading:

```
Trout, last 5 combined H+R+RBI: [0, 0, 1, 1, 5]
```

Ground truth from `player_game_logs`, newest first:

```
Aug 18 -> 0    Aug 16 -> 0    Aug 15 -> 1    Aug 14 -> 1    Aug 13 -> 5
```

So the 5 was **five games ago and Trout was cold**. Three different models called it "his last
game" and turned a slump into a hot streak. **Sports game logs are universally printed
oldest-first, so a header saying otherwise loses to the convention.** Every value is dated now
and there is no ordering left to misread.

Micah asked "are you sure it's newest first" before this shipped, which was the right
challenge: had the direction been wrong, dating the values would have made a worse error look
authoritative. Confirmed three ways (the `ORDER BY ... DESC`, the raw rows, and the rendered
dates descending).

#### 3. `0.5 win%` read as a games-back lead

Two of three runs turned it into "leads the AL West by half a game", a standings claim nowhere
in the facts; Liquid made the same misread as "a +0.5 win percentage edge". Now `.500 winning
percentage`, and `differential` became `run differential`.

#### The game's own date is in the header too

`game_result` carries **no date at all** (its keys are scores/state/winner), which is why
reading `gr["date"]` silently produced nothing. Two of three callers pass `start_time`; the
serving route in `routers/game_extras.py` cannot, so it falls back to the summary payload's
`header.competitions[0].date`, already fetched with a TTL, at no extra request.

#### Verified, same game and model

```
before  "Mike Trout broke out with 5 hits, runs and RBIs in his last game"     WRONG
after   "Mike Trout has been quiet since an Aug 13 outburst"                   right
after   "Alvarez 0-for in total bases on Aug 18 after a 5-base game Aug 14"    right, and only
                                                                               possible with dates
```

Suite 1644 passed / 1 failed on both databases.

---

### §B16 ✅ DONE: prompt evals are saved, so a prompt change is a diff (`a62bd95`)

**Micah, 2026-08-19:** *"are we throwing away the old results? would have been nice to save
them as older runs just for future reference."* He was right; they were headed for a
session-scoped scratch dir.

```
docs/evals/story-prompt/prompts/   the grounding at a point in time, v0..v3
docs/evals/story-prompt/runs/      dated model outputs, appended never overwritten
backend/eval_story_prompt.py       replay a version against any model(s)
```

`--capture mlb:401816594 --as v4-name` snapshots a fresh prompt from a live game, so a new
version starts from real data rather than a hand-edited copy.

**A prompt is code and should diff like code.** The grounding changed three times in one
afternoon and each change was tested by generating three blurbs, reading them and discarding
them, which is a memory rather than a comparison.

Two cautions written into the README on purpose, both mistakes made while finding these bugs:

1. **Grade against the WHOLE prompt.** The first pass graded against 900 of 1,442 grounding
   characters and called several correct statements hallucinations.
2. **`unsupported numbers` in a run file is a tripwire, not a grade.** It catches invented
   scores; it cannot catch a misread ordering or a wrong weekday, which were the two worst
   defects here. Read the text.

It calls a real model and costs real money. Developer tool, nothing schedules it.

---

### §B17 ✅ DONE: the UFC props timer, and the fold that broke it (`f7797ae`)

`legendarypicks-underdog-ufc-props` failed every 30 minutes from 16:07 with
`SourceIdentityConflict: source game key 291703 conflicts with canonical fighters`. The
fighters were never the problem. Game 1235 (Wint vs Chatman) had been folded into another
row, and the fold repointed `props` while leaving `prop_game_source_ids` pointing at a
game that no longer existed, so the guard read absence as a changed identity.

**Three call sites folded games by hand and every one of them knew about `props` only**,
because `props` is the table you think of. The fold now lives in
`prop_game_merge.fold_prop_game` with the list of referencing tables next to it, and
`dangling_source_mappings()` answers "is any mapping pointing at nothing" in one call.

Resolution also matches a **one-day window** rather than an exact date: Underdog files that
fight on 08-22 and ESPN on 08-23, and the exact match minted a second row for a fight we
already held under its ESPN event id.

Green: 80 props from 6 eligible of 13 source games, exit 0, zero dangling mappings.

---

### §B18 ✅ DONE: NFL and MLS props, from the relay we were archiving and not reading
(`29a7826`, `5dde0dd`)

This is the build §B13 asked for. `ingest_rotowire_props.py`, live on **both** databases:

```
nfl   1,080 props   29 games, all 29 linked to their ESPN event id   0 players queued
mls     362 props   15 games                                          1 player queued
```

Both verified through prod's own API on :8100, not inferred from a row count.

**What it does not take.** Only the publisher's `Game` category. The 750-odd NFL `Season`
futures have no fixture to key on, so they are counted and reported every run and want
their own table. That is the next NFL increment and it is where the season-long fantasy
questions live.

**Identity is a crosswalk.** RotoWire publishes its own player id in the profile link, so a
player resolves once and binds in `player_source_ids`. The ladder is exact name, then
club-scoped rules for the shapes each league actually produces: a dropped generational
suffix (`Chris Godwin` for `Chris Godwin Jr.`), a dropped middle name (`Juan Sanabria`),
a mononym (`Luighi`). Every fallback needs the club to agree AND a unique hit inside it.
A nickname (`Andrew` for `Andy Thomas`) is not derivable, so it queues.

**`Soccer` is five competitions under one label.** MLS shares it with La Liga, Ligue 1,
Serie A and the Premier League, so resolving both clubs against MLS's own roster is the
competition filter as well as the team map. 56 rows from other competitions were left
alone, correctly.

**Two things worth carrying forward.**

1. **The club matcher has to see through OUR spellings too.** It minted two duplicate
   fixtures before it did: our rows say `DC United` and `Los Angeles FC` where ESPN says
   `D.C. United` and `LAFC`. Match resolved codes, never strings.
2. **`markets` is keyed on the publisher's marketID and checked against its name.** An id
   whose name moved underneath us is a different market wearing the same number, and it
   refuses rather than filing new lines under an old key.

**My mistake, and it is worth reading.** I folded two prod duplicates by id, then ran the
same two ids against dev, where they were a tennis match and an MLB game. 32 ATP props
landed on two MLB fixtures. Fully restored (the props separated cleanly by player league,
and the deleted fixture rows were recoverable from the other database, which ingests the
same ATP board). **A prop_games id is meaningful in ONE database.** Fold by content, never
by an id you read somewhere else.

---

### §B19 The props board, read in a real browser, and the date column underneath it

**Micah: "houston dynamo vs whitecaps isnt on todays prop board. its on for tomorrow. but
scoreboard shows it properly as tonight's game."** Rendered both surfaces headless
(playwright against the chromium already in `~/.cache/ms-playwright`, no download) rather
than reasoning from SQL, which is the only reason this was found: **the two surfaces had
DIFFERENT bugs.**

```
tunnel (dev)          the game is absent from the board entirely
legendarypicks.xyz    the game IS there at 9:30 PM, but sorted above the 7:00 PM games
```

**Defect 1, dev: 17 of 30 upcoming MLS rows had no `start_time`.** Against 0 of 30 NFL,
0 of 10 MLB, 0 of 11 ATP. The board places a game by its kickoff, so a row without one
cannot be put on a day at all and silently leaves the slate. Every one of those rows
already carried an `espn_event_id`, and ESPN publishes the kickoff on a scoreboard we fetch
anyway. **We were not missing the data, we were not storing it.** Fixed both ways in
`ae38a7a`: the relay ingest fills a missing time on a row it matched (it used to set one
only on rows it created, throwing away the instant the publisher handed it), and
`backfill_prop_game_start_times.py` repaired what was stored, 18 rows on dev and 22 on
prod, on a 6-request budget. Board went 13 games to 15, verified in the browser.

**Defect 2, prod: the slate ordered by `pg.date` first.** That column carries two
conventions, so once two rows on one night disagreed about which day a 21:30 ET kickoff
belongs to, the later game sorted first. The `_UPCOMING` filter had already been moved to
the instant on 08-17; the ORDER BY one line down was left on the date. `19c227d` gives both
the same named expression. **Needs the prod rebuild to appear on legendarypicks.xyz.**

**The column itself, still open and Micah's call.** `prop_games.date` means two different
things:

```
bovada-written MLS rows   the UTC date of kickoff   -> a 21:30 ET game is filed TOMORROW
relay-written rows        the local slate day       -> filed tonight, like the scoreboard
```

**ESPN settles which is right**: `espn.games('mls','2026-08-19')` returns event 761739 at
`2026-08-20T02:30Z`. The publisher files a 02:30Z kickoff under Aug 19. So the local slate
day is correct, and `_slate_day()` (already used by the scoreboard store) is the rule.
Still wrong today: **9 rows on dev, 10 on prod**, reported by the backfill and deliberately
not changed, because that column feeds settlement and ~33 references across 12 modules.
The migration is: one writer helper, recompute `date` from `start_time`, and a test pinning
`date == _slate_day(league, start_time)` so it cannot drift again.

**A rule Micah raised and it is the more valuable half: backfill vs fix-the-ingest-and-rerun.**
A backfill is for values the ingest can no longer produce (the event has passed, the source
has moved on). If the ingest can regenerate it, fix the ingest and re-run, or the same hole
reappears tomorrow. Today needed both halves and got both. **Write this rule down properly.**

---

### §B20 MLS market coverage, measured against the eleven-market list

Micah asked for "the 80% of props". Measured on prod:

```
YES  shots 52, shots_on_target 10, passes_attempted 160, saves 54,
     clearances 38, crosses 12          <- all six NEW today, from the relay
YES  goals 833, assists 920             <- bovada, already had these
no   attempted_dribbles, tackles, fouls
                                        8 of 11 = 72%
```

**Six of the eight landed today**; MLS had two before this session. The relay prices
**7** Soccer markets and we take all 7, so there is no unmapped remainder to go collect.

The three missing are not available from anything that answers this box: the relay does not
price them, Bovada does not, and DraftKings does price player tackles but every DraftKings
host is walled at the Akamai edge for this IP (6 hosts probed 2026-08-16, all 403 including
the plain HTML page).

**The real weakness is depth, not breadth.** The relay carries ~157 MLS props a day across
15 fixtures and only PrizePicks lines for soccer, where NFL gets all three books. So
`crosses` is 12 rows and a relay-only fixture shows 4 props against a Bovada fixture's 120.

**Do not reach for Kambi to fix this.** `ingest_kambi_mls_props.py` exists, is OFF on
purpose, and its own docstring says why: it prices goals, assists and a shots-on-target
market that appeared on one fixture of thirty-two. Two sources writing goals and assists
into one board, where one of them answers almost none of the eleven-market question, is a
disagreement to adjudicate for no gain. It ran on dev at some point and never on prod,
which is why dev shows 3,059 kambi MLS props and prod shows none.

---

### §B13 Our prop market coverage is far behind our sources, and it is NOT just soccer

> **UPDATE 2026-08-19 evening: NFL and MLS are built and live. See §B18.** Still open from
> the table below: NCAAF (opens Aug 29), WNBA (0 of 17, in season now), NBA and NHL. The
> name-welded MLB `market` column is untouched and still 57% of all props.


**Micah asked about the soccer props gap and suspected it was wider. It is.** Measured
2026-08-19 against today's RotoWire archive (§B10), our `props` on `picks.db` versus the
markets the relay carries for the same sport:

| league | ours | theirs | examples we do not carry |
|---|---|---|---|
| **nfl** | **0** | **24** | Passing TDs, Receiving TDs, FG Made, Total TDs, Sacks, Tackles+Assists |
| **ncaaf** | **0** | **8** | Rush+Rec Yards, INTs Thrown, Passing TDs, Kicking Points |
| mls | 5 | 8 | Passes Attempted, Chances Created, Crosses, Shots on Target, Clearances |
| wc | 4 | 8 | same soccer set |
| nba | 0 | 4 | Points/Assists/Rebounds AVG, Triple-Doubles |
| nhl | 0 | 3 | Goals, Points, Hat Tricks |
| **wnba** | **0** | **17** | 3PT Made, BLK+STL, Assists, Rebounds, in season right now |
| ufc | 3 | 2 | we are ahead here |
| atp/wta | 5 | 0 | tennis absent from their board today |

**Re-measured 2026-08-19 (second pass, same method).** Every number above reconfirmed, with
one addition: **WNBA is 0 of 17 and is in season today**, which the first pass omitted from the
table entirely. MLB is 18 of theirs, not 17.

**The headline is not soccer. It is NFL: zero props, twenty-four markets available, today,
inside the draft window that orders the whole roadmap.** NCAAF is the same shape and opens
**Aug 29**.

**A data-quality finding underneath it, now measured properly. My first pass named the wrong
cause.** I wrote that `market` "carries raw publisher strings like `total_hits,_runs_and_rbis`".
That is wrong: `total_hits,_runs_and_rbis` is one of the **clean** ones. The real cause is that
**the player's name is welded into the market key**:

```
total_bases___tyrone_taylor_(chc)          4 rows
total_doubles___stuart_fairchild_(cle)     2 rows
total_pitcher_walks___max_meyer_(mia)      4 rows
```

Measured on `picks.db`:

```
mlb distinct markets containing `___`   1,427   <- one key per player per market
mlb distinct markets that are clean         9   <- outs, strikeouts, total_bases, hits_allowed ...
rows carrying a name-welded market     34,652   <- 57% of all 61,031 props
also affected                          atp 2, wta 2
```

**So MLB does not have 1,436 markets, it has 9**, and 34,652 rows have a key that can never
group with another player. Every hit rate, per-market rollup and research board built on
`market` is grouping on a key that is unique per athlete, which means **it silently returns a
sample of one instead of a market**. It does not error; it under-counts. This is the
ambiguous-key shape again: it never raises, it misses.

That wants normalising **before** more markets land on top, and the fix is a parse of the
existing column, not a re-ingest: the market and the player are both recoverable from the
string, and `player_id` is already on the row to check the split against.

**Acceptance criteria**

- NFL and NCAAF props ingested from the relay, since the archive already proves what is
  available and the draft window is the reason this product exists.
- A controlled market vocabulary, publisher strings mapped onto it, with unmapped strings
  **logged, never silently dropped**.
- `source` distinguishes relay props from Bovada props; neither overwrites the other.
- Coverage reported as a fraction of each league's slate.

**Skills to load:** `published-first`, `fail-loudly`, `honest-data-ui`.

---

### §B14 ✅ CLOSED 2026-08-19 23:15. Prod was in `delete` mode; dev was in `wal`.

**Cause confirmed, and it was one line of state, not code.** `data/picks.db` was
`journal_mode=delete` while `data/picks.dev.db` was `wal`. Under `delete` a writer takes an
exclusive lock on the whole database and every reader waits, so prod's API reads, the
per-minute `scoreboard_snapshots` writer and the 30-minute props ingest all serialised. The
5s default busy timeout expired and `database is locked` came back out of the API as a 500.
**Dev could never reproduce it**, which is why it survived: the two databases disagreed about
a property nothing measured.

**Shipped in `7013ef1`, both halves live in prod:**
- Prod flipped to WAL (persisted, `quick_check` ok, container verified taking a write lock and
  managing `-wal`/`-shm`). `_init_db` now re-applies it on startup, because WAL is state on a
  FILE and a restore from a pre-08-19 backup would have silently undone it with no diff.
- 30s busy timeout at the two hot-path helpers, `_core._db` (the API's, imported by 61 non-test
  modules) and `scoreboard_store._db` (the per-minute writer), rather than all 176
  `sqlite3.connect(` sites. Container rebuilt 23:13 and confirmed reporting 30000 ms; all six
  API keys re-passed through. Rollback image tagged `legendarypicks-backend:rollback-20260819`.

**A guard had to be fixed first or the 23:20 history refresh would have died on the flip.**
`apply_ufc_history_merge.apply_plan` and `run_mlb_daily_history_ingest.apply_plan` both asserted
`journal_mode == "delete"`. Never a durability property; an environment assertion in disguise.
Now `ROLLBACK_SAFE_JOURNAL_MODES`, which still refuses `off`.

**5 new tests in `test_db_contention.py`, each confirmed to FAIL against the old code**, one
with the exact `production journal_mode is wal, expected delete` the refresh would have hit.
They assert `PRAGMA busy_timeout` on a real connection, not the constants.

**Honest limit on the verification.** The overlap test was weak: the suite ran 21:58:00-21:59:13
and props-prod ran 21:59:11-21:59:16, so about 4 seconds of true overlap on a 5-second ingest
with little to POST. It succeeded, but that is consistent with the fix, not proof of it.
**The real confirmation is a clean run of daytime slates**, when props-prod has 14 games to
POST rather than a handful. Check `journalctl -u legendarypicks-props-prod.service` for EXIT 3.

<details><summary>Original entry, written 2026-08-19 18:38 (kept: the reasoning was right)</summary>

### §B14 Prod's props ingest is 500ing: database is locked

Found 2026-08-19 while chasing the red `props-prod` timer.

```
props-prod  EXIT 3, "2 of 14 mlb games failed to POST"
scraper     FAIL ingest: HTTP Error 500
container   sqlite3.OperationalError: database is locked
```

So prod is **silently dropping 2 to 3 MLB games of props on every 30-minute run**. The
scraper reports it and exits 3, which is fail-loudly working; the 500 underneath is ours.

Likely contention between the ingest POST and the timers now writing `scoreboard_snapshots`
every minute. **Do not "fix" it by widening a try/except.** Candidates: WAL mode, a busy
timeout, or serialising the writers.

**UPDATE 2026-08-19 18:11, and this turns the guess into something testable.** The unit ran
**clean for nine consecutive runs**, 13:09 through 17:41, then failed on the first run that
overlapped my own writes to `picks.db` (the props ingests plus a pytest run against the prod
database):

```
12:09  EXIT 3   3 of 14 mlb games failed to POST
12:40  EXIT 3   2 of 13
13:09 .. 17:41  Succeeded  x9
18:11  EXIT 3   1 of 5      <- concurrent with my writes to picks.db
```

**So it is contention, not a standing condition**, and the number of dropped games tracks how
much else is writing rather than anything about MLB. Two consequences:

- The fix is a **busy timeout and WAL**, not a retry loop and not a wider `except`.
  `ingest_rotowire_props.py` already opens with `timeout=30` for exactly this reason and has
  not hit it; the container's connection is the one that gives up at the 5s default.
- **Running the suite against `picks.db` while prod's timers are live will cause this.** That
  is worth knowing before someone reads a red props-prod timer as a product defect. The suite
  still MUST be run against both databases (`feedback_run_the_suite_against_both_dbs`); the
  point is to expect this, not to stop.

**Not yet confirmed.** This was written at 18:38 and the next scheduled run was 18:41, so
nobody has watched it recover with nothing else touching the database. **Check that first**:
if 18:41 and after are green with no code change, contention is proven and the busy-timeout
fix is the whole job. If it is still red on a quiet box, the cause is something else and the
nine clean runs were luck.

**Skills to load:** `fail-loudly`, `resource-check`.

</details>

---

### §B9 Carried from 2026-08-18, still open

- **Tennis**: 264 of 304 prod ATP/WTA `prop_games` unlinked, so **2,475 props cannot reach a
  game page**; ATP and WTA settle **0 of 4,521** on both databases.
- **World Cup**: 392 prod "settled" rows are voids with NULL `hit`, grading nothing.
- **UFC settles 112 on prod and 0 on dev.** A green dev suite says nothing about UFC
  settlement.
- **MLB `team_stats` is 16 rows** against 3,364 game-detail rows.
- **Story generation** deserves its own timer. Its DeepSeek 402 is now §B12, measured.
- **Not started, queued by Micah:** Bovada and Kalshi live games plus game detail; the daily
  RotoWire props dump.
- `docs/BACKLOG-holes.md` was rewritten 08-18 and is current.

---

## §C In flight right now

**MERGED TO `dev` (`d725ce8`), audited first.** Items 1-3 plus the split repairs are on `dev`
and pushed. They were never on `dev`: they sat on `scoreboard-outcomes-homepage`, so for part
of the day the props-refresh fix existed only on a feature branch while the running systemd
units were patched on the host directly.

**The audit found one real defect, and it is the §B0 shape again.** `ufc_outcome` derives
Decision from `period == regulation.periods` plus a full-round clock, and never checked that
the fight was over. A LIVE fight at the start of its final round publishes exactly those
values, since UFC rounds count down from 5:00:

```
before   LIVE, start of R3   ->  ('Decision', 3, '5:00')
after    LIVE, start of R3   ->  (None, None, None)
```

The card never showed it (`GameCard` gates on `isUFCFinal`), but the value was written into
the normalized game and into `scoreboard_snapshots`, so every other reader got a verdict on a
fight still being fought. Guarded on `status.type.completed`, **not** `state == "post"`, since
a postponed fight is also `post`. Fixed in `27b689e`.

**Why the tests could not have caught it, which is the more useful finding.** The fixture built
`status.type` as `{"state": "post", "description": "Final"}` with **no `completed` key**. ESPN
always sends it, measured on the real 2026-08-15 payload:

```
{"id":"3","name":"STATUS_FINAL","state":"post","completed":true,...}
```

So the suite was asserting against a payload the publisher never sends, and the field the guard
needed was the field the fixture had dropped. A fixture is a claim about the publisher and is
falsifiable the same way any other claim is. Fixture corrected and the empty-window cases added.

Also fixed: em dashes in the homepage `<title>` and meta copy (`ce9a921`).

Suite **1626 passed / 1 failed on both databases**, the failure being the long-standing
`test_story_form_season` MLS case.

| who | what | state |
|---|---|---|
| reasonix | `TASK-scoreboard-outcomes-and-homepage.md` items 1-3 (§B1, §B2, §B3) | **audited, fixed, merged to `dev`** |
| reasonix | `TASK-route-espn-through-paced-http.md`, 17 modules | partially done |
| me | §B4, ESPN field capture + call-overlap audit | not started |
| me | §B10, RotoWire daily archive | **done and running** |
| me | §B11, the split's outside-the-repo breakage | **fixed** |
| Micah | §B12, DeepSeek balance | **blocking previews, recaps and narratives** |

**⚠ Commit hygiene note.** I ran `git add -A` while reasonix had the tree open and swept 124
lines of its in-flight item-1 work into `b9646f7`, a commit whose message describes a docs
change. It is pushed. I did not rewrite it, because reasonix had already reconciled against
that sha and a force-push under a working agent is worse than a wrong message. **If you are
reading `b9646f7` later: its contents are the UFC method-of-victory work, not documentation.**
Rule saved to memory: stage explicit paths, never `-A`, in a shared tree.

**Ready to tag v0.8.4, pending Micah's go.** 38 commits since v0.8.3, suite **1,675 on both
databases** (one long-standing `test_story_form_season` MLS failure, unrelated), both news reds
closed, zero 402s since the LLM swap, the UFC timer green, and NFL + MLS props live and served
by prod's own API. What will still be open after the deploy, stated so the call is made with
the list rather than the checkmark: NCAAF props with the season opening **Aug 29**, WNBA 0 of
17 while in season, and NBA/NHL (§B13); the name-welded MLB `market` column, 57% of all props
(§B13); ATP/WTA settling 0 of 4,521 (§B9); and the §B14 locked-DB 500, which has gone quiet
without being confirmed fixed.

**Two things in this release only take effect on a REBUILD.** The slate ordering fix
(`19c227d`) is serving code, and prod runs the 09:41 image, so legendarypicks.xyz still
shows a 9:30pm MLS game above the 7:00pm ones until prod is redeployed. The start_time
backfill is data and is already live on both databases. **Verify the ordering in a browser
after the deploy, not from a 200.**

**One infra decision left open on purpose.** Nothing schedules `ingest_rotowire_props.py` yet.
It wants a timer, and the cadence is a real choice: the relay is not an ESPN host so it costs
nothing against that budget, but a line that moves is only worth capturing as often as we will
look at it. Not installed unannounced, per the rule that infra changes get explained before
they get built.

**⏰ Waiting on tomorrow, not on a person.** The ESPN spend log now has one clean day under
it. Re-run the §1b analysis against a second day and read the result per the table at the top
of this file. It decides whether cross-process coordination gets built at all, and it is the
only open item here that gets cheaper by waiting rather than more expensive.

**⚠ Prod's API is 23 commits behind `dev` and was NOT redeployed today.** The image dates from
09:41 (v0.8.3); everything after it is dev-only. Prod's timers DO have the fixes, because they
run from the repo working tree, so prod is currently split across two versions. See the
"where this is running" table at the top of this file.

**Timers red right now:**

```
legendarypicks-news         GREEN as of 16:22   fixed by the provider chain, §B12
legendarypicks-news-prod    GREEN as of 16:24   fixed by the provider chain, §B12
legendarypicks-props-prod   RED as of 18:11, `EXIT 3`, "1 of 5 mlb games failed to
                            POST". The §B14 shape. It ran CLEAN 13:09 through 17:41,
                            nine consecutive runs, then failed on the first run that
                            overlapped my writes to `picks.db`. See §B14, which now has
                            a testable cause rather than a guess.
legendarypicks-underdog-ufc-props   GREEN as of 18:02. Was RED from 16:07, dev only,
                            and it was a stale source mapping, not an identity
                            conflict. Fixed in `f7797ae`, see §B17.
```

**⚠ NEW red, and it is not from today's work: `legendarypicks-underdog-ufc-props`.**

```
SourceIdentityConflict: source game key 291703 conflicts with canonical fighters
```

First and only occurrence 2026-08-19 16:07. `ingest_underdog_props.py` was not touched today
and nothing changed goes near identity resolution. This is the fail-loudly guard working: an
Underdog game key maps to one of our games whose fighter set does not match, so it refuses
rather than mislink props. **Dev only** (`LP_DB_PATH=picks.dev.db`), but UFC props are not
refreshing on dev until someone diagnoses game 291703. This is the ambiguous-key shape with a
raise bolted on, which is the correct end state; the conflict itself still needs reading.

**Suite baseline: 1622 passed / 1 failed** on both databases, the long-standing
`test_story_form_season` MLS case.

## §D New this session

- **Skill added: `.claude/skills/answer-is-already-here`.** Written because I stopped at
  "espn.com 403s this box" and handed back five research questions, when ESPN's field set was
  in our own cache. Six-rung ladder to walk before escalating, plus the ban on filling a gap
  with a plausible story.
- Memory: `feedback_explain_infra_before_building`, and the corrected record of why the spend
  ledger was reverted (the handoff's reason was **invented**; Micah's real one was that it
  was never explained to him).
- **`backend/prop_game_merge.py`.** One place that folds a `prop_games` row into another,
  carrying every reference with it, plus `dangling_source_mappings()` to ask whether any
  mapping points at nothing. Three call sites used to do this by hand and all three moved
  `props` only. See §B17.
- **`backend/ingest_rotowire_props.py` + 22 tests.** NFL and MLS props off the relay. §B18.
- **Read the page in a browser before diagnosing it.** The two surfaces had DIFFERENT
  bugs (see §B19) and no amount of SQL would have separated them. Playwright works from
  this box with `executablePath` pointed at the chromium already in
  `~/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome`; there is no need to run
  `npx playwright install`, which is also the command that empties a worktree's shared
  `node_modules`.
- **A rule to write down: backfill vs fix-the-ingest-and-rerun.** Micah's, and it is the
  more valuable half of §B19. A backfill is for values the ingest can no longer produce.
  If the ingest can still regenerate it, fix the ingest and re-run, or the hole reappears
  tomorrow.
- **Lesson worth more than the code: a `prop_games` id is meaningful in exactly ONE
  database.** I folded two duplicates on prod by id, then ran the same ids against dev,
  where they were a tennis match and an MLB game. Recovered in full, but fold by content,
  never by an id carried over from somewhere else. This is a new instance of
  `feedback_stale_data_looks_clean`: both databases answer every query, so nothing tells
  you the id you are holding belongs to the other one.
