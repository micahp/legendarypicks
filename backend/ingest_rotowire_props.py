#!/usr/bin/env python3
"""Ingest player props from the RotoWire picks relay: NFL, MLB and MLS.

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
_vocabularies`). NFL publishes codes and exactly one disagrees, `WAS` against our `WSH`.
MLS publishes club display names, and the relay files MLS under a `Soccer` label it shares
with La Liga, Ligue 1, Serie A and the Premier League, so resolving BOTH clubs against
MLS's own roster is the competition filter as well as the team map. An unresolved club
refuses rather than inventing a fixture.

The club matcher has to see through OUR spellings as well as the publisher's: our own rows
say `DC United` and `Los Angeles FC` where ESPN says `D.C. United` and `LAFC`, and a club
we cannot resolve in our own table mints a duplicate beside the fixture we already had.

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
from team_codes import (
    ALIASES as TEAM_CODE_ALIASES,
    CANONICAL as CANONICAL_TEAM_CODES,
    UnknownTeamCode,
    normalize as normalize_team_code,
)

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)
SOURCE = "rotowire"

# The publisher's sport label, plus how to read a team off it.
#
# `code` leagues publish an abbreviation and we only have to fix the ones that disagree
# with ESPN. `club` leagues publish a full display name, and one sport label covers several
# competitions: "Soccer" carries MLS, La Liga, Ligue 1, Serie A and the Premier League in
# the same payload. So for those, resolving BOTH clubs against the league's own roster IS
# the membership test, and a fixture whose clubs are not MLS clubs is simply not ours.
# `day` is which calendar day a fixture is filed under.
#
# Measured 2026-08-19 on the rendered board: the slate groups games by `start_time`, not by
# this column, and falls back to `date` only when a row has no kickoff. So the truthful
# local slate day is the right value everywhere, and matching the UTC dates that Bovada's
# MLS rows carry would only make a fallback read as tomorrow.
#
# The rows that actually break the board are the ones with NO `start_time`: 17 of 30 MLS
# rows on 2026-08-19, against 0 of 30 NFL and 0 of 10 MLB. The board cannot place those at
# all. See `_fill_missing_start_time`.
LEAGUES = {
    "nfl": {"sport": "NFL", "kind": "code", "teams": {"WAS": "WSH"}},
    # RotoWire publishes codes, while MLB prop_games stores ESPN display names.
    # Both halves come from durable scoreboard snapshots; `team_codes` only
    # normalizes known cross-publisher code variants before that lookup.
    "mlb": {"sport": "MLB", "kind": "scoreboard", "team_count": 30},
    "mls": {"sport": "Soccer", "kind": "club", "aliases": {
        # Everything else falls out of accent folding, case folding, space squashing and
        # an optional trailing FC/SC. These are genuinely different names for one club,
        # and they come from BOTH sides: the relay's spelling and the spelling already
        # sitting in our own `prop_games` rows, because a club we cannot resolve in our
        # own table mints a duplicate fixture beside the one we had.
        "new york red bulls": "RBNY",
        "los angeles football club": "LAFC",
        "los angeles fc": "LAFC",
        "los angeles galaxy": "LA",
    }},
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
SOCCER_GAME_MARKETS = {
    147: ("Chances Created", "chances_created"),
    151: ("Goals Allowed", "goals_allowed"),
    152: ("Shots on Target", "shots_on_target"),
    154: ("Saves", "saves"),
    155: ("Shots", "shots"),
    157: ("Clearances", "clearances"),
    159: ("Crosses", "crosses"),
    161: ("Passes Attempted", "passes_attempted"),
}
MLB_GAME_MARKETS = {
    # Numeric count lines. These deliberately do not use the `_any` markets:
    # "over 1.5 hits" and "to record a hit" are different questions even
    # though the eventual boxscore field is the same.
    216: ("Doubles", "doubles"),
    218: ("Home Runs", "home_runs"),
    219: ("Total Bases", "total_bases"),
    220: ("Runs", "runs"),
    221: ("RBI", "rbis"),
    # 222 is a BATTER line. 232 below is the pitcher's walks-allowed line.
    222: ("Walks", "batter_walks"),
    226: ("Hits+Runs+RBI", "hits_runs_rbis"),
    229: ("Earned Runs", "earned_runs"),
    230: ("Pitcher Strikeouts", "strikeouts"),
    231: ("Hits Allowed", "hits_allowed"),
    232: ("Walks Allowed", "walks"),
    234: ("Outs", "outs"),
    238: ("Hits", "hits"),
    # Singles, Wins, and both Fantasy Score ids remain absent on purpose. They
    # have no verified boxscore/scoring-formula mapping and are reported below.
}
MARKETS = {
    "nfl": NFL_GAME_MARKETS,
    "mlb": MLB_GAME_MARKETS,
    "mls": SOCCER_GAME_MARKETS,
}

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


def _board_day(league: str, start: dt.datetime) -> Optional[str]:
    """The local day this fixture is played on. See the note on LEAGUES."""
    return _slate_day(league, start.isoformat().replace("+00:00", "Z"))


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
                    "date": _board_day(league, start),
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


def resolve_player(con: sqlite3.Connection, league: str, row: Dict, now: str,
                   team_code: Optional[str] = None) -> Optional[int]:
    """The canonical player id for one board row, or None once it has been queued.

    `team_code` is the club already resolved onto our vocabulary. It matters: the relay
    names an NFL player's team `WAS` and an MLS player's `New York City FC`, while the
    spine says `WSH` and `NYC`, so comparing the raw strings would silently fail every
    fallback that needs a team.
    """
    key = row.get("source_player_key")
    if key:
        bound = con.execute(
            "SELECT player_id FROM player_source_ids WHERE source=? AND league=? "
            "AND source_player_key=?", (SOURCE, league, key)).fetchone()
        if bound:
            return bound["player_id"]

    published = normalize_name(row["player_name"])
    roster = [dict(r) for r in con.execute(
        "SELECT id, name, team, active FROM players WHERE league=?", (league,))]
    candidates = [r for r in roster if normalize_name(r["name"]) == published]

    if not candidates and team_code:
        # Every fallback below is scoped to one club and must land on exactly one
        # player, because a looser name rule across a whole league is how a prop ends up
        # on the wrong athlete without anything raising.
        club = [r for r in roster if (r["team"] or "").upper() == team_code.upper()]
        for rule in (_same_but_for_a_suffix, _same_but_for_a_middle_name, _a_mononym):
            candidates = [r for r in club if rule(r["name"], row["player_name"])]
            if candidates:
                break

    player_id = _pick_one(candidates, team_code)
    if player_id is None:
        queue_unresolved(con, league, row, now,
                         "ambiguous" if candidates else "not_in_spine")
        return None
    if key:
        bind_player_source_key(con, league, key, player_id, now)
    return player_id


def _same_but_for_a_suffix(ours: str, published: str) -> bool:
    """`Chris Godwin Jr.` is `Chris Godwin`. The relay drops generational suffixes."""
    return strip_suffix(ours) == strip_suffix(published)


def _same_but_for_a_middle_name(ours: str, published: str) -> bool:
    """`Juan Manuel Sanabria` is `Juan Sanabria`: same first and last, middle dropped."""
    mine, theirs = strip_suffix(ours).split(), strip_suffix(published).split()
    if len(mine) < 2 or len(theirs) < 2 or (len(mine) == len(theirs)):
        return False
    return (mine[0], mine[-1]) == (theirs[0], theirs[-1])


def _a_mononym(ours: str, published: str) -> bool:
    """`Luighi` is `Luighi Hanri`. One published name against a full name on the club."""
    theirs = strip_suffix(published).split()
    mine = strip_suffix(ours).split()
    return len(theirs) == 1 and len(mine) > 1 and mine[0] == theirs[0]


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


class TeamVocabulary(dict):
    """Normalized spelling -> canonical code, plus its stored display name."""

    def __init__(self, aliases=None, display_names=None):
        super().__init__(aliases or {})
        self.display_names = dict(display_names or {})


class TeamVocabularyError(RuntimeError):
    """Durable team evidence is absent, incomplete, or internally conflicting."""


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


def resolve_game(con: sqlite3.Connection, league: str, row: Dict, now: str,
                 vocabulary: Optional[Dict[str, str]] = None) -> int:
    """The canonical prop_games id for one fixture, created only when it is new."""
    home_code = resolve_team(vocabulary, row["home"])
    away_code = resolve_team(vocabulary, row["away"])
    # What we MATCH on is always the resolved code, so "CF Montreal", "CF Montréal" and
    # "MTL" all find the one game rather than minting a third row beside the two we
    # already had. What we STORE is whatever that league's rows already carry: codes for
    # NFL, club display names for MLS. Writing a code into a table of display names, or a
    # display name into a table of codes, is how a second vocabulary gets started.
    if LEAGUES[league]["kind"] == "code":
        home, away = home_code or row["home"], away_code or row["away"]
    elif LEAGUES[league]["kind"] == "scoreboard":
        display_names = getattr(vocabulary, "display_names", {})
        home, away = display_names.get(home_code), display_names.get(away_code)
        if not home or not away:
            raise TeamVocabularyError(
                "no stored display name for resolved {} fixture {} @ {}".format(
                    league, away_code, home_code))
    else:
        home, away = row["home"], row["away"]

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

    # MLB's board date has already been normalized to the same New York slate day
    # used by scoreboards. Exact-day matching is required because baseball series
    # routinely repeat the same two clubs on consecutive dates; a +/-1 window
    # silently folds the next game into yesterday's fixture. The older league
    # paths retain their tolerance for publisher date disagreements.
    if LEAGUES[league]["kind"] == "scoreboard":
        candidates = con.execute(
            "SELECT id, home, away FROM prop_games WHERE league=? AND date=? ORDER BY id",
            (league, row["date"])).fetchall()
    else:
        candidates = con.execute(
            "SELECT id, home, away FROM prop_games WHERE league=? "
            "AND date BETWEEN date(?,'-1 day') AND date(?,'+1 day') ORDER BY id",
            (league, row["date"], row["date"])).fetchall()
    existing = [
        c for c in candidates
        if (resolve_team(vocabulary, c["home"]), resolve_team(vocabulary, c["away"]))
        == (home_code, away_code)
    ]
    if existing:
        game_id = existing[0]["id"]
        _fill_missing_start_time(con, game_id, row)
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


def _fill_missing_start_time(con: sqlite3.Connection, game_id: int, row: Dict) -> bool:
    """Give a matched row the kickoff it never had. Fills only, never overwrites.

    The board places a game by its kickoff, so a row without one cannot be put on a day at
    all: measured 2026-08-19, 17 of 30 MLS rows carried no `start_time` and the relay was
    handing us the exact instant for them while we threw it away, because a start time was
    only written when this ingest CREATED the row.

    Overwriting an existing value would be a different and much worse thing, since the row
    may already carry the publisher's own corrected time.
    """
    if not row.get("start_time"):
        return False
    changed = con.execute(
        "UPDATE prop_games SET start_time=? WHERE id=? "
        "AND (start_time IS NULL OR start_time='')",
        (row["start_time"], game_id)).rowcount
    if changed:
        print("  filled a missing start_time on game {}: {}".format(
            game_id, row["start_time"]))
    return bool(changed)


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
            if vocabulary is not None and not _fixture_is_known(row, vocabulary):
                summary["unknown_team"] += 1
                continue
            player_key = row.get("source_player_key") or row["player_name"]
            if player_key not in players:
                players[player_key] = resolve_player(
                    con, league, row, now, resolve_team(vocabulary, row["team"]))
            player_id = players[player_key]
            if player_id is None:
                summary["unresolved_player_rows"] += 1
                continue
            if row["source_game_key"] not in games:
                games[row["source_game_key"]] = resolve_game(
                    con, league, row, now, vocabulary)
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


def team_vocabulary(con: sqlite3.Connection, league: str) -> Optional[Dict[str, str]]:
    """{how a publisher might spell a club: our canonical code}, or None if unknowable.

    Every league reads this from its own published list rather than from whoever
    happens to have a roster row: a real team with an empty roster is not an unknown team,
    and reading the vocabulary off `players` would have called it one. NFL's list is
    `nfl_schedule`, the league calendar we already store. MLS's is ESPN's conference
    standings, which publishes all 30 clubs with an abbreviation and a display name, at a
    cost of one cached request. MLB reads the 30 clubs already stored in durable
    scoreboard snapshots: each payload carries abbreviation and display name.

    None means "no published vocabulary here", and then nothing is refused on the strength
    of a check we could not make.
    """
    spec = LEAGUES[league]
    if spec["kind"] == "code":
        has_table = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='nfl_schedule'"
        ).fetchone()
        if not has_table:
            return None
        codes = {r[0] for r in con.execute("SELECT DISTINCT home_team FROM nfl_schedule")}
        codes |= {r[0] for r in con.execute("SELECT DISTINCT away_team FROM nfl_schedule")}
        codes.discard(None)
        if not codes:
            return None
        # Keys are normalized, values are the canonical code, the same shape the club
        # branch builds, so `resolve_team` has one lookup rule for both leagues.
        index = {normalize_name(code): code for code in codes}
        index.update({normalize_name(publisher): ours
                      for publisher, ours in spec["teams"].items() if ours in codes})
        return index

    if spec["kind"] == "scoreboard":
        return _scoreboard_team_vocabulary(con, league, spec["team_count"])

    import espn_client as espn
    try:
        standings = espn.mls_conference_standings()
    except Exception as exc:  # a refusal is not a vocabulary, so check nothing
        print("  club vocabulary unavailable ({}: {}); team checks skipped this "
              "run".format(type(exc).__name__, exc))
        return None
    index = {}
    for group in standings.get("groups") or []:
        for club in group.get("rows") or []:
            code, name = club.get("abbrev"), club.get("name")
            if not code or not name:
                continue
            index[normalize_name(code)] = code
            index[_squash(normalize_name(code))] = code
            for spelling in _club_spellings(name):
                index[spelling] = code
                index[_squash(spelling)] = code
    for spelling, code in (spec.get("aliases") or {}).items():
        index[spelling] = code
        index[_squash(spelling)] = code
    return index or None


def _scoreboard_team_vocabulary(
    con: sqlite3.Connection, league: str, expected_count: int
) -> TeamVocabulary:
    """Build a complete code/display vocabulary from durable scoreboard rows.

    Unlike the MLS branch this performs no request and has no permissive `None`
    fallback. An incomplete set cannot prove an unknown code is outside MLB, so
    the entire ingest fails closed before it can mint a parallel fixture.
    """
    has_table = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='scoreboard_snapshots'"
    ).fetchone()
    if not has_table:
        raise TeamVocabularyError("scoreboard_snapshots is required for MLB team identity")

    display_names = {}
    for stored in con.execute(
        "SELECT payload FROM scoreboard_snapshots WHERE LOWER(league)=?", (league,)
    ):
        try:
            payload = json.loads(stored[0])
        except (TypeError, ValueError):
            raise TeamVocabularyError("malformed MLB scoreboard snapshot payload")
        for side in ("home", "away"):
            team = payload.get(side) or {}
            raw_code = team.get("abbrev")
            display = str(team.get("name") or "").strip()
            if not raw_code or not display:
                continue
            try:
                code = normalize_team_code(league, raw_code)
            except UnknownTeamCode as exc:
                raise TeamVocabularyError(str(exc))
            prior = display_names.get(code)
            if prior is not None and prior != display:
                raise TeamVocabularyError(
                    "MLB code {} has conflicting display names: {!r}, {!r}".format(
                        code, prior, display))
            display_names[code] = display

    expected_codes = set(CANONICAL_TEAM_CODES.get(league, ()))
    resolved_codes = set(display_names)
    if (
        len(resolved_codes) != expected_count
        or resolved_codes != expected_codes
    ):
        raise TeamVocabularyError(
            "MLB scoreboard vocabulary is incomplete: resolved {}/{} clubs; "
            "missing={}, unexpected={}".format(
                len(resolved_codes), expected_count,
                sorted(expected_codes - resolved_codes),
                sorted(resolved_codes - expected_codes),
            )
        )

    index = {}
    for code, display in display_names.items():
        index[normalize_name(code)] = code
        index[normalize_name(display)] = code
    # These aliases are the repository's already-published cross-source code
    # vocabulary (for this archive, notably CWS -> CHW), not a new handwritten
    # list in the RotoWire path.
    for raw_code, code in TEAM_CODE_ALIASES.get(league, {}).items():
        if code in display_names:
            index[normalize_name(raw_code)] = code
    return TeamVocabulary(index, display_names)


def _club_spellings(name: str) -> List[str]:
    """A display name and the same name without its trailing FC/SC.

    The relay says "Chicago Fire" and "Atlanta United" where ESPN says "Chicago Fire FC"
    and "Atlanta United FC", and says "Vancouver Whitecaps FC" where ESPN drops it. The
    suffix is decoration on both sides, so both spellings point at the same club.
    """
    base = normalize_name(name)
    out = [base]
    parts = base.split()
    if len(parts) > 1 and parts[-1] in {"fc", "sc", "cf"}:
        out.append(" ".join(parts[:-1]))
    else:
        out.extend(["{} {}".format(base, suffix) for suffix in ("fc", "sc")])
    return out


def resolve_team(vocabulary: Optional[Dict[str, str]], raw: Optional[str]) -> Optional[str]:
    """The canonical code for one spelling, or None if it is not this league's."""
    if not raw:
        return None
    if vocabulary is None:
        return raw
    key = normalize_name(raw)
    for candidate in (key, _squash(key)):
        if candidate in vocabulary:
            return vocabulary[candidate]
    parts = key.split()
    if len(parts) > 1 and parts[-1] in {"fc", "sc", "cf"}:
        base = " ".join(parts[:-1])
        for candidate in (base, _squash(base)):
            if candidate in vocabulary:
                return vocabulary[candidate]
    return None


def _squash(key: str) -> str:
    """`d c united` and `dc united` are the same club.

    Punctuation folding turns ESPN's `D.C. United` into `d c united` and our own stored
    `DC United` into `dc united`, and comparing those two as written minted a second
    fixture for a game we already had.
    """
    return key.replace(" ", "")


def _fixture_is_known(row: Dict, vocabulary: Optional[Dict[str, str]]) -> bool:
    """Both sides of the fixture are clubs this league publishes."""
    return all(resolve_team(vocabulary, row[side]) for side in ("home", "away"))


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
    # The sport label, not the league: "Soccer" is MLS plus four European competitions,
    # and reporting 183 of them as "MLS props" would overstate our coverage five ways.
    print("Source: {} {} props, {} of them Game category, {} Season (no fixture, not "
          "ingested).".format(counts["sport_props"], LEAGUES[args.league]["sport"],
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
          "players; {unresolved_players} players queued ({unresolved_player_rows} rows)."
          .format(**summary))
    if summary["unknown_team"]:
        # For a club league this is the competition filter doing its job, not a defect:
        # a fixture whose clubs are not in this league is another league's fixture.
        label = ("rows under this sport label but not in this league"
                 if LEAGUES[args.league]["kind"] == "club" else
                 "rows on a team code the league does not publish")
        print("  {} {}.".format(summary["unknown_team"], label))
    if args.dry_run:
        print("dry run -- nothing written.")
        return 0
    # A board with rows we correctly REJECTED is not a failure. `game_props`
    # counts the SPORT label, and RotoWire files MLS under a `Soccer` label it
    # shares with La Liga, Serie A, Ligue 1 and the Premier League. On a day
    # with no MLS fixtures the whole soccer board is another competition's, the
    # membership filter rejects all of it, and this used to exit 2 and take the
    # systemd unit down with it.
    #
    # Measured 2026-08-24: ESPN reports 0 MLS matches that day, the relay's
    # soccer board is Osasuna/Bologna/Real Madrid/Chelsea, and every row is
    # correctly rejected. Replayed against 08-22 (13 matches) the same code
    # ingests 90 props across 9 games, so nothing about MLS is broken.
    #
    # The real failure is rows that PASSED the league filter and still wrote
    # nothing. That is what this now checks.
    considered = counts["game_props"] - summary["unknown_team"]
    if considered > 0 and not (summary["new"] + summary["refreshed"]):
        print("ERROR: {} {} rows passed the league filter and none ingested."
              .format(considered, args.league))
        return 2
    if counts["game_props"] and considered <= 0:
        print("  no {} fixtures on this board; every row belonged to another "
              "competition. Not an error.".format(args.league))
    return 0


if __name__ == "__main__":
    sys.exit(main())
