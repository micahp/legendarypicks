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
import time
import urllib.request as _u
import urllib.error as _ue

_PS_BASE = "https://api.pandascore.co"
# Three separately-cached layers so idle esports doesn't ping the live feed:
#   upcoming = schedule (changes slowly)      -> long TTL
#   past     = finished results (need fresh-ish "it's over" signal) -> medium TTL
#   running  = LIVE matches (only fetched when something's in a live window) -> short TTL
_ps_cache_up = {"t": 0.0, "data": None}
_ps_cache_past = {"t": 0.0, "data": None}
_ps_cache_run = {"t": 0.0, "data": None}
_PS_TTL_UP = 600
_PS_TTL_PAST = 120
_PS_TTL_RUN = 45


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


def _cached(cache, ttl, path):
    """Return `path`'s parsed list, memoized in `cache` for `ttl` seconds."""
    if cache["data"] is not None and time.time() - cache["t"] < ttl:
        return cache["data"]
    data = _ps_get(path)
    # Keep the last good payload on a transient failure rather than blanking the slate.
    if data or cache["data"] is None:
        cache.update(t=time.time(), data=data)
    return cache["data"] or []


def _fetch_ps(include_running=True):
    """Merged esports matches across titles. `include_running=False` skips the LIVE feed entirely
    (schedule + finished results still come through cheaply) — used when nothing is in a live
    window so idle esports costs ~0 PandaScore calls beyond the slow schedule refresh."""
    if not _ps_key():
        return []
    matches = list(_cached(_ps_cache_up, _PS_TTL_UP, "/matches/upcoming?per_page=50&sort=begin_at"))
    matches += _cached(_ps_cache_past, _PS_TTL_PAST, "/matches/past?filter[status]=finished&sort=-end_at&per_page=50")
    if include_running:
        matches += _cached(_ps_cache_run, _PS_TTL_RUN, "/matches/running?per_page=50")
    # De-dup by match id (a match can appear in more than one feed at the boundary).
    seen, uniq = set(), []
    for m in matches:
        mid = m.get("id")
        if mid in seen:
            continue
        seen.add(mid)
        uniq.append(m)
    return uniq


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


def _ps_enrich(team_a, team_b, include_running=True):
    """Look up a match on PandaScore by fuzzy team-name match. Returns the authoritative status/
    score/winner + logos/canonical names/startTime, or None if no match found.

        {live, finished, score:{a,b}, winner:'a'|'b'|None, watch, logoA, logoB,
         canonicalA, canonicalB, startTime(ms), league}

    `include_running=False` looks only at the schedule + finished feeds (no live-feed ping)."""
    from .common import _strip_name

    na, nb = _strip_name(team_a), _strip_name(team_b)
    if not na or not nb:
        return None

    def _names(op):
        return {_strip_name(v) for v in (op.get("name") or "", op.get("acronym") or "",
                                         op.get("slug") or "") if v}

    def _hits(bov, names):
        if not bov:
            return False
        for n in names:
            if bov == n or bov in n or n in bov:
                return True
        import re
        bt = {t for t in re.split(r"[^a-z0-9]+", bov) if len(t) >= 3}
        for n in names:
            ft = {t for t in re.split(r"[^a-z0-9]+", n) if len(t) >= 3}
            if bt and ft:
                ov = bt & ft
                if len(ov) >= 2 or (len(ov) >= 1 and min(len(bt), len(ft)) <= 2):
                    return True
        return False

    for m in _fetch_ps(include_running=include_running):
        opps = m.get("opponents") or []
        if len(opps) < 2:
            continue
        op0 = opps[0].get("opponent") or {}
        op1 = opps[1].get("opponent") or {}
        n0, n1 = _names(op0), _names(op1)
        ab = _hits(na, n0) and _hits(nb, n1)
        ba = _hits(na, n1) and _hits(nb, n0)
        if not (ab or ba):
            continue
        swapped = ba and not ab

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

    return None
