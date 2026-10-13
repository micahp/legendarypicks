#!/usr/bin/env python3
"""backfill_mls_identity_fotmob.py: give a shadow MLS player a published identity.

WHAT IS BROKEN.

`bovada_scraper` mints a `players` row from a sportsbook display name when it cannot resolve
one. Those rows carry no publisher id and no position, because a sportsbook publishes
neither. Measured on prod 2026-09-06: 27 ACTIVE MLS players with `espn_id=None`,
`updated_at=None`, 26 of them carrying props, and the release audit failing on
`C/vocabulary[position]` and `C/vocabulary[position_group]` because of exactly those 27.

They cannot be repaired by merging. `spine_merge.py` refuses them, correctly:

    REFUSE mls 'Giovanny Sequera': every row is unresolved; nothing to merge into

Neither of that player's two rows has a publisher id, so nothing proves they are one person,
and merging on a matching name is what made 124 of 317 MLB "duplicate" groups two different
people. The missing thing is not a merge. It is an identity.

WHY FOTMOB AND NOT ESPN. `ingest_mls_ncaaf_rosters` upserts on `espn_id`, so it can never
repair a row that has none: a re-run inserts a proper row alongside the blank one and the
blank stays. ESPN is also the publisher whose per-minute budget is shared with the serving
path. FotMob publishes a full squad per club with a stable id and a position group, on its
own host, and we already depend on it for MLS appearances.

WHAT THIS FIXES, IN ONE ACT. Writing the FotMob id into `player_source_ids` gives these rows
the portable key they lacked, so `spine_merge` can then fold genuine duplicates on a SHARED
SOURCE ID rather than on a name. The position is a side effect of having found the person.

HOW IT REFUSES. A name must resolve to exactly ONE squad member across the whole league. A
name in two squads is ambiguous and is counted, not guessed: two real players do share a
name. A player in no squad is reported, not invented; on prod that is 11 of 27, mostly
departures and one Liga MX player filed under `mls`.
"""
import argparse
import datetime as dt
import os
import re
import sqlite3
import sys
import unicodedata
from typing import Dict, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ingest_fotmob_soccer_logs import _get as _fotmob_get

LEAGUE = "mls"
SOURCE = "fotmob"
DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

# FotMob's squad group -> (our position, our position_group). Read off the vocabulary this
# database already stores for MLS: D/M/F/G and Defender/Midfielder/Forward/Goalkeeper.
# `coach` is deliberately absent: a coach is not a player and must never be filed as one.
_GROUPS: Dict[str, Tuple[str, str]] = {
    "keepers": ("G", "Goalkeeper"),
    "defenders": ("D", "Defender"),
    "midfielders": ("M", "Midfielder"),
    "attackers": ("F", "Forward"),
}


def fold(value) -> str:
    ascii_value = (unicodedata.normalize("NFKD", str(value or ""))
                   .encode("ascii", "ignore").decode("ascii"))
    return re.sub(r"[^a-z ]+", "", ascii_value.lower()).strip()


def squad_index(con) -> Dict[str, list]:
    """{folded name: [(fotmob_id, position, position_group, club)]} for the whole league.

    Built from `league_clubs`, which the FotMob club ingest already populates, so this needs
    no club list of its own. A name is kept as a LIST because uniqueness is the caller's
    check, not something to silently collapse here.
    """
    index: Dict[str, list] = {}
    clubs = con.execute(
        "SELECT name, code FROM league_clubs WHERE league=? AND code GLOB '[0-9]*'",
        (LEAGUE,)).fetchall()
    for club_name, club_id in clubs:
        try:
            document = _fotmob_get(
                "https://www.fotmob.com/api/data/teams?id={}".format(club_id))
        except Exception as exc:  # noqa: BLE001 - one club is not the run
            print("  club {} ({}): fetch failed ({})".format(club_name, club_id, exc))
            continue
        for group in (document.get("squad") or {}).get("squad") or []:
            mapped = _GROUPS.get((group.get("title") or "").strip().lower())
            if not mapped:
                continue
            for member in group.get("members") or []:
                key = fold(member.get("name"))
                if not key or not member.get("id"):
                    continue
                index.setdefault(key, []).append(
                    (str(member["id"]), mapped[0], mapped[1], club_name))
    print("  indexed {} squad members across {} clubs".format(
        sum(len(v) for v in index.values()), len(clubs)))
    return index


def backfill(dry_run=True):
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    blanks = con.execute(
        "SELECT id, name, team FROM players WHERE league=? AND active=1 "
        "AND (position IS NULL OR position='')", (LEAGUE,)).fetchall()
    print("  blank-position active {} players: {}".format(LEAGUE, len(blanks)))
    if not blanks:
        con.close()
        return {}

    index = squad_index(con)
    if not index:
        # An empty index is a failed fetch, not a league with no players. Writing nothing is
        # right; reporting success would not be.
        print("  REFUSING: the squad index is empty, so nothing could be resolved")
        con.close()
        raise SystemExit(2)

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    counts = dict(resolved=0, ambiguous=0, unfound=0, duplicate=0)
    # publisher id -> the players.id already bound to it in THIS run. A second row resolving
    # to the same published person is not a conflict to overwrite, it is the duplicate
    # evidence spine_merge was missing: `ux_player_source_ids` is UNIQUE on
    # (source, league, source_player_key) precisely because one source key names one person.
    bound = {}
    for row in blanks:
        matches = index.get(fold(row["name"]), [])
        if not matches:
            counts["unfound"] += 1
            print("    NOT in any squad   {:<26} team={}".format(row["name"][:26], row["team"]))
            continue
        if len({m[0] for m in matches}) != 1:
            counts["ambiguous"] += 1
            print("    AMBIGUOUS          {:<26} in {}".format(
                row["name"][:26], ", ".join(sorted(m[3] for m in matches))))
            continue
        fotmob_id, position, group, club = matches[0]
        if fotmob_id in bound:
            counts["duplicate"] += 1
            print("    DUPLICATE          {:<26} is the same published person as players.id"
                  " {} (fotmob={}). Position filled; the fold is spine_merge's call, on the"
                  " shared source id rather than on the name.".format(
                      row["name"][:26], bound[fotmob_id], fotmob_id))
            if not dry_run:
                con.execute(
                    "UPDATE players SET position=?, position_group=?, updated_at=? WHERE id=?",
                    (position, group, now, row["id"]))
            continue
        bound[fotmob_id] = row["id"]
        counts["resolved"] += 1
        print("    resolved           {:<26} {} ({}) fotmob={} via {}".format(
            row["name"][:26], position, group, fotmob_id, club))
        if dry_run:
            continue
        con.execute(
            "UPDATE players SET position=?, position_group=?, updated_at=? WHERE id=?",
            (position, group, now, row["id"]))
        con.execute(
            "INSERT INTO player_source_ids(source, league, source_player_key, player_id, "
            "first_seen, last_seen) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(source, league, source_player_key) DO UPDATE SET "
            "player_id=excluded.player_id, last_seen=excluded.last_seen",
            (SOURCE, LEAGUE, fotmob_id, row["id"], now, now))
    if not dry_run:
        con.commit()
    remaining = con.execute(
        "SELECT COUNT(*) FROM players WHERE league=? AND active=1 "
        "AND (position IS NULL OR position='')", (LEAGUE,)).fetchone()[0]
    con.close()
    # Say every bucket, including the zeros: a run that resolved nothing must look different
    # from a run that never happened.
    print("  resolved={resolved} duplicate={duplicate} ambiguous={ambiguous} "
          "not-in-any-squad={unfound}".format(**counts))
    print("  blank-position players remaining: {}{}".format(
        remaining, " (dry run: unchanged)" if dry_run else ""))
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    backfill(dry_run=not args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
