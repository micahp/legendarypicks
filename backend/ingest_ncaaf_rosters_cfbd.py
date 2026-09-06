#!/usr/bin/env python3
"""ingest_ncaaf_rosters_cfbd.py: the NCAAF identity spine, from CFBD, in two requests.

WHY THIS EXISTS.

`ingest_mls_ncaaf_rosters.py` builds this same spine from ESPN and prices itself in its own
docstring: 1 `/teams` call plus 2 group-80 pages plus **146 per-team roster calls**, so 149
requests to `site.web.api.espn.com` for one NCAAF sync. ESPN's limit is a burst rate per host
shared with the serving path, and that host is the constraint behind nearly every design
decision in this repo: the pacing in `settle_props`, the `--request-budget` in
`ingest_soccer_logs`, the `host_lock` in `ingest_registry`.

CFBD publishes the whole thing in ONE request. Measured 2026-09-06: `/roster?year=2026`
returns **30,635 rows** carrying `id, firstName, lastName, team, position, jersey, year`.
One more call to `/teams?year=` supplies the school-to-code vocabulary. Two requests, on a
publisher we already depend on for the game logs, against zero ESPN budget.

The join key is not a name. CFBD's athlete `id` IS the ESPN athlete id, which is what
`players.espn_id` already holds and what `ingest_cfbd_logs` already resolves on. So this is a
copy keyed on the publisher's own identifier, not a name match. That matters: repairing
identity by name is how MLB rows ended up carrying a pitcher's name.

WHAT IT WILL NOT DO. It never deletes, never deactivates, and never invents a team code. A
school whose code cannot be resolved is COUNTED and SKIPPED, not minted under a guess: a
wrong team code does not raise, it silently misses, and 178 players once disappeared that way
for months.
"""
import argparse
import datetime as dt
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import team_codes
from ingest_cfbd_logs import (
    _API,
    _get_json,
    _school_to_code,
    _season_from_the_schedule,
)

LEAGUE = "ncaaf"
DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")


def _position_group(position):
    """The published position's group, or None. Never guessed."""
    try:
        from backfill_ncaaf_positions_cfbd import _position_group as group, _vocabulary
        return group(position, _vocabulary())
    except Exception:  # noqa: BLE001 - a missing group is a NULL, not a failed run
        return None


def _team_vocabulary(season):
    """school -> canonical code, from the publisher's own team list. One request."""
    teams = _get_json("%s/teams?year=%d" % (_API, season))
    abbrev_by_school = {
        (t.get("school") or "").strip(): (t.get("abbreviation") or "").strip().upper()
        for t in teams or [] if (t.get("school") or "").strip()
    }
    out = {}
    for school, abbrev in abbrev_by_school.items():
        code = _school_to_code(school, abbrev)
        if code:
            out[school] = code
    print("  /teams %d: %d published, %d resolved to canonical codes"
          % (season, len(abbrev_by_school), len(out)))
    return out


def ingest(season=None, dry_run=False):
    season = season if season is not None else _season_from_the_schedule(DB)
    if season is None:
        raise SystemExit("no --season given and no NCAAF games in the database to read one from")
    print("NCAAF CFBD roster sync, season %s%s" % (season, " (dry run)" if dry_run else ""))

    code_by_school = _team_vocabulary(season)
    rows = _get_json("%s/roster?year=%d" % (_API, season)) or []
    print("  /roster %d: %d published rows (ONE request; the ESPN path costs 149)"
          % (season, len(rows)))

    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    spine = {
        str(r["espn_id"]): r for r in con.execute(
            "SELECT id, espn_id, name, team, position, position_group FROM players "
            "WHERE league=? AND espn_id IS NOT NULL", (LEAGUE,))
    }
    print("  spine before: %d players with an espn_id" % len(spine))

    counts = dict(inserted=0, updated=0, unchanged=0, no_team_code=0,
                  no_athlete_id=0, no_name=0)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for row in rows:
        athlete_id = str(row.get("id") or "").strip()
        if not athlete_id:
            counts["no_athlete_id"] += 1
            continue
        name = " ".join(part for part in ((row.get("firstName") or "").strip(),
                                          (row.get("lastName") or "").strip()) if part)
        if not name:
            counts["no_name"] += 1
            continue
        school = (row.get("team") or "").strip()
        code = code_by_school.get(school)
        if not code:
            # Almost all of these are FCS schools CFBD carries for buy games. Counted, not
            # minted: a player filed under a guessed code joins to nothing and looks fine.
            counts["no_team_code"] += 1
            continue
        position = (row.get("position") or "").strip()
        if position == "?":
            # CFBD writes "?" for unknown. Storing it is worse than NULL: it looks like a
            # value and no vocabulary contains it.
            position = ""

        existing = spine.get(athlete_id)
        if existing is None:
            if not dry_run:
                con.execute(
                    "INSERT INTO players(name, team, league, espn_id, position, "
                    "position_group, active, updated_at) VALUES(?,?,?,?,?,?,1,?)",
                    (name, code, LEAGUE, athlete_id, position or None,
                     _position_group(position) if position else None, now))
            counts["inserted"] += 1
            continue

        # Existing identity wins on NAME. The publisher may spell it differently and this
        # sync is not the place to relitigate who someone is; team and position are the
        # facts that legitimately change during a season.
        changes = {}
        if code != (existing["team"] or ""):
            changes["team"] = code
        # Position is FILLED, never overwritten. CFBD's position vocabulary is not ESPN's,
        # and the existing value came from ESPN: the dry run wanted DE->DL, LB->EDGE and
        # PK->P, which are a different publisher's words for the same player, not news about
        # him. PK->P would have turned a placekicker into a punter. Two vocabularies in one
        # column is the defect; a blank we can fill is the opportunity.
        if position and not (existing["position"] or ""):
            changes["position"] = position
            changes["position_group"] = _position_group(position)
        if not changes:
            counts["unchanged"] += 1
            continue
        if not dry_run:
            sets = ", ".join("%s=?" % k for k in changes) + ", updated_at=?"
            con.execute("UPDATE players SET %s WHERE id=?" % sets,
                        tuple(changes.values()) + (now, existing["id"]))
        counts["updated"] += 1

    if not dry_run:
        con.commit()
    after = con.execute(
        "SELECT COUNT(*) FROM players WHERE league=? AND espn_id IS NOT NULL",
        (LEAGUE,)).fetchone()[0]
    con.close()

    # Say the zero: every bucket prints even at 0, so "clean" is distinguishable from
    # "never ran". Both requests are named so the ESPN saving is auditable, not claimed.
    print("  inserted=%(inserted)d updated=%(updated)d unchanged=%(unchanged)d" % counts)
    print("  skipped: no_team_code=%(no_team_code)d no_athlete_id=%(no_athlete_id)d "
          "no_name=%(no_name)d" % counts)
    print("  spine after: %d players%s" % (after, " (dry run: unchanged)" if dry_run else ""))
    print("  ESPN requests spent: 0")
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--season", type=int,
                        help="season year. Default: the season of the newest NCAAF game "
                             "already scheduled in the database.")
    parser.add_argument("--dry-run", action="store_true",
                        help="fetch and resolve but write nothing")
    args = parser.parse_args(argv)
    ingest(args.season, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
