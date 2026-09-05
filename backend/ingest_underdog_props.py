#!/usr/bin/env python3
"""Ingest scheduled UFC props from Underdog's published public board.

Usage:
  LP_DB_PATH=/path/to/picks.dev.db python ingest_underdog_props.py ufc
  LP_DB_PATH=/path/to/picks.dev.db python ingest_underdog_props.py ufc --dry-run

The Underdog endpoint is one unfiltered bulk book.  This command makes exactly
one request per run and parses only scheduled MMA balanced primary lines.  It
never creates a ``players`` row from a display name: an Underdog player id must
already be crosswalked, resolve to one exact canonical name, or resolve through
a reviewed ``name_alias``.  Everything else is retained in ``unresolved_players``.
"""
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import urllib.request
import collections
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple


DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)
API = "https://api.underdogfantasy.com/beta/v5/over_under_lines"
HDR = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "Chrome/131 Safari/537.36"
    )
}
SOURCE = "underdog"
LEAGUE = "ufc"

_UFC_MARKETS = {
    "significant_strikes": "significant_strikes",
    "submissions": "submissions",
    "knockouts": "knockouts",
    "fight_time": "fight_time",
    "finishes": "finishes",
}

# TENNIS, added 2026-09-05. Underdog publishes 49 tennis players and 366 balanced
# lines in the SAME payload this file already fetches every 30 minutes, and we
# had never asked: the parser filtered on sport_id == "MMA" and discarded 2,106
# of 2,134 players. Tennis is the shape this board wants and could not get
# anywhere else -- Bovada's tennis coupon has exactly ONE fantasy-style player
# over/under (Total Games) among 71 market shapes, and the RotoWire relay
# carries no tennis at all.
#
# Mapped: the counting stats a tennis game log can settle from.
_TENNIS_MARKETS = {
    "games_won": "games_won",
    "aces": "aces",
    "double_faults": "double_faults",
    "breakpoints_won": "breakpoints_won",
    "points_won": "points_won",
    "sets_won": "sets_won",
}
# DEFERRED, deliberately, and reported as unmapped rather than dropped in
# silence. Two different reasons and they should not be conflated:
#
#   period_1_games_won, period_1_aces, period_1_games_played
#       First-set-only. A single set is not a player's match performance and
#       settling it needs set-scoped logs we do not have.
#   games_played, sets_played, tie_breakers_played
#       Match LENGTH, not player performance. Both players share the value, so
#       it is the same row written twice under two names.
#
# These are useful to the tennis reprice model and wrong for a props board,
# which is the same split as the Bovada Service Game props.
_TENNIS_DEFERRED = {
    "period_1_games_won", "period_1_aces", "period_1_games_played",
    "games_played", "sets_played", "tie_breakers_played",
}
_SUBHEADER_RE = re.compile(r"^(Higher|Lower)\s+([\d.]+)\s")


class SourceIdentityConflict(RuntimeError):
    """A supposedly stable source key now names a different canonical row."""


def fetch() -> Dict:
    """Fetch the public book once; callers must reuse the returned payload."""
    req = urllib.request.Request(API, headers=HDR)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode())


def parse_ufc(data: Dict) -> Tuple[List[Dict], Dict]:
    """Return board rows plus the source-side count needed for reconciliation."""
    return parse_solo(data, "MMA", _UFC_MARKETS)


def tennis_tour(game: Dict) -> Optional[str]:
    """-> 'atp' | 'wta' | None, from Underdog's own competition grouping.

    Underdog files every tennis match under sport_id TENNIS with no tour field,
    but `sport_group_name` names the draw: "US Open Men's Singles", "US Open
    Women's Singles", "ATP Challenger Como". LP keys tennis fixtures as atp/wta,
    so a match we cannot classify is returned as None and DROPPED rather than
    guessed -- filing a women's match under atp would silently create a second
    fixture for a match we already hold.
    """
    name = (game.get("sport_group_name") or "")
    low = name.lower()
    if "women" in low or low.startswith("wta"):
        return "wta"
    if "men" in low or low.startswith("atp"):
        return "atp"
    return None


def parse_tennis(data: Dict, tour: str) -> Tuple[List[Dict], Dict]:
    """Tennis over/unders from the same payload UFC already reads, one tour."""
    return parse_solo(data, "TENNIS", _TENNIS_MARKETS,
                      deferred=_TENNIS_DEFERRED,
                      game_filter=lambda g: tennis_tour(g) == tour)


def parse_solo(data: Dict, sport_id: str, market_map: Dict,
               deferred: set = frozenset(),
               game_filter=None) -> Tuple[List[Dict], Dict]:
    """One parser for every 1v1 sport Underdog files under `solo_games`.

    Was hardcoded to MMA. Parameterised rather than copied, because a second
    copy is a second ruler for the same question and they drift.

    `deferred` names stats we CHOSE not to map. They are counted separately from
    stats we simply do not recognise, because "we decided against this" and "the
    publisher started sending something new" are different facts and a single
    unmapped bucket cannot tell them apart.
    """
    players = {
        str(player["id"]): player
        for player in data.get("players", [])
        if player.get("sport_id") == sport_id and player.get("id") is not None
    }
    appearances = {
        str(appearance["id"]): appearance
        for appearance in data.get("appearances", [])
        if str(appearance.get("player_id")) in players and appearance.get("id") is not None
    }
    games = {
        str(game["id"]): game
        for game in data.get("solo_games", [])
        if game.get("sport_id") == sport_id and game.get("id") is not None
        and (game_filter is None or game_filter(game))
    }
    scheduled_game_keys = {
        key for key, game in games.items() if game.get("status") == "scheduled"
    }

    props = []
    unmapped, deferred_hits = collections.Counter(), collections.Counter()
    for source_line in data.get("over_under_lines", []):
        if source_line.get("line_type") != "balanced":
            continue
        over_under = source_line.get("over_under") or {}
        appearance_stat = over_under.get("appearance_stat") or {}
        # Resolve the appearance FIRST. This is one unfiltered bulk book covering
        # every sport Underdog runs, so testing the market before knowing whose
        # line it is counts NFL and MLB stats as unmapped for tennis -- which is
        # exactly the noise that makes an unmapped report unreadable and then
        # ignored.
        appearance = appearances.get(str(appearance_stat.get("appearance_id")))
        if not appearance:
            continue
        stat = appearance_stat.get("stat")
        market = market_map.get(stat)
        if not market:
            # Counted, never silently dropped. A stat we chose to defer and a
            # stat the publisher just invented must not look the same.
            (deferred_hits if stat in deferred else unmapped)[stat] += 1
            continue
        game_key = str(appearance.get("match_id"))
        game = games.get(game_key)
        if not game or game_key not in scheduled_game_keys:
            continue
        player_key = str(appearance.get("player_id"))
        player = players.get(player_key)
        if not player:
            continue
        player_name = "{} {}".format(
            player.get("first_name", "").strip(), player.get("last_name", "").strip()
        ).strip()
        if not player_name:
            continue

        for option in source_line.get("options", []):
            choice = option.get("choice")
            if choice not in ("higher", "lower"):
                continue
            match = _SUBHEADER_RE.match(option.get("selection_subheader") or "")
            if not match:
                continue
            try:
                line = float(match.group(2))
            except ValueError:
                continue
            try:
                odds = int(option.get("american_price"))
            except (TypeError, ValueError):
                odds = None
            props.append({
                "source_player_key": player_key,
                "source_game_key": game_key,
                "player_name": player_name,
                "market": market,
                "line": line,
                "side": "over" if choice == "higher" else "under",
                "odds": odds,
                "home": game.get("home_player_name") or "",
                "away": game.get("away_player_name") or "",
                "date": (game.get("scheduled_at") or "")[:10],
                "start_time": game.get("scheduled_at"),
            })

    if unmapped:
        print("  UNMAPPED %s stats (publisher sent something we do not know): %s"
              % (sport_id, ", ".join("%s=%d" % kv for kv in unmapped.most_common())))
    if deferred_hits:
        print("  deferred %s stats (mapped out on purpose): %s"
              % (sport_id, ", ".join("%s=%d" % kv for kv in deferred_hits.most_common())))
    return props, {
        "scheduled_games": len(scheduled_game_keys),
        "scheduled_players": len({p["source_player_key"] for p in props}),
        "scheduled_props": len(props),
    }


def ensure_source_identity_schema(con: sqlite3.Connection) -> None:
    """Additive source-key tables; no display name is a cross-source key."""
    con.executescript("""
        CREATE TABLE IF NOT EXISTS player_source_ids(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source TEXT NOT NULL,
          league TEXT NOT NULL,
          source_player_key TEXT NOT NULL,
          player_id INTEGER NOT NULL REFERENCES players(id),
          first_seen TEXT NOT NULL,
          last_seen TEXT NOT NULL,
          UNIQUE(source, league, source_player_key)
        );
        CREATE INDEX IF NOT EXISTS idx_player_source_ids_player
          ON player_source_ids(player_id, source, league);
        CREATE TABLE IF NOT EXISTS prop_game_source_ids(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source TEXT NOT NULL,
          league TEXT NOT NULL,
          source_game_key TEXT NOT NULL,
          game_id INTEGER NOT NULL REFERENCES prop_games(id),
          first_seen TEXT NOT NULL,
          last_seen TEXT NOT NULL,
          UNIQUE(source, league, source_game_key)
        );
        CREATE INDEX IF NOT EXISTS idx_prop_game_source_ids_game
          ON prop_game_source_ids(game_id, source, league);
    """)
    columns = {row[1] for row in con.execute("PRAGMA table_info(unresolved_players)")}
    for column in ("source_player_key", "reason"):
        if column not in columns:
            con.execute("ALTER TABLE unresolved_players ADD COLUMN {} TEXT".format(column))
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_unresolved_players_source_key "
        "ON unresolved_players(source, league, source_player_key)"
    )


def queue_unresolved_player(
    con: sqlite3.Connection, source_player_key: str, player_name: str, reason: str
) -> None:
    """Queue once by source key, preserving the newest publisher display name."""
    existing = con.execute(
        "SELECT id FROM unresolved_players WHERE source=? AND league=? AND source_player_key=?",
        (SOURCE, LEAGUE, source_player_key),
    ).fetchone()
    if existing:
        con.execute(
            "UPDATE unresolved_players SET count=count+1, raw_name=?, reason=? WHERE id=?",
            (player_name, reason, existing["id"]),
        )
        return
    con.execute(
        "INSERT INTO unresolved_players("
        "source,raw_name,league,team,first_seen,count,source_player_key,reason"
        ") VALUES(?,?,?,?,?,1,?,?)",
        (SOURCE, player_name, LEAGUE, None, dt.datetime.now(dt.timezone.utc).isoformat(),
         source_player_key, reason),
    )


def resolve_player(
    con: sqlite3.Connection, source_player_key: str, player_name: str
) -> Tuple[Optional[int], str]:
    """Resolve only stable source keys, exact canonical names, or reviewed aliases."""
    mapped = con.execute(
        "SELECT p.id FROM player_source_ids psi JOIN players p ON p.id=psi.player_id "
        "WHERE psi.source=? AND psi.league=? AND psi.source_player_key=? AND p.league=?",
        (SOURCE, LEAGUE, source_player_key, LEAGUE),
    ).fetchall()
    if len(mapped) == 1:
        return mapped[0]["id"], "source_key"
    if len(mapped) > 1:
        raise SourceIdentityConflict("source player key {} has multiple mappings".format(source_player_key))

    exact = con.execute(
        "SELECT id FROM players WHERE league=? AND name=? ORDER BY id",
        (LEAGUE, player_name),
    ).fetchall()
    if len(exact) == 1:
        return exact[0]["id"], "exact_name"
    if len(exact) > 1:
        queue_unresolved_player(con, source_player_key, player_name, "ambiguous_exact_name")
        return None, "ambiguous_exact_name"

    alias_norm = normalize_name(player_name)
    aliases = con.execute(
        "SELECT DISTINCT p.id FROM name_alias na JOIN players p ON p.id=na.player_id "
        "WHERE p.league=? AND na.alias_norm=? ORDER BY p.id",
        (LEAGUE, alias_norm),
    ).fetchall()
    if len(aliases) == 1:
        return aliases[0]["id"], "reviewed_alias"
    reason = "ambiguous_reviewed_alias" if len(aliases) > 1 else "source_id_not_in_spine"
    queue_unresolved_player(con, source_player_key, player_name, reason)
    return None, reason


def normalize_name(value: str) -> str:
    """Match the repository's stored alias normalization without fuzzy matching."""
    import unicodedata

    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"\b(jr\.?|sr\.?|ii|iii|iv|v)\b", "", value.lower())
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", value)).strip()


def bind_player_source_key(
    con: sqlite3.Connection, source_player_key: str, player_id: int, now: str
) -> None:
    existing = con.execute(
        "SELECT player_id FROM player_source_ids WHERE source=? AND league=? AND source_player_key=?",
        (SOURCE, LEAGUE, source_player_key),
    ).fetchone()
    if existing and existing["player_id"] != player_id:
        raise SourceIdentityConflict(
            "source player key {} maps to {} not {}".format(
                source_player_key, existing["player_id"], player_id
            )
        )
    if existing:
        con.execute(
            "UPDATE player_source_ids SET last_seen=? WHERE source=? AND league=? AND source_player_key=?",
            (now, SOURCE, LEAGUE, source_player_key),
        )
    else:
        con.execute(
            "INSERT INTO player_source_ids(source,league,source_player_key,player_id,first_seen,last_seen) "
            "VALUES(?,?,?,?,?,?)",
            (SOURCE, LEAGUE, source_player_key, player_id, now, now),
        )


def _game_exists(con: sqlite3.Connection, game_id: int) -> bool:
    return con.execute(
        "SELECT 1 FROM prop_games WHERE id=?", (game_id,)
    ).fetchone() is not None


def _game_with_fighters(con: sqlite3.Connection, game_id: int, player_ids: Set[int]) -> bool:
    placeholders = ",".join("?" for _ in player_ids)
    found = {
        row["player_id"]
        for row in con.execute(
            "SELECT DISTINCT player_id FROM props WHERE game_id=? AND player_id IN ({})".format(
                placeholders
            ),
            (game_id, *sorted(player_ids)),
        )
    }
    return found == player_ids


def resolve_game(
    con: sqlite3.Connection, group: List[Dict], player_ids: Set[int], now: str
) -> int:
    """Resolve the native event key to one canonical game, or create a safe new one."""
    source_game_key = group[0]["source_game_key"]
    mapped = con.execute(
        "SELECT game_id FROM prop_game_source_ids WHERE source=? AND league=? AND source_game_key=?",
        (SOURCE, LEAGUE, source_game_key),
    ).fetchall()
    if len(mapped) > 1:
        raise SourceIdentityConflict("source game key {} has multiple mappings".format(source_game_key))
    if mapped:
        game_id = mapped[0]["game_id"]
        # A mapped row that no longer exists is not a changed identity, it is a game
        # that was folded into another one (link_prop_games and dedupe_prop_games both
        # do that) by a pass that did not carry the mapping across. Re-resolving finds
        # the survivor by fighter set, which is the same answer the fold intended.
        # Raising here instead cost two hours of failed runs on 2026-08-19.
        if not _game_exists(con, game_id):
            print("  stale mapping: source game {} pointed at deleted game {}, "
                  "re-resolving".format(source_game_key, game_id))
            con.execute(
                "DELETE FROM prop_game_source_ids WHERE source=? AND league=? AND source_game_key=?",
                (SOURCE, LEAGUE, source_game_key),
            )
            mapped = []
        else:
            if not _game_with_fighters(con, game_id, player_ids):
                raise SourceIdentityConflict(
                    "source game key {} conflicts with canonical fighters".format(source_game_key)
                )
            con.execute(
                "UPDATE prop_game_source_ids SET last_seen=? WHERE source=? AND league=? AND source_game_key=?",
                (now, SOURCE, LEAGUE, source_game_key),
            )
            return game_id

    # A one-day window, not an exact date. Publishers disagree by a day on the same
    # fixture because a card that starts 00:45 UTC is the previous evening in the US,
    # and link_prop_games documents the same "neighbour slate" convention. Measured
    # 2026-08-19: Underdog files Wint vs Chatman on 08-22, ESPN on 08-23, and an exact
    # match minted a second row for a fight we already had under its ESPN event id.
    # Two fighters meeting twice inside two days is not a thing, so the window is safe,
    # and an ambiguous result still refuses below rather than guessing.
    placeholders = ",".join("?" for _ in player_ids)
    candidates = con.execute(
        "SELECT pg.id FROM prop_games pg JOIN props pr ON pr.game_id=pg.id "
        "WHERE pg.league=? AND pg.date BETWEEN date(?,'-1 day') AND date(?,'+1 day') "
        "AND pr.player_id IN ({}) "
        "GROUP BY pg.id HAVING COUNT(DISTINCT pr.player_id)=?".format(placeholders),
        (LEAGUE, group[0]["date"], group[0]["date"], *sorted(player_ids), len(player_ids)),
    ).fetchall()
    if len(candidates) > 1:
        raise SourceIdentityConflict(
            "ambiguous canonical games for source game {}".format(source_game_key)
        )
    if candidates:
        game_id = candidates[0]["id"]
    else:
        game_id = con.execute(
            "INSERT INTO prop_games(league,date,home,away,espn_event_id,start_time) VALUES(?,?,?,?,?,?)",
            (LEAGUE, group[0]["date"], group[0]["home"], group[0]["away"], "",
             group[0]["start_time"]),
        ).lastrowid
    con.execute(
        "INSERT INTO prop_game_source_ids(source,league,source_game_key,game_id,first_seen,last_seen) "
        "VALUES(?,?,?,?,?,?)",
        (SOURCE, LEAGUE, source_game_key, game_id, now, now),
    )
    return game_id


def upsert_prop(con: sqlite3.Connection, game_id: int, player_id: int, prop: Dict, now: str) -> None:
    existing = con.execute(
        "SELECT id FROM props WHERE game_id=? AND player_id=? AND market=? AND line=? "
        "AND side=? AND source=?",
        (game_id, player_id, prop["market"], prop["line"], prop["side"], SOURCE),
    ).fetchone()
    if existing:
        con.execute(
            "UPDATE props SET captured_at=?, odds=?, odds_captured_at=? WHERE id=?",
            (now, prop["odds"], now if prop["odds"] is not None else None, existing["id"]),
        )
        return
    con.execute(
        "INSERT INTO props(game_id,player_id,market,line,side,source,captured_at,odds,odds_captured_at) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (game_id, player_id, prop["market"], prop["line"], prop["side"], SOURCE, now,
         prop["odds"], now if prop["odds"] is not None else None),
    )


def direct_ingest(props: List[Dict], dry_run: bool = False) -> Dict:
    """Write a parsed board while preserving source identity and loud coverage counts."""
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    summary = {
        "parsed_props": len(props), "source_games": 0, "eligible_games": 0,
        "skipped_games": 0, "written_props": 0, "resolved_players": 0,
        "unresolved_players": 0, "conflicted_games": 0,
    }
    try:
        ensure_source_identity_schema(con)
        grouped = defaultdict(list)
        for prop in props:
            grouped[prop["source_game_key"]].append(prop)
        summary["source_games"] = len(grouped)
        now = dt.datetime.now(dt.timezone.utc).isoformat()

        for source_game_key, group in grouped.items():
            participants = {}
            for prop in group:
                participants[prop["source_player_key"]] = prop["player_name"]
            resolved = {}
            for source_player_key, player_name in participants.items():
                player_id, method = resolve_player(con, source_player_key, player_name)
                if player_id is None:
                    summary["unresolved_players"] += 1
                    continue
                resolved[source_player_key] = player_id
                summary["resolved_players"] += 1
                if dry_run:
                    print("  DRY-RUN {} -> player {} ({})".format(player_name, player_id, method))

            if len(resolved) != len(participants) or len(set(resolved.values())) != len(participants):
                summary["skipped_games"] += 1
                print(
                    "  REJECTED source game {}: resolved {} of {} participant source IDs".format(
                        source_game_key, len(resolved), len(participants)
                    )
                )
                continue

            summary["eligible_games"] += 1
            if dry_run:
                summary["written_props"] += len(group)
                print("  DRY-RUN source game {}: would write {} props".format(source_game_key, len(group)))
                continue

            for source_player_key, player_id in resolved.items():
                bind_player_source_key(con, source_player_key, player_id, now)
            # A game whose identity cannot be confirmed is skipped, NOT fatal.
            # `resolve_game` fails closed on purpose -- it refuses to write props
            # onto a game whose fighter set does not match what Underdog is
            # sending -- but raising out of the loop aborted the WHOLE run, so one
            # bad fixture blocked every other event.
            #
            # It did: from 2026-08-25T01:04 until this change, every run fetched
            # 149 balanced props across 13 events and wrote ZERO, on
            # `source game key 295987 conflicts with canonical fighters` (game
            # 1274, Xiao Long vs Francesco Nuzzi, which holds only one of the two
            # fighters). The board showed 3 UFC markets instead of 6 because
            # win_by_decision comes from Bovada and kept updating while every
            # Underdog market froze. Same lesson the stale-mapping branch in
            # `resolve_game` already records from 2026-08-19.
            try:
                game_id = resolve_game(con, group, set(resolved.values()), now)
            except SourceIdentityConflict as conflict:
                summary["skipped_games"] += 1
                summary["conflicted_games"] += 1
                summary.setdefault("conflicts", []).append(str(conflict))
                print("  CONFLICT source game {}: {} -- skipped, run continues".format(
                    source_game_key, conflict))
                continue
            for prop in group:
                upsert_prop(con, game_id, resolved[prop["source_player_key"]], prop, now)
                summary["written_props"] += 1

        if dry_run:
            con.rollback()
        else:
            con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return summary


def main() -> int:
    global LEAGUE
    league = sys.argv[1] if len(sys.argv) > 1 else ""
    if league not in ("ufc", "atp", "wta"):
        print(__doc__)
        return 1
    # LEAGUE is a module constant threaded through twelve DB call sites (source
    # ids, aliases, unresolved players, fixture keys). Rebinding it once here,
    # before any of that runs, is deliberate: adding a parameter to twelve
    # signatures to support a second sport is a bigger and riskier diff than
    # setting the value the whole write path already reads. One process, one
    # league, one run.
    LEAGUE = league
    dry_run = "--dry-run" in sys.argv
    print("Fetching one Underdog public bulk book...")
    data = fetch()
    if league == "ufc":
        props, source_counts = parse_ufc(data)
    else:
        props, source_counts = parse_tennis(data, league)
    print(
        "Source: {scheduled_games} scheduled MMA games, {scheduled_players} fighters, "
        "{scheduled_props} balanced UFC props".format(**source_counts)
    )
    if not props:
        print("NO-BOARD: Underdog published no scheduled UFC balanced props; no DB write.")
        return 0
    summary = direct_ingest(props, dry_run=dry_run)
    print(
        "Ingest: {written_props} props from {eligible_games} eligible of {source_games} source games; "
        "{resolved_players} of {resolved_players_plus_unresolved} participant IDs resolved; "
        "{skipped_games} skipped games ({conflicted_games} identity conflicts), "
        "{unresolved_players} queued fighters.".format(
            resolved_players_plus_unresolved=(summary["resolved_players"] + summary["unresolved_players"]),
            **summary
        )
    )
    # A skipped game is a REPORTED game. These were fatal until 2026-08-26, which
    # at least made them loud; now that the run continues, silence would be worse.
    for line in summary.get("conflicts", []):
        print("  UNWRITTEN (identity conflict): {}".format(line))
    if summary["written_props"] == 0:
        print("ERROR: non-empty Underdog UFC board produced zero eligible props.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
