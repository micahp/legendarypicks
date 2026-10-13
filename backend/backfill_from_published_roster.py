#!/usr/bin/env python3
"""Give players we ALREADY have the identity and position their publisher already published.

`_resolve_player_for_ingest` consults `published_roster` before giving up, so a player created
from today onward is born carrying a FotMob id and a position. That does nothing for the rows
already in `players`. Measured on prod 2026-09-06: 11 active MLS players carried a blank
position, and one of them - Ezequiel Abadia-Reda - was sitting in the published roster under a
spelling that folds to exactly the one we stored. The resolver would have caught him. It never
looked, because he already existed.

So this is the same rule, applied backwards over what is already here.

WHAT IT WILL NOT DO
-------------------
Overwrite. A position we already hold is left alone even when the publisher disagrees, because
"another source says something else" is not evidence about which is right; that is a
reconciliation and it needs its own decision. Those disagreements are reported instead.

Bind a key that is already bound to somebody else. Two of our rows claiming one published
player is a DUPLICATE, and folding duplicates is `spine_merge.py`'s job, keyed on the
publisher id. This reports the collision and moves on rather than inventing a third way to
merge players.

Guess. Matching goes through `published_roster.lookup`, so it is the same fold, the same
uniqueness rule and the same reviewed aliases the resolver uses. One mechanism, so the two
can never drift into disagreeing about who somebody is.

Usage
-----
    python3 backfill_from_published_roster.py --league mls
    python3 backfill_from_published_roster.py --league mls --apply
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import published_roster

# REVIEWED DEPARTURES: a squad list is a claim about TODAY, so a player missing from one is
# either somebody who left or somebody the publisher simply does not carry. Those two look
# identical from here and they call for opposite actions, so neither is ever inferred. Each
# line below was checked against a dated, published announcement, and the citation is the
# point of the line.
#
# (league, folded name) -> (why, source)
REVIEWED_DEPARTURES = {
    ("mls", "gustavberggren"): (
        "transferred to Lech Poznan 2026-08-12; no longer an MLS player",
        "newyorkredbulls.com/news/red-bull-new-york-transfer-midfielder-gustav-berggren-"
        "to-lech-poznan"),
    ("mls", "nerimanaxundzade"): (
        "loaned to Erzurumspor FK through the 2027 season; FotMob has him there under "
        "Nariman Akhundzada, id 1392225",
        "columbuscrew.com/news/columbus-crew-loan-forward-nariman-akhundzada-to-super-lig-"
        "side-erzurumspor-futbol-kulubu"),
    ("mls", "jcngando"): (
        "Vancouver and Ngando mutually parted ways 2026-09-03; cleared waivers",
        "whitecapsfc.com - Whitecaps FC Part Ways with Midfielder J.C. Ngando"),
}

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")


def run(db_path, leagues, apply_changes):
    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    published_roster.ensure(con)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for league in leagues:
        players = con.execute(
            "SELECT id, name, team, position, position_group FROM players "
            "WHERE league=? AND active=1", (league,)).fetchall()
        bound = filled = collided = disagreed = 0
        unresolved = []
        for player in players:
            match = published_roster.lookup(con, league, player["name"], player["team"])
            if not match:
                if not (player["position"] or "").strip():
                    unresolved.append(player)
                continue
            source, key, position, group, _published_name = match
            owner = con.execute(
                "SELECT player_id FROM player_source_ids WHERE source=? AND league=? "
                "AND source_player_key=?", (source, league, key)).fetchone()
            if owner and owner["player_id"] != player["id"]:
                print("  COLLISION {} ({}) and player {} both claim {}:{}".format(
                    player["name"], player["id"], owner["player_id"], source, key))
                collided += 1
                continue
            if not owner:
                bound += 1
                if apply_changes:
                    con.execute(
                        "INSERT INTO player_source_ids(source, league, source_player_key, "
                        "player_id, first_seen, last_seen) VALUES(?,?,?,?,?,?) "
                        "ON CONFLICT(source, league, source_player_key) DO UPDATE SET "
                        "player_id=excluded.player_id, last_seen=excluded.last_seen",
                        (source, league, key, player["id"], now, now))
            held = (player["position"] or "").strip()
            if not held:
                filled += 1
                print("  {:<28} {:<6} -> {} / {}".format(
                    player["name"], player["team"] or "", position, group))
                if apply_changes:
                    con.execute(
                        "UPDATE players SET position=?, position_group=?, updated_at=? "
                        "WHERE id=?", (position, group, now, player["id"]))
            elif position and held != position:
                disagreed += 1
                print("  DISAGREES {:<28} we hold {}, {} publishes {}".format(
                    player["name"], held, source, position))
        print("{}: {} bound, {} positions filled, {} collisions, {} disagreements".format(
            league, bound, filled, collided, disagreed))
        if unresolved:
            print("  {} still blank, in no published squad. A publisher's squad is a claim "
                  "about TODAY, so this is where a departure looks the same as a gap:".format(
                      len(unresolved)))
            for player in unresolved:
                departure = REVIEWED_DEPARTURES.get(
                    (league, published_roster.fold(player["name"])))
                if departure:
                    print("    {:<28} {:<6} DEPARTED: {} [{}]".format(
                        player["name"], player["team"] or "", departure[0], departure[1]))
                    if apply_changes:
                        con.execute(
                            "UPDATE players SET active=0, updated_at=? WHERE id=?",
                            (now, player["id"]))
                    continue
                last_log = con.execute(
                    "SELECT MAX(game_date) FROM player_game_logs_all WHERE player_id=?",
                    (player["id"],)).fetchone()[0]
                last_prop = con.execute(
                    "SELECT MAX(captured_at) FROM props WHERE player_id=?",
                    (player["id"],)).fetchone()[0]
                print("    {:<28} {:<6} last log {} last priced {}".format(
                    player["name"], player["team"] or "", last_log or "never",
                    (last_prop or "never")[:10]))
    if apply_changes:
        con.commit()
    else:
        print("dry run: nothing written")
    con.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=DB)
    parser.add_argument("--league", action="append", dest="leagues")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    run(args.db, args.leagues or ["mls", "ligamx", "lcup"], args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
