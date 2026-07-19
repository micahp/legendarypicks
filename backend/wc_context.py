"""wc_context.py — build the "Game Context" summary for a WC game detail page.

Blends three sources into one fan-legible object:
  1. Form + status (ESPN scoreboard/summary).
  2. Most-likely goalscorer PER TEAM (shortest anytime-goal odds from our WC props).
  3. The broadcast's soft reads (the whisper pipeline's signals jsonl), relevance-filtered.

POC for ARG–ENG (2026-07-15). The signals file is written by
prediction-market-trading/broadcast_alpha.py; we read it cross-repo.
"""
import datetime as dt
import difflib
import hashlib
import json
import os
import re
import sqlite3
import time
import unicodedata
import urllib.request
from collections import OrderedDict

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
# Content that is never match analysis. Team and player names deliberately do
# not live here: the original ARG-ENG proof of concept put ``spain`` in this
# list and consequently deleted Spain from the ARG-ESP final.
_JUNK_KW = ("brady", "senate", "bulger", "podcast", "iheart", "dirty rats",
            "honorary", "nfl", "touchdown")

_GENERIC_SUBJ = {"game", "match", "both teams", "teams", "players",
                 "home team", "away team", "the team"}

_CACHE_MAX = 128
_BRACKET_TTL_SECONDS = 120
_bracket_cache = {"expires_at": 0.0, "data": {"rounds": []}}


def _plain(value):
    """Accent-insensitive lowercase text for identity/filter comparisons."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join(
        re.sub(r"[^a-z0-9]+", " ", text.encode("ascii", "ignore").decode().lower()).split()
    )


def _roster_names(sm):
    """Roster identity map for this match, built only from ESPN's team sheet."""
    full, last = [], {}
    for team in sm.get("rosters", []) or []:
        for r in team.get("roster", []) or []:
            nm = (r.get("athlete", {}) or {}).get("displayName")
            if nm:
                full.append(nm)
                toks = nm.split()
                if toks:
                    last[_plain(toks[-1])] = nm
    return {"full": full, "last": last}


def _team_aliases(*competitors):
    """Canonical names/abbreviations for the two teams in this match."""
    aliases = set()
    for competitor in competitors:
        team = (competitor or {}).get("team", {}) or {}
        for key in ("displayName", "shortDisplayName", "name", "abbreviation"):
            value = _plain(team.get(key))
            if value:
                aliases.add(value)
    return aliases


def _match_identities(names, team_aliases):
    """Subjects allowed to become match-specific booth cards.

    Unknown named subjects fail closed. That keeps other-match players and
    teams out without another hardcoded tournament list, while fuzzy roster
    normalization still rescues ordinary ASR misspellings.
    """
    roster = {_plain(name) for name in names.get("full", []) if name}
    roster.update(names.get("last", {}).keys())
    return {
        "subjects": set(team_aliases) | roster,
        "generic": set(_GENERIC_SUBJ) | set(team_aliases),
    }


def _normalize_subject(subj, names, generic_subjects=None):
    """Map a whisper-mangled subject to a real roster name (Jett Spence→Djed
    Spence, jute Bellingham→Jude Bellingham). Team/generic subjects pass through."""
    s = (subj or "").strip()
    generic_subjects = generic_subjects or _GENERIC_SUBJ
    if not s or _plain(s) in generic_subjects:
        return s
    last = names["last"]
    toks = s.split()
    if toks:
        lt = _plain(toks[-1])
        if lt in last:
            return last[lt]
        m = difflib.get_close_matches(lt, list(last.keys()), n=1, cutoff=0.72)
        if m:
            return last[m[0]]
    m = difflib.get_close_matches(s, names["full"], n=1, cutoff=0.72)
    return m[0] if m else s


def _subject_is_grounded(subject, identities):
    normalized = _plain(subject)
    return (
        not normalized
        or normalized in identities["generic"]
        or normalized in identities["subjects"]
    )


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


def _content_hash(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_get(cache, key):
    value = cache.get(key)
    if value is not None:
        cache.move_to_end(key)
    return value


def _cache_put(cache, key, value):
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > _CACHE_MAX:
        cache.popitem(last=False)


def _world_cup_bracket():
    """Reuse the canonical bracket contract, retaining the last good snapshot."""
    now = time.monotonic()
    if _bracket_cache["expires_at"] > now:
        return _bracket_cache["data"]
    try:
        data = espn.wc_knockout_standings()
        if isinstance(data, dict) and isinstance(data.get("rounds"), list):
            _bracket_cache["data"] = data
            _bracket_cache["expires_at"] = now + _BRACKET_TTL_SECONDS
            return data
    except Exception:
        pass
    # Avoid hammering ESPN every 30 seconds during an outage. A previously
    # verified snapshot is preferable to deleting history from an open page.
    _bracket_cache["expires_at"] = now + 30
    return _bracket_cache["data"]


def _parse_datetime(value):
    try:
        parsed = dt.datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def _tournament_history(bracket, game_id, kickoff, home_abbr, away_abbr):
    """Route-to-game context from the existing canonical WC bracket contract."""
    current_at = _parse_datetime(kickoff)
    rows = []
    for round_blob in (bracket or {}).get("rounds", []) or []:
        for match in round_blob.get("matches", []) or []:
            when = _parse_datetime(match.get("date"))
            if str(match.get("game_id")) == str(game_id):
                current_at = when or current_at
                continue
            if current_at and (when is None or when >= current_at):
                continue
            rows.append({**match, "round": round_blob.get("round"), "_when": when})

    teams = {}
    for abbr in (away_abbr, home_abbr):
        route = []
        for match in rows:
            home = match.get("home") or {}
            away = match.get("away") or {}
            if abbr not in {home.get("abbrev"), away.get("abbrev")}:
                continue
            mine = home if home.get("abbrev") == abbr else away
            opponent = away if mine is home else home
            score_for = match.get("homeScore") if mine is home else match.get("awayScore")
            score_against = match.get("awayScore") if mine is home else match.get("homeScore")
            status = str(match.get("status") or "")
            extra_time = status in {"STATUS_FINAL_AET", "STATUS_FINAL_PEN"}
            route.append({
                "game_id": str(match.get("game_id") or ""),
                "round": match.get("round"),
                "date": match.get("date"),
                "opponent": {"abbr": opponent.get("abbrev"), "name": opponent.get("name")},
                "score_for": score_for,
                "score_against": score_against,
                "result": "W" if match.get("winner") == abbr else "L",
                "extra_time": extra_time,
                "penalties": status == "STATUS_FINAL_PEN",
                "_when": match.get("_when"),
            })
        route.sort(key=lambda row: row.get("_when") or dt.datetime.min.replace(tzinfo=dt.timezone.utc))
        last_at = route[-1].get("_when") if route else None
        rest_days = None
        if current_at and last_at:
            rest_days = max(0, int((current_at - last_at).total_seconds() // 86400))
        extra_time_matches = sum(1 for row in route if row["extra_time"])
        for row in route:
            row.pop("_when", None)
        teams[abbr] = {
            "rest_days": rest_days,
            "extra_time_matches": extra_time_matches,
            "extra_time_minutes": extra_time_matches * 30,
            "matches": route[-4:],
        }

    h2h = []
    for match in rows:
        pair = {
            (match.get("home") or {}).get("abbrev"),
            (match.get("away") or {}).get("abbrev"),
        }
        if pair == {home_abbr, away_abbr}:
            h2h.append({
                "game_id": str(match.get("game_id") or ""),
                "round": match.get("round"),
                "date": match.get("date"),
                "home": match.get("home"),
                "away": match.get("away"),
                "home_score": match.get("homeScore"),
                "away_score": match.get("awayScore"),
                "winner": match.get("winner"),
            })
    return {"teams": teams, "head_to_head": h2h[-3:]}


_MATCH_STAT_FIELDS = (
    ("possessionPct", "Possession", "%"),
    ("totalShots", "Shots", ""),
    ("shotsOnTarget", "On target", ""),
    ("wonCorners", "Corners", ""),
)


def _visible_match_stats(team_stats, away_abbr, home_abbr):
    rows = []
    for key, label, unit in _MATCH_STAT_FIELDS:
        away = (team_stats.get(away_abbr) or {}).get(key)
        home = (team_stats.get(home_abbr) or {}).get(key)
        if away is None and home is None:
            continue
        rows.append({"key": key, "label": label, "unit": unit, "away": away, "home": home})
    return rows


def _broadcast_insights(tag, names, team_aliases, limit=8):
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
    identities = _match_identities(names, team_aliases)
    kept, seen = [], set()
    for r in rows:
        blob = (str(r.get("subject", "")) + " " + str(r.get("quote") or "")).lower()
        if any(k in blob for k in _JUNK_KW):
            continue
        quote = r.get("quote", "").strip()
        if not quote or len(quote) < 25:
            continue
        subject = _normalize_subject(
            str(r.get("subject", "")).strip(), names, identities["generic"]
        )
        if not _subject_is_grounded(subject, identities):
            continue
        # dedup on the quote itself → collapses repeats + same quote under two subjects
        qk = re.sub(r"[^a-z0-9]", "", quote.lower())[:50]
        if qk in seen:
            continue
        seen.add(qk)
        ts = r.get("ts")
        kept.append({
            "id": _content_hash({"tag": tag, "subject": subject, "quote": quote, "ts": ts})[:16],
            "tag": _TAG_LABEL.get(r.get("type"), "Read"),
            "subject": subject,
            "quote": quote if len(quote) <= 180 else quote[:177].rstrip() + "…",
            "strength": r.get("strength", 1),
            "ts": ts,
        })
    # A live feed must visibly move. Newest evidence leads; strength breaks ties.
    kept.sort(key=lambda x: (x.get("ts") or "", x.get("strength") or 1), reverse=True)
    return kept[:limit]


_read_cache = OrderedDict()

_READ_SYS = (
    "You are a betting-desk analyst writing live in-match INTEL. Inputs are numbered FACTS (ESPN match "
    "facts, route history, and market lines) and numbered BOOTH quotes (commentary/color, never an "
    "authoritative match fact). "
    "Produce 3-4 punchy intel lines. A line MAY carry an optional 'play', but MOST lines should NOT — "
    "plays are rare and high-conviction. "
    "WHAT A PLAY IS — a DISCOUNT: an outcome the market prices as UNLIKELY (a longish price) that the "
    "booth's NEW INFORMATION makes MORE LIKELY than the line implies (the market underweights the new "
    "info). A play is a PLAYER (to score) OR a TEAM (to win / draw). Example: team trailing, their "
    "'to win' line has drifted long, but the booth shows real momentum/a man advantage the price hasn't "
    "caught → back that team to win at the discount. "
    "RULES: "
    "(1) Match facts come ONLY from FACTS, never BOOTH. Read full-sentence context; never turn "
    "background/history into a fact about today's match. "
    "(2) A play needs CONFLUENCE: a genuine market discount AND a specific booth signal the price hasn't "
    "absorbed. This is buying an info-backed VALUE discount — NOT backing favorites, NOT 'the price "
    "looks low/high', NOT a play with no informational reason. If the market is pricing it correctly (a "
    "value trap), NO play. "
    "(3) Player plays: only a player the booth discussed BY NAME. Team plays: only the two teams or 'Draw'. "
    "(4) Flag where the NARRATIVE and the FACTS disagree. "
    "(5) Every line must cite 1-3 evidence_refs using only supplied IDs (F0, F1, B0, B1, etc). Never "
    "write 'DATA shows'; state the takeaway and let the cited evidence establish its source. Do not "
    "introduce a number that is absent from the cited evidence. "
    "Each line is a takeaway a bettor scans in ~2s; SYNTHESIZE, do not just quote. "
    'Return ONLY JSON: [{"headline":"...","evidence_refs":["F0","B1"],'
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


_insight_cache = OrderedDict()
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


def _numeric_tokens(value):
    return set(re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?%?", str(value or "")))


def _strip_data_framing(headline):
    return re.sub(
        r"^\s*(?:the\s+)?data\s+(?:shows?|says?|indicates?|confirms?|suggests?)\s+",
        "",
        str(headline or ""),
        flags=re.I,
    ).strip()


def _enrich_insights(insights, goals_market, cache_key):
    """Give every booth excerpt its own takeaway, analysis, and grounded prop lean."""
    if not insights:
        return insights
    cards = _cache_get(_insight_cache, cache_key)
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
        _cache_put(_insight_cache, cache_key, cards)
    for i, x in enumerate(insights):
        card = cards.get(i)
        if not card:
            continue
        # The enrichment model only saw this quote. Reject any new numeric fact
        # instead of letting a generated analysis turn commentary into data.
        generated_numbers = _numeric_tokens(card["headline"] + " " + card["analysis"])
        if not generated_numbers.issubset(_numeric_tokens(x["quote"])):
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
        subj = _plain(i.get("subject"))
        toks = subj.split()
        if toks and toks[-1] in lastmap:
            allowed.add(toks[-1])
    return allowed


def _synthesize_read(facts, insights, cache_key, market_lines=None):
    """Synthesize a read whose displayed evidence is always an exact source receipt."""
    cached = _cache_get(_read_cache, cache_key)
    if cached is not None:
        return cached
    if not insights:
        return []
    refs = {}
    fact_lines = []
    for index, fact in enumerate(facts):
        ref = f"F{index}"
        refs[ref] = {"kind": "fact", "text": str(fact)}
        fact_lines.append(f"{ref}: {fact}")
    quote_lines = []
    for index, insight in enumerate(insights[:18]):
        ref = f"B{index}"
        refs[ref] = {"kind": "booth", "text": insight["quote"]}
        quote_lines.append(
            f"{ref}: [{insight['tag']}/{insight['subject']}] {insight['quote']}"
        )
    prompt = "FACTS:\n" + "\n".join(fact_lines) + "\n\nBOOTH:\n" + "\n".join(quote_lines)
    out = _deepseek(_READ_SYS, prompt)
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
                    evidence_refs = it.get("evidence_refs") or []
                    if not isinstance(evidence_refs, list):
                        continue
                    selected_refs = []
                    for ref in evidence_refs[:3]:
                        key = str(ref).upper()
                        if key in refs and key not in selected_refs:
                            selected_refs.append(key)
                    if not selected_refs:
                        continue
                    headline = _strip_data_framing(str(it["headline"]))[:140]
                    evidence_numbers = set()
                    for ref in selected_refs:
                        evidence_numbers.update(_numeric_tokens(refs[ref]["text"]))
                    if not _numeric_tokens(headline).issubset(evidence_numbers):
                        continue
                    kinds = {refs[ref]["kind"] for ref in selected_refs}
                    source = "combined" if len(kinds) > 1 else next(iter(kinds))
                    evidence = []
                    for ref in selected_refs:
                        receipt = refs[ref]
                        prefix = "ESPN/market" if receipt["kind"] == "fact" else "Booth"
                        evidence.append(f"{prefix}: {receipt['text']}")
                    card = {
                        "headline": headline,
                        "evidence": " · ".join(evidence)[:420],
                        "source": source,
                        "evidence_refs": selected_refs,
                    }
                    p = it.get("prop")
                    if isinstance(p, dict) and p.get("player"):
                        market = (market_lines or {}).get(_plain(p.get("player")))
                        lean = str(p.get("lean", "watch")).lower()
                        if market and lean in {"back", "fade", "watch"}:
                            card["prop"] = {
                                "player": market["player"],
                                "market": market["market"],
                                "line": market["line"],
                                "lean": lean,
                            }
                    read.append(card)
        except Exception:
            read = []
    _cache_put(_read_cache, cache_key, read)
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
    aliases = _team_aliases(home, away)
    bracket = _world_cup_bracket()
    history = _tournament_history(
        bracket, game_id, comp.get("date"), home_abbr, away_abbr
    )
    insights_full = _broadcast_insights(tag, names, aliases, limit=40)
    raw_insight_hash = _content_hash([
        {key: insight.get(key) for key in ("id", "tag", "subject", "quote", "strength", "ts")}
        for insight in insights_full
    ])
    allowed_players = _signal_subjects(insights_full, names)
    scorers = _top_scorers(game_id, home_abbr, away_abbr)

    # live match stats → feed the synthesis so it can surface narrative-vs-data
    tstats = {}
    for t in sm.get("boxscore", {}).get("teams", []) or []:
        ab = (t.get("team", {}) or {}).get("abbreviation")
        tstats[ab] = {x.get("name"): x.get("displayValue") for x in t.get("statistics", []) or []}

    def _st(ab, k):
        return (tstats.get(ab) or {}).get(k, "—")

    away_sc, home_sc = away.get("score"), home.get("score")
    match_stats = _visible_match_stats(tstats, away_abbr, home_abbr)
    goals_mkt = _goals_market(game_id)
    team_odds = _team_odds(sm, _name(home), _name(away))
    insight_cache_key = (
        "v3", str(game_id), raw_insight_hash, _content_hash(sorted(goals_mkt.items()))
    )
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
                f"(on target {_st(ab,'shotsOnTarget')}), form {_form(t) or 'unavailable'}")

    facts = [
        f"MATCH ({status}): {_name(away)} {away_sc} - {home_sc} {_name(home)}",
        f"Score events: {ev_str}",
        _team_line(away, away_abbr, "away"),
        _team_line(home, home_abbr, "home"),
    ]
    for abbr, team_name in ((away_abbr, _name(away)), (home_abbr, _name(home))):
        route = (history.get("teams") or {}).get(abbr) or {}
        route_matches = route.get("matches") or []
        if route_matches:
            route_text = "; ".join(
                f"{row.get('round')}: {row.get('result')} {row.get('score_for')}-{row.get('score_against')} "
                f"vs {(row.get('opponent') or {}).get('name')}"
                + (" after extra time" if row.get("extra_time") else "")
                for row in route_matches
            )
            rest = route.get("rest_days")
            extra = route.get("extra_time_minutes") or 0
            facts.append(
                f"{team_name} route before this match: {route_text}; "
                f"{rest} full days since the previous match; {extra} verified extra-time minutes"
            )
    if board_str:
        facts.append(f"Bovada anytime-goalscorer board: {board_str}")
    if team_odds:
        facts.append(
            "Match-result moneyline: "
            + ", ".join(f"{name} {_fmt_odds(odds)}" for name, odds in team_odds.items())
        )

    market_lines = {}
    for player, odds in goals_mkt.items():
        last = _plain(player).split()[-1] if _plain(player).split() else ""
        if last in allowed_players:
            market_lines[_plain(player)] = {
                "player": player, "market": "to score", "line": _fmt_odds(odds)
            }
    for selection, odds in team_odds.items():
        market = {
            "player": selection, "market": "to win" if selection != "Draw" else "draw",
            "line": _fmt_odds(odds),
        }
        market_lines[_plain(selection)] = market
        if selection == _name(home):
            market_lines[_plain(home_abbr)] = market
        elif selection == _name(away):
            market_lines[_plain(away_abbr)] = market

    read_cache_key = (
        "v3", str(game_id), raw_insight_hash,
        _content_hash({"facts": facts, "markets": market_lines}),
    )
    read = _synthesize_read(facts, insights_full, read_cache_key, market_lines=market_lines)
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat()

    return {
        "game_id": str(game_id),
        "headline": f"{_name(away)} at {_name(home)}",
        "status": status,
        "teams": {
            "home": {"abbr": home_abbr, "name": _name(home), "form": _form(home)},
            "away": {"abbr": away_abbr, "name": _name(away), "form": _form(away)},
        },
        "top_scorers": scorers,
        "match_stats": match_stats,
        "history": history,
        "read": read,
        "insights": insights_full[:limit],
        "latest_booth_at": insights_full[0].get("ts") if insights_full else None,
        "generated_at": generated_at,
        "social_sentiment": {
            "status": "unavailable",
            "reason": "No validated social-sentiment source is connected; social claims are omitted.",
        },
        "sources": {
            "match_and_stats": "ESPN summary",
            "history": "ESPN World Cup bracket" if (history.get("teams") or {}) else None,
            "market": "Bovada props + ESPN pickcenter",
            "booth": os.path.basename(os.path.join(BROADCAST_DIR, f"{tag}_signals.jsonl")),
            "social": None,
        },
        "limitations": [
            "Broadcast observations are commentary receipts, not authoritative match facts.",
            "Social sentiment is omitted until a validated, timestamped source is connected.",
        ],
        "source": "ESPN facts + bracket history + market + broadcast",
    }
