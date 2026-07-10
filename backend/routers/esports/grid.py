"""grid.py — GRID Open Access client for CS2/Dota live data + score enrichment."""

import json
import os
import time
import datetime
import calendar
import urllib.request as _u

_GRID_KEY = os.environ.get("GRID_API_KEY")
_GRID_CD = "https://api-op.grid.gg/central-data/graphql"
_GRID_SS = "https://api-op.grid.gg/live-data-feed/series-state/graphql"


def _grid(url, query):
    if not _GRID_KEY:
        return None
    try:
        body = json.dumps({"query": query}).encode()
        req = _u.Request(url, data=body, headers={"x-api-key": _GRID_KEY, "Content-Type": "application/json"})
        with _u.urlopen(req, timeout=10) as r:
            return (json.loads(r.read().decode()) or {}).get("data")
    except Exception:
        return None


def _grid_state(sid):
    q = ('{ seriesState(id:"%s") { started finished valid updatedAt '
         'teams { name score won players { name kills deaths } } } }' % sid)
    d = _grid(_GRID_SS, q)
    return (d or {}).get("seriesState") if d else None


_GRID_TITLE_LABELS = [("counter", "CS2"), ("ancient", "Dota 2"), ("dota", "Dota 2")]


def _grid_title_label(name):
    n = (name or "").lower()
    for kw, label in _GRID_TITLE_LABELS:
        if kw in n:
            return label
    return None


# Cache for _grid_score_index: ~60s TTL.
_grid_idx_cache = {"t": 0.0, "data": None}


def _grid_score_index():
    """Recent CS2/Dota series with full state — used both to enrich Bovada matches AND to surface
    finished results that Bovada has already dropped (GRID's 8h window IS the persistent results
    store, so a final match doesn't vanish on a Bovada drop / backend restart). Cached ~60s."""
    if _grid_idx_cache["data"] is not None and time.time() - _grid_idx_cache["t"] < 60:
        return _grid_idx_cache["data"]

    def _ms(ts):  # GRID ISO8601 -> epoch ms
        if not ts:
            return None
        try:
            dt = datetime.datetime.strptime(ts.replace("Z", "").split(".")[0], "%Y-%m-%dT%H:%M:%S")
            return int(calendar.timegm(dt.timetuple()) * 1000)
        except Exception:
            return None

    def _is_test(names):
        return any(x in ("CS2-1", "CS2-2", "DOTA-1", "DOTA-2", "TBD-1", "TBD-2") for x in names)

    idx = []
    if _GRID_KEY:
        now = datetime.datetime.utcnow()
        lo = (now - datetime.timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
        hi = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        q = ('{ allSeries(first:50, orderBy: StartTimeScheduled, orderDirection: DESC, '
             'filter:{ startTimeScheduled:{ gte:"%s", lte:"%s" } }) '
             '{ edges { node { id startTimeScheduled title { name } tournament { name } '
             'teams { baseInfo { name } } } } } }' % (lo, hi))
        d = _grid(_GRID_CD, q)
        cands = [e.get("node") or {} for e in (((d or {}).get("allSeries") or {}).get("edges") or [])
                 if _grid_title_label(((e.get("node") or {}).get("title") or {}).get("name"))][:16]
        # One _grid_state call per candidate series, run CONCURRENTLY — sequential calls here
        # added ~4.8s to a cold /api/esports/upcoming response (up to 16 series x ~0.3s each),
        # the other half of the ~10s page-load bottleneck (the other half was PandaScore's
        # per-title fetch, fixed the same way in pandascore.py:_per_title).
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=len(cands) or 1) as ex:
            states = list(ex.map(lambda n: _grid_state(n["id"]), cands)) if cands else []
        for node, st in zip(cands, states):
            teams = (st or {}).get("teams") or []
            if not st or len(teams) != 2:
                continue
            names = [t.get("name") for t in teams]
            base_teams = node.get("teams") or []
            full_names = [(t.get("baseInfo") or {}).get("name") for t in base_teams]
            if len(full_names) != 2:
                full_names = [None, None]
            if _is_test(names):
                continue
            idx.append({
                "names": names,
                "fullNames": full_names,
                "score": {t.get("name"): t.get("score") for t in teams},
                "winner": next((t.get("name") for t in teams if t.get("won")), None),
                "finished": bool(st.get("finished")), "started": bool(st.get("started")),
                "title": _grid_title_label((node.get("title") or {}).get("name")),
                "tournament": (node.get("tournament") or {}).get("name"),
                "startMs": _ms(node.get("startTimeScheduled")),
                # updatedAt = when GRID last mutated this series-state. Live CS2/Dota series tick
                # every ~2-5min (per round); a series whose updatedAt is >30min stale has stopped
                # updating = the match is OVER even though `finished` never flipped (GRID's finished
                # flag lags/never fires on minor events). slate_state._derive_state uses this to refuse to
                # count a STALE started&&!finished series as live evidence (the Prestige v Vasteras
                # zombie: started=True finished=False, updatedAt 224min stale, frozen LIVE for 4.4h).
                "updatedAtMs": _ms(st.get("updatedAt")),
            })
    _grid_idx_cache.update(t=time.time(), data=idx)
    return idx



# GRID short codes with NO full name anywhere in its API (both allSeries.baseInfo.name and
# seriesState.teams.name return the code itself) — confirmed via _grid_score_index() for "WBT",
# whose Bovada-visible name is "Wrotberry". A generic name-matching relaxation can't bridge this
# (there's no shared substring/word overlap at all), so it needs an explicit, scoped alias instead
# of loosening `_team_match` for every caller. Add entries here only after confirming via
# _grid_score_index() that GRID truly has no full name for the team — don't guess.
_GRID_CODE_ALIASES = {
    "wbt": "wrotberry",
}


def _grid_match(team_a, team_b, idx):
    """Find the GRID series for this pairing by normalized team-name match -> (entry, gridA, gridB)."""
    from .common import _norm_team

    na, nb = _norm_team(team_a), _norm_team(team_b)

    def name_for(nx, entry):
        names = entry.get("names") or []
        full_names = entry.get("fullNames") or []
        for i, gn in enumerate(names):
            full = full_names[i] if i < len(full_names) else None
            candidates = [gn, full]
            alias = _GRID_CODE_ALIASES.get(_norm_team(gn))
            if alias:
                candidates.append(alias)
            for candidate in candidates:
                if not candidate:
                    continue
                g = _norm_team(candidate)
                # exact or substring match
                if nx == g or (nx and (nx in g or g in nx)):
                    return gn
        return None

    for entry in idx:
        ga, gb = name_for(na, entry), name_for(nb, entry)
        if ga and gb and ga != gb:
            return entry, ga, gb
    return None, None, None
