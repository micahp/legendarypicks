#!/usr/bin/env python3
"""Load archived Flashscore tennis point sequences into the dev database.

The archive reports point-score progressions grouped by game. This loader keeps
each reported sequence intact and does not infer individual point winners.
Runs in dry-run mode unless --apply is supplied.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import sqlite3
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit


REPO_ROOT = Path(__file__).resolve().parents[1]
DEV_DB = (REPO_ROOT / "backend/data/picks.dev.db").resolve()
DEFAULT_SOURCE = Path(
    "/root/tennis-records/flashscore-pbp-postcutoff-20261014/records-browser-v2"
)
SOURCE = "flashscore"
SOURCE_DATASET = "records-browser-v2-postcutoff-20261014"
MIN_FREE_BYTES = 128 * 1024 * 1024

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS tennis_points (
    id                       INTEGER PRIMARY KEY,
    source                   TEXT NOT NULL,
    source_dataset           TEXT NOT NULL,
    tour                     TEXT NOT NULL CHECK (tour IN ('atp','wta','itf')),
    source_match_id          TEXT NOT NULL,
    source_record_key        TEXT NOT NULL,
    record_kind              TEXT NOT NULL CHECK (record_kind IN ('match_status','game_sequence')),
    availability_status      TEXT NOT NULL,
    match_date               TEXT,
    player1_name             TEXT,
    player2_name             TEXT,
    source_player_ids_json   TEXT NOT NULL,
    point_no                 INTEGER,
    point_winner             TEXT,
    point_server             TEXT,
    set_no                   INTEGER,
    sequence_index           INTEGER,
    sequence_text            TEXT,
    scoreboard_source        TEXT,
    scoreboard_game_id       TEXT,
    scoreboard_match_method  TEXT,
    tournament_source        TEXT,
    tournament_id            TEXT,
    tournament_name          TEXT,
    source_match_url         TEXT,
    source_record_url        TEXT,
    source_file              TEXT NOT NULL,
    source_fetched_at        TEXT,
    loaded_at                TEXT NOT NULL,
    raw_json                 TEXT NOT NULL,
    UNIQUE (source, source_dataset, tour, source_match_id, source_record_key)
)
"""

INSERT_SQL = """
INSERT INTO tennis_points (
    source, source_dataset, tour, source_match_id, source_record_key,
    record_kind, availability_status, match_date, player1_name, player2_name,
    source_player_ids_json, point_no, point_winner, point_server, set_no,
    sequence_index, sequence_text, scoreboard_source, scoreboard_game_id,
    scoreboard_match_method, tournament_source, tournament_id, tournament_name,
    source_match_url, source_record_url, source_file, source_fetched_at,
    loaded_at, raw_json
) VALUES (
    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
    ?, ?, ?, ?, ?
)
ON CONFLICT (source, source_dataset, tour, source_match_id, source_record_key)
DO UPDATE SET
    record_kind=excluded.record_kind,
    availability_status=excluded.availability_status,
    match_date=excluded.match_date,
    player1_name=excluded.player1_name,
    player2_name=excluded.player2_name,
    source_player_ids_json=excluded.source_player_ids_json,
    point_no=excluded.point_no,
    point_winner=excluded.point_winner,
    point_server=excluded.point_server,
    set_no=excluded.set_no,
    sequence_index=excluded.sequence_index,
    sequence_text=excluded.sequence_text,
    scoreboard_source=excluded.scoreboard_source,
    scoreboard_game_id=excluded.scoreboard_game_id,
    scoreboard_match_method=excluded.scoreboard_match_method,
    tournament_source=COALESCE(excluded.tournament_source, tennis_points.tournament_source),
    tournament_id=COALESCE(excluded.tournament_id, tennis_points.tournament_id),
    tournament_name=COALESCE(excluded.tournament_name, tennis_points.tournament_name),
    source_match_url=excluded.source_match_url,
    source_record_url=excluded.source_record_url,
    source_file=excluded.source_file,
    source_fetched_at=excluded.source_fetched_at,
    loaded_at=excluded.loaded_at,
    raw_json=excluded.raw_json
"""


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _title_players_and_date(title: str | None):
    """Extract the participant segment, skipping any score prefix before `|`."""
    for segment in (title or "").split("|"):
        match = re.fullmatch(
            r"\s*(.+?)\s+v\s+(.+?)\s+(\d{2}/\d{2}/\d{4})\s*", segment
        )
        if match:
            player1, player2, date_text = match.groups()
            try:
                match_date = dt.datetime.strptime(date_text, "%d/%m/%Y").date().isoformat()
            except ValueError:
                continue
            return player1.strip(), player2.strip(), match_date
    return None, None, None


def _fallback_date(value):
    if not value:
        return None
    text = str(value).strip()
    for parser in (dt.date.fromisoformat,):
        try:
            return parser(text[:10]).isoformat()
        except ValueError:
            pass
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _source_player_ids(match_url: str | None) -> list[str]:
    if not match_url:
        return []
    parts = [part for part in urlsplit(match_url).path.split("/") if part]
    try:
        tennis_index = parts.index("tennis")
    except ValueError:
        return []
    if len(parts) <= tennis_index + 2:
        return []
    ids = []
    for slug in parts[tennis_index + 1:tennis_index + 3]:
        found = re.search(r"-([A-Za-z0-9]{6,12})$", slug)
        if not found:
            return []
        ids.append(found.group(1))
    return ids


def _normalize_name(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", ascii_name.lower())


# Each entry is backed by an official calendar or event page. Match labels from
# local scoreboards/research are used only when they agree with these references
# and the match date falls inside the published event window.
_TOURNAMENT_REFERENCES = {
    ("atp", _normalize_name("National Bank Open presented by Rogers")): {
        "name": "National Bank Open presented by Rogers",
        "source": "atp_calendar+scoreboard_crosswalk",
        "source_url": "https://www.atptour.com/en/news/what-is-the-2026-atp-tour-calendar/",
        "start": "2026-08-02", "end": "2026-08-13", "id": None,
    },
    ("wta", _normalize_name("National Bank Open presented by Rogers")): {
        "name": "National Bank Open presented by Rogers",
        "source": "wta_calendar+scoreboard_crosswalk",
        "source_url": "https://wtafiles.wtatennis.com/pdf/calendar/calendar.pdf",
        "start": "2026-08-03", "end": "2026-08-13", "id": None,
    },
    ("atp", _normalize_name("Cincinnati Open")): {
        "name": "Cincinnati Open",
        "source": "atp_calendar+scoreboard_crosswalk",
        "source_url": "https://www.atptour.com/en/news/cincinnati-2026-atp-masters-1000-history-draw-schedule",
        "start": "2026-08-11", "end": "2026-08-23", "id": "422",
    },
    ("wta", _normalize_name("Cincinnati Open")): {
        "name": "Cincinnati Open",
        "source": "wta_calendar+scoreboard_crosswalk",
        "source_url": "https://wtafiles.wtatennis.com/pdf/calendar/calendar.pdf",
        "start": "2026-08-10", "end": "2026-08-23", "id": None,
    },
    ("atp", _normalize_name("Rolex Shanghai Masters")): {
        "name": "Rolex Shanghai Masters",
        "source": "atp_calendar+scoreboard_crosswalk",
        "source_url": "https://www.atptour.com/en/news/what-is-the-2026-atp-tour-calendar/",
        "start": "2026-10-07", "end": "2026-10-18", "id": None,
    },
    ("itf", _normalize_name("ITF M15 Bol (CRO)")): {
        "name": "M15 Bol",
        "source": "itf_official_event+match_research",
        "source_url": "https://www.itftennis.com/en/tournament/m15-bol/cro/2026/m-itf-cro-2026-008/draws-and-results/",
        "start": "2026-10-12", "end": "2026-10-18", "id": "M-ITF-CRO-2026-008",
    },
    ("itf", _normalize_name("ITF M15 Sharm ElSheikh (EGY)")): {
        "name": "M15 Sharm ElSheikh",
        "source": "itf_official_event+match_research",
        "source_url": "https://www.itftennis.com/en/tournament/m15-sharm-elsheikh/egy/2026/m-itf-egy-2026-017/draws-and-results/",
        "start": "2026-10-12", "end": "2026-10-18", "id": "M-ITF-EGY-2026-017",
    },
    ("itf", _normalize_name("ITF W15 Maceio (BRA)")): {
        "name": "W15 Maceio",
        "source": "itf_official_event+match_research",
        "source_url": "https://www.itftennis.com/en/tournament/w15-maceio/bra/2026/w-itf-bra-2026-008/draws-and-results/",
        "start": "2026-10-12", "end": "2026-10-18", "id": "W-ITF-BRA-2026-008",
    },
    ("itf", _normalize_name("ITF W15 Shenzhen (CHN)")): {
        "name": "W15 Shenzhen",
        "source": "itf_official_event+match_research",
        "source_url": "https://www.itftennis.com/en/tournament/w15-shenzhen/chn/2026/w-itf-chn-2026-037/draws-and-results/",
        "start": "2026-10-12", "end": "2026-10-18", "id": "W-ITF-CHN-2026-037",
    },
    ("atp", _normalize_name("ATP Cincinnati")): {
        "name": "Cincinnati Open",
        "source": "atp_calendar+match_research",
        "source_url": "https://www.atptour.com/en/news/cincinnati-2026-atp-masters-1000-history-draw-schedule",
        "start": "2026-08-11", "end": "2026-08-23", "id": "422",
    },
}


def _tournament_reference(tour, match_date, scoreboard_event, data):
    """Return a date-checked official tournament reference, when available."""
    research_event = ((data.get("match_metadata") or {}).get("event") or "").strip()
    candidates = []
    if scoreboard_event:
        candidates.append((tour, _normalize_name(scoreboard_event)))
    if research_event:
        candidates.append((tour, _normalize_name(research_event)))
    for key in candidates:
        reference = _TOURNAMENT_REFERENCES.get(key)
        if reference and match_date and reference["start"] <= match_date <= reference["end"]:
            return reference
    return None


def _scoreboard_candidates(con: sqlite3.Connection):
    candidates = {}
    query = """
        SELECT league, game_date, game_id, payload, source
        FROM scoreboard_snapshots
        WHERE LOWER(league) IN ('atp','wta')
    """
    for league, game_date, game_id, payload, source in con.execute(query):
        try:
            data = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            continue
        home = (data.get("home") or {}).get("name")
        away = (data.get("away") or {}).get("name")
        if not home or not away:
            continue
        key = (
            str(league).lower(),
            str(game_date),
            tuple(sorted((_normalize_name(home), _normalize_name(away)))),
        )
        entry_key = (str(source) if source else None, str(game_id))
        entry = (*entry_key, str(data.get("event") or "").strip() or None)
        candidates.setdefault(key, {})[entry_key] = entry
    return candidates


def _choose_archive_records(source_dir: Path):
    selected = {}
    total_files = 0
    for path in sorted(source_dir.rglob("*.json")):
        total_files += 1
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read archive record {path}: {exc}") from exc
        tour = str(data.get("tour") or "").strip().lower()
        match_id = str(data.get("match_id") or "").strip()
        if tour not in {"atp", "wta", "itf"} or not match_id:
            raise ValueError(f"missing/invalid tour or match_id in {path}")
        status = str(data.get("status") or "").strip().lower()
        if status not in {
            "has_point_history", "no_point_history", "walkover",
            "no_points_played_walkover",
        }:
            raise ValueError(f"unexpected match status {status!r} in {path}")
        key = (tour, match_id)
        path_rel = path.relative_to(source_dir).as_posix()
        richness = (
            status == "has_point_history",
            status in {"walkover", "no_points_played_walkover"},
            bool(data.get("date")),
            len(data.get("point_feed_responses") or []),
            len(data.get("sets") or []),
            path_rel,
        )
        previous = selected.get(key)
        if previous is None or richness > previous[0]:
            selected[key] = (richness, data, path_rel)
    return total_files, {
        key: value[1:] for key, value in selected.items()
    }


def _feed_sequences(data, path_rel):
    responses = [
        item for item in (data.get("point_feed_responses") or [])
        if item.get("status") == 200 and item.get("body")
    ]
    if len(responses) != 1:
        raise ValueError(
            f"{path_rel}: expected one nonempty HTTP 200 point feed, got {len(responses)}"
        )
    response = responses[0]
    body = response["body"]
    active_set = None
    sequence_index = 0
    sequences = []
    for raw_row in body.split("~"):
        fields = {}
        for item in raw_row.split("¬"):
            if "÷" in item:
                key, value = item.split("÷", 1)
                fields[key] = value
        header = fields.get("HA", "")
        set_match = re.fullmatch(r"Set\s+(\d+)", header.strip(), flags=re.IGNORECASE)
        if set_match:
            active_set = int(set_match.group(1))
            sequence_index = 0
        if "HL" in fields:
            if active_set is None:
                raise ValueError(f"{path_rel}: point sequence before set header")
            sequence_index += 1
            sequences.append({
                "set_no": active_set,
                "sequence_index": sequence_index,
                "sequence_text": fields["HL"],
                "raw_row": raw_row,
            })
    if not sequences:
        raise ValueError(f"{path_rel}: point-history record contains no HL sequences")
    return response, sequences


def prepare(source_dir: Path, con: sqlite3.Connection):
    total_files, records = _choose_archive_records(source_dir)
    scoreboard = _scoreboard_candidates(con)
    prepared = []
    matched_games = set()
    source_id_count = 0
    sequence_total = 0
    status_counts = {}
    unresolved = 0
    tournament_links = 0
    tournament_updates = []
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    for (tour, match_id), (data, source_file) in sorted(records.items()):
        status = str(data["status"]).strip().lower()
        status_counts[status] = status_counts.get(status, 0) + 1
        player1, player2, match_date = _title_players_and_date(data.get("page_title"))
        if not match_date:
            match_date = _fallback_date(data.get("date"))
        ids = _source_player_ids(data.get("match_url"))
        if ids:
            source_id_count += 1

        match_key = None
        if tour in ("atp", "wta") and match_date and player1 and player2:
            match_key = (
                tour,
                match_date,
                tuple(sorted((_normalize_name(player1), _normalize_name(player2)))),
            )
        candidates = list(scoreboard.get(match_key, {}).values()) if match_key else []
        if len(candidates) == 1:
            scoreboard_source, scoreboard_game_id, scoreboard_event = candidates[0]
            scoreboard_method = "unique_exact_tour_date_player_pair"
            matched_games.add((tour, scoreboard_game_id))
        else:
            scoreboard_source = scoreboard_game_id = scoreboard_method = None
            scoreboard_event = None
            unresolved += 1

        tournament = _tournament_reference(
            tour, match_date, scoreboard_event, data
        )
        if tournament:
            tournament_links += 1
        common = {
            "source": SOURCE,
            "source_dataset": SOURCE_DATASET,
            "tour": tour,
            "source_match_id": match_id,
            "availability_status": status,
            "match_date": match_date,
            "player1_name": player1,
            "player2_name": player2,
            "source_player_ids_json": _json(ids),
            "scoreboard_source": scoreboard_source,
            "scoreboard_game_id": scoreboard_game_id,
            "scoreboard_match_method": scoreboard_method,
            "tournament_source": tournament["source"] if tournament else None,
            "tournament_id": tournament["id"] if tournament else None,
            "tournament_name": tournament["name"] if tournament else None,
            "source_match_url": data.get("match_url"),
            "source_file": source_file,
            "source_fetched_at": data.get("checked_at"),
            "loaded_at": now,
        }
        status_raw = {
            key: data.get(key) for key in (
                "status", "page_title", "date", "navigation_status",
                "availability_assessment", "set_count", "point_sequence_count",
                "game_row_count", "source",
            ) if key in data
        }
        if tournament:
            status_raw["tournament_reference_url"] = tournament["source_url"]
            status_raw["tournament_reference_source"] = tournament["source"]
            tournament_updates.append({
                "source": common["source"],
                "source_dataset": common["source_dataset"],
                "tour": tour,
                "source_match_id": match_id,
                "tournament_source": tournament["source"],
                "tournament_id": tournament["id"],
                "tournament_name": tournament["name"],
                "raw_json": _json(status_raw),
            })
        prepared.append(_row(
            common,
            record_key="match_status",
            record_kind="match_status",
            source_record_url=data.get("point_history_url") or data.get("match_url"),
            raw_json=_json(status_raw),
        ))

        if status == "has_point_history":
            response, sequences = _feed_sequences(data, source_file)
            for sequence in sequences:
                sequence_total += 1
                prepared.append(_row(
                    common,
                    record_key=(
                        f"set-{sequence['set_no']}-sequence-{sequence['sequence_index']}"
                    ),
                    record_kind="game_sequence",
                    source_record_url=response.get("url"),
                    set_no=sequence["set_no"],
                    sequence_index=sequence["sequence_index"],
                    sequence_text=sequence["sequence_text"],
                    raw_json=_json({
                        "feed_url": response.get("url"),
                        "raw_row": sequence["raw_row"],
                    }),
                ))

    return {
        "rows": prepared,
        "source_files": total_files,
        "matches": len(records),
        "status_counts": status_counts,
        "game_sequences": sequence_total,
        "scoreboard_matches": len(matched_games),
        "scoreboard_unresolved_matches": unresolved,
        "source_player_ids": source_id_count,
        "tournament_links": tournament_links,
        "tournament_updates": tournament_updates,
    }


def _row(common, record_key, record_kind, source_record_url, raw_json,
         set_no=None, sequence_index=None, sequence_text=None):
    values = {
        **common,
        "source_record_key": record_key,
        "record_kind": record_kind,
        "source_record_url": source_record_url,
        "set_no": set_no,
        "sequence_index": sequence_index,
        "sequence_text": sequence_text,
        "raw_json": raw_json,
    }
    columns = (
        "source", "source_dataset", "tour", "source_match_id", "source_record_key",
        "record_kind", "availability_status", "match_date", "player1_name", "player2_name",
        "source_player_ids_json", "point_no", "point_winner", "point_server", "set_no",
        "sequence_index", "sequence_text", "scoreboard_source", "scoreboard_game_id",
        "scoreboard_match_method", "tournament_source", "tournament_id", "tournament_name",
        "source_match_url", "source_record_url", "source_file", "source_fetched_at",
        "loaded_at", "raw_json",
    )
    return tuple(values.get(column) for column in columns)


def _ensure_dev_db():
    if DEV_DB != (REPO_ROOT / "backend/data/picks.dev.db").resolve():
        raise RuntimeError("refusing a database path other than picks.dev.db")
    if not DEV_DB.is_file():
        raise FileNotFoundError(f"development database not found: {DEV_DB}")


def _check_free_space(source_dir: Path):
    archive_bytes = sum(path.stat().st_size for path in source_dir.rglob("*.json"))
    free_bytes = shutil.disk_usage(DEV_DB.parent).free
    minimum = max(MIN_FREE_BYTES, 2 * archive_bytes)
    if free_bytes < minimum:
        raise RuntimeError(
            f"only {free_bytes:,} bytes free; need at least {minimum:,} for safe ingest"
        )


def _open_db(readonly: bool):
    if readonly:
        return sqlite3.connect(f"file:{DEV_DB}?mode=ro", uri=True)
    return sqlite3.connect(str(DEV_DB), timeout=30)


def _verify_schema(con):
    existing = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tennis_points'"
    ).fetchone()
    if not existing:
        return
    expected = [
        "id", "source", "source_dataset", "tour", "source_match_id",
        "source_record_key", "record_kind", "availability_status", "match_date",
        "player1_name", "player2_name", "source_player_ids_json", "point_no",
        "point_winner", "point_server", "set_no", "sequence_index", "sequence_text",
        "scoreboard_source", "scoreboard_game_id", "scoreboard_match_method",
        "tournament_source", "tournament_id", "tournament_name", "source_match_url",
        "source_record_url", "source_file", "source_fetched_at", "loaded_at", "raw_json",
    ]
    actual = [row[1] for row in con.execute("PRAGMA table_info(tennis_points)")]
    if actual != expected:
        raise RuntimeError(f"existing tennis_points schema differs: {actual}")


def _apply(rows, source_dir):
    _check_free_space(source_dir)
    con = _open_db(readonly=False)
    try:
        con.execute("BEGIN IMMEDIATE")
        _verify_schema(con)
        con.execute(TABLE_SQL)
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_tennis_points_match "
            "ON tennis_points(tour, source_match_id, record_kind)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_tennis_points_scoreboard "
            "ON tennis_points(scoreboard_source, scoreboard_game_id) "
            "WHERE scoreboard_game_id IS NOT NULL"
        )
        con.executemany(INSERT_SQL, rows)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _apply_tournament_enrichment(updates, source_dir):
    _check_free_space(source_dir)
    con = _open_db(readonly=False)
    updated_rows = 0
    try:
        con.execute("BEGIN IMMEDIATE")
        _verify_schema(con)
        for update in updates:
            key = (
                update["source"], update["source_dataset"], update["tour"],
                update["source_match_id"],
            )
            existing = con.execute(
                "SELECT DISTINCT tournament_id, tournament_name FROM tennis_points "
                "WHERE source=? AND source_dataset=? AND tour=? AND source_match_id=? "
                "AND (tournament_id IS NOT NULL OR tournament_name IS NOT NULL)",
                key,
            ).fetchall()
            for old_id, old_name in existing:
                if old_name and old_name != update["tournament_name"]:
                    raise RuntimeError(
                        f"tournament name conflict for {key}: {old_name!r} vs "
                        f"{update['tournament_name']!r}"
                    )
                if old_id and update["tournament_id"] and old_id != update["tournament_id"]:
                    raise RuntimeError(
                        f"tournament ID conflict for {key}: {old_id!r} vs "
                        f"{update['tournament_id']!r}"
                    )
            cursor = con.execute(
                "UPDATE tennis_points SET tournament_source=?, "
                "tournament_id=COALESCE(?, tournament_id), tournament_name=?, "
                "raw_json=CASE WHEN record_kind='match_status' THEN ? ELSE raw_json END "
                "WHERE source=? AND source_dataset=? AND tour=? AND source_match_id=?",
                (
                    update["tournament_source"], update["tournament_id"],
                    update["tournament_name"], update["raw_json"], *key,
                ),
            )
            if cursor.rowcount == 0:
                raise RuntimeError(f"no tennis_points rows found for {key}")
            updated_rows += cursor.rowcount
        con.commit()
        return updated_rows
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _print_summary(summary):
    print(f"Source files: {summary['source_files']}")
    print(f"Unique tour/match records: {summary['matches']}")
    print(f"Record statuses: {json.dumps(summary['status_counts'], sort_keys=True)}")
    print(f"Game point-score sequences: {summary['game_sequences']}")
    print(f"Unique exact scoreboard match links: {summary['scoreboard_matches']}")
    print(f"Unlinked matches: {summary['scoreboard_unresolved_matches']}")
    print(f"Matches with source player IDs: {summary['source_player_ids']}")
    print(f"Matches with verified tournament references: {summary['tournament_links']}")
    print(f"Rows to upsert: {len(summary['rows'])}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    write_group = parser.add_mutually_exclusive_group()
    write_group.add_argument(
        "--apply", action="store_true", help="write all prepared rows to the dev database"
    )
    write_group.add_argument(
        "--apply-tournament-enrichment", action="store_true",
        help="write only verified tournament metadata to existing dev rows",
    )
    args = parser.parse_args(argv)
    _ensure_dev_db()
    source_dir = args.source_dir.resolve()
    if not source_dir.is_dir():
        parser.error(f"source directory does not exist: {source_dir}")
    if args.apply or args.apply_tournament_enrichment:
        _check_free_space(source_dir)
    with _open_db(readonly=True) as con:
        _verify_schema(con)
        summary = prepare(source_dir, con)
    _print_summary(summary)
    if not args.apply and not args.apply_tournament_enrichment:
        print("Dry run only; pass a write flag to update the development database.")
        return 0
    if args.apply_tournament_enrichment:
        rows_updated = _apply_tournament_enrichment(
            summary["tournament_updates"], source_dir
        )
        print(f"Updated {len(summary['tournament_updates'])} match records.")
        print(f"Updated {rows_updated} tennis_points rows (match and sequence records).")
        return 0
    _apply(summary["rows"], source_dir)
    with _open_db(readonly=True) as con:
        counts = con.execute(
            "SELECT record_kind, COUNT(*) FROM tennis_points "
            "WHERE source=? AND source_dataset=? GROUP BY record_kind ORDER BY record_kind",
            (SOURCE, SOURCE_DATASET),
        ).fetchall()
        check = con.execute("PRAGMA quick_check(tennis_points)").fetchone()[0]
    print(f"Committed to {DEV_DB}")
    print(f"Stored row counts: {json.dumps(counts)}")
    print(f"tennis_points quick_check: {check}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"ingest_tennis_points: {error}", file=sys.stderr)
        sys.exit(1)
