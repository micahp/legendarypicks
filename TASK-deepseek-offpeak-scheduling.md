# TASK — Move DeepSeek spend out of peak hours before 2026-08-16

**Opened** 2026-08-14 (Micah). **Deadline: 2026-08-16 UTC**, when DeepSeek's peak/off-peak
billing takes effect. **Status:** not started.

Companion to `TASK-scores-schedule-espn-model.md` — same root theme: expensive work is
happening on the request path and on timers nobody costed.

---

## 1. The pricing change — verified, not assumed

Fetched from `api-docs.deepseek.com/quick_start/pricing` on 2026-08-14:

> "Peak hours are **01:00 – 04:00 and 06:00 – 10:00 UTC** (all other hours are off-peak)."

Effective **2026-08-16 UTC**. Both models — `deepseek-v4-flash` and `deepseek-v4-pro` — bill
**off-peak at exactly half the peak rate**. So 7 of every 24 hours cost double the other 17.

Converted for this box (`America/Chicago`, currently **CDT = UTC-5**):

| | UTC | CDT (now) | CST (after Nov) |
|---|---|---|---|
| peak A | 01:00–04:00 | 20:00–23:00 | 19:00–22:00 |
| peak B | 06:00–10:00 | 01:00–05:00 | 00:00–04:00 |
| **off-peak** | 00:00–01:00, 04:00–06:00, 10:00–24:00 | 19:00–20:00, 23:00–01:00, 05:00–19:00 | shifts an hour |

**The DST row is not trivia — it is the defect waiting to happen.** Every timer below is
written in local time, so on the November CST switch every job moves an hour in UTC and jobs
that were safe walk silently into peak. **Pin every LLM-touching timer in UTC**
(`OnCalendar=*-*-* 14:35:00 UTC`) so the schedule means what it says year-round.

## 2. Who actually calls DeepSeek — measured

Grepped `backend/` on 2026-08-14. Four call sites, two classes:

**Scheduled (controllable):**

| call site | model | driven by |
|---|---|---|
| `core_stories.py:367` (`generate_game_story`) | `deepseek-v4-pro`, `max_tokens=8000`, `reasoning_effort=high` | `legendarypicks-game-recaps.timer` → `scripts/game-recaps.sh` → `pregenerate_game_stories.py` |
| `ingest_league_narratives.py:1455,1511` | `deepseek-v4-pro`, batch, `max_tokens=4000` | `legendarypicks-news.timer` / `-prod` → `scripts/news-collect.sh` |
| `discover_topics.py:299` | `deepseek-v4-pro`, `max_tokens=4000` | same news timers |

**Request path (NOT controllable by scheduling):**

| call site | trigger |
|---|---|
| `core_stories.py:367` again, via `kick_game_stories()` in `routers/games.py` | **any user loading the scoreboard for nba/nhl/mlb/nfl** spawns daemon threads that generate stories |
| `wc_context.py:1617,1624,1700` (`deepseek-chat`) | `/api/…/wc-context` request |

Two things that are **not** in scope, verified so nobody re-checks:

- `scripts/run_pipeline.py` has **no LLM step** (grep: zero hits for story/narrative/discover).
  Its `*/30 19-23,0-3` cron overlaps peak heavily, but that costs ESPN budget, not DeepSeek.
- `legendarypicks-news-x.timer` runs `ingest_league_news.py --x-only`, which has **zero**
  DeepSeek references. Classification there is not an LLM call.

## 3. Current collisions — computed

Local CDT → UTC, checked against the peak windows:

| timer | local | in peak |
|---|---|---|
| `legendarypicks-news` | 03:35 CDT | **1/1** — 08:35 UTC |
| `legendarypicks-news-prod` | 04:20 CDT | **1/1** — 09:20 UTC |
| `legendarypicks-game-recaps` | `1/3:40` (8×/day) | **3/8** — 01:40→06:40, 04:40→09:40, 22:40→03:40 UTC |

**4 of 10 scheduled DeepSeek runs per day land in peak**, and the two news runs — the ones
that are 100% in peak — are full-batch `deepseek-v4-pro` calls. `game-recaps` is the largest
single consumer (`max_tokens=8000` at high reasoning effort, per game, 8 sweeps a day).

`RandomizedDelaySec=300` on `news-x` and `game-recaps` can also push a run across a boundary.
Any job scheduled near a peak edge must have its jitter accounted for, or be moved away from
the edge.

## 4. The work

### W1 — Move the three scheduled timers off peak (do this before 08-16)

Pin all of them in **UTC**, and leave ≥15 min clearance from a peak edge to absorb jitter.
Proposed:

| timer | from | to (UTC) | = CDT | why |
|---|---|---|---|---|
| `legendarypicks-news` | 03:35 CDT (08:35 UTC, peak) | `04:20 UTC` | 23:20 | inside the 04:00–06:00 off-peak block |
| `legendarypicks-news-prod` | 04:20 CDT (09:20 UTC, peak) | `05:05 UTC` | 00:05 | staggered 45m after dev, same block |
| `legendarypicks-game-recaps` | `1/3:40` local | `*-*-* 00,04,10,12,14,16,18,20:40 UTC` | — | 8 sweeps/day, all off-peak, still ≤4h apart during US game hours |

Constraint to respect while re-timing recaps: the sweep exists to have a recap written by the
time someone opens a finished game. Keep coverage dense across US evening finals
(00:00–06:00 UTC = 19:00–01:00 CDT) — note that block is **mostly off-peak already**
(00:00–01:00 and 04:00–06:00), so the density is achievable; it is 01:00–04:00 UTC that must
be vacated.

### W2 — Get the model off the request path

Scheduling the timers does nothing about `kick_game_stories()`, which fires
`deepseek-v4-pro` at 8000 tokens **whenever a user loads a scoreboard**, at any hour. That is
uncontrolled spend and unbounded concurrency.

- Replace the fire-and-forget daemon threads with a **queue**: the request records that a
  story is wanted; a worker drains the queue and honours an off-peak window for anything not
  user-blocking.
- A story a user is *waiting on* may still generate immediately — that is the product. The
  bulk warming triggered incidentally by page loads is what moves to the queue.
- Same for `wc_context` enrichment: cache it, generate on a schedule, serve the cached read.
- This overlaps `TASK-scores-schedule-espn-model.md` W1/W2 — both are "the request path must
  not do expensive upstream work". Land them together if convenient.

### W3 — Make the spend visible

We do not currently know what DeepSeek costs us per day, which is why a pricing change is a
scramble rather than a number.

- Log per call: timestamp (UTC), model, prompt/completion tokens, and whether it fell in peak.
- A daily line in the pipeline log: calls, tokens, peak vs off-peak split.
- Then the gate: **assert no scheduled LLM job is configured to start inside a peak window**,
  computed from the timers' UTC `OnCalendar` plus their `RandomizedDelaySec`. A config test,
  so a future edit that moves a job into peak fails CI instead of appearing on an invoice.

## 5. Done means

- `systemctl list-timers` shows every LLM-touching timer with a **UTC** `OnCalendar`, none
  starting inside 01:00–04:00 or 06:00–10:00 UTC including jitter.
- The config gate in W3 is committed and green, with the peak windows as data in one place.
- One full day of the token log, showing the peak/off-peak split, recorded in this doc.
- Verified against the **timer**, not the unit file — `systemctl list-timers` prints the next
  actual firing; read that, in UTC.

## 6. Note for whoever picks this up

DST is the trap. Verify with:

```
systemctl list-timers --all | grep legendarypicks
TZ=UTC systemctl list-timers --all | grep legendarypicks
```

If a timer's UTC firing time changes when the box switches CDT→CST, it is not pinned and this
task is not done.
