"""Bounded UFCStats fetcher and parsers for durable fighter history.

UFCStats publishes one fighter profile page containing the complete fight list,
including result, opponent, event/date, significant strikes, method, round and
elapsed time.  The ingest reads only the last requested completed rows from that
published table; it does not reconstruct fight history from event listings.
"""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import html
import http.cookiejar
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


BASE_URL = "http://www.ufcstats.com"
COMPLETED_EVENTS_URL = BASE_URL + "/statistics/events/completed?page=all"
UPCOMING_EVENTS_URL = BASE_URL + "/statistics/events/upcoming?page=all"
_MAX_RESPONSE_BYTES = 2_000_000
_USER_AGENT = "LegendaryPicks-UFCStats-Ingest/1.0"


class UfcStatsSourceError(RuntimeError):
    """The publisher could not be fetched or returned an invalid document."""


@dataclass(frozen=True)
class SourceEvent:
    source_event_key: str
    name: str
    date: str
    url: str


@dataclass(frozen=True)
class SourceFighter:
    source_player_key: str
    name: str


@dataclass(frozen=True)
class SourceCardFight:
    source_fight_key: str
    fighters: Tuple[SourceFighter, SourceFighter]


@dataclass(frozen=True)
class SourceFight:
    source_fight_key: str
    source_event_key: str
    game_date: str
    opponent: str
    opponent_source_key: str
    result: str
    method: str
    significant_strikes: int
    round_number: int
    clock_display: str
    fight_time_seconds: int


@dataclass(frozen=True)
class FighterProfile:
    source_player_key: str
    name: str
    fights: Tuple[SourceFight, ...]


@dataclass
class _Link:
    href: str
    parts: List[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return _clean(" ".join(self.parts))


@dataclass
class _Cell:
    parts: List[str] = field(default_factory=list)
    paragraphs: List[str] = field(default_factory=list)
    links: List[_Link] = field(default_factory=list)

    @property
    def text(self) -> str:
        return _clean(" ".join(self.parts))


@dataclass
class _Row:
    data_link: str
    cells: List[_Cell] = field(default_factory=list)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


class _TableParser(HTMLParser):
    """Capture table rows/cells without depending on an optional HTML package."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: List[_Row] = []
        self._row: Optional[_Row] = None
        self._cell: Optional[_Cell] = None
        self._link: Optional[_Link] = None
        self._paragraph: Optional[List[str]] = None

    def handle_starttag(self, tag: str, attrs: Sequence[Tuple[str, Optional[str]]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "tr":
            self._row = _Row(data_link=values.get("data-link", ""))
            self._cell = None
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = _Cell()
            self._row.cells.append(self._cell)
        elif tag == "a" and self._cell is not None:
            self._link = _Link(values.get("href") or values.get("data-link") or "")
            self._cell.links.append(self._link)
        elif tag == "p" and self._cell is not None:
            self._paragraph = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._link = None
        elif tag == "p" and self._cell is not None and self._paragraph is not None:
            value = _clean(" ".join(self._paragraph))
            if value:
                self._cell.paragraphs.append(value)
            self._paragraph = None
        elif tag in {"td", "th"}:
            self._cell = None
            self._link = None
            self._paragraph = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
            self._cell = None

    def handle_data(self, data: str) -> None:
        if self._cell is None or not data.strip():
            return
        self._cell.parts.append(data)
        if self._link is not None:
            self._link.parts.append(data)
        if self._paragraph is not None:
            self._paragraph.append(data)


def _rows(document: str) -> List[_Row]:
    parser = _TableParser()
    parser.feed(document)
    parser.close()
    return parser.rows


def _source_key(url: str, kind: str) -> str:
    match = re.search(r"/{}/([0-9a-f]+)".format(re.escape(kind)), url or "", re.I)
    return match.group(1).lower() if match else ""


def _published_date(value: str) -> Optional[str]:
    match = re.search(
        r"\b([A-Z][a-z]{2,8})\.?\s+(\d{1,2}),\s+(\d{4})\b", value or ""
    )
    if not match:
        return None
    month, day, year = match.groups()
    for pattern in ("%B %d %Y", "%b %d %Y"):
        try:
            return dt.datetime.strptime(
                "{} {} {}".format(month, day, year), pattern
            ).date().isoformat()
        except ValueError:
            continue
    return None


def parse_completed_events(document: str) -> List[SourceEvent]:
    events: Dict[str, SourceEvent] = {}
    for row in _rows(document):
        for cell in row.cells:
            link = next(
                (item for item in cell.links if "/event-details/" in item.href), None
            )
            if link is None:
                continue
            source_key = _source_key(link.href, "event-details")
            date_text = _published_date(cell.text)
            if not source_key or not link.text or not date_text:
                continue
            event = SourceEvent(source_key, link.text, date_text, link.href)
            prior = events.get(source_key)
            if prior is not None and prior != event:
                raise UfcStatsSourceError(
                    "event {} appeared with conflicting metadata".format(source_key)
                )
            events[source_key] = event
    if not events:
        raise UfcStatsSourceError("completed-events page contained no published events")
    return sorted(events.values(), key=lambda item: (item.date, item.source_event_key), reverse=True)


def parse_event_card(document: str) -> List[SourceCardFight]:
    fights: Dict[str, SourceCardFight] = {}
    for row in _rows(document):
        source_fight_key = _source_key(row.data_link, "fight-details")
        if not source_fight_key:
            continue
        fighter_links = [
            link for cell in row.cells for link in cell.links
            if "/fighter-details/" in link.href and link.text
        ]
        unique: List[SourceFighter] = []
        seen = set()
        for link in fighter_links:
            source_player_key = _source_key(link.href, "fighter-details")
            if source_player_key and source_player_key not in seen:
                unique.append(SourceFighter(source_player_key, link.text))
                seen.add(source_player_key)
        if len(unique) != 2:
            raise UfcStatsSourceError(
                "fight {} published {} fighter identities".format(
                    source_fight_key, len(unique)
                )
            )
        fight = SourceCardFight(source_fight_key, (unique[0], unique[1]))
        prior = fights.get(source_fight_key)
        if prior is not None and prior != fight:
            raise UfcStatsSourceError(
                "fight {} appeared with conflicting fighters".format(source_fight_key)
            )
        fights[source_fight_key] = fight
    if not fights:
        raise UfcStatsSourceError("event page contained no published fights")
    return list(fights.values())


def _profile_name(document: str) -> str:
    match = re.search(
        r"b-content__title-highlight[^>]*>(.*?)</(?:span|h2)", document, re.I | re.S
    )
    if not match:
        return ""
    return _clean(re.sub(r"<[^>]+>", " ", match.group(1)))


def _cell_values(cell: _Cell) -> List[str]:
    return cell.paragraphs or ([cell.text] if cell.text else [])


def _first_int(cell: _Cell) -> Optional[int]:
    for value in _cell_values(cell):
        match = re.search(r"\b(\d+)\b", value)
        if match:
            return int(match.group(1))
    return None


def _result(value: str) -> Optional[str]:
    lowered = (value or "").strip().lower()
    if "win" in lowered:
        return "W"
    if "loss" in lowered:
        return "L"
    if "draw" in lowered:
        return "D"
    if "nc" in lowered or "no contest" in lowered:
        return "NC"
    return None


def _method(value: str) -> Optional[str]:
    upper = (value or "").upper()
    if "KO/TKO" in upper or re.search(r"\bTKO\b|\bKO\b", upper):
        return "KO/TKO"
    if "SUB" in upper:
        return "SUB"
    if "DEC" in upper:
        return "DEC"
    if "DQ" in upper:
        return "DQ"
    if "CNC" in upper:
        return "CNC"
    if "OVERTURNED" in upper:
        return "OVERTURNED"
    return None


def parse_fighter_profile(
    document: str,
    source_player_key: str,
    limit: int = 5,
) -> FighterProfile:
    if not 1 <= limit <= 5:
        raise ValueError("limit must be between 1 and 5")
    name = _profile_name(document)
    if not name:
        raise UfcStatsSourceError("fighter profile contained no published name")

    fights: List[SourceFight] = []
    seen = set()
    for row in _rows(document):
        source_fight_key = _source_key(row.data_link, "fight-details")
        if not source_fight_key:
            continue
        if len(row.cells) < 10:
            raise UfcStatsSourceError(
                "fight {} profile row had {} columns, expected 10".format(
                    source_fight_key, len(row.cells)
                )
            )
        fighter_links = [
            link for link in row.cells[1].links if "/fighter-details/" in link.href
        ]
        if len(fighter_links) != 2:
            raise UfcStatsSourceError(
                "fight {} profile row lacked two fighter ids".format(source_fight_key)
            )
        fighter_index = next(
            (
                index for index, link in enumerate(fighter_links)
                if _source_key(link.href, "fighter-details") == source_player_key
            ),
            None,
        )
        if fighter_index is None:
            raise UfcStatsSourceError(
                "fight {} did not contain profile fighter {}".format(
                    source_fight_key, source_player_key
                )
            )
        opponent_link = fighter_links[1 - fighter_index]
        outcome = _result(row.cells[0].text)
        strike_values = [
            int(match.group(1))
            for value in _cell_values(row.cells[3])
            for match in [re.search(r"\b(\d+)\b", value)]
            if match
        ]
        event_link = next(
            (link for link in row.cells[6].links if "/event-details/" in link.href), None
        )
        game_date = _published_date(row.cells[6].text)
        method = _method(row.cells[7].text)
        round_number = _first_int(row.cells[8])
        clock_match = re.search(r"\b(\d{1,2}):(\d{2})\b", row.cells[9].text)
        if (
            outcome is None
            or len(strike_values) != 2
            or event_link is None
            or game_date is None
            or method is None
            or round_number is None
            or clock_match is None
        ):
            raise UfcStatsSourceError(
                "fight {} profile row was missing a required published field".format(
                    source_fight_key
                )
            )
        minutes, seconds = int(clock_match.group(1)), int(clock_match.group(2))
        if not 1 <= round_number <= 5 or minutes > 5 or seconds > 59:
            raise UfcStatsSourceError(
                "fight {} published invalid round/time {}/{}".format(
                    source_fight_key, round_number, clock_match.group(0)
                )
            )
        elapsed = minutes * 60 + seconds
        fight_time_seconds = (round_number - 1) * 300 + elapsed
        fight = SourceFight(
            source_fight_key=source_fight_key,
            source_event_key=_source_key(event_link.href, "event-details"),
            game_date=game_date,
            opponent=opponent_link.text,
            opponent_source_key=_source_key(opponent_link.href, "fighter-details"),
            result=outcome,
            method=method,
            significant_strikes=strike_values[fighter_index],
            round_number=round_number,
            clock_display=clock_match.group(0),
            fight_time_seconds=fight_time_seconds,
        )
        if fight.source_fight_key in seen:
            raise UfcStatsSourceError(
                "fighter profile repeated fight {}".format(fight.source_fight_key)
            )
        seen.add(fight.source_fight_key)
        fights.append(fight)

    if any(
        fights[index].game_date < fights[index + 1].game_date
        for index in range(len(fights) - 1)
    ):
        raise UfcStatsSourceError("fighter profile fights were not newest-first")
    return FighterProfile(source_player_key, name, tuple(fights[:limit]))


class UfcStatsClient:
    """Serial, paced client with durable gzip archives and challenge handling."""

    def __init__(
        self,
        archive_dir: str,
        from_archive: bool = False,
        min_interval: float = 0.75,
        timeout: float = 25.0,
    ) -> None:
        self.archive_dir = Path(archive_dir).resolve()
        self.from_archive = from_archive
        self.min_interval = max(0.0, min_interval)
        self.timeout = timeout
        self._last_request = 0.0
        jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar)
        )

    def _pace(self) -> None:
        delay = self.min_interval - (time.monotonic() - self._last_request)
        if delay > 0:
            time.sleep(delay)

    def _request(self, request: urllib.request.Request) -> bytes:
        self._pace()
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                payload = response.read(_MAX_RESPONSE_BYTES + 1)
        except Exception as exc:
            raise UfcStatsSourceError(
                "{} {} failed: {}".format(request.get_method(), request.full_url, type(exc).__name__)
            ) from exc
        finally:
            self._last_request = time.monotonic()
        if len(payload) > _MAX_RESPONSE_BYTES:
            raise UfcStatsSourceError(
                "response exceeded {} bytes: {}".format(_MAX_RESPONSE_BYTES, request.full_url)
            )
        return payload

    def _network_html(self, url: str) -> str:
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        payload = self._request(request)
        document = payload.decode("utf-8", "replace")
        if "Checking your browser" in document:
            nonce_match = re.search(r'var nonce="([0-9a-f]+)"', document)
            target_match = re.search(r"new Array\((\d+)\+1\)", document)
            if nonce_match is None or target_match is None:
                raise UfcStatsSourceError("browser challenge shape changed")
            nonce = nonce_match.group(1)
            zeros = int(target_match.group(1))
            if not 1 <= zeros <= 6:
                raise UfcStatsSourceError(
                    "browser challenge difficulty is outside the bounded range"
                )
            answer = 0
            prefix = "0" * zeros
            while not hashlib.sha256(
                "{}:{}".format(nonce, answer).encode("utf-8")
            ).hexdigest().startswith(prefix):
                answer += 1
                if answer > 5_000_000:
                    raise UfcStatsSourceError(
                        "browser challenge exceeded the bounded work limit"
                    )
            challenge = urllib.request.Request(
                BASE_URL + "/__c",
                data=urllib.parse.urlencode({"nonce": nonce, "n": answer}).encode("ascii"),
                headers={
                    "User-Agent": _USER_AGENT,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            self._request(challenge)
            payload = self._request(request)
            document = payload.decode("utf-8", "replace")
        if "Checking your browser" in document or "<html" not in document.lower():
            raise UfcStatsSourceError("publisher returned no usable HTML for {}".format(url))
        return document

    def get_html(self, url: str, archive_name: str) -> str:
        archive_path = self.archive_dir / "{}.html.gz".format(archive_name)
        if self.from_archive:
            if not archive_path.is_file():
                raise UfcStatsSourceError(
                    "required archive is missing: {}".format(archive_path)
                )
            with gzip.open(archive_path, "rt", encoding="utf-8") as handle:
                return handle.read()

        document = self._network_html(url)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        temporary = archive_path.with_suffix(archive_path.suffix + ".tmp")
        with gzip.open(temporary, "wt", encoding="utf-8") as handle:
            handle.write(document)
        os.replace(temporary, archive_path)
        return document

    def completed_events(self) -> List[SourceEvent]:
        return parse_completed_events(
            self.get_html(COMPLETED_EVENTS_URL, "events-completed")
        )

    def upcoming_events(self) -> List[SourceEvent]:
        """Return UFCStats' current published future-event inventory."""
        return parse_completed_events(
            self.get_html(UPCOMING_EVENTS_URL, "events-upcoming")
        )

    def published_events(self) -> List[SourceEvent]:
        """Return the de-duplicated completed/live and upcoming event inventory."""
        by_key = {
            event.source_event_key: event
            for event in self.completed_events() + self.upcoming_events()
        }
        return sorted(
            by_key.values(),
            key=lambda item: (item.date, item.source_event_key),
            reverse=True,
        )

    def event_card(self, event: SourceEvent) -> List[SourceCardFight]:
        return parse_event_card(
            self.get_html(event.url, "event-{}".format(event.source_event_key))
        )

    def fighter_profile(self, source_player_key: str, limit: int) -> FighterProfile:
        url = BASE_URL + "/fighter-details/" + source_player_key
        return parse_fighter_profile(
            self.get_html(url, "fighter-{}".format(source_player_key)),
            source_player_key,
            limit=limit,
        )
