"""wc_context.py — build the "Game Context" summary for a WC game detail page.

Blends three sources into one fan-legible object:
  1. Form + status (ESPN scoreboard/summary).
  2. Most-likely goalscorer PER TEAM (shortest anytime-goal odds from our WC props).
  3. The broadcast's soft reads (the whisper pipeline's signals jsonl), relevance-filtered.

POC for ARG–ENG (2026-07-15). The signals file is written by
prediction-market-trading/broadcast_alpha.py; we read it cross-repo.
"""
import difflib
import json
import os
import re
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


_GENERIC_SUBJ = {"game", "match", "both teams", "teams", "players",
                 "argentina", "england", "england vs argentina"}


def _roster_names(sm):
    """{full:[displayName], last:{lastname_lower: displayName}} for this match."""
    full, last = [], {}
    for team in sm.get("rosters", []) or []:
        for r in team.get("roster", []) or []:
            nm = (r.get("athlete", {}) or {}).get("displayName")
            if nm:
                full.append(nm)
                toks = nm.split()
                if toks:
                    last[toks[-1].lower()] = nm
    return {"full": full, "last": last}


def _normalize_subject(subj, names):
    """Map a whisper-mangled subject to a real roster name (Jett Spence→Djed
    Spence, jute Bellingham→Jude Bellingham). Team/generic subjects pass through."""
    s = (subj or "").strip()
    if not s or s.lower() in _GENERIC_SUBJ:
        return s
    last = names["last"]
    toks = s.split()
    if toks:
        lt = toks[-1].lower()
        if lt in last:
            return last[lt]
        m = difflib.get_close_matches(lt, list(last.keys()), n=1, cutoff=0.72)
        if m:
            return last[m[0]]
    m = difflib.get_close_matches(s, names["full"], n=1, cutoff=0.72)
    return m[0] if m else s


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


def _broadcast_insights(tag, names, limit=8):
    """Relevance-filtered, name-normalized, de-duplicated booth reads → cards."""
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
        quote = r.get("quote", "").strip()
        if not quote or len(quote) < 25:
            continue
        # dedup on the quote itself → collapses repeats + same quote under two subjects
        qk = re.sub(r"[^a-z0-9]", "", quote.lower())[:50]
        if qk in seen:
            continue
        seen.add(qk)
        kept.append({
            "tag": _TAG_LABEL.get(r.get("type"), "Read"),
            "subject": _normalize_subject(str(r.get("subject", "")).strip(), names),
            "quote": quote if len(quote) <= 180 else quote[:177].rstrip() + "…",
            "strength": r.get("strength", 1),
            "ts": r.get("ts"),
        })
    kept.sort(key=lambda x: (x["strength"] or 1), reverse=True)
    return kept[:limit]


_read_cache = {}

_READ_SYS = (
    "You are a sharp, concise football (soccer) analyst writing live in-match INTEL for fans. "
    "You get the current match DATA and recent BROADCAST commentary quotes. Produce 3-4 punchy "
    "insight lines: the real story right now, the danger man, and ESPECIALLY any place the "
    "commentary NARRATIVE and the DATA disagree — state the lean. Each line is a takeaway a fan "
    "scans in ~2 seconds. Do NOT just repeat quotes; SYNTHESIZE what it means. "
    'Return ONLY JSON: [{"headline":"...","evidence":"short supporting quote or stat"}]. '
    "Max 4 items. headline <= 110 chars, no trailing period."
)


def _deepseek(system, user, max_tokens=700):
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        return None
    body = json.dumps({
        "model": "deepseek-chat", "temperature": 0.2, "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)["choices"][0]["message"]["content"]
    except Exception:
        return None


def _synthesize_read(data_str, insights, cache_key):
    """LLM synthesis of the reads + data → scannable intel lines (cached)."""
    if cache_key in _read_cache:
        return _read_cache[cache_key]
    if not insights:
        return []
    quotes = "\n".join(f"- [{i['tag']}/{i['subject']}] {i['quote']}" for i in insights[:18])
    out = _deepseek(_READ_SYS, f"{data_str}\n\nBroadcast reads:\n{quotes}")
    read = []
    if out:
        txt = out.strip()
        if txt.startswith("```"):
            txt = txt.strip("`")
            txt = txt.split("\n", 1)[-1]
            if txt.lstrip().startswith("json"):
                txt = txt.lstrip()[4:]
        try:
            for it in json.loads(txt)[:4]:
                if isinstance(it, dict) and it.get("headline"):
                    read.append({"headline": str(it["headline"])[:140],
                                 "evidence": str(it.get("evidence", ""))[:170]})
        except Exception:
            read = []
    _read_cache[cache_key] = read
    return read


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

    names = _roster_names(sm)
    insights_full = _broadcast_insights(tag, names, limit=40)
    scorers = _top_scorers(home_abbr, away_abbr)

    # live match stats → feed the synthesis so it can surface narrative-vs-data
    tstats = {}
    for t in sm.get("boxscore", {}).get("teams", []) or []:
        ab = (t.get("team", {}) or {}).get("abbreviation")
        tstats[ab] = {x.get("name"): x.get("displayValue") for x in t.get("statistics", []) or []}

    def _st(ab, k):
        return (tstats.get(ab) or {}).get(k, "—")

    away_sc, home_sc = away.get("score"), home.get("score")
    data_str = (
        f"Match: {_name(away)} {away_sc}-{home_sc} {_name(home)} ({status}). "
        f"Possession: {away_abbr} {_st(away_abbr,'possessionPct')}% / {home_abbr} {_st(home_abbr,'possessionPct')}%. "
        f"Shots: {away_abbr} {_st(away_abbr,'totalShots')} / {home_abbr} {_st(home_abbr,'totalShots')}. "
        f"Form: {away_abbr} {forms.get(away_abbr)}, {home_abbr} {forms.get(home_abbr)}. "
        + ("Most likely to score: " + ", ".join(f"{s['player']} +{s['odds']} ({s['team']})" for s in scorers) if scorers else "")
    )
    cache_key = (str(game_id), len(insights_full), f"{away_sc}-{home_sc}")
    read = _synthesize_read(data_str, insights_full, cache_key)

    return {
        "game_id": str(game_id),
        "headline": f"{_name(away)} at {_name(home)}",
        "status": status,
        "teams": {
            "home": {"abbr": home_abbr, "name": _name(home), "form": _form(home)},
            "away": {"abbr": away_abbr, "name": _name(away), "form": _form(away)},
        },
        "top_scorers": scorers,
        "read": read,
        "insights": insights_full[:limit],
        "source": "broadcast + market + form",
    }
