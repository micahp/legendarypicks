"""Shared configuration and frame construction for the NCAAF C2/G2h parity forensics.

Every path is overridable by environment variable. The defaults match the box where the
diagnosis was run. docs/RESULT-ncaaf-parity-forensics.md states what each one must contain.
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.environ.get("FBS_FORENSICS_WORK", os.path.join(HERE, "work"))  # gitignored scratch
# Detached worktree of the writer commit: `git worktree add --detach <path> 88573876`.
FROZEN = os.environ.get("FBS_FROZEN_WORKTREE", "/root/lp-ncaaf-replay-88573876")
ARCHIVE_PBP = os.environ.get("FBS_ARCHIVE_PBP", "/root/lp-fbs-archive/research/fbs/parquet")
AUDIT_DATA = os.environ.get("FBS_AUDIT_DATA", "/root/lp-fbs-audit/research/fbs/parquet")
PROD_BACKEND = os.environ.get("FBS_PROD_BACKEND", "/root/lp-ncaaf-integrity/backend")
CANDIDATE_BACKEND = os.environ.get("FBS_CANDIDATE_BACKEND", "/root/lp-ncaaf-parity-candidate/backend")
LEDGER = os.environ.get("FBS_PARITY_LEDGER", "/root/fbs-data/parity/wf_research.csv")
COMMITTED_WF = os.path.join(FROZEN, "research/fbs/phase3-g/forecasts_walk_forward.csv")
FEATS = ["points_per_drive_diff", "turnovers_per_drive_diff", "start_field_position_diff",
         "rz_td_rate_diff", "third_down_rate_diff", "explosive_drive_rate_diff",
         "penalties_per_play_diff"]
BASE_COLS = ["game_id", "season", "utc_date", "y", "p_g2", "home_team_id", "away_team_id",
             "home_conference", "away_conference"]


def data_path(name):
    return os.path.join(WORK, "data", name)


def make_frame(variant):
    """The writer's 3,523-game population with research or production drive features.

    research:   committed game_features_c.csv values (research_prefilter.pkl, epa filter applied)
    production: fbs_model_service.build_frame() values for the same IDs (prod_frame pickle)
    Training membership is identical across variants by construction, so any difference in
    predictions is attributable to feature values alone.
    """
    R = pd.read_pickle(data_path("research_prefilter.pkl"))
    R["game_id"] = R["game_id"].astype(str)
    R = R[R["epa_present"]].copy()
    if variant == "research":
        F = R[BASE_COLS + FEATS].copy()
    else:
        pickle = os.environ.get("PROD_PICKLE", data_path("prod_frame.pkl"))
        P = pd.read_pickle(pickle)
        P["game_id"] = P["game_id"].astype(str)
        P = P[P["game_id"].isin(set(R["game_id"]))][["game_id"] + FEATS]
        F = R[BASE_COLS].merge(P, on="game_id", how="inner")
    F["utc_date"] = pd.to_datetime(F["utc_date"])
    F["home_team_id"] = F["home_team_id"].astype(str)
    F["away_team_id"] = F["away_team_id"].astype(str)
    F["has_drive_data"] = F[FEATS].notna().all(axis=1)  # the writer computes this before filling
    for c in FEATS:
        F[c] = F[c].fillna(0.0)
    F = F.sort_values(["utc_date", "game_id"]).reset_index(drop=True)
    F["block"] = F["season"].astype(str) + "-" + F["utc_date"].astype(str)
    return F


def use_frozen_research():
    """Import the frozen research modules. The frozen Phase 1 baseline is cached first so the
    writer's own sys.path prepend (lp-fbs-audit) cannot shadow it."""
    sys.path.insert(0, os.path.join(FROZEN, "backend"))
    import fbs_game_winner_baseline  # noqa: F401
    assert fbs_game_winner_baseline.__file__.startswith(FROZEN), fbs_game_winner_baseline.__file__


def use_production(backend):
    sys.path.insert(0, backend)
