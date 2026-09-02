#!/usr/bin/env python3
"""Publish MLS PrizePicks thresholds relayed by RotoWire.

This is deliberately a *publisher*, not a screen scraper.  A source player is
only admitted after its RotoWire profile key is bound to a canonical player and
its source fixture is matched exactly to an ESPN MLS event.  The relay's
``over`` and ``under`` fields are More/Less selections, not American odds, so
the persisted rows always keep ``odds`` NULL.

Usage:
  LP_DB_PATH=/path/to/picks.dev.db python ingest_rotowire_mls_props.py mls
  LP_DB_PATH=/path/to/picks.dev.db python ingest_rotowire_mls_props.py mls --dry-run
"""
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import sys
import urllib.request
from collections import Counter, defaultdict
from contextlib import closing
from typing import Dict, Iterable, List, Optional, Tuple

import espn_client as espn
from link_prop_games import _instant, _norm_team
from prop_source_identity import (
    SourceIdentityConflict,
    bind_player_source_key as _bind_player_source_key,
    ensure_source_identity_schema as _ensure_source_identity_schema,
    normalize_name,
    queue_unresolved_player as _queue_unresolved_player,
)


DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)
API = "https://www.rotowire.com/picks/api/lines.php"
SOURCE = "rotowire_prizepicks_relay"
LEAGUE = "mls"
PARSER_VERSION = "1"
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "LegendaryPicks MLS published-data ingest/1.0",
}

# These are source labels, not guesses based on display text.  A new provider
# market stays out of the board until a reviewed mapping is added here.
MARKETS = {
    "Shots": "shots",
    "Shots on Target": "shots_on_target",
    "Passes Attempted": "passes_attempted",
    "Saves": "saves",
    "Clearances": "clearances",
    "Tackles": "tackles",
    "Crosses": "crosses",
}
_PROFILE_ID = re.compile(r"-(\d+)(?:/)?$")


def fetch_raw() -> Tuple[bytes, Dict]:
    """Fetch one board only; callers reuse the returned body for all parsing."""
    request = urllib.request.Request(API, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
    return body, json.loads(body.decode("utf-8"))


def ensure_source_identity_schema(con: sqlite3.Connection) -> None:
    """Install only additive identity/provenance tables required by this source."""
    _ensure_source_identity_schema(con)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS prop_source_captures(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source TEXT NOT NULL, league TEXT NOT NULL,
          captured_at TEXT NOT NULL, status TEXT NOT NULL,
          payload_sha256 TEXT NOT NULL, payload_path TEXT,
          source_url TEXT NOT NULL DEFAULT '', parser_version TEXT NOT NULL DEFAULT '',
          source_prop_count INTEGER NOT NULL DEFAULT 0,
          candidate_event_count INTEGER NOT NULL DEFAULT 0,
          eligible_event_count INTEGER NOT NULL DEFAULT 0,
          rejected_event_count INTEGER NOT NULL DEFAULT 0,
          market_counts_json TEXT NOT NULL DEFAULT '{}',
          rejected_reasons_json TEXT NOT NULL DEFAULT '{}', message TEXT);
        CREATE INDEX IF NOT EXISTS idx_prop_source_captures_latest
          ON prop_source_captures(source, league, captured_at DESC);
    """)
    capture_columns = {row[1] for row in con.execute("PRAGMA table_info(prop_source_captures)")}
    for column, declaration in (
        ("source_url", "TEXT NOT NULL DEFAULT ''"),
        ("parser_version", "TEXT NOT NULL DEFAULT ''"),
        ("rejected_reasons_json", "TEXT NOT NULL DEFAULT '{}'")
    ):
        if column not in capture_columns:
            con.execute("ALTER TABLE prop_source_captures ADD COLUMN {} {}".format(column, declaration))


def _index(rows: Iterable[Dict], field: str) -> Dict[str, Dict]:
    result = {}
    for row in rows:
        key = row.get(field)
        if key is None:
            continue
        key = str(key)
        if key in result:
            raise ValueError("duplicate {} {} in RotoWire payload".format(field, key))
        result[key] = row
    return result


def _source_player_key(entity: Dict) -> Optional[str]:
    match = _PROFILE_ID.search(str(entity.get("link") or ""))
    return "rotowire-profile:" + match.group(1) if match else None


def _event_time(value) -> Optional[str]:
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value, dt.timezone.utc).isoformat().replace("+00:00", "Z")
    text = str(value or "").strip()
    return text if _instant(text) else None


def parse_board(data: Dict) -> Tuple[List[Dict], Dict]:
    """Parse source records without resolving a player or inferring a fixture.

    Events are kept separate because one bad supported player rejects the whole
    fixture.  That is safer than publishing an apparently complete matchup with
    an unreviewed identity omitted.
    """
    markets = _index(data.get("markets") or [], "marketID")
    entities = _index(data.get("entities") or [], "entityID")
    source_events = _index(data.get("events") or [], "eventID")
    events: Dict[str, Dict] = {}
    counts = Counter()
    counts["payload_props"] = len(data.get("props") or [])

    for source_prop in data.get("props") or []:
        # The observed endpoint normally nests book offers in ``lines``.  Keep
        # the flat fallback for captures from the older relay shape, but never
        # assume a parent prop itself is a PrizePicks offer when it has lines.
        source_lines = source_prop.get("lines") if isinstance(source_prop, dict) else None
        line_records = source_lines if isinstance(source_lines, list) else [source_prop]
        for source_line in line_records:
            if not isinstance(source_line, dict):
                counts["malformed_props"] += 1
                continue
            prop = dict(source_prop)
            prop.update(source_line)
            prop["entities"] = source_line.get("entities") or source_prop.get("entities") or []
            if str(prop.get("book") or "").lower() != "prizepicks":
                continue
            market = markets.get(str(prop.get("marketID")))
            entity_ids = prop.get("entities") or []
            entity = entities.get(str(entity_ids[0])) if len(entity_ids) == 1 else None
            if not market or not entity or str(entity.get("sport") or "").lower() != "soccer":
                continue
            source_event = source_events.get(str(entity.get("eventID")))
            if not source_event:
                counts["malformed_props"] += 1
                continue
            source_key = str(source_event.get("eventID"))
            event = events.setdefault(source_key, {
                "source_game_key": source_key,
                "home": source_event.get("homeTeam") or source_event.get("home") or "",
                "away": source_event.get("awayTeam") or source_event.get("away") or "",
                "start_time": _event_time(
                    source_event.get("eventTime") or source_event.get("startTime") or source_event.get("date")
                ),
                "props": [],
                "invalid": False,
            })
            counts["soccer_prizepicks_props"] += 1
            source_market = str(market.get("marketName") or market.get("name") or "")
            counts["source_market:" + source_market] += 1
            canonical_market = MARKETS.get(source_market)
            if not canonical_market:
                counts["unsupported_props"] += 1
                continue

            player_key = _source_player_key(entity)
            try:
                line = float(prop["line"])
            except (KeyError, TypeError, ValueError):
                line = None
            # Keep the event but reject it later if one supported record lacks the
            # identity or selection fields needed to publish a complete threshold.
            if (not player_key or not entity.get("name") or not entity.get("team")
                    or line is None or "over" not in prop or "under" not in prop):
                event["invalid"] = True
                counts["malformed_supported_props"] += 1
                continue
            event["props"].append({
                "source_player_key": player_key,
                "player_name": entity["name"].strip(),
                "team": entity["team"].strip(),
                "position": str(entity.get("pos") or "").strip(),
                "market": canonical_market,
                "line": line,
            })
            counts["supported_props"] += 1
            counts["market:" + canonical_market] += 1

    return list(events.values()), dict(counts)


def _dates_to_check(events: Iterable[Dict]) -> List[str]:
    dates = set()
    for event in events:
        parsed = _instant(event.get("start_time"))
        if not parsed:
            continue
        for offset in (-1, 0, 1):
            dates.add((parsed.date() + dt.timedelta(days=offset)).isoformat())
    return sorted(dates)


def load_espn_games(events: Iterable[Dict]) -> List[Dict]:
    """Fetch only UTC match days adjacent to the captured source fixtures."""
    games = []
    seen = set()
    for date in _dates_to_check(events):
        for game in espn.games(LEAGUE, date):
            key = str(game.get("game_id") or "")
            if key and key not in seen:
                seen.add(key)
                games.append(game)
    return games


def match_espn_event(event: Dict, espn_games: Iterable[Dict]) -> Tuple[Optional[Dict], str]:
    """Match source home/away and start instant exactly; never guess an MLS club."""
    home = _norm_team(event.get("home") or "", LEAGUE)
    away = _norm_team(event.get("away") or "", LEAGUE)
    start = _instant(event.get("start_time"))
    if not home or not away:
        return None, "unknown_source_team"
    if not start:
        return None, "missing_source_start_time"
    candidates = []
    for game in espn_games:
        game_home = _norm_team((game.get("home") or {}).get("abbrev") or "", LEAGUE)
        game_away = _norm_team((game.get("away") or {}).get("abbrev") or "", LEAGUE)
        if game_home == home and game_away == away and _instant(game.get("date")) == start:
            candidates.append(game)
    if not candidates:
        return None, "no_exact_espn_fixture"
    if len(candidates) != 1:
        return None, "ambiguous_espn_fixture"
    return candidates[0], "exact_espn_fixture"


def queue_unresolved_player(
    con: sqlite3.Connection, source_player_key: str, name: str, team: str, reason: str
) -> None:
    _queue_unresolved_player(
        con, source=SOURCE, league=LEAGUE, source_player_key=source_player_key,
        player_name=name, team=team, reason=reason,
    )


def _matches_player(row: sqlite3.Row, prop: Dict) -> bool:
    if _norm_team(row["team"] or "", LEAGUE) != _norm_team(prop["team"], LEAGUE):
        return False
    source_position = prop.get("position") or ""
    canonical_position = row["position"] or ""
    return not source_position or not canonical_position or source_position.upper() == canonical_position.upper()


def resolve_player(con: sqlite3.Connection, prop: Dict) -> Tuple[Optional[int], str]:
    """Resolve an MLS player by source ID, exact canonical name, or reviewed alias."""
    source_key = prop["source_player_key"]
    mapped = con.execute(
        "SELECT p.id,p.name,p.team,p.position FROM player_source_ids psi "
        "JOIN players p ON p.id=psi.player_id WHERE psi.source=? AND psi.league=? "
        "AND psi.source_player_key=? AND p.league=?",
        (SOURCE, LEAGUE, source_key, LEAGUE),
    ).fetchall()
    if len(mapped) > 1:
        raise SourceIdentityConflict("source player key {} has multiple mappings".format(source_key))
    if mapped:
        if _matches_player(mapped[0], prop):
            return mapped[0]["id"], "source_key"
        raise SourceIdentityConflict("source player key {} no longer matches canonical team or position".format(source_key))

    candidates = [
        row for row in con.execute(
            "SELECT id,name,team,position FROM players WHERE league=? ORDER BY id", (LEAGUE,)
        ).fetchall()
        if normalize_name(row["name"]) == normalize_name(prop["player_name"]) and _matches_player(row, prop)
    ]
    if len(candidates) == 1:
        return candidates[0]["id"], "exact_name_team_position"
    if len(candidates) > 1:
        queue_unresolved_player(con, source_key, prop["player_name"], prop["team"], "ambiguous_exact_identity")
        return None, "ambiguous_exact_identity"

    aliases = [
        row for row in con.execute(
            "SELECT DISTINCT p.id,p.name,p.team,p.position FROM name_alias na "
            "JOIN players p ON p.id=na.player_id WHERE p.league=? AND na.alias_norm=? ORDER BY p.id",
            (LEAGUE, normalize_name(prop["player_name"])),
        ).fetchall() if _matches_player(row, prop)
    ]
    if len(aliases) == 1:
        return aliases[0]["id"], "reviewed_alias_team_position"
    reason = "ambiguous_reviewed_alias" if len(aliases) > 1 else "source_id_not_in_spine"
    queue_unresolved_player(con, source_key, prop["player_name"], prop["team"], reason)
    return None, reason


def bind_player_source_key(con: sqlite3.Connection, source_key: str, player_id: int, now: str) -> None:
    _bind_player_source_key(
        con, source=SOURCE, league=LEAGUE, source_player_key=source_key,
        player_id=player_id, now=now,
    )


def resolve_game(con: sqlite3.Connection, event: Dict, fixture: Dict, now: str) -> int:
    source_key = event["source_game_key"]
    target_event_id = str(fixture.get("game_id") or "")
    if not target_event_id:
        raise SourceIdentityConflict("matched ESPN fixture has no event id")
    mapped = con.execute(
        "SELECT pg.id,pg.espn_event_id FROM prop_game_source_ids psi JOIN prop_games pg ON pg.id=psi.game_id "
        "WHERE psi.source=? AND psi.league=? AND psi.source_game_key=?",
        (SOURCE, LEAGUE, source_key),
    ).fetchall()
    if len(mapped) > 1:
        raise SourceIdentityConflict("source game key {} has multiple mappings".format(source_key))
    if mapped:
        if str(mapped[0]["espn_event_id"] or "") != target_event_id:
            raise SourceIdentityConflict("source game key {} changed ESPN fixture".format(source_key))
        con.execute(
            "UPDATE prop_game_source_ids SET last_seen=? WHERE source=? AND league=? AND source_game_key=?",
            (now, SOURCE, LEAGUE, source_key),
        )
        return mapped[0]["id"]

    candidates = con.execute(
        "SELECT id FROM prop_games WHERE league=? AND espn_event_id=? ORDER BY id",
        (LEAGUE, target_event_id),
    ).fetchall()
    if len(candidates) > 1:
        raise SourceIdentityConflict("ESPN MLS event {} has multiple prop games".format(target_event_id))
    if candidates:
        game_id = candidates[0]["id"]
    else:
        game_id = con.execute(
            "INSERT INTO prop_games(league,date,home,away,espn_event_id,start_time) VALUES(?,?,?,?,?,?)",
            (LEAGUE, str(fixture.get("date") or "")[:10],
             (fixture.get("home") or {}).get("name") or event["home"],
             (fixture.get("away") or {}).get("name") or event["away"],
             target_event_id, fixture.get("date") or event["start_time"]),
        ).lastrowid
    con.execute(
        "INSERT INTO prop_game_source_ids(source,league,source_game_key,game_id,first_seen,last_seen) "
        "VALUES(?,?,?,?,?,?)", (SOURCE, LEAGUE, source_key, game_id, now, now)
    )
    return game_id


def upsert_threshold(con: sqlite3.Connection, game_id: int, player_id: int, prop: Dict, now: str) -> int:
    written = 0
    for side in ("over", "under"):
        existing = con.execute(
            "SELECT id FROM props WHERE game_id=? AND player_id=? AND market=? AND side=? AND source=?",
            (game_id, player_id, prop["market"], side, SOURCE),
        ).fetchall()
        if len(existing) > 1:
            raise SourceIdentityConflict("duplicate persisted threshold for {} {} {}".format(
                player_id, prop["market"], side
            ))
        if existing:
            con.execute(
                "UPDATE props SET line=?, captured_at=?, odds=NULL, odds_captured_at=NULL WHERE id=?",
                (prop["line"], now, existing[0]["id"]),
            )
        else:
            con.execute(
                "INSERT INTO props(game_id,player_id,market,line,side,source,captured_at,odds,odds_captured_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (game_id, player_id, prop["market"], prop["line"], side, SOURCE, now, None, None),
            )
        written += 1
    return written


def direct_ingest(events: List[Dict], espn_games: Iterable[Dict], dry_run: bool = False) -> Dict:
    """Resolve and publish parsed events.  No caller should pre-create players."""
    summary = {
        "source_event_count": len(events), "candidate_event_count": 0,
        "eligible_event_count": 0, "rejected_event_count": 0, "written_props": 0,
        "resolved_players": 0, "unresolved_players": 0, "rejection_reasons": Counter(),
    }
    with closing(sqlite3.connect(DB)) as con:
        con.row_factory = sqlite3.Row
        try:
            ensure_source_identity_schema(con)
            now = dt.datetime.now(dt.timezone.utc).isoformat()
            for event in events:
                fixture, match_reason = match_espn_event(event, espn_games)
                if not fixture:
                    continue
                summary["candidate_event_count"] += 1
                if event["invalid"] or not event["props"]:
                    summary["rejected_event_count"] += 1
                    summary["rejection_reasons"]["malformed_or_unsupported_source_rows"] += 1
                    print("  REJECTED {}: malformed or unsupported MLS source rows".format(event["source_game_key"]))
                    continue
                participant_props = {}
                for prop in event["props"]:
                    participant_props[prop["source_player_key"]] = prop
                resolved = {}
                for source_key, prop in participant_props.items():
                    player_id, method = resolve_player(con, prop)
                    if player_id is None:
                        summary["unresolved_players"] += 1
                        continue
                    resolved[source_key] = player_id
                    summary["resolved_players"] += 1
                    if dry_run:
                        print("  DRY-RUN {} -> player {} ({})".format(prop["player_name"], player_id, method))
                if len(resolved) != len(participant_props) or len(set(resolved.values())) != len(participant_props):
                    summary["rejected_event_count"] += 1
                    summary["rejection_reasons"]["unresolved_or_duplicate_player_identity"] += 1
                    print("  REJECTED {}: resolved {} of {} source player IDs".format(
                        event["source_game_key"], len(resolved), len(participant_props)
                    ))
                    continue
                summary["eligible_event_count"] += 1
                if dry_run:
                    summary["written_props"] += 2 * len(event["props"])
                    continue
                for source_key, player_id in resolved.items():
                    bind_player_source_key(con, source_key, player_id, now)
                game_id = resolve_game(con, event, fixture, now)
                for prop in event["props"]:
                    summary["written_props"] += upsert_threshold(
                        con, game_id, resolved[prop["source_player_key"]], prop, now
                    )
            if dry_run:
                con.rollback()
            else:
                con.commit()
        except Exception:
            con.rollback()
            raise
    summary["rejection_reasons"] = dict(summary["rejection_reasons"])
    return summary


def write_raw_capture(body: bytes, captured_at: dt.datetime) -> Tuple[str, str]:
    digest = hashlib.sha256(body).hexdigest()
    directory = os.environ.get("LP_PROP_CAPTURE_DIR") or os.path.join(os.path.dirname(DB), "prop_source_captures")
    os.makedirs(directory, exist_ok=True)
    filename = "{}-{}-{}.json".format(
        SOURCE, captured_at.strftime("%Y%m%dT%H%M%SZ"), digest[:12]
    )
    path = os.path.join(directory, filename)
    # Immutable content-addressed name: a repeat capture cannot silently replace
    # an older raw artifact with different bytes.
    if not os.path.exists(path):
        with open(path, "xb") as output:
            output.write(body)
    return path, digest


def record_capture(
    payload_sha256: str, payload_path: Optional[str], counts: Dict, summary: Dict, status: str, message: str
) -> None:
    with closing(sqlite3.connect(DB)) as con:
        ensure_source_identity_schema(con)
        con.execute(
            "INSERT INTO prop_source_captures(source,league,captured_at,status,payload_sha256,payload_path,"
            "source_url,parser_version,source_prop_count,candidate_event_count,eligible_event_count,rejected_event_count,"
            "market_counts_json,rejected_reasons_json,message) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (SOURCE, LEAGUE, dt.datetime.now(dt.timezone.utc).isoformat(), status, payload_sha256, payload_path, API,
             PARSER_VERSION,
             int(counts.get("soccer_prizepicks_props", 0)), summary["candidate_event_count"],
             summary["eligible_event_count"], summary["rejected_event_count"], json.dumps(counts, sort_keys=True),
             json.dumps(summary["rejection_reasons"], sort_keys=True), message),
        )
        con.commit()


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] != LEAGUE:
        print(__doc__)
        return 1
    dry_run = "--dry-run" in sys.argv
    print("Fetching one RotoWire PrizePicks relay payload...")
    body, data = fetch_raw()
    captured_at = dt.datetime.now(dt.timezone.utc)
    raw_path, digest = write_raw_capture(body, captured_at)
    events, counts = parse_board(data)
    games = load_espn_games(events)
    summary = direct_ingest(events, games, dry_run=dry_run)
    if summary["candidate_event_count"] == 0:
        status, message, exit_code = "NO_MLS_BOARD", "No exact MLS fixture was present in this successful source capture.", 0
    elif summary["written_props"] == 0:
        status, message, exit_code = "REJECTED", "MLS source rows were present but none passed identity and fixture gates.", 2
    else:
        status, message, exit_code = "PUBLISHED", "Published exact-match MLS PrizePicks thresholds.", 0
    if not dry_run:
        record_capture(digest, raw_path, counts, summary, status, message)
    print("{}: {}".format(status, message))
    print(json.dumps({"source": counts, "ingest": summary}, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
