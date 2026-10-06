#!/usr/bin/env python3
"""Per-match soccer player logs from FotMob, for the stats ESPN charges most for.

Why a second provider at all. ESPN's summary answers a whole match in one
request but publishes 14 per-player fields, none of them tackles, clearances,
crosses or passes. Its core api publishes those, at ONE REQUEST PER ATHLETE --
about 48 a fixture, roughly 7,300 for a Liga MX season. FotMob returns the same
depth for a whole fixture in ONE request: ~45 for the season.

The decisive argument is not cost, it is that ESPN refuses this box. On
2026-08-25 it 403'd three separate runs, one of which wrote zero rows after 100
requests. FotMob is a different host, so a backfill against it does not compete
with the serving path for ESPN's budget -- which every ESPN backfill request
does.

Identity. FotMob has its own player ids, so rows are keyed to OUR spine by an
accent-folded full name, and AMBIGUITY FAILS CLOSED: a name matching two spine
rows resolves to neither and the row is retained unresolved, exactly as
ingest_soccer_logs does. Measured over three fixtures: 103 of 124 matched, 1
ambiguous, 20 with no spine row at all.

Collision. ESPN keys game_no on its EVENT id and FotMob's match ids are a
different space, so nothing here can safely share a table with ESPN's rows. It
does not: this writes `player_game_logs_fotmob`, its own table, and
`player_game_logs` stays ESPN's at one row per appearance. The view
`player_game_logs_all` joins the two on (player_id, game_date) -- a player plays
at most one match a date -- and keeps each provider's line in its own COLUMN, so
a value's provenance is where it was read from rather than a stamp that has to
be maintained. See scripts_split_provider_logs.py.

Usage:
  python3 ingest_fotmob_soccer_logs.py --league ligamx --dry-run
  python3 ingest_fotmob_soccer_logs.py --league ligamx
"""
import argparse
import collections
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DB_PATH = os.environ.get("LP_DB_PATH", "data/picks.dev.db")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# FotMob league ids. The international ids were verified against FotMob's own
# league documents on 2026-10-06: details.name, details.gender and
# details.selectedSeason, not inferred from a URL slug. UEFA publishes four
# Nations League divisions; LegendaryPicks presents them as one competition.
LEAGUES = {
    "ligamx": (230, 2026),
    "lcup": (10043, 2026),
    "mls": (130, 2026),
    "unl": (9806, 2026),
    "friendlies": (114, 2026),
}
LEAGUE_IDS = {
    league: (league_id,) for league, (league_id, _season) in LEAGUES.items()
}
LEAGUE_IDS["unl"] = (9806, 9807, 9808, 9809)
NATIONAL_TEAM_LEAGUES = frozenset(("unl", "friendlies"))

# FotMob's own stat KEY -> the vocabulary player_game_logs already uses.
# `passes_attempted` is deliberately absent: FotMob publishes accurate passes,
# not attempted, and mapping one onto the other would be a different question
# answered with a confident number.
#
# Keyed on the machine key with the display label as fallback, because neither
# alone is safe. FotMob's key vocabulary is inconsistent -- `total_shots` and
# `accurate_passes` are snake_case, `ShotsOnTarget` is camelCase, and tackles
# arrives as `matchstats.headers.tackles`, an i18n path leaked into the data.
# A leaked path is exactly the kind of thing that gets cleaned up upstream, and
# then a key-only map silently stops finding tackles.
STATS = {
    "goals": "goals",
    "assists": "assists",
    "total_shots": "shots",
    "ShotsOnTarget": "shots_on_target",
    "matchstats.headers.tackles": "tackles",
    "clearances": "clearances",
    "interceptions": "interceptions",
    "accurate_passes": "passes",
    "accurate_crosses": "crosses",
    "chances_created": "chances_created",
    "dribbles_succeeded": "dribbles",
    "fouls": "fouls_committed",
    "was_fouled": "fouls_suffered",
    "saves": "saves",
    "goals_conceded": "goals_conceded",
    "minutes_played": "minutes",
    "recoveries": "recoveries",
}

# The same targets by display label, used when the key is absent or changes.
LABELS = {
    "Goals": "goals",
    "Assists": "assists",
    "Total shots": "shots",
    "Shots on target": "shots_on_target",
    "Tackles": "tackles",
    "Clearances": "clearances",
    "Interceptions": "interceptions",
    "Accurate passes": "passes",
    "Accurate crosses": "crosses",
    "Chances created": "chances_created",
    "Successful dribbles": "dribbles",
    "Fouls committed": "fouls_committed",
    "Was fouled": "fouls_suffered",
    "Saves": "saves",
    "Goals conceded": "goals_conceded",
    "Minutes played": "minutes",
    "Recoveries": "recoveries",
}

_MIN_INTERVAL = float(os.environ.get("LP_FOTMOB_MIN_INTERVAL") or 1.5)
_last = [0.0]


def _get(url):
    wait = _MIN_INTERVAL - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=40) as response:
        return json.loads(response.read())


def fold(value):
    ascii_text = unicodedata.normalize("NFKD", str(value or "")).encode(
        "ascii", "ignore").decode("ascii")
    return " ".join("".join(ch for ch in ascii_text.lower()
                            if ch.isalnum() or ch.isspace()).split())


def _number(entry):
    """The value out of FotMob's {"key":..., "stat":{"value":..}} wrapper.

    Compound stats arrive as strings like '43 (72%)': the count is the part we
    want and the percentage is derived from it.
    """
    value = entry
    if isinstance(value, dict):
        value = value.get("stat", value)
    if isinstance(value, dict):
        value = value.get("value", value.get("total"))
    if value is None:
        return None
    text = str(value).split("(")[0].strip().rstrip("%")
    try:
        return float(text)
    except ValueError:
        return None


def stat_line(player):
    line = {}
    for group in player.get("stats", []) or []:
        for label, raw in (group.get("stats") or {}).items():
            target = None
            if isinstance(raw, dict):
                target = STATS.get(str(raw.get("key")))
            if not target:
                target = LABELS.get(label)
            if not target:
                continue
            value = _number(raw)
            if value is not None:
                line.setdefault(target, value)
    return line


# A cross-border tournament's athletes are owned by the DOMESTIC spines;
# `players WHERE league='lcup'` has always held zero rows. Written here after
# the same defect was fixed in the rotowire ingest, the props endpoint, the
# settler and the chart -- a fifth site, in a brand new module, because the
# module asked for "the league's players" instead of "the players who play in
# this league".
ROSTER_LEAGUES = {"lcup": ("mls", "ligamx")}


def spine(con, league):
    leagues = ROSTER_LEAGUES.get(league, (league,))
    placeholders = ",".join("?" for _ in leagues)
    index = collections.defaultdict(list)
    for row in con.execute(
            f"SELECT id, name, team, espn_id FROM players "
            f"WHERE league IN ({placeholders})", tuple(leagues)):
        index[fold(row[1])].append({"id": row[0], "team": row[2],
                                    "espn_id": row[3]})
    return index


def resolve(index, name, allowed_player_ids=None):
    """One spine row, optionally constrained to this date's ESPN roster."""
    matches = index.get(fold(name), [])
    if allowed_player_ids is not None:
        allowed = {int(player_id) for player_id in allowed_player_ids}
        matches = [row for row in matches if int(row["id"]) in allowed]
    return matches[0] if len(matches) == 1 else None


def fotmob_id_spine(con):
    """FotMob player id -> canonical player, across every competition binding.

    A national-team appearance must not resolve through ``players.league`` or a
    display name: the same person still belongs to their club spine, and two
    different people can share that name. FotMob's player id is stable across
    club and country. Duplicate bindings to the same canonical row collapse;
    one source id bound to two canonical rows remains ambiguous and misses.
    """
    index = collections.defaultdict(dict)
    for row in con.execute(
            "SELECT s.source_player_key,s.player_id,p.name,p.team,p.espn_id "
            "FROM player_source_ids s JOIN players p ON p.id=s.player_id "
            "WHERE s.source='fotmob'"):
        index[str(row[0])][int(row[1])] = {
            "id": row[1], "name": row[2], "team": row[3], "espn_id": row[4]
        }
    return {key: list(by_player.values()) for key, by_player in index.items()}


def resolve_appearance(name_index, source_index, league, name, fotmob_id,
                       allowed_player_ids=None):
    """Return (canonical row, evidence), failing closed on every ambiguity."""
    source_key = str(fotmob_id or "")
    if source_key in source_index:
        matches = source_index[source_key]
        return (matches[0], "fotmob_id") if len(matches) == 1 else (None, "ambiguous_id")
    if league in NATIONAL_TEAM_LEAGUES:
        # No name fallback for national teams. An unresolved row is retained in
        # the provider table and can bind later when its FotMob id reaches the
        # canonical club spine.
        return None, "unresolved_id"
    player = resolve(name_index, name, allowed_player_ids)
    return player, "name" if player else "unresolved_name"


def upsert(con, league, season, player, match_id, date, line, dry_run,
           fotmob_id=None, team=None, opponent=None, home_away=None,
           game_type=None):
    """Write FotMob's own row, into FotMob's own TABLE.

    Two earlier shapes, both wrong:

    1. MERGED into the ESPN row for the same (player_id, game_date). That put
       FotMob-sourced tackles on a row stamped `source='espn'` -- the column
       named the row's creator, not each field's origin. Reverted by
       scripts_unmerge_fotmob.py, 2,609 rows on dev and 1,790 on prod.
    2. A separate ROW in `player_game_logs`. That duplicated every shared
       appearance (2,619 on dev) and forced a ROW_NUMBER dedupe into the
       reader, which each of the 20+ other consumers of that table would have
       had to learn too. A duplication the reader hides is still a duplication.

    Now: a separate TABLE. `player_game_logs` is ESPN's and holds one row per
    appearance; this holds FotMob's, keyed the same way, including rows whose
    player never resolved. `player_game_logs_all` joins them so each provider's
    line sits in its own COLUMN and a value's provenance is the column it came
    from. See scripts_split_provider_logs.py. A third provider is a third
    table, not a migration of this one.
    """
    player_id = player["id"] if player else None
    if dry_run:
        return "inserted"
    con.execute(
        "INSERT INTO player_game_logs_fotmob"
        "(player_id, league, season, game_no, game_id, game_date, team, opponent,"
        " home_away, stats, source, source_player_key, game_type) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(league,source_player_key,season,game_no) DO UPDATE SET "
        "player_id=COALESCE(excluded.player_id,player_game_logs_fotmob.player_id), "
        "team=excluded.team, opponent=excluded.opponent,"
        "home_away=excluded.home_away, stats=excluded.stats,"
        "game_type=excluded.game_type, ingested_at=datetime('now')",
        # source_player_key must identify the PLAYER, not the fixture. It was
        # `fotmob-{match}-{team}` -- the same string for all eleven players on a
        # side -- so UNIQUE(league, source_player_key, season, game_no) allowed
        # ONE row per team per match and INSERT OR IGNORE silently dropped the
        # rest: a run reporting 795 inserts wrote 131.
        (player_id, league, season, f"fotmob-{match_id}", str(match_id), date,
         team, opponent, home_away, json.dumps(line), "fotmob",
         f"fotmob-{fotmob_id or player_id}", game_type))
    return "inserted"


def _score_pair(status):
    values = re.findall(r"\d+", str((status or {}).get("scoreStr") or ""))
    if len(values) < 2:
        return None, None
    return int(values[0]), int(values[1])


def normalize_fixture(match, competition_name):
    """FotMob fixture -> the provider-neutral scoreboard shape."""
    status = match.get("status") or {}
    finished = bool(status.get("finished"))
    started = bool(status.get("started"))
    cancelled = bool(status.get("cancelled"))
    state = "post" if finished or cancelled else "in" if started else "pre"
    reason = status.get("reason") or {}
    home_score, away_score = _score_pair(status)

    def side(raw, score):
        raw = raw or {}
        return {
            "abbrev": str(raw.get("shortName") or raw.get("name") or ""),
            "name": str(raw.get("name") or raw.get("shortName") or ""),
            "score": score,
        }

    detail = reason.get("short") or reason.get("long")
    return {
        "game_id": str(match.get("id") or ""),
        "date": status.get("utcTime"),
        "state": state,
        "completed": finished,
        "status": detail or ("Cancelled" if cancelled else "Live" if started else "Scheduled"),
        "status_detail": detail,
        "home": side(match.get("home"), home_score),
        "away": side(match.get("away"), away_score),
        "subtitle": competition_name,
    }


def store_scoreboard(con, league, fixtures, dry_run=False):
    """Persist FotMob's complete published fixture list, grouped by slate day."""
    from espn_client.scoreboard import _slate_day
    import scoreboard_store

    by_day = collections.defaultdict(list)
    for fixture in fixtures:
        normalized = normalize_fixture(fixture, fixture["_competition_name"])
        if not normalized["game_id"] or not normalized["date"]:
            continue
        day = _slate_day(league, normalized["date"])
        if day:
            by_day[day].append(normalized)
    if dry_run:
        return sum(len(games) for games in by_day.values()), len(by_day)
    scoreboard_store.init(con)
    written = 0
    for day, games in sorted(by_day.items()):
        written += scoreboard_store.save(league, day, games, source="fotmob", con=con)
    con.commit()
    return written, len(by_day)


def already_held(con, league, season, match_id):
    """True when this fixture's rows are already stored, so it costs nothing to skip.

    Every run used to fetch matchDetails for EVERY finished fixture in the season, one
    request each, including matches whose result cannot change. Measured 2026-09-06: a full
    MLS run spent its first ten minutes rewriting rows for 2026-02-21 through 05-17, which
    we already held, while the dates anyone was waiting on sat empty at the far end.

    `ingest_soccer_logs` has solved this next door with `_already_ingested`, and its comment
    says why: skipping stored matches is what makes a refresh resumable. This is the same
    rule against this table's own key.

    A fixture with zero stored rows is NOT held: a match that failed halfway must be
    retried, not skipped because something was written once.
    """
    row = con.execute(
        "SELECT COUNT(*) FROM player_game_logs_fotmob "
        "WHERE league=? AND season=? AND game_id=?",
        (league, season, str(match_id))).fetchone()
    return bool(row and row[0])


def record_published_schedule(con, league, finished):
    """Store the newest finished fixture FotMob publishes for this league, and when we asked.

    monitor_ingest_freshness compares our newest appearance row against this instead of
    the wall clock alone. On 2026-10-06 it alerted every hour that MLS was 101h stale and
    Leagues Cup 701h stale, while FotMob's own fixtures list said MLS last played 10-02
    (international break, next match 10-07) and Leagues Cup finished 09-07: we held both.
    An alarm that fires through every break and off-season teaches people to ignore it.
    """
    dates = [str((m.get("status") or {}).get("utcTime") or "")[:10] for m in finished]
    dates = [d for d in dates if d]
    con.execute("CREATE TABLE IF NOT EXISTS publisher_schedule("
                "league TEXT NOT NULL, publisher TEXT NOT NULL, newest_finished TEXT,"
                " finished_count INTEGER NOT NULL, checked_at TEXT NOT NULL,"
                " PRIMARY KEY (league, publisher))")
    con.execute("INSERT INTO publisher_schedule VALUES (?, 'fotmob', ?, ?, ?)"
                " ON CONFLICT(league, publisher) DO UPDATE SET"
                " newest_finished=excluded.newest_finished,"
                " finished_count=excluded.finished_count, checked_at=excluded.checked_at",
                (league, max(dates) if dates else None, len(finished),
                 time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())))
    con.commit()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--league", default="ligamx", choices=sorted(LEAGUES))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0,
                        help="stop after N fixtures (the NEWEST N)")
    parser.add_argument("--days-back", type=int, default=0,
                        help="only fetch finished match details from this many UTC days; "
                             "the complete fixture schedule is still stored")
    parser.add_argument("--force-refetch", action="store_true",
                        help="re-fetch fixtures already stored (use after changing what is "
                             "extracted from a match)")
    args = parser.parse_args(argv)

    _primary_league_id, season = LEAGUES[args.league]
    # Production has frequent short-lived scoreboard and capture writers. Wait
    # through those expected lock windows instead of aborting a long serial run.
    con = sqlite3.connect(DB_PATH, timeout=60)
    con.execute("PRAGMA busy_timeout = 60000")
    index = spine(con, args.league)
    source_index = fotmob_id_spine(con)
    print(f"{args.league}: {sum(len(v) for v in index.values())} league-spine players; "
          f"{len(source_index)} cross-competition FotMob ids")

    matches = []
    for league_id in LEAGUE_IDS[args.league]:
        document = _get(f"https://www.fotmob.com/api/data/leagues?id={league_id}")
        details = document.get("details") or {}
        if details.get("gender") != "male":
            raise RuntimeError(f"FotMob league {league_id} is not men's competition data")
        competition_name = str(details.get("name") or league_id)
        for match in (document.get("fixtures") or {}).get("allMatches") or []:
            match = dict(match)
            match["_competition_name"] = competition_name
            matches.append(match)
    if len({str(match.get("id")) for match in matches}) != len(matches):
        raise RuntimeError(f"{args.league}: duplicate FotMob match ids across competitions")
    matches.sort(key=lambda match: str((match.get("status") or {}).get("utcTime") or ""))
    scoreboard_rows, scoreboard_days = store_scoreboard(
        con, args.league, matches, dry_run=args.dry_run)
    print(f"{scoreboard_rows} fixtures across {scoreboard_days} scoreboard days "
          f"({len(LEAGUE_IDS[args.league])} league-document request(s))")

    finished = [m for m in matches
                if (m.get("status") or {}).get("finished")]
    if not args.dry_run:
        record_published_schedule(con, args.league, finished)
    if args.days_back:
        cutoff = (dt.datetime.now(dt.timezone.utc).date()
                  - dt.timedelta(days=args.days_back)).isoformat()
        finished = [m for m in finished
                    if str((m.get("status") or {}).get("utcTime") or "")[:10] >= cutoff]
    if args.limit:
        finished = finished[-args.limit:]
    print(f"{len(finished)} finished fixtures, 1 request each")

    counts = collections.Counter()
    for match in finished:
        match_id = match["id"]
        date = str((match.get("status") or {}).get("utcTime") or "")[:10]
        if not args.force_refetch and already_held(con, args.league, season, match_id):
            counts["skipped_already_held"] += 1
            continue
        try:
            detail = _get("https://www.fotmob.com/api/data/matchDetails"
                          f"?matchId={match_id}")
        except Exception as exc:  # noqa: BLE001 - one match is not the run
            print(f"  match {match_id}: fetch failed ({exc})")
            counts["fetch_failed"] += 1
            continue
        players = (detail.get("content") or {}).get("playerStats") or {}
        counts["fixtures"] += 1
        if not players:
            # A finished result is not evidence that FotMob published player
            # logs for it. Keep this as an explicit coverage miss; do not turn
            # an absent payload into zero-stat appearances.
            counts["fixtures_without_player_stats"] += 1
            continue
        # Cross-provider identity is strongest when the exact ESPN appearance
        # roster already exists.  Date scope turns duplicate domestic-spine
        # names (Víctor Guzmán at MTY and TOL) into one match participant while
        # still failing closed if both actually played that date.
        # ESPN's roster for this date NARROWS the spine when we have it: two players can
        # share a name in a league, and only one of them was in this match.
        #
        # An EMPTY set is not a narrow constraint, it is a guarantee of zero resolution, and
        # that is what it silently was. FotMob cannot resolve a date ESPN has not ingested,
        # so it could never get ahead of ESPN. Measured 2026-09-06: a live run reported
        # `fixtures=6 inserted=183 unresolved=183`, 100% unresolved, against a historical
        # 92.5% (8,954 of 9,679 stored MLS rows). Nothing was broken; the constraint was
        # empty, so every candidate was filtered out.
        #
        # With no ESPN rows for the date, fall back to the whole league spine and let
        # `resolve` fail closed on any name it cannot make unique. That is a weaker
        # constraint, honestly weaker, and it is the difference between resolving a player
        # and resolving nobody at all.
        appearance_ids = None
        if args.league not in NATIONAL_TEAM_LEAGUES:
            appearance_ids = {row[0] for row in con.execute(
                "SELECT DISTINCT player_id FROM player_game_logs "
                "WHERE league=? AND game_date=? AND player_id IS NOT NULL",
                (args.league, date),
            )} or None
        home = match.get("home") or {}
        away = match.get("away") or {}
        for fotmob_id, entry in players.items():
            line = stat_line(entry)
            if not line:
                continue
            who, evidence = resolve_appearance(
                index, source_index, args.league, entry.get("name"), fotmob_id,
                appearance_ids)
            counts[evidence] += 1
            team_id = str(entry.get("teamId") or "")
            if team_id == str(home.get("id") or ""):
                team, opponent, home_away = home.get("name"), away.get("name"), "home"
            elif team_id == str(away.get("id") or ""):
                team, opponent, home_away = away.get("name"), home.get("name"), "away"
            else:
                team, opponent, home_away = entry.get("teamName"), None, None
            counts[upsert(con, args.league, season, who, match_id, date,
                          line, args.dry_run, fotmob_id, team, opponent, home_away,
                          "EXH" if args.league == "friendlies" else "REG")] += 1
        if not args.dry_run:
            # Do not hold SQLite's single writer slot while the next serial
            # FotMob request sleeps. One fixture is the atomic retry unit.
            con.commit()

    if not args.dry_run:
        con.commit()
    landed = con.execute(
        "SELECT COUNT(*) FROM player_game_logs_fotmob WHERE league=?",
        (args.league,)).fetchone()[0]
    con.close()
    print("\n" + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if not args.dry_run:
        # Say what LANDED, not only what we attempted. A run that reported 795
        # inserts had written 131, and nothing in its own output disagreed.
        print(f"fotmob rows now in {args.league}: {landed}")
        if landed < counts["inserted"]:
            print(f"  RECONCILE: claimed {counts['inserted']} inserts, "
                  f"{landed} fotmob rows present -- writes were dropped")
    if args.dry_run:
        print("dry run -- nothing written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
