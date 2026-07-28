#!/usr/bin/env python3
"""ingest_nfl_dst.py — D/ST team-defense weekly stats from nflverse.

Reads the team-level defensive stats from the nflverse stats_team artifact,
derives points-allowed from nfl_schedule (which already has home_score/away_score),
computes ESPN-standard D/ST fantasy points, and writes them to nfl_dst_stats.

The 32 DEF player rows (one per NFL team, position='DEF', name='<Team Name> D/ST')
are created if they don't already exist.

Team codes are normalised to ESPN vocabulary at the boundary so that the
nflverse codes LA→LAR / WAS→WSH match the players table and the rest of the
backend.  points_allowed is derived directly from nfl_schedule rather than
team_game_results because the latter carries ESPN game_ids for 2025 while the
D/ST parquet and nfl_schedule both use nflverse game_ids — mixing vocabularies
would silently miss rows.

Scoring formula (standard ESPN D/ST):
  sack       = 1 pt
  int        = 2 pt
  fumble rec = 2 pt
  TD         = 6 pt
  safety     = 2 pt
  ST TD      = 6 pt
  PR TD      = 6 pt
  points_allowed tiers:
    0       = 10
    1-6     = 7
    7-13    = 4
    14-20   = 1
    21-27   = 0
    28-34   = -1
    35+     = -4

Usage: python3 ingest_nfl_dst.py [--year 2025] [--dry-run]
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import urllib.request
from typing import Dict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from team_codes import UnknownTeamCode, normalize as normalize_team

# NFL_TEAMS: canonical code -> full team name
_HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_HERE, "..", "docs", "espn-team-codes-2026-07-27.json")) as fh:
    NFL_TEAMS: Dict[str, str] = json.load(fh)["nfl"]


DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
       "stats_team/stats_team_week_{year}.parquet")

# Columns we need from the nflverse team stats artifact.
_REQUIRED_COLS = [
    "season", "week", "season_type", "team", "game_id",
    "def_sacks", "def_interceptions", "def_tds", "def_safeties",
    "fumble_recovery_opp", "special_teams_tds", "pt_return_tds",
]


def points_allowed_tier(pa: float) -> float:
    """Standard ESPN D/ST points-allowed scoring tiers."""
    if pa == 0:
        return 10.0
    if pa <= 6:
        return 7.0
    if pa <= 13:
        return 4.0
    if pa <= 20:
        return 1.0
    if pa <= 27:
        return 0.0
    if pa <= 34:
        return -1.0
    return -4.0


def compute_fantasy_pts(
    sacks: float = 0,
    interceptions: float = 0,
    fumble_rec: float = 0,
    tds: float = 0,
    safeties: float = 0,
    st_tds: float = 0,
    pr_tds: float = 0,
    points_allowed: float = 0,
) -> float:
    """Compute ESPN-standard D/ST fantasy points from per-game stats."""
    pts = 0.0
    pts += (sacks or 0) * 1.0
    pts += (interceptions or 0) * 2.0
    pts += (fumble_rec or 0) * 2.0
    pts += (tds or 0) * 6.0
    pts += (safeties or 0) * 2.0
    pts += (st_tds or 0) * 6.0
    pts += (pr_tds or 0) * 6.0
    pts += points_allowed_tier(points_allowed or 0)
    return round(pts, 1)


def ensure_dst_table(con: sqlite3.Connection) -> None:
    """Create nfl_dst_stats if it doesn't exist."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS nfl_dst_stats (
            player_id       INTEGER NOT NULL,
            season          INTEGER NOT NULL,
            week            INTEGER NOT NULL,
            sacks           REAL,
            interceptions   REAL,
            tds             REAL,
            safeties        REAL,
            fumble_rec      REAL,
            st_tds          REAL,
            pr_tds          REAL,
            points_allowed  REAL,
            fantasy_pts     REAL,
            UNIQUE(player_id, season, week)
        )
    """)
    con.commit()


def _num(v):
    """Parquet nulls arrive as None or NaN; both mean 'absent', not zero."""
    if v is None or v != v:
        return None
    f = float(v)
    return int(f) if f.is_integer() else round(f, 3)


def ensure_dst_players(con: sqlite3.Connection) -> dict:
    """Ensure 32 DEF player rows exist, return {team_code: player_id}."""
    cur = con.execute(
        "SELECT id, team FROM players WHERE league='nfl' AND position='DEF' AND active=1"
    )
    existing = {row[1]: row[0] for row in cur.fetchall()}

    missing = [
        code for code in NFL_TEAMS if code not in existing
    ]
    if missing:
        for code in missing:
            team_name = NFL_TEAMS[code]
            cur = con.execute(
                """INSERT INTO players (name, league, team, position, active, updated_at)
                   VALUES (?, 'nfl', ?, 'DEF', 1, datetime('now'))""",
                (f"{team_name} D/ST", code),
            )
            existing[code] = cur.lastrowid
        con.commit()

    return existing


def fetch(year: int, cache_dir: str) -> str:
    """Download the artifact and report its sha256."""
    path = os.path.join(cache_dir, f"stats_team_week_{year}.parquet")
    if not os.path.exists(path):
        urllib.request.urlretrieve(URL.format(year=year), path)
    with open(path, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    print(f"  artifact: {os.path.basename(path)} ({os.path.getsize(path)} bytes)")
    print(f"  sha256  : {digest}")
    return path


def build_rows(path: str) -> list:
    """Parse team defense rows from the parquet artifact."""
    import pyarrow.parquet as pq

    have = set(pq.ParquetFile(path).schema.names)
    missing = [c for c in _REQUIRED_COLS if c not in have]
    if missing:
        raise RuntimeError(
            f"artifact is missing expected columns: {missing}\n"
            f"Have: {sorted(have)}"
        )

    t = pq.read_table(path, columns=_REQUIRED_COLS).to_pydict()
    out = []
    n = len(t["season"])
    for i in range(n):
        season_type = str(t["season_type"][i] or "").strip()
        if season_type != "REG":
            continue

        raw_team = str(t["team"][i] or "").strip().upper()
        if not raw_team:
            continue
        try:
            team = normalize_team("nfl", raw_team)
        except UnknownTeamCode:
            continue
        if team not in NFL_TEAMS:
            continue

        out.append({
            "season": int(t["season"][i]),
            "week": int(t["week"][i]),
            "team": team,
            "game_id": str(t["game_id"][i] or ""),
            "sacks": _num(t["def_sacks"][i]),
            "interceptions": _num(t["def_interceptions"][i]),
            "tds": _num(t["def_tds"][i]),
            "safeties": _num(t["def_safeties"][i]),
            "fumble_rec": _num(t["fumble_recovery_opp"][i]),
            "st_tds": _num(t["special_teams_tds"][i]),
            "pr_tds": _num(t["pt_return_tds"][i]),
        })
    return out


def get_points_allowed(con: sqlite3.Connection, season: int) -> dict:
    """Fetch (team, week) -> points_allowed from nfl_schedule.

    nfl_schedule holds home_score / away_score from nflverse games.csv.
    For a home team, points allowed = away_score (opponent score).
    For an away team, points allowed = home_score.

    We source this from nfl_schedule rather than team_game_results because
    team_game_results carries mixed game_id vocabularies: 2025 rows use ESPN
    game_ids while nfl_schedule and the D/ST parquet both use nflverse
    game_ids.  nfl_schedule is the single source of truth for team-week
    score data and avoids the join mismatch.
    """
    schedule_cols = {row[1] for row in con.execute("PRAGMA table_info(nfl_schedule)")}
    needed = {"home_score", "away_score", "home_team", "away_team", "week"}
    if not needed.issubset(schedule_cols):
        return _get_pa_from_team_game_results(con, season)

    # nfl_schedule normalises team abbreviations to ESPN (ingest_nfl_schedule.py
    # line 186), so codes like LAR/WSH already match what ensure_dst_players
    # returns and what the parquet rows carry after our own normalisation.
    rows = con.execute(
        """SELECT week, home_team AS team, away_score AS points_allowed
           FROM nfl_schedule
           WHERE season = ? AND week < 19 AND away_score IS NOT NULL
        UNION ALL
        SELECT week, away_team AS team, home_score AS points_allowed
           FROM nfl_schedule
           WHERE season = ? AND week < 19 AND home_score IS NOT NULL""",
        (season, season),
    ).fetchall()

    pa = {}
    for week, team, pts in rows:
        try:
            wk = int(week)
        except (TypeError, ValueError):
            continue
        pa[(team, wk)] = pts
    return pa


def _get_pa_from_team_game_results(con: sqlite3.Connection, season: int) -> dict:
    """Fallback: key points_allowed by (team, game_id) from team_game_results.

    Only used when nfl_schedule lacks home_score/away_score columns.
    game_id mismatch between ESPN (2025) and nflverse means this may
    produce incomplete data for mixed-vocabulary seasons.
    """
    rows = con.execute(
        """SELECT tgr.team, tgr.game_id, tgr.score_against
           FROM team_game_results tgr
           WHERE tgr.league='nfl' AND tgr.season=?""",
        (season,),
    ).fetchall()
    pa = {}
    for team, game_id, score_against in rows:
        pa[(team, game_id)] = score_against
    return pa


def ingest(con: sqlite3.Connection, year: int, rows: list,
           dst_players: dict, dry_run: bool = False) -> int:
    """Write D/ST stats to nfl_dst_stats."""
    ensure_dst_table(con)

    points_allowed_map = get_points_allowed(con, year)

    written = 0
    for row in rows:
        player_id = dst_players.get(row["team"])
        if player_id is None:
            continue

        # Look up points_allowed: try (team, week) first, then (team, game_id)
        pa = points_allowed_map.get((row["team"], row["week"]))
        if pa is None:
            pa = points_allowed_map.get((row["team"], row["game_id"]))
        pa = _num(pa)

        fantasy_pts = compute_fantasy_pts(
            sacks=row["sacks"] or 0,
            interceptions=row["interceptions"] or 0,
            fumble_rec=row["fumble_rec"] or 0,
            tds=row["tds"] or 0,
            safeties=row["safeties"] or 0,
            st_tds=row["st_tds"] or 0,
            pr_tds=row["pr_tds"] or 0,
            points_allowed=pa or 0,
        )

        if not dry_run:
            con.execute(
                """INSERT INTO nfl_dst_stats
                   (player_id, season, week, sacks, interceptions, tds,
                    safeties, fumble_rec, st_tds, pr_tds, points_allowed, fantasy_pts)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(player_id, season, week) DO UPDATE SET
                     sacks=excluded.sacks,
                     interceptions=excluded.interceptions,
                     tds=excluded.tds,
                     safeties=excluded.safeties,
                     fumble_rec=excluded.fumble_rec,
                     st_tds=excluded.st_tds,
                     pr_tds=excluded.pr_tds,
                     points_allowed=excluded.points_allowed,
                     fantasy_pts=excluded.fantasy_pts""",
                (player_id, row["season"], row["week"],
                 row["sacks"], row["interceptions"], row["tds"],
                 row["safeties"], row["fumble_rec"],
                 row["st_tds"], row["pr_tds"],
                 pa, fantasy_pts),
            )
        written += 1

    if not dry_run:
        con.commit()
    return written


def main():
    ap = argparse.ArgumentParser(description="Ingest NFL D/ST weekly stats from nflverse")
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--dry-run", action="store_true",
                    help="build and report, write nothing")
    ap.add_argument("--cache-dir", default="/tmp")
    args = ap.parse_args()

    print(f"nflverse team defense stats -> nfl_dst_stats  (year={args.year})")
    path = fetch(args.year, args.cache_dir)
    rows = build_rows(path)
    print(f"  built {len(rows)} team-week defensive rows")

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    dst_players = ensure_dst_players(con)
    print(f"  {len(dst_players)} D/ST player rows ready")

    written = ingest(con, args.year, rows, dst_players, args.dry_run)
    if args.dry_run:
        print(f"  dry run: {written} rows would be written")
    else:
        print(f"  wrote {written} rows to nfl_dst_stats")

    con.close()


if __name__ == "__main__":
    main()
