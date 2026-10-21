#!/usr/bin/env python3
"""Fit and forward-evaluate the NHL V3 Phase 2A event simulator.

Inputs are the hash-pinned Phase 1 ledgers and official outcomes. The fit uses
2018-2020; 2021 is development; the partial 2022 season is the untouched final
holdout. All feature histories use games on earlier calendar dates only.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import csv
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import sys
import time as walltime
from typing import Iterable, Mapping, Sequence

import numpy as np

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
PHASE1 = REPO_ROOT / "research/nhl/nhl-v3-phase1-replay-2026-10-21"
if str(PHASE1) not in sys.path:
    sys.path.insert(0, str(PHASE1))

from prospective import PregameFeature, PregameSnapshot, SimulationRequest  # noqa: E402
from replay_data import (DEFAULT_ARTIFACT_DIR, DEFAULT_LABEL_DIR, DEFAULT_OFFICIAL_DIR,
                         InputBundle, iter_game_event_groups, load_bundle, sha256_file)  # noqa: E402
from replay_model import (SHOT_EVENTS, SOG_EVENTS, GameDefinition, NormalizedEvent,
                          GameReplay, parse_situation_code, replay_game)  # noqa: E402
from stochastic_model import (GOAL_DIMENSIONS, LEVELS, OUTCOME_CLASSES, FittedParameters,
                              coordinate_features, fit_parameters, period_level,
                              game_time_level, quality_level, score_level, simulate_game, state_key,
                              time_level)  # noqa: E402
from team_strength_v2_reference import TeamStrength as V2TeamStrength  # noqa: E402


FIT_SEASONS = (2018, 2019, 2020)
DEVELOPMENT_SEASONS = (2021,)
FINAL_HOLDOUT_SEASONS = (2022,)
OFFICIAL_SCORE_TARGETS = "canonical_frame.csv: canonical_home_score/canonical_away_score"
OFFICIAL_SOG_TARGETS = "official_team_sog_validation.csv: official_team_sog"
V2_CANONICAL_SHA256 = "7cd2fc9a6e84470c177b704aa56ba328ad67522698244ce1f182ddcb9e439f52"
V2_REFERENCE_CODE_SHA256 = "021a7364bb026240dfc2dd5aacba2f3981743484596e9c809bd3a2ebade57955"
V2_REFERENCE_COMMIT = "3935814dfba0bd2e33fb282e450d41b89a58486f"
V2_FROZEN_MODEL_SHA256 = "032f8383e946260eee11128a83b2753e2aefd0207b8905cb2483d488d6ea9e59"
DEFAULT_V2_CANONICAL = Path("/root/lp-data/nhl-official-outcome-backfill-2026-10-20/source/canonical_games_source.csv")
DEFAULT_V2_FROZEN_MODEL = Path("/root/lp-nhl-v2-interval/research/nhl/prospective-2026-27/frozen_models_2026-27_v2.json")


def _inc_pair(mapping: dict[tuple[str, ...], list[float]], key: tuple[str, ...],
              first: float = 0.0, second: float = 0.0) -> None:
    row = mapping.setdefault(key, [0.0, 0.0])
    row[0] += first
    row[1] += second


def _inc_binary(mapping: dict[tuple[str, ...], list[int]], key: tuple[str, ...],
                success: bool, total: int = 1) -> None:
    row = mapping.setdefault(key, [0, 0])
    row[0] += int(success)
    row[1] += total


def _as_pair(mapping: Mapping[tuple[str, ...], Sequence[float]]) -> dict[tuple[str, ...], tuple[float, int]]:
    return {key: (float(value[0]), int(value[1])) for key, value in mapping.items()}


def _as_binary(mapping: Mapping[tuple[str, ...], Sequence[int]]) -> dict[tuple[str, ...], tuple[int, int]]:
    return {key: (int(value[0]), int(value[1])) for key, value in mapping.items()}


def _load_v2_canonical(path: Path, frozen_model_path: Path
                       ) -> tuple[dict[str, V2CanonicalGame], dict[str, object]]:
    canonical_sha = sha256_file(path)
    if canonical_sha != V2_CANONICAL_SHA256:
        raise ValueError(f"V2_CANONICAL_HASH_MISMATCH {canonical_sha}")
    frozen_sha = sha256_file(frozen_model_path)
    if frozen_sha != V2_FROZEN_MODEL_SHA256:
        raise ValueError(f"V2_FROZEN_MODEL_HASH_MISMATCH {frozen_sha}")
    code_sha = sha256_file(HERE / "team_strength_v2_reference.py")
    if code_sha != V2_REFERENCE_CODE_SHA256:
        raise ValueError(f"V2_REFERENCE_CODE_HASH_MISMATCH {code_sha}")
    frozen = json.loads(frozen_model_path.read_text(encoding="utf-8"))
    frozen_body = {key: value for key, value in frozen.items() if key != "model_sha256"}
    frozen_internal_sha = hashlib.sha256(
        (json.dumps(frozen_body, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
        .encode("utf-8")).hexdigest()
    if frozen.get("model_sha256") != frozen_internal_sha:
        raise ValueError("V2_FROZEN_MODEL_INTERNAL_HASH_MISMATCH")
    if frozen.get("input_hashes", {}).get("canonical_games_sha256") != canonical_sha:
        raise ValueError("V2_FROZEN_CANONICAL_PIN_MISMATCH")

    rows: dict[str, V2CanonicalGame] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"game_id", "season", "game_type", "game_date", "home_team", "away_team",
                    "home_goals_model_target", "away_goals_model_target", "official_home_score",
                    "official_away_score", "neutral_site"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError("V2_CANONICAL_REQUIRED_COLUMNS_MISSING")
        for row in reader:
            game_id = row["game_id"]
            if game_id in rows:
                raise ValueError(f"V2_CANONICAL_DUPLICATE_GAME_ID {game_id}")
            neutral_text = row["neutral_site"].strip().lower()
            if neutral_text not in {"true", "false", "1", "0"}:
                raise ValueError(f"V2_CANONICAL_NEUTRAL_INVALID {game_id}/{neutral_text}")
            try:
                home_xg = float(row.get("home_xgf_5v5") or 0.0)
                away_xg = float(row.get("away_xgf_5v5") or 0.0)
            except ValueError:
                home_xg = away_xg = 0.0
            rows[game_id] = V2CanonicalGame(
                game_id=game_id, season=int(row["season"]), game_date=row["game_date"],
                home_team=row["home_team"], away_team=row["away_team"],
                home_goals_model_target=int(row["home_goals_model_target"]),
                away_goals_model_target=int(row["away_goals_model_target"]),
                home_xg_5v5=home_xg, away_xg_5v5=away_xg,
                official_home_score=int(row["official_home_score"]),
                official_away_score=int(row["official_away_score"]),
                neutral_site=neutral_text in {"true", "1"})
    if len(rows) != int(frozen.get("fit_rows", {}).get("goals_fit_games", -1)):
        raise ValueError("V2_CANONICAL_POPULATION_COUNT_MISMATCH")
    metadata = {"canonical_games_sha256": canonical_sha,
                "frozen_model_file_sha256": frozen_sha,
                "frozen_model_internal_sha256": frozen_internal_sha,
                "frozen_model_version": frozen.get("model_version"),
                "frozen_model_fit_games": len(rows),
                "reference_code_sha256": code_sha,
                "reference_code_commit": V2_REFERENCE_COMMIT}
    return rows, metadata


def _event_side(definition: GameDefinition, event: NormalizedEvent) -> str | None:
    if event.event_owner_team_id == definition.home_team_id:
        return "home"
    if event.event_owner_team_id == definition.away_team_id:
        return "away"
    return None


def _event_elapsed(event: NormalizedEvent, duration: int) -> int:
    try:
        minute_text, second_text = event.time_in_period.split(":", 1)
        elapsed = int(minute_text) * 60 + int(second_text)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"EVENT_CLOCK_INVALID {event.game_id}/{event.source_event_id}") from exc
    if not 0 <= elapsed <= duration:
        raise ValueError(f"EVENT_CLOCK_OUT_OF_RANGE {event.game_id}/{event.source_event_id}/{elapsed}")
    return elapsed


def _period_duration(period_type: str) -> int:
    return 1200 if period_type == "REG" else 300 if period_type == "OT" else 0


def _attempt_label(event_type: str) -> str:
    if event_type == "blocked-shot":
        return "BLOCKED"
    if event_type == "missed-shot":
        return "MISSED"
    if event_type == "goal":
        return "GOAL"
    if event_type == "shot-on-goal":
        return "SAVED"
    raise ValueError(f"SHOT_EVENT_LABEL_UNKNOWN {event_type}")


def _accepted_team_goal(event: NormalizedEvent, side: str | None) -> bool:
    return (event.period_type in {"REG", "OT"} and event.event_type == "goal" and
            event.quality.event == "ACCEPT" and event.quality.team_count == "ACCEPT" and
            side in {"home", "away"})


def _shot_type(value: str | None) -> str:
    if not value:
        return "UNKNOWN"
    normalized = value.strip().upper().replace("-", " ").replace("_", " ")
    aliases = {
        "WRIST": "WRIST", "SNAP": "SNAP", "SLAP": "SLAP", "BACKHAND": "BACKHAND",
        "TIP": "TIP", "DEFLECTED": "DEFLECTED", "WRAP AROUND": "WRAP",
        "WRAPAROUND": "WRAP",
    }
    return aliases.get(normalized, "OTHER")


@dataclass(frozen=True)
class TeamHistoryValue:
    attack_sog_per_game: float
    attack_n: int
    allowed_sog_per_game: float
    allowed_n: int
    last_game_date: str | None
    source_games: tuple[str, ...]


def _team_history_snapshots(bundle: InputBundle) -> dict[str, PregameSnapshot]:
    """Build same-team prior-10 boxscore features, with dates strictly earlier."""
    by_date: dict[str, list[GameDefinition]] = defaultdict(list)
    for game in bundle.games.values():
        by_date[game.game_date].append(game)
    history: dict[int, deque[tuple[str, str, int, int]]] = defaultdict(lambda: deque(maxlen=10))
    snapshots: dict[str, PregameSnapshot] = {}
    source_sha = bundle.pins["official_artifacts"]["official_team_sog_validation.csv"]

    def summarize(team_id: int) -> TeamHistoryValue:
        rows = list(history[team_id])
        if not rows:
            return TeamHistoryValue(0.0, 0, 0.0, 0, None, ())
        attack = sum(row[2] for row in rows) / len(rows)
        allowed = sum(row[3] for row in rows) / len(rows)
        return TeamHistoryValue(attack, len(rows), allowed, len(rows), rows[-1][0],
                                tuple(row[1] for row in rows))

    for game_date in sorted(by_date):
        day_games = sorted(by_date[game_date], key=lambda game: game.game_id)
        for game in day_games:
            home = summarize(game.home_team_id)
            away = summarize(game.away_team_id)
            scheduled = datetime.combine(date.fromisoformat(game.game_date), time(12, 0), tzinfo=timezone.utc)
            available = datetime.combine(date.fromisoformat(game.game_date) - timedelta(days=1),
                                         time(23, 59, 59), tzinfo=timezone.utc)
            features: list[PregameFeature] = []
            for side, value, team_id in (("home", home, game.home_team_id),
                                          ("away", away, game.away_team_id)):
                source_games = ",".join(value.source_games) if value.source_games else "NO_PRIOR_ACCEPTED_TEAM_SOG"
                as_of = value.last_game_date or "NO_PRIOR_DATE"
                for name, number in (("attack_sog_per_game", value.attack_sog_per_game),
                                     ("attack_sog_n", value.attack_n),
                                     ("allowed_sog_per_game", value.allowed_sog_per_game),
                                     ("allowed_sog_n", value.allowed_n)):
                    features.append(PregameFeature(
                        key=f"{side}_{name}", value=number, available_at_utc=available,
                        source_kind="official_team_sog_prior_games",
                        source_key=f"team={team_id};as_of_game_date={as_of};game_ids={source_games}",
                        source_sha256=source_sha, quality_disposition="ACCEPT"))
            snapshot = PregameSnapshot(
                game_id=game.game_id, scheduled_start_utc=scheduled,
                home_team_id=game.home_team_id, away_team_id=game.away_team_id,
                features=tuple(features))
            if any(feature.source_key.find(game.game_id) >= 0 for feature in snapshot.features):
                raise ValueError(f"TARGET_GAME_IN_PREGAME_FEATURES {game.game_id}")
            snapshots[game.game_id] = snapshot
        # Same-date outcomes are not available to another same-date game: the source
        # frame does not include exact puck-drop timestamps.
        for game in day_games:
            if game.sog_disposition != "ACCEPT":
                continue
            history[game.home_team_id].append((game.game_date, game.game_id,
                                               game.official_home_sog, game.official_away_sog))
            history[game.away_team_id].append((game.game_date, game.game_id,
                                               game.official_away_sog, game.official_home_sog))
    if set(snapshots) != set(bundle.games):
        raise ValueError("PREGAME_SNAPSHOT_COVERAGE_MISMATCH")
    return snapshots


def _fit_sog_reference(bundle: InputBundle, seasons: Sequence[int]) -> float:
    values = [value for game in bundle.games.values() if game.season in seasons and
              game.sog_disposition == "ACCEPT"
              for value in (game.official_home_sog, game.official_away_sog)]
    if not values:
        raise ValueError("NO_ACCEPTED_SOG_REFERENCE")
    return statistics.fmean(values)


def _pregame_quality_groups(snapshot: PregameSnapshot, sog_reference: float
                            ) -> dict[str, tuple[str, str]]:
    values = {feature.key: float(feature.value) for feature in snapshot.features
              if isinstance(feature.value, (float, int))}
    return {
        side: (
            quality_level(values[f"{side}_attack_sog_per_game"],
                          int(values[f"{side}_attack_sog_n"]), sog_reference),
            quality_level(values[f"{opponent}_allowed_sog_per_game"],
                          int(values[f"{opponent}_allowed_sog_n"]), sog_reference, defense=True),
        )
        for side, opponent in (("home", "away"), ("away", "home"))
    }


def _fast_state_key(groups: Mapping[str, tuple[str, str]], *, side: str,
                    period: str, strength: str, score_difference: int,
                    remaining: int) -> tuple[str, ...]:
    attack, defense = groups[side]
    return (period, strength, score_level(score_difference), time_level(remaining),
            game_time_level(period, remaining), "HOME" if side == "home" else "AWAY",
            attack, defense)


def _timeline_is_usable(events: Sequence[NormalizedEvent]) -> bool:
    ranks = {("REG", 1): 1, ("REG", 2): 2, ("REG", 3): 3, ("OT", 4): 4}
    previous_rank = 0
    previous_key: tuple[str, int] | None = None
    for event in events:
        if event.period_type not in {"REG", "OT"} or event.quality.event != "ACCEPT":
            continue
        if event.quality.period_number != "ACCEPT":
            return False
        key = (event.period_type, event.period_number)
        if key not in ranks or ranks[key] < previous_rank:
            return False
        _event_elapsed(event, _period_duration(event.period_type))
        previous_rank, previous_key = ranks[key], key
    return True


def _add_exposure_interval(exposures: dict[tuple[str, ...], list[float]], *,
                           groups: Mapping[str, tuple[str, str]],
                           period: str, period_number: int, duration: int,
                           start: int, end: int, manpower: object | None,
                           score: Mapping[str, int]) -> None:
    if end <= start:
        return
    boundaries = (300, 900)
    cursor = start
    while cursor < end:
        next_boundary = min((boundary for boundary in boundaries if boundary > cursor), default=end)
        right = min(end, next_boundary)
        if right <= cursor:
            right = end
        middle = (cursor + right) / 2.0
        remaining = max(0, int(duration - middle))
        time_group = "LATE" if remaining <= 300 else "MIDDLE" if remaining <= 900 else "EARLY"
        period_group = "OT" if period == "OT" else f"P{period_number}"
        for side in ("home", "away"):
            difference = score[side] - score["away" if side == "home" else "home"]
            if manpower is None:
                strength = "UNKNOWN"
            elif ((side == "home" and not manpower.away_goalie_present) or
                  (side == "away" and not manpower.home_goalie_present)):
                strength = "EMPTY_NET"
            elif ((side == "home" and manpower.home_skaters > manpower.away_skaters) or
                  (side == "away" and manpower.away_skaters > manpower.home_skaters)):
                strength = "ADVANTAGE"
            elif ((side == "home" and manpower.home_skaters < manpower.away_skaters) or
                  (side == "away" and manpower.away_skaters < manpower.home_skaters)):
                strength = "DISADVANTAGE"
            else:
                strength = "EVEN"
            key = _fast_state_key(groups, side=side, period=period_group,
                                  strength=strength, score_difference=difference,
                                  remaining=remaining)
            if key[3] != time_group:
                raise ValueError("RATE_TIME_BUCKET_SPLIT_MISMATCH")
            _inc_pair(exposures, key, (right - cursor) / 60.0, 0)
        cursor = right


@dataclass(frozen=True)
class HeldoutGame:
    definition: GameDefinition
    snapshot: PregameSnapshot
    actual_home_reg_ot_goals: int
    actual_away_reg_ot_goals: int
    actual_period_sog: tuple[tuple[str, int, int], ...]
    actual_period_goals: tuple[tuple[str, int, int], ...]
    sog_eligible: bool
    period_sog_eligible: bool
    period_goal_eligible: bool


@dataclass(frozen=True)
class V2CanonicalGame:
    game_id: str
    season: int
    game_date: str
    home_team: str
    away_team: str
    home_goals_model_target: int
    away_goals_model_target: int
    home_xg_5v5: float
    away_xg_5v5: float
    official_home_score: int
    official_away_score: int
    neutral_site: bool


@dataclass
class FoldData:
    parameters: FittedParameters | None
    heldout_games: list[HeldoutGame]
    train_counts: dict[str, int]
    event_eval: dict[str, dict[tuple[str, ...], list[int]]]
    event_eval_outcomes: dict[tuple[str, ...], list[int]]
    validation_target_totals: Counter[str]
    v2_model: V2TeamStrength
    v2_shootout_home_win_rate: float
    v2_training_games: int


def _build_fold(bundle: InputBundle, snapshots: Mapping[str, PregameSnapshot],
                v2_canonical: Mapping[str, V2CanonicalGame],
                fit_seasons: Sequence[int], eval_seasons: Sequence[int]) -> FoldData:
    location_reservoirs.clear()
    location_seen.clear()
    location_rngs.clear()
    sog_reference = _fit_sog_reference(bundle, fit_seasons)
    exposures: dict[tuple[str, ...], list[float]] = {}
    sog_binary: dict[tuple[str, ...], list[int]] = {}
    block_binary: dict[tuple[str, ...], list[int]] = {}
    goal_binary: dict[tuple[str, ...], list[int]] = {}
    outcome_classes: Counter[str] = Counter()
    event_eval: dict[str, dict[tuple[str, ...], list[int]]] = {
        "sog": {}, "block": {}, "goal": {}}
    event_eval_outcomes: dict[tuple[str, ...], list[int]] = {}
    heldout: list[HeldoutGame] = []
    training_counts: Counter[str] = Counter()
    penalty_calls = 0
    shootout_goals = 0
    shootout_attempts = 0
    baseline_attempts = 0
    timeline_games = 0
    timeline_excluded = 0
    training_game_count = 0
    evaluation_game_count = 0
    validation_target_totals: Counter[str] = Counter()
    v2_training_rows: list[dict[str, object]] = []
    v2_team_names_by_id: dict[int, str] = {}
    shootout_decisions = Counter()

    for game_id, events in iter_game_event_groups(bundle):
        definition = bundle.games[game_id]
        season = definition.season
        if season not in fit_seasons and season not in eval_seasons:
            continue
        if definition.score_disposition != "ACCEPT":
            raise ValueError(f"TEAM_SCORE_COMPONENT_NOT_ACCEPTED {game_id}/{definition.score_disposition}")
        replay = replay_game(definition, bundle.provenance[game_id], events)
        actual_score = replay.shootout_adjusted_score
        if (actual_score["home"] != definition.official_home_score or
                actual_score["away"] != definition.official_away_score):
            raise ValueError(f"OFFICIAL_SCORE_REPLAY_MISMATCH {game_id}")
        actual_regot = replay.ordinary_score
        canonical = v2_canonical.get(game_id)
        if canonical is None:
            raise ValueError(f"V2_CANONICAL_GAME_ID_MISSING {game_id}")
        if (canonical.season != definition.season or canonical.game_date != definition.game_date or
                canonical.home_team != definition.home_team or canonical.away_team != definition.away_team):
            raise ValueError(f"V2_CANONICAL_STABLE_IDENTITY_JOIN_MISMATCH {game_id}")
        if (canonical.official_home_score != definition.official_home_score or
                canonical.official_away_score != definition.official_away_score or
                canonical.home_goals_model_target != int(actual_regot["home"]) or
                canonical.away_goals_model_target != int(actual_regot["away"])):
            raise ValueError(f"V2_CANONICAL_OFFICIAL_TARGET_MISMATCH {game_id}")
        for team_id, team_name in ((definition.home_team_id, canonical.home_team),
                                   (definition.away_team_id, canonical.away_team)):
            previous_name = v2_team_names_by_id.setdefault(team_id, team_name)
            if previous_name != team_name:
                raise ValueError(f"TEAM_ID_TO_V2_LABEL_NOT_ONE_TO_ONE {team_id}/{previous_name}/{team_name}")
        if season in eval_seasons:
            evaluation_game_count += 1
            validation_target_totals["team_score_targets"] += 2
            validation_target_totals["sog_eligible_games"] += int(definition.sog_disposition == "ACCEPT")
            period_sog: Counter[tuple[str, int, str]] = Counter()
            period_goals: Counter[tuple[str, int, str]] = Counter()
            period_sog_ok = definition.sog_disposition == "ACCEPT"
            period_goal_ok = definition.score_disposition == "ACCEPT"
            for event in events:
                if event.period_type not in {"REG", "OT"}:
                    continue
                side = _event_side(definition, event)
                number = event.period_number if event.period_type == "REG" else 4
                period_valid = (event.quality.period_number == "ACCEPT" and
                                (event.period_type == "OT" or number in (1, 2, 3)))
                event_team_valid = (event.quality.event == "ACCEPT" and
                                    event.quality.team_count == "ACCEPT" and side is not None)
                if event.event_type in SOG_EVENTS:
                    if not (period_valid and event_team_valid and event.ordinary_shot_eligible is True):
                        period_sog_ok = False
                    else:
                        period_sog[(event.period_type, number, side)] += 1
                if event.event_type == "goal":
                    if not (period_valid and event_team_valid):
                        period_goal_ok = False
                    else:
                        period_goals[(event.period_type, number, side)] += 1
            if period_sog_ok:
                period_sog_ok = (
                    sum(count for (_, _, side), count in period_sog.items() if side == "home") ==
                    definition.official_home_sog and
                    sum(count for (_, _, side), count in period_sog.items() if side == "away") ==
                    definition.official_away_sog)
            if period_goal_ok:
                period_goal_ok = (
                    sum(count for (_, _, side), count in period_goals.items() if side == "home") ==
                    int(actual_regot["home"]) and
                    sum(count for (_, _, side), count in period_goals.items() if side == "away") ==
                    int(actual_regot["away"]))
            heldout.append(HeldoutGame(
                definition=definition, snapshot=snapshots[game_id],
                actual_home_reg_ot_goals=int(actual_regot["home"]),
                actual_away_reg_ot_goals=int(actual_regot["away"]),
                actual_period_sog=tuple(sorted((ptype, number, side, count)
                                               for (ptype, number, side), count in period_sog.items())),
                actual_period_goals=tuple(sorted((ptype, number, side, count)
                                                 for (ptype, number, side), count in period_goals.items())),
                sog_eligible=definition.sog_disposition == "ACCEPT",
                period_sog_eligible=period_sog_ok,
                period_goal_eligible=period_goal_ok))
        is_training = season in fit_seasons
        if is_training:
            training_game_count += 1
            training_counts["official_team_score_game_targets"] += 2
            training_counts["official_team_score_games"] += 1
            v2_training_rows.append({
                "date": canonical.game_date, "season": canonical.season,
                "home": canonical.home_team, "away": canonical.away_team,
                "hg": int(actual_regot["home"]), "ag": int(actual_regot["away"]),
                "hxg": canonical.home_xg_5v5, "axg": canonical.away_xg_5v5,
                "neutral": canonical.neutral_site,
            })
            if int(actual_regot["home"]) == int(actual_regot["away"]):
                if definition.official_home_score == definition.official_away_score:
                    raise ValueError(f"SHOOTOUT_WINNER_TARGET_TIED {game_id}")
                shootout_decisions["total"] += 1
                shootout_decisions["home_wins"] += int(
                    definition.official_home_score > definition.official_away_score)
        timeline_ok = _timeline_is_usable(events)
        if is_training and timeline_ok:
            timeline_games += 1
        elif is_training:
            timeline_excluded += 1

        score = {"home": 0, "away": 0}
        pregame_groups = _pregame_quality_groups(snapshots[game_id], sog_reference)
        manpower = parse_situation_code("1551")
        period_key: tuple[str, int] | None = None
        previous_elapsed = 0
        previous_duration = 0
        current_period_goal_elapsed: int | None = None

        def finish_period() -> None:
            nonlocal period_key, previous_elapsed, previous_duration, manpower, current_period_goal_elapsed
            if not is_training or not timeline_ok or period_key is None:
                return
            period_type, number = period_key
            finish_at = (current_period_goal_elapsed if period_type == "OT" and
                         current_period_goal_elapsed is not None else previous_duration)
            _add_exposure_interval(exposures, groups=pregame_groups, period=period_type,
                                   period_number=number, duration=previous_duration,
                                   start=previous_elapsed, end=finish_at,
                                   manpower=manpower, score=score)

        for event in events:
            side = _event_side(definition, event)
            event_elapsed: int | None = None
            ordinary = event.period_type in {"REG", "OT"}
            event_manpower = parse_situation_code(event.situation_code)
            valid_period = event.quality.period_number == "ACCEPT"
            if ordinary and event.quality.event == "ACCEPT" and valid_period:
                number = event.period_number
                current_key = (event.period_type, number)
                duration = _period_duration(event.period_type)
                if period_key is None:
                    period_key = current_key
                    previous_elapsed = 0
                    previous_duration = duration
                    current_period_goal_elapsed = None
                    manpower = parse_situation_code("1551")
                elif current_key != period_key:
                    finish_period()
                    period_key = current_key
                    previous_elapsed = 0
                    previous_duration = duration
                    current_period_goal_elapsed = None
                    manpower = parse_situation_code("1551")
                recorded_elapsed = _event_elapsed(event, duration)
                elapsed = max(previous_elapsed, recorded_elapsed)
                event_elapsed = elapsed
                if is_training and timeline_ok and recorded_elapsed < previous_elapsed:
                    training_counts["rate_timeline_clock_regressions"] += 1
                    training_counts["rate_timeline_clock_regression_seconds"] += (
                        previous_elapsed - recorded_elapsed)
                if is_training and timeline_ok:
                    _add_exposure_interval(exposures, groups=pregame_groups, period=event.period_type,
                                           period_number=number, duration=duration,
                                           start=previous_elapsed, end=elapsed,
                                           manpower=manpower, score=score)
                if event_manpower is not None:
                    manpower = event_manpower

                if event.event_type in SHOT_EVENTS and event.ordinary_shot_eligible is True and side is not None and \
                        event.quality.event == "ACCEPT" and event.quality.team_count == "ACCEPT":
                    try:
                        level = period_level(event.period_type, number)
                    except ValueError:
                        level = ""
                    if level:
                        strength = "UNKNOWN"
                        if manpower is not None:
                            if ((side == "home" and not manpower.away_goalie_present) or
                                    (side == "away" and not manpower.home_goalie_present)):
                                strength = "EMPTY_NET"
                            elif ((side == "home" and manpower.home_skaters > manpower.away_skaters) or
                                  (side == "away" and manpower.away_skaters > manpower.home_skaters)):
                                strength = "ADVANTAGE"
                            elif ((side == "home" and manpower.home_skaters < manpower.away_skaters) or
                                  (side == "away" and manpower.away_skaters < manpower.home_skaters)):
                                strength = "DISADVANTAGE"
                            else:
                                strength = "EVEN"
                        remaining = duration - elapsed
                        base = _fast_state_key(
                            pregame_groups, side=side, period=level, strength=strength,
                            score_difference=score[side] - score["away" if side == "home" else "home"],
                            remaining=remaining)
                        label = _attempt_label(event.event_type)
                        on_target = label in {"SAVED", "GOAL"}
                        distance, angle = coordinate_features(
                            float(event.shot_x) if event.shot_x is not None and event.quality.spatial == "ACCEPT" else None,
                            float(event.shot_y) if event.shot_y is not None and event.quality.spatial == "ACCEPT" else None)
                        stype = _shot_type(event.shot_type if event.quality.shot_type == "ACCEPT" else None)
                        goal_key = base + (distance, angle, stype)
                        if is_training:
                            outcome_classes[label] += 1
                            _inc_binary(sog_binary, base, on_target)
                            if not on_target:
                                _inc_binary(block_binary, base, label == "BLOCKED")
                            else:
                                _inc_binary(goal_binary, goal_key, label == "GOAL")
                            baseline_attempts += 1
                            training_counts[f"event_outcome_{label.lower()}"] += 1
                            training_counts["accepted_shot_events"] += 1
                            if event.quality.spatial == "ACCEPT" and event.shot_x is not None and event.shot_y is not None:
                                training_counts["accepted_spatial_shot_events"] += 1
                        else:
                            season_map = event_eval["sog"]
                            _inc_binary(season_map, base, on_target)
                            outcome_row = event_eval_outcomes.setdefault(goal_key, [0, 0, 0, 0])
                            outcome_row[OUTCOME_CLASSES.index(label)] += 1
                            if not on_target:
                                _inc_binary(event_eval["block"], base, label == "BLOCKED")
                            else:
                                _inc_binary(event_eval["goal"], goal_key, label == "GOAL")
                            training_counts[f"evaluation_{season}_accepted_shot_events"] += 1
                        if event.quality.spatial == "ACCEPT" and event.shot_x is not None and event.shot_y is not None:
                            location = (float(event.shot_x), float(event.shot_y), stype, strength)
                            if is_training:
                                _reservoir_add(location_reservoirs, location_seen, location,
                                               rngs=location_rngs, seed=20261021, capacity=12000)
                        if is_training and timeline_ok:
                            _inc_pair(exposures, base, 0.0, 1)
                if event.event_type == "penalty" and event.quality.event == "ACCEPT" and \
                        event.quality.penalty_timing == "ACCEPT" and event.quality.penalty_duration == "ACCEPT" and \
                        event.penalty_duration_minutes == 2 and event.period_type == "REG" and is_training:
                    penalty_calls += 1
                previous_elapsed = elapsed
            elif event.period_type == "SO" and event.event_type in SHOT_EVENTS and \
                    event.quality.event == "ACCEPT" and event.ordinary_shot_eligible is False:
                if is_training:
                    shootout_attempts += 1
                    shootout_goals += int(event.event_type == "goal")

            # Team scoring disposition is independent of shot-attempt eligibility and shifts.
            if _accepted_team_goal(event, side):
                score[side] += 1
                training_counts["accepted_team_goals_used_for_state"] += int(is_training)
                if (is_training and timeline_ok and event.period_type == "OT" and
                        event_elapsed is not None and current_period_goal_elapsed is None):
                    current_period_goal_elapsed = event_elapsed

        finish_period()
        if is_training:
            training_counts["rate_timeline_games"] += int(timeline_ok)
            training_counts["rate_timeline_excluded_games"] += int(not timeline_ok)
        if season in eval_seasons:
            # All team-score rows are retained regardless of shift or SOG disposition.
            validation_target_totals["accepted_team_score_games"] += 1

    if training_game_count == 0 or evaluation_game_count == 0:
        raise ValueError("FOLD_GAME_POPULATION_EMPTY")
    training_counts["fit_games"] = training_game_count
    training_counts["fit_score_team_targets"] = training_game_count * 2
    training_counts["evaluation_games"] = evaluation_game_count
    exposure_minutes = sum(value[0] for value in exposures.values())
    attempts_in_rate_population = int(sum(value[1] for value in exposures.values()
                                         if value[0] > 0))
    training_counts["rate_training_attempts"] = attempts_in_rate_population
    training_counts["rate_training_exposure_minutes"] = round(exposure_minutes, 4)
    training_counts["fit_penalty_calls"] = penalty_calls
    training_counts["fit_shootout_attempts"] = shootout_attempts
    training_counts["fit_shootout_goals"] = shootout_goals
    training_counts["official_sog_eligible_fit_games"] = sum(
        game.sog_disposition == "ACCEPT" for game in bundle.games.values() if game.season in fit_seasons)
    training_counts["official_score_targets_from_all_fit_games"] = training_game_count * 2
    training_counts["v2_team_strength_fit_games"] = len(v2_training_rows)
    training_counts["v2_shootout_decision_games"] = shootout_decisions["total"]
    training_counts["v2_neutral_site_fit_games"] = sum(bool(row["neutral"]) for row in v2_training_rows)

    location_pool = _flatten_reservoirs(location_reservoirs)
    location_pools = {level: tuple(row for row in location_pool if row[3] == level)
                      for level in ("EVEN", "ADVANTAGE", "DISADVANTAGE", "EMPTY_NET", "UNKNOWN")}
    parameters = fit_parameters(
        fit_seasons=fit_seasons,
        rate_exposure_counts=_as_pair(exposures),
        sog_counts=_as_binary(sog_binary), block_counts=_as_binary(block_binary),
        goal_counts=_as_binary(goal_binary),
        outcome_counts=[outcome_classes[label] for label in OUTCOME_CLASSES],
        baseline_attempts=attempts_in_rate_population,
        baseline_exposure_minutes=exposure_minutes,
        penalty_calls=penalty_calls,
        penalty_exposure_minutes=60.0 * training_game_count,
        shootout_goals=shootout_goals, shootout_attempts=shootout_attempts,
        sog_reference=sog_reference, location_pool=location_pool,
        location_pools=location_pools, training_counts=training_counts)
    if not v2_training_rows:
        raise ValueError("V2_TEAM_STRENGTH_FIT_POPULATION_EMPTY")
    v2_model = V2TeamStrength(v2_training_rows)
    shootout_home_win_rate = (shootout_decisions["home_wins"] / shootout_decisions["total"]
                              if shootout_decisions["total"] else 0.5)
    return FoldData(parameters, heldout, dict(training_counts), event_eval,
                    event_eval_outcomes, validation_target_totals, v2_model,
                    shootout_home_win_rate, len(v2_training_rows))


def _reservoir_add(reservoirs: dict[str, list[tuple[float, float, str, str]]],
                   seen: Counter[str], row: tuple[float, float, str, str], *,
                   rngs: dict[str, random.Random],
                   seed: int, capacity: int) -> None:
    level = row[3]
    pool = reservoirs.setdefault(level, [])
    seen[level] += 1
    if len(pool) < capacity:
        pool.append(row)
        return
    rng = rngs.setdefault(level, random.Random(seed + sum(level.encode("utf-8")) * 104729))
    index = rng.randrange(seen[level])
    if index < capacity:
        pool[index] = row


location_reservoirs: dict[str, list[tuple[float, float, str, str]]] = {}
location_seen: Counter[str] = Counter()
location_rngs: dict[str, random.Random] = {}


def _flatten_reservoirs(reservoirs: Mapping[str, Sequence[tuple[float, float, str, str]]]
                        ) -> tuple[tuple[float, float, str, str], ...]:
    return tuple(row for level in sorted(reservoirs) for row in reservoirs[level])


def _binary_probabilities(beta: Sequence[float], key: tuple[str, ...], dimensions) -> tuple[float, float]:
    from stochastic_model import sigmoid, _predict_linear
    return sigmoid(_predict_linear(beta, key, dimensions)), 0.0


def _event_model_metrics(parameters: FittedParameters, fold: FoldData) -> dict[str, object]:
    from stochastic_model import _predict_linear, sigmoid
    outcome_counts = fold.event_eval_outcomes
    total = sum(sum(row) for row in outcome_counts.values())
    if total == 0:
        raise ValueError("EVENT_EVALUATION_POPULATION_EMPTY")
    simple = parameters.baseline_outcome_probabilities
    scores = {"conditional": {"log_loss": 0.0, "multiclass_brier": 0.0},
              "simple_average": {"log_loss": 0.0, "multiclass_brier": 0.0}}
    state_scores: dict[str, dict[str, dict[str, float]]] = {
        name: {} for name, _, _ in LEVELS}
    for full_key, counts in outcome_counts.items():
        base = full_key[:len(LEVELS)]
        p_sog = sigmoid(_predict_linear(parameters.sog_logit_coefficients, base, parameters.rate_dimensions))
        p_block = sigmoid(_predict_linear(parameters.block_logit_coefficients, base, parameters.rate_dimensions))
        p_goal = sigmoid(_predict_linear(parameters.goal_logit_coefficients, full_key, parameters.goal_dimensions))
        probs = ((1.0 - p_sog) * p_block, (1.0 - p_sog) * (1.0 - p_block),
                 p_sog * (1.0 - p_goal), p_sog * p_goal)
        base = full_key[:len(LEVELS)]
        for index, count in enumerate(counts):
            if count <= 0:
                continue
            for name, probability in (("conditional", probs[index]), ("simple_average", simple[index])):
                probability = min(1.0 - 1e-12, max(1e-12, probability))
                scores[name]["log_loss"] += -count * math.log(probability)
            for name, forecast in (("conditional", probs), ("simple_average", simple)):
                scores[name]["multiclass_brier"] += count * sum(
                    (float(i == index) - probability) ** 2 for i, probability in enumerate(forecast))
            for dimension_index, (dimension_name, _, _) in enumerate(LEVELS):
                cell = state_scores[dimension_name].setdefault(base[dimension_index], {
                    "n": 0.0, "conditional_log_loss": 0.0,
                    "conditional_multiclass_brier": 0.0,
                    "simple_average_log_loss": 0.0,
                    "simple_average_multiclass_brier": 0.0,
                })
                cell["n"] += count
                for name, forecast in (("conditional", probs), ("simple_average", simple)):
                    probability = min(1.0 - 1e-12, max(1e-12, forecast[index]))
                    cell[f"{name}_log_loss"] += -count * math.log(probability)
                    cell[f"{name}_multiclass_brier"] += count * sum(
                        (float(i == index) - p) ** 2 for i, p in enumerate(forecast))
    for values in scores.values():
        values["log_loss"] /= total
        values["multiclass_brier"] /= total
    scores["n_shot_attempts"] = total
    scores["by_state"] = {
        dimension: {
            value: {metric: (number / cell["n"] if metric != "n" else int(number))
                    for metric, number in cell.items()}
            for value, cell in sorted(levels.items())
        }
        for dimension, levels in state_scores.items()
    }
    return scores


def _crps_discrete(samples: Sequence[int], observation: int) -> float:
    if not samples:
        raise ValueError("CRPS_SAMPLES_EMPTY")
    maximum = max(max(samples), observation)
    cumulative = 0
    score = 0.0
    for value in range(maximum + 1):
        cumulative += sum(sample == value for sample in samples)
        forecast_cdf = cumulative / len(samples)
        target_cdf = 1.0 if observation <= value else 0.0
        score += (forecast_cdf - target_cdf) ** 2
    return score


def _energy_score(samples: Sequence[tuple[int, int]], observation: tuple[int, int]) -> float:
    if not samples:
        raise ValueError("ENERGY_SAMPLES_EMPTY")
    first = statistics.fmean(math.hypot(home - observation[0], away - observation[1])
                             for home, away in samples)
    pairwise = 0.0
    for home, away in samples:
        pairwise += sum(math.hypot(home - other_home, away - other_away)
                        for other_home, other_away in samples)
    return first - pairwise / (2.0 * len(samples) ** 2)


def _quantile(sorted_values: Sequence[int], probability: float) -> int:
    index = min(len(sorted_values) - 1, max(0, int(math.floor(probability * (len(sorted_values) - 1)))))
    return sorted_values[index]


def _count_distribution_coverage(samples: Sequence[int], observation: int,
                                 coverages: Sequence[float] = (0.50, 0.80, 0.90)
                                 ) -> dict[str, bool]:
    ordered = sorted(samples)
    if not ordered:
        raise ValueError("COUNT_CALIBRATION_SAMPLES_EMPTY")
    result = {}
    for coverage in coverages:
        tail = (1.0 - coverage) / 2.0
        result[f"{int(coverage * 100)}"] = (
            _quantile(ordered, tail) <= observation <= _quantile(ordered, 1.0 - tail))
    return result


def _bootstrap_mean(values: Sequence[float], seed: int, draws: int = 2000) -> list[float]:
    if not values:
        return [0.0, 0.0]
    rng = random.Random(seed)
    results = sorted(statistics.fmean(values[rng.randrange(len(values))] for _ in values)
                     for _ in range(draws))
    return [results[int(0.025 * (draws - 1))], results[int(0.975 * (draws - 1))]]


def _evaluate_simulations(games: Sequence[HeldoutGame], parameters: FittedParameters,
                          sims: int, *, seed: int, conditional: bool) -> dict[str, object]:
    start = walltime.perf_counter()
    game_rows: list[dict[str, object]] = []
    sog_crps: list[float] = []
    sog_mean_absolute_errors: list[float] = []
    goal_mean_absolute_errors: list[float] = []
    goal_crps: list[float] = []
    winner_brier: list[float] = []
    energy_scores: list[float] = []
    final_home_sog_mcse: list[float] = []
    winner_mcse: list[float] = []
    period_shot_absolute_errors: dict[str, list[float]] = defaultdict(list)
    period_goal_absolute_errors: dict[str, list[float]] = defaultdict(list)
    reliability_bins: dict[int, list[tuple[float, int]]] = defaultdict(list)
    count_calibration: dict[str, dict[str, list[bool]]] = {
        "team_sog": {"50": [], "80": [], "90": []},
        "team_reg_ot_goals": {"50": [], "80": [], "90": []},
    }
    validation_count = 0
    accepted_sog_games = 0
    for game_index, game in enumerate(games):
        home_sog: list[int] = []
        away_sog: list[int] = []
        home_goals: list[int] = []
        away_goals: list[int] = []
        home_final: list[int] = []
        away_final: list[int] = []
        home_wins: list[int] = []
        period_sog_samples: dict[str, list[int]] = defaultdict(list)
        period_goal_samples: dict[str, list[int]] = defaultdict(list)
        for trial in range(sims):
            request = SimulationRequest(game.snapshot, seed + game_index * 1000003 + trial)
            result = simulate_game(request, parameters, conditional=conditional, validate=True)
            validation_count += 1
            home_sog.append(result.home_sog)
            away_sog.append(result.away_sog)
            home_goals.append(result.home_reg_ot_goals)
            away_goals.append(result.away_reg_ot_goals)
            home_final.append(result.home_final_goals)
            away_final.append(result.away_final_goals)
            home_wins.append(int(result.home_wins))
            sog_by_period = {(ptype, number, side): count
                             for ptype, number, side, count in result.period_sog}
            goals_by_period = {(ptype, number, side): count
                               for ptype, number, side, count in result.period_goals}
            for ptype, number in (("REG", 1), ("REG", 2), ("REG", 3), ("OT", 4)):
                key = f"{ptype}{number}"
                period_sog_samples[key].append(sog_by_period.get((ptype, number, "home"), 0) +
                                               sog_by_period.get((ptype, number, "away"), 0))
                period_goal_samples[key].append(goals_by_period.get((ptype, number, "home"), 0) +
                                                goals_by_period.get((ptype, number, "away"), 0))
        actual_home_win = int(game.definition.official_home_score > game.definition.official_away_score)
        p_home = statistics.fmean(home_wins)
        winner_loss = (p_home - actual_home_win) ** 2
        winner_brier.append(winner_loss)
        reliability_bins[min(9, int(p_home * 10))].append((p_home, actual_home_win))
        team_sog_crps = None
        if game.sog_eligible:
            accepted_sog_games += 1
            sog_mean_absolute_errors.extend((
                abs(statistics.fmean(home_sog) - game.definition.official_home_sog),
                abs(statistics.fmean(away_sog) - game.definition.official_away_sog)))
            team_sog_crps = (_crps_discrete(home_sog, game.definition.official_home_sog) +
                             _crps_discrete(away_sog, game.definition.official_away_sog)) / 2.0
            sog_crps.append(team_sog_crps)
            for side_samples, observed in ((home_sog, game.definition.official_home_sog),
                                           (away_sog, game.definition.official_away_sog)):
                for coverage, covered in _count_distribution_coverage(side_samples, observed).items():
                    count_calibration["team_sog"][coverage].append(covered)
        team_goal_crps = (_crps_discrete(home_goals, game.actual_home_reg_ot_goals) +
                          _crps_discrete(away_goals, game.actual_away_reg_ot_goals)) / 2.0
        goal_crps.append(team_goal_crps)
        goal_mean_absolute_errors.extend((
            abs(statistics.fmean(home_goals) - game.actual_home_reg_ot_goals),
            abs(statistics.fmean(away_goals) - game.actual_away_reg_ot_goals)))
        for side_samples, observed in ((home_goals, game.actual_home_reg_ot_goals),
                                       (away_goals, game.actual_away_reg_ot_goals)):
            for coverage, covered in _count_distribution_coverage(side_samples, observed).items():
                count_calibration["team_reg_ot_goals"][coverage].append(covered)
        actual_final = (game.definition.official_home_score, game.definition.official_away_score)
        energy_scores.append(_energy_score(list(zip(home_final, away_final)), actual_final))
        expected_period_sog = {(ptype, number, side): count
                               for ptype, number, side, count in game.actual_period_sog}
        expected_period_goals = {(ptype, number, side): count
                                 for ptype, number, side, count in game.actual_period_goals}
        for ptype, number in (("REG", 1), ("REG", 2), ("REG", 3), ("OT", 4)):
            key = f"{ptype}{number}"
            actual_sog = (expected_period_sog.get((ptype, number, "home"), 0) +
                          expected_period_sog.get((ptype, number, "away"), 0)) \
                if game.period_sog_eligible else None
            actual_goals = (expected_period_goals.get((ptype, number, "home"), 0) +
                            expected_period_goals.get((ptype, number, "away"), 0)) \
                if game.period_goal_eligible else None
            if actual_sog is not None:
                period_shot_absolute_errors[key].append(abs(statistics.fmean(period_sog_samples[key]) - actual_sog))
            if actual_goals is not None:
                period_goal_absolute_errors[key].append(abs(statistics.fmean(period_goal_samples[key]) - actual_goals))
        home_sd = statistics.pstdev(home_sog)
        win_sd = statistics.pstdev(home_wins)
        final_scores = list(zip(home_final, away_final))
        exact_mass = sum(pair == actual_final for pair in final_scores) / sims
        game_rows.append({
            "game_id": game.definition.game_id,
            "season": game.definition.season,
            "date": game.definition.game_date,
            "sog_eligible": game.sog_eligible,
            "actual_home_sog": game.definition.official_home_sog if game.sog_eligible else None,
            "actual_away_sog": game.definition.official_away_sog if game.sog_eligible else None,
            "predicted_home_sog_mean": statistics.fmean(home_sog),
            "predicted_away_sog_mean": statistics.fmean(away_sog),
            "team_sog_crps": team_sog_crps,
            "actual_home_reg_ot_goals": game.actual_home_reg_ot_goals,
            "actual_away_reg_ot_goals": game.actual_away_reg_ot_goals,
            "predicted_home_reg_ot_goals_mean": statistics.fmean(home_goals),
            "predicted_away_reg_ot_goals_mean": statistics.fmean(away_goals),
            "team_goal_crps_reg_ot": team_goal_crps,
            "actual_official_home_final": actual_final[0],
            "actual_official_away_final": actual_final[1],
            "predicted_home_win_probability": p_home,
            "winner_brier": winner_loss,
            "final_score_exact_mass": exact_mass,
            "final_score_energy": energy_scores[-1],
            "home_sog_mean_mcse": home_sd / math.sqrt(sims),
            "home_win_probability_mcse": math.sqrt(max(0.0, p_home * (1.0 - p_home) / sims)),
        })
        final_home_sog_mcse.append(home_sd / math.sqrt(sims))
        winner_mcse.append(math.sqrt(max(0.0, p_home * (1.0 - p_home) / sims)))
    elapsed = walltime.perf_counter() - start
    return {
        "conditional": conditional,
        "sims_per_game": sims,
        "games": len(games),
        "eligible_team_sog_games": accepted_sog_games,
        "simulation_accounting_failures": 0,
        "validated_simulations": validation_count,
        "runtime_seconds": elapsed,
        "runtime_ms_per_game_simulation": 1000.0 * elapsed / max(1, validation_count),
        "team_sog_crps": statistics.fmean(sog_crps) if sog_crps else None,
        "team_sog_mean_absolute_error": (statistics.fmean(sog_mean_absolute_errors)
                                         if sog_mean_absolute_errors else None),
        "reg_ot_team_goal_crps": statistics.fmean(goal_crps),
        "reg_ot_team_goal_mean_absolute_error": statistics.fmean(goal_mean_absolute_errors),
        "count_distribution_calibration": {
            metric: {coverage: {"n": len(values), "nominal_coverage": int(coverage) / 100.0,
                               "observed_coverage": statistics.fmean(values)}
                     for coverage, values in calibrations.items()}
            for metric, calibrations in count_calibration.items()
        },
        "winner_brier": statistics.fmean(winner_brier),
        "final_score_energy_score": statistics.fmean(energy_scores),
        "final_score_exact_log_score": -statistics.fmean(
            math.log(max(1.0 / sims, row["final_score_exact_mass"])) for row in game_rows),
        "mean_home_sog_mcse": statistics.fmean(final_home_sog_mcse),
        "mean_home_win_probability_mcse": statistics.fmean(winner_mcse),
        "period_sog_mae_by_period": {key: statistics.fmean(values)
                                      for key, values in period_shot_absolute_errors.items()},
        "period_sog_eligible_games_by_period": {
            key: len(values) for key, values in period_shot_absolute_errors.items()},
        "period_goal_mae_by_period": {key: statistics.fmean(values)
                                      for key, values in period_goal_absolute_errors.items()},
        "period_goal_eligible_games_by_period": {
            key: len(values) for key, values in period_goal_absolute_errors.items()},
        "winner_reliability_bins": {
            str(index): {"n": len(rows), "mean_probability": statistics.fmean(p for p, _ in rows),
                         "observed_home_win_rate": statistics.fmean(y for _, y in rows)}
            for index, rows in sorted(reliability_bins.items()) if rows},
        "paired_game_rows": game_rows,
    }


def _evaluate_v2_score_distribution(games: Sequence[HeldoutGame], model: V2TeamStrength,
                                   canonical: Mapping[str, V2CanonicalGame],
                                   shootout_home_win_rate: float, sims: int, *, seed: int
                                   ) -> dict[str, object]:
    """Evaluate the v2 score-only method re-fit on the same forward training window."""
    started = walltime.perf_counter()
    rows: list[dict[str, object]] = []
    goal_crps: list[float] = []
    goal_mae: list[float] = []
    winner_losses: list[float] = []
    score_energy: list[float] = []
    win_mcse: list[float] = []
    goal_coverage: dict[str, list[bool]] = {"50": [], "80": [], "90": []}
    for game_index, game in enumerate(games):
        source = canonical[game.definition.game_id]
        home_mu, away_mu = model.mus(source.home_team, source.away_team, source.neutral_site)
        rng = np.random.default_rng(seed + game_index * 1000003)
        home_goals = rng.poisson(home_mu, size=sims).astype(int)
        away_goals = rng.poisson(away_mu, size=sims).astype(int)
        home_final = home_goals.copy()
        away_final = away_goals.copy()
        tied = home_goals == away_goals
        shootout_home = rng.random(int(tied.sum())) < shootout_home_win_rate
        home_final[tied] += shootout_home.astype(int)
        away_final[tied] += (~shootout_home).astype(int)
        home_goal_crps = _crps_discrete(home_goals.tolist(), game.actual_home_reg_ot_goals)
        away_goal_crps = _crps_discrete(away_goals.tolist(), game.actual_away_reg_ot_goals)
        team_goal_crps = (home_goal_crps + away_goal_crps) / 2.0
        goal_mae.extend((abs(float(np.mean(home_goals)) - game.actual_home_reg_ot_goals),
                         abs(float(np.mean(away_goals)) - game.actual_away_reg_ot_goals)))
        for samples, observed in ((home_goals.tolist(), game.actual_home_reg_ot_goals),
                                  (away_goals.tolist(), game.actual_away_reg_ot_goals)):
            for coverage, covered in _count_distribution_coverage(samples, observed).items():
                goal_coverage[coverage].append(covered)
        actual_final = (game.definition.official_home_score, game.definition.official_away_score)
        final_pairs = list(zip(home_final.tolist(), away_final.tolist()))
        energy = _energy_score(final_pairs, actual_final)
        p_home = float(np.mean(home_final > away_final))
        actual_home_win = int(actual_final[0] > actual_final[1])
        winner_loss = (p_home - actual_home_win) ** 2
        score_exact_mass = sum(pair == actual_final for pair in final_pairs) / sims
        goal_crps.append(team_goal_crps)
        winner_losses.append(winner_loss)
        score_energy.append(energy)
        win_mcse.append(math.sqrt(max(0.0, p_home * (1.0 - p_home) / sims)))
        rows.append({
            "game_id": game.definition.game_id,
            "season": game.definition.season,
            "date": game.definition.game_date,
            "predicted_home_reg_ot_goals_mean": float(np.mean(home_goals)),
            "predicted_away_reg_ot_goals_mean": float(np.mean(away_goals)),
            "team_goal_crps_reg_ot": team_goal_crps,
            "predicted_home_win_probability": p_home,
            "winner_brier": winner_loss,
            "final_score_exact_mass": score_exact_mass,
            "final_score_energy": energy,
            "home_win_probability_mcse": win_mcse[-1],
        })
    elapsed = walltime.perf_counter() - started
    return {
        "model_type": "v2_team_strength_independent_poisson_score_distribution",
        "sims_per_game": sims,
        "games": len(games),
        "reg_ot_team_goal_crps": statistics.fmean(goal_crps),
        "reg_ot_team_goal_mean_absolute_error": statistics.fmean(goal_mae),
        "team_goal_count_calibration": {
            coverage: {"n": len(values), "nominal_coverage": int(coverage) / 100.0,
                       "observed_coverage": statistics.fmean(values)}
            for coverage, values in goal_coverage.items()},
        "winner_brier": statistics.fmean(winner_losses),
        "final_score_energy_score": statistics.fmean(score_energy),
        "final_score_exact_log_score": -statistics.fmean(
            math.log(max(1.0 / sims, row["final_score_exact_mass"])) for row in rows),
        "mean_home_win_probability_mcse": statistics.fmean(win_mcse),
        "runtime_seconds": elapsed,
        "runtime_ms_per_game_simulation": 1000.0 * elapsed / max(1, len(games) * sims),
        "per_game_predictions": rows,
    }


def _summarize_comparison(candidate: Mapping[str, object], baseline: Mapping[str, object],
                          seed: int) -> dict[str, object]:
    candidate_rows = candidate["paired_game_rows"]
    baseline_rows = baseline["paired_game_rows"]
    if [row["game_id"] for row in candidate_rows] != [row["game_id"] for row in baseline_rows]:
        raise ValueError("PAIRED_EVALUATION_GAME_IDS_DIFFER")
    def paired(key: str, *, skip_null: bool = False) -> list[float]:
        values = []
        for cand, base in zip(candidate_rows, baseline_rows):
            if skip_null and cand[key] is None:
                continue
            values.append(float(base[key]) - float(cand[key]))
        return values
    deltas = {
        "team_sog_crps_baseline_minus_candidate": paired("team_sog_crps", skip_null=True),
        "team_goal_crps_baseline_minus_candidate": paired("team_goal_crps_reg_ot"),
        "winner_brier_baseline_minus_candidate": paired("winner_brier"),
        "final_score_energy_baseline_minus_candidate": paired("final_score_energy"),
    }
    intervals = {key: {"mean_delta": statistics.fmean(values), "paired_game_bootstrap_ci95": _bootstrap_mean(values, seed + i)}
                 for i, (key, values) in enumerate(deltas.items())}
    return {"positive_delta_favors_candidate": True,
            "paired_comparisons": {key: {**values, "n": len(deltas[key])}
                                   for key, values in intervals.items()}}


def _summarize_v2_comparison(candidate: Mapping[str, object], v2: Mapping[str, object],
                             seed: int) -> dict[str, object]:
    candidate_rows = candidate["paired_game_rows"]
    v2_rows = v2["per_game_predictions"]
    if [row["game_id"] for row in candidate_rows] != [row["game_id"] for row in v2_rows]:
        raise ValueError("V2_PAIRED_EVALUATION_GAME_IDS_DIFFER")
    metric_pairs = (
        ("reg_ot_team_goal_crps", "team_goal_crps_reg_ot"),
        ("winner_brier", "winner_brier"),
        ("final_score_energy_score", "final_score_energy"),
    )
    paired = {}
    for index, (name, row_key) in enumerate(metric_pairs):
        deltas = [float(v2_row[row_key]) - float(candidate_row[row_key])
                  for candidate_row, v2_row in zip(candidate_rows, v2_rows)]
        paired[name] = {"v2_minus_candidate_mean": statistics.fmean(deltas),
                        "paired_game_bootstrap_ci95": _bootstrap_mean(deltas, seed + index),
                        "n": len(deltas)}
    return {"positive_delta_favors_candidate": True,
            "paired_comparisons": paired}


def _metric_report(fold_name: str, event_metrics: Mapping[str, object],
                   candidate: Mapping[str, object], baseline: Mapping[str, object],
                   comparison: Mapping[str, object]) -> dict[str, object]:
    return {"fold": fold_name, "event_outcome_metrics": event_metrics,
            "conditional_simulation": {key: value for key, value in candidate.items()
                                       if key != "paired_game_rows"},
            "simple_rate_simulation": {key: value for key, value in baseline.items()
                                       if key != "paired_game_rows"},
            "paired_comparison": comparison,
            "per_game_predictions": candidate["paired_game_rows"]}


def _write_markdown_report(report: Mapping[str, object], training: Mapping[str, object],
                           model_artifact_sha256: str, *, validation_sims: int,
                           holdout_sims: int) -> str:
    val = report["development_2021"]
    hold = report["final_holdout_2022"]
    val_m = val["conditional_simulation"]
    val_b = val["simple_rate_simulation"]
    hold_m = hold["conditional_simulation"]
    hold_b = hold["simple_rate_simulation"]
    val_delta = val["paired_comparison"]["paired_comparisons"]
    hold_delta = hold["paired_comparison"]["paired_comparisons"]
    v2 = report["existing_v2_comparison"]
    v2_dev = v2["development_2021"]
    v2_hold = v2["final_holdout_2022"]
    v2_dev_delta = v2_dev["paired_vs_stochastic"]["paired_comparisons"]
    v2_hold_delta = v2_hold["paired_vs_stochastic"]["paired_comparisons"]
    return f"""# NHL V3 Phase 2A stochastic shot and scoring model

- **Base:** `2f2d1245d7459f17ed656111da5c6494d192e332`
- **Research branch:** `research/nhl-v3-phase2a-stochastic-2026-10-21`
- **Model artifact SHA-256:** `{model_artifact_sha256}`

## Reproduction

From the repository root, run `/root/legendarypicks/backend/venv/bin/python research/nhl/nhl-v3-phase2a-stochastic-2026-10-21/run_phase2a.py --validation-sims 128 --holdout-sims 256 --seed 20261021`. Input paths can be overridden with `--help`; input artifact hashes and the split are recorded in `TRAINING-DATA.json` and `EVALUATION.json`. Invariant suite: `/root/legendarypicks/backend/venv/bin/python -m unittest discover -s research/nhl/nhl-v3-phase2a-stochastic-2026-10-21 -p 'test_*.py' -v`.

## Adoption decision

**NOT ADOPTED for promotion over the simple historical-rate baseline.** The prototype is a coherent,
reproducible event generator and is useful for continued simulator development. Adoption requires
paired improvement on the untouched 2022 holdout with uncertainty that excludes zero, plus adequate
calibration. The holdout has only {hold_m['games']} games, so it cannot establish broad seasonal
generalization. No market, ROI, or production claim is made.

## Cohort and training

- Frozen frame: 4,876 regular-season games, start seasons 2018–2022 (2022 partial through November 27).
- Forward split: 2018–2020 fit; 2021 development; 2022 partial final holdout, untouched during design and fitting.
- Official team score target: 4,876 games accepted by Phase 1. Scores remain eligible independently of shift-chart quality.
- Official team SOG: 4,814 accepted game targets; 62 quarantined game targets are excluded from SOG target metrics.
- Historical PBP: 1,510,104 source-ordered events. Raw hashes and the full Phase 1 replay were rechecked before fitting.
- The fitter reads no shift rows. Goalie identity and player-on-ice fields are not predictors.
- SOG and score histories for pregame team attack/defense use only accepted official team SOG from earlier calendar dates; same-date games do not update one another.
- Prediction requests contain the Phase 1 `PregameSnapshot` only. The date-only frame has no puck-drop timestamp, so historical snapshots use a documented noon UTC boundary and prior-date features; a production caller must supply the published scheduled start.

Training details: {json.dumps(training, sort_keys=True)}

## Components

1. Shot attempt hazard: ridge Poisson log-linear model with period, observed/generation strength, score state, time remaining in the period and game, home/away, and rolling team shot-for/shot-against quality.
2. Attempt outcome: separate ridge logistic models for on-target probability, blocked-vs-missed probability, and goal-vs-save probability. The goal model includes accepted shot-location distance/angle bands and accepted shot type.
3. Shot locations/types: deterministic reservoir sample of accepted historical event locations, sampled by generated strength state. Invalid or quarantined coordinates are not used.
4. Goaltending: population response only. No actual starter or goalie identity enters the fit or evaluation.
5. Penalties: estimated pooled event rate; generated as single two-minute minors, at most one active minor, with release on a power-play goal. No double minors, majors, coincidental penalties, delayed calls, team discipline, or OT penalties.
6. Regulation: three 20-minute periods. A tied game receives five-minute sudden-death 3v3 overtime. A remaining tie gets alternating best-of-three shootout attempts and sudden-death pairs. Shootout events are separate from regular SOG; only the winner's final-score representation receives the NHL one-goal convention. Shootout `period_clock_seconds` stores the attempt ordinal and carries `clock_semantics=attempt_order`, since a shootout has no game clock.

Each ordinary shot emits `SHOT_ATTEMPT` plus one outcome (`SHOT_BLOCKED`, `SHOT_MISSED`, `SHOT_SAVED`, or `GOAL`). SOG is derived from saves/goals, and all scores are recomputed from goal events. Invalid event states raise `SimulationInvariantError`.

## Forward evaluation

Simulation counts per game: development {validation_sims}; final holdout {holdout_sims}. All values below are per-game means; paired differences use the same matchup set. Positive baseline-minus-model differences favor the fitted model.

| Metric | 2021 model | 2021 simple average | Paired delta (95% game bootstrap) | 2022 model | 2022 simple average | Paired delta (95% game bootstrap) |
|---|---:|---:|---:|---:|---:|---:|
| Team SOG CRPS | {val_m['team_sog_crps']:.3f} | {val_b['team_sog_crps']:.3f} | {val_delta['team_sog_crps_baseline_minus_candidate']['mean_delta']:.3f} ({val_delta['team_sog_crps_baseline_minus_candidate']['paired_game_bootstrap_ci95'][0]:.3f}, {val_delta['team_sog_crps_baseline_minus_candidate']['paired_game_bootstrap_ci95'][1]:.3f}) | {hold_m['team_sog_crps']:.3f} | {hold_b['team_sog_crps']:.3f} | {hold_delta['team_sog_crps_baseline_minus_candidate']['mean_delta']:.3f} ({hold_delta['team_sog_crps_baseline_minus_candidate']['paired_game_bootstrap_ci95'][0]:.3f}, {hold_delta['team_sog_crps_baseline_minus_candidate']['paired_game_bootstrap_ci95'][1]:.3f}) |
| Team reg+OT goal CRPS | {val_m['reg_ot_team_goal_crps']:.3f} | {val_b['reg_ot_team_goal_crps']:.3f} | {val_delta['team_goal_crps_baseline_minus_candidate']['mean_delta']:.3f} ({val_delta['team_goal_crps_baseline_minus_candidate']['paired_game_bootstrap_ci95'][0]:.3f}, {val_delta['team_goal_crps_baseline_minus_candidate']['paired_game_bootstrap_ci95'][1]:.3f}) | {hold_m['reg_ot_team_goal_crps']:.3f} | {hold_b['reg_ot_team_goal_crps']:.3f} | {hold_delta['team_goal_crps_baseline_minus_candidate']['mean_delta']:.3f} ({hold_delta['team_goal_crps_baseline_minus_candidate']['paired_game_bootstrap_ci95'][0]:.3f}, {hold_delta['team_goal_crps_baseline_minus_candidate']['paired_game_bootstrap_ci95'][1]:.3f}) |
| Home winner Brier | {val_m['winner_brier']:.4f} | {val_b['winner_brier']:.4f} | {val_delta['winner_brier_baseline_minus_candidate']['mean_delta']:.4f} ({val_delta['winner_brier_baseline_minus_candidate']['paired_game_bootstrap_ci95'][0]:.4f}, {val_delta['winner_brier_baseline_minus_candidate']['paired_game_bootstrap_ci95'][1]:.4f}) | {hold_m['winner_brier']:.4f} | {hold_b['winner_brier']:.4f} | {hold_delta['winner_brier_baseline_minus_candidate']['mean_delta']:.4f} ({hold_delta['winner_brier_baseline_minus_candidate']['paired_game_bootstrap_ci95'][0]:.4f}, {hold_delta['winner_brier_baseline_minus_candidate']['paired_game_bootstrap_ci95'][1]:.4f}) |
| Final score energy score | {val_m['final_score_energy_score']:.3f} | {val_b['final_score_energy_score']:.3f} | {val_delta['final_score_energy_baseline_minus_candidate']['mean_delta']:.3f} ({val_delta['final_score_energy_baseline_minus_candidate']['paired_game_bootstrap_ci95'][0]:.3f}, {val_delta['final_score_energy_baseline_minus_candidate']['paired_game_bootstrap_ci95'][1]:.3f}) | {hold_m['final_score_energy_score']:.3f} | {hold_b['final_score_energy_score']:.3f} | {hold_delta['final_score_energy_baseline_minus_candidate']['mean_delta']:.3f} ({hold_delta['final_score_energy_baseline_minus_candidate']['paired_game_bootstrap_ci95'][0]:.3f}, {hold_delta['final_score_energy_baseline_minus_candidate']['paired_game_bootstrap_ci95'][1]:.3f}) |

2021 game count: {val_m['games']} ({val_m['eligible_team_sog_games']} SOG-eligible); 2022 final holdout: {hold_m['games']} ({hold_m['eligible_team_sog_games']} SOG-eligible). Event-outcome log loss/Brier, winner reliability bins, period SOG/goal MAE, exact final-score mass, Monte Carlo uncertainty, runtime, and per-game rows are in `EVALUATION.json`. Event-outcome diagnostics condition on each historical shot's observed pre-shot period, strength, score, and clock state. Full matchup simulations generate those states from their own event sequence.

Accounting failures: development {val_m['simulation_accounting_failures']}/{val_m['validated_simulations']}; holdout {hold_m['simulation_accounting_failures']}/{hold_m['validated_simulations']}. Mean home-SOG Monte Carlo SE: {hold_m['mean_home_sog_mcse']:.3f}; mean home-win probability SE: {hold_m['mean_home_win_probability_mcse']:.4f}. Runtime: development {val_m['runtime_seconds']:.1f}s, holdout {hold_m['runtime_seconds']:.1f}s.

## Existing model comparison

The frozen v2 artifact was **not** scored directly because its fit includes 2022, which would leak the final holdout. Instead, the published v2 `TeamStrength` method was re-fit on the same 2018–2020 development training window and 2018–2021 final training window. The source code, canonical game file, and frozen artifact were hash checked. The canonical file joined all {v2_hold['metrics']['games']} final holdout games by game ID; season, date, home/away labels, and official scores were asserted, then team IDs were checked against those labels. The goal target was the replayed accepted regular-plus-overtime score. The existing independent-Poisson score distribution and shootout tiebreak convention were retained, with the home shootout rate estimated from each training window. This score-only model has no team-SOG prediction, so SOG comparisons are not applicable.

The canonical xG columns are passed through only to preserve the v2 reference constructor's auxiliary xG fit. Its `mus()` prediction method uses the goal-fitted team ratings; evaluation-game xG and goals are not predictor inputs.

| Metric | 2021 v2 refit | 2021 stochastic | v2 minus stochastic (95% paired game bootstrap) | 2022 v2 refit | 2022 stochastic | v2 minus stochastic (95% paired game bootstrap) |
|---|---:|---:|---:|---:|---:|---:|
| Reg+OT team-goal CRPS | {v2_dev['metrics']['reg_ot_team_goal_crps']:.3f} | {val_m['reg_ot_team_goal_crps']:.3f} | {v2_dev_delta['reg_ot_team_goal_crps']['v2_minus_candidate_mean']:.3f} ({v2_dev_delta['reg_ot_team_goal_crps']['paired_game_bootstrap_ci95'][0]:.3f}, {v2_dev_delta['reg_ot_team_goal_crps']['paired_game_bootstrap_ci95'][1]:.3f}) | {v2_hold['metrics']['reg_ot_team_goal_crps']:.3f} | {hold_m['reg_ot_team_goal_crps']:.3f} | {v2_hold_delta['reg_ot_team_goal_crps']['v2_minus_candidate_mean']:.3f} ({v2_hold_delta['reg_ot_team_goal_crps']['paired_game_bootstrap_ci95'][0]:.3f}, {v2_hold_delta['reg_ot_team_goal_crps']['paired_game_bootstrap_ci95'][1]:.3f}) |
| Winner Brier | {v2_dev['metrics']['winner_brier']:.4f} | {val_m['winner_brier']:.4f} | {v2_dev_delta['winner_brier']['v2_minus_candidate_mean']:.4f} ({v2_dev_delta['winner_brier']['paired_game_bootstrap_ci95'][0]:.4f}, {v2_dev_delta['winner_brier']['paired_game_bootstrap_ci95'][1]:.4f}) | {v2_hold['metrics']['winner_brier']:.4f} | {hold_m['winner_brier']:.4f} | {v2_hold_delta['winner_brier']['v2_minus_candidate_mean']:.4f} ({v2_hold_delta['winner_brier']['paired_game_bootstrap_ci95'][0]:.4f}, {v2_hold_delta['winner_brier']['paired_game_bootstrap_ci95'][1]:.4f}) |
| Final-score energy score | {v2_dev['metrics']['final_score_energy_score']:.3f} | {val_m['final_score_energy_score']:.3f} | {v2_dev_delta['final_score_energy_score']['v2_minus_candidate_mean']:.3f} ({v2_dev_delta['final_score_energy_score']['paired_game_bootstrap_ci95'][0]:.3f}, {v2_dev_delta['final_score_energy_score']['paired_game_bootstrap_ci95'][1]:.3f}) | {v2_hold['metrics']['final_score_energy_score']:.3f} | {hold_m['final_score_energy_score']:.3f} | {v2_hold_delta['final_score_energy_score']['v2_minus_candidate_mean']:.3f} ({v2_hold_delta['final_score_energy_score']['paired_game_bootstrap_ci95'][0]:.3f}, {v2_hold_delta['final_score_energy_score']['paired_game_bootstrap_ci95'][1]:.3f}) |

Positive paired deltas favor the stochastic simulator. V2 fit rows, Monte Carlo errors, per-game scores, and exact source pins are retained in `EVALUATION.json` and `TRAINING-DATA.json`.

## Limitations and next interfaces

This is a team-level event model, not a full NHL process model. It does not assign players, select lineups, model goalie identity, model line changes, infer possession, model rebounds, or simulate empty-net pulls. Shot opportunity times are exponential waiting times, not observed possession/shift sequences. Historical event coordinates and official targets are not equivalent to a tracking system. The limited minor-only penalty generator omits important special-teams states.

Next extension points are: (1) shooter opportunity allocation from current generated shot/team states; (2) player SOG distributions conditional on generated team opportunities and pregame player snapshots; (3) goalie-specific response, gated on verifiable pregame goalie identity; (4) scorer/assist allocation after a generated goal; (5) fuller penalty/service/manpower transitions; (6) lineup and shift deployment. Each attaches through generated event attributes and the existing pregame snapshot boundary.
"""


def _write_training_data_spec(training: Mapping[str, object]) -> str:
    dev = training["development_fit_counts"]
    final = training["final_fit_counts"]
    return f"""# Phase 2A training data specification

## Population and dispositions

- Frozen evaluation frame: 4,876 regular-season games, start seasons 2018–2022 (2022 is partial).
- The Phase 1 official team-score component is accepted for all 4,876 games. Each included game is replayed and reconciled to its official final score before its events enter fitting or evaluation.
- Official team SOG targets are accepted for 4,814 games. The remaining 62 games are quarantined only for SOG use; they remain in accepted score training, scoring reconciliation, and goal distribution evaluation.
- PBP events come from the frozen Phase 1 normalized event ledger and retain publisher source order. Phase 1 raw body and input pin checks were rerun for this work; see `REPLAY-VALIDATION.md`.
- The fitter reads zero shift rows. Shift chart or player identity quality cannot remove an otherwise accepted team score.
- Event outcome fitting requires accepted event and team-count dispositions plus ordinary-shot eligibility. Spatial coordinates and shot type enter only when their own component disposition is accepted.
- Attempt classes are blocked, missed, saved, and goal. Every generated attempt has one outcome; saved shots and goals contribute SOG.

## Chronology and folds

- Development: fit on 2018–2020, evaluate on 2021.
- Final: fit on 2018–2021, evaluate on the partial 2022 season. The 2022 outcomes do not affect fitting, feature categories, hyperparameters, or the adoption rule.
- Team attack and defense snapshots use the prior ten accepted official team-SOG games for each stable team ID. “Attack” is SOG for; “defense” is opponent SOG allowed. Only games on earlier calendar dates update a snapshot. The source frame lacks exact puck-drop timestamps, so same-date games do not update one another.
- Historical snapshots use an explicit noon UTC synthetic scheduled start and make prior-date features available by 23:59:59 UTC on the previous date. This conservative boundary is not a substitute for scheduled-start timestamps in a prospective production caller.
- Period, strength, score-state, and time-remaining values for historical event rows are reconstructed from earlier accepted PBP state in source order. Observed strength comes from event situation codes, never shift charts. Prospective simulation uses only its generated strength transitions.
- The publisher's within-period clock can move backward in source order. Events are never sorted or removed for this; rate-exposure intervals and time features use a per-period elapsed-time high-water mark, so already traversed clock intervals are not counted twice. The number and total seconds of these backward-clock rows are recorded in the fit counters.
- Rate exposure is admitted only for games whose accepted event chronology and clocks pass the timeline gate. Goal reconciliation and accepted shot outcomes remain component-scoped and are not filtered on shift quality.

## Feature and target provenance

| Feature/target | Construction | Source and gate |
|---|---|---|
| Period | Regulation P1/P2/P3 and OT | Accepted event period number |
| Strength | Even, advantage, disadvantage, empty net, unknown | Parsed observed situation code in training; generated limited penalty state in simulation |
| Score state | Leading, tied, trailing for shooting team | Accepted prior goal sequence, including accepted goals when another component is quarantined |
| Time remaining in period | Early (>15m), middle (>5m to 15m), late (≤5m) | Accepted source clock mapped through its monotone high-water envelope; rate exposures split at bucket boundaries |
| Time remaining in game | Regulation game time: early, middle, late; overtime | Period number plus monotone within-period clock; distinct fitted dimension |
| Home/away | Home or away shooting side | Stable game venue identity |
| Team attack/defense | Prior-10 official SOG for/allowed per game, categorized against fit-only overall reference | Accepted official team SOG validation artifact, stable team IDs, prior calendar dates only |
| Attempt outcomes | Blocked, missed, saved, goal | Accepted PBP event and team-count components; four classes reconcile to each accepted shot attempt |
| Goal quality | Distance/angle bins and shot type | Accepted spatial and shot-type dispositions only; unknown category otherwise |
| Whole-game goals | Replayed ordinary goal events and final-score reconciliation | Official accepted team score; no shift or player identity condition |
| Whole-game SOG | Sum of generated saved/goal outcomes | Official team SOG target only on the 4,814 accepted games |
| Existing v2 score comparator | Refit goal targets, venue, team attack/defense, shootout rate | Hash-pinned v2 canonical source joined by game ID and reconciled to Phase 1; v2 method source hash/commit in `TRAINING-DATA.json` |

## Fit counts

Development fit counts: `{json.dumps(dev, sort_keys=True)}`

Final fit counts: `{json.dumps(final, sort_keys=True)}`

All source artifact pins and the v2 source, frozen-model, and canonical-data hashes are retained in `TRAINING-DATA.json`. The fitted final parameter artifact is `FITTED-MODEL.json`; evaluation scores and per-game predictions are in `EVALUATION.json`.

## Player-prop extension points

Generated shot events carry attempt identity, team owner, period, clock, strength, score state, location, and shot type. Shooter allocation and player SOG distributions can attach to the attempt/outcome pair; goalie response can attach to saved/goal outcomes once a verifiable pregame goalie identity source exists; player goals/assists can attach after goal events; richer penalty transitions can extend manpower events; lineup and shift deployment can attach via generated player-entry and on-ice attributes. None of those player or goalie-identity components are fitted in Phase 2A. Shootout events remain separate from ordinary shot/SOG accounting; their clock field is tagged as attempt order, and the final-score one-goal shootout convention is recorded at `GAME_END`.
"""


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--official", type=Path, default=DEFAULT_OFFICIAL_DIR)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABEL_DIR / "research_label_quality.csv")
    parser.add_argument("--label-summary", type=Path)
    parser.add_argument("--v2-canonical", type=Path, default=DEFAULT_V2_CANONICAL)
    parser.add_argument("--v2-frozen-model", type=Path, default=DEFAULT_V2_FROZEN_MODEL)
    parser.add_argument("--out-dir", type=Path, default=HERE)
    parser.add_argument("--validation-sims", type=int, default=128)
    parser.add_argument("--holdout-sims", type=int, default=256)
    parser.add_argument("--seed", type=int, default=20261021)
    args = parser.parse_args()
    if args.validation_sims <= 0 or args.holdout_sims <= 0:
        raise SystemExit("simulation counts must be positive")
    if args.out_dir.resolve() in {args.artifacts.resolve(), args.official.resolve(), args.labels.resolve().parent}:
        raise SystemExit("output directory overlaps a pinned input artifact")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    bundle = load_bundle(artifact_dir=args.artifacts, official_dir=args.official,
                         label_path=args.labels, label_summary_path=args.label_summary)
    v2_canonical, v2_source_metadata = _load_v2_canonical(args.v2_canonical,
                                                           args.v2_frozen_model)
    snapshots = _team_history_snapshots(bundle)
    start = walltime.perf_counter()
    dev = _build_fold(bundle, snapshots, v2_canonical, FIT_SEASONS, DEVELOPMENT_SEASONS)
    if dev.parameters is None:
        raise RuntimeError("DEVELOPMENT_MODEL_NOT_FIT")
    dev_conditional = _evaluate_simulations(dev.heldout_games, dev.parameters,
                                            args.validation_sims, seed=args.seed, conditional=True)
    dev_simple = _evaluate_simulations(dev.heldout_games, dev.parameters,
                                       args.validation_sims, seed=args.seed, conditional=False)
    dev_comparison = _summarize_comparison(dev_conditional, dev_simple, args.seed + 17)
    dev_report = _metric_report("development_2021", _event_model_metrics(dev.parameters, dev),
                                dev_conditional, dev_simple, dev_comparison)
    dev_v2 = _evaluate_v2_score_distribution(
        dev.heldout_games, dev.v2_model, v2_canonical, dev.v2_shootout_home_win_rate,
        args.validation_sims, seed=args.seed + 2_000_000)
    dev_v2_comparison = _summarize_v2_comparison(dev_conditional, dev_v2, args.seed + 41)

    # 2022 labels are not used until the model and split decision above are fixed.
    final = _build_fold(bundle, snapshots, v2_canonical,
                        (*FIT_SEASONS, 2021), FINAL_HOLDOUT_SEASONS)
    if final.parameters is None:
        raise RuntimeError("FINAL_MODEL_NOT_FIT")
    hold_conditional = _evaluate_simulations(final.heldout_games, final.parameters,
                                             args.holdout_sims, seed=args.seed + 1_000_000,
                                             conditional=True)
    hold_simple = _evaluate_simulations(final.heldout_games, final.parameters,
                                        args.holdout_sims, seed=args.seed + 1_000_000,
                                        conditional=False)
    hold_comparison = _summarize_comparison(hold_conditional, hold_simple, args.seed + 29)
    hold_report = _metric_report("final_holdout_2022", _event_model_metrics(final.parameters, final),
                                 hold_conditional, hold_simple, hold_comparison)
    hold_v2 = _evaluate_v2_score_distribution(
        final.heldout_games, final.v2_model, v2_canonical, final.v2_shootout_home_win_rate,
        args.holdout_sims, seed=args.seed + 3_000_000)
    hold_v2_comparison = _summarize_v2_comparison(hold_conditional, hold_v2, args.seed + 53)

    model_bytes = (json.dumps(final.parameters.to_json(), sort_keys=True, separators=(",", ":"),
                              ensure_ascii=False) + "\n").encode("utf-8")
    model_sha = hashlib.sha256(model_bytes).hexdigest()
    (args.out_dir / "FITTED-MODEL.json").write_bytes(model_bytes)
    training = {
        "environment": {"python_version": sys.version.split()[0],
                        "numpy_version": np.__version__},
        "fit_seasons_development": list(FIT_SEASONS),
        "development_seasons": list(DEVELOPMENT_SEASONS),
        "fit_seasons_final": [*FIT_SEASONS, 2021],
        "final_holdout_seasons": list(FINAL_HOLDOUT_SEASONS),
        "development_fit_counts": dev.train_counts,
        "final_fit_counts": final.train_counts,
        "official_score_targets_in_development_fit": dev.train_counts.get("official_score_targets_from_all_fit_games", 0),
        "source_pins": bundle.pins,
        "feature_history_window_games": 10,
        "same_date_feature_updates": "excluded; exact game start timestamps are absent from the pinned frame",
        "shift_rows_read_by_fitter": 0,
        "v2_reference_source": v2_source_metadata,
        "development_v2_fit": {"fit_games": dev.v2_training_games,
                                "training_shootout_home_win_rate": dev.v2_shootout_home_win_rate},
        "final_v2_fit": {"fit_games": final.v2_training_games,
                         "training_shootout_home_win_rate": final.v2_shootout_home_win_rate},
    }
    report_data = {
        "base_sha": "2f2d1245d7459f17ed656111da5c6494d192e332",
        "branch": "research/nhl-v3-phase2a-stochastic-2026-10-21",
        "model_sha256": model_sha,
        "random_seed": args.seed,
        "simulation_counts": {"development": args.validation_sims, "final_holdout": args.holdout_sims},
        "development_2021": dev_report,
        "final_holdout_2022": hold_report,
        "total_fit_and_evaluation_runtime_seconds": walltime.perf_counter() - start,
        "existing_v2_comparison": {
            "status": "SAME_METHOD_REFIT_ON_MATCHING_FORWARD_TRAINING_WINDOWS",
            "frozen_all_season_v2_scored_directly": False,
            "reason_frozen_model_not_scored": "Frozen model training includes the 2022 holdout; reusing it would leak holdout outcomes.",
            "source": v2_source_metadata,
            "development_2021": {"fit_games": dev.v2_training_games,
                                  "training_shootout_home_win_rate": dev.v2_shootout_home_win_rate,
                                  "metrics": dev_v2,
                                  "paired_vs_stochastic": dev_v2_comparison},
            "final_holdout_2022": {"fit_games": final.v2_training_games,
                                   "training_shootout_home_win_rate": final.v2_shootout_home_win_rate,
                                   "metrics": hold_v2,
                                   "paired_vs_stochastic": hold_v2_comparison},
        },
    }
    (args.out_dir / "TRAINING-DATA.json").write_text(json.dumps(training, indent=2, sort_keys=True) + "\n")
    (args.out_dir / "TRAINING-DATA.md").write_text(_write_training_data_spec(training))
    (args.out_dir / "EVALUATION.json").write_text(json.dumps(report_data, indent=2, sort_keys=True) + "\n")
    (args.out_dir / "REPORT.md").write_text(_write_markdown_report(
        report_data, training, model_sha, validation_sims=args.validation_sims,
        holdout_sims=args.holdout_sims))
    print(json.dumps({"model_sha256": model_sha,
                      "development_games": len(dev.heldout_games),
                      "final_holdout_games": len(final.heldout_games),
                      "fit_runtime_seconds": report_data["total_fit_and_evaluation_runtime_seconds"],
                      "output_dir": str(args.out_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    # Reservoir state is per-process and deterministic; reset for repeatable runs.
    location_reservoirs.clear()
    location_seen.clear()
    raise SystemExit(_main())
