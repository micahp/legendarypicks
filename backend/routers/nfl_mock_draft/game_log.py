"""Per-game log endpoint and helpers for the NFL mock-draft package."""

import json

from fastapi import Query

from . import router
from .constants import (
    _CONTRACT,
    _CURRENT_SEASON,
    _REG_SEASON_TEAM_GAMES,
)
from .db import _conn
from .helpers import _json
from ..nfl_offseason import _availability_aggregates, _dst_aggregates, _table_columns

# Which per-game fields matter, by position, as ESPN-style tabs. Deliberately
# narrow: the log rows carry ~52 keys and a research table that shows all of
# them shows none of them.
#
# The tab layout is the fix for the sideways scroll -- not a wider box and not
# fewer stats. Wk, Opp and the points anchor are rendered by the component for
# every tab, so they must NOT appear in a tab's fields; a tab's fields are the
# only columns that change when it is selected, and no tab may declare more
# than 5 of them (Wk + Opp + PPR + 5 = 8 columns, the widest the 520px card
# fits). The published `fields` list stays the ordered union of the tab
# fields, so the row-building below is unchanged.
#
# aDOT and Separation moved OUT to the player detail's advanced block. They are
# Next Gen scouting inputs, not box-score facts, and they were costing two of
# the eight columns on the surface where a fantasy manager is asking "what did
# he do". Snap %, target share and expected points stay: those are the three
# that answer a question the raw box score cannot.
_LOG_FIELDS = {
    "QB": [
        {"id": "passing", "label": "Passing",
         "fields": ["cmp", "att", "pass_yds", "pass_td", "intc"]},
        {"id": "rushing", "label": "Rushing",
         "fields": ["carries", "rush_yds", "rush_td"]},
        {"id": "misc", "label": "Misc",
         "fields": ["sacks_taken", "fum_lost", "misc_td"]},
        {"id": "usage", "label": "Usage",
         "fields": ["off_pct", "xfpts_ppr"]},
    ],
    "RB": [
        {"id": "rushing", "label": "Rushing",
         "fields": ["carries", "rush_yds", "rush_td"]},
        {"id": "receiving", "label": "Receiving",
         "fields": ["targets", "rec", "rec_yds", "rec_td"]},
        {"id": "misc", "label": "Misc",
         "fields": ["fum_lost", "misc_td"]},
        {"id": "usage", "label": "Usage",
         "fields": ["off_pct", "target_share", "xfpts_ppr"]},
    ],
    "WR": [
        {"id": "receiving", "label": "Receiving",
         "fields": ["targets", "rec", "rec_yds", "rec_td"]},
        {"id": "rushing", "label": "Rushing",
         "fields": ["carries", "rush_yds", "rush_td"]},
        {"id": "misc", "label": "Misc",
         "fields": ["fum_lost", "misc_td"]},
        {"id": "usage", "label": "Usage",
         "fields": ["off_pct", "target_share", "xfpts_ppr"]},
    ],
    # Raw counts only. Kicker fantasy points are computed from distance buckets
    # in _pk_aggregates; recomputing them here would be a second implementation
    # of the same number, which is how the board and the pool ended up printing
    # different figures for the same player. The season rate already ships on
    # the overview tab -- the log's job is what he actually kicked. PK has no
    # PPR field at all, so its anchor is null and the component renders no
    # points column.
    "PK": [
        {"id": "kicking", "label": "Kicking",
         "fields": ["fg_made", "fg_att", "fg_long", "pat_made", "pat_att"]},
    ],
}
# D/ST have no player_game_logs rows at all -- their week rows live in
# nfl_dst_stats. Read that table rather than reporting 17 weeks of absence for a
# defense that played every one of them. D/ST anchor on their own fantasy_pts,
# not fpts_ppr, which no defense has.
_DST_LOG_FIELDS = [
    {"id": "defense", "label": "Defense",
     "fields": ["sacks", "interceptions", "fumble_rec", "safeties",
                "points_allowed"]},
]
_LOG_FIELDS["TE"] = _LOG_FIELDS["WR"]
_LOG_FIELDS["FB"] = _LOG_FIELDS["RB"]

# Misc TD is computed, so it is defined once in nfl_stat_derivations and imported
# by every surface that renders it -- the player page shows the same column.
from nfl_stat_derivations import DERIVED as _DERIVED  # noqa: E402


@router.get("/api/nfl/draft/player/{player_id}/game-log")
def player_game_log(player_id: int):
    """Per-game log for the player overlay's research tab.

    Returns one entry per week the player's TEAM played -- not one per week he
    recorded a stat line. A log that lists only the games a player appeared in
    repeats the exact defect the availability work exists to fix: it makes a
    12-game season look like a full one, and it hides the weeks that are the
    most informative thing on the card.

    Weeks with no row are returned with `played: false` and null stats. Weeks
    absent from the team's schedule entirely (the bye) are simply not present,
    because a bye is not an absence.
    """
    connection = _conn()
    try:
        _pos_expr = (
            "COALESCE(na.position, p.position)"
            if "position" in _table_columns(connection, "nfl_adp")
            else "p.position"
        )
        player = connection.execute(
            f"""SELECT p.id, p.name, p.team,
                      {_pos_expr} AS position
                 FROM players p
                 LEFT JOIN nfl_adp na ON na.player_id = p.id AND na.season = ?
                WHERE p.id=? AND p.league='nfl'""",
            (_CURRENT_SEASON, player_id),
        ).fetchone()
        if player is None:
            return _json({"error": "Player not found"}, status=404)

        position = player["position"]

        # Reference season = the most recent season with logs, matching pool().
        row = connection.execute(
            "SELECT MAX(season) FROM player_game_logs WHERE league='nfl'"
        ).fetchone()
        season = (row[0] if row and row[0] else _CURRENT_SEASON - 1)

        availability = _availability_aggregates(connection, season)
        if position == "DEF":
            _dst_avail, dst_team_weeks = _dst_aggregates(connection, season)
            team_weeks = sorted(dst_team_weeks.get(player["team"], []))
        else:
            agg = availability.get(player_id) or {}
            team_weeks = sorted(agg.get("team_weeks", []))

        if position == "DEF":
            return _json(_dst_game_log(
                connection, player, player_id, season, team_weeks,
            ))

        tabs = _LOG_FIELDS.get(position, [])
        anchor = "fpts_ppr" if position in ("QB", "RB", "WR", "TE", "FB") else None
        fields = [f for tab in tabs for f in tab["fields"]]
        # The anchor column (PPR) is rendered by the component for every tab,
        # so it is deliberately absent from `fields` -- but the row must still
        # carry it, or the anchor cell would read as an empty dash each week.
        stat_fields = fields + ([anchor] if anchor else [])

        by_week = {}
        for log in connection.execute(
            """SELECT game_no, opponent, team, stats, game_type
                 FROM player_game_logs
                WHERE player_id=? AND season=? AND league='nfl'""",
            (player_id, season),
        ):
            # Playoff rows sit alongside regular-season rows (B10). The team's
            # week list is regular season, so they drop out on the join -- but
            # drop them explicitly rather than relying on that coincidence.
            if log["game_type"] and log["game_type"] != "REG":
                continue
            try:
                week = int(log["game_no"])
            except (TypeError, ValueError):
                continue
            try:
                stats = json.loads(log["stats"]) if log["stats"] else {}
            except (TypeError, ValueError):
                stats = {}
            by_week[week] = {
                "opponent": log["opponent"],
                "team": log["team"],
                "stats": {
                    f: (_DERIVED[f](stats) if f in _DERIVED else stats.get(f))
                    for f in stat_fields
                },
            }

        games = []
        for week in team_weeks:
            entry = by_week.get(week)
            games.append({
                "week": week,
                "played": entry is not None,
                "opponent": entry["opponent"] if entry else None,
                "team": entry["team"] if entry else None,
                "stats": entry["stats"] if entry else {f: None for f in stat_fields},
            })

        return _json({
            "contract": "nfl-player-game-log-v1",
            "player_id": player_id,
            "name": player["name"],
            "position": position,
            "reference_season": season,
            "anchor": anchor,
            "tabs": tabs,
            "fields": fields,
            "team_games": len(team_weeks),
            "games_played": sum(1 for g in games if g["played"]),
            "games": games,
        })
    finally:
        connection.close()


def _dst_game_log(connection, player, player_id, season, team_weeks):
    """Week rows for a team defense, read from nfl_dst_stats.

    Separate from the skill-position path because D/ST never appear in
    player_game_logs. Routing them through it reported every week of a
    17-week season as "did not play" for a defense that played all 17 --
    a fabricated absence, which is the same defect as a fabricated number.
    """
    tabs = _DST_LOG_FIELDS
    anchor = "fantasy_pts"
    columns = _table_columns(connection, "nfl_dst_stats")
    if not {"player_id", "season", "week"}.issubset(columns):
        return {
            "contract": "nfl-player-game-log-v1",
            "player_id": player_id,
            "name": player["name"],
            "position": "DEF",
            "reference_season": season,
            "anchor": anchor,
            "tabs": tabs,
            "fields": [f for tab in tabs for f in tab["fields"]],
            "team_games": len(team_weeks),
            "games_played": 0,
            "games": [],
            "unavailable": "per-week D/ST scoring is not loaded",
        }

    fields = [f for tab in tabs for f in tab["fields"] if f in columns]
    # Same rule as the skill-position path: the anchor column (Pts) is rendered
    # by the component, so it is not a tab field -- but the row carries it.
    stat_fields = fields + ([anchor] if anchor in columns else [])
    by_week = {}
    for row in connection.execute(
        "SELECT * FROM nfl_dst_stats WHERE player_id=? AND season=?",
        (player_id, season),
    ):
        try:
            by_week[int(row["week"])] = {f: row[f] for f in stat_fields}
        except (TypeError, ValueError):
            continue

    games = []
    for week in team_weeks:
        stats = by_week.get(week)
        games.append({
            "week": week,
            "played": stats is not None,
            "opponent": None,
            "team": player["team"],
            "stats": stats if stats else {f: None for f in stat_fields},
        })

    return {
        "contract": "nfl-player-game-log-v1",
        "player_id": player_id,
        "name": player["name"],
        "position": "DEF",
        "reference_season": season,
        "anchor": anchor,
        "tabs": tabs,
        "fields": fields,
        "team_games": len(team_weeks),
        "games_played": sum(1 for g in games if g["played"]),
        "games": games,
    }