#!/usr/bin/env python3
"""Fold stale unlinked NCAAF Bovada fixture rows onto their canonical games.

Step 4 of the 2026-10-02 repair order. Two dispositions, both measured first:

A. TWIN FOLD. An unlinked Bovada row whose date and two clubs match a linked
   prop_games row on the same local date, with at least one player priced on
   both rows, is the same game ingested twice. The Bovada row never enters
   settlement (no event id, no final), so its props are dead until they move.
   The fold repoints `props` and `prop_game_source_ids` with the shared
   `prop_game_merge.fold_prop_game` and deletes the loser row.

B. STALE LINK. The diagnosis's four unmatched fixtures (plus Sam Houston State
   at Texas Tech, priced after the diagnosis) have no linked twin because the
   linker never resolved them. Each has exactly one final scoreboard snapshot
   on its date whose two clubs match; that snapshot's game_id is the event id.
   The fixtures and their verified event ids are recorded below, and the apply
   re-verifies every one against the stored snapshot before writing.

Scope: rows dated before today only. The current slate belongs to the
scheduled linker (`link_prop_games.py`), which resolves fixtures once the
scoreboard publishes them; folding today's rows would guess.

    python fold_ncaaf_unlinked_fixtures.py            # dry run
    python fold_ncaaf_unlinked_fixtures.py --apply
"""
import argparse
import datetime as dt
import json
import re
import sqlite3
import sys

sys.path.insert(0, "/root/legendarypicks/backend")
import ingest_rotowire_props as r  # noqa: E402
from prop_game_merge import fold_prop_game  # noqa: E402

# Fixture text (the two club words + date as stored on the Bovada row) -> the
# ESPN event id verified against the unique final scoreboard snapshot of that
# date. Verified 2026-10-03 on DEV; the apply re-checks each against the stored
# snapshot. Club words are unordered: the two publishers disagree about which
# side is home.
VERIFIED_LINKS = {
    (frozenset(("army", "south florida")), "2026-09-12"): "401862702",
    (frozenset(("pittsburgh", "syracuse")), "2026-09-17"): "401858225",
    (frozenset(("coastal carolina", "liberty")), "2026-09-24"): "401869941",
    (frozenset(("army", "temple")), "2026-09-25"): "401862779",
    (frozenset(("sam houston state", "texas tech")), "2026-09-26"): "401856805",
}


def _strip_rank(word):
    return re.sub(r"\s*\([^()]*#\d+[^()]*\)\s*$", "", (word or "").strip()).strip()


def _norm(word):
    return " ".join(re.findall(r"[a-z0-9]+", (word or "").lower()))


def main(db_path, apply):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    vocabulary = r.team_vocabulary(con, "ncaaf")
    today = dt.date.today().isoformat()

    unlinked = con.execute("""
        SELECT pg.id, pg.date, pg.home, pg.away, COUNT(p.id) props
        FROM prop_games pg JOIN props p ON p.game_id = pg.id
        LEFT JOIN prop_results pr ON pr.prop_id = p.id
        WHERE pg.league='ncaaf'
          AND (pg.espn_event_id IS NULL OR pg.espn_event_id='')
          AND pg.final_home IS NULL AND pg.date < ?
        GROUP BY pg.id ORDER BY pg.date
    """, (today,)).fetchall()
    print(f"stale unlinked ncaaf rows (date < {today}):", len(unlinked),
          "props:", sum(x["props"] for x in unlinked))

    linked = con.execute("""
        SELECT pg.id, pg.date, pg.home, pg.away, pg.espn_event_id
        FROM prop_games pg
        WHERE pg.league='ncaaf'
          AND pg.espn_event_id IS NOT NULL AND pg.espn_event_id != ''
    """).fetchall()
    players_on = {}
    for row in con.execute("""
        SELECT DISTINCT game_id, player_id FROM props
        WHERE game_id IN (SELECT id FROM prop_games WHERE league='ncaaf')
    """):
        players_on.setdefault(row["game_id"], set()).add(row["player_id"])

    def codes(words):
        return frozenset(
            c.upper() for c in (
                r.resolve_team(vocabulary, _strip_rank(w)) for w in words
            ) if c)

    linked_by_date = {}
    for g in linked:
        linked_by_date.setdefault(g["date"], []).append(g)

    folded = linked_new = skipped = 0
    unresolved_rows = []
    for u in unlinked:
        ucodes = codes((u["home"], u["away"]))
        cands = [g for g in linked_by_date.get(u["date"], [])
                 if ucodes and codes((g["home"], g["away"])) == ucodes
                 and players_on.get(u["id"], set()) & players_on.get(g["id"], set())]
        if len(cands) == 1:
            twin = cands[0]
            results = con.execute(
                "SELECT COUNT(*) FROM prop_results WHERE prop_id IN "
                "(SELECT id FROM props WHERE game_id=?)", (u["id"],)).fetchone()[0]
            if results:
                print(f"  SKIP {u['id']} {u['away']} @ {u['home']} {u['date']}: "
                      f"{results} result rows on the loser row")
                skipped += 1
                continue
            print(f"  FOLD {u['id']} -> {twin['id']} ({twin['espn_event_id']}) "
                  f"{u['away']} @ {u['home']} {u['date']}: {u['props']} props")
            if apply:
                fold_prop_game(con, u["id"], twin["id"])
                con.commit()
            folded += u["props"]
            continue

        # No twin: the stale-link half. Evidence is recorded, not guessed.
        event = VERIFIED_LINKS.get((frozenset((_norm(_strip_rank(u["away"])),
                                               _norm(_strip_rank(u["home"])))), u["date"]))
        if not event:
            print(f"  LEAVE {u['id']} {u['away']} @ {u['home']} {u['date']}: "
                  f"{u['props']} props (no verified link)")
            unresolved_rows.append(u)
            skipped += 1
            continue
        snaps = con.execute(
            "SELECT game_id, payload, state FROM scoreboard_snapshots "
            "WHERE league='ncaaf' AND game_date=? AND game_id=?",
            (u["date"], event)).fetchall()
        if len(snaps) != 1:
            print(f"  REFUSE {u['id']} {u['away']} @ {u['home']} {u['date']}: "
                  f"expected 1 snapshot for {event}, found {len(snaps)}")
            skipped += 1
            continue
        payload = json.loads(snaps[0]["payload"])
        if (snaps[0]["state"] or "") not in ("post", "final"):
            print(f"  REFUSE {u['id']}: snapshot {event} state={snaps[0]['state']}")
            skipped += 1
            continue
        def _club_words(team):
            """Name, nickname, and the school form (name minus nickname)."""
            name = _norm((team or {}).get("name"))
            nickname = _norm((team or {}).get("nickname"))
            words = {name, nickname}
            if nickname and name.endswith(nickname):
                school = name[: -len(nickname)].strip()
                if school:
                    words.add(school)
            return words

        sides = _club_words(payload.get("home")) | _club_words(payload.get("away"))
        stored = {_norm(_strip_rank(u["home"])), _norm(_strip_rank(u["away"]))}
        if not (sides & stored) or len(sides) < 2:
            print(f"  REFUSE {u['id']}: snapshot clubs {sorted(sides)} do not cover "
                  f"{sorted(stored)}")
            skipped += 1
            continue
        # Each stored club must appear in exactly one snapshot side.
        home_w, away_w = _club_words(payload.get("home")), _club_words(payload.get("away"))
        if any((stored_team in home_w) and (stored_team in away_w) for stored_team in stored):
            print(f"  REFUSE {u['id']}: a stored club appears on both snapshot sides")
            skipped += 1
            continue
        clash = con.execute(
            "SELECT id, date FROM prop_games WHERE league='ncaaf' "
            "AND espn_event_id=? AND id != ?", (event, u["id"])).fetchall()
        holders = [h for h in clash if h["date"] == u["date"]]
        if len(clash) > 1 or len(holders) > 1:
            print(f"  REFUSE {u['id']}: event {event} on {len(clash)} other row(s)")
            skipped += 1
            continue
        if holders:
            # The event is already linked (the Bovada club word "Sam Houston State"
            # is outside the vocabulary, so the twin rule could not see it). The
            # event id is the identity: fold onto the holder under the same
            # safety checks.
            holder = holders[0]
            results = con.execute(
                "SELECT COUNT(*) FROM prop_results WHERE prop_id IN "
                "(SELECT id FROM props WHERE game_id=?)", (u["id"],)).fetchone()[0]
            if results:
                print(f"  SKIP {u['id']}: {results} result rows on the loser row")
                skipped += 1
                continue
            print(f"  FOLD {u['id']} -> {holder['id']} ({event}) {u['away']} @ "
                  f"{u['home']} {u['date']}: {u['props']} props (event already linked)")
            if apply:
                fold_prop_game(con, u["id"], holder["id"])
                con.commit()
            folded += u["props"]
            continue
        print(f"  LINK {u['id']} <- {event} {u['away']} @ {u['home']} "
              f"{u['date']}: {u['props']} props")
        if apply:
            con.execute("UPDATE prop_games SET espn_event_id=? WHERE id=?",
                        (event, u["id"]))
            con.commit()
        linked_new += u["props"]

    left_props = sum(u["props"] for u in unresolved_rows)
    verb = "APPLIED" if apply else "DRY RUN"
    print(f"{verb}: folded {folded} props, linked {linked_new} props, "
          f"left {left_props} props on {len(unresolved_rows)} unresolved rows")
    con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--db", default=None)
    args = ap.parse_args()
    main(args.db or __import__("os").environ.get(
        "LP_DB_PATH",
        "/root/legendarypicks/backend/data/picks.dev.db"), args.apply)
