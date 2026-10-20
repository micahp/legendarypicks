#!/usr/bin/env python3
"""Run the FBS game-winner Phase 1 ladder on the local schedule releases.

The input loader is reused from fbs_game_winner_baseline.py so that the
SportsDataverse membership flags, ESPN home/away orientation, and cross-source
score checks remain identical to the already-audited local data path. This
module implements the revised G0-G3 ladder and writes a separate, reproducible
result set without replacing the earlier game-winner report.

Run from the repository root:
  /root/legendarypicks/backend/venv/bin/python backend/fbs_game_winner_phase1.py
"""
import argparse
import csv
import hashlib
import math
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import fbs_game_winner_baseline as source_loader


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "research/fbs/parquet"
DEFAULT_OUT_DIR = ROOT / "research/fbs"
SEASONS = (2022, 2023, 2024, 2025, 2026)
RUN_TAG = "20261017"
MODEL_COLUMNS = {
    "G0": "p_g0_home_win",
    "G1": "p_g1_home_win",
    "G2": "p_g2_home_win",
    "G3": "p_g3_home_win",
}
MODEL_LABELS = {
    "G0": "Constant 0.50",
    "G1": "Prior home-win rate",
    "G2": "Chronological Elo + home field",
    "G3": "Margin-aware Elo",
}
ELO_INITIAL = 1500.0
ELO_SCALE = 400.0
ELO_HOME_ADVANTAGE = 55.0
ELO_K = 20.0
ELO_OFFSEASON_REGRESSION = 0.25
RESULT_LAG_HOURS = 24
BOOTSTRAP_REPLICATES = 2000
BOOTSTRAP_SEED = 20261017
CALIBRATION_BINS = 10


class PriorHomeRate:
    """Beta(1,1)-smoothed prior home rate, tracked separately by venue type."""

    def __init__(self):
        self.wins = {False: 0, True: 0}
        self.games = {False: 0, True: 0}

    def probability(self, neutral):
        neutral = bool(neutral)
        return (self.wins[neutral] + 1.0) / (self.games[neutral] + 2.0)

    def update_group(self, games):
        for game in games:
            neutral = bool(game.neutral_site)
            self.wins[neutral] += int(game.home_win)
            self.games[neutral] += 1


class Elo:
    """Fixed-parameter Elo; ratings update only after a prior kickoff group."""

    def __init__(self, margin_aware=False):
        self.ratings = defaultdict(lambda: ELO_INITIAL)
        self.season = None
        self.margin_aware = margin_aware

    def ensure_season(self, season):
        season = int(season)
        if self.season is None:
            self.season = season
            return
        if season < self.season:
            raise ValueError("chronological Elo received an earlier season")
        if season > self.season:
            factor = 1.0 - ELO_OFFSEASON_REGRESSION
            for team_id in list(self.ratings):
                self.ratings[team_id] = (
                    ELO_INITIAL + (self.ratings[team_id] - ELO_INITIAL) * factor
                )
            self.season = season

    def rating_difference(self, home_id, away_id, neutral):
        advantage = 0.0 if neutral else ELO_HOME_ADVANTAGE
        return self.ratings[home_id] + advantage - self.ratings[away_id]

    def probability(self, home_id, away_id, neutral):
        difference = self.rating_difference(home_id, away_id, neutral)
        return 1.0 / (1.0 + 10.0 ** (-difference / ELO_SCALE))

    def update_group(self, games):
        changes = defaultdict(float)
        for game in games:
            self.ensure_season(game.season)
            difference = self.rating_difference(
                game.home_team_id, game.away_team_id, game.neutral_site
            )
            expected = 1.0 / (1.0 + 10.0 ** (-difference / ELO_SCALE))
            actual = float(game.home_win)
            multiplier = 1.0
            if self.margin_aware:
                margin = abs(int(game.home_score) - int(game.away_score))
                multiplier = (
                    math.log1p(margin)
                    * 2.2
                    / (2.2 + 0.001 * abs(difference))
                )
            change = ELO_K * multiplier * (actual - expected)
            changes[game.home_team_id] += change
            changes[game.away_team_id] -= change
        for team_id, change in changes.items():
            self.ratings[team_id] += change


def utc_iso(value):
    if value is None or pd.isna(value):
        return ""
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    return stamp.tz_convert("UTC").isoformat().replace("+00:00", "Z")


def week_start_utc(value):
    stamp = pd.Timestamp(value).tz_convert("UTC")
    monday = stamp.normalize() - pd.Timedelta(days=stamp.weekday())
    return monday.date().isoformat()


def schedule_input_paths(data_dir, seasons):
    paths = []
    for season in seasons:
        paths.extend([
            Path(source_loader.season_schedule_path(str(data_dir), season)),
            Path(data_dir) / ("espn_schedule_%d.parquet" % season),
            Path(data_dir) / ("cfb_team_info_%d.parquet" % season),
        ])
    return paths


def hash_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_source_manifest(data_dir, seasons, out_path):
    roles = ("FBS membership, season, phase, and result cross-check",
             "kickoff, home/away orientation, final status, and score",
             "team metadata required by the audited source loader")
    rows = []
    for index, path in enumerate(schedule_input_paths(data_dir, seasons)):
        if not path.is_file():
            raise FileNotFoundError("required input missing: %s" % path)
        try:
            display_path = str(path.relative_to(ROOT))
        except ValueError:
            display_path = str(path)
        rows.append({
            "path": display_path,
            "file": path.name,
            "bytes": path.stat().st_size,
            "sha256": hash_file(path),
            "role": roles[index % 3],
        })
    pd.DataFrame(rows).to_csv(out_path, index=False)
    return rows


def source_coverage(data_dir, seasons, coverage, season_schedules, events):
    rows = []
    eligible = events[events.evaluation_population.astype(bool)]
    for cover in coverage.to_dict("records"):
        season = int(cover["season"])
        cfb = season_schedules[season]
        espn_path = Path(data_dir) / ("espn_schedule_%d.parquet" % season)
        espn = pd.read_parquet(espn_path)
        joined = cfb.merge(
            espn, on="game_id", how="left", suffixes=("_cfb", "_espn"),
            validate="one_to_one", indicator=True
        )
        fbs = joined[joined.fbs_game.fillna(False)].copy()
        division_known = cfb.home_division.notna() & cfb.away_division.notna()
        home_division_is_fbs = cfb.home_division.astype(str).str.casefold().eq("fbs")
        away_division_is_fbs = cfb.away_division.astype(str).str.casefold().eq("fbs")
        division_says_fbs_game = home_division_is_fbs & away_division_is_fbs
        division_says_fbs_participant = home_division_is_fbs | away_division_is_fbs
        fbs_membership_disagreements = int((
            cfb.loc[division_known, "fbs_game"].fillna(False).astype(bool).to_numpy()
            != division_says_fbs_game[division_known].to_numpy()
        ).sum())
        participant_membership_disagreements = int((
            cfb.loc[division_known, "fbs_participant"].fillna(False).astype(bool).to_numpy()
            != division_says_fbs_participant[division_known].to_numpy()
        ).sum())
        final = fbs[
            fbs.status_espn.eq("STATUS_FINAL")
            & fbs.home_score.notna()
            & fbs.away_score.notna()
        ].copy()
        score_rows = final[
            final.home_points.notna() & final.away_points.notna()
        ]
        aligned_matches = 0
        unresolved_teams = 0
        conflicts = 0
        for game in final.itertuples(index=False):
            c_home = game.home_id_cfb
            c_away = game.away_id_cfb
            e_home = game.home_id_espn
            e_away = game.away_id_espn
            if pd.isna(c_home) or pd.isna(c_away) or pd.isna(e_home) or pd.isna(e_away):
                unresolved_teams += 1
                continue
            if pd.isna(game.home_points) or pd.isna(game.away_points):
                continue
            if int(c_home) == int(e_home) and int(c_away) == int(e_away):
                expected = (float(game.home_points), float(game.away_points))
            elif int(c_home) == int(e_away) and int(c_away) == int(e_home):
                expected = (float(game.away_points), float(game.home_points))
            else:
                unresolved_teams += 1
                continue
            observed = (float(game.home_score), float(game.away_score))
            if expected == observed:
                aligned_matches += 1
            else:
                conflicts += 1
        season_eligible = eligible[eligible.season.eq(season)]
        nonfinal = fbs[~(
            fbs.status_espn.eq("STATUS_FINAL")
            & fbs.home_score.notna()
            & fbs.away_score.notna()
        )]
        rows.append({
            **cover,
            "eligible_forecasts": int(len(season_eligible)),
            "fbs_membership_disagreements": fbs_membership_disagreements,
            "fbs_participant_disagreements": participant_membership_disagreements,
            "cross_season_duplicate_event_rows": int(cover.get("cross_season_duplicate_event_rows", 0)),
            "scheduled_fbs_vs_fbs": int(len(fbs)),
            "completed_fbs_vs_fbs_source_rows": int(len(final)),
            "completed_fbs_vs_fcs_excluded": int(cover.get("fbs_vs_fcs_completed", 0)),
            "notfinal_fbs_vs_fbs": int(len(fbs) - len(final)),
            "home_site_games": int((~season_eligible.neutral_site.astype(bool)).sum()),
            "neutral_site_games": int(season_eligible.neutral_site.astype(bool).sum()),
            "first_eligible_kickoff_utc": (
                utc_iso(season_eligible.kickoff_utc.min()) if len(season_eligible) else ""
            ),
            "last_eligible_kickoff_utc": (
                utc_iso(season_eligible.kickoff_utc.max()) if len(season_eligible) else ""
            ),
            "nonfinal_in_progress": int(nonfinal.status_espn.eq("STATUS_IN_PROGRESS").sum()),
            "nonfinal_canceled": int(nonfinal.status_espn.eq("STATUS_CANCELED").sum()),
            "nonfinal_no_espn_schedule_row": int((nonfinal._merge != "both").sum()),
            "cfbd_score_pairs_available": int(len(score_rows)),
            "cfbd_score_pairs_agree": aligned_matches,
            "cfbd_score_conflicts": conflicts,
            "eligible_rows_unresolved_team_ids": int(
                season_eligible.home_team_id.isna().sum()
                + season_eligible.away_team_id.isna().sum()
            ),
            "fbs_vs_fbs_unresolved_team_ids_excluded": int(unresolved_teams),
            "excluded_unresolved_team_ids": int(cover.get("excluded_unresolved_team_ids", 0)),
            "excluded_ties_without_winner": int(cover.get("excluded_ties_without_winner", 0)),
            "excluded_missing_kickoff": int(cover.get("excluded_missing_kickoff", 0)),
            "duplicate_schedule_rows": int(cover.get("duplicate_schedule_rows", 0)),
            "missing_schedule_ids": int(cover.get("missing_schedule_ids", 0)),
            "duplicate_espn_rows": int(cover.get("duplicate_espn_rows", 0)),
            "missing_espn_game_ids": int(cover.get("missing_espn_game_ids", 0)),
            "cross_season_duplicate_event_rows": int(cover.get("cross_season_duplicate_event_rows", 0)),
            "schedule_duplicate_ids": int(
                len(cfb) - cfb.game_id.astype(str).nunique()
            ),
            "espn_duplicate_ids": int(
                len(espn) - espn.game_id.astype(str).nunique()
            ),
        })
    result = pd.DataFrame(rows)
    if int(result.cfbd_score_conflicts.sum()) != 0:
        raise ValueError("CFBD/ESPN final-score mismatch; refusing to score forecasts")
    return result


def make_forecasts(events):
    eligible = events[events.evaluation_population.astype(bool)].copy()
    eligible = eligible.sort_values(
        ["kickoff_utc", "season", "game_id"]
    ).reset_index(drop=True)
    if eligible.empty:
        raise ValueError("no completed FBS-vs-FBS games in the selected seasons")
    if eligible.game_id.astype(str).duplicated().any():
        raise ValueError("eligible FBS-vs-FBS game IDs are not unique")
    if (eligible.home_score == eligible.away_score).any():
        raise ValueError("completed tied game has no binary winner under the brief")

    records = list(eligible.itertuples(index=False))
    prior_rate = PriorHomeRate()
    elo = Elo(margin_aware=False)
    margin_elo = Elo(margin_aware=True)
    cursor = 0
    prior_game_count = 0
    prior_latest_kickoff = None
    forecast_rows = []
    index = 0
    while index < len(records):
        kickoff = pd.Timestamp(records[index].kickoff_utc).to_pydatetime()
        cutoff = kickoff - timedelta(hours=RESULT_LAG_HOURS)

        # A final result is treated as available only after its kickoff has been
        # at least 24 hours old. The source has no final-whistle timestamp.
        while cursor < len(records):
            history_kickoff = pd.Timestamp(records[cursor].kickoff_utc).to_pydatetime()
            if not history_kickoff < cutoff:
                break
            end = cursor + 1
            while end < len(records):
                next_kickoff = pd.Timestamp(records[end].kickoff_utc).to_pydatetime()
                if next_kickoff != history_kickoff:
                    break
                end += 1
            history_group = records[cursor:end]
            group_seasons = {int(game.season) for game in history_group}
            if len(group_seasons) != 1:
                raise ValueError("one kickoff timestamp spans multiple season keys")
            prior_rate.update_group(history_group)
            elo.update_group(history_group)
            margin_elo.update_group(history_group)
            prior_game_count += len(history_group)
            prior_latest_kickoff = history_kickoff
            cursor = end

        end_index = index + 1
        while end_index < len(records):
            next_kickoff = pd.Timestamp(records[end_index].kickoff_utc).to_pydatetime()
            if next_kickoff != kickoff:
                break
            end_index += 1
        prediction_group = records[index:end_index]
        group_seasons = {int(game.season) for game in prediction_group}
        if len(group_seasons) != 1:
            raise ValueError("one kickoff timestamp spans multiple season keys")
        current_season = next(iter(group_seasons))
        elo.ensure_season(current_season)
        margin_elo.ensure_season(current_season)

        for game in prediction_group:
            if prior_latest_kickoff is not None and not prior_latest_kickoff < cutoff:
                raise ValueError("as-of violation: prior result is not before cutoff")
            g1_neutral = bool(game.neutral_site)
            elo_gap = elo.rating_difference(
                game.home_team_id, game.away_team_id, game.neutral_site
            )
            margin_gap = margin_elo.rating_difference(
                game.home_team_id, game.away_team_id, game.neutral_site
            )
            record = game._asdict()
            record.update({
                "model_version": "fbs-game-winner-g0-g3-v1-20261017",
                "evaluation_role": (
                    "2025_out_of_time_holdout" if int(game.season) == 2025
                    else "2026_walk_forward" if int(game.season) == 2026
                    else "historical_walk_forward"
                ),
                "home_fbs_member_in_season": bool(game.fbs_game),
                "away_fbs_member_in_season": bool(game.fbs_game),
                "kickoff_utc": utc_iso(kickoff),
                "result_information_cutoff_utc": utc_iso(cutoff),
                "result_lag_hours": RESULT_LAG_HOURS,
                "history_latest_kickoff_utc": utc_iso(prior_latest_kickoff),
                "prior_eligible_game_count": prior_game_count,
                "prior_same_site_game_count": prior_rate.games[g1_neutral],
                "prior_same_site_home_wins": prior_rate.wins[g1_neutral],
                "elo_home_rating": float(elo.ratings[game.home_team_id]),
                "elo_away_rating": float(elo.ratings[game.away_team_id]),
                "elo_home_advantage_points": 0.0 if game.neutral_site else ELO_HOME_ADVANTAGE,
                "elo_rating_difference": float(elo_gap),
                "margin_elo_rating_difference": float(margin_gap),
                "p_g0_home_win": 0.5,
                "p_g1_home_win": prior_rate.probability(g1_neutral),
                "p_g2_home_win": elo.probability(
                    game.home_team_id, game.away_team_id, game.neutral_site
                ),
                "p_g3_home_win": margin_elo.probability(
                    game.home_team_id, game.away_team_id, game.neutral_site
                ),
                "week_start_utc": week_start_utc(kickoff),
                "history_rule": "completed FBS-vs-FBS games with kickoff < kickoff minus 24h",
            })
            forecast_rows.append(record)
        index = end_index

    forecasts = pd.DataFrame(forecast_rows)
    for model_id, probability_column in MODEL_COLUMNS.items():
        values = forecasts[probability_column].to_numpy(dtype=float)
        if not np.isfinite(values).all() or ((values < 0.0) | (values > 1.0)).any():
            raise ValueError("invalid probability in %s" % model_id)
    if not np.all(forecasts.p_g0_home_win.to_numpy(dtype=float) == 0.5):
        raise ValueError("G0 is not exactly 0.50")
    if len(forecasts) != len(eligible) or forecasts.game_id.astype(str).duplicated().any():
        raise ValueError("forecast ledger is not one row per eligible game")
    return forecasts


def score_metrics(rows, probability_column):
    if rows.empty:
        return {"games": 0}
    p = rows[probability_column].to_numpy(dtype=float)
    y = rows.home_win.to_numpy(dtype=float)
    p_safe = np.clip(p, 1e-15, 1.0 - 1e-15)
    brier = float(np.mean((p - y) ** 2))
    log_loss = float(np.mean(-(y * np.log(p_safe) + (1.0 - y) * np.log(1.0 - p_safe))))
    prevalence = float(np.mean(y))
    reliability = 0.0
    resolution = 0.0
    for bin_number in range(CALIBRATION_BINS):
        lower = bin_number / CALIBRATION_BINS
        upper = (bin_number + 1) / CALIBRATION_BINS
        inside = (p >= lower) & ((p < upper) if bin_number < CALIBRATION_BINS - 1 else (p <= upper))
        if not inside.any():
            continue
        weight = float(np.mean(inside))
        observed = float(np.mean(y[inside]))
        predicted = float(np.mean(p[inside]))
        reliability += weight * (predicted - observed) ** 2
        resolution += weight * (observed - prevalence) ** 2
    return {
        "games": int(len(rows)),
        "brier": brier,
        "brier_skill_vs_coin_flip": 1.0 - brier / 0.25,
        "log_loss": log_loss,
        "accuracy": float(np.mean((p >= 0.5) == y.astype(bool))),
        "mean_predicted_home_win": float(np.mean(p)),
        "observed_home_win_rate": prevalence,
        "reliability_10bin": reliability,
        "resolution_10bin": resolution,
        "uncertainty": prevalence * (1.0 - prevalence),
    }


def make_periods(forecasts):
    periods = [("all_walk_forward_2022_2026", forecasts)]
    for season in SEASONS:
        subset = forecasts[forecasts.season.eq(season)]
        periods.append(("season_%d" % season, subset))
    return periods


def build_metrics(forecasts):
    rows = []
    for period, subset in make_periods(forecasts):
        for model_id, probability_column in MODEL_COLUMNS.items():
            rows.append({
                "period": period,
                "season": int(subset.season.iloc[0]) if subset.season.nunique() == 1 else "all",
                "model_id": model_id,
                "model": MODEL_LABELS[model_id],
                **score_metrics(subset, probability_column),
            })
    return pd.DataFrame(rows)


def block_bootstrap_delta(rows, candidate_column, control_column, replicates):
    if len(rows) < 2:
        return None
    work = rows[["season", "week_start_utc", "home_win", candidate_column, control_column]].copy()
    y = work.home_win.to_numpy(dtype=float)
    candidate = work[candidate_column].to_numpy(dtype=float)
    control = work[control_column].to_numpy(dtype=float)
    work["delta_sum_item"] = (candidate - y) ** 2 - (control - y) ** 2
    block_stats = (
        work.groupby(["season", "week_start_utc"], sort=True)
        .delta_sum_item.agg(["sum", "count"])
        .reset_index()
    )
    seed_text = "%s|%s|%s|%d" % (
        candidate_column, control_column, ",".join(map(str, sorted(rows.season.unique()))), len(rows)
    )
    seed = BOOTSTRAP_SEED + int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    by_season = []
    for _, season_blocks in block_stats.groupby("season", sort=True):
        sums = season_blocks["sum"].to_numpy(dtype=float)
        counts = season_blocks["count"].to_numpy(dtype=float)
        by_season.append((sums, counts))
    estimates = np.empty(replicates, dtype=float)
    for replicate in range(replicates):
        total_sum = 0.0
        total_count = 0.0
        for sums, counts in by_season:
            selected = rng.integers(0, len(sums), size=len(sums))
            total_sum += float(sums[selected].sum())
            total_count += float(counts[selected].sum())
        estimates[replicate] = total_sum / total_count
    observed = float(work.delta_sum_item.sum() / len(work))
    return {
        "delta_brier_candidate_minus_control": observed,
        "ci95_low": float(np.quantile(estimates, 0.025)),
        "ci95_high": float(np.quantile(estimates, 0.975)),
        "bootstrap_method": "paired UTC calendar-week block bootstrap, season-stratified",
        "bootstrap_blocks": int(len(block_stats)),
        "bootstrap_replicates": int(replicates),
    }


def build_paired_comparisons(forecasts, replicates):
    rows = []
    adjacent = (
        ("G1", "G0"),
        ("G2", "G0"), ("G2", "G1"),
        ("G3", "G0"), ("G3", "G1"), ("G3", "G2"),
    )
    for period, subset in make_periods(forecasts):
        for candidate_id, control_id in adjacent:
            candidate_column = MODEL_COLUMNS[candidate_id]
            control_column = MODEL_COLUMNS[control_id]
            rows.append({
                "period": period,
                "candidate_id": candidate_id,
                "candidate": MODEL_LABELS[candidate_id],
                "control_id": control_id,
                "control": MODEL_LABELS[control_id],
                "games": int(len(subset)),
                **(block_bootstrap_delta(
                    subset, candidate_column, control_column, replicates
                ) or {}),
            })
    return pd.DataFrame(rows)


def build_calibration(forecasts):
    rows = []
    for period, subset in make_periods(forecasts):
        for model_id, probability_column in MODEL_COLUMNS.items():
            p = subset[probability_column].to_numpy(dtype=float)
            y = subset.home_win.to_numpy(dtype=float)
            for bin_number in range(CALIBRATION_BINS):
                lower = bin_number / CALIBRATION_BINS
                upper = (bin_number + 1) / CALIBRATION_BINS
                inside = (p >= lower) & (
                    (p < upper) if bin_number < CALIBRATION_BINS - 1 else (p <= upper)
                )
                if not inside.any():
                    continue
                rows.append({
                    "period": period,
                    "model_id": model_id,
                    "model": MODEL_LABELS[model_id],
                    "bin_lower": lower,
                    "bin_upper": upper,
                    "games": int(inside.sum()),
                    "mean_predicted": float(np.mean(p[inside])),
                    "observed_home_win_rate": float(np.mean(y[inside])),
                })
    return pd.DataFrame(rows)


def build_weekly_metrics(forecasts):
    rows = []
    for (season, week), subset in forecasts.groupby(["season", "week_start_utc"], sort=True):
        for model_id, probability_column in MODEL_COLUMNS.items():
            rows.append({
                "season": int(season),
                "week_start_utc": week,
                "model_id": model_id,
                "model": MODEL_LABELS[model_id],
                **score_metrics(subset, probability_column),
            })
    return pd.DataFrame(rows)


def build_market_coverage(data_dir, forecasts):
    rows = []
    for season in (2025, 2026):
        path = Path(data_dir) / ("betting_%d.parquet" % season)
        if not path.is_file():
            rows.append({"season": season, "file": path.name, "file_present": False})
            continue
        betting = pd.read_parquet(path)
        subset = forecasts[forecasts.season.eq(season)]
        betting["game_id_key"] = betting.game_id.astype(str)
        game_ids = set(subset.game_id.astype(str))
        matched = betting[betting.game_id_key.isin(game_ids)]
        moneyline_fields = [
            column for column in betting.columns
            if "money" in column.casefold() or column.casefold() in ("ml", "home_ml", "away_ml")
        ]
        timestamp_fields = [
            column for column in betting.columns
            if "time" in column.casefold() or "date" in column.casefold()
        ]
        rows.append({
            "season": season,
            "file": path.name,
            "file_present": True,
            "eligible_games": int(len(subset)),
            "matched_betting_rows": int(len(matched)),
            "matched_nonnull_spread_rows": int(matched.game_spread.notna().sum()),
            "moneyline_fields": ",".join(moneyline_fields),
            "timestamp_fields": ",".join(timestamp_fields),
            "valid_asof_moneyline_rows": 0 if not moneyline_fields or not timestamp_fields else None,
            "provider_values": ",".join(sorted(matched.odds_source.dropna().astype(str).unique()))
            if "odds_source" in matched else "",
        })
    return pd.DataFrame(rows)


def fmt(value, digits=4):
    if value is None or pd.isna(value):
        return "—"
    return ("%.*f" % (digits, float(value)))


def metrics_markdown(metrics, period):
    selected = metrics[metrics.period.eq(period)]
    lines = [
        "| Model | Games | Brier | Coin-flip BSS | Log loss | Accuracy | Mean P(home) | Home win rate | Reliability | Resolution |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in selected.itertuples(index=False):
        lines.append(
            "| %s | %d | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                row.model, row.games, fmt(row.brier), fmt(row.brier_skill_vs_coin_flip),
                fmt(row.log_loss), fmt(row.accuracy), fmt(row.mean_predicted_home_win),
                fmt(row.observed_home_win_rate), fmt(row.reliability_10bin),
                fmt(row.resolution_10bin),
            )
        )
    return "\n".join(lines)


def coverage_markdown(coverage):
    lines = [
        "| Season | Scheduled FBS-vs-FBS | Completed eligible | Completed FBS-vs-FCS excluded | Not final | In progress | Canceled | No ESPN schedule row | FBS-vs-FBS unresolved IDs excluded | Duplicate schedule/ESPN rows | CFBD score pairs checked / agree |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in coverage.itertuples(index=False):
        lines.append(
            "| %d | %d | %d | %d | %d | %d | %d | %d | %d | %d | %d / %d |" % (
                row.season, row.scheduled_fbs_vs_fbs, row.eligible_forecasts,
                row.completed_fbs_vs_fcs_excluded, row.notfinal_fbs_vs_fbs,
                row.nonfinal_in_progress, row.nonfinal_canceled,
                row.nonfinal_no_espn_schedule_row, row.fbs_vs_fbs_unresolved_team_ids_excluded,
                row.duplicate_schedule_rows + row.duplicate_espn_rows,
                row.cfbd_score_pairs_available,
                row.cfbd_score_pairs_agree,
            )
        )
    return "\n".join(lines)


def paired_markdown(comparisons, period):
    selected = comparisons[comparisons.period.eq(period)]
    lines = [
        "| Candidate vs control | Games | Δ Brier (candidate − control) | 95% time-block interval |",
        "|---|---:|---:|---:|",
    ]
    for row in selected.itertuples(index=False):
        lines.append(
            "| %s vs %s | %d | %s | [%s, %s] |" % (
                row.candidate_id, row.control_id, row.games,
                fmt(row.delta_brier_candidate_minus_control), fmt(row.ci95_low), fmt(row.ci95_high),
            )
        )
    return "\n".join(lines)


def calibration_plot(calibration, out_path):
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/lp-fbs-mplconfig")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharex=True, sharey=True)
    selections = (("season_2025", "2025 out-of-time holdout"),
                  ("season_2026", "2026 walk-forward through cached finals"))
    colors = {"G0": "#6b7280", "G1": "#2563eb", "G2": "#059669", "G3": "#d97706"}
    for ax, (period, title) in zip(axes, selections):
        ax.plot([0, 1], [0, 1], color="#9ca3af", linestyle="--", linewidth=1, label="Perfect calibration")
        for model_id in MODEL_COLUMNS:
            rows = calibration[
                calibration.period.eq(period) & calibration.model_id.eq(model_id)
            ]
            if rows.empty:
                continue
            sizes = rows.games.to_numpy(dtype=float)
            ax.plot(
                rows.mean_predicted, rows.observed_home_win_rate,
                marker="o", linewidth=1.6, color=colors[model_id],
                label=MODEL_LABELS[model_id],
            )
            for x, y, n in zip(rows.mean_predicted, rows.observed_home_win_rate, sizes):
                ax.annotate(str(int(n)), (x, y), xytext=(3, 3), textcoords="offset points", fontsize=7,
                            color=colors[model_id])
        ax.set_title(title)
        ax.set_xlabel("Mean forecast P(home win)")
        ax.grid(alpha=0.22)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
    axes[0].set_ylabel("Observed home-win rate")
    axes[1].legend(loc="upper left", fontsize=8)
    fig.suptitle("FBS game-winner reliability by 0.10 probability bins (labels show game count)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def recommendation(metrics, comparisons):
    def row_for(period, model):
        return metrics[(metrics.period == period) & (metrics.model_id == model)].iloc[0]

    def delta_for(period, candidate, control):
        return comparisons[
            (comparisons.period == period)
            & (comparisons.candidate_id == candidate)
            & (comparisons.control_id == control)
        ].iloc[0]

    g3_supported = True
    for period in ("season_2025", "season_2026"):
        score = row_for(period, "G3")
        control = row_for(period, "G2")
        delta = delta_for(period, "G3", "G2")
        if not (
            score.brier < control.brier
            and delta.ci95_high < 0.0
            and score.reliability_10bin <= control.reliability_10bin
        ):
            g3_supported = False
    if g3_supported:
        return (
            "**Keep G3 as the lead reference for the next phase.** It improves paired Brier "
            "with a week-block interval below zero and no increase in 10-bin reliability "
            "error in both the 2025 holdout and 2026 walk-forward sample. This is a result-only "
            "baseline decision, not evidence of market competitiveness."
        )
    g2_supported = True
    for period in ("season_2025", "season_2026"):
        score = row_for(period, "G2")
        control = row_for(period, "G1")
        delta = delta_for(period, "G2", "G1")
        if not (score.brier < control.brier and delta.ci95_high < 0.0):
            g2_supported = False
    if g2_supported:
        return (
            "**Keep G2; do not promote G3.** G2 improves over G1 on both holdout periods "
            "under the paired week-block interval, while G3 does not meet the same gate against G2."
        )
    return (
        "**No rating rung is demonstrated as an upgrade under the predeclared paired gate.** "
        "Retain G1 as the simple probability reference and keep G2/G3 as measured candidates; "
        "their point estimates and intervals are in the tables."
    )


def write_report(out_path, generated_at, coverage, metrics, comparisons,
                 market_coverage, source_manifest, forecasts,
                 plot_path, weekly_path, ledger_path, metrics_path,
                 paired_path, calibration_csv_path, coverage_path,
                 manifest_path, bootstrap_replicates):
    eligible = int(len(forecasts))
    by_season = forecasts.groupby("season").size().to_dict()
    homes = int((~forecasts.neutral_site.astype(bool)).sum())
    neutrals = int(forecasts.neutral_site.astype(bool).sum())
    exact_kickoff_collisions = int(forecasts.kickoff_utc.duplicated().sum())
    report = [
        "# FBS Game-Winner Baseline Results — Phase 1",
        "",
        "Generated: %s  " % generated_at,
        "Branch: `feat/fbs-data-audit`  ",
        "Model version: `fbs-game-winner-g0-g3-v1-20261017`",
        "",
        "## Scope and result",
        "",
        "This run evaluates G0–G3 on every completed FBS-vs-FBS game available in the local 2022–2026 schedule releases. It uses no player, player-prop, box-score, play-by-play, market, or same-game outcome features. Every model receives a forecast for the same game rows. The earlier `REPORT-FBS-GAME-WINNER-BASELINE-20261017.md` is preserved as a separate prior run; its three-model, 2023+ results are not substituted for this revised ladder.",
        "",
        "2025 is the out-of-time holdout year for model selection: constants are fixed in code and were not tuned on any evaluation year. It is evaluated walk-forward, so earlier completed 2025 games can inform later 2025 forecasts after the 24-hour lag, but no game's result informs its own forecast. For every game, history contains only completed eligible games whose kickoff was strictly more than 24 hours before the target kickoff. The source files do not publish final-whistle timestamps, so the ledger proves the kickoff-time cutoff; it cannot verify each historical result's exact publication timestamp.",
        "",
        "2026 is a separate walk-forward evaluation through the completed games present in the cached schedule snapshot. Later 2026 games absent or unfinished in that snapshot are not evaluated. FBS-vs-FCS games are excluded from both evaluation and rating updates.",
        "",
        "| Population measure | Value |",
        "|---|---:|",
        "| Eligible completed FBS-vs-FBS games | %d |" % eligible,
        "| Evaluated seasons | 2022–2026 |",
        "| Home-site games | %d |" % homes,
        "| Neutral-site games | %d |" % neutrals,
        "| Additional games with a previously seen identical kickoff timestamp | %d |" % exact_kickoff_collisions,
        "| Eligible rows without a resolved stable team ID | 0 |",
        "| `fbs_game` vs known home/away division membership disagreements | %d |" % int(coverage.fbs_membership_disagreements.sum()),
        "| `fbs_participant` vs known home/away division membership disagreements | %d |" % int(coverage.fbs_participant_disagreements.sum()),
        "| Excluded completed FBS-vs-FBS rows with unresolved team IDs | %d |" % int(coverage.fbs_vs_fbs_unresolved_team_ids_excluded.sum()),
        "| Duplicate schedule/ESPN rows excluded | %d |" % int(coverage.duplicate_schedule_rows.sum() + coverage.duplicate_espn_rows.sum()),
        "| Duplicate game IDs in the forecast ledger | %d |" % int(forecasts.game_id.astype(str).duplicated().sum()),
        "| Cross-season duplicate completed FBS-participant rows excluded | %d |" % int(coverage.cross_season_duplicate_event_rows.sum()),
        "",
        "Eligible games by season: %s. Every same-timestamp group is forecast before any result from that group can update a rating." % ", ".join(
            "%s: %d" % (year, by_season.get(year, 0)) for year in SEASONS
        ),
        "",
        "## Population coverage and exclusions",
        "",
        coverage_markdown(coverage),
        "",
        "The primary membership flag is the season-specific `fbs_game` field in `cfb_schedules`; each ledger row also carries explicit home and away FBS membership booleans. The source loader compares the published FBS game/participant flags with the two season-specific division fields where both are known; disagreement counts are above and in the eligibility CSV. FBS-participant games are separately counted to identify completed FBS-vs-FCS exclusions. ESPN schedule rows supply kickoff, home/away orientation, `STATUS_FINAL`, and final scores. The loader excludes duplicate source IDs, unresolved team identities, tied outcomes, and missing-kickoff rows; team-identity or score conflicts fail the run. The table counts final-score cross-checks where both the CFBD schedule and ESPN schedule provide scores; all checked pairs agree. In 2026, 11 ESPN-final FBS-vs-FBS rows were not yet marked completed by the CFBD schedule release and are included from ESPN's final status and score.",
        "",
        "2024's one canceled FBS-vs-FBS fixture has a 0–0 placeholder and is excluded because both schedule sources mark it canceled. The 2026 cached release has 15 FBS-vs-FBS games marked in progress and 396 scheduled FBS-vs-FBS rows with no matching ESPN schedule event; all 411 are non-final and excluded. The schedule source does not distinguish the future/no-ESPN rows from other absent event IDs, so they are reported as that measured category rather than inferred to be completed or canceled.",
        "",
        "## Model definitions",
        "",
        "| Model | Definition |",
        "|---|---|",
        "| G0 | Fixed P(home wins) = 0.50 for every game. Its one-outcome Brier is exactly 0.2500 on binary outcomes. |",
        "| G1 | Expanding prior home-win rate over earlier eligible FBS-vs-FBS games, split between neutral and home-site games, with Beta(1,1) smoothing. |",
        "| G2 | Elo ratings start at 1500; logistic scale 400; K=20; fixed home advantage 55 rating points (0 at neutral); 25% regression toward 1500 when a new season begins. |",
        "| G3 | Same pregame Elo probability and season handling as G2, but rating updates use score margin: K multiplier = ln(1 + absolute margin) × 2.2 / (2.2 + 0.001 × absolute pregame Elo gap). |",
        "",
        "G0–G3 use only completed FBS-vs-FBS outcomes and margins from the local archive. The model constants are fixed, not fitted. All games with an identical kickoff timestamp are predicted before any of their results are applied. A neutral-site game receives no Elo home-field points; G1 uses its separate neutral-site prior.",
        "",
        "## Pooled walk-forward results",
        "",
        metrics_markdown(metrics, "all_walk_forward_2022_2026"),
        "",
        "Brier uses one binary outcome per game: `(P(home win) − y)^2`, where y=1 only when the home-designated team wins. Lower is better. Coin-flip BSS is `1 − Brier/0.25`. Reliability and resolution are the fixed 10-bin Murphy decomposition components and therefore are binned approximations. Calibration is also reported as mean forecast against the observed home-win rate.",
        "",
        "## Season-by-season results",
        "",
    ]
    for season in SEASONS:
        report.extend([
            "### %d%s" % (
                season,
                " — out-of-time holdout" if season == 2025
                else " — walk-forward" if season == 2026
                else " — chronological development years",
            ),
            "",
            metrics_markdown(metrics, "season_%d" % season),
            "",
        ])
    report.extend([
        "Week-level scores for every season and model are in [%s](%s). Weeks are Monday-starting UTC calendar weeks derived from the actual ESPN kickoff timestamp. The per-game ledger includes `week_start_utc` for consistent breakdowns." % (weekly_path.name, weekly_path.name),
        "",
        "## Paired uncertainty and rung comparisons",
        "",
        "Intervals are 95%% percentile intervals from %d paired, season-stratified UTC calendar-week block bootstrap replicates. Each sampled block carries all its games, preserving pairing between the compared forecasts. Blocks are resampled within season for the pooled result. This captures within-week dependence better than resampling individual games, though repeated-team dependence across weeks remains." % bootstrap_replicates,
        "",
        "### All eligible games",
        "",
        paired_markdown(comparisons, "all_walk_forward_2022_2026"),
        "",
        "### 2025 holdout",
        "",
        paired_markdown(comparisons, "season_2025"),
        "",
        "### 2026 walk-forward",
        "",
        paired_markdown(comparisons, "season_2026"),
        "",
        "All season-specific paired intervals are in [%s](%s). Negative Δ Brier favors the candidate rung." % (paired_path.name, paired_path.name),
        "",
        "## Calibration",
        "",
        "The reliability plot shows 2025 and 2026 separately; each point is a non-empty 0.10 probability bin and its label is the number of games in that bin. Detailed bin counts and observed rates for each model, each season, and the pooled sample are in [%s](%s)." % (calibration_csv_path.name, calibration_csv_path.name),
        "",
        "![FBS game-winner calibration by holdout season](%s)" % plot_path.name,
        "",
        "## Market reference availability",
        "",
        "The cached game-level betting files were inspected separately. Their columns contain game spread, total, home-favorite flag, and source, but no two-sided moneylines or odds timestamps. Only 2025 and 2026 betting files are present; they do not provide an earlier-season spread-to-probability calibration set for 2025. Since the snapshots' pre-kickoff timing cannot be verified, no market probability is scored and no spread-implied probability is substituted.",
        "",
        "| Season | Eligible games | Matched spread rows | Non-null spreads | Moneyline fields | Timestamp fields |",
        "|---:|---:|---:|---:|---|---|",
    ])
    for row in market_coverage.itertuples(index=False):
        if not row.file_present:
            report.append("| %d | — | — | — | — | — |" % row.season)
        else:
            report.append(
                "| %d | %d | %d | %d | %s | %s |" % (
                    row.season, row.eligible_games, row.matched_betting_rows,
                    row.matched_nonnull_spread_rows,
                    row.moneyline_fields or "none", row.timestamp_fields or "none",
                )
            )
    report.extend([
        "",
        "## Keep/reject recommendation",
        "",
        recommendation(metrics, comparisons),
        "",
        "This recommendation applies only to the game-winner baseline ladder. It does not authorize or start Phase 2.",
        "",
        "## Reproduction and artifacts",
        "",
        "Run from the repo root with the existing backend environment:",
        "",
        "```bash",
        "/root/legendarypicks/backend/venv/bin/python backend/fbs_game_winner_phase1.py",
        "```",
        "",
        "Source file paths, byte sizes, and SHA-256 hashes are in [%s](%s). The source releases used are listed below:" % (manifest_path.name, manifest_path.name),
        "",
    ])
    for row in source_manifest:
        report.append("- `%s`" % Path(row["path"]).name)
    report.extend([
        "",
        "| Artifact | Purpose |",
        "|---|---|",
        "| [%s](%s) | One pregame forecast row for every eligible completed FBS-vs-FBS game; includes as-of cutoff, source IDs, result, and G0–G3 probabilities. |" % (ledger_path.name, ledger_path.name),
        "| [%s](%s) | Season and pooled scoring metrics. |" % (metrics_path.name, metrics_path.name),
        "| [%s](%s) | Paired week-block bootstrap intervals by season and pooled period. |" % (paired_path.name, paired_path.name),
        "| [%s](%s) | Reliability-bin counts and observed rates. |" % (calibration_csv_path.name, calibration_csv_path.name),
        "| [%s](%s) | Monday-starting UTC calendar-week scores. |" % (weekly_path.name, weekly_path.name),
        "| [%s](%s) | Eligibility, exclusion, source reconciliation, and home/neutral coverage. |" % (coverage_path.name, coverage_path.name),
        "| [%s](%s) | Input file manifest with SHA-256 and byte sizes. |" % (manifest_path.name, manifest_path.name),
        "| [%s](%s) | Standalone 2025/2026 reliability plot. |" % (plot_path.name, plot_path.name),
        "",
    ])
    out_path.write_text("\n".join(report), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--bootstrap-replicates", type=int, default=BOOTSTRAP_REPLICATES)
    args = parser.parse_args()
    if args.bootstrap_replicates < 100:
        raise ValueError("use at least 100 bootstrap replicates")
    data_dir = Path(args.data_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    ledger_path = out_dir / ("fbs_game_winner_forecasts_%s.csv" % RUN_TAG)
    metrics_path = out_dir / ("fbs_game_winner_metrics_%s.csv" % RUN_TAG)
    paired_path = out_dir / ("fbs_game_winner_paired_%s.csv" % RUN_TAG)
    calibration_csv_path = out_dir / ("fbs_game_winner_calibration_%s.csv" % RUN_TAG)
    weekly_path = out_dir / ("fbs_game_winner_weekly_metrics_%s.csv" % RUN_TAG)
    coverage_path = out_dir / ("fbs_game_winner_eligibility_%s.csv" % RUN_TAG)
    manifest_path = out_dir / ("fbs_game_winner_sources_%s.csv" % RUN_TAG)
    plot_path = out_dir / ("fbs_game_winner_calibration_%s.png" % RUN_TAG)
    report_path = out_dir / "RESULT-FBS-GAME-WINNERS-20261017.md"

    print("Loading audited schedule sources for seasons %s" % ",".join(map(str, SEASONS)), flush=True)
    events, raw_coverage, season_schedules, _ = source_loader.load_events(
        str(data_dir), list(SEASONS)
    )
    coverage = source_coverage(
        data_dir, SEASONS, raw_coverage, season_schedules, events
    )
    source_manifest = build_source_manifest(data_dir, SEASONS, manifest_path)
    forecasts = make_forecasts(events)
    metrics = build_metrics(forecasts)
    comparisons = build_paired_comparisons(forecasts, args.bootstrap_replicates)
    calibration = build_calibration(forecasts)
    weekly = build_weekly_metrics(forecasts)
    market = build_market_coverage(data_dir, forecasts)

    forecasts.to_csv(ledger_path, index=False, quoting=csv.QUOTE_MINIMAL)
    metrics.to_csv(metrics_path, index=False)
    comparisons.to_csv(paired_path, index=False)
    calibration.to_csv(calibration_csv_path, index=False)
    weekly.to_csv(weekly_path, index=False)
    coverage.to_csv(coverage_path, index=False)
    calibration_plot(calibration, plot_path)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    write_report(
        report_path, generated_at, coverage, metrics, comparisons, market,
        source_manifest, forecasts, plot_path, weekly_path,
        ledger_path, metrics_path, paired_path, calibration_csv_path,
        coverage_path, manifest_path, args.bootstrap_replicates,
    )

    print("eligible forecasts:", len(forecasts), flush=True)
    print("eligible by season:", forecasts.groupby("season").size().to_dict(), flush=True)
    print("metrics:\n", metrics.to_string(index=False), flush=True)
    print("paired comparisons:\n", comparisons.to_string(index=False), flush=True)
    print("report:", report_path, flush=True)
    print("ledger:", ledger_path, flush=True)


if __name__ == "__main__":
    main()
