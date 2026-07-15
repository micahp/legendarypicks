"""wc_context.py — build the "Game Context" summary for a WC game detail page.

Blends three sources into one fan-legible object:
  1. Form + status (ESPN scoreboard/summary).
  2. Most-likely goalscorer PER TEAM (shortest anytime-goal odds from our WC props).
  3. The broadcast's soft reads (the whisper pipeline's signals jsonl), relevance-filtered.

POC for ARG–ENG (2026-07-15). The signals file is written by
prediction-market-trading/broadcast_alpha.py; we read it cross-repo.
"""
import json
import os
import sqlite3
import urllib.request

import espn_client as espn

_SCOREBOARD = ("https://site.api.espn.com/apis/site/v2/sports/soccer/"
               "fifa.world/scoreboard?dates={date}")


def _forms(date, game_id):
    """{abbr: form-string} from the scoreboard (summary endpoint omits form)."""
    try:
        req = urllib.request.Request(_SCOREBOARD.format(date=date),
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.load(r)
        for e in d.get("events", []):
            if str(e.get("id")) == str(game_id):
                out = {}
                for t in e["competitions"][0].get("competitors", []):
                    out[t.get("team", {}).get("abbreviation", "")] = t.get("form")
                return out
    except Exception:
        pass
    return {}

BROADCAST_DIR = os.environ.get(
    "LP_BROADCAST_DIR", "/root/prediction-market-trading/data/broadcast"
)

# fan-facing tag for each raw extractor `type`
_TAG_LABEL = {
    "momentum": "Momentum", "tactical": "Tactical", "morale": "Mentality",
    "fatigue": "Fatigue", "lockin": "Key man", "injury": "Injury",
}
# drop signals that are iHeart promos / other-sport filler / other-match tangents
_JUNK_KW = ("brady", "senate", "bulger", "podcast", "iheart", "dirty rats",
            "honorary", "nfl", "touchdown", "mbappe", "france", "spain")


def _db():
    path = os.environ.get("LP_DB_PATH", "data/picks.db")
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def _top_scorers(home_abbr, away_abbr):
    """Shortest anytime-goalscorer odds per team → the 'most likely to score'."""
    out = []
    try:
        c = _db()
        for abbr in (away_abbr, home_abbr):  # away first (matchup reads "A @ H")
            r = c.execute(
                "SELECT pl.name, p.odds FROM props p "
                "JOIN prop_games g ON p.game_id=g.id "
                "JOIN players pl ON p.player_id=pl.id "
                "WHERE g.league='wc' AND p.market='goals' AND pl.team=? "
                "ORDER BY p.odds ASC LIMIT 1", (abbr,)).fetchone()
            if r:
                out.append({"team": abbr, "player": r["name"], "odds": r["odds"]})
        c.close()
    except Exception:
        pass
    return out


def _broadcast_insights(tag, limit=8):
    """Relevance-filtered booth reads → tagged insight cards, strongest first."""
    path = os.path.join(BROADCAST_DIR, f"{tag}_signals.jsonl")
    if not os.path.exists(path):
        return []
    rows = []
    with open(path) as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    kept, seen = [], set()
    for r in rows:
        blob = (str(r.get("subject", "")) + " " + r.get("quote", "")).lower()
        if any(k in blob for k in _JUNK_KW):
            continue
        subj = str(r.get("subject", "")).strip()
        quote = r.get("quote", "").strip()
        if not quote or len(quote) < 25:
            continue
        key = (r.get("type"), subj)
        if key in seen:
            continue
        seen.add(key)
        kept.append({
            "tag": _TAG_LABEL.get(r.get("type"), "Read"),
            "subject": subj,
            "quote": quote if len(quote) <= 180 else quote[:177].rstrip() + "…",
            "strength": r.get("strength", 1),
            "ts": r.get("ts"),
        })
    kept.sort(key=lambda x: (x["strength"] or 1), reverse=True)
    return kept[:limit]


def build_context(game_id, limit=8):
    """Return the Game Context object for a WC game detail page, or None."""
    try:
        sm = espn.summary("wc", game_id)
    except Exception:
        return None
    comp = ((sm.get("header", {}).get("competitions") or [{}])[0])
    competitors = comp.get("competitors", [])
    if len(competitors) < 2:
        return None
    home = next((t for t in competitors if t.get("homeAway") == "home"), competitors[0])
    away = next((t for t in competitors if t.get("homeAway") == "away"), competitors[1])

    def _abbr(t):
        return (t.get("team", {}) or {}).get("abbreviation", "")

    def _name(t):
        return (t.get("team", {}) or {}).get("displayName", "")

    home_abbr, away_abbr = _abbr(home), _abbr(away)
    date = (comp.get("date") or "")[:10].replace("-", "")  # YYYYMMDD
    tag = f"{date}_WC_{away_abbr}{home_abbr}"

    # form (summary omits it → fall back to the scoreboard)
    forms = _forms(date, game_id)

    def _form(t):
        f = t.get("form")
        if isinstance(f, str):
            return f
        return forms.get(_abbr(t))

    status = ((sm.get("header", {}).get("competitions") or [{}])[0]
              .get("status", {}).get("type", {}).get("detail")) \
        or sm.get("header", {}).get("competitions", [{}])[0].get("status", {}).get("type", {}).get("description")

    return {
        "game_id": str(game_id),
        "headline": f"{_name(away)} at {_name(home)}",
        "status": status,
        "teams": {
            "home": {"abbr": home_abbr, "name": _name(home), "form": _form(home)},
            "away": {"abbr": away_abbr, "name": _name(away), "form": _form(away)},
        },
        "top_scorers": _top_scorers(home_abbr, away_abbr),
        "insights": _broadcast_insights(tag, limit=limit),
        "source": "broadcast + market + form",
    }
