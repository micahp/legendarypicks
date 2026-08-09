#!/usr/bin/env python3
"""Gap classification: what a difference between the published set and ours is made of.

Extracted from reconcile_totals.py 2026-08-08 (monolith split). Depends on
reconcile_core for the oracle primitives. No behavior change.
"""
import os
import re
import sys
import time
from typing import Dict, List, NamedTuple, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reconcile_core import (
    CORE,
    OracleUnreachable,
    _get_json,
    _log,
    _MIN_INTERVAL,
    bulk_event_index,
    published_event_ids,
)

class Gap(NamedTuple):
    """What a difference between the published set and ours is actually made of."""
    published: int          # everything in the publisher's collection
    exhibition: int         # All-Star and friends: published, played, not a league game
    not_played: int         # postponed/canceled shells, superseded by a makeup event id
    expected: int           # published - exhibition - not_played - not_yet_played - beyond_horizon
    missing: List[str]      # published, real, played, and absent from our table
    extra: List[str]        # ours and not theirs — always a bug, in us or in the key
    not_yet_played: int = 0  # scheduled/in-progress: published, not finished, not a gap
    beyond_horizon: int = 0  # finished AFTER the last game we hold: outside the claim


def explain_gap(url: str, ours: set, horizon: Optional[str] = None) -> Gap:
    """Diff a published collection against ours and classify only the difference.

    The cost is one request per *differing* event, not per event, so a clean season
    costs three requests and a broken one costs as many as it is broken. That is what
    makes it affordable to run this on every league.

    It exists because a headline count difference is not a defect until it is
    classified. NBA 2025-26 published 1,239 regular-season events against our 1,227,
    and the 12 were three different things: 4 All-Star exhibitions (ESPN files NBA
    All-Star under season type **2**, unlike the NFL Pro Bowl under type 3 — which is
    why the exhibition type id is never assumed here and always read from the event),
    4 postponed shells whose makeups carry new event ids, and only 4 real misses.
    Reporting "12 missing" would have sent someone to fix a problem we did not have.
    """
    published = published_event_ids(url)
    diff = [e for e in published if e not in ours]
    exhibition = not_played = not_yet_played = beyond_horizon = 0
    missing: List[str] = []
    # Progress, to stderr, because a run with no output is indistinguishable from a
    # hung one. A finished season differs by a handful of events and prints nothing
    # worth reading; a MID-SEASON league differs by its whole remaining schedule --
    # MLB 2026 differs by ~750, which is 20 minutes of paced requests. The first
    # version of this printed only at the end, and a 54-minute silence is not
    # something anyone should be asked to take on faith.
    total = len(diff)
    index: Dict[str, dict] = {}
    if total > 50:
        _log(f"classifying {total} differing events")
        # Above this many, the per-event fetch is the wrong instrument. Below it, a
        # finished season pays three requests and the bulk index would cost more than
        # it saves.
        index = bulk_event_index(url)
        covered = sum(1 for e in diff if e in index)
        if index:
            _log(f"  index covers {covered}/{total} differing events; "
                 f"{total - covered} still need their own fetch "
                 f"(~{(total - covered) * _MIN_INTERVAL / 60:.0f} min at {_MIN_INTERVAL}s pacing)")
    started = time.monotonic()
    for n, event_id in enumerate(diff, 1):
        if total > 50 and n % 100 == 0:
            rate = (time.monotonic() - started) / n
            _log(f"  {n}/{total}  missing={len(missing)} "
                 f"not-yet-played={not_yet_played} past-horizon={beyond_horizon} "
                 f"eta={(total - n) * rate / 60:.0f}m")
        ev = index.get(event_id)
        if ev is None:
            try:
                ev = _get_json(f"{CORE}/{ESPN_PATH_BY_URL(url)}/events/{event_id}")
            except OracleUnreachable:
                missing.append(event_id)  # unclassifiable is not innocent
                continue
        comp = (ev.get("competitions") or [{}])[0]
        if (comp.get("type") or {}).get("abbreviation") == "ALLSTAR":
            exhibition += 1
            continue
        state = _event_state(comp)
        if state in ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_SUSPENDED"):
            not_played += 1
            continue
        # Not-yet-played: a season in progress (MLB 2026) publishes its whole
        # schedule, so the collection holds games that have not been played yet.
        # They are not missing — they have not happened. Counting them as missing
        # would report every future MLB game as a defect and demote a season that
        # is exactly as complete as it can be today. The status type carries the
        # answer: `completed` False with no terminal name means scheduled or in
        # progress, and the game we cannot have yet is not a game we lost.
        if state in ("STATUS_SCHEDULED", "STATUS_IN_PROGRESS", "STATUS_PRE"):
            not_yet_played += 1
            continue
        # Finished, absent from our table, and played AFTER the last game we hold.
        #
        # This is the difference between a gap and an edge, and getting it wrong is
        # what made a live season unofferable. `not_yet_played` above handles
        # September. It does nothing for last night: those games ARE finished, so
        # without this branch they count as missing the moment they end, the verdict
        # drops to `partial`, and the league disappears from /leagues every morning
        # until the next ingest runs — availability that tracks cron timing rather
        # than data quality.
        #
        # So the coverage row claims a WINDOW, not an instant: every published game
        # up to `horizon` is present. A game past the horizon is outside the claim,
        # not a hole in it. A game missing INSIDE the window is still a real miss and
        # still fails, which is the whole point of keeping the two apart.
        if horizon and str(ev.get("date") or "")[:10] > horizon:
            beyond_horizon += 1
            continue
        missing.append(event_id)
    return Gap(
        published=len(published),
        exhibition=exhibition,
        not_played=not_played,
        expected=len(published) - exhibition - not_played - not_yet_played - beyond_horizon,
        missing=missing,
        extra=sorted(ours - set(published)),
        not_yet_played=not_yet_played,
        beyond_horizon=beyond_horizon,
    )

def _event_state(comp: dict) -> str:
    """The competition's status name, following the `$ref` when it is not inlined."""
    status = comp.get("status") or {}
    kind = status.get("type") or {}
    if not kind and status.get("$ref"):
        try:
            kind = _get_json(status["$ref"]).get("type") or {}
        except OracleUnreachable:
            return ""
    return str(kind.get("name") or "")

def ESPN_PATH_BY_URL(url: str) -> str:  # noqa: N802 - reads as a lookup at call sites
    """Recover the league path segment from a season-scoped collection URL."""
    m = re.search(r"/v2/sports/(.+?)/seasons/", url)
    if not m:
        raise OracleUnreachable(f"cannot locate league path in {url}")
    return m.group(1)

def describe_gap(gap: Gap) -> str:
    """The one-line arithmetic, so a passing check still shows what it excluded."""
    parts = [f"{gap.published} published"]
    if gap.exhibition:
        parts.append(f"-{gap.exhibition} exhibition")
    if gap.not_played:
        parts.append(f"-{gap.not_played} not played")
    if gap.not_yet_played:
        parts.append(f"-{gap.not_yet_played} not yet played")
    if gap.beyond_horizon:
        parts.append(f"-{gap.beyond_horizon} past our horizon")
    return " ".join(parts)


def report_gap(rep: "Report", name: str, gap: Gap) -> None:
    """Name the individual events on both sides of a difference.

    A count tells you something is wrong; an event id tells you what. The four NBA
    games lost on 2026-07-14 were findable in one query once someone printed them.
    """
    for event_id in gap.missing[:10]:
        rep.note("  missing event", f"{name}: {event_id} published, played, not ours")
    for event_id in gap.extra[:10]:
        rep.note("  extra event", f"{name}: {event_id} ours, not in the published set")
