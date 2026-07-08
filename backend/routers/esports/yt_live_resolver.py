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
import time
import urllib.request as _u
import urllib.error as _ue

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

_resolve_cache = {}   # frag_url -> (ts, embedUrl|None)
_TTL = 90             # matches the live-slate cache cadence
_TTL_NEG = 45         # re-try a failed resolution sooner than a good one expires
_VID_RE = r"[A-Za-z0-9_-]{11}"


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


def _data_api_live_video_id(channel_id, key):
    """Official Data API v3: the currently-live videoId on a channel, or None. Pins the exact video
    (unlike a channel-live embed) so a multi-simulcast network resolves to THIS channel's cast."""
    try:
        q = ("https://www.googleapis.com/youtube/v3/search?part=snippet&type=video"
             "&eventType=live&maxResults=1&channelId=%s&key=%s" % (channel_id, key))
        d = json.loads(_get(q, timeout=6))
        items = d.get("items") or []
        vid = items[0]["id"]["videoId"] if items else None
        return vid if (vid and re.fullmatch(_VID_RE, vid)) else None
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


def yt_live_embed(url):
    """A frag/PS YouTube stream URL -> confirmed live+embeddable embedUrl, or None (=> keep Twitch).
    Cached per URL. Fail-CLOSED: any uncertainty returns None so we never ship a wrong/dead VOD.

    Path 1 (scrape, no key): deterministic currentVideoEndpoint videoId from the /live page, gated
    on right-channel + isLive + embeddable. Works when the box isn't bot-walled.
    Path 2 (Data API, keyed): when the wall strips the scraped videoId, recover the exact live
    videoId via YouTube Data API v3. Both paths pin a specific videoId — never a channel guess."""
    if not url or ("youtube" not in url and "youtu.be" not in url):
        return None
    ck = url
    c = _resolve_cache.get(ck)
    if c and time.time() - c[0] < (_TTL if c[1] else _TTL_NEG):
        return c[1]

    result = None
    try:
        want = _handle_from_url(url)
        vid = _direct_video_id(url)
        if vid is None:
            if want is None:
                raise ValueError("no video id and no channel handle")
            vid = _live_page_video_id(url)
        if vid:
            handle, cid, is_live = _watch_ownership_and_live(vid)
            nh = (handle or "").lstrip("@")           # watch-page handle, @-normalized
            owner_ok = (want is None or                                   # frag gave a bare video id
                        (want.startswith("@") and nh and nh == want.lstrip("@")) or
                        (want.startswith("UC") and cid == want))
            if owner_ok and is_live and _is_embeddable(vid):
                result = "https://www.youtube.com/embed/%s?autoplay=1" % vid
        # Bot wall stripped the scraped videoId. Recover the EXACT live videoId via the official
        # Data API (channel_id survives the wall even when videoId doesn't). NOT a channel-live
        # embed: that pins no videoId and can surface the wrong arena on EWC's multi-simulcast
        # networks (tried and rejected before). Inert without a key => Twitch kept, same as today.
        key = _yt_api_key()
        if result is None and want and key:
            cid = want if want.startswith("UC") else _channel_id_from_live_page(url)
            if cid and cid.startswith("UC"):
                vid = _data_api_live_video_id(cid, key)
                if vid and _is_embeddable(vid):
                    result = "https://www.youtube.com/embed/%s?autoplay=1" % vid
    except Exception:
        result = None

    _resolve_cache[ck] = (time.time(), result)
    return result


def resolve_pool_youtube(candidates):
    """Integration helper: fill embedUrl on YouTube candidates that lack one. Call ONCE inside
    _pick_stream, before ranking. A resolved embedUrl flips the candidate's `playable` to 0 so
    YouTube's platform priority wins; an unresolved one stays embed-less and Twitch wins."""
    for c in candidates:
        if c and c.get("platform") == "youtube" and not c.get("embedUrl"):
            e = yt_live_embed(c.get("url") or "")
            if e:
                c["embedUrl"] = e
    return candidates
