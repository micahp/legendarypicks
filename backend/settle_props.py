#!/usr/bin/env python3
"""
settle_props.py — Drive the settlement pipeline.

Find all prop_games that are FINAL and have unsettled props, settle each via settlement.py.
Idempotent: re-running is safe (skips already-settled props).

Usage: venv/bin/python settle_props.py [--dry-run] [--league LEAGUE]
"""
import sys, os, sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from settlement import settle_game
import espn_client as espn

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")


def main(dry_run: bool = False, league: str = ""):
    # settle_game asks ESPN for a boxscore per game, so this loop is a fan-out.
    # Unpaced it reached 50 requests in a single minute on 2026-08-24, alongside
    # ingest_scoreboards' steady 4/min, and site.web.api refused for the next four
    # minutes; 26 of those refusals hit uvicorn. ESPN measures requests per minute,
    # not per run, so the batch job spaces itself and the request handlers do not.
    # Nobody waits on this script, so it is also allowed to wait out a cooldown.
    with espn.batch_pacing():
        return _main(dry_run=dry_run, league=league)


def _main(dry_run: bool = False, league: str = ""):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # Find finaled games with unsettled props
    games = con.execute("""
        SELECT DISTINCT pg.id, pg.league, pg.home, pg.away, pg.espn_event_id,
               pg.final_home, pg.final_away, pg.date,
               COUNT(p.id) as total_props,
               COUNT(pr.prop_id) as result_rows
        FROM prop_games pg
        JOIN props p ON p.game_id = pg.id
        LEFT JOIN prop_results pr ON pr.prop_id = p.id
        WHERE (pg.final_home IS NOT NULL OR pg.espn_event_id != '')
          AND (? = '' OR pg.league = ?)
        GROUP BY pg.id
        HAVING result_rows < total_props
        ORDER BY pg.date DESC
    """, (league, league)).fetchall()

    if not games:
        print("No finaled games with unsettled props.")
        # Try games with espn_event_id but no finals
        games_with_espn = con.execute("""
            SELECT DISTINCT pg.id, pg.league, pg.home, pg.away, pg.espn_event_id,
                   pg.date, COUNT(p.id) as total_props,
                   COUNT(pr.prop_id) as result_rows
            FROM prop_games pg
            JOIN props p ON p.game_id = pg.id
            LEFT JOIN prop_results pr ON pr.prop_id = p.id
            WHERE pg.espn_event_id != '' AND pg.espn_event_id IS NOT NULL
              AND (? = '' OR pg.league = ?)
            GROUP BY pg.id
            HAVING result_rows < total_props
            ORDER BY pg.date DESC
        """, (league, league)).fetchall()
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
    dry = "--dry-run" in sys.argv
    scope = ""
    for index, arg in enumerate(sys.argv):
        if arg == "--league" and index + 1 < len(sys.argv):
            scope = sys.argv[index + 1].lower()
        elif arg.startswith("--league="):
            scope = arg.split("=", 1)[1].lower()
    if scope and scope not in espn.LEAGUES:
        print(f"Unsupported league: {scope}", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(dry_run=dry, league=scope) or 0)
