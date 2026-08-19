# Design: the outbound request budget

Written 2026-08-18. Reference document, not a handoff.

**Read §1b before writing any code against this.** §1 posed the question and §1b answers it
from a day of spend-log data: the limit is a **short-window burst rate**, not a request count
per host and not an hourly budget. §1 is kept as the reasoning that got there, not as an open
question. The last attempt at this was reverted; §1 says why.

---

## 1. The question that blocked this, and why (ANSWERED in §1b, 2026-08-19)

Both of these are measured and real, and they are not the same mechanism:

| | what it limits | evidence |
|---|---|---|
| **A. A request COUNT per host** | how many requests we may issue before the host starts refusing | 2026-08-04: `roster_sync.py` fired 128 requests back to back and tripped a wall. 2026-08-18: two concurrent backfills spending ~107 between them took `site.web.api`, `site.api` and `sports.core.api` all to 403 within minutes, including endpoints that had answered 200 an hour earlier. |
| **B. An event CAP per response** | how many events one scoreboard response will return | 2026-08-18: a 30-day `?dates=START-END` scoreboard request came back with **exactly 100 events**, truncated mid-day. |

**B is certain.** It is a pagination ceiling on a single response and it is reproducible.

**A is inferred from behaviour**, twice, and both times other explanations were available
(concurrency, a transient block, a different endpoint being gated). ESPN publishes no limit,
returns no `Retry-After`, and sends no `X-RateLimit-*` headers, so there is nothing to read.

If the real constraint is B, a cross-process request-count ledger is machinery for a wall
that does not exist, and the correct fix is chunking and caching, which is what the range
backfill already does.

### Why the last attempt was reverted, corrected 2026-08-18

`6b01fd1` (a cross-process spend ledger) was reverted as `fe82812` on 2026-08-17, three
minutes after it landed. The 08-17 handoff recorded the reason as "built on a misreading of
Micah's '100 limit per call'." **That is not the reason.** Micah's own account, 2026-08-18:

> I reverted it because first of all I didn't understand what you were doing, and I thought
> we could just do the 100 limit each call and it would be fine.

Two separate things, and both matter more than the technical argument:

1. **It was built without being explained.** A change to `paced_http`, which every ingest on
   the box imports, arrived as a fait accompli. Reverting something you cannot evaluate is
   the correct response, and the failure was upstream of the code.
2. **The model was "cap each call at 100 and we never cross the line."** That is coherent,
   and it is exactly what `HOST_BUDGET = 100` per process does. It holds **if only one job
   talks to a host at a time.** It fails because the cap is per JOB and the limit is per
   HOST: five jobs each stopping politely at 100 means the host saw 500. Every job tells the
   truth about itself and none can see the others.

The smallest demonstration is 2026-08-18: two backfills, each with a declared ceiling of 60,
each stopping short of it, together sending about 107 to one host, and all three ESPN hosts
began refusing. Both logs said "within budget". Both were correct.

So the disagreement was never really about the number. It is about whether the counter is
per process or per host, and that is worth settling with §4's data rather than with either
of our recollections.

**Do not rebuild the ledger until A is established from data.** Build §4 first: it is
non-destructive, it costs nothing, and it answers the question.

> **It did. §1b has the answer, and it says the hourly ledger this section was arguing about
> is the wrong shape.** Read it before acting on anything above.

---

## 1b. ✅ ANSWERED 2026-08-19 from the spend log: A is real, and it is a BURST RATE

The §4 instrumentation ran for a day and the question is settled. **Limit A exists, but it is
not a request count per host and it is not an hourly budget. It is a short-window rate.**

Measured over 27,801 ESPN requests, `2026-08-18T19:15` to `2026-08-19T19:37`, on
`site.web.api.espn.com` (the healthy host), comparing what preceded each 403 against a
2,000-request sample of 200s:

```
requests in the 60s   before a 403 : median   63     before a 200 : median   36
requests in the 5min  before a 403 : median  311     before a 200 : median  141
requests in the 1h    before a 403 : median 1238     before a 200 : median 1266   <- FLAT
```

**The hour is flat. The minute is not.** A refusal is preceded by roughly 1.75x the
per-minute traffic and 2.2x the five-minute traffic of a successful call, while the preceding
hour is indistinguishable (1238 vs 1266 is noise). Hourly volume does not predict a refusal:
02:00 ran 3,033 requests for 1.1% 403s while 17:00 ran 1,430 for 9.2%.

**The confound was tested and ruled out.** The obvious alternative is that high-403 hours run
different code against different endpoints. They do not: hot and cold hours run the same
processes (`ingest_scoreboards.py`, `__main__.py`, `pregenerate_game_stories.py`,
`settle_props.py`) in the same proportions against the same top paths. The 403s also spread
across all five processes (243/79/65/47/32) rather than concentrating in one, which is what a
shared host-level limit looks like and not what a per-process bug looks like.

### What this means for the design

A cross-process **hourly** ledger is the wrong shape and would not have prevented any of
these refusals. What the data asks for is a **short-window rate limit**, roughly a token
bucket over 60 seconds, which is far simpler: it needs no durable shared state, only a
per-host recent-request timestamp ring.

**Also settled: most of our 403s are not this at all.** Split by host, the "403 problem" is
mostly permanent refusals being retried:

```
site.web.api.espn.com        n=25188   403=  568 ( 2.3%)   <- the real rate signal
site.api.espn.com            n= 2606   403= 2588 (99.3%)   <- walled host
sports.core.api.espn.com     n=  232   403=  174 (75.0%)   <- gated endpoint
lm-api-reads.fantasy.espn.com n=    4   403=    0 ( 0.0%)
```

Two endpoints answer 403 essentially every time and account for **2,761 of 3,206 real ESPN
403s (86.1%)**:

```
2587 403 / 2587  100%  site.api.espn.com/apis/v2/sports/baseball/mlb
 174 403 /  232   75%  sports.core.api.espn.com/v2/sports/basketball/leagues/nba
```

Per the permanent-refusal rule (`.claude/skills/espn-request-budget` §5), **neither should be
retried at all.** A 100% refusal rate over 2,587 attempts is a gated endpoint, not a rate
block, and the fix is to stop asking, not to pace.

### ⚠ The instrument pollutes its own log

A third endpoint looked like the same thing and is not:

```
 102 403 /  102  100%  site.web.api.espn.com/apis/v2/sports/test/standings
```

**Those 102 requests never happened.** `test_espn_client_degradation.py:28` builds that URL to
exercise the 403 degradation path, and it mocks `urllib.request.urlopen` to raise a synthetic
`HTTPError(403)`. No packet leaves the box. But `record_spend` logs the attempt anyway, so
every suite run writes fake refusals into the file we are using to decide the budget.

This is small (102 of 27,801, and 3.1% of all 403s) and it is excluded from every number in
this section. It matters as a class, not a quantity: **an instrument that records simulated
events alongside real ones will eventually be read as if all of them were real.** Two obvious
fixes, either is fine: have the tests point at a non-ESPN hostname, or have `record_spend`
skip when `urlopen` is patched. The first is simpler and needs no production change.

### The concentration that governs everything

```
ingest_scoreboards.py      19,856 of 27,801 ESPN requests   = 71%
__main__.py                 2,991
pregenerate_game_stories.py 2,513
settle_props.py             1,656
link_prop_games.py            426
uvicorn (the serving path)    310
```

**One process is 71% of all ESPN traffic.** Whatever the budget turns out to be, it is
overwhelmingly a statement about `ingest_scoreboards.py`, which runs every 10 minutes. Pacing
that one caller is most of the available win, and a global ledger coordinating six processes
is machinery for the remaining 29%.

Note `uvicorn` at 310: the serving path does reach ESPN, so it must keep the serving posture
(no pacing, no retry ladder, `on_exhausted="refuse"`). See
`feedback_serving_path_must_not_enforce_a_batch_budget`.

### Limits of this measurement

One day, 25 hourly buckets, 466 usable 403s on the healthy host (the synthetic test-suite
403s are excluded throughout). The burst-rate conclusion is
supported by the 60s and 5min windows agreeing while the 1h window is flat, and by the
endpoint-mix confound being ruled out, but it rests on a single day of one traffic shape. It
does **not** establish the threshold. Median 63 requests in the preceding 60s says roughly
where refusals begin, not where they are certain. Before setting a number in code, re-run this
against a second day.

---

## 2. What is actually broken today, regardless of which limit is real

This part does not depend on the answer to §1.

`paced_http._host_spend` is a **module global in one process**. The budget is enforced per
process. Whatever ESPN's limit is, it is per host across every process on this box.

Measured 2026-08-18:

```
18 active systemd timers, roughly 8 to 12 of which touch an ESPN host
96 modules import espn_client or reach an espn.com host
~11 of them declare a budget at all
```

Everything else inherits `HOST_BUDGET = 100` as a **default, not a policy**. So the ceiling
we impose is 100 *per running process*, which on this box is north of a thousand before
anything throttles. `bovada_scraper` alone runs on three timers (`props`, `props-prod`,
`mlb-capture`), calls ESPN, and declares nothing, so that is three independent allowances
for one scraper.

Each process tells the truth about itself and none can see the others. That is the whole
defect, and it is an accounting problem, not a politeness problem. Spacing requests further
apart does not address it, which is why "add pacing" has failed twice.

---

## 3. Industry practice, and what of it applies here

The standard progression, in the order it is normally reached for:

1. **One chokepoint.** All third-party calls go through a single long-lived process: an
   egress service, a sidecar, or a job runner. Rate limiting becomes trivially correct
   because there is one counter in one place. A client library in every process is the
   recognised anti-pattern.
2. **If you must stay distributed, centralise the counter, not the client.** Redis with a
   Lua token bucket is canonical, because Lua gives atomic check-and-decrement. Algorithms:
   token bucket (allows controlled bursts), sliding window counter (cheap approximation),
   sliding window log (exact, more memory), fixed window (simple, but boundary spikes let
   you spend double across the seam).
3. **Queue the work.** Producers enqueue fetch intents, one consumer drains at a fixed rate.
   Retries, backpressure and dead-lettering come free.
4. **Let the server tell you.** Honour `429` and `Retry-After`, read `X-RateLimit-Remaining`,
   use adaptive concurrency (AIMD) and a circuit breaker.
5. **Cache first.** The cheapest request is the one not made.

**What applies to us, and what does not:**

- **(4) does not apply.** ESPN is undocumented and sends none of those signals. You cannot
  negotiate with a limit you cannot read, so the posture must be more conservative than for
  a paid API with an SLA, not less.
- **(5) applies most and is already paying.** The disk cache was the half of `6b01fd1` that
  was kept, because it took one repair sweep from 31 requests to 0. Bulk and range endpoints
  are the same lever: the range backfill turns 65 requests into about 11.
- **(2) applies, but not with Redis.** One box, SQLite already a dependency, WAL mode plus a
  single transaction is sufficient. Introducing Redis for this would be resume-driven
  infrastructure.
- **(1) is the real answer and the largest change.** See §5.

---

## 4. Step one: instrumentation. Build this first.

Nothing else should be built until this has run for a few days, because every number in this
document except the response cap is inferred.

Emit, per request, to a durable local store:

```
timestamp · host · path family · status · process name · was it a cache hit
```

Then the questions that are currently guesses become queries:

- What is our actual spend per host per hour, and what is the peak?
- How many distinct processes touch a host in the same minute?
- **Does a 403 correlate with a request count, or with a time of day, or with nothing?**
  This is the question that settles §1.
- Which jobs are the top spenders, and what fraction of their requests are cache hits?

Cost: one append per request. No behaviour change, nothing to revert, and it is the evidence
base for whatever comes next.

---

## 5. Step two, once §1 is answered

**If A is real** (a request-count wall):

1. Make `paced_http` the only way to reach an ESPN host, and make the budget
   **non-optional** rather than a default a module can inherit without noticing. A module
   wanting different behaviour declares it; a module declaring nothing draws on the shared
   pool, not a private 100.
2. Move the counter into SQLite, keyed by host, with a rolling window. This is `6b01fd1`
   rebuilt on evidence rather than on a reading of a sentence.
3. **Two pools.** The serving path gets reserved quota and refuses instantly when spent,
   which is already its behaviour since `e7e4108`. Batch jobs draw the remainder and wait.
   A page load must never sit through a batch job's cooldown.
4. **Circuit-break on 403.** Today a refusal teaches one process something and the other
   seventeen nothing. On 2026-08-18 that cost every ESPN host for several hours.
5. **Fail open on an unreadable ledger.** Refusing there would wedge every batch job on the
   box behind a file nobody knows to delete. This was right in `6b01fd1` and should survive.

**If A is not real** and B is the only limit, then the work is entirely different and
smaller: chunk every bulk read below the response cap, detect truncation rather than storing
a partial slate as complete, and keep caching. No ledger, no pools, no circuit breaker.

---

## 6. The invariants, whichever way §1 resolves

- **A shared resource needs a single owner.** Per-process counters against a per-host limit
  are a category error.
- **Make bypass impossible.** If a module can reach the API without the limiter, one
  eventually will. 96 modules can today.
- **Absent evidence is not a zero.** A truncated response, a refused host and an empty slate
  must be distinguishable in whatever we store, or we permanently record gaps as facts. This
  has already bitten twice: a capped range response stored as a complete day, and an empty
  range response retiring days forever.
- **Never retry a permanent refusal.** A 403 on one endpoint while others on the same host
  answer 200 is a gated endpoint, not a rate block. Hit a second endpoint before concluding.
- **Declare the spend before running the job, and print what it actually spent.** A job whose
  cost nobody can see is one nobody can size later.

---

## 7. History, so this is not attempted a fourth time

| date | what happened |
|---|---|
| 2026-08-04 | `roster_sync.py` fires 128 requests, trips a wall. The reflex fix is pacing. Pacing is the wrong lever: the run still spends 128, it just takes longer to get blocked. `.claude/skills/espn-request-budget` written from this. |
| 2026-08-04 | Blocks established as per **hostname**, not per IP or account. `site.api` walled from this box; `site.web.api`, `sports.core.api` and `lm-api-reads.fantasy` answer. |
| 2026-08-17 00:59 | `6b01fd1` adds a cross-process on-disk spend ledger with a rolling window, opt-in for batch callers, failing open. |
| 2026-08-17 01:02 | `fe82812` reverts it. The handoff records the reason as a misreading; **that is wrong** (see §1). Micah reverted it because the change was never explained to him, and because he understood the fix as capping each call at 100, which is correct per job and does not hold across eighteen of them. The disk-cache half is kept and pays for itself immediately. |
| 2026-08-18 | Two concurrent backfills each stop politely at their own declared 60 and together take all three ESPN hosts to 403. `ingest_scoreboards.py` gains an exclusive `flock`. That fixes one instance, not the class: it covers two timers out of eighteen. |
| 2026-08-18 | The range form is measured: 200 for team, combat and soccer leagues, `events: []` for tennis, and a hard **100-event response cap**. This is limit B, and it is the likely source of the misreading in the revert. |

---

## 8. What is gated on this

`/scores` rebuilt on the ESPN model (ROADMAP §6) has as its stated target **zero ESPN
requests to load a past date, enforced by a request-count gate**. That gate cannot mean
anything while the counter is per process and 17 modules reach ESPN without going through
`paced_http` at all: a gate reading a number that only some callers increment is a green
light that proves nothing, which is the exact shape this repo keeps re-finding.

So the order is: close the bypass doors
(`docs/TASK-route-espn-through-paced-http.md`), let §4 run and answer §1, then spec the
remainder of the scoreboard rebuild. Decided with Micah 2026-08-18.
