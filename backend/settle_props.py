#!/usr/bin/env python3
"""
settle_props.py — Drive the settlement pipeline.

Find all prop_games that are FINAL and have unsettled props, settle each via settlement.py.
Idempotent: re-running is safe (skips already-settled props).

Usage: venv/bin/python settle_props.py [--dry-run]
"""
import sys, os, sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from settlement import settle_game

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")


def main(dry_run: bool = False):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # Find finaled games with unsettled props
    games = con.execute("""
        SELECT DISTINCT pg.id, pg.league, pg.home, pg.away, pg.espn_event_id,
               pg.final_home, pg.final_away, pg.date,
               COUNT(p.id) as total_props,
               COUNT(pr.prop_id) as settled_props
        FROM prop_games pg
        JOIN props p ON p.game_id = pg.id
        LEFT JOIN prop_results pr ON pr.prop_id = p.id
        WHERE pg.final_home IS NOT NULL OR pg.espn_event_id != ''
        GROUP BY pg.id
        HAVING settled_props < total_props
        ORDER BY pg.date DESC
    """).fetchall()

    if not games:
        print("No finaled games with unsettled props.")
        # Try games with espn_event_id but no finals
        games_with_espn = con.execute("""
            SELECT DISTINCT pg.id, pg.league, pg.home, pg.away, pg.espn_event_id,
                   pg.date, COUNT(p.id) as total_props,
                   COUNT(pr.prop_id) as settled_props
            FROM prop_games pg
            JOIN props p ON p.game_id = pg.id
            LEFT JOIN prop_results pr ON pr.prop_id = p.id
            WHERE pg.espn_event_id != '' AND pg.espn_event_id IS NOT NULL
            GROUP BY pg.id
            HAVING settled_props < total_props
            ORDER BY pg.date DESC
        """).fetchall()
        if games_with_espn:
            print(f"  {len(games_with_espn)} games with ESPN IDs but no finals (will check ESPN)")
        else:
            print("  No games with ESPN IDs either — nothing to settle.")
            con.close()
            return
        games = games_with_espn

    print(f"Games to settle: {len(games)}")
    totals = {"settled": 0, "void": 0, "unmappable": 0, "errors": 0, "skipped": 0}

    for g in games:
        gid = g["id"]
        league = g["league"]
        unsettled_count = g["total_props"] - (g["settled_props"] or 0)
        print(f"\n  Game {gid}: {g['away']} @ {g['home']} ({league}, {g['date']}) "
              f"— {unsettled_count} unsettled props")

        if dry_run:
            print(f"    [dry-run] would settle")
            continue

        result = settle_game(con, gid)
        print(f"    settled={result.get('settled',0)} void={result.get('void',0)} "
              f"unmappable={result.get('unmappable',0)} errors={result.get('errors',0)}")
        if result.get("msg"):
            print(f"    {result['msg']}")
        if result.get("error_msg"):
            print(f"    ERROR: {result['error_msg']}")

        for k in ("settled", "void", "unmappable", "errors"):
            totals[k] += result.get(k, 0)

    # Summary
    total_results = con.execute("SELECT COUNT(*) FROM prop_results").fetchone()[0]
    total_props = con.execute("SELECT COUNT(*) FROM props").fetchone()[0]
    con.close()

    print(f"\n{'='*50}")
    print(f"Pipeline complete:")
    print(f"  Settled:   {totals['settled']}")
    print(f"  Void/DNP:  {totals['void']}")
    print(f"  Unmappable:{totals['unmappable']}")
    print(f"  Errors:    {totals['errors']}")
    print(f"  prop_results total: {total_results} / {total_props} props graded")
    if dry_run:
        print(f"  (DRY RUN — no changes written)")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    main(dry_run=dry)
