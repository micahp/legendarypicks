"""Independent audit of rendered relationship copy.

It does not trust the template. It re-reads the finished text and checks it against
the relationship graph and the candidate: trade direction, claims the graph holds,
unsupported "first", availability wording, emotion words, teams outside the matchup,
postgame language, facts after the cutoff, and the no-em-dash house rule.

`audit(...)` returns {"ok": bool, "failures": [{"check", "detail"}]}.
"""
from __future__ import annotations

import re

from storyline_templates import TEAM_FULL, team_nick

BANNED = [r"revenge", r"bad blood", r"grudge", r"heated", r"betray\w*", r"something to prove",
          r"prove\b.*\bwrong", r"payback", r"vendetta", r"bitter\w*", r"personal\b", r"chip on", r"rival\w*"]
POSTGAME = [r"\bwon\b", r"\blost\b", r"\bbeat\b", r"\bdefeated\b", r"\bscored\b", r"\boutscored\b",
            r"\bfinal score\b", r"\bbox score\b", r"\b\d{2,3}-\d{2,3}\b"]
EXPECTED = re.compile(r"\b(is|are) expected to\b|\bwill (play|face|return)\b|\bis set to\b", re.I)
WENT = re.compile(r"(?P<who>[^.]+?) went from the (?P<frm>[^.]+?) to the (?P<to>[^.]+?)\.")
DATE_KEYS = ("date", "trade_date", "left_on", "effective_date", "end", "start")
_CODE_OF = {name: code for code, name in TEAM_FULL.items()}


def banned_words(text):
    return [m.group(0) for pat in BANNED for m in re.finditer(pat, text, re.I)]


def _moves_of(c):
    out = []
    for claim in c["claims"]:
        if claim["type"] == "moved":
            out.append(claim)
        for m in claim.get("moves", []):
            out.append(dict(m, type="moved", date=claim.get("trade_date")))
    return out


def _all_dates(claims):
    for claim in claims:
        for key in DATE_KEYS:
            if claim.get(key):
                yield claim[key]


def _claim_teams(c):
    teams = set(c["entities"]["teams"])
    for claim in c["claims"]:
        teams.update(claim.get("teams_in_deal", []))
        for key in ("from", "to", "former_team", "current_team", "team"):
            if claim.get(key):
                teams.add(claim[key])
        teams.update(x for m in claim.get("moves", []) for x in (m["from"], m["to"]))
    return teams


def audit(c, text, graph, *, as_of, names):
    fails = []

    def fail(check, detail):
        fails.append({"check": check, "detail": detail})

    for word in banned_words(text):
        fail("banned_word", word)
    for pat in POSTGAME:
        if re.search(pat, text, re.I):
            fail("postgame_language", pat)
    if "\u2014" in text:
        fail("style", "em dash")
    for date in _all_dates(c["claims"]):
        if date > as_of:
            fail("future_fact", date)
    for p in c["entities"]["players"]:
        if names.get(p) is None or names[p] not in text:
            fail("missing_name", p)

    kind = c["kind"]
    if re.search(r"\bfirst\b", text, re.I):
        claim = c["claims"][0] if c["claims"] else {}
        ok = (kind == "first_team_meeting_after_trade" and claim.get("meetings_checked_from")
              and claim["meetings_checked_from"] <= claim.get("trade_date", ""))
        ok = ok or (kind == "first_return_to_former_arena" and claim.get("first_return") is True)
        if not ok:
            fail("unsupported_first", kind)
    if EXPECTED.search(text) and not c["headline_eligible"]:
        fail("availability", "expected wording without confirmation")

    allowed = _claim_teams(c)
    for code, full in TEAM_FULL.items():
        if code in allowed:
            continue
        if re.search(r"\b%s\b" % re.escape(full), text) or re.search(r"\b%s\b" % re.escape(team_nick(code)), text):
            fail("unexpected_team", code)

    truth = {(names.get(m.player_key), m.from_team, m.to_team)
             for m in graph.movements() if m.date <= as_of}
    stated = set()
    for m in WENT.finditer(text):
        frm, to = _CODE_OF.get(m.group("frm")), _CODE_OF.get(m.group("to"))
        for who in re.split(r", | and ", m.group("who")):
            stated.add((who.strip(), frm, to))
    for item in sorted(stated, key=str):
        if item not in truth:
            fail("direction", "%s went from %s to %s is not in the graph" % item)
    for m in _moves_of(c):
        item = (names.get(m["player"]), m["from"], m["to"])
        if item not in truth:
            fail("claim_not_in_graph", "%s %s->%s" % item)
        elif kind in ("reciprocal_trade_reunion", "first_team_meeting_after_trade") and item not in stated:
            fail("direction", "text does not state %s went from %s to %s" % item)
    for claim in c["claims"]:
        if claim["type"] == "former_team":
            held = any(s.team == claim["former_team"] and s.end == claim["left_on"]
                       for s in graph.stints(c["entities"]["players"][0]))
            if not held:
                fail("claim_not_in_graph", "former team %s" % claim["former_team"])
        if claim["type"] == "shared_tenure":
            p1, p2 = c["entities"]["players"]
            held = any(s.team == claim["team"] and s.start == claim["start"] and s.end == claim["end"]
                       for s in graph.shared_tenure(p1, p2))
            if not held:
                fail("claim_not_in_graph", "shared tenure at %s" % claim["team"])
    fails.sort(key=lambda f: (f["check"], f["detail"]))
    return {"ok": not fails, "failures": fails}
