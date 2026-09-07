#!/usr/bin/env python3
"""ingest_published_rosters.py: fill the roster the resolver reads.

`published_roster.py` explains why the table exists. This fills it, one league at a time,
from whichever publisher that league names. The resolver never fetches; it only reads what
this leaves behind, because it runs inside a request handler.

Each league declares its own source rather than the resolver branching on league:

    mls, ligamx, lcup    FotMob squads, one request per club, on FotMob's own host

NFL should take nflverse and MLB the MLB API when someone adds them. Adding a league is a row
in `_PROVIDERS`, not a change to anything that reads the table.

WHAT IT WILL NOT DO. Write an empty roster over a full one. An empty result is a request that
told us nothing, not a league with no players, and the resolver would then start refusing
people it had been resolving yesterday.
"""
import argparse
import datetime as dt
import os
import sqlite3
import sys
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import published_roster
from ingest_fotmob_soccer_logs import _get as _fotmob_get

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

# FotMob's squad group -> (position, position_group), in the vocabulary these databases
# already store for soccer. `coach` is deliberately absent: a coach is not a player.
_FOTMOB_GROUPS = {
    "keepers": ("G", "Goalkeeper"),
    "defenders": ("D", "Defender"),
    "midfielders": ("M", "Midfielder"),
    "attackers": ("F", "Forward"),
}


def _fotmob_squads(con, league: str) -> List[Dict]:
    """Every squad member FotMob publishes for a league, via `league_clubs`.

    Uses the club list the FotMob club ingest already stores, so this needs no club list of
    its own and the two cannot disagree about which clubs exist.
    """
    clubs = con.execute(
        "SELECT name, code FROM league_clubs WHERE league=? AND code GLOB '[0-9]*'",
        (league,)).fetchall()
    if not clubs:
        print("  {}: no published clubs stored; run ingest_league_clubs.py first".format(league))
        return []
    out: List[Dict] = []
    for club_name, club_id in clubs:
        try:
            document = _fotmob_get(
                "https://www.fotmob.com/api/data/teams?id={}".format(club_id))
        except Exception as exc:  # noqa: BLE001 - one club is not the run
            print("  {} club {}: fetch failed ({})".format(league, club_name, exc))
            continue
        for group in (document.get("squad") or {}).get("squad") or []:
            mapped = _FOTMOB_GROUPS.get((group.get("title") or "").strip().lower())
            if not mapped:
                continue
            for member in group.get("members") or []:
                if not member.get("id") or not member.get("name"):
                    continue
                out.append({
                    "source": "fotmob",
                    "source_player_key": str(member["id"]),
                    "name": member["name"],
                    "team": club_name,
                    "position": mapped[0],
                    "position_group": mapped[1],
                })
    return out


_PROVIDERS = {
    "mls": _fotmob_squads,
    "ligamx": _fotmob_squads,
    "lcup": _fotmob_squads,
}


def ingest(leagues, dry_run=True):
    con = sqlite3.connect(DB, timeout=30)
    published_roster.ensure(con)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    total = 0
    for league in leagues:
        provider = _PROVIDERS.get(league)
        if provider is None:
            print("  {}: no publisher declared for this league; skipped".format(league))
            continue
        members = provider(con, league)
        if not members:
            # Never overwrite a full roster with an empty fetch.
            print("  {}: published NOTHING; leaving the stored roster alone".format(league))
            continue
        print("  {}: {} published squad members".format(league, len(members)))
        if dry_run:
            continue
        con.executemany(
            "INSERT INTO published_roster(league, source, source_player_key, name, "
            "name_folded, team, position, position_group, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(league, source, source_player_key) DO UPDATE SET "
            "name=excluded.name, name_folded=excluded.name_folded, team=excluded.team, "
            "position=excluded.position, position_group=excluded.position_group, "
            "updated_at=excluded.updated_at",
            [(league, m["source"], m["source_player_key"], m["name"],
              published_roster.fold(m["name"]), m["team"], m["position"],
              m["position_group"], now) for m in members])
        total += len(members)
    if not dry_run:
        con.commit()
    held = con.execute(
        "SELECT league, COUNT(*) FROM published_roster GROUP BY league ORDER BY 1").fetchall()
    con.close()
    print("  wrote {}{}".format(total, " (dry run: nothing written)" if dry_run else ""))
    for league, count in held:
        print("    published_roster holds {} members for {}".format(count, league))
    return total


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("leagues", nargs="*", help="default: every league with a publisher")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    ingest(args.leagues or sorted(_PROVIDERS), dry_run=not args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
