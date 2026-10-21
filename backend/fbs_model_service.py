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
import hashlib
import json
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
    fit_offset_logistic,
    logit,
    sigmoid,
)

FEATURES_C = feat_c.FEATURE_NAMES_C
DEFAULT_DATA_DIR = os.environ.get("FBS_DATA_DIR", "/root/fbs-data/parquet")
LAM_TEAM = 9.0
LAM_CONF = 156.0
RIDGE = 1.0
MIN_TRAIN_GAMES = 200
# The adopted drive features (research/fbs/phase3/game_features_c.csv) are as-of team ratings over
# every season from 2014. Loading only the scored seasons changes every feature value.
FEATURE_FIRST_SEASON = 2014
# Historical eligibility comes from the pinned cfbfastR coverage manifest, built offline by
# backend/fbs_cfbfastr_coverage.py. It is never an ID list in code.
COVERAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fbs_coverage")
COVERAGE_MANIFEST = "cfbfastr_pbp_coverage.manifest.json"

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


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_coverage(directory: str | None = None) -> dict:
    """Load the pinned cfbfastR coverage table and verify it against the hash its manifest records.

    The directory is resolved at call time, so a redirected COVERAGE_DIR is honoured.
    """
    directory = directory or COVERAGE_DIR
    manifest_path = os.path.join(directory, COVERAGE_MANIFEST)
    if not os.path.exists(manifest_path):
        raise FBSModelError("no cfbfastR coverage manifest at %s" % manifest_path)
    with open(manifest_path) as handle:
        manifest = json.load(handle)
    csv_path = os.path.join(directory, manifest["csv"])
    if not os.path.exists(csv_path) or _sha256(csv_path) != manifest["csv_sha256"]:
        raise FBSModelError("coverage table %s does not match its manifest" % csv_path)
    table = pd.read_csv(csv_path, dtype={"game_id": str})
    if table.duplicated(["season", "game_id"]).any():
        raise FBSModelError("coverage table %s has duplicate (season, game_id) rows" % csv_path)
    return {"manifest": manifest, "table": table}


def apply_pbp_eligibility(frame: pd.DataFrame, table: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Drop completed games whose verified source has no plays. Halt on anything unverified.

    Only games with a known outcome are checked. An upcoming game has no plays yet and is kept.
    A completed game with no coverage row, or with an unknown status, raises: a missing record is
    never read as zero coverage. Returns (kept frame with coverage_status, excluded games). Results are
    graded only from rows whose coverage_status is has_plays: the archive, not the schedule, confirms the
    final result.
    """
    merged = frame[["season", "game_id", "y"]].merge(
        table[["season", "game_id", "coverage_status"]], on=["season", "game_id"], how="left")
    completed = merged["y"].notna().to_numpy()
    status = merged["coverage_status"]
    unresolved = completed & (status.isna() | status.astype(str).str.startswith("unknown")).to_numpy()
    if unresolved.any():
        ids = merged.loc[unresolved, "game_id"].tolist()
        raise FBSModelError("%d completed games lack verified cfbfastR coverage: %s" % (len(ids), ids[:10]))
    if (completed & (status == "not_completed").to_numpy()).any():
        raise FBSModelError("completed games carry a not_completed coverage status; the manifest is inconsistent")
    drop = completed & (status == "no_plays_in_complete_snapshot").to_numpy()
    excluded = frame.loc[drop, ["season", "game_id", "home_team", "away_team"]].reset_index(drop=True)
    kept = frame.loc[~drop].reset_index(drop=True)
    kept["coverage_status"] = status.to_numpy()[~drop]
    return kept, excluded


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
    # Applied after the Elo forecast, as the writer does: an excluded game still feeds the Elo history.
    coverage = load_coverage()
    frame, excluded = apply_pbp_eligibility(frame, coverage["table"])
    if verbose and len(excluded):
        print("eligibility: excluded %d completed game(s) with no source plays: %s"
              % (len(excluded), excluded["game_id"].tolist()))

    feature_seasons = list(range(FEATURE_FIRST_SEASON, max(seasons) + 1))
    pbp_missing = [s for s in feature_seasons if not os.path.exists(
        os.path.join(data_dir, "espn_cfb_pbp", "play_by_play_%d.parquet" % s))]
    if pbp_missing:
        raise FBSModelError("drive features need play-by-play for %s under %s" % (pbp_missing, data_dir))
    features_c, team_games, ratings = feat_c.build_features_c(data_dir, feature_seasons)
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

    # C2 — the research estimator, verbatim (fbs_phase3_increment.walk_forward).
    c2 = fit_c2(train)

    # G2h — hierarchy on team-season within conference, same offset and features.
    hier = HierarchicalLogistic(lam_team=LAM_TEAM, lam_conf=LAM_CONF, ridge=RIDGE)
    hier.fit(train, FEATURES_C)
    if not hier.converged:
        raise FBSModelError("hierarchical fit failed to converge (grad %.3e)" % hier.grad_norm)

    return {"as_of": cutoff, "train_games": len(train), "c2": c2, "g2h": hier,
            "train_last_date": train["utc_date"].max()}


def _c2_design(rows: pd.DataFrame, mu: pd.Series, sd: pd.Series) -> np.ndarray:
    return np.column_stack([np.ones(len(rows))] + [((rows[c] - mu[c]) / sd[c]).to_numpy(dtype=float)
                                                    for c in FEATURES_C])


def fit_c2(train: pd.DataFrame) -> dict:
    """C2 as the research harness fits it: standardize on the training games, ridge logistic,
    G2 logit as a fixed offset. Standardization and penalty must match the adopted C2 exactly."""
    mu = train[FEATURES_C].mean()
    sd = train[FEATURES_C].std().replace(0, 1.0)
    coef = fit_offset_logistic(_c2_design(train, mu, sd), train["y"].to_numpy(dtype=float),
                               logit(train["p_g2"].to_numpy(dtype=float)))
    return {"mu": mu, "sd": sd, "coef": coef}


def predict_c2(c2: dict, rows: pd.DataFrame) -> np.ndarray:
    offset = logit(rows["p_g2"].to_numpy(dtype=float))
    return sigmoid(offset + _c2_design(rows, c2["mu"], c2["sd"]) @ c2["coef"])


def predict(frame: pd.DataFrame, state: dict, rows: pd.DataFrame) -> pd.DataFrame:
    """Score the given rows under the fitted state. G2 needs no fit."""
    out = rows.copy()
    out["p_c2"] = predict_c2(state["c2"], out)
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
