#!/usr/bin/env python3
"""fbs_phase3_features_c.py -- increment (c): drive and box-score splits, as-of team ratings.

Seven per-team-per-game splits, each built from the opponent-raw drive record and turned into an as-of
rating with the same machinery as increment (b) (half-life 6, K = 150, league-mean fill and flag):

    points_per_drive, turnovers_per_drive, start_field_position, rz_td_rate,
    third_down_rate, explosive_drive_rate, penalties_per_play

Sources: `espn_cfb_pbp` drive-level fields for all seven. `espn_cfb_team_box` was in the
pre-registration; the drive table carries the same facts at a finer grain, so the box score is not
needed and the increment stays behind one column guard. That substitution is recorded in the result
doc before the run.

Publisher model output stays banned: no EPA, wpa, ppa, qbr or havoc column is requested, and the same
BANNED regex from fbs_phase3_features.py is applied.

Run:
  /root/legendarypicks/backend/venv/bin/python backend/fbs_phase3_features_c.py
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fbs_phase3_features as base  # noqa: E402

ALLOWED_C = [
    "game_id", "season", "week", "pos_team_id", "def_pos_team_id", "homeTeamId", "awayTeamId",
    "drive.id", "drive.start.yardLine", "drive.yards", "drive.offensivePlays", "drive.result",
    "start.down", "start.yardsToEndzone", "firstD_by_yards", "scoring_play", "touchdown",
    "isTurnover", "penalty_flag", "pos_score_pts", "type.text",
]
METRIC_COLS_C = [
    "off_points_per_drive", "off_turnovers_per_drive", "off_start_field_position",
    "off_rz_td_rate", "off_third_down_rate", "off_explosive_drive_rate", "off_penalties_per_play",
    "def_points_per_drive", "def_turnovers_per_drive", "def_start_field_position",
    "def_rz_td_rate", "def_third_down_rate", "def_explosive_drive_rate", "def_penalties_per_play",
]
FEATURE_NAMES_C = ["points_per_drive_diff", "turnovers_per_drive_diff", "start_field_position_diff",
                   "rz_td_rate_diff", "third_down_rate_diff", "explosive_drive_rate_diff",
                   "penalties_per_play_diff"]
RZ_YARDS = 20
EXPLOSIVE_DRIVE_YARDS = 30.0


def assert_allowed_c(columns):
    extra = [c for c in columns if c not in ALLOWED_C]
    if extra:
        raise ValueError("column(s) outside the (c) allow-list: %s" % extra)
    banned = [c for c in columns if base.BANNED.search(c)]
    if banned:
        raise ValueError("column(s) look like publisher model output: %s" % banned)


def load_season_c(data_dir, season):
    assert_allowed_c(ALLOWED_C)
    path = os.path.join(data_dir, "espn_cfb_pbp", "play_by_play_%d.parquet" % season)
    df = pq.read_table(path, columns=ALLOWED_C).to_pandas()
    df["season"] = season
    return df


def drive_table(df):
    """One row per drive: who had it, what it produced, and how it started."""
    work = df.copy()
    for col in ("drive.start.yardLine", "drive.yards", "drive.offensivePlays",
                "start.down", "start.yardsToEndzone", "pos_score_pts"):
        work[col] = pd.to_numeric(work[col], errors="coerce")
    work["firstD_by_yards"] = work["firstD_by_yards"].fillna(False).astype(bool)
    work["scoring_play"] = work["scoring_play"].fillna(False).astype(bool)
    work["touchdown"] = work["touchdown"].fillna(False).astype(bool)
    work["isTurnover"] = work["isTurnover"].fillna(False).astype(bool)
    work["penalty_flag"] = work["penalty_flag"].fillna(False).astype(bool)
    work["third_down"] = work["start.down"].eq(3)
    work["third_conv"] = work["third_down"] & (work["firstD_by_yards"] | work["scoring_play"])
    work["rz_play"] = work["start.yardsToEndzone"].le(RZ_YARDS)
    grouped = work.groupby(["game_id", "drive.id"], sort=False)
    drives = grouped.agg(
        offense_id=("pos_team_id", "first"),
        defense_id=("def_pos_team_id", "first"),
        season=("season", "first"),
        week=("week", "first"),
        points=("pos_score_pts", "sum"),
        start_fp=("drive.start.yardLine", "first"),
        yards=("drive.yards", "first"),
        plays=("drive.offensivePlays", "first"),
        td=("touchdown", "max"),
        rz=("rz_play", "max"),
        third_downs=("third_down", "sum"),
        third_convs=("third_conv", "sum"),
        turnovers=("isTurnover", "sum"),
        penalties=("penalty_flag", "sum"),
        n_plays=("drive.id", "size"),
    ).reset_index()
    drives["rz_td"] = drives["rz"] & drives["td"]
    drives["explosive"] = drives["yards"].fillna(0) >= EXPLOSIVE_DRIVE_YARDS
    return drives


def _aggregate(drives, id_col, prefix):
    g = drives.groupby(["game_id", id_col], sort=False)
    out = g.agg(
        season=("season", "first"), week=("week", "first"),
        drives=("drive.id", "size"),
        points=("points", "sum"), yards=("yards", "sum"), plays=("plays", "sum"),
        start_fp=("start_fp", "mean"), rz=("rz", "sum"), rz_td=("rz_td", "sum"),
        third_downs=("third_downs", "sum"), third_convs=("third_convs", "sum"),
        turnovers=("turnovers", "sum"), penalties=("penalties", "sum"),
        explosive=("explosive", "sum"), n_plays=("n_plays", "sum"),
    ).reset_index().rename(columns={id_col: "pos_team"})
    out[prefix + "points_per_drive"] = out["points"] / out["drives"]
    out[prefix + "turnovers_per_drive"] = out["turnovers"] / out["drives"]
    out[prefix + "start_field_position"] = out["start_fp"]
    out[prefix + "rz_td_rate"] = np.where(out["rz"] > 0, out["rz_td"] / out["rz"], np.nan)
    out[prefix + "third_down_rate"] = np.where(out["third_downs"] > 0,
                                               out["third_convs"] / out["third_downs"], np.nan)
    out[prefix + "explosive_drive_rate"] = out["explosive"] / out["drives"]
    out[prefix + "penalties_per_play"] = np.where(out["n_plays"] > 0,
                                                  out["penalties"] / out["n_plays"], np.nan)
    out[prefix + "plays"] = out["plays"].fillna(0.0)
    return out


def team_game_table_c(drives):
    off = _aggregate(drives, "offense_id", "off_")
    de = _aggregate(drives, "defense_id", "def_")
    off = off.rename(columns={"off_plays": "off_plays"})
    de = de.rename(columns={"def_plays": "def_plays"})
    merged = off.merge(de, on=["game_id", "pos_team"], how="outer", suffixes=("", "_d"))
    merged["season"] = merged["season"].fillna(merged["season_d"])
    merged["week"] = merged["week"].fillna(merged["week_d"])
    merged["off_plays"] = merged["off_plays"].fillna(0.0).clip(lower=0.0)
    merged["def_plays"] = merged["def_plays"].fillna(0.0).clip(lower=0.0)
    return merged


def _id_str(value):
    """Stable string id: ids arrive as int64 in some seasons and float64 in others."""
    return str(pd.to_numeric(pd.Series([value]), errors="coerce").astype("Int64").iloc[0])


def side_map_c(df):
    """(game_id, team_id) -> 'home'/'away', straight from the pbp's own team ids."""
    per_game = df.groupby("game_id").agg(home=("homeTeamId", "first"), away=("awayTeamId", "first"))
    rows = []
    for game_id, rec in per_game.iterrows():
        rows.append((_id_str(game_id), _id_str(rec["home"]), "home"))
        rows.append((_id_str(game_id), _id_str(rec["away"]), "away"))
    return pd.DataFrame(rows, columns=["game_id", "pos_team", "side"]).drop_duplicates(
        ["game_id", "side"])


def build_features_c(data_dir, seasons):
    frames = []
    sides = []
    for season in seasons:
        df = load_season_c(data_dir, season)
        drives = drive_table(df)
        frames.append(team_game_table_c(drives))
        sides.append(side_map_c(df))
        print("  %d: plays %6d, games %4d, drives %6d, points/drive %.2f"
              % (season, len(df), df.game_id.nunique(), len(drives),
                 float(drives["points"].sum() / len(drives))))
    team_games = pd.concat(frames, ignore_index=True)
    team_games["pos_team"] = [
        _id_str(v) for v in pd.to_numeric(team_games["pos_team"], errors="coerce")]
    team_games["game_id"] = [_id_str(v) for v in pd.to_numeric(team_games["game_id"], errors="coerce")]
    ratings = base.build_team_ratings(team_games, METRIC_COLS_C)
    sides = pd.concat(sides, ignore_index=True)
    key = ratings.merge(sides, on=["game_id", "pos_team"], how="inner")
    home = key[key.side == "home"].drop_duplicates("game_id").set_index("game_id")
    away = key[key.side == "away"].drop_duplicates("game_id").set_index("game_id")
    common = home.index.intersection(away.index)
    pairs = {
        "points_per_drive_diff": "points_per_drive",
        "turnovers_per_drive_diff": "turnovers_per_drive",
        "start_field_position_diff": "start_field_position",
        "rz_td_rate_diff": "rz_td_rate",
        "third_down_rate_diff": "third_down_rate",
        "explosive_drive_rate_diff": "explosive_drive_rate",
        "penalties_per_play_diff": "penalties_per_play",
    }
    feats = pd.DataFrame(index=common)
    for name, metric in pairs.items():
        feats[name] = ((home.loc[common, "off_" + metric] + away.loc[common, "def_" + metric])
                       - (away.loc[common, "off_" + metric] + home.loc[common, "def_" + metric]))
    feats["home_has_history"] = home.loc[common, "has_history"]
    feats["away_has_history"] = away.loc[common, "has_history"]
    feats = feats.reset_index().rename(columns={"index": "game_id"})
    return feats, team_games, ratings


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-dir", default=os.path.join("research", "fbs", "parquet"))
    ap.add_argument("--seasons", default="2014,2015,2016,2017,2018,2019,2020,2021,2022,2023,2024,2025,2026")
    ap.add_argument("--out", default=os.path.join("research", "fbs", "phase3", "game_features_c.csv"))
    a = ap.parse_args(argv)
    seasons = [int(s) for s in a.seasons.split(",")]
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    feats, team_games, ratings = build_features_c(a.data_dir, seasons)
    feats.to_csv(a.out, index=False)
    print("wrote %s: %d games, columns %s" % (a.out, len(feats), list(feats.columns)))
    print("games without features: %d" % int(feats["points_per_drive_diff"].isna().sum()))


if __name__ == "__main__":
    main()
