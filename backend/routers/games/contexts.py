"""routers/games/contexts.py — WC/CoD/Leagues-Cup context endpoints and helpers."""
import json
import os

from fastapi import HTTPException, Query
from typing import Optional
from _core import *
from . import router



def _attach_cod_detail_ids(matches):
    """Add a PandaScore detail id only when the fixture identity resolves.

    BreakingPoint remains the scoreboard source and keeps its own ``game_id``.
    The dedicated CoD detail route is PandaScore-backed, so expose that separate
    id after the shared esports matcher verifies both opponents and match time.
    Unresolved fixtures intentionally stay without a detail id.
    """
    try:
        from routers.esports.pandascore import _iso_to_ms, _ps_enrich
    except Exception as exc:
        print(f"[sports_service] CoD detail identity unavailable ({exc})")
        return matches

    for match in matches:
        # Rows already reconciled (EWC bracket rows carry a PandaScore id from the indexed
        # bracket graph) must not trigger a second, per-row fuzzy lookup.
        if match.get("detail_game_id"):
            continue
        home = (match.get("home") or {}).get("name")
        away = (match.get("away") or {}).get("name")
        near_ms = _iso_to_ms(match.get("date"))
        if not home or not away or not near_ms:
            continue
        try:
            identity = _ps_enrich(
                home,
                away,
                include_running=True,
                near_ms=near_ms,
                league="Call of Duty",
            )
        except Exception as exc:
            print(f"[sports_service] CoD detail identity failed for {match.get('game_id')} ({exc})")
            continue
        if identity and identity.get("_ps_id") is not None:
            match["detail_game_id"] = str(identity["_ps_id"])
    return matches
@router.get("/api/wc/knockout")
def wc_knockout():
    """World Cup knockout bracket — the SAME canonical {rounds:[...]} shape as
    /api/wc/standings during knockouts. Single source of truth:
    espn.wc_knockout_standings(). Returns {rounds:[{round, matches:[{game_id,
    date, home:{abbrev,name}, away:{abbrev,name}, homeScore, awayScore, winner,
    status, state}]}]}."""
    try:
        return espn.wc_knockout_standings()
    except Exception as e:
        raise HTTPException(404, str(e))


@router.get("/api/wc/{game_id}/context")
def wc_context(
    game_id: str,
    limit: int = Query(8, ge=1, le=100),
    phase: Optional[str] = Query(None),
):
    """Phase-aware WC catch-up plus receipt-backed booth episodes.

    With no phase, episodes come from the current match phase. The Booth tab
    may request a past phase on interaction without downloading the whole
    broadcast on initial render.
    """
    allowed_phases = {
        "pregame", "first_half", "halftime", "second_half",
        "extra_time", "penalties", "final",
    }
    if phase is not None and phase not in allowed_phases:
        raise HTTPException(400, f"phase must be one of {sorted(allowed_phases)}")
    import wc_context as _wcc
    ctx = _wcc.build_context(game_id, limit=limit, phase=phase)
    if not ctx:
        raise HTTPException(404, "no context for this game")
    return ctx


@router.get("/api/wc/{game_id}/context/episodes/{episode_id}")
def wc_context_episode(game_id: str, episode_id: str):
    """Full receipt stack for one episode, fetched only when a user expands it."""
    import wc_context as _wcc
    detail = _wcc.get_episode_detail(game_id, episode_id)
    if detail is None:
        # A normal list request primes this bounded derived cache. Rebuild once
        # after a worker restart so an already-open browser can still expand.
        _wcc.build_context(game_id, limit=1)
        detail = _wcc.get_episode_detail(game_id, episode_id)
    if detail is None:
        raise HTTPException(404, "episode not found")
    return detail


@router.get("/api/cod/{game_id}/context")
def cod_game_context(game_id: str, limit: int = Query(12, ge=1, le=100)):
    """Grounded Call of Duty match context from PandaScore history, the existing
    esports slate, and timestamp-matched CDL booth reads."""
    import cod_context as _cod
    ctx = _cod.build_context(game_id, limit=limit)
    if not ctx:
        raise HTTPException(404, "no Call of Duty context for this game")
    return ctx


# Broadcast tapes live in the sibling prediction-market-trading repo. Leagues Cup
# watchers write <YYYYMMDD>_LCUP_<AWAY><HOME>_{transcript,signals}.jsonl there.
_BROADCAST_DIR = "/root/prediction-market-trading/data/broadcast"

_SIGNAL_TAGS = {
    "tilt": "Mentality", "lockin": "Mentality", "fatigue": "Fatigue",
    "tactical": "Tactical", "morale": "Mentality", "momentum": "Momentum",
}


@router.get("/api/lcup/{game_id}/context")
def lcup_game_context(game_id: str, limit: int = Query(12, ge=1, le=100)):
    """Leagues Cup booth: live Spanish radio transcript + soft-signal reads for
    the game, straight from the broadcast_alpha tapes (legacy insights shape,
    newest first). 404 when no watcher is running for this game."""
    import espn_client as _espn
    try:
        summary = _espn.summary("lcup", game_id)
    except Exception:
        raise HTTPException(404, "no context for this game")
    comp = (summary.get("header", {}).get("competitions") or [{}])[0]
    date = (comp.get("date") or "")[:10].replace("-", "")
    abbrevs = {}
    for c in comp.get("competitors", []):
        abbrevs[c.get("homeAway")] = (c.get("team") or {}).get("abbreviation", "")
    if not date or not abbrevs.get("home") or not abbrevs.get("away"):
        raise HTTPException(404, "no context for this game")
    tag = f"{date}_LCUP_{abbrevs['away']}{abbrevs['home']}"

    insights = []

    # Soft signals (DeepSeek-extracted claims) — richer, prefer them first.
    spath = os.path.join(_BROADCAST_DIR, f"{tag}_signals.jsonl")
    if os.path.exists(spath):
        for line in open(spath, encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                s = json.loads(line)
            except Exception:
                continue
            if not s.get("quote"):
                continue
            insights.append({
                "id": f"{tag}-sig-{len(insights)}",
                "tag": _SIGNAL_TAGS.get((s.get("type") or "").lower(), "Momentum"),
                "subject": s.get("subject", "Broadcast"),
                "quote": s["quote"],
                "strength": int(s.get("strength") or 1),
                "ts": s.get("ts"),
                "analysis": (s.get("direction") or "") and f"Booth lean: {s['direction']}",
            })

    # Raw transcript lines — the booth's evidence even before extraction runs.
    # Skip silence/noise lines (whisper renders dead air as dots/single chars).
    tpath = os.path.join(_BROADCAST_DIR, f"{tag}_transcript.jsonl")
    if os.path.exists(tpath):
        for line in open(tpath, encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                t = json.loads(line)
            except Exception:
                continue
            text = (t.get("text") or "").strip()
            if not text:
                continue
            words = [w for w in text.split() if any(ch.isalnum() for ch in w)]
            if len(words) < 2:
                continue
            insights.append({
                "id": f"{tag}-tx-{len(insights)}",
                "tag": "Live",
                "subject": "Radio",
                "quote": text,
                "strength": 1,
                "ts": t.get("ts"),
            })

    if not insights:
        raise HTTPException(404, "no booth data for this game yet")
    insights.sort(key=lambda i: i.get("ts") or "", reverse=True)
    return {"insights": insights[:limit]}


# Free English radio for Leagues Cup — ESPN 106.3 West Palm (WUUB-FM), Inter
# Miami's official English-language radio partner (airs every Inter Miami game).
# amperwave HLS won't play in Chrome's <audio>, so the relay transcodes to MP3
# with ffmpeg and streams it — one ffmpeg per listener.
#
# Sourced from the repo's own radio maps (data/radio-mls.json, verified entries)
# so coverage scales with the JSON instead of this dict. `_LCUP_RADIO` keeps its
# name (game detail + misc.py import it) but now reads ATX/CLB/MIA at startup.
# A stream verified on 2026-08-06 may not resolve today; the endpoint reports
# the failure as a 502 upstream rather than hanging.
# The radio map ships in backend/data/ (mounted into the prod container) with
# the repo-root data/ copy as the authoring location. Both are checked so the
# module works in-container and in-repo.
_RADIO_MLS_CANDIDATES = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "..", "..", "data", "radio-mls.json"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "..", "..", "..", "data", "radio-mls.json"),
]
_RADIO_MLS_PATH = next((p for p in _RADIO_MLS_CANDIDATES if os.path.isfile(p)),
                       _RADIO_MLS_CANDIDATES[0])


def _load_league_radio() -> dict:
    try:
        with open(_RADIO_MLS_PATH) as f:
            d = json.load(f)
        # league -> stream, using only verified entries (never a placeholder).
        return {
            "lcup": d["MIA"]["stream"],  # reference entry: every Inter Miami game
            "mls": d,
        }
    except Exception as exc:
        print(f"[sports_service] radio map unavailable ({exc})")
        return {}


_RADIO_MAP = _load_league_radio()

# Per-club English radio, sourced from data/radio-mls.json (verified entries
# only). Keyed by the lowercase abbrev the frontend's lib/radio.ts streams
# against, e.g. /api/stream/clb. MIA is the lcup reference entry: ESPN 106.3
# airs every Inter Miami game, which is what game detail has always played for
# lcup fixtures without a verified club station of their own.
_LCUP_RADIO = {k.lower(): v["stream"] for k, v in _RADIO_MAP["mls"].items()
               if not k.startswith("_") and isinstance(v, dict)
               and v.get("verified") and v.get("stream")}
_LCUP_RADIO["lcup"] = _LCUP_RADIO["clb"]  # tonight's fixture: Columbus radio
_LCUP_RADIO.setdefault("atx", "https://stream.revma.ihrhls.com/zc7053/hls.m3u8")
