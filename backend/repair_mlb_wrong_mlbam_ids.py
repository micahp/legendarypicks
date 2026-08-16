#!/usr/bin/env python3
"""repair_mlb_wrong_mlbam_ids.py — fix player rows carrying a DIFFERENT
same-named person's mlbam_id, proving each repair against the box score.

WHY THIS EXISTS
---------------
Some `players` rows carry the MLB id of a different man who happens to share
their name. Found 2026-08-11 while deduplicating:

    players.id=12     Joe Mack       mlbam 118086 -> Boston Braves, debut 1945
    players.id=94     Jacob Wilson   mlbam 607111 -> Sugar Land Skeeters, inactive
    players.id=27342  Luis Castillo  mlbam 699127 -> Wisconsin Timber Rattlers, OF

Each carries real props (1,540 / 3,631 / 262 = **5,433**) and every one of them
settles to `hit=NULL, actual=NULL` forever, because MLB settlement keys the box
score by `mlbam_id` and that id never appears in it. The pipeline fails closed,
so there is no wrong grade and no error — just props that silently never grade.
The correct id already exists in the table, on a twin row with zero props.

WHY THIS IS NOT A DEDUPE
------------------------
`dedupe_mlb.py` merges rows that SHARE an mlbam_id, and it is right to refuse
these: the two ids are different, so as far as identity goes they are different
men. Repairing them means deciding that one of the rows is mislabelled, which is
a claim about the world and needs evidence, not a name match. After this script
runs the repaired row becomes a genuine duplicate of its twin, and `dedupe_mlb.py`
merges them on the next pass.

THE EVIDENCE — never a name, never a position
---------------------------------------------
A candidate is only repaired when, for every game sampled from its OWN props:

  1. its current mlbam_id is ABSENT from the published box score, and
  2. exactly one same-name sibling's mlbam_id is PRESENT in it.

That is a falsifiable test against the publisher rather than a resemblance
argument (published-first §5). Measured on the three above, plus a control:

    Joe Mack       118086 in box: False | 691788 in box: True   -> repair
    Jacob Wilson   607111 in box: False | 805779 in box: True   -> repair
    Luis Castillo  699127 in box: False | 622491 in box: True   -> repair
    Jared Jones    683003 in box: True                          -> LEAVE ALONE

Jared Jones is the control that matters: he sits in the same name-collision
list and looks identical to the eye, and his id is already correct. A repair
driven by "these two rows look alike" would have corrupted him.

REQUEST COST
------------
statsapi.mlb.com only — a different publisher from ESPN with no comparable
per-host ceiling, and the issuer of the ids in question. Roughly
`candidates x --games` schedule+boxscore pairs; the count is printed before it
is spent. Schedules are cached per date by settlement._mlb_schedule.

Usage:
  LP_DB_PATH=data/picks.dev.db python3 repair_mlb_wrong_mlbam_ids.py [--apply]

Default is a dry run. Takes its own backup before writing. Run dedupe_mlb.py
afterwards to merge each repaired row into its twin.
"""
import argparse
import datetime as dt
import os
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from settlement import _fetch_mlb_gamepk, _fetch_mlb_boxscore  # noqa: E402


def norm_name(n):
    s = unicodedata.normalize("NFKD", n or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", "", s)).strip()


def boxscore_mlbam_ids(box):
    """Every mlbam_id that appears in a published box score."""
    ids = set()
    for side in ("home", "away"):
        players = ((box.get("teams", {}).get(side, {}) or {}).get("players", {}) or {})
        for key in players:
            try:
                ids.add(int(str(key).replace("ID", "")))
            except ValueError:
                continue
    return ids


def name_collision_groups(con):
    """MLB rows sharing a normalised name but holding DIFFERENT mlbam_ids."""
    rows = [dict(r) for r in con.execute(
        """SELECT id, name, team, position, mlbam_id FROM players
           WHERE league='mlb' AND mlbam_id IS NOT NULL AND mlbam_id != 0""")]
    by_name = defaultdict(list)
    for r in rows:
        by_name[norm_name(r["name"])].append(r)
    return {k: v for k, v in by_name.items()
            if len({r["mlbam_id"] for r in v}) > 1}


def verdict(con, row, siblings, n_games):
    """(decision, detail). Decides ONLY from published box scores.

    Returns ('repair', mlbam) / ('ok', mlbam) / ('unproven', reason).
    """
    games = con.execute(
        """SELECT DISTINCT g.date, g.home, g.away FROM props p
           JOIN prop_games g ON g.id = p.game_id
           WHERE p.player_id=? AND g.date IS NOT NULL
           ORDER BY g.date DESC LIMIT ?""", (row["id"], n_games)).fetchall()
    if not games:
        return "unproven", "no props to check against"

    sib_ids = [s["mlbam_id"] for s in siblings]
    present_self, present_sib, checked = 0, defaultdict(int), 0
    for g in games:
        pk = _fetch_mlb_gamepk(g["date"], g["home"], g["away"])
        if not pk:
            continue
        box = _fetch_mlb_boxscore(pk)
        if not box:
            continue
        ids = boxscore_mlbam_ids(box)
        checked += 1
        if row["mlbam_id"] in ids:
            present_self += 1
        for s in sib_ids:
            if s in ids:
                present_sib[s] += 1

    if not checked:
        return "unproven", "no box score could be read"
    if present_self:
        return "ok", row["mlbam_id"]
    winners = [s for s, n in present_sib.items() if n == checked]
    if len(winners) == 1:
        return "repair", winners[0]
    if not winners:
        return "unproven", "neither this id nor any sibling appears in %d box scores" % checked
    return "unproven", "%d siblings both appear — ambiguous" % len(winners)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--games", type=int, default=3,
                    help="box scores to check per candidate (all must agree)")
    args = ap.parse_args()

    db = os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    groups = name_collision_groups(con)
    candidates = []
    for name, rows in sorted(groups.items()):
        for r in rows:
            n = con.execute("SELECT COUNT(*) FROM props WHERE player_id=?", (r["id"],)).fetchone()[0]
            if n:
                candidates.append((r, [s for s in rows if s["id"] != r["id"]], n))

    print("name-collision groups : %d" % len(groups))
    print("rows carrying props   : %d" % len(candidates))
    print("statsapi cost         : up to %d schedule+boxscore pairs (no ESPN)"
          % (len(candidates) * args.games))
    print()

    repairs, oks, unproven = [], [], []
    for row, sibs, nprops in candidates:
        d, detail = verdict(con, row, sibs, args.games)
        if d == "repair":
            repairs.append((row, detail, nprops))
            print("  REPAIR   id=%-6s %-20s %s -> %s   (%d props)"
                  % (row["id"], row["name"], row["mlbam_id"], detail, nprops))
        elif d == "ok":
            oks.append(row)
            print("  ok       id=%-6s %-20s %s appears in its own box scores"
                  % (row["id"], row["name"], row["mlbam_id"]))
        else:
            unproven.append((row, detail))
            print("  UNPROVEN id=%-6s %-20s %s" % (row["id"], row["name"], detail))

    print("\nrepair: %d   already correct: %d   unproven (left alone): %d"
          % (len(repairs), len(oks), len(unproven)))
    if repairs:
        print("props that would become gradeable: %d" % sum(n for _, _, n in repairs))

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")
        return
    if not repairs:
        print("\nNothing to write.")
        return

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bak = "%s.pre-idrepair-%s.bak" % (db, stamp)
    con.execute("VACUUM INTO ?", (bak,))
    chk = sqlite3.connect(bak).execute("PRAGMA quick_check").fetchone()[0]
    print("\nbackup: %s (quick_check: %s)" % (bak, chk))
    if chk != "ok":
        sys.exit("backup failed integrity check — refusing to write")

    for row, new_id, _ in repairs:
        con.execute("UPDATE players SET mlbam_id=? WHERE id=?", (new_id, row["id"]))
    con.commit()
    print("re-identified %d rows" % len(repairs))
    print("NEXT: run dedupe_mlb.py — each repaired row is now a true duplicate "
          "of its twin and must be merged.")


if __name__ == "__main__":
    main()
