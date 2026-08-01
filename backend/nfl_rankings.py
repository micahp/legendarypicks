"""Canonical NFL regular-season rank-card readers.

The rank card is a view over the published ``player_stats`` season population.
It must never fall back to legacy weekly rows or silently cross seasons.
"""

NFL_REGULAR_SEASON_SOURCE = "nflverse_regular_season"

NFL_RANK_STATS = {
    "QB": (
        ("pass_yds_g", "Pass Yds/G"),
        ("pass_td", "Pass TD"),
        ("interceptions", "INT"),
        ("cmp_g", "Cmp/G"),
    ),
    "RB": (
        ("rush_yds_g", "Rush Yds/G"),
        ("carries_g", "Carries/G"),
        ("rec_yds_g", "Rec Yds/G"),
        ("fantasy_ppr_g", "PPR/G"),
    ),
    "WR": (
        ("rec_yds_g", "Rec Yds/G"),
        ("targets", "Targets"),
        ("receptions", "Receptions"),
        ("fantasy_ppr_g", "PPR/G"),
    ),
    "TE": (
        ("rec_yds_g", "Rec Yds/G"),
        ("targets", "Targets"),
        ("receptions", "Receptions"),
        ("fantasy_ppr_g", "PPR/G"),
    ),
}

_RANK_ASC = frozenset(("interceptions",))


def nfl_player_rank_context(connection, player_id, position, season):
    """Return one player's phase-correct rank card and sample metadata."""
    rank_stats = NFL_RANK_STATS.get(str(position or "").strip().upper())
    if not rank_stats or season is None:
        return {"season": season, "games": None, "stats": {}}

    player_row = connection.execute(
        """SELECT games, pass_yds_g, pass_td, interceptions, cmp_g,
                  rush_yds_g, carries_g, rec_yds_g, targets, receptions,
                  fantasy_ppr_g
             FROM player_stats
            WHERE player_id=? AND league='nfl' AND season=?
              AND stat_type='season' AND source=?""",
        (int(player_id), int(season), NFL_REGULAR_SEASON_SOURCE),
    ).fetchone()
    if player_row is None:
        return {"season": season, "games": None, "stats": {}}

    results = {}
    for stat_col, stat_label in rank_stats:
        value = player_row[stat_col]
        if value is None:
            continue
        comparison = "<" if stat_col in _RANK_ASC else ">"
        rank = connection.execute(
            f"""SELECT COUNT(*) + 1
                  FROM player_stats
                 WHERE league='nfl' AND season=? AND stat_type='season'
                   AND source=? AND {stat_col} IS NOT NULL
                   AND {stat_col} {comparison} ?""",
            (int(season), NFL_REGULAR_SEASON_SOURCE, value),
        ).fetchone()[0]
        results[stat_col] = {
            "value": float(value),
            "rank": int(rank),
            "label": stat_label,
        }
    return {
        "season": int(season),
        "games": int(player_row["games"]) if player_row["games"] is not None else None,
        "stats": results,
    }


def nfl_player_stat_ranks_batch(connection, season):
    """Return competition ranks for the complete canonical season population."""
    if season is None:
        return {}
    stat_labels = {
        column: label
        for position_stats in NFL_RANK_STATS.values()
        for column, label in position_stats
    }
    by_player = {}
    for stat_col, label in stat_labels.items():
        order = "ASC" if stat_col in _RANK_ASC else "DESC"
        rows = connection.execute(
            f"""SELECT player_id, {stat_col} AS value,
                       RANK() OVER (ORDER BY {stat_col} {order}) AS rank
                  FROM player_stats
                 WHERE league='nfl' AND season=? AND stat_type='season'
                   AND source=? AND {stat_col} IS NOT NULL""",
            (int(season), NFL_REGULAR_SEASON_SOURCE),
        )
        for row in rows:
            by_player.setdefault(row["player_id"], {})[stat_col] = {
                "value": float(row["value"]),
                "rank": int(row["rank"]),
                "label": label,
            }
    return by_player
