"""Per-league player stat fetchers for the props surface.

Lifted out of `_core.py` unchanged. Self-contained: these call the publishers
and shape their answers, and import nothing from `_core`.

One function per league because the leagues genuinely differ — an NFL block is
chosen by position, MLB carries a Statcast id, NHL splits skater from goalie.
Collapsing them into one parameterised fetcher would mean a per-league branch
in a shared body, which is the shape that made this file 1,649 lines.
"""
import os
import re
import unicodedata


def _normalize_name(name: str) -> str:
    """Normalize player name for matching: lowercase, strip punctuation + suffixes + accents."""
    if not name:
        return ""
    n = name.lower().strip()
    # Strip suffixes
    n = re.sub(r'\b(jr\.?|sr\.?|ii|iii|iv|v)\b', '', n)
    # Strip punctuation
    n = re.sub(r'[^\w\s]', '', n)
    # Strip accents
    n = unicodedata.normalize('NFKD', n).encode('ascii', 'ignore').decode('ascii')
    # Collapse whitespace
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def _get_mlb_stats(player_name: str, player_id: int, statcast_id, now: float):
    """Pull canonical MLB stats published by ``ingest_statcast.py``."""
    import os, sqlite3 as sq

    try:
        db_path = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
        con = sq.connect(db_path)
        con.row_factory = sq.Row

        bat = canonical_player_stats_row(
            con, player_id=player_id, league="mlb", stat_type="batting"
        )
        pit = canonical_player_stats_row(
            con, player_id=player_id, league="mlb", stat_type="pitching"
        )

        if not bat and not pit:
            con.close()
            return {"stats": None, "message": f"No Statcast data for {player_name}. Run ingest_statcast.py to populate."}

        out = {"window": str(bat["season"]) if bat else (str(pit["season"]) if pit else "?"), "batting": None, "pitching": None}

        if bat and bat["avg"] is not None:
            out["batting"] = {
                "avg": bat["avg"], "hr": bat["hr"], "k_pct": bat["k_pct"], "bb_pct": bat["bb_pct"],
                "exit_velo": bat["exit_velo"], "hard_hit_pct": bat["hard_hit_pct"],
                "barrel_pct": bat["barrel_pct"], "launch_angle": bat["launch_angle"],
                "woba": bat["woba"], "xwoba": bat["xwoba"],
            }

        if pit and pit["whiff_pct"] is not None:
            out["pitching"] = {
                "whiff_pct": pit["whiff_pct"], "k_pct": pit["k_pct"],
                "exit_velo_against": pit["exit_velo_against"],
                "barrel_pct_against": pit["barrel_pct_against"],
                "xwoba_against": pit["xwoba_against"],
            }

        con.close()
        return out
    except Exception as e:
        return {"stats": None, "message": f"MLB stats error: {str(e)[:200]}"}


# player_stats stores every NFL column for every player, zero-filled — a receiver
# carries pass_yds_g 0, a quarterback carries targets 0. Rendering the row whole
# opens a tight end's page on "Pass Yds/G 0 · Pass TDs 0 · INTs 0 · Comp/G 0 ·
# Pass EPA 0 · Carries/G 0", which is the first thing on the page and says nothing.
# Which phases a player participates in is a property of his position, so pick the
# blocks off position and prune values second.
_NFL_STAT_BLOCKS = {
    "passing":   ("passing_yards_pg", "passing_tds", "interceptions",
                  "completions_pg", "passing_epa"),
    "rushing":   ("carries_pg", "rushing_yards_pg"),
    "receiving": ("receptions", "receiving_yards_pg", "targets"),
    "fantasy":   ("fantasy_points_pg", "fantasy_points_ppr_pg"),
}

_NFL_POSITION_BLOCKS = {
    "QB": ("passing", "rushing", "fantasy"),
    "RB": ("rushing", "receiving", "fantasy"),
    "FB": ("rushing", "receiving", "fantasy"),
    "WR": ("receiving", "fantasy"),
    "TE": ("receiving", "fantasy"),
}


def _nfl_stats_for_position(stats: dict, position):
    """Narrow a zero-filled NFL stat row to the phases the position plays.

    Within a kept block a zero is a real number — a quarterback with no
    interceptions has thrown none — so only ``None`` is dropped there. An
    unrecognized position (linemen, kickers, defenders, or a missing value) has no
    known phase, so it falls back to dropping anything empty rather than to
    printing the whole zero-filled row."""
    blocks = _NFL_POSITION_BLOCKS.get(str(position or "").upper().strip())
    if blocks is None:
        return {k: v for k, v in stats.items() if v}
    keep = {k for b in blocks for k in _NFL_STAT_BLOCKS[b]}
    return {k: v for k, v in stats.items() if k in keep and v is not None}


def _get_nfl_stats(player_name: str, player_id: int, now: float):
    """Pull the canonical published NFL regular-season totals."""
    import os, sqlite3 as sq

    try:
        db_path = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
        con = sq.connect(db_path)
        con.row_factory = sq.Row

        row = canonical_player_stats_row(
            con, player_id=player_id, league="nfl", stat_type="season"
        )

        if not row:
            con.close()
            return {"stats": None, "message": f"No NFL data for {player_name}. Run ingest_nfl.py."}

        out = {
            "window": str(row["season"]),
            "player_name_nfl": player_name,
            "position": row["nfl_position"],
            "team": row["nfl_team"],
            "games": row["games"],
            "source": row["source"] or "nflverse",
            "stats": _nfl_stats_for_position({
                "passing_yards_pg": row["pass_yds_g"],
                "passing_tds": row["pass_td"],
                "interceptions": row["interceptions"],
                "completions_pg": row["cmp_g"],
                "passing_epa": row["pass_epa"],
                "carries_pg": row["carries_g"],
                "rushing_yards_pg": row["rush_yds_g"],
                "receptions": row["receptions"],
                "receiving_yards_pg": row["rec_yds_g"],
                "targets": row["targets"],
                "fantasy_points_pg": row["fantasy_pts_g"],
                "fantasy_points_ppr_pg": row["fantasy_ppr_g"],
            }, row["nfl_position"]),
        }
        con.close()
        return out
    except Exception as e:
        return {"stats": None, "message": f"NFL stats error: {str(e)[:200]}"}


def _get_nba_stats(player_name: str, player_id: int, now: float):
    """Pull the canonical NBA season row."""
    import os, sqlite3 as sq

    try:
        db_path = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
        con = sq.connect(db_path)
        con.row_factory = sq.Row

        row = canonical_player_stats_row(
            con, player_id=player_id, league="nba", stat_type="season"
        )

        if not row:
            con.close()
            return {
                "stats": None,
                "message": (
                    f"Could not find NBA stats for {player_name}. "
                    "Run the season-appropriate published stats ingest."
                ),
            }

        out = {
            "window": str(row["season"]),
            "player_name_nba": player_name,
            "team": row["team"],
            "games": row["games"],
            # Never default a publisher. A row with no source has no known
            # publisher, and naming one is a claim we cannot support -- the old
            # default said "hoopR" for rows that may never have come from it,
            # and as of 2026-08-05 there are no hoopR rows left at all.
            "source": row["source"] or None,
            "stats": {
                "pts": round(float(row["pts"]), 1),
                "reb": round(float(row["reb"]), 1),
                "ast": round(float(row["ast"]), 1),
                "stl": round(float(row["stl"]), 1),
                "blk": round(float(row["blk"]), 1),
                "fg_pct": round(float(row["fgm"]) / float(row["fga"]) * 100, 1) if row["fga"] else 0,
                "fg3_pct": round(float(row["fg3m"]) / float(row["fg3a"]) * 100, 1) if row["fg3a"] else 0,
                "ft_pct": round(float(row["ftm"]) / float(row["fta"]) * 100, 1) if row["fta"] else 0,
                "min_pg": round(float(row["minutes"]), 1) if row["minutes"] else 0,
                "turnovers": round(float(row["tov"]), 1),
                "ts_pct": round(float(row["ts_pct"]), 1),
            }
        }
        con.close()
        return out
    except Exception as e:
        return {"stats": None, "message": f"NBA stats error: {str(e)[:200]}"}


def _get_nhl_stats(player_name: str, player_id: int, now: float):
    """Pull NHL's published nhle.com season row."""
    import os, sqlite3 as sq

    try:
        db_path = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
        con = sq.connect(db_path)
        con.row_factory = sq.Row

        row = canonical_player_stats_row(
            con, player_id=player_id, league="nhl", stat_type="season"
        )

        if not row:
            con.close()
            return {"stats": None, "message": f"No NHL data for {player_name}. Run ingest_nhl.py."}

        out = {
            "window": str(row["season"]),
            "player_name_nhl": player_name,
            "position": row["nhl_position"],
            "team": row["nhl_team"],
            "games": row["games"],
            "source": row["source"] or "nhle.com",
            "stats": {
                "goals": row["goals"], "assists": row["assists"], "points": row["points_nhl"],
                "shots": row["shots"], "shooting_pct": row["shooting_pct"],
                "plus_minus": row["plus_minus"], "pim": row["pim"],
                "ppg": row["ppg"], "ppp": row["ppp"], "shg": row["shg"],
                "toi": row["toi"], "faceoff_pct": row["faceoff_pct"],
            }
        }
        con.close()
        return out
    except Exception as e:
        return {"stats": None, "message": f"NHL stats error: {str(e)[:200]}"}


# Export the underscore-prefixed helpers: `from _core import *` has to keep
# reaching them, and the default `import *` rule hides a leading underscore.
# _core.py does exactly this for the same reason.
__all__ = [n for n in dir() if not n.startswith("__")]
