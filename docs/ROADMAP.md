# Roadmap & bug ledger

Running list. Add to it, don't rewrite it — mark items superseded rather than deleting,
so the reasoning stays readable.

Last updated 2026-07-27.

---

## User evidence — 2026-07-26

First conversation with a potential user, and the first outside signal this roadmap has.

- Pitching **"the app" in general was hard. Pitching NFL was easy.** The framing problem is
  a scope problem.
- **She had no place she went to do draft research.** Not "she prefers a competitor" — no
  incumbent at all. That vacancy is what the board fills.
- **The v0.6.9 availability UX landed on a first-time viewer**: she could scan and see who
  misses games. Accent-marks-absence did its job on someone who'd never had it explained.

**Consequence: R6 moves up.** It was scheduled after v0.7.0, decided before anyone was
asking for the board. She cannot reach it — prod is v0.6.7 and the board is dev-only behind
a trycloudflare URL. Everything else on this list is an improvement to something no user
can open. See R7, R8.

---

## Now — v0.7.0

### R7. Player search on the draft board — **user-blocking**
522 eligible players, 50 per page, and the only controls are a position filter, a sort, and
prev/next. Draft research is name-driven — "what about Rashee Rice" — and today that means
paging. A search input over the board is the smallest change that makes it usable for the
thing she described doing.

### R8. Decide what happens to a user's draft notes
`rank` / `watch` / `fade` persist to `localStorage` under `lp_nfl_draft_notes`. Device-local:
gone on a cache clear, invisible between phone and laptop. Doing the research *is* the
retention hook, so this is the wrong storage for it long-term. Two options — label it
honestly as this-device-only for now, or move it behind an account. **Needs Micah's call;**
the account path is much larger than the label.

### R1. Rebuild `/api/nfl/draft-board` around availability
**The board already exists** (`routers/nfl_offseason.py`, contract `nfl-draft-board-v1`,
511 eligible players). It ranks by `fantasy_ppr_g` — points per *game played* — which is an
average conditioned on the player being healthy enough to play, i.e. the exact thing you
were trying to predict. It also ships `season_proj_pts = projection * games_assumed`, so it
already calls itself a projection, and `games_assumed` — the availability variable — is
computed internally and never surfaced.

What availability actually is, per Micah: **injuries, suspensions, and legal absences.** The
board's job is to help someone draft accounting for those *and* for snap share. Not a
statistics exercise — a "will this guy be on the field" exercise.

- Surface availability as the headline, not an intermediate.
- Show both numbers: PPR when played, PPR per team game.
- Season strips with visible gaps for missed games; accent colour reserved for absence.
- Stop labelling it a projection.
- Fold in snap share (`off_pct`) — a healthy player in a timeshare is a different risk from
  an injured starter, and the board must distinguish them.
- Scope: QB/RB/WR/TE. See R5 before assuming IDP/K.

### R2. 2024 in the UI without availability
2024 data can render immediately; it does **not** need the availability calculation to be
useful. Don't block the 2024 display on R1.

---

## Bugs caught, not yet fixed

### B1. Mid-season team change doubles the availability denominator
Joe Flacco reads `13/34` for 2025 because he changed teams and the denominator sums both
teams' full seasons. Denominator must be scoped to team games *while the player was on that
team*, or counted as distinct team-games in the season. Found while prototyping the
availability query — this would have shipped a visibly wrong number.

### B2. `team_game_results` has two incompatible key schemes
2025 rows use **ESPN event ids** (`401772718`); 2024 and 2026 rows use **nflverse ids**
(`2026_01_NE_SEA`). Consequences:
- 2025 rows do not join to `nfl_schedule` at all.
- Loading 2025 from `games.csv` naively would add 544 duplicate rows under the second
  scheme, giving 544 distinct game_ids each with 2 rows — **every 2025 game double-counted,
  breaking the team-stats aggregate** (34 games per team instead of 17). Do not do this
  without deduplicating first.

**Open question from Micah (2026-07-27): should we repull the schedule from ESPN instead?**
That would make every season ESPN-keyed and consistent with the existing 2025 rows, at the
cost of losing what `games.csv` gives free — rest days, roof/surface, spread/total lines,
coaches, starting-QB gsis ids. Not decided. Weigh before touching B2.

### B3. Team abbreviations disagree between tables
ESPN says `LAR`/`WSH`; nflverse says `LA`/`WAS`. `player_game_logs` is nflverse,
2025 `team_game_results` is ESPN. **The Rams and Washington already fail to join between
those tables.** Recorded as `ESPN_ALIASES` in `ingest_nfl_schedule.py`. Same decision as B2.

### B4. Three draft-board tests are red for a fixture gap
`test_nfl_offseason_api` × 3 all fail with `sqlite3.OperationalError: no such table:
nfl_adp` — the fixture DB lacks the table. Not a product bug, but they've been red long
enough that nobody reads them. Fix with R1.

### B7. `players.nfl_gsis_id` mixes two id schemes
**651 active NFL players carry an ESPN-style synthetic key** (`LOV121782`,
`TAT143045`) in a column named for gsis. A real gsis is `00-0041027`. Exactly **0**
of the 651 have game logs — they are the players nflverse has never seen through
our ingests, which is to say the rookies and no-signal players the draft board most
needs to say something about. Jeremiyah Love (ADP 17.5, 98% owned) joined to
nothing until this was found.

The pollution originates **upstream**: nflverse's own depth chart carries the same
synthetic keys for players without a gsis yet (e.g. Drew Allar → `ALL015451`), and
our spine was evidently populated from that feed.

`ingest_nfl_depth_charts.py` works around it by falling back to `espn_id`, which
resolves 914/914 rows. That is a workaround in one script, not a repair — every
other nflverse join still silently misses these players.

**Repair available and measured:** `espn_id` bridges 619 of the 651 to a real gsis
in the 2026 depth chart artifact. 26 more have only a synthetic key upstream too
(genuinely no gsis yet — never played a snap); 6 are absent from the artifact. Name
agreement across the bridge is exact but for 6 generational suffixes (`Murvin Kenion`
vs `Murvin Kenion III`), all the same player. Backfilling mutates the identity
spine, so it wants its own change and its own review rather than riding along with
a board feature.

### B5. `test_league_stats_contract` failing
`test_mlb_never_queries_game_logs_and_always_has_no_comparison`. Pre-existing, uninvestigated.

### B6. The 16-row NFL cleanup is not reproducible
The cleanup of 14 rows in 2024 (`source='nflverse'`) and 2 in 2025 (`source='nflverse_pbp'`)
was a one-off manual SQL operation with no script behind it. Documented in
`NFL-DATA-INVENTORY.md`, not repeatable. Confirm `migrate_nfl_stats_to_prod.py` copies dev
rows wholesale — if so the cleaned rows come along and nothing more is needed. **Check
before the prod deploy, not after.**

---

## Next

### R3. Snapshot betting lines and ADP daily
Two datasets that only become useful as a series:
- `nfl_schedule` has spread/total/moneylines for only **51 of 272** 2026 games (weeks 1–3
  plus 3 games in week 4) — books post the near slate only, and it fills in over time.
- `nfl_adp` is a single snapshot, so actual draft timing is still an assumption.

Snapshot both daily and draft timing becomes measurable in ~2 weeks, before the Labor Day
peak (Sept 5–7). Week 1 opens **2026-09-09**.

### R4. Expose `nfl_schedule` through the API
The table has **zero API exposure** — `/api/nfl/schedule-week[s]` call `espn.nfl_schedule_weeks`
live and never read it. So nothing loaded on 2026-07-27 is visible in the UI. Needed for
week-1 matchup context, rest days, roof/surface, and the weeks 1–3 lines. Depends on the
B2/B3 decision.

### R5. Decide `--all-positions` for IDP and kickers — **needs Micah's call**
`ingest_nfl_weekly_stats.py --all-positions` has never been run. The DB holds only offensive
skill positions in real volume (WR 4,489 / RB 2,804 / TE 2,317 / QB 1,389 / FB 161); the tail
(P 20, OT 15, S 14, CB 6, LB 4, PK 1, K 1) is linemen who caught a touchdown, not IDP
coverage. The 2025 artifact has **~19,400 player-weeks against our 5,635**, so ~13,800
defensive and kicking rows exist upstream. If IDP/K leagues are in scope this ingest run is
a prerequisite, not a UI change.

### R6. Deploy to prod — **after v0.7.0**, per Micah
Prod is on v0.6.7 serving pre-swap NFL numbers, no 2025 postseason, no 2026 schedule.
Needs `migrate_nfl_stats_to_prod.py` plus the `nfl_schedule` table, which does not exist in
prod. Blocked on B6 and R1.

---

## Ops

### O1. Reduce to two servers — **DONE 2026-07-27**
Four were running; we wanted **prod and dev**. Two of the four turned out to be zombies:
`/root/lp-ufc-fight-stats` had been **deleted from disk** while its servers kept running out
of the deleted directory (`readlink /proc/PID/cwd` → `(deleted)`). `:3095` was serving 500.

| port | pid | what | outcome |
|---|---|---|---|
| 8095 | 3916288 | uvicorn, cwd `/root/lp-ufc-fight-stats/backend` **(deleted)** | killed |
| 3095 | 3907514 | next dev, cwd `/root/lp-ufc-fight-stats` **(deleted)**, 500 | killed |
| 8096 | 3878741 | uvicorn, cwd `/root/legendarypicks/backend`, absolute `LP_DB_PATH` | **kept — dev backend** |
| 3096 | 160173  | next dev, cwd `/root/legendarypicks` | **kept — dev frontend** |

`:8000` (`--host 0.0.0.0`) is prod and was never in scope.

**Lesson:** a port table is not evidence of which checkout a server belongs to. Check
`/proc/PID/cwd` for `(deleted)` before treating a listening port as a real environment.

### O2. Tunnel — **NOT A BUG, closed 2026-07-27**
The premise ("points at the wrong frontend") was wrong. `:3096` is the *correct* frontend:
its proxy target comes from `.env.local` (`API_PROXY_TARGET=http://localhost:8096`), not the
process environment, which is why `/proc/PID/environ` showed nothing. `next.config.js` logs
the resolved target at startup — grep the dev log for `[next.config.js] API proxy target:`
instead of inferring it.

`https://someone-decorative-wearing-produce.trycloudflare.com` (pid 3928058, up since 07-23)
returns 200 with real app content and a working `/api/*` proxy. **Deliberately not
refreshed** — restarting would mint a new URL and break a working one. Micah was most likely
holding the dead `cf3095` URL from 07-14.

Note: a fresh trycloudflare URL returns NXDOMAIN *from this box* but is live externally —
verify with a pinned IP, don't restart cloudflared on that signal alone.

### O3. `:8096` CPU — **still open, and no longer moot**
67% CPU is uvicorn's `--reload` supervisor stat()ing 5,861 files 4×/sec, 5,733 of them in
`venv/`. `watchfiles==0.24.0` installed. Restart script written, **never run**. O1 did *not*
make this moot — `:8096` is the survivor, so this is now the dev backend burning the CPU.
`--reload-exclude` must be an **absolute** path; relative patterns silently exclude nothing.
