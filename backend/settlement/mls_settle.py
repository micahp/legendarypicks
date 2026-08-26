#!/usr/bin/env python3
"""mls_settle.py — settle MLS props from the summary roster-stat surface."""
import datetime as dt
import json
import sqlite3
import unicodedata
from typing import Optional

from settlement.market_mapping import normalize_market, MARKET_ALIASES
from settlement.grading import _grade_actual


# ESPN's own field names on `rosters[].roster[].stats`, verified against a real
# completed Leagues Cup summary (event 401863625) rather than taken from docs.
# That surface publishes fourteen fields; these are the ones a priced market
# asks about. Measured 2026-08-25 across 1,640 lcup logs: every one of these is
# present on 1,640 of 1,640 rows.
_MLS_ROSTER_MARKETS = {
    "goals": "totalGoals",
    "assists": "goalAssists",
    "shots": "totalShots",
    "shots_on_target": "shotsOnTarget",
    "sot": "shotsOnTarget",
    "fouls_committed": "foulsCommitted",
    "fouls_suffered": "foulsSuffered",
    "saves": "saves",
    "shots_faced": "shotsFaced",
    "goals_allowed": "goalsConceded",
    "offsides": "offsides",
}

# Priced markets ESPN does NOT publish for these competitions. Measured at 0 of
# 1,640 rows: tackles, clearances, crosses, dribbles, passes attempted. They are
# left out deliberately so they count as `unmappable` and stay ungraded, rather
# than being mapped to a near-miss field and graded WRONG. `sot` and
# `shots_on_target` both appear above because the props table carries both keys
# for the same stat -- one stat, two vocabularies, which is its own defect.

# Markets whose actual is the SUM of published stats rather than one of them.
_MLS_ROSTER_SUM_MARKETS = {
    "card_shown": ("yellowCards", "redCards"),
    "goal_or_assist": ("totalGoals", "goalAssists"),
}

# Markets that no box score can answer, because they are about ORDER.
_MLS_EVENT_MARKETS = {"first_goal_scorer"}

# Markets the SUMMARY does not carry but the CORE api does, stored by
# `ingest_soccer_logs --deep` into player_game_logs. Settled from that stored
# row rather than a second live fetch: the deep pass costs about one request per
# athlete, and settlement must not pay that per prop.
#
# A prop whose match has no deep row stays PENDING, never zero. The distinction
# matters: 0 tackles is a real result a player can have, so writing 0 because we
# did not look would grade a bet on a number nobody measured.
_MLS_DEEP_LOG_MARKETS = {
    "tackles": "tackles",
    "clearances": "clearances",
    "crosses": "crosses",
    "passes_attempted": "passes_attempted",
    "passes": "passes",
    "shots_assisted": "shots_assisted",
}


def _soccer_name(text: str) -> str:
    """Accent-fold an exact soccer roster name without using substring matching."""
    ascii_text = unicodedata.normalize("NFKD", str(text or "")).encode(
        "ascii", "ignore").decode("ascii")
    return " ".join("".join(
        char for char in ascii_text.lower()
        if char.isalnum() or char.isspace()).split())


def _settle_mls_props(con: sqlite3.Connection, props: list, summary: dict) -> dict:
    """Grade MLS goals/assists from the summary roster-stat surface."""
    roster_rows = [
        row
        for group in summary.get("rosters") or []
        for row in group.get("roster") or []
    ]
    if not roster_rows:
        return {"settled": 0, "void": 0, "unmappable": 0, "pending": 0,
                "errors": 1, "error_msg": "MLS summary has no player rosters"}

    by_espn_id = {}
    by_name = {}
    for row in roster_rows:
        athlete = row.get("athlete") or {}
        athlete_id = str(athlete.get("id") or "")
        if athlete_id:
            by_espn_id.setdefault(athlete_id, []).append(row)
        name_key = _soccer_name(athlete.get("displayName"))
        if name_key:
            by_name.setdefault(name_key, []).append(row)

    # The stored deep row is keyed by the ESPN event id, which the summary
    # publishes on its own header rather than being passed in.
    event_id = (((summary.get("header") or {}).get("competitions") or [{}])[0]
                .get("id") or "")

    settled = 0
    void = 0
    unmappable = 0
    pending = 0
    errors = 0
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    from ingest_soccer_logs import _first_goal_scorer
    first_scorer, goal_events_published = _first_goal_scorer(summary)

    for prop in props:
        canonical = normalize_market(prop["market"])
        canonical = MARKET_ALIASES.get(canonical, canonical)
        stat_name = _MLS_ROSTER_MARKETS.get(canonical)
        sum_stats = _MLS_ROSTER_SUM_MARKETS.get(canonical)
        deep_key = _MLS_DEEP_LOG_MARKETS.get(canonical)
        if (not stat_name and not sum_stats and not deep_key
                and canonical not in _MLS_EVENT_MARKETS):
            unmappable += 1
            continue

        if prop["espn_id"]:
            matches = by_espn_id.get(str(prop["espn_id"]), [])
        else:
            matches = by_name.get(_soccer_name(prop["player_name"]), [])
        if not matches:
            pending += 1
            continue
        if len(matches) != 1:
            pending += 1
            continue

        stats_by_name = {stat.get("name"): stat.get("value")
                         for stat in matches[0].get("stats") or []}

        if deep_key:
            stored = con.execute(
                "SELECT json_extract(stats, ?) FROM player_game_logs "
                "WHERE player_id=? AND game_id=? "
                "AND json_extract(stats, ?) IS NOT NULL LIMIT 1",
                (f"$.{deep_key}", prop["player_id"], str(event_id),
                 f"$.{deep_key}")).fetchone()
            if not stored or stored[0] is None:
                pending += 1
                continue
            actual_value = stored[0]
        elif canonical in _MLS_EVENT_MARKETS:
            if not goal_events_published:
                pending += 1
                continue
            actual_value = 1.0 if str(prop["espn_id"] or "") == str(first_scorer or "") \
                else 0.0
            if not prop["espn_id"]:
                pending += 1
                continue
        elif sum_stats:
            values = [stats_by_name.get(name) for name in sum_stats]
            if any(v in (None, "") for v in values):
                pending += 1
                continue
            try:
                actual_value = float(sum(float(v) for v in values))
            except (TypeError, ValueError):
                pending += 1
                continue
        else:
            published = [value for name, value in stats_by_name.items()
                         if name == stat_name]
            if len(published) != 1 or published[0] in (None, ""):
                pending += 1
                continue
            actual_value = published[0]

        try:
            actual = float(actual_value)
            if _grade_actual(con, prop, actual, now):
                settled += 1
            else:
                unmappable += 1
        except (TypeError, ValueError):
            pending += 1
        except Exception:
            errors += 1

    con.commit()
    return {"settled": settled, "void": void, "unmappable": unmappable,
            "pending": pending, "errors": errors}
