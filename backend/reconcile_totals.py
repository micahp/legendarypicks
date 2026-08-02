#!/usr/bin/env python3
"""
reconcile_totals.py — compare what we stored against what the publisher says exists.

Every ingest in this repo answers "did rows land?" Nothing answers "did *all* the rows
land?" — and a partial ingest is indistinguishable from a complete one by inspection.
The 2024 NFL game logs sat at 29% of 2025 for months looking entirely normal.

The cheap oracle: ESPN's core API returns the cardinality of any collection in the
envelope of a `limit=1` request. One HTTP call, no traversal, no key needed:

    GET .../seasons/2025/types/2/events?limit=1   ->  {"count": 272, ...}
    GET .../seasons/2025/teams?limit=1            ->  {"count": 32,  ...}
    GET .../athletes/<id>/eventlog?limit=1        ->  {"events": {"count": 17, ...}}

Usage:
    python3 reconcile_totals.py                    # all checks
    python3 reconcile_totals.py --league nfl
    python3 reconcile_totals.py --season 2024
    python3 reconcile_totals.py --sample 40        # per-player eventlog sample size

Exit code is 1 if any check MISMATCHes or its oracle is unreachable. An unreachable
oracle is a FAIL, not a skip: "evidence unavailable" must never read as green.

Environment:
    LP_DB_PATH — the sqlite database (default: backend/data/picks.db)
"""
import argparse
import os
import sqlite3
import sys
import time
from typing import Dict, List, Optional, Tuple

import requests

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)

CORE = "https://sports.core.api.espn.com/v2/sports"

# league -> ESPN core API path segment
ESPN_PATH = {
    "nfl": "football/leagues/nfl",
    "nba": "basketball/leagues/nba",
    "mlb": "baseball/leagues/mlb",
    "nhl": "hockey/leagues/nhl",
}

# ESPN season type ids
REGULAR, POSTSEASON = 2, 3

TIMEOUT = 20


class OracleUnreachable(Exception):
    """The published total could not be read. Distinct from a mismatch."""


# ESPN's core API rate-limits a burst with a bare 403 — not a 429, no Retry-After, and
# the same URL that answered a second ago starts refusing. Measured 2026-08-02: a few
# dozen unpaced requests trips it and the block outlives a short backoff. So pace every
# request, back off long, and cache — the whole point of this script is that a phantom
# gap is worse than a slow check.
_CACHE: Dict[str, dict] = {}
_MIN_INTERVAL = 0.5
_last_request = 0.0


def _get_json(url: str, attempts: int = 6) -> dict:
    global _last_request
    if url in _CACHE:
        return _CACHE[url]
    last = None
    for i in range(attempts):
        gap = _MIN_INTERVAL - (time.monotonic() - _last_request)
        if gap > 0:
            time.sleep(gap)
        try:
            _last_request = time.monotonic()
            r = requests.get(url, timeout=TIMEOUT)
            if r.status_code in (403, 429, 500, 502, 503):
                last = f"HTTP {r.status_code}"
                time.sleep(min(60, 3 * 2 ** i))
                continue
            r.raise_for_status()
            body = r.json()
            _CACHE[url] = body
            return body
        except OSError as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(min(60, 3 * 2 ** i))
    raise OracleUnreachable(f"{last} after {attempts} attempts")


def published_count(url: str, *, path: Optional[List[str]] = None) -> int:
    """Read a collection's cardinality from a limit=1 envelope. One request."""
    sep = "&" if "?" in url else "?"
    try:
        node = _get_json(f"{url}{sep}limit=1")
    except OracleUnreachable:
        raise
    except Exception as e:  # noqa: BLE001 - any failure is "no evidence"
        raise OracleUnreachable(f"{type(e).__name__}: {e}") from e
    for key in path or []:
        if key not in node:
            raise OracleUnreachable(f"no '{key}' in response from {url}")
        node = node[key]
    if "count" not in node:
        raise OracleUnreachable(f"no 'count' in response from {url}")
    return int(node["count"])


def published_real_games(url: str, ours: int) -> int:
    """Count events excluding all-star exhibitions.

    ESPN files the Pro Bowl under season type 3, so its postseason `count` is 14 where
    the playoff bracket is 13. The oracle is not wrong — it answers a slightly different
    question than ours, and the gap is a definition, not a defect. Read the publisher's
    definition before you treat a difference as a bug.

    Classifying an event costs a request each, so only drill in when the headline count
    already disagrees: if `count` matches `ours` there is nothing to explain.
    """
    sep = "&" if "?" in url else "?"
    envelope = _get_json(f"{url}{sep}limit=100")
    if int(envelope.get("count", -1)) == ours:
        return ours
    real = 0
    for item in envelope.get("items", []):
        ev = _get_json(item["$ref"])
        kind = ev.get("competitions", [{}])[0].get("type", {}).get("abbreviation")
        if kind != "ALLSTAR":
            real += 1
    return real


def db_count(conn: sqlite3.Connection, sql: str, args=()) -> int:
    return int(conn.execute(sql, args).fetchone()[0])


class Report:
    def __init__(self) -> None:
        self.rows: List[Tuple[str, str, str, str]] = []
        self.failed = 0

    def check(self, name: str, ours: int, theirs: int, note: str = "") -> None:
        ok = ours == theirs
        if not ok:
            self.failed += 1
        delta = "" if ok else f"  ({ours - theirs:+d})"
        self.rows.append(
            ("PASS" if ok else "MISMATCH", name, f"ours={ours} published={theirs}{delta}", note)
        )

    def unreachable(self, name: str, why: str) -> None:
        self.failed += 1
        self.rows.append(("NO-ORACLE", name, "expected total unavailable", why))

    def note(self, name: str, text: str) -> None:
        self.rows.append(("INFO", name, text, ""))

    def render(self) -> str:
        width = max((len(r[1]) for r in self.rows), default=0)
        lines = []
        for status, name, detail, note in self.rows:
            line = f"{status:<10} {name:<{width}}  {detail}"
            if note:
                line += f"   [{note}]"
            lines.append(line)
        return "\n".join(lines)


def check_nfl(conn: sqlite3.Connection, rep: Report, season: int, sample: int) -> None:
    base = f"{CORE}/{ESPN_PATH['nfl']}/seasons/{season}"

    # --- games: schedule table vs ESPN's event count, per season type
    for type_id, game_type, label in ((REGULAR, "REG", "regular"), (POSTSEASON, "POST", "post")):
        name = f"nfl {season} {label}-season games"
        ours = db_count(
            conn,
            "SELECT COUNT(*) FROM nfl_schedule WHERE season=? AND game_type "
            + ("= 'REG'" if game_type == "REG" else "!= 'REG'"),
            (season,),
        )
        try:
            if type_id == POSTSEASON:
                theirs = published_real_games(f"{base}/types/{type_id}/events", ours)
            else:
                theirs = published_count(f"{base}/types/{type_id}/events")
        except OracleUnreachable as e:
            rep.unreachable(name, str(e))
            continue
        rep.check(name, ours, theirs, "nfl_schedule")

        # --- coverage: every one of those games should appear in the derived tables
        for table, col in (("player_game_logs", "game_id"), ("nfl_pbp", "game_id")):
            if game_type == "POST" and table == "nfl_pbp":
                continue  # nfl_pbp has no game_type column; it is checked once, vs REG
            covered = db_count(
                conn,
                f"SELECT COUNT(DISTINCT {col}) FROM {table} WHERE season=?"
                + (" AND league='nfl'" if table == "player_game_logs" else "")
                + (" AND game_type='REG'" if table == "player_game_logs" and game_type == "REG" else "")
                + (" AND game_type!='REG'" if table == "player_game_logs" and game_type == "POST" else ""),
                (season,),
            )
            rep.check(f"{name} in {table}", covered, theirs, "distinct game_id")

    # --- teams
    name = f"nfl {season} teams"
    try:
        theirs = published_count(f"{base}/teams")
    except OracleUnreachable as e:
        rep.unreachable(name, str(e))
    else:
        ours = db_count(
            conn,
            "SELECT COUNT(DISTINCT home_team) FROM nfl_schedule WHERE season=?",
            (season,),
        )
        rep.check(name, ours, theirs, "nfl_schedule.home_team")

    # --- per-player game counts: the check that catches a partial ingest
    # A season total can look right while individual players are short.
    # `eventlog` for a season is REGULAR SEASON ONLY (measured: Drake Maye 2025 returns
    # 17 events, Sep 7 -> Jan 4, though he played four playoff games). So compare REG to
    # REG — the first draft of this check compared our 21 to their 17 and reported seven
    # healthy Patriots as short.
    players = conn.execute(
        """
        SELECT p.id, p.name, p.espn_id, COUNT(l.id)
          FROM players p
          JOIN player_game_logs l
            ON l.player_id = p.id AND l.season = ? AND l.game_type = 'REG'
         WHERE p.league = 'nfl' AND p.espn_id IS NOT NULL AND p.espn_id != ''
         GROUP BY p.id
         ORDER BY COUNT(l.id) DESC
         LIMIT ?
        """,
        (season, sample),
    ).fetchall()
    if not players:
        rep.unreachable(f"nfl {season} per-player game counts", "no joinable players with espn_id")
        return

    short = []
    unreachable = 0
    for pid, pname, espn_id, ours in players:
        try:
            theirs = published_count(
                f"{base}/athletes/{espn_id}/eventlog", path=["events"]
            )
        except OracleUnreachable:
            unreachable += 1
            continue
        if ours != theirs:
            short.append(f"{pname} ours={ours} published={theirs}")
    checked = len(players) - unreachable
    name = f"nfl {season} per-player game counts"
    if checked == 0:
        rep.unreachable(name, "every eventlog request failed")
    else:
        if unreachable:
            # Never let a dead oracle quietly shrink the denominator into a pass.
            rep.unreachable(f"{name} (partial)", f"{unreachable} of {len(players)} eventlogs unreadable")
        rep.check(name, checked - len(short), checked, f"sampled {checked} players")
        for s in short[:10]:
            rep.note("  short player", s)


def check_generic(conn: sqlite3.Connection, rep: Report, league: str, season: int) -> None:
    """Games-played coverage for the non-NFL leagues, which share player_game_logs.

    Caveat before you trust a MISMATCH here: **our season key is not ESPN's.** We store
    the NHL 2025-26 season as `20252026` and the NBA 2025-26 season as `2026`; ESPN keys
    both by the starting year. Until that is normalised these checks will compare the
    wrong season and report a gap that is really a vocabulary mismatch — the same class
    of bug as the LAR/LA join key. NFL is unaffected (one calendar year, same key).
    """
    base = f"{CORE}/{ESPN_PATH[league]}/seasons/{season}"
    name = f"{league} {season} regular-season games in player_game_logs"
    try:
        theirs = published_count(f"{base}/types/{REGULAR}/events")
    except OracleUnreachable as e:
        rep.unreachable(name, str(e))
        return
    ours = db_count(
        conn,
        "SELECT COUNT(DISTINCT game_id) FROM player_game_logs WHERE league=? AND season=?",
        (league, season),
    )
    rep.check(name, ours, theirs, "distinct game_id")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", choices=sorted(ESPN_PATH), action="append")
    ap.add_argument("--season", type=int, action="append")
    ap.add_argument("--sample", type=int, default=25, help="players to spot-check per season")
    args = ap.parse_args()

    if not os.path.exists(DB):
        print(f"no database at {DB}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rep = Report()

    leagues = args.league or ["nfl"]
    for league in leagues:
        seasons = args.season or [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT season FROM player_game_logs WHERE league=? ORDER BY season",
                (league,),
            )
        ]
        for season in seasons:
            if league == "nfl":
                check_nfl(conn, rep, season, args.sample)
            else:
                check_generic(conn, rep, league, season)

    print(f"reconcile_totals — db={DB}\n")
    print(rep.render())
    print()
    if rep.failed:
        print(f"FAIL — {rep.failed} check(s) disagree with the published total or had no oracle")
        return 1
    print("PASS — every stored total matches the publisher")
    return 0


if __name__ == "__main__":
    sys.exit(main())
