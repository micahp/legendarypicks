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

``--publish-membership`` adds the stricter current-roster contract. It requires every canonical
FBS team, every in-scope athlete ID exactly once, and a recognised position vocabulary before
one atomic identity + membership publication. The flag is deliberately absent from the
scheduled registry command: changing this file must not silently begin a new PROD write path.
"""
import argparse
import collections
import datetime as dt
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cfbd_shared import (
    _API,
    _get_json,
    _school_to_code,
    _season_from_the_schedule,
)
import team_codes
from roster_membership import (
    normalized_source_payload,
    publish_roster_snapshot,
    require_roster_schema,
)

LEAGUE = "ncaaf"
SOURCE = "cfbd"
SNAPSHOT_SOURCE = "cfbd:roster+espn:verified-identity"
EXPECTED_TEAM_CODES = frozenset(team_codes.CANONICAL[LEAGUE])
DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")


class NCAAFRosterError(RuntimeError):
    """The CFBD roster population cannot be safely published."""


# Verified 2026-10-02 against the live ESPN athlete/team rosters and both
# schools' official rosters. CFBD currently emits two copies of Georgia State
# CB Darius Johnson Jr.'s profile under Syracuse WR Darius Johnson's ESPN ID.
# It also emits the Georgia State player correctly under 5095071. Keep this
# correction fingerprint-exact so any upstream change requires revalidation.
_COLLIDED_2026_ID = "5212990"
_COLLIDED_2026_FINGERPRINTS = (
    (
        "Georgia State", "Darius", "Johnson", 180, 70, "12", 1, "CB",
        "Watkinsville", "GA", ("108016",),
    ),
    (
        "Syracuse", "Darius", "Johnson", 180, 70, "12", 1, "CB",
        "Watkinsville", "GA", ("108016",),
    ),
)
_GEORGIA_STATE_2026_OWNER = (
    "Georgia State", "Darius", "Johnson Jr.", 180, 70, "12", 4, "CB",
    "Watkinsville", "GA", ("256120",),
)


def _position_group(position):
    """The published position's group, or None. Never guessed."""
    try:
        from backfill_ncaaf_positions_cfbd import _position_group as group, _vocabulary
        return group(position, _vocabulary())
    except Exception:  # noqa: BLE001 - a missing group is a NULL, not a failed run
        return None


def _required_position_vocabulary():
    try:
        from backfill_ncaaf_positions_cfbd import _vocabulary
        vocabulary = _vocabulary()
    except Exception as exc:  # noqa: BLE001 - absence blocks publication
        raise NCAAFRosterError(
            "NCAAF position vocabulary could not be loaded: %s" % exc
        ) from exc
    if not vocabulary:
        raise NCAAFRosterError("NCAAF position vocabulary is missing")
    return vocabulary


def _normalized_position(value, vocabulary=None):
    """Return one committed position vocabulary, or fail before publication."""
    position = str(value or "").strip().upper()
    if not position or position == "?":
        return None, None
    # RotoWire says K while the committed ESPN vocabulary says PK. CFBD
    # currently publishes PK, but normalizing this common synonym at the
    # boundary keeps the membership contract usable by both prop sources.
    position = {"K": "PK"}.get(position, position)
    from backfill_ncaaf_positions_cfbd import _position_group as group
    vocabulary = vocabulary or _required_position_vocabulary()
    positions, _ancestry = vocabulary
    if position not in positions:
        raise NCAAFRosterError(
            "CFBD published unrecognised NCAAF position %r" % position
        )
    position_group = group(position, vocabulary)
    if not position_group:
        raise NCAAFRosterError(
            "NCAAF position %r has no published position group" % position
        )
    return position, position_group


def _roster_identity_fingerprint(row):
    recruit_ids = tuple(sorted(str(value) for value in (row.get("recruitIds") or [])))
    return (
        str(row.get("team") or "").strip(),
        str(row.get("firstName") or "").strip(),
        str(row.get("lastName") or "").strip(),
        row.get("weight"),
        row.get("height"),
        str(row.get("jersey") or "").strip(),
        row.get("year"),
        str(row.get("position") or "").strip().upper(),
        str(row.get("homeCity") or "").strip(),
        str(row.get("homeState") or "").strip(),
        recruit_ids,
    )


def _apply_verified_roster_corrections(rows):
    """Repair only the exact live CFBD identity collision verified by ESPN.

    ESPN's athlete 5212990 and Syracuse's official roster identify a sophomore
    WR wearing 6. ESPN and Georgia State identify the CB as athlete 5095071.
    Refuse if CFBD changes either fingerprint instead of extending a stale
    exception to a payload that has not been independently rechecked.
    """
    rows = list(rows or [])
    collided = [
        row for row in rows
        if str(row.get("id") or "").strip() == _COLLIDED_2026_ID
    ]
    if not collided:
        return rows, 0

    actual = tuple(sorted(_roster_identity_fingerprint(row) for row in collided))
    if actual != tuple(sorted(_COLLIDED_2026_FINGERPRINTS)):
        raise NCAAFRosterError(
            "CFBD athlete id 5212990 no longer matches the verified 2026 "
            "collision fingerprint; revalidate against ESPN and both schools"
        )

    georgia_state_owner = [
        row for row in rows
        if str(row.get("id") or "").strip() == "5095071"
    ]
    if (
        len(georgia_state_owner) != 1
        or _roster_identity_fingerprint(georgia_state_owner[0])
        != _GEORGIA_STATE_2026_OWNER
    ):
        raise NCAAFRosterError(
            "CFBD's verified Georgia State owner 5095071 is missing or changed"
        )

    corrected = [
        row for row in rows
        if str(row.get("id") or "").strip() != _COLLIDED_2026_ID
    ]
    corrected.append({
        "id": _COLLIDED_2026_ID,
        "firstName": "Darius",
        "lastName": "Johnson",
        "team": "Syracuse",
        "weight": 185,
        "height": 70,
        "jersey": 6,
        "year": 2,
        "position": "WR",
        "homeCity": "Carol City",
        "homeState": "FL",
        "recruitIds": [],
    })
    return corrected, len(collided)


_CLUBS_DDL = """
CREATE TABLE IF NOT EXISTS league_clubs (
    league     TEXT NOT NULL,
    name       TEXT NOT NULL,
    code       TEXT,
    source     TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (league, name)
);
"""


def _store_clubs(con, league, code_by_school, now):
    """Persist the publisher's club list so a checker never needs a request to know it.

    league_membership judges whether a fixture belongs to the league claiming it, and it runs
    inside a request handler, so it can only read what is already stored. Its club record was
    built from scoreboard snapshots and linked games, which is incomplete: three real NCAAF
    fixtures (Texas State @ Texas, Oklahoma State @ Tulsa, UNLV @ Hawaii) read as foreign
    purely because we had never recorded the opponent. The publisher hands us the whole list
    in the call this job already makes; throwing it away was the only reason the check had to
    be lenient.
    """
    con.executescript(_CLUBS_DDL)
    con.executemany(
        "INSERT INTO league_clubs(league,name,code,source,updated_at) VALUES(?,?,?,?,?) "
        "ON CONFLICT(league,name) DO UPDATE SET code=excluded.code, "
        "source=excluded.source, updated_at=excluded.updated_at",
        [(league, school, code, SOURCE, now) for school, code in code_by_school.items()])
    return len(code_by_school)


def _canonical_team_vocabulary(teams, expected_codes=None):
    """Return exactly one published school for every canonical FBS code.

    A direct canonical abbreviation outranks the display-name fallback. That
    prevents an FCS school whose short name prefixes an FBS display name from
    borrowing the FBS code (``Eastern`` -> EMU, ``San Diego`` -> SDSU).
    """
    expected = frozenset(expected_codes or EXPECTED_TEAM_CODES)
    direct = collections.defaultdict(list)
    fallback = collections.defaultdict(list)
    published = 0
    for row in teams or []:
        school = str(row.get("school") or "").strip()
        abbreviation = str(row.get("abbreviation") or "").strip().upper()
        if not school:
            continue
        published += 1
        if team_codes.is_canonical(LEAGUE, abbreviation):
            direct[abbreviation].append(school)
            continue
        code = _school_to_code(school, abbreviation)
        if code in expected:
            fallback[code].append(school)

    out = {}
    failures = []
    for code in sorted(expected):
        candidates = direct.get(code) or fallback.get(code) or []
        if len(candidates) != 1:
            failures.append("%s=%s" % (code, candidates or "missing"))
            continue
        out[candidates[0]] = code
    if failures:
        raise NCAAFRosterError(
            "CFBD team directory does not resolve exactly one school for all "
            "%d canonical FBS codes: %s" % (
                len(expected), ", ".join(failures[:10]))
        )
    if len(out) != len(expected) or set(out.values()) != set(expected):
        raise NCAAFRosterError(
            "CFBD team directory did not produce a one-to-one FBS vocabulary"
        )
    return published, out


def _team_vocabulary(season):
    """school -> canonical code, from the publisher's own team list. One request."""
    teams = _get_json("%s/teams?year=%d" % (_API, season))
    published, out = _canonical_team_vocabulary(teams)
    print("  /teams %d: %d published, %d canonical FBS teams"
          % (season, published, len(out)))
    return out


def _validated_rosters(rows, code_by_school, expected_codes=None):
    """Validate the complete in-scope source population without DB mutation."""
    expected = frozenset(expected_codes or EXPECTED_TEAM_CODES)
    if len(code_by_school) != len(expected) or set(code_by_school.values()) != set(expected):
        raise NCAAFRosterError(
            "team vocabulary has %d schools / %d codes; expected %d unique FBS teams"
            % (len(code_by_school), len(set(code_by_school.values())), len(expected))
        )

    rows, corrected_source_rows = _apply_verified_roster_corrections(rows)
    rosters = {code: [] for code in sorted(expected)}
    seen_source_ids = {}
    duplicate_conflicts = []
    skipped_out_of_scope = 0
    position_vocabulary = _required_position_vocabulary()
    for row in rows or []:
        school = str(row.get("team") or "").strip()
        team = code_by_school.get(school)
        if team is None:
            skipped_out_of_scope += 1
            continue
        source_key = str(row.get("id") or "").strip()
        name = " ".join(
            part for part in (
                str(row.get("firstName") or "").strip(),
                str(row.get("lastName") or "").strip(),
            ) if part
        )
        if not source_key or not name:
            raise NCAAFRosterError(
                "%s roster has incomplete member id=%r name=%r"
                % (team, source_key, name)
            )
        position, position_group = _normalized_position(
            row.get("position"), position_vocabulary
        )
        jersey = row.get("jersey")
        member = {
            "player_id": source_key,
            "name": name,
            "team": team,
            "position": position,
            "position_group": position_group,
            "jersey": None if jersey in (None, "") else str(jersey),
        }
        prior = seen_source_ids.get(source_key)
        if prior is not None:
            if prior == member:
                continue
            duplicate_conflicts.append(
                "%s:%s/%s" % (source_key, prior["team"], team)
            )
            continue
        seen_source_ids[source_key] = member
        rosters[team].append(member)

    if duplicate_conflicts:
        raise NCAAFRosterError(
            "CFBD FBS roster reuses athlete IDs across conflicting memberships: "
            + ", ".join(duplicate_conflicts[:10])
        )

    empty = sorted(team for team, members in rosters.items() if not members)
    if empty:
        raise NCAAFRosterError(
            "CFBD roster published no usable members for FBS teams: "
            + ", ".join(empty)
        )
    return rosters, skipped_out_of_scope, corrected_source_rows


def _publish_membership(con, season, rows, code_by_school, *, dry_run):
    """Plan and optionally atomically publish the canonical FBS membership."""
    require_roster_schema(con)
    rosters, skipped_out_of_scope, corrected_source_rows = _validated_rosters(
        rows, code_by_school
    )
    source_payload = normalized_source_payload(LEAGUE, rosters)

    by_source = collections.defaultdict(list)
    for player in con.execute(
        "SELECT id,espn_id,name,team,position,position_group "
        "FROM players WHERE league=? AND espn_id IS NOT NULL",
        (LEAGUE,),
    ):
        by_source[str(player["espn_id"])].append(player)

    planned = []
    for team in sorted(rosters):
        for member in rosters[team]:
            owners = by_source.get(member["player_id"], [])
            if len(owners) > 1:
                raise NCAAFRosterError(
                    "CFBD athlete id %s has multiple canonical owners"
                    % member["player_id"]
                )
            planned.append({
                **member,
                "action": "update" if owners else "insert",
                "canonical_player_id": int(owners[0]["id"]) if owners else None,
            })

    result = {
        "status": "ready" if dry_run else "publishing",
        "season": int(season),
        "teams": len(rosters),
        "players": len(planned),
        "inserted": sum(item["action"] == "insert" for item in planned),
        "matched": sum(item["action"] == "update" for item in planned),
        "skipped_out_of_scope": skipped_out_of_scope,
        "corrected_source_rows": corrected_source_rows,
        "snapshot_id": None,
    }
    if dry_run:
        return result

    captured_at = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        con.execute("BEGIN IMMEDIATE")
        memberships = []
        for item in planned:
            if item["action"] == "insert":
                cursor = con.execute(
                    "INSERT INTO players(name,team,league,espn_id,position,"
                    "position_group,active,updated_at) VALUES(?,?,?,?,?,?,1,?)",
                    (
                        item["name"], item["team"], LEAGUE,
                        item["player_id"], item["position"],
                        item["position_group"], captured_at,
                    ),
                )
                player_id = int(cursor.lastrowid)
            else:
                player_id = int(item["canonical_player_id"])
                con.execute(
                    "UPDATE players SET team=?,position=COALESCE(position,?),"
                    "position_group=COALESCE(position_group,?),active=1,updated_at=? "
                    "WHERE id=? AND league=?",
                    (
                        item["team"], item["position"], item["position_group"],
                        captured_at, player_id, LEAGUE,
                    ),
                )
            memberships.append({
                "player_id": player_id,
                "source_player_key": item["player_id"],
                "team": item["team"],
                "position": item["position"],
                "jersey": item["jersey"],
                "roster_status": "active",
                "display_name": item["name"],
            })

        snapshot_id = publish_roster_snapshot(
            con,
            league=LEAGUE,
            season=int(season),
            source=SNAPSHOT_SOURCE,
            captured_at=captured_at,
            source_payload=source_payload,
            team_count=len(rosters),
            memberships=memberships,
        )
        con.commit()
    except Exception:
        con.rollback()
        raise
    result["status"] = "published"
    result["snapshot_id"] = snapshot_id
    return result


def ingest(season=None, dry_run=False, publish_membership=False):
    season = season if season is not None else _season_from_the_schedule(DB)
    if season is None:
        raise SystemExit("no --season given and no NCAAF games in the database to read one from")
    print("NCAAF CFBD roster sync, season %s%s" % (season, " (dry run)" if dry_run else ""))

    # The snapshot schema is an explicit migration. Refuse before spending the
    # two source requests when the target database cannot honor the contract.
    if publish_membership:
        preflight = sqlite3.connect(DB, timeout=30)
        try:
            require_roster_schema(preflight)
        finally:
            preflight.close()

    code_by_school = _team_vocabulary(season)
    rows = _get_json("%s/roster?year=%d" % (_API, season)) or []
    print("  /roster %d: %d published rows (ONE request; the ESPN path costs 149)"
          % (season, len(rows)))

    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    if publish_membership:
        try:
            result = _publish_membership(
                con, season, rows, code_by_school, dry_run=dry_run
            )
        finally:
            con.close()
        print("  membership: status=%(status)s teams=%(teams)d players=%(players)d "
              "matched=%(matched)d inserted=%(inserted)d "
              "skipped_out_of_scope=%(skipped_out_of_scope)d "
              "corrected_source_rows=%(corrected_source_rows)d" % result)
        if result["snapshot_id"] is not None:
            print("  roster snapshot: %d" % result["snapshot_id"])
        print("  ESPN requests spent: 0")
        return result

    spine = {
        str(r["espn_id"]): r for r in con.execute(
            "SELECT id, espn_id, name, team, position, position_group FROM players "
            "WHERE league=? AND espn_id IS NOT NULL", (LEAGUE,))
    }
    print("  spine before: %d players with an espn_id" % len(spine))

    counts = dict(inserted=0, updated=0, unchanged=0, no_team_code=0,
                  no_athlete_id=0, no_name=0)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    if not dry_run:
        print("  league_clubs: stored %d published %s schools"
              % (_store_clubs(con, LEAGUE, code_by_school, now), LEAGUE))
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
    parser.add_argument(
        "--publish-membership", action="store_true",
        help="publish an atomic FBS roster snapshot (opt-in; registry omits it)",
    )
    args = parser.parse_args(argv)
    ingest(
        args.season,
        dry_run=args.dry_run,
        publish_membership=args.publish_membership,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
