"""NFL relay-prop settlement from ESPN's published player boxscore."""
import datetime as dt

from settlement.boxscore_extract import _find_player_compound_stat, _find_player_stat
from settlement.grading import _grade_actual


_DIRECT = {
    "passing_yards": ("passing", "YDS"),
    "passing_touchdowns": ("passing", "TD"),
    "interceptions_thrown": ("passing", "INT"),
    "rushing_yards": ("rushing", "YDS"),
    "receiving_yards": ("receiving", "YDS"),
    "receptions": ("receiving", "REC"),
    "sacks": ("defensive", "SACKS"),
    "kicking_points": ("kicking", "PTS"),
}
_COMPOUND = {
    "passing_rushing_yards": (["passing", "rushing"], ["YDS", "YDS"]),
    "rushing_receiving_yards": (["rushing", "receiving"], ["YDS", "YDS"]),
    "rushing_receiving_touchdowns": (["rushing", "receiving"], ["TD", "TD"]),
    # A player-scored touchdown may appear in any published scoring category.
    "total_touchdowns": (
        ["rushing", "receiving", "defensive", "interceptions", "kickReturns", "puntReturns"],
        ["TD", "TD", "TD", "TD", "TD", "TD"],
    ),
}
_KICKING_MADE = {"field_goals_made": "FG", "extra_points_made": "XP"}


def _kicking_made(box, prop, label):
    """Read ESPN's ``made/attempted`` kick field as the published made count."""
    # `_find_player_stat` intentionally refuses strings such as 2/2.  Locate
    # exactly the same athlete/group and parse only the numeric made component.
    wanted = str(prop["espn_id"] or "")
    if not wanted:
        return None
    for team in box.get("players") or []:
        for group in team.get("statistics") or []:
            if (group.get("name") or "").lower() != "kicking":
                continue
            labels = group.get("labels") or []
            if label not in labels:
                continue
            idx = labels.index(label)
            matches = [entry for entry in group.get("athletes") or []
                       if str((entry.get("athlete") or {}).get("id") or "") == wanted]
            if len(matches) != 1:
                return None
            stats = matches[0].get("stats") or []
            if idx >= len(stats):
                return None
            text = str(stats[idx] or "")
            made, sep, attempted = text.partition("/")
            if not sep or not made.isdigit() or not attempted.isdigit():
                return None
            return float(made)
    return None


def _nfl_actual(box, prop):
    market = str(prop["market"] or "")
    direct = _DIRECT.get(market)
    if direct:
        return _find_player_stat(box, prop["player_name"], prop["player_team"], *direct,
                                 espn_id=prop["espn_id"])
    compound = _COMPOUND.get(market)
    if compound:
        wanted = str(prop["espn_id"] or "")
        present = any(
            str((entry.get("athlete") or {}).get("id") or "") == wanted
            for team in box.get("players") or []
            for group in team.get("statistics") or []
            for entry in group.get("athletes") or []
        )
        if not wanted or not present:
            return None
        # ESPN omits a player from unrelated stat groups; that is a published
        # zero for a cross-category sum, not an unknown result.
        return sum(_find_player_stat(box, prop["player_name"], prop["player_team"], category, key,
                                     espn_id=wanted) or 0.0
                   for category, key in zip(*compound))
    label = _KICKING_MADE.get(market)
    return _kicking_made(box, prop, label) if label else None


def _settle_nfl_props(con, props, box):
    settled = unmappable = pending = errors = 0
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    supported = set(_DIRECT) | set(_COMPOUND) | set(_KICKING_MADE)
    for prop in props:
        if prop["market"] not in supported:
            unmappable += 1
            continue
        actual = _nfl_actual(box, prop)
        if actual is None:
            pending += 1
            continue
        try:
            if _grade_actual(con, prop, actual, now): settled += 1
            else: unmappable += 1
        except Exception:
            errors += 1
    con.commit()
    return {"settled": settled, "void": 0, "unmappable": unmappable,
            "pending": pending, "errors": errors}
