"""yt_live_resolver.py — CANDIDATE: resolve a YouTube LIVE embedUrl from a frag stream URL.

Integration-ready helper for streams.py. Reliable, NEVER embeds a wrong/dead video, no browser in
the request path (<=3 cached HTTP GETs per channel per TTL; a rebuild touches ~1-3 YT channels).

THREE independent gates make a wrong/dead embed impossible — any failure => return None, and the
caller keeps the Twitch/Kick candidate (whose `playable` rank then wins). We either embed the RIGHT
channel's live, embeddable stream, or we embed nothing from YouTube.

  (1) WHICH VIDEO — deterministic, not "first recommended".
      currentVideoEndpoint.watchEndpoint.videoId from the /live page's ytInitialData. Proven stable
      across fetches (the old bug embedded a random recommended id that changed every fetch).
  (2) RIGHT CHANNEL + ACTUALLY LIVE — from the watch page (ungated, no login):
      canonicalBaseUrl must equal the frag-provided @handle (defeats a cross-channel mismatch), and
      '"isLive":true' must be present (defeats embedding a VOD if /live ever falls back to one).
  (3) EMBEDDABLE — oEmbed returns HTML only for videos the owner allows to embed; a 401/404 here
      means "embedding disabled" -> don't embed a broken player, fall back to Twitch.

Verified live 2026-07-03 on Valorant VCL Brazil "MIBR Academy v la Masia":
  @gamersclubvalorant/live -> videoId uDsAKdT62Fw (stable x3), oEmbed title
  "LM 1x0 MIBR AC | GC VALORANT Challengers Brazil 2026 ...", author @gamersclubvalorant,
  watch page isLive:true + canonicalBaseUrl /@gamersclubvalorant. Ranked above Twitch, Twitch kept
  as an alternate. (Pixel-proof of playback is blocked by YouTube's datacenter-IP bot gate on this
  server; production embeds load in the user's browser from a residential IP — see review doc.)
"""

import json
import os
import re
import threading
import time
import urllib.request as _u
import urllib.error as _ue
from concurrent.futures import ThreadPoolExecutor

# Official YouTube Data API v3 — the only clean way past the datacenter-IP bot wall that strips
# the videoId from scraped /live pages (a plain headless browser hits "Sign in to confirm you're
# not a bot" from this egress). Returns the SPECIFIC live videoId for a SPECIFIC channel, so it
# also fixes the EWC multi-simulcast case a channel-live embed can't. Inert (=> keep Twitch) until
# a valid key is set. Key checked lazily so dropping it in needs no code change / restart-only.
def _yt_api_key():
    return (os.environ.get("YOUTUBE_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
_HDRS = {"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9", "Cookie": "CONSENT=YES+1"}

_resolve_cache = {}   # (frag_url, team_names) -> (ts, embedUrl|None)
_TTL = 900            # 15min — search.list costs 100 quota units/call against a ~100/day project
                       # default; the old 90s TTL against a live-board rebuild cadence burned the
                       # entire day's quota in under an hour (2026-07-08 incident, zero streams
                       # ever resolved). Do not drop this back down without raising the Cloud quota.
_TTL_NEG = 600         # a failed resolution still cost a real call; don't hammer it every rebuild
_VID_RE = r"[A-Za-z0-9_-]{11}"

# Hard daily budget on search.list (the only quota-expensive call here — channels.list/videos.list
# are 1 unit, search.list is 100). Default project quota is ~100 search.list calls/day; capping
# well under that leaves headroom for the rest of the day and fails closed (None, same as any other
# gate in this module) instead of spending the whole budget and then 429ing silently with nothing
# to show for it.
_DAILY_SEARCH_BUDGET = 40
_search_budget = {"day": None, "used": 0}


def _search_call_allowed():
    day = time.strftime("%Y-%m-%d", time.gmtime())
    if _search_budget["day"] != day:
        _search_budget["day"] = day
        _search_budget["used"] = 0
    if _search_budget["used"] >= _DAILY_SEARCH_BUDGET:
        return False
    _search_budget["used"] += 1
    return True


# ---------------------------------------------------------------------------
# Free path: scrape the channel's /streams tab. Costs ZERO Data API quota (it's a plain
# youtube.com page fetch, same mechanism as the existing /live scrape below) and — unlike
# search.list — returns EVERY concurrently live/upcoming video on the channel in one request, so
# a rebuild that touches a handful of tournament channels costs a handful of HTTP GETs, not a
# per-match API call. This is now the PRIMARY resolution path; the paid Data API
# (_data_api_find_video) is kept only as a fallback for a channel this scrape can't reach.
# Verified 2026-07-08 against @ewc (UCENNtCRTPTdH_IGXs42LuHQ): correctly lists concurrent LIVE
# (ALGS, Dota Stream A/B/C) and UPCOMING (Opening Ceremony) entries with real titles.
_channel_streams_cache = {}   # channel_id -> (ts, [{"videoId","title","status"}])
_CHANNEL_STREAMS_TTL = 300    # 5min — cheap enough to refresh often, still one fetch per channel


def _find_lockups(node, out):
    """Recursively collect every lockupViewModel dict from parsed ytInitialData (no regex —
    Python's stdlib re can't balance-match nested braces, and this is more robust anyway)."""
    if isinstance(node, dict):
        lv = node.get("lockupViewModel")
        if isinstance(lv, dict):
            out.append(lv)
        for v in node.values():
            _find_lockups(v, out)
    elif isinstance(node, list):
        for it in node:
            _find_lockups(it, out)


def _channel_streams(channel_ref):
    """channel_ref is a UC id or an '@handle' — both resolve on youtube.com directly."""
    c = _channel_streams_cache.get(channel_ref)
    if c and time.time() - c[0] < _CHANNEL_STREAMS_TTL:
        return c[1]
    out = []
    try:
        base = ("channel/" + channel_ref) if channel_ref.startswith("UC") else channel_ref
        html = _get("https://www.youtube.com/%s/streams" % base, timeout=10)
        m = re.search(r"ytInitialData\s*=\s*(\{.*?\});</script>", html)
        if m:
            data = json.loads(m.group(1))
            lockups = []
            _find_lockups(data, lockups)
            for lv in lockups:
                vid = lv.get("contentId")
                if not vid or not re.fullmatch(_VID_RE, vid):
                    continue
                title = None
                try:
                    title = lv["metadata"]["lockupMetadataViewModel"]["title"]["content"]
                except Exception:
                    pass
                badge = None
                try:
                    for ov in lv["contentImage"]["thumbnailViewModel"]["overlays"]:
                        for b in ov.get("thumbnailBottomOverlayViewModel", {}).get("badges", []):
                            badge = b.get("thumbnailBadgeViewModel", {}).get("text")
                except Exception:
                    pass
                status = ("live" if badge == "LIVE" else
                          "upcoming" if badge == "Upcoming" else "past")
                out.append({"videoId": vid, "title": title or "", "status": status})
    except Exception:
        out = []
    _channel_streams_cache[channel_ref] = (time.time(), out)
    return out


_ARENA_TAG_RE = re.compile(r"\b(stream|stage|arena|court|group)\s*([a-z0-9]{1,3})\b", re.I)


def extract_arena_tag(text):
    """Pull a stable disambiguating label like 'stream a' out of a broadcast title/live-title, when
    present. Team names don't survive across platforms for a multi-arena event (EWC's YouTube
    titles never carry them — verified 2026-07-08), but the ARENA LABEL does: Twitch's live title
    'Vici Gaming vs. PVISION | Dota 2 at EWC 26 - Day 2 - Group Stage - Stream A - LIVE' and
    YouTube's static video title 'Dota 2 at EWC 26 - Day 2 - Group Stage - Stream A' share
    'Stream A' verbatim even though nothing else does — so cross-referencing on the PART of the
    title that's platform-invariant (not the part that's match-specific) disambiguates generally,
    not just for EWC."""
    m = _ARENA_TAG_RE.search(text or "")
    return ("%s %s" % (m.group(1), m.group(2))).lower() if m else None


# A board game title -> the word(s) identifying its broadcast in a YouTube video title. A
# multi-game tournament channel (EWC runs Valorant + Dota + ALGS + CS2 simultaneously) is narrowed
# to the right GAME before arena/team disambiguation — one Valorant stream is live so it resolves
# immediately; Dota has 3 (Stream A/B/C) and still needs the arena tag.
_GAME_KW = {
    "valorant": ("valorant",),
    "dota 2": ("dota",),
    "cs2": ("cs2", "counter-strike", "counter strike"),
    "lol": ("league of legends", "lol"),
    "league of legends": ("league of legends", "lol"),
    "rocket league": ("rocket league",),
}


def _game_keywords(game):
    return _GAME_KW.get((game or "").strip().lower(), ())


def _scrape_find_video(channel_ref, team_names=None, status="live", extra_hints=None, game=None):
    """Free-path equivalent of _data_api_find_video: pick the one video in `status` on this
    channel that's THIS match, or None if ambiguous. Same fail-closed contract — a channel running
    several concurrent broadcasts with no shared textual signal at all stays unresolved rather than
    guessing the wrong arena. `game` narrows to the match's title first (EWC runs several games at
    once); `extra_hints` (an arena tag from an attested Twitch title, see extract_arena_tag) match as
    literal substrings, unlike `team_names` which get tokenized/length-filtered."""
    items = [it for it in _channel_streams(channel_ref) if it["status"] == status]
    if not items:
        return None
    # Narrow to the match's GAME first — an EWC Valorant match must not resolve to a Dota stream.
    gk = _game_keywords(game)
    if gk and len(items) > 1:
        gitems = [it for it in items if any(k in it["title"].lower() for k in gk)]
        if gitems:
            items = gitems
    if len(items) == 1:
        return items[0]["videoId"]
    names = _name_variants(team_names) | {h.lower() for h in (extra_hints or []) if h}
    if not names:
        return None
    hits = [it for it in items if any(n in it["title"].lower() for n in names)]
    return hits[0]["videoId"] if len(hits) == 1 else None


def _get(url, timeout=8):
    with _u.urlopen(_u.Request(url, headers=_HDRS), timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _direct_video_id(url):
    for pat in (r"[?&]v=(" + _VID_RE + r")", r"youtu\.be/(" + _VID_RE + r")",
                r"/live/(" + _VID_RE + r")", r"/embed/(" + _VID_RE + r")"):
        m = re.search(pat, url or "")
        if m:
            return m.group(1)
    return None


def _handle_from_url(url):
    m = re.search(r"youtube\.com/(@[A-Za-z0-9_.\-]+)", url or "")
    if m:
        return m.group(1).lower()
    m = re.search(r"youtube\.com/channel/(UC[A-Za-z0-9_\-]+)", url or "")
    return m.group(1) if m else None


def _live_page_video_id(live_url):
    """Deterministic currentVideoEndpoint videoId from a channel /live page, or None."""
    try:
        html = _get(live_url)
        m = re.search(r"ytInitialData\s*=\s*(\{.*?\});</script>", html)
        if not m:
            return None
        cve = (json.loads(m.group(1)).get("currentVideoEndpoint") or {})
        vid = (cve.get("watchEndpoint") or {}).get("videoId")
        return vid if (vid and re.fullmatch(_VID_RE, vid)) else None
    except Exception:
        return None


def _channel_id_from_live_page(live_url):
    """UC channel id from a channel /live page. Survives the datacenter bot wall that strips
    ytInitialData (the videoId gate fails on this server, but externalId/browseId persist), so
    it's the anchor for the channel-live embed fallback. Returns a UC id or None."""
    try:
        html = _get(live_url)
    except Exception:
        return None
    for pat in (r'"externalId":"(UC[A-Za-z0-9_-]{22})',
                r'"browseId":"(UC[A-Za-z0-9_-]{22})',
                r'"channelId":"(UC[A-Za-z0-9_-]{22})'):
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return None


def _name_variants(team_names):
    """Team names -> lowercase substrings worth matching in a video title/description. Splits
    multi-word names ('Team Spirit') so a caster's shorthand ('Spirit') still hits, but drops
    short/common tokens (<4 chars — 'OG', 'X-CAST') that would false-positive on generic words."""
    out = set()
    for n in team_names or ():
        n = (n or "").strip().lower()
        if not n:
            continue
        if len(n) >= 3:
            out.add(n)
        for tok in re.split(r"[\s.\-]+", n):
            if len(tok) >= 4:
                out.add(tok)
    return out


def _data_api_find_video(channel_id, key, team_names=None, event_type="live", extra_hints=None, game=None):
    """Official Data API v3: a videoId live/upcoming on a channel right now, matched to THIS match.

    A big tournament org (EWC verified 2026-07-08: 5 simultaneous live videos — ALGS, Fatal Fury,
    Dota Stream A/B/C) frequently multi-simulcasts; a PandaScore/frag-attested per-match channel can
    do the same (one caster handle running several games). Guessing among concurrent videos risks
    embedding the WRONG game, worse than the honest Twitch fallback — so:
      - exactly one candidate on the channel => trust it (nothing to disambiguate).
      - multiple candidates => only resolve if team_names picks out exactly ONE by substring match
        against title+description (we already know from frag/PS which match this channel belongs
        to, so trusting a name hit here is sound, not a guess).
      - no unique signal => None, fail-closed like every other gate in this module.
    """
    if not _search_call_allowed():
        return None
    try:
        q = ("https://www.googleapis.com/youtube/v3/search?part=snippet&type=video"
             "&eventType=%s&maxResults=10&channelId=%s&key=%s" % (event_type, channel_id, key))
        d = json.loads(_get(q, timeout=6))
        items = d.get("items") or []
        if not items:
            return None
        gk = _game_keywords(game)
        if gk and len(items) > 1:
            gitems = [it for it in items
                      if any(k in ((it.get("snippet") or {}).get("title") or "").lower() for k in gk)]
            if gitems:
                items = gitems
        if len(items) == 1:
            vid = items[0]["id"]["videoId"]
            return vid if re.fullmatch(_VID_RE, vid) else None
        names = _name_variants(team_names) | {h.lower() for h in (extra_hints or []) if h}
        if not names:
            return None
        hits = []
        for it in items:
            sn = it.get("snippet") or {}
            text = ((sn.get("title") or "") + " " + (sn.get("description") or "")).lower()
            if any(n in text for n in names):
                hits.append(it)
        if len(hits) == 1:
            vid = hits[0]["id"]["videoId"]
            return vid if re.fullmatch(_VID_RE, vid) else None
        return None
    except Exception:
        return None


def _watch_ownership_and_live(video_id):
    """(canonical_handle, channel_id, is_live) from the ungated watch page, or (None,None,None)."""
    try:
        html = _get("https://www.youtube.com/watch?v=" + video_id)
    except Exception:
        return None, None, None
    h = re.search(r'"canonicalBaseUrl":"(/@[^"]+)"', html)
    cid = re.search(r'"channelId":"(UC[\w-]+)"', html)
    handle = h.group(1).lstrip("/").lower() if h else None
    is_live = '"isLive":true' in html
    return handle, (cid.group(1) if cid else None), is_live


def _is_embeddable(video_id):
    """oEmbed 200 <=> owner allows embedding this video."""
    try:
        _get("https://www.youtube.com/oembed?format=json&url="
             "https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3D" + video_id, timeout=6)
        return True
    except (_ue.HTTPError, _ue.URLError, Exception):
        return False


def yt_live_embed(url, team_names=None, extra_hints=None, game=None):
    """A frag/PS YouTube stream URL -> confirmed embeddable embedUrl, or None (=> keep Twitch).
    Cached per (url, team_names, game). Fail-CLOSED: any uncertainty returns None, never a
    wrong/dead VOD.

    A URL with a specific video id (frag/PS already picked one) just gets confirmed: right
    channel, live, embeddable. A bare channel URL (no video id) needs to pick the right one of
    however many videos that channel has live/upcoming right now — done via the FREE /streams-tab
    scrape (_scrape_find_video, no API quota), matched by team name or `extra_hints` (an arena tag
    cross-referenced from another platform's live title — see resolve_pool_youtube). Only if that
    scrape turns up nothing at all does this fall back to the budget-capped paid Data API."""
    if not url or ("youtube" not in url and "youtu.be" not in url):
        return None
    names = tuple(sorted(_name_variants(team_names)))
    # Key on (url, team_names, game) — NOT the arena hint (that needs a network call to compute, so
    # keying on it would make the rebuild-path peek, which has no hint, miss). game is in the key so
    # two matches sharing a channel url + ambiguous teams still resolve to their own game's stream.
    ck = (url, names, (game or "").lower())
    c = _resolve_cache.get(ck)
    if c and time.time() - c[0] < (_TTL if c[1] else _TTL_NEG):
        return c[1]

    result = None
    try:
        want = _handle_from_url(url)
        vid = _direct_video_id(url)
        if vid:
            # frag/PS gave a SPECIFIC video already — just confirm it's the right channel, live,
            # and embeddable. No disambiguation needed, nothing to cross-reference.
            handle, cid, is_live = _watch_ownership_and_live(vid)
            nh = (handle or "").lstrip("@")
            owner_ok = (want is None or                                   # frag gave a bare video id
                        (want.startswith("@") and nh and nh == want.lstrip("@")) or
                        (want.startswith("UC") and cid == want))
            if owner_ok and is_live and _is_embeddable(vid):
                result = "https://www.youtube.com/embed/%s?autoplay=1" % vid
        elif want:
            # A channel-level URL (no specific video) — on an org channel running several
            # concurrent broadcasts (EWC: verified 2026-07-08, up to 5 simultaneous live videos)
            # the /live page's redirect is an ARBITRARY pick, so go straight to the candidate list
            # instead of trusting a single scrape. FREE (no Data API quota): scrape the channel's
            # /streams tab for every live/upcoming video at once, cached per channel.
            hints = list(extra_hints or [])
            for status in ("live", "upcoming"):
                vid2 = _scrape_find_video(want, team_names, status, hints, game)
                if vid2 and _is_embeddable(vid2):
                    result = "https://www.youtube.com/embed/%s?autoplay=1" % vid2
                    break
            # Scrape found nothing at all for this channel (bot wall on this box on a given day,
            # or an unusual page layout) — fall back to the paid Data API, budget-capped so a bad
            # day can't zero out the quota again (2026-07-08 incident).
            if result is None:
                key = _yt_api_key()
                if key:
                    cid = want if want.startswith("UC") else _channel_id_from_live_page(url)
                    if cid and cid.startswith("UC"):
                        for et in ("live", "upcoming"):
                            vid3 = _data_api_find_video(cid, key, team_names, et, hints, game)
                            if vid3 and _is_embeddable(vid3):
                                result = "https://www.youtube.com/embed/%s?autoplay=1" % vid3
                                break
    except Exception:
        result = None

    _resolve_cache[ck] = (time.time(), result)
    return result


# Background resolver: all YouTube network work (channel /streams scrape, oEmbed, Twitch-title arena
# hint) runs OFF the rebuild path in this pool, populating _resolve_cache. The rebuild reads cache
# only (see resolve_pool_youtube), so a cold rebuild is O(dict) instead of the 60s+ it took when
# every marquee match scraped inline. Small pool: the work is I/O-bound and dedup keeps it sparse.
_executor = None
_executor_lock = threading.Lock()
_inflight = set()
_inflight_lock = threading.Lock()


def _get_executor():
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="yt-resolve")
    return _executor


def _resolve_peek(url, team_names, game=None):
    """Cache-only read for (url, team_names, game): (embedUrl, fresh?). Never touches the network."""
    names = tuple(sorted(_name_variants(team_names)))
    c = _resolve_cache.get((url, names, (game or "").lower()))
    if not c:
        return None, False
    return c[1], (time.time() - c[0] < (_TTL if c[1] else _TTL_NEG))


def _bg_resolve(yt_urls, team_names, hint_channels, game=None):
    """Background job: does ALL the network — Twitch title -> arena hint -> per-url resolution —
    and populates _resolve_cache. The next rebuild reads the result from cache. Deduped so the same
    match's job doesn't pile up while one is already running."""
    key = (tuple(sorted(yt_urls)), tuple(sorted(_name_variants(team_names))), (game or "").lower())
    with _inflight_lock:
        if key in _inflight:
            return
        _inflight.add(key)
    try:
        # Arena tag from an already-attested Twitch candidate's live title ('Vici Gaming vs. PVISION
        # | ... Stream A - LIVE' -> 'stream a') — the label shared across platforms when the YouTube
        # title carries no team names (EWC's 'Stream A/B/C'). See extract_arena_tag.
        hint = None
        for ch in hint_channels:
            hint = extract_arena_tag(_twitch_live_title(ch))
            if hint:
                break
        hints = [hint] if hint else None
        for url in yt_urls:
            yt_live_embed(url, team_names, hints, game)   # blocking; result lands in _resolve_cache
    except Exception:
        pass
    finally:
        with _inflight_lock:
            _inflight.discard(key)


def resolve_pool_youtube(candidates, team_names=None, game=None):
    """Fill embedUrl on YouTube candidates from CACHE ONLY (zero network on the rebuild path), and
    hand off a background refresh for anything missing or stale. Call ONCE inside _pick_stream,
    before ranking. A resolved embedUrl flips the candidate's `playable` to 0 so YouTube's platform
    priority wins.

    Trade-off (deliberate): a YouTube embed appears ~one rebuild cycle after the match goes live
    instead of blocking the rebuild on per-channel scrapes (which pushed a cold rebuild to 60s+,
    2026-07-08). Until the background job lands, an unresolved YouTube candidate stays embed-less
    and Twitch wins — the same graceful fallback as before, just one cycle sooner to respond."""
    yt_cands = [c for c in candidates
                if c and c.get("platform") == "youtube" and not c.get("embedUrl")]
    if not yt_cands:
        return candidates
    need_refresh = False
    for c in yt_cands:
        cached, fresh = _resolve_peek(c.get("url") or "", team_names, game)
        if cached:
            c["embedUrl"] = cached     # show the last-known embed even while a refresh is pending
        if not fresh:
            need_refresh = True
    if need_refresh:
        yt_urls = [c.get("url") or "" for c in yt_cands]
        hint_channels = [c["channel"] for c in candidates
                         if c and c.get("attested") and c.get("platform") == "twitch"
                         and c.get("channel")]
        try:
            _get_executor().submit(_bg_resolve, yt_urls, team_names, hint_channels, game)
        except Exception:
            pass
    return candidates


_twitch_title_cache = {}   # channel -> (ts, title|None)
_TWITCH_TITLE_TTL = 60     # a live title can change mid-match (new game in a Bo3) — keep it fresh


def _twitch_live_title(channel):
    """A Twitch channel's current live stream title via decapi.me (no auth, free). Used only to
    pull an arena tag for cross-platform disambiguation — see resolve_pool_youtube."""
    c = _twitch_title_cache.get(channel)
    if c and time.time() - c[0] < _TWITCH_TITLE_TTL:
        return c[1]
    title = None
    try:
        txt = _get("https://decapi.me/twitch/title/%s" % channel, timeout=6).strip()
        if txt and not any(w in txt.lower() for w in ("error", "not found", "offline")):
            title = txt
    except Exception:
        title = None
    _twitch_title_cache[channel] = (time.time(), title)
    return title
