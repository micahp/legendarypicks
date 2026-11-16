#!/usr/bin/env python3
"""Publish non-ESPN ATP and WTA player identities into ``players``.

ATP identities come from TennisExplorer's paginated 2026 ranking pages, with
two reviewed player-profile supplements omitted from those pages. The player
URL slug is the publisher ID. WTA identities come from the WTA ranked players
API, which publishes its own numeric player ID and full name.

Player rows are never created from sportsbook names. A publisher identity is
matched to an existing row by its normalized full name or a previously bound
Underdog ID. Unmatched publisher identities are inserted with their publisher
ID. Unique Underdog IDs already recorded in ``unresolved_players`` are bound
only when their names resolve to one publisher identity.

The only supported database is the managed development database:
  /root/legendarypicks/backend/data/picks.dev.db

Run a read-only plan first, then explicitly apply with a new backup path:
  python ingest_tennis_players.py --dry-run
  python ingest_tennis_players.py --apply --backup /tmp/picks.dev.db.before-tennis
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Iterable


DEV_DB = Path("/root/legendarypicks/backend/data/picks.dev.db")
DB = os.environ.get("LP_DB_PATH", str(DEV_DB))
LEAGUES = ("atp", "wta")
ATP_PUBLISHER = "tennisexplorer.com"
WTA_PUBLISHER = "wtatennis.com"
# Reviewed display variants mapped to the publisher profile ID named in each
# key. Each URL identifies the canonical source profile used for review.
# ATP profiles: https://www.tennisexplorer.com/player/{publisher_id}/
# WTA profiles use the IDs and canonical slugs in the corresponding URL below.
PUBLISHER_NAME_ALIASES = {
    ("atp", "shelbayh"): ("Abdullah Shelbayh",),
    ("atp", "meligeni-rodrigues-alves"): ("Felipe Meligeni Alves",),
    ("atp", "miyoshi-3eaae"): ("Kenta (2004) Miyoshi",),
    ("atp", "fancutt"): ("Thomas Fancutt",),
    ("atp", "yunchaokete"): ("Yunchaokete Bu",),
    ("atp", "wong-d3ead"): ("Chak Lam Coleman Wong",),
    ("atp", "auger-aliassime"): ("Felix Auger-Aliassime",),
    ("atp", "wolf-e839f"): ("J.J. Wolf",),
    ("atp", "damm-4f98a"): ("Martin Damm Jr",),
    ("wta", "321157"): ("Irene Burillo Escorihuela",),
    ("wta", "326735"): ("Leylah Annie Fernandez",),
    ("wta", "330894"): ("Lucija Ciric-Bagaric",),
    ("wta", "329464"): ("Maria Camila Torres Murcia",),
    ("wta", "322638"): ("Maria Carle",),
    ("wta", "323119"): ("Miriam Bianca Bulgaru",),
    ("wta", "325725"): ("Catherine McNally",),
    ("wta", "324830"): ("En Shuo Liang",),
    ("wta", "325338"): ("Yulia Starodubtseva",),
    ("wta", "325898"): ("Maria Camila Osorio",),
}
# WTA alias evidence, in the same order as their IDs above:
# https://www.wtatennis.com/players/321157/irene-burillo
# https://www.wtatennis.com/players/326735/leylah-fernandez
# https://www.wtatennis.com/players/330894/lucija-ciric-bagaric
# https://www.wtatennis.com/players/329464/maria-torres-murcia
# https://www.wtatennis.com/players/322638/maria-lourdes-carle
# https://www.wtatennis.com/players/323119/miriam-bulgaru
# https://www.wtatennis.com/players/325725/caty-mcnally
# https://www.wtatennis.com/players/324830/en-shuo-liang
# https://www.wtatennis.com/players/325338/yuliia-starodubtseva
# https://www.wtatennis.com/players/325898/camila-osorio
# TennisExplorer profile records omitted from the current ranked page scrape.
# Nishikori's profile reports rank 436 although ATP page 9 omitted him. Truong's
# profile has 2026 lower-level results but no current rank. The slugs are
# publisher identities, not Underdog or Bovada IDs.
ATP_PROFILE_SUPPLEMENTS = (
    {
        "publisher_id": "nishikori",
        "name": "Kei Nishikori",
        "active": True,
        "profile_url": "https://www.tennisexplorer.com/player/nishikori/",
    },
    {
        "publisher_id": "truong-914c5",
        "name": "Thanh Minh Truong",
        "active": True,
        "profile_url": "https://www.tennisexplorer.com/player/truong-914c5/",
    },
)
ATP_HOST = "www.tennisexplorer.com"
WTA_HOST = "api.wtatennis.com"
ATP_PAGE_SIZE = 50
WTA_PAGE_SIZE = 100
MIN_ATP_INTERVAL = 2.0
MIN_WTA_INTERVAL = 2.0
MAX_PAGES = 100

ATP_URL = "https://www.tennisexplorer.com/ranking/atp-men/{year}/?page={page}"
WTA_URL = (
    "https://api.wtatennis.com/tennis/players/ranked"
    "?type=rankSingles&metric=singles&page={page}&pageSize={page_size}"
)


class TennisSpineError(RuntimeError):
    """A published identity population is not safe to publish."""


def normalize_name(value: str) -> str:
    """Match Underdog's reviewed-alias normalization without fuzzy matching."""
    value = unicodedata.normalize("NFKD", value or "").encode(
        "ascii", "ignore"
    ).decode("ascii")
    value = re.sub(r"\b(jr\.?|sr\.?|ii|iii|iv|v)\b", "", value.lower())
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", value)).strip()


def _slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def tennisexplorer_name(display_name: str, player_url: str) -> tuple[str, str]:
    """Convert TennisExplorer's ``Surname Given`` row to ``Given Surname``.

    The player URL starts with the surname slug. Longest matching leading
    surname spans support compound surnames such as ``Van de Zandschulp``.
    The complete URL slug, including its disambiguating suffix when present,
    is retained as the publisher identity.
    """
    words = display_name.split()
    path = urllib.parse.urlparse(player_url).path.strip("/").split("/")
    if len(path) != 2 or path[0] != "player" or not path[1]:
        raise TennisSpineError(
            f"TennisExplorer player row has an invalid identity URL: {player_url!r}"
        )
    slug = path[1]
    slug_name = _slugify(slug)
    if len(words) < 2 or not slug_name:
        raise TennisSpineError(
            f"TennisExplorer player row has an invalid identity: {display_name!r}"
        )

    for surname_words in range(len(words) - 1, 0, -1):
        surname = " ".join(words[:surname_words])
        prefix = _slugify(surname)
        if slug_name == prefix or slug_name.startswith(prefix + "-"):
            canonical_name = " ".join(words[surname_words:] + words[:surname_words])
            return canonical_name, slug

    raise TennisSpineError(
        "TennisExplorer player URL does not identify the leading surname for "
        f"{display_name!r}: {player_url!r}"
    )


class _RankingHTMLParser(HTMLParser):
    """Extract ranked player rows and page links from a TennisExplorer page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict] = []
        self.page_numbers: set[int] = set()
        self._row: dict | None = None
        self._rank_depth = 0
        self._rank_text: list[str] = []
        self._player_anchor: dict | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "tr":
            self._row = {"rank": "", "player": None, "player_url": None}
            self._rank_depth = 0
            self._rank_text = []

        if tag == "td" and self._row is not None:
            classes = set((values.get("class") or "").split())
            if "rank" in classes:
                self._rank_depth += 1

        if tag == "a":
            href = values.get("href") or ""
            query = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            for raw_page in query.get("page", []):
                if raw_page.isdigit():
                    self.page_numbers.add(int(raw_page))
            path = urllib.parse.urlparse(href).path
            if self._row is not None and re.fullmatch(r"/player/[^/]+/?", path):
                self._player_anchor = {"href": href, "text": []}

    def handle_data(self, data: str) -> None:
        if self._row is not None and self._rank_depth:
            self._rank_text.append(data)
        if self._player_anchor is not None:
            self._player_anchor["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._player_anchor is not None:
            if self._row is not None and self._row["player"] is None:
                self._row["player"] = " ".join(
                    "".join(self._player_anchor["text"]).split()
                )
                self._row["player_url"] = self._player_anchor["href"]
            self._player_anchor = None
        elif tag == "td" and self._rank_depth:
            self._rank_depth -= 1
        elif tag == "tr" and self._row is not None:
            self._row["rank"] = "".join(self._rank_text).strip()
            rank_match = re.search(r"\d+", self._row["rank"])
            if rank_match and self._row["player"] and self._row["player_url"]:
                self.rows.append({
                    "rank": int(rank_match.group()),
                    "display_name": self._row["player"],
                    "player_url": self._row["player_url"],
                })
            self._row = None
            self._rank_depth = 0
            self._rank_text = []


def parse_tennisexplorer_page(document: str, page: int) -> dict:
    parser = _RankingHTMLParser()
    parser.feed(document)
    players = []
    for row in parser.rows:
        name, publisher_id = tennisexplorer_name(
            row["display_name"], row["player_url"]
        )
        players.append({
            "publisher_id": publisher_id,
            "name": name,
            "active": True,
            "rank": row["rank"],
        })
    return {
        "players": players,
        "has_later_page": any(number > page for number in parser.page_numbers),
    }


def _http_text(url: str, timeout: int = 30) -> tuple[int, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "Chrome/131 Safari/537.36"
            ),
            "Accept": "text/html,application/json,*/*",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def _http_json(url: str, timeout: int = 30) -> tuple[int, object]:
    status, text = _http_text(url, timeout=timeout)
    if status != 200:
        return status, text
    try:
        return status, json.loads(text)
    except json.JSONDecodeError as exc:
        raise TennisSpineError(f"WTA API returned invalid JSON at {url}: {exc}") from exc


def _paced_fetch(
    fetch: Callable[[str], object], url: str, *, host: str,
    last_request: dict[str, float], interval: float,
    sleep: Callable[[float], None],
) -> object:
    elapsed = time.monotonic() - last_request.get(host, 0.0)
    if last_request.get(host) is not None and elapsed < interval:
        sleep(interval - elapsed)
    result = fetch(url)
    last_request[host] = time.monotonic()
    return result


def tennisexplorer_url(league: str, year: int, page: int) -> str:
    if league != "atp":
        raise TennisSpineError(f"TennisExplorer ATP source cannot serve {league!r}")
    return ATP_URL.format(year=year, page=page)


def _validate_population(league: str, players: list[dict], publisher: str) -> None:
    if not players:
        raise TennisSpineError(f"{league} {publisher} published 0 player identities")
    ids = [str(player.get("publisher_id") or "").strip() for player in players]
    if any(not value for value in ids):
        raise TennisSpineError(f"{league} {publisher} has a player with no publisher ID")
    if len(ids) != len(set(ids)):
        raise TennisSpineError(
            f"{league} {publisher} published {len(set(ids))} unique IDs "
            f"for {len(ids)} players"
        )
    names = [normalize_name(player.get("name") or "") for player in players]
    if any(not value for value in names):
        raise TennisSpineError(f"{league} {publisher} has a player with no usable name")
    if len(names) != len(set(names)):
        raise TennisSpineError(
            f"{league} {publisher} published {len(set(names))} unique resolver names "
            f"for {len(names)} players"
        )


def _publisher_aliases(league: str, publisher_id: str) -> tuple[str, ...]:
    return PUBLISHER_NAME_ALIASES.get((league, str(publisher_id)), ())


def _append_atp_profile_supplements(players: list[dict]) -> tuple[int, int]:
    """Add reviewed TennisExplorer profile identities missing from its ranking pages."""
    by_id = {str(player["publisher_id"]): player for player in players}
    by_name = {normalize_name(player["name"]): player for player in players}
    already_ranked = added = 0
    for supplement in ATP_PROFILE_SUPPLEMENTS:
        publisher_id = supplement["publisher_id"]
        name_key = normalize_name(supplement["name"])
        existing_id = by_id.get(publisher_id)
        if existing_id is not None:
            if normalize_name(existing_id["name"]) != name_key:
                raise TennisSpineError(
                    f"TennisExplorer profile {publisher_id} changed its published name"
                )
            already_ranked += 1
            continue
        existing_name = by_name.get(name_key)
        if existing_name is not None:
            raise TennisSpineError(
                f"TennisExplorer profile {publisher_id} duplicates publisher name "
                f"{supplement['name']!r} under ID {existing_name['publisher_id']}"
            )
        player = {
            key: supplement[key]
            for key in ("publisher_id", "name", "active")
        }
        players.append(player)
        by_id[publisher_id] = player
        by_name[name_key] = player
        added += 1
    return already_ranked, added


def fetch_atp_population(
    *, year: int, fetch_page: Callable[[str], object] | None = None,
    request_counts: collections.Counter | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict:
    """Fetch every ranked ATP page, at most one request per two seconds."""
    fetch_page = fetch_page or _http_text
    request_counts = request_counts if request_counts is not None else collections.Counter()
    last_request: dict[str, float] = {}
    players: list[dict] = []
    page_count = 0
    previous_rank = 0
    previous_advertised_next = False

    for page in range(1, MAX_PAGES + 1):
        url = tennisexplorer_url("atp", year, page)
        result = _paced_fetch(
            fetch_page, url, host=ATP_HOST, last_request=last_request,
            interval=MIN_ATP_INTERVAL, sleep=sleeper,
        )
        request_counts[ATP_HOST] += 1
        if isinstance(result, tuple):
            status, document = result
        else:
            status, document = 200, result
        if status == 404 and players:
            if previous_advertised_next:
                raise TennisSpineError(
                    f"ATP TennisExplorer advertised page {page} after "
                    f"{len(players)} identities, then returned HTTP 404"
                )
            break
        if status != 200:
            raise TennisSpineError(
                f"ATP TennisExplorer page {page} returned HTTP {status}: {url}"
            )
        parsed = parse_tennisexplorer_page(str(document), page)
        page_players = parsed["players"]
        if not page_players:
            if not players:
                raise TennisSpineError(
                    f"ATP TennisExplorer published 0 players on page 1: {url}"
                )
            raise TennisSpineError(
                f"ATP TennisExplorer page {page} was empty after {len(players)} "
                "published identities; refusing a partial roster"
            )
        if len(page_players) > ATP_PAGE_SIZE:
            raise TennisSpineError(
                f"ATP TennisExplorer page {page} returned {len(page_players)} rows, "
                f"more than the {ATP_PAGE_SIZE}-row page size"
            )
        page_ranks = [player["rank"] for player in page_players]
        if page_ranks[0] < previous_rank or page_ranks != sorted(page_ranks):
            raise TennisSpineError(
                f"ATP TennisExplorer page {page} has a non-increasing rank range"
            )
        previous_rank = page_ranks[-1]
        players.extend(page_players)
        page_count += 1
        previous_advertised_next = parsed["has_later_page"]
        if len(page_players) < ATP_PAGE_SIZE:
            if parsed["has_later_page"]:
                raise TennisSpineError(
                    f"ATP TennisExplorer page {page} returned {len(page_players)} of "
                    f"{ATP_PAGE_SIZE} rows but advertises a later page"
                )
            break
    else:
        raise TennisSpineError(
            f"ATP TennisExplorer exceeded the {MAX_PAGES}-page safety bound"
        )

    ranked_rows = len(players)
    _validate_population("atp", players, ATP_PUBLISHER)
    profile_supplements_ranked, profile_supplements_added = (
        _append_atp_profile_supplements(players)
    )
    _validate_population("atp", players, ATP_PUBLISHER)
    return {
        "players": players,
        "ranked_rows": ranked_rows,
        "profile_supplements_total": len(ATP_PROFILE_SUPPLEMENTS),
        "profile_supplements_ranked": profile_supplements_ranked,
        "profile_supplements_added": profile_supplements_added,
        "pages": page_count,
        "requests": request_counts[ATP_HOST],
        "publisher": ATP_PUBLISHER,
        "host": ATP_HOST,
    }


def _wta_player(item: object, page: int, row_no: int) -> dict:
    player = item.get("player") if isinstance(item, dict) else None
    if not isinstance(player, dict):
        raise TennisSpineError(f"WTA page {page} row {row_no} has no player object")
    publisher_id = str(player.get("id") or "").strip()
    name = player.get("fullName")
    if not publisher_id or publisher_id == "0":
        raise TennisSpineError(f"WTA page {page} row {row_no} has no WTA player ID")
    if not isinstance(name, str) or not name.strip():
        raise TennisSpineError(
            f"WTA page {page} player {publisher_id} has no full name"
        )
    return {"publisher_id": publisher_id, "name": name.strip(), "active": True}


def fetch_wta_population(
    *, fetch_json: Callable[[str], object] | None = None,
    request_counts: collections.Counter | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict:
    """Fetch the full current WTA singles ranking population, 100 per page."""
    fetch_json = fetch_json or _http_json
    request_counts = request_counts if request_counts is not None else collections.Counter()
    last_request: dict[str, float] = {}
    players: list[dict] = []
    page_count = 0

    for page in range(0, MAX_PAGES):
        url = WTA_URL.format(page=page, page_size=WTA_PAGE_SIZE)
        result = _paced_fetch(
            fetch_json, url, host=WTA_HOST, last_request=last_request,
            interval=MIN_WTA_INTERVAL, sleep=sleeper,
        )
        request_counts[WTA_HOST] += 1
        if isinstance(result, tuple):
            status, document = result
        else:
            status, document = 200, result
        if status != 200:
            raise TennisSpineError(f"WTA ranked players page {page} returned HTTP {status}")
        if not isinstance(document, list):
            raise TennisSpineError(f"WTA ranked players page {page} is not a JSON list")
        if not document:
            if not players:
                raise TennisSpineError("WTA ranked players API published 0 players")
            raise TennisSpineError(
                f"WTA ranked players page {page} was empty after {len(players)} "
                "published identities; refusing a partial roster"
            )
        if len(document) > WTA_PAGE_SIZE:
            raise TennisSpineError(
                f"WTA page {page} returned {len(document)} rows, "
                f"more than the {WTA_PAGE_SIZE}-row page size"
            )
        players.extend(
            _wta_player(item, page, row_no)
            for row_no, item in enumerate(document, start=1)
        )
        page_count += 1
        if len(document) < WTA_PAGE_SIZE:
            break
    else:
        raise TennisSpineError(
            f"WTA ranked players API exceeded the {MAX_PAGES}-page safety bound"
        )

    _validate_population("wta", players, WTA_PUBLISHER)
    return {
        "players": players,
        "pages": page_count,
        "requests": request_counts[WTA_HOST],
        "publisher": WTA_PUBLISHER,
        "host": WTA_HOST,
    }


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _player_columns(connection: sqlite3.Connection) -> set[str]:
    return {row[1] for row in connection.execute("PRAGMA table_info(players)")}


def _required_schema(connection: sqlite3.Connection) -> set[str]:
    columns = _player_columns(connection)
    required = {"id", "name", "team", "league", "espn_id", "active", "updated_at"}
    missing = sorted(required - columns)
    if missing:
        raise TennisSpineError(
            "players schema cannot hold the tennis spine; missing " + ", ".join(missing)
        )
    return columns


def _read_unresolved(connection: sqlite3.Connection) -> list[dict]:
    if not _table_exists(connection, "unresolved_players"):
        return []
    return [dict(row) for row in connection.execute(
        """SELECT source,league,raw_name,source_player_key,count
           FROM unresolved_players
           WHERE league IN ('atp','wta') AND source IN ('underdog','bovada')
           ORDER BY league,source,raw_name,source_player_key"""
    )]


def _read_source_ids(connection: sqlite3.Connection) -> dict[tuple[str, str, str], list[int]]:
    if not _table_exists(connection, "player_source_ids"):
        return {}
    result: dict[tuple[str, str, str], list[int]] = collections.defaultdict(list)
    for row in connection.execute(
        """SELECT source,league,source_player_key,player_id
           FROM player_source_ids WHERE league IN ('atp','wta')"""
    ):
        result[(row["source"], row["league"], str(row["source_player_key"]))].append(
            int(row["player_id"])
        )
    return result


def _plan_publication(
    connection: sqlite3.Connection,
    populations: dict[str, dict],
) -> dict:
    columns = _required_schema(connection)
    has_publisher = "publisher" in columns and "publisher_id" in columns
    if ("publisher" in columns) != ("publisher_id" in columns):
        raise TennisSpineError("players has only one of publisher and publisher_id")

    current_rows = connection.execute(
        "SELECT * FROM players WHERE league IN ('atp','wta') ORDER BY league,id"
    ).fetchall()
    by_id = {int(row["id"]): row for row in current_rows}
    by_league_name: dict[str, dict[str, list[sqlite3.Row]]] = {
        league: collections.defaultdict(list) for league in LEAGUES
    }
    publisher_owners: dict[tuple[str, str, str], int] = {}
    for row in current_rows:
        by_league_name[row["league"]][normalize_name(row["name"])].append(row)
        if has_publisher:
            publisher = str(row["publisher"] or "").strip()
            publisher_id = str(row["publisher_id"] or "").strip()
            if publisher_id and not publisher:
                raise TennisSpineError(
                    f"players.id {row['id']} has a publisher ID without a publisher"
                )
            if publisher and publisher_id:
                key = (row["league"], publisher, publisher_id)
                if key in publisher_owners and publisher_owners[key] != int(row["id"]):
                    raise TennisSpineError(
                        f"duplicate stored publisher identity {key}: "
                        f"players.id {publisher_owners[key]} and {row['id']}"
                    )
                publisher_owners[key] = int(row["id"])

    unresolved = _read_unresolved(connection)
    source_id_owners = _read_source_ids(connection)
    underdog_ids_by_name: dict[str, dict[str, set[int]]] = {
        league: collections.defaultdict(set) for league in LEAGUES
    }
    underdog_groups: dict[str, dict[str, dict]] = {
        league: {} for league in LEAGUES
    }
    for item in unresolved:
        if item["source"] != "underdog":
            continue
        league = item["league"]
        key = str(item["source_player_key"] or "").strip()
        name = str(item["raw_name"] or "").strip()
        if not key or not name:
            continue
        name_key = normalize_name(name)
        previous = underdog_groups[league].get(key)
        if previous and normalize_name(previous["name"]) != name_key:
            raise TennisSpineError(
                f"Underdog {league} source key {key} has conflicting unresolved names"
            )
        underdog_groups[league][key] = {"name": name, "name_key": name_key}
        mapped = source_id_owners.get(("underdog", league, key), [])
        if len(mapped) > 1:
            raise TennisSpineError(
                f"Underdog {league} source key {key} has {len(mapped)} stored player mappings"
            )
        if mapped:
            if mapped[0] not in by_id:
                raise TennisSpineError(
                    f"Underdog {league} source key {key} maps to missing players.id {mapped[0]}"
                )
            underdog_ids_by_name[league][name_key].add(mapped[0])

    plans: dict[str, list[dict]] = {}
    planned_owner: dict[tuple[str, str, str], str] = {}
    for league, population in populations.items():
        publisher = population["publisher"]
        plans[league] = []
        source_names: set[str] = set()
        for player in population["players"]:
            name_key = normalize_name(player["name"])
            if name_key in source_names:
                raise TennisSpineError(
                    f"{league} {publisher} has duplicate resolver name {player['name']!r}"
                )
            source_names.add(name_key)
            source_key = (league, publisher, player["publisher_id"])
            old_owner = publisher_owners.get(source_key)
            matching_names = by_league_name[league].get(name_key, [])
            if len(matching_names) > 1:
                raise TennisSpineError(
                    f"{league} publisher name {player['name']!r} matches "
                    f"{len(matching_names)} existing player rows"
                )
            candidates = set(underdog_ids_by_name[league].get(name_key, set()))
            if len(matching_names) == 1:
                candidates.add(int(matching_names[0]["id"]))
            if old_owner is not None:
                candidates.add(old_owner)
            if len(candidates) > 1:
                raise TennisSpineError(
                    f"{league} publisher identity {player['publisher_id']} for "
                    f"{player['name']!r} points at multiple stored player rows"
                )
            existing_id = next(iter(candidates), None)
            existing = by_id.get(existing_id) if existing_id is not None else None
            if existing_id is not None and existing is None:
                raise TennisSpineError(
                    f"{league} identity {player['name']!r} references missing "
                    f"players.id {existing_id}"
                )
            if existing is not None and has_publisher:
                old_publisher = str(existing["publisher"] or "").strip()
                old_publisher_id = str(existing["publisher_id"] or "").strip()
                if old_publisher and old_publisher != publisher:
                    raise TennisSpineError(
                        f"players.id {existing_id} already uses publisher {old_publisher}"
                    )
                if old_publisher_id and old_publisher_id != player["publisher_id"]:
                    raise TennisSpineError(
                        f"players.id {existing_id} has {publisher} ID {old_publisher_id}, "
                        f"source now publishes {player['publisher_id']}"
                    )
            if source_key in planned_owner:
                raise TennisSpineError(
                    f"duplicate planned publisher identity {source_key}"
                )
            planned_owner[source_key] = name_key
            plans[league].append({
                "player": player,
                "existing_id": existing_id,
                "publisher": publisher,
            })

    source_by_name: dict[str, dict[str, dict]] = {}
    for league in plans:
        source_by_name[league] = {}
        for item in plans[league]:
            player = item["player"]
            keys = {
                normalize_name(player["name"]),
                *(
                    normalize_name(alias)
                    for alias in _publisher_aliases(league, player["publisher_id"])
                ),
            }
            for name_key in keys:
                owner = source_by_name[league].get(name_key)
                if owner is not None and owner["player"]["publisher_id"] != player["publisher_id"]:
                    raise TennisSpineError(
                        f"{league} canonical or reviewed alias name {name_key!r} "
                        "matches multiple publisher identities"
                    )
                source_by_name[league][name_key] = item
    underdog_bindings: dict[str, list[dict]] = {league: [] for league in LEAGUES}
    for league in populations:
        for key, source_player in underdog_groups[league].items():
            candidate = source_by_name[league].get(source_player["name_key"])
            mapped = source_id_owners.get(("underdog", league, key), [])
            if mapped and candidate and candidate["existing_id"] is not None:
                if mapped[0] != candidate["existing_id"]:
                    raise TennisSpineError(
                        f"Underdog {league} ID {key} maps to players.id {mapped[0]}, "
                        f"but publisher name resolves to {candidate['existing_id']}"
                    )
            underdog_bindings[league].append({
                "source_player_key": key,
                "name": source_player["name"],
                "candidate": candidate,
                "existing_player_id": mapped[0] if mapped else None,
            })

    coverage: dict[str, dict[str, dict]] = {
        league: {
            source: {"rows": 0, "distinct_names": set(), "covered": 0,
                     "unmatched": [], "ambiguous": 0}
            for source in ("underdog", "bovada")
        }
        for league in populations
    }
    for item in unresolved:
        league = item["league"]
        if league not in populations:
            continue
        source = item["source"]
        metric = coverage[league][source]
        metric["rows"] += 1
        raw_name = str(item["raw_name"] or "")
        metric["distinct_names"].add(raw_name)
        raw_norm = normalize_name(raw_name)
        candidates = [
            plan for plan in plans[league]
            if raw_norm == normalize_name(plan["player"]["name"])
            or raw_norm in {
                normalize_name(alias)
                for alias in _publisher_aliases(
                    league, plan["player"]["publisher_id"]
                )
            }
        ]
        if len(candidates) == 1:
            metric["covered"] += 1
        elif len(candidates) > 1:
            metric["ambiguous"] += 1
        else:
            metric["unmatched"].append(raw_name)

    for league, bindings in underdog_bindings.items():
        for binding in bindings:
            candidate = binding["candidate"]
            if candidate is not None:
                if binding["existing_player_id"] is not None:
                    binding["state"] = "already_bound"
                else:
                    binding["state"] = "to_bind"
            elif binding["existing_player_id"] is not None:
                binding["state"] = "already_bound"
            else:
                binding["state"] = "unmatched"

    return {
        "plans": plans,
        "coverage": coverage,
        "underdog_bindings": underdog_bindings,
        "existing_rows": len(current_rows),
        "columns": columns,
        "publisher_owners": publisher_owners,
    }


def _source_id_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS player_source_ids(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source TEXT NOT NULL,
          league TEXT NOT NULL,
          source_player_key TEXT NOT NULL,
          player_id INTEGER NOT NULL REFERENCES players(id),
          first_seen TEXT NOT NULL,
          last_seen TEXT NOT NULL,
          UNIQUE(source, league, source_player_key)
        )"""
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_player_source_ids_player "
        "ON player_source_ids(player_id, source, league)"
    )


def _add_publisher_columns(connection: sqlite3.Connection) -> None:
    columns = _player_columns(connection)
    if "publisher" not in columns:
        connection.execute("ALTER TABLE players ADD COLUMN publisher TEXT")
    if "publisher_id" not in columns:
        connection.execute("ALTER TABLE players ADD COLUMN publisher_id TEXT")
    connection.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_players_publisher_identity
           ON players(league,publisher,publisher_id)
           WHERE publisher IS NOT NULL AND publisher_id IS NOT NULL"""
    )


def _ensure_name_alias_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS name_alias(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          player_id INTEGER NOT NULL REFERENCES players(id),
          alias_norm TEXT NOT NULL
        )"""
    )


def verified_backup(connection: sqlite3.Connection, backup_path: str | Path) -> str:
    """Make and verify a WAL-safe SQLite backup before the dev publication."""
    destination_path = Path(backup_path)
    if not destination_path.is_absolute():
        raise TennisSpineError("backup path must be absolute")
    destination_path = destination_path.resolve()
    source_path = Path(connection.execute("PRAGMA database_list").fetchone()[2]).resolve()
    if destination_path == source_path:
        raise TennisSpineError("backup path must differ from database path")
    if destination_path.exists():
        raise TennisSpineError(f"backup path already exists: {destination_path}")
    if not destination_path.parent.is_dir():
        raise TennisSpineError(f"backup directory does not exist: {destination_path.parent}")
    backup = sqlite3.connect(str(destination_path))
    try:
        connection.backup(backup)
        check = backup.execute("PRAGMA quick_check").fetchone()[0]
        if check != "ok":
            raise TennisSpineError(f"backup quick_check failed: {check}")
        backup.commit()
    except Exception:
        backup.close()
        try:
            destination_path.unlink()
        except FileNotFoundError:
            pass
        raise
    finally:
        try:
            backup.close()
        except Exception:
            pass
    return check


def _apply_plan(
    connection: sqlite3.Connection,
    populations: dict[str, dict],
    plan: dict,
) -> dict[str, dict]:
    _add_publisher_columns(connection)
    _source_id_schema(connection)
    _ensure_name_alias_table(connection)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    player_ids: dict[str, dict[str, int]] = {league: {} for league in populations}
    results: dict[str, dict] = {}

    for league, population in populations.items():
        matched = inserted = backfilled = unchanged = 0
        for item in plan["plans"][league]:
            player = item["player"]
            existing_id = item["existing_id"]
            if existing_id is None:
                cursor = connection.execute(
                    """INSERT INTO players
                       (name,team,league,publisher,publisher_id,active,updated_at)
                       VALUES(?,NULL,?,?,?,1,?)""",
                    (player["name"], league, population["publisher"],
                     player["publisher_id"], now),
                )
                player_id = int(cursor.lastrowid)
                inserted += 1
            else:
                player_id = existing_id
                matched += 1
                row = connection.execute(
                    "SELECT publisher,publisher_id FROM players WHERE id=?", (player_id,)
                ).fetchone()
                old_publisher = str(row[0] or "").strip()
                old_id = str(row[1] or "").strip()
                if not old_publisher and not old_id:
                    connection.execute(
                        """UPDATE players SET publisher=?,publisher_id=?,updated_at=?
                           WHERE id=?""",
                        (population["publisher"], player["publisher_id"], now, player_id),
                    )
                    backfilled += 1
                elif old_publisher == population["publisher"] and old_id == player["publisher_id"]:
                    unchanged += 1
                else:
                    raise TennisSpineError(
                        f"players.id {player_id} publisher identity changed after planning"
                    )
            player_ids[league][player["publisher_id"]] = player_id

        results[league] = {
            "matched_existing": matched,
            "inserted": inserted,
            "publisher_id_backfilled": backfilled,
            "publisher_id_unchanged": unchanged,
            "stored_identity_ids": set(player_ids[league]),
            "publisher": population["publisher"],
        }

    inserted_bindings = {league: 0 for league in populations}
    refreshed_bindings = {league: 0 for league in populations}
    inserted_aliases = {league: 0 for league in populations}
    stored_aliases = {league: 0 for league in populations}
    for league, population in populations.items():
        for publisher_id, player_id in player_ids[league].items():
            for alias in _publisher_aliases(league, publisher_id):
                alias_norm = normalize_name(alias)
                canonical_norm = normalize_name(next(
                    p["name"] for p in population["players"]
                    if str(p["publisher_id"]) == publisher_id
                ))
                if alias_norm == canonical_norm:
                    continue
                owners = {
                    int(row[0]) for row in connection.execute(
                        "SELECT player_id FROM name_alias WHERE alias_norm=?",
                        (alias_norm,),
                    )
                }
                if owners and owners != {player_id}:
                    raise TennisSpineError(
                        f"publisher alias {alias!r} for {league} ID {publisher_id} "
                        f"is already owned by players {sorted(owners)}"
                    )
                if not owners:
                    connection.execute(
                        "INSERT INTO name_alias(player_id,alias_norm) VALUES(?,?)",
                        (player_id, alias_norm),
                    )
                    inserted_aliases[league] += 1
                stored_aliases[league] += 1
    for league, bindings in plan["underdog_bindings"].items():
        if league not in populations:
            continue
        for binding in bindings:
            candidate = binding["candidate"]
            if candidate is None:
                continue
            player = candidate["player"]
            player_id = player_ids[league][player["publisher_id"]]
            existing = connection.execute(
                """SELECT player_id FROM player_source_ids
                   WHERE source='underdog' AND league=? AND source_player_key=?""",
                (league, binding["source_player_key"]),
            ).fetchone()
            if existing:
                if int(existing[0]) != player_id:
                    raise TennisSpineError(
                        f"Underdog {league} ID {binding['source_player_key']} maps to "
                        f"players.id {existing[0]}, not publisher-backed players.id {player_id}"
                    )
                connection.execute(
                    """UPDATE player_source_ids SET last_seen=?
                       WHERE source='underdog' AND league=? AND source_player_key=?""",
                    (now, league, binding["source_player_key"]),
                )
                refreshed_bindings[league] += 1
            else:
                connection.execute(
                    """INSERT INTO player_source_ids
                       (source,league,source_player_key,player_id,first_seen,last_seen)
                       VALUES('underdog',?,?,?,?,?)""",
                    (league, binding["source_player_key"], player_id, now, now),
                )
                inserted_bindings[league] += 1

    for league, population in populations.items():
        stored = {
            str(row[0]) for row in connection.execute(
                """SELECT publisher_id FROM players
                   WHERE league=? AND publisher=? AND publisher_id IS NOT NULL""",
                (league, population["publisher"]),
            )
        }
        stored_current = len(results[league]["stored_identity_ids"] & stored)
        source_total = len(population["players"])
        if stored_current != source_total:
            raise TennisSpineError(
                f"{league} stored {stored_current} of {source_total} current publisher IDs"
            )
        results[league]["stored_current"] = stored_current
        results[league]["publisher_rows_total"] = len(stored)
        results[league]["underdog_new_bindings"] = inserted_bindings[league]
        results[league]["underdog_refreshed_bindings"] = refreshed_bindings[league]
        results[league]["verified_aliases_stored"] = stored_aliases[league]
        results[league]["verified_aliases_inserted"] = inserted_aliases[league]
    return results


def refresh(
    db_path: str | Path,
    *,
    leagues: Iterable[str] = LEAGUES,
    fetch_atp_page: Callable[[str], object] | None = None,
    fetch_wta_json: Callable[[str], object] | None = None,
    request_counts: collections.Counter | None = None,
    dry_run: bool = False,
    backup_path: str | Path | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict:
    selected = tuple(leagues)
    if not selected or len(set(selected)) != len(selected) or any(
        league not in LEAGUES for league in selected
    ):
        raise TennisSpineError(f"leagues must be a unique non-empty subset of {LEAGUES}")
    db_path = Path(db_path).resolve()
    if not db_path.is_file():
        raise TennisSpineError(f"database must already exist: {db_path}")
    request_counts = request_counts if request_counts is not None else collections.Counter()

    populations = {}
    year = dt.date.today().year
    if "atp" in selected:
        populations["atp"] = fetch_atp_population(
            year=year, fetch_page=fetch_atp_page,
            request_counts=request_counts, sleeper=sleeper,
        )
    if "wta" in selected:
        populations["wta"] = fetch_wta_population(
            fetch_json=fetch_wta_json, request_counts=request_counts, sleeper=sleeper,
        )

    connection = sqlite3.connect(str(db_path), timeout=60)
    connection.row_factory = sqlite3.Row
    try:
        plan = _plan_publication(connection, populations)
        output = {}
        for league, population in populations.items():
            source_players = population["players"]
            coverage = plan["coverage"][league]
            existing = sum(item["existing_id"] is not None for item in plan["plans"][league])
            inserted = len(source_players) - existing
            bindings = plan["underdog_bindings"][league]
            output[league] = {
                "publisher": population["publisher"],
                "source_rows": len(source_players),
                "unique_ids": len({p["publisher_id"] for p in source_players}),
                "unique_names": len({normalize_name(p["name"]) for p in source_players}),
                "pages": population["pages"],
                "requests": population["requests"],
                "ranked_rows": population.get("ranked_rows", len(source_players)),
                "profile_supplements_total": population.get("profile_supplements_total", 0),
                "profile_supplements_ranked": population.get("profile_supplements_ranked", 0),
                "profile_supplements_added": population.get("profile_supplements_added", 0),
                "matched_existing": existing,
                "inserted": inserted,
                "publisher_id_backfilled": sum(
                    item["existing_id"] is not None
                    and not ("publisher" in plan["columns"]
                             and plan["publisher_owners"].get(
                                 (league, population["publisher"],
                                  item["player"]["publisher_id"])
                             ) == item["existing_id"])
                    for item in plan["plans"][league]
                ),
                "underdog_rows": coverage["underdog"]["rows"],
                "underdog_distinct_names": len(coverage["underdog"]["distinct_names"]),
                "underdog_covered": coverage["underdog"]["covered"],
                "underdog_unmatched": len(coverage["underdog"]["unmatched"]),
                "bovada_rows": coverage["bovada"]["rows"],
                "bovada_distinct_names": len(coverage["bovada"]["distinct_names"]),
                "bovada_covered": coverage["bovada"]["covered"],
                "bovada_unmatched": len(coverage["bovada"]["unmatched"]),
                "underdog_key_count": len(bindings),
                "underdog_already_bound": sum(b["state"] == "already_bound" for b in bindings),
                "underdog_to_bind": sum(b["state"] == "to_bind" for b in bindings),
                "underdog_key_unmatched": sum(b["state"] == "unmatched" for b in bindings),
                "verified_aliases": sum(
                    len(_publisher_aliases(league, str(p["publisher_id"])))
                    for p in source_players
                ),
                "unmatched_underdog_examples": coverage["underdog"]["unmatched"][:10],
                "unmatched_bovada_examples": coverage["bovada"]["unmatched"][:10],
            }

        if dry_run:
            output["dry_run"] = True
            output["schema_written"] = False
            return output

        if backup_path is None:
            raise TennisSpineError("apply requires a verified backup path")
        backup_check = verified_backup(connection, backup_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            applied = _apply_plan(connection, populations, plan)
            database_check = connection.execute("PRAGMA quick_check").fetchone()[0]
            if database_check != "ok":
                raise TennisSpineError(
                    f"development database quick_check failed after publication: {database_check}"
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        for league, item in applied.items():
            output[league].update(item)
        output["dry_run"] = False
        output["schema_written"] = True
        output["backup_path"] = str(Path(backup_path).resolve())
        output["backup_quick_check"] = backup_check
        output["database_quick_check"] = database_check
        return output
    finally:
        connection.close()


def _print_results(results: dict) -> None:
    for league in LEAGUES:
        if league not in results:
            continue
        result = results[league]
        source_count = result["source_rows"]
        print(
            f"{league} source {result['publisher']}: {result['ranked_rows']} of "
            f"{result['ranked_rows']} ranked player rows across "
            f"{result['pages']} of {result['pages']} pages; "
            f"{result['requests']} requests for {result['pages']} pages"
        )
        if result["profile_supplements_total"]:
            included = (
                result["profile_supplements_ranked"]
                + result["profile_supplements_added"]
            )
            print(
                f"  publisher profile supplements included {included} of "
                f"{result['profile_supplements_total']} "
                f"({result['profile_supplements_ranked']} already ranked, "
                f"{result['profile_supplements_added']} added)"
            )
        print(
            f"  publisher IDs {result['unique_ids']} of {source_count}; resolver-safe names "
            f"{result['unique_names']} of {source_count}"
        )
        print(
            f"  unresolved Underdog names covered {result['underdog_covered']} of "
            f"{result['underdog_rows']} rows ({result['underdog_distinct_names']} "
            f"distinct names); unmatched {result['underdog_unmatched']} of "
            f"{result['underdog_rows']}"
        )
        print(
            f"  unresolved Bovada names covered {result['bovada_covered']} of "
            f"{result['bovada_rows']} rows ({result['bovada_distinct_names']} "
            f"distinct names); unmatched {result['bovada_unmatched']} of "
            f"{result['bovada_rows']}"
        )
        print(
            f"  Underdog IDs already bound {result['underdog_already_bound']} of "
            f"{result['underdog_key_count']} keys; to bind {result['underdog_to_bind']} "
            f"of {result['underdog_key_count']}; unmatched {result['underdog_key_unmatched']} "
            f"of {result['underdog_key_count']}"
        )
        print(
            f"  player rows matched {result['matched_existing']} of {source_count}; "
            f"publisher-backed rows to insert {result['inserted']} of {source_count}; "
            f"publisher IDs to backfill {result['publisher_id_backfilled']} of "
            f"{result['matched_existing']} existing matches"
        )
        if not results.get("dry_run", True):
            print(
                f"  stored current publisher IDs {result['stored_current']} of "
                f"{source_count}; all stored {result['publisher_rows_total']} of "
                f"{result['publisher_rows_total']} publisher-backed rows"
            )
            print(
                f"  Underdog IDs newly bound {result['underdog_new_bindings']} of "
                f"{result['underdog_to_bind']} planned keys; existing mappings refreshed "
                f"{result['underdog_refreshed_bindings']} of "
                f"{result['underdog_already_bound']} existing keys"
            )
            print(
                f"  verified publisher aliases stored {result['verified_aliases_stored']} of "
                f"{result['verified_aliases']}; newly added "
                f"{result['verified_aliases_inserted']} of {result['verified_aliases']}"
            )
        else:
            print(
                f"  verified publisher aliases planned {result['verified_aliases']} of "
                f"{result['verified_aliases']}"
            )
        for label in ("unmatched_underdog_examples", "unmatched_bovada_examples"):
            if result[label]:
                print(f"  {label.replace('_', ' ')}: {', '.join(result[label])}")
    if results.get("backup_path"):
        print(
            f"backup: {results['backup_path']}; "
            f"quick_check={results['backup_quick_check']}"
        )
        print(f"development database quick_check: {results['database_quick_check']}")


def _print_request_counts(counts: collections.Counter) -> None:
    for host in (ATP_HOST, WTA_HOST):
        if counts.get(host, 0):
            print(f"requests: {host} {counts[host]} total, paced; no per-player requests")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="fetch and plan without DB writes")
    mode.add_argument("--apply", action="store_true", help="back up and publish to dev DB")
    parser.add_argument("--db", default=DB, help="must be the managed development database")
    parser.add_argument("--league", choices=LEAGUES, action="append",
                        help="publish one league (repeatable)")
    parser.add_argument("--backup", help="new absolute SQLite backup path required by --apply")
    args = parser.parse_args(argv)
    db_path = Path(args.db).resolve()
    if db_path != DEV_DB.resolve():
        print(
            f"ERROR: this ingest is dev-only; database must be {DEV_DB}",
            file=sys.stderr,
        )
        return 2
    if args.apply and not args.backup:
        parser.error("--apply requires --backup")
    if not args.apply and args.backup:
        parser.error("--backup is only valid with --apply")

    leagues = tuple(args.league or LEAGUES)
    counts: collections.Counter = collections.Counter()
    print(f"database: {db_path}{' (apply)' if args.apply else ' (dry run)'}")
    print(
        "source request plan: ATP paginated at 2 seconds apart; "
        "WTA ranked API at 2 seconds apart; no per-player requests"
    )
    try:
        results = refresh(
            db_path,
            leagues=leagues,
            request_counts=counts,
            dry_run=not args.apply,
            backup_path=args.backup,
        )
        _print_results(results)
        return 0
    except TennisSpineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        _print_request_counts(counts)


if __name__ == "__main__":
    sys.exit(main())
