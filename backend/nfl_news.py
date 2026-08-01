"""Validated RotoWire NFL news feed reader and canonical-player resolver.

The feed is a rolling source snapshot, not canonical identity.  RotoWire's
native player ID is retained, and an existing ``player_external_ids`` mapping
wins when available.  Until that crosswalk is published, name matching is only
candidate discovery: team and position must independently identify exactly one
NFL player or the item fails closed.
"""

from __future__ import annotations

from datetime import datetime
import logging
import re
import threading
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET


LOGGER = logging.getLogger(__name__)

ROTOWIRE_NFL_NEWS_URL = (
    "https://rotowire-secrets-ebgmaeh8ecc4huhf.canadaeast-01.azurewebsites.net"
    "/api/proxy?feed=NFLNews"
)
ROTOWIRE_SOURCE = "rotowire"
ROTOWIRE_LABEL = "RotoWire"
FEED_TTL_SECONDS = 600
MIN_VALID_UPDATES = 20

_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})
_TEAM_ALIASES = {
    "JAC": "JAX",
    "LA": "LAR",
    "WAS": "WSH",
}
_POSITION_ALIASES = {
    "K": "PK",
    "G": "OG",
}

_CACHE = {
    "items": None,
    "feed_date": None,
    "fetched_at": None,
    "status": "unavailable",
    "message": "Fantasy news is temporarily unavailable.",
    "next_refresh_at": 0.0,
}
_CACHE_LOCK = threading.Lock()


class NewsFeedError(ValueError):
    """Raised when the upstream response cannot prove a complete usable feed."""


def _text(element):
    return (element.text or "").strip() if element is not None else ""


def _required_text(update, path, label):
    value = _text(update.find(path))
    if not value:
        raise NewsFeedError(f"missing {label}")
    return value


def _parse_datetime(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise NewsFeedError("invalid publication timestamp") from exc


def parse_news_feed(raw, previous_count=None):
    """Parse and validate one complete XML snapshot, newest first."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise NewsFeedError("invalid XML") from exc

    if _text(root.find("League")).upper() != "NFL":
        raise NewsFeedError("wrong league")

    feed_date = _required_text(root, "Date", "feed date")
    updates = root.findall(".//Update")
    minimum = MIN_VALID_UPDATES
    if previous_count:
        minimum = max(minimum, int(previous_count * 0.8))
    if len(updates) < minimum:
        raise NewsFeedError(
            f"partial feed: received {len(updates)} updates; need at least {minimum}"
        )

    items = []
    seen_update_ids = set()
    for update in updates:
        update_id = (update.get("Id") or "").strip()
        if not update_id or not update_id.isdigit():
            raise NewsFeedError("missing or invalid update ID")
        if update_id in seen_update_ids:
            raise NewsFeedError("duplicate update ID")
        seen_update_ids.add(update_id)

        player = update.find("Player")
        source_player_id = (player.get("Id") or "").strip() if player is not None else ""
        if not source_player_id or not source_player_id.isdigit():
            raise NewsFeedError("missing or invalid player ID")

        team = update.find("Team")
        injury = update.find("Injury")
        published = _required_text(update, "DateTime", "publication timestamp")
        published_at = _parse_datetime(published)
        link = _required_text(update, ".//Player/Link", "player link")
        if not link.startswith(("https://", "http://")):
            raise NewsFeedError("invalid player link")

        items.append(
            {
                "id": int(update_id),
                "source_player_id": source_player_id,
                "first_name": _required_text(update, ".//Player/FirstName", "first name"),
                "last_name": _required_text(update, ".//Player/LastName", "last name"),
                "position": _required_text(update, ".//Player/Position", "position"),
                "team": (team.get("Code") or "").strip() if team is not None else "",
                "headline": _required_text(update, "Headline", "headline"),
                "notes": _required_text(update, "Notes", "notes"),
                "analysis": _required_text(update, "Analysis", "analysis"),
                "injury_status": (injury.get("Status") or "").strip() if injury is not None else "",
                "injury_type": (injury.get("Type") or "").strip() if injury is not None else "",
                "injury_location": (injury.get("Location") or "").strip() if injury is not None else "",
                "return_date": (injury.get("ReturnDate") or "").strip() if injury is not None else "",
                "published": published,
                "_published_at": published_at,
                "link": link,
            }
        )

    items.sort(key=lambda item: item["_published_at"], reverse=True)
    for item in items:
        item.pop("_published_at", None)
    return {"feed_date": feed_date, "items": items}


def reset_news_cache():
    """Clear the process cache. Used by focused tests and reload-safe diagnostics."""
    with _CACHE_LOCK:
        _CACHE.update(
            {
                "items": None,
                "feed_date": None,
                "fetched_at": None,
                "status": "unavailable",
                "message": "Fantasy news is temporarily unavailable.",
                "next_refresh_at": 0.0,
            }
        )


def load_news_feed(now=None, opener=None):
    """Return a validated fresh/stale/unavailable feed snapshot."""
    monotonic_now = time.monotonic() if now is None else float(now)
    fetch = opener or urllib.request.urlopen

    with _CACHE_LOCK:
        cached_items = _CACHE["items"]
        if monotonic_now < _CACHE["next_refresh_at"]:
            return {
                "status": _CACHE["status"],
                "items": cached_items or [],
                "feed_date": _CACHE["feed_date"],
                "fetched_at": _CACHE["fetched_at"],
                "message": _CACHE["message"],
            }

        try:
            request = urllib.request.Request(
                ROTOWIRE_NFL_NEWS_URL,
                headers={"Accept": "application/xml", "User-Agent": "LegendaryPicks/0.7"},
            )
            with fetch(request, timeout=10) as response:
                raw = response.read()
            parsed = parse_news_feed(
                raw,
                previous_count=len(cached_items) if cached_items is not None else None,
            )
            fetched_at = datetime.now().astimezone().isoformat()
            _CACHE.update(
                {
                    "items": parsed["items"],
                    "feed_date": parsed["feed_date"],
                    "fetched_at": fetched_at,
                    "status": "ready",
                    "message": None,
                    "next_refresh_at": monotonic_now + FEED_TTL_SECONDS,
                }
            )
            return {
                "status": "ready",
                "items": parsed["items"],
                "feed_date": parsed["feed_date"],
                "fetched_at": fetched_at,
                "message": None,
            }
        except Exception as exc:  # preserve the last validated snapshot only
            LOGGER.warning("RotoWire NFL news refresh failed: %s", exc)
            if cached_items is not None:
                message = "Latest fantasy news refresh is delayed."
                _CACHE.update(
                    {
                        "status": "stale",
                        "message": message,
                        "next_refresh_at": monotonic_now + 60,
                    }
                )
                return {
                    "status": "stale",
                    "items": cached_items,
                    "feed_date": _CACHE["feed_date"],
                    "fetched_at": _CACHE["fetched_at"],
                    "message": message,
                }
            message = "Fantasy news is temporarily unavailable."
            _CACHE.update(
                {
                    "status": "unavailable",
                    "message": message,
                    "next_refresh_at": monotonic_now + 60,
                }
            )
            return {
                "status": "unavailable",
                "items": [],
                "feed_date": None,
                "fetched_at": None,
                "message": message,
            }


def normalize_person_name(value):
    """Normalize display names for candidate discovery, including suffixes."""
    folded = unicodedata.normalize("NFKD", str(value or ""))
    ascii_name = "".join(char for char in folded if not unicodedata.combining(char))
    tokens = re.findall(r"[a-z0-9]+", ascii_name.lower())
    while tokens and tokens[-1] in _SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def normalize_team(value):
    team = str(value or "").strip().upper()
    return _TEAM_ALIASES.get(team, team)


def normalize_position(value):
    position = str(value or "").strip().upper()
    return _POSITION_ALIASES.get(position, position)


def _table_exists(connection, name):
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def resolve_source_player(connection, item):
    """Resolve one feed item to exactly one canonical ``players.id``.

    A persisted RotoWire crosswalk wins.  Without one, the unique normalized
    name candidate must also agree on position and, when published, team.
    """
    if _table_exists(connection, "player_external_ids"):
        rows = connection.execute(
            """SELECT e.player_id FROM player_external_ids e
               JOIN players p ON p.id=e.player_id
               WHERE e.source=? AND e.source_id=? AND p.league='nfl'""",
            (ROTOWIRE_SOURCE, item["source_player_id"]),
        ).fetchall()
        if len(rows) == 1:
            return {"player_id": int(rows[0]["player_id"]), "method": "source_id"}
        if len(rows) > 1:
            return {"player_id": None, "method": "ambiguous_source_id"}

    source_name = normalize_person_name(
        f"{item['first_name']} {item['last_name']}"
    )
    base_name = f"{item['first_name']} {item['last_name']}".strip()
    rows = connection.execute(
        """SELECT id, name, team, position FROM players
           WHERE league='nfl'
             AND (name=? COLLATE NOCASE OR name LIKE ? COLLATE NOCASE)""",
        (base_name, f"{base_name} %"),
    ).fetchall()
    candidates = []
    source_team = normalize_team(item.get("team"))
    source_position = normalize_position(item.get("position"))
    for row in rows:
        if normalize_person_name(row["name"]) != source_name:
            continue
        if normalize_position(row["position"]) != source_position:
            continue
        if source_team and normalize_team(row["team"]) != source_team:
            continue
        candidates.append(int(row["id"]))

    if len(candidates) == 1:
        return {"player_id": candidates[0], "method": "name_team_position"}
    return {
        "player_id": None,
        "method": "ambiguous_candidate" if candidates else "unresolved_candidate",
    }


def source_name_matches_player(item, player_name):
    return normalize_person_name(
        f"{item['first_name']} {item['last_name']}"
    ) == normalize_person_name(player_name)
