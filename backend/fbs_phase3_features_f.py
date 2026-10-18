#!/usr/bin/env python3
"""fbs_phase3_features_f.py -- increment (f): recent form against a team's own baseline.

Pre-registered in RESULT-FBS-PHASE3-B-20261018.md §17:

    form = mean of the team's last 3 prior team-games - its full-history decayed rating
    metrics: off_epa, def_epa, off_success, def_success
    game features: the four home-minus-away differences in the (b)/(c) direction

The full-history rating is the (b) rating (half-life 6 team-games, K = 150 shrink). The recent window uses
only games that kicked off at least one full UTC day before the game being forecast, the same embargo as
(b). The team-game table is built once and cached, so the half-life sensitivity runs (3 and 10) reuse it.

Run:
  /root/legendarypicks/backend/venv/bin/python backend/fbs_phase3_features_f.py [--half-life 6]
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fbs_phase3_features as base  # noqa: E402

FORM_METRICS = ["off_epa", "def_epa", "off_success", "def_success"]
FEATURE_NAMES_F = ["off_epa_form_diff", "def_epa_form_diff", "off_success_form_diff",
                   "def_success_form_diff"]
RECENT_WINDOW = 3


def build_team_games(data_dir, seasons, cache_path):
    """The (b) team-game table: one row per team per game with offence/defence EPA and success."""
    if os.path.exists(cache_path):
        df = pd.read_csv(cache_path, dtype={"game_id": str, "pos_team": str})
        print("team-game table loaded from cache: %d rows" % len(df))
        return df
    aggs = {s: base.season_ep_system(base.add_states(base.load_season(data_dir, s))) for s in seasons}
    frames = []
    for season in seasons:
        if not any(s < season for s in aggs):
            continue
        df = base.add_states(base.load_season(data_dir, season))
        epa_df = base.attach_epa(df, base.fit_ep(aggs, season))
        frames.append(base.team_game_table(epa_df))
    team_games = pd.concat(frames, ignore_index=True)
    team_games["game_id"] = team_games["game_id"].astype(str)
    team_games["pos_team"] = team_games["pos_team"].astype(str)
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    team_games.to_csv(cache_path, index=False)
    print("team-game table built: %d rows (cached to %s)" % (len(team_games), cache_path))
    return team_games


def recent_window_means(team_games, window=RECENT_WINDOW):
    """Equal-weight mean of the previous `window` team-games per team, shifted so it never includes
    the game being rated."""
    out = []
    for team, grp in team_games.groupby("pos_team", sort=False):
        grp = grp.sort_values(["season", "week", "game_id"])
        rolled = grp[FORM_METRICS].rolling(window=window, min_periods=1).mean().shift(1)
        block = pd.DataFrame({
            "game_id": grp["game_id"].to_numpy(),
            "pos_team": team,
            "recent_n": grp[FORM_METRICS].rolling(window=window, min_periods=1).count().shift(1)
            .max(axis=1).to_numpy(),
        })
        for m in FORM_METRICS:
            block[m + "_recent"] = rolled[m].to_numpy()
        out.append(block)
    return pd.concat(out, ignore_index=True)


def build_features_f(data_dir, team_games, half_life=base.HALF_LIFE_GAMES):
    ratings = base.build_team_ratings(team_games, FORM_METRICS, half_life)
    recent = recent_window_means(team_games)
    merged = ratings.merge(recent, on=["game_id", "pos_team"], how="left")
    for m in FORM_METRICS:
        # no recent games -> form is zero (the team is at its own baseline), with the flag below
        merged[m + "_form"] = (merged[m + "_recent"] - merged[m]).fillna(0.0)

    sides = base.side_map(data_dir, sorted(team_games["season"].unique()))
    sides["game_id"] = sides["game_id"].astype(str)
    merged["name"] = merged["pos_team"].map(base.normalise_name)
    key = merged.merge(sides, on=["game_id", "name"], how="inner")
    home = key[key.side == "home"].drop_duplicates("game_id").set_index("game_id")
    away = key[key.side == "away"].drop_duplicates("game_id").set_index("game_id")
    common = home.index.intersection(away.index)
    # form is home-minus-away, with defence flipped so positive always favours the home side
    feats = pd.DataFrame(index=common)
    feats["off_epa_form_diff"] = home.loc[common, "off_epa_form"] - away.loc[common, "off_epa_form"]
    feats["def_epa_form_diff"] = away.loc[common, "def_epa_form"] - home.loc[common, "def_epa_form"]
    feats["off_success_form_diff"] = (home.loc[common, "off_success_form"]
                                      - away.loc[common, "off_success_form"])
    feats["def_success_form_diff"] = (away.loc[common, "def_success_form"]
                                      - home.loc[common, "def_success_form"])
    feats["home_recent_n"] = home.loc[common, "recent_n"]
    feats["away_recent_n"] = away.loc[common, "recent_n"]
    feats["form_known"] = (feats["home_recent_n"].fillna(0) >= 1) & (feats["away_recent_n"].fillna(0) >= 1)
    return feats.reset_index().rename(columns={"index": "game_id"})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-dir", default=os.path.join("research", "fbs", "parquet"))
    ap.add_argument("--seasons", default="2014,2015,2016,2017,2018,2019,2020,2021,2022,2023,2024,2025,2026")
    ap.add_argument("--half-life", type=float, default=6.0)
    ap.add_argument("--cache", default=os.path.join("research", "fbs", "phase3-f", "team_games.csv"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    seasons = [int(s) for s in a.seasons.split(",")]
    out = a.out or os.path.join("research", "fbs", "phase3", "game_features_f_hl%d.csv" % int(a.half_life))
    team_games = build_team_games(a.data_dir, seasons, a.cache)
    feats = build_features_f(a.data_dir, team_games, a.half_life)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    feats.to_csv(out, index=False)
    print("wrote %s: %d games, half-life %.0f" % (out, len(feats), a.half_life))
    print("  form known %.3f | recent_n median %.0f"
          % (feats.form_known.mean(), feats.home_recent_n.median()))
    for c in FEATURE_NAMES_F:
        print("  %-22s median %+.3f, 5-95%% [%+.3f, %+.3f]"
              % (c, feats[c].median(), feats[c].quantile(0.05), feats[c].quantile(0.95)))


if __name__ == "__main__":
    main()
