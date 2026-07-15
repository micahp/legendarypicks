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


def _goals_market():
    """{player: anytime-goalscorer american odds} for the WC game — the prop board."""
    m = {}
    try:
        c = _db()
        for r in c.execute(
                "SELECT pl.name, p.odds FROM props p "
                "JOIN prop_games g ON p.game_id=g.id JOIN players pl ON p.player_id=pl.id "
                "WHERE g.league='wc' AND p.market='goals'").fetchall():
            m[r["name"]] = r["odds"]
        c.close()
    except Exception:
        pass
    return m


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
    "You are a betting-desk analyst writing live in-match INTEL for a bettor who has the BOVADA prop "
    "board open. Inputs: DATA (score, events, lineup — AUTHORITATIVE for all match facts), PROP LINES "
    "(Bovada anytime-goalscorer odds), recent BROADCAST quotes + a raw transcript tail (use only for "
    "the WHY / color). Produce 3-4 punchy lines that connect what the booth is saying to a BETTABLE "
    "prop. RULES: "
    "(1) Match facts (score, who scored/assisted, who started) come ONLY from DATA — NEVER from the "
    "transcript. "
    "(2) Commentary is natural conversation that mixes live action with BACKGROUND/history — read the "
    "FULL sentence in context; never state a historical detail (e.g. 'came off the bench in a prior "
    "round') as a fact about today's match. "
    "(3) When the booth flags a player as a threat or as quiet/cold, TIE it to that player's prop line "
    "and give a lean: back / fade / watch. "
    "(4) Flag where the NARRATIVE and the DATA disagree. "
    "Each line is a takeaway a bettor scans in ~2s; SYNTHESIZE, do not just quote. "
    'Return ONLY JSON: [{"headline":"...","evidence":"quote or stat",'
    '"prop":{"player":"","market":"to score","line":"+150","lean":"back|fade|watch"}}]. '
    "prop is OPTIONAL (include only when a line is relevant). Max 4 items. headline <= 110 chars, no trailing period."
)


_EVENT_KINDS = ("Goal", "Penalty", "Own Goal", "Red Card", "Yellow Card", "Substitution")


def _match_events(sm):
    """Hard match events from ESPN keyEvents (goals/cards/subs) — the events the
    audio extractor misses. This is the reliable source for what actually happened."""
    out = []
    for e in sm.get("keyEvents", []) or []:
        typ = (e.get("type", {}) or {}).get("text", "") or ""
        if not any(k in typ for k in _EVENT_KINDS):
            continue
        players = [(p.get("athlete", {}) or {}).get("displayName")
                   for p in e.get("participants", []) or [] if p.get("athlete")]
        out.append({
            "clock": (e.get("clock", {}) or {}).get("displayValue", ""),
            "kind": typ,
            "team": (e.get("team", {}) or {}).get("abbreviation", ""),
            "players": [p for p in players if p],
            "scoring": bool(e.get("scoringPlay")),
            "text": e.get("text", ""),
        })
    return out


def _transcript_tail(tag, n=16):
    """Recent transcript text — carries the goal call / passages the extractor skipped."""
    path = os.path.join(BROADCAST_DIR, f"{tag}_transcript.jsonl")
    if not os.path.exists(path):
        return ""
    lines = []
    with open(path) as f:
        for line in f:
            try:
                lines.append(json.loads(line).get("text", ""))
            except Exception:
                continue
    return " ".join(lines[-n:])[-2400:]


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
                    card = {"headline": str(it["headline"])[:140],
                            "evidence": str(it.get("evidence", ""))[:170]}
                    p = it.get("prop")
                    if isinstance(p, dict) and p.get("player"):
                        card["prop"] = {
                            "player": str(p.get("player", ""))[:40],
                            "market": str(p.get("market", "to score"))[:24],
                            "line": str(p.get("line", ""))[:12],
                            "lean": str(p.get("lean", "watch"))[:6],
                        }
                    read.append(card)
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
    goals_mkt = _goals_market()
    board_str = ", ".join(f"{n} {'+' if o > 0 else ''}{o}"
                          for n, o in sorted(goals_mkt.items(), key=lambda kv: kv[1]))
    events = _match_events(sm)
    ev_str = "; ".join(
        f"{e['clock']} {e['kind']}{' [GOAL]' if e['scoring'] else ''}: "
        f"{', '.join(e['players']) or e['team']} ({e['team']})" for e in events) or "none yet"
    def _team_line(t, ab, side):
        return (f"{_name(t)} ({side}, {ab}) — score {t.get('score')}, "
                f"possession {_st(ab,'possessionPct')}%, shots {_st(ab,'totalShots')} "
                f"(on target {_st(ab,'shotsOnTarget')}), form {forms.get(ab)}")

    data_str = (
        f"MATCH ({status}): {_name(away)} {away_sc} - {home_sc} {_name(home)}. "
        f"Score events (authoritative): {ev_str}. "
        f"TEAM STATS — {_team_line(away, away_abbr, 'away')}. {_team_line(home, home_abbr, 'home')}. "
        + (f"Bovada anytime-goalscorer board: {board_str}. " if board_str else "")
        + f"Broadcast transcript (color/why only, may mix live action with history): {_transcript_tail(tag)}"
    )
    cache_key = (str(game_id), len(insights_full), f"{away_sc}-{home_sc}", len(events))
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
