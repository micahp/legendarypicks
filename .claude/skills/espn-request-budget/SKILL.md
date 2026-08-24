---
name: espn-request-budget
description: MUST load before writing or running any code that calls an ESPN host (site.api.espn.com, sports.core.api.espn.com, site.web.api.espn.com, lm-api-reads.fantasy.espn.com) or before diagnosing a 403/timeout from one. ESPN's limit is a BURST RATE per host, measured in requests per minute, not an hourly or per-run count: the hour is flat, the minute is not. So the two levers are issuing fewer requests and spacing the ones you issue, and a fan-out that inherits the serving path's min_interval=0 will refuse the request handlers' traffic along with its own. Triggers on roster sync, any per-athlete loop, "rate limit", 403 from ESPN, adding a league, and any ingest that would issue more than ~50 requests to one host.
---

# The ESPN request budget

## 1. The one thing to know

**ESPN's limit is a BURST RATE per host, not a count.** Measured 2026-08-19 across 27,801
requests from `backend/data/http-spend.jsonl`:

```
requests in the 60s  before a 403 : median   63     before a 200 : median   36
requests in the 5min before a 403 : median  311     before a 200 : median  141
requests in the 1h   before a 403 : median 1238     before a 200 : median 1266   <- FLAT
```

**The hour is flat. The minute is not.** Hourly volume does not predict a refusal. So there
are exactly two levers, and both are real:

1. **Issue fewer requests.** A bulk endpoint that returns 578 athletes in 6 calls beats 643
   per-athlete calls no matter how you pace them.
2. **Space the ones you do issue.** Requests per minute is the quantity being measured.

Do not build a cross-process hourly ledger. It is the wrong shape and would not have
prevented any of these refusals. A token bucket over roughly 60s per host needs no durable
shared state. Full working: `docs/DESIGN-request-budget.md` §1b.

**The budget is shared with the serving path.** 2026-08-24: the UFC plan fired 52 requests
inside one minute while `ingest_scoreboards` ran its normal 4/min. `site.web.api` refused for
four minutes and **26 of those refusals landed on uvicorn**, so a batch job made the live
site read as broken. Size a fan-out against what the box is already spending, not against
zero.

## 1b. SUPERSEDED: the count model

The 2026-08-04 reading of the same wall was "roughly 100 requests per host, regardless of
spacing, so pacing does not save you". That is preserved here because it is what this file
said for two weeks and because its **corollary is still true**: when a job needs hundreds of
requests, pacing alone will not rescue it, and the answer is a bulk endpoint or a cache.

What was wrong about it: the 08-04 runs measured successive attempts against a host that was
already tripped and cooling, which reads as a count ceiling. The 08-19 sample separates the
windows and the hour is flat. **Pace your fan-outs.** The line "sleeping longer makes a
blocked job slower without making it succeed" is what left the UFC ingest at min_interval=0
on 2026-08-24.

## 2. Per-host, and the hosts are genuinely different

Blocks are per **hostname**, not per IP and not per account. These are four separate budgets:

```
site.api.espn.com               roster / team surfaces   -- walled from this box
sports.core.api.espn.com        core entities, counts    -- answers fine
site.web.api.espn.com           bulk byathlete reports   -- answers fine
lm-api-reads.fantasy.espn.com   fantasy universe, ADP    -- answers fine
```

**A measured figure for one host does not transfer to another.** The ~100 ceiling was
measured on one host; do not assume it for the others, and do not assume a host that 403s
today is blocked forever. Probe the specific host before concluding anything about it.

`www.espn.com` (the website) has a separate bot wall that 403s datacenter IPs. That is not
the API limit and fixing one does not fix the other.

## 3. Before you write the loop

Walk this in order. Every rung above the last removes requests rather than spacing them.

1. **Is there a bulk endpoint?** One request for the whole league beats one per athlete.
   `ingest_nba_season_stats.py` exists solely because the per-athlete path cost **643
   requests** and published zero rows for years; the bulk `byathlete` report on
   `site.web.api` returns 578 athletes in **6**. Look for `byathlete`, `?limit=20000`, or a
   season-wide report before writing a per-entity loop.
2. **Does the publisher publish the count?** `sports.core.api.espn.com` returns the
   cardinality of any collection in a `?limit=1` envelope — one call, no traversal. Use it to
   size or verify a job instead of walking it.
3. **Is a different publisher cheaper?** MLB, nflverse and nhle.com publish league-wide
   files and have no comparable ceiling. If ESPN is not the issuer of the id you need,
   asking ESPN is a request spent for nothing.
4. **Can it be cached?** `paced_http` has a disk cache keyed on the URL. A second run inside
   the TTL costs **zero** requests — measured: 128 requests / 188s became 0 / 1.7s.
5. **And pace what is left.** Spacing is the second real lever, not a courtesy: the
   quantity ESPN measures is requests per minute. Set it where the fan-out happens (§4),
   and size it against the traffic the box is already producing, not against zero.

## 4. Use the shared client, and configure it where the work happens

`backend/paced_http.py` is the single home for pacing, the per-host budget and the retry
ladder. Do not hand-roll `urllib` with a `time.sleep` — six modules each had their own copy
and the one every serving path went through had none.

**Configure it in the function that does the work, not only in `main()`.** On 2026-08-04
`roster_sync`'s pacing and cache lived in `main()` alone, so every caller entering by
`import roster_sync; sync_league(...)` — which is how the production run was launched — ran
unpaced and uncached and paid all 128 requests again. *Configuration that only applies when
you enter through one door is configuration you do not have.*

Set `host_budget` so the job refuses rather than discovers the wall. A job that stops at its
declared budget with a clear message beats one that gets a 403 halfway and leaves a partial
write.

## 5. When you see a 403

**A 403 is not a reason to give up on the question.** It is a fact about one host at one
moment. In order:

1. Which host? Try the same question against a different ESPN host.
2. Is another publisher authoritative for this value? Usually yes.
3. Is it the website bot wall rather than the API? `www.espn.com` 403s this box always;
   `sports.core.api.espn.com` does not.
4. Wayback has historical pages when the live host refuses.

Never record "ESPN doesn't publish X" after a 403. Record the host, the parameters and the
date — a gap is a statement about which endpoint you asked, not a property of the world.

## 6. Before you call it done

- State the request count the job will issue, per host, **before running it**.
- If it is over ~50 to one host, justify why a bulk endpoint or a cache cannot cut it.
- Print the count the job actually spent. A silent job is one nobody can size later.
