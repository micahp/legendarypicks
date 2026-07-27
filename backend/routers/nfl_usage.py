"""NFL usage trend: per-game snap/target/air-yard shares + WOPR.

READ-ONLY against player_game_logs.  Never writes to the DB.
"""

import json
import sqlite3
from contextlib import closing
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query
from _core import _db

router = APIRouter()

# ── stat vocabulary helpers ──────────────────────────────────────────
# 2024 (source='nflverse'): receiving_yards, rushing_yards, passing_yards,
#   receptions, rushing_tds, receiving_tds, fantasy_points_ppr
# 2025 (source='nflverse_pbp'): rec_yds, rush_yds, pass_yds, rec, rush_td,
#   rec_td, fpts_ppr
# targets is identically named in both — do NOT COALESCE it.


def _num(stats: dict, *keys: str) -> Optional[float]:
    """Return the first non-None numeric value from *keys, or None."""
    for k in keys:
        v = stats.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
    return None


def _yards(stats: dict) -> Optional[float]:
    return _num(stats, "rec_yds", "receiving_yards")


def _rec(stats: dict) -> Optional[float]:
    return _num(stats, "rec", "receptions")


def _rec_td(stats: dict) -> Optional[float]:
    return _num(stats, "rec_td", "receiving_tds")


def _fpts_ppr(stats: dict) -> Optional[float]:
    return _num(stats, "fpts_ppr", "fantasy_points_ppr")


# carries is identically named in both pipelines; the yardage and TD keys are not.
def _carries(stats: dict) -> Optional[float]:
    return _num(stats, "carries")


def _rush_yds(stats: dict) -> Optional[float]:
    return _num(stats, "rush_yds", "rushing_yards")


def _rush_td(stats: dict) -> Optional[float]:
    return _num(stats, "rush_td", "rushing_tds")


# Next Gen and play-by-play metrics. All spelled identically in both pipelines,
# so none of them needs a COALESCE. cpoe / pass_epa exist only from 2025 — the
# 2024 source is nflverse's weekly summary, which does not carry them.
#
# These were ingested and then rendered nowhere. The receiving three are the
# WR/TE separation story; the passing two are the QB accuracy story. See
# docs/NFL-DATA-INVENTORY.md for what covers whom.
_ADVANCED_STATS = ("separation", "cushion", "yac_above_exp", "cpoe", "pass_epa",
                   "st_snaps", "st_pct")


# Derived stats that are stored identically across seasons
def _stat(stats: dict, key: str) -> Optional[float]:
    v = stats.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _targets(stats: dict) -> Optional[float]:
    return _stat(stats, "targets")


def _snaps(stats: dict) -> Optional[float]:
    return _stat(stats, "off_snaps")


def _snap_share(stats: dict) -> Optional[float]:
    return _stat(stats, "off_pct")


def _air_yds_share(stats: dict) -> Optional[float]:
    return _stat(stats, "air_yds_share")


def _adot(stats: dict) -> Optional[float]:
    return _stat(stats, "adot")


# ── target-share computation ─────────────────────────────────────────


def _build_game_key(season: int, game_no: str, game_id: Optional[str]) -> str:
    """Partition key: game_id when present, else (season, game_no)."""
    if game_id:
        return game_id
    return f"{season}-{game_no}"


# Stat keys this module is allowed to aggregate team-wide. Both are named
# identically across the 2024 and 2025 ingest pipelines, so neither needs a
# COALESCE — see the vocabulary note at the top of the file.
_TEAM_SUM_STATS = ("targets", "carries")


def _fetch_team_stat_sums(
    con: sqlite3.Connection,
    game_keys: List[Tuple[int, str, Optional[str], str]],  # (season, game_no, game_id, team)
    stat_key: str,
) -> Dict[Tuple[str, str], float]:
    """Batch-fetch a team-wide stat sum for multiple (game_key, team) pairs.

    Returns a dict keyed by (game_key, team) -> sum of `stat_key`.
    """
    if stat_key not in _TEAM_SUM_STATS:
        raise ValueError(f"unsupported team-sum stat: {stat_key}")
    if not game_keys:
        return {}

    # Collect unique (season, game_no, game_id, team) tuples
    unique = set(game_keys)

    # Build OR clauses for each tuple
    clauses: List[str] = []
    params: List[Any] = []
    for season, game_no, game_id, team in unique:
        if game_id:
            clauses.append("(league='nfl' AND game_id=? AND team=?)")
            params.extend([game_id, team])
        else:
            clauses.append("(league='nfl' AND season=? AND game_no=? AND team=?)")
            params.extend([season, game_no, team])

    if not clauses:
        return {}

    # stat_key is checked against _TEAM_SUM_STATS above, so this interpolation
    # cannot carry anything a caller supplied.
    query = f"""SELECT game_id, season, game_no, team,
                       SUM(CAST(COALESCE(json_extract(stats, '$.{stat_key}'), 0) AS REAL)) AS team_sum
                FROM player_game_logs
                WHERE {' OR '.join(clauses)}
                GROUP BY COALESCE(game_id, season || '-' || game_no), team"""

    rows = con.execute(query, params).fetchall()
    result: Dict[Tuple[str, str], float] = {}
    for row in rows:
        key = _build_game_key(
            row["season"], row["game_no"], row["game_id"],
        )
        result[(key, row["team"])] = float(row["team_sum"])
    return result


def _fetch_team_target_sums(
    con: sqlite3.Connection,
    game_keys: List[Tuple[int, str, Optional[str], str]],
) -> Dict[Tuple[str, str], float]:
    return _fetch_team_stat_sums(con, game_keys, "targets")


# ── WOPR ─────────────────────────────────────────────────────────────


def _wopr(target_share: Optional[float], air_yds_share: Optional[float]) -> Optional[float]:
    """Weighted Opportunity Rating.
    target_share is a 0-1 fraction; air_yds_share is stored 0-100.
    Returns None when air_yds_share is absent (non-receivers).
    """
    if air_yds_share is None:
        return None
    if target_share is None:
        return None
    return round(1.5 * target_share + 0.7 * (air_yds_share / 100.0), 3)


# ── trend ─────────────────────────────────────────────────────────────


def _trend(values: List[Optional[float]]) -> Optional[str]:
    """Compare mean of most recent 3 to prior 3; require >=4 games."""
    clean = [v for v in values if v is not None]
    if len(clean) < 4:
        return None
    recent = clean[:3]
    prior = clean[3:6]
    if not prior:
        return None
    recent_avg = sum(recent) / len(recent)
    prior_avg = sum(prior) / len(prior)
    if prior_avg == 0:
        return "up" if recent_avg > 0 else "flat"
    ratio = recent_avg / prior_avg
    if ratio > 1.10:
        return "up"
    elif ratio < 0.90:
        return "down"
    return "flat"


# ── endpoint ──────────────────────────────────────────────────────────


@router.get("/api/nfl/usage/{player_id}")
def nfl_usage(
    player_id: int,
    season: Optional[int] = Query(None),
    weeks: int = Query(8, ge=1, le=18),
):
    """Per-game usage trend for an NFL player: snaps, targets, air yards, WOPR.

    Query params:
      - season (int, optional) — defaults to player's most recent season in game logs.
      - weeks  (int, default 8, max 18) — how many most-recent games to return.
    """
    with closing(_db()) as con:
        con.row_factory = sqlite3.Row

        # 1. Player lookup
        player = con.execute(
            "SELECT id, name, team, position, league FROM players WHERE id=?",
            (player_id,),
        ).fetchone()

        if not player:
            raise HTTPException(404, "Player not found")

        if player["league"] != "nfl":
            raise HTTPException(400, "NFL only")

        # 2. Resolve season
        if season is None:
            srow = con.execute(
                """SELECT season FROM player_game_logs
                   WHERE player_id=? AND league='nfl'
                   ORDER BY season DESC LIMIT 1""",
                (player_id,),
            ).fetchone()
            if srow is None:
                # player has no game logs — return empty
                return {
                    "player_id": player_id,
                    "name": player["name"],
                    "team": player["team"],
                    "position": player["position"],
                    "season": None,
                    "games": [],
                    "averages": {"snap_share": None, "target_share": None, "wopr": None},
                    "trend": {"snap_share": None, "target_share": None, "wopr": None},
                }
            season = srow["season"]

        weeks = min(weeks, 18)
        assert season is not None  # resolved above

        # 3. Fetch game logs
        logs = con.execute(
            """SELECT game_no, game_id, game_date, opponent, team, stats
               FROM player_game_logs
               WHERE player_id=? AND league='nfl' AND season=?
               ORDER BY COALESCE(game_date,'') DESC, CAST(game_no AS INTEGER) DESC
               LIMIT ?""",
            (player_id, season, weeks),
        ).fetchall()

        if not logs:
            return {
                "player_id": player_id,
                "name": player["name"],
                "team": player["team"],
                "position": player["position"],
                "season": season,
                "games": [],
                "averages": {"snap_share": None, "target_share": None, "wopr": None},
                "trend": {"snap_share": None, "target_share": None, "wopr": None},
            }

        # 4. Batch-fetch all team target sums
        game_keys = [
            (season, row["game_no"], row["game_id"], row["team"])
            for row in logs
        ]
        team_sums = _fetch_team_target_sums(con, game_keys)
        # Backfield share is to a runner what target share is to a receiver.
        # Without it the usage table is almost entirely dashes for an RB.
        team_carry_sums = _fetch_team_stat_sums(con, game_keys, "carries")

        # 5. Build per-game records
        games: List[Dict[str, Any]] = []
        snap_shares: List[Optional[float]] = []
        target_shares: List[Optional[float]] = []
        woprs: List[Optional[float]] = []

        for row in logs:
            stats = json.loads(row["stats"])

            tgts = _targets(stats)
            gk = _build_game_key(season, row["game_no"], row["game_id"])
            team_tgt = team_sums.get((gk, row["team"]), 0.0)
            tgt_share = round(tgts / team_tgt, 3) if (tgts is not None and team_tgt > 0) else None

            ays = _air_yds_share(stats)
            w = _wopr(tgt_share, ays)

            car = _carries(stats)
            team_car = team_carry_sums.get((gk, row["team"]), 0.0)
            car_share = round(car / team_car, 3) if (car is not None and team_car > 0) else None

            game = {
                "week": int(row["game_no"]) if row["game_no"] else None,
                "opponent": row["opponent"],
                "snaps": _snaps(stats),
                "snap_share": _snap_share(stats),
                "targets": tgts,
                "target_share": tgt_share,
                "air_yds_share": ays,
                "adot": _adot(stats),
                "wopr": w,
                "rec": _rec(stats),
                "rec_yds": _yards(stats),
                "rec_td": _rec_td(stats),
                "carries": car,
                "carry_share": car_share,
                "rush_yds": _rush_yds(stats),
                "rush_td": _rush_td(stats),
                "fpts_ppr": _fpts_ppr(stats),
            }
            game.update({k: _stat(stats, k) for k in _ADVANCED_STATS})
            # pass_epa is stored as a game total (a sum of per-play qb_epa).
            # Per-dropback is the comparable form — a 40-attempt game and a
            # 20-attempt game are not on the same scale otherwise.
            att = _num(stats, "att", "attempts")
            game["pass_att"] = att
            # Dropbacks, not attempts. `att` used to double as the dropback count
            # only because the ingest counted sacks as attempts; now that it does
            # not, dividing by `att` would overstate EPA per dropback. Fall back
            # to `att` for rows written before the ingest fix, where the two are
            # still the same number.
            dropbacks = _num(stats, "dropbacks") or att
            game["epa_per_db"] = (
                round(game["pass_epa"] / dropbacks, 3)
                if (game["pass_epa"] is not None and dropbacks) else None
            )
            games.append(game)

            snap_shares.append(_snap_share(stats))
            target_shares.append(tgt_share)
            woprs.append(w)

        # 6. Averages
        def _avg(vals: List[Optional[float]]) -> Optional[float]:
            clean = [v for v in vals if v is not None]
            if not clean:
                return None
            return round(sum(clean) / len(clean), 3)

        averages = {
            "snap_share": _avg(snap_shares),
            "target_share": _avg(target_shares),
            "wopr": _avg(woprs),
        }

        # 7. Trend
        trend = {
            "snap_share": _trend(snap_shares),
            "target_share": _trend(target_shares),
            "wopr": _trend(woprs),
        }

        return {
            "player_id": player_id,
            "name": player["name"],
            "team": player["team"],
            "position": player["position"],
            "season": season,
            "games": games,
            "averages": averages,
            "trend": trend,
        }
