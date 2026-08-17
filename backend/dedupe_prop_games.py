#!/usr/bin/env python3
"""Merge the prop_games rows that are the same published event.

An ESPN event id IS the identity of a game. Prod holds 59 event ids spread across
124 prop_games rows -- one real fixture stored two or three times, usually on
consecutive calendar dates with the same two clubs:

    event 401815804  row 28  2026-06-18  Mets @ Phillies  91 props  final 4-6
                     row 58  2026-06-19  Mets @ Phillies  16 props  final 4-6

Why it matters, and it is not tidiness: settlement works one prop_games row at a
time. It grades row 28, writes its results, and row 58's 16 props are never
looked at again -- there is no second game for them to be graded against. That is
the mechanism behind prod's June hole, where 14,046 MLB props sit unsettled
against 693 settled. The props were split across a fixture that got stored twice.

How the rows come to exist: the props ingest matches an existing game on
(league, date, home, away) and inserts when it misses. A first pitch at 21:40 ET
is the next day in UTC, so the same fixture arrives under two calendar dates
depending on which convention the payload carried, and each date misses the
other's row. The linker then resolves BOTH to the same ESPN event, which is what
makes them recoverable now.

Rules
-----
  1. A group is the set of rows sharing (league, espn_event_id), event id
     non-blank. Rows with no event id are never touched: without the publisher's
     id there is nothing asserting they are the same game, and date+teams is
     exactly the guess that created this mess.
  2. Winner = the row that carries a final score, then the one with the most
     props, then the lowest id. Deterministic, and it keeps the row settlement
     has already worked with.
  3. props.game_id is the only integer reference to prop_games -- verified
     against the schema, the other game_id columns hold ESPN's text id and key
     on nothing here. Repointing props is the whole merge.
  4. ABORT if a group disagrees about a fact: different home/away teams, or two
     different non-null final scores. Either means the LINK is wrong, and
     merging on a wrong link would fuse two real games into one. An unmerged row
     is recoverable; a fused one is not.

This does NOT dedupe props. Repointing can land two identical props rows on one
game, which is exactly what dedupe_props.py exists for -- run it after.

Usage:
  venv/bin/python dedupe_prop_games.py --db data/picks.dev.db [--apply]
"""
import argparse
import collections
import os
import sqlite3
import sys


def _groups(con):
    """{(league, espn_event_id): [row ids]} for every event stored more than once."""
    grouped = collections.defaultdict(list)
    for row in con.execute(
            "SELECT league, espn_event_id, id FROM prop_games "
            "WHERE espn_event_id IS NOT NULL AND espn_event_id != '' ORDER BY id"):
        grouped[(row[0], row[1])].append(row[2])
    return {key: ids for key, ids in grouped.items() if len(ids) > 1}


def _facts(con, ids):
    """{id: row} for the columns a merge has to agree about."""
    marks = ",".join("?" * len(ids))
    return {r["id"]: r for r in con.execute(
        f"SELECT id, league, date, home, away, start_time, final_home, final_away, "
        f"espn_event_id FROM prop_games WHERE id IN ({marks})", ids)}


def run(db_path, apply=False):
    con = sqlite3.connect(os.path.abspath(db_path))
    con.row_factory = sqlite3.Row
    print(f"database: {os.path.abspath(db_path)}")

    before_games = con.execute("SELECT COUNT(*) FROM prop_games").fetchone()[0]
    before_props = con.execute("SELECT COUNT(*) FROM props").fetchone()[0]

    groups = _groups(con)
    prop_counts = dict(con.execute(
        "SELECT game_id, COUNT(*) FROM props GROUP BY game_id").fetchall())
    print(f"  prop_games: {before_games}")
    print(f"  events stored more than once: {len(groups)} "
          f"({sum(len(v) for v in groups.values())} rows)")

    conflicts = []
    losers = []          # (loser_id, winner_id)
    winners_by_group = {}
    per_league = collections.Counter()

    for key, ids in groups.items():
        rows = _facts(con, ids)

        teams = {(r["home"], r["away"]) for r in rows.values()}
        if len(teams) > 1:
            conflicts.append(("teams", key, sorted(teams)))
            continue
        finals = {(r["final_home"], r["final_away"]) for r in rows.values()
                  if r["final_home"] is not None or r["final_away"] is not None}
        if len(finals) > 1:
            conflicts.append(("final score", key, sorted(finals)))
            continue

        winner = sorted(
            ids,
            key=lambda i: (rows[i]["final_home"] is None,      # a settled row first
                           -prop_counts.get(i, 0),             # then the fuller one
                           i))[0]                              # then deterministic
        winners_by_group[key] = winner
        per_league[key[0]] += len(ids) - 1
        for i in ids:
            if i != winner:
                losers.append((i, winner))

    if conflicts:
        print(f"\nABORT — {len(conflicts)} group(s) disagree about a fact. Nothing written.")
        print("A disagreement here means the LINK is wrong, not that the rows are dupes;")
        print("merging on it would fuse two different games into one.")
        for kind, key, values in conflicts[:20]:
            print(f"  {kind:12s} {key}: {values}")
        if len(conflicts) > 20:
            print(f"  ... and {len(conflicts) - 20} more")
        con.close()
        return 2

    moved_props = sum(prop_counts.get(i, 0) for i, _ in losers)
    print(f"  rows to remove: {len(losers)}   props to repoint: {moved_props}")
    print("  by league: " + (", ".join(f"{k}={v}" for k, v in per_league.most_common())
                             or "(none)"))

    if not apply:
        print("\ndry run — nothing written. Re-run with --apply.")
        con.close()
        return 0

    for loser, winner in losers:
        con.execute("UPDATE props SET game_id=? WHERE game_id=?", (winner, loser))
    marks_batch = [l for l, _ in losers]
    for chunk in range(0, len(marks_batch), 500):
        batch = marks_batch[chunk:chunk + 500]
        con.execute("DELETE FROM prop_games WHERE id IN ({})".format(
            ",".join("?" * len(batch))), batch)
    con.commit()

    after_games = con.execute("SELECT COUNT(*) FROM prop_games").fetchone()[0]
    after_props = con.execute("SELECT COUNT(*) FROM props").fetchone()[0]
    remaining = len(_groups(con))
    orphaned = con.execute(
        "SELECT COUNT(*) FROM props p LEFT JOIN prop_games g ON g.id=p.game_id "
        "WHERE g.id IS NULL").fetchone()[0]
    still_pointing = con.execute(
        "SELECT COUNT(*) FROM props WHERE game_id IN ({})".format(
            ",".join("?" * len(marks_batch))), marks_batch).fetchone()[0] if marks_batch else 0

    print(f"\n  prop_games  {before_games} -> {after_games}  (removed "
          f"{before_games - after_games})")
    print(f"  props       {before_props} -> {after_props}  ({moved_props} repointed)")

    # Every row that left has to be one this run decided to remove, and no prop may be
    # left pointing at a row that no longer exists. A count that merely went down is not
    # evidence.
    checks = {
        "prop_games removed == losers": before_games - after_games == len(losers),
        "props count unchanged": before_props == after_props,
        "no props left on a removed row": still_pointing == 0,
        "no orphaned props": orphaned == 0,
        "no duplicated events left": remaining == 0,
    }
    for label, passed in checks.items():
        print("    {:34s} {}".format(label, "ok" if passed else "FAIL"))
    ok = all(checks.values())

    if ok:
        # The constraint is the actual fix; this merge only clears the way for it. SQLite
        # refuses to build a unique index over data that violates it, so this statement
        # succeeding is itself the last check -- and from here the ingest cannot recreate
        # what we just removed. See _core.py for why the duplicates arise honestly.
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_prop_games_event "
                    "ON prop_games(league, espn_event_id) "
                    "WHERE espn_event_id IS NOT NULL AND espn_event_id != ''")
        con.commit()
        print("    {:34s} {}".format("unique index created", "ok"))

    print("  reconciled: {}".format("yes" if ok else "NO -- investigate"))
    print("\nprops were repointed, not deduped — two identical props can now share a "
          "game.\nRun dedupe_props.py next.")
    con.close()
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/picks.dev.db")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    return run(args.db, apply=args.apply)


if __name__ == "__main__":
    sys.exit(main())
