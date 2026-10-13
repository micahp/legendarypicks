#!/usr/bin/env python3
"""merge_shadow_players.py - retire duplicate `players` rows minted from a book.

Bovada used to mint a `players` row straight from a sportsbook display name when
the spine had no match, with no publisher id behind it. `bovada_scraper/direct.py`
still documents the cost: 531 shadow rows in prod MLS, each duplicating an athlete
the spine already held, so prop -> player -> game_log never joined for any of them.
The mint is now scoped to `wc` and `ufc`; these are the survivors.

A shadow row is merged ONLY when two independent signals name the same athlete:

  1. our own rostered spine (a row carrying an espn_id) matches the name, and
  2. the club's roster as ESPN published it on the artifact date matches on
     surname plus first initial.

Two signals because one is how a prop lands on the wrong athlete. The club code
deliberately does NOT have to agree: it is the field the book gets wrong (a
Seattle player published as `TOL`, an LAFC player as `NFO`), so requiring it
would reject exactly the rows most worth fixing. It is used only to break a tie
between two athletes sharing a surname.

A prop that already exists on the canonical row with the same
(game_id, market, line, side, source) is a duplicate of a prop we already hold,
and is dropped rather than repointed. That is the only destructive step and it
is counted and printed per player.

Usage:
  LP_DB_PATH=<db> python3 scripts/merge_shadow_players.py --league mls          # dry run
  LP_DB_PATH=<db> python3 scripts/merge_shadow_players.py --league mls --apply
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_DB = os.environ.get(
    "LP_DB_PATH", os.path.join(ROOT, "backend", "data", "picks.db"))
ROSTER = os.path.join(ROOT, "docs", "espn-mls-roster-2026-08-25.json")
PROP_KEY = ("game_id", "market", "line", "side", "source")


def fold(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z]", " ", s.lower()).split()


def pairs(con, league, published):
    """(shadow_row, canonical_id) for every row both signals agree on."""
    rostered = [dict(r) for r in con.execute(
        "SELECT id,name,team,espn_id FROM players "
        "WHERE league=? AND espn_id IS NOT NULL AND espn_id!=''", (league,))]
    by_name = {}
    for r in rostered:
        by_name.setdefault(" ".join(fold(r["name"])), []).append(r)
    by_surname = {}
    for aid, v in published.items():
        t = fold(v["name"])
        if t:
            by_surname.setdefault(t[-1], []).append((aid, v))

    out, skipped = [], []
    for row in con.execute(
            "SELECT id,name,team FROM players WHERE league=? "
            "AND (espn_id IS NULL OR espn_id='') ORDER BY name", (league,)):
        row = dict(row)
        t = fold(row["name"])
        spine = by_name.get(" ".join(t), [])
        cands = [c for c in by_surname.get(t[-1], []) if t
                 and fold(c[1]["name"])[0][:1] == t[0][:1]]
        if len(cands) > 1:
            tie = [c for c in cands
                   if c[1]["team"] == (row["team"] or "").upper()]
            cands = tie if len(tie) == 1 else []
        if len(spine) != 1 or len(cands) != 1:
            skipped.append((row, "signals: spine=%d published=%d"
                            % (len(spine), len(cands))))
            continue
        if spine[0]["espn_id"] != cands[0][0]:
            # Two signals naming two different athletes is the one outcome that
            # must never be resolved by preferring either. Leave it.
            skipped.append((row, "signals DISAGREE: %s vs %s"
                            % (spine[0]["espn_id"], cands[0][0])))
            continue
        out.append((row, spine[0]["id"], spine[0]["espn_id"], cands[0][1]["team"]))
    return out, skipped


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--league", default="mls")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--apply", action="store_true",
                    help="write; without it nothing is changed")
    args = ap.parse_args(argv)

    with open(ROSTER) as fh:
        published = json.load(fh)["athletes"]

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row

    def orphans():
        return con.execute(
            "SELECT COUNT(*) FROM props p "
            "LEFT JOIN players pl ON pl.id=p.player_id "
            "WHERE pl.id IS NULL").fetchone()[0]

    # Measured BEFORE, because this database already carries orphaned props that
    # have nothing to do with the merge (78 on both dev and prod, 2026-08-25).
    # A guard that compares the after-count to zero fails on someone else's
    # defect and says nothing about this one. The claim being checked is "this
    # merge orphaned nothing", so the ruler has to be the same on both sides.
    before = orphans()
    matched, skipped = pairs(con, args.league, published)

    print("db        %s" % args.db)
    print("roster    %s (%d athletes)" % (os.path.basename(ROSTER), len(published)))
    print("mode      %s\n" % ("APPLY" if args.apply else "dry run"))

    sel = ",".join(PROP_KEY)
    moved = dropped = 0
    for row, canonical, espn_id, espn_team in matched:
        theirs = {tuple(r) for r in con.execute(
            "SELECT %s FROM props WHERE player_id=?" % sel, (canonical,))}
        # `props.id` is the primary key; the select carries it at position 0,
        # so compare on the tail.
        clash = [rid for k, rid in
                 ((tuple(r)[1:], r[0]) for r in con.execute(
                     "SELECT id,%s FROM props WHERE player_id=?" % sel,
                     (row["id"],)))
                 if k in theirs]
        n_props = con.execute(
            "SELECT COUNT(*) FROM props WHERE player_id=?", (row["id"],)).fetchone()[0]
        n_move = n_props - len(clash)
        print("  %-24s shadow %-6d -> %-6d  espn %-7s %-5s  "
              "move %d, drop %d duplicate" % (
                  row["name"], row["id"], canonical, espn_id, espn_team,
                  n_move, len(clash)))
        moved += n_move
        dropped += len(clash)
        if args.apply:
            if clash:
                con.execute("DELETE FROM props WHERE id IN (%s)"
                            % ",".join("?" * len(clash)), clash)
            con.execute("UPDATE props SET player_id=? WHERE player_id=?",
                        (canonical, row["id"]))
            for table, col in (("player_source_ids", "player_id"),
                               ("name_alias", "player_id")):
                try:
                    con.execute("UPDATE OR IGNORE %s SET %s=? WHERE %s=?"
                                % (table, col, col), (canonical, row["id"]))
                except sqlite3.OperationalError:
                    pass
            con.execute("DELETE FROM players WHERE id=?", (row["id"],))

    print("\n  merged %d row(s): %d prop(s) repointed, %d duplicate prop(s) dropped"
          % (len(matched), moved, dropped))
    print("  left alone: %d" % len(skipped))
    for row, why in skipped:
        print("     %-24s %-5s %s" % (row["name"], row["team"], why))

    if args.apply:
        after = orphans()
        left = con.execute(
            "SELECT COUNT(*) FROM players WHERE league=? "
            "AND (espn_id IS NULL OR espn_id='')", (args.league,)).fetchone()[0]
        print("\n  orphaned props: %d before, %d after" % (before, after))
        if after > before:
            con.rollback()
            raise SystemExit(
                "this merge orphaned %d prop(s); rolled back" % (after - before))
        con.commit()
        print("  after: %d shadow row(s) remain" % left)
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
