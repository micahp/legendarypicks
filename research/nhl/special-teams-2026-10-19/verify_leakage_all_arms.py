#!/usr/bin/env python3
"""Leakage audit for every feature the ST / penalty arms use.

Independent recompute from the raw DuckDB, compared to features_all_arms.csv:
  - ST PP/PK per-60  (5on4 xGF, 4on5 xGA)
  - penalty drawn/taken per-60  (situation 'all')
For each target (game, team), the source window must be games with
game_date < target_date only. Any mismatch, or any source date >= target date,
is a leak. Reports checks and mismatches; exit 1 on any mismatch or leak.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
AUDIT = Path("/root/legendarypicks/research/nhl/kalshi-playoff-audit-2025-26")
CANON = AUDIT / "canonical_games_v1_7cd2fc9a6e84470c.csv"
DB = "/root/nhl_database_2025-26-playoffs.duckdb"
ALIAS = {"PHX": "ARI", "TBL": "T.B", "NJD": "N.J", "LAK": "L.A", "SJS": "S.J"}

feat = {int(r["game_id"]): r for r in csv.DictReader(open(HERE / "features_all_arms.csv"))}
gdate = {int(c["game_id"]): c["game_date"] for c in csv.DictReader(open(CANON))}

con = duckdb.connect(DB, read_only=True)

# --- ST features: prior-window recompute, separate SQL path ---
st_rows = con.execute("""
    SELECT gameId, team, home_or_away, situation, iceTime,
           scoreVenueAdjustedxGoalsFor AS xgf, scoreVenueAdjustedxGoalsAgainst AS xga
    FROM teams_gamelogs WHERE situation IN ('5on4','4on5')
""").fetchall()
st_per = defaultdict(dict)
for g, team, ha, sit, ice, xgf, xga in st_rows:
    d = st_per[(int(g), ALIAS.get(str(team), str(team)))]
    d["date"] = gdate.get(int(g)); d["ha"] = ha
    # separate denominators: PP uses 5on4 ice, PK uses 4on5 ice
    if sit == "5on4":
        d["xgf_pp"] = float(xgf); d["ice_pp"] = float(ice)
    else:
        d["xga_pk"] = float(xga); d["ice_pk"] = float(ice)
st_hist = defaultdict(list); st_src = {}
for (g, team), d in sorted(st_per.items(), key=lambda kv: (kv[1]["date"], kv[0][0], kv[0][1])):
    st_src[(g, d["ha"])] = [x for x in st_hist[team] if x["date"] < d["date"]][-10:]
    st_hist[team].append(d)

# --- penalty features: prior-window recompute ---
pen_rows = con.execute("""
    SELECT gameId, team, home_or_away, penaltiesFor, penaltiesAgainst, iceTime
    FROM teams_gamelogs WHERE situation='all'
""").fetchall()
con.close()
pen_per = defaultdict(dict)
for g, team, ha, pf, pa, ice in pen_rows:
    d = pen_per[(int(g), ALIAS.get(str(team), str(team)))]
    d["date"] = gdate.get(int(g)); d["ha"] = ha
    d["pf"] = float(pf); d["pa"] = float(pa); d["ice"] = float(ice)
pen_hist = defaultdict(list); pen_src = {}
for (g, team), d in sorted(pen_per.items(), key=lambda kv: (kv[1]["date"], kv[0][0], kv[0][1])):
    prior = [x for x in pen_hist[team] if x["date"] < d["date"]][-10:]
    pen_src[(g, d["ha"])] = prior
    pen_hist[team].append(d)

checks = 0; mismatches = 0; date_leaks = 0; detail = []

for gid, r in feat.items():
    day = gdate[gid]
    for side, st_keys, pen_keys in (
            ("HOME", ("hpp", "hpk"), ("hdrawn", "htaken")),
            ("AWAY", ("app", "apk"), ("adrawn", "ataken"))):
        # ST
        prior = st_src.get((gid, side), [])
        for x in prior:
            if not (x["date"] < day):
                date_leaks += 1
        ice_pp = sum(x.get("ice_pp", 0.0) for x in prior)
        ice_pk = sum(x.get("ice_pk", 0.0) for x in prior)
        pp = 60.0 * sum(x.get("xgf_pp", 0.0) for x in prior) / ice_pp if ice_pp > 0 else None
        pk = 60.0 * sum(x.get("xga_pk", 0.0) for x in prior) / ice_pk if ice_pk > 0 else None
        for key, val in zip(st_keys, (pp, pk)):
            checks += 1
            csv_v = r[key]
            if csv_v in ("", "None"):
                if val is not None: mismatches += 1; detail.append((gid, key, csv_v, val))
            elif val is None or abs(float(csv_v) - val) > 1e-9:
                mismatches += 1; detail.append((gid, key, csv_v, val))
        # penalty
        prior = pen_src.get((gid, side), [])
        for x in prior:
            if not (x["date"] < day):
                date_leaks += 1
        ice = sum(x["ice"] for x in prior)
        drawn = 60.0 * sum(x["pa"] for x in prior) / ice if ice > 0 else None
        taken = 60.0 * sum(x["pf"] for x in prior) / ice if ice > 0 else None
        for key, val in zip(pen_keys, (drawn, taken)):
            checks += 1
            csv_v = r[key]
            if csv_v in ("", "None"):
                if val is not None: mismatches += 1; detail.append((gid, key, csv_v, val))
            elif val is None or abs(float(csv_v) - val) > 1e-9:
                mismatches += 1; detail.append((gid, key, csv_v, val))

print(f"leakage audit: features_all_arms.csv, {len(feat)} games, "
      f"{len(feat)*4} ST checks + {len(feat)*4} penalty checks = {checks} total checks")
print(f"  mismatches={mismatches}")
print(f"  source-date violations (source game_date >= target game_date)={date_leaks}")
if detail[:10]:
    print("  first mismatches:", detail[:10])
print("LEAKAGE AUDIT:", "PASS" if mismatches == 0 and date_leaks == 0 else "FAIL")
raise SystemExit(0 if mismatches == 0 and date_leaks == 0 else 1)
