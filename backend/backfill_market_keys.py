#!/usr/bin/env python3
"""Strip the player name welded into 561,543 market keys, then re-grade what it broke.

The Bovada parser canonicalised the whole market description when the market map did not
recognise it, so an unmapped market kept the player's name:
"total_hits,_runs_and_rbis___austin_riley_(atl)". One market key per player, groupable by
nothing — and settlement's market map cannot see through it, so Austin Riley was graded 0
for a game the box score credits him with three hits in.

The parser no longer mints them (a703f29). This repairs the rows already written.

Only four stems are affected: total_bases, total_doubles, total_hits,_runs_and_rbis,
total_pitcher_walks.

Collisions are expected and harmless. `props` stores one row per CAPTURE, not per logical
prop, so a game already holds many rows for the same player/market/line/side; stripping the
suffix merges nothing and drops nothing. Each row keeps its own prop_results entry.

Usage: venv/bin/python backfill_market_keys.py --db data/picks.dev.db [--dry-run]
"""
import argparse, os, sqlite3, sys, time

import settlement
from migrate_schema import create_verified_backup
from regrade_props import measure, finals_for, SAMPLE_SIZE, PACE_SECONDS

STRIP = ("UPDATE props SET market = substr(market, 1, instr(market, '___') - 1) "
         "WHERE instr(market, '___') > 0")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/picks.dev.db")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    db = os.path.abspath(args.db)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    polluted = con.execute("SELECT COUNT(*) FROM props WHERE instr(market,'___')>0").fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM props").fetchone()[0]
    stems = [r[0] for r in con.execute(
        "SELECT DISTINCT substr(market,1,instr(market,'___')-1) FROM props WHERE instr(market,'___')>0")]
    print(f"database  {db}")
    print(f"polluted  {polluted:,} of {total:,} props")
    print(f"stems     {stems}\n")

    import datetime as _dt
    cutoff = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
    sample = [r[0] for r in con.execute("""
        SELECT DISTINCT g.espn_event_id FROM prop_games g JOIN props p ON p.game_id = g.id
        JOIN prop_results r ON r.prop_id = p.id
        WHERE g.league='mlb' AND g.espn_event_id IS NOT NULL AND g.date <= ?
        ORDER BY g.date DESC""", (cutoff,))][:SAMPLE_SIZE]

    print("── BEFORE ─────────────────────────────────────────────")
    b_checked, b_wrong, _ = measure(con, sample)
    print(f"  {b_wrong} of {b_checked} graded props disagree with ESPN's final box score")

    if args.dry_run:
        print("\ndry run — nothing changed")
        return

    backup = create_verified_backup(db)
    print(f"\nbackup    {backup}\n")

    print("── STRIPPING ──────────────────────────────────────────")
    cur = con.execute(STRIP)
    con.commit()
    print(f"  {cur.rowcount:,} market keys rewritten")
    left = con.execute("SELECT COUNT(*) FROM props WHERE instr(market,'___')>0").fetchone()[0]
    print(f"  {left} still carrying a suffix")

    print("\n── RE-GRADING ─────────────────────────────────────────")
    games = con.execute("""
        SELECT DISTINCT g.id, g.espn_event_id, g.date, g.home, g.away
        FROM prop_games g JOIN props p ON p.game_id = g.id
        WHERE g.league='mlb' AND g.espn_event_id IS NOT NULL ORDER BY g.date""").fetchall()
    finals, regraded, skipped, purged, errors = {}, 0, 0, 0, 0
    for i, g in enumerate(games, 1):
        d = g["date"]
        if d not in finals:
            try:
                finals[d] = finals_for(d)
            except Exception:
                finals[d] = {}
        con.execute("""DELETE FROM prop_results WHERE prop_id IN
                       (SELECT id FROM props WHERE game_id=?)""", (g["id"],))
        con.commit()
        if finals[d].get((g["home"], g["away"])) is None:
            # Not final. The teams-first gamePk lookup still needs a finality answer, and
            # settle_game asks ESPN for it — but a game the schedule does not call Final
            # gets no result at all rather than a fabricated one.
            skipped += 1
            purged += 1
            continue
        try:
            res = settlement.settle_game(con, g["id"])
            errors += 1 if res.get("errors") else 0
            regraded += 1
        except Exception as e:
            errors += 1
            print(f"  game {g['espn_event_id']} failed: {e}")
        time.sleep(PACE_SECONDS)
        if i % 100 == 0:
            print(f"  {i}/{len(games)} · {regraded} re-graded · {skipped} not final · {errors} errors")
    print(f"\n  {regraded} re-graded · {skipped} not final · {errors} errors")

    print("\n── AFTER ──────────────────────────────────────────────")
    a_checked, a_wrong, a_ex = measure(con, sample)
    print(f"  {a_wrong} of {a_checked} graded props disagree with ESPN's final box score")
    for e in a_ex[:5]:
        print(f"    {e}")
    print("\n── SAME RULER, BOTH SIDES ─────────────────────────────")
    print(f"  before  {b_wrong}/{b_checked}")
    print(f"  after   {a_wrong}/{a_checked}")
    print(f"  backup  {backup}")
    con.close()


if __name__ == "__main__":
    main()
