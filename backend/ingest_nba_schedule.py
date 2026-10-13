#!/usr/bin/env python3
"""NBA schedule from nba.com game pages: the league's own game ids, crosswalked to ours.

Every NBA game we hold is keyed by an ESPN event id. nba.com's id (0012600001) is what its
box scores and play-by-play are keyed by, and nobody here had it. This copies the schedule
as nba.com publishes it, one row per game, into `nba_schedule` (the shape of nfl_schedule:
the publisher's game id is the key, `espn` is the crosswalk column).

WHERE IT IS PUBLISHED. www.nba.com/game/<gameId> embeds __NEXT_DATA__ with pageProps.game:
gameId, gameCode ("20261008/NOPMIA", the US Eastern date then away+home tricodes),
gameTimeUTC, gameLabel ("Preseason", "Emirates NBA Cup"), gameStatus (1 scheduled, 2 live,
3 final), and homeTeam/awayTeam with teamTricode, teamName and score. Future games carry all
of it. stats.nba.com tarpits this box and cdn.nba.com answers 403, so the page is the route.

IDS ARE NOT DATE ORDERED (0012600001 is NOP at MIA on 10-08, not the first preseason game).
The id is <type><yy><serial>: 001 preseason, 002 regular season (the Cup's group games are
in here), 006 the Cup final. Playoff and play-in ids are numbered by series and are not walked. An id past the last game redirects
to /games, whose page carries no game: that is a miss. A walk stops after MISS_STREAK
consecutive misses, or on the third consecutive refusal (free-provider policy).

COUNT CHECK. A complete regular season is 1230 games (30 teams x 82 / 2). A walk that
publishes any other count refuses to write.

ESPN CROSSWALK. No request to ESPN. `espn` is filled from ESPN event ids we ALREADY store
(team_game_results, prop_games), joined on Eastern date + home + away. A game we hold no
ESPN id for keeps espn NULL; that is unknown, not absent.

    python ingest_nba_schedule.py --season 2027            # dry run
    python ingest_nba_schedule.py --season 2027 --apply
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import time

import paced_http

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from season_keys import normalize_season  # noqa: E402
from team_codes import UnknownTeamCode, normalize  # noqa: E402

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)
SOURCE = "nba.com"
GAME_URL = "https://www.nba.com/game/{game_id}"
SEASON_TYPES = {"001": "PRE", "002": "REG", "006": "CUP"}
# Playoff (004) and play-in (005) ids are numbered by round and series (0042500101), not
# serially, so the serial walk below cannot reach them. Not walked; add a walker when needed.
DEFAULT_TYPES = ("001", "002", "006")
REGULAR_SEASON_GAMES = 1230
# The Cup's knockout block. Measured 2026-10-02 for 2026-27: 1201-1204 (quarterfinals) and
# 1229-1230 (semifinals) are published with teams TBD, and 1205-1228 do not exist yet: those
# 24 games are scheduled once group play ends in December. A regular-season id missing BELOW
# this block is a real hole; one inside it is not yet published.
CUP_BLOCK_FIRST = 1201
MISS_STREAK = 5
MAX_SERIAL = 1400
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
_GAME_CODE = re.compile(r"(\d{8})/([A-Z]{3})([A-Z]{3})")

_FETCH = paced_http.Fetcher(
    min_interval=float(os.environ.get("LP_NBA_MIN_INTERVAL", "1.0")),
    retry_waits=(5.0, 20.0),
    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"},
    timeout=30,
    host_budget=int(os.environ.get("LP_NBA_SCHEDULE_BUDGET", "1500")),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS nba_schedule (
    game_id TEXT PRIMARY KEY,
    season INTEGER NOT NULL,
    season_type TEXT NOT NULL,
    game_code TEXT NOT NULL,
    game_date TEXT NOT NULL,
    start_utc TEXT,
    away_team TEXT,
    home_team TEXT,
    label TEXT,
    sub_label TEXT,
    status INTEGER,
    status_text TEXT,
    away_score INTEGER,
    home_score INTEGER,
    espn TEXT,
    source TEXT NOT NULL,
    ingested_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nba_schedule_date ON nba_schedule(game_date);
CREATE INDEX IF NOT EXISTS idx_nba_schedule_espn ON nba_schedule(espn);
"""


class NBAScheduleError(RuntimeError):
    """The schedule walk cannot be safely published."""


def _game_page(game_id: str) -> dict | None:
    """pageProps.game for this id, or None when nba.com has no such game (redirect to /games)."""
    body = _FETCH.fetch_text(GAME_URL.format(game_id=game_id))
    match = _NEXT_DATA.search(body or "")
    if not match:
        raise NBAScheduleError(f"{game_id}: page carries no __NEXT_DATA__")
    game = (json.loads(match.group(1)).get("props", {}).get("pageProps", {}) or {}).get("game")
    return game if isinstance(game, dict) and game.get("gameId") else None


def season_yy(season: int) -> str:
    """End-year season 2027 -> '26', the start year nba.com writes into its ids."""
    if normalize_season(SOURCE, "nba", f"{season - 1}{season}") != season:
        raise NBAScheduleError(f"season {season} does not round-trip through season_keys")
    return f"{(season - 1) % 100:02d}"


def _score(team: dict, status) -> int | None:
    if status != 3:
        return None
    value = team.get("score")
    return int(value) if isinstance(value, int) or str(value or "").isdigit() else None


def parse_game(game: dict, requested: str, season: int) -> dict:
    if game.get("gameId") != requested:
        raise NBAScheduleError(f"{requested}: page reports gameId {game.get('gameId')!r}")
    code = str(game.get("gameCode") or "")
    home, away = game.get("homeTeam") or {}, game.get("awayTeam") or {}
    if not code and not home.get("teamId") and not away.get("teamId"):
        # A slot whose teams are not decided yet: the Cup knockout games (0022601201..1230,
        # "Quarterfinal"/"Semifinal", gameStatusText "TBD", teamId 0). They are scheduled
        # regular-season games and count toward the 1230, so they are kept with teams NULL
        # and filled by a later walk. gameEt is the Eastern wall time written with a Z.
        et = str(game.get("gameEt") or "")[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", et):
            raise NBAScheduleError(f"{requested}: undecided slot without a gameEt date")
        return {
            "game_id": requested, "season": season, "season_type": SEASON_TYPES[requested[:3]],
            "game_code": "", "game_date": et, "start_utc": game.get("gameTimeUTC"),
            "away_team": None, "home_team": None, "home_name": "", "away_name": "",
            "label": game.get("gameLabel") or None, "sub_label": game.get("gameSubLabel") or None,
            "status": game.get("gameStatus"), "status_text": game.get("gameStatusText"),
            "away_score": None, "home_score": None,
        }
    match = _GAME_CODE.fullmatch(code)
    if not match:
        raise NBAScheduleError(f"{requested}: gameCode {code!r} is not YYYYMMDD/AWYHOM")
    if (away.get("teamTricode"), home.get("teamTricode")) != (match.group(2), match.group(3)):
        raise NBAScheduleError(f"{requested}: gameCode {code} disagrees with the team objects")
    try:
        home_code = normalize("nba", match.group(3))
        away_code = normalize("nba", match.group(2))
    except UnknownTeamCode as exc:
        # Exhibitions against non-NBA clubs (international, G League) carry codes we do not
        # hold. Those are not our games; skip them, and say so in the report.
        return {"game_id": requested, "skipped": f"non-NBA team: {exc}"}
    status = game.get("gameStatus")
    return {
        "game_id": requested, "season": season, "season_type": SEASON_TYPES[requested[:3]],
        "game_code": code, "game_date": dt.datetime.strptime(match.group(1), "%Y%m%d").date().isoformat(),
        "start_utc": game.get("gameTimeUTC"), "away_team": away_code, "home_team": home_code,
        "home_name": str(home.get("teamName") or ""), "away_name": str(away.get("teamName") or ""),
        "label": game.get("gameLabel") or None, "sub_label": game.get("gameSubLabel") or None,
        "status": status, "status_text": game.get("gameStatusText"),
        "away_score": _score(away, status), "home_score": _score(home, status),
    }


def walk(season: int, types=DEFAULT_TYPES, fetch_game=_game_page, log=print,
         checkpoint: str | None = None) -> tuple[list, list, dict]:
    """Every game nba.com publishes for the season, plus skipped ids and a spend report.

    `checkpoint` is a JSONL file of ids already answered (a game, a skip or a miss). A walk
    that dies at id 1201 resumes there instead of paying 1,200 requests again."""
    yy = season_yy(season)
    games, skipped = [], []
    done = {}
    if checkpoint and os.path.exists(checkpoint):
        with open(checkpoint) as fh:
            for line in fh:
                entry = json.loads(line)
                done[entry["id"]] = entry
    ck = open(checkpoint, "a") if checkpoint else None

    def remember(game_id, kind, value=None):
        if ck:
            ck.write(json.dumps({"id": game_id, "kind": kind, "value": value}) + "\n")
            ck.flush()
    spent = refused = consecutive_refusals = 0
    unpublished = []
    for prefix in types:
        misses = 0
        for serial in range(1, MAX_SERIAL + 1):
            # Regular-season ids are read all the way to 1230 regardless of gaps, so a gap is
            # recorded, never mistaken for the end of the season.
            within_season = prefix == "002" and serial <= REGULAR_SEASON_GAMES
            game_id = f"{prefix}{yy}{serial:05d}"
            if game_id in done:
                entry = done[game_id]
                if entry["kind"] == "miss":
                    if within_season:
                        unpublished.append(game_id)
                        continue
                    misses += 1
                    if misses >= MISS_STREAK:
                        break
                    continue
                misses = 0
                (skipped if entry["kind"] == "skip" else games).append(entry["value"])
                continue
            try:
                game = fetch_game(game_id)
                spent += 1
                consecutive_refusals = 0
            except NBAScheduleError:
                raise
            except Exception as exc:  # noqa: BLE001 -- counted; the third in a row stops the walk
                spent += 1
                refused += 1
                consecutive_refusals += 1
                if consecutive_refusals >= 3:
                    raise NBAScheduleError(
                        f"three consecutive refusals from www.nba.com (last: {game_id}: {exc}); "
                        f"stopped after {spent} requests") from exc
                skipped.append({"game_id": game_id, "skipped": f"refused: {exc}"})
                continue
            if game is None:
                remember(game_id, "miss")
                if within_season:
                    unpublished.append(game_id)
                    continue
                misses += 1
                if misses >= MISS_STREAK:
                    break
                continue
            misses = 0
            row = parse_game(game, game_id, season)
            remember(game_id, "skip" if "skipped" in row else "game", row)
            (skipped if "skipped" in row else games).append(row)
            if serial % 100 == 0:
                log(f"  {game_id}: {len(games)} games so far, {spent} requests", flush=True)
    if ck:
        ck.close()
    skipped.extend({"game_id": g, "skipped": "unpublished"} for g in unpublished)
    return games, skipped, {"host": "www.nba.com", "requests": spent, "refused": refused,
                            "resumed_from_checkpoint": len(done)}


def check_counts(games: list, skipped: list) -> list[str]:
    failures = []
    refused = [s for s in skipped if str(s["skipped"]).startswith("refused")]
    if refused:
        failures.append(f"{len(refused)} ids were refused; the walk is not complete")
    regular = sum(1 for g in games if g["season_type"] == "REG")
    unpublished = [s["game_id"] for s in skipped if s["skipped"] == "unpublished"]
    holes = [g for g in unpublished if int(g[-5:]) < CUP_BLOCK_FIRST]
    if holes:
        failures.append(f"regular-season ids missing outside the Cup block: {holes[:10]}")
    if regular and regular + len(unpublished) != REGULAR_SEASON_GAMES:
        failures.append(f"{regular} regular-season games published + {len(unpublished)} unpublished; "
                        f"a full season is {REGULAR_SEASON_GAMES}")
    keys = [(g["game_date"], g["home_team"], g["away_team"]) for g in games if g["home_team"]]
    if len(keys) != len(set(keys)):
        failures.append("two nba.com ids share one date, home and away")
    return failures


def stored_espn_ids(connection: sqlite3.Connection) -> tuple[dict, list]:
    """ESPN event ids we already hold, by (Eastern date, home code, away code), plus prop_games
    rows keyed by full team names, which are matched on the nickname nba.com publishes."""
    by_code = {}
    for game_id, team, opponent, date in connection.execute(
            "SELECT game_id, team, opponent, game_date FROM team_game_results "
            "WHERE league='nba' AND home_away='home'"):
        by_code[(date, team, opponent)] = str(game_id)
    named = connection.execute(
        "SELECT date, home, away, espn_event_id FROM prop_games "
        "WHERE league='nba' AND espn_event_id IS NOT NULL").fetchall()
    return by_code, named


def crosswalk(games: list, by_code: dict, named: list) -> int:
    matched = 0
    for g in games:
        if not g["home_team"]:
            g["espn"] = None
            continue
        espn = by_code.get((g["game_date"], g["home_team"], g["away_team"]))
        if espn is None:
            hits = {str(e) for d, h, a, e in named
                    if d == g["game_date"] and g["home_name"] and g["away_name"]
                    and str(h or "").endswith(g["home_name"]) and str(a or "").endswith(g["away_name"])}
            espn = hits.pop() if len(hits) == 1 else None
        g["espn"] = espn
        matched += espn is not None
    return matched


def publish(connection: sqlite3.Connection, games: list, *, apply: bool) -> None:
    if not apply:
        return
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    cols = ("game_id", "season", "season_type", "game_code", "game_date", "start_utc", "away_team",
            "home_team", "label", "sub_label", "status", "status_text", "away_score", "home_score",
            "espn")
    connection.executescript(SCHEMA)
    with connection:
        connection.executemany(
            f"INSERT INTO nba_schedule({','.join(cols)},source,ingested_at) "
            f"VALUES ({','.join('?' * len(cols))},?,?) "
            f"ON CONFLICT(game_id) DO UPDATE SET "
            + ",".join(f"{c}=excluded.{c}" for c in cols[1:] if c != "espn")
            + ",espn=COALESCE(excluded.espn, nba_schedule.espn),source=excluded.source,"
              "ingested_at=excluded.ingested_at",
            [tuple(g[c] for c in cols) + (SOURCE, now) for g in games])


def refresh(db_path: str, season: int, *, apply: bool = False, types=DEFAULT_TYPES,
            save: str | None = None, load: str | None = None,
            checkpoint: str | None = None) -> dict:
    """A walk is ~1,300 requests, so a dry run can --save it and the apply --load it."""
    started = time.time()
    if load:
        with open(load) as fh:
            saved = json.load(fh)
        if saved["season"] != season:
            raise NBAScheduleError(f"{load} holds season {saved['season']}, not {season}")
        games, skipped, spend = saved["games"], saved["skipped"], dict(saved["spend"], replayed=load)
    else:
        games, skipped, spend = walk(season, types, checkpoint=checkpoint)
        if save:
            with open(save, "w") as fh:
                json.dump({"season": season, "games": games, "skipped": skipped, "spend": spend}, fh)
    failures = check_counts(games, skipped)
    connection = sqlite3.connect(db_path, timeout=60)
    try:
        by_code, named = stored_espn_ids(connection)
        matched = crosswalk(games, by_code, named)
        status = "refused" if failures else ("published" if apply else "ready")
        publish(connection, games, apply=apply and not failures)
    finally:
        connection.close()
    by_type = {}
    for g in games:
        by_type[g["season_type"]] = by_type.get(g["season_type"], 0) + 1
    return {"status": status, "season": season, "games": len(games), "by_type": by_type,
            "espn_matched": matched, "skipped": skipped, "failures": failures,
            "spend": [spend], "seconds": round(time.time() - started)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=DB)
    parser.add_argument("--season", type=int, required=True, help="end year: 2027 is 2026-27")
    parser.add_argument("--types", default=",".join(DEFAULT_TYPES),
                        help="id prefixes to walk: 001 pre, 002 regular, 006 Cup final")
    parser.add_argument("--save", help="write the walked games to this JSON file")
    parser.add_argument("--load", help="publish a walk saved with --save instead of walking again")
    parser.add_argument("--checkpoint", help="JSONL of answered ids; a rerun resumes from it")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    result = refresh(os.path.abspath(args.db), args.season, apply=args.apply,
                     types=tuple(t.strip() for t in args.types.split(",") if t.strip()),
                     save=args.save, load=args.load, checkpoint=args.checkpoint)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    if not args.apply:
        print("DRY RUN -- nothing written. Re-run with --apply.")
    return 2 if result["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
