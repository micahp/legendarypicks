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
from collections import OrderedDict, defaultdict

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
_MARKET_QUOTE_STALE_AFTER_SECONDS = 90
_BOOTH_STALE_AFTER_SECONDS = 180
_EPISODE_WINDOW_SECONDS = 20 * 60
_MAX_EPISODE_RECEIPTS = 3
_bracket_cache = {"expires_at": 0.0, "data": {"rounds": []}}
_episode_detail_cache = OrderedDict()


def _plain(value):
    """Accent-insensitive lowercase text for identity/filter comparisons."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join(
        re.sub(r"[^a-z0-9]+", " ", text.encode("ascii", "ignore").decode().lower()).split()
    )


def _roster_names(sm, canonical_teams=None):
    """Roster identity map for this match, built only from ESPN's team sheet.

    Surnames deliberately map to *all* matching players. A single-value surname
    map silently turned Lisandro Martinez into Lautaro Martinez in the final.
    """
    full, players = [], []
    by_alias, last = defaultdict(list), defaultdict(list)
    canonical_teams = canonical_teams or {}
    for team in sm.get("rosters", []) or []:
        team_blob = team.get("team", {}) or {}
        team_abbr = str(team_blob.get("abbreviation") or "")
        team_name = canonical_teams.get(team_abbr) or team_blob.get("displayName") or team_abbr
        for r in team.get("roster", []) or []:
            athlete = r.get("athlete", {}) or {}
            nm = athlete.get("displayName")
            if nm:
                full.append(nm)
                aliases = []
                for key in ("displayName", "fullName", "shortName"):
                    alias = str(athlete.get(key) or "").strip()
                    if alias and _plain(alias) not in {_plain(value) for value in aliases}:
                        aliases.append(alias)
                player = {
                    "id": str(athlete.get("id") or "") or None,
                    "name": nm,
                    "team_abbr": team_abbr or None,
                    "team_name": team_name or None,
                    "aliases": aliases,
                }
                players.append(player)
                for alias in aliases:
                    by_alias[_plain(alias)].append(player)
                toks = nm.split()
                if toks:
                    last[_plain(toks[-1])].append(player)
    return {
        "full": full,
        "players": players,
        "by_alias": dict(by_alias),
        "last": dict(last),
        "teams": dict(canonical_teams),
    }


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


def _team_subjects(*competitors):
    """All current-team aliases mapped to one canonical team subject."""
    subjects = {}
    for competitor in competitors:
        team = (competitor or {}).get("team", {}) or {}
        abbr = str(team.get("abbreviation") or "")
        name = str(team.get("displayName") or team.get("name") or abbr)
        entry = {
            "name": name,
            "subject_id": f"team:{abbr or _plain(name)}",
            "subject_kind": "team",
            "team_abbr": abbr or None,
        }
        for key in ("displayName", "shortDisplayName", "name", "abbreviation"):
            alias = _plain(team.get(key))
            if alias:
                subjects[alias] = entry
    return subjects


def _candidate_rows(value):
    """Read both the v2 collision-safe roster map and old unit-test fixtures."""
    if value is None:
        return []
    if isinstance(value, str):
        return [{"id": None, "name": value, "team_abbr": None, "team_name": None, "aliases": [value]}]
    if isinstance(value, dict):
        return [value]
    return [row for row in value if isinstance(row, dict)]


def _player_resolution(player, status, raw):
    player_id = player.get("id")
    return {
        "name": player.get("name") or raw,
        "subject_id": f"player:{player_id}" if player_id else f"player-name:{_plain(player.get('name'))}",
        "subject_kind": "player",
        "subject_resolution": status,
        "subject_raw": raw,
        "team_abbr": player.get("team_abbr"),
        "team_name": player.get("team_name"),
        "espn_id": player_id,
    }


def _team_fallback(candidates, names, raw):
    teams = {row.get("team_abbr") for row in candidates if row.get("team_abbr")}
    if len(teams) != 1:
        return None
    abbr = next(iter(teams))
    name = (names.get("teams") or {}).get(abbr) or candidates[0].get("team_name") or abbr
    return {
        "name": name,
        "subject_id": f"team:{abbr}",
        "subject_kind": "team",
        "subject_resolution": "ambiguous_team_fallback",
        "subject_raw": raw,
        "team_abbr": abbr,
        "team_name": name,
        "ambiguous_players": [row.get("name") for row in candidates if row.get("name")],
    }


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


def _resolve_subject(subj, names, generic_subjects=None, team_subjects=None):
    """Resolve a signal subject without guessing across same-surname players.

    Exact full aliases win. A unique surname or unambiguous fuzzy alias may be
    rescued. If several players in the same team share the surname, the signal
    falls back to that team; it never inherits one of their player props.
    """
    s = str(subj or "").strip()
    plain = _plain(s)
    generic_subjects = generic_subjects or _GENERIC_SUBJ
    team_subjects = team_subjects or {}
    if plain in team_subjects:
        return {
            **team_subjects[plain],
            "subject_resolution": "exact_team",
            "subject_raw": s,
            "team_name": team_subjects[plain].get("name"),
        }
    if not s or plain in generic_subjects:
        return {
            "name": s,
            "subject_id": f"match:{plain or 'unknown'}",
            "subject_kind": "match",
            "subject_resolution": "generic",
            "subject_raw": s,
            "team_abbr": None,
            "team_name": None,
        }

    exact = _candidate_rows((names.get("by_alias") or {}).get(plain))
    if not exact:
        # Compatibility with older fixtures that only provide ``full``.
        exact = [
            {"id": None, "name": value, "team_abbr": None, "team_name": None, "aliases": [value]}
            for value in names.get("full", [])
            if _plain(value) == plain
        ]
    if len(exact) == 1:
        return _player_resolution(exact[0], "exact_player", s)
    if len(exact) > 1:
        fallback = _team_fallback(exact, names, s)
        if fallback:
            return fallback

    toks = plain.split()
    surname = toks[-1] if toks else ""
    surname_candidates = _candidate_rows((names.get("last") or {}).get(surname))
    if len(surname_candidates) == 1:
        return _player_resolution(surname_candidates[0], "unique_surname", s)
    if len(surname_candidates) > 1:
        fallback = _team_fallback(surname_candidates, names, s)
        if fallback:
            return fallback
        return {
            "name": s,
            "subject_id": None,
            "subject_kind": "unresolved",
            "subject_resolution": "ambiguous",
            "subject_raw": s,
            "team_abbr": None,
            "team_name": None,
        }

    # Rescue ordinary ASR misspellings only when the winning alias is unique
    # and meaningfully clearer than the runner-up.
    alias_map = names.get("by_alias") or {
        _plain(value): [{"id": None, "name": value, "aliases": [value]}]
        for value in names.get("full", [])
    }
    scored = sorted(
        ((difflib.SequenceMatcher(None, plain, alias).ratio(), alias)
         for alias, rows in alias_map.items() if len(_candidate_rows(rows)) == 1),
        reverse=True,
    )
    if scored and scored[0][0] >= 0.72 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.08):
        return _player_resolution(
            _candidate_rows(alias_map[scored[0][1]])[0], "fuzzy_player", s
        )
    return {
        "name": s,
        "subject_id": None,
        "subject_kind": "unresolved",
        "subject_resolution": "unresolved",
        "subject_raw": s,
        "team_abbr": None,
        "team_name": None,
    }


def _player_mentioned_in_quote(quote, names):
    """Return one exact full-name roster mention, never a surname-only guess."""
    normalized = f" {_plain(quote)} "
    found = {}
    for alias, value in (names.get("by_alias") or {}).items():
        if len(alias.split()) < 2 or f" {alias} " not in normalized:
            continue
        candidates = _candidate_rows(value)
        if len(candidates) != 1:
            continue
        row = candidates[0]
        found[row.get("id") or _plain(row.get("name"))] = row
    return next(iter(found.values())) if len(found) == 1 else None


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


def _quote_state(price_as_of, now=None):
    current = now or dt.datetime.now(dt.timezone.utc)
    captured = _parse_datetime(price_as_of)
    if not captured:
        return "unavailable", None
    age = max(0, int((current - captured).total_seconds()))
    return (
        "stale" if age > _MARKET_QUOTE_STALE_AFTER_SECONDS else "current",
        age,
    )


def _top_scorers(game_id, home_abbr, away_abbr, now=None):
    """Fresh shortest anytime-goalscorer quote per team.

    Old Bovada captures are not presented as a live recommendation. The full
    props tab remains the historical/detail surface.
    """
    out = []
    try:
        c = _db()
        for abbr in (away_abbr, home_abbr):  # away first (matchup reads "A @ H")
            r = c.execute(
                "SELECT pl.id AS player_id, pl.espn_id, pl.name, p.odds, p.source, "
                "COALESCE(p.odds_captured_at,p.captured_at) AS price_as_of FROM props p "
                "JOIN prop_games g ON p.game_id=g.id "
                "JOIN players pl ON p.player_id=pl.id "
                "WHERE g.league='wc' AND g.espn_event_id=? "
                "AND p.market='goals' AND pl.team=? AND p.odds IS NOT NULL "
                "ORDER BY COALESCE(p.odds_captured_at,p.captured_at) DESC, p.odds ASC LIMIT 1",
                (str(game_id), abbr)).fetchone()
            if r:
                quote_status, quote_age = _quote_state(r["price_as_of"], now=now)
                if quote_status == "current":
                    out.append({
                        "team": abbr,
                        "player_id": r["player_id"],
                        "espn_id": r["espn_id"],
                        "player": r["name"],
                        "odds": r["odds"],
                        "price_as_of": r["price_as_of"],
                        "quote_status": quote_status,
                        "quote_age_seconds": quote_age,
                        "quote_source": r["source"] or "Bovada",
                    })
        c.close()
    except Exception:
        pass
    return out


def _goals_market(game_id, now=None):
    """Latest timestamped anytime-goalscorer record for every player."""
    m = {}
    try:
        c = _db()
        for r in c.execute(
                "SELECT pl.id AS player_id, pl.espn_id, pl.name, pl.team, p.odds, p.source, "
                "COALESCE(p.odds_captured_at,p.captured_at) AS price_as_of FROM props p "
                "JOIN prop_games g ON p.game_id=g.id JOIN players pl ON p.player_id=pl.id "
                "WHERE g.league='wc' AND g.espn_event_id=? "
                "AND p.market='goals' AND p.odds IS NOT NULL "
                "ORDER BY COALESCE(p.odds_captured_at,p.captured_at),p.id",
                (str(game_id),)).fetchall():
            quote_status, quote_age = _quote_state(r["price_as_of"], now=now)
            m[r["name"]] = {
                "player_id": r["player_id"],
                "espn_id": str(r["espn_id"] or "") or None,
                "player": r["name"],
                "team": r["team"],
                "market": "to score",
                "odds": r["odds"],
                "line": _fmt_odds(r["odds"]),
                "price_as_of": r["price_as_of"],
                "quote_status": quote_status,
                "quote_age_seconds": quote_age,
                "quote_source": r["source"] or "Bovada",
            }
        c.close()
    except Exception:
        pass
    return m


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


_HISTORICAL_CUES = (
    r"\b(?:last|previous|prior) (?:game|match|round|half|season)\b",
    r"\b(?:semi[- ]?final|quarter[- ]?final|round of \d+)\b",
    r"\bagainst [a-z]", r"\bas [a-z ]+ found out\b",
    r"\b(?:in|during) the spring\b", r"\bcoming into (?:this|the) (?:game|match)\b",
    r"\bthis (?:knockout round|tournament)\b", r"\bwe (?:ve|have) seen\b",
    r"\b(?:ever played|has never lost|have never lost|unbeaten)\b",
    r"\b(?:goals?|games?) after the \d+", r"\b\d+ of (?:their )?\d+ goals\b",
    r"\bused to\b", r"\bcareer\b", r"\bpregame\b",
)
_CURRENT_CUES = (
    r"\bright now\b", r"\bso far\b", r"\bat the moment\b", r"\bthis match\b",
    r"\bthis game\b", r"\bthis (?:first|second) half\b", r"\btoday\b", r"\btonight\b",
)


def _time_scope(quote):
    """Separate a live observation from history mentioned during the broadcast."""
    text = _plain(quote)
    historical = any(re.search(pattern, text, re.I) for pattern in _HISTORICAL_CUES)
    current = any(re.search(pattern, text, re.I) for pattern in _CURRENT_CUES)
    if historical and current:
        return "mixed"
    if historical:
        return "historical_reference"
    return "current_match"


def _broadcast_rows(tag):
    path = os.path.join(BROADCAST_DIR, f"{tag}_signals.jsonl")
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def _broadcast_insights(tag, names, team_aliases, limit=None, rows=None, team_subjects=None):
    """Ground every relevant booth observation before collapsing it into episodes."""
    rows = list(rows) if rows is not None else _broadcast_rows(tag)
    identities = _match_identities(names, team_aliases)
    kept, seen = [], set()
    for r in rows:
        blob = (str(r.get("subject", "")) + " " + str(r.get("quote") or "")).lower()
        if any(k in blob for k in _JUNK_KW):
            continue
        quote = r.get("quote", "").strip()
        if not quote or len(quote) < 25:
            continue
        resolved = _resolve_subject(
            str(r.get("subject", "")).strip(), names, identities["generic"], team_subjects
        )
        mentioned = _player_mentioned_in_quote(quote, names)
        if mentioned and resolved.get("subject_kind") != "player":
            resolved = _player_resolution(mentioned, "exact_quote_mention", resolved.get("subject_raw"))
        subject = resolved.get("name") or ""
        if not _subject_is_grounded(subject, identities):
            continue
        # Exact quote repeats are one observation. Semantic overlap is collapsed
        # later at the episode layer, where the receipt count remains visible.
        qk = _plain(quote)
        if qk in seen:
            continue
        seen.add(qk)
        ts = r.get("ts")
        kept.append({
            "id": _content_hash({"tag": tag, "subject": subject, "quote": quote, "ts": ts})[:16],
            "tag": _TAG_LABEL.get(r.get("type"), "Read"),
            "subject": subject,
            "quote": quote if len(quote) <= 420 else quote[:417].rstrip() + "…",
            "strength": r.get("strength", 1),
            "ts": ts,
            "time_scope": _time_scope(quote),
            **{key: value for key, value in resolved.items() if key != "name"},
        })
    # A live feed must visibly move. Newest evidence leads; strength breaks ties.
    kept.sort(key=lambda x: (x.get("ts") or "", x.get("strength") or 1), reverse=True)
    return kept if limit is None else kept[:limit]


def _annotate_match_phases(insights, kickoff, status):
    """Assign broad match phases without inventing an exact game clock.

    The broadcast source only timestamps wall time. A clear mid-match silence
    identifies halftime; otherwise phase labels stay conservative.
    """
    kickoff_at = _parse_datetime(kickoff)
    parsed = sorted(
        ((stamp, row) for row in insights if (stamp := _parse_datetime(row.get("ts")))),
        key=lambda pair: pair[0],
    )
    halftime_gap = None
    if kickoff_at:
        eligible = []
        for (left, _), (right, _) in zip(parsed, parsed[1:]):
            gap = (right - left).total_seconds()
            if left >= kickoff_at + dt.timedelta(minutes=30) and gap >= 8 * 60:
                eligible.append((gap, left, right))
        if eligible:
            _, gap_start, gap_end = max(eligible)
            halftime_gap = (gap_start, gap_end)

    status_text = str(status or "").upper()
    current_phase = "pregame"
    for stamp, row in parsed:
        if kickoff_at and stamp < kickoff_at:
            phase = "pregame"
        elif halftime_gap and stamp <= halftime_gap[0]:
            phase = "first_half"
        elif halftime_gap and stamp < halftime_gap[1]:
            phase = "halftime"
        elif halftime_gap:
            phase = "second_half"
        elif "HALF" in status_text or status_text == "HT":
            phase = "first_half"
        elif re.match(r"^(?:[4-9]\d|1\d\d)'", status_text):
            phase = "second_half"
        else:
            phase = "first_half" if kickoff_at else "live"
        row["phase"] = phase
        current_phase = phase
    return current_phase


def _current_phase(status, derived_phase):
    normalized = _plain(status)
    if normalized in {"ht", "half time", "halftime"}:
        return "halftime"
    if normalized in {"ft", "full time", "final"} or normalized.startswith("final "):
        return "final"
    return derived_phase


_TOPIC_RULES = (
    ("injury", r"\b(?:injur|limp|down injured|cannot continue|won t make|not going to be able|big loss)"),
    ("player_influence", r"\b(?:get involved|turn it on|pockets of space|something out of nothing|changes? (?:the )?(?:game|match))\b"),
    ("outlet", r"\b(?:outlet|drop deeper|higher up|nothing forward|can t get out|cannot get out)\b"),
    ("game_management", r"\b(?:half ?time|second half|after the 80|late in games?|sit back|wait for)\b"),
    ("pressing_shape", r"\b(?:press|shape|spread out|connection across|connected|defensive set)\b"),
    ("chance_creation", r"\b(?:shots?|on target|chances?|break down|dangerous|passing lane|score)\b"),
    ("possession_control", r"\b(?:possession|have the ball|has the ball|without the ball|better of the play)\b"),
    ("mentality", r"\b(?:comfortable|confidence|belief|mentality|calm|pressure situation)\b"),
)


def _episode_topic(insight):
    text = _plain(" ".join(
        str(insight.get(key) or "") for key in ("quote", "headline", "analysis")
    ))
    for topic, pattern in _TOPIC_RULES:
        if re.search(pattern, text, re.I):
            return topic
    return _plain(insight.get("tag")) or "booth_read"


def _episode_anchor(insight, topic):
    team_abbr = insight.get("team_abbr")
    if topic == "injury" and team_abbr:
        return f"team:{team_abbr}:injury"
    if insight.get("subject_kind") == "player":
        return insight.get("subject_id") or f"player:{_plain(insight.get('subject'))}"
    if team_abbr:
        return f"team:{team_abbr}"
    return insight.get("subject_id") or f"subject:{_plain(insight.get('subject'))}"


def _merge_scope(left, right):
    scopes = {value for value in (left, right) if value}
    if len(scopes) <= 1:
        return next(iter(scopes), "current_match")
    return "mixed"


def _collapse_episodes(insights):
    """Collapse overlapping extractor rows into evolving, receipt-backed stories."""
    episodes = []
    for insight in sorted(insights, key=lambda row: row.get("ts") or ""):
        topic = _episode_topic(insight)
        anchor = _episode_anchor(insight, topic)
        stamp = _parse_datetime(insight.get("ts"))
        episode = None
        for candidate in reversed(episodes):
            if candidate["_anchor"] != anchor or candidate["topic"] != topic:
                continue
            if candidate.get("phase") != insight.get("phase"):
                continue
            updated = _parse_datetime(candidate.get("updated_at"))
            if stamp and updated and (stamp - updated).total_seconds() > _EPISODE_WINDOW_SECONDS:
                continue
            episode = candidate
            break

        receipt = {
            "id": insight.get("id"),
            "quote": insight.get("quote"),
            "ts": insight.get("ts"),
            "time_scope": insight.get("time_scope", "current_match"),
            "subject_raw": insight.get("subject_raw"),
        }
        if episode is None:
            episode = {
                "_anchor": anchor,
                "_receipts": [receipt],
                "id": None,
                "topic": topic,
                "tag": insight.get("tag"),
                "tags": [insight.get("tag")],
                "subject": insight.get("subject"),
                "subject_id": insight.get("subject_id"),
                "subject_kind": insight.get("subject_kind"),
                "subject_resolution": insight.get("subject_resolution"),
                "espn_id": insight.get("espn_id"),
                "team_abbr": insight.get("team_abbr"),
                "entities": ([{
                    "id": insight.get("subject_id"),
                    "name": insight.get("subject"),
                    "kind": "player",
                }] if insight.get("subject_kind") == "player" else []),
                "phase": insight.get("phase", "live"),
                "time_scope": insight.get("time_scope", "current_match"),
                "started_at": insight.get("ts"),
                "updated_at": insight.get("ts"),
                "strength": insight.get("strength", 1),
                "quote": insight.get("quote"),
            }
            episodes.append(episode)
        else:
            episode["_receipts"].append(receipt)
            episode["updated_at"] = max(
                value for value in (episode.get("updated_at"), insight.get("ts")) if value
            )
            episode["strength"] = max(episode.get("strength", 1), insight.get("strength", 1))
            episode["time_scope"] = _merge_scope(
                episode.get("time_scope"), insight.get("time_scope")
            )
            if insight.get("tag") and insight.get("tag") not in episode["tags"]:
                episode["tags"].append(insight["tag"])
            if insight.get("subject_kind") == "player":
                entity = {
                    "id": insight.get("subject_id"),
                    "name": insight.get("subject"),
                    "kind": "player",
                }
                if entity not in episode["entities"]:
                    episode["entities"].append(entity)
            # The latest high-strength receipt is the enrichment representative.
            if (insight.get("strength", 1), insight.get("ts") or "") >= (
                episode.get("strength", 1), episode.get("updated_at") or ""
            ):
                episode["quote"] = insight.get("quote")

    for episode in episodes:
        receipts = sorted(
            episode.pop("_receipts"), key=lambda row: row.get("ts") or "", reverse=True
        )
        episode["receipt_count"] = len(receipts)
        episode["_all_receipts"] = receipts
        episode["receipts"] = receipts[:_MAX_EPISODE_RECEIPTS]
        episode["id"] = _content_hash({
            "anchor": episode.pop("_anchor"),
            "topic": episode["topic"],
            "phase": episode["phase"],
            "started_at": episode["started_at"],
        })[:16]
    episodes.sort(
        key=lambda row: (row.get("updated_at") or "", row.get("strength") or 1), reverse=True
    )
    return episodes


def _attach_match_events(episodes, events):
    """Link a booth episode to an authoritative ESPN event on an exact full name."""
    for episode in episodes:
        episode["priority"] = "availability" if episode.get("topic") == "injury" else "storyline"
        quotes = " ".join(
            str(row.get("quote") or "")
            for row in episode.get("_all_receipts", episode.get("receipts", []))
        )
        receipt_text = f" {_plain(quotes)} "
        matches = []
        for event in events:
            exact_players = [
                player for player in event.get("players", [])
                if len(_plain(player).split()) >= 2 and f" {_plain(player)} " in receipt_text
            ]
            if not exact_players:
                continue
            matches.append((event, exact_players))
        if len(matches) == 1:
            event, exact_players = matches[0]
            episode["match_event"] = {
                "clock": event.get("clock"),
                "kind": event.get("kind"),
                "team": event.get("team"),
                "players": event.get("players", []),
                "text": event.get("text"),
                "matched_players": exact_players,
            }
            episode["event_clock"] = event.get("clock")
    return episodes


_TOPIC_WEIGHT = {
    "injury": 50,
    "player_influence": 18,
    "outlet": 16,
    "pressing_shape": 15,
    "chance_creation": 14,
    "game_management": 13,
    "possession_control": 12,
    "mentality": 8,
    "tactical": 10,
    "momentum": 8,
    "fatigue": 7,
}


def _rank_episodes(episodes):
    """Availability first, then impact/receipts/recency within one match phase."""
    if not episodes:
        return []
    latest = max(
        (_parse_datetime(row.get("updated_at")) for row in episodes), default=None
    )

    def score(row):
        updated = _parse_datetime(row.get("updated_at"))
        age_minutes = max(0, (latest - updated).total_seconds() / 60) if latest and updated else 0
        scope_penalty = 6 if row.get("time_scope") == "historical_reference" else 0
        generic_penalty = 3 if row.get("subject_kind") == "match" else 0
        return (
            100 if row.get("priority") == "availability" else 0
        ) + _TOPIC_WEIGHT.get(row.get("topic"), 6) + min(
            int(row.get("receipt_count") or 1), 6
        ) * 2 + int(row.get("strength") or 1) * 3 - age_minutes * 0.35 - scope_penalty - generic_penalty

    return sorted(
        episodes,
        key=lambda row: (score(row), row.get("updated_at") or ""),
        reverse=True,
    )


def _select_featured(episodes, limit=6):
    """Choose a compact, persona-useful mix instead of five versions of one team."""
    ranked = _rank_episodes(episodes)
    selected, selected_ids = [], set()
    team_counts, topics = defaultdict(int), set()

    for row in ranked:
        if row.get("priority") != "availability":
            continue
        selected.append(row)
        selected_ids.add(row.get("id"))
        if len(selected) >= limit:
            return selected

    for row in ranked:
        if row.get("id") in selected_ids:
            continue
        team = row.get("team_abbr")
        if row.get("subject_kind") == "team" and team and team_counts[team] >= 2:
            continue
        if row.get("topic") in topics and row.get("subject_kind") != "player":
            continue
        selected.append(row)
        selected_ids.add(row.get("id"))
        topics.add(row.get("topic"))
        if row.get("subject_kind") == "team" and team:
            team_counts[team] += 1
        if len(selected) >= limit:
            break

    player_rows = [
        row for row in ranked
        if row.get("subject_kind") == "player" and row.get("id") not in selected_ids
    ]
    if player_rows and not any(row.get("subject_kind") == "player" for row in selected):
        replacement = next(
            (index for index in range(len(selected) - 1, -1, -1)
             if selected[index].get("priority") != "availability"),
            None,
        )
        if replacement is not None:
            selected[replacement] = player_rows[0]

    if len(selected) < limit:
        for row in ranked:
            if row.get("id") in {item.get("id") for item in selected}:
                continue
            selected.append(row)
            if len(selected) >= limit:
                break
    return selected


_read_cache = OrderedDict()

_READ_SYS = (
    "You are a betting-desk analyst writing live in-match INTEL. Inputs are numbered FACTS (ESPN match "
    "facts and current market lines) and numbered BOOTH episodes (commentary/color, never an "
    "authoritative match fact). "
    "Produce exactly ONE concise RIGHT-NOW catch-up line about what is happening in this match. "
    "It should connect the two most important current developments in one fan-readable sentence. Historical references "
    "may explain a current development but must be described explicitly as history; never make a "
    "history-only line look live. A line MAY carry an optional 'play', but MOST lines should NOT — "
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
    "most lines. Return exactly 1 item. headline <= 140 chars, no trailing period."
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
    "Turn each numbered broadcast EPISODE into a takeaway-first card for a fan watching live. "
    "An episode may have several receipts describing one evolving story. For EVERY episode return: "
    "(1) headline: <=8 words, the actual development; (2) analysis: <=130 characters explaining "
    "why it matters, grounded ONLY in its receipts; (3) lean: back/fade/watch only when a PROP line "
    "is supplied AND current-match evidence genuinely changes the case "
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


def _market_for_subject(subject, goals_market):
    target = _plain(subject)
    for key, value in (goals_market or {}).items():
        player = value.get("player") if isinstance(value, dict) else key
        if _plain(player or key) != target:
            continue
        if isinstance(value, dict):
            return value
        return {
            "player": key,
            "market": "to score",
            "odds": value,
            "line": _fmt_odds(value),
            "quote_status": "unavailable",
            "quote_age_seconds": None,
            "price_as_of": None,
            "espn_id": None,
        }
    return None


def _actionable_market(insight, goals_market):
    """A player chip requires exact roster ID, current scope, and a fresh quote."""
    if insight.get("subject_kind") != "player":
        return None
    if insight.get("time_scope") != "current_match":
        return None
    if insight.get("subject_resolution") not in {"exact_player", "exact_quote_mention"}:
        return None
    market = _market_for_subject(insight.get("subject"), goals_market)
    if not market or market.get("quote_status") != "current":
        return None
    espn_id = str(insight.get("espn_id") or "")
    market_espn_id = str(market.get("espn_id") or "")
    if not espn_id or espn_id != market_espn_id:
        return None
    return market


def _parse_enrichment(out):
    cards = {}
    if not out:
        return cards
    txt = out.strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        txt = txt.split("\n", 1)[-1]
        if txt.lstrip().startswith("json"):
            txt = txt.lstrip()[4:]
    try:
        for item in json.loads(txt):
            if isinstance(item, dict) and "i" in item and item.get("headline"):
                cards[int(item["i"])] = {
                    "headline": str(item["headline"])[:100],
                    "analysis": str(item.get("analysis", ""))[:160],
                    "lean": str(item.get("lean", "")).lower(),
                }
    except Exception:
        return {}
    return cards


def _episode_prompt_line(index, insight, goals_market):
    receipts = insight.get("receipts") or [{"quote": insight.get("quote")}]
    evidence = " | ".join(str(row.get("quote") or "") for row in receipts[:3])
    market = _actionable_market(insight, goals_market)
    prop = f"{market['line']} to score" if market else "none"
    return (
        f"{index}. [{insight.get('tag')}/{insight.get('subject')}; "
        f"phase={insight.get('phase')}; scope={insight.get('time_scope')}] "
        f"PROP: {prop}; RECEIPTS: {evidence}"
    )


def _enrich_insights(insights, goals_market, cache_key):
    """Enrich episodes in bounded batches and retry omitted indices once."""
    if not insights:
        return insights
    cards, missing = {}, []
    cache_keys = {}
    for index, insight in enumerate(insights):
        item_key = (
            "episode-v2",
            _content_hash({
                "subject": insight.get("subject"),
                "phase": insight.get("phase"),
                "scope": insight.get("time_scope"),
                "receipts": insight.get("receipts") or insight.get("quote"),
                "market": _actionable_market(insight, goals_market),
            }),
        )
        cache_keys[index] = item_key
        cached = _cache_get(_insight_cache, item_key)
        if cached is None:
            missing.append(index)
        elif cached:
            cards[index] = cached

    # Small batches prevent the model from silently dropping the tail of a
    # forty-row prompt. One retry covers any omitted indices.
    for start in range(0, len(missing), 10):
        batch = missing[start:start + 10]
        prompt = "\n".join(
            _episode_prompt_line(index, insights[index], goals_market) for index in batch
        )
        parsed = _parse_enrichment(_deepseek(_INSIGHT_SYS, prompt, max_tokens=1800))
        omitted = [index for index in batch if index not in parsed]
        if omitted:
            retry_prompt = "\n".join(
                _episode_prompt_line(index, insights[index], goals_market) for index in omitted
            )
            parsed.update(_parse_enrichment(
                _deepseek(_INSIGHT_SYS, retry_prompt, max_tokens=max(500, 260 * len(omitted)))
            ))
        for index in batch:
            card = parsed.get(index)
            if card:
                cards[index] = card
                _cache_put(_insight_cache, cache_keys[index], card)
    for i, x in enumerate(insights):
        card = cards.get(i)
        if not card:
            continue
        # The enrichment model only saw this episode. Reject any new numeric fact
        # instead of letting a generated analysis turn commentary into data.
        generated_numbers = _numeric_tokens(card["headline"] + " " + card["analysis"])
        receipt_text = " ".join(
            str(row.get("quote") or "") for row in (x.get("receipts") or [{"quote": x.get("quote")}])
        )
        if not generated_numbers.issubset(_numeric_tokens(receipt_text)):
            continue
        x["headline"] = card["headline"]
        if card["analysis"]:
            x["analysis"] = card["analysis"]
        market = _actionable_market(x, goals_market)
        if market and card["lean"] in {"back", "fade", "watch"}:
            x["prop"] = {
                "player": x["subject"],
                "market": "to score",
                "line": market["line"],
                "lean": card["lean"],
                "price_as_of": market["price_as_of"],
                "quote_status": market["quote_status"],
                "quote_age_seconds": market["quote_age_seconds"],
                "quote_source": market["quote_source"],
            }
    return insights


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
        if isinstance(fact, dict):
            receipt = {
                "kind": fact.get("kind", "fact"),
                "scope": fact.get("scope", "current_match"),
                "text": str(fact.get("text") or ""),
                "ts": fact.get("ts"),
            }
        else:
            receipt = {"kind": "fact", "scope": "current_match", "text": str(fact), "ts": None}
        refs[ref] = receipt
        fact_lines.append(f"{ref} [{receipt['scope']}]: {receipt['text']}")
    quote_lines = []
    for index, insight in enumerate(insights[:18]):
        ref = f"B{index}"
        refs[ref] = {
            "kind": "booth",
            "scope": insight.get("time_scope", "current_match"),
            "text": insight["quote"],
            "ts": insight.get("updated_at") or insight.get("ts"),
        }
        quote_lines.append(
            f"{ref} [{refs[ref]['scope']}]: "
            f"[{insight['tag']}/{insight['subject']}] {insight['quote']}"
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
                    evidence_items = []
                    for ref in selected_refs:
                        receipt = refs[ref]
                        prefix = "ESPN/market" if receipt["kind"] == "fact" else "Booth"
                        evidence.append(f"{prefix}: {receipt['text']}")
                        evidence_items.append({
                            "ref": ref,
                            "kind": receipt["kind"],
                            "scope": receipt["scope"],
                            "text": receipt["text"],
                            "ts": receipt.get("ts"),
                        })
                    scopes = {refs[ref]["scope"] for ref in selected_refs}
                    context_scope = (
                        "right_now" if "current_match" in scopes or "mixed" in scopes
                        else "path_here"
                    )
                    card = {
                        "headline": headline,
                        "evidence": " · ".join(evidence),
                        "evidence_items": evidence_items,
                        "source": source,
                        "context_scope": context_scope,
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
                                **{key: market[key] for key in (
                                    "price_as_of", "quote_status", "quote_age_seconds", "quote_source"
                                ) if key in market},
                            }
                    read.append(card)
        except Exception:
            read = []
    _cache_put(_read_cache, cache_key, read)
    return read


_PHASE_LABELS = {
    "pregame": "Pregame",
    "first_half": "First half",
    "halftime": "Halftime",
    "second_half": "Second half",
    "extra_time": "Extra time",
    "final": "Final",
    "live": "Live",
}


def _coverage_payload(
    raw_rows, observations, episodes, current_phase, now, limit,
    selected_phase=None, returned_count=None,
):
    raw_stamped = sorted(
        ((stamp, row.get("ts")) for row in raw_rows if (stamp := _parse_datetime(row.get("ts")))),
        key=lambda pair: pair[0],
    )
    observation_stamped = sorted(
        ((stamp, row.get("ts")) for row in observations if (stamp := _parse_datetime(row.get("ts")))),
        key=lambda pair: pair[0],
    )
    phase_rows = []
    for phase in _PHASE_LABELS:
        rows = [row for row in episodes if row.get("phase") == phase]
        if not rows:
            continue
        phase_rows.append({
            "key": phase,
            "label": _PHASE_LABELS[phase],
            "episode_count": len(rows),
            "started_at": min(row.get("started_at") for row in rows if row.get("started_at")),
            "updated_at": max(row.get("updated_at") for row in rows if row.get("updated_at")),
        })
    if current_phase not in {row["key"] for row in phase_rows}:
        phase_rows.append({
            "key": current_phase,
            "label": _PHASE_LABELS.get(current_phase, current_phase.replace("_", " ").title()),
            "episode_count": 0,
            "started_at": None,
            "updated_at": None,
        })
    latest = raw_stamped[-1][0] if raw_stamped else None
    age = max(0, int((now - latest).total_seconds())) if latest else None
    selected_count = len([
        row for row in episodes if selected_phase is None or row.get("phase") == selected_phase
    ])
    return {
        "current_phase": current_phase,
        "selected_phase": selected_phase or current_phase,
        "source_started_at": raw_stamped[0][1] if raw_stamped else None,
        "source_latest_at": raw_stamped[-1][1] if raw_stamped else None,
        "source_observation_count": len(raw_rows),
        "relevant_observation_count": len(observations),
        "episode_count": len(episodes),
        "selected_episode_count": selected_count,
        "returned_episode_count": (
            min(selected_count, limit) if returned_count is None else returned_count
        ),
        "truncated": selected_count > limit,
        "booth_status": (
            "complete" if current_phase == "final"
            else "quiet" if current_phase == "halftime"
            else "unavailable" if age is None
            else "stale" if age > _BOOTH_STALE_AFTER_SECONDS
            else "current"
        ),
        "booth_age_seconds": age,
        "relevant_started_at": observation_stamped[0][1] if observation_stamped else None,
        "phases": phase_rows,
    }


def _public_episode(episode):
    return {key: value for key, value in episode.items() if not key.startswith("_")}


def _cache_episode_details(game_id, episodes):
    for episode in episodes:
        key = (str(game_id), str(episode.get("id")))
        _cache_put(_episode_detail_cache, key, {
            "schema_version": "wc-context-episode-v1",
            "game_id": str(game_id),
            "episode_id": str(episode.get("id")),
            "receipt_count": int(episode.get("receipt_count") or 0),
            "receipts": list(episode.get("_all_receipts") or episode.get("receipts") or []),
        })


def get_episode_detail(game_id, episode_id):
    return _cache_get(_episode_detail_cache, (str(game_id), str(episode_id)))


def build_context(game_id, limit=8, phase=None):
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

    now = dt.datetime.now(dt.timezone.utc)
    canonical_teams = {home_abbr: _name(home), away_abbr: _name(away)}
    names = _roster_names(sm, canonical_teams)
    aliases = _team_aliases(home, away)
    team_subjects = _team_subjects(home, away)
    bracket = _world_cup_bracket()
    history = _tournament_history(
        bracket, game_id, comp.get("date"), home_abbr, away_abbr
    )
    raw_rows = _broadcast_rows(tag)
    observations = _broadcast_insights(
        tag, names, aliases, rows=raw_rows, team_subjects=team_subjects
    )
    derived_phase = _annotate_match_phases(observations, comp.get("date"), status)
    current_phase = _current_phase(status, derived_phase)
    insights_full = _collapse_episodes(observations)
    events = _match_events(sm)
    insights_full = _attach_match_events(insights_full, events)
    raw_insight_hash = _content_hash([
        {key: insight.get(key) for key in (
            "id", "topic", "tag", "subject", "quote", "strength", "phase",
            "time_scope", "started_at", "updated_at", "receipt_count",
        )}
        for insight in insights_full
    ])
    scorers = _top_scorers(game_id, home_abbr, away_abbr, now=now)

    # live match stats → feed the synthesis so it can surface narrative-vs-data
    tstats = {}
    for t in sm.get("boxscore", {}).get("teams", []) or []:
        ab = (t.get("team", {}) or {}).get("abbreviation")
        tstats[ab] = {x.get("name"): x.get("displayValue") for x in t.get("statistics", []) or []}

    def _st(ab, k):
        return (tstats.get(ab) or {}).get(k, "—")

    away_sc, home_sc = away.get("score"), home.get("score")
    match_stats = _visible_match_stats(tstats, away_abbr, home_abbr)
    goals_mkt = _goals_market(game_id, now=now)
    available_phases = {row.get("phase") for row in insights_full}
    selected_phase = phase if phase in available_phases else current_phase
    if selected_phase not in available_phases and insights_full:
        selected_phase = insights_full[0].get("phase")
    selected_pool = _rank_episodes([
        row for row in insights_full if row.get("phase") == selected_phase
    ])
    visible_episodes = selected_pool[:limit]
    current_featured = _select_featured([
        row for row in insights_full if row.get("phase") == current_phase
    ], limit=6)
    if not current_featured:
        current_featured = _select_featured(insights_full, limit=6)
    enrich_targets, enrich_seen = [], set()
    for episode in current_featured + visible_episodes:
        if episode.get("id") in enrich_seen:
            continue
        enrich_seen.add(episode.get("id"))
        enrich_targets.append(episode)
    insight_cache_key = (
        "v4", str(game_id), raw_insight_hash, _content_hash(goals_mkt)
    )
    _enrich_insights(enrich_targets, goals_mkt, insight_cache_key)
    _cache_episode_details(game_id, insights_full)

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
        {"kind": "fact", "scope": "current_match",
         "text": f"MATCH ({status}): {_name(away)} {away_sc} - {home_sc} {_name(home)}"},
        {"kind": "fact", "scope": "current_match", "text": f"Score events: {ev_str}"},
        {"kind": "fact", "scope": "current_match", "text": _team_line(away, away_abbr, "away")},
        {"kind": "fact", "scope": "current_match", "text": _team_line(home, home_abbr, "home")},
    ]

    market_lines = {}
    for episode in insights_full:
        market = _actionable_market(episode, goals_mkt)
        if market:
            market_lines[_plain(episode.get("subject"))] = market

    current_episodes = [
        episode for episode in current_featured
        if episode.get("time_scope") in {"current_match", "mixed"}
    ][:8]
    if not current_episodes:
        current_episodes = [
            episode for episode in insights_full
            if episode.get("time_scope") in {"current_match", "mixed"}
        ][:12]

    read_cache_key = (
        "v4", str(game_id), current_phase, raw_insight_hash,
        _content_hash({"facts": facts, "markets": market_lines}),
    )
    read = _synthesize_read(facts, current_episodes, read_cache_key, market_lines=market_lines)
    right_now = [row for row in read if row.get("context_scope") == "right_now"][:1]
    generated_at = now.isoformat()
    coverage = _coverage_payload(
        raw_rows, observations, insights_full, current_phase, now, limit,
        selected_phase=selected_phase, returned_count=len(visible_episodes),
    )

    return {
        "schema_version": "wc-context-v2",
        "surface": "game_context",
        "game_id": str(game_id),
        "headline": f"{_name(away)} at {_name(home)}",
        "status": status,
        "current_phase": current_phase,
        "teams": {
            "home": {"abbr": home_abbr, "name": _name(home), "form": _form(home)},
            "away": {"abbr": away_abbr, "name": _name(away), "form": _form(away)},
        },
        "top_scorers": scorers,
        "match_stats": match_stats,
        "history": history,
        "right_now": right_now,
        "read": right_now,
        "featured_episodes": (
            [_public_episode(row) for row in current_featured[:5]] if phase is None else []
        ),
        "episodes": [_public_episode(row) for row in visible_episodes],
        "coverage": coverage,
        "latest_booth_at": coverage["source_latest_at"],
        "server_time": generated_at,
        "generated_at": generated_at,
        "freshness_policy": {
            "booth_stale_after_seconds": _BOOTH_STALE_AFTER_SECONDS,
            "market_quote_stale_after_seconds": _MARKET_QUOTE_STALE_AFTER_SECONDS,
        },
        "market_context": {
            "canonical_live_signal_endpoint": "/api/live/discounts?league=wc",
            "player_action_rule": (
                "A player action requires current-match evidence, exact ESPN identity, "
                "and a current timestamped quote."
            ),
        },
        "social_sentiment": {
            "status": "unavailable",
            "reason": "No validated social-sentiment source is connected; social claims are omitted.",
        },
        "sources": {
            "match_and_stats": "ESPN summary",
            "history": "ESPN World Cup bracket" if (history.get("teams") or {}) else None,
            "market": "Timestamped Bovada props; live team signals use /api/live/discounts",
            "booth": os.path.basename(os.path.join(BROADCAST_DIR, f"{tag}_signals.jsonl")),
            "social": None,
        },
        "limitations": [
            "Broadcast observations are commentary receipts, not authoritative match facts.",
            "Exact game clock is unavailable for booth receipts; broad match phases and wall time are retained.",
            "Social sentiment is omitted until a validated, timestamped source is connected.",
        ],
        "source": "ESPN facts + bracket history + timestamped market references + broadcast episodes",
    }
