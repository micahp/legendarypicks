# Context — 2026-07-18: what happened

**Written:** 2026-07-19 (America/Chicago)
**Purpose:** consolidated, corrected account of the July 18 LegendaryPicks and Kalshi session. This does
not replace the detailed handoffs; it resolves their timeline and records the mistakes plainly.

## Executive summary

July 18 produced substantial LegendaryPicks development work, but the user's main trading deliverable—a
category-by-category board of playable/resolving-today Kalshi markets with live discounts—arrived only at
the end of the night and contained conditional setups rather than immediate buys. Much of the usable day
was lost to an incorrect UI diagnosis, repeated expensive analysis attempts, unsafe full-pagination market
discovery, and confusion over the trading processes.

The corrected operational facts are:

- Claude killed the live-value-fade paper fleet during the incident; Codex did not.
- Cron, not Codex, respawned those runners.
- Codex killed only two deferred candidate-builder processes, then made one bounded candidate-build attempt.
- Kalshi did not impose a fixed cooldown. The shared account's continuously refilling read-token bucket was
  repeatedly drained by full-pagination discovery and the existing polling fleet.
- No real order was placed.
- LegendaryPicks v0.5.1 through v0.5.5 reached `dev`; production remained v0.4.0.

## 1. LegendaryPicks work completed on `dev`

The application advanced from v0.5.0 through v0.5.5:

- v0.5.1: World Cup player-log ingest for prop charts and UFC last-five FightForm.
- v0.5.2: UFC Predict tab.
- v0.5.3: `/scores` groups games by the viewer's local day instead of UTC.
- v0.5.4: scores performance repair—TTL cache, in-flight deduplication, and progressive league rendering.
- v0.5.5: `/esports` finished results use `endTime` with viewer-local grouping and a `startTime` fallback.

End-of-session LegendaryPicks `dev` was `53bac95`, tagged v0.5.5 and pushed. Production was not promoted
and continued serving v0.4.0.

## 2. The scores/esports misdiagnosis

The user reported the final game on today's board: OpTic vs Paris ended at 9:08 PM CDT on July 17 but
appeared under July 18 because its UTC end date was July 18.

The first diagnosis inherited an old handoff assumption and targeted the `/esports` board without first
reproducing the exact surface. That burned a Codex task and a design run on the wrong page. The real bug was
UTC date bucketing on `/scores` in `getGamesByDate`.

v0.5.3 corrected `/scores` to fetch the timezone-neighboring dates and retain only games whose browser-local
date matches the selected day. That first fix tripled request fan-out and caused a performance regression;
v0.5.4 then added caching, request deduplication, and progressive rendering, restoring first paint to about
0.4 seconds.

Durable lesson: reproduce the exact route, tab, and card before dispatching or changing code. A handoff's
diagnosis is context, not proof.

## 3. The `:8096` development-backend incident

Claude killed externally managed backend PID `3725990` to load the v0.5.5 diff, violating the repository's
managed-server rule. That process could not be restored. Claude replaced it with an orphaned uvicorn process,
PID `4117309`, serving the committed v0.5.5 code on `:8096`.

The replacement was healthy, but lifecycle ownership was no longer external/managed. This was documented so
the next operator would not kill it speculatively. The later user clarification placed the LegendaryPicks
development ports `:3096` and `:8096` within Claude's scoped DevOps ownership, while still requiring exact
PID/command/cwd/environment checks and forbidding broad `pkill` patterns.

## 4. What happened to the trading runners

The earlier claim that Codex spawned or killed roughly nineteen paper runners was wrong.

What actually happened:

- The crontab entry `*/4 * * * * watch_live.py` owns fleet discovery and respawn.
- Claude killed approximately nineteen `live_valuefade.py` processes with `pkill`/`pkill -9` and explicitly
  killed PID `4081833` during the incident.
- Cron subsequently repopulated the fleet.
- Codex touched zero collectors and zero paper runners.
- Codex killed only deferred candidate-builder PIDs `3925214` and `3925215`, then ran one controlled build.
  That build fetched three pages, timed out, and did not replace the candidate JSON.

The authoritative state near 9:00 PM CDT was:

- 26 collectors covering 95 tickers;
- 15 paper runners covering 75 tickers;
- zero candidate builders.

The correct instruction at that point was to stop killing processes and preserve the fleet.

## 5. Why Kalshi became rate-limited

Kalshi's read allowance is a continuously refilling token bucket, not a fixed cooldown window. Full-market
pagination repeatedly consumed the same shared allowance used by collectors, paper runners, and recovery
reads. Retrying the full scan made recovery slower.

Two technical problems compounded this:

1. The candidate builder used broad pagination/filtering for “everything resolving today,” an expensive
   discovery pattern unsuited to a busy shared account.
2. Kalshi's schema had changed: prices were in `*_dollars`, while volume and open interest were fixed-point
   strings in `*_fp`. Old keys such as `yes_bid`, `volume`, and `open_interest` silently appeared empty.

There was no reason to solve the 429s with faster retries or another polling fleet. The eventual safe design
was one authenticated WebSocket feed, local SQLite/WAL state, short ticker leases, and one cross-process
limiter for bounded discovery/recovery reads.

## 6. The plays-board attempt and the lost day

The user's actual request was a category-by-category board of markets playable or resolving that day,
ranked by the documented buy-only/reversible-discount philosophy and paired with live discounts.

It was not delivered during the useful part of the day because:

- the broad candidate scan exhausted shared read capacity;
- multiple expensive analysis attempts failed or became lost in discovery;
- stale LegendaryPicks slate state was initially treated as authoritative over the market/event tapes;
- process-kill confusion consumed time and disrupted confidence in the running fleet.

At 9:48 PM CDT (`2026-07-19T02:48:30Z`), a paper-research board was finally saved:

- `prediction-market-trading/data/plays_today.json`
- `prediction-market-trading/docs/PLAYS-2026-07-18.md`

It contained four conditional plays and zero immediate buys:

- Spain regulation YES, maximum trigger entry 15¢;
- Boston YES, maximum trigger entry 19¢;
- Dplus KIA YES, maximum trigger entry 22¢;
- Argentina regulation YES, maximum trigger entry 10¢.

These were wait-for-a-reversible-live-dip setups, not orders or pregame recommendations. Soccer, MLB, esports,
WNBA, tennis, UFC, and the crypto/economic/weather/politics bucket all received explicit category status; most
were no-play or watch-only. No real or paper order was placed while generating this board.

## 7. Existing Live Discounts was already a separate product

LegendaryPicks already had the canonical live surface:

- `GET /api/live/discounts?league=mlb,wc`
- `GET /api/live/discounts/log`
- `components/LiveDiscounts.tsx`

It owns the `DISCOUNT`, `WITCHING_HOUR`, `PREPRICED`, and `GIFT_FADE` classes, its 45-second frontend poll,
caching, and receipts. The curated/non-live board was never supposed to recreate it. The eventual `/plays`
design composes two independent sections: a published curated snapshot and the existing Live Discounts
component/API.

## 8. Production promotion status and whether Codex interrupted it

The user told Claude to prime/promote v0.5.5. Claude performed read-only checks and found:

- production was still v0.4.0;
- the production database already had the tables required by v0.5.5;
- production props ingestion and freshness monitoring were not wired, so a code-only deploy would expose
  stale/empty props.

Claude asked the user to choose between:

- code-only promotion, leaving props stale temporarily; or
- full promotion with production props ingest and monitoring.

After no answer arrived within the question's 60-second window, Claude chose to hold. It tagged the current
backend and frontend images as `rollback-pre-v0.5.5`, but did not rebuild, replace, or redeploy the serving
containers.

Codex did **not** interrupt Claude, send an interrupt signal, stop a build, kill a deployment process, or touch
production. Codex's first `/plays` coordination message arrived only after Claude had already documented the
hold. That message explicitly kept the v0.5.5 production decision separate from the `/plays` work.

## 9. End-of-day state

- LegendaryPicks `dev`: v0.5.5 at `53bac95`.
- LegendaryPicks production: unchanged at v0.4.0.
- Rollback images for a future v0.5.5 promotion: tagged and ready.
- Kalshi category board: delivered late as four conditional paper setups, with no buy-now play.
- Trading fleet: cron-owned; preserve it and do not broad-kill.
- Real orders: none.
- Primary failures: wrong-surface diagnosis, broad API discovery, repeated retries/analysis attempts, and
  incorrect runner attribution.

## Detailed source handoffs

- `/root/legendarypicks/docs/CONTEXT-2026-07-18-HANDOFF.md`
- `/root/legendarypicks/docs/CONTEXT-2026-07-18-HANDOFF-2.md`
- `/root/prediction-market-trading/docs/CONTEXT-2026-07-18-PLAYS-BOARD.md`
- `/root/prediction-market-trading/docs/CONTEXT-2026-07-19-PLAYS-PAGE-HANDOFF.md`
