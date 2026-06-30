"""frag.py — per-match live stream, logos, and canonical team names via frag.se (PandaScore-backed).

Frag.se's /api/live carries official + community streams per match (embed-ready, multi-language),
team logos (image_url), and cleaner canonical team names. This replaces the hardcoded
_WATCH_RULES for live matches. Fall back to existing hardcoded maps when frag.se is
unavailable or can't match a game.
"""

import json
import time
import urllib.request as _u

_FRAG_URL = "https://frag.se/api/live"
_frag_cache = {"t": 0.0, "data": None}


def _fetch_frag_live():
    """Return the parsed frag.se /api/live JSON, cached ~60s. Returns [] on failure."""
    if _frag_cache["data"] is not None and time.time() - _frag_cache["t"] < 60:
        return _frag_cache["data"]
    try:
        req = _u.Request(_FRAG_URL, headers={"User-Agent": "Mozilla/5.0"})
        with _u.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode())
        live = data.get("dataLive") or []
        _frag_cache.update(t=time.time(), data=live)
        return live
    except Exception:
        return _frag_cache["data"] or []


def _frag_stream_to_watch(stream):
    """Convert a frag.se stream dict to our watch-shape. frag gives a ready-to-embed `embed_url`
    for Twitch/Kick/YouTube alike, so we pass it through as `embedUrl` and the frontend iframes it
    directly — no per-platform channel re-derivation (that's what dropped YouTube streams before)."""
    embed = (stream.get("embed_url") or "").strip()
    raw = (stream.get("raw_url") or "").strip()
    url = embed or raw
    if not url:
        return None

    if "kick.com/" in url:
        platform = "kick"
        channel = embed.rsplit("/", 1)[-1].split("?")[0] if embed else None
    elif "twitch.tv/" in url:
        platform = "twitch"
        channel = url.split("channel=", 1)[1].split("&")[0] if "channel=" in url else url.rstrip("/").rsplit("/", 1)[-1]
    elif "youtube.com/" in url or "youtu.be/" in url:
        platform = "youtube"
        channel = None
    else:
        platform = "web"
        channel = None

    return {
        "platform": platform,
        "url": raw or embed,        # human-clickable page for the ↗ link
        "channel": channel,
        "embedUrl": embed or None,  # ready-to-embed iframe src (Twitch/Kick/YouTube)
        "online": True,             # frag.se only lists live matches — stream is broadcasting
    }


def _frag_enrich(team_a, team_b):
    """Look up a live match on frag.se by fuzzy team-name match.

    Returns a dict with enrichment data, or None if no match:
        {
            "watch":       {platform, url, channel, online},  # best stream
            "logoA":       "https://...",   # team A logo URL (or None)
            "logoB":       "https://...",   # team B logo URL (or None)
            "canonicalA":  "Clean Name",    # frag's canonical team name
            "canonicalB":  "Clean Name",
        }

    Stream priority: main+official > main > official > any community.
    """
    from .common import _strip_name

    na = _strip_name(team_a)
    nb = _strip_name(team_b)

    live = _fetch_frag_live()
    if not live:
        return None

    best_stream = None  # (priority, watch_dict)

    for m in live:
        opponents = m.get("opponents") or []
        if len(opponents) < 2:
            continue

        opp0 = opponents[0].get("opponent") or {}
        opp1 = opponents[1].get("opponent") or {}

        # Collect all name variants for each frag team: name, acronym, slug.
        def _frag_names(opp):
            return {_strip_name(v) for v in (
                opp.get("name") or "",
                opp.get("acronym") or "",
                opp.get("slug") or "",
            ) if v}

        names_a = _frag_names(opp0)
        names_b = _frag_names(opp1)

        # Match: each Bovada team must hit at least one frag variant.
        match_ab = (na and any(na == fn or na in fn or fn in na for fn in names_a)) and \
                   (nb and any(nb == fn or nb in fn or fn in nb for fn in names_b))
        match_ba = (na and any(na == fn or na in fn or fn in na for fn in names_b)) and \
                   (nb and any(nb == fn or nb in fn or fn in nb for fn in names_a))
        if not (match_ab or match_ba):
            continue

        # We found the matching frag match. Collect streams + logos.
        swapped = match_ba  # if matched reversed, swap A/B

        # Team logos
        img_a = (opponents[0].get("opponent") or {}).get("image_url") or None
        img_b = (opponents[1].get("opponent") or {}).get("image_url") or None

        # Best stream
        streams = m.get("streams") or []
        for s in streams:
            url = s.get("embed_url") or s.get("raw_url") or ""
            if not url.strip():
                continue
            w = _frag_stream_to_watch(s)
            if not w:
                continue

            is_main = s.get("main", False)
            is_official = s.get("official", False)
            if is_main and is_official:
                prio = 0
            elif is_main:
                prio = 1
            elif is_official:
                prio = 2
            else:
                prio = 3

            if best_stream is None or prio < best_stream[0]:
                best_stream = (prio, w)

        # Fallback: official_stream_url when streams[] is empty.
        if best_stream is None:
            off = m.get("official_stream_url") or ""
            if off.strip():
                w = _frag_stream_to_watch({"embed_url": off})
                if w:
                    best_stream = (2, w)

        watch = best_stream[1] if best_stream else None

        frag_team_a = opp0.get("name") or ""
        frag_team_b = opp1.get("name") or ""

        return {
            "watch": watch,
            "logoA": img_b if swapped else img_a,
            "logoB": img_a if swapped else img_b,
            "canonicalA": frag_team_b if swapped else frag_team_a,
            "canonicalB": frag_team_a if swapped else frag_team_b,
        }

    return None
