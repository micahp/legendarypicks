#!/usr/bin/env python3
"""Ingest RotoWire's public, position-filtered per-match soccer stat samples.

The stats page is subscriber-gated and its logged-out JSON calls return at most
five rows for each published position filter. This collector does not pretend
those samples are a complete league population. It archives every response,
paces requests, caps each invocation, deduplicates overlapping filters, and
prints the capped-response count explicitly.

Rows are fixture-matched to durable ESPN/FotMob appearances and written to a
provider-owned table. Stable RotoWire player IDs bind through player_source_ids;
new identities resolve only against the exact fixture roster and ambiguity
stays unresolved.

Usage:
  python3 ingest_rotowire_soccer_stats.py --league mls --start-week 1 --dry-run
  python3 ingest_rotowire_soccer_stats.py --league ligamx --start-week 1
"""
import argparse
import collections
import datetime as dt
import gzip
import glob
import json
import os
import sqlite3
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

from scripts_add_rotowire_soccer_logs import TABLE


_HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get(
    "LP_DB_PATH", os.path.join(_HERE, "data", "picks.dev.db"))
ARCHIVE_DIR = os.environ.get(
    "LP_ROTOWIRE_SOCCER_STATS_ARCHIVE",
    os.path.join(_HERE, "data", "rotowire-soccer-stats-archive"),
)
SOURCE = "rotowire"
ENDPOINT = "https://www.rotowire.com/soccer/tables/player-stats.php"
REFERER = "https://www.rotowire.com/soccer/stats.php"
ESPN_FIXTURES = {
    "mls": "https://site.web.api.espn.com/apis/site/v2/sports/soccer/usa.1/scoreboard",
    "ligamx": "https://site.web.api.espn.com/apis/site/v2/sports/soccer/mex.1/scoreboard",
}
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")

LEAGUES = {"mls": "MLS", "ligamx": "LMX"}
POSITION_FILTERS = ("A", "G", "F", "M", "D", "FM", "MD", "FMD")
PUBLIC_ROW_LIMIT = 5
HARD_REQUEST_LIMIT = 32
_MIN_INTERVAL = max(
    2.0, float(os.environ.get("LP_ROTOWIRE_STATS_MIN_INTERVAL") or 2.0)
)
_last_request = [0.0]

_LEAGUE_FLAGS = (
    "EPL", "FRAN", "LIGA", "SERI", "BUND", "MLS", "NWSL", "LMX",
    "ENG_CH", "UCL", "WOC", "UEL", "EURO", "FAC", "WWC",
)

# RotoWire's page definitions name AP "Attempted Passes". P is "Passes";
# across the sampled MLS and Liga MX fixtures it exactly matched FotMob's
# accurate-passes value, which is the existing normalized `passes` vocabulary.
STAT_KEYS = {
    "g": "goals",
    "a": "assists",
    "s": "shots",
    "sog": "sot",
    "p": "passes",
    "ap": "passes_attempted",
    "cr": "crosses",
    "acr": "accurate_crosses",
    "tkl": "tackles",
    "tklw": "tackles_won",
    "cl": "clearances",
    "ecl": "effective_clearances",
    "cc": "chances_created",
    "bcc": "big_chances_created",
    "int": "interceptions",
    "blk": "blocks",
    "touch": "touches",
    "dr": "dribbles",
    "dw": "dribbles_won",
    "sv": "saves",
    "gc": "goals_conceded",
    "cs": "clean_sheets",
    "fc": "fouls_committed",
    "fs": "fouls_suffered",
    "off": "offsides",
    "y": "yellow_cards",
    "r": "red_cards",
    "min": "minutes",
}

TEAM_ALIASES = {
    "mls": {
        "DCU": "DC", "GAL": "LA", "LAF": "LAFC", "NER": "NE",
        "NYR": "RBNY", "SJE": "SJ", "FIR": "CHI", "MNU": "MIN",
        "RAP": "COL", "SOU": "SEA", "WHI": "VAN",
    },
    "ligamx": {
        "CA": "CAZ", "GUA": "GDL", "MON": "MTY", "NEC": "NCX", "QUE": "QRO",
        "TIG": "UANL", "UNM": "UNAM",
    },
}


class SourceContractError(RuntimeError):
    """The publisher response no longer satisfies the measured contract."""


class IdentityConflict(RuntimeError):
    """A stable RotoWire ID conflicts with fixture-roster identity."""


def fold(value):
    ascii_text = unicodedata.normalize("NFKD", str(value or "")).encode(
        "ascii", "ignore").decode("ascii")
    return " ".join("".join(
        char for char in ascii_text.lower()
        if char.isalnum() or char.isspace()).split())


def normalize_team(league, value):
    code = str(value or "").strip().upper()
    if not code:
        raise SourceContractError(f"blank {league} team code")
    return TEAM_ALIASES.get(league, {}).get(code, code)


def _number(value):
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def stat_line(row):
    line = {}
    for source_key, target in STAT_KEYS.items():
        if source_key not in row:
            continue
        value = _number(row.get(source_key))
        if value is not None:
            line[target] = value
    return line


def request_params(league, season, week, position):
    params = {name: "0" for name in _LEAGUE_FLAGS}
    params.update({
        "season": str(season),
        "position": position,
        "start": str(week),
        "end": str(week),
        LEAGUES[league]: "1",
    })
    return params


def _get(params):
    wait = _MIN_INTERVAL - (time.monotonic() - _last_request[0])
    if wait > 0:
        time.sleep(wait)
    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url, headers={"Referer": REFERER, "User-Agent": UA})
    _last_request[0] = time.monotonic()
    with urllib.request.urlopen(request, timeout=40) as response:
        if response.status != 200:
            raise SourceContractError(f"RotoWire returned HTTP {response.status}")
        return json.loads(response.read())


def archive_response(payload, league, season, week, position, captured_at=None):
    captured_at = captured_at or dt.datetime.now(dt.timezone.utc)
    stamp = captured_at.strftime("%Y%m%dT%H%M%S.%fZ")
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    path = os.path.join(
        ARCHIVE_DIR,
        f"rotowire-soccer-{stamp}-{league}-{season}-mw{week}-{position}.json.gz",
    )
    temp = path + ".tmp"
    with gzip.open(temp, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
    os.replace(temp, path)
    return path


def latest_archive(league, season, week, position):
    """Return the newest exact response archive for one request, if present."""
    pattern = os.path.join(
        ARCHIVE_DIR,
        f"rotowire-soccer-*-{league}-{season}-mw{week}-{position}.json.gz",
    )
    paths = glob.glob(pattern)
    return max(paths, key=os.path.getmtime) if paths else None


def load_archive(path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def fixture_archive_response(payload, league, season, captured_at=None):
    captured_at = captured_at or dt.datetime.now(dt.timezone.utc)
    stamp = captured_at.strftime("%Y%m%dT%H%M%S.%fZ")
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    path = os.path.join(
        ARCHIVE_DIR,
        f"rotowire-soccer-fixtures-{stamp}-{league}-{season}.json.gz",
    )
    temp = path + ".tmp"
    with gzip.open(temp, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
    os.replace(temp, path)
    return path


def latest_fixture_archive(league, season):
    pattern = os.path.join(
        ARCHIVE_DIR, f"rotowire-soccer-fixtures-*-{league}-{season}.json.gz")
    paths = glob.glob(pattern)
    return max(paths, key=os.path.getmtime) if paths else None


def fetch_fixture_schedule(league, season):
    url = ESPN_FIXTURES[league] + "?" + urllib.parse.urlencode({
        "dates": str(season), "limit": "1000",
    })
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=40) as response:
        if response.status != 200:
            raise SourceContractError(
                f"ESPN fixture schedule returned HTTP {response.status}")
        return json.loads(response.read())


def parse_fixture_schedule(payload, league, season):
    events = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(events, list):
        raise SourceContractError("ESPN fixture schedule has no events list")
    fixtures = []
    for event in events:
        published_season = (event.get("season") or {}).get("year")
        competition = ((event.get("competitions") or [{}])[0] or {})
        completed = bool(
            (((competition.get("status") or {}).get("type") or {}).get("completed")))
        if int(published_season or 0) != int(season) or not completed:
            continue
        sides = {}
        for competitor in competition.get("competitors") or []:
            side = competitor.get("homeAway")
            code = ((competitor.get("team") or {}).get("abbreviation") or "")
            if side in ("home", "away") and code:
                sides[side] = normalize_team(league, code)
        game_id = str(event.get("id") or "")
        game_date = str(competition.get("date") or event.get("date") or "")[:10]
        if set(sides) != {"home", "away"} or not game_id or not game_date:
            raise SourceContractError(
                f"ESPN fixture {game_id or '<blank>'} lacks identity/date/sides")
        for side, opponent_side in (("home", "away"), ("away", "home")):
            fixtures.append({
                "game_id": game_id,
                "game_date": game_date,
                "team": sides[side],
                "opponent": sides[opponent_side],
                "home_away": side,
                "game_type": "REG",
            })
    if not fixtures:
        raise SourceContractError(
            f"ESPN published zero completed {league} fixtures for season {season}")
    return fixtures


def parse_response(payload, league, season, week, position):
    if not isinstance(payload, list):
        raise SourceContractError(
            f"{league} matchweek {week} position {position}: response is not a list")
    expected_league = LEAGUES[league]
    parsed = []
    for offset, raw in enumerate(payload):
        if not isinstance(raw, dict):
            raise SourceContractError(
                f"{league} matchweek {week} row {offset}: not an object")
        if raw.get("league") != expected_league:
            raise SourceContractError(
                f"{league} matchweek {week}: expected {expected_league}, "
                f"received {raw.get('league')!r}")
        try:
            games_played = int(raw.get("gp"))
        except (TypeError, ValueError):
            games_played = -1
        if games_played != 1:
            raise SourceContractError(
                f"{league} matchweek {week} {raw.get('player')!r}: "
                f"gp={raw.get('gp')!r}, expected one per-match row")
        player_key = str(raw.get("ID") or "").strip()
        name = str(raw.get("player") or "").strip()
        side = {"H": "home", "A": "away"}.get(
            str(raw.get("homeaway") or "").upper())
        if not player_key or not name or not side:
            raise SourceContractError(
                f"{league} matchweek {week} row {offset}: missing ID/name/homeaway")
        line = stat_line(raw)
        if not line:
            raise SourceContractError(
                f"{league} matchweek {week} {name!r}: no recognized stats")
        parsed.append({
            "source_player_key": player_key,
            "player_name": name,
            "league": league,
            "season": season,
            "matchweek": week,
            "position_filter": position,
            "position": raw.get("position"),
            "team": normalize_team(league, raw.get("team")),
            "opponent": normalize_team(league, raw.get("opp")),
            "home_away": side,
            "stats": line,
        })
    return parsed


def merge_filter_rows(rows):
    """Collapse overlap between public filters; conflicting copies are fatal."""
    merged = {}
    for row in rows:
        key = (
            row["source_player_key"], row["matchweek"], row["team"],
            row["opponent"], row["home_away"],
        )
        existing = merged.get(key)
        if existing:
            comparable = ("player_name", "league", "season", "position",
                          "team", "opponent", "home_away", "stats")
            if any(existing[name] != row[name] for name in comparable):
                raise SourceContractError(
                    f"conflicting filtered rows for RotoWire player {key[0]} "
                    f"in matchweek {key[1]}")
            existing["position_filters"].add(row["position_filter"])
            continue
        item = dict(row)
        item["position_filters"] = {row["position_filter"]}
        merged[key] = item
    return list(merged.values())


def require_schema(con):
    table = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)
    ).fetchone()
    view_columns = {row[1] for row in con.execute(
        "PRAGMA table_info(player_game_logs_all)")}
    required = {"players", "player_source_ids", "unresolved_players"}
    tables = {row[0] for row in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    missing = sorted(required - tables)
    if not table or "rotowire_stats" not in view_columns or missing:
        raise RuntimeError(
            "RotoWire soccer schema is not applied; run "
            "scripts_add_rotowire_soccer_logs.py --db ABSOLUTE_PATH --apply "
            f"first (missing tables={missing})")


def fixture_index(con, league, season, published_fixtures=None):
    index = collections.defaultdict(dict)
    rows = con.execute(
        "SELECT DISTINCT game_id, game_date, team, opponent, home_away, game_type "
        "FROM player_game_logs_all WHERE league=? AND season=? "
        "AND (espn_stats IS NOT NULL OR fotmob_stats IS NOT NULL)",
        (league, season),
    )
    for row in rows:
        if not row["game_id"] or not row["game_date"] or not row["home_away"]:
            continue
        try:
            key = (
                normalize_team(league, row["team"]),
                normalize_team(league, row["opponent"]),
                row["home_away"].lower(),
            )
        except SourceContractError:
            continue
        identity = (str(row["game_id"]), str(row["game_date"]))
        index[key][identity] = {
            "game_id": identity[0], "game_date": identity[1],
            "team": key[0], "opponent": key[1], "home_away": key[2],
            "game_type": row["game_type"],
        }
    for fixture in published_fixtures or ():
        if fixture["team"] == fixture["opponent"]:
            raise SourceContractError(
                f"fixture {fixture['game_id']} names the same team twice")
        key = (fixture["team"], fixture["opponent"], fixture["home_away"])
        identity = (fixture["game_id"], fixture["game_date"])
        index[key][identity] = fixture
    return index


def resolve_fixture(index, row):
    candidates = list(index.get(
        (row["team"], row["opponent"], row["home_away"]), {}).values())
    return candidates[0] if len(candidates) == 1 else None


def resolve_player(con, row, fixture):
    bound = con.execute(
        "SELECT psi.player_id, p.name, p.league FROM player_source_ids psi "
        "JOIN players p ON p.id=psi.player_id "
        "WHERE psi.source=? AND psi.league=? AND psi.source_player_key=?",
        (SOURCE, row["league"], row["source_player_key"]),
    ).fetchall()
    if len(bound) > 1:
        raise IdentityConflict(
            f"RotoWire player {row['source_player_key']} has multiple bindings")

    roster = con.execute(
        "SELECT DISTINCT p.id, p.name, l.team "
        "FROM player_game_logs_all l JOIN players p ON p.id=l.player_id "
        "WHERE l.league=? AND l.game_id=? AND l.game_date=?",
        (row["league"], fixture["game_id"], fixture["game_date"]),
    ).fetchall()
    if not roster:
        roster = con.execute(
            "SELECT DISTINCT p.id, p.name, COALESCE(l.team,p.team) AS team "
            "FROM player_game_logs_all l JOIN players p ON p.id=l.player_id "
            "WHERE l.league=? AND l.game_date=?",
            (row["league"], fixture["game_date"]),
        ).fetchall()
    roster_ids = {candidate["id"] for candidate in roster}
    if bound:
        if (bound[0]["league"] != row["league"]
                or fold(bound[0]["name"]) != fold(row["player_name"])):
            raise IdentityConflict(
                f"RotoWire player {row['source_player_key']} binding disagrees "
                "with published name/team identity")
        if bound[0]["player_id"] in roster_ids:
            return bound[0]["player_id"], "source_id"
        bound_team = normalize_team(row["league"], con.execute(
            "SELECT team FROM players WHERE id=?", (bound[0]["player_id"],)
        ).fetchone()[0])
        if bound_team != row["team"]:
            raise IdentityConflict(
                f"RotoWire player {row['source_player_key']} binding disagrees "
                "with published name/team identity")
        return bound[0]["player_id"], "source_id_name_team"

    candidates = [candidate for candidate in roster
                  if fold(candidate["name"]) == fold(row["player_name"])]
    same_team = [candidate for candidate in candidates
                 if normalize_team(row["league"], candidate["team"]) == row["team"]]
    candidates = same_team or candidates
    if len(candidates) == 1:
        return candidates[0]["id"], "fixture_name_team"
    return None, "ambiguous_fixture_name" if candidates else "not_on_fixture_roster"


def _queue_unresolved(con, row, reason, now):
    existing = con.execute(
        "SELECT id, count FROM unresolved_players WHERE source=? AND league=? "
        "AND source_player_key=?",
        (SOURCE, row["league"], row["source_player_key"]),
    ).fetchone()
    if existing:
        con.execute(
            "UPDATE unresolved_players SET count=?, reason=?, team=? WHERE id=?",
            ((existing["count"] or 0) + 1, reason, row["team"], existing["id"]),
        )
        return
    con.execute(
        "INSERT INTO unresolved_players(source,raw_name,league,team,first_seen,count,"
        "source_player_key,reason) VALUES(?,?,?,?,?,1,?,?)",
        (SOURCE, row["player_name"], row["league"], row["team"], now,
         row["source_player_key"], reason),
    )


def _bind_player(con, row, player_id, now):
    existing = con.execute(
        "SELECT player_id FROM player_source_ids WHERE source=? AND league=? "
        "AND source_player_key=?",
        (SOURCE, row["league"], row["source_player_key"]),
    ).fetchone()
    if existing:
        if existing["player_id"] != player_id:
            raise IdentityConflict(
                f"RotoWire player {row['source_player_key']} changed identity")
        con.execute(
            "UPDATE player_source_ids SET last_seen=? WHERE source=? AND league=? "
            "AND source_player_key=?",
            (now, SOURCE, row["league"], row["source_player_key"]),
        )
        con.execute(
            "DELETE FROM unresolved_players WHERE source=? AND league=? "
            "AND source_player_key=?",
            (SOURCE, row["league"], row["source_player_key"]),
        )
        return
    con.execute(
        "INSERT INTO player_source_ids(source,league,source_player_key,player_id,"
        "first_seen,last_seen) VALUES(?,?,?,?,?,?)",
        (SOURCE, row["league"], row["source_player_key"], player_id, now, now),
    )
    con.execute(
        "DELETE FROM unresolved_players WHERE source=? AND league=? "
        "AND source_player_key=?",
        (SOURCE, row["league"], row["source_player_key"]),
    )


def publish(con, rows, dry_run=False, published_fixtures=None):
    indexes = {}
    counts = collections.Counter()
    planned = []
    fixture_failures = []
    for row in rows:
        key = (row["league"], row["season"])
        if key not in indexes:
            indexes[key] = fixture_index(
                con, *key, published_fixtures=published_fixtures)
        fixture = resolve_fixture(indexes[key], row)
        if fixture is None:
            fixture_failures.append(
                f"mw{row['matchweek']} {row['team']} {row['home_away']} "
                f"vs {row['opponent']} ({row['player_name']})")
            continue
        player_id, method = resolve_player(con, row, fixture)
        counts[method] += 1
        planned.append((row, fixture, player_id, method))
    if fixture_failures:
        sample = "; ".join(fixture_failures[:5])
        raise SourceContractError(
            f"{len(fixture_failures)} rows did not resolve to exactly one durable "
            f"fixture; nothing written. First: {sample}")
    if dry_run:
        counts["planned"] = len(planned)
        return counts

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    con.execute("BEGIN IMMEDIATE")
    try:
        for row, fixture, player_id, method in planned:
            filters = ",".join(sorted(row["position_filters"]))
            stats = json.dumps(row["stats"], sort_keys=True)
            game_no = f"rotowire-{fixture['game_id']}"
            existing = con.execute(
                f"SELECT player_id,game_id,game_date,team,opponent,home_away,"
                f"stats,game_type,source_matchweek,source_position_filters "
                f"FROM {TABLE} WHERE league=? AND source_player_key=? "
                f"AND season=? AND game_no=?",
                (row["league"], row["source_player_key"], row["season"], game_no),
            ).fetchone()
            desired = (
                player_id, fixture["game_id"], fixture["game_date"],
                fixture["team"], fixture["opponent"], fixture["home_away"],
                stats, fixture["game_type"], row["matchweek"], filters,
            )
            if existing is not None and tuple(existing) == desired:
                if player_id is not None:
                    con.execute(
                        "DELETE FROM unresolved_players WHERE source=? AND league=? "
                        "AND source_player_key=?",
                        (SOURCE, row["league"], row["source_player_key"]),
                    )
                counts["unchanged"] += 1
                continue
            if player_id is None:
                _queue_unresolved(con, row, method, now)
            else:
                _bind_player(con, row, player_id, now)
            con.execute(
                f"INSERT INTO {TABLE}(player_id,league,season,game_no,game_id,"
                "game_date,team,opponent,home_away,stats,source,source_player_key,"
                "ingested_at,game_type,source_matchweek,source_position_filters) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(league,source_player_key,season,game_no) DO UPDATE SET "
                "player_id=excluded.player_id, game_id=excluded.game_id, "
                "game_date=excluded.game_date, team=excluded.team, "
                "opponent=excluded.opponent, home_away=excluded.home_away, "
                "stats=excluded.stats, ingested_at=excluded.ingested_at, "
                "game_type=excluded.game_type, "
                "source_matchweek=excluded.source_matchweek, "
                "source_position_filters=excluded.source_position_filters",
                (player_id, row["league"], row["season"],
                 game_no, fixture["game_id"],
                 fixture["game_date"], fixture["team"], fixture["opponent"],
                 fixture["home_away"], stats,
                 SOURCE, row["source_player_key"], now, fixture["game_type"],
                 row["matchweek"], filters),
            )
            counts["published"] += 1
        con.commit()
    except Exception:
        con.rollback()
        raise
    return counts


def _positions(value):
    positions = tuple(part.strip().upper() for part in value.split(",") if part.strip())
    unknown = sorted(set(positions) - set(POSITION_FILTERS))
    if not positions or unknown:
        raise argparse.ArgumentTypeError(
            f"positions must come from {','.join(POSITION_FILTERS)}; unknown={unknown}")
    return positions


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--league", required=True, choices=sorted(LEAGUES))
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--start-week", type=int, required=True)
    parser.add_argument("--end-week", type=int)
    parser.add_argument("--positions", type=_positions,
                        default=POSITION_FILTERS)
    parser.add_argument("--max-requests", type=int, default=16)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--reuse-archives", action="store_true",
        help="reuse the newest exact week/filter archive before making a request",
    )
    parser.add_argument(
        "--allow-empty", action="store_true",
        help="allow an explicitly probed range to contain no published rows",
    )
    args = parser.parse_args(argv)
    end_week = args.end_week if args.end_week is not None else args.start_week
    if args.start_week < 1 or end_week < args.start_week:
        parser.error("matchweek range must be positive and ordered")
    requests = (end_week - args.start_week + 1) * len(args.positions)
    if args.max_requests < 1 or requests > args.max_requests:
        parser.error(
            f"planned requests {requests} exceed --max-requests {args.max_requests}; "
            "split the run into smaller matchweek chunks")
    if requests > HARD_REQUEST_LIMIT:
        parser.error(
            f"planned requests {requests} exceed hard per-run limit {HARD_REQUEST_LIMIT}")

    path = os.path.abspath(DB_PATH)
    if not os.path.isfile(path):
        parser.error(f"database must already exist: {path}")
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        require_schema(con)
        print(f"database: {path}")
        print(f"request plan: {requests} calls, >= {_MIN_INTERVAL:.1f}s apart")
        fetched = []
        report = collections.Counter()
        for week in range(args.start_week, end_week + 1):
            for position in args.positions:
                archive = (latest_archive(
                    args.league, args.season, week, position)
                    if args.reuse_archives else None)
                if archive:
                    payload = load_archive(archive)
                    report["archives_reused"] += 1
                else:
                    params = request_params(
                        args.league, args.season, week, position)
                    payload = _get(params)
                    report["requests"] += 1
                    archive_response(
                        payload, args.league, args.season, week, position)
                    report["archives_written"] += 1
                report["source_rows"] += len(payload) if isinstance(payload, list) else 0
                if isinstance(payload, list) and len(payload) == PUBLIC_ROW_LIMIT:
                    report["capped_responses"] += 1
                if isinstance(payload, list) and not payload:
                    report["empty_responses"] += 1
                fetched.extend(parse_response(
                    payload, args.league, args.season, week, position))

        if not fetched:
            if args.allow_empty:
                print("  ".join(
                    f"{key}={value}" for key, value in sorted(report.items())))
                print("NO PUBLISHED ROWS in requested week/filter range; nothing written")
                return 0
            raise SourceContractError(
                "all RotoWire position-filter responses were empty; nothing written")
        rows = merge_filter_rows(fetched)
        report["unique_filtered_rows"] = len(rows)
        fixture_archive = (latest_fixture_archive(args.league, args.season)
                           if args.reuse_archives else None)
        if fixture_archive:
            fixture_payload = load_archive(fixture_archive)
            report["fixture_archives_reused"] += 1
        else:
            fixture_payload = fetch_fixture_schedule(args.league, args.season)
            report["fixture_requests"] += 1
            fixture_archive_response(
                fixture_payload, args.league, args.season)
            report["fixture_archives_written"] += 1
        published_fixtures = parse_fixture_schedule(
            fixture_payload, args.league, args.season)
        report["completed_fixture_sides"] = len(published_fixtures)
        result = publish(
            con, rows, dry_run=args.dry_run,
            published_fixtures=published_fixtures)
        report.update(result)
        print("  ".join(f"{key}={value}" for key, value in sorted(report.items())))
        print("coverage: PUBLIC FILTERED SAMPLE; not a complete league roster")
        if args.dry_run:
            print("dry run -- no database rows written")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
