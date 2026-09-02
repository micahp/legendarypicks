#!/usr/bin/env python3
"""Fill the NCAAF positions CFBD cannot, from ESPN's published rosters.

`backfill_ncaaf_positions_cfbd.py` labels every athlete CFBD rosters -- 5,360 of
5,539 on the dev DB, measured 2026-08-16. The 179 it cannot are FCS squads
(Idaho State, South Carolina State, Southern, Prairie View, LIU ...) that appear
in our DB only because they played an FBS opponent and CFBD published the game
log. CFBD rosters no FCS team, but ESPN does.

Request budget (state BEFORE running, per espn-request-budget):
  1  site.web  /teams?limit=900   -> all 759 college-football teams, FBS + FCS,
                                     abbreviation -> id, in ONE request
  N  site.web  /teams/{id}/roster -> only the teams that still have a blank,
                                     36 on the dev DB
Total 37 to one host, comfortably under the measured ~100 ceiling. Fetching the
179 athletes individually would have been 179 and would have tripped it.

Matching is by **espn_id only**. Every row this script targets already carries
one, so no name is compared at any point.

Usage:
  cd backend && venv/bin/python backfill_ncaaf_positions_espn.py \\
      --db /abs/path/picks.db [--apply]

Dry run by default.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import espn_client as espn  # noqa: E402

LEAGUE = "ncaaf"
_SITE = "https://site.web.api.espn.com/apis/site/v2/sports/football/college-football"
_VOCABULARY_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "position-vocabulary.json")


def _vocabulary():
    with open(_VOCABULARY_PATH) as fh:
        entry = (json.load(fh).get("leagues") or {}).get(LEAGUE) or {}
    return entry.get("positions", {}), entry.get("ancestry", {})


def _position_group(position, vocab):
    if not position:
        return None
    positions, ancestry = vocab
    chain = ancestry.get(position) or []
    root = chain[-1] if chain else position
    return (positions.get(root) or {}).get("name")


def team_ids() -> dict:
    """{ABBREV: espn team id} for every published college-football team."""
    d = espn._get(_SITE + "/teams?limit=900", ttl=43200)
    out = {}
    for sport in d.get("sports", []) or []:
        for league in sport.get("leagues", []) or []:
            for item in league.get("teams", []) or []:
                team = item.get("team") or {}
                abbrev = (team.get("abbreviation") or "").upper()
                tid = str(team.get("id") or "")
                if abbrev and tid:
                    out[abbrev] = tid
    return out


def roster_positions(team_id: str) -> dict:
    """{espn athlete id: position} for one team."""
    d = espn._get(_SITE + f"/teams/{team_id}/roster?limit=200", ttl=43200)
    out = {}
    for group in d.get("athletes", []) or []:
        items = group.get("items") if isinstance(group, dict) and "items" in group else [group]
        for athlete in items or []:
            if not isinstance(athlete, dict):
                continue
            aid = athlete.get("id")
            position = (athlete.get("position") or {}).get("abbreviation")
            if aid and position:
                out[str(aid)] = position
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    vocab = _vocabulary()
    if not vocab[0]:
        print("FAIL: no published position vocabulary on disk.")
        return 2

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    try:
        blank = con.execute(
            "SELECT id, name, team, espn_id FROM players WHERE league=? AND active=1 "
            "AND COALESCE(entity_type,'player')='player' "
            "AND (position IS NULL OR TRIM(position)='') AND espn_id IS NOT NULL",
            (LEAGUE,)).fetchall()
        if not blank:
            print("nothing to do: no blank-position active {} players".format(LEAGUE))
            return 0
        teams = sorted({r["team"] for r in blank if r["team"]})
        print("blank-position ACTIVE {} players: {} across {} teams"
              .format(LEAGUE, len(blank), len(teams)))

        published = team_ids()
        missing_team = [t for t in teams if t not in published]
        if missing_team:
            print("  ESPN publishes no team id for: {}".format(missing_team))

        positions = {}
        fetched = 0
        for abbrev in teams:
            tid = published.get(abbrev)
            if not tid:
                continue
            try:
                positions.update(roster_positions(tid))
                fetched += 1
            except Exception as exc:  # noqa: BLE001 — one team must not stop all
                print("  FAILED roster {} ({}): {}".format(abbrev, tid, exc))
        print("  fetched {} rosters, {} athletes carry a published position"
              .format(fetched, len(positions)))

        updates, unknown = [], []
        for row in blank:
            position = positions.get(str(row["espn_id"]))
            if not position:
                continue
            if position not in vocab[0]:
                unknown.append(position)
                continue
            updates.append((position, _position_group(position, vocab), row["id"]))

        print("  ESPN can label: {}".format(len(updates)))
        print("  still blank:    {}".format(len(blank) - len(updates)))
        if unknown:
            print("  REJECTED positions not in ESPN's published vocabulary: {}"
                  .format(sorted(set(unknown))))
        if not updates:
            print("FAIL: {} blank rows and ESPN labelled none of them."
                  .format(len(blank)))
            return 2

        if not args.apply:
            print("\ndry run -- nothing written. re-run with --apply")
            return 0

        con.executemany(
            "UPDATE players SET position=?, position_group=? WHERE id=?", updates)
        con.commit()
        remaining = con.execute(
            "SELECT COUNT(*) FROM players WHERE league=? AND active=1 "
            "AND COALESCE(entity_type,'player')='player' "
            "AND (position IS NULL OR TRIM(position)='')", (LEAGUE,)).fetchone()[0]
        expected = len(blank) - len(updates)
        print("\nwrote {} rows".format(len(updates)))
        print("blank ACTIVE positions now: {} (expected {}){}".format(
            remaining, expected, "" if remaining == expected else "  <-- MISMATCH"))
        return 0 if remaining == expected else 2
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
