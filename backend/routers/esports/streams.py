"""streams.reviewed.py — candidate-pool broadcast resolution with platform priority + fallback.

REDESIGN (2026-07-03 expert review, see logs/SLATE-EXPERT-REVIEW-2026-07-03.md):

The old resolver picked ONE stream per source and stopped at the first hit; a raw-URL-only frag
stream (live example: ex-Sashi Academy v eternal premium, frag's only stream = kick eplcs_en with an
EMPTY embed_url) shipped with no embedUrl even though the embed is trivially derivable, and a
positively-offline hardcoded channel (twitch/ewc during EWC Valorant, actually broadcast on
ewc_stcarena_en — decapi confirmed 'ewc is offline' while ewc_stcarena_en was 3h+ live) shipped
anyway because there was no fallback.

New model: every source contributes CANDIDATES into one pool; candidates are normalized (platform,
channel, embedUrl — synthesized from the raw URL when the source didn't provide one), liveness-checked
where a platform allows it, ranked, and the best is returned with the runners-up as `alternates`.

Ranking: platform priority YouTube > Twitch > Kick > web (YouTube/Twitch embeds are reliable from any
network). Kick liveness+viewer_count is now verified via the official OAuth API (api.kick.com/public/v1,
client-credentials grant — added 2026-07-22 once KICK_CLIENT_ID/SECRET existed); the direct kick.com
site/API stays Cloudflare-403 from our datacenter IP for ANY request, even a real-browser XHR (reverified
2026-07-22), so Kick still ranks last in platform priority — verifying liveness doesn't make its embed
more reliable than YouTube/Twitch, it just means we're no longer flying blind on it. Within a platform:
source-attested-live first, then main+official, then English. A candidate that is POSITIVELY offline
(Twitch via decapi, Kick via the official API) is excluded unless every candidate is offline — then the
top one ships flagged online=false, honestly.

Kick policy (evaluating the prior patch): embedding a Kick channel is RIGHT when the match itself is
live-confirmed upstream and the candidate is source-attested (frag/PandaScore list it as the live
broadcast) or the official API confirms is_live — the player handles a dark channel gracefully and
alternates now give an escape hatch. It stays wrong only as a sole blind hardcoded guess with no
attestation and no confirmed liveness, which the ranking already demotes.
"""

import json
import logging
import os
import re
import threading
import time
import urllib.error as _ue
import urllib.parse as _up
import urllib.request as _u
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeout

from .yt_live_resolver import resolve_pool_youtube, yt_viewer_count

_LOG = logging.getLogger(__name__)

# Hardcoded per-league channel rules — the LAST-RESORT candidate source (frag/PandaScore per-match
# streams rank ahead of these in the pool). Kept from streams.py; still used alone for scheduled
# matches ("where it'll air").
_WATCH_RULES = [
    ("league-of-legends", "midseason", [("twitch", "riotgames")]),
    ("league-of-legends", "primeleague", [("twitch", "primeleague")]),
    ("league-of-legends", None, [("twitch", "riotgames")]),
    ("valorant", "esportsworldcup", [("twitch", "ewc_stcarena_en"), ("twitch", "ewc")]),
    # exclude="gamechangers": "emea"/"pacific" are naive substring checks on the fully-stripped
    # league string, so "VCT — Game Changers EMEA Stage 3" matched "emea" too (BUG, fixed 2026-07-22)
    # and injected the MAIN bracket's channel as a fallback candidate into a Game Changers match that
    # already has its own correctly-attested different channel — worse, that wrong candidate could
    # win the pool outright when the match's REAL channel was momentarily offline (decapi-confirmed)
    # while the wrong one was busy airing an unrelated main-bracket game. Game Changers matches always
    # carry their own real frag/PandaScore stream in practice, so excluding them here costs nothing.
    ("valorant", "emea", [("twitch", "valorant_emea")], "gamechangers"),
    ("valorant", "pacific", [("twitch", "valorant_pacific")], "gamechangers"),
    ("valorant", None, [("twitch", "valorant")]),
    ("counter-strike-2", "cct", [("kick", "cct_cs"), ("twitch", "cct_cs"), ("kick", "cct_cs2")]),
    ("counter-strike-2", "europeanproleague", [("kick", "eplcs_en"), ("twitch", "eplcs_en2")]),
    ("counter-strike-2", "united21", [("kick", "united21_en")]),
    ("dota-2", "europeanproleague", [("kick", "epldota_en"), ("twitch", "epldota_en2")]),
    ("rainbow-six", None, [("twitch", "rainbow6")]),
    ("king-of-glory", None, [("web", "https://www.honorofkings.com/esports/?language=en")]),
    # CoD: the live embed comes from the Data-API-resolved official CDL channel below
    # (_YT_TOURNAMENT_CHANNELS); this web link is the scheduled "where it'll air" fallback (lowest
    # prio, non-embedding) for when nothing's live to resolve yet — same pattern as king-of-glory.
    ("call-of-duty", None, [("web", "https://www.youtube.com/@CODLeague/live")]),
]

# Lower = preferred. YouTube first (requirement), then Twitch (verifiable via decapi), then Kick
# (verifiable via the official API since 2026-07-22, but still ranked last — its embed itself isn't
# more reliable than YouTube/Twitch, verifying liveness just stopped us flying blind on it), then
# bare web links.
_PLATFORM_PRIO = {"youtube": 0, "twitch": 1, "kick": 2, "web": 3}

# Tournament -> official YouTube channel, title-agnostic (a festival's main channel can carry any
# arena depending on the moment). yt_live_resolver resolves this via the Data API (channel_id
# survives the datacenter bot wall); if nothing's live on that channel right now it just returns
# None and Twitch/Kick wins, so a wrong/stale entry here is harmless, never a wrong embed.
_YT_TOURNAMENT_CHANNELS = [
    # @ewc, 1.45M subs, verified live 2026-07-08 (5 concurrent live videos incl. Dota Stream A/B/C).
    # NOTE: UC1Xqp122TsjLISeYa1EwcaQ (customUrl @esportsworldcup) is a DIFFERENT, abandoned
    # 56-subscriber channel that happens to hold that handle — do not revert to it.
    ("esportsworldcup", "UCENNtCRTPTdH_IGXs42LuHQ"),
    # @CODLeague, 1.97M subs — the official English CDL broadcast. Keyed on "cdl" so it matches the
    # Bovada league string "Cdl Championship" (ls="cdlchampionship") and future "Cdl Major N", but
    # NOT "Call of Duty Challengers" (that broadcasts on codchallengers, carried via PS streams_list).
    # NOTE: @CallofDutyLeague (UC-VqDM9ogg-Q4urJjKneHxQ, 76 subs) is a DECOY — do not use it.
    ("cdl", "UCbLIqv9Puhyp9_ZjVtfOy7w"),
]

# Known official Twitch channel -> its sibling official YouTube channel. Some organizers simulcast
# on Twitch+YouTube, but PandaScore/frag may list only the Twitch side for a given match. Without a
# sibling candidate, platform priority (YouTube > Twitch) has nothing YouTube-shaped to rank.
#
# Key this on the source-attested Twitch broadcaster rather than a league string: one entry covers
# every event that broadcaster runs, while normalized league labels can lose the identifying region
# or organizer. Channel comparison is case-insensitive because source casing varies.
_TWITCH_YT_SIBLINGS = {
    # @vctemea, verified live 2026-07-22 (FNC vs KC VCT EMEA Stage 2).
    "valorant_emea": "UCp6n8d8Y8r3MwKNw_MMaouQ",
    # @BLASTPremier, verified live 2026-07-26 on BLAST Bounty S2 Day 6. FRAG carried the official
    # twitch.tv/BLASTPremier stream but omitted the simultaneous official YouTube broadcast.
    # Broadcaster-level mapping also covers BLAST Open/Rivals and future Bounty events.
    "blastpremier": "UC9k--dE_UE0Faxzgb_DDkYQ",
}


def _yt_sibling_candidates(pool):
    """For each known Twitch channel already resolved into the pool, add its verified official
    YouTube sibling as an extra candidate (yt_live_resolver still has to confirm it's actually live
    right now — a wrong/stale entry here is harmless, never a wrong embed, same guarantee as
    _yt_channel_candidates).

    BUG FIXED 2026-07-22: only trust the channel if a real per-match source (frag/pandascore, i.e.
    NOT source=="rule") put it there. `_WATCH_RULES`'s "emea" keyword rule matches "Game Changers
    EMEA" too (a substring hit, not a real region check) and injects the MAIN valorant_emea Twitch
    channel as a low-confidence fallback guess into Game Changers matches that already have their
    own correctly-attested different channel (valorant_emea2, remakeval, ...). Gating on source
    excludes that guess: Karmine Corp GC vs Habos Babos and Twisted Minds Orchid vs ALTERNATE aTTaX
    Ruby were both wrongly resolving to the MAIN bracket's YouTube video (an acronym collision —
    Karmine Corp's main and Game Changers rosters share the "KC" acronym in PandaScore's data —
    made worse by the rule guess putting the wrong channel in the pool in the first place)."""
    out = []
    twitch_channels = {(c.get("channel") or "").lower() for c in pool
                       if c and c.get("platform") == "twitch"
                       and c.get("channel") and c.get("source") != "rule"}
    for twitch_chan, yt_channel_id in _TWITCH_YT_SIBLINGS.items():
        if twitch_chan in twitch_channels:
            out.append(_candidate(url=f"https://www.youtube.com/channel/{yt_channel_id}/live",
                                   platform="youtube", channel=None, source="rule-yt-sibling"))
    return out


def _yt_channel_candidates(league):
    ls = re.sub(r"[^a-z0-9]+", "", (league or "").lower())
    out = []
    for kw, chan_id in _YT_TOURNAMENT_CHANNELS:
        if kw in ls:
            out.append(_candidate(url=f"https://www.youtube.com/channel/{chan_id}/live",
                                   platform="youtube", channel=None, source="rule-yt"))
    return out

_live_cache = {}       # Twitch "platform:channel" -> (ts, True|False|None)
_LIVE_TTL = 90         # confirmed statuses
_LIVE_TTL_UNKNOWN = 600  # unverifiable after a transient API/network failure

_KICK_TOKEN_URL = "https://id.kick.com/oauth/token"
_KICK_API_CHANNELS = "https://api.kick.com/public/v1/channels"
_KICK_API_USER_LIVESTREAMS = "https://api.kick.com/public/v1/users/livestreams"
_KICK_HTTP_TIMEOUT = 4
_KICK_VIEWER_TTL = 60
_KICK_VIEWER_RETRY_TTL = 30
_KICK_VIEWER_REFRESH_WAIT = 5
_kick_token_cache = {"token": None, "exp": 0, "failure_status": None}

# Kick liveness and viewer data have different freshness needs. Keep one snapshot per channel
# instead of storing liveness in _live_cache and viewer_count in a side-effect cache. In particular,
# a fresh online=True value must not make a missing viewer count look fresh for another 90 seconds.
_kick_snapshot_cache = {}
_kick_snapshot_lock = threading.Lock()
_kick_viewer_inflight = {}
_kick_viewer_inflight_lock = threading.Lock()


def _kick_snapshot(fetched_at, online=None, viewers=None, broadcaster_user_id=None,
                   failure_kind=None, status_code=None, viewer_retry_at=None):
    return {
        "fetched_at": fetched_at,
        "online": online,
        "viewers": viewers,
        "broadcaster_user_id": broadcaster_user_id,
        "failure_kind": failure_kind,
        "status_code": status_code,
        "viewer_retry_at": viewer_retry_at,
    }


def _kick_log_failure(channel, failure_kind, status_code=None):
    """Safe diagnostics only: never include tokens, credentials, headers, or response bodies."""
    _LOG.warning(
        "Kick stream lookup failed channel=%s failure_kind=%s status=%s",
        channel,
        failure_kind,
        status_code if status_code is not None else "-",
    )


def _kick_failure(channel, failure_kind, *, status_code=None, broadcaster_user_id=None,
                  online=None):
    _kick_log_failure(channel, failure_kind, status_code)
    return _kick_snapshot(
        time.time(),
        online=online,
        broadcaster_user_id=broadcaster_user_id,
        failure_kind=failure_kind,
        status_code=status_code,
    )


def _kick_cached_snapshot(channel):
    with _kick_snapshot_lock:
        snapshot = _kick_snapshot_cache.get(channel)
        return dict(snapshot) if snapshot else None


def _store_kick_snapshot(channel, snapshot):
    """Atomically replace a channel snapshot while retaining retry/broadcaster context."""
    with _kick_snapshot_lock:
        previous = _kick_snapshot_cache.get(channel)
        stored = dict(snapshot)
        if previous and stored.get("broadcaster_user_id") is None:
            stored["broadcaster_user_id"] = previous.get("broadcaster_user_id")
        if stored.get("viewers") is not None:
            stored["viewer_retry_at"] = None
        elif previous and stored.get("viewer_retry_at") is None:
            stored["viewer_retry_at"] = previous.get("viewer_retry_at")
        _kick_snapshot_cache[channel] = stored
        return dict(stored)


def _mark_kick_viewer_retry(channel, attempted_at):
    with _kick_snapshot_lock:
        current = dict(_kick_snapshot_cache.get(channel) or _kick_snapshot(attempted_at))
        current["viewer_retry_at"] = attempted_at
        _kick_snapshot_cache[channel] = current


def _kick_viewer_value(value):
    # Kick documents an integer. Zero is meaningful (including broadcasters who hide the count);
    # booleans are ints in Python but must not leak through as viewer counts.
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _kick_api_json(url, token, client_id):
    req = _u.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Client-Id": client_id,
            "Accept": "application/json",
        },
    )
    try:
        with _u.urlopen(req, timeout=_KICK_HTTP_TIMEOUT) as response:
            raw = response.read().decode()
            status_code = getattr(response, "status", None)
    except _ue.HTTPError as exc:
        return None, "http_error", exc.code
    except Exception:
        return None, "http_error", None
    try:
        body = json.loads(raw)
    except (TypeError, ValueError):
        return None, "response_invalid", status_code
    if not isinstance(body, dict):
        return None, "response_invalid", status_code
    return body, None, status_code


def _kick_token():
    """Client-credentials app token for the official Kick API (api.kick.com/public/v1). Requires
    KICK_CLIENT_ID/KICK_CLIENT_SECRET (a registered Kick developer app, added 2026-07-22 — the
    direct kick.com site/API is Cloudflare-403 from our datacenter IP for every request, verified
    even via a real headless-browser session, so this OAuth path is the only way to reach Kick data
    at all from this host). Token is long-lived (~60d observed); cached until near expiry."""
    now = time.time()
    if _kick_token_cache["token"] and now < _kick_token_cache["exp"]:
        return _kick_token_cache["token"]
    client_id = os.environ.get("KICK_CLIENT_ID")
    client_secret = os.environ.get("KICK_CLIENT_SECRET")
    if not client_id or not client_secret:
        _kick_token_cache["failure_status"] = None
        return None
    try:
        data = _up.urlencode({"grant_type": "client_credentials", "client_id": client_id,
                               "client_secret": client_secret}).encode()
        with _u.urlopen(_u.Request(_KICK_TOKEN_URL, data=data, method="POST"), timeout=6) as r:
            body = json.loads(r.read().decode())
        _kick_token_cache["token"] = body["access_token"]
        _kick_token_cache["exp"] = now + body.get("expires_in", 3600) - 60
        _kick_token_cache["failure_status"] = None
        return _kick_token_cache["token"]
    except _ue.HTTPError as exc:
        _kick_token_cache["failure_status"] = exc.code
        return None
    except Exception:
        _kick_token_cache["failure_status"] = None
        return None


def _kick_channel_data(channel):
    """A diagnostic snapshot from Kick's official Channels endpoint."""
    client_id = os.environ.get("KICK_CLIENT_ID")
    if not client_id or not os.environ.get("KICK_CLIENT_SECRET"):
        return _kick_failure(channel, "token_unavailable")
    token = _kick_token()
    if not token or not client_id:
        return _kick_failure(
            channel,
            "token_unavailable",
            status_code=_kick_token_cache.get("failure_status"),
        )

    url = f"{_KICK_API_CHANNELS}?slug={_up.quote(channel)}"
    body, failure_kind, status_code = _kick_api_json(url, token, client_id)
    if failure_kind:
        return _kick_failure(channel, failure_kind, status_code=status_code)
    rows = body.get("data")
    if not isinstance(rows, list) or not rows:
        return _kick_failure(channel, "empty_data", status_code=status_code)
    row = rows[0]
    if not isinstance(row, dict):
        return _kick_failure(channel, "response_invalid", status_code=status_code)

    broadcaster_user_id = row.get("broadcaster_user_id")
    stream = row.get("stream")
    if not isinstance(stream, dict) or not isinstance(stream.get("is_live"), bool):
        return _kick_failure(
            channel,
            "stream_missing",
            status_code=status_code,
            broadcaster_user_id=broadcaster_user_id,
            # Preserve the prior resolver's behavior: a channel row without a live stream is
            # positively offline for ranking, even though diagnostics explain why no count exists.
            online=False,
        )

    online = stream["is_live"]
    viewers = _kick_viewer_value(stream.get("viewer_count"))
    failure_kind = "viewer_missing" if online and viewers is None else None
    if failure_kind:
        _kick_log_failure(channel, failure_kind, status_code)
    return _kick_snapshot(
        time.time(),
        online=online,
        viewers=viewers,
        broadcaster_user_id=broadcaster_user_id,
        failure_kind=failure_kind,
        status_code=status_code,
    )


def _kick_user_livestream_data(channel, broadcaster_user_id):
    """Viewer fallback from Kick's official active-livestream endpoint."""
    client_id = os.environ.get("KICK_CLIENT_ID")
    if not client_id or not os.environ.get("KICK_CLIENT_SECRET"):
        return _kick_failure(
            channel,
            "token_unavailable",
            broadcaster_user_id=broadcaster_user_id,
        )
    token = _kick_token()
    if not token:
        return _kick_failure(
            channel,
            "token_unavailable",
            status_code=_kick_token_cache.get("failure_status"),
            broadcaster_user_id=broadcaster_user_id,
        )

    query = _up.urlencode({"user_id": broadcaster_user_id})
    body, failure_kind, status_code = _kick_api_json(
        f"{_KICK_API_USER_LIVESTREAMS}?{query}",
        token,
        client_id,
    )
    if failure_kind:
        return _kick_failure(
            channel,
            failure_kind,
            status_code=status_code,
            broadcaster_user_id=broadcaster_user_id,
        )
    rows = body.get("data")
    if not isinstance(rows, list) or not rows:
        return _kick_failure(
            channel,
            "empty_data",
            status_code=status_code,
            broadcaster_user_id=broadcaster_user_id,
        )
    row = rows[0]
    if not isinstance(row, dict):
        return _kick_failure(
            channel,
            "response_invalid",
            status_code=status_code,
            broadcaster_user_id=broadcaster_user_id,
        )
    viewers = _kick_viewer_value(row.get("viewer_count"))
    if viewers is None:
        return _kick_failure(
            channel,
            "viewer_missing",
            status_code=status_code,
            broadcaster_user_id=broadcaster_user_id,
            online=True,
        )
    return _kick_snapshot(
        time.time(),
        online=True,
        viewers=viewers,
        broadcaster_user_id=broadcaster_user_id,
        status_code=status_code,
    )


def _refresh_kick_viewer_snapshot(channel):
    """Retry Channels once, then use the official active-livestream endpoint if needed."""
    previous = _kick_cached_snapshot(channel)
    primary = _kick_channel_data(channel)
    if previous and primary.get("online") is None and previous.get("online") is not None:
        primary = dict(primary)
        primary["online"] = previous["online"]
    primary = _store_kick_snapshot(channel, primary)
    if primary.get("viewers") is not None:
        return primary

    broadcaster_user_id = primary.get("broadcaster_user_id")
    if broadcaster_user_id is None:
        return primary
    fallback = _kick_user_livestream_data(channel, broadcaster_user_id)
    if fallback.get("viewers") is not None:
        return _store_kick_snapshot(channel, fallback)

    # The fallback's failure is the terminal reason, but retain any liveness evidence returned by
    # Channels. A failed viewer fallback must not turn known liveness into unknown.
    combined = dict(primary)
    combined["fetched_at"] = fallback["fetched_at"]
    combined["failure_kind"] = fallback.get("failure_kind") or primary.get("failure_kind")
    combined["status_code"] = fallback.get("status_code")
    return _store_kick_snapshot(channel, combined)


def _clear_kick_viewer_inflight(channel, future):
    with _kick_viewer_inflight_lock:
        if _kick_viewer_inflight.get(channel) is future:
            _kick_viewer_inflight.pop(channel, None)


def _submit_kick_viewer_refresh(channel):
    """Submit at most one viewer refresh per channel; callers may share the returned Future."""
    with _kick_viewer_inflight_lock:
        current = _kick_viewer_inflight.get(channel)
        if current and not current.done():
            return current
        _mark_kick_viewer_retry(channel, time.time())
        try:
            future = _get_probe_executor().submit(_refresh_kick_viewer_snapshot, channel)
        except Exception:
            _kick_log_failure(channel, "refresh_submit_error")
            return None
        _kick_viewer_inflight[channel] = future
    # add_done_callback may invoke immediately for an already-finished Future, so register it only
    # after releasing the non-reentrant inflight lock.
    future.add_done_callback(lambda done: _clear_kick_viewer_inflight(channel, done))
    return future


def _kick_viewer_count(channel, *, confirmed_live=False, has_last_good=False,
                       wait_for_first_sample=True):
    """Return a fresh Kick count, with one bounded first-sample retry for a live channel."""
    now = time.time()
    snapshot = _kick_cached_snapshot(channel)
    if (snapshot and snapshot.get("viewers") is not None
            and now - snapshot["fetched_at"] < _KICK_VIEWER_TTL):
        return snapshot["viewers"]
    if not (confirmed_live or has_last_good):
        return None

    retry_at = snapshot.get("viewer_retry_at") if snapshot else None
    retry_due = retry_at is None or now - retry_at >= _KICK_VIEWER_RETRY_TTL
    with _kick_viewer_inflight_lock:
        future = _kick_viewer_inflight.get(channel)
        if future and future.done():
            future = None
    if future is None and retry_due:
        future = _submit_kick_viewer_refresh(channel)

    # Only the confirmed-live first-sample hole waits. Later misses return the existing last-good
    # value while the shared refresh runs in the background.
    if not (future and confirmed_live and not has_last_good and wait_for_first_sample):
        return None
    try:
        refreshed = future.result(timeout=_KICK_VIEWER_REFRESH_WAIT)
    except _FutureTimeout:
        _kick_log_failure(channel, "refresh_timeout")
        return None
    except Exception:
        _kick_log_failure(channel, "refresh_error")
        return None
    return _kick_viewer_value((refreshed or {}).get("viewers"))


_twitch_viewer_cache = {}   # channel -> (ts, viewer_count|None)
_TWITCH_VIEWER_TTL = 60      # viewer counts drift second to second; cheap decapi call


def _twitch_viewer_count(channel):
    """Live viewer count via decapi.me (no auth, free) — a separate endpoint from the uptime check
    used for liveness, so this is one extra HTTP call per Twitch candidate we resolve."""
    c = _twitch_viewer_cache.get(channel)
    if c and time.time() - c[0] < _TWITCH_VIEWER_TTL:
        return c[1]
    viewers = None
    try:
        with _u.urlopen(_u.Request(f"https://decapi.me/twitch/viewercount/{channel}",
                                   headers={"User-Agent": "Mozilla/5.0"}), timeout=6) as r:
            txt = r.read().decode().strip()
        viewers = int(txt) if txt.isdigit() else None
    except Exception:
        viewers = None
    _twitch_viewer_cache[channel] = (time.time(), viewers)
    return viewers


# Last known good count per stream, so ONE transient fetch miss doesn't blank a number that was
# on screen seconds ago. Every upstream here fails to None on any hiccup (decapi timeout, Kick
# token blip, YT parse miss) and the per-platform caches happily store that None, so a single bad
# call used to show an empty viewer slot on a stream that is plainly live — observed live on the
# board: cct_cs3 read None one cycle and 311 the next with no code change. A slightly stale count
# beats a hole, but only briefly: past _VIEWER_STALE_MAX we'd rather show nothing than a lie.
_viewer_last_good = {}    # "platform:channel-or-embed" -> (ts, count)
_VIEWER_STALE_MAX = 900   # 15 min
_VIEWER_FRESH_TTL = 60    # matches the Twitch/YouTube/Kick platform cache TTLs
_viewer_refresh_inflight = {}
_viewer_refresh_inflight_lock = threading.Lock()


def _viewer_key(c):
    return f"{c.get('platform')}:{c.get('channel') or c.get('embedUrl') or ''}"


def _recent_viewer_count(key, now=None):
    now = time.time() if now is None else now
    previous = _viewer_last_good.get(key)
    return previous if previous and now - previous[0] < _VIEWER_STALE_MAX else None


def _viewer_count(c, *, confirmed_live=False, wait_for_first_sample=True):
    """Live viewer count for a candidate, or None if unknown/unverifiable.

    Kick owns an independently fresh snapshot and a bounded first-sample retry; Twitch and YouTube
    retain their existing fetch paths. All platforms fall back to a recent last-known-good count.
    """
    platform = c.get("platform")
    key = _viewer_key(c)
    now = time.time()
    recent_prev = _recent_viewer_count(key, now)

    if platform == "twitch" and c.get("channel"):
        fresh = _twitch_viewer_count(c["channel"])
    elif platform == "kick" and c.get("channel"):
        fresh = _kick_viewer_count(
            c["channel"],
            confirmed_live=confirmed_live,
            has_last_good=recent_prev is not None,
            wait_for_first_sample=wait_for_first_sample,
        )
    elif platform == "youtube" and c.get("embedUrl"):
        fresh = yt_viewer_count(c["embedUrl"])
    else:
        return None

    if fresh is not None:
        _viewer_last_good[key] = (time.time(), fresh)
        return fresh
    return recent_prev[1] if recent_prev else None


def _clear_viewer_refresh(key, future):
    with _viewer_refresh_inflight_lock:
        if _viewer_refresh_inflight.get(key) is future:
            _viewer_refresh_inflight.pop(key, None)


def _submit_viewer_refresh(c):
    """Refresh a Twitch/YouTube viewer count off-thread, deduplicated by resolved stream."""
    key = _viewer_key(c)
    with _viewer_refresh_inflight_lock:
        current = _viewer_refresh_inflight.get(key)
        if current and not current.done():
            return current
        try:
            future = _get_probe_executor().submit(_viewer_count, dict(c))
        except Exception:
            return None
        _viewer_refresh_inflight[key] = future
    # A Future may already be done here; register only after releasing the non-reentrant lock.
    future.add_done_callback(lambda done: _clear_viewer_refresh(key, done))
    return future


def _viewer_count_cached(c, *, confirmed_live=False):
    """Return a cached/last-good count and refresh stale data without blocking the caller.

    Scheduled rows use this path while the slate rebuild is running. Kick already owns a
    non-blocking cache refresh; Twitch and YouTube network reads are handed to the shared probe
    executor so a slow viewer endpoint can never stall the whole board.
    """
    platform = c.get("platform")
    key = _viewer_key(c)
    now = time.time()
    recent = _recent_viewer_count(key, now)
    if recent and now - recent[0] < _VIEWER_FRESH_TTL:
        return recent[1]

    if platform == "kick" and c.get("channel"):
        return _viewer_count(
            c,
            confirmed_live=confirmed_live,
            wait_for_first_sample=False,
        )
    if ((platform == "twitch" and c.get("channel"))
            or (platform == "youtube" and c.get("embedUrl"))):
        _submit_viewer_refresh(c)
    return recent[1] if recent else None


def _chan_url(platform, channel):
    if platform == "twitch":
        return f"https://www.twitch.tv/{channel}"
    if platform == "kick":
        return f"https://kick.com/{channel}"
    return channel  # web: channel holds the full URL


_YT_ID = re.compile(r"(?:youtube\.com/(?:watch\?v=|embed/|live/)|youtu\.be/)([A-Za-z0-9_-]{6,})")


def _embed_url(platform, channel, url):
    """Best iframe src for a candidate. Pass a source-provided embed through; otherwise SYNTHESIZE
    from the channel/raw URL — a Twitch/Kick channel always has a canonical player URL, so a
    raw-URL-only stream (frag's eplcs_en case) must never ship embed-less."""
    u = (url or "").strip()
    if "player.twitch.tv" in u or "player.kick.com" in u or "/embed" in u or "blackboard/live" in u:
        return u  # already an embed
    if platform == "twitch" and channel:
        return f"https://player.twitch.tv/?channel={channel}"
    if platform == "kick" and channel:
        return f"https://player.kick.com/{channel}"
    if platform == "youtube":
        m = _YT_ID.search(u)
        if m:
            return f"https://www.youtube.com/embed/{m.group(1)}"
    return None


def _parse_platform_channel(url):
    """(platform, channel) from any stream URL, embed or raw."""
    u = (url or "").strip()
    if not u:
        return None, None
    if "twitch.tv" in u:
        if "channel=" in u:
            return "twitch", u.split("channel=", 1)[1].split("&")[0]
        return "twitch", u.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    if "kick.com" in u:
        return "kick", u.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube", None
    return "web", None


def _channel_online(platform, channel):
    """True/False/None per platform. Twitch: decapi.me (works from this host). Kick: the official
    OAuth API (falls back to None if KICK_CLIENT_ID/SECRET aren't set or the call fails — same as
    before creds existed). YouTube: no free liveness endpoint -> None (a frag-attested YouTube
    stream is live by listing)."""
    if platform not in ("twitch", "kick"):
        return None
    if platform == "kick":
        snapshot = _kick_cached_snapshot(channel)
        if snapshot:
            ttl = _LIVE_TTL if snapshot.get("online") is not None else _LIVE_TTL_UNKNOWN
            if time.time() - snapshot["fetched_at"] < ttl:
                return snapshot.get("online")
        return _store_kick_snapshot(channel, _kick_channel_data(channel)).get("online")

    key = f"{platform}:{channel}"
    c = _live_cache.get(key)
    if c and time.time() - c[0] < (_LIVE_TTL if c[1] is not None else _LIVE_TTL_UNKNOWN):
        return c[1]
    online = None
    try:
        with _u.urlopen(_u.Request(f"https://decapi.me/twitch/uptime/{channel}",
                                   headers={"User-Agent": "Mozilla/5.0"}), timeout=6) as r:
            txt = r.read().decode().lower()
        online = bool(txt.strip()) and not any(w in txt for w in ("offline", "error", "unable", "not found"))
    except Exception:
        online = None
    _live_cache[key] = (time.time(), online)
    return online


# Background liveness pool: the decapi/Kick ping is the ONLY blocking network call in _pick_stream.
# Running it inline for scheduled matches on the rebuild path is what let the broadcast-liveness
# promotion hang the endpoint. Mirror the YouTube resolver: the rebuild reads platform caches only
# (zero network) and hands a refresh to this pool, so a promotion lands ~one cycle after the channel
# goes live instead of blocking the rebuild. Deduped so the same channel's probe can't pile up.
_probe_executor = None
_probe_executor_lock = threading.Lock()
_probe_inflight = set()
_probe_inflight_lock = threading.Lock()


def _get_probe_executor():
    global _probe_executor
    if _probe_executor is None:
        with _probe_executor_lock:
            if _probe_executor is None:
                _probe_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="chan-live")
    return _probe_executor


def _channel_online_cached(platform, channel):
    """Non-blocking liveness: the fresh cached value if we have one, else None while a background
    probe refreshes the platform cache for next cycle. Never touches the network on the caller's
    thread. Only Twitch/Kick are verifiable (others -> None, no probe)."""
    if platform not in ("twitch", "kick") or not channel:
        return None
    key = f"{platform}:{channel}"
    if platform == "kick":
        snapshot = _kick_cached_snapshot(channel)
        cached_online = snapshot.get("online") if snapshot else None
        cached_at = snapshot.get("fetched_at") if snapshot else None
    else:
        c = _live_cache.get(key)
        cached_online = c[1] if c else None
        cached_at = c[0] if c else None
    if cached_at is not None:
        ttl = _LIVE_TTL if cached_online is not None else _LIVE_TTL_UNKNOWN
        if time.time() - cached_at < ttl:
            return cached_online
    with _probe_inflight_lock:
        if key not in _probe_inflight:
            _probe_inflight.add(key)

            def _job():
                try:
                    _channel_online(platform, channel)   # blocking; result lands in platform cache
                except Exception:
                    pass
                finally:
                    with _probe_inflight_lock:
                        _probe_inflight.discard(key)
            try:
                _get_probe_executor().submit(_job)
            except Exception:
                with _probe_inflight_lock:
                    _probe_inflight.discard(key)
    return cached_online   # last-known value if stale, else unknown-for-now


def _candidate(url=None, embed=None, platform=None, channel=None,
               main=False, official=False, language=None, attested=False, source=""):
    """Normalize one stream into a pool candidate. `attested` = the SOURCE says this stream is the
    live broadcast of a currently-live match (frag only lists live matches; PandaScore streams_list
    on a `running` match) — stronger than an unverifiable platform check, weaker than a positive one."""
    raw = (url or "").strip()
    emb = (embed or "").strip()
    if platform is None:
        platform, channel = _parse_platform_channel(emb or raw)
    if platform is None:
        return None
    if channel is None and platform in ("twitch", "kick"):
        _, channel = _parse_platform_channel(emb or raw)
    embed_url = _embed_url(platform, channel, emb or raw)
    click = raw or (_chan_url(platform, channel) if channel else emb)
    if not (click or embed_url):
        return None
    return {"platform": platform, "channel": channel, "url": click or embed_url,
            "embedUrl": embed_url, "main": bool(main), "official": bool(official),
            "language": (language or "").lower() or None, "attested": bool(attested),
            "source": source}


def _rule_candidates(title_slug, league):
    """Hardcoded-rule candidates for a title/league (may be empty)."""
    ls = re.sub(r"[^a-z0-9]+", "", (league or "").lower())
    out = []
    for rule in _WATCH_RULES:
        t, kw, cands = rule[0], rule[1], rule[2]
        exclude = rule[3] if len(rule) > 3 else None
        if t != title_slug or (kw is not None and kw not in ls) or (exclude is not None and exclude in ls):
            continue
        for platform, ch in cands:
            if platform == "web":
                out.append(_candidate(url=ch, platform="web", channel=None, source="rule"))
            else:
                out.append(_candidate(url=_chan_url(platform, ch), platform=platform, channel=ch,
                                      source="rule"))
        break
    out += _yt_channel_candidates(league)
    return [c for c in out if c]


def _watch_shape(c, online, viewers=None):
    return {"platform": c["platform"], "url": c["url"], "channel": c.get("channel"),
            "embedUrl": c.get("embedUrl"), "online": online,
            # Surface the stream's language (already used for ranking above) so the board can demote a
            # non-English broadcast from the auto-playing hero. None = unknown (treated as non-foreign).
            "language": c.get("language"),
            # Live viewer count (None = unknown/unverifiable) — lets the board sort by what's
            # actually being watched instead of only competitive prestige. See _viewer_count.
            "viewers": viewers}


def _pick_stream(candidates, match_live=True, team_names=None, network_checks=True,
                  game=None, max_alternates=4, extra_hints=None):
    """Rank the pool, return the watch dict with `alternates`, or None if the pool is empty.

    Selection: drop positively-offline candidates (unless ALL are offline); rank the rest by
    (platform prio, liveness confidence, main+official, English). `online` on the result: True when
    confirmed or attested, True when unverifiable but the MATCH is live-confirmed upstream (prior
    patch's rule, kept deliberately — see module docstring), False only when positively dark.

    `network_checks=False` (a scheduled match not starting soon) skips BOTH the Twitch/Kick
    liveness ping and YouTube resolution below — those are per-candidate blocking HTTP calls with
    multi-second timeouts and no concurrency; running them for every one of ~500 scheduled PS
    matches on a single rebuild pass is what hung the /api/esports/upcoming endpoint entirely
    (2026-07-08). Candidates still carry whatever embedUrl they got for free (Twitch/Kick synthesize
    one from the channel with zero network cost); only YouTube (which needs the network to resolve
    at all) stays an unembedded link until the match is close enough to be worth the round trip."""
    pool = []
    seen = set()
    for c in candidates:
        if not c:
            continue
        k = (c["platform"], c.get("channel") or c.get("embedUrl") or c.get("url"))
        if k in seen:
            continue
        seen.add(k)
        # TWITCH and KICK are both positively verifiable now (decapi; official Kick API since
        # 2026-07-22), so verify either even when a source attests the stream — attestation goes
        # STALE (frag/PS keep listing a broadcast channel after it goes dark), and a
        # confirmed-offline channel must never ship as a live embed on the strength of a stale
        # attestation (live Twitch case: frag's foreign co-stream `locomass22`, already offline,
        # was outranking the live Kick main; same risk now applies to Kick, e.g. an attested Kick
        # candidate whose stream ended between maps). YouTube keeps the attestation shortcut — no
        # free liveness check exists for it.
        # network_checks: True = blocking ping (S_LIVE branch, already scoped to a handful of
        # matches); "cache" = non-blocking cached read + background refresh (scheduled near-start
        # matches, off the rebuild path — never block the rebuild on a ping); False = skip entirely.
        checked = None
        if network_checks and c.get("channel") and (c["platform"] in ("twitch", "kick") or not c.get("attested")):
            checked = (_channel_online_cached(c["platform"], c.get("channel"))
                       if network_checks == "cache"
                       else _channel_online(c["platform"], c.get("channel")))
        c = dict(c)
        c["_checked"] = checked
        pool.append(c)
    if not pool:
        return None

    # Fill embedUrl on YouTube candidates (deterministic currentVideoEndpoint id, verified
    # right-channel + live/upcoming + embeddable, team-name-disambiguated on multi-stream channels
    # — see yt_live_resolver). A resolved embed flips `playable` to 0 so YouTube's platform
    # priority wins; unresolved stays embed-less and Twitch/Kick wins. Runs for near-term scheduled
    # matches too (a PS-provided scheduled YouTube handle resolves via eventType=upcoming) — the
    # inner loop only makes a network call for actual youtube-platform candidates, so this costs
    # nothing extra on matches with no YouTube candidate at all.
    if network_checks:
        resolve_pool_youtube(pool, team_names, game, extra_hints=extra_hints)

    # A positively-dark candidate (decapi False) is excluded even if attested — a stale attestation
    # can't resurrect a channel decapi confirms is offline (see the per-candidate check above).
    selectable = [c for c in pool if c["_checked"] is not False]
    ranked_from = selectable or pool

    def _rank(c):
        conf = 0 if c["_checked"] is True else (1 if c.get("attested") else 2)
        lang = c.get("language")
        # Play IN the app, don't link out: a candidate we can actually EMBED beats one we can't,
        # before any platform preference. A YouTube channel-handle /live URL has no video id to
        # synthesize an embed from, so it must not outrank an embeddable Twitch of the same
        # broadcast (MIBR Academy v la Masia: youtube.com/@gamersclubvalorant/live had no embed
        # while twitch.tv/gamersclubvalorant did). Among embeddable candidates YouTube still wins.
        playable = 0 if c.get("embedUrl") else 1
        # Never rank a KNOWN-foreign broadcast above a non-foreign one (Micah's call): a Russian
        # YouTube cast must not beat the official English Kick main. Unknown language (None) is
        # treated as non-foreign so YouTube priority is preserved when we simply don't know.
        foreign = 1 if (lang and lang != "en") else 0
        return (playable, foreign,
                _PLATFORM_PRIO.get(c["platform"], 9), conf,
                0 if (c.get("main") and c.get("official")) else 1,
                0 if lang == "en" else 1)

    # Every remaining candidate is positively DARK (decapi-confirmed offline) and unattested — i.e.
    # a pool of dead guesses, not the real broadcast (the classic case: a regional LoL match whose
    # per-match PS stream hasn't posted, leaving only the global `riotgames` rule, which is offline
    # because that channel never carries a specific regional game). Shipping the top one flagged
    # online=false is worse than nothing: the frontend can't embed a dark channel so it renders a
    # dead "· TWITCH ↗" link, and the visibility filter counts a non-null `watch` as a stream, which
    # keeps a PandaScore phantom-`running` card on the live board with no way to actually watch it.
    # Return None so the match honestly has no stream — the board filter then drops it (no odds, no
    # stream) or shows "no stream available", and a real embed appears the moment an ATTESTED stream
    # posts (which skips this check entirely). Attested candidates are never in this bucket.
    if not selectable:
        return None

    ranked = sorted(ranked_from, key=_rank)
    top = ranked[0]

    def _online_val(c):
        if c["_checked"] is False:
            return False  # decapi says dark — overrides a stale attestation
        if c["_checked"] is True or c.get("attested"):
            return True
        return True if match_live else None  # unverifiable on a live-confirmed match -> embed anyway

    # Viewer count belongs to the winning primary (the source shown by default). Alternates can be
    # selected manually and, crucially, can prove that a shared broadcast is still on-air between
    # games; do not stamp an alternate's audience onto the primary source.
    top_online = _online_val(top)
    if network_checks is True:
        top_viewers = _viewer_count(top, confirmed_live=top_online is True)
    elif network_checks == "cache" and any(_online_val(c) is True for c in ranked):
        # A scheduled row can represent the same continuous broadcast during a gap. Its preferred
        # YouTube source is not independently liveness-checkable, while a Twitch/Kick alternate can
        # still prove the broadcast is on-air. Keep the preferred source and scheduled state, but
        # continue its own viewer sampling from cache/off-thread so the count does not disappear
        # between games. No platform may perform a blocking viewer read on this rebuild thread.
        top_viewers = _viewer_count_cached(
            top,
            confirmed_live=top_online is True,
        )
    else:
        top_viewers = None
    watch = _watch_shape(top, top_online, top_viewers)
    alts = []
    for c in ranked[1:]:
        alts.append(_watch_shape(c, _online_val(c)))
        if len(alts) >= max_alternates:
            break
    watch["alternates"] = alts
    return watch


def _resolve_watch(title_slug, league, live=False, extra_candidates=None, team_names=None,
                    network_checks=True):
    """Rule candidates, plus (for scheduled matches) real per-match candidates from PS/frag when
    given — a PS scheduled match often already carries its stream (including a YouTube handle,
    e.g. '@ValorantEsportsKR/live') well before it goes live, and YouTube supports resolving a
    scheduled premiere via eventType=upcoming, so a scheduled match doesn't have to wait for the
    live branch to get a real embed. `extra_candidates` triggers full pool resolution (network
    calls, cached); without it this stays the old zero-network rule-only lookup (finished matches /
    no per-match data). `network_checks=False` for scheduled matches far out — see _pick_stream."""
    cands = _rule_candidates(title_slug, league) + (extra_candidates or [])
    if not cands:
        return None
    if extra_candidates:
        return _pick_stream(cands, match_live=live, team_names=team_names,
                             network_checks=network_checks)
    if not live:
        w = _watch_shape(cands[0], None)
        w["alternates"] = []
        return w
    return _pick_stream(cands, match_live=True)
