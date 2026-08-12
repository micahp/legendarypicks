#!/usr/bin/env python3
"""Move props off a same-named player who was not in the game.

Two men named Max Muncy play in this league. The prop ingest matched on
(name, league) and took whichever row the database yielded first, so 433 Dodgers
props were written onto the Athletics Muncy's row. Nothing raised — an ambiguous
key never raises, it misses — and the graded results that followed were scored
against a box score the man never appeared in.

The repair uses the one signal that is published and exact: a prop belongs to a
game, and a game names its two teams. A prop sitting on a player whose team is not
in that game, when exactly one other row of the same name IS in that game, is
mislinked to a knowable target. Anything short of that is left alone and printed.

Any result row for a repointed prop is deleted, not rewritten — it was graded
against the wrong player, and the grader is what decides the new value.

    python repair_mislinked_same_name_props.py            # dry run
    python repair_mislinked_same_name_props.py --apply
"""
import argparse
import datetime as dt
import os
import shutil
import sqlite3
import sys
from collections import defaultdict

from link_prop_games import _TEAM_MAPS

DB = os.environ.get("LP_DB_PATH", "data/picks.db")

# The publisher id that makes a row a real identity rather than a name someone typed.
_LEAGUE_ID_COL = {"mlb": "mlbam_id", "nfl": "nfl_gsis_id", "nhl": "nhl_id", "nba": "nba_id"}


def game_teams(league, home, away):
    """The game's two teams as abbrevs; prop_games mixes full names and codes."""
    tmap = _TEAM_MAPS.get(league, {})
    out = set()
    for value in (home, away):
        value = (value or "").strip()
        if value:
            out.add(tmap.get(value.lower(), value.upper()))
    return out


def plan(con):
    """(moves, skips) — moves are (prop_id, from_id, to_id, game_id, why)."""
    dupes = con.execute(
        "SELECT name, league FROM players GROUP BY name, league HAVING COUNT(*)>1"
    ).fetchall()

    moves, skips = [], []
    for d in dupes:
        idcol = _LEAGUE_ID_COL.get(d["league"])
        if not idcol:
            continue
        rows = con.execute(
            f"SELECT id, team, {idcol} AS pub_id, "
            "(SELECT COUNT(*) FROM props x WHERE x.player_id=players.id) AS props "
            "FROM players WHERE name=? AND league=?", (d["name"], d["league"])
        ).fetchall()
        if not any(r["props"] for r in rows):
            continue  # nothing hangs off these rows; not this script's problem

        # A row with no publisher id is a stub someone's ingest minted, not a second
        # man. Moving props between a real row and a stub hides a duplicate that
        # wants deduping — refuse, and say so.
        if any(r["pub_id"] is None for r in rows):
            stubs = [r["id"] for r in rows if r["pub_id"] is None]
            skips.append(
                f"{d['name']} ({d['league']}): row(s) {stubs} carry no {idcol} — "
                f"a duplicate to dedupe, not a mislink to repoint")
            continue

        by_team = defaultdict(list)
        for r in rows:
            by_team[(r["team"] or "").strip().upper()].append(r["id"])
        if "" in by_team:
            skips.append(f"{d['name']} ({d['league']}): row(s) {by_team['']} carry no team — cannot place them in a game")

        for r in rows:
            team = (r["team"] or "").strip().upper()
            if not team:
                continue
            props = con.execute(
                "SELECT p.id AS prop_id, g.id AS game_id, g.home, g.away "
                "FROM props p JOIN prop_games g ON g.id=p.game_id WHERE p.player_id=?",
                (r["id"],)
            ).fetchall()
            for p in props:
                teams = game_teams(d["league"], p["home"], p["away"])
                if not teams or team in teams:
                    continue  # he is in this game, or we cannot read the game
                targets = [pid for t, ids in by_team.items() if t and t in teams for pid in ids]
                if len(targets) != 1:
                    skips.append(
                        f"{d['name']} ({d['league']}) prop {p['prop_id']} game {p['game_id']} "
                        f"{p['away']} @ {p['home']}: {len(targets)} same-named candidates in the game")
                    continue
                moves.append((p["prop_id"], r["id"], targets[0], p["game_id"],
                              f"{d['name']}: {team} not in {p['away']} @ {p['home']}"))
    return moves, skips


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    moves, skips = plan(con)

    by_pair = defaultdict(list)
    for prop_id, src, dst, game_id, why in moves:
        by_pair[(src, dst, why.split(":")[0])].append(prop_id)

    print(f"{'APPLY' if args.apply else 'DRY RUN'} — {len(moves)} mislinked props, {len(by_pair)} player pairs")
    for (src, dst, name), props in sorted(by_pair.items(), key=lambda kv: -len(kv[1])):
        graded = con.execute(
            "SELECT COUNT(*) FROM prop_results WHERE prop_id IN (%s)" % ",".join("?" * len(props)),
            props).fetchone()[0]
        print(f"  {name}: {len(props)} props {src} -> {dst} ({graded} already graded, results dropped)")
    for s in sorted(set(skips)):
        print(f"  SKIP {s}")

    if not args.apply or not moves:
        return 0

    backup = f"{DB}.pre-mislink-{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}.bak"
    shutil.copy2(DB, backup)
    print(f"  backup: {backup}")

    with con:
        for prop_id, _src, dst, _game_id, _why in moves:
            con.execute("UPDATE props SET player_id=? WHERE id=?", (dst, prop_id))
            con.execute("DELETE FROM prop_results WHERE prop_id=?", (prop_id,))
    print(f"  repointed {len(moves)} props; their results deleted for regrade")
    return 0


if __name__ == "__main__":
    sys.exit(main())
