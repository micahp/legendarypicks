#!/usr/bin/env python3
"""
settle_props.py — Drive the settlement pipeline.

Find all prop_games that are FINAL and have unsettled props, settle each via settlement.py.
Idempotent: re-running is safe (skips already-settled props).

Usage: venv/bin/python settle_props.py [--dry-run] [--league LEAGUE]
                                     [--through YYYY-MM-DD] [--max-games N]
                                     [--window-hours N]
"""
import datetime as dt
import sys, os, sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from settlement import settle_game
from settlement.ncaaf_settle import _ensure_attempt_table
import espn_client as espn

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
SETTLE_WINDOW_HOURS = 72


def _game_start(start_time, date_text):
    value = str(start_time or "").strip()
    if not value:
        value = str(date_text or "").strip() + "T00:00:00Z"
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _window_expired(game, window_hours, now=None):
    if not window_hours:
        return False
    started = _game_start(game["start_time"], game["date"])
    if started is None:
        return False
    now = now or dt.datetime.now(dt.timezone.utc)
    return now - started > dt.timedelta(hours=window_hours)


def _flag_manual(con, game_id):
    rows = con.execute("""
        SELECT p.id,
               (SELECT sa.reason FROM settlement_attempts sa
                WHERE sa.prop_id=p.id AND sa.terminal<>'manual'
                ORDER BY sa.id DESC LIMIT 1) AS last_reason
        FROM props p
        LEFT JOIN prop_results pr ON pr.prop_id=p.id
        WHERE p.game_id=? AND pr.prop_id IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM settlement_attempts manual
              WHERE manual.prop_id=p.id AND manual.terminal='manual'
          )
        ORDER BY p.id
    """, (game_id,)).fetchall()
    if not rows:
        return 0
    attempted_at = dt.datetime.now(dt.timezone.utc).isoformat()
    with con:
        con.executemany(
            "INSERT INTO settlement_attempts(prop_id,game_id,attempted_at,stage,"
            "terminal,reason,actual_value,hit) VALUES (?,?,?,'manual','manual',?,NULL,NULL)",
            [(row["id"], game_id, attempted_at,
              "window_expired:" + (row["last_reason"] or "none")) for row in rows],
        )
    return len(rows)


def _manual_backlog(con):
    return con.execute("""
        SELECT pg.league, COUNT(DISTINCT sa.prop_id) AS props
        FROM settlement_attempts sa
        JOIN props p ON p.id=sa.prop_id
        JOIN prop_games pg ON pg.id=p.game_id
        LEFT JOIN prop_results pr ON pr.prop_id=p.id
        WHERE sa.terminal='manual' AND pr.prop_id IS NULL
        GROUP BY pg.league
        ORDER BY pg.league
    """).fetchall()


def main(dry_run: bool = False, league: str = "", through: str = "",
         max_games: int = 0, window_hours: float = SETTLE_WINDOW_HOURS):
    return _main(dry_run=dry_run, league=league, through=through,
                 max_games=max_games, window_hours=window_hours)


def _main(dry_run: bool = False, league: str = "", through: str = "",
          max_games: int = 0, window_hours: float = SETTLE_WINDOW_HOURS):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    _ensure_attempt_table(con)
    game_columns = {row[1] for row in con.execute("PRAGMA table_info(prop_games)")}
    start_time = "pg.start_time" if "start_time" in game_columns else "NULL"

    # Find finaled games with unsettled props
    games = con.execute(f"""
        SELECT DISTINCT pg.id, pg.league, pg.home, pg.away, pg.espn_event_id,
               pg.final_home, pg.final_away, pg.date, {start_time} AS start_time,
               COUNT(p.id) as open_props
        FROM prop_games pg
        JOIN props p ON p.game_id = pg.id
        LEFT JOIN prop_results pr ON pr.prop_id = p.id
        WHERE (pg.final_home IS NOT NULL OR pg.espn_event_id != '')
          AND pr.prop_id IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM settlement_attempts sa
              WHERE sa.prop_id=p.id AND sa.terminal='manual'
          )
          AND (? = '' OR pg.league = ?)
          AND pg.date <= COALESCE(NULLIF(?, ''), date('now'))
        GROUP BY pg.id
        ORDER BY pg.date DESC
    """, (league, league, through)).fetchall()

    if not games:
        print("No finaled games with unsettled props.")
        # Try games with espn_event_id but no finals
        games_with_espn = con.execute(f"""
            SELECT DISTINCT pg.id, pg.league, pg.home, pg.away, pg.espn_event_id,
                   pg.date, {start_time} AS start_time, COUNT(p.id) as open_props
            FROM prop_games pg
            JOIN props p ON p.game_id = pg.id
            LEFT JOIN prop_results pr ON pr.prop_id = p.id
            WHERE pg.espn_event_id != '' AND pg.espn_event_id IS NOT NULL
              AND pr.prop_id IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM settlement_attempts sa
                  WHERE sa.prop_id=p.id AND sa.terminal='manual'
              )
              AND (? = '' OR pg.league = ?)
              AND pg.date <= COALESCE(NULLIF(?, ''), date('now'))
            GROUP BY pg.id
            ORDER BY pg.date DESC
        """, (league, league, through)).fetchall()
        if games_with_espn:
            print(f"  {len(games_with_espn)} games with publisher IDs but no finals "
                  "(will check stored rows)")
        else:
            print("  No games with ESPN IDs either — nothing to settle.")
        games = games_with_espn

    if max_games:
        games = games[:max_games]

    print(f"Games to settle: {len(games)}")
    totals = {"settled": 0, "void": 0, "unmappable": 0, "pending": 0,
              "errors": 0, "skipped": 0}
    manual_props = 0
    manual_games = 0
    manual_by_league = {}

    for g in games:
        gid = g["id"]
        league = g["league"]
        unsettled_count = g["open_props"]
        print(f"\n  Game {gid}: {g['away']} @ {g['home']} ({league}, {g['date']}) "
              f"— {unsettled_count} unsettled props")

        if _window_expired(g, window_hours):
            if dry_run:
                print(f"    [dry-run] would flag {unsettled_count} props manual")
                continue
            flagged = _flag_manual(con, gid)
            if flagged:
                manual_props += flagged
                manual_games += 1
                manual_by_league[league] = manual_by_league.get(league, 0) + flagged
            print(f"    manual={flagged} window_expired")
            continue

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

    print(f"\nmanual: newly_flagged={manual_props} props across {manual_games} games")
    for manual_league, count in sorted(manual_by_league.items()):
        print(f"  newly_flagged {manual_league}: {count}")
    backlog = _manual_backlog(con)
    if backlog:
        for row in backlog:
            print(f"  manual backlog {row['league']}: {row['props']}")
    else:
        print("  manual backlog: none")

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
    through = ""
    max_games = 0
    window_hours = SETTLE_WINDOW_HOURS
    for index, arg in enumerate(sys.argv):
        if arg == "--league" and index + 1 < len(sys.argv):
            scope = sys.argv[index + 1].lower()
        elif arg.startswith("--league="):
            scope = arg.split("=", 1)[1].lower()
        elif arg == "--through" and index + 1 < len(sys.argv):
            through = sys.argv[index + 1]
        elif arg.startswith("--through="):
            through = arg.split("=", 1)[1]
        elif arg == "--max-games" and index + 1 < len(sys.argv):
            max_games = int(sys.argv[index + 1])
        elif arg.startswith("--max-games="):
            max_games = int(arg.split("=", 1)[1])
        elif arg == "--window-hours" and index + 1 < len(sys.argv):
            window_hours = float(sys.argv[index + 1])
        elif arg.startswith("--window-hours="):
            window_hours = float(arg.split("=", 1)[1])
    if scope and scope not in espn.LEAGUES:
        print(f"Unsupported league: {scope}", file=sys.stderr)
        raise SystemExit(2)
    try:
        if through:
            dt.date.fromisoformat(through)
    except ValueError:
        print(f"Invalid --through date: {through}", file=sys.stderr)
        raise SystemExit(2)
    if max_games < 0:
        print("Invalid --max-games: must be non-negative", file=sys.stderr)
        raise SystemExit(2)
    if window_hours < 0:
        print("Invalid --window-hours: must be non-negative", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(dry_run=dry, league=scope, through=through,
                          max_games=max_games, window_hours=window_hours) or 0)
