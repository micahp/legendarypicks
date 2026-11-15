"""Plain broadcast wording for relationship candidates. Pure, no model call.

Every sentence is built from the structured claims of one candidate. Wording follows
the certainty of the candidate: a player who is not expected or confirmed to play is
named with "If X plays". "First" appears only for the two kinds that prove it. No
motive, emotion or result is ever written. A missing name raises ValueError.
"""
from __future__ import annotations

import datetime as dt

from ingest_nba_player_movement import TEAM_NAME_TO_CODE

TEAM_FULL = {code: name for name, code in TEAM_NAME_TO_CODE.items()}
_CITY_PREFIX = ("Los Angeles", "New York", "New Orleans", "Golden State", "San Antonio", "Oklahoma City")


def team_city(code):
    full = TEAM_FULL[code]
    for prefix in _CITY_PREFIX:
        if full.startswith(prefix):
            return prefix
    return full.split(" ", 1)[0]


def team_nick(code):
    return TEAM_FULL[code][len(team_city(code)) + 1:]


def _day(iso):
    d = dt.date.fromisoformat(iso)
    return "%s %d, %d" % (d.strftime("%B"), d.day, d.year)


def _month(iso):
    d = dt.date.fromisoformat(iso)
    return "%s %d" % (d.strftime("%B"), d.year)


def _join(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _name(names, key):
    if key not in names:
        raise ValueError("no display name for player %s" % key)
    return names[key]


def _moves_text(moves, names):
    """'A went from the X to the Y.' per direction, players sorted by name."""
    groups = {}
    for m in moves:
        groups.setdefault((m["from"], m["to"]), []).append(_name(names, m["player"]))
    return " ".join("%s went from the %s to the %s." % (_join(sorted(who)), TEAM_FULL[a], TEAM_FULL[b])
                    for (a, b), who in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])))


def render(c, names):
    kind, claims, teams = c["kind"], c["claims"], c["entities"]["teams"]
    eligible = c["headline_eligible"]
    if kind == "reciprocal_trade_reunion":
        moves = [x for x in claims if x["type"] == "moved"]
        deal = next(x for x in claims if x["type"] == "transaction")
        others = [t for t in deal["teams_in_deal"] if t not in teams]
        body = _moves_text(moves, names)
        if others:
            body += " The deal also involved the %s." % _join(TEAM_FULL[t] for t in sorted(others))
        return _out(c, "Trade reunion",
                    "%s and %s are linked by the %s trade." % (team_city(teams[0]), team_city(teams[1]),
                                                              _day(deal["effective_date"])), body)
    if kind == "first_team_meeting_after_trade":
        claim = claims[0]
        return _out(c, "First meeting since the trade",
                    "%s and %s meet for the first time since the %s trade." % (
                        team_city(teams[0]), team_city(teams[1]), _day(claim["trade_date"])),
                    _moves_text(claim["moves"], names))
    if kind in ("former_team_matchup", "former_arena_return", "first_return_to_former_arena"):
        claim = claims[0]
        who, former = _name(names, c["entities"]["players"][0]), claim["former_team"]
        how = ("in a trade on " if c.get("event_id") else "on ") + _day(claim["left_on"])
        body = "He left the %s %s." % (TEAM_FULL[former], how)
        if kind == "former_team_matchup":
            head = ("%s is expected to face the %s, a former team." if eligible else
                    "If %s plays, he faces a former team, the %s.") % (who, TEAM_FULL[former])
            return _out(c, "Former team", head, body)
        city = team_city(former)
        if kind == "first_return_to_former_arena":
            head = "%s is expected to make his first return to %s since leaving the %s." % (
                who, city, TEAM_FULL[former])
        elif eligible:
            head = "%s is expected to be in %s, home of his former team, the %s." % (who, city, TEAM_FULL[former])
        else:
            head = "If %s plays, he is in %s, home of his former team, the %s." % (who, city, TEAM_FULL[former])
        return _out(c, "Return to a former home", head, body)
    if kind == "former_teammates_now_opponents":
        a, b = (_name(names, p) for p in sorted(c["entities"]["players"], key=lambda p: names.get(p, p)))
        claim = claims[0]
        team = TEAM_FULL[claim["team"]]
        if claim["complete"]:
            body = "They were teammates on the %s from %s to %s." % (team, _month(claim["start"]), _month(claim["end"]))
        else:
            body = ("The data shows them together on the %s until %s. When their time together began is "
                    "not documented." % (team, _month(claim["end"])))
        head = ("%s and %s were teammates with the %s and now face each other." % (a, b, team) if eligible
                else "%s and %s share a past with the %s." % (a, b, team))
        return _out(c, "Former teammates", head, body)
    raise ValueError("no template for kind %r" % (kind,))


def _out(c, label, headline, body):
    return {"candidate_id": c["candidate_id"], "label": label, "headline": headline, "body": body,
            "text": headline + " " + body}
