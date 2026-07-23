"""Esports endpoint and rebuild orchestrator around an explicit match state machine.

REDESIGN (2026-07-03 expert review — full critique with live evidence in
logs/SLATE-EXPERT-REVIEW-2026-07-03.md). The public contract is the APIRouter and
``/api/esports/upcoming`` response shape, including these additive fields:

    match.state           'scheduled' | 'live' | 'finished' | 'ended_unknown'
    match.resultUnknown   True on an ended_unknown match (winner/score are null, never fabricated)
    match.watch.alternates  ranked runner-up streams (see streams.reviewed.py)

The two structural fixes over slate.py:

1. ONE IDENTITY, THEN ONE STATE. slate.py mutated two booleans (live/finished) across six
   sequential passes, each with its own ad-hoc name matcher; every matcher miss forked a duplicate
   row or dropped a signal (live evidence 2026-07-03: 'Team Heretics' appeared as THREE rows —
   'v Anyone's Legend' live on a dead twitch/ewc link, 'v AG.AL International' live with the real
   stream, 'v AllGamers' rotting in Scheduled). Here, all source rows are CLUSTERED by one shared
   team matcher first, merged to one row per real-world match, and the state is derived ONCE from
   the combined evidence.

2. STATE IS EVIDENCE, NOT CARRY-OVER. A row Bovada dropped mid-live used to be carried with
   live=False, finished=unknown -> the frontend's `!live && !finished` bucket showed it as
   Scheduled hours after it ended (the "stale scheduled ghosts"). Carried rows now contribute
   IDENTITY only (never live/score), and the invariant holds: no match with a past start time is
   ever emitted as SCHEDULED — it is live, finished, affirmatively delayed (a source says
   not_started), or honestly ENDED_UNKNOWN.

HONESTY RULE: a winner comes only from an explicit source signal (GRID won-flags, PandaScore
winner_id, a settled Kalshi market) — never derived from a partial score (we don't know Bo1 vs
Bo3). A final whose real scoreline we never captured ships score=null, not a fake 0-0.
"""

import importlib.util
import json
import os
import threading
import time

from fastapi import APIRouter

from .common import _TITLE_SLUG, _canon_team
from .frag import _parse_frag_score
from .grid import _grid_score_index
from .kalshi import _kalshi_esports_matchups
from .league_tier import apply_tier_and_filter
from .lol import msi_predictions
from .match_identity import (_is_map_market, _normalize_match_metadata,
                             _repair_logos_by_psid, _same_pair, _same_team)
from .pandascore import (_ps_enrich, _ps_logo_for, _ps_surface_matches, _ps_team_logo_api,
                         _fetch_ps, _iso_to_ms, _stable_stream_key, _PS_VG_TITLE)
from .results_store import _load_results_store, _save_results_store
from .slate_sources import (_fetch_bovada_rows, _frag_candidates, _frag_lookup,
                            _grid_lookup, _kalshi_winner_fuzzy, _ps_candidates)
from .slate_state import (S_ENDED_UNKNOWN, S_FINISHED, S_LIVE, S_SCHEDULED,
                          _CHANNEL_LIVE_TAIL_MS, _FINISH_GRACE_MS, _LIVE_LEAD_MS,
                          _LIVE_TAIL_MS, _START_SLACK_MS, _carry_row, _cluster,
                          _derive_state, _has_result, _is_placeholder_score, _key,
                          _suppress_display_dupes)

# Stream helpers: post-swap these live in streams.py; pre-swap (validation) load the reviewed file
# by path so this module is testable without touching the running streams.py.
try:
    from .streams import _pick_stream, _rule_candidates, _resolve_watch, _yt_sibling_candidates
except ImportError:
    _spec = importlib.util.spec_from_file_location(
        "routers.esports._streams_reviewed",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "streams.reviewed.py"))
    _sr = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_sr)
    _pick_stream, _rule_candidates, _resolve_watch, _yt_sibling_candidates = (
        _sr._pick_stream, _sr._rule_candidates, _sr._resolve_watch, _sr._yt_sibling_candidates)

router = APIRouter()

_up_cache = {"t": 0.0, "data": None}
_up_rebuild_lock = threading.Lock()
_up_rebuilding = False
_up_rebuild_started = 0.0
_REBUILD_STUCK_S = 300
_finish_seen = {}

# How many days of finished results the DURABLE store keeps (the on-disk layer that survives
# restarts). This is the guaranteed floor: after any restart the board reconstructs at least this
# many days of results from disk, instead of dropping to whatever a cold rebuild happens to find.
# The in-memory carry is intentionally NOT capped to this — while a process stays warm it may show
# an older tail on top; this only sets the floor that persists. One knob, env-overridable.
_RESULTS_RETENTION_DAYS = int(os.environ.get("LP_RESULTS_RETENTION_DAYS", "7"))

# ---------------------------------------------------------------------------
# endpoint (stale-while-revalidate, unchanged semantics + stuck-rebuild watchdog)
# ---------------------------------------------------------------------------
@router.get("/api/esports/upcoming")
def esports_upcoming():
    now = time.time()
    global _up_rebuilding, _up_rebuild_started
    # Single-flight, warm OR cold. Serve the cache when fresh; otherwise ensure AT MOST ONE rebuild
    # runs in the background and return whatever we have (the stale board when warm, an empty
    # "building" board on a cold start). The cold path used to call _rebuild_upcoming() inline with
    # NO lock, so a burst of first requests (frontend poll + tab loads) each launched a full rebuild;
    # under the GIL those concurrent rebuilds share one core and thrash the PandaScore canon index,
    # so none finishes, the cache never warms, and the endpoint pins at 100% CPU forever (2026-07-10
    # outage). Now cold callers kick off one rebuild and return immediately, same as the warm path.
    if _up_cache["data"] is not None and now - _up_cache["t"] < _up_cache.get("ttl", 60):
        return _up_cache["data"]
    with _up_rebuild_lock:
        stuck = _up_rebuilding and (now - _up_rebuild_started > _REBUILD_STUCK_S)
        start_build = (not _up_rebuilding) or stuck
        if start_build:
            _up_rebuilding = True
            _up_rebuild_started = now
    if start_build:
        def _bg():
            global _up_rebuilding
            try:
                _rebuild_upcoming()
            except Exception:
                pass  # a failed rebuild must release the single-flight flag, never freeze the slate
            finally:
                with _up_rebuild_lock:
                    _up_rebuilding = False
        threading.Thread(target=_bg, daemon=True).start()
    return _up_cache["data"] or {"matches": [], "building": True}


# ---------------------------------------------------------------------------
# prod board warmer
# ---------------------------------------------------------------------------
# The board above is computed lazily ON-REQUEST: a hit past the TTL kicks off a background rebuild.
# With ~0 organic prod traffic the cache just sits stale, so a short-lived match can come and go
# entirely within one stale window and never surface as live (dev only ever looks correct because
# the monitor cron pokes :8095 every 5 min). This warmer pokes the SAME endpoint path on a timer so
# prod's board recomputes without waiting for a visitor. It lives in-app on purpose — no external
# poker (cron/tunnel) that can silently fall off.
#
# ONE knob: set to 0 to DISABLE and restore the pre-warmer lazy-only behavior. At 3600s the board is
# at most ~1h stale, which is fine while there are no users; drop it toward the 60s live-TTL once
# real traffic / real-time liveness matters. Env var overrides the constant for ops without a rebuild.
ESPORTS_WARMER_INTERVAL_S = int(os.environ.get("LP_ESPORTS_WARMER_INTERVAL_S", "900"))  # 15 min; 0 disables
_warmer_started = False


def start_esports_warmer():
    """Start the background board warmer once. No-op if disabled (interval<=0) or already running."""
    global _warmer_started
    if _warmer_started or ESPORTS_WARMER_INTERVAL_S <= 0:
        return
    _warmer_started = True

    def _loop():
        while True:
            try:
                esports_upcoming()  # same single-flight path a real visit takes; triggers a bg rebuild
            except Exception:
                pass  # a warmer tick must never kill the loop
            time.sleep(ESPORTS_WARMER_INTERVAL_S)

    threading.Thread(target=_loop, name="esports-warmer", daemon=True).start()


# ---------------------------------------------------------------------------
# rebuild pipeline: gather rows -> cluster -> evidence -> state -> streams
# ---------------------------------------------------------------------------
def _rebuild_upcoming():
    now = time.time()
    now_ms = now * 1000
    stale_cutoff_ms = now_ms - 4 * 3600 * 1000

    # pandascore._ps_indexed memoizes on id() of GC-able cache lists — CPython reuses freed
    # addresses, so a recycled address can serve a STALE match index (statuses frozen from an old
    # fetch) while everything else refreshes: the exact signature of the 'shoke stuck in Scheduled
    # while PS says running' incident (2026-07-03). Until pandascore.py keys that memo on a
    # monotonic generation counter, drop it once per rebuild — within-rebuild reuse (the thing the
    # memo exists for, ~250 _ps_enrich calls) is preserved.
    try:
        from .pandascore import _ps_indexed_cache
        _ps_indexed_cache.clear()
    except Exception:
        pass

    # One-time warm seed: a fresh restart (swap-in) starts with an empty in-process cache, which
    # would cold-start the board down to Bovada's current window — far-future carried matches (e.g.
    # a fixture 5 days out that Bovada only lists intermittently) would vanish until they re-list.
    # If a snapshot was written at swap time, adopt it as prev_matches once, then delete it.
    if _up_cache["data"] is None:
        _warm = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data",
                             "esports_warmcache.json")
        try:
            with open(_warm) as _wf:
                _up_cache["data"] = {"matches": json.load(_wf)}
            os.remove(_warm)
        except Exception:
            pass

    prev_matches = (_up_cache["data"] or {}).get("matches", [])

    bov_rows = _fetch_bovada_rows(stale_cutoff_ms)
    if bov_rows is None:
        return _up_cache["data"] or {"matches": [], "error": "schedule unavailable"}

    rows = list(bov_rows)

    # Carry: identity-only survivors of a Bovada drop (window-gated as before).
    fresh_pairs = [(r["title"], r["teamA"], r["teamB"], r.get("startTime")) for r in rows]
    for old in prev_matches:
        if _is_map_market(old):
            continue
        st = old.get("startTime")
        if not ((st and st > stale_cutoff_ms) or old.get("finishedAt")):
            continue
        dup = any(t == old.get("title") and _same_pair(a, b, old.get("teamA", ""), old.get("teamB", ""))
                  and (not s or not st or abs(s - st) <= 8 * 3600 * 1000)
                  for t, a, b, s in fresh_pairs)
        if not dup:
            rows.append(_carry_row(old))

    # Durable results store.
    raw_store = _load_results_store()
    store = {}
    for stored in raw_store.values():
        if _is_map_market(stored):
            continue  # stale Bovada map markets are not matches and must age out immediately
        stored = _normalize_match_metadata(dict(stored))
        stored = _repair_logos_by_psid(stored)  # fix flipped crests from prior cycles
        key = _key(stored)
        current = store.get(key)
        if current is None or (_has_result(stored) and not _has_result(current)):
            store[key] = stored
    have_keys = {_key(r) for r in rows}
    for k, v in store.items():
        if k not in have_keys:
            rows.append(_carry_row(v))

    # Live window (same definition as before, on raw rows).
    def _in_live_window(r):
        if r.get("finishedAt"):
            return False
        if r.get("_bov_live"):
            return True
        st = r.get("startTime")
        return bool(st and now_ms - _LIVE_TAIL_MS <= st <= now_ms + _LIVE_LEAD_MS)
    live_window = any(_in_live_window(r) for r in rows)

    # Surfaced sources join the SAME row pool and get clustered like everything else — the old
    # code's frozenset-key dedup let a differently-spelled twin through (Heretics/AG.AL).
    gidx = _grid_score_index() if live_window else []
    for entry in gidx:
        if not entry.get("started"):
            continue
        ga, gb = entry["names"][0], entry["names"][1]
        rows.append({"startTime": entry.get("startMs"), "title": entry["title"],
                     "league": entry.get("tournament") or entry["title"],
                     "teamA": ga, "teamB": gb, "favorite": None, "watch": None,
                     "source": "grid", "_origin": "grid"})
    try:
        for pm in _ps_surface_matches(kalshi_pairs=_kalshi_esports_matchups()):
            pm = dict(pm)
            pm["_origin"] = "pandascore"
            pm.pop("live", None)
            pm.pop("finished", None)  # state comes from the evidence pass, not the surfaced row
            pm.pop("score", None)     # PS seeds not_started with 0-0 — never pre-attach
            pm.pop("winner", None)
            rows.append(pm)
    except Exception:
        pass

    # Reconcile unresolved archives BEFORE clustering. Persisted PandaScore ids make this exact on
    # future cycles; the league-scoped fallback bootstraps older rows that predate psId persistence.
    # A postponed fixture must move back to Scheduled at its new time, not become a false Final at
    # the abandoned time (United21 LEO v Prestige Academy, shifted by ~51h on 2026-07-09).
    for row in rows:
        if not (row.get("finishedAt") and row.get("resultUnknown")):
            continue
        old_key = _key(row)
        ps = _ps_enrich(row.get("teamA", ""), row.get("teamB", ""),
                        include_running=live_window, near_ms=row.get("startTime"),
                        league=row.get("league"), ps_id=row.get("psId"),
                        allow_reschedule=True)
        if not ps:
            continue
        row["psId"] = ps.get("_ps_id")
        ps_start = ps.get("startTime")
        if (not ps.get("live") and not ps.get("finished") and ps_start
                and ps_start > now_ms - _START_SLACK_MS):
            row["startTime"] = ps_start
            row["teamA"] = ps.get("canonicalA") or row.get("teamA")
            row["teamB"] = ps.get("canonicalB") or row.get("teamB")
            for field in ("finishedAt", "finished", "resultUnknown", "state", "winner", "score"):
                row.pop(field, None)
            row["_origin"] = "carry"
            store.pop(old_key, None)

    matches = _cluster(rows)

    # ---------------- evidence + state ----------------
    # NOT gated on live_window: a scheduled match's PS stream (sometimes already a YouTube handle,
    # e.g. '@ValorantEsportsKR/live') is known well before the match goes live, and gating this on
    # "something else is live right now" meant scheduled matches never got a real stream at all —
    # the upcoming/past feeds are already cached from _ps_enrich below regardless.
    ps_streams_by_id = {}
    # Stable stream/event identity that SURVIVES a match finishing (a finished match's watch degrades
    # to a bare web link and loses its stream key). streamKey = channel-level (twitch:callofduty), so
    # a broadcast's games group together; eventId = serie.id. Keyed by PS match id, plus a
    # (title, team-pair) fallback for archived finished rows that lost their ps id by output time.
    ps_meta_by_id = {}    # ps match id -> {"streamKey", "eventId"}
    ps_meta_by_pair = {}  # (title, frozenset(canonA, canonB)) -> same meta
    for m in _fetch_ps(include_running=live_window):
        if m.get("id") is None:
            continue
        sl = m.get("streams_list") or []
        ps_streams_by_id[m["id"]] = sl
        eid = (m.get("serie") or {}).get("id")
        meta = {"streamKey": _stable_stream_key(sl), "eventId": eid,
                "endTime": _iso_to_ms(m.get("end_at"))}
        ps_meta_by_id[m["id"]] = meta
        title = (_PS_VG_TITLE.get((m.get("videogame") or {}).get("slug"))
                 or _PS_VG_TITLE.get(((m.get("videogame") or {}).get("name") or "").lower()))
        opps = m.get("opponents") or []
        if title and len(opps) >= 2:
            na = ((opps[0].get("opponent") or {}).get("name")) or ""
            nb = ((opps[1].get("opponent") or {}).get("name")) or ""
            ca, cb = _canon_team(na), _canon_team(nb)
            if ca and cb:
                pk = (title, frozenset((ca, cb)))
                # Prefer an entry that actually resolved a channel key; else keep the first seen.
                if pk not in ps_meta_by_pair or (meta["streamKey"] and not ps_meta_by_pair[pk]["streamKey"]):
                    ps_meta_by_pair[pk] = meta

    for m in matches:
        ev = {"grid": None, "ps": None, "frag": None, "kalshi": None}
        archived = m.get("finishedAt") is not None

        # PandaScore: statuses/score/winner/logos for everything not already settled (an archived
        # entry only gets the narrow Class-F score repair below).
        ps = None
        if (not archived or m.get("resultUnknown") or not _has_result(m)
                or (m.get("winner") and _is_placeholder_score(m.get("score")))):
            ps = _ps_enrich(m.get("teamA", ""), m.get("teamB", ""),
                            include_running=live_window, near_ms=m.get("startTime"),
                            league=m.get("league"), ps_id=m.get("psId"))
        ev["ps"] = ps
        if ps:
            m["_ps_id"] = ps.get("_ps_id")
            m["psId"] = ps.get("_ps_id")
            # Independently aligned per-side logo fill. Re-derive the PS orientation from the matched
            # team names (canonical A/B) rather than coupling logoA/logoB to a single conditional:
            # the old `if ps.logoA and not m.logoA: m.logoA, m.logoB = ps.logoA, ps.logoB` could write
            # the wrong crest to the surviving side when the base row already had one side populated or
            # came from a prior PS match with a different orientation — freezing flipped logos into the
            # results store (e.g. GamerLegion/Xtreme, G2/LYON). Fill each side from its own matched PS
            # opponent, confirmed against canonicalA/canonicalB.
            # Force-correct each side's crest from the matched PS record. We do NOT gate on
            # "already has a logo": a wrong crest baked into the base row (e.g. from a prior PS
            # match with a different orientation) must be overwritten, not frozen. Match the row
            # side to PS canonicalA/canonicalB so the correct logo lands on the correct side even
            # when PS lists the pairing reversed vs the base row.
            psa, psb = ps.get("logoA"), ps.get("logoB")
            ca, cb = ps.get("canonicalA"), ps.get("canonicalB")
            if ca and cb and psa and psb:
                if _same_team(m.get("teamA", ""), ca):
                    m["logoA"] = psa
                elif _same_team(m.get("teamA", ""), cb):
                    m["logoA"] = psb
                if _same_team(m.get("teamB", ""), cb):
                    m["logoB"] = psb
                elif _same_team(m.get("teamB", ""), ca):
                    m["logoB"] = psa
            if ps.get("startTime") and not m.get("startTime"):
                m["startTime"] = ps["startTime"]
            if ps.get("endTime") is not None:
                m["endTime"] = ps["endTime"]

        # GRID (CS2/Dota): realtime score + the honest finished/won flags.
        gentry = gswap = None
        if m.get("title") in ("CS2", "Dota 2") and gidx:
            gentry, ga, gb = _grid_lookup(m.get("teamA", ""), m.get("teamB", ""), gidx)
            if gentry:
                gswap = (ga, gb)
                ev["grid"] = gentry

        # frag: live-evidence + stream pool + canonical names/logos.
        fmatch = fswap = None
        if not archived and live_window and _in_live_window(m):
            fmatch, fswap = _frag_lookup(m.get("teamA", ""), m.get("teamB", ""))
            if fmatch:
                ev["frag"] = fmatch
                opps = fmatch.get("opponents") or []
                if len(opps) >= 2:
                    o0 = opps[0].get("opponent") or {}
                    o1 = opps[1].get("opponent") or {}
                    if fswap:
                        o0, o1 = o1, o0
                    if o0.get("name"):
                        m["teamA"] = o0["name"]
                    if o1.get("name"):
                        m["teamB"] = o1["name"]
                    if o0.get("image_url") and not m.get("logoA"):
                        m["logoA"] = o0["image_url"]
                    if o1.get("image_url") and not m.get("logoB"):
                        m["logoB"] = o1["image_url"]

        # Kalshi settled-winner fallback — only consulted for a past-start match with no finish
        # evidence yet (the minor-league blind spot: GRID window rotation + PS past-feed misses).
        # A resultUnknown archive is retried too — it's "ended, unresolved", not "settled".
        st = m.get("startTime")
        if ((not archived or m.get("resultUnknown") or not _has_result(m)) and st and st < now_ms - _START_SLACK_MS
                and not (gentry and gentry.get("finished")) and not (ps and ps.get("finished"))):
            ev["kalshi"] = _kalshi_winner_fuzzy(m.get("title"), m.get("teamA", ""),
                                                m.get("teamB", ""), near_ms=st)

        # A genuinely-settled archive (a real RESULT — winner or real score — and not resultUnknown)
        # is frozen at S_FINISHED — no need to re-derive it every cycle. Everything else (fresh
        # matches, a resultUnknown archive, and a resultLESS 'finished' archive still being retried)
        # goes through _derive_state, which keeps an unresolved carry honestly labeled S_ENDED_UNKNOWN
        # until a real result actually lands.
        state = (S_FINISHED if (archived and not m.get("resultUnknown") and _has_result(m))
                 else _derive_state(m, ev, now_ms))
        m["state"] = state
        m["_ev"] = ev
        m["_gswap"] = gswap
        m["_fmatch"] = fmatch

        # ---------------- winner + score (source hierarchy, honesty rule) ----------------
        def _grid_ws():
            e, sw = gentry, gswap
            if not e or not sw:
                return None, None
            ga, gb = sw
            w = "a" if e.get("winner") == ga else "b" if e.get("winner") == gb else None
            sc = {"a": e["score"].get(ga), "b": e["score"].get(gb)} if (e.get("started") or e.get("finished")) else None
            return w, sc

        if state == S_FINISHED:
            gw, gsc = _grid_ws()
            if gentry and gentry.get("finished") and gw:
                m["winner"], m["score"] = gw, gsc
            elif ps and ps.get("finished"):
                m["winner"] = ps.get("winner") or m.get("winner")
                if ps.get("score") and (not m.get("score") or
                                        (_is_placeholder_score(m.get("score")) and not _is_placeholder_score(ps["score"]))):
                    m["score"] = ps["score"]
            elif archived and not m.get("resultUnknown"):
                pass  # a genuinely-settled archive stands as-is (score repair below)
            # else: archived-but-resultUnknown, just promoted to S_FINISHED this cycle by a fresh
            # source — fall through to the kalshi branch below so its winner actually gets assigned
            # (a bare `elif archived: pass` here would silently keep the old null winner forever).
            elif ev["kalshi"]:
                m["winner"] = ev["kalshi"]
                m["score"] = None  # Kalshi is winner-only — no fake scoreline
            # Class-F repair: archived winner with placeholder score + a real score now available.
            if m.get("winner") and _is_placeholder_score(m.get("score")):
                if gentry and gentry.get("finished") and not _is_placeholder_score(_grid_ws()[1] or {}):
                    m["score"] = _grid_ws()[1]
                    m["_score_repaired"] = True
                elif ps and ps.get("finished") and ps.get("score") and not _is_placeholder_score(ps["score"]):
                    m["score"] = ps["score"]
                    m["_score_repaired"] = True
            # HONESTY: never display a placeholder 0-0 as a final scoreline.
            if m.get("winner") and _is_placeholder_score(m.get("score")):
                m["score"] = None
        elif state == S_LIVE:
            gw, gsc = _grid_ws()
            if gsc is not None:
                m["score"] = gsc
            elif fmatch is not None:
                fsc = _parse_frag_score(fmatch.get("score"))
                if fsc:
                    m["score"] = {"a": fsc["b"], "b": fsc["a"]} if fswap else fsc
            elif ps and ps.get("live") and ps.get("score"):
                m["score"] = ps["score"]
            m["winner"] = None
        else:  # scheduled / ended_unknown carry NO score and NO winner — nothing is known
            m["score"] = None
            m["winner"] = None

    # ---------------- MSI model edge + logos (unchanged) ----------------
    try:
        msi = msi_predictions()
        msi_map = {}
        for pm in msi.get("matches", []):
            a, b = pm.get("teamA"), pm.get("teamB")
            if not a or not b:
                continue
            na, nb = a.get("name") or "", b.get("name") or ""

            def _edge(t):
                mp, kp = t.get("winPct"), t.get("marketPct")
                return (mp - kp) if (mp is not None and kp is not None) else None
            ea, eb = _edge(a), _edge(b)
            val_team = a if (ea if ea is not None else -999) >= (eb if eb is not None else -999) else b
            ve = _edge(val_team)
            msi_map[(na, nb)] = {
                "favName": val_team.get("code") or val_team.get("name", ""),
                "modelPct": val_team.get("winPct"), "marketPct": val_team.get("marketPct"),
                "edge": round(ve, 1) if ve is not None else None,
                "logoA": a.get("image"), "logoB": b.get("image"),
            }
        for m in matches:
            if m.get("model") or m.get("title") != "LoL":
                continue
            for (pna, pnb), val in msi_map.items():
                if _same_pair(m.get("teamA", ""), m.get("teamB", ""), pna, pnb):
                    m["model"] = {"favName": val["favName"], "modelPct": val["modelPct"],
                                  "marketPct": val["marketPct"], "edge": val["edge"]}
                    m["logoA"], m["logoB"] = val["logoA"], val["logoB"]
                    break
    except Exception:
        pass

    # ---------------- durable results store ----------------
    for m in matches:
        if m["state"] != S_FINISHED or m.get("finishedAt") is not None:
            continue
        k = _key(m)
        if m.get("winner") and _is_placeholder_score(m.get("score")) and m.get("score") is not None:
            seen = _finish_seen.setdefault(k, now_ms)
            if now_ms - seen < _FINISH_GRACE_MS:
                continue  # wait for the real scoreline before freezing
        _finish_seen.pop(k, None)
        if k not in store:
            m2 = {kk: vv for kk, vv in m.items() if not kk.startswith("_")}
            m2["finishedAt"] = now_ms
            m2["finished"] = True
            store[k] = m2
        elif "finishedAt" not in store[k]:
            store[k]["finishedAt"] = now_ms
    for m in matches:
        if m.get("_score_repaired"):
            k = _key(m)
            if k in store and _is_placeholder_score(store[k].get("score")):
                store[k]["score"] = m["score"]
    # ENDED_UNKNOWN persistence (data-must-not-vanish): a match that is genuinely OVER but for which
    # no source (GRID final / PS / Kalshi) has a result must NOT disappear and must NOT be faked. We
    # archive it too — but as an explicit result-UNKNOWN entry (winner/score null, resultUnknown
    # true), so it survives Bovada drops / restarts / the carry window and stays visible in Results
    # as "Ended — result unavailable" instead of vanishing. If a later cycle DOES obtain a result
    # (e.g. Kalshi settles late), the match re-derives to S_FINISHED and archives the real winner
    # first (that branch runs above), so this only ever persists the truly-unresolvable case.
    for m in matches:
        if m["state"] != S_ENDED_UNKNOWN:
            continue
        k = _key(m)
        if k not in store:
            m2 = {kk: vv for kk, vv in m.items() if not kk.startswith("_")}
            m2.update(finishedAt=now_ms, finished=True, resultUnknown=True,
                      winner=None, score=None)
            store[k] = m2

    # Promotion freeze: an archived carry (resultUnknown, or a resultLESS 'finished') that obtained a
    # real result THIS cycle — via the corrected PandaScore past feed, a clustered resolved twin, or
    # a late Kalshi settle — is written back so the store stops re-querying it AND the result survives
    # after the source match leaves the feed. Without this, a resolved carry could silently revert to
    # 'result unavailable' days later when it re-derives with nothing left to match against.
    for m in matches:
        if m["state"] != S_FINISHED or not _has_result(m):
            continue
        ex = store.get(_key(m))
        if ex is not None and (ex.get("resultUnknown") or not _has_result(ex)):
            ex.update(winner=m.get("winner"), score=m.get("score"),
                      resultUnknown=False, finished=True, psId=m.get("psId"))

    cutoff_ms = now_ms - _RESULTS_RETENTION_DAYS * 86400 * 1000
    store = {_key(v): _normalize_match_metadata(v) for v in store.values()
             if not _is_map_market(v) and v.get("finishedAt", 0) > cutoff_ms}
    _save_results_store(store)

    # ---------------- logo backfill (unchanged mechanism) ----------------
    for m in matches:
        if not m.get("logoA"):
            m["logoA"] = _ps_logo_for(m.get("teamA")) or _ps_team_logo_api(m.get("teamA"), m.get("title"))
        if not m.get("logoB"):
            m["logoB"] = _ps_logo_for(m.get("teamB")) or _ps_team_logo_api(m.get("teamB"), m.get("title"))

    # ---------------- streams: candidate pool + platform priority + fallback ----------------
    for m in matches:
        slug = _TITLE_SLUG.get(m.get("title"))
        team_names = (m.get("teamA"), m.get("teamB"))
        if m["state"] == S_LIVE and slug:
            pool = []
            if m.get("_fmatch") is not None:
                pool += _frag_candidates(m["_fmatch"])
            ps = m.get("_ev", {}).get("ps")
            if ps and m.get("_ps_id") is not None:
                pool += _ps_candidates(m["_ps_id"], ps_streams_by_id, ps.get("live"))
            pool += _rule_candidates(slug, m.get("league"))
            pool += _yt_sibling_candidates(pool)
            # Team acronyms (Fnatic -> FNC) disambiguate a channel's video titles that never spell
            # out the full names (VCT EMEA: "FNC vs KC") — see streams.py _pick_stream extra_hints.
            acronym_hints = [h for h in (ps.get("acronymA") if ps else None,
                                          ps.get("acronymB") if ps else None) if h]
            m["watch"] = _pick_stream(pool, match_live=True, team_names=team_names,
                                       game=m.get("title"),
                                       extra_hints=acronym_hints or None) if pool else None
        elif m["state"] == S_SCHEDULED and slug:
            ps_cands = (_ps_candidates(m["_ps_id"], ps_streams_by_id, False)
                        if m.get("_ps_id") is not None else [])
            # network_checks=False by default: a full liveness/YouTube pass on every one of ~500
            # scheduled matches, each a blocking HTTP call, hung the endpoint (2026-07-08). But a
            # match AT/PAST start still sitting in Scheduled (no data feed flipped it live) uses
            # "cache" mode: the liveness read is cache-only and any refresh is handed to a background
            # pool (streams._channel_online_cached), so it stays off the rebuild path. If the official
            # broadcast is confirmed on-air and start has passed, the broadcast itself is the live
            # signal — promote to LIVE so the page actually plays it (the minor-circuit blind spot).
            st = m.get("startTime")
            near = (st is not None
                    and now_ms - _CHANNEL_LIVE_TAIL_MS <= st <= now_ms + _START_SLACK_MS)
            m["watch"] = _resolve_watch(slug, m.get("league"), live=False,
                                         extra_candidates=ps_cands, team_names=team_names,
                                         network_checks=("cache" if near else False))
            if (near and st <= now_ms and m["watch"] and m["watch"].get("online") is True):
                m["state"] = S_LIVE
        elif m["state"] == S_FINISHED and slug:
            m["watch"] = _resolve_watch(slug, m.get("league"), live=False)
        else:
            m["watch"] = None  # ended_unknown: no honest stream to offer

    # ---------------- stable stream identity (survives finishing) ----------------
    # Attach a channel/event-level streamKey + eventId that persists after a match ends, so the board
    # can group a broadcast's games and hold the featured slot through FINAL + gaps. Looked up by PS
    # match id first; a (title, team-pair) fallback recovers archived finished rows that lost their ps
    # id. Falls back to the event id as a grouping anchor when there's no stable channel key (e.g. a
    # YouTube-video-only broadcast) so same-event games still group. Additive: null when unknown.
    for m in matches:
        exact_meta = None
        pid = m.get("_ps_id") or m.get("psId")
        if pid is not None:
            exact_meta = ps_meta_by_id.get(pid)
        meta = exact_meta
        if meta is None:
            ca, cb = _canon_team(m.get("teamA", "")), _canon_team(m.get("teamB", ""))
            if ca and cb:
                meta = ps_meta_by_pair.get((m.get("title"), frozenset((ca, cb))))
        # End time is identity-sensitive: only copy it from an exact PandaScore match id, never the
        # team-pair fallback (the same teams can rematch within one event).
        if exact_meta and exact_meta.get("endTime") is not None:
            m["endTime"] = exact_meta["endTime"]
        if meta:
            eid = meta.get("eventId")
            m["streamKey"] = meta.get("streamKey") or (f"event:{eid}" if eid is not None else None)
            if eid is not None:
                m["eventId"] = eid

    # ---------------- output shaping ----------------
    # Final display-dupe net: drop a same-fixture twin that differs only by team-name casing/spacing
    # (e.g. 'PARIVISION' vs 'Parivision') and slipped past `_cluster`. Runs before `_origin`/`_` fields
    # are stripped below so it can pick the most informative survivor. See slate_state docstring.
    matches = _suppress_display_dupes(matches)

    out_matches = []
    for m in matches:
        state = m["state"]
        st = m.get("startTime")
        m["endTime"] = m.get("endTime")
        # Data must not vanish: an ENDED_UNKNOWN match is KEPT (shown in Results as "result
        # unavailable"), NOT dropped and NOT faked. It only leaves the board when it ages out of the
        # 3-day store retention like any other result.
        m["live"] = state == S_LIVE
        m["finished"] = state in (S_FINISHED, S_ENDED_UNKNOWN)
        if state == S_ENDED_UNKNOWN:
            m["resultUnknown"] = True  # legacy bucket: Results (it IS over); no winner, no score
            m["score"] = None
            m["winner"] = None
        elif m.get("resultUnknown"):
            # Was carried in as resultUnknown but just resolved to a real state this cycle (S_FINISHED
            # via a fresh grid/ps/kalshi result, or even back to S_LIVE on a genuine rematch) — clear
            # the stale flag so the output isn't self-contradictory (finished+resultUnknown+a winner).
            m["resultUnknown"] = False
        _normalize_match_metadata(m)
        # Stable identity for the client (picks + crowd + settlement all key on this exact string).
        m["matchKey"] = _key(m)
        for k in [kk for kk in m if kk.startswith("_")]:
            m.pop(k, None)
        out_matches.append(m)

    # League-tier sort (marquee int'l > regional pro > challengers/dev > minor/novelty) + the
    # odds-or-stream visibility filter: this board's purpose is matches you can watch or bet on,
    # so a live/finished/ended_unknown match with neither has no reason to be shown (never applied
    # to SCHEDULED — a market/stream often just hasn't posted yet). See league_tier.py.
    out_matches, _dropped = apply_tier_and_filter(out_matches)

    any_live = any(m.get("live") for m in out_matches)
    # A scheduled match at/just-past start is a broadcast-liveness promotion candidate: its first
    # rebuild only SCHEDULES the background decapi probe, so hold the fast (60s) cadence until it
    # resolves — otherwise the 300s idle TTL outlives the 90s liveness cache and the promotion never
    # lands (the confirmed-on-air minor-circuit match would stay stuck in Scheduled).
    any_promote_pending = any(
        m.get("state") == S_SCHEDULED and m.get("startTime") is not None
        and now_ms - _CHANNEL_LIVE_TAIL_MS <= m["startTime"] <= now_ms
        for m in out_matches)
    out = {"matches": out_matches, "source": "bovada"}
    _up_cache.update(t=now, data=out, ttl=(60 if (any_live or any_promote_pending) else 300))
    return out
