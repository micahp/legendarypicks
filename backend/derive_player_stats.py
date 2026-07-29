#!/usr/bin/env python3
"""Publish the NFL season compatibility row from durable weekly logs.

NFL's source is the published nflverse weekly artifact stored in
``player_game_logs``. NBA and NHL both publish season totals directly and have
dedicated ingesters.
NEVER creates new players rows; NEVER matches by name — uses player_id from logs.
"""

import json
import os
import sqlite3
import sys

from league_stats import (
    LeagueStatContractError,
    publish_player_stats,
    supports_derived_stats,
)

# ── aggregation logic ──────────────────────────────────────

def derive_league(db_path: str, league: str):
    """Publish NFL's latest regular-season rollup in one transaction."""
    league = str(league or "").lower()
    if not supports_derived_stats(league):
        raise LeagueStatContractError(
            f"{league or 'blank'} season stats are publisher-owned; "
            "the compatibility rollup supports only nfl"
        )
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    # Find latest season in logs for this league
    latest = con.execute(
        "SELECT season FROM player_game_logs WHERE league=? GROUP BY season ORDER BY season DESC LIMIT 1",
        (league,),
    ).fetchone()
    if not latest:
        print(f"  {league}: no game logs found, skipping.")
        con.close()
        return
    season = latest["season"]
    print(f"  {league}: latest season = {season}")

    log_columns = {
        str(row[1])
        for row in con.execute("PRAGMA table_info(player_game_logs)")
    }
    population_clause = ""
    if "game_type" in log_columns:
        if "game_no" in log_columns:
            population_clause = (
                " AND (pgl.game_type='REG' OR "
                "(pgl.game_type IS NULL AND pgl.game_no<19))"
            )
        else:
            population_clause = " AND pgl.game_type='REG'"

    # Fetch all regular-season logs, grouped by canonical player identity.
    rows = con.execute(
        f"""SELECT pgl.player_id, p.name AS player_name, p.position, pgl.team,
                  pgl.stats, pgl.game_date
           FROM player_game_logs pgl
           JOIN players p ON p.id = pgl.player_id
           WHERE pgl.league=? AND pgl.season=?
           {population_clause}
           ORDER BY pgl.player_id, pgl.game_date""",
        (league, season),
    ).fetchall()

    if not rows:
        print(f"  {league}: no rows returned, skipping.")
        con.close()
        return

    # Group by player_id
    from collections import defaultdict
    groups = defaultdict(list)
    for r in rows:
        groups[r["player_id"]].append(r)

    upserted = 0
    try:
        con.execute("BEGIN IMMEDIATE")
        for player_id, grp in groups.items():
            position = grp[0]["position"] or ""
            # Use most recent team
            team = grp[-1]["team"] or ""
            games = len(grp)
            stats = _aggregate_nfl(grp)
            _upsert_nfl(
                con, player_id, team, season, games, stats, position
            )
            upserted += 1
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    print(f"  {league}: upserted {upserted} player rows for season {season}")


def _aggregate_nfl(grp):
    g = len(grp)
    sum_pass_yds = sum_pass_td = sum_int = sum_cmp = 0
    sum_pass_epa = 0.0
    sum_carries = sum_rush_yds = 0
    sum_rec = sum_rec_yds = sum_targets = 0
    sum_fant = sum_fant_ppr = 0.0
    for r in grp:
        s = json.loads(r["stats"])
        # 2025 format uses short keys: pass_yds, pass_td, intc, cmp, etc.
        # 2024 format uses long keys: passing_yards, passing_tds, interceptions, etc.
        sum_pass_yds += s.get("pass_yds", s.get("passing_yards", 0))
        sum_pass_td += s.get("pass_td", s.get("passing_tds", 0))
        sum_int += s.get("intc", s.get("interceptions", 0))
        sum_cmp += s.get("cmp", s.get("completions", 0))
        sum_pass_epa += float(s.get("pass_epa", s.get("passing_epa", 0)) or 0)
        sum_carries += s.get("carries", 0)
        sum_rush_yds += s.get("rush_yds", s.get("rushing_yards", 0))
        sum_rec += s.get("rec", s.get("receptions", 0))
        sum_rec_yds += s.get("rec_yds", s.get("receiving_yards", 0))
        sum_targets += s.get("targets", 0)
        sum_fant += float(s.get("fpts", s.get("fantasy_points", 0)) or 0)
        sum_fant_ppr += float(s.get("fpts_ppr", s.get("fantasy_points_ppr", 0)) or 0)

    return {
        "pass_yds_g": round(sum_pass_yds / g, 1),
        "pass_td": sum_pass_td,
        "interceptions": sum_int,
        "cmp_g": round(sum_cmp / g, 1),
        "pass_epa": round(sum_pass_epa, 1),
        "carries_g": round(sum_carries / g, 1),
        "rush_yds_g": round(sum_rush_yds / g, 1),
        "receptions": sum_rec,
        "rec_yds_g": round(sum_rec_yds / g, 1),
        "targets": sum_targets,
        "fantasy_pts_g": round(sum_fant / g, 1),
        "fantasy_ppr_g": round(sum_fant_ppr / g, 1),
    }


# ── upsert helpers ─────────────────────────────────────────

def _upsert_nfl(con, player_id, team, season, games, s, position):
    publish_player_stats(
        con,
        player_id=player_id,
        league="nfl",
        season=season,
        stat_type="season",
        source="nflverse_weekly_rollup",
        games=games,
        values={
            "nfl_position": position, "nfl_team": team,
            "pass_yds_g": s["pass_yds_g"], "pass_td": s["pass_td"],
            "interceptions": s["interceptions"], "cmp_g": s["cmp_g"],
            "pass_epa": s["pass_epa"], "carries_g": s["carries_g"],
            "rush_yds_g": s["rush_yds_g"], "receptions": s["receptions"],
            "rec_yds_g": s["rec_yds_g"], "targets": s["targets"],
            "fantasy_pts_g": s["fantasy_pts_g"],
            "fantasy_ppr_g": s["fantasy_ppr_g"],
        },
    )


# ── main ───────────────────────────────────────────────────

def main():
    db_path = os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "picks.dev.db"
    )
    print(f"DB: {db_path}")
    requested = [
        value.lower()
        for value in sys.argv[1:]
        if value.lower() == "nfl"
    ]
    for league in requested or ("nfl",):
        derive_league(db_path, league)
    print("Done.")


if __name__ == "__main__":
    main()
