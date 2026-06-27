#!/usr/bin/env python3
"""derive_player_stats.py — current-season aggregates from player_game_logs → player_stats.

For NBA/NFL/NHL: reads per-game logs, groups by player_id, aggregates stats,
and upserts into player_stats keyed on (player_name, league, season).
NEVER creates new players rows; NEVER matches by name — uses player_id from logs.
"""

import json
import os
import sqlite3
import sys

# ── helpers ────────────────────────────────────────────────

def _normalize_name(name: str) -> str:
    """Normalize player name for matching: lowercase, strip punctuation + suffixes."""
    if not name:
        return ""
    n = name.lower().strip()
    # suffixes
    for sfx in (" jr.", " sr.", " ii", " iii", " iv", " v", " jr", " sr"):
        if n.endswith(sfx):
            n = n[: -len(sfx)]
    # punctuation
    for ch in ".'-":
        n = n.replace(ch, "")
    return " ".join(n.split())  # collapse whitespace


def toi_to_seconds(toi: str) -> int:
    """Convert 'MM:SS' or 'MM' to total seconds."""
    if not toi:
        return 0
    parts = toi.strip().split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    try:
        return int(parts[0]) * 60
    except (ValueError, IndexError):
        return 0


def seconds_to_toi(secs: int) -> str:
    """Convert total seconds back to 'MM:SS'."""
    m = secs // 60
    s = secs % 60
    return f"{m}:{s:02d}"


def ts_pct(pts, fga, fta):
    """True shooting percentage: PTS / (2 * (FGA + 0.44 * FTA)) * 100."""
    denom = 2 * (fga + 0.44 * fta)
    if denom <= 0:
        return 0.0
    return (pts / denom) * 100


# ── aggregation logic ──────────────────────────────────────

def derive_league(db_path: str, league: str):
    """Aggregate player_game_logs for LEAGUE's latest season, upsert into player_stats."""
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

    # Fetch all game logs for this league + season, grouped by player_id
    rows = con.execute(
        """SELECT pgl.player_id, p.name AS player_name, p.position, pgl.team,
                  pgl.stats, pgl.game_date
           FROM player_game_logs pgl
           JOIN players p ON p.id = pgl.player_id
           WHERE pgl.league=? AND pgl.season=?
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
    for player_id, grp in groups.items():
        player_name = grp[0]["player_name"]
        name_norm = _normalize_name(player_name)
        position = grp[0]["position"] or ""
        # Use most recent team
        team = grp[-1]["team"] or ""
        games = len(grp)

        stats = _aggregate(league, grp)
        if stats is None:
            continue

        try:
            if league == "nba":
                _upsert_nba(con, player_id, player_name, name_norm, team, season, games, stats)
            elif league == "nfl":
                _upsert_nfl(con, player_id, player_name, name_norm, team, season, games, stats, position)
            elif league == "nhl":
                _upsert_nhl(con, player_id, player_name, name_norm, team, season, games, stats, position)
            upserted += 1
        except Exception as e:
            print(f"    WARN: {player_name} (id={player_id}): {e}", file=sys.stderr)

    con.commit()
    con.close()
    print(f"  {league}: upserted {upserted} player rows for season {season}")


def _aggregate(league: str, grp):
    """Aggregate per-game stats JSON into a flat dict of computed values."""
    if league == "nba":
        return _aggregate_nba(grp)
    elif league == "nfl":
        return _aggregate_nfl(grp)
    elif league == "nhl":
        return _aggregate_nhl(grp)
    return None


def _aggregate_nba(grp):
    g = len(grp)
    sum_pts = sum_pts_raw = 0
    sum_reb = sum_ast = sum_stl = sum_blk = sum_tov = sum_min = 0
    sum_fgm = sum_fga = sum_fg3m = sum_fg3a = sum_ftm = sum_fta = 0
    for r in grp:
        s = json.loads(r["stats"])
        pts = s.get("PTS", 0)
        sum_pts_raw += pts  # for ts_pct calculation
        sum_pts += pts
        sum_reb += s.get("REB", 0)
        sum_ast += s.get("AST", 0)
        sum_stl += s.get("STL", 0)
        sum_blk += s.get("BLK", 0)
        sum_tov += s.get("TO", 0)
        sum_min += s.get("MIN", 0)
        sum_fgm += s.get("FGM", 0)
        sum_fga += s.get("FGA", 0)
        sum_fg3m += s.get("3PM", 0)
        # NBA game logs don't have 3PA, field-goal attempts include 3PA
        # we don't have a separate 3PA so we set it to 0
        sum_fg3a += 0
        sum_ftm += s.get("FTM", 0)
        sum_fta += s.get("FTA", 0)

    return {
        "pts": round(sum_pts / g, 1),
        "reb": round(sum_reb / g, 1),
        "ast": round(sum_ast / g, 1),
        "stl": round(sum_stl / g, 1),
        "blk": round(sum_blk / g, 1),
        "tov": round(sum_tov / g, 1),
        "minutes": round(sum_min / g, 1),
        "fgm": sum_fgm,
        "fga": sum_fga,
        "fg3m": sum_fg3m,
        "fg3a": sum_fg3a,
        "ftm": sum_ftm,
        "fta": sum_fta,
        "ts_pct": round(ts_pct(sum_pts_raw, sum_fga, sum_fta), 1),
    }


def _aggregate_nfl(grp):
    g = len(grp)
    sum_pass_yds = sum_pass_td = sum_int = sum_cmp = sum_att = 0
    sum_pass_epa = 0.0
    sum_carries = sum_rush_yds = sum_rush_td = 0
    sum_rec = sum_rec_yds = sum_rec_td = sum_targets = 0
    sum_fant = sum_fant_ppr = 0.0
    for r in grp:
        s = json.loads(r["stats"])
        # 2025 format uses short keys: pass_yds, pass_td, intc, cmp, etc.
        # 2024 format uses long keys: passing_yards, passing_tds, interceptions, etc.
        sum_pass_yds += s.get("pass_yds", s.get("passing_yards", 0))
        sum_pass_td += s.get("pass_td", s.get("passing_tds", 0))
        sum_int += s.get("intc", s.get("interceptions", 0))
        sum_cmp += s.get("cmp", s.get("completions", 0))
        sum_att += s.get("att", s.get("attempts", 0))
        sum_pass_epa += float(s.get("pass_epa", s.get("passing_epa", 0)) or 0)
        sum_carries += s.get("carries", 0)
        sum_rush_yds += s.get("rush_yds", s.get("rushing_yards", 0))
        sum_rush_td += s.get("rush_td", s.get("rushing_tds", 0))
        sum_rec += s.get("rec", s.get("receptions", 0))
        sum_rec_yds += s.get("rec_yds", s.get("receiving_yards", 0))
        sum_rec_td += s.get("rec_td", s.get("receiving_tds", 0))
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


def _aggregate_nhl(grp):
    g = len(grp)
    sum_goals = sum_assists = sum_points = sum_shots = 0
    sum_pm = sum_pim = sum_ppg = sum_ppp = sum_shg = 0
    toi_secs = []

    for r in grp:
        s = json.loads(r["stats"])
        sum_goals += s.get("goals", 0)
        sum_assists += s.get("assists", 0)
        sum_points += s.get("points", 0)
        sum_shots += s.get("shots", 0)
        sum_pm += s.get("plusMinus", 0)
        sum_pim += s.get("pim", 0)
        sum_ppg += s.get("powerPlayGoals", 0)
        sum_ppp += s.get("powerPlayPoints", 0)
        sum_shg += s.get("shorthandedPoints", 0)
        toi = s.get("toi", "")
        if toi:
            toi_secs.append(toi_to_seconds(toi))

    avg_toi_secs = round(sum(toi_secs) / len(toi_secs)) if toi_secs else 0
    shooting_pct = round((sum_goals / sum_shots) * 100, 1) if sum_shots > 0 else 0.0

    return {
        "goals": sum_goals,
        "assists": sum_assists,
        "points_nhl": sum_points,
        "shots": sum_shots,
        "shooting_pct": shooting_pct,
        "plus_minus": sum_pm,
        "pim": sum_pim,
        "ppg": sum_ppg,
        "ppp": sum_ppp,
        "shg": sum_shg,
        "toi": seconds_to_toi(avg_toi_secs),
        "faceoff_pct": None,  # not in game logs
    }


# ── upsert helpers ─────────────────────────────────────────

def _upsert_nba(con, player_id, name, name_norm, team, season, games, s):
    con.execute(
        """INSERT OR REPLACE INTO player_stats
           (player_name, name_norm, league, team, season, games,
            pts, reb, ast, stl, blk, tov,
            fgm, fga, fg3m, fg3a, ftm, fta, minutes,
            ts_pct, source, player_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (name, name_norm, "nba", team, season, games,
         s["pts"], s["reb"], s["ast"], s["stl"], s["blk"], s["tov"],
         s["fgm"], s["fga"], s["fg3m"], s["fg3a"], s["ftm"], s["fta"], s["minutes"],
         s["ts_pct"], "derived", player_id),
    )


def _upsert_nfl(con, player_id, name, name_norm, team, season, games, s, position):
    con.execute(
        """INSERT OR REPLACE INTO player_stats
           (player_name, name_norm, league, team, season, games,
            nfl_position, nfl_team,
            pass_yds_g, pass_td, interceptions, cmp_g, pass_epa,
            carries_g, rush_yds_g, receptions, rec_yds_g, targets,
            fantasy_pts_g, fantasy_ppr_g,
            source, player_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (name, name_norm, "nfl", team, season, games,
         position, team,
         s["pass_yds_g"], s["pass_td"], s["interceptions"], s["cmp_g"], s["pass_epa"],
         s["carries_g"], s["rush_yds_g"], s["receptions"], s["rec_yds_g"], s["targets"],
         s["fantasy_pts_g"], s["fantasy_ppr_g"],
         "derived", player_id),
    )


def _upsert_nhl(con, player_id, name, name_norm, team, season, games, s, position):
    con.execute(
        """INSERT OR REPLACE INTO player_stats
           (player_name, name_norm, league, team, season, games,
            nhl_position, nhl_team,
            goals, assists, points_nhl, shots, shooting_pct,
            plus_minus, pim, ppg, ppp, shg, toi, faceoff_pct,
            source, player_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (name, name_norm, "nhl", team, season, games,
         position, team,
         s["goals"], s["assists"], s["points_nhl"], s["shots"], s["shooting_pct"],
         s["plus_minus"], s["pim"], s["ppg"], s["ppp"], s["shg"], s["toi"], s["faceoff_pct"],
         "derived", player_id),
    )


# ── main ───────────────────────────────────────────────────

def main():
    db_path = os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "picks.dev.db"
    )
    print(f"DB: {db_path}")
    for league in ("nba", "nfl", "nhl"):
        derive_league(db_path, league)
    print("Done.")


if __name__ == "__main__":
    main()
