#!/usr/bin/env python3
"""Re-grade every settled prop against a FINAL box score.

Why this exists: settle_game's finality gate sat below the MLB branch, which returns before
reaching it, so MLB props were graded against whatever the box score held when the nightly
job ran — mid-game, or before first pitch. Measured on 401816457: settled 45 minutes after
first pitch, Brady Singer graded at 6 outs and 0 strikeouts against a real 18 and 3. The
gate is fixed (e20b736); this repairs the rows written while it was broken.

Method, in order:

  1. VACUUM INTO backup, verified with quick_check. Never cp — a plain copy of a live
     database races writers (docs/BACKUP-POLICY.md).
  2. Measure BEFORE against an INDEPENDENT source. Grading reads the MLB Stats API, so the
     ruler reads ESPN. A check that uses the grader's own source can only tell us the
     grader agrees with itself.
  3. Re-grade: for each game the MLB schedule reports Final, drop its results and settle it
     again through the fixed path.
  4. Measure AFTER with the same script, the same sample, the same source.

Usage:
  venv/bin/python regrade_props.py --db data/picks.dev.db [--limit N] [--dry-run]
"""
import argparse, json, os, sqlite3, sys, time

import settlement
from migrate_schema import create_verified_backup

SAMPLE_SIZE = 12          # games cross-checked against ESPN, before and after
PACE_SECONDS = 0.35       # between MLB Stats API boxscore pulls


# ── the ruler ────────────────────────────────────────────────────────────────────────────
def espn_truth(event_id):
    """{player: {stat: value}} from ESPN's box score — the source grading does NOT use."""
    import espn_client as espn
    d = espn._get(espn._SITE.format(path="baseball/mlb") + f"/summary?event={event_id}", ttl=900)
    out = {}
    for team in (d.get("boxscore") or {}).get("players", []) or []:
        for grp in team.get("statistics", []) or []:
            kind = (grp.get("type") or "").lower()
            labels = [l.upper() for l in (grp.get("labels") or [])]
            for a in grp.get("athletes") or []:
                name = (a.get("athlete") or {}).get("displayName")
                stats = a.get("stats") or []
                if not name or len(stats) != len(labels):
                    continue
                row = dict(zip(labels, stats))
                try:
                    if kind == "batting":
                        out.setdefault(name, {}).update({
                            "total_hits,_runs_and_rbis": int(row.get("H", 0)) + int(row.get("R", 0))
                                                          + int(row.get("RBI", 0))})
                    elif kind == "pitching":
                        ip = float(row.get("IP", 0))
                        out.setdefault(name, {}).update({
                            "outs": int(ip) * 3 + round((ip - int(ip)) * 10),
                            "hits_allowed": int(row.get("H", 0)),
                            "earned_runs": int(row.get("ER", 0)),
                            "strikeouts": int(row.get("K", 0))})
                except (ValueError, TypeError):
                    continue
    return out


def measure(con, sample):
    """-> (checked, disagreeing) against ESPN, plus a few examples."""
    import re
    clean = lambda m: re.sub(r"___.*$", "", m)
    checked = wrong = 0
    examples = []
    for event_id in sample:
        truth = espn_truth(event_id)
        rows = con.execute("""
            SELECT pl.name, p.market, r.actual_value FROM props p
            JOIN prop_games g ON g.id = p.game_id
            JOIN players pl ON pl.id = p.player_id
            JOIN prop_results r ON r.prop_id = p.id
            WHERE g.espn_event_id = ? AND r.hit IS NOT NULL
            GROUP BY pl.id, p.market""", (event_id,)).fetchall()
        for name, market, actual in rows:
            mk = clean(market)
            if name not in truth or mk not in truth[name]:
                continue
            checked += 1
            if actual != truth[name][mk]:
                wrong += 1
                if len(examples) < 8:
                    examples.append(f"{name} {mk}: graded {actual:g}, ESPN {truth[name][mk]}")
    return checked, wrong, examples


# ── the repair ───────────────────────────────────────────────────────────────────────────
def finals_for(date_str):
    """{(home_name, away_name): (home_score, away_score)} for games the schedule calls Final."""
    out = {}
    for entry in settlement._mlb_schedule(date_str).get("dates", []):
        for g in entry.get("games", []):
            if ((g.get("status") or {}).get("abstractGameState") or "") != "Final":
                continue
            t = g.get("teams") or {}
            home = ((t.get("home") or {}).get("team") or {}).get("name")
            away = ((t.get("away") or {}).get("team") or {}).get("name")
            if home and away:
                out[(home, away)] = ((t.get("home") or {}).get("score"),
                                     (t.get("away") or {}).get("score"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/picks.dev.db")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db = os.path.abspath(args.db)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    games = con.execute("""
        SELECT DISTINCT g.id, g.espn_event_id, g.date, g.home, g.away
        FROM prop_games g JOIN props p ON p.game_id = g.id
        WHERE g.league = 'mlb' AND g.espn_event_id IS NOT NULL
        ORDER BY g.date""").fetchall()
    if args.limit:
        games = games[:args.limit]

    # The ruler has to compare against games that were actually PLAYED. Ordering purely by
    # date descending picked 2026-08-11 and 08-12 — fixtures that had not happened yet and
    # already carried `hit` values, which is the bug itself, and gave the check nothing to
    # measure. Sample from games whose date is in the past.
    import datetime as _dt
    cutoff = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
    graded = [r["espn_event_id"] for r in con.execute("""
        SELECT DISTINCT g.espn_event_id FROM prop_games g JOIN props p ON p.game_id = g.id
        JOIN prop_results r ON r.prop_id = p.id
        WHERE g.league='mlb' AND g.espn_event_id IS NOT NULL AND g.date <= ?
        ORDER BY g.date DESC""", (cutoff,))]
    sample = graded[:SAMPLE_SIZE]

    print(f"database   {db}")
    print(f"games      {len(games)} MLB games carrying props")
    print(f"sample     {len(sample)} games cross-checked against ESPN\n")

    print("── BEFORE ─────────────────────────────────────────────")
    b_checked, b_wrong, b_ex = measure(con, sample)
    print(f"  {b_wrong} of {b_checked} graded props disagree with ESPN's final box score")
    for e in b_ex[:5]:
        print(f"    {e}")

    if args.dry_run:
        print("\ndry run — nothing changed")
        return

    backup = create_verified_backup(db)
    print(f"\nbackup     {backup}\n")

    print("── RE-GRADING ─────────────────────────────────────────")
    finals_cache, settled_games, skipped, errors = {}, 0, 0, 0
    purged = [0]
    for i, g in enumerate(games, 1):
        date = g["date"]
        if date not in finals_cache:
            try:
                finals_cache[date] = finals_for(date)
            except Exception as e:
                print(f"  schedule {date} failed: {e}")
                finals_cache[date] = {}
        final = finals_cache[date].get((g["home"], g["away"]))
        if final is None:
            # Not final — and any result sitting on it is a fabrication, written before the
            # game was played. Delete it. A game that has not finished has no results, and
            # "not graded" is the honest state; the fixed settle_game will grade it once it
            # is over.
            removed = con.execute("""DELETE FROM prop_results WHERE prop_id IN
                                     (SELECT id FROM props WHERE game_id=?)""", (g["id"],)).rowcount
            con.commit()
            purged[0] += removed
            skipped += 1
            continue
        con.execute("UPDATE prop_games SET final_home=?, final_away=? WHERE id=?",
                    (final[0], final[1], g["id"]))
        con.execute("""DELETE FROM prop_results WHERE prop_id IN
                       (SELECT id FROM props WHERE game_id=?)""", (g["id"],))
        con.commit()
        try:
            res = settlement.settle_game(con, g["id"])
            if res.get("errors"):
                errors += 1
            settled_games += 1
        except Exception as e:
            errors += 1
            print(f"  game {g['id']} ({g['espn_event_id']}) failed: {e}")
        time.sleep(PACE_SECONDS)
        if i % 50 == 0:
            print(f"  {i}/{len(games)} games · {settled_games} re-graded · "
                  f"{skipped} not final · {errors} errors")

    print(f"\n  {settled_games} re-graded · {skipped} not final "
          f"({purged[0]} false results deleted) · {errors} errors")

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
