---
name: resource-check
description: MUST load before running ANY CPU/memory/IO-heavy batch job on this box — backfills, multi-chunk loops, bulk scrapes, multiprocessing workers, full-range ingests. Enforces reading the script's actual implementation for hidden parallelism/memory footprint AND checking current load/memory headroom, then saying the expected cost BEFORE running, especially while the live dev server/tunnel is up. Triggers on backfill, batch job, bulk fetch, chunked loop, multiprocessing, full-range ingest, scrape all, "run this in the background", pkill/kill verification.
---

# Resource Check

Load this before dispatching any heavy batch job on this box (backfills, chunked
loops, bulk scrapes, anything spawning subprocesses or multiprocessing workers) —
whether you run it yourself or hand it to Hermes.

It exists because a 17-chunk MLB backfill (pybaseball `statcast()` + an internal
multiprocessing worker per chunk) ran back-to-back with zero throttling on this
box while the live dev backend, frontend, and cloudflared tunnel were up and the
user was actively browsing through them. Load average hit 9+, the user's page
load broke, and it was never flagged before or during — the user had to notice
degraded page loads and call it out themselves. A follow-up `pkill` was then
reported as having stopped the job when it silently hadn't.

It happened AGAIN the same night, worse (load 189, swap 3.9/4.0GB, tunnel
starved to death) on a script that had already been "fixed" once — because the
fix only chunked the *date range* the caller passed in; it never looked at what
`pybaseball.statcast()` does internally. That call spins up a thread per day in
the range via `ThreadPoolExecutor`, each holding a full day's wide pitch-level
DataFrame concurrently, then `pd.concat`s them all — invisible from the outside,
only visible by reading `statcast.py`'s source. Checking `uptime` before the run
looked fine; the box was already sitting at ~4.6GB/5.8GB baseline, and that
concurrency was what tipped it into swap thrashing.

## Two hard rules, both required — neither alone is enough

**1. Read the script before running it, not just its CLI args.** Actually open
the file (and anything it imports/calls out to — a library's `statcast()`,
`Pool()`, `ThreadPoolExecutor`, etc.) and ask: does this fork/thread internally?
Does it load a whole range into memory before processing, or stream it? A
chunked `--start`/`--end` argument on the outside says nothing about what
happens on the inside — the previous "fix" proved that. If a library call's
internals aren't obvious from the name, go read its source
(`python3 -c "import inspect,X; print(inspect.getsourcefile(X))"` + Read) before
trusting it on this box.

**2. Check current load AND memory headroom, then say the cost out loud BEFORE
running at full speed.**

```
uptime
free -h
ps aux --sort=-%cpu | head -10
```

`uptime` alone is not enough — this box's real ceiling is RAM/swap (5.8GB total),
not CPU. Check `free -h` every time; if `available` is under ~1-1.5GB, that's
already tight before adding anything. Then tell the user: what the job will
cost (CPU%, memory, duration, subprocess/thread count), and whether it contends
with the live dev server / tunnel on this box. If a live dev server or tunnel is
running, treat that as a hard constraint on how aggressively background work
can run — not background noise to ignore.

## Prefer throttled execution

- Test on the smallest real unit first (one day, one page, one item) and watch
  `free -h`/`uptime` during that single unit before trusting the loop at scale.
  A chunk size that "worked before" on a different code path is not evidence —
  the MLB backfill's 7-day chunks had already "worked" 8 times before the
  script's internal per-day threading finally blew it up on chunk 9.
- Small chunks (e.g. day-by-day, not a week or a 140-day range in one call) with
  brief pauses between them, not a tight back-to-back loop.
- Single-process/single-thread over any internal parallelism (library defaults
  like `parallel=True` included) when the box is already serving a live dev
  environment.
- Check `uptime` AND `free -h` again mid-run on anything that takes more than a
  couple minutes; stop and flag if load or swap climbs, don't wait for the user
  to notice.

## After killing anything

Verify the target process is actually gone (`ps`/`pgrep`) before telling the
user it's stopped. A `kill`/`pkill` exit code alone is not proof — it can fail
silently (wrong PID, race with a loop that respawns children), and reporting
"stopped" when it isn't is its own separate trust failure, distinct from the
resource problem itself.

## Known ceiling on this box

This box has a history of resource exhaustion under concurrent load (parallel
worktree dev servers OOM'd it once independently of this incident). Same
underlying discipline applies whether the load is parallel servers or a single
heavy sequential job: check first, throttle, say something before being asked.

## Note on enforcement

No hook backs this — the user explicitly rejected a `PreToolUse` hook on Bash
(both a blocking variant and an informational `uptime`-injection variant).
This skill, loaded by judgment, is the entire mechanism. Don't propose a hook
for this again unless the user brings it up.
