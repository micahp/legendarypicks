"""Player detail endpoint for the NFL mock-draft package."""

from fastapi import Query
from nfl_rankings import nfl_player_rank_context

from . import router
from .constants import (
    _CONTRACT,
    _CURRENT_SEASON,
    _REG_SEASON_TEAM_GAMES,
    _THIN_SAMPLE_GAMES,
)
from .db import _conn
from .helpers import _json, _named_stat_line
from ..nfl_offseason import (
    _availability_aggregates,
    _dst_aggregates,
    _percentage,
    _pk_aggregates,
    _regular_season_aggregates,
    _rounded_ratio,
    _round,
    _table_columns,
)


@router.get("/api/nfl/draft/player/{player_id}")
def player_detail(player_id: int):
    """Return player detail for the mock draft overlay.

    Includes: name, team, position, ADP, percent owned, season stats,
    game strip (weeks played vs team weeks), and for WR/RB/TE the QB on
    their team.
    """
    connection = _conn()
    try:
        # 1. Player lookup. The injury columns are optional (a concurrent
        # feature's migration may not have landed on this DB) — selected only
        # where they exist, so a pre-migration DB serves honest NULLs instead
        # of 500ing on the SELECT.
        _injury_cols = (
            ", p.injury_status, p.last_news_date"
            if {"injury_status", "last_news_date"}
            <= {r["name"] for r in connection.execute("PRAGMA table_info(players)")}
            else ""
        )
        # Position comes from nfl_adp (the fantasy table) with players as the
        # fallback: a team defence plays no position, so `players.position` is
        # NULL for the 32 D/ST rows, and the fantasy label lives in nfl_adp.
        _pos_expr = (
            "COALESCE(na.position, p.position)"
            if "position" in _table_columns(connection, "nfl_adp")
            else "p.position"
        )
        player = connection.execute(
            f"""SELECT p.id, p.name, p.team,
                       {_pos_expr} AS position,
                       p.active{_injury_cols}
                  FROM players p
                  LEFT JOIN nfl_adp na ON na.player_id = p.id AND na.season = ?
                 WHERE p.id=? AND p.league='nfl'""",
            (_CURRENT_SEASON, player_id),
        ).fetchone()

        if player is None:
            return _json({"error": "Player not found"}, status=404)

        name = player["name"]
        team = player["team"]
        position = player["position"]
        active = bool(player["active"])
        injury_status = player["injury_status"] if _injury_cols else None
        last_news_date = player["last_news_date"] if _injury_cols else None

        # 2. ADP / percent owned from nfl_adp. D/ST's published ADP is ESPN's
        #    PPR rank (v0.7.0 T1) — the same mapping the pool applies, so the
        #    overlay and the pool can never disagree about a defense. The rank
        #    columns are conditional: a pre-migration DB serves honest NULLs.
        adp = None
        percent_owned = None
        espn_ppr_rank = None
        espn_standard_rank = None
        adp_ppr = None
        adp_columns = _table_columns(connection, "nfl_adp")
        _has_ppr = "adp_ppr" in adp_columns
        _ppr_col = ", adp_ppr" if _has_ppr else ""
        _rank_cols = ", " + ", ".join(
            column if column in adp_columns else f"NULL AS {column}"
            for column in ("espn_ppr_rank", "espn_standard_rank")
        )
        adp_row = connection.execute(
            f"SELECT adp, percent_owned{_rank_cols}{_ppr_col} "
            f"FROM nfl_adp WHERE player_id=? AND season=?",
            (player_id, _CURRENT_SEASON),
        ).fetchone()
        if adp_row:
            percent_owned = adp_row["percent_owned"]
            if _has_ppr and position == "DEF":
                adp = adp_row["adp_ppr"]
            else:
                adp = adp_row["adp"]
            if _has_ppr:
                adp_ppr = adp_row["adp_ppr"]
            espn_ppr_rank = adp_row["espn_ppr_rank"]
            espn_standard_rank = adp_row["espn_standard_rank"]

        proj_2026_pts = None
        projection_2026 = None
        projection_source = None
        season_outlook = None
        season_outlook_source = None
        season_totals = None
        season_totals_source = None
        projection_columns = _table_columns(connection, "nfl_player_projections")
        if "lp_ppr_projected_points" in projection_columns:
            detail_columns = (
                "lp_ppr_projected_points", "raw_projection_json", "projected_games",
                "pass_att", "pass_cmp", "pass_yds", "pass_td", "interceptions",
                "rush_att", "rush_yds", "rush_td", "receptions", "targets",
                "rec_yds", "rec_td", "fg_att", "fg_made", "xp_att", "xp_made",
                "def_td", "def_int", "def_sack", "def_fumble_rec",
                "def_points_allowed", "def_yds_allowed", "season_outlook",
                "outlook_source", "actual_season", "raw_actual_json",
                "actual_qbr", "actual_passer_rating", "actual_adj_qbr", "qbr_source",
            )
            select_columns = ", ".join(
                column if column in projection_columns else f"NULL AS {column}"
                for column in detail_columns
            )
            split_filter = (
                " AND stat_split_type_id=0"
                if "stat_split_type_id" in projection_columns
                else ""
            )
            proj_row = connection.execute(
                f"SELECT {select_columns} FROM nfl_player_projections "
                f"WHERE player_id=? AND season=?{split_filter}",
                (player_id, _CURRENT_SEASON),
            ).fetchone()
        else:
            proj_row = None
        if proj_row:
            proj_2026_pts = proj_row["lp_ppr_projected_points"]
            projection_source = "espn" if proj_2026_pts is not None else None
            projection_2026 = _named_stat_line(proj_row["raw_projection_json"])
            season_outlook = proj_row["season_outlook"]
            season_outlook_source = proj_row["outlook_source"]
            actual_line = _named_stat_line(
                proj_row["raw_actual_json"], include_actual_first_downs=True
            )
            if actual_line:
                actual_line["qbr"] = proj_row["actual_qbr"]
                actual_line["passer_rating"] = proj_row["actual_passer_rating"]
                actual_line["adj_qbr"] = proj_row["actual_adj_qbr"]
                season_totals = {
                    "season": proj_row["actual_season"],
                    **actual_line,
                    "ppr_points": None,
                }
                season_totals_source = "espn"

        # 3. Season stats from player_game_logs
        _log_season_row = connection.execute(
            "SELECT MAX(season) FROM player_game_logs WHERE league='nfl'"
        ).fetchone()
        _log_season = (_log_season_row[0] if _log_season_row and _log_season_row[0]
                       else _CURRENT_SEASON - 1)
        rank_context = nfl_player_rank_context(
            connection, player_id, position, _log_season
        )
        availability_by_player = _availability_aggregates(
            connection, _log_season
        )
        dst_by_player, dst_team_weeks = _dst_aggregates(
            connection, _log_season
        )

        # Third surface, same aggregate. This endpoint used to re-accumulate the
        # season in Python, which is how it ended up telling a drafter 16.7 for
        # a player the research board showed at 16.8.
        _season_stats = _regular_season_aggregates(
            connection,
            _log_season,
            availability=availability_by_player,
            player_ids=[player_id],
        ).get(player_id)

        if position == "DEF":
            availability = dst_by_player.get(player_id)
            team_weeks = dst_team_weeks.get(team, [])
            team_games = (
                len(team_weeks) or _REG_SEASON_TEAM_GAMES
                if availability is not None
                else None
            )
        else:
            availability = availability_by_player.get(player_id)
            team_weeks = availability.get("team_weeks", []) if availability else []
            team_games = (
                availability.get("team_games", _REG_SEASON_TEAM_GAMES)
                if availability
                else None
            )

        games_played = (
            availability["games_played"] if availability is not None else None
        )
        weeks_played = sorted(availability["weeks"]) if availability else []

        # Sample classification
        if games_played is None or games_played == 0:
            sample = "none"
        elif games_played < _THIN_SAMPLE_GAMES:
            sample = "thin"
        else:
            sample = "full"

        # PPR calculations
        ppr_total = _season_stats["ppr_total"] if _season_stats else None
        ppr_per_game_played = (
            _rounded_ratio(ppr_total, games_played)
            if ppr_total is not None and games_played
            else None
        )
        ppr_per_team_game = (
            _rounded_ratio(ppr_total, team_games)
            if ppr_total is not None and team_games
            else None
        )
        snap_pct = (
            _percentage(_season_stats["snap_pct"], 0)
            if _season_stats and _season_stats["snap_pct"] is not None
            else None
        )
        target_share = (
            _percentage(_season_stats["target_share"], 1)
            if _season_stats and _season_stats["target_share"] is not None
            else None
        )
        xfp_per_game = (
            _round(_season_stats["xfp_per_game"], 1)
            if _season_stats and _season_stats["xfp_per_game"] is not None
            else None
        )

        # 4. QB lookup — for WR/RB/TE, rank team QBs by games played, return top QB
        qb = None
        if position in ("WR", "RB", "TE") and team:
            qb_rows = connection.execute(
                """SELECT p.id, p.name, p.team
                   FROM players p
                   WHERE p.league='nfl' AND p.active=1
                     AND p.position='QB' AND p.team=?
                   ORDER BY p.id ASC""",
                (team,),
            ).fetchall()

            best_qb = None
            best_games = -1
            for qb_row in qb_rows:
                qb_availability = availability_by_player.get(qb_row["id"])
                games = (
                    qb_availability["games_played"]
                    if qb_availability
                    else 0
                )
                if games > best_games:
                    best_games = games
                    best_qb = {
                        "player_id": qb_row["id"],
                        "name": qb_row["name"],
                        "team": qb_row["team"],
                        "games_played": games,
                    }

            if best_qb is not None and best_games > 0:
                qb = best_qb

        # 5. PK scoring, kept separate from the shared presence aggregate.
        pk_pts_total = None
        pk_pts_per_game = None
        if position == "PK":
            pk_row = _pk_aggregates(
                connection, _log_season, availability_by_player
            ).get(player_id)
            if pk_row and pk_row["pk_pts_total"] is not None:
                pk_pts_total = round(pk_row["pk_pts_total"], 1)
                pk_pts_per_game = pk_row["pk_pts_per_game"]

        # 6. D/ST scoring from the same position-specific aggregate as the board.
        dst_pts_total = None
        dst_pts_per_game = None
        if position == "DEF":
            dst_row = dst_by_player.get(player_id)
            if dst_row and dst_row["dst_total"] is not None:
                dst_pts_total = round(dst_row["dst_total"], 1)
                if dst_row["dst_avg"] is not None:
                    dst_pts_per_game = round(dst_row["dst_avg"], 1)

        # ESPN publishes the actual counting-stat season line directly. PPR is
        # the one value absent from that source row, so pair it with the same
        # published-weekly scoring total already used everywhere else in this
        # endpoint. D/ST and kicker retain their position-specific scoring.
        if season_totals is not None:
            if position == "DEF":
                season_totals["ppr_points"] = dst_pts_total
            elif position == "PK":
                season_totals["ppr_points"] = pk_pts_total
            else:
                season_totals["ppr_points"] = (
                    round(ppr_total, 1) if ppr_total is not None else None
                )

        # 7. No presence means unknown missed games, not a fabricated 17.
        games_missed = (
            max(0, team_games - games_played)
            if availability is not None
            else None
        )

        # 7b. Same prior-sample flag the pool publishes, so the overlay does not
        #     call a veteran who missed the season a rookie.
        has_prior_nfl_sample = bool(
            connection.execute(
                """SELECT 1 FROM player_game_logs
                   WHERE league='nfl' AND player_id=? AND season < ? LIMIT 1""",
                (player_id, _log_season),
            ).fetchone()
        )

        # 8. PK/DEF null-override for skill-position fields — all five, so a
        #    fake-punt carry cannot surface as kicking output (see the pool).
        if position in ("PK", "DEF"):
            ppr_per_game_played = None
            ppr_per_team_game = None
            xfp_per_game = None
            snap_pct = None
            target_share = None

        return _json({
            "player_id": player_id,
            "name": name,
            "team": team,
            "position": position,
            "active": active,
            "adp": adp,
            "espn_ppr_rank": espn_ppr_rank,
            "espn_standard_rank": espn_standard_rank,
            "adp_ppr": adp_ppr,
            "proj_2026_pts": proj_2026_pts,
            "projection_2026": projection_2026,
            "projection_source": projection_source,
            "season_outlook": season_outlook,
            "season_outlook_source": season_outlook_source,
            "season_totals": season_totals,
            "season_totals_source": season_totals_source,
            "stat_ranks": rank_context["stats"],
            "stat_rank_season": rank_context["season"],
            "stat_rank_games": rank_context["games"],
            "percent_owned": percent_owned,
            "sample": sample,
            "has_prior_nfl_sample": has_prior_nfl_sample,
            "games_played": games_played,
            "games_missed": games_missed,
            "team_games": team_games,
            "weeks_played": weeks_played,
            "team_weeks": team_weeks,
            "ppr_per_game_played": ppr_per_game_played,
            "ppr_per_team_game": ppr_per_team_game,
            "snap_pct": snap_pct,
            "target_share": target_share,
            "xfp_per_game": xfp_per_game,
            "pk_pts_total": pk_pts_total,
            "pk_pts_per_game": pk_pts_per_game,
            "dst_pts_total": dst_pts_total,
            "dst_pts_per_game": dst_pts_per_game,
            "qb": qb,
            "injury_status": injury_status,
            "last_news_date": last_news_date,
        })
    finally:
        connection.close()