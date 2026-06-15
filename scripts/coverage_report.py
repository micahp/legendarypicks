#!/usr/bin/env python3
"""
coverage_report.py — identity spine + stats coverage SLO check.

Measures:
  1. Spine coverage: % of players per league with source IDs populated
  2. Stats coverage: % of spine players that have player_stats rows (by player_id)
  3. Resolution rate: % of player_stats rows that have player_id populated
  4. Per-team breakdown for each league

Gate: roster-based coverage ≥95% per league.
Verification players: Bobby Witt Jr, Shohei Ohtani (batting+pitching), a non-star NHL player.
"""
import sqlite3, os, sys

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend", "data", "picks.db")

def _pct(numerator, denominator):
    if denominator == 0:
        return 0.0
    return round(numerator / denominator * 100, 1)

def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    print("=" * 72)
    print("  LEGENDARY PICKS — Identity Spine Coverage Report")
    print("=" * 72)

    league_totals = {}

    for league in ("mlb", "nfl", "nba", "nhl"):
        print(f"\n── {league.upper()} ──")

        # Total players in spine
        total_spine = con.execute(
            "SELECT COUNT(*) FROM players WHERE league=?", (league,)
        ).fetchone()[0]

        # Players with source IDs populated
        if league == "mlb":
            id_col = "mlbam_id"
        elif league == "nfl":
            id_col = "nfl_gsis_id"
        elif league == "nba":
            id_col = "nba_id"
        elif league == "nhl":
            id_col = "nhl_id"

        with_source_id = con.execute(
            f"SELECT COUNT(*) FROM players WHERE league=? AND {id_col} IS NOT NULL AND {id_col} != 0 AND {id_col} != ''",
            (league,)
        ).fetchone()[0]

        # Players with stats (joined by player_id)
        with_stats = con.execute("""
            SELECT COUNT(DISTINCT p.id)
            FROM players p
            JOIN player_stats ps ON ps.player_id = p.id
            WHERE p.league=?
        """, (league,)).fetchone()[0]

        # Stats rows resolution rate
        total_stats_rows = con.execute(
            "SELECT COUNT(*) FROM player_stats WHERE league=?", (league,)
        ).fetchone()[0]
        resolved_stats_rows = con.execute(
            "SELECT COUNT(*) FROM player_stats WHERE league=? AND player_id IS NOT NULL AND player_id > 0",
            (league,)
        ).fetchone()[0]

        print(f"  Spine players:           {total_spine:>6}")
        print(f"  With source ID:          {with_source_id:>6}  ({_pct(with_source_id, total_spine)}%)")
        print(f"  With stats (by player_id): {with_stats:>6}  ({_pct(with_stats, total_spine)}%)")
        print(f"  Stats rows total:        {total_stats_rows:>6}")
        print(f"  Stats rows resolved:     {resolved_stats_rows:>6}  ({_pct(resolved_stats_rows, total_stats_rows)}%)")

        # Per-team breakdown
        teams = con.execute(
            "SELECT team, COUNT(*) as cnt FROM players WHERE league=? AND team IS NOT NULL AND team != '' GROUP BY team ORDER BY cnt DESC",
            (league,)
        ).fetchall()

        if teams:
            print(f"\n  Per-team (top 10 + bottom 5):")
            for i, t in enumerate(teams):
                team_name = t["team"]
                team_total = t["cnt"]
                team_with_stats = con.execute("""
                    SELECT COUNT(DISTINCT p.id)
                    FROM players p
                    JOIN player_stats ps ON ps.player_id = p.id
                    WHERE p.league=? AND p.team=?
                """, (league, team_name)).fetchone()[0]
                pct = _pct(team_with_stats, team_total)
                flag = "✅" if pct >= 95 else ("⚠️" if pct >= 50 else "❌")
                if i < 10 or i >= len(teams) - 5:
                    print(f"    {flag} {team_name:>5}: {team_with_stats:>4}/{team_total:<4} ({pct}%)")
                elif i == 10:
                    print(f"    ... ({len(teams) - 15} more teams) ...")
        else:
            print(f"  (no team data in spine)")

        league_totals[league] = {
            "spine": total_spine,
            "with_source_id": with_source_id,
            "with_stats": with_stats,
            "total_stats": total_stats_rows,
            "resolved_stats": resolved_stats_rows,
            "stats_pct": _pct(with_stats, total_spine),
            "resolution_pct": _pct(resolved_stats_rows, total_stats_rows),
        }

    # ── Summary ──
    print(f"\n{'=' * 72}")
    print(f"  LEAGUE SUMMARY")
    print(f"  Gate: ≥95% of stats rows have player_id linked")
    print(f"  {'League':<6} {'Spine':>7} {'StatsRows':>9} {'Resolved':>9} {'Res%':>6}  Gate")
    print(f"  {'-'*6} {'-'*7} {'-'*9} {'-'*9} {'-'*6}  {'-'*6}")
    all_pass = True
    for lg in ("mlb", "nfl", "nba", "nhl"):
        t = league_totals[lg]
        gate = "✅ PASS" if t["resolution_pct"] >= 95 else "❌ FAIL"
        if t["resolution_pct"] < 95:
            all_pass = False
        print(f"  {lg.upper():<6} {t['spine']:>7} {t['total_stats']:>9} {t['resolved_stats']:>9} {t['resolution_pct']:>5}%  {gate}")

    # ── Verification players ──
    print(f"\n{'=' * 72}")
    print(f"  VERIFICATION PLAYERS")
    print(f"  (Must resolve via player_id — name joins are the leak)")

    verifications = [
        ("Bobby Witt Jr.", "mlb"),
        ("Shohei Ohtani", "mlb"),
        ("Shohei Ohtani", "mlb"),
    ]

    # Non-star NHL player: pick one with stats
    nhl_sample = con.execute("""
        SELECT p.name, p.id FROM players p
        JOIN player_stats ps ON ps.player_id = p.id
        WHERE p.league='nhl'
        ORDER BY ps.points_nhl LIMIT 1
    """).fetchone()
    if nhl_sample:
        verifications.append((nhl_sample["name"], "nhl"))

    for vname, vleague in verifications:
        # Check spine presence
        spine = con.execute(
            "SELECT id, name, mlbam_id, nfl_gsis_id, nhl_id, nba_id FROM players WHERE league=? AND name=?",
            (vleague, vname)
        ).fetchone()
        if not spine:
            print(f"  ❌ {vname} ({vleague}): NOT IN SPINE")
            continue

        # Check stats via player_id
        stats = con.execute("""
            SELECT ps.player_name, ps.stat_type, ps.season,
                   ps.pts, ps.reb, ps.ast, ps.avg, ps.hr, ps.goals, ps.assists as nhl_assists
            FROM player_stats ps
            WHERE ps.player_id = ?
            ORDER BY ps.season DESC
        """, (spine["id"],)).fetchall()

        if stats:
            for s in stats:
                if vleague == "mlb":
                    detail = f"AVG={s['avg']}, HR={s['hr']}" if s['stat_type'] == 'batting' else f"K%={s['pts']}"
                elif vleague == "nhl":
                    detail = f"G={s['goals']}, A={s['nhl_assists']}"
                else:
                    detail = f"PTS={s['pts']}, REB={s['reb']}, AST={s['ast']}"
                print(f"  ✅ {vname} ({vleague}/{s['stat_type']}): player_id={spine['id']}  {detail}  [{s['season']}]")
        else:
            print(f"  ⚠️  {vname} ({vleague}): IN SPINE (id={spine['id']}) but no stats yet — ready for next ingest")

    # ── unresolved_players summary ──
    unresolved_total = con.execute("SELECT COUNT(*) FROM unresolved_players").fetchone()[0]
    print(f"\n{'=' * 72}")
    print(f"  REVIEW QUEUE: unresolved_players = {unresolved_total}")
    if unresolved_total > 0:
        by_league = con.execute(
            "SELECT league, COUNT(*) as cnt FROM unresolved_players GROUP BY league ORDER BY cnt DESC"
        ).fetchall()
        for r in by_league:
            print(f"    {r['league']}: {r['cnt']}")
        # Show a few samples
        samples = con.execute(
            "SELECT raw_name, league, team, count FROM unresolved_players ORDER BY count DESC LIMIT 5"
        ).fetchall()
        print(f"  Top unresolved:")
        for s in samples:
            print(f"    {s['raw_name']} ({s['league']}, {s['team']}) — {s['count']}x")

    con.close()

    print(f"\n{'=' * 72}")
    if all_pass:
        print("  RESULT: ALL LEAGUES PASS ≥95% coverage gate ✅")
    else:
        print("  RESULT: SOME LEAGUES BELOW 95% — see ❌ lines above")
    print(f"{'=' * 72}")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
