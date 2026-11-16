"""client — Bovada scraper client layer."""
import re
import json
import os
import sys
import collections
import datetime as dt
import unicodedata
import urllib.request

import json
import os
import urllib.request
from .config import BOVADA, HDR  # noqa: E402
from .parsers import _parse_mls_props, _parse_standard_props, _parse_tennis_props, _parse_ufc_props, _parse_wc_props  # noqa: E402

def fetch_events(sport: str, league: str) -> list:
    # The bare path silently returns a TRUNCATED coupon, and any query parameter
    # at all defeats it. Measured 2026-09-05 within the same minute:
    #
    #   soccer/.../mls   bare 0 events    lang=en 15 events
    #   baseball/mlb     bare 15 events   (with a param, 27)
    #
    # So MLS read as "Bovada does not carry this league" while it carried the
    # whole 13-fixture slate, and MLB was ingesting about half its fixtures.
    # Nothing ever raised, because a short list is a perfectly plausible list:
    # an out-of-season sport and a truncated response look identical.
    #
    # `lang=en` and NOT `marketFilterId=def`. The latter looks like the obvious
    # choice and is a trap -- it is Bovada's DEFAULT market filter and returns
    # Game Lines ONLY, stripping every player prop:
    #
    #   marketFilterId=def   14 events   {Game Lines}
    #   lang=en              15 events   {Game Lines, Goalscorer, Assists,
    #                                     Cards, Corners, Goal Props, ...}
    #
    # A locale parameter imposes no market filter, which is the whole point:
    # we want the coupon Bovada would show a browser, not a filtered view.
    url = f"{BOVADA}/{sport}/{league}?lang=en"
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode())
    events = []
    for group in data:
        for ev in group.get("events", []):
            events.append(ev)
    return events

def tennis_tour_events(tour: str, data: list) -> list:
    """Events of one tour (`atp` or `wta`) from the bare `tennis` coupon.

    Bovada files tennis by tour and tournament: /tennis/atp/shanghai/... Matching the tour prefix
    keeps the lane alive across tournaments, unlike a hard-coded tournament path that goes stale
    when the event ends.
    """
    prefix = "/tennis/%s/" % tour
    out = []
    for group in data:
        for ev in group.get("events", []):
            if str(ev.get("link") or "").startswith(prefix):
                out.append(ev)
    return out


def fetch_tennis_tour(tour: str) -> list:
    """Read-only GET of the bare tennis coupon, filtered to one tour."""
    url = f"{BOVADA}/tennis?lang=en"
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode())
    return tennis_tour_events(tour, data)


def parse_player_props(event: dict, league: str) -> list:
    """Extract all player props from a single Bovada event."""
    if league in ("mls", "lcup"):
        # One soccer parser for both. It already decides the competition itself from
        # the event's two dominant club codes (see _MLS_CLUB_CODES): a fixture with a
        # non-MLS club files under `lcup`. So routing `lcup` here does not need a
        # second parser, and must not get one -- a copy would be a second ruler for
        # the same question.
        return _parse_mls_props(event)
    if league == "wc":
        return _parse_wc_props(event)
    if league == "ufc":
        return _parse_ufc_props(event)
    if league in ("atp", "wta"):
        return _parse_tennis_props(event, league)
    return _parse_standard_props(event, league)
