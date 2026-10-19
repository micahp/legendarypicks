#!/usr/bin/env python3
"""Independent verification for the special-teams experiment.

1. Ground-truth check: recompute one game's PP/PK rolling feature straight from
   the DuckDB with a separate code path and compare to the merged CSV.
2. Leakage audit: every ST feature's source games must be strictly before the
   game date.
3. PIT / KS for the registered distribution gate.
"""
from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import duckdb
import numpy as np

HERE = Path(__file__).resolve().parent
AUDIT = Path("/root/legendarypicks/research/nhl/kalshi-playoff-audit-2025-26")
CANON = AUDIT / "canonical_games_v1_7cd2fc9a6e84470c.csv"
DB = "/root/nhl_database_2025-26-playoffs.duckdb"
ALIAS = {"PHX": "ARI", "TBL": "T.B", "NJD": "N.J", "LAK": "L.A", "SJS": "S.J"}

merged = {int(r["game_id"]): r for r in csv.DictReader(open(HERE / "special_teams_merged_features.csv"))}
canon = {int(r["game_id"]): r for r in csv.DictReader(open(CANON))}

# ---------------------------------------------------------------------------
# 1. Ground-truth recompute for one game
# ---------------------------------------------------------------------------
con = duckdb.connect(DB, read_only=True)
# pick a 2025 game
gid = next(g for g in sorted(merged) if merged[g]["season"] == "2025")
row = merged[gid]
day = row["game_date"]
home = row["home_team"]
print(f"verify game_id={gid} date={day} home={home} away={row['away_team']}")
print(f"  CSV home pp_off={row['hpp']} pk_def={row['hpk']}  away pp_off={row['app']} pk_def={row['apk']}")

# find the home team's prior 10 games from teams_gamelogs, using the canonical
# source team code for that team in each game.
log_team = canon[gid]["source_team_home_code"]
# all games where this team appears as either side, before day
hist = con.execute("""
    SELECT g.gameId, c.game_date, g.situation, g.iceTime,
           g.scoreVenueAdjustedxGoalsFor AS xgf, g.scoreVenueAdjustedxGoalsAgainst AS xga
    FROM teams_gamelogs g
    JOIN read_csv(?) c ON g.gameId = c.game_id
    WHERE g.team = ? AND g.situation IN ('5on4','4on5')
      AND c.game_date < ?
    ORDER BY c.game_date DESC, g.gameId DESC
    LIMIT 20
""", [str(CANON), log_team, day]).fetchall()
# group by game, keep the 10 most recent games
by_game = defaultdict(dict)
for g, d, sit, ice, xgf, xga in hist:
    by_game[g]["date"] = d
    if sit == "5on4":
        by_game[g]["xgf_pp"] = float(xgf); by_game[g]["ice_pp"] = float(ice)
    else:
        by_game[g]["xga_pk"] = float(xga); by_game[g]["ice_pk"] = float(ice)
recent = list(by_game.values())[:10]
ice_pp = sum(x["ice_pp"] for x in recent)
ice_pk = sum(x["ice_pk"] for x in recent)
pp_off = 60.0 * sum(x["xgf_pp"] for x in recent) / ice_pp
pk_def = 60.0 * sum(x["xga_pk"] for x in recent) / ice_pk
print(f"  DB  home pp_off={pp_off:.6f} pk_def={pk_def:.6f}  (from {len(recent)} prior games, log_code={log_team})")
print(f"  match: pp_off={abs(pp_off-float(row['hpp']))<1e-6} pk_def={abs(pk_def-float(row['hpk']))<1e-6}")
con.close()

# ---------------------------------------------------------------------------
# 2. Leakage audit — recompute all ST features and compare to the CSV
# ---------------------------------------------------------------------------
con = duckdb.connect(DB, read_only=True)
rows = con.execute("""
    SELECT gameId, team, home_or_away, situation, iceTime,
           scoreVenueAdjustedxGoalsFor AS xgf, scoreVenueAdjustedxGoalsAgainst AS xga
    FROM teams_gamelogs WHERE situation IN ('5on4','4on5')
""").fetchall()
con.close()
gdate = {int(c["game_id"]): c["game_date"] for c in csv.DictReader(open(CANON))}
per = defaultdict(dict)
for g, team, ha, sit, ice, xgf, xga in rows:
    d = per[(int(g), ALIAS.get(str(team), str(team)))]
    d["date"] = gdate.get(int(g))
    d["ha"] = ha
    if sit == "5on4":
        d["xgf_pp"] = float(xgf); d["ice_pp"] = float(ice)
    else:
        d["xga_pk"] = float(xga); d["ice_pk"] = float(ice)
order = sorted(per.items(), key=lambda kv: (kv[1]["date"], kv[0][0], kv[0][1]))
hist = defaultdict(list)
recomputed = {}
for (g, team), d in order:
    prior = [x for x in hist[team] if x["date"] < d["date"]][-10:]
    if len(prior) >= 5 and sum(x["ice_pp"] for x in prior) > 0 and sum(x["ice_pk"] for x in prior) > 0:
        recomputed[(g, d["ha"])] = (
            60.0 * sum(x["xgf_pp"] for x in prior) / sum(x["ice_pp"] for x in prior),
            60.0 * sum(x["xga_pk"] for x in prior) / sum(x["ice_pk"] for x in prior))
    else:
        recomputed[(g, d["ha"])] = (None, None)
    hist[team].append(d)

mismatch = 0; checked = 0; leak = 0
for g, r in merged.items():
    for side, key in (("HOME", "hpp"), ("HOME", "hpk"), ("AWAY", "app"), ("AWAY", "apk")):
        v = recomputed.get((g, side))
        idx = 0 if key in ("hpp", "app") else 1
        csv_v = r[key]
        checked += 1
        if csv_v in ("", "None"):
            if v[idx] is not None: mismatch += 1
        else:
            if v[idx] is None or abs(float(csv_v) - v[idx]) > 1e-9: mismatch += 1
print(f"leakage/ground-truth audit: checked={checked} mismatches={mismatch}")

# ---------------------------------------------------------------------------
# 3. PIT / KS for the distribution gate
# ---------------------------------------------------------------------------
res = json.load(open(HERE / "results_special_teams.json"))

def pmf(mu, cap=21):
    mu = max(float(mu), 1e-9); ks = np.arange(cap)
    p = np.exp(-mu + ks * math.log(mu) - np.array([math.lgamma(k + 1) for k in ks]))
    return p / p.sum()

def pit_ks(mus, obs):
    """Midpoint PIT: F(y-1) + 0.5*p(y)."""
    us = []
    for mu, y in zip(mus, obs):
        p = pmf(mu); F = np.cumsum(p)
        u = (F[y - 1] if y > 0 else 0.0) + 0.5 * p[y]
        us.append(u)
    us = np.sort(np.array(us))
    n = len(us)
    ks = max(abs((np.arange(1, n + 1) / n) - us).max(), abs(us - (np.arange(0, n) / n)).max())
    return float(ks), float(us.mean())

# rebuild per-arm mus from the run? the runner did not persist them; recompute here
# by re-fitting is expensive. Instead, load the merged CSV and the params, predict.
import sys
sys.path.insert(0, str(HERE))
from run_special_teams import load_games, build_st_features, fit_arm, predict_arm, EVAL_SEASONS, TRAIN_FROM

games = load_games(); st = build_st_features(games)
merged_games = []
for g in games:
    h = st.get((g["game_id"], "HOME")); a = st.get((g["game_id"], "AWAY"))
    if not h or not a or None in h or None in a: continue
    merged_games.append({**g, "hpp": h[0], "hpk": h[1], "app": a[0], "apk": a[1]})
all_g = {g["game_id"]: g for g in merged_games}
so_home_by_season = {}
pit = {"b5": {"home": [], "away": []}, "st": {"home": [], "away": []}}
for season in EVAL_SEASONS:
    evalg = [g for g in merged_games if g["season"] == season]
    train = [g for g in merged_games if TRAIN_FROM <= g["season"] < season]
    so = [g for g in train if g.get("period") == "SO"]
    so_home = sum(g["home_win"] for g in so) / len(so)
    so_home_by_season[season] = so_home
    for m in ("b5", "st"):
        params = fit_arm(train, m); mus = predict_arm(evalg, m, params)
        for g in evalg:
            mh, ma = mus[g["game_id"]]
            pit[m]["home"].append((mh, g["hg"])); pit[m]["away"].append((ma, g["ag"]))
print("so_home by season:", {s: round(v, 4) for s, v in so_home_by_season.items()})
for m in ("b5", "st"):
    kh, uh = pit_ks([x[0] for x in pit[m]["home"]], [x[1] for x in pit[m]["home"]])
    ka, ua = pit_ks([x[0] for x in pit[m]["away"]], [x[1] for x in pit[m]["away"]])
    print(f"  {m}: PIT KS home={kh:.4f} (mean {uh:.4f})  away={ka:.4f} (mean {ua:.4f})")
