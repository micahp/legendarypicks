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
import json
import os
import sqlite3
import sys
import time
import unicodedata
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DB_PATH = os.environ.get("LP_DB_PATH", "data/picks.dev.db")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# FotMob league ids, verified against its own allLeagues document.
LEAGUES = {"ligamx": (230, 2026), "lcup": (10043, 2026), "mls": (130, 2026)}

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


def resolve(index, name):
    """One spine row, or None. A name naming two players resolves to neither."""
    matches = index.get(fold(name), [])
    return matches[0] if len(matches) == 1 else None


def upsert(con, league, season, player, match_id, date, line, dry_run,
           fotmob_id=None):
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
    cursor = con.execute(
        "INSERT OR IGNORE INTO player_game_logs_fotmob"
        "(player_id, league, season, game_no, game_id, game_date, stats,"
        " source, source_player_key) VALUES(?,?,?,?,?,?,?,?,?)",
        # source_player_key must identify the PLAYER, not the fixture. It was
        # `fotmob-{match}-{team}` -- the same string for all eleven players on a
        # side -- so UNIQUE(league, source_player_key, season, game_no) allowed
        # ONE row per team per match and INSERT OR IGNORE silently dropped the
        # rest: a run reporting 795 inserts wrote 131.
        (player_id, league, season, f"fotmob-{match_id}", str(match_id), date,
         json.dumps(line), "fotmob", f"fotmob-{fotmob_id or player_id}"))
    return "inserted" if cursor.rowcount else "unchanged"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--league", default="ligamx", choices=sorted(LEAGUES))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0,
                        help="stop after N fixtures")
    args = parser.parse_args(argv)

    league_id, season = LEAGUES[args.league]
    # Production has frequent short-lived scoreboard and capture writers. Wait
    # through those expected lock windows instead of aborting a long serial run.
    con = sqlite3.connect(DB_PATH, timeout=60)
    con.execute("PRAGMA busy_timeout = 60000")
    index = spine(con, args.league)
    print(f"{args.league}: {sum(len(v) for v in index.values())} spine players")

    fixtures = _get(f"https://www.fotmob.com/api/data/leagues?id={league_id}")
    finished = [m for m in fixtures["fixtures"]["allMatches"]
                if (m.get("status") or {}).get("finished")]
    if args.limit:
        finished = finished[-args.limit:]
    print(f"{len(finished)} finished fixtures, 1 request each")

    counts = collections.Counter()
    for match in finished:
        match_id = match["id"]
        date = str((match.get("status") or {}).get("utcTime") or "")[:10]
        try:
            detail = _get("https://www.fotmob.com/api/data/matchDetails"
                          f"?matchId={match_id}")
        except Exception as exc:  # noqa: BLE001 - one match is not the run
            print(f"  match {match_id}: fetch failed ({exc})")
            counts["fetch_failed"] += 1
            continue
        players = (detail.get("content") or {}).get("playerStats") or {}
        counts["fixtures"] += 1
        for fotmob_id, entry in players.items():
            line = stat_line(entry)
            if not line:
                continue
            who = resolve(index, entry.get("name"))
            counts["resolved" if who else "unresolved"] += 1
            counts[upsert(con, args.league, season, who, match_id, date,
                          line, args.dry_run, fotmob_id)] += 1
        if not args.dry_run and counts["fixtures"] % 10 == 0:
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
