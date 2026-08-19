#!/usr/bin/env python3
"""Ingest player props from the RotoWire picks relay, starting with NFL.

    LP_DB_PATH=data/picks.dev.db python ingest_rotowire_props.py nfl
    LP_DB_PATH=data/picks.dev.db python ingest_rotowire_props.py nfl --dry-run
    LP_DB_PATH=data/picks.dev.db python ingest_rotowire_props.py nfl --from-archive DATE

## Why this exists

Measured 2026-08-19 against the archive: we carried **zero NFL props** while the relay
carried 24 NFL markets, inside the draft window that orders the whole roadmap. NCAAF is
the same shape and opens Aug 29. `ingest_rotowire_archive.py` already stores the whole
payload daily; this is the first thing that parses it into `props`.

## What it does and does not take

Only the publisher's **Game** category, which is a prop on one player in one fixture and
is what `props` can express. The **Season** category (753 NFL rows on 2026-08-19) is
season-long futures with no fixture, so it has no `game_id` to hang on. Those are counted
and reported every run, never silently dropped, and they want their own table.

## Identity

An Underdog-style crosswalk, for the same reason: a name is not a key. RotoWire publishes
its own player id inside `link` (`.../matthew-stafford-5971`), so a player is resolved
once and bound in `player_source_ids`, and every later run is an id lookup. First
resolution is by exact name, then by name plus team, then by a suffix-stripped name plus
team, because RotoWire drops generational suffixes: it says "Chris Godwin", our spine says
"Chris Godwin Jr.". Measured on the 2026-08-19 board, that ladder resolves 172 of 172.
A player who does not resolve is queued in `unresolved_players`, never minted.

Teams are mapped onto the ESPN vocabulary, which is canonical here (`reference_lp_team_code
_vocabularies`). Exactly one code disagrees on a 32-team league, `WAS` against our `WSH`,
and an unmapped code refuses rather than inventing a fixture.

## Books

The relay carries several books per prop at different lines, so `source` is
`rotowire:<book>` and each book's line is its own row. Bovada rows are untouched, and a
per-book source means "what did PrizePicks hang on this?" stays answerable.
"""
import argparse
import collections
import datetime as dt
import glob
import gzip
import json
import os
import re
import sqlite3
import sys
import unicodedata
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ingest_rotowire_archive as archive
from espn_client.scoreboard import _slate_day

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)
SOURCE = "rotowire"

# The publisher's sport label, and the team codes that disagree with ESPN's.
LEAGUES = {
    "nfl": {"sport": "NFL", "teams": {"WAS": "WSH"}},
}

# marketID -> (the marketName we verified it under, our key).
#
# Keyed on the publisher's id because that is the stable thing, and checked against the
# name because an id whose name moved underneath us is a different market wearing the same
# number. A market that is not in here is REPORTED, never guessed at: the whole point of a
# controlled vocabulary is that `passing_yards` means one thing across every publisher.
NFL_GAME_MARKETS = {
    4: ("Field Goals Made", "field_goals_made"),
    7: ("Interceptions Thrown", "interceptions_thrown"),
    8: ("Kicking Points", "kicking_points"),
    12: ("Passing Touchdowns", "passing_touchdowns"),
    13: ("Passing Yards", "passing_yards"),
    14: ("Passing + Rushing Yards", "passing_rushing_yards"),
    15: ("Total Touchdowns", "total_touchdowns"),
    19: ("Receiving Yards", "receiving_yards"),
    20: ("Receptions", "receptions"),
    23: ("Rushing Yards", "rushing_yards"),
    24: ("Rushing + Receiving Touchdowns", "rushing_receiving_touchdowns"),
    25: ("Rushing + Receiving Yards", "rushing_receiving_yards"),
    26: ("Sacks", "sacks"),
    32: ("Extra Points Made", "extra_points_made"),
}
MARKETS = {"nfl": NFL_GAME_MARKETS}

_SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"}
_LINK_ID = re.compile(r"-(\d+)/?$")


def normalize_name(value: str) -> str:
    """Accent-folded, punctuation-free lowercase, for comparing two spellings."""
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def strip_suffix(value: str) -> str:
    """`Chris Godwin Jr.` -> `chris godwin`. RotoWire publishes the bare name."""
    parts = normalize_name(value).split()
    while parts and parts[-1] in _SUFFIXES:
        parts.pop()
    return " ".join(parts)


def source_player_key(entity: Dict) -> Optional[str]:
    """RotoWire's own player id, off the end of its profile link."""
    match = _LINK_ID.search((entity.get("link") or "").strip())
    return match.group(1) if match else None


def ensure_schema(con: sqlite3.Connection) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS player_source_ids(
        id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, league TEXT NOT NULL,
        source_player_key TEXT NOT NULL, player_id INTEGER NOT NULL,
        first_seen TEXT NOT NULL, last_seen TEXT NOT NULL)""")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_player_source_ids "
                "ON player_source_ids(source, league, source_player_key)")
    con.execute("""CREATE TABLE IF NOT EXISTS prop_game_source_ids(
        id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, league TEXT NOT NULL,
        source_game_key TEXT NOT NULL, game_id INTEGER NOT NULL,
        first_seen TEXT NOT NULL, last_seen TEXT NOT NULL)""")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_prop_game_source_ids "
                "ON prop_game_source_ids(source, league, source_game_key)")


def parse(payload: Dict, league: str) -> Tuple[List[Dict], Dict]:
    """Board rows for one league, plus the counts needed to reconcile against the source.

    Every row carries the publisher's own ids, so nothing downstream has to re-derive
    identity from a display string.
    """
    spec = LEAGUES[league]
    markets = MARKETS[league]
    events = {e["eventID"]: e for e in payload.get("events", [])}
    entities = {e["entityID"]: e for e in payload.get("entities", [])}
    published = {m["marketID"]: m for m in payload.get("markets", [])}

    counts = collections.Counter()
    unmapped_markets = collections.Counter()
    renamed_markets = {}
    rows = []

    for prop in payload.get("props", []):
        market = published.get(prop.get("marketID"))
        if not market or market.get("sport") != spec["sport"]:
            continue
        counts["sport_props"] += 1
        if market.get("category") != "Game":
            counts["season_props"] += 1
            continue
        counts["game_props"] += 1

        known = markets.get(market["marketID"])
        if not known:
            unmapped_markets[(market["marketID"], market.get("marketName"))] += 1
            continue
        expected_name, market_key = known
        if market.get("marketName") != expected_name:
            # The id we trust now names something else. Report it and take nothing:
            # writing these would file a new market's lines under an old market's key.
            renamed_markets[market["marketID"]] = (expected_name, market.get("marketName"))
            continue

        participants = prop.get("entities") or []
        if len(participants) != 1:
            counts["not_a_single_player"] += 1
            continue
        entity = entities.get(participants[0])
        if not entity:
            counts["entity_missing"] += 1
            continue
        event = events.get(entity.get("eventID"))
        if not event or not event.get("gameID") or "homeTeam" not in event:
            counts["event_missing"] += 1
            continue

        start = dt.datetime.fromtimestamp(event["eventTime"], dt.timezone.utc)
        for line in prop.get("lines") or []:
            if line.get("line") is None:
                continue
            for side in ("over", "under"):
                rows.append({
                    "source_game_key": str(event["gameID"]),
                    "source_player_key": source_player_key(entity),
                    "player_name": entity.get("name"),
                    "team": entity.get("team"),
                    "position": entity.get("pos"),
                    "home": event["homeTeam"],
                    "away": event["awayTeam"],
                    "date": _slate_day(league, start.isoformat().replace("+00:00", "Z")),
                    "start_time": start.isoformat().replace("+00:00", "Z"),
                    "market": market_key,
                    "line": float(line["line"]),
                    "side": side,
                    "odds": line.get(side),
                    "book": line.get("book") or "unknown",
                })
    return rows, {
        "counts": counts,
        "unmapped_markets": unmapped_markets,
        "renamed_markets": renamed_markets,
    }


def resolve_player(con: sqlite3.Connection, league: str, row: Dict, now: str) -> Optional[int]:
    """The canonical player id for one board row, or None once it has been queued."""
    key = row.get("source_player_key")
    if key:
        bound = con.execute(
            "SELECT player_id FROM player_source_ids WHERE source=? AND league=? "
            "AND source_player_key=?", (SOURCE, league, key)).fetchone()
        if bound:
            return bound["player_id"]

    candidates = [
        dict(r) for r in con.execute(
            "SELECT id, name, team, active FROM players WHERE league=?", (league,))
        if normalize_name(r["name"]) == normalize_name(row["player_name"])
    ]
    if not candidates:
        # RotoWire drops generational suffixes; our spine keeps them. Team is required
        # here so a bare surname collision cannot resolve on spelling alone.
        candidates = [
            dict(r) for r in con.execute(
                "SELECT id, name, team, active FROM players WHERE league=? AND team=?",
                (league, row["team"]))
            if strip_suffix(r["name"]) == strip_suffix(row["player_name"])
        ]

    player_id = _pick_one(candidates, row["team"])
    if player_id is None:
        queue_unresolved(con, league, row, now,
                         "ambiguous" if candidates else "not_in_spine")
        return None
    if key:
        bind_player_source_key(con, league, key, player_id, now)
    return player_id


def _pick_one(candidates: List[Dict], team: Optional[str]) -> Optional[int]:
    """One id, or None. Never a guess between two live rows."""
    if len(candidates) == 1:
        return candidates[0]["id"]
    if not candidates:
        return None
    same_team = [c for c in candidates if (c["team"] or "").upper() == (team or "").upper()]
    if len(same_team) == 1:
        return same_team[0]["id"]
    # Our own spine holds duplicate rows for a few stars (measured 2026-08-19: Davante
    # Adams and Patrick Mahomes each have two NFL rows, one active). Prefer the active
    # one; if that is still not unique, refuse and let the queue show it.
    active = [c for c in (same_team or candidates) if c["active"]]
    return active[0]["id"] if len(active) == 1 else None


def bind_player_source_key(con: sqlite3.Connection, league: str, key: str,
                           player_id: int, now: str) -> None:
    existing = con.execute(
        "SELECT player_id FROM player_source_ids WHERE source=? AND league=? "
        "AND source_player_key=?", (SOURCE, league, key)).fetchone()
    if existing:
        if existing["player_id"] != player_id:
            raise SourceIdentityConflict(
                "rotowire player {} was {}, now resolves to {}".format(
                    key, existing["player_id"], player_id))
        con.execute("UPDATE player_source_ids SET last_seen=? WHERE source=? AND league=? "
                    "AND source_player_key=?", (now, SOURCE, league, key))
        return
    con.execute(
        "INSERT INTO player_source_ids(source,league,source_player_key,player_id,"
        "first_seen,last_seen) VALUES(?,?,?,?,?,?)",
        (SOURCE, league, key, player_id, now, now))


class SourceIdentityConflict(RuntimeError):
    """A stable source key now names a different canonical row."""


def queue_unresolved(con: sqlite3.Connection, league: str, row: Dict, now: str,
                     reason: str) -> None:
    existing = con.execute(
        "SELECT id, count FROM unresolved_players WHERE source=? AND league=? AND raw_name=?",
        (SOURCE, league, row["player_name"])).fetchone()
    if existing:
        con.execute("UPDATE unresolved_players SET count=? WHERE id=?",
                    ((existing["count"] or 0) + 1, existing["id"]))
        return
    con.execute(
        "INSERT INTO unresolved_players(source,raw_name,league,team,first_seen,count,"
        "source_player_key,reason) VALUES(?,?,?,?,?,1,?,?)",
        (SOURCE, row["player_name"], league, row["team"], now,
         row.get("source_player_key"), reason))


def resolve_game(con: sqlite3.Connection, league: str, row: Dict, now: str) -> int:
    """The canonical prop_games id for one fixture, created only when it is new."""
    spec = LEAGUES[league]
    home = spec["teams"].get(row["home"], row["home"])
    away = spec["teams"].get(row["away"], row["away"])

    mapped = con.execute(
        "SELECT game_id FROM prop_game_source_ids WHERE source=? AND league=? "
        "AND source_game_key=?", (SOURCE, league, row["source_game_key"])).fetchone()
    if mapped and _game_exists(con, mapped["game_id"]):
        con.execute("UPDATE prop_game_source_ids SET last_seen=? WHERE source=? AND league=? "
                    "AND source_game_key=?", (now, SOURCE, league, row["source_game_key"]))
        return mapped["game_id"]
    if mapped:
        # Folded into another row by link_prop_games or dedupe_prop_games. See
        # prop_game_merge: the mapping is stale, not the identity.
        con.execute("DELETE FROM prop_game_source_ids WHERE source=? AND league=? "
                    "AND source_game_key=?", (SOURCE, league, row["source_game_key"]))

    # A one-day window, because publishers disagree by a day on a fixture that starts
    # after midnight UTC, and both spellings are the same game.
    existing = con.execute(
        "SELECT id FROM prop_games WHERE league=? AND home=? AND away=? "
        "AND date BETWEEN date(?,'-1 day') AND date(?,'+1 day') ORDER BY id",
        (league, home, away, row["date"], row["date"])).fetchall()
    if existing:
        game_id = existing[0]["id"]
    else:
        game_id = con.execute(
            "INSERT INTO prop_games(league,date,home,away,espn_event_id,start_time) "
            "VALUES(?,?,?,?,'',?)",
            (league, row["date"], home, away, row["start_time"])).lastrowid
    con.execute(
        "INSERT INTO prop_game_source_ids(source,league,source_game_key,game_id,"
        "first_seen,last_seen) VALUES(?,?,?,?,?,?)",
        (SOURCE, league, row["source_game_key"], game_id, now, now))
    return game_id


def _game_exists(con: sqlite3.Connection, game_id: int) -> bool:
    return con.execute("SELECT 1 FROM prop_games WHERE id=?", (game_id,)).fetchone() is not None


def upsert_prop(con: sqlite3.Connection, game_id: int, player_id: int, row: Dict,
                now: str) -> str:
    source = "{}:{}".format(SOURCE, row["book"])
    existing = con.execute(
        "SELECT id FROM props WHERE game_id=? AND player_id=? AND market=? AND line=? "
        "AND side=? AND source=?",
        (game_id, player_id, row["market"], row["line"], row["side"], source)).fetchone()
    if existing:
        con.execute("UPDATE props SET captured_at=?, odds=?, odds_captured_at=? WHERE id=?",
                    (now, row["odds"], now if row["odds"] is not None else None,
                     existing["id"]))
        return "refreshed"
    con.execute(
        "INSERT INTO props(game_id,player_id,market,line,side,source,captured_at,odds,"
        "odds_captured_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (game_id, player_id, row["market"], row["line"], row["side"], source, now,
         row["odds"], now if row["odds"] is not None else None))
    return "new"


def ingest(rows: List[Dict], league: str, dry_run: bool = False) -> Dict:
    # A 30s busy timeout, not the 5s default: the scoreboard timers write every minute
    # and prod's props ingest is already 500ing on `database is locked` (roadmap B14).
    # Waiting for the writer is correct here; failing the run and dropping a slate of
    # props is not.
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    ensure_schema(con)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    summary = collections.Counter()
    summary["board_rows"] = len(rows)
    games, players = {}, {}

    vocabulary = team_vocabulary(con, league)
    try:
        for row in rows:
            if vocabulary is not None and not _fixture_is_known(row, league, vocabulary):
                summary["unknown_team"] += 1
                continue
            player_key = row.get("source_player_key") or row["player_name"]
            if player_key not in players:
                players[player_key] = resolve_player(con, league, row, now)
            player_id = players[player_key]
            if player_id is None:
                summary["unresolved_player_rows"] += 1
                continue
            if row["source_game_key"] not in games:
                games[row["source_game_key"]] = resolve_game(con, league, row, now)
            summary[upsert_prop(con, games[row["source_game_key"]], player_id, row, now)] += 1
        if dry_run:
            con.rollback()
        else:
            con.commit()
    finally:
        con.close()

    summary["games"] = len(games)
    summary["players"] = len([p for p in players.values() if p is not None])
    summary["unresolved_players"] = len([p for p in players.values() if p is None])
    # A plain dict, so a key nobody incremented reads as 0 in the report rather than
    # raising: `**Counter()` drops absent keys, it does not default them.
    return {key: summary[key] for key in (
        "board_rows", "new", "refreshed", "games", "players", "unresolved_players",
        "unresolved_player_rows", "unknown_team")}


def team_vocabulary(con: sqlite3.Connection, league: str) -> Optional[set]:
    """The league's published team codes, or None when we have nothing to check against.

    Taken from `nfl_schedule`, which is the league's own calendar, rather than from
    whoever happens to have a roster row: a real team with an empty roster is not an
    unknown team, and reading the vocabulary off `players` would have called it one.
    None means "no published vocabulary here", and then an unmapped code is accepted
    rather than everything being refused on the strength of a check we cannot make.
    """
    if league != "nfl":
        return None
    has_table = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='nfl_schedule'").fetchone()
    if not has_table:
        return None
    codes = {r[0] for r in con.execute("SELECT DISTINCT home_team FROM nfl_schedule")}
    codes |= {r[0] for r in con.execute("SELECT DISTINCT away_team FROM nfl_schedule")}
    codes.discard(None)
    return codes or None


def _fixture_is_known(row: Dict, league: str, vocabulary: set) -> bool:
    """Both sides of the fixture map onto codes the league itself publishes."""
    mapping = LEAGUES[league]["teams"]
    return all(mapping.get(row[side], row[side]) in vocabulary for side in ("home", "away"))


def load_archive(date_str: str) -> Dict:
    matches = sorted(glob.glob(os.path.join(
        archive.ARCHIVE_DIR, "rotowire-{}.json*".format(date_str))))
    if not matches:
        raise SystemExit("no archived payload for {} in {}".format(date_str, archive.ARCHIVE_DIR))
    path = matches[0]
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt") as handle:
        return json.load(handle)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("league", choices=sorted(LEAGUES))
    parser.add_argument("--dry-run", action="store_true",
                        help="parse and resolve, write nothing")
    parser.add_argument("--from-archive", metavar="YYYY-MM-DD",
                        help="read an archived payload instead of making a request")
    args = parser.parse_args(argv)

    if args.from_archive:
        payload = load_archive(args.from_archive)
        print("Reading the archived payload for {}.".format(args.from_archive))
    else:
        payload, _ = archive.fetch()
        print("Fetched the RotoWire relay once.")

    rows, report = parse(payload, args.league)
    counts = report["counts"]
    print("Source: {} {} props, {} of them Game category, {} Season (no fixture, not "
          "ingested).".format(counts["sport_props"], args.league.upper(),
                              counts["game_props"], counts["season_props"]))

    for (market_id, name), n in sorted(report["unmapped_markets"].items(),
                                       key=lambda kv: -kv[1]):
        print("  UNMAPPED market {} '{}': {} props not ingested".format(market_id, name, n))
    for market_id, (was, now_name) in report["renamed_markets"].items():
        print("  RENAMED market {}: we mapped '{}', the relay now says '{}'. Refusing "
              "until the vocabulary is reviewed.".format(market_id, was, now_name))
    for reason in ("not_a_single_player", "entity_missing", "event_missing"):
        if counts[reason]:
            print("  {}: {} props skipped".format(reason, counts[reason]))

    summary = ingest(rows, args.league, dry_run=args.dry_run)
    print("Ingest: {new} new, {refreshed} refreshed across {games} games and {players} "
          "players; {unresolved_players} players queued ({unresolved_player_rows} rows), "
          "{unknown_team} rows on an unknown team.".format(**summary))
    if args.dry_run:
        print("dry run -- nothing written.")
        return 0
    if counts["game_props"] and not (summary["new"] + summary["refreshed"]):
        print("ERROR: a non-empty {} board produced zero props.".format(args.league))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
