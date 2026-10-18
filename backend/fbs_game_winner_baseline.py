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
import hashlib
import math
import os
from collections import defaultdict
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytz
from scipy import sparse
from scipy.sparse.linalg import lsmr


MODEL_VERSION = "fbs-game-winner-baselines-v2-20261018"
FIRST_EVALUATION_SEASON = 2023
ELO_INITIAL = 1500.0
ELO_HOME_ADVANTAGE = 55.0
ELO_K = 20.0
ELO_OFFSEASON_REGRESSION = 0.25
STRENGTH_RIDGE = 15.0
STRENGTH_SEASON_HALF_LIFE = 1.0
BOOTSTRAP_REPLICATES = 2000
BOOTSTRAP_SEED = 20261017
MODEL_COLUMNS = [
    "coinflip_home_prob", "home_base_prob", "elo_home_prob", "margin_home_prob"
]
MODEL_LABELS = {
    "coinflip_home_prob": "G0 constant 0.50",
    "home_base_prob": "G1 historical home/neutral base rate",
    "elo_home_prob": "G2 chronological Elo",
    "margin_home_prob": "G3 opponent-adjusted margin strength",
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


def schedule_row_to_event(row, season, source_label,
                          allow_verified_score_disagreement=False):
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
        if (expected != (e_home_score, e_away_score)
                and not allow_verified_score_disagreement):
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
        "week": as_int(row.week_cfb),
        "kickoff_utc": kickoff,
        "utc_date": kickoff.date(),
        "week_start_utc": (
            kickoff.date() - timedelta(days=kickoff.weekday())
        ).isoformat(),
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
        "cfbd_score_disagreement_verified": bool(allow_verified_score_disagreement),
    }


def load_events(data_dir, seasons, include_reporting_metadata=True,
                verified_score_disagreement_ids=None):
    events = []
    coverage = []
    team_info_by_season = {}
    season_rows = {}
    verified_score_disagreement_ids = {
        str(game_id) for game_id in (verified_score_disagreement_ids or ())
    }
    encountered_score_disagreements = set()
    for season in seasons:
        schedule_path = season_schedule_path(data_dir, season)
        espn_path = os.path.join(data_dir, "espn_schedule_%d.parquet" % season)
        team_path = os.path.join(data_dir, "cfb_team_info_%d.parquet" % season)
        required_paths = [schedule_path, espn_path]
        if include_reporting_metadata:
            required_paths.append(team_path)
        if not all(os.path.exists(path) for path in required_paths):
            raise FileNotFoundError("missing required local source for season %d" % season)
        schedule_raw = pd.read_parquet(schedule_path)
        espn_raw = pd.read_parquet(espn_path)
        team_info = pd.read_parquet(team_path) if include_reporting_metadata else pd.DataFrame()
        schedule_duplicate = (
            schedule_raw.game_id.notna()
            & schedule_raw.game_id.astype(str).duplicated(keep=False)
        )
        espn_duplicate = (
            espn_raw.game_id.notna()
            & espn_raw.game_id.astype(str).duplicated(keep=False)
        )
        schedule_missing_id = schedule_raw.game_id.isna()
        espn_missing_id = espn_raw.game_id.isna()
        schedule = schedule_raw.loc[~schedule_duplicate & ~schedule_missing_id].copy()
        espn = espn_raw.loc[~espn_duplicate & ~espn_missing_id].copy()
        team_info_by_season[season] = team_info
        season_rows[season] = schedule

        joined = schedule.merge(
            espn, on="game_id", how="left", suffixes=("_cfb", "_espn"),
            validate="one_to_one", indicator=True
        )
        participant = joined[joined.fbs_participant.fillna(False)]
        fbs = joined[joined.fbs_game.fillna(False)]
        division_known = schedule.home_division.notna() & schedule.away_division.notna()
        division_home_fbs = schedule.home_division.astype(str).str.casefold().eq("fbs")
        division_away_fbs = schedule.away_division.astype(str).str.casefold().eq("fbs")
        division_fbs_game = division_home_fbs & division_away_fbs
        division_fbs_participant = division_home_fbs | division_away_fbs
        membership_disagreement = int((
            schedule.loc[division_known, "fbs_game"].fillna(False).astype(bool).to_numpy()
            != division_fbs_game[division_known].to_numpy()
        ).sum())
        participant_disagreement = int((
            schedule.loc[division_known, "fbs_participant"].fillna(False).astype(bool).to_numpy()
            != division_fbs_participant[division_known].to_numpy()
        ).sum())
        participant_final = participant[
            participant.status_espn.eq("STATUS_FINAL")
        ]
        fbs_present_espn = fbs[fbs._merge.eq("both")]
        fbs_final_status = fbs_present_espn[
            fbs_present_espn.status_espn.eq("STATUS_FINAL")
        ]
        completed_espn = participant_final[
            participant_final.home_score.notna()
            & participant_final.away_score.notna()
        ]
        primary_espn = fbs_final_status[
            fbs_final_status.home_score.notna()
            & fbs_final_status.away_score.notna()
        ]

        excluded_unresolved_ids = 0
        excluded_ties = 0
        excluded_missing_kickoff = 0
        for row in completed_espn.itertuples(index=False):
            c_home_id = as_int(row.home_id_cfb)
            c_away_id = as_int(row.away_id_cfb)
            e_home_id = as_int(row.home_id_espn)
            e_away_id = as_int(row.away_id_espn)
            if None in (c_home_id, c_away_id, e_home_id, e_away_id):
                excluded_unresolved_ids += 1
                continue
            same_order = c_home_id == e_home_id and c_away_id == e_away_id
            reverse_order = c_home_id == e_away_id and c_away_id == e_home_id
            if not same_order and not reverse_order:
                excluded_unresolved_ids += 1
                continue
            if float(row.home_score) == float(row.away_score):
                excluded_ties += 1
                continue
            if parse_utc(row.game_date) is None and parse_utc(row.start_date) is None:
                excluded_missing_kickoff += 1
                continue
            source_label = "ESPN schedule; CFBD schedule membership/conference"
            c_home_score = as_float(row.home_points)
            c_away_score = as_float(row.away_points)
            e_home_score = as_float(row.home_score)
            e_away_score = as_float(row.away_score)
            same_order = (c_home_id == e_home_id and c_away_id == e_away_id)
            c_scores = ((c_home_score, c_away_score) if same_order
                        else (c_away_score, c_home_score))
            score_disagreement = (
                c_scores[0] is not None and c_scores[1] is not None
                and (c_scores[0], c_scores[1]) != (e_home_score, e_away_score)
            )
            game_id = str(row.game_id)
            if score_disagreement:
                if game_id not in verified_score_disagreement_ids:
                    raise ValueError(
                        "schedule publishers disagree on score for game %s" % game_id
                    )
                encountered_score_disagreements.add(game_id)
            event = schedule_row_to_event(
                row, season, source_label,
                allow_verified_score_disagreement=score_disagreement,
            )
            if event["home_win"] not in (0, 1):
                raise ValueError("invalid binary target in game %s" % event["game_id"])
            events.append(event)

        coverage.append({
            "season": season,
            "schedule_source": os.path.basename(schedule_path),
            "espn_schedule_source": os.path.basename(espn_path),
            "all_schedule_rows": int(len(schedule_raw)),
            "unique_schedule_ids": int(schedule.game_id.astype(str).nunique()),
            "duplicate_schedule_rows": int(schedule_duplicate.sum()),
            "missing_schedule_ids": int(schedule_missing_id.sum()),
            "duplicate_espn_rows": int(espn_duplicate.sum()),
            "missing_espn_game_ids": int(espn_missing_id.sum()),
            "fbs_game_rows": int(len(fbs)),
            "fbs_participant_rows": int(len(participant)),
            "division_membership_unknown_rows": int((~division_known).sum()),
            "fbs_membership_disagreements": membership_disagreement,
            "fbs_participant_disagreements": participant_disagreement,
            "completed_fbs_participant": int(len(completed_espn)),
            "completed_fbs_vs_fbs_candidate": int(len(primary_espn)),
            "eligible_fbs_vs_fbs": 0,
            "fbs_vs_fcs_completed": int(len(completed_espn) - len(primary_espn)),
            "fbs_without_espn_event": int((fbs._merge != "both").sum()),
            "fbs_espn_not_final": int(
                len(fbs_present_espn) - len(fbs_final_status)
            ),
            "fbs_espn_final_missing_score": int(
                len(fbs_final_status) - len(primary_espn)
            ),
            "espn_final_without_cfb_completed": int(
                (primary_espn.completed.fillna(False) == False).sum()
            ),
            "excluded_unresolved_team_ids": excluded_unresolved_ids,
            "excluded_ties_without_winner": excluded_ties,
            "excluded_missing_kickoff": excluded_missing_kickoff,
            "verified_cfbd_score_disagreements": 0,
        })
        if membership_disagreement or participant_disagreement:
            raise ValueError(
                "CFBD FBS membership flags disagree with season division fields "
                "for season %d" % season
            )

    frame = pd.DataFrame(events)
    duplicate_event_ids = set(
        frame.loc[frame.game_id.duplicated(keep=False), "game_id"].astype(str)
    )
    duplicate_event_rows_by_season = (
        frame[frame.game_id.astype(str).isin(duplicate_event_ids)]
        .groupby("season").size().to_dict()
    )
    if duplicate_event_ids:
        frame = frame[~frame.game_id.astype(str).isin(duplicate_event_ids)].copy()
    frame = frame.sort_values(["kickoff_utc", "season", "game_id"]).reset_index(drop=True)
    frame["evaluation_population"] = frame.fbs_game.astype(bool)
    eligible_by_season = frame[frame.evaluation_population].groupby("season").size()
    for row in coverage:
        row["eligible_fbs_vs_fbs"] = int(eligible_by_season.get(row["season"], 0))
        row["cross_season_duplicate_event_rows"] = int(
            duplicate_event_rows_by_season.get(row["season"], 0)
        )
        row["verified_cfbd_score_disagreements"] = sum(
            1 for game_id in encountered_score_disagreements
            if game_id in set(
                frame.loc[frame.season.eq(row["season"]), "game_id"].astype(str)
            )
        )

    unexpected_unseen = verified_score_disagreement_ids - encountered_score_disagreements
    if unexpected_unseen:
        raise ValueError(
            "verified score disagreement IDs were not encountered as completed games: %s"
            % ",".join(sorted(unexpected_unseen))
        )

    if include_reporting_metadata:
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
            latest_history_game = max(
                eligible_history, key=lambda item: item["kickoff_utc"]
            )
            latest_history_kickoff = latest_history_game["kickoff_utc"]
            latest_history_game_id = str(latest_history_game["game_id"])
        else:
            strength, fitted_home_advantage, sigma = {}, 0.0, 21.0
            latest_history_kickoff = None
            latest_history_game_id = ""
        for row in today.itertuples(index=False):
            if (latest_history_kickoff is not None
                    and row.kickoff_utc - latest_history_kickoff
                    < timedelta(hours=24)):
                raise RuntimeError(
                    "history embargo violated for forecast game %s" % row.game_id
                )
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
                "latest_history_game_kickoff_utc": (
                    latest_history_kickoff.isoformat()
                    if latest_history_kickoff is not None else ""
                ),
                "latest_history_game_id": latest_history_game_id,
                "training_games_available": len(eligible_history),
                "coinflip_home_prob": 0.5,
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


def make_frozen_season_predictions(events, season):
    """Forecast one complete season from prior seasons, without in-season updates."""
    history = events[
        events.fbs_participant.astype(bool) & events.season.lt(season)
    ].copy()
    history = history.sort_values(
        ["utc_date", "kickoff_utc", "game_id"]
    ).reset_index(drop=True)
    evaluation = events[
        events.evaluation_population & events.season.eq(season)
    ].sort_values(["kickoff_utc", "game_id"]).reset_index(drop=True)
    if history.empty or evaluation.empty:
        raise RuntimeError("frozen holdout requires prior history and evaluation games")
    if int(history.season.max()) >= int(season):
        raise RuntimeError("frozen holdout history includes the evaluation season")

    base = HomeBase()
    base.update(history)
    elo = Elo()
    for _, day_games in history.groupby("utc_date", sort=True):
        elo.update_day(day_games)
    elo.ensure_season(season)
    strength, fitted_home_advantage, sigma = fit_margin_model(history, season)
    latest_history_game = max(
        history.to_dict("records"), key=lambda item: item["kickoff_utc"]
    )
    latest_history_kickoff = latest_history_game["kickoff_utc"]
    latest_history_game_id = str(latest_history_game["game_id"])

    rows = []
    for row in evaluation.itertuples(index=False):
        if row.kickoff_utc - latest_history_kickoff < timedelta(hours=24):
            raise RuntimeError(
                "frozen history embargo violated for game %s" % row.game_id
            )
        margin = (
            strength.get(row.home_team_id, 0.0)
            - strength.get(row.away_team_id, 0.0)
            + (0.0 if row.neutral_site else fitted_home_advantage)
        )
        pred = row._asdict()
        pred.update({
            "game_id": str(row.game_id),
            "season": int(row.season),
            "week": row.week,
            "coinflip_home_prob": 0.5,
            "home_base_prob": base.probability(row.neutral_site),
            "elo_home_prob": elo.probability(
                row.home_team_id, row.away_team_id, row.neutral_site
            ),
            "margin_home_prob": normal_probability(margin, sigma),
            "predicted_score_margin": margin,
            "frozen_training_games_available": int(len(history)),
            "frozen_latest_history_game_kickoff_utc": latest_history_kickoff.isoformat(),
            "frozen_latest_history_game_id": latest_history_game_id,
            "frozen_pregame_data_cutoff_utc": row.kickoff_utc.isoformat(),
            "model_version": MODEL_VERSION + "-frozen-" + str(season),
        })
        rows.append(pred)
    result = pd.DataFrame(rows)
    if result.game_id.duplicated().any():
        raise RuntimeError("duplicate game IDs in frozen holdout forecasts")
    return result


def score_metrics(rows, probability_column, target_column="home_win"):
    if rows.empty:
        return {"games": 0}
    p = rows[probability_column].to_numpy(dtype=float)
    y = rows[target_column].to_numpy(dtype=float)
    p = np.clip(p, 1e-12, 1.0 - 1e-12)
    brier = float(np.mean((p - y) ** 2))
    log_loss = float(np.mean(-(y * np.log(p) + (1.0 - y) * np.log(1.0 - p))))
    accuracy = (
        None if probability_column == "coinflip_home_prob"
        else float(np.mean((p >= 0.5) == y.astype(bool)))
    )
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
        "brier_skill_vs_coinflip": 1.0 - brier / 0.25,
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
    work = rows[["season", "week_start_utc"]].copy()
    work["delta_sum_item"] = difference
    blocks = (
        work.groupby(["season", "week_start_utc"], sort=True)
        .delta_sum_item.agg(["sum", "count"])
        .reset_index()
    )
    seed_text = "%s|%s|%s|%d" % (
        model_column, baseline_column,
        ",".join(map(str, sorted(rows.season.unique()))), len(rows),
    )
    stable_seed = seed + int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:8], 16)
    rng = np.random.default_rng(stable_seed)
    estimate_sums = np.zeros(replicates, dtype=float)
    estimate_counts = np.zeros(replicates, dtype=float)
    for _, season_blocks in blocks.groupby("season", sort=True):
        block_sums = season_blocks["sum"].to_numpy(dtype=float)
        block_counts = season_blocks["count"].to_numpy(dtype=float)
        sampled = rng.integers(
            0, len(block_sums), size=(replicates, len(block_sums))
        )
        estimate_sums += block_sums[sampled].sum(axis=1)
        estimate_counts += block_counts[sampled].sum(axis=1)
    estimates = estimate_sums / estimate_counts
    return {
        "difference": float(np.mean(difference)),
        "ci_low": float(np.quantile(estimates, 0.025)),
        "ci_high": float(np.quantile(estimates, 0.975)),
        "replicates": replicates,
        "bootstrap_method": "paired UTC calendar-week block bootstrap, season-stratified",
        "bootstrap_blocks": int(len(blocks)),
    }


def build_metrics(forecasts, frozen_holdout):
    metric_rows = []
    period_rows = [
        ("Walk-forward 2023-2025", forecasts.season.between(2023, 2025)),
        ("2025 rolling walk-forward", forecasts.season.eq(2025)),
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
    for model_column in MODEL_COLUMNS:
        metric_rows.append({
            "period": "2025 frozen holdout",
            "slice": "All FBS-vs-FBS games",
            "model": MODEL_LABELS[model_column],
            "model_column": model_column,
            **score_metrics(frozen_holdout, model_column),
        })

    for (season, week), subset in forecasts.groupby(["season", "week"], dropna=False):
        for model_column in MODEL_COLUMNS:
            metric_rows.append({
                "period": "Week-by-week",
                "slice": "Season %s, week %s" % (season, week),
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
    for period, period_frame in [
        ("Walk-forward 2023-2025", main),
        ("2026 current forward", forecasts[forecasts.season.eq(2026)]),
    ]:
        for label, column in slice_specs:
            for value, subset in period_frame.groupby(column, dropna=False):
                for model_column in MODEL_COLUMNS:
                    metric_rows.append({
                        "period": period,
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


def paired_comparisons(forecasts, frozen_holdout):
    rows = []
    periods = [
        ("Walk-forward 2023-2025", forecasts.season.between(2023, 2025)),
        ("2025 rolling walk-forward", forecasts.season.eq(2025)),
        ("2026 current forward", forecasts.season.eq(2026)),
    ]
    period_frames = [(period, forecasts[mask]) for period, mask in periods]
    period_frames.append(("2025 frozen holdout", frozen_holdout))
    for period, subset in period_frames:
        for column, control_column in [
            ("home_base_prob", "coinflip_home_prob"),
            ("elo_home_prob", "coinflip_home_prob"),
            ("margin_home_prob", "coinflip_home_prob"),
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


def calibration_rows(forecasts, frozen_holdout):
    rows = []
    periods = [
        ("Walk-forward 2023-2025", forecasts.season.between(2023, 2025)),
        ("2025 rolling walk-forward", forecasts.season.eq(2025)),
        ("2026 current forward", forecasts.season.eq(2026)),
    ]
    period_frames = [(period, forecasts[mask]) for period, mask in periods]
    period_frames.append(("2025 frozen holdout", frozen_holdout))
    for period, subset in period_frames:
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


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_manifest(data_dir, seasons):
    manifest = []
    for season in seasons:
        files = [
            ("SportsDataverse cfb_schedules", season_schedule_path(data_dir, season)),
            ("SportsDataverse espn_cfb_schedules", os.path.join(
                data_dir, "espn_schedule_%d.parquet" % season)),
            ("SportsDataverse cfb_team_info", os.path.join(
                data_dir, "cfb_team_info_%d.parquet" % season)),
        ]
        betting_path = os.path.join(data_dir, "betting_%d.parquet" % season)
        if os.path.exists(betting_path):
            files.append(("SportsDataverse espn_cfb_betting", betting_path))
        for source_name, path in files:
            if not os.path.exists(path):
                continue
            rows = len(pd.read_parquet(path))
            manifest.append({
                "season": season,
                "source": source_name,
                "file": os.path.relpath(path, os.path.dirname(data_dir)),
                "rows": rows,
                "bytes": os.path.getsize(path),
                "sha256": sha256_file(path),
            })
    return pd.DataFrame(manifest)


def audit_market_files(data_dir, forecasts):
    rows = []
    for season in sorted(forecasts.season.unique()):
        path = os.path.join(data_dir, "betting_%d.parquet" % int(season))
        games = forecasts[forecasts.season.eq(season)]
        if not os.path.exists(path):
            rows.append({
                "season": int(season), "forecast_games": len(games),
                "matched_stored_spreads": 0, "matched_moneylines": 0,
                "timestamped_pregame_records": 0,
                "odds_sources": "no cached file",
                "assessment": "No cached game betting file",
            })
            continue
        betting = pd.read_parquet(path)
        betting["game_id"] = betting.game_id.astype(str)
        game_ids = pd.DataFrame({"game_id": games.game_id.astype(str)})
        matched = game_ids.merge(betting, on="game_id", how="left", validate="one_to_one")
        spread_col = next((name for name in ("home_team_spread", "game_spread")
                           if name in matched.columns), None)
        timestamp_cols = [
            name for name in betting.columns
            if any(token in name.casefold()
                   for token in ("time", "date", "snapshot", "updated", "created"))
        ]
        moneyline_cols = [name for name in betting.columns
                          if "moneyline" in name.casefold() or name.casefold().endswith("_ml")]
        has_home_ml = any("home" in name.casefold() for name in moneyline_cols)
        has_away_ml = any("away" in name.casefold() for name in moneyline_cols)
        matched_spreads = (
            int(matched[spread_col].notna().sum()) if spread_col else 0
        )
        timestamped = (
            int(matched[timestamp_cols].notna().any(axis=1).sum())
            if timestamp_cols else 0
        )
        source_values = sorted(
            str(value) for value in betting.odds_source.dropna().unique()
        ) if "odds_source" in betting else []
        rows.append({
            "season": int(season),
            "forecast_games": int(len(games)),
            "matched_stored_spreads": matched_spreads,
            "matched_moneylines": int(
                matched[moneyline_cols].notna().all(axis=1).sum()
                if has_home_ml and has_away_ml else 0
            ),
            "timestamped_pregame_records": timestamped,
            "odds_sources": ", ".join(source_values) or "unknown",
            "assessment": (
                "Spread available, but no quote timestamp; excluded from as-of market scoring"
                if matched_spreads and not timestamp_cols
                else "No verified as-of two-sided market snapshot"
            ),
        })
    return pd.DataFrame(rows)


def plot_calibration(calibration, plot_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    periods = [
        "Walk-forward 2023-2025",
        "2025 frozen holdout",
        "2026 current forward",
    ]
    colors = {
        "Walk-forward 2023-2025": "#146c94",
        "2025 frozen holdout": "#d97706",
        "2026 current forward": "#6b4eff",
    }
    figure, axes = plt.subplots(2, 2, figsize=(10, 8), sharex=True, sharey=True)
    for model_column, axis in zip(MODEL_COLUMNS, axes.flat):
        label = MODEL_LABELS[model_column]
        axis.plot([0, 1], [0, 1], color="#777777", linestyle="--", linewidth=1)
        model_rows = calibration[calibration.model.eq(label)]
        for period in periods:
            subset = model_rows[model_rows.period.eq(period)].sort_values("mean_predicted")
            if subset.empty:
                continue
            axis.plot(
                subset.mean_predicted, subset.observed_home_win_rate,
                marker="o", linewidth=1.5, color=colors[period], label=period,
            )
        axis.set_title(label)
        axis.grid(alpha=0.2)
        axis.set_xlim(0, 1)
        axis.set_ylim(0, 1)
    axes[1, 0].set_xlabel("Mean predicted home-win probability")
    axes[1, 1].set_xlabel("Mean predicted home-win probability")
    axes[0, 0].set_ylabel("Observed home-win rate")
    axes[1, 0].set_ylabel("Observed home-win rate")
    axes[0, 0].legend(fontsize=8, loc="upper left")
    figure.suptitle("FBS game-winner calibration by model and evaluation period")
    figure.tight_layout()
    figure.savefig(plot_path, dpi=160)
    plt.close(figure)


def build_report(forecasts, frozen_holdout, coverage, metrics, comparisons,
                 calibration, manifest, market_coverage, plot_name,
                 report_path, run_date):
    generated = datetime.now(pytz.UTC).strftime("%Y-%m-%d %H:%M UTC")
    period_frames = [
        ("Walk-forward 2023-2025", forecasts[forecasts.season.between(2023, 2025)]),
        ("2025 rolling walk-forward", forecasts[forecasts.season.eq(2025)]),
        ("2025 frozen holdout", frozen_holdout),
        ("2026 current forward", forecasts[forecasts.season.eq(2026)]),
    ]

    overall_rows = []
    for period, frame in period_frames:
        for model_column in MODEL_COLUMNS:
            result = score_metrics(frame, model_column)
            overall_rows.append({
                "period": period,
                "model": MODEL_LABELS[model_column],
                "games": result.get("games", 0),
                "brier": fmt(result.get("brier")),
                "coinflip BSS": fmt(result.get("brier_skill_vs_coinflip")),
                "log loss": fmt(result.get("log_loss")),
                "accuracy": fmt(result.get("accuracy")),
                "predicted / observed": "%s / %s" % (
                    fmt(result.get("mean_predicted_home_win")),
                    fmt(result.get("observed_home_win_rate")),
                ),
                "reliability": fmt(result.get("reliability_10bin")),
                "resolution": fmt(result.get("resolution_10bin")),
            })

    season_rows = []
    for season in sorted(forecasts.season.unique()):
        subset = forecasts[forecasts.season.eq(season)]
        for model_column in MODEL_COLUMNS:
            result = score_metrics(subset, model_column)
            season_rows.append({
                "season": int(season), "model": MODEL_LABELS[model_column],
                "games": result.get("games", 0),
                "brier": fmt(result.get("brier")),
                "coinflip BSS": fmt(result.get("brier_skill_vs_coinflip")),
                "log loss": fmt(result.get("log_loss")),
                "accuracy": fmt(result.get("accuracy")),
            })

    week_rows = []
    for (season, week), subset in forecasts.groupby(["season", "week"], dropna=False):
        row = {"season": int(season), "week": week, "games": int(len(subset))}
        for model_column in MODEL_COLUMNS:
            row[MODEL_LABELS[model_column]] = fmt(
                score_metrics(subset, model_column).get("brier")
            )
        week_rows.append(row)

    coverage_rows = []
    for row in coverage.itertuples(index=False):
        season_forecasts = forecasts[forecasts.season.eq(row.season)]
        evaluated = int(len(season_forecasts))
        coverage_rows.append({
            "season": row.season,
            "schedule rows": row.all_schedule_rows,
            "FBS-FBS scheduled": row.fbs_game_rows,
            "division unknown": row.division_membership_unknown_rows,
            "FBS flag vs divisions": row.fbs_membership_disagreements,
            "FBS participant vs divisions": row.fbs_participant_disagreements,
            "completed candidates": row.completed_fbs_vs_fbs_candidate,
            "eligible games": row.eligible_fbs_vs_fbs,
            "evaluated games": evaluated,
            "home-site games": int((~season_forecasts.neutral_site.astype(bool)).sum()),
            "neutral-site games": int(season_forecasts.neutral_site.astype(bool).sum()),
            "FBS-FCS completed": row.fbs_vs_fcs_completed,
            "no ESPN event": row.fbs_without_espn_event,
            "ESPN not final": row.fbs_espn_not_final,
            "final missing score": row.fbs_espn_final_missing_score,
            "ESPN final / CFB incomplete": row.espn_final_without_cfb_completed,
            "unresolved IDs excluded": row.excluded_unresolved_team_ids,
            "ties excluded": row.excluded_ties_without_winner,
            "missing kickoff excluded": row.excluded_missing_kickoff,
            "duplicate source rows": (
                row.duplicate_schedule_rows + row.duplicate_espn_rows
                + row.cross_season_duplicate_event_rows
            ),
        })

    slice_rows = []
    slice_periods = ["Walk-forward 2023-2025", "2026 current forward"]
    prefixes = ("Local kickoff day:", "Conference matchup:", "Game phase:")
    slices = metrics[
        metrics.period.isin(slice_periods)
        & metrics.slice.map(lambda value: str(value).startswith(prefixes))
    ]
    for row in slices.itertuples(index=False):
        slice_rows.append({
            "period": row.period,
            "slice": row.slice,
            "model": row.model,
            "games": row.games,
            "brier": fmt(getattr(row, "brier", None)),
            "log loss": fmt(getattr(row, "log_loss", None)),
            "accuracy": fmt(getattr(row, "accuracy", None)),
        })

    conference_rows = []
    conference_metrics = metrics[
        metrics.period.eq("Walk-forward 2023-2025")
        & metrics.slice.str.startswith("Conference team:")
    ]
    for row in conference_metrics.itertuples(index=False):
        conference_rows.append({
            "conference": row.slice.replace("Conference team: ", ""),
            "team-games": row.games, "model": row.model,
            "brier": fmt(getattr(row, "brier", None)),
            "log loss": fmt(getattr(row, "log_loss", None)),
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
            "slice": row.slice, "model": row.model, "games": row.games,
            "brier": fmt(getattr(row, "brier", None)),
            "log loss": fmt(getattr(row, "log_loss", None)),
            "accuracy": fmt(getattr(row, "accuracy", None)),
        })

    comparison_rows = []
    for row in comparisons.itertuples(index=False):
        comparison_rows.append({
            "period": row.period, "candidate": row.candidate,
            "control": row.control, "games": row.games,
            "delta": fmt(row.difference),
            "95% paired interval": "[%s, %s]" % (fmt(row.ci_low), fmt(row.ci_high)),
        })

    source_rows = []
    for row in manifest.itertuples(index=False):
        source_rows.append({
            "season": row.season, "source": row.source, "file": row.file,
            "rows": row.rows, "bytes": row.bytes, "sha256": row.sha256,
        })
    market_rows = []
    for row in market_coverage.itertuples(index=False):
        market_rows.append({
            "season": row.season, "forecast games": row.forecast_games,
            "stored spreads matched": row.matched_stored_spreads,
            "moneylines matched": row.matched_moneylines,
            "timestamped records": row.timestamped_pregame_records,
            "odds source": row.odds_sources, "assessment": row.assessment,
        })

    rolling = forecasts[forecasts.season.between(2023, 2025)]
    elo_score = score_metrics(rolling, "elo_home_prob")
    margin_score = score_metrics(rolling, "margin_home_prob")
    margin_vs_elo = comparisons[
        comparisons.period.eq("Walk-forward 2023-2025")
        & comparisons.candidate.eq(MODEL_LABELS["margin_home_prob"])
        & comparisons.control.eq(MODEL_LABELS["elo_home_prob"])
    ].iloc[0]
    if margin_vs_elo.ci_low <= 0 <= margin_vs_elo.ci_high:
        margin_decision = "does not demonstrate an improvement over Elo"
    elif margin_vs_elo.ci_high < 0:
        margin_decision = "improves on Elo on this paired sample"
    else:
        margin_decision = "scores worse than Elo on this paired sample"
    lower = rolling[
        rolling.conference_matchup_group.eq("SEC/Big 12 vs lower non-elite")
    ]
    saturday = int(rolling.day_group.eq("Saturday").sum())
    off_saturday = int(rolling.day_group.eq("Off-Saturday").sum())
    unknown_day = int(rolling.day_group.eq("Unknown").sum())
    decision = (
        "On the 2023-2025 walk-forward sample, G2 Elo scored Brier %s and G3 "
        "margin strength scored %s. G3 minus G2 was %s with paired 95%% "
        "interval [%s, %s], so it %s. G3's mean predicted home-win rate was "
        "%s against an observed %s. Keep G0-G2 as references and do not add "
        "team-stat inputs in this Phase 1 run."
    ) % (
        fmt(elo_score.get("brier")), fmt(margin_score.get("brier")),
        fmt(margin_vs_elo.difference), fmt(margin_vs_elo.ci_low),
        fmt(margin_vs_elo.ci_high), margin_decision,
        fmt(margin_score.get("mean_predicted_home_win")),
        fmt(margin_score.get("observed_home_win_rate")),
    )

    coverage_table = markdown_table(
        coverage_rows,
        ["season", "schedule rows", "FBS-FBS scheduled", "division unknown",
         "FBS flag vs divisions",
         "FBS participant vs divisions", "completed candidates",
         "eligible games", "evaluated games", "home-site games", "neutral-site games",
         "FBS-FCS completed", "no ESPN event",
         "ESPN not final", "final missing score", "ESPN final / CFB incomplete",
         "unresolved IDs excluded", "ties excluded", "missing kickoff excluded",
         "duplicate source rows"],
        ["Season", "All schedules", "FBS-FBS scheduled", "Division unknown",
         "FBS flag mismatches",
         "Participant flag mismatches", "Completed candidates", "Eligible FBS-FBS",
         "Evaluated", "Home-site", "Neutral-site", "FBS-FCS completed", "No ESPN event",
         "ESPN not final", "Final missing score", "ESPN final / CFB incomplete",
         "Unresolved IDs excluded", "Ties excluded", "No kickoff excluded",
         "Duplicate rows"],
    )
    report = [
        "# FBS game-winner benchmark — Phase 1",
        "",
        "Generated: %s" % generated,
        "Model version: `%s`" % MODEL_VERSION,
        "Execution brief: `research/fbs/AUDIT-FBS-BASELINE-20261017.md` (current brief at file top)",
        "",
        "## Result",
        "",
        "This reproducible benchmark forecasts P(home-designated FBS team wins). It uses only prior completed game results and score margins; no player props, player statistics, box scores, play-by-play, sportsbook prices, or same-day results enter the forecasts. The primary ledger has one row per eligible FBS-FBS game. 2022 warms the models; chronological evaluation covers 2023-2026, with 2025 also reported as a frozen season holdout trained only through 2024.",
        "",
        markdown_table(
            overall_rows,
            ["period", "model", "games", "brier", "coinflip BSS", "log loss",
             "accuracy", "predicted / observed", "reliability", "resolution"],
            ["Evaluation period", "Model", "Games", "Brier", "Coinflip BSS",
             "Log loss", "Accuracy", "Mean forecast / outcome rate",
             "Reliability (10 bins)", "Resolution (10 bins)"],
        ),
        "",
        "Brier is mean `(p - outcome)^2` for one binary outcome; lower is better. G0 must score exactly 0.2500 on every non-empty sample. Coinflip BSS is `1 - Brier / 0.25`. Calibration is mean predicted / observed home-win rate. Reliability and resolution use fixed 0.10 bins; their decomposition is approximate because of binning. G0 has no directional winner pick, so accuracy is reported as unavailable.",
        "",
        "The 2025 frozen holdout uses only games through 2024 to set its base rate, Elo ratings and margin model; 2025 results do not update those forecasts. The separate 2025 rolling walk-forward uses prior 2025 results only after the conservative embargo. 2026 is a current-season walk-forward through the 2026-10-17 source snapshot.",
        "",
        "## Season results",
        "",
        markdown_table(
            season_rows,
            ["season", "model", "games", "brier", "coinflip BSS", "log loss", "accuracy"],
            ["Season", "Model", "Games", "Brier", "Coinflip BSS", "Log loss", "Accuracy"],
        ),
        "",
        "## Weekly Brier scores",
        "",
        markdown_table(
            week_rows,
            ["season", "week", "games"] + [MODEL_LABELS[column] for column in MODEL_COLUMNS],
            ["Season", "Week", "Games"] + ["Brier: " + MODEL_LABELS[column] for column in MODEL_COLUMNS],
        ),
        "",
        "## Eligibility, exclusions, and source reconciliation",
        "",
        coverage_table,
        "",
        "The all-division `cfb_schedules` release marks season-specific `fbs_game` and `fbs_participant` membership. As an independent consistency check, `fbs_game` matched `home_division == fbs` and `away_division == fbs` for every cached season. ESPN's schedule supplies the game kickoff, event home/away orientation, final status, and scores. The code joins by game ID, excludes duplicate source rows, unresolved/conflicting IDs, ties, missing kickoff, non-final games, and missing scores, and fails on a score disagreement. No prop table filters the population.",
        "",
        "FBS-FCS completed games are reported separately and update Elo and the margin ratings; the historical home-rate baseline uses FBS-FBS games only. The 2026 `no ESPN event` count is mostly future scheduled games absent from that ESPN snapshot, not cancellations. ESPN-final games with the CFB `completed` flag still false are retained only when the ESPN event has final scores; those rows are shown separately.",
        "",
        "## Input provenance",
        "",
        "Source files are SportsDataverse `cfb_schedules`, `espn_cfb_schedules`, `cfb_team_info`, and cached `espn_cfb_betting` where available. Exact local file snapshots are pinned below by SHA-256; Parquet assets are fetched by `backend/fetch_fbs_parquet.py` from SportsDataverse releases.",
        "",
        markdown_table(
            source_rows, ["season", "source", "file", "rows", "bytes", "sha256"],
            ["Season", "Publisher release", "Cached file", "Rows", "Bytes", "SHA-256"],
        ),
        "",
        "## Calibration",
        "",
        "Calibration bins for the combined 2023-2025 walk-forward sample, frozen 2025 holdout, and 2026 current forward sample are in `fbs_game_winner_calibration_%s.csv`." % run_date,
        "",
        "![Calibration plot](%s)" % plot_name,
        "",
        "## Saturday, conference, postseason, and strength slices",
        "",
        "Kickoff day is classified in the home team's local time zone, or the venue time zone for neutral sites. For the 2023-2025 sample: %d Saturday, %d off-Saturday, and %d unknown-time-zone games, out of %d total. Unknowns remain their own slice." % (saturday, off_saturday, unknown_day, len(rolling)),
        "",
        markdown_table(
            slice_rows,
            ["period", "slice", "model", "games", "brier", "log loss", "accuracy"],
            ["Period", "Slice", "Model", "Games", "Brier", "Log loss", "Accuracy"],
        ),
        "",
        "`SEC/Big 12 vs lower non-elite` uses conferences with no Top-10-ranked team in the season rank fields and no CFP participant that season. It is a retrospective reporting group, never a feature. This slice has %d games across 2023-2025. The 2026 non-SEC/Big 12 group stays unknown because that season's postseason participants are not yet known." % len(lower),
        "",
        "Conference team-game metrics below count each conference member once per game and convert away-team outcomes and probabilities to that team's perspective.",
        "",
        markdown_table(
            conference_rows,
            ["conference", "team-games", "model", "brier", "log loss", "accuracy"],
            ["Conference", "Team-games", "Model", "Brier", "Log loss", "Accuracy"],
        ),
        "",
        "Favorite/underdog-like slices use each model's own pregame pick; they are not sportsbook favorites. Strength bands use G3's predicted score-margin difference.",
        "",
        markdown_table(
            strength_rows,
            ["slice", "model", "games", "brier", "log loss", "accuracy"],
            ["Slice", "Model", "Games", "Brier", "Log loss", "Accuracy"],
        ),
        "",
        "## Paired Brier comparisons",
        "",
        "Negative candidate-minus-control differences favor the candidate. Intervals use a paired UTC-calendar-week block bootstrap, stratified by season, with 2,000 resamples. This groups games kicked off in the same week; it does not cluster repeat appearances by team across different weeks.",
        "",
        markdown_table(
            comparison_rows,
            ["period", "candidate", "control", "games", "delta", "95% paired interval"],
            ["Period", "Candidate", "Control", "Games", "Δ Brier", "95% interval"],
        ),
        "",
        "## Market data availability",
        "",
        markdown_table(
            market_rows,
            ["season", "forecast games", "stored spreads matched", "moneylines matched",
             "timestamped records", "odds source", "assessment"],
            ["Season", "Forecast games", "Matched stored spreads", "Matched moneylines",
             "Timestamped records", "Odds source", "Assessment"],
        ),
        "",
        "The cached betting files carry spread fields but no quote timestamp and no two-sided moneyline fields. The stored spreads cannot be placed before the forecast cutoff, so they are not a valid as-of market benchmark and no spread-to-probability curve is fit. Market Brier skill and matched-market comparisons are unavailable on this evidence; the full-population G0-G3 comparisons remain market-blind.",
        "",
        "## Model definitions and decision",
        "",
        "- **G0:** fixed P(home win) = 0.50.",
        "- **G1:** expanding prior FBS-FBS home-win rate with Beta(1,1) smoothing, separated for neutral and non-neutral games.",
        "- **G2:** Elo initialized at 1500, logistic scale 400, fixed 55-point home advantage (zero at neutral), K=20, and 25% offseason regression. Completed FBS-FBS and FBS-FCS results update ratings.",
        "- **G3:** ridge least-squares opponent-adjusted score-margin ratings, ridge penalty 15, prior-season weight half-life one season; probability is a normal margin CDF using the pregame in-sample FBS-FBS residual scale floored at 15 points.",
        "",
        "For each UTC kickoff date, only completed games whose UTC date is at least two calendar days earlier enter the update. The ledger stores the forecast kickoff cutoff, latest history game ID/time, and history count; code asserts at least 24 hours between the latest history kickoff and forecast kickoff. All games on one UTC date share a pregame state. Neutral games receive no normal home-field advantage. Hyperparameters are fixed and no calibration is fit.",
        "",
        "**Decision:** %s" % decision,
        "",
        "## Reproduction and artifacts",
        "",
        "Run `/root/legendarypicks/backend/venv/bin/python backend/fbs_game_winner_baseline.py --run-date %s` from the repository root. Outputs are date-stamped so the prior audit artifacts remain unchanged." % run_date,
        "",
        "- Forecast ledger: `fbs_game_winner_predictions_%s.csv` (one row per game)." % run_date,
        "- Frozen 2025 ledger: `fbs_game_winner_holdout_2025_%s.csv`." % run_date,
        "- Metrics: `fbs_game_winner_metrics_%s.csv`." % run_date,
        "- Paired comparisons: `fbs_game_winner_paired_comparisons_%s.csv`." % run_date,
        "- Calibration bins: `fbs_game_winner_calibration_%s.csv`." % run_date,
        "- Input manifest: `fbs_game_winner_sources_%s.csv`." % run_date,
        "- Market availability audit: `fbs_game_winner_market_coverage_%s.csv`." % run_date,
        "- Calibration figure: `%s`." % plot_name,
        "",
        "**Phase 1 limitation:** the matched as-of sportsbook benchmark is not available from the cached market files because their quote times are absent. No player-prop history was used. This run does not start Phase 2 historical backfill.",
        "",
    ]
    with open(report_path, "w", encoding="utf-8") as output:
        output.write("\n".join(report))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "research", "fbs", "parquet"))
    parser.add_argument("--output-dir", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "research", "fbs"))
    parser.add_argument("--seasons", default="2022,2023,2024,2025,2026")
    parser.add_argument("--run-date", default=None,
                        help="output date suffix YYYYMMDD; defaults to current UTC date")
    args = parser.parse_args()
    seasons = [int(part.strip()) for part in args.seasons.split(",") if part.strip()]
    run_date = args.run_date or datetime.now(pytz.UTC).strftime("%Y%m%d")
    os.makedirs(args.output_dir, exist_ok=True)

    events, coverage, _, _ = load_events(args.data_dir, seasons)
    forecasts = make_predictions(events, FIRST_EVALUATION_SEASON)
    frozen_holdout = make_frozen_season_predictions(events, 2025)
    metrics = build_metrics(forecasts, frozen_holdout)
    comparisons = paired_comparisons(forecasts, frozen_holdout)
    calibration = calibration_rows(forecasts, frozen_holdout)
    manifest = source_manifest(args.data_dir, seasons)
    market_coverage = audit_market_files(args.data_dir, forecasts)

    forecasts_path = os.path.join(
        args.output_dir, "fbs_game_winner_predictions_%s.csv" % run_date
    )
    frozen_path = os.path.join(
        args.output_dir, "fbs_game_winner_holdout_2025_%s.csv" % run_date
    )
    metrics_path = os.path.join(
        args.output_dir, "fbs_game_winner_metrics_%s.csv" % run_date
    )
    comparisons_path = os.path.join(
        args.output_dir, "fbs_game_winner_paired_comparisons_%s.csv" % run_date
    )
    calibration_path = os.path.join(
        args.output_dir, "fbs_game_winner_calibration_%s.csv" % run_date
    )
    manifest_path = os.path.join(
        args.output_dir, "fbs_game_winner_sources_%s.csv" % run_date
    )
    market_path = os.path.join(
        args.output_dir, "fbs_game_winner_market_coverage_%s.csv" % run_date
    )
    plot_name = "fbs_game_winner_calibration_%s.png" % run_date
    plot_path = os.path.join(args.output_dir, plot_name)
    report_path = os.path.join(
        args.output_dir, "RESULT-FBS-GAME-WINNERS-%s.md" % run_date
    )

    export = forecasts.copy()
    export["kickoff_utc"] = export.kickoff_utc.map(lambda value: value.isoformat())
    export["utc_date"] = export.utc_date.map(str)
    columns = [
        "game_id", "kickoff_utc", "pregame_data_cutoff_utc", "season", "week",
        "season_type", "game_phase", "home_team_id", "home_team",
        "home_conference", "away_team_id", "away_team", "away_conference",
        "neutral_site", "venue", "kickoff_local", "day_group", "home_rank",
        "away_rank", "home_score", "away_score", "home_win",
        "conference_matchup_group", "home_conference_group",
        "away_conference_group", "week_start_utc", "coinflip_home_prob",
        "home_base_prob", "elo_home_prob",
        "elo_rating_margin", "margin_home_prob", "predicted_score_margin",
        "margin_sigma_points", "training_games_available", "history_embargo_days",
        "latest_history_game_kickoff_utc", "latest_history_game_id",
        "feature_set", "model_version", "result_source",
    ]
    export[columns].to_csv(forecasts_path, index=False, quoting=csv.QUOTE_MINIMAL)
    frozen_export = frozen_holdout.copy()
    frozen_export["kickoff_utc"] = frozen_export.kickoff_utc.map(
        lambda value: value.isoformat()
    )
    frozen_export["utc_date"] = frozen_export.utc_date.map(str)
    frozen_export.to_csv(frozen_path, index=False, quoting=csv.QUOTE_MINIMAL)
    metrics.to_csv(metrics_path, index=False)
    comparisons.to_csv(comparisons_path, index=False)
    calibration.to_csv(calibration_path, index=False)
    manifest.to_csv(manifest_path, index=False)
    market_coverage.to_csv(market_path, index=False)
    plot_calibration(calibration, plot_path)
    build_report(
        forecasts, frozen_holdout, coverage, metrics, comparisons, calibration,
        manifest, market_coverage, plot_name, report_path, run_date,
    )

    print("wrote %d forecasts across seasons %s" % (len(forecasts), ",".join(map(str, seasons))))
    for season in sorted(forecasts.season.unique()):
        print("  %d: %d FBS-vs-FBS games" % (season, int(forecasts.season.eq(season).sum())))
    print("frozen 2025 holdout: %d FBS-vs-FBS games" % len(frozen_holdout))
    print("report: %s" % report_path)
    print("predictions: %s" % forecasts_path)
    print("frozen holdout: %s" % frozen_path)
    print("metrics: %s" % metrics_path)
    print("paired comparisons: %s" % comparisons_path)
    print("calibration: %s" % calibration_path)
    print("input manifest: %s" % manifest_path)
    print("market coverage: %s" % market_path)
    print("calibration plot: %s" % plot_path)


if __name__ == "__main__":
    main()
