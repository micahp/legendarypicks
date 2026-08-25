"""profile — players router profile layer."""
import json
import math
import sqlite3
import time
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Optional
from _core import *
from league_offering import offered_leagues, sql_league_filter
from league_stats import LEADERBOARD_LEAGUES, canonical_population_sql
from nfl_rankings import nfl_player_rank_context
from nfl_stat_derivations import with_derived as _with_derived
from nfl_news import (ROTOWIRE_LABEL, load_news_feed, load_player_news_page, load_sleeper_crosswalk, merge_player_news, resolve_rotowire_id)
from . import router
from .search import _reg_season_game_filter  # noqa: E402
from .stats import _DST_POSITIONS, _NFL_KEY_NORMALIZE, _NFL_PROJECTION_STATS, _PUBLISHED_FANTASY_POSITIONS  # noqa: E402



def __season_stats_for_profile_pkg(*args, **kwargs):
    """Resolve `routers.players._season_stats_for_profile` at call time (tests patch the package attr)."""
    from routers.players import _season_stats_for_profile as _pkg
    return _pkg(*args, **kwargs)

def __db_pkg(*args, **kwargs):
    """Resolve `routers.players._db` at call time (tests patch the package attr)."""
    from routers.players import _db as _pkg
    return _pkg(*args, **kwargs)

def _dst_game_logs(connection, player_id: int, season=None):
    """A defense's weekly log, from `nfl_dst_stats` instead of `player_game_logs`.

    `player_game_logs` holds zero DEF rows and always will: every row in it comes
    from a box-score PLAYER line, and a defense is not a player. So the profile's
    season lookup returned None, and the page rendered no Game Log section at all
    for a position people draft in the first six rounds.

    `nfl_dst_stats` is where the mock draft already reads them -- one row per team
    per week. Returns `(season, rows)` shaped like `player_game_logs` rows so the
    caller's serializer needs no branch. `game_date` is null because the table does
    not publish one; the NFL schedule block that follows resolves opponent and venue
    from `game_no`, which is the week.
    """
    try:
        srow = connection.execute(
            "SELECT MAX(season) AS season FROM nfl_dst_stats WHERE player_id=?"
            if season is None else
            "SELECT season FROM nfl_dst_stats WHERE player_id=? AND season=? LIMIT 1",
            (player_id,) if season is None else (player_id, season),
        ).fetchone()
    except sqlite3.OperationalError:
        return None, None          # table absent: no logs, not a 500
    season = srow["season"] if srow else None
    if season is None:
        return None, None
    rows = connection.execute(
        """SELECT week, sacks, interceptions, tds, safeties, fumble_rec,
                  st_tds, pr_tds, points_allowed, fantasy_pts
           FROM nfl_dst_stats WHERE player_id=? AND season=?
           ORDER BY week DESC""",
        (player_id, season),
    ).fetchall()
    logs = []
    for row in rows:
        stats = {
            "sacks": row["sacks"],
            "interceptions": row["interceptions"],
            "fumble_rec": row["fumble_rec"],
            "def_td": row["tds"],
            "safeties": row["safeties"],
            "points_allowed": row["points_allowed"],
            # A defense scores the same in standard and PPR -- it catches no passes.
            # Both keys carry the published number rather than one being derived.
            "fpts": row["fantasy_pts"],
            "fpts_ppr": row["fantasy_pts"],
        }
        logs.append({
            "stats": json.dumps({k: v for k, v in stats.items() if v is not None}),
            "game_date": None,
            "opponent": None,
            "home_away": None,
            "game_no": row["week"],
        })
    return season, logs

def _season_stats_for_profile(player_id: int, player_name: str, league: str):
    """Reuse the DB-backed advanced-stat readers for the page-level profile."""
    getter = {
        "mlb": lambda: _get_mlb_stats(player_name, player_id, None, time.time()),
        "nfl": lambda: _get_nfl_stats(player_name, player_id, time.time()),
        "nba": lambda: _get_nba_stats(player_name, player_id, time.time()),
        "nhl": lambda: _get_nhl_stats(player_name, player_id, time.time()),
    }.get(str(league or "").lower())
    if getter is None:
        return None
    result = getter()
    if not isinstance(result, dict):
        return None
    has_stats = (
        bool(result.get("stats"))
        or bool(result.get("batting"))
        or bool(result.get("pitching"))
    )
    return result if has_stats else None


def _same_published_season(league, log_season, stats_season):
    """Match equivalent publisher keys without rewriting either stored value."""
    try:
        stats_year = int(stats_season)
    except (TypeError, ValueError):
        return False
    raw_log_season = str(log_season or "")
    if str(league or "").lower() in ("nba", "nhl") and len(raw_log_season) == 8:
        raw_log_season = raw_log_season[-4:]
    try:
        return int(raw_log_season) == stats_year
    except ValueError:
        return False

@router.get("/api/player/{player_id}")
def player_profile(
    player_id: int,
    league: Optional[str] = None,
    season: Optional[int] = None,
):
    """Aggregate for the player page: header + recent game logs + per-stat
    projections + current props on this player. (Advanced metrics stay at
    /api/player/{id}/stats; this is the page-level rollup.)"""
    import json as _json
    with closing(__db_pkg()) as con:
        player_columns = {
            row[1] for row in con.execute("PRAGMA table_info(players)").fetchall()
        }
        injury_select = (
            ", injury_status" if "injury_status" in player_columns
            else ", NULL AS injury_status"
        )
        news_date_select = (
            ", last_news_date" if "last_news_date" in player_columns
            else ", NULL AS last_news_date"
        )
        position_group_select = (
            ", position_group" if "position_group" in player_columns
            else ", NULL AS position_group"
        )
        p = con.execute(
            f"SELECT id, name, team, league, position{position_group_select}"
            f"{injury_select}{news_date_select} "
            "FROM players WHERE id=?",
            (player_id,),
        ).fetchone()
        if not p:
            raise HTTPException(404, "Player not found")
        identity_league = str(p["league"] or "").lower()
        requested_league = str(league or "").strip().lower() or None

        # One durable player identity can have appearances in several competition
        # keys (MLS, Leagues Cup, CCC) and seasons. Publish those choices rather
        # than silently mixing all rows with the same player_id and year.
        context_rows = con.execute(
            """SELECT LOWER(league) AS league, season, COUNT(*) AS games
               FROM player_game_logs
               WHERE player_id=? AND league IS NOT NULL AND TRIM(league)<>''
                 AND season IS NOT NULL
               GROUP BY LOWER(league), season
               ORDER BY season DESC, LOWER(league)""",
            (player_id,),
        ).fetchall()
        log_contexts = [
            {"league": row["league"], "season": row["season"], "games": row["games"]}
            for row in context_rows
        ]

        # D/ST weekly rows deliberately live outside player_game_logs. They still
        # participate in the same year selector contract.
        is_dst = (
            identity_league == "nfl"
            and str(p["position"] or "").upper() in _DST_POSITIONS
        )
        if is_dst and not log_contexts:
            try:
                dst_contexts = con.execute(
                    """SELECT season, COUNT(*) AS games FROM nfl_dst_stats
                       WHERE player_id=? AND season IS NOT NULL
                       GROUP BY season ORDER BY season DESC""",
                    (player_id,),
                ).fetchall()
                log_contexts = [
                    {"league": "nfl", "season": row["season"], "games": row["games"]}
                    for row in dst_contexts
                ]
            except sqlite3.OperationalError:
                pass

        context_leagues = {row["league"] for row in log_contexts}
        if requested_league and requested_league not in context_leagues:
            raise HTTPException(400, "No game logs for selected league")
        selected_league = requested_league
        if selected_league is None and log_contexts:
            selected_league = (
                identity_league if identity_league in context_leagues
                else log_contexts[0]["league"]
            )
        if selected_league is None:
            selected_league = identity_league

        available_seasons = [
            row["season"] for row in log_contexts
            if row["league"] == selected_league
        ]
        if season is not None and season not in available_seasons:
            raise HTTPException(400, "No game logs for selected season")
        selected_season = season if season is not None else (
            max(available_seasons) if available_seasons else None
        )
        dst_logs = None
        published_fantasy = {}
        if is_dst and selected_league == "nfl" and selected_season is not None:
            _, dst_logs = _dst_game_logs(con, player_id, selected_season)
        logs = []
        postseason_logs = []
        preseason_logs = []
        nfl_schedule_games = []
        postseason_games = 0
        preseason_games = 0
        regular_season_games = 0
        if selected_season is not None:
            reg_filter, _ = _reg_season_game_filter(con, selected_league)
            if dst_logs is None:
                logs = con.execute(
                    f"""SELECT stats, game_date, opponent, home_away, game_no
                       FROM player_game_logs
                       WHERE player_id=? AND league=? AND season=?
                       {reg_filter}
                       ORDER BY COALESCE(game_date,'') DESC,
                                CAST(game_no AS INTEGER) DESC LIMIT 25""",
                    (player_id, selected_league, selected_season),
                ).fetchall()
            # COUNT, not len(logs). `logs` is LIMIT 25 — a page of recent games, not
            # the season — and `regular_season_games` renders on the player page as
            # "2026 · N games". For NFL's 17-game season the two agreed and the bug
            # was unreachable; NHL plays 82, so the header read "2026 · 25 games" for
            # a player who missed nothing. A page size is not a measurement.
            regular_season_games = con.execute(
                f"""SELECT COUNT(*) FROM player_game_logs
                   WHERE player_id=? AND league=? AND season=? {reg_filter}""",
                (player_id, selected_league, selected_season)).fetchone()[0]
            # Count postseason games separately (ESPN: separate containers)
            log_columns = {
                row[1]
                for row in con.execute(
                    "PRAGMA table_info(player_game_logs)"
                ).fetchall()
            }
            # Any league whose rows carry a phase, not just NFL. NHL logs gained one
            # on 2026-08-02; leaving this NFL-only would render a player who played
            # 22 playoff games as having played none — absence as a claim about the
            # player, in a season where we can prove we looked.
            #
            # The legacy fallback stays NFL-ONLY and that is load-bearing, not
            # tidiness: it reads `game_no` as a week number, and NHL's game_no is a
            # game id ("2025020001"), so `CAST(game_no AS INTEGER) >= 19` is true of
            # every NHL row ever written. Applied league-wide it would file an entire
            # unphased league as postseason.
            if "game_type" in log_columns:
                legacy_postseason = (
                    """OR (
                         game_type IS NULL
                         AND CAST(game_no AS INTEGER) >= 19
                       )"""
                    if "game_no" in log_columns and selected_league == "nfl"
                    else ""
                )
                post_row = con.execute(
                    f"""SELECT COUNT(*) FROM player_game_logs
                       WHERE player_id=? AND season=?
                         AND league=?
                         AND (
                           (game_type IS NOT NULL AND game_type NOT IN ('REG','PRE'))
                           {legacy_postseason}
                         )""",
                    (player_id, selected_season, selected_league)).fetchone()
                postseason_games = post_row[0] if post_row else 0
                postseason_logs = con.execute(
                    f"""SELECT stats, game_date, opponent, home_away, game_no
                       FROM player_game_logs WHERE player_id=? AND season=? AND league=?
                         AND (
                           (game_type IS NOT NULL AND game_type NOT IN ('REG','PRE'))
                           {legacy_postseason}
                         )
                       ORDER BY COALESCE(game_date,'') DESC,
                                CAST(game_no AS INTEGER) DESC LIMIT 25""",
                    (player_id, selected_season, selected_league),
                ).fetchall()
                preseason_logs = con.execute(
                    """SELECT stats, game_date, opponent, home_away, game_no
                       FROM player_game_logs
                       WHERE player_id=? AND season=? AND league=? AND game_type='PRE'
                       ORDER BY COALESCE(game_date,'') DESC,
                                CAST(game_no AS INTEGER) DESC LIMIT 25""",
                    (player_id, selected_season, selected_league),
                ).fetchall()
                # Same LIMIT-25 trap as regular_season_games above.
                preseason_games = con.execute(
                    """SELECT COUNT(*) FROM player_game_logs
                       WHERE player_id=? AND season=? AND league=? AND game_type='PRE'""",
                    (player_id, selected_season, selected_league)).fetchone()[0]

            # NFL game logs currently leave home_away null. Resolve venue
            # and opponent from the published schedule rather than
            # guessing from row order or treating every game as away.
            #
            # NFL-ONLY, and explicitly so now that the phase block above is not.
            # `nfl_schedule` is matched on bare team codes, and CHI, DAL, LA and
            # friends name a team in both leagues — run this for an NHL player and
            # it silently attaches an NFL schedule to them.
            # A defense's rows do not live in `player_game_logs`, so every query
            # above found nothing for it. Substitute the published weekly log here,
            # before the schedule block, so the defense gets opponent and venue from
            # exactly the same resolution every other NFL player gets.
            if dst_logs is not None:
                logs = dst_logs
                regular_season_games = len(dst_logs)

            # ESPN's own scored total per week, for the two positions nflverse does
            # not score. Loaded once here rather than per row. Absent table or absent
            # season leaves the log's existing value alone -- this overlays a better
            # number where one is published, it does not blank out anything.
            if (
                selected_league == "nfl"
                and str(p["position"] or "").upper() in _PUBLISHED_FANTASY_POSITIONS
            ):
                try:
                    published_fantasy = {
                        int(row["week"]): row["points"]
                        for row in con.execute(
                            """SELECT week, points FROM nfl_published_fantasy_points
                               WHERE player_id=? AND season=?""",
                            (player_id, selected_season),
                        )
                    }
                except sqlite3.OperationalError:
                    published_fantasy = {}

            if selected_league == "nfl":
                schedule_columns = {
                    row[1]
                    for row in con.execute(
                        "PRAGMA table_info(nfl_schedule)"
                    ).fetchall()
                }
                required_schedule = {
                    "season", "week", "game_type", "home_team", "away_team"
                }
                schedule_team = p["team"]
                if "team" in log_columns:
                    primary_team = con.execute(
                        f"""SELECT team, COUNT(*) AS games,
                                   MAX(CAST(game_no AS INTEGER)) AS latest_week
                            FROM player_game_logs
                            WHERE player_id=? AND league=? AND season=? AND team IS NOT NULL
                              {reg_filter}
                            GROUP BY team
                            ORDER BY games DESC, latest_week DESC, team DESC
                            LIMIT 1""",
                        (player_id, selected_league, selected_season),
                    ).fetchone()
                    if primary_team and primary_team["team"]:
                        schedule_team = primary_team["team"]
                if schedule_team and required_schedule.issubset(schedule_columns):
                    schedule_rows = con.execute(
                        """SELECT week, game_type, home_team, away_team
                           FROM nfl_schedule
                           WHERE season=? AND (home_team=? OR away_team=?)
                           ORDER BY week DESC, game_type DESC""",
                        (selected_season, schedule_team, schedule_team),
                    ).fetchall()
                    for schedule_row in schedule_rows:
                        game_type = str(schedule_row["game_type"] or "").upper()
                        if game_type == "REG":
                            phase = "regular"
                        elif game_type == "PRE":
                            phase = "preseason"
                        elif game_type:
                            phase = "postseason"
                        else:
                            continue
                        is_home = schedule_row["home_team"] == schedule_team
                        nfl_schedule_games.append({
                            "week": schedule_row["week"],
                            "phase": phase,
                            "opponent": (
                                schedule_row["away_team"]
                                if is_home else schedule_row["home_team"]
                            ),
                            "home": is_home,
                        })
        rank_context = (
            nfl_player_rank_context(
                con, p["id"], p["position"], selected_season
            )
            if selected_league == "nfl" else {"season": None, "games": None, "stats": {}}
        )

        props = con.execute(
            """SELECT market, side, line, MAX(captured_at) ca FROM props
               WHERE player_id=? GROUP BY market, side ORDER BY ca DESC LIMIT 30""",
            (player_id,)).fetchall()

    def serialize_game_logs(rows, fantasy_by_week=None):
        serialized = []
        for row in rows:
            stats = _json.loads(row["stats"])
            if selected_league == "nfl":
                stats = {_NFL_KEY_NORMALIZE.get(k, k): v for k, v in stats.items()}
                # Misc TD, from the same definition the draft overlay renders.
                stats = _with_derived(stats)
            # Kickers and defenses: the fantasy points come from ESPN, who scored
            # them, rather than from a second implementation of ESPN's rules here.
            # nflverse's `fantasy_points` is defined over passing/rushing/receiving
            # only, so every kicker in `player_game_logs` carries a literal 0 --
            # Aubrey kicked 4 field goals in week 15 and his line read 0.0.
            if fantasy_by_week:
                week = row["game_no"]
                try:
                    published = fantasy_by_week.get(int(week))
                except (TypeError, ValueError):
                    published = None
                if published is not None:
                    # A defense catches no passes, so PPR and standard are the
                    # same number, and a kicker's PPR is likewise his score.
                    stats["fpts"] = published
                    stats["fpts_ppr"] = published
            serialized.append({
                "date": row["game_date"],
                "opponent": row["opponent"],
                "home": (
                    row["home_away"] == "home"
                    if row["home_away"] else None
                ),
                "game_no": row["game_no"],
                "stats": stats,
            })
        return serialized

    series = {}
    recent = serialize_game_logs(logs, published_fantasy)
    postseason_recent = serialize_game_logs(postseason_logs, published_fantasy)
    preseason_recent = serialize_game_logs(preseason_logs, published_fantasy)
    for game in recent:
        s = game["stats"]
        for k, v in s.items():
            if isinstance(v, (int, float)):
                series.setdefault(k, []).append(v)
    projections = {}
    for k, vals in series.items():
        if selected_league == "nfl" and k not in _NFL_PROJECTION_STATS:
            continue
        pr = proj_mod.project_stat(vals)
        if not pr:
            continue
        if selected_league == "nfl" and not pr.get("season_avg") and not pr.get("projection"):
            continue
        projections[k] = pr

    season_stats = __season_stats_for_profile_pkg(p["id"], p["name"], identity_league)
    if season_stats is not None and selected_season is not None:
        if not _same_published_season(
            identity_league, selected_season, season_stats.get("window")
        ):
            season_stats = None
    return {
        "id": p["id"], "name": p["name"], "team": p["team"],
        "league": identity_league, "selected_league": selected_league,
        "position": p["position"], "position_group": p["position_group"],
        "season": selected_season, "log_contexts": log_contexts,
        "injury_status": p["injury_status"],
        "last_news_date": p["last_news_date"],
        "regular_season_games": regular_season_games,
        "postseason_games": postseason_games,
        "preseason_games": preseason_games,
        "recent_games": recent,
        "postseason_recent_games": postseason_recent,
        "preseason_recent_games": preseason_recent,
        "nfl_schedule_games": nfl_schedule_games,
        "projections": projections,
        "stat_ranks": rank_context["stats"],
        "stat_rank_season": rank_context["season"],
        "stat_rank_games": rank_context["games"],
        "props": [{"market": _base_market(x["market"]), "side": x["side"], "line": x["line"]} for x in props],
        "season_stats": season_stats,
        "coverage": {
            "game_logs": bool(logs),
            "props": bool(props),
            "season_stats": season_stats is not None,
        },
        "data_status": "ready" if (logs or props or season_stats) else "unavailable",
    }
