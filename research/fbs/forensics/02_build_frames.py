"""Step 2: frames for the forensics.

usage:
  02_build_frames.py research                       -> WORK/data/research_prefilter.pkl (writer frame)
  02_build_frames.py production BACKEND PICKLE_NAME -> WORK/data/PICKLE_NAME (fbs_model_service.build_frame)
"""
import os
import sys

import pandas as pd

import common

out_dir = os.path.join(common.WORK, "data")
os.makedirs(out_dir, exist_ok=True)

if sys.argv[1] == "research":
    common.use_frozen_research()
    import fbs_game_winner_baseline as base
    import fbs_phase3_features_c as feat_c
    os.chdir(common.FROZEN)
    seasons = [2022, 2023, 2024, 2025, 2026]
    events, _, _, _ = base.load_events(common.AUDIT_DATA, seasons)
    forecasts = base.make_predictions(events, 2022)
    forecasts["game_id"] = forecasts["game_id"].astype(str)
    frame = forecasts.rename(columns={"home_win": "y"})
    frame["y"] = frame["y"].astype(float)
    frame["p_g2"] = frame["elo_home_prob"]
    frame["utc_date"] = pd.to_datetime(frame["utc_date"])
    frame = frame.sort_values(["utc_date", "game_id"]).reset_index(drop=True)
    fb = pd.read_csv("research/fbs/phase3/game_features.csv", dtype={"game_id": str})
    fc = pd.read_csv("research/fbs/phase3/game_features_c.csv", dtype={"game_id": str})
    frame = frame.merge(fb[["game_id", "epa_diff"]], on="game_id", how="left")
    frame = frame.merge(fc[["game_id"] + common.FEATS], on="game_id", how="left", suffixes=("", "_csv"))
    frame["has_drive_data"] = frame[common.FEATS].notna().all(axis=1)
    frame["epa_present"] = frame["epa_diff"].notna()
    print("pre-filter rows by season:", frame.groupby("season").size().to_dict())
    print("epa_diff null:", frame.loc[~frame.epa_present, ["game_id", "season", "utc_date"]].to_dict("records"))
    frame.to_pickle(os.path.join(out_dir, "research_prefilter.pkl"))
else:
    backend, name = sys.argv[2], sys.argv[3]
    common.use_production(backend)
    import fbs_model_service as service
    frame = service.build_frame(verbose=False)
    frame["game_id"] = frame["game_id"].astype(str)
    print("production rows by season:", frame.groupby("season").size().to_dict())
    print("production baseline:", sys.modules["fbs_game_winner_baseline"].__file__)
    frame.to_pickle(os.path.join(out_dir, name))
