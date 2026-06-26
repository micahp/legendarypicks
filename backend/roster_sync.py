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
import sys, os, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import espn_client as espn
from sports_service import _normalize_name

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")


def sync_league(con: sqlite3.Connection, league: str) -> dict:
    teams = [t["abbrev"] for t in espn.team_strength(league)]
    # Existing players in this league: index by espn_id (authoritative) and by name_norm.
    name_to_id = {}
    eid_to_id = {}
    for r in con.execute("SELECT id, name, espn_id FROM players WHERE league=?", (league,)):
        if r["name"]:
            name_to_id.setdefault(_normalize_name(r["name"]), r["id"])
        if r["espn_id"]:
            eid_to_id[str(r["espn_id"])] = r["id"]

    # Reset active for this league; rostered players get re-activated below.
    con.execute("UPDATE players SET active=0 WHERE league=?", (league,))

    matched = inserted = updated_espn = 0
    seen_teams = 0
    for abbr in teams:
        try:
            roster = espn.roster(league, abbr)
        except Exception:
            continue
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
                         espn_id=COALESCE(espn_id, ?) WHERE id=?""",
                    (abbr, pos, eid, pid))
                matched += 1
                if eid:
                    updated_espn += 1
            else:
                cur = con.execute(
                    "INSERT INTO players(name, league, team, position, espn_id, active) VALUES (?,?,?,?,?,1)",
                    (name, league, abbr, pos, eid))
                name_to_id[nn] = cur.lastrowid
                if eid:
                    eid_to_id[eid] = cur.lastrowid
                inserted += 1
    con.commit()
    active_now = con.execute("SELECT COUNT(*) FROM players WHERE league=? AND active=1", (league,)).fetchone()[0]
    return {"teams": seen_teams, "matched": matched, "inserted": inserted,
            "espn_id_filled": updated_espn, "active_now": active_now}


def main(leagues):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    for lg in leagues:
        print(f"Syncing {lg} rosters...")
        s = sync_league(con, lg)
        print(f"  {lg}: {s['teams']} teams | matched {s['matched']} | inserted {s['inserted']} new "
              f"| espn_id filled {s['espn_id_filled']} | now {s['active_now']} active")
    con.close()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a in ("nfl", "nba", "nhl", "mlb")]
    main(args or ["nfl", "nba", "nhl", "mlb"])
