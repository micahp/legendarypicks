"""cod_ewc.py — narrow EWC Call of Duty scoreboard reconciliation adapter.

Fixes the raw ``TBD`` defect on ``GET /api/cod/games`` during the EWC bracket (PLAN-esports-
ewc-2026.md Phase 1).  Breaking Point keeps useful CDL history but is NOT the sole participant
authority for EWC bracket games: its feed references EWC team ids that are absent from its
``teams`` dict, so ``breakingpoint_client`` degrades them to the literal string ``"TBD"`` — even
on finished matches with real scores.

This adapter reconciles EWC rows against the indexed PandaScore ``codmw`` EWC window:

- The PandaScore bracket graph (``/tournaments/<id>/brackets``) is fetched **once per refresh**
  and indexed; every scoreboard row is reconciled in memory.  Never one fetch per row.
- Association is by bracket round + participants/score evidence + bounded time — never by time
  alone, and never by loosening shared esports identity functions.
- Undecided bracket slots render structurally (``participant: {state: pending, feederGameId,
  outcome, label}``) instead of a fabricated club or a bare ``TBD``.
- Non-EWC CDL rows pass through untouched.
"""

import json
import threading
import time

from .ewc import (named_participant, participant_label, pending_participant,
                  unavailable_participant)
from .match_identity import _same_team
from .pandascore import _iso_to_ms, _ps_get

# Round-name vocabulary: PandaScore node-name prefix -> Breaking Point round label.
_PS_ROUND_PREFIX = ("quarterfinal", "semifinal", "3rd place", "grand final")
_BP_ROUND_KEYS = {
    "quarterfinals": "quarterfinal",
    "semifinals": "semifinal",
    "3rd place decider": "3rd place",
    "grand finals": "grand final",
}
_TIME_TOL_MS = 3 * 3600 * 1000      # absorbs the observed 1h30m-1h40m BP/PS schedule shift
_CACHE_TTL_S = 120

_cache = {"t": 0.0, "data": None}
_cache_lock = threading.Lock()


# ---------------------------------------------------------------------------
# graph build (pure; fixture-testable)
# ---------------------------------------------------------------------------
def _round_key(node_name):
    """Normalize a PandaScore node name to its round key, e.g. 'Quarterfinal 1: G2 vs HTCS'
    -> 'quarterfinal', 'Grand final: TBD vs TBD' -> 'grand final'."""
    name = (node_name or "").lower()
    for prefix in _PS_ROUND_PREFIX:
        if name.startswith(prefix):
            return prefix
    return None


def _bp_round_key(round_label):
    norm = " ".join((round_label or "").lower().split())
    return _BP_ROUND_KEYS.get(norm)


def _side_name(opponents, index):
    """Club name of the index-th opponent, or None (absent = undecided slot)."""
    if opponents is None or index >= len(opponents):
        return None
    opp = opponents[index]
    if isinstance(opp, dict) and "opponent" in opp:
        opp = opp.get("opponent") or {}  # raw PandaScore wrapper shape
    return opp.get("name")


def _results_map(match):
    return {r.get("team_id"): r.get("score") for r in (match.get("results") or [])}


def build_ewc_cod_graph(bracket_matches, serie_matches):
    """Build the indexed EWC CoD bracket graph from raw PandaScore payloads.

    Returns ``{"nodes": {ps_id: node}, "by_round": {round_key: [node, ...]}}`` where each node
    carries: ps_id, round_key, node_name, scheduled_ms, begin_ms, status, opponents (club names),
    prev [(outcome, feeder_ps_id)], winner_id, results.  ``serie_matches`` supplies feeder
    details (club names) for matches that share ids with bracket nodes.
    """
    by_id = {}
    for m in serie_matches:
        if m.get("id") is not None:
            by_id[m["id"]] = m

    nodes, by_round = {}, {}
    bracket_ids = set()
    for bm in bracket_matches:
        mid = bm.get("id")
        if mid is None:
            continue
        bracket_ids.add(mid)
        name = bm.get("name") or ""
        rk = _round_key(name)
        opps = bm.get("opponents") or []
        node = {
            "ps_id": mid,
            "node_name": name,
            "round_key": rk,
            "scheduled_ms": _iso_to_ms(bm.get("scheduled_at") or bm.get("begin_at")),
            "begin_ms": _iso_to_ms(bm.get("begin_at")),
            "status": (bm.get("status") or "").lower(),
            "opponents": [o.get("opponent") or {} for o in opps],
            "prev": [(p.get("type"), p.get("match_id")) for p in (bm.get("previous_matches") or [])],
            "winner_id": bm.get("winner_id"),
            "results": _results_map(bm),
        }
        # feeder index: node ids also appear in serie_matches (they carry opponents)
        feeder = by_id.get(mid)
        if feeder is not None:
            node["opponents"] = [o.get("opponent") or {} for o in (feeder.get("opponents") or [])]
            node["status"] = (feeder.get("status") or "").lower()
            node["results"] = _results_map(feeder)
            node["winner_id"] = feeder.get("winner_id")
        nodes[mid] = node
        by_round.setdefault(rk, []).append(node)
    for lst in by_round.values():
        lst.sort(key=lambda n: (n["scheduled_ms"] is None, n["scheduled_ms"] or 0))
    # Group-stage matches: serie matches that are not bracket nodes, indexed for the
    # event + name + narrow-time association of non-bracket EWC scoreboard rows.
    group_matches = []
    for m in serie_matches:
        mid = m.get("id")
        if mid is None or mid in bracket_ids:
            continue
        opps = [o.get("opponent") or {} for o in (m.get("opponents") or [])]
        if len(opps) < 2 or not opps[0].get("name") or not opps[1].get("name"):
            continue
        group_matches.append({
            "ps_id": mid,
            "opponents": opps,
            "scheduled_ms": _iso_to_ms(m.get("scheduled_at") or m.get("begin_at")),
            "status": (m.get("status") or "").lower(),
            "results": _results_map(m),
            "winner_id": m.get("winner_id"),
        })
    return {"nodes": nodes, "by_round": by_round, "group_matches": group_matches}


def _feeder_display(graph, feeder_id):
    """A short display for a feeder match: 'A vs B' when both sides are known clubs, else the
    feeder's bracket node name (e.g. 'Quarterfinal 3').  When the feeder node is absent from the
    graph, an honest structural label is used — never a literal 'TBD'."""
    node = graph["nodes"].get(feeder_id)
    if node is None:
        return "preceding match"
    names = [_side_name(node["opponents"], i) for i in (0, 1)]
    if names[0] and names[1]:
        return f"{names[0]}–{names[1]}"
    return node["node_name"].split(":")[0].strip() or "preceding match"


def _feeder_outcome_club(graph, feeder_id, outcome):
    """The club a decided feeder produces for its downstream slot, or None if undecided.

    ``outcome`` is the predecessor entry type ('winner' or 'loser'): the winner side is the
    feeder's ``winner_id`` club; the loser side is the *other* named opponent.  Returns
    ``(club_id, club_name)``, or None when the side cannot be determined (feeder undecided, the
    loser's identity absent from the feeder's opponent list, or an unknown outcome type)."""
    node = graph["nodes"].get(feeder_id)
    if node is None or not node.get("winner_id"):
        return None
    if outcome == "loser":
        others = [opp for opp in node["opponents"] if opp.get("id") != node["winner_id"]]
        if len(others) == 1 and others[0].get("id") and others[0].get("name"):
            return (others[0]["id"], others[0]["name"])
        return None
    if outcome == "winner":
        for opp in node["opponents"]:
            if opp.get("id") == node["winner_id"]:
                return (opp.get("id"), opp.get("name"))
    return None


def resolve_sides(graph, ps_id):
    """Resolve the two display sides of a bracket node.

    For a node with predecessor entries the sides come from the feeder graph (winner/loser of the
    feeder match), never from the node's own stale ``opponents``/``name`` (PandaScore seeds those
    with the pre-tournament slot names).  The predecessor's ``type`` decides which side of the
    feeder fills the slot: ``winner`` for semifinal/grand-final slots, ``loser`` for the 3rd-place
    decider.  Verified against the 2026-08-08 fixture: PandaScore's
    ``previous_matches`` lists slot 2 first, then slot 1 (e.g. SF1 ``[winner(1609943),
    winner(1609942)]`` while ``opponents[0]``/name put HTCS = winner(1609942) on slot 1), so the
    pair is emitted as ``[prev[1], prev[0]]`` to match the node's own slot order.  Returns
    ``[participant, participant]``.
    """
    node = graph["nodes"].get(ps_id)
    if node is None:
        return [unavailable_participant(), unavailable_participant()]
    prev = node.get("prev") or []
    if not prev:
        sides = []
        for i in (0, 1):
            opp = node["opponents"][i] if i < len(node["opponents"]) else {}
            if opp.get("name"):
                sides.append(named_participant(opp.get("id"), opp["name"]))
            else:
                sides.append(unavailable_participant())
        return sides
    ordered = [prev[1] if len(prev) > 1 else prev[0], prev[0]]
    sides = []
    for outcome, feeder_id in ordered:
        resolved = _feeder_outcome_club(graph, feeder_id, outcome)
        if resolved is not None:
            sides.append(named_participant(resolved[0], resolved[1]))
            continue
        word = "Winner" if outcome == "winner" else "Loser"
        label = f"{word} of {_feeder_display(graph, feeder_id)}"
        sides.append(pending_participant(feeder_id, outcome, label))
    while len(sides) < 2:
        sides.append(unavailable_participant())
    return sides[:2]


# ---------------------------------------------------------------------------
# BP row association (round + evidence tiers, never time alone)
# ---------------------------------------------------------------------------
def _score_pair(node):
    """(a, b) score pair for a node in opponent order, or None when no real scores exist."""
    results = node.get("results") or {}
    if not results:
        return None
    ids = [o.get("id") for o in node.get("opponents", [])]
    if len(ids) < 2 or ids[0] is None or ids[1] is None:
        return None
    a, b = results.get(ids[0]), results.get(ids[1])
    if a is None or b is None:
        return None
    return (a, b)


def _same_score(bp_score, node_score):
    if bp_score is None or node_score is None:
        return False
    a, b = bp_score
    na, nb = node_score
    return (a == na and b == nb) or (a == nb and b == na)


def associate_bp_row(bp_row, graph, used_ids):
    """Associate a Breaking Point EWC row to a bracket node. Returns ps_id or None.

    Evidence tiers, in order (never time alone):
    1. Both BP participants known -> round + both names + bounded time.
    2. Real score pair on both sides -> round + exact score pair (any orientation), unique.
    3. Otherwise -> round + bounded time + not already used; closest wins.
    Ambiguity (two equally strong candidates) -> None (caller renders Participant unavailable).
    """
    round_key = _bp_round_key(bp_row.get("round") or bp_row.get("status") or "")
    if not round_key:
        return None
    candidates = graph["by_round"].get(round_key) or []
    if not candidates:
        return None
    bp_home = (bp_row.get("home") or {}).get("name")
    bp_away = (bp_row.get("away") or {}).get("name")
    bp_ms = _iso_to_ms(bp_row.get("date"))
    bp_score = None
    hs, as_ = (bp_row.get("home") or {}).get("score"), (bp_row.get("away") or {}).get("score")
    if hs is not None and as_ is not None:
        bp_score = (hs, as_)

    # Tier 1: both names known.
    if bp_home and bp_away and bp_home not in ("TBD", "TBA") and bp_away not in ("TBD", "TBA"):
        hits = []
        for node in candidates:
            names = [_side_name(node["opponents"], i) for i in (0, 1)]
            if not names[0] or not names[1]:
                continue
            if not (_same_team(bp_home, names[0]) and _same_team(bp_away, names[1]) or
                    _same_team(bp_home, names[1]) and _same_team(bp_away, names[0])):
                continue
            if bp_ms and node["scheduled_ms"] and abs(bp_ms - node["scheduled_ms"]) > _TIME_TOL_MS:
                continue
            hits.append(node["ps_id"])
        # One exact name match resolves; two or more is ambiguity — never guess the first.
        return hits[0] if len(hits) == 1 else None

    # Tier 2: decided score pair.
    if bp_score is not None:
        hits = [n for n in candidates if n["ps_id"] not in used_ids and _same_score(bp_score, _score_pair(n))]
        if len(hits) == 1:
            return hits[0]["ps_id"]
        if len(hits) > 1:
            return None  # ambiguous score pair — never resolve by guess

    # Tier 2.5: a live row maps to the round's unique running node. Breaking Point's EWC
    # datetimes are shifted vs PandaScore's scheduled times for part of the bracket, so a live
    # row must not fall through to time matching while its running node is unambiguous.
    if bp_row.get("state") == "in":
        running = [n for n in candidates if n["ps_id"] not in used_ids and n["status"] == "running"]
        if len(running) == 1:
            return running[0]["ps_id"]
        if len(running) > 1:
            return None  # two arenas live in one round — no unique running node

    # Tier 3: bounded time, unused node; prefer an exact/near-exact slot time, else strictly
    # closest (a tie never resolves).
    if bp_ms:
        in_range = [n for n in candidates if n["ps_id"] not in used_ids
                    and n["scheduled_ms"] and abs(bp_ms - n["scheduled_ms"]) <= _TIME_TOL_MS]
        if len(in_range) == 1:
            return in_range[0]["ps_id"]
        if len(in_range) > 1:
            near = [n for n in in_range if abs(bp_ms - n["scheduled_ms"]) <= 30 * 60 * 1000]
            if len(near) == 1:
                return near[0]["ps_id"]
            if len(near) > 1:
                return None
            in_range.sort(key=lambda n: abs(bp_ms - n["scheduled_ms"]))
            if abs(bp_ms - in_range[0]["scheduled_ms"]) != abs(bp_ms - in_range[1]["scheduled_ms"]):
                return in_range[0]["ps_id"]
    return None


_GROUP_TIME_TOL_MS = 45 * 60 * 1000  # group-stage BP/PS datetimes agree within ~0-30 min (observed)


def _associate_group_row(bp_row, graph):
    """Associate a non-bracket EWC row against the group-stage serie index.

    Evidence: event + participant names (one or both, whichever Breaking Point resolved) + a
    narrow time window.  A row with no resolvable names has no evidence -> None.  Time is never
    the only evidence; ambiguity never resolves by guess.
    """
    bp_home = (bp_row.get("home") or {}).get("name")
    bp_away = (bp_row.get("away") or {}).get("name")
    known = [n for n in (bp_home, bp_away) if n and n not in ("TBD", "TBA")]
    bp_ms = _iso_to_ms(bp_row.get("date"))
    if not known or bp_ms is None:
        return None
    hits = []
    for gm in graph.get("group_matches", []):
        names = [_side_name(gm["opponents"], i) for i in (0, 1)]
        if bp_ms and gm["scheduled_ms"] and abs(bp_ms - gm["scheduled_ms"]) > _GROUP_TIME_TOL_MS:
            continue
        if len(known) == 2:
            both = (_same_team(bp_home, names[0]) and _same_team(bp_away, names[1]) or
                    _same_team(bp_home, names[1]) and _same_team(bp_away, names[0]))
            if both:
                hits.append(gm)
        else:
            if _same_team(known[0], names[0]) or _same_team(known[0], names[1]):
                hits.append(gm)
    if len(hits) == 1:
        return hits[0]["ps_id"]
    return None


# ---------------------------------------------------------------------------
# fetch + cache (once per refresh; single-flight; last good survives)
# ---------------------------------------------------------------------------
def _fetch_bracket_graph():
    """Fetch the EWC CoD bracket graph from PandaScore: reuse the existing codmw feeds for the
    serie/tournament discovery and feeder index, plus ONE brackets call."""
    from .pandascore import _fetch_ps
    from .ewc import is_ewc_2026_serie

    serie_matches = []
    playoffs_tournament_id = None
    for m in _fetch_ps(include_running=True):
        # Restrict to the Call of Duty EWC serie: other EWC titles (CS2, R6, ...) also run
        # has_bracket tournaments and would otherwise hijack the bracket graph.
        if ((m.get("videogame") or {}).get("slug") or "") != "cod-mw":
            continue
        serie = m.get("serie") or {}
        if is_ewc_2026_serie(serie, m.get("league")):
            serie_matches.append(m)
            tour = m.get("tournament") or {}
            if tour.get("has_bracket") and playoffs_tournament_id is None:
                playoffs_tournament_id = tour.get("id")
    if playoffs_tournament_id is None:
        return None
    bracket = _ps_get(f"/tournaments/{playoffs_tournament_id}/brackets")
    if not isinstance(bracket, list) or not bracket:
        return None
    return build_ewc_cod_graph(bracket, serie_matches)


def get_ewc_cod_graph():
    """Cached graph accessor: one fetch per TTL, single-flight, last good on failure."""
    now = time.time()
    with _cache_lock:
        if _cache["data"] is not None and now - _cache["t"] < _CACHE_TTL_S:
            return _cache["data"]
    graph = None
    try:
        graph = _fetch_bracket_graph()
    except Exception as exc:  # network/parse faults must never crash the scoreboard
        print(f"[cod_ewc] bracket fetch failed: {exc}")
    if graph is not None:
        with _cache_lock:
            _cache.update(t=time.time(), data=graph)
    return _cache["data"] or graph


# ---------------------------------------------------------------------------
# reconciliation entrypoint
# ---------------------------------------------------------------------------
def _is_ewc_bp_row(row):
    """A Breaking Point row belongs to the EWC event when BP labels it so."""
    from .ewc import is_ewc_2026_label
    return is_ewc_2026_label((row.get("event") or "").strip()) or is_ewc_2026_label(
        (row.get("round") or "").strip())


def _rewrite_side(participant, score):
    """A /api/cod/games home/away dict from a resolved participant."""
    if participant.get("state") == "named":
        name = participant.get("clubName") or ""
        return {
            "abbrev": name.split()[0] if name else None,
            "name": name,
            "score": score,
            "participant": participant,
        }
    return {
        "abbrev": None,
        "name": None,
        "score": None,
        "participant": participant,
    }


def reconcile_cod_matches(matches, graph=None):
    """Rewrite EWC CoD scoreboard rows: real clubs from the indexed bracket graph, structural
    pending participants for undecided slots, Participant unavailable for unresolvable rows.
    Non-EWC rows are returned unchanged. ``graph`` injectable for tests."""
    if graph is None:
        graph = get_ewc_cod_graph()
    if graph is None:
        # No usable bracket graph: EWC rows must still never show a bare TBD.
        out = []
        for m in matches:
            if _is_ewc_bp_row(m):
                m = dict(m)
                m["home"] = _rewrite_side(unavailable_participant(), None)
                m["away"] = _rewrite_side(unavailable_participant(), None)
            out.append(m)
        return out

    used_ids = set()
    out = []
    # Decide rows first (score evidence), then time-closest, so a decided row never steals a
    # later row's node.
    def _score_order(m):
        hs = (m.get("home") or {}).get("score")
        as_ = (m.get("away") or {}).get("score")
        return 0 if (hs is not None and as_ is not None) else 1

    for m in sorted(matches, key=_score_order):
        if not _is_ewc_bp_row(m):
            out.append(m)
            continue
        ps_id = associate_bp_row(m, graph, used_ids)
        node = None
        if ps_id is not None:
            node = graph["nodes"].get(ps_id)
        if ps_id is None:
            # Non-bracket EWC rows (group play) reconcile against the group-stage index.
            ps_id = _associate_group_row(m, graph)
            node = None
            if ps_id is not None:
                for gm in graph.get("group_matches", []):
                    if gm["ps_id"] == ps_id:
                        node = gm
                        break
        if ps_id is None or node is None:
            print(f"[cod_ewc] unresolved EWC row {m.get('game_id')} ({m.get('date')})")
            m = dict(m)
            m["home"] = _rewrite_side(unavailable_participant(), None)
            m["away"] = _rewrite_side(unavailable_participant(), None)
            out.append(m)
            continue
        used_ids.add(ps_id)
        if "round_key" in node:
            # bracket node: sides resolve through the feeder graph (undecided slots stay pending)
            side_a, side_b = resolve_sides(graph, ps_id)
        else:
            # group-stage match: both sides are decided clubs
            side_a = named_participant(node["opponents"][0].get("id"), node["opponents"][0].get("name"))
            side_b = named_participant(node["opponents"][1].get("id"), node["opponents"][1].get("name"))
        hs = node["results"].get(node["opponents"][0].get("id")) if node["results"] and node["opponents"] else None
        as_ = node["results"].get(node["opponents"][1].get("id")) if node["results"] and len(node["opponents"]) > 1 else None
        live = node["status"] == "running"
        finished = node["status"] == "finished"
        score_a = hs if (live or finished) and hs is not None else None
        score_b = as_ if (live or finished) and as_ is not None else None
        m = dict(m)
        m["home"] = _rewrite_side(side_a, score_a)
        m["away"] = _rewrite_side(side_b, score_b)
        if m.get("detail_game_id") is None:
            m["detail_game_id"] = str(ps_id)
        if live:
            m["state"] = "in"
            m["status"] = "Live"
        elif finished:
            m["state"] = "post"
            m["status"] = "Final"
        out.append(m)
    # Restore original ordering (live first, then upcoming, then completed, by date).
    state_order = {"in": 0, "pre": 1, "post": 2}
    out.sort(key=lambda r: (state_order.get(r.get("state"), 9), r.get("date") or ""))
    return out
