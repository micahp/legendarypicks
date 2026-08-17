#!/usr/bin/env python3
"""Repair the two MLB `players` rows that props can never settle against.

Settlement resolves an MLB prop through `players.mlbam_id` (settlement.py builds its
lookup from `WHERE league='mlb' AND mlbam_id IS NOT NULL AND mlbam_id != 0`). A prop
hanging off a row with no mlbam_id is therefore not "hard to grade" -- it is outside
the query that grades anything, permanently. On 2026-08-17 prod held 380 such props
and dev 406, every one of them unsettled, across exactly two rows.

They are two different defects and get two different repairs.

1. `James Outman` -- a duplicate person
-----------------------------------------------------------------------
    id 26852  mlbam 681546  DET  active   70 game logs, 1 stat row, 2 rosters,   0 props
    id 29097  mlbam NULL    MIN  inactive  0 game logs,                        51 props

MLB Stats publishes exactly one James Outman (`people/search?names=James Outman` ->
681546), so this is one person on two rows, and every prop landed on the copy that
cannot resolve while all the real data sits on the copy that can. This is a MERGE:
props repoint to 26852 and the shadow row goes. Odds snapshots hang off `prop_id`,
not `player_id`, so they follow the props untouched.

The merge is keyed on the PUBLISHED id, not the name. The name is what made the two
rows look alike; it is not what proves they are the same person -- see
project_lp_mlb_pitcher_name_corruption. Four other MLB name collisions in prod are
genuinely different people (two Max Muncys, two Jared Joneses, two Gabriel Rodriguezes,
two Luis Castillos, each pair holding two distinct mlbam ids) and this script must not
touch them. It is written to act on these ids alone and to verify the shape first.

2. The nameless row -- props with no player at all
-----------------------------------------------------------------------
    id 28987  name ''  team ''  mlbam NULL  329 props (prod), 346 (dev)

Not a person. A bucket. Two unrelated shapes fell into it because the old market regex
demanded an uppercase team parenthetical and anything without one produced an empty
name that nothing downstream rejected:

  * 152 `total_hits,_runs_and_errors` -- a GAME-level market. There is no player to
    attribute it to, so it was never a player prop.
  * ~177 player props whose names never resolved -- Cooper Pratt, Sean Keys, Ivan
    Johnson, Brett Bateman, Kohl Drake, Kyler Fedko. Call-ups absent from `players`.
    They are not merged into a wrong player; they are collapsed into one bucket, which
    is worse: distinct people made indistinguishable from each other and from a
    game-level total.

The ingest already stopped doing this. `bovada_scraper.py:774` (commit a703f29,
2026-08-10) drops a prop it cannot attribute, and the last capture on this row is
2026-08-10 -- the mechanism is closed and this is history, not a leak.

So history gets the rule the ingest now applies: **delete**. The alternative --
resolving those 177 names into new `players` rows -- would mint players out of
sportsbook display names with no publisher id behind them, which is precisely the
shape that put 531 shadow players into prod MLS. Recovering 177 unsettleable props is
not worth re-opening that door.

Usage:
  venv/bin/python repair_mlb_player_identity.py --db data/picks.db            # dry run
  venv/bin/python repair_mlb_player_identity.py --db data/picks.db --apply
"""
import argparse
import os
import sqlite3
import sys

OUTMAN_SHADOW = 29097
OUTMAN_CANON = 26852
OUTMAN_MLBAM = 681546
NAMELESS = 28987


def _counts(con, pid):
    props = con.execute("SELECT COUNT(*) FROM props WHERE player_id=?", (pid,)).fetchone()[0]
    results = con.execute(
        "SELECT COUNT(*) FROM prop_results WHERE prop_id IN "
        "(SELECT id FROM props WHERE player_id=?)", (pid,)).fetchone()[0]
    snaps = con.execute(
        "SELECT COUNT(*) FROM prop_odds_snapshots WHERE prop_id IN "
        "(SELECT id FROM props WHERE player_id=?)", (pid,)).fetchone()[0]
    return props, results, snaps


def _row(con, pid):
    return con.execute(
        "SELECT id,name,team,league,mlbam_id,active FROM players WHERE id=?", (pid,)).fetchone()


def merge_outman(con, apply=False):
    """Repoint the shadow row's props onto the row carrying the published id."""
    shadow, canon = _row(con, OUTMAN_SHADOW), _row(con, OUTMAN_CANON)
    if shadow is None or canon is None:
        print("  outman: one of the rows is already gone — nothing to do")
        return 0, True

    # Fail closed on anything that is not the shape the docstring describes. An id that
    # has been reused by a later ingest must not be merged on the strength of a constant
    # written down a week ago.
    problems = []
    if canon["mlbam_id"] != OUTMAN_MLBAM:
        problems.append("canonical row {} has mlbam {}, expected {}".format(
            OUTMAN_CANON, canon["mlbam_id"], OUTMAN_MLBAM))
    if shadow["mlbam_id"]:
        problems.append("shadow row {} has mlbam {} — it is not a shadow".format(
            OUTMAN_SHADOW, shadow["mlbam_id"]))
    if (shadow["name"] or "").strip().lower() != (canon["name"] or "").strip().lower():
        problems.append("names differ: {!r} vs {!r}".format(shadow["name"], canon["name"]))
    if (shadow["league"], canon["league"]) != ("mlb", "mlb"):
        problems.append("not both MLB rows")
    if problems:
        print("  outman: ABORT — " + "; ".join(problems))
        return 0, False

    props, results, snaps = _counts(con, OUTMAN_SHADOW)
    print("  outman: shadow {} holds {} props ({} results, {} odds snapshots)".format(
        OUTMAN_SHADOW, props, results, snaps))
    print("          canonical {} holds {} props, mlbam {}".format(
        OUTMAN_CANON, _counts(con, OUTMAN_CANON)[0], canon["mlbam_id"]))

    # The shadow row carries the properly-cased display name and prod's canonical row
    # carries a lowercased one. Take the better string while we have both in hand;
    # once the shadow is deleted the casing is unrecoverable.
    better = (shadow["name"] or "").strip()
    if better and better != (canon["name"] or ""):
        print("          name: {!r} -> {!r}".format(canon["name"], better))

    if not apply:
        return props, True

    con.execute("UPDATE props SET player_id=? WHERE player_id=?", (OUTMAN_CANON, OUTMAN_SHADOW))
    if better:
        con.execute("UPDATE players SET name=? WHERE id=?", (better, OUTMAN_CANON))
    con.execute("DELETE FROM players WHERE id=?", (OUTMAN_SHADOW,))
    con.commit()
    return props, True


def purge_nameless(con, apply=False):
    """Delete props that were never attributable, and the bucket row itself."""
    row = _row(con, NAMELESS)
    if row is None:
        print("  nameless: row already gone — nothing to do")
        return 0, True
    if (row["name"] or "").strip() or row["mlbam_id"]:
        print("  nameless: ABORT — id {} is {!r} / mlbam {}, not the empty bucket".format(
            NAMELESS, row["name"], row["mlbam_id"]))
        return 0, False

    props, results, snaps = _counts(con, NAMELESS)
    print("  nameless: row {} holds {} props ({} results, {} odds snapshots)".format(
        NAMELESS, props, results, snaps))
    for market, n in con.execute(
            "SELECT market, COUNT(*) n FROM props WHERE player_id=? GROUP BY 1 "
            "ORDER BY n DESC LIMIT 3", (NAMELESS,)):
        print("            {:52s} {}".format(market[:52], n))
    if not apply:
        return props, True

    # Order matters: children before parents, or the deletes leave orphans behind.
    con.execute("DELETE FROM prop_results WHERE prop_id IN "
                "(SELECT id FROM props WHERE player_id=?)", (NAMELESS,))
    con.execute("DELETE FROM prop_odds_snapshots WHERE prop_id IN "
                "(SELECT id FROM props WHERE player_id=?)", (NAMELESS,))
    con.execute("DELETE FROM props WHERE player_id=?", (NAMELESS,))
    con.execute("DELETE FROM players WHERE id=?", (NAMELESS,))
    con.commit()
    return props, True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/picks.dev.db")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    path = os.path.abspath(args.db)
    print("database: {}".format(path))
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row

    before = con.execute(
        "SELECT COUNT(*) FROM props p JOIN players pl ON pl.id=p.player_id "
        "WHERE pl.league='mlb' AND (pl.mlbam_id IS NULL OR pl.mlbam_id=0)").fetchone()[0]
    print("  MLB props on a player with no mlbam_id, before: {}".format(before))

    moved, ok1 = merge_outman(con, apply=args.apply)
    dropped, ok2 = purge_nameless(con, apply=args.apply)
    if not (ok1 and ok2):
        print("\nABORTED — nothing written.")
        return 2

    if not args.apply:
        print("\ndry run — nothing written. re-run with --apply")
        print("  would repoint {} props, delete {} props".format(moved, dropped))
        return 0

    after = con.execute(
        "SELECT COUNT(*) FROM props p JOIN players pl ON pl.id=p.player_id "
        "WHERE pl.league='mlb' AND (pl.mlbam_id IS NULL OR pl.mlbam_id=0)").fetchone()[0]
    orphan_res = con.execute(
        "SELECT COUNT(*) FROM prop_results r LEFT JOIN props p ON p.id=r.prop_id "
        "WHERE p.id IS NULL").fetchone()[0]
    orphan_snap = con.execute(
        "SELECT COUNT(*) FROM prop_odds_snapshots s LEFT JOIN props p ON p.id=s.prop_id "
        "WHERE p.id IS NULL").fetchone()[0]
    outman_props = con.execute(
        "SELECT COUNT(*) FROM props WHERE player_id=?", (OUTMAN_CANON,)).fetchone()[0]

    # Reconcile rather than report. The counts above are a claim about what happened;
    # these are the questions that would have caught it going wrong.
    checks = {
        "no MLB props left without mlbam": after == 0,
        "shadow row gone": _row(con, OUTMAN_SHADOW) is None,
        "nameless row gone": _row(con, NAMELESS) is None,
        "canonical row kept its mlbam": (_row(con, OUTMAN_CANON) or {})["mlbam_id"] == OUTMAN_MLBAM,
        "repointed props landed": outman_props >= moved,
        "no orphaned prop_results": orphan_res == 0,
        "no orphaned odds snapshots": orphan_snap == 0,
    }
    print("\n  MLB props on a player with no mlbam_id, after: {}".format(after))
    print("  {} props repointed to {} · {} unattributable props deleted".format(
        moved, OUTMAN_CANON, dropped))
    for label, passed in checks.items():
        print("    {:34s} {}".format(label, "ok" if passed else "FAIL"))
    good = all(checks.values())
    print("  reconciled: {}".format("yes" if good else "NO -- investigate"))
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
