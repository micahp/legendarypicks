#!/usr/bin/env python3
"""fbs_phase3_features.py -- increment (b) features: prior-play EPA, success, explosiveness, tempo.

Everything here is computed from play states. Publisher EPA, win probability, PPA, success flags and
rating/line columns are never read; `ALLOWED_COLUMNS` is the complete list this module may request from
the play-by-play file, and `assert_allowed` fails on anything else. See
research/fbs/PHASE3-LADDER-20261018.md.

Pipeline
--------
1. Expected points are fitted per season on strictly earlier seasons over a state grid of
   (down, distance bucket, yards-to-goal bucket); the target is the offence's remaining scoring margin.
2. EPA for a play is EP(next state, offence perspective) - EP(current state), sign flipped when
   possession changes; a scoring play is worth its points minus the pre-play expectation.
3. Team-game aggregates (offence and defence: EPA/play, success rate, explosive rate, plays) come from
   scrimmage plays only (pass or rush).
4. Team ratings are as-of: exponentially weighted over a team's prior team-games, half-life 6 games,
   shrunk toward the league mean of completed earlier weeks with an effective-play prior of K = 150.

All parameters are the pre-registered ones; none are tuned here.

Run standalone to build the feature table:
  /root/legendarypicks/backend/venv/bin/python backend/fbs_phase3_features.py
"""
from __future__ import annotations

import argparse
import os
import re
from collections import defaultdict

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

# --- the only play-by-play columns this module may read -------------------------------------------
ALLOWED_COLUMNS = [
    "game_id", "season", "week", "season_type", "play_number", "drive_id", "drive_play_number",
    "period", "clock_minutes", "clock_seconds", "pos_team", "def_pos_team", "play_type",
    "down", "distance", "yards_to_goal", "down_end", "distance_end", "yards_to_goal_end",
    "yards_gained", "pass", "rush", "change_of_pos_team", "pts_scored",
]
BANNED = re.compile(
    r"(^|_)(epa|wpa|wp|wp_before|wp_after|ep_before|ep_after|ppa|qbr|havoc|fpi|rating|ratings|rank|"
    r"spread|total|line|win_prob|win_probability|percentile|success|explosive)($|_)", re.I)

DIST_BINS = [0, 3, 6, 10, 15, 200]
DIST_LABELS = ["1-3", "4-6", "7-10", "11-15", "16+"]
YTG_BINS = list(range(0, 101, 10))
YTG_BINS[-1] = 101
HALF_LIFE_GAMES = 6.0
SHRINK_K_PLAYS = 150.0


def assert_allowed(columns):
    """Fail loudly if a column outside the pre-registered list is requested or looks banned."""
    extra = [c for c in columns if c not in ALLOWED_COLUMNS]
    if extra:
        raise ValueError("column(s) outside the pre-registered allow-list: %s" % extra)
    banned = [c for c in columns if BANNED.search(c)]
    if banned:
        raise ValueError("column(s) look like publisher model output: %s" % banned)


def plays_path(data_dir, season):
    return os.path.join(data_dir, "cfbfastR_cfb_pbp", "play_by_play_%d.parquet" % season)


def load_season(data_dir, season):
    assert_allowed(ALLOWED_COLUMNS)
    df = pq.read_table(plays_path(data_dir, season), columns=ALLOWED_COLUMNS).to_pandas()
    df["season"] = season
    return df


def add_states(df):
    out = df.copy()
    for col in ("down", "distance", "yards_to_goal", "down_end", "distance_end", "yards_to_goal_end"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out["dist_bucket"] = pd.cut(out["distance"], DIST_BINS, labels=DIST_LABELS, right=True)
    out["ytg_bucket"] = pd.cut(out["yards_to_goal"], YTG_BINS, labels=False, right=True)
    out["state"] = (out["down"].fillna(0).astype(int).astype(str) + "|" +
                    out["dist_bucket"].astype(str) + "|" +
                    out["ytg_bucket"].fillna(-1).astype(int).astype(str))
    out["dist_bucket_end"] = pd.cut(out["distance_end"], DIST_BINS, labels=DIST_LABELS, right=True)
    out["ytg_bucket_end"] = pd.cut(out["yards_to_goal_end"], YTG_BINS, labels=False, right=True)
    out["state_end"] = (out["down_end"].fillna(0).astype(int).astype(str) + "|" +
                        out["dist_bucket_end"].astype(str) + "|" +
                        out["ytg_bucket_end"].fillna(-1).astype(int).astype(str))
    return out


def scrimmage_mask(df):
    return df["pass"].fillna(False).astype(bool) | df["rush"].fillna(False).astype(bool)


def remaining_margin(df):
    """Offence's remaining scoring margin from the start of each play, offence perspective.

    Points on a play come from the score-difference columns, signed from the offence's perspective:
    a touchdown is +7 for the offence, a defensive return is -7. Each play contributes +delta to the
    offence and -delta to the defence, so a per-team cumulative sum gives each side's net points and
    the remaining margin follows directly.
    """
    # `pts_scored` is the signed points on the play from the offence's perspective: +7 touchdown,
    # +3 field goal, -7 defensive return, -2 safety, 0 otherwise. Verified against the season's value
    # counts (only those five values occur).
    delta = pd.to_numeric(df["pts_scored"], errors="coerce").fillna(0.0).to_numpy()
    work = pd.DataFrame({
        "row": np.arange(len(df)),
        "game_id": df["game_id"].to_numpy(),
        "pos_team": df["pos_team"].to_numpy(),
        "def_pos_team": df["def_pos_team"].to_numpy(),
        "delta": delta,
    })
    offense_long = pd.DataFrame({"row": work["row"], "game_id": work["game_id"],
                                 "team": work["pos_team"], "pts": work["delta"]})
    defense_long = pd.DataFrame({"row": work["row"], "game_id": work["game_id"],
                                 "team": work["def_pos_team"], "pts": -work["delta"]})
    long = pd.concat([offense_long, defense_long], ignore_index=True)
    long = long.sort_values(["game_id", "team", "row"])
    long["cum"] = long.groupby(["game_id", "team"])["pts"].cumsum()
    totals = long.groupby(["game_id", "team"])["pts"].sum().rename("total")
    long = long.join(totals, on=["game_id", "team"])
    long["remaining"] = long["total"] - long["cum"]
    off_view = long.merge(work[["row", "pos_team"]], left_on=["row", "team"],
                          right_on=["row", "pos_team"], how="inner")
    def_view = long.merge(work[["row", "def_pos_team"]], left_on=["row", "team"],
                          right_on=["row", "def_pos_team"], how="inner")
    rem_off = off_view.drop_duplicates("row").set_index("row")["remaining"]
    rem_def = def_view.drop_duplicates("row").set_index("row")["remaining"]
    return (rem_off - rem_def).reindex(np.arange(len(df))).to_numpy(dtype=float)


EP_FEATURES = ["intercept", "down2", "down3", "down4", "dist_4_6", "dist_7_10", "dist_11_15",
               "dist_16p", "field", "field_sq", "down4_x_field"]
EP_RIDGE = 1e-6


def state_design(df, suffix=""):
    """Design matrix for the EP regression, built only from down, distance and field position."""
    down = pd.to_numeric(df["down" + suffix], errors="coerce").fillna(0).to_numpy()
    distance = pd.to_numeric(df["distance" + suffix], errors="coerce").fillna(0).to_numpy()
    ytg = pd.to_numeric(df["yards_to_goal" + suffix], errors="coerce").fillna(50).to_numpy()
    field = np.clip(ytg, 1, 99) / 9.9            # 0 at own goal, 10 at opponent goal
    cols = [
        np.ones(len(df)),
        (down == 2).astype(float),
        (down == 3).astype(float),
        (down == 4).astype(float),
        ((distance >= 4) & (distance <= 6)).astype(float),
        ((distance >= 7) & (distance <= 10)).astype(float),
        ((distance >= 11) & (distance <= 15)).astype(float),
        (distance >= 16).astype(float),
        field,
        field ** 2,
        (down == 4).astype(float) * field,
    ]
    return np.column_stack(cols)


def season_ep_system(df):
    """Accumulate X'X and X'y for the EP regression from one season of scrimmage plays."""
    rm = remaining_margin(df)
    mask = (scrimmage_mask(df) & df["down"].notna() & df["distance"].notna()
            & df["yards_to_goal"].notna() & np.isfinite(rm))
    X = state_design(df)[mask]
    y = rm[mask]
    return X.T @ X, X.T @ y, int(mask.sum())


def fit_ep(systems_by_season, target_season):
    """EP coefficients from seasons strictly before target_season (ridge on the normal equations)."""
    usable = [s for s in sorted(systems_by_season) if s < target_season]
    if not usable:
        raise ValueError("no prior season to fit EP for %d" % target_season)
    XtX = sum(systems_by_season[s][0] for s in usable)
    Xty = sum(systems_by_season[s][1] for s in usable)
    p = XtX.shape[0]
    coef = np.linalg.solve(XtX + EP_RIDGE * np.eye(p), Xty)
    return coef


def attach_epa(df, coef):
    """EPA = EP(next state) - EP(current) + points on the play, offence perspective.

    Points are added explicitly so a touchdown is worth +7 rather than the drop from a pre-score
    state to a post-score state; the formula is therefore invariant to any constant shift in the EP
    surface. Possession is only flipped for non-scoring plays, because after a score the next play
    (the kickoff) belongs to the scoring team.
    """
    out = df.copy()
    ep_cur = pd.Series(state_design(out) @ coef, index=out.index)
    ep_next = pd.Series(state_design(out, suffix="_end") @ coef, index=out.index)
    delta = pd.to_numeric(out["pts_scored"], errors="coerce").fillna(0.0).to_numpy()
    scored = delta != 0
    flipped = out["change_of_pos_team"].fillna(False).astype(bool).to_numpy() & ~scored
    ep_next = np.where(flipped, -ep_next.to_numpy(), ep_next.to_numpy())
    out["epa"] = ep_next - ep_cur.to_numpy() + delta
    out["success"] = (out["epa"] > 0).astype(float)
    out["explosive"] = (out["epa"] >= 2.0).astype(float)
    return out


def team_game_table(df):
    """One row per (game_id, team) with offence and defence aggregates from scrimmage plays."""
    mask = scrimmage_mask(df) & df["epa"].notna()
    sc = df[mask]
    week_by_game = sc.groupby("game_id")["week"].min().rename("week")
    off = sc.groupby(["game_id", "season", "pos_team"]).agg(
        off_epa=("epa", "mean"), off_success=("success", "mean"),
        off_explosive=("explosive", "mean"), off_plays=("epa", "size")).reset_index()
    de = sc.groupby(["game_id", "season", "def_pos_team"]).agg(
        def_epa=("epa", "mean"), def_success=("success", "mean"),
        def_explosive=("explosive", "mean"), def_plays=("epa", "size")).reset_index()
    de = de.rename(columns={"def_pos_team": "pos_team"})
    out = off.merge(de, on=["game_id", "season", "pos_team"], how="outer")
    out = out.join(week_by_game, on="game_id")
    return out


METRIC_COLS = ["off_epa", "off_success", "off_explosive", "def_epa", "def_success", "def_explosive"]


def decayed_ratings(team_games, half_life=HALF_LIFE_GAMES):
    """Expanding half-life weighted ratings per team, one row per team-game, using only earlier games."""
    rows = []
    decay = 0.5 ** (1.0 / half_life)
    for team, grp in team_games.groupby("pos_team", sort=False):
        grp = grp.sort_values(["season", "week", "game_id"])
        num = {m: 0.0 for m in METRIC_COLS}
        den = {m: 0.0 for m in METRIC_COLS}
        plays = 0.0
        games = 0.0
        for rec in grp.itertuples(index=False):
            # ratings for this game use PRIOR games only: emit before updating with this game
            row = {"game_id": rec.game_id, "pos_team": team, "season": rec.season, "week": rec.week}
            row["decayed_plays"] = plays
            row["decayed_games"] = games
            for m in METRIC_COLS:
                row[m + "_raw"] = num[m] / den[m] if den[m] > 0 else np.nan
            row["has_history"] = bool(den["off_epa"] > 0)
            rows.append(row)
            for m in METRIC_COLS:
                v = getattr(rec, m)
                if v is None or (isinstance(v, float) and np.isnan(v)):
                    continue
                w = float(getattr(rec, "off_plays", 0) or 0) if m.startswith("off_") else float(
                    getattr(rec, "def_plays", 0) or 0)
                w = max(w, 1.0)
                num[m] = num[m] * decay + v * w
                den[m] = den[m] * decay + w
            plays = plays * decay + float(getattr(rec, "off_plays", 0) or 0)
            games = games * decay + 1.0
    return pd.DataFrame(rows)


def league_means_by_week(team_games):
    """Weighted league mean of each metric using only weeks strictly earlier than the row's week."""
    tg = team_games.copy()
    pairs = tg[["season", "week"]].drop_duplicates().sort_values(["season", "week"]).reset_index(drop=True)
    per_week = []
    for rec in pairs.itertuples(index=False):
        s, w = rec.season, rec.week
        subset = tg[(tg.season == s) & (tg.week == w)]
        row = {"season": s, "week": w}
        for m in ("off_epa", "off_success", "off_explosive"):
            plays = float(subset["off_plays"].fillna(0).sum())
            vals = subset[m].fillna(0.0) * subset["off_plays"].fillna(0.0)
            row[m] = vals.sum() / plays if plays else 0.0
        for m in ("def_epa", "def_success", "def_explosive"):
            plays = float(subset["def_plays"].fillna(0).sum())
            vals = subset[m].fillna(0.0) * subset["def_plays"].fillna(0.0)
            row[m] = vals.sum() / plays if plays else 0.0
        per_week.append(row)
    per_week = pd.DataFrame(per_week).sort_values(["season", "week"]).reset_index(drop=True)
    for m in METRIC_COLS:
        per_week[m + "_league"] = per_week[m].shift(1).expanding().mean()
    # The only week with no prior week at all is 2015 week 1, where no team has any history, so the
    # shrink target has no effect (every raw rating is NaN and the games produce no features).
    for m in METRIC_COLS:
        per_week[m + "_league"] = per_week[m + "_league"].fillna(0.0)
    return per_week[["season", "week"] + [m + "_league" for m in METRIC_COLS]]


def build_team_ratings(team_games, half_life=HALF_LIFE_GAMES, shrink_k=SHRINK_K_PLAYS):
    ratings = decayed_ratings(team_games, half_life)
    league = league_means_by_week(team_games)
    ratings = ratings.merge(league, on=["season", "week"], how="left")
    shrink = ratings["decayed_plays"].fillna(0.0) / (ratings["decayed_plays"].fillna(0.0) + shrink_k)
    for m in METRIC_COLS:
        # a team with no prior plays gets the league mean, and is flagged (ladder section 4)
        raw = ratings[m + "_raw"].fillna(ratings[m + "_league"])
        ratings[m] = ratings[m + "_league"] + (raw - ratings[m + "_league"]) * shrink
    ratings["tempo_plays"] = (ratings["decayed_plays"] / ratings["decayed_games"].replace(0, np.nan))
    return ratings[["game_id", "pos_team", "season", "week", "has_history"] + METRIC_COLS
                    + ["decayed_plays", "tempo_plays"]]


def normalise_name(value):
    text = re.sub(r"[^a-z0-9 ]", " ", str(value).lower())
    return " ".join(text.split())


def side_map(data_dir, seasons):
    """Map (game_id, normalised team name) to 'home'/'away' from the schedule."""
    rows = []
    for season in seasons:
        path = os.path.join(data_dir, "cfb_schedules", "cfb_schedules_%d.parquet" % season)
        if not os.path.exists(path):
            continue
        df = pq.read_table(path, columns=["game_id", "home_team", "away_team"]).to_pandas()
        for rec in df.itertuples(index=False):
            rows.append((str(rec.game_id), normalise_name(rec.home_team), "home"))
            rows.append((str(rec.game_id), normalise_name(rec.away_team), "away"))
    return pd.DataFrame(rows, columns=["game_id", "name", "side"]).drop_duplicates(
        ["game_id", "side"])


def build_features(data_dir, seasons, half_life=HALF_LIFE_GAMES, shrink_k=SHRINK_K_PLAYS):
    """One row per game with the four pre-registered feature differences."""
    aggs = {}
    for season in seasons:
        aggs[season] = season_ep_system(add_states(load_season(data_dir, season)))
    team_games = []
    for season in seasons:
        if not any(s < season for s in aggs):
            print("  %d: no prior season to fit EP, used as warm-up only" % season)
            continue
        df = add_states(load_season(data_dir, season))
        ep = fit_ep(aggs, season)
        epa_df = attach_epa(df, ep)
        team_games.append(team_game_table(epa_df))
        mask = scrimmage_mask(epa_df)
        print("  %d: plays %6d, scrimmage %6d, mean EPA %+.4f, success %.3f"
              % (season, len(epa_df), int(mask.sum()), float(epa_df.loc[mask, "epa"].mean()),
                 float(epa_df.loc[mask, "success"].mean())))
    team_games = pd.concat(team_games, ignore_index=True)
    ratings = build_team_ratings(team_games, half_life, shrink_k)
    ratings["game_id"] = ratings["game_id"].astype(str)
    ratings["name"] = ratings["pos_team"].map(normalise_name)
    sides = side_map(data_dir, seasons)
    sides["game_id"] = sides["game_id"].astype(str)
    key = ratings.merge(sides, left_on=["game_id", "name"], right_on=["game_id", "name"], how="inner")
    home = key[key.side == "home"].drop_duplicates("game_id").set_index("game_id")
    away = key[key.side == "away"].drop_duplicates("game_id").set_index("game_id")
    common = home.index.intersection(away.index)
    feats = pd.DataFrame(index=common)
    feats["epa_diff"] = (home.loc[common, "off_epa"] + away.loc[common, "def_epa"]
                         - away.loc[common, "off_epa"] - home.loc[common, "def_epa"])
    feats["success_diff"] = (home.loc[common, "off_success"] + away.loc[common, "def_success"]
                             - away.loc[common, "off_success"] - home.loc[common, "def_success"])
    feats["explosive_diff"] = (home.loc[common, "off_explosive"] + away.loc[common, "def_explosive"]
                               - away.loc[common, "off_explosive"] - home.loc[common, "def_explosive"])
    feats["tempo_diff"] = home.loc[common, "tempo_plays"] - away.loc[common, "tempo_plays"]
    feats["home_decayed_plays"] = home.loc[common, "decayed_plays"]
    feats["away_decayed_plays"] = away.loc[common, "decayed_plays"]
    feats["home_has_history"] = home.loc[common, "has_history"]
    feats["away_has_history"] = away.loc[common, "has_history"]
    feats = feats.reset_index().rename(columns={"index": "game_id"})
    return feats, team_games, ratings, len(sides)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-dir", default=os.path.join("research", "fbs", "parquet"))
    ap.add_argument("--seasons", default="2014,2015,2016,2017,2018,2019,2020,2021,2022,2023,2024,2025,2026")
    ap.add_argument("--out", default=os.path.join("research", "fbs", "phase3", "game_features.csv"))
    ap.add_argument("--half-life", type=float, default=HALF_LIFE_GAMES)
    ap.add_argument("--k", type=float, default=SHRINK_K_PLAYS)
    a = ap.parse_args(argv)
    seasons = [int(s) for s in a.seasons.split(",")]
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    feats, team_games, ratings, _ = build_features(a.data_dir, seasons, a.half_life, a.k)
    feats.to_csv(a.out, index=False)
    print("wrote %s: %d games, columns %s" % (a.out, len(feats), list(feats.columns)))


if __name__ == "__main__":
    main()
