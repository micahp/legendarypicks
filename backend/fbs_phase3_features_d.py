#!/usr/bin/env python3
"""fbs_phase3_features_d.py -- increment (d): game-level rest, travel and weather covariates.

Pre-registered in RESULT-FBS-PHASE3-B-20261018.md §13 after auditing what the archive actually holds:

    rest_diff           home rest - away rest, days, capped at 21 (season opener -> 7, flagged)
    away_travel_km      great-circle distance from the away team's home to the home team's, log1p
    lon_shift           home longitude - away longitude, positive = the away team travels east
    temperature_c       kickoff temperature in Celsius (secondary)
    wind_kph            kickoff wind in km/h (secondary)

Sources: `cfb_schedules` start dates and team ids, `cfb_team_info` coordinates, and (secondary only)
`cfb_matchup_line` weather. No publisher model output is read; home field is not modelled here because
G2 already carries it.

Neutral-site games cannot be located (the archive has no venue coordinates), so their travel values are
set to the neutral 0 with `travel_known = false`.

Run:
  /root/legendarypicks/backend/venv/bin/python backend/fbs_phase3_features_d.py
"""
from __future__ import annotations

import argparse
import glob
import os

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

REST_CAP_DAYS = 21.0
REST_NEUTRAL_DAYS = 7.0
MAX_PLAUSIBLE_GAP = 30.0
MIN_PLAUSIBLE_GAP = 2.0
EARTH_RADIUS_KM = 6371.0


def _id_str(values):
    return pd.to_numeric(pd.Series(values), errors="coerce").astype("Int64").astype(str)


def load_schedules(data_dir, seasons):
    frames = []
    for season in seasons:
        path = os.path.join(data_dir, "cfb_schedules", "cfb_schedules_%d.parquet" % season)
        df = pq.read_table(path, columns=["game_id", "season", "season_type", "start_date", "home_id",
                                          "away_id", "neutral_site"]).to_pandas()
        frames.append(df)
    sch = pd.concat(frames, ignore_index=True)
    sch["game_id"] = _id_str(sch["game_id"])
    sch["home_id"] = _id_str(sch["home_id"])
    sch["away_id"] = _id_str(sch["away_id"])
    sch["start_date"] = pd.to_datetime(sch["start_date"], errors="coerce", utc=True)
    return sch.dropna(subset=["start_date"])


def team_rest(sch):
    """Days of rest per team-game, capped, with a neutral flag for openers and bad dates."""
    long = pd.concat([
        sch[["game_id", "season", "start_date", "home_id"]].rename(columns={"home_id": "team_id"}),
        sch[["game_id", "season", "start_date", "away_id"]].rename(columns={"away_id": "team_id"}),
    ], ignore_index=True).sort_values(["team_id", "start_date"])
    long["prev_date"] = long.groupby("team_id")["start_date"].shift(1)
    gap = (long["start_date"] - long["prev_date"]).dt.total_seconds() / 86400.0
    implausible = gap.isna() | (gap > MAX_PLAUSIBLE_GAP) | (gap < MIN_PLAUSIBLE_GAP)
    long["rest_neutral"] = implausible
    long["rest_days"] = gap.where(~implausible, REST_NEUTRAL_DAYS).clip(upper=REST_CAP_DAYS)
    return long[["game_id", "team_id", "rest_days", "rest_neutral"]]


def team_coords(data_dir, seasons):
    frames = []
    for season in seasons:
        path = os.path.join(data_dir, "cfb_team_info", "cfb_team_info_%d.parquet" % season)
        if not os.path.exists(path):
            continue
        df = pq.read_table(path, columns=["team_id", "latitude", "longitude"]).to_pandas()
        df["team_id"] = _id_str(df["team_id"])
        df["season"] = season
        frames.append(df)
    coords = pd.concat(frames, ignore_index=True)
    coords = coords.sort_values("season").drop_duplicates("team_id", keep="last")
    return coords.dropna(subset=["latitude", "longitude"])


def haversine(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def load_weather(data_dir, seasons):
    frames = []
    for season in seasons:
        path = os.path.join(data_dir, "cfb_matchup_line", "cfb_matchup_line_%d.parquet" % season)
        if not os.path.exists(path):
            continue
        df = pq.read_table(path, columns=["game_id", "temperature", "wind_speed"]).to_pandas()
        df["game_id"] = _id_str(df["game_id"])
        df["season"] = season
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["game_id", "temperature_c", "wind_kph"])
    w = pd.concat(frames, ignore_index=True).drop_duplicates("game_id")
    # source units are Fahrenheit and mph
    w["temperature_c"] = (w["temperature"] - 32.0) * 5.0 / 9.0
    w["wind_kph"] = w["wind_speed"] * 1.609344
    return w[["game_id", "temperature_c", "wind_kph"]]


def build_features_d(data_dir, seasons):
    sch = load_schedules(data_dir, seasons)
    rest = team_rest(sch)
    coords = team_coords(data_dir, seasons)

    home = sch.merge(rest.rename(columns={"team_id": "home_id"}), on=["game_id", "home_id"], how="left")
    home = home.merge(rest.rename(columns={"team_id": "away_id"}), on=["game_id", "away_id"],
                      how="left", suffixes=("", "_away"))
    home_coords = coords.rename(columns={"team_id": "home_id", "latitude": "home_lat",
                                         "longitude": "home_lon"})[["home_id", "home_lat", "home_lon"]]
    away_coords = coords.rename(columns={"team_id": "away_id", "latitude": "away_lat",
                                         "longitude": "away_lon"})[["away_id", "away_lat", "away_lon"]]
    home = home.merge(home_coords, on="home_id", how="left")
    home = home.merge(away_coords, on="away_id", how="left")

    neutral = home["neutral_site"].fillna(False).astype(bool)
    have_coords = home[["home_lat", "home_lon", "away_lat", "away_lon"]].notna().all(axis=1)
    home["travel_known"] = (~neutral) & have_coords
    distance = haversine(home["away_lat"], home["away_lon"], home["home_lat"], home["home_lon"])
    home["away_travel_km"] = np.where(home["travel_known"], np.log1p(distance), 0.0)
    home["lon_shift"] = np.where(home["travel_known"], home["home_lon"] - home["away_lon"], 0.0)
    home["rest_diff"] = home["rest_days"] - home["rest_days_away"]

    weather = load_weather(data_dir, seasons)
    feats = home.merge(weather, on="game_id", how="left")
    feats["weather_known"] = feats["temperature_c"].notna() & feats["wind_kph"].notna()
    # fixed neutral fill (15 C, 10 km/h) rather than a median computed across seasons, so no
    # later-season information reaches an earlier game
    feats["temperature_c"] = feats["temperature_c"].fillna(15.0)
    feats["wind_kph"] = feats["wind_kph"].fillna(10.0)
    cols = ["game_id", "season", "rest_diff", "away_travel_km", "lon_shift", "temperature_c",
            "wind_kph", "rest_neutral", "rest_neutral_away", "travel_known", "weather_known"]
    return feats[cols]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-dir", default=os.path.join("research", "fbs", "parquet"))
    ap.add_argument("--seasons", default="2021,2022,2023,2024,2025,2026")
    ap.add_argument("--out", default=os.path.join("research", "fbs", "phase3", "game_features_d.csv"))
    a = ap.parse_args(argv)
    seasons = [int(s) for s in a.seasons.split(",")]
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    feats = build_features_d(a.data_dir, seasons)
    feats.to_csv(a.out, index=False)
    print("wrote %s: %d games" % (a.out, len(feats)))
    print("  travel unknown %.3f, weather unknown %.3f, rest neutral (home) %.3f"
          % ((~feats.travel_known).mean(), (~feats.weather_known).mean(), feats.rest_neutral.mean()))
    print("  rest_diff: median %.1f, 5-95%% [%.1f, %.1f]"
          % (feats.rest_diff.median(), feats.rest_diff.quantile(0.05), feats.rest_diff.quantile(0.95)))
    print("  away_travel_km (log1p): median %.2f, max %.2f"
          % (feats.away_travel_km.median(), feats.away_travel_km.max()))
    print("  lon_shift: median %.1f, 5-95%% [%.1f, %.1f]"
          % (feats.lon_shift.median(), feats.lon_shift.quantile(0.05), feats.lon_shift.quantile(0.95)))


if __name__ == "__main__":
    main()
