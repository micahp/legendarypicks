#!/usr/bin/env python3
"""repair_mislabelled_fixtures.py: put a fixture under the league it was actually played in.

`audit_foreign_fixtures.py` finds games filed under a league they do not belong to. This
repairs the two kinds it finds, and refuses everything else.

RELABEL. A fixture whose clubs are all members of one other league we know is moved to that
league. Four Liga MX games sat under `lcup`, which is MLS against Liga MX by definition, and
one sat under `mls`. Two of them carry settled results, so this must NEVER delete: the games
were played, the props graded, and only the label was wrong.

FOLD. A fixture that duplicates one we already hold correctly is folded into it with
`prop_game_merge.fold_prop_game`, which repoints every reference before dropping the loser.
2351 (`lcup`, unlinked, 249 props) is the same match as 2106 (`mls`, espn_event_id 761780,
40 props): same date, same clubs, different spelling.

WHAT IT REFUSES. A fixture with no home league we can name. Sassuolo @ Bologna is Serie A,
which this project does not carry, so there is nowhere honest to put it and inventing a
league would be worse than leaving it visible to the audit.

The target is DERIVED from league_membership, never hardcoded, so this cannot quietly
disagree with the check that found the problem.

Usage:
  LP_DB_PATH=.../picks.db venv/bin/python repair_mislabelled_fixtures.py
  LP_DB_PATH=.../picks.db venv/bin/python repair_mislabelled_fixtures.py --apply
"""
import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import league_membership
from prop_game_merge import fold_prop_game

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

# Leagues a mislabelled fixture may be moved INTO. Deliberately a short list of competitions
# this project already carries: a relabel must land somewhere real.
_CANDIDATES = ("mls", "ligamx", "lcup", "nfl", "mlb", "nba", "nhl", "ncaaf")


def _twin(con, row):
    """A correctly-filed game that is the same match, or None.

    Same date and both clubs, with an ESPN event id, which is the crosswalk having agreed
    that the fixture is real. Requiring the id is what stops one unverified row folding into
    another unverified row.
    """
    for other in con.execute(
            "SELECT id, league, home, away FROM prop_games "
            "WHERE date=? AND id<>? AND COALESCE(espn_event_id,'') <> ''",
            (row["date"], row["id"])):
        clubs = {league_membership.fold(other["home"]), league_membership.fold(other["away"])}
        mine = {league_membership.fold(row["home"]), league_membership.fold(row["away"])}
        if clubs == mine:
            return other
        # One publisher writes "Seattle Sounders", the other "Seattle Sounders FC".
        if all(any(a.startswith(b) or b.startswith(a) for b in clubs) for a in mine):
            return other
    return None


def plan(con):
    cache = {}
    relabels, folds, refused = [], [], []
    rows = con.execute(
        "SELECT id, league, date, home, away, espn_event_id FROM prop_games").fetchall()
    for row in rows:
        verdict = league_membership.belongs(
            con, row["league"], row["home"], row["away"], _cache=cache, strict=True)
        if verdict is not False:
            continue
        twin = _twin(con, row)
        if twin is not None:
            folds.append((row, twin))
            continue
        homes = [league for league in _CANDIDATES
                 if league != row["league"]
                 and league_membership.belongs(
                     con, league, row["home"], row["away"], _cache=cache, strict=True)]
        if len(homes) == 1:
            relabels.append((row, homes[0]))
        else:
            # Zero candidates means no league we carry; more than one means the clubs are
            # ambiguous across competitions. Both are a human's decision, not a script's.
            refused.append((row, homes))
    return relabels, folds, refused


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    relabels, folds, refused = plan(con)

    def props(game_id):
        return con.execute(
            "SELECT COUNT(*) FROM props WHERE game_id=?", (game_id,)).fetchone()[0]

    def settled(game_id):
        return con.execute(
            "SELECT COUNT(*) FROM prop_results r JOIN props p ON p.id=r.prop_id "
            "WHERE p.game_id=?", (game_id,)).fetchone()[0]

    print("relabel: {}".format(len(relabels)))
    for row, target in relabels:
        print("  id={:<6} {} -> {:<7} {} {} @ {}  props={} settled={}".format(
            row["id"], row["league"], target, row["date"], row["away"], row["home"],
            props(row["id"]), settled(row["id"])))
    print("fold: {}".format(len(folds)))
    for row, twin in folds:
        print("  id={:<6} ({}) -> id={} ({}, espn-linked)  {} props move".format(
            row["id"], row["league"], twin["id"], twin["league"], props(row["id"])))
    print("refused: {}".format(len(refused)))
    for row, homes in refused:
        print("  id={:<6} {} {} @ {}  candidates={}  [{}]".format(
            row["id"], row["league"], row["away"], row["home"], homes or "none",
            "no league we carry" if not homes else "ambiguous across competitions"))

    if not args.apply:
        print("audit only; pass --apply")
        con.close()
        return 0

    for row, target in relabels:
        con.execute("UPDATE prop_games SET league=? WHERE id=?", (target, row["id"]))
    for row, twin in folds:
        fold_prop_game(con, row["id"], twin["id"])
    con.commit()
    print("applied: {} relabelled, {} folded, {} left alone".format(
        len(relabels), len(folds), len(refused)))
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
