"""build_nfl_starters_snapshot.py -- full starting units for one NFL game, from the nflverse depth chart.

The published depth chart is the only roster source here. ingest_nfl_depth_charts.py keeps offensive skill
positions because the draft board asks only about those. A simulated game needs the whole starting unit, so this
builder reads every position group and picks the starters by a fixed football rule:

  offense, 11 personnel: QB1, RB1, TE1, WR1-WR3, LT, LG, C, RG, RT
  defense, by base front: four front players, three linebackers, two corners, two safeties
  special teams: K, P, LS, H, KR, PR (rank 1)

It never fills a missing slot with another position. A team with an unfilled starter gets a row in "missing"
so the gap is visible instead of silently patched.
"""
import argparse
import datetime
import json
import os
import sqlite3

import pyarrow.parquet as pq

OFFENSE_GROUP = "3WR 1TE"
OFFENSE_SLOTS = [("QB", 1), ("RB", 1), ("TE", 1), ("WR", 3), ("LT", 1), ("LG", 1), ("C", 1), ("RG", 1), ("RT", 1)]
DEFENSE_SLOTS = {
    "Base 4-3 D": [("LDE", 1), ("LDT", 1), ("RDT", 1), ("RDE", 1), ("MLB", 1), ("WLB", 1), ("SLB", 1),
                   ("LCB", 1), ("RCB", 1), ("FS", 1), ("SS", 1)],
    "Base 3-4 D": [("LDE", 1), ("NT", 1), ("RDE", 1), ("LILB", 1), ("RILB", 1), ("SLB", 1), ("WLB", 1),
                   ("LCB", 1), ("RCB", 1), ("FS", 1), ("SS", 1)],
}
SPECIAL_TEAMS = [("PK", 1), ("P", 1), ("LS", 1), ("H", 1), ("KR", 1), ("PR", 1)]
NEEDED = ["dt", "team", "player_name", "gsis_id", "pos_grp", "pos_abb", "pos_rank"]
SOURCE = "nflverse_depth_charts"
ROSTER_SOURCE = "nflverse_rosters"


def latest_dt(table, team):
    dts = sorted({str(d) for d, t in zip(table["dt"], table["team"]) if t == team})
    if not dts:
        raise ValueError("no depth chart rows for {}".format(team))
    return dts[-1]


def rows_for(table, team, dt):
    out = []
    for i in range(len(table["dt"])):
        if table["team"][i] == team and str(table["dt"][i]) == dt:
            out.append({k: table[k][i] for k in NEEDED})
    return out


def pick(rows, group, slots):
    """Return (starters, missing) for one group. A slot is filled only by its own abbreviation, by rank."""
    starters, missing = [], []
    for abb, count in slots:
        candidates = sorted(
            (r for r in rows if r["pos_grp"] == group and (r["pos_abb"] or "").strip().upper() == abb and r["pos_rank"] is not None),
            key=lambda r: int(r["pos_rank"]))
        seen = set()
        taken = 0
        for r in candidates:
            gsis = (r["gsis_id"] or "").strip()
            if not gsis or gsis in seen:
                continue
            seen.add(gsis)
            starters.append({"pos_abb": abb, "pos_rank": int(r["pos_rank"]), "group": group,
                             "gsis_id": gsis, "player_name": r["player_name"]})
            taken += 1
            if taken == count:
                break
        if taken < count:
            missing.append({"pos_abb": abb, "needed": count, "found": taken, "group": group})
    return starters, missing


def build_team(table, team, dt, snapshot_at, player_ids):
    rows = rows_for(table, team, dt)
    groups = {r["pos_grp"] for r in rows}
    offense, miss_o = pick(rows, OFFENSE_GROUP, OFFENSE_SLOTS) if OFFENSE_GROUP in groups else ([], [{"group": OFFENSE_GROUP, "missing_group": True}])
    defense_group = next((g for g in DEFENSE_SLOTS if g in groups), None)
    if defense_group:
        defense, miss_d = pick(rows, defense_group, DEFENSE_SLOTS[defense_group])
    else:
        defense, miss_d = [], [{"missing_group": "defense"}]
    special, miss_s = pick(rows, "Special Teams", SPECIAL_TEAMS)
    players = []
    for p in offense + defense + special:
        players.append({
            "gsis_id": p["gsis_id"], "player_id": player_ids.get(p["gsis_id"]), "player_name": p["player_name"],
            "pos_abb": p["pos_abb"], "pos_rank": p["pos_rank"], "group": p["group"], "unit": (
                "offense" if p["group"] == OFFENSE_GROUP else "special_teams" if p["group"] == "Special Teams" else "defense"),
            "snapshot_at": snapshot_at, "source": SOURCE, "team": team,
        })
    missing = miss_o + miss_d + miss_s
    return {"team": team, "depth_chart_dt": dt, "defense_group": defense_group, "players": players, "missing": missing}


def latest_jerseys(roster_path, teams):
    """Jersey numbers from the latest regular-season roster week, keyed by gsis_id.

    Returns {gsis_id: {"team", "jersey_number", "week"}}. A player listed for another team in that week is
    returned with his roster team, so the caller can flag the mismatch instead of trusting the number.
    """
    cols = ["team", "week", "game_type", "jersey_number", "gsis_id", "full_name"]
    t = pq.read_table(roster_path, columns=cols).to_pydict()
    reg = [i for i in range(len(t["week"])) if t["game_type"][i] == "REG"]
    week = max(t["week"][i] for i in reg)
    out = {}
    for i in reg:
        if t["week"][i] != week or not t["gsis_id"][i]:
            continue
        out.setdefault(t["gsis_id"][i], {"team": t["team"][i], "jersey_number": t["jersey_number"][i],
                                         "week": week, "full_name": t["full_name"][i]})
    return out


def attach_jerseys(doc, jerseys):
    """Copy jersey numbers onto starters. A missing number or a team mismatch is a gap, never a guess."""
    for side in doc["rosters"]:
        r = doc["rosters"][side]
        for p in r["players"]:
            j = jerseys.get(p["gsis_id"])
            if j is None:
                p["jersey_number"] = None
                r["missing"].append({"player_name": p["player_name"], "gap": "no_jersey_in_roster"})
            elif j["team"] != r["team"]:
                p["jersey_number"] = None
                r["missing"].append({"player_name": p["player_name"], "gap": "team_mismatch",
                                     "roster_team": j["team"]})
            else:
                p["jersey_number"] = int(j["jersey_number"]) if j["jersey_number"] is not None else None
                if p["jersey_number"] is None:
                    r["missing"].append({"player_name": p["player_name"], "gap": "null_jersey_number"})
        r["jersey_week"] = max((j["week"] for j in jerseys.values()), default=None)
    return doc


def resolve_player_ids(gsis_ids, db_path):
    """Read-only lookup of LP player ids. Returns {} when no database is present; nothing is written."""
    if not db_path or not os.path.exists(db_path):
        return {}
    con = sqlite3.connect("file:{}?mode=ro".format(db_path), uri=True)
    try:
        out = {}
        for g in gsis_ids:
            r = con.execute("SELECT id FROM players WHERE league='nfl' AND nfl_gsis_id=? LIMIT 1", (g,)).fetchone()
            if r:
                out[g] = r[0]
        return out
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("parquet")
    ap.add_argument("--away", required=True)
    ap.add_argument("--home", required=True)
    ap.add_argument("--roster", required=True, help="nflverse roster parquet, for jersey numbers")
    ap.add_argument("--db", default=None, help="LP database, read only, for player ids")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    table = pq.read_table(args.parquet, columns=NEEDED).to_pydict()
    teams = {"away": args.away, "home": args.home}
    built = {}
    for side, team in teams.items():
        dt = latest_dt(table, team)
        snapshot_at = dt
        built[side] = build_team(table, team, dt, snapshot_at, {})
    gsis = [p["gsis_id"] for side in built for p in built[side]["players"]]
    ids = resolve_player_ids(gsis, args.db)
    for side in built:
        for p in built[side]["players"]:
            p["player_id"] = ids.get(p["gsis_id"])
    doc = {
        "schema": "lp-nfl-starters-snapshot-1",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": SOURCE,
        "source_artifact": os.path.basename(args.parquet),
        "rosters": {side: {"team": built[side]["team"], "depth_chart_dt": built[side]["depth_chart_dt"],
                           "defense_group": built[side]["defense_group"], "players": built[side]["players"],
                           "missing": built[side]["missing"]} for side in built},
    }
    attach_jerseys(doc, latest_jerseys(args.roster, teams))
    doc["roster_source"] = ROSTER_SOURCE
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")
    for side in built:
        n = len(built[side]["players"])
        print("{} {}: {} starters, {} gaps".format(side, built[side]["team"], n, len(built[side]["missing"])))
    return doc


if __name__ == "__main__":
    main()
