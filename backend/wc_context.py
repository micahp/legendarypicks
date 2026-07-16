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


def _top_scorers(game_id, home_abbr, away_abbr):
    """Shortest anytime-goalscorer odds per team → the 'most likely to score'."""
    out = []
    try:
        c = _db()
        for abbr in (away_abbr, home_abbr):  # away first (matchup reads "A @ H")
            r = c.execute(
                "SELECT pl.name, p.odds FROM props p "
                "JOIN prop_games g ON p.game_id=g.id "
                "JOIN players pl ON p.player_id=pl.id "
                "WHERE g.league='wc' AND g.espn_event_id=? "
                "AND p.market='goals' AND pl.team=? AND p.odds IS NOT NULL "
                "ORDER BY p.odds ASC LIMIT 1", (str(game_id), abbr)).fetchone()
            if r:
                out.append({"team": abbr, "player": r["name"], "odds": r["odds"]})
        c.close()
    except Exception:
        pass
    return out


def _goals_market(game_id):
    """{player: anytime-goalscorer american odds} for the WC game — the prop board."""
    m = {}
    try:
        c = _db()
        for r in c.execute(
                "SELECT pl.name, p.odds FROM props p "
                "JOIN prop_games g ON p.game_id=g.id JOIN players pl ON p.player_id=pl.id "
                "WHERE g.league='wc' AND g.espn_event_id=? "
                "AND p.market='goals' AND p.odds IS NOT NULL "
                "ORDER BY COALESCE(p.odds_captured_at,p.captured_at),p.id",
                (str(game_id),)).fetchall():
            m[r["name"]] = r["odds"]
        c.close()
    except Exception:
        pass
    return m


def _team_odds(sm, home_name, away_name):
    """3-way match-result moneyline from ESPN pickcenter — no scraper/table needed.
    Returns {selection: american_odds} for away/home/Draw, or {}."""
    for p in sm.get("pickcenter", []) or []:
        ho = (p.get("homeTeamOdds", {}) or {}).get("moneyLine")
        ao = (p.get("awayTeamOdds", {}) or {}).get("moneyLine")
        do = (p.get("drawOdds", {}) or {}).get("moneyLine")
        if ho is None and ao is None:
            continue
        out = {}
        if ao is not None:
            out[away_name] = int(ao)
        if ho is not None:
            out[home_name] = int(ho)
        if do is not None:
            out["Draw"] = int(do)
        return out
    return {}


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
    "You are a betting-desk analyst writing live in-match INTEL. Inputs: DATA (score, events, lineup, "
    "team stats — AUTHORITATIVE for match facts), MARKET LINES (Bovada player anytime-goalscorer odds "
    "AND the 3-way match-result moneyline), recent BROADCAST quotes + a transcript tail (the WHY/color). "
    "Produce 3-4 punchy intel lines. A line MAY carry an optional 'play', but MOST lines should NOT — "
    "plays are rare and high-conviction. "
    "WHAT A PLAY IS — a DISCOUNT: an outcome the market prices as UNLIKELY (a longish price) that the "
    "booth's NEW INFORMATION makes MORE LIKELY than the line implies (the market underweights the new "
    "info). A play is a PLAYER (to score) OR a TEAM (to win / draw). Example: team trailing, their "
    "'to win' line has drifted long, but the booth shows real momentum/a man advantage the price hasn't "
    "caught → back that team to win at the discount. "
    "RULES: "
    "(1) Match facts come ONLY from DATA, never the transcript. Read full-sentence context; never turn "
    "background/history into a fact about today's match. "
    "(2) A play needs CONFLUENCE: a genuine market discount AND a specific booth signal the price hasn't "
    "absorbed. This is buying an info-backed VALUE discount — NOT backing favorites, NOT 'the price "
    "looks low/high', NOT a play with no informational reason. If the market is pricing it correctly (a "
    "value trap), NO play. "
    "(3) Player plays: only a player the booth discussed BY NAME. Team plays: only the two teams or 'Draw'. "
    "(4) Flag where the NARRATIVE and the DATA disagree. "
    "Each line is a takeaway a bettor scans in ~2s; SYNTHESIZE, do not just quote. "
    'Return ONLY JSON: [{"headline":"...","evidence":"quote or stat",'
    '"prop":{"player":"Argentina","market":"to win","line":"+205","lean":"back|fade|watch"}}]. '
    '"player" holds the selection (a player name OR a team name / "Draw"). prop is OPTIONAL — omit it on '
    "most lines. Max 4 items. headline <= 110 chars, no trailing period."
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


_insight_cache = {}
_INSIGHT_SYS = (
    "Turn each numbered broadcast excerpt into a takeaway-first card for a bettor watching live. "
    "For EVERY excerpt return: (1) headline: <=8 words, the actual insight; (2) analysis: <=130 "
    "characters explaining why the excerpt matters, grounded ONLY in that excerpt; (3) lean: "
    "back/fade/watch only when a PROP line is supplied AND the excerpt genuinely changes the case "
    "for that named player to score, otherwise an empty string. Commentary is natural conversation "
    "and may describe prior matches: preserve the full sentence's timeframe and NEVER turn history "
    "into a fact about today's match. Do not claim an outcome, score, lineup fact, or that the booth "
    "foreshadowed something unless the excerpt itself says so. Do not attach another player's prop. "
    'Return ONLY JSON: [{"i":0,"headline":"...","analysis":"...","lean":"back|fade|watch|"}].'
)


def _fmt_odds(odds):
    try:
        value = int(odds)
        return f"+{value}" if value > 0 else str(value)
    except (TypeError, ValueError):
        return str(odds)


def _enrich_insights(insights, goals_market, cache_key):
    """Give every booth excerpt its own takeaway, analysis, and grounded prop lean."""
    if not insights:
        return insights
    cards = _insight_cache.get(cache_key)
    if cards is None:
        numbered = "\n".join(
            f"{i}. [{x['tag']}/{x['subject']}] "
            f"PROP: {_fmt_odds(goals_market[x['subject']])} to score; QUOTE: {x['quote']}"
            if x["subject"] in goals_market else
            f"{i}. [{x['tag']}/{x['subject']}] PROP: none; QUOTE: {x['quote']}"
            for i, x in enumerate(insights)
        )
        out = _deepseek(_INSIGHT_SYS, numbered, max_tokens=2600)
        cards = {}
        if out:
            txt = out.strip()
            if txt.startswith("```"):
                txt = txt.strip("`")
                txt = txt.split("\n", 1)[-1]
                if txt.lstrip().startswith("json"):
                    txt = txt.lstrip()[4:]
            try:
                for it in json.loads(txt):
                    if isinstance(it, dict) and "i" in it and it.get("headline"):
                        cards[int(it["i"])] = {
                            "headline": str(it["headline"])[:100],
                            "analysis": str(it.get("analysis", ""))[:160],
                            "lean": str(it.get("lean", "")).lower(),
                        }
            except Exception:
                cards = {}
        _insight_cache[cache_key] = cards
    for i, x in enumerate(insights):
        card = cards.get(i)
        if not card:
            continue
        x["headline"] = card["headline"]
        if card["analysis"]:
            x["analysis"] = card["analysis"]
        odds = goals_market.get(x["subject"])
        if odds is not None and card["lean"] in {"back", "fade", "watch"}:
            x["prop"] = {
                "player": x["subject"],
                "market": "to score",
                "line": _fmt_odds(odds),
                "lean": card["lean"],
            }
    return insights


def _signal_subjects(insights, names):
    """Last names the booth actually made the SUBJECT of a read — the only players a
    prop lean may attach to (stops the LLM free-picking longshots it never discussed)."""
    lastmap = names["last"]
    allowed = set()
    for i in insights:
        subj = (i.get("subject") or "").strip().lower()
        toks = subj.split()
        if toks and toks[-1] in lastmap:
            allowed.add(toks[-1])
    return allowed


def _synthesize_read(data_str, insights, cache_key, allowed_players=None, allowed_teams=None):
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
                        sel = str(p.get("player", ""))[:40]
                        last = sel.split()[-1].lower() if sel.split() else ""
                        # grounding guard: a TEAM play must name one of the two teams / Draw;
                        # a PLAYER play must name a player the booth made a signal subject.
                        is_team = bool(allowed_teams) and sel.lower() in allowed_teams
                        is_player = allowed_players is None or last in allowed_players
                        if is_team or is_player:
                            card["prop"] = {
                                "player": sel,
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
    allowed = _signal_subjects(insights_full, names)
    scorers = _top_scorers(game_id, home_abbr, away_abbr)

    # live match stats → feed the synthesis so it can surface narrative-vs-data
    tstats = {}
    for t in sm.get("boxscore", {}).get("teams", []) or []:
        ab = (t.get("team", {}) or {}).get("abbreviation")
        tstats[ab] = {x.get("name"): x.get("displayValue") for x in t.get("statistics", []) or []}

    def _st(ab, k):
        return (tstats.get(ab) or {}).get(k, "—")

    away_sc, home_sc = away.get("score"), home.get("score")
    goals_mkt = _goals_market(game_id)
    team_odds = _team_odds(sm, _name(home), _name(away))
    allowed_teams = {s.lower() for s in (_name(home), _name(away), "Draw", home_abbr, away_abbr) if s}
    insight_cache_key = ("v2", str(game_id), len(insights_full), tuple(sorted(goals_mkt.items())))
    insights_full = _enrich_insights(insights_full, goals_mkt, insight_cache_key)
    board_str = ", ".join(f"{n} {'+' if o > 0 else ''}{o}"
                          for n, o in sorted(goals_mkt.items(), key=lambda kv: kv[1]))
    events = _match_events(sm)

    def _ev_fmt(e):
        if e["scoring"] and e["players"]:
            assist = f" (assist: {e['players'][1]})" if len(e["players"]) > 1 else ""
            return f"{e['clock']} GOAL scored by {e['players'][0]}{assist} for {e['team']}"
        who = ", ".join(e["players"]) or e["team"]
        return f"{e['clock']} {e['kind']}: {who} ({e['team']})"
    ev_str = "; ".join(_ev_fmt(e) for e in events) or "none yet"
    def _team_line(t, ab, side):
        return (f"{_name(t)} ({side}, {ab}) — score {t.get('score')}, "
                f"possession {_st(ab,'possessionPct')}%, shots {_st(ab,'totalShots')} "
                f"(on target {_st(ab,'shotsOnTarget')}), form {forms.get(ab)}")

    data_str = (
        f"MATCH ({status}): {_name(away)} {away_sc} - {home_sc} {_name(home)}. "
        f"Score events (authoritative): {ev_str}. "
        f"TEAM STATS — {_team_line(away, away_abbr, 'away')}. {_team_line(home, home_abbr, 'home')}. "
        + (f"Bovada anytime-goalscorer board: {board_str}. " if board_str else "")
        + (("Match-result moneyline: "
            + ", ".join(f"{k} {_fmt_odds(v)}" for k, v in team_odds.items()) + ". ") if team_odds else "")
        + f"Broadcast transcript (color/why only, may mix live action with history): {_transcript_tail(tag)}"
    )
    cache_key = (str(game_id), len(insights_full), f"{away_sc}-{home_sc}", len(events))
    read = _synthesize_read(data_str, insights_full, cache_key,
                            allowed_players=allowed, allowed_teams=allowed_teams)

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
