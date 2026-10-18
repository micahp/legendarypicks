#!/usr/bin/env python3
"""fbs_phase3_features_e.py -- increment (e): coaching tenure, returning production, talent.

Pre-registered in RESULT-FBS-PHASE3-B-20261018.md §15 after auditing the archive:

    coach_tenure_diff        consecutive seasons under the current head coach, home minus away, cap 10
    off_returning_diff       returning offensive production (0-1), home minus away
    def_returning_diff       returning defensive production (0-1), home minus away
    talent_diff              247Sports talent composite / 1000, home minus away   (secondary)
    net_transfer_talent_diff portal net transfer talent / 1000, home minus away    (secondary)

Every input is a season-level fact fixed before week 1, so these are game-level covariates rather than
as-of team ratings. Only identity columns are read from `espn_cfb_coach_tendencies`; its EPA and
tendency aggregates are never touched.

Run:
  /root/legendarypicks/backend/venv/bin/python backend/fbs_phase3_features_e.py
"""
from __future__ import annotations

import argparse
import glob
import os

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

TENURE_CAP = 10


def _id_str(values):
    return pd.to_numeric(pd.Series(values), errors="coerce").astype("Int64").astype(str)


def read_rel(base, rel, cols):
    frames = []
    for f in sorted(glob.glob(os.path.join(base, rel, "*.parquet"))):
        names = pq.ParquetFile(f).schema_arrow.names
        keep = [c for c in cols if c in names]
        df = pq.read_table(f, columns=keep).to_pandas()
        if "season" not in df.columns:
            season = int(f.rsplit("_", 1)[1].split(".")[0])
            df["season"] = season
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def coach_tenure(base):
    """Consecutive seasons with the same head coach, per team-season."""
    co = read_rel(base, "espn_cfb_coach_tendencies", ["season", "pos_team_id", "coach", "role"])
    co = co[co.role.fillna("HC").eq("HC")].copy()
    co["team_id"] = _id_str(co["pos_team_id"])
    co = co.sort_values(["team_id", "season"])
    tenure = []
    for team, grp in co.groupby("team_id", sort=False):
        prev_season = None
        prev_coach = None
        run = 0
        for rec in grp.sort_values("season").itertuples(index=False):
            if prev_coach == rec.coach and prev_season == rec.season - 1:
                run += 1
            else:
                run = 1
            tenure.append({"season": rec.season, "team_id": team, "coach": rec.coach,
                           "coach_tenure": min(run, TENURE_CAP)})
            prev_season, prev_coach = rec.season, rec.coach
    return pd.DataFrame(tenure)


def team_season_table(base, seasons):
    tenure = coach_tenure(base)
    tenure = tenure[tenure.season.isin(seasons)]

    rp = read_rel(base, "cfb_returning_production",
                  ["season", "team_id", "off_returning", "def_returning", "overall_returning"])
    rp["team_id"] = _id_str(rp["team_id"])
    rp = rp[rp.season.isin(seasons)][["season", "team_id", "off_returning", "def_returning"]]

    tal = read_rel(base, "cfb_team_talent", ["season", "team_id", "talent_composite"])
    tal["team_id"] = _id_str(tal["team_id"])
    tal = tal[tal.season.isin(seasons)][["season", "team_id", "talent_composite"]]
    tal["talent"] = pd.to_numeric(tal["talent_composite"], errors="coerce") / 1000.0

    por = read_rel(base, "cfb_team_portal", ["season", "team_id", "net_transfer_talent"])
    por["team_id"] = _id_str(por["team_id"])
    por = por[por.season.isin(seasons)][["season", "team_id", "net_transfer_talent"]]
    por["transfer_talent"] = pd.to_numeric(por["net_transfer_talent"], errors="coerce") / 1000.0

    out = tenure.merge(rp, on=["season", "team_id"], how="outer")
    out = out.merge(tal[["season", "team_id", "talent"]], on=["season", "team_id"], how="outer")
    out = out.merge(por[["season", "team_id", "transfer_talent"]], on=["season", "team_id"], how="outer")
    return out


def build_features_e(base, seasons):
    teams = team_season_table(base, seasons)
    sch = []
    for season in seasons:
        path = os.path.join(base, "cfb_schedules", "cfb_schedules_%d.parquet" % season)
        df = pq.read_table(path, columns=["game_id", "season", "home_id", "away_id"]).to_pandas()
        sch.append(df)
    sch = pd.concat(sch, ignore_index=True)
    sch["game_id"] = _id_str(sch["game_id"])
    sch["home_id"] = _id_str(sch["home_id"])
    sch["away_id"] = _id_str(sch["away_id"])

    cols = ["coach_tenure", "off_returning", "def_returning", "talent", "transfer_talent"]
    home = teams.rename(columns={c: "home_" + c for c in cols}).rename(columns={"team_id": "home_id"})
    away = teams.rename(columns={c: "away_" + c for c in cols}).rename(columns={"team_id": "away_id"})
    feats = sch.merge(home[["season", "home_id"] + ["home_" + c for c in cols]],
                      on=["season", "home_id"], how="left")
    feats = feats.merge(away[["season", "away_id"] + ["away_" + c for c in cols]],
                        on=["season", "away_id"], how="left")

    for c in ("coach_tenure", "off_returning", "def_returning", "talent", "transfer_talent"):
        feats[c + "_known"] = feats["home_" + c].notna() & feats["away_" + c].notna()
        feats[c + "_diff"] = (feats["home_" + c] - feats["away_" + c]).fillna(0.0)
    keep = ["game_id", "season"] + [c + "_diff" for c in cols] + [c + "_known" for c in cols]
    return feats[keep]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-dir", default=os.path.join("research", "fbs", "parquet"))
    ap.add_argument("--seasons", default="2022,2023,2024,2025,2026")
    ap.add_argument("--out", default=os.path.join("research", "fbs", "phase3", "game_features_e.csv"))
    a = ap.parse_args(argv)
    seasons = [int(s) for s in a.seasons.split(",")]
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    feats = build_features_e(a.data_dir, seasons)
    feats.to_csv(a.out, index=False)
    print("wrote %s: %d games" % (a.out, len(feats)))
    for c in ("coach_tenure", "off_returning", "def_returning", "talent", "transfer_talent"):
        print("  %-16s known %.3f | diff median %+.3f, 5-95%% [%+.3f, %+.3f]"
              % (c, feats[c + "_known"].mean(), feats[c + "_diff"].median(),
                 feats[c + "_diff"].quantile(0.05), feats[c + "_diff"].quantile(0.95)))


if __name__ == "__main__":
    main()
