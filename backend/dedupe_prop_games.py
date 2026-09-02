#!/usr/bin/env python3
"""Merge the prop_games rows that are the same published event.

An ESPN event id IS the identity of a game. Prod holds 59 event ids spread across
124 prop_games rows -- one real fixture stored two or three times, usually on
consecutive calendar dates with the same two clubs:

    event 401815804  row 28  2026-06-18  Mets @ Phillies  91 props  final 4-6
                     row 58  2026-06-19  Mets @ Phillies  16 props  final 4-6

Why it matters, and it is not tidiness: settlement works one prop_games row at a
time. It grades row 28, writes its results, and row 58's 16 props are never
looked at again -- there is no second game for them to be graded against.

Sized honestly, because an earlier draft of this docstring called it "the mechanism
behind prod's June hole" and that was wrong. June's 14,124 unsettled MLB props (against
693 settled) partition as: 827 on rows never linked, 4,467 on linked rows with no final
score, 2,212 on duplicated rows, and 6,618 on rows that are linked, unique and final.
The duplicates are 16%. The dominant cause is a missing start_time -- without one,
_fetch_mlb_gamepk searches day-1/day/day+1, a series plays the same clubs on consecutive
days, and it fails closed rather than grade against the wrong game. This merge is worth
doing on its own terms; backfill_prop_game_start_time.py is what unblocks June.

How the rows come to exist: the props ingest matches an existing game on
(league, date, home, away) and inserts when it misses. A first pitch at 21:40 ET
is the next day in UTC, so the same fixture arrives under two calendar dates
depending on which convention the payload carried, and each date misses the
other's row. The linker then resolves BOTH to the same ESPN event, which is what
makes them recoverable now.

Rules
-----
  1. A group is the set of rows sharing (league, espn_event_id), event id
     non-blank. Rows with no event id are never touched: without the publisher's
     id there is nothing asserting they are the same game, and date+teams is
     exactly the guess that created this mess.
  2. Winner = the row that carries a final score, then the one with the most
     props, then the lowest id. Deterministic, and it keeps the row settlement
     has already worked with.
  3. props.game_id is the only integer reference to prop_games -- verified
     against the schema, the other game_id columns hold ESPN's text id and key
     on nothing here. Repointing props is the whole merge.
  4. ABORT if a group disagrees about a fact: different home/away teams, or two
     different non-null final scores. Either means the LINK is wrong, and
     merging on a wrong link would fuse two real games into one. An unmerged row
     is recoverable; a fused one is not.
  5. `--resolve-finals` (MLB only) settles rule 4's final-score disagreements by
     asking the publisher instead of aborting. See below.

`--resolve-finals`: when two rows disagree, ask MLB
---------------------------------------------------
Rule 4 is right to refuse a guess, but a disagreement is a question, not a dead end.
Prod's 7 conflicting groups on 2026-08-17 all had the same shape, and MLB Stats
answered it: `schedule?sportId=1&date=` over both of a group's dates returns exactly
ONE real game between those clubs, and exactly one of the two stored finals matches
the published line score. Every time, it was the LATER-dated row:

    event 401816224  Marlins @ Astros   published pk 824166, 2026-07-23T00:10Z, 2-5
      row 342  2026-07-22  stored 3-5     <- the 2026-07-22 game's score
      row 361  2026-07-23  stored 2-5     <- matches the publisher

So the earlier row is the day-early duplicate AND its final came from the previous
day's game between the same two clubs -- graded against the wrong fixture, the exact
failure _fetch_mlb_gamepk's docstring was written about.

That makes the loser's prop_results wrong, not merely redundant, so this mode deletes
them. It has to: settle_game is idempotent and skips a prop that already holds a
result, so a wrong grade left in place is permanent. Deleting it returns the prop to
ungraded and the next settlement run recomputes it against the surviving row.

Fail-closed throughout. The publisher must return exactly one game for the group's
clubs across its dates, exactly one stored final must match it, and a fetch that
raises aborts the group rather than resolving it. Anything else falls back to rule 4.
An unmerged row is still recoverable.

This does NOT dedupe props. Repointing can land two identical props rows on one
game, which is exactly what dedupe_props.py exists for -- run it after.

Usage:
  venv/bin/python dedupe_prop_games.py --db data/picks.dev.db [--apply]
  venv/bin/python dedupe_prop_games.py --db data/picks.db --resolve-finals --apply
"""
import argparse
import collections
import json
import os
import sqlite3
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prop_game_merge import fold_prop_game

_SCHEDULE_CACHE = {}


def _mlb_schedule(date_str):
    """MLB's published slate for a calendar date. Cached: a group re-asks its own dates."""
    if date_str not in _SCHEDULE_CACHE:
        url = ("https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=" + date_str)
        with urllib.request.urlopen(url, timeout=25) as fh:
            _SCHEDULE_CACHE[date_str] = json.load(fh)
        time.sleep(0.2)
    return _SCHEDULE_CACHE[date_str]


def _published_final(dates, home, away):
    """-> (gamePk, final_home, final_away) when MLB publishes exactly one such game.

    None when the publisher is ambiguous, silent, or unreachable -- every one of which
    must leave the caller aborting rather than merging. `statsapi` is used rather than
    ESPN because it is authoritative for MLB and costs nothing against the ESPN
    per-host request budget.
    """
    found = {}
    for date_str in dates:
        try:
            payload = _mlb_schedule(date_str)
        except Exception:
            return None                      # a failed fetch is not "no game"
        for day in payload.get("dates", []):
            for game in day.get("games", []):
                teams = game.get("teams", {})
                if (teams.get("home", {}).get("team", {}).get("name") == home
                        and teams.get("away", {}).get("team", {}).get("name") == away):
                    found[game.get("gamePk")] = game
    if len(found) != 1:
        return None
    pk, game = next(iter(found.items()))
    if (game.get("status") or {}).get("abstractGameState") != "Final":
        return None
    try:
        url = "https://statsapi.mlb.com/api/v1.1/game/{}/feed/live".format(pk)
        with urllib.request.urlopen(url, timeout=30) as fh:
            live = json.load(fh)
        line = live["liveData"]["linescore"]["teams"]
    except Exception:
        return None
    home_runs, away_runs = line["home"].get("runs"), line["away"].get("runs")
    if home_runs is None or away_runs is None:
        return None
    return pk, home_runs, away_runs


def _groups(con):
    """{(league, espn_event_id): [row ids]} for every event stored more than once."""
    grouped = collections.defaultdict(list)
    for row in con.execute(
            "SELECT league, espn_event_id, id FROM prop_games "
            "WHERE espn_event_id IS NOT NULL AND espn_event_id != '' ORDER BY id"):
        grouped[(row[0], row[1])].append(row[2])
    return {key: ids for key, ids in grouped.items() if len(ids) > 1}


def _facts(con, ids):
    """{id: row} for the columns a merge has to agree about."""
    marks = ",".join("?" * len(ids))
    return {r["id"]: r for r in con.execute(
        f"SELECT id, league, date, home, away, start_time, final_home, final_away, "
        f"espn_event_id FROM prop_games WHERE id IN ({marks})", ids)}


def run(db_path, apply=False, resolve_finals=False):
    con = sqlite3.connect(os.path.abspath(db_path))
    con.row_factory = sqlite3.Row
    print(f"database: {os.path.abspath(db_path)}")

    before_games = con.execute("SELECT COUNT(*) FROM prop_games").fetchone()[0]
    before_props = con.execute("SELECT COUNT(*) FROM props").fetchone()[0]

    groups = _groups(con)
    prop_counts = dict(con.execute(
        "SELECT game_id, COUNT(*) FROM props GROUP BY game_id").fetchall())
    print(f"  prop_games: {before_games}")
    print(f"  events stored more than once: {len(groups)} "
          f"({sum(len(v) for v in groups.values())} rows)")

    conflicts = []
    resolutions = []     # (key, gamePk, pub_home, pub_away, winner_id, [loser_ids])
    wrong_final_losers = []   # rows whose final came from a DIFFERENT game
    losers = []          # (loser_id, winner_id)
    winners_by_group = {}
    per_league = collections.Counter()

    for key, ids in groups.items():
        rows = _facts(con, ids)

        teams = {(r["home"], r["away"]) for r in rows.values()}
        if len(teams) > 1:
            conflicts.append(("teams", key, sorted(teams)))
            continue
        finals = {(r["final_home"], r["final_away"]) for r in rows.values()
                  if r["final_home"] is not None or r["final_away"] is not None}
        if len(finals) > 1:
            resolved = None
            if resolve_finals and key[0] == "mlb":
                sample = next(iter(rows.values()))
                published = _published_final(
                    sorted({r["date"] for r in rows.values()}),
                    sample["home"], sample["away"])
                if published:
                    pk, pub_home, pub_away = published
                    matching = [i for i, r in rows.items()
                                if (r["final_home"], r["final_away"]) == (pub_home, pub_away)]
                    if len(matching) == 1:
                        resolved = matching[0]
                        resolutions.append((key, pk, pub_home, pub_away, resolved,
                                            [i for i in ids if i != resolved]))
            if resolved is None:
                conflicts.append(("final score", key, sorted(finals)))
                continue
            # The rows that did not match were graded against a different fixture, so
            # their results are wrong rather than redundant. Force the winner: the
            # ordering below would otherwise pick on prop count and could keep the row
            # holding the wrong score.
            winners_by_group[key] = resolved
            per_league[key[0]] += len(ids) - 1
            for i in ids:
                if i != resolved:
                    losers.append((i, resolved))
                    wrong_final_losers.append(i)
            continue

        winner = sorted(
            ids,
            key=lambda i: (rows[i]["final_home"] is None,      # a settled row first
                           -prop_counts.get(i, 0),             # then the fuller one
                           i))[0]                              # then deterministic
        winners_by_group[key] = winner
        per_league[key[0]] += len(ids) - 1
        for i in ids:
            if i != winner:
                losers.append((i, winner))

    if conflicts:
        print(f"\nABORT — {len(conflicts)} group(s) disagree about a fact. Nothing written.")
        print("A disagreement here means the LINK is wrong, not that the rows are dupes;")
        print("merging on it would fuse two different games into one.")
        for kind, key, values in conflicts[:20]:
            print(f"  {kind:12s} {key}: {values}")
        if len(conflicts) > 20:
            print(f"  ... and {len(conflicts) - 20} more")
        con.close()
        return 2

    moved_props = sum(prop_counts.get(i, 0) for i, _ in losers)
    print(f"  rows to remove: {len(losers)}   props to repoint: {moved_props}")
    print("  by league: " + (", ".join(f"{k}={v}" for k, v in per_league.most_common())
                             or "(none)"))

    # The prop ids are captured BEFORE any repoint, because that is the only moment the
    # rows graded against the wrong fixture are still identifiable -- once game_id moves
    # they are indistinguishable from the winner's own props.
    stale_prop_ids = []
    if wrong_final_losers:
        marks = ",".join("?" * len(wrong_final_losers))
        stale_prop_ids = [r[0] for r in con.execute(
            f"SELECT id FROM props WHERE game_id IN ({marks})", wrong_final_losers)]
        stale_results = con.execute(
            f"SELECT COUNT(*) FROM prop_results WHERE prop_id IN "
            f"(SELECT id FROM props WHERE game_id IN ({marks}))",
            wrong_final_losers).fetchone()[0]
        print(f"\n  publisher resolved {len(resolutions)} final-score conflict(s):")
        for key, pk, ph, pa, win, lost in resolutions:
            print(f"    event {key[1]}  MLB pk {pk} final {pa}-{ph}  keep row {win}, "
                  f"drop {lost}")
        print(f"  {stale_results} prop_results on the dropped rows were graded against a "
              f"different\n  fixture and will be deleted so settlement recomputes them.")

    if not apply:
        print("\ndry run — nothing written. Re-run with --apply.")
        con.close()
        return 0

    deleted_results = 0
    for chunk in range(0, len(stale_prop_ids), 500):
        batch = stale_prop_ids[chunk:chunk + 500]
        cur = con.execute("DELETE FROM prop_results WHERE prop_id IN ({})".format(
            ",".join("?" * len(batch))), batch)
        deleted_results += cur.rowcount

    for loser, winner in losers:
        fold_prop_game(con, loser, winner)
    marks_batch = [l for l, _ in losers]
    con.commit()

    after_games = con.execute("SELECT COUNT(*) FROM prop_games").fetchone()[0]
    after_props = con.execute("SELECT COUNT(*) FROM props").fetchone()[0]
    remaining = len(_groups(con))
    orphaned = con.execute(
        "SELECT COUNT(*) FROM props p LEFT JOIN prop_games g ON g.id=p.game_id "
        "WHERE g.id IS NULL").fetchone()[0]
    still_pointing = con.execute(
        "SELECT COUNT(*) FROM props WHERE game_id IN ({})".format(
            ",".join("?" * len(marks_batch))), marks_batch).fetchone()[0] if marks_batch else 0

    print(f"\n  prop_games  {before_games} -> {after_games}  (removed "
          f"{before_games - after_games})")
    print(f"  props       {before_props} -> {after_props}  ({moved_props} repointed)")
    if resolutions:
        print(f"  prop_results deleted (graded against the wrong fixture): {deleted_results}")

    # Every row that left has to be one this run decided to remove, and no prop may be
    # left pointing at a row that no longer exists. A count that merely went down is not
    # evidence.
    checks = {
        "prop_games removed == losers": before_games - after_games == len(losers),
        "props count unchanged": before_props == after_props,
        "no props left on a removed row": still_pointing == 0,
        "no orphaned props": orphaned == 0,
        "no duplicated events left": remaining == 0,
        # Ask the table, not the counter. `deleted_results` is what this run believes it
        # did; this is whether any wrongly-graded prop still holds a result.
        "no stale results survive": (not stale_prop_ids) or con.execute(
            "SELECT COUNT(*) FROM prop_results WHERE prop_id IN ({})".format(
                ",".join("?" * len(stale_prop_ids))), stale_prop_ids).fetchone()[0] == 0,
        "resolved winners survived": all(
            con.execute("SELECT 1 FROM prop_games WHERE id=?", (w,)).fetchone() is not None
            for _, _, _, _, w, _ in resolutions),
    }
    for label, passed in checks.items():
        print("    {:34s} {}".format(label, "ok" if passed else "FAIL"))
    ok = all(checks.values())

    if ok:
        # The constraint is the actual fix; this merge only clears the way for it. SQLite
        # refuses to build a unique index over data that violates it, so this statement
        # succeeding is itself the last check -- and from here the ingest cannot recreate
        # what we just removed. See _core.py for why the duplicates arise honestly.
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_prop_games_event "
                    "ON prop_games(league, espn_event_id) "
                    "WHERE espn_event_id IS NOT NULL AND espn_event_id != ''")
        con.commit()
        print("    {:34s} {}".format("unique index created", "ok"))

    print("  reconciled: {}".format("yes" if ok else "NO -- investigate"))
    print("\nprops were repointed, not deduped — two identical props can now share a "
          "game.\nRun dedupe_props.py next.")
    con.close()
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/picks.dev.db")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--resolve-finals", action="store_true",
                    help="MLB only: ask the publisher which final is right instead of "
                         "aborting, and delete results graded against the wrong fixture "
                         "(see the module docstring)")
    args = ap.parse_args()
    return run(args.db, apply=args.apply, resolve_finals=args.resolve_finals)


if __name__ == "__main__":
    sys.exit(main())
