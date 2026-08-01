"""Validated RotoWire NFL news feed reader and canonical-player resolver.

The feed is a rolling source snapshot, not canonical identity.  RotoWire's
native player ID is retained, and an existing ``player_external_ids`` mapping
wins when available.  Until that crosswalk is published, name matching is only
candidate discovery: team and position must independently identify exactly one
NFL player or the item fails closed.
"""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from html.parser import HTMLParser
import json
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
SLEEPER_NFL_PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"
ROTOWIRE_PLAYER_URL = "https://www.rotowire.com/football/player.php?id={source_player_id}"
ROTOWIRE_SOURCE = "rotowire"
ROTOWIRE_LABEL = "RotoWire"
FEED_TTL_SECONDS = 600
CROSSWALK_TTL_SECONDS = 86400
PLAYER_PAGE_TTL_SECONDS = 600
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

_CROSSWALK_CACHE = {
    "crosswalk": None,
    "fetched_at": None,
    "status": "unavailable",
    "message": "Fantasy news identity data is temporarily unavailable.",
    "next_refresh_at": 0.0,
}
_CROSSWALK_CACHE_LOCK = threading.Lock()

_PLAYER_PAGE_CACHE = {}
_PLAYER_PAGE_CACHE_LOCK = threading.Lock()


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
    with _CROSSWALK_CACHE_LOCK:
        _CROSSWALK_CACHE.update(
            {
                "crosswalk": None,
                "fetched_at": None,
                "status": "unavailable",
                "message": "Fantasy news identity data is temporarily unavailable.",
                "next_refresh_at": 0.0,
            }
        )
    with _PLAYER_PAGE_CACHE_LOCK:
        _PLAYER_PAGE_CACHE.clear()


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


def parse_sleeper_crosswalk(raw):
    """Build a RotoWire crosswalk from Sleeper's public NFL identity file."""
    try:
        players = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise NewsFeedError("invalid Sleeper player data") from exc
    if not isinstance(players, dict) or len(players) < 1000:
        raise NewsFeedError("partial Sleeper player data")

    by_espn = {}
    by_gsis = {}
    by_name_position = {}
    mapped = 0
    for player in players.values():
        if not isinstance(player, dict):
            continue
        source_player_id = str(player.get("rotowire_id") or "").strip()
        if not source_player_id.isdigit():
            continue
        mapped += 1
        for key, target in (("espn_id", by_espn), ("gsis_id", by_gsis)):
            source_id = str(player.get(key) or "").strip()
            if source_id:
                target.setdefault(source_id, set()).add(source_player_id)
        name = normalize_person_name(player.get("full_name"))
        position = normalize_position(player.get("position"))
        if name and position:
            by_name_position.setdefault((name, position), set()).add(source_player_id)

    if mapped < 1000:
        raise NewsFeedError("partial Sleeper RotoWire crosswalk")
    return {
        "by_espn": by_espn,
        "by_gsis": by_gsis,
        "by_name_position": by_name_position,
        "mapped_players": mapped,
    }


def load_sleeper_crosswalk(now=None, opener=None):
    """Return a validated fresh/stale RotoWire identity crosswalk."""
    monotonic_now = time.monotonic() if now is None else float(now)
    fetch = opener or urllib.request.urlopen
    with _CROSSWALK_CACHE_LOCK:
        cached = _CROSSWALK_CACHE["crosswalk"]
        if monotonic_now < _CROSSWALK_CACHE["next_refresh_at"]:
            return {
                "status": _CROSSWALK_CACHE["status"],
                "crosswalk": cached,
                "fetched_at": _CROSSWALK_CACHE["fetched_at"],
                "message": _CROSSWALK_CACHE["message"],
            }
        try:
            request = urllib.request.Request(
                SLEEPER_NFL_PLAYERS_URL,
                headers={"Accept": "application/json", "User-Agent": "LegendaryPicks/0.7"},
            )
            with fetch(request, timeout=30) as response:
                crosswalk = parse_sleeper_crosswalk(response.read())
            fetched_at = datetime.now().astimezone().isoformat()
            _CROSSWALK_CACHE.update(
                {
                    "crosswalk": crosswalk,
                    "fetched_at": fetched_at,
                    "status": "ready",
                    "message": None,
                    "next_refresh_at": monotonic_now + CROSSWALK_TTL_SECONDS,
                }
            )
            return {
                "status": "ready",
                "crosswalk": crosswalk,
                "fetched_at": fetched_at,
                "message": None,
            }
        except Exception as exc:
            LOGGER.warning("Sleeper NFL identity refresh failed: %s", exc)
            if cached is not None:
                message = "Latest fantasy-news identity refresh is delayed."
                _CROSSWALK_CACHE.update(
                    {
                        "status": "stale",
                        "message": message,
                        "next_refresh_at": monotonic_now + 60,
                    }
                )
                return {
                    "status": "stale",
                    "crosswalk": cached,
                    "fetched_at": _CROSSWALK_CACHE["fetched_at"],
                    "message": message,
                }
            message = "Fantasy news identity data is temporarily unavailable."
            _CROSSWALK_CACHE.update(
                {
                    "status": "unavailable",
                    "message": message,
                    "next_refresh_at": monotonic_now + 60,
                }
            )
            return {
                "status": "unavailable",
                "crosswalk": None,
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


def resolve_rotowire_id(connection, player, crosswalk_result=None):
    """Resolve one canonical NFL player to one RotoWire ID.

    A persisted source mapping wins. Otherwise Sleeper's published ESPN/GSIS
    crosswalk is stable evidence; unique name+position is only the final
    fallback and never overrides conflicting native IDs.
    """
    if _table_exists(connection, "player_external_ids"):
        rows = connection.execute(
            """SELECT source_id FROM player_external_ids
               WHERE player_id=? AND source=?""",
            (player["id"], ROTOWIRE_SOURCE),
        ).fetchall()
        source_ids = {str(row["source_id"]).strip() for row in rows if row["source_id"]}
        if len(source_ids) == 1:
            return {"source_player_id": source_ids.pop(), "method": "persisted_source_id"}
        if len(source_ids) > 1:
            return {"source_player_id": None, "method": "ambiguous_persisted_source_id"}

    result = crosswalk_result or load_sleeper_crosswalk()
    crosswalk = result.get("crosswalk") if result else None
    if not crosswalk:
        return {"source_player_id": None, "method": "crosswalk_unavailable"}

    keys = set(player.keys()) if hasattr(player, "keys") else set(player)
    native_matches = []
    for player_key, index_key in (("espn_id", "by_espn"), ("nfl_gsis_id", "by_gsis")):
        value = str(player[player_key] or "").strip() if player_key in keys else ""
        matches = set(crosswalk[index_key].get(value, set())) if value else set()
        if matches:
            native_matches.append(matches)
    if native_matches:
        combined = set().union(*native_matches)
        if len(combined) == 1 and all(matches == combined for matches in native_matches):
            return {"source_player_id": combined.pop(), "method": "sleeper_native_id"}
        return {"source_player_id": None, "method": "conflicting_sleeper_native_id"}

    name_key = (
        normalize_person_name(player["name"]),
        normalize_position(player["position"] if "position" in keys else ""),
    )
    candidates = set(crosswalk["by_name_position"].get(name_key, set()))
    if len(candidates) == 1:
        return {"source_player_id": candidates.pop(), "method": "unique_name_position"}
    return {
        "source_player_id": None,
        "method": "ambiguous_name_position" if candidates else "unresolved_name_position",
    }


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


class _RotoWirePlayerNewsParser(HTMLParser):
    """Extract the public player-news cards from one RotoWire profile page."""

    _FIELDS = {
        "news-update__headline": "headline",
        "news-update__timestamp": "published_label",
        "news-update__news": "notes",
        "news-update__analysis": "analysis",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items = []
        self.current = None
        self.div_depth = 0
        self.field = None
        self.field_depth = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "div":
            if self.current is None and "news-update" in classes:
                self.current = {
                    "headline": [],
                    "published_label": [],
                    "notes": [],
                    "analysis": [],
                    "analysis_locked": False,
                }
                self.div_depth = 1
                return
            if self.current is not None:
                self.div_depth += 1
                for class_name, field in self._FIELDS.items():
                    if class_name in classes:
                        self.field = field
                        self.field_depth = self.div_depth
                        break
        elif self.current is not None and tag == "a" and self.field == "analysis":
            if str(attributes.get("href") or "").startswith("/subscribe"):
                self.current["analysis_locked"] = True
        elif self.current is not None and tag == "br" and self.field:
            self.current[self.field].append(" ")

    def handle_endtag(self, tag):
        if tag != "div" or self.current is None:
            return
        if self.field and self.div_depth == self.field_depth:
            self.field = None
            self.field_depth = 0
        self.div_depth -= 1
        if self.div_depth == 0:
            self.items.append(self.current)
            self.current = None

    def handle_data(self, data):
        if self.current is not None and self.field:
            self.current[self.field].append(data)


def _collapse_text(parts):
    return " ".join("".join(parts).split())


def _page_article_id(source_player_id, published, headline):
    digest = sha256(f"{source_player_id}|{published}|{headline}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def parse_player_news_page(raw, source_player_id):
    """Parse up to 25 public history cards from a RotoWire player page."""
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    history_marker = text.find('id="news"')
    top_marker = text.find("is-top-news-update")
    if history_marker < 0 and top_marker < 0:
        if "p-card" in text and str(source_player_id) in text:
            return []
        raise NewsFeedError("invalid RotoWire player page")
    starts = [position for position in (top_marker, history_marker) if position >= 0]
    marker = min(starts)
    end = text.find('id="rumors"', marker)
    fragment = text[marker : end if end >= 0 else len(text)]
    parser = _RotoWirePlayerNewsParser()
    parser.feed(fragment)

    items = []
    for parsed in parser.items:
        headline = _collapse_text(parsed["headline"])
        notes = _collapse_text(parsed["notes"])
        published_label = _collapse_text(parsed["published_label"])
        if not headline or not notes or not published_label:
            continue
        try:
            published = datetime.strptime(published_label, "%B %d, %Y").date().isoformat()
        except ValueError:
            continue
        analysis = "" if parsed["analysis_locked"] else _collapse_text(parsed["analysis"])
        if analysis.upper().startswith("ANALYSIS "):
            analysis = analysis[9:].strip()
        items.append(
            {
                "id": _page_article_id(source_player_id, published, headline),
                "source_player_id": str(source_player_id),
                "headline": headline,
                "notes": notes,
                "analysis": analysis,
                "injury_status": "",
                "injury_type": "",
                "injury_location": "",
                "return_date": "",
                "published": published,
                "link": ROTOWIRE_PLAYER_URL.format(source_player_id=source_player_id),
            }
        )
    return items


def load_player_news_page(source_player_id, now=None, opener=None):
    """Return one player's public RotoWire history with a small per-ID cache."""
    source_player_id = str(source_player_id or "").strip()
    if not source_player_id.isdigit():
        return {
            "status": "unavailable",
            "items": [],
            "fetched_at": None,
            "message": "Fantasy news identity could not be verified for this player.",
        }
    monotonic_now = time.monotonic() if now is None else float(now)
    with _PLAYER_PAGE_CACHE_LOCK:
        cached = _PLAYER_PAGE_CACHE.get(source_player_id)
        if cached and monotonic_now < cached["next_refresh_at"]:
            return {key: cached[key] for key in ("status", "items", "fetched_at", "message")}

    fetch = opener or urllib.request.urlopen
    try:
        request = urllib.request.Request(
            ROTOWIRE_PLAYER_URL.format(source_player_id=source_player_id),
            headers={"Accept": "text/html", "User-Agent": "LegendaryPicks/0.7"},
        )
        with fetch(request, timeout=12) as response:
            items = parse_player_news_page(response.read(), source_player_id)
        fetched_at = datetime.now().astimezone().isoformat()
        result = {
            "status": "ready",
            "items": items,
            "fetched_at": fetched_at,
            "message": None,
            "next_refresh_at": monotonic_now + PLAYER_PAGE_TTL_SECONDS,
        }
    except Exception as exc:
        LOGGER.warning("RotoWire player news refresh failed for %s: %s", source_player_id, exc)
        if cached is not None:
            result = {
                **cached,
                "status": "stale",
                "message": "Latest fantasy news refresh is delayed.",
                "next_refresh_at": monotonic_now + 60,
            }
        else:
            result = {
                "status": "unavailable",
                "items": [],
                "fetched_at": None,
                "message": "Fantasy news is temporarily unavailable.",
                "next_refresh_at": monotonic_now + 60,
            }
    with _PLAYER_PAGE_CACHE_LOCK:
        _PLAYER_PAGE_CACHE[source_player_id] = result
    return {key: result[key] for key in ("status", "items", "fetched_at", "message")}


def merge_player_news(source_player_id, feed, history, limit):
    """Merge full current-feed fields with broader player-page history."""
    candidates = [
        item for item in feed.get("items", [])
        if str(item.get("source_player_id")) == str(source_player_id)
    ] + list(history.get("items", []))
    articles = []
    seen = set()
    for item in candidates:
        published_day = str(item.get("published") or "")[:10]
        key = (normalize_person_name(item.get("headline")), published_day)
        if key in seen:
            continue
        seen.add(key)
        articles.append(item)

    def sort_key(item):
        value = str(item.get("published") or "")
        try:
            return _parse_datetime(value).timestamp()
        except NewsFeedError:
            try:
                return datetime.strptime(value[:10], "%Y-%m-%d").timestamp()
            except ValueError:
                return 0

    articles.sort(key=sort_key, reverse=True)
    return articles[:limit]
