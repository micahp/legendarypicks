#!/usr/bin/env python3
"""
settle_props.py — Drive the settlement pipeline.

Find all prop_games that are FINAL and have unsettled props, settle each via settlement.py.
Idempotent: re-running is safe (skips already-settled props).

Usage: venv/bin/python settle_props.py [--dry-run] [--league nfl] [--game-id 123] [--since YYYY-MM-DD] [--through YYYY-MM-DD] [--limit 5]
"""
import argparse
import datetime as dt
import sys, os, sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from settlement import settle_game

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")


def _candidate_games(con, leagues=None, game_ids=None, since=None, through=None, limit=None,
                     include_without_final=False):
    """Unsettled games, optionally constrained before any publisher request."""
    clauses = ["pg.espn_event_id != ''" if include_without_final
               else "(pg.final_home IS NOT NULL OR pg.espn_event_id != '')"]
    params = []
    if leagues:
        clauses.append("pg.league IN ({})".format(",".join("?" for _ in leagues)))
        params.extend(leagues)
    if game_ids:
        clauses.append("pg.id IN ({})".format(",".join("?" for _ in game_ids)))
        params.extend(game_ids)
    if since:
        clauses.append("pg.date >= ?")
        params.append(since)
    if through:
        clauses.append("pg.date <= ?")
        params.append(through)
    query = """
        SELECT DISTINCT pg.id, pg.league, pg.home, pg.away, pg.espn_event_id,
               pg.final_home, pg.final_away, pg.date,
               COUNT(p.id) as total_props,
               COUNT(pr.prop_id) as result_rows
        FROM prop_games pg
        JOIN props p ON p.game_id = pg.id
        LEFT JOIN prop_results pr ON pr.prop_id = p.id
        WHERE {}
        GROUP BY pg.id
        HAVING result_rows < total_props
        ORDER BY pg.date DESC, pg.id DESC
    """.format(" AND ".join(clauses))
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    return con.execute(query, params).fetchall()


def main(dry_run: bool = False, leagues=None, game_ids=None, since=None, through=None, limit=None):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # Find finaled games with unsettled props
    games = _candidate_games(con, leagues=leagues, game_ids=game_ids, since=since,
                             through=through, limit=limit)

    if not games:
        print("No finaled games with unsettled props.")
        # Try games with espn_event_id but no finals
        games_with_espn = _candidate_games(
            con, leagues=leagues, game_ids=game_ids, since=since, through=through, limit=limit,
            include_without_final=True
        )
        if games_with_espn:
            print(f"  {len(games_with_espn)} games with ESPN IDs but no finals (will check ESPN)")
        else:
            print("  No games with ESPN IDs either — nothing to settle.")
            con.close()
            return
        games = games_with_espn

    print(f"Games to settle: {len(games)}")
    totals = {"settled": 0, "void": 0, "unmappable": 0, "pending": 0,
              "errors": 0, "skipped": 0}

    for g in games:
        gid = g["id"]
        league = g["league"]
        unsettled_count = g["total_props"] - (g["result_rows"] or 0)
        print(f"\n  Game {gid}: {g['away']} @ {g['home']} ({league}, {g['date']}) "
              f"— {unsettled_count} unsettled props")

        if dry_run:
            print(f"    [dry-run] would settle")
            continue

        result = settle_game(con, gid)
        print(f"    settled={result.get('settled',0)} void={result.get('void',0)} "
              f"unmappable={result.get('unmappable',0)} pending={result.get('pending',0)} "
              f"errors={result.get('errors',0)}")
        if result.get("msg"):
            print(f"    {result['msg']}")
        if result.get("error_msg"):
            print(f"    ERROR: {result['error_msg']}")

        for k in ("settled", "void", "unmappable", "pending", "errors"):
            totals[k] += result.get(k, 0)

    # Summary
    numeric_results, null_results = con.execute("""
        SELECT COALESCE(SUM(actual_value IS NOT NULL), 0),
               COALESCE(SUM(actual_value IS NULL), 0)
        FROM prop_results
    """).fetchone()
    total_props = con.execute("SELECT COUNT(*) FROM props").fetchone()[0]
    con.close()

    print(f"\n{'='*50}")
    print(f"Pipeline complete:")
    print(f"  Settled:   {totals['settled']}")
    print(f"  Void/DNP:  {totals['void']}")
    print(f"  Unmappable:{totals['unmappable']}")
    print(f"  Pending:   {totals['pending']}")
    print(f"  Errors:    {totals['errors']}")
    print(f"  Numeric outcomes: {numeric_results} / {total_props} props")
    print(f"  Null outcome rows (void or legacy placeholder): {null_results}")
    if dry_run:
        print(f"  (DRY RUN — no changes written)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--league", action="append",
                        help="restrict to one league; repeat for a bounded multi-league run")
    parser.add_argument("--game-id", action="append", type=int,
                        help="restrict to an exact prop_games.id; repeat to inspect several")
    parser.add_argument("--since", metavar="YYYY-MM-DD",
                        help="consider only games on or after this date")
    parser.add_argument("--through", metavar="YYYY-MM-DD",
                        help="consider only games on or before this date")
    parser.add_argument("--limit", type=int,
                        help="maximum games to inspect after league filtering")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.game_id and any(game_id < 1 for game_id in args.game_id):
        parser.error("--game-id must be positive")
    for option, value in (("--since", args.since), ("--through", args.through)):
        if not value:
            continue
        try:
            if dt.date.fromisoformat(value).isoformat() != value:
                raise ValueError
        except ValueError:
            parser.error("{} must be YYYY-MM-DD".format(option))
    if args.since and args.through and args.since > args.through:
        parser.error("--since must not be after --through")
    main(dry_run=args.dry_run, leagues=args.league, game_ids=args.game_id,
         since=args.since, through=args.through, limit=args.limit)
