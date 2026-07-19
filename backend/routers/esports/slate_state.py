"""Match lifecycle, clustering, and state policy for the esports slate."""

import re

from .common import _canon_tokens, _fold, _strip_name
from .match_identity import _normalize_match_metadata, _same_pair, _same_team


S_SCHEDULED = "scheduled"
S_LIVE = "live"
S_FINISHED = "finished"
S_ENDED_UNKNOWN = "ended_unknown"

_START_SLACK_MS = 15 * 60 * 1000
_DELAYED_CAP_MS = 4 * 3600 * 1000
_LIVE_LEAD_MS = 20 * 60 * 1000
_LIVE_TAIL_MS = 6 * 3600 * 1000
_FINISH_GRACE_MS = 45 * 60 * 1000
_LIVE_FRESH_MS = 30 * 60 * 1000
_MAX_LIVE_MS = 6 * 3600 * 1000
_BOV_LIVE_MAX_MS = 3 * 3600 * 1000
_CHANNEL_LIVE_TAIL_MS = _DELAYED_CAP_MS

_CARRY_FIELDS = ("startTime", "endTime", "title", "league", "teamA", "teamB", "favorite",
                 "logoA", "logoB", "model", "minorLeague", "psId")
_ORIGIN_PRIO = {"bovada": 0, "pandascore": 1, "grid": 2, "carry": 3, "store": 4}
_RELAXED_MERGE_MS = 10 * 60 * 1000
_DISTINCT_SQUAD = frozenset({
    "academy", "youth", "junior", "juniors", "jr", "women", "woman", "female", "fem",
    "prospect", "prospects", "reserve", "reserves", "ii", "iii", "b", "ex",
})


def _is_placeholder_score(score):
    if not score:
        return True
    return not (score.get("a") or 0) and not (score.get("b") or 0)


def _has_result(match):
    """Return whether a finished match carries an explicit winner or non-placeholder score."""
    return bool(match.get("winner")) or (
        match.get("score") is not None and not _is_placeholder_score(match.get("score")))


def _key(match):
    return (f"{match.get('teamA', '')}||{match.get('teamB', '')}||"
            f"{match.get('title', '')}||{match.get('league', '')}")


def _carry_row(previous):
    """Carry identity and schedule only; preserve settled fields only for archived results."""
    row = {field: previous.get(field) for field in _CARRY_FIELDS
           if previous.get(field) is not None}
    row.update({"watch": None, "pinned": True, "_origin": "carry"})
    if previous.get("finishedAt"):
        row.update({
            "finishedAt": previous["finishedAt"],
            "finished": True,
            "winner": previous.get("winner"),
            "score": previous.get("score"),
            "_origin": "store",
        })
        if previous.get("resultUnknown"):
            row["resultUnknown"] = True
    return _normalize_match_metadata(row)


def _label_variant(left, right):
    """Return whether labels plausibly differ only by a non-squad org or spelling token."""
    left_tokens, right_tokens = set(_canon_tokens(left)), set(_canon_tokens(right))
    if not (left_tokens & right_tokens):
        return False
    return not ((left_tokens ^ right_tokens) & _DISTINCT_SQUAD)


def _league_signature(league):
    """Return an order-insensitive league identity while retaining season and stage tokens."""
    return tuple(sorted(re.findall(r"[a-z0-9]+", _fold(league or "").lower())))


def _same_league(left, right):
    left_signature = _league_signature(left.get("league"))
    right_signature = _league_signature(right.get("league"))
    return bool(left_signature and left_signature == right_signature)


def _league_scoped_variant(left, right):
    """Permit unrelated labels only when league/time guards agree and no squad marker differs."""
    tokens = set(_canon_tokens(left)) | set(_canon_tokens(right))
    return bool(left and right) and not (tokens & _DISTINCT_SQUAD)


def _same_match_relaxed(left, right):
    """Return whether one exact side plus league/time evidence proves the same physical fixture."""
    left_start, right_start = left.get("startTime"), right.get("startTime")
    if (not (left_start and right_start)
            or abs(left_start - right_start) > _RELAXED_MERGE_MS):
        return False
    a1, b1 = left.get("teamA", ""), left.get("teamB", "")
    a2, b2 = right.get("teamA", ""), right.get("teamB", "")
    same_league = _same_league(left, right)

    def other_side_matches(first, second):
        return (_label_variant(first, second)
                or (same_league and _league_scoped_variant(first, second)))

    return ((_same_team(a1, a2) and other_side_matches(b1, b2))
            or (_same_team(b1, b2) and other_side_matches(a1, a2))
            or (_same_team(a1, b2) and other_side_matches(b1, a2))
            or (_same_team(b1, a2) and other_side_matches(a1, b2)))


def _cluster(rows):
    """Union rows for the same title, physical pairing, and time into one match."""
    parent = list(range(len(rows)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    by_title = {}
    for index, row in enumerate(rows):
        by_title.setdefault(row.get("title"), []).append(index)
    for indexes in by_title.values():
        for left_offset in range(len(indexes)):
            for right_offset in range(left_offset + 1, len(indexes)):
                left_index, right_index = indexes[left_offset], indexes[right_offset]
                left, right = rows[left_index], rows[right_index]
                left_start, right_start = left.get("startTime"), right.get("startTime")
                same_ps_id = bool(left.get("psId") and left.get("psId") == right.get("psId"))
                if (not same_ps_id and left_start and right_start
                        and abs(left_start - right_start) > 8 * 3600 * 1000):
                    continue
                if (same_ps_id
                        or _same_pair(left.get("teamA", ""), left.get("teamB", ""),
                                      right.get("teamA", ""), right.get("teamB", ""))
                        or _same_match_relaxed(left, right)):
                    left_parent, right_parent = find(left_index), find(right_index)
                    if left_parent != right_parent:
                        parent[right_parent] = left_parent

    groups = {}
    for index in range(len(rows)):
        groups.setdefault(find(index), []).append(index)

    merged = []
    for indexes in groups.values():
        group = sorted((rows[index] for index in indexes),
                       key=lambda row: _ORIGIN_PRIO.get(row.get("_origin"), 9))
        base = dict(group[0])
        if base.get("_origin") == "bovada":
            ps_twin = next((row for row in group[1:]
                            if row.get("_origin") == "pandascore"), None)
            if ps_twin and ps_twin.get("teamA") and ps_twin.get("teamB"):
                if (_same_team(base.get("teamA", ""), ps_twin["teamA"])
                        and _same_team(base.get("teamB", ""), ps_twin["teamB"])):
                    base["teamA"], base["teamB"] = ps_twin["teamA"], ps_twin["teamB"]
                elif (_same_team(base.get("teamA", ""), ps_twin["teamB"])
                      and _same_team(base.get("teamB", ""), ps_twin["teamA"])):
                    base["teamA"], base["teamB"] = ps_twin["teamB"], ps_twin["teamA"]

        for other in group[1:]:
            for field in ("favorite", "model", "logoA", "logoB", "startTime", "endTime", "league", "source"):
                if not base.get(field) and other.get(field):
                    base[field] = other[field]
            better_result = _has_result(other) and not _has_result(base)
            if other.get("finishedAt") and (not base.get("finishedAt") or better_result):
                base["finishedAt"] = other["finishedAt"]
                base["finished"] = True
                direct = (_same_team(base.get("teamA", ""), other.get("teamA", ""))
                          or _same_team(base.get("teamB", ""), other.get("teamB", "")))
                crossed = (_same_team(base.get("teamA", ""), other.get("teamB", ""))
                           or _same_team(base.get("teamB", ""), other.get("teamA", "")))
                flipped = crossed and not direct
                if better_result:
                    base["resultUnknown"] = False
                elif other.get("resultUnknown"):
                    base["resultUnknown"] = True
                winner = other.get("winner")
                if winner in ("a", "b"):
                    base["winner"] = (("b" if winner == "a" else "a")
                                      if flipped else winner)
                score = other.get("score")
                if score:
                    base["score"] = ({"a": score.get("b"), "b": score.get("a")}
                                     if flipped else score)
            if other.get("_bov_live"):
                base["_bov_live"] = True
            if other.get("pinned"):
                base.setdefault("pinned", True)
        merged.append(base)
    return merged


# State priority for choosing which twin survives a display-dupe collapse: a settled result outranks
# a live one, live outranks scheduled, and ended_unknown (over, no result) is the least informative.
_DUPE_STATE_RANK = {S_FINISHED: 0, S_LIVE: 1, S_SCHEDULED: 2, S_ENDED_UNKNOWN: 3}


def _suppress_display_dupes(matches):
    """Final safety net (Class A): collapse two board rows that are the SAME physical fixture but
    reached the assembled board as separate rows because they differ only in team-name CASING /
    SPACING / PUNCTUATION at the same start time — e.g. 'PARIVISION' vs 'Parivision', 'The Boys' vs
    'TheBoys'. `_cluster` already unions on identity + time; this catches the residue that slips past
    it (a source re-spells a team AFTER clustering, or a twin arrives from a different assembly path).

    STRICT on purpose, so it can never eat a real rematch or two genuinely different teams:
    - keys on `_strip_name` (case/space/punct/accent-insensitive ONLY — NOT the generic-word/alias
      collapse of `_canon_team`), so BOTH sides must be the same spelling modulo formatting. A name
      VARIANT like '9z' vs '9Z Globant' has an extra token and stays SEPARATE (that's the deliberate
      Class B case, left to the monitor).
    - requires both start times within `_START_SLACK_MS` (15 min). Rematches are hours/days apart;
      same-fixture start-time jitter across sources is a couple minutes — so the window is safe.
    The surviving twin is the most informative one (has-result > live > scheduled, then origin
    priority). Its `matchKey`/identity is untouched, so picks + crowd continuity are preserved."""
    def sig(match):
        return (match.get("title"),
                frozenset((_strip_name(match.get("teamA")), _strip_name(match.get("teamB")))))

    groups = {}
    for match in matches:
        groups.setdefault(sig(match), []).append(match)

    kept = []
    for members in groups.values():
        if len(members) == 1:
            kept.append(members[0])
            continue
        # Bucket the same-signature rows into physical fixtures by start-time proximity, so a genuine
        # rematch (far-apart start times, same two teams) survives as separate rows.
        remaining = list(members)
        while remaining:
            head = remaining.pop(0)
            fixture, rest = [head], []
            for match in remaining:
                head_start, match_start = head.get("startTime"), match.get("startTime")
                if head_start and match_start and abs(head_start - match_start) <= _START_SLACK_MS:
                    fixture.append(match)
                else:
                    rest.append(match)
            remaining = rest
            fixture.sort(key=lambda match: (
                0 if _has_result(match) else 1,
                _DUPE_STATE_RANK.get(match.get("state"), 9),
                _ORIGIN_PRIO.get(match.get("_origin"), 9),
            ))
            kept.append(fixture[0])
    return kept


def _grid_live_fresh(grid, now_ms, past):
    """Return whether a started GRID series is still updating and therefore genuinely live."""
    if not (grid and grid.get("started") and not grid.get("finished")):
        return False
    updated_at = grid.get("updatedAtMs")
    if updated_at is not None:
        return now_ms - updated_at < _LIVE_FRESH_MS
    return not past


def _derive_state(row, evidence, now_ms):
    """Derive the one match state from fresh source evidence and persisted result state."""
    grid, pandascore, frag = (evidence.get("grid"), evidence.get("ps"),
                             evidence.get("frag"))
    start_time = row.get("startTime")
    past = start_time is not None and start_time < now_ms - _START_SLACK_MS
    too_old_to_live = (start_time is not None and now_ms - start_time > _MAX_LIVE_MS)

    grid_live = _grid_live_fresh(grid, now_ms, past)
    ps_live = bool(pandascore and pandascore.get("live"))
    frag_live = frag is not None
    bovada_live = bool(
        row.get("_bov_live") and pandascore is None
        and (start_time is None or now_ms - start_time <= _BOV_LIVE_MAX_MS))
    live_evidence = (grid_live or ps_live or frag_live or bovada_live) and not too_old_to_live

    fresh_finish = bool((grid and grid.get("finished"))
                        or (pandascore and pandascore.get("finished")))
    fresh_kalshi = bool(evidence.get("kalshi")) and not live_evidence
    if fresh_finish or fresh_kalshi:
        return S_FINISHED
    if row.get("finishedAt") is not None:
        return (S_ENDED_UNKNOWN
                if row.get("resultUnknown") or not _has_result(row)
                else S_FINISHED)
    if live_evidence:
        return S_LIVE
    if not start_time or start_time > now_ms - _START_SLACK_MS:
        return S_SCHEDULED
    if (pandascore and not pandascore.get("live") and not pandascore.get("finished")
            and now_ms - start_time < _DELAYED_CAP_MS):
        return S_SCHEDULED
    return S_ENDED_UNKNOWN
