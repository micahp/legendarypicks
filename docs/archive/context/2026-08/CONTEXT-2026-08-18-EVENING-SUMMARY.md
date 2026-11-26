# 2026-08-18 evening — range backfill: the §7.2 open item is closed

Previous: [2026-08-18 handoff](/root/legendarypicks/docs/CONTEXT-2026-08-18-HANDOFF.md).

## What was done

The backfill now fetches finished days by date RANGE (`?dates=YYYYMMDD-YYYYMMDD`)
instead of one request per (league, day). That was open item §7.2 of the
morning handoff, and the whole point of rung 3 of the `espn-request-budget`
skill.

### Measured first, clean (not during the block — the §3 lesson)

The only prior measurement of the range form was taken mid-block and was
worthless; these were all taken after the hosts recovered, and each one
changed the design:

| probe | result | design consequence |
|---|---|---|
| `mlb ?dates=20260814-20260816` | 200, 44 events | range form works |
| `mlb ?dates=20260801-20260830` | **exactly 100 events, cut mid-day** | response is capped ~100 events |
| `mlb ?dates=20260816-20260819` | 56 events, complete | 4-day window is safe |
| `ufc ?dates=...` | 200, whole UFC 330 card | combat leagues answer |
| `mls ?dates=...` | 200, soccer events | soccer leagues answer |
| `atp/wta ?dates=...` | **events: []** | tennis must stay per-day |
| bucket rule vs store | 374/374 rows exact | US leagues → America/New_York date; tennis → UTC |

The "one request per league for the whole window" hope from the handoff is
dead: ESPN caps the response at ~100 events, so the backfill chunks the
window (5 days max) and splits a chunk in half when it comes back at the
ceiling. The 65-request backfill becomes ~27 requests on this run.

### Code

- `espn_client/scoreboard.py`:
  - `games()` refactored to `games()` + `_games_from_payload(league, date, d)`
    (pure move, no behaviour change — the 1574-suite baseline held).
  - `scoreboard_raw_range(league, start, end)` — the range fetch.
  - `_ny_date()` / `_slate_day()` — DST-aware America/New_York day bucketing
    (no zoneinfo on the py3.8 venv, so the DST rule is computed).
  - `games_by_day(league, start, end)` — one range request, bucketed by local
    day. Explicitly refuses tennis.
- `espn_client/__init__.py` — exports the new names.
- `ingest_scoreboards.py`:
  - `_range_chunks()` — contiguous runs, max 5 days, split at gaps and at the cap.
  - `_fetch_range_chunk()` — one range, saves each day, splits a capped chunk
    in half and retries (a truncated response cannot masquerade as a complete day).
  - `run_backfill_range()` — gating unchanged from `run_schedule`
    (`league_activity.plan` then `needs_refresh`); tennis per-day, everyone
    else ranged.
  - `main()` `--backfill` now calls `run_backfill_range`.
- `test_scoreboard_range_backfill.py` — 16 new tests (chunking, cap split,
  tennis refusal, bucketing incl. DST boundaries, dry-run no-request).

### Verified

- Targeted suites: 58 passed. Full backend suite: **1590 passed / 1 failed** —
  the one failure is the long-standing `test_story_form_season` MLS case from
  the handoff §6, unchanged; 1574 → 1590 is exactly the 16 new tests.
- Real run on dev: `--backfill 12` → **253 games stored, 0 failed, 29.9s**,
  spend `site.api=15, site.web.api=45` (the 15 site.api are the story threads
  it kicks — see below; the range work itself is the 45).
- Store: coverage now `2026-08-06 .. 2026-08-19`, 113 refresh rows, 627
  snapshots. Previously the handoff showed gaps from 08-08 back with only
  2–4 leagues/day; mlb 08-06/08-07 (11/15 games) and tennis 08-06..08-14 are
  the newly captured windows.
- Live on the 3096 tunnel: `/api/mlb/games?date=2026-08-07` serves 15 games,
  `x-lp-data-source: scoreboard_snapshots`. Back arrow answers `source=local`;
  the 64-instant cap trims display to the closest past window by design
  (`_SCHEDULE_CANDIDATE_LIMIT`), older days are reachable by stepping back.
- Prod `picks.db` untouched (mlb 08-06 = 0 rows there).

## Two things worth knowing

1. **The story threads the backfill kicks fail with 402.** `kick_game_stories`
   fires for mlb/nfl during the backfill (same as the schedule path), and the
   DeepSeek/OpenRouter provider answered `Insufficient Balance` (HTTP 402) for
   every story. That is §7.3's story-generation problem AND a billing problem
   — the provider account is out of balance. Story generation also reaches
   `site.api.espn.com` through `stakes.py` (walled since Aug 4), which is the
   15 wasted requests in the spend line. Not chased tonight: it is the §7.3
   open item, and the 402 needs Micah's billing call.
2. **The skill learned the range form.** `espn-request-budget` §7 now records
   the measured facts (answers for team/combat/soccer, empty for tennis,
   ~100-event cap, NY-vs-UTC bucketing rule) so the next person does not
   re-measure them mid-block.

## Open (unchanged from the morning handoff, minus §7.2)

1. **Prod deploy** — the whole scoreboard fix (including the range backfill)
   is dev-only. Still the user's call; container rebuild required.
2. **Story generation timer** (§7.3) — now with the added wrinkle that the LLM
   provider is out of balance (402).
3. **Bovada and Kalshi live games + game detail; RotoWire props dump at
   midnight** — queued from the user, not started.
4. The 3106/8106 dev pair is still dead and still not mine to kill.
