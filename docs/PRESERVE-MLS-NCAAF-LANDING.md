# PRESERVED — MLS/NCAAF landing artifacts (2026-08-08)

Status: **NOT SHIPPED.** EWC landed to dev (2d706f4) and prod (v0.7.10/e55ee17)
2026-08-08. MLS/NCAAF was explicitly EXCLUDED from that promotion. This branch
(`feat/league-mls-ncaaf`, HEAD 2d6ab86) carries the complete feature for a
later dedicated landing. Do not treat any of this as shipped.

## What lives on this branch (committed at 2d6ab86)

Backend (all ncaaf-wired, verified in the original worktree):
- backend/espn_leagues.py (new registry: ncaaf path + scope_group 80)
- backend/ingest_cfbd_logs.py (log source, 56,577 rows, 888/888 games)
- backend/reconcile_core.py / reconcile_gap.py / reconcile_report.py /
  reconcile_coverage.py / reconcile_checks.py + slim reconcile_totals.py
  (the 6-file reconcile suite; host budget 100, 403 fails fast)
- backend/espn_client.py (ncaaf LEAGUES entry; **+ ncaaf_conference_standings()
  + _parse_record 2026-08-09** — CFB conference-grouped standings builder;
  router games.py now serves {group, rows} for ncaaf and mls)
- backend/team_codes.py (ncaaf NON_FRANCHISE all-star/combine subtraction)
- backend/team_stats_contract.py (ncaaf EXPECTED_TEAMS=137, STAT_FIELDS,
  ESPN_TO_COLUMN, aggregate branch)
- backend/team_stats_schema.py (result W/D/L column)
- backend/backfill_team_parity.py (ncaaf LEAGUE_CFG + GROUP_SCOPED 80 +
  enumerate_games_group)
- backend/audit_league_stats.py / audit_field_utilization.py (ncaaf MANIFEST)
- backend/season_keys.py (ncaaf start-year keying docs)
- verify-gates.sh (COV-ncaaf gate)

Frontend (committed): presentation.ts, StandingsTab.tsx (Conference/Soccer),
PlayerGameLog.tsx (league-aware), useStandingsData.ts, PredictTab.tsx
(draw gating), PlayerGameLog.test.tsx.

## UNCOMMITTED on this branch — dev-tree-only additions re-applied 2026-08-08

These existed ONLY in the dev working tree during the aborted landing and were
reverted by the dev branch switch; re-applied here so they are not lost:

- pages/leagues.tsx          — MLS + NCAAF hub cards (MLS card added too; branch
                               predates the dev merges that had it)
- pages/scores.tsx           — NCAAF in LEAGUE_PRIORITY, LEAGUES filter,
                               All-view fetch array (+MLS entries, branch predates)
- components/Player/LeagueGameLog.tsx — ncaaf stat columns (C/ATT, YDS, TD, INT,
                               RUSH, REC, tackles/sacks/TFL/PD/INT line)
- components/Leagues/hooks/useLeagueRouteState.ts — ncaaf tab set = standings +
                               schedule ONLY (Stats hidden: no ncaaf leaders
                               backend — dead-surface rule)

## DB-only (not in git) — for the landing's DB copy step

Dev DB `/root/legendarypicks/backend/data/picks.dev.db` currently holds the
ncaaf rows copied during the aborted landing (verified still present):
- players 20,926 (incl. 183 id-collision rows re-inserted with fresh ids and
  their 605 log rows re-mapped — 0 orphans, 0 wrong-league links)
- player_game_logs 56,577
- team_game_results 1,776, team_game_stats 1,776
- team_stats_coverage ncaaf/2025/complete
Backup: /root/lp-db-backups/picks.dev.before-ncaaf-land-20260808-181212.db

## Landing checklist for the later dedicated landing (from the landing playbook)

> **audit_league_stats.py hazard (2026-08-10):** the copy on THIS branch is the
> OLD presence-based version. Main dev's copy has the coverage-floor machinery
> (dict-form position_content + per-key `key_coverage`), which was extended
> 2026-08-10 so ncaaf DB/CB/S declare `def_int: 0.05` (CFBD omits the
> interceptions category when no INT was recorded — honest zero, not data
> loss; see LEAGUE-STAT-GAPS.md). At landing, copy the ncaaf MANIFEST hunk
> (and the check_position_content key_coverage support) INTO main's newer
> file — do NOT copy this branch's audit file wholesale or it regresses the
> coverage-floor machinery for every league.

1. Copy backend hunks to dev (espn_client LEAGUES entry, espn_leagues.py,
   ingest_cfbd_logs.py, ALL SIX reconcile files, backfill/contract/team_codes/
   season_keys/audit diffs, verify-gates.sh COV-ncaaf).
2. Copy frontend files (presentation.ts, StandingsTab, PlayerGameLog + test,
   PredictTab, useStandingsData, useLeagueRouteState) + the 4 uncommitted
   files above.
3. Copy DB rows (players/logs/results/stats/coverage) with the id-collision
   remap (see earlier session; the 183-id remap matters).
4. Coverage row flips /leagues/ncaaf live (coverage-driven).
5. Browser-verify /leagues/ncaaf (standings, schedule, player game log,
   empty states), then run verify-gates COV-ncaaf on dev.
