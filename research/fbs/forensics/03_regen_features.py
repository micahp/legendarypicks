"""Step 3: regenerate drive features with the FROZEN build_features_c and vary only the seasons.

usage: 03_regen_features.py {full|prod} OUT_CSV
  full = 2014..2026 (the committed game_features_c.csv was built with the script's default range)
  prod = 2022..2026 (what fbs_model_service.build_frame passed before the candidate fix)
"""
import os
import sys

import common

mode, out = sys.argv[1], sys.argv[2]
common.use_frozen_research()
os.chdir(common.FROZEN)
import fbs_phase3_features_c as feat_c  # noqa: E402

seasons = list(range(2014, 2027)) if mode == "full" else list(range(2022, 2027))
feats, _, _ = feat_c.build_features_c(common.ARCHIVE_PBP, seasons)
feats["game_id"] = feats["game_id"].astype(str)
feats.to_csv(out, index=False)
print("wrote", out, feats.shape, "seasons", seasons[0], "-", seasons[-1])
