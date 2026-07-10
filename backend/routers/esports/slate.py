"""slate.reviewed.py — the esports slate rebuilt around an explicit match STATE MACHINE.

REDESIGN (2026-07-03 expert review — full critique with live evidence in
logs/SLATE-EXPERT-REVIEW-2026-07-03.md). Drop-in for slate.py: same APIRouter, same
/api/esports/upcoming response shape, plus additive fields:

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
import re
import threading
import time
import urllib.request as _u

from fastapi import APIRouter

from .common import (_amer_to_p, _ESPORTS_TITLES, _slug_to_name, _TITLE_SLUG, _canon_team_x,
                     _canon_tokens, _fold, _GRID_LABEL_SLUG)
from .grid import _grid_score_index
from .lol import msi_predictions
from .results_store import _load_results_store, _save_results_store
from .frag import _fetch_frag_live, _parse_frag_score
from .pandascore import (_ps_enrich, _ps_logo_for, _ps_surface_matches, _ps_team_logo_api,
                         _fetch_ps)
from .kalshi import _kalshi_esports_matchups, _kalshi_results
from .league_tier import apply_tier_and_filter

# Stream helpers: post-swap these live in streams.py; pre-swap (validation) load the reviewed file
# by path so this module is testable without touching the running streams.py.
try:
    from .streams import _pick_stream, _rule_candidates, _resolve_watch, _candidate  # noqa: F401
except ImportError:
    _spec = importlib.util.spec_from_file_location(
        "routers.esports._streams_reviewed",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "streams.reviewed.py"))
    _sr = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_sr)
    _pick_stream, _rule_candidates, _resolve_watch, _candidate = (
        _sr._pick_stream, _sr._rule_candidates, _sr._resolve_watch, _sr._candidate)

router = APIRouter()

_BOV_ESPORTS = ("https://www.bovada.lv/services/sports/event/coupon/events/A/description/"
                "esports?marketFilterId=def&liveOnly=false&lang=en")
_up_cache = {"t": 0.0, "data": None}
_up_rebuild_lock = threading.Lock()
_up_rebuilding = False
_up_rebuild_started = 0.0
_REBUILD_STUCK_S = 300  # watchdog: a single-flight flag held >5min means a hung rebuild — the old
                        # code froze the whole slate forever in that case (no timeout, endpoint kept
                        # 200ing stale data); now a new rebuild is allowed to take over.

# ---------------------------------------------------------------------------
# state machine
# ---------------------------------------------------------------------------
S_SCHEDULED = "scheduled"
S_LIVE = "live"
S_FINISHED = "finished"
S_ENDED_UNKNOWN = "ended_unknown"

_START_SLACK_MS = 15 * 60 * 1000       # start-time drift tolerance before "past start" means anything
_DELAYED_CAP_MS = 4 * 3600 * 1000      # how long an affirmed not_started match may stay SCHEDULED past start
_LIVE_LEAD_MS = 20 * 60 * 1000
_LIVE_TAIL_MS = 6 * 3600 * 1000
_FINISH_GRACE_MS = 45 * 60 * 1000      # wait for a real scoreline before archiving a winner-only final
# --- live-evidence FRESHNESS (zombie-live fix) ---
# GRID CS2/Dota series-state ticks every ~2-5min while a match is live (per round). A
# `started && !finished` series whose GRID `updatedAt` is older than this has STOPPED updating =
# the match is over even though GRID's `finished` flag never flipped (it lags / never fires on
# minor events). 30min sits far above the ~5min live cadence and any realistic map/tech break, and
# far below the observed zombie (Prestige v Vasteras: 229min stale) — no risk of demoting a real
# live match, decisive on a dead one.
_LIVE_FRESH_MS = 30 * 60 * 1000
# Hard backstop: NOTHING is LIVE more than this past its start, whatever any source claims. A CS2/
# Dota Bo5 tops out ~4-5h; 6h leaves headroom while killing any stale-flag zombie a per-source
# freshness check might miss (stale frag listing, PS lagging running->finished).
_MAX_LIVE_MS = 6 * 3600 * 1000
# Bovada's live flag is the stickiest, least-reliable liveness signal (it silently keeps/drops and
# carries no timestamp — unlike PS `running` or frag's live-only feed, which are active "live now"
# assertions). A match whose ONLY live signal is Bovada's flag is trusted live for at most this long
# past start (a long Bo5); beyond it, a bov-only signal is treated as stale. Real long matches almost
# always also surface on PS/frag/GRID, so this near-exclusively kills stale-flag zombies.
_BOV_LIVE_MAX_MS = 3 * 3600 * 1000
_finish_seen = {}

# ---------------------------------------------------------------------------
# identity — ONE team matcher for clustering, GRID lookup, and Kalshi lookup
# ---------------------------------------------------------------------------
# Cross-source aliases (NIP/Ninjas in Pyjamas, AG.AL/AllGamers/Anyone's Legend, BB/BetBoom, SYF/
# SYGaming) now live in common._XALIASES so `_ps_enrich` bridges them too — see `_ckey` below.
# Affix-match residual policy (ALLOWLIST, not blocklist). A word-boundary affix match ('Keyd' vs
# 'Keyd Stars') is the same team ONLY IF the extra word(s) are a known generic/sponsor/name suffix.
# Any OTHER distinct word means a DIFFERENT squad — 'G2' vs 'G2 HEL', 'Vitality' vs 'Vitality Rising
# Bees', 'Team Secret' vs 'Team Secret Whales', 'MIBR' vs 'MIBR LOS'. This flips the old tiny
# blocklist (which passed everything not explicitly listed) to fail-closed: unknown suffix => split.
# (esports/gaming/gg/team are already dropped as generic tokens, so they never reach the residual.)
_MERGE_OK_SUFFIX = frozenset({"stars", "galaxy", "kia", "globant", "w7m"})


def _residual_droppable(residual):
    """True if every residual token is a droppable generic/sponsor/name suffix.

    Map-market markers are deliberately NOT droppable: ``Team - LMap 2`` is a betting sub-market,
    not another spelling of the series team, and must never merge into the real match.
    """
    for tok in residual:
        if tok in _MERGE_OK_SUFFIX:
            continue
        return False
    return True


def _ckey(name):
    return _canon_team_x(name or "")


_VOWELS = frozenset("aeiou")


def _consonant_skeleton(k):
    """Vowel-elided form of a canonical key — the SAME letters minus vowels, order preserved.
    'levelup' -> 'lvlp', 'lvlup' -> 'lvlp'. Lets the matcher recognize a vowel-dropped abbreviation
    ('LVLUP' == 'Level UP') as one team WITHOUT a hardcoded alias — this is a mechanical spelling of
    the same name, not a genuinely-different label (contrast Power Ranger vs Poor Rangers, which are
    different words and still need an explicit alias)."""
    return "".join(ch for ch in k if ch not in _VOWELS)


def _same_team(a, b):
    """One shared answer to 'are these the same team?' — canonical equality, anagram (letter-swap
    typos: Dontsu/Donstu, AION/Aoin — Kalshi and GRID both carry such variants), a guarded affix
    match ('9z' vs '9z Globant' sponsor suffix) whose residual isn't a distinct-squad marker, or a
    vowel-elided abbreviation ('LVLUP' == 'Level UP')."""
    ka, kb = _ckey(a), _ckey(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    if len(ka) >= 4 and len(kb) >= 4 and sorted(ka) == sorted(kb):
        return True  # exact anagram
    # Affix match at WORD-TOKEN granularity (not substrings of the concatenated key). The old
    # char-level `l.startswith(s)` matched 'gam' INSIDE 'gamerlegion' and merged unrelated orgs
    # (GAM Esports==GamerLegion, Rustec==TEC, Eterna==eternal premium). Now the shorter name's
    # tokens must be a leading or trailing RUN of the longer's, with a residual carrying no
    # distinct-squad marker — keeps '9z'=='9z Globant', 'Keyd'=='Keyd Stars', 'Nigma'=='Nigma Galaxy'.
    ta, tb = _canon_tokens(a), _canon_tokens(b)
    ss, ls = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if ss and len(ss) < len(ls):
        residual = (ls[len(ss):] if ls[:len(ss)] == ss else
                    ls[:len(ls) - len(ss)] if ls[len(ls) - len(ss):] == ss else None)
        if residual is not None and _residual_droppable(residual):
            return True
    # Trivial spelling variant of the SAME name — plural/truncation ('Inner Circle Prospect' vs
    # '...Prospects', 'Falcon' vs 'Falcons'): concatenated keys differ only by a <=2-char tail. The
    # word-boundary rule above treats 'prospect'/'prospects' as different tokens and won't merge
    # them, so this recovers that (the old char-level affix used to, incidentally). Guarded to keys
    # >=6 chars with a <=2-char residual so it can't reopen the short-prefix whole-word merges just
    # closed ('g2'/'g2hel', 'gam'/'gamerlegion' have <6-char shorter keys or a >2-char residual).
    sp, lp = (ka, kb) if len(ka) <= len(kb) else (kb, ka)
    if len(sp) >= 6 and lp.startswith(sp) and (len(lp) - len(sp)) <= 2:
        return True
    # Vowel-elided abbreviation: identical consonant skeletons (>=4 to keep short names like
    # 'BIG'/'Bug'->'bg' from colliding) AND actually different by vowels (not a same-length reshuffle
    # the anagram rule already owns). Requires the vowel-dropped one to be a subsequence of the other
    # so it's a real abbreviation, not two words that merely share consonants.
    sk, lk = (ka, kb) if len(ka) <= len(kb) else (kb, ka)
    sa, sb = _consonant_skeleton(ka), _consonant_skeleton(kb)
    if len(sa) >= 4 and sa == sb and ka != kb and _is_subsequence(sk, lk):
        return True
    return False


def _is_subsequence(s, l):
    """Is every char of s found in l in order (s an abbreviation of l)? 'lvlup' ⊆ 'levelup'."""
    it = iter(l)
    return all(ch in it for ch in s)


def _same_pair(a1, b1, a2, b2):
    return ((_same_team(a1, a2) and _same_team(b1, b2)) or
            (_same_team(a1, b2) and _same_team(b1, a2)))


_MAP_SUFFIX_RE = re.compile(r"\s*[-–—]?\s*l?map\s*\d+\s*$", re.IGNORECASE)


def _strip_map_suffix(name):
    """Remove a trailing Bovada map-market marker from a display label."""
    return _MAP_SUFFIX_RE.sub("", name or "").strip()


def _is_map_market(m):
    """A two-sided ``- LMap N`` row is a map betting market, not a real series match."""
    a, b = m.get("teamA") or "", m.get("teamB") or ""
    return bool(_MAP_SUFFIX_RE.search(a) and _MAP_SUFFIX_RE.search(b))


_RES_ARCHIVE_LEAGUE_FIXES = {
    frozenset({_ckey("Arch"), _ckey("Virtus.pro")}):
        "RES Showdown Europe Fall 2026 — East European Open Qualifier",
    frozenset({_ckey("Metanoia Wolves"), _ckey("Bounty Hunters")}):
        "RES Showdown South America Fall 2026 — Open Qualifier #2",
}


def _normalize_match_metadata(m):
    """Apply verified archive-label corrections and remove map-marker display contamination."""
    if (m.get("league") or "").strip().lower() == "res showdown fall 2025":
        pair = frozenset({_ckey(m.get("teamA")), _ckey(m.get("teamB"))})
        if pair in _RES_ARCHIVE_LEAGUE_FIXES:
            m["league"] = _RES_ARCHIVE_LEAGUE_FIXES[pair]
    m["teamA"] = _strip_map_suffix(m.get("teamA"))
    m["teamB"] = _strip_map_suffix(m.get("teamB"))
    if m.get("favorite") and m["favorite"].get("name"):
        m["favorite"] = dict(m["favorite"])
        m["favorite"]["name"] = _strip_map_suffix(m["favorite"]["name"])
    return m


def _repair_logos_by_psid(m):
    """Re-align logoA/logoB to the authoritative PandaScore record for a stored match.

    A stored entry can carry flipped crests baked in from a prior cycle (the old coupled fill in
    _rebuild_upcoming wrote the wrong side). When the row carries a stable ``psId`` we re-enrich the
    stored team names through ``_ps_enrich`` (which returns a swapped-correct logo per side) and adopt
    its logos when they differ from what's stored — correcting a previously-flipped crest rather than
    freezing it. No-op when there's no psId or the enrichment yields no logos.

    Fallback: rows WITHOUT a psId (older records predating psId persistence) still get corrected by a
    name-based PS enrich — if PS can canonicalize both team names, re-derive each side's crest from the
    matched canonical side so a flipped crest is fixed even when no stable id is available."""
    ta, tb = m.get("teamA", ""), m.get("teamB", "")
    if not (ta and tb):
        return m
    psid = m.get("psId") or m.get("_ps_id")
    ps = None
    if psid:
        ps = _ps_enrich(ta, tb, include_running=True, near_ms=m.get("startTime"),
                        league=m.get("league"), ps_id=psid)
    if not ps:
        # psId-less fallback: resolve on names so legacy rows still get the correct crests.
        ps = _ps_enrich(ta, tb, include_running=True, near_ms=m.get("startTime"),
                        league=m.get("league"))
    if not ps:
        return m
    la, lb = ps.get("logoA"), ps.get("logoB")
    ca, cb = ps.get("canonicalA"), ps.get("canonicalB")
    if not (la and lb and ca and cb):
        return m
    new_a = la if _same_team(ta, ca) else (lb if _same_team(ta, cb) else m.get("logoA"))
    new_b = lb if _same_team(tb, cb) else (la if _same_team(tb, ca) else m.get("logoB"))
    if new_a != m.get("logoA") or new_b != m.get("logoB"):
        m["logoA"], m["logoB"] = new_a, new_b
    return m


def _is_placeholder_score(sc):
    if not sc:
        return True
    return not (sc.get("a") or 0) and not (sc.get("b") or 0)


def _has_result(m):
    """A finished match actually carries a RESULT — a winner, or a real (non-placeholder) scoreline
    (a Bo2 group-stage 1-1 draw is a legit result with no winner). A finished archive that has
    NEITHER is not really settled: it's ended_unknown and must be retried, never frozen as a bare
    'Final' (the mislabeled-finish class behind the EWC/round-robin no-result cards, 2026-07-09)."""
    return bool(m.get("winner")) or (m.get("score") is not None and not _is_placeholder_score(m.get("score")))


# ---------------------------------------------------------------------------
# source lookups sharing the one matcher
# ---------------------------------------------------------------------------
def _grid_lookup(team_a, team_b, gidx):
    """GRID entry for a pairing -> (entry, gridA, gridB). Uses _same_team over both the short
    seriesState names AND allSeries full names, so anagram variants (GRID 'Team Aoin' vs slate
    'Team AION') resolve — the old _grid_match's substring-only test missed them, which is why a
    finished Dota match shipped a fake 0-0 while GRID held the real 0-2 (live case 2026-07-03)."""
    for entry in gidx:
        names = entry.get("names") or []
        fulls = entry.get("fullNames") or []
        ga = gb = None
        for i, gn in enumerate(names):
            variants = [gn] + ([fulls[i]] if i < len(fulls) and fulls[i] else [])
            if any(_same_team(team_a, v) for v in variants):
                ga = gn
            if any(_same_team(team_b, v) for v in variants):
                gb = gn
        if ga and gb and ga != gb:
            return entry, ga, gb
    return None, None, None


def _kalshi_winner_fuzzy(title, team_a, team_b, near_ms=None, tol_ms=12 * 3600 * 1000):
    """Settled-market winner ('a'/'b') via _same_team instead of exact canonical-frozenset keys.
    The exact-key lookup missed BOTH of today's rotting ghosts even though Kalshi HAD settled them:
    slate '9Z Globant' vs Kalshi '9z', slate 'Dontsu' vs Kalshi 'Donstu' (verified live 2026-07-03)."""
    best = None  # (delta, winner_name)
    seen_winners = set()  # ambiguity guard (2026-07-06, the NRG/Karmine flip)
    for (t, pair), settlements in (_kalshi_results() or {}).items():
        if t != title or len(pair) != 2:
            continue
        p = sorted(pair)
        if not _same_pair(team_a, team_b, p[0], p[1]):
            continue
        for winner, close_ms in settlements:
            if near_ms and close_ms and abs(close_ms - near_ms) > tol_ms:
                continue
            seen_winners.add(winner)
            d = abs((close_ms or near_ms or 0) - (near_ms or 0))
            if best is None or d < best[0]:
                best = (d, winner)
    if best is None:
        return None
    # Multiple in-window settlements naming DIFFERENT winners for this pair (map markets,
    # split series events) -> we don't actually know the match winner. Wait for a real result.
    if len(seen_winners) > 1:
        return None
    w = best[1]
    return "a" if _same_team(w, team_a) else "b" if _same_team(w, team_b) else None


def _frag_lookup(team_a, team_b):
    """frag.se live record for a pairing -> (match_dict, swapped) or (None, None). Full record so
    the stream pass can pool ALL its streams (the old _frag_enrich pre-picked one and threw the
    rest away — losing e.g. the YouTube cast of Heretics v AG.AL, live case 2026-07-03).
    frag's status/score are used as LIVE evidence only — never to declare finished/winner (its
    status vocabulary is unvetted, and deriving a winner from a partial score is forbidden)."""
    for m in _fetch_frag_live() or []:
        opps = m.get("opponents") or []
        if len(opps) < 2:
            continue
        def _vars(o):
            op = o.get("opponent") or {}
            return [v for v in (op.get("name"), op.get("acronym"), op.get("slug")) if v]
        va, vb = _vars(opps[0]), _vars(opps[1])
        ab = any(_same_team(team_a, v) for v in va) and any(_same_team(team_b, v) for v in vb)
        ba = any(_same_team(team_a, v) for v in vb) and any(_same_team(team_b, v) for v in va)
        if ab or ba:
            return m, (ba and not ab)
    return None, None


def _frag_candidates(frag_match):
    """All of a frag record's streams as pool candidates (attested: frag only lists live matches)."""
    out = []
    for s in (frag_match.get("streams") or []):
        out.append(_candidate(url=s.get("raw_url"), embed=s.get("embed_url"),
                              main=s.get("main"), official=s.get("official"),
                              language=s.get("language"), attested=True, source="frag"))
    if not out:
        off = (frag_match.get("official_stream_url") or "").strip()
        if off:
            out.append(_candidate(embed=off, official=True, attested=True, source="frag"))
    return [c for c in out if c]


def _ps_candidates(ps_id, ps_streams_by_id, running):
    """PandaScore streams_list of the matched match as pool candidates."""
    out = []
    for s in ps_streams_by_id.get(ps_id) or []:
        out.append(_candidate(url=s.get("raw_url"), embed=s.get("embed_url"),
                              main=s.get("main"), official=s.get("official"),
                              language=s.get("language"), attested=bool(running), source="pandascore"))
    return [c for c in out if c]


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
# rebuild pipeline: gather rows -> cluster -> evidence -> state -> streams
# ---------------------------------------------------------------------------
def _key(m):
    return f"{m.get('teamA','')}||{m.get('teamB','')}||{m.get('title','')}||{m.get('league','')}"


def _fetch_bovada_rows(now_ms, stale_cutoff_ms):
    try:
        req = _u.Request(_BOV_ESPORTS, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        with _u.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
    except Exception:
        return None  # signal "Bovada down" — caller decides fallback
    rows = []
    for grp in data:
        for e in grp.get("events", []):
            parts = [p for p in (e.get("link") or "").split("/") if p]
            if len(parts) < 3:
                continue
            title_slug, league_slug = parts[1], parts[2]
            if title_slug not in _ESPORTS_TITLES:
                continue
            st = e.get("startTime")
            if not e.get("live") and st and st < stale_cutoff_ms:
                continue
            # Bovada lists LIVE MAP lines as separate events ('Power Ranger - LMap 2 vs
            # GamerLegion - LMap 2') — sub-match markets, not matches; they were rendering as
            # phantom rows with absurd 95% favorites (seen 2026-07-07). Match-winner rows only.
            if re.search(r"\bl?map\s*\d", (e.get("description") or "").lower()):
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
                    fav = {"name": pairs[0][0] if p0 >= 50 else pairs[1][0], "pct": max(p0, 100 - p0)}
            rows.append(_normalize_match_metadata({
                "startTime": st, "title": _ESPORTS_TITLES[title_slug],
                "league": _slug_to_name(league_slug),
                "teamA": pairs[0][0], "teamB": pairs[1][0],
                "favorite": fav, "watch": None,
                "_origin": "bovada", "_bov_live": bool(e.get("live")),
            }))
    return rows


_CARRY_FIELDS = ("startTime", "title", "league", "teamA", "teamB", "favorite",
                 "logoA", "logoB", "model", "minorLeague", "psId")


def _carry_row(old):
    """Identity + schedule ONLY from a previous-cycle row. live/score/winner/watch are NEVER carried
    (a carried live flag or scoreline is last cycle's state, not this cycle's — the BetBoom 'stale
    1-0 partial' class). An archived result (finishedAt) keeps its settled fields."""
    row = {f: old.get(f) for f in _CARRY_FIELDS if old.get(f) is not None}
    row.update({"watch": None, "pinned": True, "_origin": "carry"})
    if old.get("finishedAt"):
        row.update({"finishedAt": old["finishedAt"], "finished": True,
                    "winner": old.get("winner"), "score": old.get("score"),
                    "_origin": "store"})
        if old.get("resultUnknown"):
            # Carry the label too, not just the null winner/score — otherwise a reloaded
            # ended_unknown entry re-derives as a bare S_FINISHED (implying a settled 0-0/no-winner
            # result) instead of staying honestly marked "result unavailable, still being retried".
            row["resultUnknown"] = True
    return _normalize_match_metadata(row)


_ORIGIN_PRIO = {"bovada": 0, "pandascore": 1, "grid": 2, "carry": 3, "store": 4}


# A team cannot play two matches within this window, so two same-title rows this close in start time
# that share an exactly-matched team are the SAME real match — even if the strict pair test misses
# because the OTHER team is labelled differently across sources.
_RELAXED_MERGE_MS = 10 * 60 * 1000


# Squad-distinguishing words: their presence means two similar names are DIFFERENT teams of one org
# (a main team vs its academy/B/women's side), never a labelling variant — so they must never be
# collapsed. 'academy' is the canonical case (common.py keeps it out of the generic-word strip).
_DISTINCT_SQUAD = frozenset({"academy", "youth", "junior", "juniors", "jr", "women", "woman",
                             "female", "fem", "prospect", "prospects", "reserve", "reserves",
                             "ii", "iii", "b", "ex"})  # 'ex' = departed roster, a distinct entity


def _label_variant(a, b):
    """The two names plausibly label the SAME team — an org-tag / spelling variant like 'Sharks' vs
    'YNG Sharks Esports' — and NOT two distinct squads of one org. They must share >=1 canonical
    token AND the differing tokens must carry no distinct-squad marker. This guards the NON-exact
    side of a relaxed same-match merge: it accepts 'Sharks' <> 'YNG Sharks' (residual {yng}) but
    rejects 'FaZe' <> 'FaZe Academy' (residual {academy}), so a main-squad match and its academy's
    match at the same time can never collapse into one."""
    ta, tb = set(_canon_tokens(a)), set(_canon_tokens(b))
    if not (ta & tb):
        return False
    return not ((ta ^ tb) & _DISTINCT_SQUAD)


def _league_signature(league):
    """Order-insensitive league identity for cross-source label variants.

    Sources reorder the same league words (for example, ``CCT South America — Series 3 2026`` vs
    ``CCT 2026 South America Series 3``). Keeping every normalized token, including season, series,
    and stage, makes those spellings equal without collapsing distinct events.
    """
    return tuple(sorted(re.findall(r"[a-z0-9]+", _fold(league or "").lower())))


def _same_league(ri, rj):
    li, lj = _league_signature(ri.get("league")), _league_signature(rj.get("league"))
    return bool(li and li == lj)


def _league_scoped_variant(a, b):
    """Allow unrelated labels only when the match-level league/time guards already agree.

    Distinct-roster markers remain a hard veto so the physical-invariant fallback cannot merge a
    main squad with its academy, women's, reserve, or departed roster.
    """
    tokens = set(_canon_tokens(a)) | set(_canon_tokens(b))
    return bool(a and b) and not (tokens & _DISTINCT_SQUAD)


def _same_match_relaxed(ri, rj):
    """Merge two same-title rows the strict pair test missed but which MUST be the same real match:
    their starts are within _RELAXED_MERGE_MS and ONE team matches exactly (_same_team) while the
    OTHER is either a lexical label variant (_label_variant), or the rows carry the same normalized
    league identity and the other labels have no distinct-roster marker. The latter is deliberately
    match-scoped: it merges `LP` with `largadosypelados` for the same CCT fixture without making the
    globally-ambiguous `LP` a team alias. The physical invariant does the work: a team can't be in
    two matches at once. Academy/women/reserve/ex-roster differences remain a hard veto."""
    si, sj = ri.get("startTime"), rj.get("startTime")
    if not (si and sj) or abs(si - sj) > _RELAXED_MERGE_MS:
        return False
    a1, b1 = ri.get("teamA", ""), ri.get("teamB", "")
    a2, b2 = rj.get("teamA", ""), rj.get("teamB", "")
    same_league = _same_league(ri, rj)

    def _other_side_matches(x, y):
        return _label_variant(x, y) or (same_league and _league_scoped_variant(x, y))

    return ((_same_team(a1, a2) and _other_side_matches(b1, b2)) or
            (_same_team(b1, b2) and _other_side_matches(a1, a2)) or
            (_same_team(a1, b2) and _other_side_matches(b1, a2)) or
            (_same_team(b1, a2) and _other_side_matches(a1, b2)))


def _cluster(rows):
    """Union-find over (same title, same pair, near start) -> one merged row per real match."""
    n = len(rows)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    by_title = {}
    for i, r in enumerate(rows):
        by_title.setdefault(r.get("title"), []).append(i)
    for idxs in by_title.values():
        for x in range(len(idxs)):
            for y in range(x + 1, len(idxs)):
                i, j = idxs[x], idxs[y]
                ri, rj = rows[i], rows[j]
                si, sj = ri.get("startTime"), rj.get("startTime")
                same_ps_id = bool(ri.get("psId") and ri.get("psId") == rj.get("psId"))
                if not same_ps_id and si and sj and abs(si - sj) > 8 * 3600 * 1000:
                    continue  # same pair meeting twice (rematch) stays two matches
                if (same_ps_id
                        or _same_pair(ri.get("teamA", ""), ri.get("teamB", ""),
                                      rj.get("teamA", ""), rj.get("teamB", ""))
                        or _same_match_relaxed(ri, rj)):
                    pi, pj = find(i), find(j)
                    if pi != pj:
                        parent[pj] = pi
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    merged = []
    for idxs in groups.values():
        grp = sorted((rows[i] for i in idxs), key=lambda r: _ORIGIN_PRIO.get(r.get("_origin"), 9))
        base = dict(grp[0])
        # DISPLAY NAMES: prefer PandaScore's canonical team names over Bovada's labels when a
        # PS twin exists (Micah 2026-07-07: Bovada prints 'Power Ranger' for what the EWC
        # officially lists as 'Poor Rangers'). Identity/dedup is _canon_team's job and already
        # merged the rows; this only picks the honest spelling, aligned via _same_team so a
        # reversed pair can't swap names onto the wrong sides.
        if base.get("_origin") == "bovada":
            ps_twin = next((r for r in grp[1:] if r.get("_origin") == "pandascore"), None)
            if ps_twin and ps_twin.get("teamA") and ps_twin.get("teamB"):
                if _same_team(base.get("teamA", ""), ps_twin["teamA"]) and \
                   _same_team(base.get("teamB", ""), ps_twin["teamB"]):
                    base["teamA"], base["teamB"] = ps_twin["teamA"], ps_twin["teamB"]
                elif _same_team(base.get("teamA", ""), ps_twin["teamB"]) and \
                     _same_team(base.get("teamB", ""), ps_twin["teamA"]):
                    base["teamA"], base["teamB"] = ps_twin["teamB"], ps_twin["teamA"]
        for other in grp[1:]:
            for f in ("favorite", "model", "logoA", "logoB", "startTime", "league", "source"):
                if not base.get(f) and other.get(f):
                    base[f] = other[f]
            # Align + adopt an archived result from a clustered twin (the '3DMAX v 9z' finished
            # entry resolving the '3DMAX v 9Z Globant' ghost). A resultUnknown base may already have
            # finishedAt, so a real result from its twin must still replace it (LP/largadosypelados).
            better_result = _has_result(other) and not _has_result(base)
            if other.get("finishedAt") and (not base.get("finishedAt") or better_result):
                base["finishedAt"] = other["finishedAt"]
                base["finished"] = True
                direct = (_same_team(base.get("teamA", ""), other.get("teamA", "")) or
                          _same_team(base.get("teamB", ""), other.get("teamB", "")))
                crossed = (_same_team(base.get("teamA", ""), other.get("teamB", "")) or
                           _same_team(base.get("teamB", ""), other.get("teamA", "")))
                flipped = crossed and not direct
                if better_result:
                    base["resultUnknown"] = False
                elif other.get("resultUnknown"):
                    base["resultUnknown"] = True
                w = other.get("winner")
                if w in ("a", "b"):
                    base["winner"] = (("b" if w == "a" else "a") if flipped else w)
                sc = other.get("score")
                if sc:
                    base["score"] = ({"a": sc.get("b"), "b": sc.get("a")} if flipped else sc)
            if other.get("_bov_live"):
                base["_bov_live"] = True
            if other.get("pinned"):
                base.setdefault("pinned", True)
        merged.append(base)
    return merged


def _grid_live_fresh(grid, now_ms, past):
    """GRID `started && !finished` counts as LIVE evidence ONLY if the series-state is still
    updating. A stale series (updatedAt older than _LIVE_FRESH_MS) has stopped ticking = the match
    is over, GRID just never flipped `finished` (the zombie mechanism). If GRID gave no updatedAt
    (older grid.py without the field), don't manufacture a zombie: trust `started&&!finished` only
    when the match isn't already past its start."""
    if not (grid and grid.get("started") and not grid.get("finished")):
        return False
    ua = grid.get("updatedAtMs")
    if ua is not None:
        return (now_ms - ua) < _LIVE_FRESH_MS
    return not past


def _derive_state(row, ev, now_ms):
    """The one place state comes from.

    'It's over' (any one ends the match): GRID.finished / PS.finished / archived result. GRID's
    finished flag LAGS on minor events (a PS finish must not be vetoed by GRID still showing
    started; the reverse holds for PS lag). A settled Kalshi market also ends it, but only when NO
    source affirms the match is live right now (a fuzzy same-pair settlement must not kill a
    genuinely running rematch).

    'It's live' — live evidence must be FRESH (zombie-live fix). A stale GRID series, or ANY source
    still claiming live past the _MAX_LIVE_MS hard cap, does NOT count as live. A match whose only
    'live' signal is stale is demoted here, which also UNBLOCKS the Kalshi/finish resolution below
    (`if kalshi and not live_ev`) so a demoted zombie becomes its real result instead of freezing.

    An ARCHIVED resultUnknown carry (a prior cycle's "ended, no source had a result") stays labeled
    S_ENDED_UNKNOWN — not a bare S_FINISHED implying a settled no-winner result — unless a FRESH
    source now confirms a real finish/settlement, so it's retried every cycle without ever losing
    the honest 'still unresolved' label, and can still be promoted the moment a result lands."""
    grid, ps, frag = ev.get("grid"), ev.get("ps"), ev.get("frag")
    st = row.get("startTime")
    past = st is not None and st < now_ms - _START_SLACK_MS
    too_old_to_live = st is not None and (now_ms - st) > _MAX_LIVE_MS

    grid_live = _grid_live_fresh(grid, now_ms, past)
    ps_live = bool(ps and ps.get("live"))          # explicit queried status (running), inherently fresh
    frag_live = frag is not None                    # frag /api/live is a live-only, ~60s-cached feed
    # Bovada flag: this-cycle only, unrebutted by PS, and only within the sticky-flag freshness window.
    bov_live = bool(row.get("_bov_live") and ps is None
                    and (st is None or (now_ms - st) <= _BOV_LIVE_MAX_MS))
    # Hard cap is the last-resort backstop for a live signal with no per-source freshness of its own.
    live_ev = (grid_live or ps_live or frag_live or bov_live) and not too_old_to_live

    fresh_finish = bool((grid and grid.get("finished")) or (ps and ps.get("finished")))
    fresh_kalshi = bool(ev.get("kalshi")) and not live_ev
    if fresh_finish or fresh_kalshi:
        return S_FINISHED
    if row.get("finishedAt") is not None:
        # A finished archive with no result (no winner, no real score) is really ended_unknown — keep
        # it retryable instead of freezing a bare 'Final' (relabels the mislabeled-finish archives).
        return S_ENDED_UNKNOWN if (row.get("resultUnknown") or not _has_result(row)) else S_FINISHED
    if live_ev:
        return S_LIVE
    if not st or st > now_ms - _START_SLACK_MS:
        return S_SCHEDULED
    if ps and not ps.get("live") and not ps.get("finished") and now_ms - st < _DELAYED_CAP_MS:
        # PandaScore AFFIRMS not_started: a delayed match is still scheduled, capped.
        return S_SCHEDULED
    return S_ENDED_UNKNOWN


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

    bov_rows = _fetch_bovada_rows(now_ms, stale_cutoff_ms)
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
    for m in _fetch_ps(include_running=live_window):
        if m.get("id") is not None:
            ps_streams_by_id[m["id"]] = m.get("streams_list") or []

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

    cutoff_ms = now_ms - 3 * 86400 * 1000
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
            m["watch"] = _pick_stream(pool, match_live=True, team_names=team_names,
                                       game=m.get("title")) if pool else None
        elif m["state"] == S_SCHEDULED and slug:
            ps_cands = (_ps_candidates(m["_ps_id"], ps_streams_by_id, False)
                        if m.get("_ps_id") is not None else [])
            # network_checks=False: even narrowed to a 3h window this was still enough concurrent
            # scheduled matches across all leagues, each paying sequential blocking HTTP calls
            # (Twitch/Kick liveness pings + YouTube resolution, no concurrency), to hang the
            # endpoint (2026-07-08 incident). Scheduled matches still get PS's raw stream URL
            # (Twitch/Kick embed synthesizes for free, no network) — just no verified/YouTube-
            # resolved embed until the match goes live and hits the S_LIVE branch above, which
            # already scopes down to the handful of matches actually live at once.
            m["watch"] = _resolve_watch(slug, m.get("league"), live=False,
                                         extra_candidates=ps_cands, team_names=team_names,
                                         network_checks=False)
        elif m["state"] == S_FINISHED and slug:
            m["watch"] = _resolve_watch(slug, m.get("league"), live=False)
        else:
            m["watch"] = None  # ended_unknown: no honest stream to offer

    # ---------------- output shaping ----------------
    out_matches = []
    for m in matches:
        state = m["state"]
        st = m.get("startTime")
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
        for k in [kk for kk in m if kk.startswith("_")]:
            m.pop(k, None)
        out_matches.append(m)

    # League-tier sort (marquee int'l > regional pro > challengers/dev > minor/novelty) + the
    # odds-or-stream visibility filter: this board's purpose is matches you can watch or bet on,
    # so a live/finished/ended_unknown match with neither has no reason to be shown (never applied
    # to SCHEDULED — a market/stream often just hasn't posted yet). See league_tier.py.
    out_matches, _dropped = apply_tier_and_filter(out_matches)

    any_live = any(m.get("live") for m in out_matches)
    out = {"matches": out_matches, "source": "bovada"}
    _up_cache.update(t=now, data=out, ttl=(60 if any_live else 300))
    return out
