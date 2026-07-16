"""wc_context.py — build the "Game Context" summary for a WC game detail page.

Blends three sources into one fan-legible object:
  1. Form + status (ESPN scoreboard/summary).
  2. Exact event markets (Bovada match/player lines + Kalshi fallback and price history).
  3. The broadcast's soft reads (the whisper pipeline's signals jsonl), relevance-filtered.

POC for ARG–ENG (2026-07-15). The signals file is written by
prediction-market-trading/broadcast_alpha.py; we read it cross-repo.
"""
import datetime as dt
import difflib
import json
import os
import re
import sqlite3
import urllib.request

import espn_client as espn
from routers.live_discounts import wc_event_markets

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
# drop signals that are iHeart promos / other-sport filler; other-match tangents are
# rejected dynamically against the current event roster below (never by hard-coded teams)
_JUNK_KW = ("brady", "senate", "bulger", "podcast", "iheart", "dirty rats",
            "honorary", "nfl", "touchdown")


_GENERIC_SUBJ = {"game", "match", "both teams", "teams", "players"}
_SIGNAL_EDGE_WINDOW_MIN = 15


def _roster_names(sm):
    """Canonical roster names plus the ESPN team abbreviation for each player."""
    full, last, team_by_name, team_names = [], {}, {}, set()
    for team in sm.get("rosters", []) or []:
        team_data = team.get("team", {}) or {}
        team_abbr = team_data.get("abbreviation", "")
        for value in (team_abbr, team_data.get("displayName"), team_data.get("name")):
            if value:
                team_names.add(value.lower())
        for r in team.get("roster", []) or []:
            nm = (r.get("athlete", {}) or {}).get("displayName")
            if nm:
                full.append(nm)
                team_by_name[nm] = team_abbr
                toks = nm.split()
                if toks:
                    last[toks[-1].lower()] = nm
    return {"full": full, "last": last, "team_by_name": team_by_name, "teams": team_names}


def _normalize_subject(subj, names):
    """Map a whisper-mangled subject to a real roster name (Jett Spence→Djed
    Spence, jute Bellingham→Jude Bellingham). Team/generic subjects pass through."""
    s = (subj or "").strip()
    if not s or s.lower() in _GENERIC_SUBJ or s.lower() in names["teams"]:
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


_PLAYER_MARKET_LABEL = {
    "goals": "to score",
    "assists": "to assist",
    "shots": "shots",
    "shots_on_target": "shots on target",
}


def _american_probability(odds):
    try:
        value = int(odds)
        return round(100 / (value + 100), 4) if value > 0 else round(-value / (-value + 100), 4)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _player_market_name(market, line):
    label = _PLAYER_MARKET_LABEL.get(market, market.replace("_", " "))
    if market in ("goals", "assists"):
        return label
    try:
        threshold = int(line) if float(line).is_integer() else float(line)
        return f"{threshold}+ {label}"
    except (TypeError, ValueError):
        return label


def _player_markets(game_id, event_state):
    """Current, event-scoped Bovada board with the snapshots needed to detect repricing."""
    board = []
    try:
        c = _db()
        for r in c.execute(
                "SELECT p.id,pl.name,pl.team,p.market,p.line,p.side,p.odds,p.odds_captured_at "
                "FROM props p "
                "JOIN prop_games g ON p.game_id=g.id JOIN players pl ON p.player_id=pl.id "
                "WHERE g.league='wc' AND g.espn_event_id=? "
                "AND p.odds IS NOT NULL "
                "ORDER BY pl.name,p.market,p.line,p.id",
                (str(game_id),)).fetchall():
            history = c.execute(
                "SELECT odds,captured_at FROM prop_odds_snapshots WHERE prop_id=? "
                "ORDER BY captured_at DESC LIMIT 2", (r["id"],)).fetchall()
            opening = c.execute(
                "SELECT odds FROM prop_odds_snapshots WHERE prop_id=? ORDER BY captured_at LIMIT 1",
                (r["id"],)).fetchone()
            captured = r["odds_captured_at"]
            fresh = False
            if captured:
                try:
                    seen = dt.datetime.fromisoformat(captured.replace("Z", "+00:00"))
                    fresh = (dt.datetime.now(dt.timezone.utc) - seen).total_seconds() <= 30 * 60
                except (TypeError, ValueError):
                    pass
            board.append({
                "market_id": f"bovada:{r['id']}",
                "kind": "player",
                "team": r["team"],
                "selection": r["name"],
                "market": _player_market_name(r["market"], r["line"]),
                "price": r["odds"],
                "implied_probability": _american_probability(r["odds"]),
                "previous_price": history[1]["odds"] if len(history) > 1 else None,
                "opening_price": opening["odds"] if opening else None,
                "source": "Bovada",
                "as_of": captured,
                "tradable": event_state in ("pre", "in") and fresh,
            })
        c.close()
    except Exception:
        pass
    return board


def _bovada_match_markets(game_id, event_state, team_abbrs):
    """Latest full-match moneyline plus prior quotes for one linked ESPN event."""
    board = []
    try:
        c = _db()
        rows = c.execute(
            "SELECT q.* FROM wc_market_quotes q JOIN prop_games g ON g.id=q.prop_game_id "
            "WHERE g.league='wc' AND g.espn_event_id=? AND q.id=("
            "SELECT q2.id FROM wc_market_quotes q2 "
            "WHERE q2.prop_game_id=q.prop_game_id AND q2.source_outcome_id=q.source_outcome_id "
            "ORDER BY q2.captured_at DESC,q2.id DESC LIMIT 1) ORDER BY q.selection",
            (str(game_id),)).fetchall()
        for r in rows:
            history = c.execute(
                "SELECT odds FROM wc_market_quotes WHERE prop_game_id=? AND source_outcome_id=? "
                "ORDER BY captured_at DESC,id DESC LIMIT 2",
                (r["prop_game_id"], r["source_outcome_id"])).fetchall()
            opening = c.execute(
                "SELECT odds FROM wc_market_quotes WHERE prop_game_id=? AND source_outcome_id=? "
                "ORDER BY captured_at,id LIMIT 1",
                (r["prop_game_id"], r["source_outcome_id"])).fetchone()
            fresh = False
            try:
                seen = dt.datetime.fromisoformat(r["captured_at"].replace("Z", "+00:00"))
                fresh = (dt.datetime.now(dt.timezone.utc) - seen).total_seconds() <= 10 * 60
            except (TypeError, ValueError):
                pass
            team = next(
                (abbr for abbr, name in team_abbrs.items()
                 if name.lower() == r["selection"].lower()), None)
            board.append({
                "market_id": (f"bovada:{r['source_event_id']}:"
                              f"{r['source_market_id']}:{r['source_outcome_id']}"),
                "kind": "match",
                "team": team,
                "selection": r["selection"],
                "market": r["market"],
                "price": r["odds"],
                "implied_probability": _american_probability(r["odds"]),
                "previous_price": history[1]["odds"] if len(history) > 1 else None,
                "opening_price": opening["odds"] if opening else None,
                "source": "Bovada",
                "as_of": r["captured_at"],
                "tradable": event_state in ("pre", "in") and fresh and r["status"] == "O",
            })
        c.close()
    except Exception:
        pass
    return board


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
        current_entities = names["teams"] | set(names["last"])
        if (str(r.get("subject", "")).strip().lower() not in _GENERIC_SUBJ
                and not any(re.search(rf"\b{re.escape(entity)}\b", blob)
                            for entity in current_entities)):
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
            "direction": r.get("direction", ""),
            "strength": r.get("strength", 1),
            "ts": r.get("ts"),
        })
    kept.sort(key=lambda x: (x["strength"] or 1), reverse=True)
    return kept[:limit]


_read_cache = {}

_READ_SYS = (
    "You are a betting-desk analyst writing live in-match INTEL. Inputs: DATA (score, events, lineup — "
    "AUTHORITATIVE for all match facts), exact EVENT MARKET CANDIDATES, recent BROADCAST quotes, and a "
    "raw transcript tail (use only for the WHY / color). Produce 3-4 punchy lines. RULES: "
    "(1) Match facts (score, who scored/assisted, who started) come ONLY from DATA — NEVER from the "
    "transcript. "
    "(2) Commentary is natural conversation that mixes live action with BACKGROUND/history — read the "
    "FULL sentence in context; never state a historical detail (e.g. 'came off the bench in a prior "
    "round') as a fact about today's match. "
    "(3) A market play is OPTIONAL. Select one only when game-specific information in the reads makes "
    "that exact outcome more likely than it was immediately before and its current price appears not to "
    "fully reflect the change. It may be a team outcome or a named-player market. A low/high absolute "
    "price, a price dip, or generic praise is never enough. Do not mechanically buy bottoms or sell tops. "
    "If the market already moved with the information, is stale, or the evidence is weak, omit market_id. "
    "(4) Use ONLY a supplied market_id; never invent a selection, market, or price. Player markets are "
    "supplied only for players the reads actually name. "
    "(5) Flag where the NARRATIVE and the DATA disagree. "
    "Each line is a takeaway a bettor scans in ~2s; SYNTHESIZE, do not just quote. "
    'Return ONLY JSON: [{"headline":"...","evidence":"quote or stat","market_id":"optional exact id"}]. '
    "Max 4 items. headline <= 110 chars, no trailing period."
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
    "characters explaining what changed and why it matters, grounded ONLY in that excerpt; "
    "(3) market_id: optional. Choose one exact supplied candidate only when this is NEW, game-specific "
    "information that makes that outcome more likely than it was immediately before and its current "
    "price appears not to fully reflect that probability change. This can be a TEAM outcome or a named-"
    "player market. It does not need to be a prop. Do not attach a market merely because its absolute "
    "price is low/high, because it dipped, or because every card is expected to have a play. Never buy "
    "bottoms or sell tops mechanically. If the market already repriced, is stale, or no candidate is a "
    "real divergence, return an empty market_id. Commentary is natural conversation "
    "and may describe prior matches: preserve the full sentence's timeframe and NEVER turn history "
    "into a fact about today's match. Do not claim an outcome, score, lineup fact, or that the booth "
    "foreshadowed something unless the excerpt itself says so. Use ONLY an exact supplied market_id. "
    'Return ONLY JSON: [{"i":0,"headline":"...","analysis":"...","market_id":"or empty"}].'
)


def _fmt_odds(odds):
    try:
        value = int(odds)
        return f"+{value}" if value > 0 else str(value)
    except (TypeError, ValueError):
        return str(odds)


def _fmt_market_price(market, key="price"):
    value = market.get(key)
    if value is None:
        return None
    if market.get("source") == "Kalshi":
        return f"{round(float(value) * 100)}¢"
    return _fmt_odds(value)


def _market_prompt(market):
    current = _fmt_market_price(market)
    previous = _fmt_market_price(market, "previous_price")
    opening = _fmt_market_price(market, "opening_price")
    history = []
    if previous is not None:
        history.append(f"previous {previous}")
    if opening is not None:
        history.append(f"opening {opening}")
    trail = f"; {', '.join(history)}" if history else "; no earlier quote captured"
    return (f"[{market['market_id']}] {market['selection']} | {market['market']} | "
            f"current {current} at {market.get('source')}{trail}")


def _candidate_markets(insight, market_board, names, team_abbrs):
    """Markets causally adjacent to this excerpt; never hand the model unrelated longshots."""
    try:
        signal_time = dt.datetime.fromisoformat(insight.get("ts", "").replace("Z", "+00:00"))
        if (dt.datetime.now(dt.timezone.utc) - signal_time).total_seconds() > _SIGNAL_EDGE_WINDOW_MIN * 60:
            return []
    except (TypeError, ValueError):
        return []
    subject = (insight.get("subject") or "").strip().lower()
    quote = (insight.get("quote") or "").lower()
    mentioned_players = set()
    for player in names["full"]:
        last = player.split()[-1].lower()
        if subject == player.lower() or re.search(rf"\b{re.escape(last)}\b", quote):
            mentioned_players.add(player)

    subject_team = None
    for abbr, team_name in team_abbrs.items():
        if (subject in (abbr.lower(), team_name.lower())
                or re.search(rf"\b{re.escape(team_name.lower())}\b", subject)):
            subject_team = abbr
            break
    player_teams = {names["team_by_name"].get(player) for player in mentioned_players}
    player_teams.discard(None)

    candidates = []
    for market in market_board:
        if not market.get("tradable"):
            continue
        if market["kind"] == "player" and market["selection"] in mentioned_players:
            candidates.append(market)
        elif market["kind"] == "match":
            # Team-level reads can support either side (e.g. England retreating makes Argentina
            # more likely); a player read can support that player's own team as well as the prop.
            if subject_team or subject.lower() in _GENERIC_SUBJ:
                candidates.append(market)
            elif market.get("team") in player_teams:
                candidates.append(market)
    return candidates


def _resolve_opportunity(raw, allowed_ids, market_index):
    market_id = str(raw.get("market_id", "")).strip() if isinstance(raw, dict) else ""
    market = market_index.get(market_id)
    if not market or market_id not in allowed_ids or not market.get("tradable"):
        return None
    opportunity = {
        "market_id": market_id,
        "kind": market["kind"],
        "selection": market["selection"],
        "market": market["market"],
        "price": _fmt_market_price(market),
        "source": market["source"],
        "action": "back",
        "change": "more likely now",
    }
    previous = _fmt_market_price(market, "previous_price")
    if previous is not None and previous != opportunity["price"]:
        opportunity["previous_price"] = previous
    return opportunity


def _enrich_insights(insights, market_board, names, team_abbrs, cache_key):
    """Give every excerpt a takeaway; attach a grounded opportunity only when one exists."""
    if not insights:
        return insights
    market_index = {m["market_id"]: m for m in market_board}
    allowed_by_i = {
        i: _candidate_markets(x, market_board, names, team_abbrs)
        for i, x in enumerate(insights)
    }
    cards = _insight_cache.get(cache_key)
    if cards is None:
        rows = []
        for i, x in enumerate(insights):
            candidates = allowed_by_i[i]
            board = " || ".join(_market_prompt(m) for m in candidates) or "none"
            rows.append(f"{i}. [{x['tag']}/{x['subject']}/{x.get('direction','')}] "
                        f"QUOTE: {x['quote']} CANDIDATES: {board}")
        numbered = "\n".join(rows)
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
                            "market_id": str(it.get("market_id", ""))[:160],
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
        opportunity = _resolve_opportunity(
            card, {m["market_id"] for m in allowed_by_i[i]}, market_index)
        if opportunity:
            x["opportunity"] = opportunity
    return insights


def _synthesize_read(data_str, insights, market_board, names, team_abbrs, cache_key):
    """LLM synthesis of the reads + data → scannable intel lines (cached)."""
    if cache_key in _read_cache:
        return _read_cache[cache_key]
    if not insights:
        return []
    quotes = "\n".join(f"- [{i['tag']}/{i['subject']}] {i['quote']}" for i in insights[:18])
    allowed_markets = {}
    for insight in insights[:18]:
        for market in _candidate_markets(insight, market_board, names, team_abbrs):
            allowed_markets[market["market_id"]] = market
    board = "\n".join(f"- {_market_prompt(m)}" for m in allowed_markets.values()) or "- none"
    out = _deepseek(
        _READ_SYS,
        f"{data_str}\n\nExact event market candidates:\n{board}\n\nBroadcast reads:\n{quotes}")
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
                    opportunity = _resolve_opportunity(
                        it, set(allowed_markets), allowed_markets)
                    if opportunity:
                        card["opportunity"] = opportunity
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
    game_date = (comp.get("date") or "")[:10]
    date = game_date.replace("-", "")  # YYYYMMDD
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
    event_state = (comp.get("status", {}).get("type", {}) or {}).get("state", "")

    names = _roster_names(sm)
    insights_full = _broadcast_insights(tag, names, limit=40)
    scorers = _top_scorers(game_id, home_abbr, away_abbr)

    # live match stats → feed the synthesis so it can surface narrative-vs-data
    tstats = {}
    for t in sm.get("boxscore", {}).get("teams", []) or []:
        ab = (t.get("team", {}) or {}).get("abbreviation")
        tstats[ab] = {x.get("name"): x.get("displayValue") for x in t.get("statistics", []) or []}

    def _st(ab, k):
        return (tstats.get(ab) or {}).get(k, "—")

    events = _match_events(sm)
    away_sc, home_sc = away.get("score"), home.get("score")
    team_abbrs = {away_abbr: _name(away), home_abbr: _name(home)}
    player_board = _player_markets(game_id, event_state)
    scored_players = {e["players"][0] for e in events if e["scoring"] and e["players"]}
    for market in player_board:
        if market["market"] == "to score" and market["selection"] in scored_players:
            market["tradable"] = False
    match_board = _bovada_match_markets(game_id, event_state, team_abbrs)
    if not match_board:
        try:
            match_board = wc_event_markets(game_id, game_date)
        except Exception:
            match_board = []
    market_board = match_board + player_board
    market_key = tuple(
        (m["market_id"], m.get("price"), m.get("previous_price"), m.get("tradable"))
        for m in market_board)
    signal_key = tuple((i.get("ts"), i.get("subject"), i.get("quote")) for i in insights_full)
    insight_cache_key = ("v3", str(game_id), signal_key, market_key)
    insights_full = _enrich_insights(
        insights_full, market_board, names, team_abbrs, insight_cache_key)

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
        + f"Broadcast transcript (color/why only, may mix live action with history): {_transcript_tail(tag)}"
    )
    cache_key = ("v3", str(game_id), signal_key, f"{away_sc}-{home_sc}", len(events), market_key)
    read = _synthesize_read(
        data_str, insights_full, market_board, names, team_abbrs, cache_key)

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
