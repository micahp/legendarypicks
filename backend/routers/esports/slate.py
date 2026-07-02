"""slate.py — the full off-board esports schedule: Bovada -> GRID enrich -> MSI edge -> results store."""

import json
import threading
import time
import urllib.request as _u

from fastapi import APIRouter

from .common import _amer_to_p, _ESPORTS_TITLES, _slug_to_name, _TITLE_SLUG, _team_match, _norm_team, _GRID_LABEL_SLUG, _strip_name, _canon_team
from .grid import _grid_score_index, _grid_match
from .lol import msi_predictions
from .results_store import _load_results_store, _save_results_store
from .frag import _frag_enrich
from .pandascore import _ps_enrich, _ps_logo_for, _ps_surface_matches
from .streams import _resolve_watch

router = APIRouter()

_BOV_ESPORTS = ("https://www.bovada.lv/services/sports/event/coupon/events/A/description/"
                "esports?marketFilterId=def&liveOnly=false&lang=en")
_up_cache = {"t": 0.0, "data": None}
_up_rebuild_lock = threading.Lock()
_up_rebuilding = False

# A finished match with a winner but only a placeholder 0-0 score usually gets its real scoreline a
# PandaScore refresh or two later; hold off archiving it into the durable store for this long so the
# real score can land first (once archived+finishedAt, the pinned guard freezes the score forever —
# logs/ESPORTS-BUG-TRACKER.md Class F). Keyed by match key -> first time seen finished-but-scoreless.
_FINISH_GRACE_MS = 45 * 60 * 1000
_finish_seen = {}


def _is_placeholder_score(sc):
    """A score carrying no real result yet: absent, or 0-0 — which is exactly what a Bo1 shows all
    through live play, and what PandaScore seeds a not_started match with. A *finished* match still
    showing this means the real scoreline was never captured (ESPORTS-BUG-TRACKER Class F)."""
    if not sc:
        return True
    return not (sc.get("a") or 0) and not (sc.get("b") or 0)


@router.get("/api/esports/upcoming")
def esports_upcoming():
    """The full off-board esports slate (next ~2 weeks) as a single **chronological** list —
    what's coming next first (live matches lead). Each match is tagged with its title + league
    and priced by the Bovada moneyline favorite. Covers LoL/Valorant/CS2/Dota/R6/KoG (CoD is on
    the scoreboard, so it's excluded). Cache: 4h merge — old matches survive Bovada drops.

    Stale-while-revalidate: a rebuild (Bovada + PandaScore + GRID + frag) costs several seconds
    even after parallelizing the upstream fetches — that's real external API latency, not
    something further code changes can remove. So once ANY cached response exists, a request
    NEVER blocks on it: an expired cache is served as-is while a background thread refreshes it
    for the next request. Only a true cold start (process just restarted, no cache at all) blocks
    synchronously, since there's nothing else to serve."""
    now = time.time()

    if _up_cache["data"] is not None:
        if now - _up_cache["t"] < _up_cache.get("ttl", 60):
            return _up_cache["data"]
        # Stale but present: serve immediately, refresh in the background (single-flight — don't
        # stack up N concurrent rebuilds if several requests land while one is already running).
        global _up_rebuilding
        with _up_rebuild_lock:
            already = _up_rebuilding
            _up_rebuilding = True
        if not already:
            def _bg():
                global _up_rebuilding
                try:
                    _rebuild_upcoming()
                finally:
                    with _up_rebuild_lock:
                        _up_rebuilding = False
            threading.Thread(target=_bg, daemon=True).start()
        return _up_cache["data"]

    # True cold start — nothing cached yet, must build synchronously this one time.
    return _rebuild_upcoming()


def _rebuild_upcoming():
    now = time.time()
    CACHE_TTL = 4 * 3600
    STALE_CUTOFF_MS = (now - 4 * 3600) * 1000

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
    # A match Bovada dropped is NOT live anymore — never carry `live` forward (that
    # resurrected phantom "live" games with no stream/hero). Keep it only if it's still
    # within the schedule window or a finished result; a genuinely-live match that Bovada
    # keeps listing stays fresh above, and real live CS2/Dota re-enters via the GRID loop.
    fresh_keys = {_key(m) for m in matches}
    for old in prev_matches:
        if _key(old) not in fresh_keys:
            st = old.get("startTime")
            if (st and st > STALE_CUTOFF_MS) or old.get("finished"):
                old = dict(old)
                old["pinned"] = True
                old["live"] = False
                matches.append(old)

    # Live-window gate: do we need the LIVE feeds this cycle? Only if a match is plausibly on-air
    # (Bovada flags it live, or its start time is within the window). When nothing's live we skip
    # frag / PandaScore-running / GRID series-state entirely — idle esports shouldn't ping upstreams.
    now_ms = now * 1000
    LIVE_LEAD_MS = 20 * 60 * 1000    # a match ~20min pre-start may already have a stream up
    LIVE_TAIL_MS = 6 * 3600 * 1000   # ...and a Bo5 can still be running ~6h after start
    def _in_live_window(m):
        if m.get("finished"):
            return False
        if m.get("live"):
            return True
        st = m.get("startTime")
        return bool(st and now_ms - LIVE_TAIL_MS <= st <= now_ms + LIVE_LEAD_MS)
    live_window = any(_in_live_window(m) for m in matches)

    # PandaScore: authoritative status / score / winner / logos across ALL titles (Valorant, R6,
    # LoL, ...). Its explicit `finished` status is what finally tells us a Bovada match ENDED —
    # Bovada silently drops finished games, which is what stuck them as zombie-live. GRID (below)
    # still overrides for CS2/Dota. The live `running` feed is only fetched inside the live window.
    used_ps_ids = set()  # PandaScore match ids already attached to a slate match — the surface block
                         # below skips these so a Bovada match and its PandaScore twin (different team
                         # spelling) can't both show as two rows.
    for m in matches:
        ps = _ps_enrich(m["teamA"], m["teamB"], include_running=live_window, near_ms=m.get("startTime"))
        if not ps:
            continue
        if ps.get("_ps_id") is not None:
            used_ps_ids.add(ps["_ps_id"])
        # Logos + winner backfill for EVERY match, including pinned results-store entries — those
        # were saved logo-less (GRID gives no crests) but PandaScore has them. This must NOT touch a
        # stored result's finished/score state, so it runs before the pinned guard below.
        if ps.get("logoA") and not m.get("logoA"):
            m["logoA"], m["logoB"] = ps["logoA"], ps.get("logoB")
        if ps.get("winner") and not m.get("winner"):
            m["winner"] = ps["winner"]
        # Only a CONFIRMED-finished results-store entry (has `finishedAt`, set once below when it's
        # first archived) should freeze here — its finished/score state is settled and must not be
        # second-guessed. A match that's merely `pinned` because Bovada dropped it mid-cycle (line
        # ~151) is NOT yet known to be finished — skipping it here was the bug: it never got
        # rechecked again, so it sat showing finished=false (-> Scheduled tab) forever instead of
        # resolving to finished=true (-> Results) once PandaScore/GRID actually confirmed the
        # result. See logs/ESPORTS-BUG-TRACKER.md Class C.
        if m.get("pinned") and "finishedAt" in m:
            # Narrow score-only self-heal (Class F): an already-archived entry that has a winner but
            # a placeholder 0-0 score can have JUST its score repaired from a finished PandaScore
            # record — never its settled finished/winner/finishedAt state. _ps_enrich's near_ms
            # disambiguation guards against attaching a same-team match's score.
            if (m.get("winner") and _is_placeholder_score(m.get("score"))
                    and ps.get("finished") and not _is_placeholder_score(ps.get("score") or {})):
                m["score"] = ps["score"]
                m["_score_repaired"] = True
            continue
        # Full status/score enrichment for fresh matches AND unresolved pinned carry-forwards.
        if ps.get("finished"):
            m["finished"], m["live"] = True, False
        elif ps.get("live"):
            m["live"], m["finished"] = True, False
        else:
            m["live"] = False  # PandaScore says not_started — authoritative that it's NOT live
        # A finished PandaScore record's real score supersedes a placeholder 0-0 captured during
        # live play — without this, a Bo1's all-match 0-0 sticks and the game archives as "winner
        # but 0-0" (Class F, slate.py truthy-{0,0} guard). Otherwise only fill when we have nothing.
        if ps.get("score"):
            if not m.get("score") or (ps.get("finished") and _is_placeholder_score(m.get("score"))
                                      and not _is_placeholder_score(ps["score"])):
                m["score"] = ps["score"]
        if ps.get("startTime") and not m.get("startTime"):
            m["startTime"] = ps["startTime"]
        if ps.get("watch"):
            m["_ps_watch"] = ps["watch"]  # link fallback, used if frag has no embed

    # Attach GRID state to CS2/Dota matches — the honest "score + is it over" signal.
    gidx = _grid_score_index() if live_window else []
    used_grid = set()
    for m in matches:
        if m["title"] not in ("CS2", "Dota 2"):
            continue
        entry, ga, gb = _grid_match(m["teamA"], m["teamB"], gidx)
        if not entry:
            continue
        used_grid.add(id(entry))
        # Only attach a score once the series is under way — a not-yet-started series is 0-0,
        # which must not surface as a live scoreline on an upcoming match.
        if entry["started"] or entry["finished"]:
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

    # Surface live (and just-finished) PandaScore matches that neither Bovada nor GRID lists — a
    # minor Dota/Valorant/R6 qualifier can be genuinely live with a real stream yet invisible here,
    # because PandaScore is otherwise enrich-only and never ADDS a match (it drops off the slate the
    # moment Bovada stops listing it — see the Bolivia v Ecuador SA-qualifier drop, ESPORTS-BUG-
    # TRACKER Class G). PandaScore analogue of the GRID-surface block above; the dedup guard keeps a
    # match we already have (Bovada/GRID) from being double-added, and _collapse() is the safety net.
    existing_dk = {(m.get("title"), frozenset({_canon_team(m.get("teamA", "")), _canon_team(m.get("teamB", ""))}))
                   for m in matches}
    for pm in _ps_surface_matches():
        if pm.get("_ps_id") in used_ps_ids:
            continue  # already on the slate via a Bovada match (id-matched by _ps_enrich) — skip the twin
        dk = (pm["title"], frozenset({_canon_team(pm["teamA"]), _canon_team(pm["teamB"])}))
        if dk in existing_dk:
            continue
        existing_dk.add(dk)
        matches.append(pm)

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
    # `"finishedAt" not in m`, not `not m.get("pinned")`: a carry-forward match (line ~151) that
    # JUST resolved to finished=true this cycle (via the PandaScore/GRID recheck above) is still
    # tagged pinned=True, but it's a newly-confirmed result that needs archiving like any other —
    # excluding it here was the other half of the Class C bug (it would resolve correctly for one
    # cycle, then get re-pinned as an unarchived, still-technically-"pinned" entry with no
    # `finishedAt` and never permanently settle into Results).
    store = _load_results_store()
    for m in matches:
        if m.get("finished") and "finishedAt" not in m:
            k = _key(m)
            # Grace window (Class F): a finished match with a winner but only a placeholder 0-0 score
            # usually gets its real score a PandaScore refresh or two later. Don't freeze it into the
            # store yet — once archived+finishedAt, the pinned guard blocks the score forever. Archive
            # anyway past the window so a genuine 0-0 (e.g. a GRID forfeit) still lands in Results
            # instead of sticking in Scheduled (Class C).
            if m.get("winner") and _is_placeholder_score(m.get("score")):
                seen = _finish_seen.setdefault(k, now * 1000)
                if now * 1000 - seen < _FINISH_GRACE_MS:
                    continue
            _finish_seen.pop(k, None)
            if k not in store:
                m2 = dict(m)
                m2["finishedAt"] = now * 1000
                store[k] = m2
            elif "finishedAt" not in store[k]:
                store[k]["finishedAt"] = now * 1000

    # Class F self-heal persist: write a repaired placeholder score (set at the pinned guard above)
    # back onto its already-archived store entry. Score only — finished/winner/finishedAt stay settled.
    for m in matches:
        if m.get("_score_repaired"):
            k = _key(m)
            if k in store and _is_placeholder_score(store[k].get("score")):
                store[k]["score"] = m["score"]

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
        return (m.get("title"), frozenset({_canon_team(m.get("teamA", "")), _canon_team(m.get("teamB", ""))}))

    def _anagram_dk(m):
        # Letter-transposition typos across sources ('AION'/'Aoin', 'Dontsu'/'Donstu') are exact
        # anagrams — same letters, reordered. Fold each team to its sorted letters so they collapse.
        # Guarded to names >=4 chars (short codes like 'og'/'wbt' are excluded — too easy to be
        # coincidental anagrams) and, being a frozenset of BOTH teams, only merges when BOTH sides
        # anagram-match under the same title, which two genuinely different fixtures never do.
        def _ana(n):
            c = _canon_team(n)
            return "".join(sorted(c)) if len(c) >= 4 else c
        return (m.get("title"), frozenset({_ana(m.get("teamA", "")), _ana(m.get("teamB", ""))}))

    def _collapse(ms, keyfn=_dk):
        deduped = {}
        for m in ms:
            k = keyfn(m)
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
        out = list(deduped.values())
        for m in out:
            if m.get("finished"):
                m["live"] = False
        return out

    matches = _collapse(matches)

    # Backfill any still-missing team crest by NAME from PandaScore's cached team-logo index. Runs
    # AFTER the results-store merge so it also lights up GRID-sourced / pinned finished results whose
    # exact fixture PandaScore doesn't carry. Reads the already-cached feeds — no extra API calls.
    for m in matches:
        if not m.get("logoA"):
            lg = _ps_logo_for(m.get("teamA"))
            if lg:
                m["logoA"] = lg
        if not m.get("logoB"):
            lg = _ps_logo_for(m.get("teamB"))
            if lg:
                m["logoB"] = lg

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
                # If frag gave us a stream, we're done; otherwise fall through.
                if enrich.get("watch"):
                    continue
            # Next: PandaScore's stream link (official broadcast, may be a clickable ↗ not an embed).
            if m.get("_ps_watch"):
                m["watch"] = m["_ps_watch"]
                continue
            # Last: hardcoded map with on-air verification.
            m["watch"] = _resolve_watch(slug, m.get("league"), live=True)
        else:
            m["watch"] = _resolve_watch(slug, m.get("league"), live=False) if slug else None

    # NOTE: no live-hero fabrication. If nothing is live, the page honestly shows
    # "what's next" — we do NOT re-insert the last-seen live match (that kept a dead
    # game pinned as "live" for hours with no stream to play).

    # Re-collapse after frag's canonical-name rewrite above. frag matches by name/acronym/slug,
    # which is more lenient than _dk's fuzzy match — two entries that looked like different
    # matches going into the first _collapse() (e.g. Bovada's "Inner Circle Academy" vs a
    # GRID-surfaced entry using GRID's short name "IC Academy") can both get renamed to the same
    # frag canonical name here, and would otherwise survive as a cosmetic duplicate: same display
    # names, never merged, because dedup only ran once, before the rename. See
    # logs/ESPORTS-BUG-TRACKER.md Class A #5.
    matches = _collapse(matches)

    # Final pass: collapse cross-source letter-transposition typos the canonical key can't bridge
    # ('AION Esports'/'Team Aoin', 'Dontsu'/'Donstu') — same team, same match, one logo-bearing copy
    # from frag and one without, which is why the merge also fixes the missing-logo cases.
    matches = _collapse(matches, _anagram_dk)

    # Qualifier/nation-team brackets are real matches (can be genuinely live with a real stream —
    # confirmed for "Esports Nation Cup Qualifiers" Bolivia v Ecuador on 2026-07-01, PandaScore
    # showed a progressing score, not a stale zombie-live flag) but they're lower-stakes than a
    # pro league's actual playoffs/group stage, and "live sorts first" alone let a national
    # qualifier outrank a live Playoffs match from a real league. User call: minor brackets never
    # take the featured/first live slot, even when legitimately live.
    _MINOR_LEAGUE_KW = ("qualifier", "nation cup", "nations cup", "amateur")
    for m in matches:
        m["minorLeague"] = any(kw in (m.get("league") or "").lower() for kw in _MINOR_LEAGUE_KW)

    matches.sort(key=lambda m: (not m["live"], m["minorLeague"], m["startTime"] or 0))

    for m in matches:
        m.pop("_ps_watch", None)  # internal-only stream fallback, not part of the API shape
        m.pop("_score_repaired", None)  # internal self-heal flag, not part of the API shape
        m.pop("_ps_id", None)  # internal PandaScore id for dedup, not part of the API shape

    # Idle (nothing live) -> hold the response 5min so we stop rebuilding/pinging upstreams every
    # minute; something live -> 60s so scores stay fresh.
    any_live = any(m.get("live") for m in matches)
    out = {"matches": matches, "source": "bovada"}
    _up_cache.update(t=now, data=out, ttl=(60 if any_live else 300))
    return out
