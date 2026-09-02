#!/usr/bin/env python3
"""Collapse duplicate `props` rows, keeping the one the rest of the app points at.

WHY THEY EXIST. `/api/props/ingest` INSERTed unconditionally into a table with no UNIQUE
constraint while the scrapers ran on 30-minute timers, so an unchanged board was copied in
full on every scrape. Measured on dev 2026-08-16: 47,827
(game_id, player_id, market, line, side, source) groups holding more than one row.

Nothing ever errored. The board reads latest-per-key so it rendered correctly the whole
time, while every hit-rate denominator counted the same prop once per scrape — a number
that is wrong on a page users read, produced by a pipeline that looked healthy.

The endpoint was fixed to upsert (commit c11370d). This clears what it already wrote.

WHICH ROW SURVIVES, AND WHY IT IS NOT SIMPLY THE NEWEST. `prop_results` and
`prop_odds_snapshots` both reference `props.id`. Keeping MAX(id) blindly deletes the row a
settled result hangs off and orphans it — which is exactly what an earlier ad-hoc pass at
the MLS rows did, leaving 3 unreachable `prop_results`. So:

  1. Winner = the NEWEST row in the group that carries a prop_results row.
  2. If no row in the group carries one, the newest row wins.
  3. A loser's referencing rows are REPOINTED at the winner before the losers are deleted.

DUPLICATE SETTLEMENTS, AND WHY THIS DOES NOT SILENTLY PICK ONE. The first version of this
script assumed at most one row per group could be settled, and asserted so in a comment.
That assumption was wrong and `--apply` raised on it: `prop_results.prop_id` is an INTEGER
PRIMARY KEY, so repointing onto a winner that already has a result is a constraint
violation. Measured on dev 2026-08-17: 45,096 of the 46,495 groups carry more than one
settled row.

The same measurement is what makes collapsing them safe — all 45,096 agree exactly on
(actual_value, hit), because they describe one real prop graded from one published
boxscore. A redundant copy of an identical grade is dropped.

Two rows disagreeing would be a different and much worse finding: the same prop graded two
ways. This script does not get to choose between them. It ABORTS, names the groups, and
writes nothing. `prop_odds_snapshots` is treated identically under its
UNIQUE(prop_id, side, captured_at).

Nothing is deleted that something else still points at, and the counts are reconciled
after the write rather than assumed.

Usage:
  python3 dedupe_props.py --db data/picks.dev.db
  python3 dedupe_props.py --db data/picks.dev.db --apply
"""
import argparse
import collections
import os
import sqlite3
import sys

KEY = "game_id, player_id, market, line, side, source"


def _groups(con):
    """Duplicate groups as {key_tuple: [prop ids oldest-first]}."""
    rows = con.execute(
        "SELECT game_id, player_id, market, line, side, source, id "
        "FROM props ORDER BY game_id, player_id, market, line, side, source, id"
    ).fetchall()
    grouped = collections.defaultdict(list)
    for row in rows:
        grouped[tuple(row[:6])].append(row[6])
    return {key: ids for key, ids in grouped.items() if len(ids) > 1}


def _results(con):
    """{prop_id: (actual_value, hit)} for every settled prop."""
    return {r[0]: (r[1], r[2])
            for r in con.execute("SELECT prop_id, actual_value, hit FROM prop_results")}


def _snapshots(con):
    """{prop_id: {(side, captured_at): (odds, odds_opp, is_close, de_vig_status)}}.

    Keyed by the columns of UNIQUE(prop_id, side, captured_at) so a repoint collision can be
    predicted before it is attempted, and the colliding rows compared rather than guessed at.
    """
    out = collections.defaultdict(dict)
    for row in con.execute(
            "SELECT prop_id, side, captured_at, odds, odds_opp, is_close, de_vig_status "
            "FROM prop_odds_snapshots"):
        out[row[0]][(row[1], row[2])] = tuple(row[3:])
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    print("database: {}".format(os.path.abspath(args.db)))

    before_props = con.execute("SELECT COUNT(*) FROM props").fetchone()[0]
    before_results = con.execute("SELECT COUNT(*) FROM prop_results").fetchone()[0]
    before_snaps = con.execute("SELECT COUNT(*) FROM prop_odds_snapshots").fetchone()[0]

    orphan_results = con.execute(
        "SELECT COUNT(*) FROM prop_results r LEFT JOIN props p ON p.id=r.prop_id "
        "WHERE p.id IS NULL").fetchone()[0]
    orphan_snaps = con.execute(
        "SELECT COUNT(*) FROM prop_odds_snapshots s LEFT JOIN props p ON p.id=s.prop_id "
        "WHERE p.id IS NULL").fetchone()[0]

    groups = _groups(con)
    results = _results(con)
    snapshots = _snapshots(con)

    losers = []
    move_results = []     # (winner_id, loser_id)  -- winner has no result yet
    drop_results = []     # loser_id               -- winner already has an identical one
    move_snaps = []       # (winner_id, loser_id, side, captured_at)
    drop_snaps = []       # (loser_id, side, captured_at)
    conflicts = []        # (kind, key, [(prop_id, value), ...])
    per_league = collections.Counter()
    league_of = dict(con.execute(
        "SELECT p.id, pl.league FROM props p JOIN players pl ON pl.id=p.player_id"))

    for key, ids in groups.items():
        settled = [i for i in ids if i in results]
        winner = max(settled) if settled else max(ids)

        # Every settled row in a group grades the same real prop from the same published
        # boxscore, so they must agree. Disagreement is not something to resolve by picking
        # the newest -- it means one of them is wrong, and this script must not hide that.
        if len(settled) > 1:
            distinct = {results[i] for i in settled}
            if len(distinct) > 1:
                conflicts.append(("prop_results", key, [(i, results[i]) for i in settled]))

        won_snaps = snapshots.get(winner, {})
        for prop_id in ids:
            if prop_id == winner:
                continue
            losers.append(prop_id)
            per_league[league_of.get(prop_id, "?")] += 1

            if prop_id in results:
                if winner in results:
                    drop_results.append(prop_id)
                else:
                    move_results.append((winner, prop_id))

            for snap_key, value in snapshots.get(prop_id, {}).items():
                if snap_key not in won_snaps:
                    move_snaps.append((winner, prop_id) + snap_key)
                    won_snaps[snap_key] = value       # a later loser must not collide with it
                elif won_snaps[snap_key] == value:
                    drop_snaps.append((prop_id,) + snap_key)
                else:
                    conflicts.append(("prop_odds_snapshots", key,
                                      [(winner, won_snaps[snap_key]), (prop_id, value)]))

    print("  duplicate groups: {}".format(len(groups)))
    print("  rows to remove:   {}".format(len(losers)))
    print("  prop_results      {} repointed, {} redundant duplicates dropped".format(
        len(move_results), len(drop_results)))
    print("  odds snapshots    {} repointed, {} redundant duplicates dropped".format(
        len(move_snaps), len(drop_snaps)))
    print("  pre-existing orphans — prop_results {}, prop_odds_snapshots {}"
          .format(orphan_results, orphan_snaps))
    for league, count in per_league.most_common():
        print("      {:8s} {}".format(league, count))

    if conflicts:
        # Fail closed. Two gradings of one prop that do not match is a settlement defect,
        # and collapsing the rows would destroy the evidence of it.
        print("\nABORT — {} duplicate group(s) disagree about a value. Nothing written."
              .format(len(conflicts)))
        for kind, key, members in conflicts[:20]:
            print("  {} {}".format(kind, key))
            for prop_id, value in members:
                print("      prop {} -> {}".format(prop_id, value))
        if len(conflicts) > 20:
            print("  ... and {} more".format(len(conflicts) - 20))
        return 2

    if not args.apply:
        print("\ndry run -- nothing written. re-run with --apply")
        return 0

    moved_results = moved_snaps = 0
    for winner, loser in move_results:
        moved_results += con.execute(
            "UPDATE prop_results SET prop_id=? WHERE prop_id=?", (winner, loser)).rowcount
    for winner, loser, side, captured_at in move_snaps:
        moved_snaps += con.execute(
            "UPDATE prop_odds_snapshots SET prop_id=? "
            "WHERE prop_id=? AND side=? AND captured_at=?",
            (winner, loser, side, captured_at)).rowcount

    # What is left on a loser is a byte-identical copy of something the winner already has,
    # compared field by field above. Deleting the loser's props row would take these with it
    # only if the FK cascaded, which it does not -- so they are removed explicitly.
    dropped_dupe_results = dropped_dupe_snaps = 0
    for chunk in range(0, len(drop_results), 500):
        batch = drop_results[chunk:chunk + 500]
        dropped_dupe_results += con.execute(
            "DELETE FROM prop_results WHERE prop_id IN ({})".format(",".join("?" * len(batch))),
            batch).rowcount
    for loser, side, captured_at in drop_snaps:
        dropped_dupe_snaps += con.execute(
            "DELETE FROM prop_odds_snapshots WHERE prop_id=? AND side=? AND captured_at=?",
            (loser, side, captured_at)).rowcount

    for chunk in range(0, len(losers), 500):
        batch = losers[chunk:chunk + 500]
        con.execute("DELETE FROM props WHERE id IN ({})".format(",".join("?" * len(batch))),
                    batch)
    # Orphans that predate this run point at rows that no longer exist and cannot be
    # re-linked -- the prop they described is gone. They are removed so the table stops
    # claiming results for props nobody can reach; settlement re-derives from the publisher.
    dropped_orphans = con.execute(
        "DELETE FROM prop_results WHERE prop_id NOT IN (SELECT id FROM props)").rowcount
    con.commit()

    after_props = con.execute("SELECT COUNT(*) FROM props").fetchone()[0]
    after_results = con.execute("SELECT COUNT(*) FROM prop_results").fetchone()[0]
    after_snaps = con.execute("SELECT COUNT(*) FROM prop_odds_snapshots").fetchone()[0]
    remaining = len(_groups(con))
    still_orphan = con.execute(
        "SELECT COUNT(*) FROM prop_results r LEFT JOIN props p ON p.id=r.prop_id "
        "WHERE p.id IS NULL").fetchone()[0]
    still_orphan_snaps = con.execute(
        "SELECT COUNT(*) FROM prop_odds_snapshots s LEFT JOIN props p ON p.id=s.prop_id "
        "WHERE p.id IS NULL").fetchone()[0]

    print("\n  props           {} -> {}  (removed {})".format(
        before_props, after_props, before_props - after_props))
    print("  prop_results    {} -> {}  ({} repointed, {} redundant dropped, "
          "{} orphans dropped)".format(before_results, after_results, moved_results,
                                       dropped_dupe_results, dropped_orphans))
    print("  odds snapshots  {} -> {}  ({} repointed, {} redundant dropped)".format(
        before_snaps, after_snaps, moved_snaps, dropped_dupe_snaps))
    print("  duplicate groups remaining: {}".format(remaining))
    print("  orphaned prop_results remaining: {}".format(still_orphan))
    print("  orphaned snapshots remaining: {} (was {})".format(
        still_orphan_snaps, orphan_snaps))

    # Every row that left a table has to be one this run decided to remove. A count that
    # merely went down is not evidence; these are the specific numbers it committed to.
    checks = {
        "props removed == losers":
            before_props - after_props == len(losers),
        "prop_results removed == redundant + orphans":
            before_results - after_results == dropped_dupe_results + dropped_orphans,
        "snapshots removed == redundant":
            before_snaps - after_snaps == dropped_dupe_snaps,
        "no duplicate groups left": remaining == 0,
        "no orphaned prop_results": still_orphan == 0,
        "no NEW orphaned snapshots": still_orphan_snaps <= orphan_snaps,
    }
    for label, passed in checks.items():
        print("    {:44s} {}".format(label, "ok" if passed else "FAIL"))
    ok = all(checks.values())
    print("  reconciled: {}".format("yes" if ok else "NO -- investigate"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
