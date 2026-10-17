#!/usr/bin/env python3
"""Chronological FBS game-winner baselines from locally cached schedules.

Uses schedule/result data only. Predictions for a UTC kickoff date are generated
from games kicked off at least one full UTC calendar day earlier. This embargo
is intentionally conservative because the source releases do not provide final
whistle timestamps. All games on a kickoff date share the same pregame state.

Run from the repository root with:
  /root/legendarypicks/backend/venv/bin/python backend/fbs_game_winner_baseline.py
"""
import argparse
import csv
import math
import os
from collections import defaultdict
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytz
from scipy import sparse
from scipy.sparse.linalg import lsmr


MODEL_VERSION = "fbs-game-winner-baselines-v1-20261017"
FIRST_EVALUATION_SEASON = 2023
ELO_INITIAL = 1500.0
ELO_HOME_ADVANTAGE = 55.0
ELO_K = 20.0
ELO_OFFSEASON_REGRESSION = 0.25
STRENGTH_RIDGE = 15.0
STRENGTH_SEASON_HALF_LIFE = 1.0
BOOTSTRAP_REPLICATES = 2000
BOOTSTRAP_SEED = 20261017
MODEL_COLUMNS = ["home_base_prob", "elo_home_prob", "margin_home_prob"]
MODEL_LABELS = {
    "home_base_prob": "Historical home/neutral base rate",
    "elo_home_prob": "Chronological Elo",
    "margin_home_prob": "Opponent-adjusted margin strength",
}
SEC_BIG12 = {"sec", "big 12"}


def as_int(value):
    if pd.isna(value):
        return None
    return int(value)


def as_float(value):
    if pd.isna(value):
        return None
    return float(value)


def truthy(value):
    return bool(value) if not pd.isna(value) else False


def season_schedule_path(data_dir, season):
    if season == 2026:
        snapshot = os.path.join(
            data_dir, "cfb_schedules_2026_snapshot_20261017.parquet"
        )
        if os.path.exists(snapshot):
            return snapshot
    return os.path.join(data_dir, "cfb_schedules_%d.parquet" % season)


def normalized_conf(value):
    if value is None or pd.isna(value):
        return ""
    return " ".join(str(value).strip().casefold().split())


def parse_utc(value):
    stamp = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(stamp):
        return None
    return stamp.to_pydatetime()


def get_timezone_map(team_info):
    by_team = {}
    by_venue = {}
    for row in team_info.itertuples(index=False):
        tz_name = getattr(row, "timezone", None)
        if not tz_name or pd.isna(tz_name):
            continue
        try:
            pytz.timezone(str(tz_name))
        except Exception:
            continue
        team_id = as_int(getattr(row, "team_id", None))
        venue_id = as_int(getattr(row, "venue_id", None))
        if team_id is not None:
            by_team[team_id] = str(tz_name)
        if venue_id is not None:
            by_venue[venue_id] = str(tz_name)
    return by_team, by_venue


def classify_local_day(kickoff_utc, neutral, home_id, venue_id, tz_by_team,
                        tz_by_venue):
    tz_name = None
    if neutral:
        if venue_id is not None:
            tz_name = tz_by_venue.get(venue_id)
    else:
        tz_name = tz_by_team.get(home_id)
        if not tz_name and venue_id is not None:
            tz_name = tz_by_venue.get(venue_id)
    if not kickoff_utc or not tz_name:
        return None, "Unknown"
    local = kickoff_utc.astimezone(pytz.timezone(tz_name))
    return local.isoformat(), "Saturday" if local.weekday() == 5 else "Off-Saturday"


def schedule_row_to_event(row, season, source_label):
    game_id = str(row.game_id)
    c_home_id = as_int(row.home_id_cfb)
    c_away_id = as_int(row.away_id_cfb)
    e_home_id = as_int(row.home_id_espn)
    e_away_id = as_int(row.away_id_espn)
    if None in (c_home_id, c_away_id, e_home_id, e_away_id):
        raise ValueError("missing team id for completed FBS-participant game %s" % game_id)

    same_order = c_home_id == e_home_id and c_away_id == e_away_id
    reverse_order = c_home_id == e_away_id and c_away_id == e_home_id
    if not same_order and not reverse_order:
        raise ValueError("schedule publishers disagree on teams for game %s" % game_id)

    e_home_score = as_float(row.home_score)
    e_away_score = as_float(row.away_score)
    if e_home_score is None or e_away_score is None:
        raise ValueError("completed game has no ESPN score: %s" % game_id)
    c_home_score = as_float(row.home_points)
    c_away_score = as_float(row.away_points)
    if c_home_score is not None and c_away_score is not None:
        expected = ((c_home_score, c_away_score) if same_order
                    else (c_away_score, c_home_score))
        if expected != (e_home_score, e_away_score):
            raise ValueError("schedule publishers disagree on score for game %s" % game_id)

    if same_order:
        home_conf, away_conf = row.home_conference, row.away_conference
        home_rank, away_rank = row.home_rank, row.away_rank
    else:
        home_conf, away_conf = row.away_conference, row.home_conference
        home_rank, away_rank = row.away_rank, row.home_rank

    kickoff = parse_utc(row.game_date)
    if kickoff is None:
        kickoff = parse_utc(row.start_date)
    if kickoff is None:
        raise ValueError("completed game has no parseable kickoff date: %s" % game_id)

    neutral_value = row.neutral_site_espn
    neutral = truthy(neutral_value) if not pd.isna(neutral_value) else truthy(row.neutral_site_cfb)
    phase_raw = str(row.season_type_cfb or "").strip().casefold()
    notes = "" if pd.isna(row.notes) else str(row.notes)
    playoff = normalized_conf(row.playoff_competition) == "cfp"
    if playoff:
        phase = "Playoff"
    elif "championship" in notes.casefold():
        phase = "Conference championship"
    elif phase_raw == "postseason":
        phase = "Bowl"
    else:
        phase = "Regular season"

    return {
        "game_id": game_id,
        "season": int(season),
        "kickoff_utc": kickoff,
        "utc_date": kickoff.date(),
        "season_type": phase_raw,
        "game_phase": phase,
        "home_team_id": e_home_id,
        "away_team_id": e_away_id,
        "home_team": str(row.home_team_espn),
        "away_team": str(row.away_team_espn),
        "home_conference": "" if pd.isna(home_conf) else str(home_conf),
        "away_conference": "" if pd.isna(away_conf) else str(away_conf),
        "home_score": int(e_home_score),
        "away_score": int(e_away_score),
        "home_win": int(e_home_score > e_away_score),
        "neutral_site": neutral,
        "venue_id": as_int(row.venue_id),
        "venue": str(row.venue_espn or row.venue_cfb or ""),
        "home_rank": as_float(home_rank),
        "away_rank": as_float(away_rank),
        "fbs_game": truthy(row.fbs_game),
        "fbs_participant": truthy(row.fbs_participant),
        "cfb_completed": truthy(row.completed),
        "result_source": source_label,
    }


def load_events(data_dir, seasons):
    events = []
    coverage = []
    team_info_by_season = {}
    season_rows = {}
    for season in seasons:
        schedule_path = season_schedule_path(data_dir, season)
        espn_path = os.path.join(data_dir, "espn_schedule_%d.parquet" % season)
        team_path = os.path.join(data_dir, "cfb_team_info_%d.parquet" % season)
        if not all(os.path.exists(path) for path in (schedule_path, espn_path, team_path)):
            raise FileNotFoundError("missing required local source for season %d" % season)
        schedule = pd.read_parquet(schedule_path)
        espn = pd.read_parquet(espn_path)
        team_info = pd.read_parquet(team_path)
        if schedule.game_id.astype(str).duplicated().any():
            raise ValueError("duplicate game_id in %s" % schedule_path)
        if espn.game_id.astype(str).duplicated().any():
            raise ValueError("duplicate game_id in %s" % espn_path)
        team_info_by_season[season] = team_info
        season_rows[season] = schedule

        joined = schedule.merge(
            espn, on="game_id", how="left", suffixes=("_cfb", "_espn"),
            validate="one_to_one", indicator=True
        )
        participant = joined[joined.fbs_participant.fillna(False)]
        fbs = joined[joined.fbs_game.fillna(False)]
        completed_espn = participant[
            participant.status_espn.eq("STATUS_FINAL")
            & participant.home_score.notna()
            & participant.away_score.notna()
        ]
        primary_espn = fbs[
            fbs.status_espn.eq("STATUS_FINAL")
            & fbs.home_score.notna()
            & fbs.away_score.notna()
        ]
        coverage.append({
            "season": season,
            "schedule_source": os.path.basename(schedule_path),
            "all_schedule_rows": int(len(schedule)),
            "unique_schedule_ids": int(schedule.game_id.astype(str).nunique()),
            "fbs_game_rows": int(len(fbs)),
            "fbs_participant_rows": int(len(participant)),
            "completed_fbs_participant": int(len(completed_espn)),
            "completed_fbs_vs_fbs": int(len(primary_espn)),
            "fbs_vs_fcs_completed": int(len(completed_espn) - len(primary_espn)),
            "espn_final_without_cfb_completed": int(
                (primary_espn.completed.fillna(False) == False).sum()
            ),
            "fbs_rows_missing_espn_id": int((fbs._merge != "both").sum()),
            "fbs_rows_canceled_or_not_final": int(
                len(fbs) - len(primary_espn)
            ),
        })

        for row in completed_espn.itertuples(index=False):
            source_label = "ESPN schedule; CFBD schedule membership/conference"
            event = schedule_row_to_event(row, season, source_label)
            if event["home_win"] not in (0, 1):
                raise ValueError("invalid binary target in game %s" % event["game_id"])
            events.append(event)

    frame = pd.DataFrame(events)
    if frame.game_id.duplicated().any():
        dupes = frame.loc[frame.game_id.duplicated(), "game_id"].tolist()[:10]
        raise ValueError("duplicate event IDs across seasons: %s" % dupes)
    frame = frame.sort_values(["kickoff_utc", "season", "game_id"]).reset_index(drop=True)
    frame["evaluation_population"] = frame.fbs_game.astype(bool)

    for season in seasons:
        team_info = team_info_by_season[season]
        tz_by_team, tz_by_venue = get_timezone_map(team_info)
        selected = frame.season.eq(season)
        local_values = []
        local_days = []
        for row in frame.loc[selected].itertuples(index=False):
            local, day_group = classify_local_day(
                row.kickoff_utc, row.neutral_site, row.home_team_id,
                row.venue_id, tz_by_team, tz_by_venue
            )
            local_values.append(local)
            local_days.append(day_group)
        frame.loc[selected, "kickoff_local"] = local_values
        frame.loc[selected, "day_group"] = local_days

    add_conference_groups(frame, season_rows)
    return frame, pd.DataFrame(coverage), season_rows, team_info_by_season


def add_conference_groups(frame, season_rows):
    conference_top10 = defaultdict(set)
    conference_playoff = defaultdict(set)
    team_playoff = defaultdict(set)
    for season, schedule in season_rows.items():
        for row in schedule[schedule.fbs_game.fillna(False)].itertuples(index=False):
            home_conf = normalized_conf(row.home_conference)
            away_conf = normalized_conf(row.away_conference)
            if as_float(row.home_rank) is not None and as_float(row.home_rank) <= 10:
                if home_conf:
                    conference_top10[season].add(home_conf)
            if as_float(row.away_rank) is not None and as_float(row.away_rank) <= 10:
                if away_conf:
                    conference_top10[season].add(away_conf)
            if normalized_conf(row.playoff_competition) == "cfp":
                if home_conf:
                    conference_playoff[season].add(home_conf)
                if away_conf:
                    conference_playoff[season].add(away_conf)
                team_playoff[season].add(as_int(row.home_id))
                team_playoff[season].add(as_int(row.away_id))

    home_groups = []
    away_groups = []
    matchup_groups = []
    for row in frame.itertuples(index=False):
        season = row.season
        hconf = normalized_conf(row.home_conference)
        aconf = normalized_conf(row.away_conference)
        if hconf in SEC_BIG12:
            hgroup = "SEC/Big 12"
        elif season == 2026:
            hgroup = "Other; postseason status not known"
        elif hconf and (hconf in conference_top10[season]
                        or hconf in conference_playoff[season]):
            hgroup = "Other conference with Top 10/CFP team"
        else:
            hgroup = "Other conference without Top 10/CFP team"
        if aconf in SEC_BIG12:
            agroup = "SEC/Big 12"
        elif season == 2026:
            agroup = "Other; postseason status not known"
        elif aconf and (aconf in conference_top10[season]
                        or aconf in conference_playoff[season]):
            agroup = "Other conference with Top 10/CFP team"
        else:
            agroup = "Other conference without Top 10/CFP team"
        home_groups.append(hgroup)
        away_groups.append(agroup)
        if hgroup == "SEC/Big 12" and agroup == "Other conference without Top 10/CFP team":
            matchup = "SEC/Big 12 vs lower non-elite"
        elif agroup == "SEC/Big 12" and hgroup == "Other conference without Top 10/CFP team":
            matchup = "SEC/Big 12 vs lower non-elite"
        elif hgroup == "SEC/Big 12" or agroup == "SEC/Big 12":
            matchup = "SEC/Big 12 involved"
        elif (hgroup == "Other conference without Top 10/CFP team"
              and agroup == "Other conference without Top 10/CFP team"):
            matchup = "Lower non-elite conferences only"
        elif season == 2026:
            matchup = "Other 2026 matchup; postseason status not known"
        else:
            matchup = "Other FBS matchup"
        matchup_groups.append(matchup)
    frame["home_conference_group"] = home_groups
    frame["away_conference_group"] = away_groups
    frame["conference_matchup_group"] = matchup_groups
    frame["home_model_favorite"] = None
    return frame


class Elo:
    def __init__(self):
        self.ratings = defaultdict(lambda: ELO_INITIAL)
        self.season = None

    def ensure_season(self, season):
        if self.season is None:
            self.season = int(season)
        elif int(season) > self.season:
            factor = 1.0 - ELO_OFFSEASON_REGRESSION
            for team in list(self.ratings.keys()):
                self.ratings[team] = ELO_INITIAL + (self.ratings[team] - ELO_INITIAL) * factor
            self.season = int(season)

    def probability(self, home_id, away_id, neutral):
        home_rating = self.ratings[home_id]
        away_rating = self.ratings[away_id]
        advantage = 0.0 if neutral else ELO_HOME_ADVANTAGE
        delta = home_rating + advantage - away_rating
        return 1.0 / (1.0 + 10.0 ** (-delta / 400.0))

    def update_day(self, games):
        deltas = defaultdict(float)
        for row in games.itertuples(index=False):
            self.ensure_season(row.season)
            expected = self.probability(row.home_team_id, row.away_team_id,
                                        row.neutral_site)
            actual = float(row.home_win)
            change = ELO_K * (actual - expected)
            deltas[row.home_team_id] += change
            deltas[row.away_team_id] -= change
        for team_id, change in deltas.items():
            self.ratings[team_id] += change


class HomeBase:
    def __init__(self):
        self.counts = {False: [0, 0], True: [0, 0]}

    def update(self, games):
        for row in games.itertuples(index=False):
            if not row.fbs_game:
                continue
            key = bool(row.neutral_site)
            self.counts[key][0] += int(row.home_win)
            self.counts[key][1] += 1

    def probability(self, neutral):
        wins, count = self.counts[bool(neutral)]
        return (wins + 1.0) / (count + 2.0)


def fit_margin_model(history, current_season):
    if history.empty:
        return {}, 0.0, 21.0
    team_ids = sorted(set(history.home_team_id.astype(int))
                      | set(history.away_team_id.astype(int)))
    team_index = {team_id: idx for idx, team_id in enumerate(team_ids)}
    rows = np.repeat(np.arange(len(history)), 3)
    cols = np.empty(len(history) * 3, dtype=np.int32)
    values = np.empty(len(history) * 3, dtype=np.float64)
    for i, row in enumerate(history.itertuples(index=False)):
        offset = i * 3
        cols[offset] = team_index[int(row.home_team_id)]
        cols[offset + 1] = team_index[int(row.away_team_id)]
        cols[offset + 2] = len(team_ids)
        values[offset] = 1.0
        values[offset + 1] = -1.0
        values[offset + 2] = 0.0 if row.neutral_site else 1.0
    design = sparse.coo_matrix(
        (values, (rows, cols)), shape=(len(history), len(team_ids) + 1)
    ).tocsr()
    years_ago = np.maximum(0, int(current_season) - history.season.to_numpy(dtype=int))
    weights = np.power(0.5, years_ago / STRENGTH_SEASON_HALF_LIFE)
    root_weight = np.sqrt(weights)
    weighted_design = design.multiply(root_weight[:, None]).tocsr()
    penalty = sparse.hstack((
        sparse.eye(len(team_ids), format="csr") * math.sqrt(STRENGTH_RIDGE),
        sparse.csr_matrix((len(team_ids), 1)),
    ), format="csr")
    augmented = sparse.vstack((weighted_design, penalty), format="csr")
    target = history.home_score.to_numpy(dtype=float) - history.away_score.to_numpy(dtype=float)
    augmented_target = np.concatenate((target * root_weight, np.zeros(len(team_ids))))
    solution = lsmr(augmented, augmented_target, atol=1e-6, btol=1e-6,
                    maxiter=max(300, len(team_ids) * 2))[0]
    ratings = {team_id: float(solution[idx]) for team_id, idx in team_index.items()}
    home_advantage = float(solution[-1])
    residual = target - design.dot(solution)
    fbs_fbs = history.fbs_game.to_numpy(dtype=bool)
    if fbs_fbs.any():
        sigma = float(np.std(residual[fbs_fbs]))
    else:
        sigma = float(np.std(residual))
    # Avoid converting a small in-sample residual into unjustifiably sharp odds.
    sigma = max(15.0, sigma)
    return ratings, home_advantage, sigma


def normal_probability(margin, sigma):
    return 0.5 * (1.0 + math.erf(margin / (sigma * math.sqrt(2.0))))


def make_predictions(events, first_evaluation_season):
    training = events[events.fbs_participant.astype(bool)].copy()
    evaluation = events[
        events.evaluation_population
        & events.season.ge(first_evaluation_season)
    ].copy()
    training = training.sort_values(["utc_date", "kickoff_utc", "game_id"]).reset_index(drop=True)
    evaluation = evaluation.sort_values(["utc_date", "kickoff_utc", "game_id"]).reset_index(drop=True)

    base = HomeBase()
    elo = Elo()
    eligible_history = []
    pred_rows = []
    cursor = 0
    training_records = list(training.itertuples(index=False))
    for game_date in sorted(evaluation.utc_date.unique()):
        embargo_cutoff = game_date - timedelta(days=1)
        new_records = []
        while cursor < len(training_records) and training_records[cursor].utc_date < embargo_cutoff:
            new_records.append(training_records[cursor])
            cursor += 1
        if new_records:
            new_frame = pd.DataFrame([r._asdict() for r in new_records])
            # Apply results only after predictions for every game on that date
            # have been formed. The one-day embargo ensures a result can be final.
            for eligible_date, day_games in new_frame.groupby("utc_date", sort=True):
                day_games = day_games.copy()
                base.update(day_games)
                elo.update_day(day_games)
                eligible_history.extend(day_games.to_dict("records"))

        today = evaluation[evaluation.utc_date.eq(game_date)]
        for row in today.itertuples(index=False):
            elo.ensure_season(row.season)
        history = pd.DataFrame(eligible_history)
        if not history.empty:
            strength, fitted_home_advantage, sigma = fit_margin_model(
                history, int(today.season.max())
            )
        else:
            strength, fitted_home_advantage, sigma = {}, 0.0, 21.0
        for row in today.itertuples(index=False):
            base_prob = base.probability(row.neutral_site)
            elo_prob = elo.probability(row.home_team_id, row.away_team_id,
                                       row.neutral_site)
            predicted_margin = (
                strength.get(row.home_team_id, 0.0)
                - strength.get(row.away_team_id, 0.0)
                + (0.0 if row.neutral_site else fitted_home_advantage)
            )
            margin_prob = normal_probability(predicted_margin, sigma)
            pred = row._asdict()
            pred.update({
                "model_version": MODEL_VERSION,
                "pregame_data_cutoff_utc": row.kickoff_utc.isoformat(),
                "history_embargo_days": 1,
                "training_games_available": len(eligible_history),
                "home_base_prob": base_prob,
                "elo_home_prob": elo_prob,
                "elo_rating_margin": (
                    elo.ratings[row.home_team_id] - elo.ratings[row.away_team_id]
                    + (0.0 if row.neutral_site else ELO_HOME_ADVANTAGE)
                ),
                "margin_home_prob": margin_prob,
                "predicted_score_margin": predicted_margin,
                "margin_sigma_points": sigma,
                "feature_set": "prior completed game outcomes/margins; venue neutral/home",
            })
            pred_rows.append(pred)

    forecasts = pd.DataFrame(pred_rows)
    if forecasts.empty:
        raise RuntimeError("no FBS-vs-FBS evaluation games were forecast")
    if forecasts.game_id.duplicated().any():
        raise RuntimeError("duplicate forecast game IDs")
    for column in MODEL_COLUMNS:
        forecasts[column] = forecasts[column].clip(1e-6, 1.0 - 1e-6)
    return forecasts


def score_metrics(rows, probability_column, target_column="home_win"):
    if rows.empty:
        return {"games": 0}
    p = rows[probability_column].to_numpy(dtype=float)
    y = rows[target_column].to_numpy(dtype=float)
    p = np.clip(p, 1e-12, 1.0 - 1e-12)
    brier = float(np.mean((p - y) ** 2))
    log_loss = float(np.mean(-(y * np.log(p) + (1.0 - y) * np.log(1.0 - p))))
    accuracy = float(np.mean((p >= 0.5) == y.astype(bool)))
    prevalence = float(np.mean(y))
    reliability = 0.0
    resolution = 0.0
    for lower in np.arange(0.0, 1.0, 0.1):
        mask = (p >= lower) & (p < lower + 0.1)
        if not mask.any():
            continue
        observed = float(np.mean(y[mask]))
        predicted = float(np.mean(p[mask]))
        weight = float(np.mean(mask))
        reliability += weight * (predicted - observed) ** 2
        resolution += weight * (observed - prevalence) ** 2
    return {
        "games": int(len(rows)),
        "brier": brier,
        "log_loss": log_loss,
        "accuracy": accuracy,
        "mean_predicted_home_win": float(np.mean(p)),
        "observed_home_win_rate": prevalence,
        "reliability_10bin": reliability,
        "resolution_10bin": resolution,
        "uncertainty": prevalence * (1.0 - prevalence),
    }


def bootstrap_brier_difference(rows, model_column, baseline_column,
                               replicates=BOOTSTRAP_REPLICATES,
                               seed=BOOTSTRAP_SEED):
    if len(rows) < 2:
        return None
    y = rows.home_win.to_numpy(dtype=float)
    p_model = rows[model_column].to_numpy(dtype=float)
    p_base = rows[baseline_column].to_numpy(dtype=float)
    difference = (p_model - y) ** 2 - (p_base - y) ** 2
    rng = np.random.default_rng(seed + sum(ord(ch) for ch in model_column)
                                + len(rows))
    estimates = np.empty(replicates, dtype=float)
    chunk_size = 100
    offset = 0
    while offset < replicates:
        count = min(chunk_size, replicates - offset)
        indices = rng.integers(0, len(difference), size=(count, len(difference)))
        estimates[offset:offset + count] = difference[indices].mean(axis=1)
        offset += count
    return {
        "difference": float(np.mean(difference)),
        "ci_low": float(np.quantile(estimates, 0.025)),
        "ci_high": float(np.quantile(estimates, 0.975)),
        "replicates": replicates,
    }


def build_metrics(forecasts):
    metric_rows = []
    period_rows = [
        ("Walk-forward 2023-2025", forecasts.season.between(2023, 2025)),
        ("2025 complete season", forecasts.season.eq(2025)),
        ("2026 current forward", forecasts.season.eq(2026)),
    ]
    for season in sorted(forecasts.season.unique()):
        period_rows.append(("Season %d" % season, forecasts.season.eq(season)))
    for period, mask in period_rows:
        subset = forecasts[mask]
        for model_column in MODEL_COLUMNS:
            metric_rows.append({
                "period": period,
                "slice": "All FBS-vs-FBS games",
                "model": MODEL_LABELS[model_column],
                "model_column": model_column,
                **score_metrics(subset, model_column),
            })

    slice_specs = [
        ("Local kickoff day", "day_group"),
        ("Game phase", "game_phase"),
        ("Conference matchup", "conference_matchup_group"),
        ("Home conference group", "home_conference_group"),
        ("Away conference group", "away_conference_group"),
    ]
    main = forecasts[forecasts.season.between(2023, 2025)]
    for label, column in slice_specs:
        for value, subset in main.groupby(column, dropna=False):
            if str(value) == "Unknown" and label == "Local kickoff day":
                pass
            for model_column in MODEL_COLUMNS:
                metric_rows.append({
                    "period": "Walk-forward 2023-2025",
                    "slice": "%s: %s" % (label, value),
                    "model": MODEL_LABELS[model_column],
                    "model_column": model_column,
                    **score_metrics(subset, model_column),
                })

    conference_names = {}
    for value in list(main.home_conference) + list(main.away_conference):
        key = normalized_conf(value)
        if key and key not in conference_names:
            conference_names[key] = str(value)
    for conference_key, conference_name in sorted(conference_names.items()):
        team_rows = []
        for row in main.itertuples(index=False):
            if normalized_conf(row.home_conference) == conference_key:
                team_row = row._asdict()
                team_row["team_win"] = int(row.home_win)
                team_rows.append(team_row)
            if normalized_conf(row.away_conference) == conference_key:
                team_row = row._asdict()
                team_row["team_win"] = 1 - int(row.home_win)
                for model_column in MODEL_COLUMNS:
                    team_row[model_column] = 1.0 - float(team_row[model_column])
                team_rows.append(team_row)
        conference_games = pd.DataFrame(team_rows)
        for model_column in MODEL_COLUMNS:
            metric_rows.append({
                "period": "Walk-forward 2023-2025",
                "slice": "Conference team: " + conference_name,
                "model": MODEL_LABELS[model_column],
                "model_column": model_column,
                **score_metrics(conference_games, model_column, "team_win"),
            })

    for model_column in MODEL_COLUMNS:
        favored = forecasts[model_column] >= 0.5
        for name, mask in (("Model selects home", favored), ("Model selects away", ~favored)):
            subset = forecasts[mask & forecasts.season.between(2023, 2025)]
            metric_rows.append({
                "period": "Walk-forward 2023-2025",
                "slice": "Favorite status: " + name,
                "model": MODEL_LABELS[model_column],
                "model_column": model_column,
                **score_metrics(subset, model_column),
            })

    for low, high, name in [
        (-float("inf"), -14.0, "Margin-model strength <= -14"),
        (-14.0, -7.0, "Margin-model strength -14 to -7"),
        (-7.0, 0.0, "Margin-model strength -7 to 0"),
        (0.0, 7.0, "Margin-model strength 0 to 7"),
        (7.0, 14.0, "Margin-model strength 7 to 14"),
        (14.0, float("inf"), "Margin-model strength >= 14"),
    ]:
        subset = main[(main.predicted_score_margin >= low)
                      & (main.predicted_score_margin < high)]
        for model_column in MODEL_COLUMNS:
            metric_rows.append({
                "period": "Walk-forward 2023-2025",
                "slice": name,
                "model": MODEL_LABELS[model_column],
                "model_column": model_column,
                **score_metrics(subset, model_column),
            })
    return pd.DataFrame(metric_rows)


def paired_comparisons(forecasts):
    rows = []
    periods = [
        ("Walk-forward 2023-2025", forecasts.season.between(2023, 2025)),
        ("2025 complete season", forecasts.season.eq(2025)),
        ("2026 current forward", forecasts.season.eq(2026)),
    ]
    for period, mask in periods:
        subset = forecasts[mask]
        for column, control_column in [
            ("elo_home_prob", "home_base_prob"),
            ("margin_home_prob", "home_base_prob"),
            ("margin_home_prob", "elo_home_prob"),
        ]:
            comparison = bootstrap_brier_difference(
                subset, column, control_column
            )
            rows.append({
                "period": period,
                "candidate": MODEL_LABELS[column],
                "control": MODEL_LABELS[control_column],
                "games": int(len(subset)),
                **(comparison or {}),
            })
    return pd.DataFrame(rows)


def calibration_rows(forecasts):
    rows = []
    periods = [
        ("Walk-forward 2023-2025", forecasts.season.between(2023, 2025)),
        ("2025 complete season", forecasts.season.eq(2025)),
        ("2026 current forward", forecasts.season.eq(2026)),
    ]
    for period, mask in periods:
        subset = forecasts[mask]
        for model_column in MODEL_COLUMNS:
            p = subset[model_column].to_numpy(dtype=float)
            y = subset.home_win.to_numpy(dtype=float)
            for bucket in range(10):
                lower, upper = bucket / 10.0, (bucket + 1) / 10.0
                inside = (p >= lower) & ((p < upper) if bucket < 9 else (p <= upper))
                if not inside.any():
                    continue
                rows.append({
                    "period": period,
                    "model": MODEL_LABELS[model_column],
                    "probability_bin": "%.1f-%.1f" % (lower, upper),
                    "games": int(inside.sum()),
                    "mean_predicted": float(np.mean(p[inside])),
                    "observed_home_win_rate": float(np.mean(y[inside])),
                })
    return pd.DataFrame(rows)


def fmt(value, digits=4):
    if value is None or pd.isna(value):
        return "—"
    return ("%%.%df" % digits) % float(value)


def markdown_table(rows, columns, headers):
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(col, "—")) for col in columns) + " |")
    return "\n".join(lines)


def build_report(forecasts, coverage, metrics, comparisons, calibration, report_path):
    generated = datetime.now(pytz.UTC).strftime("%Y-%m-%d %H:%M UTC")
    primary = forecasts
    overall_rows = []
    for season in sorted(primary.season.unique()):
        for model_column in MODEL_COLUMNS:
            m = score_metrics(primary[primary.season.eq(season)], model_column)
            overall_rows.append({
                "season": str(season),
                "model": MODEL_LABELS[model_column],
                "games": m["games"], "brier": fmt(m["brier"]),
                "log_loss": fmt(m["log_loss"]), "accuracy": fmt(m["accuracy"]),
            })
    all_rows = []
    for period, mask in [
        ("2023-2025", primary.season.between(2023, 2025)),
        ("2025 holdout", primary.season.eq(2025)),
        ("2026 forward", primary.season.eq(2026)),
    ]:
        for model_column in MODEL_COLUMNS:
            m = score_metrics(primary[mask], model_column)
            all_rows.append({
                "period": period, "model": MODEL_LABELS[model_column],
                "games": m["games"], "brier": fmt(m["brier"]),
                "log_loss": fmt(m["log_loss"]), "accuracy": fmt(m["accuracy"]),
                "calibration": "%s / %s" % (
                    fmt(m["mean_predicted_home_win"]),
                    fmt(m["observed_home_win_rate"])),
                "reliability": fmt(m["reliability_10bin"]),
                "resolution": fmt(m["resolution_10bin"]),
            })

    slice_rows = []
    chosen = metrics[
        metrics.period.eq("Walk-forward 2023-2025")
        & metrics.slice.isin([
            "Local kickoff day: Saturday", "Local kickoff day: Off-Saturday",
            "Local kickoff day: Unknown",
            "Conference matchup: SEC/Big 12 vs lower non-elite",
            "Conference matchup: Lower non-elite conferences only",
            "Conference matchup: SEC/Big 12 involved",
            "Game phase: Regular season", "Game phase: Conference championship",
            "Game phase: Bowl", "Game phase: Playoff",
        ])
    ]
    for row in chosen.itertuples(index=False):
        slice_rows.append({
            "slice": row.slice,
            "model": row.model,
            "games": row.games,
            "brier": fmt(getattr(row, "brier", None)),
            "log_loss": fmt(getattr(row, "log_loss", None)),
            "accuracy": fmt(getattr(row, "accuracy", None)),
        })

    strength_rows = []
    strength_metrics = metrics[
        metrics.period.eq("Walk-forward 2023-2025")
        & (metrics.slice.str.startswith("Favorite status:")
           | metrics.slice.str.startswith("Margin-model strength"))
    ]
    for row in strength_metrics.itertuples(index=False):
        strength_rows.append({
            "slice": row.slice,
            "model": row.model,
            "games": row.games,
            "brier": fmt(getattr(row, "brier", None)),
            "log_loss": fmt(getattr(row, "log_loss", None)),
            "accuracy": fmt(getattr(row, "accuracy", None)),
        })

    conference_rows = []
    conference_metrics = metrics[
        metrics.period.eq("Walk-forward 2023-2025")
        & metrics.slice.str.startswith("Conference team:")
    ]
    for row in conference_metrics.itertuples(index=False):
        conference_rows.append({
            "slice": row.slice,
            "model": row.model,
            "games": row.games,
            "brier": fmt(getattr(row, "brier", None)),
            "log_loss": fmt(getattr(row, "log_loss", None)),
            "accuracy": fmt(getattr(row, "accuracy", None)),
        })

    coverage_rows = []
    for row in coverage.itertuples(index=False):
        coverage_rows.append({
            "season": row.season,
            "schedule rows": row.all_schedule_rows,
            "FBS games": row.fbs_game_rows,
            "completed FBS-FBS": row.completed_fbs_vs_fbs,
            "completed FBS-FCS": row.fbs_vs_fcs_completed,
            "FBS final not marked complete in CFB": row.espn_final_without_cfb_completed,
            "not final/canceled": row.fbs_rows_canceled_or_not_final,
        })

    comparison_rows = []
    for row in comparisons.itertuples(index=False):
        comparison_rows.append({
            "period": row.period,
            "candidate": row.candidate,
            "control": row.control,
            "games": row.games,
            "Δ Brier": fmt(row.difference),
            "paired 95% interval": "[%s, %s]" % (fmt(row.ci_low), fmt(row.ci_high)),
        })

    saturday_games = int(primary[primary.season.between(2023, 2025)].day_group.eq("Saturday").sum())
    off_saturday_games = int(primary[primary.season.between(2023, 2025)].day_group.eq("Off-Saturday").sum())
    unknown_day_games = int(primary[primary.season.between(2023, 2025)].day_group.eq("Unknown").sum())
    total_2023_25 = int(primary.season.between(2023, 2025).sum())
    lower = primary[(primary.season.between(2023, 2025))
                    & primary.conference_matchup_group.eq("SEC/Big 12 vs lower non-elite")]
    elo_metrics = score_metrics(
        primary[primary.season.between(2023, 2025)], "elo_home_prob"
    )
    margin_metrics = score_metrics(
        primary[primary.season.between(2023, 2025)], "margin_home_prob"
    )
    margin_vs_elo = comparisons[
        comparisons.period.eq("Walk-forward 2023-2025")
        & comparisons.candidate.eq(MODEL_LABELS["margin_home_prob"])
        & comparisons.control.eq(MODEL_LABELS["elo_home_prob"])
    ].iloc[0]
    decision = (
        "Elo is the lead result-only baseline: Brier %s versus %s for the "
        "margin-strength probability. The paired margin-minus-Elo Brier "
        "difference is %s (95%% interval %s to %s), so the margin model does "
        "not establish an improvement on the primary metric. It also predicts "
        "a %s average home-win probability against a %s observed rate, showing "
        "material overprediction. Keep Elo and the base rate as benchmarks; "
        "do not add team-stat features yet. The next justified experiment is "
        "chronological probability calibration for margin strength, judged "
        "against frozen Elo on the same games."
    ) % (
        fmt(elo_metrics["brier"]), fmt(margin_metrics["brier"]),
        fmt(margin_vs_elo.difference), fmt(margin_vs_elo.ci_low),
        fmt(margin_vs_elo.ci_high),
        fmt(margin_metrics["mean_predicted_home_win"]),
        fmt(margin_metrics["observed_home_win_rate"]),
    )

    report = """# FBS Game-Winner Baseline — Phase 1

Generated: %s
Model version: `%s`
Research brief: `docs/BRIEF-fbs-game-prediction-research-plan.md`

## Result

This is the first reproducible, chronological game-winner benchmark. It forecasts the probability that the schedule's home team wins. It uses no player-prop, player, box-score, or play-by-play features. The 2022 season warms the models; evaluation begins in 2023. 2025 is evaluated across the full season with earlier 2025 results entering later forecasts only after the embargo. 2026 is a forward sample through the source snapshot dated 2026-10-17.

%s

Brier is the primary score; lower is better. Reliability and resolution use fixed 0.10 probability bins, with lower reliability error and higher resolution preferred. Calibration is shown as average predicted probability / actual home-win rate. The reported Brier decomposition terms are binned summaries; their sum approximates the Brier score.

## Season results

%s

## Data coverage and reconciliation

%s

- The all-division SportsDataverse `cfb_schedules` release supplies historical FBS membership (`fbs_game` / `fbs_participant`), season-specific conferences, schedule phase, neutral-site and venue IDs. The ESPN-native schedule supplies event home/away orientation, kickoff timestamps, final status and scores.
- All completed FBS-participant rows in 2022–25 joined to an ESPN schedule row. Seven 2022–24 FBS games have reversed home/away orientation between the two schedule releases; ESPN orientation and scores reconcile to the CFBD scores after swapping sides. The model uses that orientation and reorients conference and rank metadata by team ID.
- In 2024, one canceled FBS-vs-FBS game carries a 0–0 placeholder in the all-division schedule; it is excluded because ESPN does not mark it final.
- In the 2026 snapshot, 11 ESPN-final FBS-vs-FBS games were not yet marked completed by the all-division schedule. ESPN final rows are used for those outcomes; the source lag is visible in the coverage table.
- The 2026 schedule table is `cfb_schedules_2026_snapshot_20261017.parquet`, fetched separately to preserve the earlier cached file.
- Local Saturday classification uses the home team's IANA timezone for non-neutral games and a venue-ID timezone match for neutral sites. %d of %d evaluated 2023–25 games are Saturday, %d are off-Saturday, and %d have unknown local venue timezone and are excluded from those two slices.
- Lower-conference labels are descriptive, retrospective season groupings: non-SEC/Big 12 conferences with no Top-10-ranked team in schedule rank fields and no CFP participant. These labels are not model features. 2026 postseason status is unknown, so those games are not assigned to the lower-non-elite group.
- The cached betting releases contain spread/total fields but no timestamped moneyline prices. No market probability or market favorite label is used. Favorite/underdog error slices use each candidate model's own pregame pick.

## Paired Brier comparisons

Negative differences favor the candidate. Intervals are paired game-level bootstrap intervals (2,000 resamples); they do not account for dependence between games involving the same teams.

%s

## Saturday, conference, and phase slices (2023–25)

%s

The `SEC/Big 12 vs lower non-elite` slice contains %d games. Lower non-elite means the opposing conference had no Top-10-ranked team in the schedule rank fields and no CFP participant that season. This is a retrospective reporting label, never a prediction feature. Unknown-timezone neutral-site games remain separately visible.

Conference team-game rows below use each team's season-aligned conference. In same-conference matchups, both teams count as observations; probabilities and outcomes are converted to each team's win perspective.

%s

## Favorite and strength-difference slices (2023–25)

Favorite status is each model's own pregame pick. Margin bands use the opponent-adjusted model's predicted score-margin difference before kickoff.

%s

## Model definitions and leakage controls

1. **Historical home/neutral base rate:** expanding prior FBS-vs-FBS home-win rate, separated by neutral-site status, with a Beta(1,1) smoothing prior.
2. **Chronological Elo:** team ratings start at 1500; logistic scale 400; fixed 55-point home advantage (zero at neutral sites); K=20; 25%% offseason regression toward 1500; FBS-vs-FBS and FBS-vs-FCS outcomes update ratings.
3. **Opponent-adjusted margin strength:** ridge least-squares team ratings from previous score margins, with a fitted home-advantage term, fixed ridge penalty 15, and season weights halved per prior season. It trains on FBS-participant games and estimates probability with a normal margin CDF; the scale is the prior in-sample FBS-vs-FBS residual standard deviation, floored at 15 points.

For every UTC kickoff date, predictions are made before adding games kicked off on that date or the immediately preceding UTC date. The last eligible kickoff date is therefore at least 24 hours before the forecast date; this conservative date embargo avoids relying on unavailable final-whistle timestamps. Each CSV row records that game's actual kickoff as the prediction cutoff. Neutral games receive no standard home-field advantage. No random split or future season result enters a prediction. Predictions, cutoff, source phase, teams, actual scores, and model probabilities are in `research/fbs/fbs_game_winner_predictions.csv`.

## Limitations and next experiment

- The base-rate and Elo results are the cleanest first controls. Margin-strength probabilities rely on a normal approximation and an in-sample residual scale, so calibration is a known limitation; the paired results decide whether it merits further work.
- The current 2026 sample is incomplete and is not a full-season validation.
- Conference slices are uneven, and Saturday coverage omits neutral sites without a venue timezone in the available reference file.
- No timestamped historical moneyline data is available in the cached betting releases, so the sportsbook comparison is unavailable.
- **Decision:** %s

## Reproduction

`/root/legendarypicks/backend/venv/bin/python backend/fbs_game_winner_baseline.py`
""" % (
        generated, MODEL_VERSION,
        markdown_table(all_rows,
                       ["period", "model", "games", "brier", "log_loss", "accuracy", "calibration", "reliability", "resolution"],
                       ["Period", "Model", "Games", "Brier", "Log loss", "Accuracy", "Predicted / actual", "Reliability", "Resolution"]),
        markdown_table(overall_rows,
                       ["season", "model", "games", "brier", "log_loss", "accuracy"],
                       ["Season", "Model", "Games", "Brier", "Log loss", "Accuracy"]),
        markdown_table(coverage_rows,
                       ["season", "schedule rows", "FBS games", "completed FBS-FBS", "completed FBS-FCS", "FBS final not marked complete in CFB", "not final/canceled"],
                       ["Season", "All schedule rows", "FBS-vs-FBS scheduled", "Completed FBS-vs-FBS", "Completed FBS-vs-FCS", "ESPN final / CFB incomplete", "Canceled or not final"]),
        saturday_games, total_2023_25, off_saturday_games, unknown_day_games,
        markdown_table(comparison_rows,
                       ["period", "candidate", "control", "games", "Δ Brier", "paired 95% interval"],
                       ["Period", "Candidate", "Control", "Games", "Δ Brier (candidate minus control)", "95% interval"]),
        markdown_table(slice_rows,
                       ["slice", "model", "games", "brier", "log_loss", "accuracy"],
                       ["Slice", "Model", "Games", "Brier", "Log loss", "Accuracy"]),
        len(lower),
        markdown_table(conference_rows,
                       ["slice", "model", "games", "brier", "log_loss", "accuracy"],
                       ["Conference team-games", "Model", "Team-games", "Brier", "Log loss", "Accuracy"]),
        markdown_table(strength_rows,
                       ["slice", "model", "games", "brier", "log_loss", "accuracy"],
                       ["Slice", "Model", "Games", "Brier", "Log loss", "Accuracy"]),
        decision,
    )
    with open(report_path, "w", encoding="utf-8") as output:
        output.write(report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "research", "fbs", "parquet"))
    parser.add_argument("--output-dir", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "research", "fbs"))
    parser.add_argument("--seasons", default="2022,2023,2024,2025,2026")
    args = parser.parse_args()
    seasons = [int(part.strip()) for part in args.seasons.split(",") if part.strip()]
    os.makedirs(args.output_dir, exist_ok=True)

    events, coverage, _, _ = load_events(args.data_dir, seasons)
    forecasts = make_predictions(events, FIRST_EVALUATION_SEASON)
    metrics = build_metrics(forecasts)
    comparisons = paired_comparisons(forecasts)
    calibration = calibration_rows(forecasts)

    forecasts_path = os.path.join(args.output_dir, "fbs_game_winner_predictions.csv")
    metrics_path = os.path.join(args.output_dir, "fbs_game_winner_metrics.csv")
    comparisons_path = os.path.join(args.output_dir, "fbs_game_winner_paired_comparisons.csv")
    calibration_path = os.path.join(args.output_dir, "fbs_game_winner_calibration.csv")
    report_path = os.path.join(args.output_dir, "REPORT-FBS-GAME-WINNER-BASELINE-20261017.md")

    export = forecasts.copy()
    export["kickoff_utc"] = export.kickoff_utc.map(lambda value: value.isoformat())
    export["utc_date"] = export.utc_date.map(str)
    columns = [
        "game_id", "kickoff_utc", "pregame_data_cutoff_utc", "season",
        "season_type", "game_phase", "home_team_id", "home_team",
        "home_conference", "away_team_id", "away_team", "away_conference",
        "neutral_site", "venue", "kickoff_local", "day_group", "home_rank",
        "away_rank", "home_score", "away_score", "home_win",
        "conference_matchup_group", "home_conference_group",
        "away_conference_group", "home_base_prob", "elo_home_prob",
        "elo_rating_margin", "margin_home_prob", "predicted_score_margin",
        "margin_sigma_points", "training_games_available", "history_embargo_days",
        "feature_set", "model_version", "result_source",
    ]
    export[columns].to_csv(forecasts_path, index=False, quoting=csv.QUOTE_MINIMAL)
    metrics.to_csv(metrics_path, index=False)
    comparisons.to_csv(comparisons_path, index=False)
    calibration.to_csv(calibration_path, index=False)
    build_report(forecasts, coverage, metrics, comparisons, calibration, report_path)

    print("wrote %d forecasts across seasons %s" % (len(forecasts), ",".join(map(str, seasons))))
    for season in sorted(forecasts.season.unique()):
        print("  %d: %d FBS-vs-FBS games" % (season, int(forecasts.season.eq(season).sum())))
    print("report: %s" % report_path)
    print("predictions: %s" % forecasts_path)
    print("metrics: %s" % metrics_path)
    print("paired comparisons: %s" % comparisons_path)
    print("calibration: %s" % calibration_path)


if __name__ == "__main__":
    main()
