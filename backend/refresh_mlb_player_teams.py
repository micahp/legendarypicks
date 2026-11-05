#!/usr/bin/env python3
"""refresh_mlb_player_teams.py — copy each MLB player's team and position from
the publisher instead of trusting whatever our ingest last wrote.

WHY THIS EXISTS
---------------
`players.team` for MLB is wrong often enough that it cannot be used as evidence.
Found 2026-08-11 while deduplicating: where one person had two rows, the two
rows frequently disagreed about the club, and the publisher sided with the newer
one.

    Marcell Ozuna    ours(id 26934)=LAD  ours(id 29878)=PIT  statsapi=Pittsburgh
    Randal Grichuk   ours(id 26937)=ATL  ours(id 29870)=CHW  statsapi=White Sox
    Jackson Holliday ours(id 26571)=SD   ours(id 32176)=BAL  statsapi=Baltimore

Holliday and Jackson Merrill held each other's clubs, which is the signature of
an identity repair done by name match rather than by id — see
project_lp_mlb_pitcher_name_corruption.

A team is a DEFINITION, not a computation: statsapi publishes it per `mlbam_id`,
so it is copied, never inferred (published-first §2, rung 5). This script exists
separately from `dedupe_mlb.py` because merging two rows and refreshing a row's
attributes are different jobs; the dedupe should not silently rewrite teams, and
this should be re-runnable on its own after any roster move.

TWO BOUNDARIES, BOTH HANDLED HERE AND NOWHERE ELSE
--------------------------------------------------
**Vocabulary.** statsapi says `AZ` and `CWS`; this repo says `ARI` and `CHW`.
Converted once, at ingest, per published-first §5 — never by a reader.

**"Current team" is not always an MLB club.** 26 of 125 players checked had a
`currentTeam` in the minors (Sugar Land Skeeters, El Paso Chihuahuas) or, for a
retired man sharing a name, a club that folded in 1952. The publisher is
answering "where does this person play", which is a different question from
"which MLB club does this row represent". Those rows are LEFT ALONE and counted
in the output rather than being overwritten with a Triple-A affiliate.

Usage:
  LP_DB_PATH=data/picks.dev.db python3 refresh_mlb_player_teams.py [--apply]

Default is a dry run. Takes its own backup before writing.
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import urllib.request

STATSAPI = "https://statsapi.mlb.com/api/v1"

# statsapi -> this repo's vocabulary. The only place this conversion happens.
TEAM_FIX = {"AZ": "ARI", "CWS": "CHW"}


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def mlb_team_abbrevs():
    """{team_id: abbrev} for the 30 MLB clubs. Anything absent is not MLB."""
    return {t["id"]: t.get("abbreviation")
            for t in _get("%s/teams?sportId=1" % STATSAPI).get("teams", [])}


def published_people(mlbam_ids, teams):
    """{mlbam_id: {team, team_name, pos, active}}, 40 ids per request.

    statsapi is a different publisher from ESPN with no comparable per-host
    ceiling, so this is not subject to the espn-request-budget wall. It is still
    one bulk request per 40 players rather than one per player — the count is
    printed so the job can be sized later.
    """
    out = {}
    ids = sorted(mlbam_ids)
    print("statsapi lookups : %d ids in %d requests"
          % (len(ids), (len(ids) + 39) // 40))
    for i in range(0, len(ids), 40):
        chunk = ids[i:i + 40]
        d = _get("%s/people?personIds=%s&hydrate=currentTeam"
                 % (STATSAPI, ",".join(map(str, chunk))))
        for p in d.get("people", []):
            ct = p.get("currentTeam") or {}
            abbr = teams.get(ct.get("id"))          # None => not an MLB club
            out[p["id"]] = {"team": TEAM_FIX.get(abbr, abbr),
                            "team_name": ct.get("name"),
                            "pos": (p.get("primaryPosition") or {}).get("abbreviation"),
                            "active": p.get("active")}
    return out


def plan_changes(rows, pub):
    """(changes, minors, inactive, unknown) — pure, so it is testable offline.

    The `inactive` bucket is a SAFETY GATE, not a nicety. This script trusts
    `players.mlbam_id`, and some rows carry the id of a different man with the
    same name:

        players.id=12  Joe Mack      mlbam 118086 -> Boston Braves, debut 1945
        players.id=94  Jacob Wilson  mlbam 607111 -> inactive, wrong man

    statsapi resolves 118086's club to the modern Atlanta franchise, so applying
    it would stamp `ATL` onto a Marlins prospect and make a bad identity look
    freshly published. Both bad rows share one signal — the publisher says
    `active: false` — so a retired or non-roster player never rewrites a row that
    our own data says is on an MLB club today. Re-identification is a separate
    job (see the REFUSED list in dedupe_mlb.py's output); this one must not
    quietly do it.
    """
    changes, minors, inactive, unknown = [], [], [], []
    for r in rows:
        p = pub.get(r["mlbam_id"])
        if not p:
            unknown.append(r)
            continue
        if not p["team"]:
            minors.append((r, p))
            continue
        if p.get("active") is False:
            inactive.append((r, p))
            continue
        if (p["team"] or "") != (r["team"] or ""):
            changes.append((r, p))
    return changes, minors, inactive, unknown


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    db = os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    rows = [dict(r) for r in con.execute(
        """SELECT id, name, team, position, mlbam_id FROM players
           WHERE league='mlb' AND mlbam_id IS NOT NULL AND mlbam_id != 0""")]
    print("mlb rows with an mlbam_id: %d" % len(rows))

    teams = mlb_team_abbrevs()
    pub = published_people({r["mlbam_id"] for r in rows}, teams)
    changes, minors, inactive, unknown = plan_changes(rows, pub)

    print("\nteam DISAGREES with publisher : %d" % len(changes))
    print("publisher says minors/other    : %d (left alone)" % len(minors))
    print("publisher says INACTIVE        : %d (left alone — likely a wrong mlbam_id)"
          % len(inactive))
    for r, p in inactive[:6]:
        print("   SKIP id=%-6s %-24s ours=%-4s publisher=%s (%s)"
              % (r["id"], r["name"], r["team"], p["team"], p["team_name"]))
    print("not returned by publisher      : %d (left alone)" % len(unknown))
    for r, p in changes[:20]:
        print("   id=%-6s %-24s %-4s -> %-4s  (%s)"
              % (r["id"], r["name"], r["team"], p["team"], p["team_name"]))
    if len(changes) > 20:
        print("   ... and %d more" % (len(changes) - 20))

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")
        return
    if not changes:
        print("\nNothing to write.")
        return

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bak = "%s.pre-teamrefresh-%s.bak" % (db, stamp)
    con.execute("VACUUM INTO ?", (bak,))
    chk = sqlite3.connect(bak).execute("PRAGMA quick_check").fetchone()[0]
    print("\nbackup: %s (quick_check: %s)" % (bak, chk))
    if chk != "ok":
        sys.exit("backup failed integrity check — refusing to write")

    for r, p in changes:
        con.execute("UPDATE players SET team=? WHERE id=?", (p["team"], r["id"]))
        if p["pos"]:
            con.execute("UPDATE players SET position=? WHERE id=?", (p["pos"], r["id"]))
    con.commit()
    print("updated %d rows from the publisher" % len(changes))


if __name__ == "__main__":
    main()
