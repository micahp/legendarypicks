#!/usr/bin/env python3
"""mlb_settle.py — settle MLB props from the MLB Stats API boxscore."""
import datetime as dt
import sqlite3
from typing import Optional

from settlement.market_mapping import normalize_market, MARKET_ALIASES
from settlement.mlb_api import _fetch_mlb_gamepk, _fetch_mlb_boxscore


# MLB Stats API field names → our canonical stat_key
_MLB_BATTING_STATS = {
    "hits": "H", "totalBases": "TB", "rbi": "RBI", "runs": "R",
    "homeRuns": "HR", "doubles": "2B", "triples": "3B",
    "stolenBases": "SB", "atBats": "AB",
}
_MLB_PITCHING_STATS = {
    "strikeOuts": "SO", "hits": "H", "earnedRuns": "ER",
    "baseOnBalls": "BB", "inningsPitched": "IP", "outs": "outs",
}

# Canonical market name → (mlb_api_category, mlb_api_field_name)
_MLB_MARKET_MAP = {
    # Pitching
    "strikeouts":    ("pitching", "strikeOuts"),
    "hits_allowed":  ("pitching", "hits"),
    "outs":          ("pitching", "outs"),
    "earned_runs":   ("pitching", "earnedRuns"),
    "walks":         ("pitching", "baseOnBalls"),
    # Batting
    "batter_walks":          ("batting", "baseOnBalls"),
    "doubles":               ("batting", "doubles"),
    "home_runs":             ("batting", "homeRuns"),
    "runs":                  ("batting", "runs"),
    "rbis":                  ("batting", "rbi"),
    "hits":                  ("batting", "hits"),
    "total_bases":           ("batting", "totalBases"),
    "hits_runs_rbis":        (None, None),  # compound — sum H+R+RBI
    "home_run_any":          ("batting", "homeRuns"),
    "hit_any":               ("batting", "hits"),
    "rbi_any":               ("batting", "rbi"),
    "run_any":               ("batting", "runs"),
    "stolen_base_any":       ("batting", "stolenBases"),
    "double_any":            ("batting", "doubles"),
    "triple_any":            ("batting", "triples"),
}


def _settle_mlb_props(con, game_row, props) -> dict:
    """Settle MLB props using the MLB Stats API boxscore (mlbam_id-based matching)."""
    import settlement
    from settlement.grading import _grade_actual
    from settlement.market_mapping import normalize_market, MARKET_ALIASES

    date_str = game_row["date"]
    home = game_row["home"]
    away = game_row["away"]
    try:
        start_time = game_row["start_time"]
    except (KeyError, IndexError):
        start_time = None
    gamePk = settlement._fetch_mlb_gamepk(date_str, home, away, start_time=start_time)
    if not gamePk:
        return {"settled": 0, "void": 0, "unmappable": 0,
                "pending": len(props),
                "errors": 0,
                "msg": f"MLB gamePk not found for {away}@{home} on {date_str} "
                       f"(start_time={start_time or 'none'})"}

    box = settlement._fetch_mlb_boxscore(gamePk)
    if not box:
        return {"settled": 0, "void": 0, "unmappable": 0,
                "pending": len(props),
                "errors": 1,
                "error_msg": f"MLB boxscore failed for gamePk={gamePk}"}

    # Build lookup: mlbam_id → {"batting": {...}, "pitching": {...}}
    player_stats = {}
    for side in ("away", "home"):
        team_data = box.get("teams", {}).get(side, {})
        players_dict = team_data.get("players", {})
        for key, pdata in players_dict.items():
            if key.startswith("ID"):
                try:
                    mlbam = int(key[2:])
                except ValueError:
                    continue
            else:
                try:
                    mlbam = int(key)
                except ValueError:
                    continue
            stats = pdata.get("stats", {})
            game_status = pdata.get("gameStatus") or {}
            player_stats[mlbam] = {
                "batting": stats.get("batting", {}),
                "pitching": stats.get("pitching", {}),
                "appeared": any(bool(group) for group in stats.values()),
                # A final boxscore explicitly identifies unused bench players.
                # Require every stat group to be empty as well: a player who
                # appeared and later returned to the bench is not a DNP.
                "dnp": (
                    game_status.get("isOnBench") is True
                    and game_status.get("isSubstitute") is False
                    and not any(bool(group) for group in stats.values())
                ),
            }

    # Build player_id → mlbam_id lookup from the spine
    player_mlbam = {}
    for r in con.execute("SELECT id, mlbam_id FROM players WHERE league='mlb' AND mlbam_id IS NOT NULL AND mlbam_id != 0"):
        player_mlbam[r["id"]] = r["mlbam_id"]

    settled = 0
    void = 0
    unmappable = 0
    pending = 0
    errors = 0
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    for prop in props:
        mlbam_id = player_mlbam.get(prop["player_id"])
        if not mlbam_id:
            pending += 1
            continue

        ps = player_stats.get(mlbam_id)
        if not ps:
            pending += 1
            continue

        if ps.get("dnp"):
            try:
                con.execute(
                    "INSERT INTO prop_results(prop_id, actual_value, hit, settled_at) "
                    "VALUES (?,NULL,NULL,?)",
                    (prop["id"], now))
                void += 1
            except Exception:
                errors += 1
            continue

        canonical = normalize_market(prop["market"])
        canonical = MARKET_ALIASES.get(canonical, canonical)
        mapping = _MLB_MARKET_MAP.get(canonical)

        # The player appeared, but not in the role this market measures (for
        # example Ohtani batted but did not pitch, or a position player pitched
        # without taking a plate appearance).  An empty required category plus
        # a populated different category is positive role-DNP evidence.
        required_category = ("batting" if canonical == "hits_runs_rbis"
                             else (mapping[0] if mapping else None))
        if (required_category and ps.get("appeared")
                and not ps.get(required_category)):
            try:
                con.execute(
                    "INSERT INTO prop_results(prop_id, actual_value, hit, settled_at) "
                    "VALUES (?,NULL,NULL,?)",
                    (prop["id"], now))
                void += 1
            except Exception:
                errors += 1
            continue

        if not mapping or mapping == (None, None):
            if canonical in ("hits_runs_rbis", "hits_runs_rbis"):
                bat = ps.get("batting") or {}
                parts = [bat.get(k) for k in ("hits", "runs", "rbi")]
                if any(v is None for v in parts):
                    pending += 1
                    continue
                actual = float(sum(parts))
            else:
                unmappable += 1
                continue
        else:
            category, mlb_field = mapping
            stats_dict = ps.get(category, {})

            if mlb_field == "outs" and "outs" not in stats_dict:
                ip_str = stats_dict.get("inningsPitched")
                if ip_str:
                    try:
                        actual = float(ip_str) * 3
                    except (ValueError, TypeError):
                        pending += 1
                        continue
                else:
                    pending += 1
                    continue
            else:
                actual = stats_dict.get(mlb_field)
                if actual is None:
                    pending += 1
                    continue
                try:
                    actual = float(actual)
                except (ValueError, TypeError):
                    pending += 1
                    continue

        line = prop["line"]
        side = (prop["side"] or "").lower()
        if side == "over":
            hit = 1 if actual > line else (0 if actual < line else None)
        elif side == "under":
            hit = 1 if actual < line else (0 if actual > line else None)
        else:
            unmappable += 1
            continue

        try:
            con.execute(
                "INSERT INTO prop_results(prop_id, actual_value, hit, settled_at) VALUES (?,?,?,?)",
                (prop["id"], actual, hit, now))
            settled += 1
        except Exception:
            errors += 1

    con.commit()
    return {"settled": settled, "void": void, "unmappable": unmappable,
            "pending": pending, "errors": errors}
