#!/usr/bin/env python3
"""Load pinned historical point archives into separate canonical SQLite databases.

Each project gets its own database under ``backend/data/tennis_point_archives``.
The two databases share the same canonical match/event schema and preserve every
original CSV row as JSON. Dry-run is the default.
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import io
import json
import re
import shutil
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path


HERE = Path(__file__).resolve().parent
ARCHIVE_DIR = (HERE / "data" / "tennis_point_archives").resolve()
MIN_HEADROOM_BYTES = 2 * 1024**3
BATCH_SIZE = 5_000
USER_AGENT = "LegendaryPicks-historical-tennis-ingest/1.0"

SOURCES = {
    "grand_slam_archive": {
        "repo": "AngieXuAU/tennis-point-by-point-archive",
        "commit": "83733587353df8a41f2fd4f516147d5aa83f5a8d",
        "license": "CC BY-NC-SA 4.0",
        "license_url": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
        "kind": "slam",
    },
    "match_charting_project": {
        "repo": "JeffSackmann/tennis_MatchChartingProject",
        "commit": "1813a1309b7ed7ebf1c7e884b32bf675d00e4edf",
        "license": "CC BY-NC-SA 4.0",
        "license_url": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
        "kind": "mcp",
    },
}

MATCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS tennis_point_matches (
    id                       INTEGER PRIMARY KEY,
    source                   TEXT NOT NULL,
    source_dataset           TEXT NOT NULL,
    source_match_id          TEXT NOT NULL,
    tour                     TEXT NOT NULL CHECK (tour IN ('atp','wta','mixed','unknown')),
    event_category           TEXT NOT NULL,
    match_year               INTEGER,
    match_date               TEXT,
    tournament_name          TEXT,
    tournament_key           TEXT,
    round                    TEXT,
    surface                  TEXT,
    player1_name             TEXT,
    player2_name             TEXT,
    player1_partner          TEXT,
    player2_partner          TEXT,
    player1_source_id        TEXT,
    player2_source_id        TEXT,
    player1_partner_source_id TEXT,
    player2_partner_source_id TEXT,
    source_file              TEXT NOT NULL,
    source_license           TEXT NOT NULL,
    raw_json                 TEXT NOT NULL,
    loaded_at                TEXT NOT NULL,
    UNIQUE (source, source_dataset, source_match_id)
)
"""

SOURCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS tennis_point_sources (
    source               TEXT NOT NULL,
    source_dataset       TEXT NOT NULL,
    source_url           TEXT NOT NULL,
    source_commit        TEXT,
    source_license       TEXT NOT NULL,
    source_license_url   TEXT,
    loaded_at            TEXT NOT NULL,
    source_match_rows    INTEGER NOT NULL,
    source_event_rows    INTEGER NOT NULL,
    played_point_rows    INTEGER NOT NULL,
    PRIMARY KEY (source, source_dataset)
)
"""

EVENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS tennis_point_events (
    id                       INTEGER PRIMARY KEY,
    source                   TEXT NOT NULL,
    source_dataset           TEXT NOT NULL,
    source_match_id          TEXT NOT NULL,
    source_file              TEXT NOT NULL,
    source_row_no            INTEGER NOT NULL,
    point_id                 TEXT NOT NULL,
    sequence_no              INTEGER NOT NULL,
    is_point                 INTEGER NOT NULL CHECK (is_point IN (0,1)),
    point_no                 INTEGER,
    set_no                   TEXT,
    game_no                  TEXT,
    event_type               TEXT NOT NULL,
    point_score              TEXT,
    p1_score                 TEXT,
    p2_score                 TEXT,
    score_before_json        TEXT,
    score_after_json         TEXT,
    score_timing             TEXT,
    event_time_start_utc     TEXT,
    event_time_end_utc       TEXT,
    timestamp_precision      TEXT,
    point_winner             TEXT,
    point_winner_name        TEXT,
    point_server             TEXT,
    point_server_name        TEXT,
    serve_number             TEXT,
    is_ace                   INTEGER CHECK (is_ace IN (0,1) OR is_ace IS NULL),
    is_double_fault          INTEGER CHECK (is_double_fault IN (0,1) OR is_double_fault IS NULL),
    is_rally_winner          INTEGER CHECK (is_rally_winner IN (0,1) OR is_rally_winner IS NULL),
    is_unforced_error        INTEGER CHECK (is_unforced_error IN (0,1) OR is_unforced_error IS NULL),
    rally_length             INTEGER,
    serve_speed_kmh          REAL,
    first_serve_sequence     TEXT,
    second_serve_sequence    TEXT,
    raw_json                 TEXT NOT NULL,
    loaded_at                TEXT NOT NULL,
    FOREIGN KEY (source, source_dataset, source_match_id)
      REFERENCES tennis_point_matches(source, source_dataset, source_match_id)
)
"""

MATCH_INSERT = """
INSERT INTO tennis_point_matches (
 source,source_dataset,source_match_id,tour,event_category,match_year,match_date,
 tournament_name,tournament_key,round,surface,player1_name,player2_name,
 player1_partner,player2_partner,player1_source_id,player2_source_id,
 player1_partner_source_id,player2_partner_source_id,source_file,source_license,
 raw_json,loaded_at
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""

EVENT_INSERT = """
INSERT INTO tennis_point_events (
 source,source_dataset,source_match_id,source_file,source_row_no,point_id,sequence_no,is_point,
 point_no,set_no,game_no,event_type,point_score,p1_score,p2_score,score_before_json,
 score_after_json,score_timing,event_time_start_utc,event_time_end_utc,timestamp_precision,
 point_winner,point_winner_name,point_server,point_server_name,
 serve_number,is_ace,is_double_fault,is_rally_winner,is_unforced_error,rally_length,
 serve_speed_kmh,first_serve_sequence,second_serve_sequence,raw_json,loaded_at
) VALUES ({placeholders})
""".format(placeholders=",".join("?" for _ in range(36)))


@dataclass
class MatchMeta:
    source_file: str
    row: dict[str, str | None]
    score: int


@dataclass
class SourcePlan:
    source: str
    dataset: str
    match_paths: list[str]
    point_paths: list[str]
    matches: dict[str, MatchMeta] = field(default_factory=dict)
    match_rows: int = 0
    malformed_match_rows: int = 0
    duplicate_match_rows: int = 0
    point_rows: int = 0
    played_points: int = 0
    nonpoint_rows: int = 0
    point_json_bytes: int = 0
    tours: collections.Counter = field(default_factory=collections.Counter)
    nonpoint_reasons: collections.Counter = field(default_factory=collections.Counter)
    point_file_rows: dict[str, int] = field(default_factory=dict)
    point_match_ids: set[str] = field(default_factory=set)
    coverage_rows: collections.Counter = field(default_factory=collections.Counter)
    coverage_points: collections.Counter = field(default_factory=collections.Counter)
    coverage_matches: dict[tuple[int, str, str], set[str]] = field(default_factory=dict)


class IngestError(RuntimeError):
    pass


def _request(url: str):
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT})


def _tree(source: str) -> list[dict]:
    spec = SOURCES[source]
    url = f"https://api.github.com/repos/{spec['repo']}/git/trees/{spec['commit']}?recursive=1"
    try:
        with urllib.request.urlopen(_request(url), timeout=45) as response:
            result = json.load(response)
    except Exception as exc:
        raise IngestError(f"cannot read pinned GitHub tree for {source}: {exc}") from exc
    if result.get("truncated"):
        raise IngestError(f"GitHub tree was truncated for {source}")
    return result.get("tree", [])


def _raw_url(source: str, path: str) -> str:
    spec = SOURCES[source]
    return (
        f"https://raw.githubusercontent.com/{spec['repo']}/{spec['commit']}/"
        + urllib.parse.quote(path, safe="/")
    )


def _csv_rows(source: str, path: str, *, strict_width: bool):
    url = _raw_url(source, path)
    try:
        response = urllib.request.urlopen(_request(url), timeout=120)
    except Exception as exc:
        raise IngestError(f"cannot fetch {path}: {exc}") from exc
    with response:
        text = io.TextIOWrapper(response, encoding="utf-8-sig", newline="")
        reader = csv.reader(text)
        try:
            headers = next(reader)
        except StopIteration as exc:
            raise IngestError(f"empty CSV: {path}") from exc
        if not headers or len(headers) != len(set(headers)):
            raise IngestError(f"empty or duplicate CSV header: {path}: {headers}")
        for line_no, cells in enumerate(reader, start=2):
            if not cells or all(not cell.strip() for cell in cells):
                continue
            if strict_width and len(cells) != len(headers):
                raise IngestError(
                    f"unexpected field count in {path}:{line_no}: "
                    f"{len(cells)} != {len(headers)}"
                )
            row = {header: (cells[i] if i < len(cells) else None)
                   for i, header in enumerate(headers)}
            if len(cells) > len(headers):
                row["__extra_fields__"] = json.dumps(cells[len(headers):], ensure_ascii=False)
            yield headers, line_no, row, len(cells)


def _person_name(value) -> bool:
    value = (value or "").strip()
    letters = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ]", "", value)
    return len(letters) >= 3 and value.casefold() not in {"retired", "unknown"}


def _date(value) -> str | None:
    text = (value or "").strip()
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return dt.date.fromisoformat(text).isoformat()
        except ValueError:
            return None
    return None


def _meta_names(source: str, row: dict[str, str | None]):
    if SOURCES[source]["kind"] == "slam":
        return row.get("player1"), row.get("player2")
    return row.get("Player 1"), row.get("Player 2")


def _meta_score(source: str, row: dict[str, str | None]) -> int:
    p1, p2 = _meta_names(source, row)
    score = 100 if _person_name(p1) and _person_name(p2) else 0
    if SOURCES[source]["kind"] == "slam":
        if (row.get("year") or "").isdigit():
            score += 10
        if (row.get("round") or "").strip():
            score += 4
        if (row.get("event_name") or "").strip():
            score += 2
    else:
        if _date(row.get("Date")):
            score += 10
        if (row.get("Tournament") or "").strip():
            score += 5
        if (row.get("Round") or "").strip():
            score += 3
        if (row.get("Surface") or "").strip():
            score += 1
    return score


def _category_slam(row: dict[str, str | None], context_path: str) -> tuple[str, str]:
    raw = (row.get("event_name") or "").strip().casefold()
    if raw in {"event_ms", "men's singles", "mens singles"}:
        return "atp", "men's singles"
    if raw in {"event_ws", "women's singles", "womens singles"}:
        return "wta", "women's singles"
    if raw in {"event_md", "md"}:
        return "atp", "men's doubles"
    if raw in {"event_wd", "wd"}:
        return "wta", "women's doubles"
    if raw in {"event_xd", "xd"}:
        return "mixed", "mixed doubles"
    if "mixed" in raw:
        return "mixed", "mixed doubles"
    if "men" in raw and "double" in raw:
        return "atp", "men's doubles"
    if "women" in raw and "double" in raw:
        return "wta", "women's doubles"

    match_num = (row.get("match_num") or "").strip()
    prefix2 = match_num[:2].upper()
    if prefix2 == "MS":
        return "atp", "men's singles"
    if prefix2 == "WS":
        return "wta", "women's singles"
    if prefix2 == "MD":
        return "atp", "men's doubles"
    if prefix2 == "WD":
        return "wta", "women's doubles"
    if prefix2 == "XD":
        return "mixed", "mixed doubles"
    prefix = match_num[:1].upper()
    if prefix == "1":
        return "atp", "men's singles"
    if prefix == "2":
        return "wta", "women's singles"
    if prefix in {"M", "3"}:
        return "atp", "men's doubles"
    if prefix in {"W", "4"}:
        return "wta", "women's doubles"
    if prefix in {"X", "5"} or "-mixed" in context_path:
        return "mixed", "mixed doubles"
    raise IngestError(
        f"cannot assign Slam event category for {row.get('match_id')} "
        f"(event_name={row.get('event_name')!r}, match_num={match_num!r})"
    )


def _chosen_match(candidates: list[MatchMeta], source: str, match_id: str) -> MatchMeta:
    top_score = max(candidate.score for candidate in candidates)
    top = [candidate for candidate in candidates if candidate.score == top_score]
    identities = set()
    for candidate in top:
        p1, p2 = _meta_names(source, candidate.row)
        if _person_name(p1) and _person_name(p2):
            identities.add((p1.strip().casefold(), p2.strip().casefold()))
    if len(identities) > 1:
        raise IngestError(f"conflicting equally complete match metadata for {source}/{match_id}")
    # Keep the most complete candidate, with source order as a deterministic tie-break.
    chosen = dict(top[0].row)
    for candidate in sorted(candidates, key=lambda c: c.score, reverse=True):
        for key, value in candidate.row.items():
            if value not in (None, "") and chosen.get(key) in (None, ""):
                chosen[key] = value
    return MatchMeta(top[0].source_file, chosen, top_score)


def _match_paths(source: str, tree: list[dict]) -> tuple[list[str], list[str]]:
    all_paths = sorted(
        node["path"] for node in tree
        if node.get("type") == "blob" and node["path"].endswith(".csv")
    )
    if source == "grand_slam_archive":
        base = "slam_pointbypoint/"
        points = [p for p in all_paths if p.startswith(base)
                  and re.search(r"-points(?:-doubles|-mixed)?\.csv$", p)]
        matches = [p for p in all_paths if p.startswith(base)
                   and re.search(r"-matches(?:-doubles|-mixed)?\.csv$", p)]
    else:
        points = [p for p in all_paths if re.fullmatch(
            r"charting-[mw]-points-(?:to-2009|2010s|2020s)\.csv", p)]
        matches = [p for p in all_paths if re.fullmatch(r"charting-[mw]-matches\.csv", p)]
    if not points or not matches:
        raise IngestError(f"source files not found in pinned tree for {source}")
    if source == "grand_slam_archive":
        expected = {re.sub(r"-points(?=(-doubles|-mixed)?\.csv$)", "-matches", p) for p in points}
        if expected != set(matches):
            raise IngestError("Slam point/match file inventory does not pair exactly")
    return matches, points


def _build_plan(source: str) -> SourcePlan:
    spec = SOURCES[source]
    dataset = f"{spec['repo']}@{spec['commit']}"
    match_paths, point_paths = _match_paths(source, _tree(source))
    plan = SourcePlan(source, dataset, match_paths, point_paths)
    candidates: dict[str, list[MatchMeta]] = collections.defaultdict(list)
    field_counts = collections.Counter()

    for path in match_paths:
        for headers, line_no, row, width in _csv_rows(source, path, strict_width=False):
            plan.match_rows += 1
            field_counts[(len(headers), width)] += 1
            if width != len(headers):
                plan.malformed_match_rows += 1
                allowed = {11, 13} if source == "match_charting_project" else set()
                if width not in allowed:
                    raise IngestError(
                        f"unexpected match metadata field count in {path}:{line_no}: "
                        f"{width} != {len(headers)}"
                    )
            match_id = (row.get("match_id") or "").strip()
            if not match_id:
                raise IngestError(f"missing match_id in {path}:{line_no}")
            candidates[match_id].append(MatchMeta(path, row, _meta_score(source, row)))

    for match_id, entries in candidates.items():
        if len(entries) > 1:
            plan.duplicate_match_rows += len(entries) - 1
        plan.matches[match_id] = _chosen_match(entries, source, match_id)

    # Validate category resolution across the complete match inventory.
    for match_id, meta in plan.matches.items():
        row = meta.row
        if source == "grand_slam_archive":
            _category_slam(row, meta.source_file)
        else:
            if not re.match(r"^\d{8}-[MW]-", match_id):
                raise IngestError(f"unexpected charting match ID {match_id}")

    previous: dict[tuple[str, str], int] = {}
    for index, path in enumerate(point_paths, start=1):
        file_rows = 0
        for _, line_no, row, _ in _csv_rows(source, path, strict_width=True):
            file_rows += 1
            match_id = (row.get("match_id") or "").strip()
            if match_id not in plan.matches:
                raise IngestError(f"point row has no match metadata: {path}:{line_no}:{match_id}")
            point_id = (row.get("PointNumber") if source == "grand_slam_archive" else row.get("Pt"))
            point_id = (point_id or "").strip()
            if not point_id:
                raise IngestError(f"point row has no source point key: {path}:{line_no}")
            plan.point_match_ids.add(match_id)
            point_no = int(point_id) if point_id.isdigit() else None
            if source == "grand_slam_archive":
                is_point = int(
                    point_no is not None and point_no > 0
                    and (row.get("PointWinner") or "").strip() in {"1", "2"}
                )
                if not is_point:
                    if point_no == 0:
                        reason = "point_number_zero_setup"
                    elif point_no is None:
                        reason = f"non_numeric_setup_{point_id[-1:] or 'blank'}"
                    else:
                        reason = "missing_point_winner"
                    plan.nonpoint_reasons[reason] += 1
            else:
                is_point = int(
                    point_no is not None and point_no > 0
                    and (row.get("PtWinner") or "").strip() in {"1", "2"}
                )
                if not is_point:
                    plan.nonpoint_reasons["not_a_valid_charted_point"] += 1
            plan.point_rows += 1
            plan.played_points += is_point
            plan.nonpoint_rows += 1 - is_point
            plan.point_json_bytes += len(
                json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            )
            meta = plan.matches[match_id].row
            if source == "grand_slam_archive":
                year = _number(meta.get("year"), integer=True)
                tournament = {
                    "ausopen": "Australian Open", "frenchopen": "French Open",
                    "usopen": "US Open", "wimbledon": "Wimbledon",
                }.get((meta.get("slam") or "").strip().casefold(), "Unknown")
                _, category = _category_slam(meta, plan.matches[match_id].source_file)
            else:
                match_date = _date(meta.get("Date"))
                year = int(match_date[:4]) if match_date else int(match_id[:4])
                tournament = (meta.get("Tournament") or "Unknown").replace("_", " ").strip() or "Unknown"
                category = "men's charted match" if path.startswith("charting-m-") else "women's charted match"
            coverage_key = (year or 0, tournament, category)
            plan.coverage_rows[coverage_key] += 1
            plan.coverage_points[coverage_key] += is_point
            plan.coverage_matches.setdefault(coverage_key, set()).add(match_id)
            if is_point:
                if source == "grand_slam_archive":
                    tour, _ = _category_slam(plan.matches[match_id].row, path)
                else:
                    tour = "atp" if path.startswith("charting-m-") else "wta"
                plan.tours[tour] += 1
        plan.point_file_rows[path] = file_rows
        if index % 10 == 0 or index == len(point_paths):
            print(
                f"preflight {source}: {index}/{len(point_paths)} point files, "
                f"{plan.played_points:,} played points", flush=True
            )
    return plan


def _flag(row: dict[str, str | None], keys: tuple[str, ...]) -> int | None:
    present = [row[key] for key in keys if key in row]
    if not present or all(value in (None, "") for value in present):
        return None
    return int(any(str(value).strip().casefold() in {"1", "true", "yes", "y"}
                   for value in present if value not in (None, "")))


def _number(value, *, integer=False):
    text = (value or "").strip()
    if not text:
        return None
    try:
        number = float(text)
        if integer:
            return int(number) if number.is_integer() else None
        return number
    except (TypeError, ValueError):
        return None


def _split_point_score(value):
    text = (value or "").strip()
    if "-" not in text:
        return None, None
    player1, player2 = text.split("-", 1)
    return player1.strip() or None, player2.strip() or None


def _score_json(*, set_no=None, game_no=None, p1=None, p2=None, point_score=None):
    score = {}
    if set_no not in (None, ""):
        score["set"] = str(set_no)
    if game_no not in (None, ""):
        score["game"] = str(game_no)
    if p1 not in (None, ""):
        score["player1"] = str(p1)
    if p2 not in (None, ""):
        score["player2"] = str(p2)
    if point_score not in (None, ""):
        score["point_score"] = str(point_score)
    return json.dumps(score, ensure_ascii=False, sort_keys=True, separators=(",", ":")) if score else None


def _event_type(is_point, ace, double_fault, rally_winner, unforced_error, row):
    if not is_point:
        return "status"
    if double_fault:
        return "double_fault"
    if ace:
        return "ace"
    if unforced_error:
        return "unforced_error"
    sentence = " ".join(str(row.get(key) or "") for key in ("Sentence", "Notes")).casefold()
    if "forced error" in sentence:
        return "forced_error"
    if rally_winner:
        return "winner"
    return "point"


def _event_tuple(source: str, dataset: str, path: str, line_no: int,
                 row: dict[str, str | None], loaded_at: str, sequence_no: int,
                 previous_score: dict | None, player_names: tuple[str | None, str | None]):
    source_kind = SOURCES[source]["kind"]
    point_id = (row.get("PointNumber") if source_kind == "slam" else row.get("Pt")) or ""
    point_id = point_id.strip()
    point_no = int(point_id) if point_id.isdigit() else None
    if source_kind == "slam":
        winner = (row.get("PointWinner") or "").strip()
        server = (row.get("PointServer") or "").strip()
        is_point = int(point_no is not None and point_no > 0 and winner in {"1", "2"})
        set_no, game_no = row.get("SetNo"), row.get("GameNo")
        point_score, p1_score, p2_score = None, row.get("P1Score"), row.get("P2Score")
        serve_number = row.get("ServeIndicator") or row.get("ServeNumber")
        ace_keys = ("P1Ace", "P2Ace")
        df_keys = ("P1DoubleFault", "P2DoubleFault")
        winner_keys = ("P1Winner", "P2Winner")
        error_keys = ("P1UnfErr", "P2UnfErr")
        rally = row.get("Rally") or row.get("RallyCount")
        speed = row.get("Speed_KMH")
        first, second = None, None
    else:
        winner = (row.get("PtWinner") or "").strip()
        server = (row.get("Svr") or "").strip()
        is_point = int(point_no is not None and point_no > 0 and winner in {"1", "2"})
        if source_kind == "mcp":
            sets1 = _number(row.get("Set1"), integer=True)
            sets2 = _number(row.get("Set2"), integer=True)
            games1 = _number(row.get("Gm1"), integer=True)
            games2 = _number(row.get("Gm2"), integer=True)
            set_no = str(sets1 + sets2 + 1) if sets1 is not None and sets2 is not None else None
            game_no = str(games1 + games2 + 1) if games1 is not None and games2 is not None else None
            server_score, return_score = _split_point_score(row.get("Pts"))
            if server == "1":
                p1_score, p2_score = server_score, return_score
            elif server == "2":
                p1_score, p2_score = return_score, server_score
            else:
                p1_score = p2_score = None
            point_score = f"{p1_score}-{p2_score}" if p1_score is not None and p2_score is not None else None
        else:
            set_no, game_no = None, row.get("Gm#")
            point_score = row.get("Pts")
            p1_score, p2_score = _split_point_score(point_score)
        serve_number = None
        ace_keys = ("isAce",)
        df_keys = ("isDouble",)
        winner_keys = ("isRallyWinner",)
        error_keys = ("isUnforced",)
        rally = row.get("rallyCount") or row.get("RallyCount")
        speed = row.get("Speed_KMH")
        first, second = row.get("1st"), row.get("2nd")
    player1, player2 = player_names
    winner_name = player1 if winner == "1" else player2 if winner == "2" else None
    server_name = player1 if server == "1" else player2 if server == "2" else None
    ace = _flag(row, ace_keys)
    double_fault = _flag(row, df_keys)
    rally_winner = _flag(row, winner_keys)
    unforced_error = _flag(row, error_keys)
    if source_kind == "slam":
        after_json = _score_json(set_no=set_no, game_no=game_no, p1=p1_score, p2=p2_score)
        if is_point and previous_score is not None and (
            previous_score.get("set_no") == set_no and previous_score.get("game_no") == game_no
        ):
            before_json = previous_score.get("score_after_json")
        elif is_point:
            before_json = _score_json(set_no=set_no, game_no=game_no, p1="0", p2="0")
        else:
            before_json = None
        score_timing = "source_after"
    else:
        before_json = _score_json(set_no=None, game_no=game_no, p1=p1_score, p2=p2_score)
        after_json = None
        score_timing = "source_before"
    event_type = _event_type(is_point, ace, double_fault, rally_winner, unforced_error, row)
    raw_json = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (
        source, dataset, (row.get("match_id") or "").strip(), path, line_no,
        point_id, sequence_no, is_point, point_no, set_no, game_no, event_type,
        point_score, p1_score, p2_score, before_json, after_json, score_timing,
        None, None, None,
        winner or None, winner_name, server or None, server_name, (serve_number or None),
        ace, double_fault, rally_winner, unforced_error, _number(rally, integer=True), _number(speed),
        first or None, second or None, raw_json, loaded_at,
    )


def _match_tuple(source: str, dataset: str, match_id: str, meta: MatchMeta, loaded_at: str):
    spec = SOURCES[source]
    row = meta.row
    if source == "grand_slam_archive":
        tour, category = _category_slam(row, meta.source_file)
        year = _number(row.get("year"), integer=True)
        tournament = {
            "ausopen": "Australian Open", "frenchopen": "French Open",
            "usopen": "US Open", "wimbledon": "Wimbledon",
        }.get((row.get("slam") or "").strip().casefold())
        year_text = str(int(year)) if year is not None else "unknown"
        slam = (row.get("slam") or "unknown").strip().casefold()
        tournament_key = f"{year_text}-{slam}"
        p1, p2 = row.get("player1"), row.get("player2")
        partner1 = row.get("partner1") or row.get("player1_partner")
        partner2 = row.get("partner2") or row.get("player2_partner")
        p1id, p2id = row.get("player1id"), row.get("player2id")
        partner1id = row.get("partner1id") or row.get("player1_partner_id")
        partner2id = row.get("partner2id") or row.get("player2_partner_id")
        match_date = None
        round_name = row.get("round")
        surface = None
    else:
        tour = "atp" if meta.source_file.startswith("charting-m-") else "wta"
        category = "men's charted match" if tour == "atp" else "women's charted match"
        p1, p2 = row.get("Player 1"), row.get("Player 2")
        partner1 = partner2 = partner1id = partner2id = None
        p1id = p2id = None
        match_date = _date(row.get("Date"))
        year = int(match_date[:4]) if match_date else int(match_id[:4])
        tournament = (row.get("Tournament") or "").replace("_", " ").strip() or None
        tournament_key = tournament
        round_name = row.get("Round")
        surface = row.get("Surface")
    return (
        source, dataset, match_id, tour, category, year, match_date, tournament,
        tournament_key, round_name, surface, p1, p2, partner1, partner2, p1id, p2id,
        partner1id, partner2id, meta.source_file, spec["license"],
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")), loaded_at,
    )


def _validate_existing_schema(con: sqlite3.Connection):
    expected = {
        "tennis_point_sources": [
            "source", "source_dataset", "source_url", "source_commit", "source_license",
            "source_license_url", "loaded_at", "source_match_rows", "source_event_rows",
            "played_point_rows",
        ],
        "tennis_point_matches": [
            "id", "source", "source_dataset", "source_match_id", "tour", "event_category",
            "match_year", "match_date", "tournament_name", "tournament_key", "round", "surface",
            "player1_name", "player2_name", "player1_partner", "player2_partner",
            "player1_source_id", "player2_source_id", "player1_partner_source_id",
            "player2_partner_source_id", "source_file", "source_license", "raw_json", "loaded_at",
        ],
        "tennis_point_events": [
            "id", "source", "source_dataset", "source_match_id", "source_file", "source_row_no",
            "point_id", "sequence_no", "is_point", "point_no", "set_no", "game_no", "event_type",
            "point_score", "p1_score", "p2_score", "score_before_json", "score_after_json",
            "score_timing", "event_time_start_utc", "event_time_end_utc", "timestamp_precision",
            "point_winner", "point_winner_name", "point_server", "point_server_name",
            "serve_number", "is_ace", "is_double_fault",
            "is_rally_winner", "is_unforced_error", "rally_length", "serve_speed_kmh",
            "first_serve_sequence", "second_serve_sequence", "raw_json", "loaded_at",
        ],
    }
    for table, columns in expected.items():
        exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if exists:
            actual = [row[1] for row in con.execute(f"PRAGMA table_info({table})")]
            if actual != columns:
                raise IngestError(f"existing {table} schema differs: {actual}")


def _ensure_schema(con: sqlite3.Connection):
    con.execute(SOURCE_SCHEMA)
    con.execute(MATCH_SCHEMA)
    con.execute(EVENT_SCHEMA)
    _validate_existing_schema(con)


def _load_source(db_path: Path, plan: SourcePlan, loaded_at: str):
    con = sqlite3.connect(db_path, timeout=120)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=120000")
    try:
        con.execute("BEGIN IMMEDIATE")
        _ensure_schema(con)
        existing = con.execute(
            "SELECT COUNT(*) FROM tennis_point_events WHERE source=? AND source_dataset=?",
            (plan.source, plan.dataset),
        ).fetchone()[0]
        if existing:
            raise IngestError(
                f"refusing to append/reload {plan.source}@{plan.dataset}: already has {existing:,} rows"
            )
        con.executemany(
            MATCH_INSERT,
            (_match_tuple(plan.source, plan.dataset, mid, meta, loaded_at)
             for mid, meta in plan.matches.items()),
        )
        spec = SOURCES[plan.source]
        con.execute(
            "INSERT INTO tennis_point_sources (source,source_dataset,source_url,source_commit,"
            "source_license,source_license_url,loaded_at,source_match_rows,source_event_rows,"
            "played_point_rows) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                plan.source, plan.dataset,
                f"https://github.com/{spec['repo']}", spec["commit"], spec["license"],
                spec["license_url"], loaded_at, len(plan.matches), plan.point_rows,
                plan.played_points,
            ),
        )
        batch = []
        seen_file_rows = collections.Counter()
        match_sequences = collections.Counter()
        previous_scores = {}
        for index, path in enumerate(plan.point_paths, start=1):
            file_count = 0
            for _, line_no, row, _ in _csv_rows(plan.source, path, strict_width=True):
                match_id = (row.get("match_id") or "").strip()
                if match_id not in plan.matches:
                    raise IngestError(f"point metadata changed between passes: {path}:{line_no}")
                match_sequences[match_id] += 1
                sequence_no = match_sequences[match_id]
                if SOURCES[plan.source]["kind"] == "mcp":
                    source_point_no = _number(row.get("Pt"), integer=True)
                    if source_point_no is not None and source_point_no > 0:
                        sequence_no = source_point_no
                prior = previous_scores.get(match_id)
                batch.append(_event_tuple(
                    plan.source, plan.dataset, path, line_no, row, loaded_at,
                    sequence_no, prior,
                    _meta_names(plan.source, plan.matches[match_id].row),
                ))
                if SOURCES[plan.source]["kind"] == "slam" and (
                    (row.get("PointNumber") or "").isdigit()
                    and int(row["PointNumber"]) > 0
                    and (row.get("PointWinner") or "").strip() in {"1", "2"}
                ):
                    score_after = _score_json(
                        set_no=row.get("SetNo"), game_no=row.get("GameNo"),
                        p1=row.get("P1Score"), p2=row.get("P2Score"),
                    )
                    if score_after:
                        previous_scores[match_id] = {
                            "set_no": row.get("SetNo"), "game_no": row.get("GameNo"),
                            "score_after_json": score_after,
                        }
                file_count += 1
                if len(batch) >= BATCH_SIZE:
                    con.executemany(EVENT_INSERT, batch)
                    batch.clear()
            if file_count != plan.point_file_rows[path]:
                raise IngestError(
                    f"source row count changed for {path}: {file_count} != {plan.point_file_rows[path]}"
                )
            seen_file_rows[path] = file_count
            if index % 10 == 0 or index == len(plan.point_paths):
                print(
                    f"loading {plan.source}: {index}/{len(plan.point_paths)} files, "
                    f"{sum(seen_file_rows.values()):,} source rows", flush=True
                )
        if batch:
            con.executemany(EVENT_INSERT, batch)

        # These indexes also make source rows and real point sequences queryable.
        con.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_tennis_point_events_source_row "
            "ON tennis_point_events(source,source_dataset,source_file,source_row_no)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS ix_tennis_point_events_match_point "
            "ON tennis_point_events(source,source_dataset,source_match_id,is_point,sequence_no)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS ix_tennis_point_events_double_fault "
            "ON tennis_point_events(source,source_dataset,source_match_id) "
            "WHERE is_point=1 AND is_double_fault=1"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS ix_tennis_point_matches_tournament "
            "ON tennis_point_matches(tour,match_year,tournament_key)"
        )

        got = con.execute(
            "SELECT COUNT(*),SUM(is_point),COUNT(DISTINCT source_match_id) "
            "FROM tennis_point_events WHERE source=? AND source_dataset=?",
            (plan.source, plan.dataset),
        ).fetchone()
        if got != (plan.point_rows, plan.played_points, len({
            row[0] for row in con.execute(
                "SELECT DISTINCT source_match_id FROM tennis_point_events "
                "WHERE source=? AND source_dataset=?", (plan.source, plan.dataset)
            )
        })):
            raise IngestError(
                f"post-insert count mismatch for {plan.source}: "
                f"rows/points/matches={got}, expected rows={plan.point_rows:,}, "
                f"points={plan.played_points:,}"
            )
        missing_matches = con.execute(
            "SELECT COUNT(*) FROM tennis_point_events e LEFT JOIN tennis_point_matches m "
            "ON m.source=e.source AND m.source_dataset=e.source_dataset "
            "AND m.source_match_id=e.source_match_id "
            "WHERE e.source=? AND e.source_dataset=? AND m.id IS NULL",
            (plan.source, plan.dataset),
        ).fetchone()[0]
        if missing_matches:
            raise IngestError(f"{missing_matches:,} loaded point rows lack match metadata")
        quick = con.execute("PRAGMA quick_check(tennis_point_events)").fetchone()[0]
        if quick != "ok":
            raise IngestError(f"tennis_point_events quick_check failed: {quick}")
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _print_plan(plan: SourcePlan):
    missing_names = 0
    incomplete_point_matches = 0
    for match_id, meta in plan.matches.items():
        p1, p2 = _meta_names(plan.source, meta.row)
        if not _person_name(p1) or not _person_name(p2):
            missing_names += 1
            if match_id in plan.point_match_ids:
                incomplete_point_matches += 1
    print(
        f"{plan.source}: {len(plan.match_paths)} match files, {len(plan.point_paths)} point files, "
        f"{plan.match_rows:,} source match rows -> {len(plan.matches):,} unique matches, "
        f"{plan.duplicate_match_rows:,} duplicate metadata rows, "
        f"{plan.malformed_match_rows:,} malformed-width match rows"
    )
    print(
        f"  source point rows={plan.point_rows:,}; played points={plan.played_points:,}; "
        f"nonpoint/status rows={plan.nonpoint_rows:,}; tour counts={dict(plan.tours)}; "
        f"raw JSON payload={plan.point_json_bytes:,} bytes"
    )
    print(
        f"  matches with one or more participant names missing={missing_names:,}; "
        f"of those, matches referenced by point files={incomplete_point_matches:,}"
    )
    if plan.nonpoint_reasons:
        print(f"  excluded from played-point count but preserved: {dict(plan.nonpoint_reasons)}")


def _existing_complete(db_path: Path, plan: SourcePlan) -> bool:
    if not db_path.exists() or not db_path.stat().st_size:
        return False
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        _validate_existing_schema(con)
        source = con.execute(
            "SELECT source_event_rows,played_point_rows,source_match_rows "
            "FROM tennis_point_sources WHERE source=? AND source_dataset=?",
            (plan.source, plan.dataset),
        ).fetchone()
        event_rows, point_rows, matches = con.execute(
            "SELECT COUNT(*),SUM(is_point),COUNT(DISTINCT source_match_id) "
            "FROM tennis_point_events WHERE source=? AND source_dataset=?",
            (plan.source, plan.dataset),
        ).fetchone()
        quick = con.execute("PRAGMA quick_check").fetchone()[0]
        complete = (
            source == (plan.point_rows, plan.played_points, len(plan.matches))
            and event_rows == plan.point_rows and point_rows == plan.played_points
            and matches == len(plan.matches) and quick == "ok"
        )
        if not complete:
            raise IngestError(
                f"existing database is incomplete or differs from the pinned source: {db_path}; "
                f"source metadata={source}, events={(event_rows, point_rows, matches)}, quick_check={quick}"
            )
        return True
    except sqlite3.Error as exc:
        raise IngestError(f"cannot verify existing project database {db_path}: {exc}") from exc
    finally:
        if 'con' in locals():
            con.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["all", *SOURCES], default="all")
    parser.add_argument("--apply", action="store_true", help="write each project to its own database")
    args = parser.parse_args(argv)
    sources = list(SOURCES) if args.source == "all" else [args.source]
    plans = [_build_plan(source) for source in sources]
    for plan in plans:
        _print_plan(plan)
    if not args.apply:
        print(f"dry run only; no database changes (pass --apply to load under {ARCHIVE_DIR})")
        return 0

    total_raw = sum(plan.point_json_bytes for plan in plans)
    required = (2 * total_raw) + MIN_HEADROOM_BYTES
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(ARCHIVE_DIR).free
    if free < required:
        raise IngestError(
            f"insufficient free space: have {free:,} bytes, conservative requirement "
            f"{required:,} bytes (serialized rows x2 + 2 GiB headroom)"
        )

    for plan in plans:
        db_path = ARCHIVE_DIR / f"{plan.source}.db"
        if _existing_complete(db_path, plan):
            print(f"already loaded and verified {plan.source}: {db_path}", flush=True)
            continue
        if db_path.exists() and db_path.stat().st_size:
            raise IngestError(f"refusing to overwrite an existing project database: {db_path}")
        loaded_at = dt.datetime.now(dt.timezone.utc).isoformat()
        _load_source(db_path, plan, loaded_at)
        verify = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            quick = verify.execute("PRAGMA quick_check").fetchone()[0]
            counts = verify.execute(
                "SELECT is_point,COUNT(*) FROM tennis_point_events GROUP BY is_point ORDER BY is_point"
            ).fetchall()
            raw_missing = verify.execute(
                "SELECT COUNT(*) FROM tennis_point_events WHERE raw_json IS NULL"
            ).fetchone()[0]
            match_count = verify.execute("SELECT COUNT(*) FROM tennis_point_matches").fetchone()[0]
            if quick != "ok" or raw_missing or match_count != len(plan.matches):
                raise IngestError(
                    f"post-load verification failed for {db_path}: quick_check={quick}, "
                    f"raw_missing={raw_missing}, match_count={match_count}"
                )
            if sum(count for _, count in counts) != plan.point_rows:
                raise IngestError(f"post-load event row count mismatch for {db_path}: {counts}")
        finally:
            verify.close()
        print(
            f"loaded and verified {plan.source}: {db_path} ({db_path.stat().st_size:,} bytes); "
            f"matches={match_count:,}, events={counts}, quick_check={quick}", flush=True
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (IngestError, OSError, sqlite3.Error, urllib.error.URLError) as exc:
        print(f"ingest_historical_tennis_point_events: {exc}", file=sys.stderr)
        sys.exit(1)
