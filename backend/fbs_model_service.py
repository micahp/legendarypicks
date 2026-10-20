"""Production forecaster for the three adopted FBS game-winner models.

Models, all on the same game population and the same chronological discipline:

  G2   basic chronological Elo (Phase 1 ladder)
  C2   flat ridge logistic on the G2 offset + seven drive splits
  G2h  hierarchical random-intercept logistic on the same offset + drive splits (default)

This module only produces forecasts. It never reads the sportsbook, never writes to the
picks databases, and never fits on a game dated on or after the forecast cutoff.

Sources (all local, read-only):
  <data_dir>/cfb_schedule_<season>.parquet or ncaa_mfb_schedule_<season>.parquet
  <data_dir>/espn_schedule_<season>.parquet, cfb_team_info_<season>.parquet
  <data_dir>/espn_pbp_<season>.parquet (drive features)

The research modules under backend/ are the single implementation of these models; this
module composes them for production instead of re-implementing the statistics.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fbs_game_winner_baseline as base  # noqa: E402
import fbs_phase3_features_c as feat_c  # noqa: E402
from fbs_phase3_hierarchical import HierarchicalLogistic  # noqa: E402
from fbs_phase3_increment import (  # noqa: E402
    FEATURES as FEATURES_B,
    logit,
    sigmoid,
)

FEATURES_C = feat_c.FEATURE_NAMES_C
DEFAULT_DATA_DIR = os.environ.get("FBS_DATA_DIR", "/root/fbs-data/parquet")
LAM_TEAM = 9.0
LAM_CONF = 156.0
RIDGE = 1.0
MIN_TRAIN_GAMES = 200

MODEL_IDS = ("g2", "c2", "g2h")
MODEL_LABELS = {
    "g2": "Basic Elo (G2)",
    "c2": "Drive + efficiency (C2)",
    "g2h": "Hierarchical (G2h)",
}


class FBSModelError(RuntimeError):
    pass


def seasons_available(data_dir: str) -> list[int]:
    """Seasons with every source the models need: schedule, ESPN schedule, team info, PBP."""
    found = set()
    for name in os.listdir(data_dir):
        if not name.endswith(".parquet"):
            continue
        stem, _, season = name[:-len(".parquet")].rpartition("_")
        if not season.isdigit():
            continue
        if stem in ("cfb_schedules", "cfb_schedule", "ncaa_mfb_schedule", "espn_schedule"):
            found.add(int(season))
    complete = []
    for season in sorted(found):
        needed = [os.path.join(data_dir, "espn_schedule_%d.parquet" % season),
                  os.path.join(data_dir, "cfb_team_info_%d.parquet" % season),
                  os.path.join(data_dir, "espn_pbp_%d.parquet" % season)]
        if all(os.path.exists(path) for path in needed):
            complete.append(season)
    return complete


def build_frame(data_dir: str | None = None, seasons: list[int] | None = None,
                verbose: bool = False, return_ratings: bool = False):
    """One row per game: Phase 1 Elo forecast, drive features, outcome and kickoff.

    With return_ratings=True returns (frame, ratings) where ratings carries the as-of team
    metrics used to build the drive features — the same snapshot a future matchup is scored on.
    """
    data_dir = data_dir or DEFAULT_DATA_DIR
    seasons = seasons or seasons_available(data_dir)
    if not seasons:
        raise FBSModelError("no schedule parquet files in %s" % data_dir)
    events, _, _, _ = base.load_events(data_dir, seasons)
    forecasts = base.make_predictions(events, min(seasons))
    forecasts["game_id"] = forecasts["game_id"].astype(str)
    frame = forecasts.rename(columns={"home_win": "y"})
    frame["p_g2"] = frame["elo_home_prob"]
    frame["utc_date"] = pd.to_datetime(frame["utc_date"])
    frame = frame.sort_values(["utc_date", "game_id"]).reset_index(drop=True)

    features_c, team_games, ratings = feat_c.build_features_c(data_dir, seasons)
    features_c["game_id"] = features_c["game_id"].astype(str)
    frame = frame.merge(features_c[["game_id"] + FEATURES_C], on="game_id", how="left")
    frame["has_drive_data"] = frame[FEATURES_C].notna().all(axis=1)
    for col in FEATURES_C:
        frame[col] = frame[col].fillna(0.0)
    frame["home_team_id"] = frame["home_team_id"].astype(str)
    frame["away_team_id"] = frame["away_team_id"].astype(str)
    if verbose:
        print("frame: %d games, %d with outcomes, %d with drive data"
              % (len(frame), int(frame["y"].notna().sum()), int(frame["has_drive_data"].sum())))
    return (frame, ratings) if return_ratings else frame


def _training(frame: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    train = frame[(frame["utc_date"] < as_of) & frame["y"].notna()]
    train = train.dropna(subset=["p_g2"] + FEATURES_C)
    if len(train) < MIN_TRAIN_GAMES:
        raise FBSModelError("only %d training games before %s (need %d)"
                            % (len(train), as_of.date(), MIN_TRAIN_GAMES))
    return train


def fit(frame: pd.DataFrame, as_of: dt.date | dt.datetime | str) -> dict:
    """Fit the three models on games strictly before `as_of`. Returns fitted state."""
    cutoff = pd.Timestamp(as_of)
    if cutoff.tzinfo is not None:
        cutoff = cutoff.tz_convert("UTC").tz_localize(None)
    train = _training(frame, cutoff)

    y = train["y"].to_numpy(dtype=float)
    offset = logit(train["p_g2"].to_numpy(dtype=float))

    # C2 — flat ridge logistic on the seven drive splits, G2 as fixed offset.
    x = np.column_stack([np.ones(len(train))] + [train[c].to_numpy(dtype=float) for c in FEATURES_C])
    coef = _fit_offset_logistic(x, y, offset, ridge=RIDGE)

    # G2h — hierarchy on team-season within conference, same offset and features.
    hier = HierarchicalLogistic(lam_team=LAM_TEAM, lam_conf=LAM_CONF, ridge=RIDGE)
    hier.fit(train, FEATURES_C)
    if not hier.converged:
        raise FBSModelError("hierarchical fit failed to converge (grad %.3e)" % hier.grad_norm)

    return {"as_of": cutoff, "train_games": len(train), "c2_coef": coef, "g2h": hier,
            "train_last_date": train["utc_date"].max()}


def _fit_offset_logistic(x: np.ndarray, y: np.ndarray, offset: np.ndarray,
                         ridge: float = 1.0) -> np.ndarray:
    """Penalised logistic with a fixed offset; intercept column is x[:, 0]."""
    from scipy.optimize import minimize

    def objective(beta):
        eta = offset + x @ beta
        p = sigmoid(eta)
        eps = 1e-12
        nll = -np.sum(y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps))
        return nll + 0.5 * ridge * np.sum(beta[1:] ** 2)

    def gradient(beta):
        p = sigmoid(offset + x @ beta)
        grad = x.T @ (p - y)
        pen = ridge * beta.copy()
        pen[0] = 0.0
        return grad + pen

    result = minimize(objective, np.zeros(x.shape[1]), jac=gradient, method="L-BFGS-B",
                      options={"maxiter": 500, "gtol": 1e-6})
    if not result.success:
        raise FBSModelError("C2 fit failed: %s" % result.message)
    return result.x


def predict(frame: pd.DataFrame, state: dict, rows: pd.DataFrame) -> pd.DataFrame:
    """Score the given rows under the fitted state. G2 needs no fit."""
    out = rows.copy()
    offset = logit(out["p_g2"].to_numpy(dtype=float))
    x = np.column_stack([np.ones(len(out))] + [out[c].to_numpy(dtype=float) for c in FEATURES_C])
    out["p_c2"] = sigmoid(offset + x @ state["c2_coef"])
    out["p_g2h"] = state["g2h"].predict(out)
    out["p_g2"] = out["p_g2"].astype(float)
    return out


def upcoming(frame: pd.DataFrame, after: dt.datetime | None = None,
             horizon_days: int = 21) -> pd.DataFrame:
    """Games not yet played, kicking off in (after, after + horizon]."""
    now = pd.Timestamp(after or dt.datetime.now(dt.timezone.utc)).tz_localize(None)
    horizon = now + pd.Timedelta(days=horizon_days)
    slate = frame[frame["y"].isna() & (frame["utc_date"] > now) & (frame["utc_date"] <= horizon)]
    return slate.sort_values(["utc_date", "game_id"]).reset_index(drop=True)
