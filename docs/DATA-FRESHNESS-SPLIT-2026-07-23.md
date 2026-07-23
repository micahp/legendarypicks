# Data freshness: what's on cron, what's lazy, what's neither (2026-07-23)

Triggered by: NFL Recent Trades showing empty on prod after the v0.6.0 deploy. Root cause was
mundane (new table, no ingest ever run against prod) but it surfaced that this codebase has three
different freshness strategies in play with no written rule for which one a new data source should
get. This doc is the inventory + the criteria, so the NFL ADP/transactions decision (and the next
one) has something to point at instead of a fresh judgment call each time.

## The three patterns in use today

### 1. systemd timer → ingest script → DB (push, scheduled)

The data is pulled on a fixed interval regardless of traffic; whoever reads the DB always sees
whatever the last successful run left behind.

| Unit | Interval | Feeds |
|---|---|---|
| `legendarypicks-props.timer` / `-props-prod.timer` | 30 min | `bovada_scraper.py all --ingest` — player props, all leagues, dev + prod |
| `legendarypicks-wc-props.timer` / `-wc-props-prod.timer` | 15 min | `bovada_scraper.py wc --ingest` — World Cup props |
| `legendarypicks-mlb-capture.timer` | 5 min | `bovada_scraper.py mlb --capture` — opening/closing odds snapshots |
| `legendarypicks-props-freshness.timer` | 30 min | not a data feed itself — watchdog: checks each env's latest `captured_at`, alerts + self-heals (re-triggers ingest) if >3h stale |

Common thread: **high-value-per-hour-of-staleness** data (live odds, in-progress capture) feeding a
**page that gets traffic** (props page). The timer cadence roughly matches how fast the underlying
number actually moves. This is also the only category with a freshness *watchdog* — everything else
below can go stale silently.

### 2. In-process background warmer + stale-while-revalidate (lazy, self-refreshing)

No systemd unit. A daemon thread started from `sports_service.py`'s FastAPI startup event re-pokes
an expensive endpoint on an interval; a request never blocks on a rebuild — it gets the current
cached value (possibly stale) while a background rebuild kicks off if the TTL's elapsed.

- **Esports slate** (`routers/esports/slate.py`): `ESPORTS_WARMER_INTERVAL_S` (default 900s/15min,
  `LP_ESPORTS_WARMER_INTERVAL_S` env override, `0` disables). Single-flight rebuild guard
  (`_up_rebuilding` + a stuck-rebuild watchdog) so concurrent requests don't pile up duplicate
  rebuilds. Explicitly documented rationale in-file: **with ~0 organic prod traffic, pure
  lazy-on-request caching means a short-lived match could pass entirely within one stale window and
  never surface as live** — the warmer exists to cover for the lack of real traffic, not despite it.
- Smaller **in-memory TTL caches**, same idea at a much smaller scope, no daemon thread (just "is
  the cached value older than N seconds, if so refetch on next request"): `breakingpoint_client.py`
  (300s), `cdl_client.py` (300s), `wc_context.py` bracket cache (120s), `espn_client.py` game-summary
  cache (20s), `backfill_team_stats.py` (30s).

Common thread: **externally-sourced, expensive-to-rebuild, read-heavy** data where the source system
itself updates faster than anyone will plausibly reload the page, and a slightly-stale response beats
a slow or empty one.

### 3. Manual one-off script, no scheduler at all (the gap)

Runs exactly when a human (or Claude) invokes it. Nothing re-runs it, nothing alerts if it's never
been run, nothing alerts if it silently stops mattering.

- `roster_sync.py` — NFL/other-league roster + `espn_id` spine
- `ingest_nfl_adp.py` — ESPN fantasy ADP (**today's incident, half of it**: table didn't exist on
  prod until run manually post-deploy)
- `nfl_transactions_sync.py` — ESPN transactions ticker, feeds Recent Trades (**today's incident,
  the other half**: existed on prod but only via a `--pages 3` default run that happened to catch a
  trade-free window; needed `--full` to backfill back to January and actually surface trades)
- `ingest_nfl_logs.py` / `ingest_mlb_logs.py` / `ingest_nhl_logs.py` / `ingest_nba_logs.py` /
  `ingest_wc_logs.py` / `ingest_mlb_pitcher_logs.py` / `ingest_nfl_pbp_logs.py` — all per-game-log
  ingestion, across every league. This is the same gap flagged in the MLB props-loop audit
  (`docs/SPEC-prop-loop-mlb.md`) and the 2026-07-23 handoff's "next up" note — **it's not NFL-specific,
  it's every league's box-score/game-log pipeline.**

Common thread: was built to answer a question once (verify a feature, backfill a season), then left
in place as if it were the ongoing feed. Nobody decided "this doesn't need a cron" — it just never
got one.

## The actual criteria (reverse-engineered from what's already working)

Looking at why category 1 and 2 work and category 3 doesn't, the split isn't "cron vs. lazy" as a
binary — it's answering two questions:

1. **How fast does the underlying real-world value change relative to how long a stale copy is
   tolerable?** Live odds move by the minute → timer. Esports match state changes over a game's
   duration, but a slightly-stale board is fine → warmer with a TTL matched to that duration. Season
   ADP or a roster's `espn_id` mapping changes over weeks → neither a 30-min timer nor a 15-min
   warmer is buying anything real.
2. **Does anything depend on it being current *without a human re-triggering it*?** Props page has
   traffic and a watchdog because staleness there is a visible, immediate product failure. NFL
   Recent Trades/ADP had neither — so the first time anyone looked, it was silently empty (ADP) or
   silently stale-in-a-way-that-hid-the-feature (transactions defaulting to a 75-row/trade-free
   window instead of the full season).

Category 3 isn't wrong because it lacks a systemd unit — it's wrong when the data source has become
a **live product surface** (Recent Trades is now a rendered section on a page people load) but the
ingest is still being treated like the one-time backfill script it started as. The trigger for
"needs a scheduler" isn't "has a cron would be nice" — it's "this became something a user-facing page
depends on including today's version of reality."

## Open question for the decision

NFL ADP + transactions are both now real, live-linked columns/sections on Player Rankings — by the
criteria above they've crossed into "needs *something*," but they don't obviously need the
30-minute-props-timer treatment either:

- ADP changes slowly pre-season (weekly refresh would be generous), and picks up urgency only as
  actual draft season approaches.
- Transactions/trades are bursty and rare (0 in the most recent 75 items when checked today) but
  each one matters the moment it happens — a daily incremental sync (the script's existing
  non-`--full` default, 3 pages / ~75 items) is enough to never miss one, it just needs to actually
  *run* daily instead of once.
- Neither has anywhere near props-page traffic, so a background warmer (category 2) buys nothing —
  there's no "cache serving stale while rebuilding" problem, there's just "nobody re-ran the script."

That points toward category 1 (systemd timer) at a much lower frequency than the props timers —
daily, not every 30 min — rather than category 2. But that's the call to make, not one to assume;
this doc is the input to that decision, not the decision itself.

## Decision (2026-07-23)

Daily systemd timer, category 1, matching the reasoning above. Shipped same day:

- `legendarypicks-nfl-adp.timer` / `-prod` → `ingest_nfl_adp.py` (idempotent `INSERT OR REPLACE`,
  safe to re-run) — dev 04:10, prod 04:15.
- `legendarypicks-nfl-transactions.timer` / `-prod` → `nfl_transactions_sync.py` in its existing
  default incremental mode (3 pages / ~75 items, `INSERT OR IGNORE` dedup — no need for `--full`
  on the daily runs now that the one-time backfill has already seeded history back to January) —
  dev 04:20, prod 04:25.

All four `Persistent=true` so a missed run (box down at 4am) catches up on next boot instead of
silently waiting a full day. Host-level systemd units, not repo files — not tracked in git (see
worktree-isolation note in `hermes-worktree.sh` docs: host config lives outside any checkout).

Also removed as part of the same pass: `legendarypicks-wc-props.timer` / `-prod` (World Cup ended
2026-07-19, last `prop_games` row for `league='wc'` is that date — nothing to keep polling for).
The ingest script (`bovada_scraper.py wc`) is untouched for next tournament; only the always-on
timers are gone.
