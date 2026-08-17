#!/usr/bin/env python3
"""Fill NCAAF `players.position` from CFBD's published roster.

`ingest_cfbd_logs.py` mints a spine row for every athlete it sees in a game log
and writes `position NULL, position_group NULL, active 1`, with the comment
"NULL for the roster sync to backfill". The roster sync is
`ingest_mls_ncaaf_rosters.py`, which reads ESPN's published team rosters -- and
those athletes are not on them. Measured 2026-08-16 on the dev DB: re-running
the roster sync moved 5,897 blanks to 5,853. The backfill the comment promises
has never happened, so 27% of ACTIVE ncaaf players carry no position, which is
what `C/vocabulary[position]` reports the moment the overlap ahead of it is
resolved.

CFBD publishes the value and we already ingest CFBD (published-first rung 2:
one more column beats one more derivation). `/roster?year=` returns the whole
year in ONE request -- 30,072 rows across 315 teams, 1.6s -- keyed by `id`,
which is the same ESPN athlete id `players.espn_id` already holds. No name
matching is involved anywhere in this script, by construction.

`position_group` is recomputed from the committed ESPN ancestry artifact
(`data/position-vocabulary.json`), the same root-walk `ingest_mls_ncaaf_rosters`
uses, so both columns stay one vocabulary.

CFBD publishes `?` for an athlete whose position it does not know. That is a
published *absence* and is never written -- a blank stays blank rather than
becoming a fake label.

Usage:
  cd backend && venv/bin/python backfill_ncaaf_positions_cfbd.py \\
      --db /abs/path/picks.db [--years 2025,2026] [--apply]

Dry run by default. Idempotent: only rows whose position is currently blank are
considered, and only rows whose value would change are written.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.request

LEAGUE = "ncaaf"
API = "https://api.collegefootballdata.com/roster?year={year}"
_VOCABULARY_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "position-vocabulary.json")
# CFBD's own marker for "we do not know this athlete's position".
_UNKNOWN_POSITION = "?"


def _api_key() -> str:
    key = os.environ.get("CFBD_API_KEY")
    if key:
        return key
    path = os.path.expanduser("~/.hermes/.env")
    try:
        for line in open(path):
            if line.startswith("CFBD_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    raise RuntimeError("CFBD_API_KEY not found (env or ~/.hermes/.env)")


def _vocabulary():
    """{positions, ancestry} as ESPN published them, or None if not on disk."""
    try:
        with open(_VOCABULARY_PATH) as f:
            artifact = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    entry = (artifact.get("leagues") or {}).get(LEAGUE)
    if not entry:
        return None
    return entry.get("positions", {}), entry.get("ancestry", {})


def _position_group(position, vocab):
    """The terminal parent of `position`, mapped to its published name."""
    if not position:
        return None
    positions, ancestry = vocab
    chain = ancestry.get(position) or []
    root = chain[-1] if chain else position
    info = positions.get(root) or {}
    return info.get("name") or info.get("displayName") or root


def fetch_roster(year: int, key: str) -> list:
    request = urllib.request.Request(
        API.format(year=year),
        headers={"Authorization": "Bearer " + key, "User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode())


def published_positions(years, key) -> dict:
    """{espn_athlete_id: position} across the requested years, newest wins."""
    out = {}
    for year in years:
        rows = fetch_roster(year, key)
        usable = 0
        for row in rows:
            athlete_id, position = row.get("id"), row.get("position")
            if not athlete_id or not position or position == _UNKNOWN_POSITION:
                continue
            out[str(athlete_id)] = position
            usable += 1
        print("  CFBD {}: {} roster rows, {} carry a published position"
              .format(year, len(rows), usable))
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--years", default="2025,2026")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--deactivate-unrostered", action="store_true",
                        help="mark blank-position players inactive when NO publisher "
                             "rosters them; never writes a position")
    args = parser.parse_args(argv)

    vocab = _vocabulary()
    if not vocab:
        print("FAIL: no published position vocabulary on disk -- run "
              "fetch_position_vocabulary.py. Refusing to invent a group.")
        return 2

    years = [int(y) for y in args.years.split(",") if y.strip()]
    print("database: {}".format(args.db))
    published = published_positions(years, _api_key())
    if not published:
        print("FAIL: CFBD published no usable positions for {}.".format(years))
        return 2

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    try:
        blank = con.execute(
            "SELECT id, espn_id FROM players WHERE league=? AND active=1 "
            "AND COALESCE(entity_type,'player')='player' "
            "AND (position IS NULL OR TRIM(position)='') AND espn_id IS NOT NULL",
            (LEAGUE,)).fetchall()
        updates, unknown_position, rejected = [], [], 0
        for row in blank:
            position = published.get(str(row["espn_id"]))
            if not position:
                rejected += 1
                continue
            group = _position_group(position, vocab)
            if position not in vocab[0]:
                # Writing a code ESPN never published would trade a blank for a
                # vocabulary violation. Report it; never write it.
                unknown_position.append(position)
                continue
            updates.append((position, group, row["id"]))

        print("blank-position ACTIVE {} players: {}".format(LEAGUE, len(blank)))
        print("  CFBD can label:   {}".format(len(updates)))
        print("  CFBD cannot:      {} (on no roster CFBD publishes)".format(rejected))
        if unknown_position:
            print("  REJECTED {} rows: CFBD position not in ESPN's published "
                  "vocabulary: {}".format(len(unknown_position),
                                          sorted(set(unknown_position))))
        # A row CFBD cannot label is not necessarily a defect. These athletes exist because
        # they appeared in ONE game log; `ingest_cfbd_logs` then minted them `active=1`,
        # which was an assumption rather than a measurement. When neither publisher rosters
        # somebody -- ESPN's team rosters do not list them and CFBD's own roster (tens of
        # thousands of rows per year) does not either -- the false claim is `active`, not the
        # blank position. A position is a CURRENT roster spot, which is exactly why the
        # audit scopes its blank check to active players.
        #
        # So this corrects the flag we asserted without evidence, and never invents a
        # position. Opt-in, because deactivating a player is not a side effect anyone should
        # get from a script whose name says "backfill positions".
        unrostered = [row["id"] for row in blank
                      if not published.get(str(row["espn_id"]))]
        if args.deactivate_unrostered and unrostered:
            print("  --deactivate-unrostered: {} players on NO roster either publisher "
                  "publishes will be marked inactive (their blank position stays blank -- "
                  "it is the honest value)".format(len(unrostered)))

        if not updates and not (args.deactivate_unrostered and unrostered):
            print("FAIL: {} blank rows and CFBD labelled none of them."
                  .format(len(blank)))
            return 2

        if not args.apply:
            print("\ndry run -- nothing written. re-run with --apply")
            return 0

        if args.deactivate_unrostered and unrostered:
            con.executemany("UPDATE players SET active=0 WHERE id=?",
                            [(i,) for i in unrostered])
            print("  marked {} unrostered players inactive".format(len(unrostered)))

        con.executemany(
            "UPDATE players SET position=?, position_group=? WHERE id=?", updates)
        con.commit()
        remaining = con.execute(
            "SELECT COUNT(*) FROM players WHERE league=? AND active=1 "
            "AND COALESCE(entity_type,'player')='player' "
            "AND (position IS NULL OR TRIM(position)='')", (LEAGUE,)).fetchone()[0]
        # Reconcile rather than trust the write: the count that matters is the
        # one the gate reads, not the one we intended.
        # Deactivated rows leave the ACTIVE population too, so they come out of the
        # expectation as well. Leaving them in made a correct run report MISMATCH and exit 2 --
        # a reconciliation that cries wolf is one people stop reading.
        deactivated = len(unrostered) if (args.deactivate_unrostered and unrostered) else 0
        expected = len(blank) - len(updates) - deactivated
        print("\nwrote {} rows".format(len(updates)))
        print("blank ACTIVE positions now: {} (expected {}){}".format(
            remaining, expected,
            "" if remaining == expected else "  <-- MISMATCH"))
        return 0 if remaining == expected else 2
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
