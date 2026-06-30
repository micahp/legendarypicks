"""slate.py — the full off-board esports schedule: Bovada -> GRID enrich -> MSI edge -> results store."""

import json
import time
import urllib.request as _u

from fastapi import APIRouter

from .common import _amer_to_p, _ESPORTS_TITLES, _slug_to_name, _TITLE_SLUG, _team_match, _norm_team, _GRID_LABEL_SLUG, _strip_name
from .grid import _grid_score_index, _grid_match
from .lol import msi_predictions
from .results_store import _load_results_store, _save_results_store
from .frag import _frag_enrich
from .streams import _resolve_watch

router = APIRouter()

_BOV_ESPORTS = ("https://www.bovada.lv/services/sports/event/coupon/events/A/description/"
                "esports?marketFilterId=def&liveOnly=false&lang=en")
_up_cache = {"t": 0.0, "data": None}
_pinned_live = {"match": None, "t": 0.0}  # last real live match + when we last saw it (no hardcoded seed)


@router.get("/api/esports/upcoming")
def esports_upcoming():
    """The full off-board esports slate (next ~2 weeks) as a single **chronological** list —
    what's coming next first (live matches lead). Each match is tagged with its title + league
    and priced by the Bovada moneyline favorite. Covers LoL/Valorant/CS2/Dota/R6/KoG (CoD is on
    the scoreboard, so it's excluded). Cache: 4h merge — old matches survive Bovada drops."""
    now = time.time()
    CACHE_TTL = 4 * 3600
    STALE_CUTOFF_MS = (now - 4 * 3600) * 1000

    if _up_cache["data"] is not None and now - _up_cache["t"] < 60:
        return _up_cache["data"]

    prev_matches = (_up_cache["data"] or {}).get("matches", [])

    try:
        req = _u.Request(_BOV_ESPORTS, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        with _u.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
    except Exception:
        return _up_cache["data"] or {"matches": [], "error": "schedule unavailable"}

    def _key(m):
        return f"{m.get('teamA','')}||{m.get('teamB','')}||{m.get('title','')}||{m.get('league','')}"

    matches = []
    for grp in data:
        for e in grp.get("events", []):
            parts = [p for p in (e.get("link") or "").split("/") if p]
            if len(parts) < 3:
                continue
            title_slug, league_slug = parts[1], parts[2]
            if title_slug not in _ESPORTS_TITLES:
                continue
            st = e.get("startTime")
            if not e.get("live") and st and st < STALE_CUTOFF_MS:
                continue

            ml = None
            for dg in e.get("displayGroups", []):
                for mk in dg.get("markets", []):
                    if (mk.get("description") or "").lower() == "moneyline":
                        ml = mk
                        break
                if ml:
                    break
            pairs = []
            if ml:
                for o in ml.get("outcomes", []):
                    am = (o.get("price") or {}).get("american")
                    if am not in (None, "EVEN", "", "-"):
                        try:
                            pairs.append((o.get("description"), _amer_to_p(am)))
                        except Exception:
                            pairs.append((o.get("description"), None))
                    else:
                        pairs.append((o.get("description"), None))
            if len(pairs) != 2:
                desc = e.get("description") or ""
                names = [s.strip() for s in desc.split(" vs ")] if " vs " in desc else []
                if len(names) != 2:
                    continue
                pairs = [(names[0], None), (names[1], None)]

            fav = None
            if pairs[0][1] is not None and pairs[1][1] is not None:
                s = pairs[0][1] + pairs[1][1]
                if s > 0:
                    p0 = round(pairs[0][1] / s * 100)
                    fav = {"name": pairs[0][0] if p0 >= 50 else pairs[1][0],
                           "pct": max(p0, 100 - p0)}

            matches.append({
                "startTime": e.get("startTime"),
                "live": bool(e.get("live")),
                "title": _ESPORTS_TITLES[title_slug],
                "league": _slug_to_name(league_slug),
                "teamA": pairs[0][0], "teamB": pairs[1][0],
                "favorite": fav,
                "watch": None,  # resolved in the final on-air pass below
            })

    # Merge: keep old matches that Bovada dropped, for up to CACHE_TTL (4h).
    fresh_keys = {_key(m) for m in matches}
    for old in prev_matches:
        if _key(old) not in fresh_keys:
            st = old.get("startTime")
            if (st and st > STALE_CUTOFF_MS) or old.get("live"):
                old = dict(old)
                old["pinned"] = True
                matches.append(old)

    # Attach GRID state to CS2/Dota matches — the honest "score + is it over" signal.
    gidx = _grid_score_index()
    used_grid = set()
    for m in matches:
        if m["title"] not in ("CS2", "Dota 2"):
            continue
        entry, ga, gb = _grid_match(m["teamA"], m["teamB"], gidx)
        if not entry:
            continue
        used_grid.add(id(entry))
        m["score"] = {"a": entry["score"].get(ga), "b": entry["score"].get(gb)}
        m["finished"] = entry["finished"]
        m["winner"] = "a" if entry["winner"] == ga else "b" if entry["winner"] == gb else None
        m["live"] = entry["started"] and not entry["finished"]  # GRID is authoritative on live-ness

    # Surface live/finished GRID series that Bovada no longer lists.
    for entry in gidx:
        if id(entry) in used_grid:
            continue
        if not (entry["started"]):  # not yet started — Bovada already covers the schedule
            continue
        ga, gb = entry["names"][0], entry["names"][1]
        slug = _GRID_LABEL_SLUG.get(entry["title"])
        matches.append({
            "startTime": entry["startMs"],
            "live": entry["started"] and not entry["finished"],
            "finished": entry["finished"],
            "title": entry["title"],
            "league": entry["tournament"] or entry["title"],
            "teamA": ga, "teamB": gb,
            "favorite": None,
            "score": {"a": entry["score"].get(ga), "b": entry["score"].get(gb)},
            "winner": "a" if entry["winner"] == ga else "b" if entry["winner"] == gb else None,
            "watch": None,  # resolved in the final on-air pass below
            "source": "grid",
        })

    # Attach MSI model edge + logos to LoL slate matches.
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
                "modelPct": val_team.get("winPct"),
                "marketPct": val_team.get("marketPct"),
                "edge": round(ve, 1) if ve is not None else None,
                "logoA": a.get("image"),
                "logoB": b.get("image"),
            }
        for m in matches:
            if m.get("model") or m.get("title") != "LoL":
                continue
            md = None
            for (pna, pnb), val in msi_map.items():
                if (_team_match(m["teamA"], pna) and _team_match(m["teamB"], pnb)) or \
                   (_team_match(m["teamA"], pnb) and _team_match(m["teamB"], pna)):
                    md = val
                    break
            if md:
                m["model"] = {"favName": md["favName"], "modelPct": md["modelPct"],
                              "marketPct": md["marketPct"], "edge": md["edge"]}
                m["logoA"] = md["logoA"]
                m["logoB"] = md["logoB"]
    except Exception:
        pass  # MSI model unavailable — slate still works without it

    # --- durable results store ---
    store = _load_results_store()
    for m in matches:
        if m.get("finished") and not m.get("pinned"):
            k = _key(m)
            if k not in store:
                m2 = dict(m)
                m2["finishedAt"] = now * 1000
                store[k] = m2
            elif "finishedAt" not in store[k]:
                store[k]["finishedAt"] = now * 1000

    cutoff_ms = (now - 3 * 86400) * 1000
    store = {k: v for k, v in store.items() if v.get("finishedAt", 0) > cutoff_ms}
    _save_results_store(store)

    existing = {_key(m) for m in matches}
    for k, v in store.items():
        if k not in existing:
            v = dict(v)
            v["pinned"] = True
            matches.append(v)

    # --- dedup: collapse Bovada duplicates (spacing/acronym diffs) + frag/Bovada overlap ---
    def _dk(m):
        return (m.get("title"), frozenset({_strip_name(m.get("teamA", "")), _strip_name(m.get("teamB", ""))}))

    deduped = {}
    for m in matches:
        k = _dk(m)
        if k not in deduped:
            deduped[k] = m
        else:
            base = deduped[k]
            # Merge missing fields from the incoming copy.
            for f in ("favorite", "score", "winner", "model", "logoA", "logoB", "startTime", "league"):
                if not base.get(f) and m.get(f):
                    base[f] = m[f]
            # Prefer the copy that has a stream.
            if not base.get("watch") and m.get("watch"):
                base["watch"] = m["watch"]
            # Prefer the copy with logos.
            if not base.get("logoA") and m.get("logoA"):
                base["logoA"] = m["logoA"]
                base["logoB"] = m.get("logoB")
            # Prefer the canonical (frag) team names over Bovada raw names.
            if m.get("logoA") and not base.get("logoA"):
                base["teamA"] = m.get("teamA", base["teamA"])
                base["teamB"] = m.get("teamB", base["teamB"])
            base["live"] = bool(base.get("live") or m.get("live"))
            base["finished"] = bool(base.get("finished") or m.get("finished"))
    matches = list(deduped.values())
    for m in matches:
        if m.get("finished"):
            m["live"] = False

    # --- resolve the watch channel: frag.se first (per-match, live), fall back to hardcoded maps ---
    for m in matches:
        slug = _TITLE_SLUG.get(m.get("title"))
        if m.get("live") and slug:
            # Try frag.se for the canonical per-match stream + logos + score + clean names.
            enrich = _frag_enrich(m["teamA"], m["teamB"])
            if enrich:
                if enrich.get("watch"):
                    m["watch"] = enrich["watch"]
                if enrich.get("logoA"):
                    m["logoA"] = enrich["logoA"]
                if enrich.get("logoB"):
                    m["logoB"] = enrich["logoB"]
                if enrich.get("canonicalA"):
                    m["teamA"] = enrich["canonicalA"]
                if enrich.get("canonicalB"):
                    m["teamB"] = enrich["canonicalB"]
                # Apply frag score when GRID hasn't already set one (GRID stays authoritative for CS2/Dota).
                if enrich.get("score") and not m.get("score"):
                    m["score"] = enrich["score"]
                if enrich.get("finished") and not m.get("finished"):
                    m["finished"] = enrich["finished"]
                if enrich.get("winner") and not m.get("winner"):
                    m["winner"] = enrich["winner"]
                # If frag gave us a stream, we're done; otherwise fall through to hardcoded.
                if enrich.get("watch"):
                    continue
            # Fall back to hardcoded map with on-air verification.
            m["watch"] = _resolve_watch(slug, m.get("league"), live=True)
        else:
            m["watch"] = _resolve_watch(slug, m.get("league"), live=False) if slug else None

    # Pin live match for hero.
    live_now = [m for m in matches if m["live"]]
    if live_now:
        _pinned_live["match"] = live_now[0]
        _pinned_live["t"] = now
    elif _pinned_live["match"] and now - _pinned_live["t"] < CACHE_TTL:
        pinned = dict(_pinned_live["match"])
        pinned["pinned"] = True
        if not any(_key(m) == _key(pinned) for m in matches):
            matches.insert(0, pinned)

    matches.sort(key=lambda m: (not m["live"], m["startTime"] or 0))

    out = {"matches": matches, "source": "bovada"}
    _up_cache.update(t=now, data=out)
    return out
