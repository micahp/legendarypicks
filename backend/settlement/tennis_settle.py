#!/usr/bin/env python3
"""tennis_settle.py — settle tennis props from ESPN's tournament scoreboard."""
import datetime as dt
import re

from settlement.grading import _grade_actual
from settlement.market_mapping import normalize_market


_TENNIS_LEAGUES = {"atp": "mens-singles", "wta": "womens-singles"}
_SET_BETTING = re.compile(r"^set_betting___(\d+)_(\d+)$")


def _tennis_terminal_reason(competition: dict):
    """Return a published non-normal final state that has special settlement rules.

    A walkover has no played match.  A retirement has played stats, but only an
    outcome that is already irreversible from those stats may be graded.  In
    both cases we deliberately leave void props out of ``prop_results``: a
    NULL result row falsely looks like a settled numerical outcome downstream.
    """
    status_type = ((competition.get("status") or {}).get("type") or {})
    values = " ".join(str(status_type.get(key) or "") for key in
                      ("name", "description", "detail", "shortDetail")).lower()
    if "walkover" in values:
        return "walkover"
    if "retir" in values:
        return "retirement"
    return None


def _tennis_scoreboard_competition(espn, league: str, date_text: str, event_id: str) -> dict:
    """Return one exact singles competition from the publisher's daily board.

    Tennis tournament scoreboards contain both draws.  The requested league and
    the draw slug therefore both have to agree before an event can be graded.
    """
    expected_group = _TENNIS_LEAGUES[league]
    wanted = str(event_id)
    checked = []
    for day in espn.neighbor_dates(date_text):
        checked.append(day)
        payload = espn.scoreboard_raw(league, day, ttl=60)
        returned = ((payload.get("leagues") or [{}])[0].get("slug") or "").lower()
        if returned != league:
            raise ValueError(
                f"tennis scoreboard league mismatch: requested {league}, got {returned or 'none'}")
        for event in payload.get("events") or []:
            for grouping in event.get("groupings") or []:
                slug = ((grouping.get("grouping") or {}).get("slug") or "").lower()
                if slug != expected_group:
                    continue
                for competition in grouping.get("competitions") or []:
                    if str(competition.get("id") or "") == wanted:
                        return competition
    raise ValueError(
        f"tennis event {wanted} absent from {league} scoreboards {', '.join(checked)}")


def _tennis_actuals(competition: dict) -> dict:
    """Return exact player outcomes, refusing partial or contradictory results."""
    status_type = ((competition.get("status") or {}).get("type") or {})
    if status_type.get("completed") is not True:
        raise ValueError("tennis competition is not completed")

    competitors = competition.get("competitors") or []
    if len(competitors) != 2:
        raise ValueError(f"expected two tennis competitors, got {len(competitors)}")

    rows = []
    for competitor in competitors:
        athlete_id = str(competitor.get("id") or "")
        if not athlete_id.isdigit() or int(athlete_id) <= 0:
            raise ValueError("tennis competitor has no valid ESPN athlete id")
        linescores = competitor.get("linescores") or []
        if not linescores:
            raise ValueError(f"tennis competitor {athlete_id} has no published set scores")
        values = []
        set_winners = []
        for score in linescores:
            value = score.get("value")
            if not isinstance(value, (int, float)) or value < 0:
                raise ValueError(f"tennis competitor {athlete_id} has invalid set score")
            if not isinstance(score.get("winner"), bool):
                raise ValueError(f"tennis competitor {athlete_id} has no published set winner")
            values.append(float(value))
            set_winners.append(score["winner"])
        rows.append({
            "athlete_id": athlete_id,
            "winner": competitor.get("winner"),
            "games": sum(values),
            "set_winners": set_winners,
        })

    if rows[0]["athlete_id"] == rows[1]["athlete_id"]:
        raise ValueError("tennis competition repeats an ESPN athlete id")
    if not all(isinstance(row["winner"], bool) for row in rows):
        raise ValueError("tennis competition has no published match winner")
    if sum(row["winner"] for row in rows) != 1:
        raise ValueError("tennis competition has contradictory match winners")
    if len(rows[0]["set_winners"]) != len(rows[1]["set_winners"]):
        raise ValueError("tennis competitors publish a different number of sets")

    for index, winners in enumerate(zip(rows[0]["set_winners"], rows[1]["set_winners"])):
        if sum(winners) != 1:
            raise ValueError(f"tennis set {index + 1} has no unique winner")
    if max(sum(row["set_winners"]) for row in rows) < 2:
        # ATP/WTA singles cannot be a normally completed one-set match.  A
        # completed flag after a retirement does not publish the bookmaker's
        # settlement rule, so retain these props for review/retry instead.
        raise ValueError("tennis final has fewer than two completed sets")

    return {
        row["athlete_id"]: {
            "match_winner": 1.0 if row["winner"] else 0.0,
            "total_games": row["games"],
            "sets_won": float(sum(row["set_winners"])),
            "opponent_sets_won": float(sum(other["set_winners"])),
        }
        for row, other in ((rows[0], rows[1]), (rows[1], rows[0]))
    }


def _tennis_prop_actual(prop, actuals: dict):
    """Return one numeric published outcome, or None for an unsupported market."""
    athlete_id = str(prop["espn_id"] or "")
    player = actuals.get(athlete_id)
    if not player:
        return None
    raw_market = str(prop["market"] or "").strip().lower()
    market = normalize_market(raw_market)
    if market in {"match_winner", "total_games"}:
        return player[market]
    if market == "win_a_set":
        return 1.0 if player["sets_won"] >= 1 else 0.0
    set_betting = _SET_BETTING.fullmatch(raw_market)
    if set_betting:
        wanted = (float(set_betting.group(1)), float(set_betting.group(2)))
        actual = (player["sets_won"], player["opponent_sets_won"])
        return 1.0 if actual == wanted else 0.0
    return None


def _retirement_actuals(competition: dict) -> dict:
    """Read only the score already published before a retirement.

    The unfinished set need not have a winner, unlike a normal final.  Its
    completed games remain usable for a monotonic total-games threshold.
    """
    actuals = {}
    competitors = competition.get("competitors") or []
    if len(competitors) != 2:
        return actuals
    for competitor in competitors:
        athlete_id = str(competitor.get("id") or "")
        if not athlete_id.isdigit() or int(athlete_id) <= 0:
            return {}
        games = 0.0
        sets_won = 0
        for score in competitor.get("linescores") or []:
            value = score.get("value")
            if not isinstance(value, (int, float)) or value < 0:
                return {}
            games += float(value)
            sets_won += 1 if score.get("winner") is True else 0
        actuals[athlete_id] = {"total_games": games, "sets_won": sets_won}
    return actuals


def _settle_tennis_retirement_props(con, props: list, competition: dict) -> dict:
    """Grade only outcomes locked by official play before a retirement.

    This follows the shared LegendaryPicks policy: no awarded post-retirement
    statistics, no inferred future play, and no result row for a void prop.
    """
    actuals = _retirement_actuals(competition)
    settled = 0
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for prop in props:
        player = actuals.get(str(prop["espn_id"] or ""))
        if not player:
            continue
        market = normalize_market(str(prop["market"] or "").strip().lower())
        side = str(prop["side"] or "").lower()
        actual = None
        if market == "total_games" and side == "over":
            candidate = player["total_games"]
            if candidate > prop["line"]:
                actual = candidate
        elif market == "win_a_set" and side == "over":
            candidate = 1.0 if player["sets_won"] >= 1 else 0.0
            if candidate > prop["line"]:
                actual = candidate
        if actual is not None and _grade_actual(con, prop, actual, now):
            settled += 1
    con.commit()
    return {"settled": settled, "void": len(props) - settled, "unmappable": 0,
            "pending": 0, "errors": 0}


def _settle_tennis_props(con, props: list, competition: dict) -> dict:
    """Grade supported tennis props from one already-validated competition."""
    reason = _tennis_terminal_reason(competition)
    if reason == "walkover":
        return {"settled": 0, "void": len(props), "unmappable": 0,
                "pending": 0, "errors": 0}
    if reason == "retirement":
        return _settle_tennis_retirement_props(con, props, competition)
    try:
        actuals = _tennis_actuals(competition)
    except ValueError as exc:
        return {"settled": 0, "void": 0, "unmappable": 0, "pending": len(props),
                "errors": 1, "error_msg": str(exc)}

    settled = unmappable = pending = errors = 0
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for prop in props:
        actual = _tennis_prop_actual(prop, actuals)
        if actual is None:
            # An absent ESPN identity is a retryable data-integrity gap; an
            # unknown market is a mapping gap.  Neither may create a result row.
            if str(prop["espn_id"] or "") not in actuals:
                pending += 1
            else:
                unmappable += 1
            continue
        try:
            if _grade_actual(con, prop, actual, now):
                settled += 1
            else:
                unmappable += 1
        except Exception:
            errors += 1
    con.commit()
    return {"settled": settled, "void": 0, "unmappable": unmappable,
            "pending": pending, "errors": errors}
