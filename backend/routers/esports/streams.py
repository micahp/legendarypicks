"""streams.py — broadcast channel resolution and on-air verification."""

import json
import re
import urllib.request as _u

_WATCH_RULES = [
    ("league-of-legends", "midseason", [("twitch", "riotgames")]),
    ("league-of-legends", "primeleague", [("twitch", "primeleague")]),
    ("league-of-legends", None, [("twitch", "riotgames")]),
    ("valorant", "esportsworldcup", [("twitch", "ewc")]),
    ("valorant", "emea", [("twitch", "valorant_emea")]),
    ("valorant", "pacific", [("twitch", "valorant_pacific")]),
    ("valorant", None, [("twitch", "valorant")]),
    ("counter-strike-2", "cct", [("kick", "cct_cs"), ("twitch", "cct_cs"), ("kick", "cct_cs2")]),
    ("counter-strike-2", "europeanproleague", [("kick", "eplcs_en"), ("twitch", "eplcs_en2")]),
    ("counter-strike-2", "united21", [("kick", "united21_en")]),
    ("dota-2", "europeanproleague", [("kick", "epldota_en"), ("twitch", "epldota_en2")]),
    ("rainbow-six", None, [("twitch", "rainbow6")]),
    ("king-of-glory", None, [("web", "https://www.honorofkings.com/esports/?language=en")]),
]

_live_cache = {}  # "platform:channel" -> (ts, bool|None) — on-air status, cached ~90s


def _chan_url(platform, channel):
    if platform == "twitch":
        return f"https://www.twitch.tv/{channel}"
    if platform == "kick":
        return f"https://kick.com/{channel}"
    return channel  # web: channel holds the full URL


def _channel_online(platform, channel):
    """Is this channel actually broadcasting right now? Twitch via decapi, Kick via api/v1.
    Returns True/False, or None if unverifiable. Cached ~90s so we don't hammer on every poll."""
    if platform not in ("twitch", "kick"):
        return None
    import time
    key = f"{platform}:{channel}"
    c = _live_cache.get(key)
    if c and time.time() - c[0] < 90:
        return c[1]
    online = None
    try:
        if platform == "twitch":
            with _u.urlopen(_u.Request(f"https://decapi.me/twitch/uptime/{channel}",
                                       headers={"User-Agent": "Mozilla/5.0"}), timeout=6) as r:
                txt = r.read().decode().lower()
            online = bool(txt.strip()) and not any(w in txt for w in ("offline", "error", "unable", "not found"))
        else:  # kick
            with _u.urlopen(_u.Request(f"https://kick.com/api/v1/channels/{channel}",
                                       headers={"User-Agent": "Mozilla/5.0"}), timeout=6) as r:
                online = json.loads(r.read().decode()).get("livestream") is not None
    except Exception:
        online = None
    if online is not None:
        _live_cache[key] = (time.time(), online)
    return online


def _resolve_watch(title_slug, league, live=False):
    """Pick the watch channel for a match. For a LIVE match, return the first CANDIDATE that's
    actually on-air (so we never show a dead/wrong link); if none are live, return the top candidate
    flagged offline. For a scheduled match, return the top candidate (where it'll be). None if no rule."""
    ls = re.sub(r"[^a-z0-9]+", "", (league or "").lower())
    for t, kw, cands in _WATCH_RULES:
        if t != title_slug or (kw is not None and kw not in ls):
            continue
        if not live:
            platform, ch = cands[0]
            return {"platform": platform, "url": _chan_url(platform, ch),
                    "channel": (ch if platform != "web" else None), "online": None}
        # live: surface the candidate that's confirmed broadcasting
        for platform, ch in cands:
            if platform == "web":
                return {"platform": platform, "url": _chan_url(platform, ch), "channel": None, "online": None}
            if _channel_online(platform, ch):
                return {"platform": platform, "url": _chan_url(platform, ch), "channel": ch, "online": True}
        platform, ch = cands[0]  # nothing on-air -> top candidate, marked offline
        return {"platform": platform, "url": _chan_url(platform, ch),
                "channel": (ch if platform != "web" else None), "online": False}
    return None
