"""Bovada coupon retrieval, source-native retention, and prop parsing."""
from __future__ import annotations

import json
import os
import sqlite3
import urllib.request

from .config import BOVADA, HDR  # noqa: E402
from .parsers import _parse_mls_props, _parse_standard_props, _parse_tennis_props, _parse_ufc_props, _parse_wc_props  # noqa: E402
from publisher_capture import capture_payload  # noqa: E402


def coupon_url(sport: str, league: str) -> str:
    """Return the exact publisher endpoint used for a coupon request."""
    return f"{BOVADA}/{sport}/{league}"


def fetch_coupon(sport: str, league: str) -> tuple[str, object]:
    """Fetch the complete publisher body before any event flattening occurs."""
    url = coupon_url(sport, league)
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode())
    return url, data


def events_from_coupon(coupon: object) -> list:
    """Flatten a retained Bovada coupon into its event product view."""
    if not isinstance(coupon, list):
        raise ValueError("Bovada coupon must be a JSON array")
    events = []
    for group in coupon:
        if not isinstance(group, dict):
            continue
        for ev in group.get("events", []):
            if isinstance(ev, dict):
                events.append(ev)
    return events


def fetch_events(sport: str, league: str) -> list:
    """Compatibility event-only view for scoreboards and existing callers."""
    _endpoint, coupon = fetch_coupon(sport, league)
    return events_from_coupon(coupon)


def record_coupon_capture(
    coupon: object,
    *,
    league: str,
    endpoint: str,
    db_path: str | None = None,
) -> tuple[int, bool]:
    """Durably record the untouched coupon in the explicitly selected database.

    Normalized parsing is deliberately downstream of this call.  No implicit
    database default is allowed: an operator must set ``LP_DB_PATH`` (or a test
    must pass ``db_path``) so an ad-hoc fetch can never silently target prod.
    """
    path = db_path or os.environ.get("LP_DB_PATH")
    if not path or not os.path.isabs(path) or not os.path.isfile(path):
        raise RuntimeError("Bovada capture requires an existing absolute LP_DB_PATH")
    connection = sqlite3.connect(path)
    try:
        result = capture_payload(
            connection,
            source="bovada",
            league=league,
            endpoint=endpoint,
            payload=coupon,
        )
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

def parse_player_props(event: dict, league: str) -> list:
    """Extract all player props from a single Bovada event."""
    if league == "mls":
        return _parse_mls_props(event)
    if league == "wc":
        return _parse_wc_props(event)
    if league == "ufc":
        return _parse_ufc_props(event)
    if league in ("atp", "wta"):
        return _parse_tennis_props(event, league)
    return _parse_standard_props(event, league)
