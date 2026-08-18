# Design: the outbound request budget

Written 2026-08-18. Reference document, not a handoff.

**Read §1 before writing any code against this.** There are two different limits both
called "100" in this repo, and the last attempt at this was reverted because of it.

---

## 1. ⛔ The unresolved question: there are two "100"s

Both of these are measured and real, and they are not the same mechanism:

| | what it limits | evidence |
|---|---|---|
| **A. A request COUNT per host** | how many requests we may issue before the host starts refusing | 2026-08-04: `roster_sync.py` fired 128 requests back to back and tripped a wall. 2026-08-18: two concurrent backfills spending ~107 between them took `site.web.api`, `site.api` and `sports.core.api` all to 403 within minutes, including endpoints that had answered 200 an hour earlier. |
| **B. An event CAP per response** | how many events one scoreboard response will return | 2026-08-18: a 30-day `?dates=START-END` scoreboard request came back with **exactly 100 events**, truncated mid-day. |

**B is certain.** It is a pagination ceiling on a single response and it is reproducible.

**A is inferred from behaviour**, twice, and both times other explanations were available
(concurrency, a transient block, a different endpoint being gated). ESPN publishes no limit,
returns no `Retry-After`, and sends no `X-RateLimit-*` headers, so there is nothing to read.

This distinction is why `6b01fd1` (a cross-process spend ledger) was reverted as `fe82812`
on 2026-08-17, three minutes after it landed, **at Micah's instruction**, recorded as "built
on a misreading of Micah's '100 limit per call'." If the real constraint is B, a
cross-process request-count ledger is machinery for a wall that does not exist, and the
correct fix is chunking and caching, which is what the range backfill already does.

**Do not rebuild the ledger until A is established from data.** Build §4 first: it is
non-destructive, it costs nothing, and it answers the question.

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
| 2026-08-17 01:02 | `fe82812` reverts it at Micah's instruction: "built on a misreading of Micah's '100 limit per call'". The disk-cache half is kept and pays for itself immediately. |
| 2026-08-18 | Two concurrent backfills each stop politely at their own declared 60 and together take all three ESPN hosts to 403. `ingest_scoreboards.py` gains an exclusive `flock`. That fixes one instance, not the class: it covers two timers out of eighteen. |
| 2026-08-18 | The range form is measured: 200 for team, combat and soccer leagues, `events: []` for tennis, and a hard **100-event response cap**. This is limit B, and it is the likely source of the misreading in the revert. |
