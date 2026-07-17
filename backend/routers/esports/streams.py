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
network; Kick's API is Cloudflare-403 from our datacenter IP so Kick liveness is UNVERIFIABLE — it
ranks last so we only land on it when nothing better exists). Within a platform: source-attested-live
first, then main+official, then English. A candidate that is POSITIVELY offline (Twitch via decapi)
is excluded unless every candidate is offline — then the top one ships flagged online=false, honestly.

Kick policy (evaluating the prior patch): embedding an unverifiable Kick channel is RIGHT when the
match itself is live-confirmed upstream and the candidate is source-attested (frag/PandaScore list it
as the live broadcast) — the player handles a dark channel gracefully and alternates now give an
escape hatch. It stays wrong only as a sole blind hardcoded guess, which the ranking already demotes.
"""

import json
import re
import threading
import time
import urllib.request as _u
from concurrent.futures import ThreadPoolExecutor

from .yt_live_resolver import resolve_pool_youtube

# Hardcoded per-league channel rules — the LAST-RESORT candidate source (frag/PandaScore per-match
# streams rank ahead of these in the pool). Kept from streams.py; still used alone for scheduled
# matches ("where it'll air").
_WATCH_RULES = [
    ("league-of-legends", "midseason", [("twitch", "riotgames")]),
    ("league-of-legends", "primeleague", [("twitch", "primeleague")]),
    ("league-of-legends", None, [("twitch", "riotgames")]),
    ("valorant", "esportsworldcup", [("twitch", "ewc_stcarena_en"), ("twitch", "ewc")]),
    ("valorant", "emea", [("twitch", "valorant_emea")]),
    ("valorant", "pacific", [("twitch", "valorant_pacific")]),
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
# (unverifiable from this host — kick.com/api/v1|v2 both 403 via Cloudflare, verified 2026-07-03),
# then bare web links.
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


def _yt_channel_candidates(league):
    ls = re.sub(r"[^a-z0-9]+", "", (league or "").lower())
    out = []
    for kw, chan_id in _YT_TOURNAMENT_CHANNELS:
        if kw in ls:
            out.append(_candidate(url=f"https://www.youtube.com/channel/{chan_id}/live",
                                   platform="youtube", channel=None, source="rule-yt"))
    return out

_live_cache = {}       # "platform:channel" -> (ts, True|False|None)
_LIVE_TTL = 90         # confirmed statuses
_LIVE_TTL_UNKNOWN = 600  # unverifiable (Kick 403) — don't re-ping a blocked API every rebuild


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
    """True/False/None per platform. Twitch: decapi.me (works from this host). Kick: api 403s from
    our datacenter IP (Cloudflare) -> None, cached longer so we don't hammer a blocked endpoint.
    YouTube: no free liveness endpoint -> None (a frag-attested YouTube stream is live by listing)."""
    if platform not in ("twitch", "kick"):
        return None
    key = f"{platform}:{channel}"
    c = _live_cache.get(key)
    if c and time.time() - c[0] < (_LIVE_TTL if c[1] is not None else _LIVE_TTL_UNKNOWN):
        return c[1]
    online = None
    try:
        if platform == "twitch":
            with _u.urlopen(_u.Request(f"https://decapi.me/twitch/uptime/{channel}",
                                       headers={"User-Agent": "Mozilla/5.0"}), timeout=6) as r:
                txt = r.read().decode().lower()
            online = bool(txt.strip()) and not any(w in txt for w in ("offline", "error", "unable", "not found"))
        else:  # kick — expected to fail (403) from this host; kept so it self-heals if unblocked
            with _u.urlopen(_u.Request(f"https://kick.com/api/v2/channels/{channel}",
                                       headers={"User-Agent": "Mozilla/5.0"}), timeout=6) as r:
                online = json.loads(r.read().decode()).get("livestream") is not None
    except Exception:
        online = None
    _live_cache[key] = (time.time(), online)
    return online


# Background liveness pool: the decapi/Kick ping is the ONLY blocking network call in _pick_stream.
# Running it inline for scheduled matches on the rebuild path is what let the broadcast-liveness
# promotion hang the endpoint. Mirror the YouTube resolver: the rebuild reads _live_cache ONLY
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
    decapi probe refreshes _live_cache for next cycle. Never touches the network on the caller's
    thread. Only twitch/kick are verifiable (others -> None, no probe)."""
    if platform not in ("twitch", "kick") or not channel:
        return None
    key = f"{platform}:{channel}"
    c = _live_cache.get(key)
    if c and time.time() - c[0] < (_LIVE_TTL if c[1] is not None else _LIVE_TTL_UNKNOWN):
        return c[1]
    with _probe_inflight_lock:
        if key not in _probe_inflight:
            _probe_inflight.add(key)

            def _job():
                try:
                    _channel_online(platform, channel)   # blocking; result lands in _live_cache
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
    return c[1] if c else None   # last-known value if stale, else unknown-for-now


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
    for t, kw, cands in _WATCH_RULES:
        if t != title_slug or (kw is not None and kw not in ls):
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


def _watch_shape(c, online):
    return {"platform": c["platform"], "url": c["url"], "channel": c.get("channel"),
            "embedUrl": c.get("embedUrl"), "online": online,
            # Surface the stream's language (already used for ranking above) so the board can demote a
            # non-English broadcast from the auto-playing hero. None = unknown (treated as non-foreign).
            "language": c.get("language")}


def _pick_stream(candidates, match_live=True, team_names=None, network_checks=True,
                  game=None, max_alternates=4):
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
        # TWITCH is positively verifiable (decapi), so verify it even when a source attests the
        # stream — attestation goes STALE (frag/PS keep listing a broadcast channel after it goes
        # dark), and a decapi-confirmed-offline Twitch must never ship as a live embed on the
        # strength of a stale attestation (live case: frag's foreign Twitch co-stream `locomass22`,
        # already offline, was outranking the live Kick main). Other platforms keep the attestation
        # shortcut: Kick's API 403s from our datacenter IP so we genuinely can't verify it, and
        # probing every unattested pool candidate is what the rebuild-cost note below guards.
        # network_checks: True = blocking decapi ping (S_LIVE branch, already scoped to a handful of
        # matches); "cache" = non-blocking cached read + background refresh (scheduled near-start
        # matches, off the rebuild path — never block the rebuild on a ping); False = skip entirely.
        checked = None
        if network_checks and c.get("channel") and (c["platform"] == "twitch" or not c.get("attested")):
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
        resolve_pool_youtube(pool, team_names, game)

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

    watch = _watch_shape(top, _online_val(top))
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
