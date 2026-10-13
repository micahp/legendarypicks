"""Repair NCAAF props written under the pre-strict wrong bindings.

Step 3's rebind disposition, one table down: the binding replay re-verified
six relay keys onto team-verified rows, but the props already stored under the
old row keep pointing at the wrong human. A prop sitting on a player whose
team is not in the prop's game, where the verified row's team IS in the game,
moves to the verified row. Props outside a verified fixture are left alone.
Result rows for moved props are deleted — they were graded against the wrong
player, and the grader decides the new value.

    python repair_ncaaf_wrong_binding_props.py            # dry run
    python repair_ncaaf_wrong_binding_props.py --apply
"""
import argparse
import re
import sqlite3
import sys

sys.path.insert(0, "/root/legendarypicks/backend")
import ingest_rotowire_props as r  # noqa: E402

# Verified by the 2026-10-02 binding replay (source team = roster team =
# fixture team, all three published). (old_player_id, new_player_id)
VERIFIED_REBINDS = [
    (61518, 33534),  # Brian Williams    BRY WR -> AUB WR
    (37573, 45202),  # Chris Henry       CCU S  -> OSU WR
    (54625, 37747),  # Chris Johnson     SDSU CB -> CLEM RB
    (46215, 50567),  # DJ Allen          RUTG DL -> UTSA WR
    (41610, 61632),  # Jackson Williams  LSU S  -> NDSU WR
    (54343, 41561),  # Winston Watkins   TOW QB -> LSU WR
]


def main(db_path, apply):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    vocabulary = r.team_vocabulary(con, "ncaaf")

    def strip_rank(word):
        return re.sub(r"\s*\([^()]*#\d+[^()]*\)\s*$", "", (word or "").strip()).strip()

    moved_total = 0
    for old_id, new_id in VERIFIED_REBINDS:
        new_row = con.execute(
            "SELECT name, team FROM players WHERE id=?", (new_id,)).fetchone()
        if not new_row:
            print(f"SKIP {old_id}->{new_id}: verified row missing")
            continue
        team = (new_row["team"] or "").upper()
        props = con.execute(
            "SELECT p.id, p.game_id, pg.home, pg.away, pg.date "
            "FROM props p JOIN prop_games pg ON pg.id=p.game_id "
            "WHERE p.player_id=? AND pg.league='ncaaf'", (old_id,)).fetchall()
        moved = 0
        for x in props:
            codes = {
                c.upper() for c in (
                    r.resolve_team(vocabulary, strip_rank(x["home"])),
                    r.resolve_team(vocabulary, strip_rank(x["away"])),
                ) if c
            }
            if team not in codes:
                print(f"  LEAVE prop {x['id']} ({x['date']}): {team} not in {sorted(codes)}")
                continue
            if apply:
                con.execute("UPDATE props SET player_id=? WHERE id=?", (new_id, x["id"]))
                con.execute("DELETE FROM prop_results WHERE prop_id=?", (x["id"],))
            moved += 1
        print(f"{new_row['name']} ({team}): {moved}/{len(props)} props "
              f"{'MOVED' if apply else 'would move'} {old_id} -> {new_id}")
        moved_total += moved

    if apply:
        con.commit()
        print("APPLIED to", db_path)
    else:
        con.rollback()
        print("dry run; rerun with --apply")
    con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--db", default="data/picks.dev.db")
    args = ap.parse_args()
    main(args.db, args.apply)
