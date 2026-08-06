---
name: espn-request-budget
description: MUST load before writing or running any code that calls an ESPN host — site.api.espn.com, sports.core.api.espn.com, site.web.api.espn.com, lm-api-reads.fantasy.espn.com — or before diagnosing a 403/timeout from one. ESPN's limit is a request COUNT per host, not a rate, so pacing does not save you and sleeping longer makes a blocked job slower without making it succeed. Triggers on roster sync, any per-athlete loop, "rate limit", 403 from ESPN, adding a league, and any ingest that would issue more than ~50 requests to one host.
---

# The ESPN request budget

## 1. The one thing to know

**ESPN's limit is a COUNT per host, not a rate.** Measured 2026-08-04: roughly **100
requests to a single host** and that host starts refusing, regardless of how far apart the
requests were spaced.

This is the opposite of the intuition, and acting on the intuition is what cost a day.
`roster_sync.py` fired 128 requests back to back, tripped the wall, and the reflex fix was to
add pacing. Pacing was the wrong lever: the run still spent 128 requests, it just took longer
to get blocked. **The only lever that works is issuing fewer requests.**

A corollary that matters: once you are near the ceiling, *waiting does not restore the
budget within a run*. Do not write a retry ladder that assumes a 403 is transient. Treat it
as "this host is spent" and fail loudly.

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
5. **Only then**, pace it — and pace it to be polite, not because pacing buys budget.

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
