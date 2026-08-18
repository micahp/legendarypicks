"""Pool endpoint for the NFL mock-draft package."""

from fastapi import Query
from fastapi.responses import Response
from nfl_rankings import (
    NFL_RANK_STATS,
    nfl_player_rank_context,
    nfl_player_stat_ranks_batch,
)

from . import router
from .cache import _clear_pool_cache, _pool_cache_get, _pool_cache_put
from .constants import (
    _CONTRACT,
    _CURRENT_SEASON,
    _DRAFT_POSITIONS,
    _REG_SEASON_TEAM_GAMES,
    _THIN_SAMPLE_GAMES,
)
from .db import _conn
from .helpers import _json
from ..nfl_offseason import (
    _availability_aggregates,
    _database_cache_token,
    _dst_aggregates,
    _percentage,
    _pk_aggregates,
    _regular_season_aggregates,
    _rounded_ratio,
    _round,
    _table_columns,
)


@router.get("/api/nfl/mock-draft/pool")
def pool(season: int = Query(...)):
    """Return the full published player universe for mock drafts (v0.7.0 T2).

    No cap, no active/ownership filter: every nfl_adp row for the season is a
    pool entry — free agents included, rendering a "—" ADP. D/ST carry ESPN's
    published PPR rank as their ADP (v0.7.0 T1). X-Device-Id is NOT required
    for this endpoint — it is read-only public data.
    """
    if season != _CURRENT_SEASON:
        return _json({"error": f"season must be {_CURRENT_SEASON}"}, status=400)

    connection = _conn()
    try:
        database_token = _database_cache_token(connection)
        cache_key = (
            (database_token, season)
            if database_token is not None else None
        )
        cached_body = _pool_cache_get(cache_key)
        if cached_body is not None:
            return Response(content=cached_body, media_type="application/json")

        # ------------------------------------------------------------------
        # Availability aggregates — read from the most recent completed
        # season (what the player actually did), not from the draft season
        # (which hasn't been played yet).
        # ------------------------------------------------------------------
        _log_season_row = connection.execute(
            "SELECT MAX(season) FROM player_game_logs WHERE league='nfl'"
        ).fetchone()
        _log_season = (_log_season_row[0] if _log_season_row and _log_season_row[0]
                       else _CURRENT_SEASON - 1)

        availability = _availability_aggregates(
            connection, _log_season
        )

        # One implementation of the season aggregate, shared with the research
        # board. job16 originally re-accumulated these in Python to guarantee
        # pool/detail parity, which anchored two surfaces to each other and left
        # the board -- the surface a drafter consults for truth -- disagreeing
        # with both on six players. The difference was never rounding mode but
        # float accumulation order: Chris Olave's 268.0 PPR over 16 games is an
        # exact 16.75, which SQLite's SUM reaches and a Python loop misses by a
        # last bit, so one screen said 16.8 and the other 16.7. Deriving all
        # three from _regular_season_aggregates makes the question moot.
        _log_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(player_game_logs)"
            ).fetchall()
        }
        season_stats = {}
        if "stats" in _log_columns:
            pk_by_player = _pk_aggregates(
                connection, _log_season, availability
            )
        else:
            pk_by_player = {}
        dst_availability, dst_team_weeks = _dst_aggregates(
            connection, _log_season
        )

        # ------------------------------------------------------------------
        # Query the pool: the FULL published universe for the season, from
        # nfl_adp (v0.7.0 T2 — 11,515 players incl. free agents). No cap, no
        # active filter, no ownership filter: the UI filters "available" vs
        # "drafted", and a free agent is a real pool entry that renders a "—"
        # ADP. Projections/rank/adp_ppr columns are conditional: a DB that has
        # not yet run the migrations must not 500 — it serves honest NULLs.
        # ------------------------------------------------------------------
        _has_proj = bool(_table_columns(connection, "nfl_player_projections"))
        _has_rank = "espn_ppr_rank" in _table_columns(connection, "nfl_adp")
        _has_ppr = "adp_ppr" in _table_columns(connection, "nfl_adp")
        _has_pos = "position" in _table_columns(connection, "nfl_adp")
        _has_injury = {"injury_status", "last_news_date"}.issubset(
            _table_columns(connection, "players")
        )
        _injury_select = (
            ", p.injury_status, p.last_news_date"
            if _has_injury else ", NULL AS injury_status, NULL AS last_news_date"
        )
        _position_expr = "na.position" if _has_pos else "p.position"
        _pos_select = f"{_position_expr} AS position"
        _proj_select = (
            ", np.lp_ppr_projected_points AS proj_ppr_points"
            if _has_proj else ", NULL AS proj_ppr_points"
        )
        _proj_join = (
            " LEFT JOIN nfl_player_projections np"
            " ON np.player_id = p.id AND np.season = ?"
            if _has_proj else ""
        )
        _proj_params = (season,) if _has_proj else ()
        _rank_select = ", na.espn_ppr_rank" if _has_rank else ", NULL AS espn_ppr_rank"
        _ppr_select = ", na.adp_ppr" if _has_ppr else ", NULL AS adp_ppr"
        # D/ST's published ADP is ESPN's PPR rank (v0.7.0 T1: DEN 234, SEA 239).
        # Pre-v0.7.0 DBs have no adp_ppr column and fall back to the ADP column.
        _adp_select = (
            "CASE WHEN na.position = 'DEF' THEN na.adp_ppr ELSE na.adp END AS adp"
            if (_has_ppr and _has_pos) else "na.adp"
        )

        rows = connection.execute(
            f"""SELECT p.id AS player_id, p.name, {_pos_select}, p.team,
                           {_adp_select}, na.percent_owned{_rank_select}{_ppr_select}{_proj_select}{_injury_select}
                    FROM players p
                    JOIN nfl_adp na ON na.player_id = p.id AND na.season = ?
                    {_proj_join}
                    WHERE p.league = 'nfl'
                      AND {_position_expr} IN ({','.join('?' for _ in _DRAFT_POSITIONS)})""",
            (season, *_proj_params, *_DRAFT_POSITIONS),
        ).fetchall()

        # Sort by the published ESPN PPR rank — the ESPN-shell contract's RK
        # column. Nulls (e.g. Dominic Zvada, who has ADP but no published rank)
        # follow every ranked player; ADP/ownership break the tie inside a rank.
        rows.sort(key=lambda r: (
            0 if r["espn_ppr_rank"] is not None else 1,
            r["espn_ppr_rank"] if r["espn_ppr_rank"] is not None else 999999,
            0 if r["adp"] is not None else 1,
            r["adp"] if r["adp"] is not None else 999999,
            -(r["percent_owned"] or 0),
            r["name"],
        ))

        # Season aggregates over the whole log table, keeping the pool's rows.
        # Passing player_ids would build an IN clause of ~11,500 terms — past
        # SQLite 3.31's 999-variable limit. The unfiltered scan returns the
        # same per-player numbers: the aggregate groups by player, so narrowing
        # the scan cannot change a result (the helper's own contract).
        if "stats" in _log_columns and rows:
            _all_season_stats = _regular_season_aggregates(
                connection,
                _log_season,
                availability=availability,
            )
            season_stats = {
                pid: _all_season_stats[pid]
                for pid in (row["player_id"] for row in rows)
                if pid in _all_season_stats
            }

        # Whether we hold any NFL game log for this player *before* the
        # reference season. Without it a surface cannot tell a rookie apart
        # from a veteran who missed the whole year, and the pool called Odell
        # Beckham Jr. a rookie -- an outright false statement about a player
        # with eight prior-season rows sitting in this same table. Intersected
        # in Python because the IN clause would exceed the variable limit at
        # pool size.
        prior_sample_ids = set()
        if rows:
            prior_sample_ids = {
                r[0]
                for r in connection.execute(
                    """SELECT DISTINCT player_id FROM player_game_logs
                       WHERE league='nfl' AND season < ?""",
                    (_log_season,),
                )
            } & {row["player_id"] for row in rows}

        # ESPN-style 4-stat rank card for the whole pool, computed once
        # (4 queries) instead of once per player (~17,000 at pool size).
        pool_rank_map = (
            nfl_player_stat_ranks_batch(connection, _log_season) if rows else {}
        )

        players = []
        for row in rows:
            pid = row["player_id"]
            pos = row["position"]

            if pos == "DEF":
                avail = dst_availability.get(pid)
                tw = dst_team_weeks.get(row["team"], [])
                team_games = (
                    len(tw) or _REG_SEASON_TEAM_GAMES
                    if avail is not None
                    else None
                )
            else:
                avail = availability.get(pid)
                tw = avail.get("team_weeks", []) if avail else []
                team_games = (
                    avail.get("team_games", _REG_SEASON_TEAM_GAMES)
                    if avail
                    else None
                )

            gp = avail["games_played"] if avail is not None else None
            wp = sorted(avail["weeks"]) if avail else []
            gm = max(0, team_games - gp) if avail else None
            sample = (
                "full"
                if gp is not None and gp >= _THIN_SAMPLE_GAMES
                else "thin"
                if gp is not None and gp > 0
                else "none"
            )

            # Field for field, the research board's derivation. Any change here
            # has to be made there too, or the two screens start disagreeing
            # about the same player again.
            stats = season_stats.get(pid)
            ppr_total = stats["ppr_total"] if stats else None
            ppr_per_game_played = (
                _rounded_ratio(ppr_total, gp)
                if ppr_total is not None and gp
                else None
            )
            ppr_per_team_game = (
                # Per-player team_games, not the 17-constant (see the board).
                _rounded_ratio(ppr_total, team_games)
                if ppr_total is not None and team_games
                else None
            )
            xfp_per_game = (
                _round(stats["xfp_per_game"], 1)
                if stats and stats["xfp_per_game"] is not None
                else None
            )
            snap_pct = (
                _percentage(stats["snap_pct"], 0)
                if stats and stats["snap_pct"] is not None
                else None
            )
            target_share = (
                _percentage(stats["target_share"], 1)
                if stats and stats["target_share"] is not None
                else None
            )

            pk_pts_total = None
            pk_pts_per_game = None
            if pos == "PK":
                pk_row = pk_by_player.get(pid)
                if pk_row and pk_row["pk_pts_total"] is not None:
                    pk_pts_total = round(pk_row["pk_pts_total"], 1)
                    pk_pts_per_game = pk_row["pk_pts_per_game"]

            dst_pts_total = None
            dst_pts_per_game = None
            if pos == "DEF":
                dst_row = dst_availability.get(pid)
                if dst_row and dst_row["dst_total"] is not None:
                    dst_pts_total = round(dst_row["dst_total"], 1)
                    if dst_row["dst_avg"] is not None:
                        dst_pts_per_game = round(dst_row["dst_avg"], 1)

            if pos in ("PK", "DEF"):
                # All five, not three. A kicker who takes a fake-punt carry
                # picks up real offensive rows, and leaving these two alive
                # published Brandon Aubrey at 0.0 PPR/team-game and 0.8
                # xFP/game as though they were kicking output -- while the
                # research board, which suppresses all five, showed nothing.
                ppr_per_game_played = None
                ppr_per_team_game = None
                xfp_per_game = None
                snap_pct = None
                target_share = None

            # ESPN-style 4-stat rank card — from the batched rank map computed
            # once for the whole pool (v0.7.0: 4 queries, not 17,000).
            stat_ranks = {
                col: entry
                for col, _ in NFL_RANK_STATS.get(pos, ())
                for entry in [pool_rank_map.get(pid, {}).get(col)]
                if entry is not None
            }
            players.append({
                "player_id": pid,
                "name": row["name"],
                "position": pos,
                "team": row["team"],
                "injury_status": row["injury_status"],
                "last_news_date": row["last_news_date"],
                "adp": row["adp"],
                "espn_ppr_rank": row["espn_ppr_rank"],
                "adp_ppr": row["adp_ppr"],
                # 2026 season-long PPR projection computed from ESPN's
                # published projected stat line. Null means the source did not
                # publish a usable projection; it is never coerced to zero.
                "proj_ppr_points": row["proj_ppr_points"],
                "proj_season": season,
                "proj_source": "espn" if row["proj_ppr_points"] is not None else None,
                "percent_owned": row["percent_owned"],
                "sample": sample,
                "has_prior_nfl_sample": pid in prior_sample_ids,
                "games_played": gp,
                "games_missed": gm,
                "weeks_played": wp,
                "team_weeks": tw,
                "team_games": team_games,
                "ppr_per_game_played": ppr_per_game_played,
                "ppr_per_team_game": ppr_per_team_game,
                "xfp_per_game": xfp_per_game,
                "snap_pct": snap_pct,
                "target_share": target_share,
                "pk_pts_total": pk_pts_total,
                "pk_pts_per_game": pk_pts_per_game,
                "dst_pts_total": dst_pts_total,
                "dst_pts_per_game": dst_pts_per_game,
                "stat_ranks": stat_ranks,
            })

        payload = {
            "contract": _CONTRACT,
            "season": season,
            # `season` is the season being drafted; every statistic in this
            # payload describes `reference_season`. Without it a client has
            # to guess which year it is labelling, and the guess is right
            # until it silently isn't -- the draft board publishes this for
            # the same reason.
            "reference_season": _log_season,
            "count": len(players),
            "players": players,
        }
        response = _json(payload)
        # Cache encoded bytes: a cached multi-megabyte dict still pays JSON
        # serialization on every hit and is mutable by callers.
        _pool_cache_put(cache_key, response.body)
        return response
    finally:
        connection.close()