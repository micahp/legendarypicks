#!/usr/bin/env python3
"""Settle soccer props from durable provider-separated appearance rows."""
import datetime as dt
import json
import sqlite3
import unicodedata

from settlement.grading import _grade_actual
from settlement.market_mapping import MARKET_ALIASES, normalize_market


# These keys name the durable ESPN JSON vocabulary in player_game_logs_all.
_MLS_ROSTER_MARKETS = {
    "goals": "goals",
    "assists": "assists",
    "shots": "shots",
    "shots_on_target": "sot",
    "sot": "sot",
    "fouls_committed": "fouls_committed",
    "fouls_suffered": "fouls_suffered",
    "saves": "saves",
    "shots_faced": "shots_faced",
    "goals_allowed": "goals_conceded",
    "offsides": "offsides",
}

_MLS_ROSTER_SUM_MARKETS = {
    "card_shown": ("yellow_cards", "red_cards"),
    "goal_or_assist": ("goals", "assists"),
}

_MLS_EVENT_MARKETS = {"first_goal_scorer"}

_MLS_DEEP_LOG_MARKETS = {
    "tackles": "tackles",
    "clearances": "clearances",
    "crosses": "crosses",
    # FotMob publishes accurate/completed passes, not attempts. This exact key
    # can therefore be answered only by a provider row that really carries it.
    "passes_attempted": "passes_attempted",
    "passes": "passes",
    "shots_assisted": "shots_assisted",
    "chances_created": "chances_created",
    "dribbles": "dribbles",
    "interceptions": "interceptions",
}

# A different stored spelling is not a different statistic. ESPN remains first
# because player_id is keyed to its identity spine; FotMob is the fallback.
_FOTMOB_KEYS = {
    "sot": "shots_on_target",
    "shots_assisted": "chances_created",
}

_ROTOWIRE_KEYS = {
    "shots_assisted": "chances_created",
}


def _soccer_name(text: str) -> str:
    """Accent-fold an exact soccer roster name without substring matching."""
    ascii_text = unicodedata.normalize("NFKD", str(text or "")).encode(
        "ascii", "ignore").decode("ascii")
    return " ".join("".join(
        char for char in ascii_text.lower()
        if char.isalnum() or char.isspace()).split())


def _json_object(raw):
    try:
        value = json.loads(raw or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _stored_appearance(con: sqlite3.Connection, game, player_id,
                       has_rotowire=False):
    """Return one exact/date-safe appearance, or None when identity is unclear."""
    rotowire = "rotowire_stats" if has_rotowire else "NULL AS rotowire_stats"
    # ESPN's event id is the durable identity.  Do not pre-filter it by date:
    # late North American matches can have a local prop date and a next-day UTC
    # competition date (the two 2026-08-25 Leagues Cup quarterfinals exposed
    # this by hiding every exact event row).
    exact = con.execute(
        f"SELECT game_id, espn_stats, fotmob_stats, {rotowire} "
        "FROM player_game_logs_all "
        "WHERE player_id=? AND league=? AND game_id=? AND espn_stats IS NOT NULL",
        (player_id, game["league"], str(game["espn_event_id"] or "")),
    ).fetchall()
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None

    # A FotMob-only row has a provider-specific game id. Date+player is the
    # cross-provider key used by the view, but it is safe only when unique.
    rows = con.execute(
        f"SELECT game_id, espn_stats, fotmob_stats, {rotowire} "
        "FROM player_game_logs_all WHERE player_id=? AND league=? AND game_date=?",
        (player_id, game["league"], game["date"]),
    ).fetchall()
    fotmob_only = [row for row in rows if row["espn_stats"] is None]
    return fotmob_only[0] if len(fotmob_only) == 1 else None


def _stored_actual(row, espn_keys, fotmob_keys=None, rotowire_keys=None):
    """Prefer complete ESPN, FotMob, then RotoWire values for one appearance."""
    if row is None:
        return None
    fotmob_keys = fotmob_keys or espn_keys
    rotowire_keys = rotowire_keys or espn_keys
    for raw, keys in ((row["espn_stats"], espn_keys),
                      (row["fotmob_stats"], fotmob_keys),
                      (row["rotowire_stats"], rotowire_keys)):
        stats = _json_object(raw)
        values = [stats.get(key) for key in keys]
        if any(value in (None, "") for value in values):
            continue
        try:
            return float(sum(float(value) for value in values))
        except (TypeError, ValueError):
            continue
    return None


def _summary_first_goal_actual(summary, prop):
    """Use the live event fallback without turning a non-participant into zero."""
    from ingest_soccer_logs import _first_goal_scorer

    roster_rows = [
        row for group in summary.get("rosters") or []
        for row in group.get("roster") or []
    ]
    if prop["espn_id"]:
        matches = [row for row in roster_rows
                   if str((row.get("athlete") or {}).get("id") or "")
                   == str(prop["espn_id"])]
    else:
        matches = [row for row in roster_rows
                   if _soccer_name((row.get("athlete") or {}).get("displayName"))
                   == _soccer_name(prop["player_name"])]
    if len(matches) != 1 or not prop["espn_id"]:
        return None

    first_scorer, goal_events_published = _first_goal_scorer(summary)
    if not goal_events_published:
        return None
    return 1.0 if str(prop["espn_id"]) == str(first_scorer or "") else 0.0

def _settle_mls_props(con: sqlite3.Connection, game, props: list,
                      summary_loader=None) -> dict:
    """Grade soccer props DB-first, loading a summary only for missing event data."""
    settled = 0
    void = 0
    unmappable = 0
    pending = 0
    errors = 0
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    summary = None
    summary_attempted = False
    summary_failed = False
    view_columns = {row[1] for row in con.execute(
        "PRAGMA table_info(player_game_logs_all)")}
    has_rotowire = "rotowire_stats" in view_columns

    def load_summary():
        nonlocal summary, summary_attempted, summary_failed, errors
        if not summary_attempted:
            summary_attempted = True
            try:
                summary = summary_loader() if summary_loader else None
            except Exception:
                summary_failed = True
                errors += 1
        return summary

    for prop in props:
        canonical = normalize_market(prop["market"])
        canonical = MARKET_ALIASES.get(canonical, canonical)
        stat_key = _MLS_ROSTER_MARKETS.get(canonical)
        sum_keys = _MLS_ROSTER_SUM_MARKETS.get(canonical)
        deep_key = _MLS_DEEP_LOG_MARKETS.get(canonical)
        if (not stat_key and not sum_keys and not deep_key
                and canonical not in _MLS_EVENT_MARKETS):
            unmappable += 1
            continue

        appearance = _stored_appearance(
            con, game, prop["player_id"], has_rotowire=has_rotowire)
        if (appearance is not None
                and _json_object(appearance["espn_stats"]).get("did_not_play") == 1):
            try:
                con.execute(
                    "INSERT INTO prop_results(prop_id, actual_value, hit, settled_at) "
                    "VALUES (?,NULL,NULL,?)",
                    (prop["id"], now))
                void += 1
            except sqlite3.Error:
                errors += 1
            continue
        if canonical in _MLS_EVENT_MARKETS:
            actual = _stored_actual(appearance, ("first_goal",))
            if actual is None:
                published = load_summary()
                actual = (_summary_first_goal_actual(published, prop)
                          if published else None)
        elif sum_keys:
            actual = _stored_actual(appearance, sum_keys)
        else:
            key = deep_key or stat_key
            fotmob_key = _FOTMOB_KEYS.get(key, key)
            rotowire_key = _ROTOWIRE_KEYS.get(key, key)
            actual = _stored_actual(
                appearance, (key,), (fotmob_key,), (rotowire_key,))

        if actual is None:
            pending += 1
            continue
        try:
            if _grade_actual(con, prop, actual, now):
                settled += 1
            else:
                unmappable += 1
        except Exception:
            errors += 1

    con.commit()
    result = {"settled": settled, "void": void, "unmappable": unmappable,
              "pending": pending, "errors": errors}
    if summary_failed:
        result["error_msg"] = "soccer summary fallback failed"
    return result
