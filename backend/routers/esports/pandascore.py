"""pandascore.py — authoritative per-match status / score / winner / logos across ALL esports
titles via the PandaScore API (https://api.pandascore.co).

frag.se (a PandaScore frontend) only exposes LIVE matches and only for streams; Bovada gives us
the schedule + odds but has NO "match finished" signal — so once a Valorant/R6/LoL match ended and
fell off Bovada's board, nothing told us, and it got stuck flagged `live` forever (zombie-live).

PandaScore is the fix: it returns an explicit `status` (not_started / running / finished / canceled),
real scores, the winner, team logos, canonical names, and scheduled times for every title. GRID stays
authoritative for CS2/Dota (more granular, per-player); PandaScore covers the rest (Valorant, R6, LoL)
and backfills the "is it over + final score" truth Bovada can't give.

Free tier: 1000 req/hr. We fetch three combined endpoints (running/upcoming/past) and cache ~90s,
so a busy slate costs ~2 req/min — well inside budget.
"""

import json
import os
import re
import time
import urllib.request as _u
import urllib.error as _ue

_PS_BASE = "https://api.pandascore.co"

# PandaScore videogame slug/name -> our display title label (common._ESPORTS_TITLES values). Used
# to surface a PandaScore-only match onto the slate; anything not in here is a title we don't cover.
_PS_VG_TITLE = {
    "dota-2": "Dota 2", "dota2": "Dota 2",
    "cs-go": "CS2", "csgo": "CS2", "cs2": "CS2", "counter-strike": "CS2", "counter-strike-2": "CS2",
    "valorant": "Valorant",
    "rainbow-6-siege": "Rainbow Six", "r6-siege": "Rainbow Six", "rainbow-six-siege": "Rainbow Six",
    "league-of-legends": "LoL", "lol": "LoL",
    "king-of-glory": "King of Glory", "honor-of-kings": "King of Glory",
    "ow": "Overwatch", "overwatch": "Overwatch",
    # CoD: match-object videogame.slug is "cod-mw" (name "Call of Duty"); the per-title feed path
    # alias is "codmw" (no hyphen — same short-alias divergence as csgo/dota2 vs cs-go/dota-2).
    "cod-mw": "Call of Duty", "call of duty": "Call of Duty", "codmw": "Call of Duty",
}
# The titles we surface. Per-title feeds (vs one combined endpoint) give far deeper coverage:
# the combined /matches/past returns only ~50 most-recent-globally, so minor CS2/Dota results from
# hours ago fall off it — per-title past-100 keeps them (and their team logos).
_PS_TITLES = ["valorant", "csgo", "dota2", "r6siege", "lol", "kog", "ow", "codmw"]
# Three separately-cached layers so idle esports doesn't ping the live feed:
#   upcoming = schedule (changes slowly)      -> long TTL
#   past     = finished results (need fresh-ish "it's over" signal) -> medium TTL
#   running  = LIVE matches (only fetched when something's in a live window) -> short TTL
_ps_cache_up = {"t": 0.0, "data": None}
_ps_cache_past = {"t": 0.0, "data": None}
_ps_cache_run = {"t": 0.0, "data": None}
_ps_cache_logos = {"t": 0.0, "data": None}
_PS_TTL_UP = 600
_PS_TTL_PAST = 120
_PS_TTL_RUN = 45
_PS_TTL_LOGOS = 120


def _ps_key():
    return (os.environ.get("PANDASCORE_API_KEY") or "").strip()


def _iso_to_ms(s):
    """Parse a PandaScore ISO-8601 UTC timestamp -> epoch ms, or None."""
    if not s:
        return None
    try:
        import datetime
        dt = datetime.datetime.strptime(s.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def _ps_get(path):
    """GET a PandaScore endpoint, return parsed JSON list (or [] on any failure)."""
    key = _ps_key()
    if not key:
        return []
    try:
        req = _u.Request(f"{_PS_BASE}{path}", headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "User-Agent": "LegendaryPicks/1.0",
        })
        with _u.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        return data if isinstance(data, list) else []
    except (_ue.HTTPError, _ue.URLError, Exception):
        return []


def _cached(cache, ttl, loader):
    """Return `loader()`'s list, memoized in `cache` for `ttl` seconds."""
    if cache["data"] is not None and time.time() - cache["t"] < ttl:
        return cache["data"]
    data = loader()
    # Keep the last good payload on a transient failure rather than blanking the slate.
    if data or cache["data"] is None:
        cache.update(t=time.time(), data=data)
    return cache["data"] or []


def _per_title(kind, query):
    """Concatenate a per-title match feed across all our titles (deeper than the combined feed).

    Titles are fetched CONCURRENTLY. Sequential per-title calls (the original implementation)
    added ~8s to a cold-cache /api/esports/upcoming response — 6 titles x ~1-1.5s each — which
    is what made the whole esports page take ~10s to load whenever the 600s/120s cache expired.
    A thread pool cuts that to roughly one request's latency.
    """
    from concurrent.futures import ThreadPoolExecutor
    paths = [f"/{t}/matches/{kind}?per_page=100&{query}" for t in _PS_TITLES]
    with ThreadPoolExecutor(max_workers=len(paths)) as ex:
        results = list(ex.map(_ps_get, paths))
    out = []
    for r in results:
        out += r
    return out


def _fetch_ps(include_running=True):
    """Merged esports matches across titles. `include_running=False` skips the LIVE feed entirely
    (schedule + finished results still come through cheaply) — used when nothing is in a live
    window so idle esports costs ~0 PandaScore calls beyond the slow schedule refresh."""
    if not _ps_key():
        return []
    matches = list(_cached(_ps_cache_up, _PS_TTL_UP, lambda: _per_title("upcoming", "sort=begin_at")))
    # Sort the finished feed by -scheduled_at, NOT -end_at: a large slice of finished matches have a
    # NULL end_at (never back-filled), and Postgres sorts NULLs FIRST on a DESC sort — so `-end_at`
    # packed page 1 (per_page=100) with ~100 null-end_at rows and pushed every real same-day result to
    # page 2+, out of our fetch window. That silently hid whole marquee tournaments (all 36 Esports
    # World Cup Dota results, EPL, CCT South America, RES Showdown…) behind a bare "Final". scheduled_at
    # is set at creation so it's populated for ~every match: page 1 now holds the 100 most-recently-
    # SCHEDULED finished matches per title (~8-10 days deep even for Dota — well past our 3-day store
    # retention). (EWC result hole, 2026-07-09.)
    matches += _cached(_ps_cache_past, _PS_TTL_PAST, lambda: _per_title("past", "filter[status]=finished&sort=-scheduled_at"))
    if include_running:
        matches += _cached(_ps_cache_run, _PS_TTL_RUN, lambda: _ps_get("/matches/running?per_page=50"))
    # De-dup by match id (a match can appear in more than one feed at the boundary).
    seen, uniq = set(), []
    for m in matches:
        mid = m.get("id")
        if mid in seen:
            continue
        seen.add(mid)
        uniq.append(m)
    return uniq


def _ps_team_logos():
    """A cached {team-name-key: logo_url} index harvested from every team seen in the feeds — so we
    can fill a match's crest by TEAM NAME even when that exact fixture isn't in PandaScore (e.g. a
    GRID-sourced result). Built off already-cached match data, so it costs no extra calls.

    Includes the RUNNING feed (a live team's crest — e.g. WBT/Wrotberry — is otherwise only in the
    live feed and would be missing), and ACCUMULATES across rebuilds: a logo seen once persists after
    that team ages out of the 100-deep feed window, so we never lose a crest we've already learned."""
    if _ps_cache_logos["data"] is not None and time.time() - _ps_cache_logos["t"] < _PS_TTL_LOGOS:
        return _ps_cache_logos["data"]
    from .common import _strip_name, _canon_team
    idx = dict(_ps_cache_logos["data"] or {})  # accumulate — don't drop logos learned earlier
    for m in _fetch_ps(include_running=True):
        for o in (m.get("opponents") or []):
            op = o.get("opponent") or {}
            img = op.get("image_url")
            if not img:
                continue
            # Index each variant under BOTH the plain stripped name and the canonical key, so a logo
            # carried under a short code ('WBT') is findable by the full name ('Wrotberry') and vice
            # versa — the acronym-logo gap the user hit. _strip_name keys stay for exact matches.
            for v in (op.get("name"), op.get("acronym"), op.get("slug")):
                for k in (_strip_name(v or ""), _canon_team(v or "")):
                    if k and k not in idx:
                        idx[k] = img
    _ps_cache_logos.update(t=time.time(), data=idx)
    return idx


def _ps_logo_for(name):
    """Best logo URL for a team name via the cached index: canonical key (acronym/generic-word aware)
    -> exact stripped-name -> conservative substring match (>=5 chars) to catch 'Procyon' ->
    'Procyon Gaming'."""
    from .common import _strip_name, _canon_team
    ck = _canon_team(name or "")
    idx = _ps_team_logos()
    if ck and ck in idx:
        return idx[ck]
    k = _strip_name(name or "")
    if not k:
        return None
    if k in idx:
        return idx[k]
    if len(k) >= 5:
        for tk, img in idx.items():
            if len(tk) >= 5 and (k in tk or tk in k):
                return img
    return None


# PandaScore game slug per our title label, for the teams-API logo fallback.
_PS_GAME_SLUG = {"CS2": "csgo", "Dota 2": "dota2", "Valorant": "valorant", "LoL": "lol",
                 "Rainbow Six": "r6siege", "King of Glory": "kog", "Overwatch": "ow"}
_PS_API_LOGO_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                 "data", "esports_team_logos.json")
_ps_api_logos = None  # {canon-name: url}  ('' = queried, PandaScore has no crest — a cached negative)


def _load_api_logos():
    global _ps_api_logos
    if _ps_api_logos is None:
        try:
            with open(_PS_API_LOGO_PATH) as f:
                _ps_api_logos = json.load(f)
        except Exception:
            _ps_api_logos = {}
    return _ps_api_logos


def _ps_team_logo_api(name, title):
    """Fallback crest straight from the PandaScore *teams* API, for a team whose matches aren't in the
    current match-feed window so the feed-derived index (`_ps_logo_for`) can't see its logo — the
    proven-recoverable case (Nemiga Gaming / Fortress / Vasco). Result (including a NEGATIVE for a team
    PandaScore genuinely has no crest for) is cached to disk, so each team is queried at most once and
    cold starts stay fast."""
    from .common import _canon_team
    ck = _canon_team(name)
    game = _PS_GAME_SLUG.get(title)
    if not ck or not game or not _ps_key():
        return None
    cache = _load_api_logos()
    if ck in cache:
        return cache[ck] or None
    import urllib.parse
    res = _ps_get(f"/{game}/teams?{urllib.parse.urlencode({'search[name]': name, 'per_page': 10})}")
    url = ""
    for t in (res or []):
        if ck in (_canon_team(t.get("name") or ""), _canon_team(t.get("acronym") or ""), _canon_team(t.get("slug") or "")):
            url = t.get("image_url") or ""
            break
    cache[ck] = url
    try:
        tmp = _PS_API_LOGO_PATH + ".tmp"
        os.makedirs(os.path.dirname(_PS_API_LOGO_PATH), exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(cache, f)
        os.replace(tmp, _PS_API_LOGO_PATH)
    except Exception:
        pass
    return url or None


def _ps_stream_to_watch(streams_list, live):
    """Best stream from PandaScore's streams_list in our watch-shape. PandaScore often gives a
    channel `/live` raw_url with no ready embed_url, so this is a clickable-link fallback; frag's
    per-match embed_url stays the preferred embeddable source. Priority: official+main > main >
    official > any."""
    best = None  # (prio, watch)
    for s in streams_list or []:
        raw = (s.get("raw_url") or "").strip()
        embed = (s.get("embed_url") or "").strip()
        url = embed or raw
        if not url:
            continue
        if "twitch.tv/" in url:
            platform = "twitch"
            channel = url.split("channel=", 1)[1].split("&")[0] if "channel=" in url else url.rstrip("/").rsplit("/", 1)[-1]
        elif "kick.com/" in url:
            platform, channel = "kick", url.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
        elif "youtube.com/" in url or "youtu.be/" in url:
            platform, channel = "youtube", None
        else:
            platform, channel = "web", None
        prio = (0 if (s.get("main") and s.get("official")) else 1 if s.get("main")
                else 2 if s.get("official") else 3)
        w = {"platform": platform, "url": raw or embed, "channel": channel,
             "embedUrl": embed or None, "online": bool(live)}
        if best is None or prio < best[0]:
            best = (prio, w)
    return best[1] if best else None


def _stable_stream_key(streams_list):
    """A CHANNEL-level, per-game-STABLE stream identity used to GROUP the games of one broadcast
    together — and to keep the featured slot on that broadcast after a game finishes.

    Deliberately DIFFERENT from _ps_stream_to_watch / the frontend's watch-derived `yt:<videoid>`
    key: PandaScore rotates the YouTube `watch?v=` id per GAME within a single event (serie 10734
    gave three different video ids on one Twitch channel), so a video-level key splits one broadcast
    into a new "stream" every game. This anchors on the CHANNEL instead, which is constant across the
    broadcast's games. Two concurrent arenas = two channels = two keys (correct — they stay separate).

    Channels are lowercased (Twitch/Kick are case-insensitive; PS mixes 'callofduty'/'CallofDuty'
    across series). Priority official+main > main > official > any. Returns None when the only stream
    is a bare rotating YouTube video (no channel anchor) — callers fall back to the event id."""
    best = None  # (prio, key)
    for s in streams_list or []:
        raw = (s.get("raw_url") or s.get("embed_url") or "").strip().lower()
        if not raw:
            continue
        key = None
        if "twitch.tv/" in raw:
            ch = raw.split("channel=", 1)[1].split("&")[0] if "channel=" in raw else raw.rstrip("/").rsplit("/", 1)[-1]
            if ch:
                key = f"twitch:{ch}"
        elif "kick.com/" in raw:
            ch = raw.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
            if ch:
                key = f"kick:{ch}"
        elif "youtube.com/channel/" in raw:
            cid = raw.split("/channel/", 1)[1].split("/")[0].split("?")[0]
            if cid:
                key = f"ytc:{cid}"
        elif "youtube.com/@" in raw:
            handle = raw.split("/@", 1)[1].split("/")[0].split("?")[0]
            if handle:
                key = f"ytc:@{handle}"
        # a bare watch?v= / youtu.be video is per-GAME, not a stable channel anchor -> skip it
        if not key:
            continue
        prio = (0 if (s.get("main") and s.get("official")) else 1 if s.get("main")
                else 2 if s.get("official") else 3)
        if best is None or prio < best[0]:
            best = (prio, key)
    return best[1] if best else None


# _ps_enrich is called once PER BOVADA MATCH (~50-80 times per /api/esports/upcoming request),
# and each call used to re-scan the full ~1174-entry PandaScore match list AND recompute each
# opponent's stripped name set from scratch every time — same ~1174 PandaScore matches, same
# names, redone 50-80x per request. Measured cost: ~3s of a ~7s cold request. Fix: memoize the
# (match, op0, op1, names0, names1) tuples once per _fetch_ps() cache generation (keyed by the
# id() of the list _fetch_ps returns — a fresh list object means a new generation, so this can't
# go stale) instead of recomputing per Bovada match.
_ps_indexed_cache = {}


def _ps_names(op):
    from .common import _strip_name
    return {_strip_name(v) for v in (op.get("name") or "", op.get("acronym") or "",
                                     op.get("slug") or "") if v}


_TOK_RE = re.compile(r"[^a-z0-9]+")


def _tokset(s):
    """Alphanumeric tokens (len>=3) of a stripped name — the exact set _ps_enrich's fuzzy matcher
    used to recompute inline. Precomputed once per PS name in _ps_indexed so the per-match enrich
    loop (177 matches x ~250 PS rows) stops re-tokenizing the same ~250 names 177 times over."""
    return {t for t in _TOK_RE.split(s or "") if len(t) >= 3}


def _ps_league_compatible(slate_league, match):
    """Narrow fixture-level league bridge for United21's inconsistent source labels.

    Bovada emits ``United 21`` / ``United21 Season 52 (Group Stage)`` while PandaScore splits the
    same identity across league/serie/tournament fields. This is intentionally NOT a general fuzzy
    league matcher: it only recognizes the United21 family and rejects conflicting season numbers.
    """
    from .common import _fold

    def _norm(value):
        value = re.sub(r"\bunited\s*21\b", "united21", _fold(value or "").lower())
        return re.findall(r"[a-z0-9]+", value)

    source_tokens = _norm(slate_league)
    ps_text = " ".join(filter(None, [
        (match.get("league") or {}).get("name"),
        (match.get("serie") or {}).get("full_name"),
        (match.get("tournament") or {}).get("name"),
    ]))
    target_tokens = _norm(ps_text)
    if "united21" not in source_tokens or "united21" not in target_tokens:
        return False

    def _season(tokens):
        for i, token in enumerate(tokens[:-1]):
            if token == "season" and tokens[i + 1].isdigit():
                return tokens[i + 1]
        return None

    source_season, target_season = _season(source_tokens), _season(target_tokens)
    return not (source_season and target_season and source_season != target_season)


def _ps_indexed(include_running):
    # _fetch_ps() rebuilds a brand-new list object (list(...) + dedup pass) on EVERY call, even
    # when the underlying _ps_cache_* entries are still warm — so id() of its return value is
    # never stable and can't be used as a memoization key. Key on the underlying caches' own
    # data-object identities instead; those only change when a cache actually re-fetches.
    gen = (id(_ps_cache_up["data"]), id(_ps_cache_past["data"]),
           id(_ps_cache_run["data"]) if include_running else None, include_running)
    cached = _ps_indexed_cache.get(gen)
    if cached is not None:
        return cached
    matches = _fetch_ps(include_running=include_running)
    _ps_indexed_cache.clear()  # old generation's list is gone (new fetch/cache cycle) — drop it
    from .common import _canon_team_x
    out = []
    for m in matches:
        opps = m.get("opponents") or []
        if len(opps) < 2:
            continue
        op0 = opps[0].get("opponent") or {}
        op1 = opps[1].get("opponent") or {}
        n0, n1 = _ps_names(op0), _ps_names(op1)
        # Precompute each name's token set AND canon-identity set ONCE (both were recomputed per
        # enrich call — together the ~7.8s hot spot: 177 matches x ~250 PS rows re-tokenizing and
        # re-canonicalizing the same names). Enrich now just does set ops against these.
        tk0 = [t for t in (_tokset(n) for n in n0) if t]
        tk1 = [t for t in (_tokset(n) for n in n1) if t]
        cs0 = {_canon_team_x(v) for v in (op0.get("name"), op0.get("acronym"), op0.get("slug")) if v}
        cs1 = {_canon_team_x(v) for v in (op1.get("name"), op1.get("acronym"), op1.get("slug")) if v}
        out.append((m, op0, op1, n0, n1, tk0, tk1, cs0, cs1))
    _ps_indexed_cache[gen] = out
    return out


def _ps_enrich(team_a, team_b, include_running=True, near_ms=None, league=None, ps_id=None,
               allow_reschedule=False):
    """Look up a match on PandaScore by fuzzy team-name match. Returns the authoritative status/
    score/winner + logos/canonical names/startTime, or None if no match found.

        {live, finished, score:{a,b}, winner:'a'|'b'|None, watch, logoA, logoB,
         canonicalA, canonicalB, startTime(ms), league}

    `include_running=False` looks only at the schedule + finished feeds (no live-feed ping)."""
    from .common import _strip_name, _canon_team_x

    na, nb = _strip_name(team_a), _strip_name(team_b)
    if not na or not nb:
        return None
    # Canonical (acronym/alias-aware) identity keys — bridges pairs the plain stripped-name matcher
    # can't (PandaScore's 'NAVI Junior' vs Bovada's 'Natus Vincere Junior'). Used as an ADDITIONAL
    # accept path below; the `near_ms` time guard still prevents same-team-different-match collisions.
    ca, cb = _canon_team_x(team_a), _canon_team_x(team_b)

    def _canon_hit(cx, canon_set):
        return cx in canon_set  # canon_set precomputed once in _ps_indexed

    def _hits(bov, bt, names, name_toks):
        # bt = precomputed token set of `bov`; name_toks = precomputed token sets of `names`
        # (see _tokset/_ps_indexed). Semantics identical to the old inline version: substring hit on
        # any name, OR token-overlap hit on any name.
        if not bov:
            return False
        for n in names:
            if bov == n or bov in n or n in bov:
                return True
        if not bt:
            return False
        for ft in name_toks:
            ov = bt & ft
            if len(ov) >= 2 or (len(ov) >= 1 and min(len(bt), len(ft)) <= 2):
                return True
        return False

    bta, btb = _tokset(na), _tokset(nb)

    # Teams play many matches; a name match alone attaches a PAST result to a same-team FUTURE
    # fixture (e.g. a finished Edward Gaming game -> the Edward Gaming EWC match days later, marked
    # falsely finished). When we know the fixture's time (`near_ms`), require the PandaScore match to
    # be within a day-ish of it and pick the CLOSEST — that disambiguates same-team collisions.
    NEAR_TOL_MS = 36 * 3600 * 1000
    RESCHEDULE_TOL_MS = 7 * 86400 * 1000
    best = None  # ((id_priority, time_delta), match_dict, swapped)
    for m, op0, op1, n0, n1, tk0, tk1, cs0, cs1 in _ps_indexed(include_running):
        # Each side may use its strongest evidence independently. This matters when one side is a
        # lexical variant (MIBR <-> MIBR LOS) while the other needs an explicit cross-source alias
        # (Anyone's Legend <-> AG.AL International). Requiring BOTH sides to use the same matching
        # path missed that real fixture. The time guard below still prevents a same-team rematch from
        # receiving the wrong result, and this does not change match_identity._same_team's global
        # split policy.
        a0 = _hits(na, bta, n0, tk0) or _canon_hit(ca, cs0)
        a1 = _hits(na, bta, n1, tk1) or _canon_hit(ca, cs1)
        b0 = _hits(nb, btb, n0, tk0) or _canon_hit(cb, cs0)
        b1 = _hits(nb, btb, n1, tk1) or _canon_hit(cb, cs1)
        league_fixture = _ps_league_compatible(league, m)
        # Fixture-scoped fallback: same United21 season/time plus ONE matched opponent is enough to
        # bridge a source label such as Prestige Esports <-> Prestige Academy. It does not change
        # global team identity; outside this exact fixture those squads remain distinct.
        ab = (a0 and b1) or (league_fixture and (a0 or b1))
        ba = (a1 and b0) or (league_fixture and (a1 or b0))
        same_id = ps_id is not None and m.get("id") == ps_id
        if not (ab or ba):
            if not same_id:
                continue
            ab = True  # a stable source id is authoritative; preserve the stored orientation
        begin_ms = _iso_to_ms(m.get("begin_at") or m.get("scheduled_at"))
        delta = abs(begin_ms - near_ms) if (near_ms and begin_ms) else 0
        status = (m.get("status") or "").lower()
        rescheduled = (allow_reschedule and league_fixture
                       and status in ("not_started", "not started")
                       and delta <= RESCHEDULE_TOL_MS)
        if near_ms and begin_ms and delta > NEAR_TOL_MS and not (same_id or rescheduled):
            continue  # same team names, but a different match at a different time — not this one
        rank = (0 if same_id else 1, delta)
        if best is None or rank < best[0]:
            best = (rank, m, ba and not ab)

    if best is None:
        return None
    _, m, swapped = best
    op0 = (m.get("opponents") or [])[0].get("opponent") or {}
    op1 = (m.get("opponents") or [])[1].get("opponent") or {}

    status = (m.get("status") or "").lower()
    live = status == "running"
    finished = status == "finished"

    # Score from results[] keyed by team_id, aligned to opponent order then to our A/B.
    # Only real once the match is under way — PandaScore seeds not_started matches with 0-0,
    # which must NOT surface as a live "0 - 0" scoreline on an upcoming game.
    score = None
    if live or finished:
        res = {r.get("team_id"): r.get("score") for r in (m.get("results") or [])}
        s0, s1 = res.get(op0.get("id")), res.get(op1.get("id"))
        if s0 is not None or s1 is not None:
            score = {"a": s1 if swapped else s0, "b": s0 if swapped else s1}

    winner = None
    win_id = m.get("winner_id")
    if win_id:
        if win_id == op0.get("id"):
            winner = "b" if swapped else "a"
        elif win_id == op1.get("id"):
            winner = "a" if swapped else "b"

    img0, img1 = op0.get("image_url"), op1.get("image_url")
    name0, name1 = op0.get("name") or "", op1.get("name") or ""

    return {
        "_ps_id": m.get("id"),  # PandaScore match id — lets slate_state.py dedup the surface block by
                                # identity (this match was already consumed by a Bovada entry) instead
                                # of by fuzzy team names.
        "live": live,
        "finished": finished,
        "score": score,
        "winner": winner,
        "watch": _ps_stream_to_watch(m.get("streams_list"), live),
        "logoA": img1 if swapped else img0,
        "logoB": img0 if swapped else img1,
        "canonicalA": name1 if swapped else name0,
        "canonicalB": name0 if swapped else name1,
        "startTime": _iso_to_ms(m.get("begin_at") or m.get("scheduled_at")),
        "league": (m.get("league") or {}).get("name"),
    }


def _ps_match_tier(m):
    """PandaScore prestige tier for a match: 's' (marquee — EWC, MSI, Worlds, TI, Majors, KPL…) down
    to 'd'. Lives on the match, else the serie/tournament. Lowercased, '' if absent."""
    return (m.get("tier") or (m.get("serie") or {}).get("tier")
            or (m.get("tournament") or {}).get("tier") or "").lower()


def _ps_surface_matches(finished_window_ms=3 * 3600 * 1000,
                        upcoming_window_ms=14 * 86400 * 1000,
                        upcoming_tiers=("s",), kalshi_pairs=None):  # major upcoming events (EWC, MSI, Worlds, TI, Majors,
                                                 # KPL) land ahead of time; minor scheduled matches
                                                 # don't. Bovada-overlap dups are removed in slate_state.py
                                                 # by PandaScore match-id (used_ps_ids), not by name.
    """Live, just-finished, and MAJOR-upcoming PandaScore matches in slate match-shape, so slate.py
    can SURFACE a match Bovada dropped/never listed and GRID doesn't cover. Everything else in the
    pipeline treats PandaScore as enrich-only (it fills score/winner on matches we already have) and
    cannot ADD a match, so such a match — a live qualifier with a real stream, or a whole major
    tournament Bovada isn't pricing (e.g. Esports World Cup) — was invisible on our board.

    - `running` + just-finished (end within `finished_window_ms`): surfaced regardless of tier — any
      live match is worth showing, and a just-finished one so a surfaced live match survives its own
      finish transition into Results instead of vanishing the moment it ends.
    - `not_started`: surfaced ONLY for major events (tier in `upcoming_tiers`, default 's') within
      `upcoming_window_ms`. Without a tier gate, 100s of minor scheduled matches would swamp the board;
      the gate is how "all the major tournaments" land ahead of time without the noise.

    Reads the cached feeds; the only marginal cost over what enrich already does is one running-feed
    fetch when nothing else put us in a live window."""
    now_ms = time.time() * 1000
    out = []
    for m in _fetch_ps(include_running=True):
        status = (m.get("status") or "").lower()
        running = status == "running"
        finished = status == "finished"
        upcoming = status in ("not_started", "not started")
        if not (running or finished or upcoming):
            continue
        title = _PS_VG_TITLE.get((m.get("videogame") or {}).get("slug")) \
            or _PS_VG_TITLE.get(((m.get("videogame") or {}).get("name") or "").lower())
        if not title:
            continue  # a title we don't surface
        opps = m.get("opponents") or []
        if len(opps) < 2:
            continue
        op0 = opps[0].get("opponent") or {}
        op1 = opps[1].get("opponent") or {}
        na, nb = op0.get("name"), op1.get("name")
        if not na or not nb:
            continue  # placeholder bracket slot (TBD vs TBD) — nothing to show yet

        end_ms = _iso_to_ms(m.get("end_at"))
        begin_ms = _iso_to_ms(m.get("begin_at") or m.get("scheduled_at"))
        if finished and (not end_ms or now_ms - end_ms > finished_window_ms):
            continue  # only surface RECENT finishes, not the whole 100-deep past feed
        if upcoming:
            from .common import _canon_team
            is_major = _ps_match_tier(m) in upcoming_tiers
            is_kalshi = kalshi_pairs is not None and (title, frozenset({_canon_team(na), _canon_team(nb)})) in kalshi_pairs
            if not is_major and not is_kalshi:
                continue  # minor scheduled match Kalshi isn't trading either — don't pre-surface
            if not begin_ms or begin_ms - now_ms > upcoming_window_ms or begin_ms < now_ms - 6 * 3600 * 1000:
                continue  # outside the schedule window

        res = {r.get("team_id"): r.get("score") for r in (m.get("results") or [])}
        s0, s1 = res.get(op0.get("id")), res.get(op1.get("id"))
        score = {"a": s0, "b": s1} if (s0 is not None or s1 is not None) else None
        win_id = m.get("winner_id")
        winner = "a" if win_id == op0.get("id") else "b" if win_id == op1.get("id") else None

        league = (m.get("league") or {}).get("name") or ""
        serie = (m.get("serie") or {}).get("full_name") or ""
        tour = (m.get("tournament") or {}).get("name") or ""
        league_str = " — ".join([p for p in (league, serie) if p]) or league or serie or title
        if tour and tour.lower() not in league_str.lower():
            league_str = f"{league_str} ({tour})"

        out.append({
            "_ps_id": m.get("id"),
            "startTime": begin_ms,
            "live": running,
            "finished": finished,
            "title": title,
            "league": league_str,
            "teamA": na, "teamB": nb,
            "favorite": None,
            "score": score,
            "winner": winner,
            "logoA": op0.get("image_url"), "logoB": op1.get("image_url"),
            "watch": None,  # resolved in slate.py's on-air pass; the stream link rides on _ps_watch
            "_ps_watch": _ps_stream_to_watch(m.get("streams_list"), running),
            "source": "pandascore",
        })
    return out
