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
    url = f"{BOVADA}/{sport}/{league}"
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode())
    events = []
    for group in data:
        for ev in group.get("events", []):
            events.append(ev)
    return events

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
