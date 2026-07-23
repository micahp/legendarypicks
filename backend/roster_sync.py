#!/usr/bin/env python3
"""
roster_sync.py — ensure every CURRENTLY-ROSTERED player exists in `players`, with
espn_id / team / position populated, and the `active` flag reflecting current rosters.

Why: the per-game-log ingests only resolve players who appeared in a game. Bench /
injured / just-signed players never log a row, so the roster is incomplete and the
`active` flag is stale (it was effectively "ever seen" = always 1). This walks every
team's ESPN roster, matches to existing players by normalized name (to avoid
duplicates), upserts, and rebuilds `active` per league.

Usage: python3 roster_sync.py [nfl nba nhl mlb]   (default: all four)
"""
import datetime as dt
import sys, os, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import espn_client as espn
from sports_service import _normalize_name

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
_EXPECTED_TEAM_COUNTS = {"nfl": 32, "nba": 30, "nhl": 32, "mlb": 30}


def sync_league(con: sqlite3.Connection, league: str) -> dict:
    teams = list(dict.fromkeys(
        t.get("abbrev") for t in espn.team_strength(league) if t.get("abbrev")
    ))
    expected_teams = _EXPECTED_TEAM_COUNTS.get(league, len(teams))
    if not teams or len(teams) != expected_teams:
        active_now = con.execute(
            "SELECT COUNT(*) FROM players WHERE league=? AND active=1", (league,)
        ).fetchone()[0]
        return {
            "status": "incomplete",
            "teams": len(teams),
            "expected_teams": expected_teams,
            "matched": 0,
            "inserted": 0,
            "espn_id_filled": 0,
            "active_now": active_now,
            "verified_at": None,
            "failures": [{
                "team": None,
                "reason": f"expected {expected_teams} teams, got {len(teams)}",
            }],
        }
    # Fetch the complete population before mutating active flags. A partial
    # upstream response must not deactivate an entire missing team's roster or
    # stamp the league as freshly verified.
    rosters = {}
    failures = []
    for abbr in teams:
        try:
            roster = espn.roster(league, abbr)
        except Exception as exc:
            failures.append({"team": abbr, "reason": str(exc)})
            continue
        if not roster:
            failures.append({"team": abbr, "reason": "empty roster"})
            continue
        rosters[abbr] = roster

    if failures or len(rosters) != expected_teams:
        active_now = con.execute(
            "SELECT COUNT(*) FROM players WHERE league=? AND active=1", (league,)
        ).fetchone()[0]
        return {
            "status": "incomplete",
            "teams": len(rosters),
            "expected_teams": expected_teams,
            "matched": 0,
            "inserted": 0,
            "espn_id_filled": 0,
            "active_now": active_now,
            "verified_at": None,
            "failures": failures,
        }

    # Existing players in this league: index by espn_id (authoritative) and by name_norm.
    name_to_id = {}
    eid_to_id = {}
    for r in con.execute("SELECT id, name, espn_id FROM players WHERE league=?", (league,)):
        if r["name"]:
            name_to_id.setdefault(_normalize_name(r["name"]), r["id"])
        if r["espn_id"]:
            eid_to_id[str(r["espn_id"])] = r["id"]

    verified_at = dt.datetime.now(dt.timezone.utc).isoformat()
    # Reset active only after every team supplied a non-empty roster. Rostered
    # players get re-activated below with the same verification timestamp.
    con.execute(
        "UPDATE players SET active=0, updated_at=? WHERE league=?",
        (verified_at, league),
    )

    matched = inserted = updated_espn = 0
    seen_teams = 0
    for abbr, roster in rosters.items():
        seen_teams += 1
        for p in roster:
            name = p.get("name")
            if not name:
                continue
            eid = str(p.get("player_id")) if p.get("player_id") else None
            pos = p.get("position")
            nn = _normalize_name(name)
            # Resolve by espn_id first (authoritative), then by normalized name.
            pid = (eid_to_id.get(eid) if eid else None) or name_to_id.get(nn)
            if pid:
                con.execute(
                    """UPDATE players SET active=1, team=?, position=COALESCE(?, position),
                         espn_id=COALESCE(espn_id, ?), updated_at=? WHERE id=?""",
                    (abbr, pos, eid, verified_at, pid))
                matched += 1
                if eid:
                    updated_espn += 1
            else:
                cur = con.execute(
                    """INSERT INTO players
                       (name, league, team, position, espn_id, active, updated_at)
                       VALUES (?,?,?,?,?,1,?)""",
                    (name, league, abbr, pos, eid, verified_at))
                name_to_id[nn] = cur.lastrowid
                if eid:
                    eid_to_id[eid] = cur.lastrowid
                inserted += 1
    con.commit()
    active_now = con.execute("SELECT COUNT(*) FROM players WHERE league=? AND active=1", (league,)).fetchone()[0]
    return {"status": "complete", "teams": seen_teams, "expected_teams": expected_teams,
            "matched": matched, "inserted": inserted,
            "espn_id_filled": updated_espn, "active_now": active_now,
            "verified_at": verified_at, "failures": []}


def main(leagues):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    for lg in leagues:
        print(f"Syncing {lg} rosters...")
        s = sync_league(con, lg)
        print(f"  {lg}: {s['status']} | {s['teams']}/{s['expected_teams']} teams "
              f"| matched {s['matched']} | inserted {s['inserted']} new "
              f"| espn_id filled {s['espn_id_filled']} | now {s['active_now']} active")
        if s["failures"]:
            print(f"    NOT APPLIED — incomplete roster population: {s['failures']}")
    con.close()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a in ("nfl", "nba", "nhl", "mlb")]
    main(args or ["nfl", "nba", "nhl", "mlb"])
