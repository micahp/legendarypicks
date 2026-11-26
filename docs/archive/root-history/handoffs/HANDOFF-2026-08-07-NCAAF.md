# HANDOFF — NCAAF FBS push (2026-08-07, session 3)

Covers today's NCAAF work in the worktree `/root/lp-league-mls-ncaaf` (branch
`feat/league-mls-ncaaf`). MLS finish + team-stats fix is in
`HANDOFF-2026-08-07.md` (same day, same tree). Nothing landed to main yet.

## Where things stand

**NCAAF went from spine-only (~10%) to a built, verified data pipeline in the
worktree.** The league is NOT clickable anywhere yet — no main-tree code, no DB
rows on main dev, and two open decisions block the coverage verdict. Grade:
data pipeline DONE in worktree, landing NOT done.

## 1. Two real bugs fixed in ingest_ncaaf_logs.py

- **Pagination: `?offset=` → `?limit=100&page=N` + `pageCount`.** sports.core
  ignores `offset` and re-serves page 1, so the first run enumerated only 100 of
  888 events and "completed" in 2 minutes. The soccer ingest (`_type_events`)
  already used page pagination — copied that pattern, verified 888/888 ids.
- **Core fetches routed through the shared fetcher.** `_core_get` used raw
  urllib (no pacing, no per-host budget, no disk cache) → tripped ESPN's 403
  wall. Now goes through `espn._get` (budget + cooldown + disk cache) and the
  ingest opts into the batch retry ladder (`set_retry_waits`).

## 2. Log ingest COMPLETED (888/888)

```
season 2025 (2025): type 2 'Regular Season' published 2025-08-23 .. 2025-12-13
group 80: 888 published Regular Season events
Done. 19055 NCAAF FBS logs from 888 completed games
  (11993 resolved rows, 7062 unresolved rows).
  0 events skipped, 0 summaries failed, 0 phase mismatches.
```

- Ran with `LP_ESPN_CACHE_DIR` + `LP_INGEST_MIN_INTERVAL=0.5`; took ~30 min
  through the 100/host budget + 60s cooldowns.
- **7,062 unresolved rows (63% resolved)** — next session's MLS-style resolution
  pass: the worktree cache (333 MB, now ~1,500 files) holds every summary with
  roster names, so this should be zero-ESPN-request like MLS was.
- One game quirk found: **Army-Navy (401762521)** — its boxscore.players has
  EMPTY passing/rushing/receiving groups (offense only in the `leaders` block),
  so 0 log rows were written for it. player_game_logs = 887 distinct game_ids vs
  888 published. DECISION NEEDED: accept 887, or backfill that game from the
  leaders block (partial data).

## 3. Backfill wired + ran (888 games, 0 failures)

- `backfill_team_parity.py`: added `ncaaf` LEAGUE_CFG (football/college-football,
  2025, type 2), `GROUP_SCOPED = {"ncaaf": "80"}`, and `enumerate_games_group()`
  — group-scoped event enumeration instead of per-team schedules (per-team would
  walk all 807 league-wide teams incl. FCS and pollute the FBS table). Fixed a
  signature bug (our key "ncaaf" vs site path "college-football" conflated).
- Result: **888 games, 1,776 team_game_results + 1,776 team_game_stats rows, 0
  failures.** season 2025-08-23 .. 2025-12-13. Provenance stamped
  `espn_site_web_api:scoreboard+summary`.
- **230 distinct teams = 137 FBS + 93 FCS buy-game opponents** (e.g. Alabama vs
  Mercer) — legitimately part of the group-80 schedule. The 146-id publisher
  team list carries nine all-star/combine sides (Team Gaither/Team Robinson,
  East/West/North All-Stars, South/North Florida Stars, American, National)
  that never play a regular-season game. DECIDED 2026-08-07: scope FBS-facing
  surfaces (COV gate, aggregates, reconcile team count) to the 137 canonical
  FBS teams via team_codes NON_FRANCHISE + is_canonical; keep all 230 rows.

## 4. team_stats_contract.py fully wired for ncaaf (tests 31/31)

- `EXPECTED_TEAMS["ncaaf"] = 137` (played FBS: the 146-id publisher list carries
  nine all-star/combine sides that never play — scoped via team_codes NON_FRANCHISE)
- `STAT_FIELDS["ncaaf"]` = first_downs, total_yards, net_passing_yards,
  rushing_yards, turnovers — measured from a REAL cached summary (WIS-ALA 2025).
  NFL-only columns college does not publish (total_offensive_plays,
  defensive_special_teams_tds) deliberately NOT mapped.
- `ESPN_TO_COLUMN["ncaaf"]` — firstDowns/totalYards/netPassingYards/rushingYards/
  turnovers, measured from cache.
- `LEAGUE_CATEGORIES["ncaaf"]` — Record, Offense (PTS/G, YDS/G, Pass/Rush YDS/G,
  1st Downs/G), Defense (Opp PTS/G, Opp YDS/G, Turnovers).
- `_aggregate_rows` ncaaf branch + opponent-stats accumulation (yards_allowed
  etc. like NFL — never emit 0 for unavailable).
- `pytest test_team_stats_contract.py test_backfill_team_stats_fixture.py` →
  31 passed.

## 5. NEW-LEAGUE-CHECKLIST items done

- MANIFEST entry for ncaaf confirmed pre-existing in `audit_league_stats.py`
  (offense-only scope declared, QB/RB/WR/TE position_content, qualifier NONE
  PUBLISHED). ENDPOINTS in `audit_field_utilization.py` confirmed.
- `docs/DATA-SPINE.md` — added MLS (1,236) + NCAAF (15,029) rows and a written
  single-publisher (ESPN) status incl. what ESPN does NOT print. NOTE: its
  2026-08-07 CORRECTION records that the CFBD "do not use" ruling was
  news-engine-only, so NCAAF log sourcing is an open decision for landing.
- `docs/LEAGUE-STAT-GAPS.md` — new §4 with MLS + NCAAF gap tables.
- `verify-gates.sh` — COV-ncaaf gate added (888 logs / 888 results / 146 teams /
  0 NULL game_type), expectations written BEFORE the data existed.

## 6. Open items / next session (ordered)

1. ~~**FBS team-scoping**~~ **DECIDED 2026-08-07**: 137 canonical FBS teams (see
   §3) — team_codes NON_FRANCHISE + is_canonical scoping in the worktree;
   EXPECTED_TEAMS=137; COV-ncaaf gate, aggregates, and reconcile team counts all
   updated. All 230 rows kept.
2. ~~**Army-Navy**~~ **RESOLVED by the CFBD re-source (2026-08-07)** — ESPN's
   summaries publish EMPTY player groups for 401762521 (leaders block is
   yards-only), but CFBD publishes the game (42 rows). The accept-887 exception
   is removed; COV-ncaaf expects 888 logs again.
3. Re-run `reconcile_totals.py --league ncaaf --season 2025 --write-coverage`
   after a 403-wall reset (last run: PASS 888 games in team_game_results,
   MISMATCH 887 logs, per-team counts NO-ORACLE 403). **Per-team oracle changed
   2026-08-07**: the live per-team events loop (~137 requests, tripped the
   ~100/host wall) is now an internal cross-table check (logs per team vs
   team_game_results per team, minus PLAYER_LOG_GAP_GAMES) — zero live
   requests; the "every playing FBS team appears in logs" whitelist check stays
   live against the publisher (2 requests total).
4. ~~**NCAAF log source**~~ **DONE 2026-08-07 — CFBD is the log source.**
   `ingest_cfbd_logs.py` re-sourced the 2025 FBS season: 888/888 games, 56,577
   rows, 100% linked (CFBD athlete ids ARE spine espn_ids; self-heal adds any
   missing player), defensive stats mapped (tackles/sacks/INTs into the stats
   JSON), FCS buy-game players kept (230 teams), ~139 CFBD calls total. ESPN
   summaries retired for logs (kept for team backfill/reconcile).
5. ~~**Resolve 7,062 unresolved log rows**~~ **UNNECESSARY** — the CFBD re-source
   is 100% resolved (0 NULL player_id); the old ESPN rows were deleted by the
   re-source.
6. **Land to main dev** (the MLS pattern): copy espn_client LEAGUES entry +
   suspended-fix, espn_leagues.py, ingest_cfbd_logs.py (the log source; the
   retired ingest_ncaaf_logs.py can stay as reference or be dropped),
   backfill/contract/reconcile diffs, team_codes (JSON doc already in main),
   frontend files (presentation.ts, useLeagueRouteState.ts, StandingsTab.tsx,
   PlayerGameLog.tsx, [league].tsx), then DB rows
   (players/logs/results/stats/coverage). Main currently has ZERO ncaaf rows
   and no ncaaf code.
   **NOTE 2026-08-08: reconcile_totals.py was split into a package of siblings**
   (reconcile_core.py / reconcile_gap.py / reconcile_report.py /
   reconcile_coverage.py / reconcile_checks.py + slim entry). Landing must copy
   ALL six files, not just reconcile_totals.py. CLI contract unchanged
   (`reconcile_totals.py --league ...`). test_coverage_gate.py now imports
   reconcile_gap for monkeypatch targets.
7. Browser-verify /leagues/ncaaf at 375/1440, run verify-gates COV-statset,
   update task docs + this handoff's landing section.

## Lessons

- sports.core.api paginates by `page`/`pageCount`, NOT `offset` — offset silently
  re-serves page 1 and looks like success.
- Raw urllib in an ingest = 403 wall with no recovery; always route through the
  shared paced_http fetcher (budget + cooldown + disk cache).
- FBS-vs-FCS buy games put FCS opponents in the group-80 schedule — team counts
  will exceed the FBS whitelist; scope explicitly, don't discover it at the gate.
- ESPN boxscore.players can have EMPTY stat groups for a single game (Army-Navy)
  while the same data lives in `leaders` — check the exception before assuming
  the ingest is broken.
- Subagent/process timeouts ≠ failure: check the live transcript/DB before
  redoing work (the first "100/888 Done" was a pagination bug, not a timeout).
