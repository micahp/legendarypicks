#!/usr/bin/env python3
"""review_queue.py - the unresolved_players queue, named rather than counted.

coverage_report.py already prints this queue, but only as a per-league total
plus a top-5 by hit count. That answers "how big is it", which is the one
question nobody can act on. Addressing a queue means knowing WHICH names, on
WHICH team, refused for WHICH reason, so the work can be picked up away from
the terminal that found it.

The reason column is the point. `not_in_spine` on a Liga MX club is a missing
roster, `ambiguous_normalized_name` is two players sharing a fold, and
`duplicate_spine_mlbam_id` is a spine defect. Three different jobs that a
single count merges into one number.
"""
import argparse
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.environ.get(
    "LP_DB_PATH", os.path.join(HERE, os.pardir, "backend", "data", "picks.db"))


def rows(con, league=None, reason=None):
    sql = ("SELECT league, COALESCE(reason,'(unrecorded)') AS reason, "
           "COALESCE(team,'(no team)') AS team, raw_name, count, "
           "COALESCE(source_player_key,'') AS source_player_key, "
           "source, first_seen "
           "FROM unresolved_players WHERE 1=1")
    args = []
    if league:
        sql += " AND LOWER(league)=?"
        args.append(league.lower())
    if reason:
        sql += " AND COALESCE(reason,'(unrecorded)')=?"
        args.append(reason)
    sql += " ORDER BY league, reason, team, count DESC, raw_name"
    return con.execute(sql, args).fetchall()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--league", help="restrict to one league, e.g. lcup")
    ap.add_argument("--reason", help="restrict to one reason")
    ap.add_argument("--tsv", metavar="PATH",
                    help="also write every row here, so the queue outlives the terminal")
    ap.add_argument("--limit", type=int, default=25,
                    help="names printed per (league, reason, team) group; 0 for all")
    args = ap.parse_args(argv)

    if not os.path.exists(args.db):
        print(f"[review-queue] no database at {args.db}", file=sys.stderr)
        return 2

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    try:
        found = rows(con, args.league, args.reason)
    except sqlite3.OperationalError as exc:
        print(f"[review-queue] {exc}", file=sys.stderr)
        return 2
    finally:
        pass

    print(f"[review-queue] {args.db}")
    if not found:
        # An empty queue is a real answer, not a missing one: nothing has been
        # refused yet. Say which filter produced it so it cannot be read as
        # "this league is clean" when the league has simply never ingested.
        scope = args.league or "all leagues"
        print(f"  0 rows for {scope}"
              + (f", reason={args.reason}" if args.reason else ""))
        con.close()
        return 0

    print(f"  {len(found)} row(s)\n")
    group = None
    shown = 0
    for r in found:
        key = (r["league"], r["reason"], r["team"])
        if key != group:
            group = key
            shown = 0
            n = sum(1 for x in found
                    if (x["league"], x["reason"], x["team"]) == key)
            hits = sum(x["count"] or 0 for x in found
                       if (x["league"], x["reason"], x["team"]) == key)
            print(f"  {r['league']} / {r['reason']} / {r['team']}: "
                  f"{n} name(s), {hits} sighting(s)")
        shown += 1
        if args.limit and shown > args.limit:
            if shown == args.limit + 1:
                print("      ...")
            continue
        key_txt = f" [{r['source_player_key']}]" if r["source_player_key"] else ""
        print(f"      {r['raw_name']}{key_txt}  {r['count']}x  "
              f"since {r['first_seen'][:10]}  via {r['source']}")

    if args.tsv:
        cols = ["league", "reason", "team", "raw_name", "count",
                "source_player_key", "source", "first_seen"]
        with open(args.tsv, "w", encoding="utf-8") as fh:
            fh.write("\t".join(cols) + "\n")
            for r in found:
                fh.write("\t".join(str(r[c]) for c in cols) + "\n")
        print(f"\n  wrote {len(found)} row(s) to {args.tsv}")

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
