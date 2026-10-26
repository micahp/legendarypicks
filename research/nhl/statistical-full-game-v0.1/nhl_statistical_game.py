#!/usr/bin/env python3
"""Research-only NHL full-game event generator using verified PBP period blocks.

This is an empirical block bootstrap, not a team-strength forecast or physical simulator.
The source cache remains outside the repository. Only a small generated example and
aggregate development diagnostics are intended to be checked in.
"""

from __future__ import annotations

import argparse
import bisect
import collections
import csv
import gzip
import hashlib
import json
import math
import random
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


MODEL_VERSION = "empirical-period-bootstrap-v0.1"
EXPECTED_MANIFEST_SHA256 = "d87e40a3387f014429377cc8dfb010cec8ca2d0e4d03d0b5bdbfacd8de9ca990"
DEFAULT_DATA_ROOT = Path("/root/lp-data/nhl-fullframe-event-audit-2026-10-21")
EXPECTED_BOXSCORE_MANIFEST_SHA256 = "0ba44bcebefecb0a8eefbea995e8f5370583600eec77d0be12be574f308d71a2"
DEFAULT_BOXSCORE_ROOT = Path("/root/lp-data/nhl-official-outcome-backfill-2026-10-20")
TRAIN_SEASONS = (2019, 2020)
DEVELOPMENT_SEASONS = (2021,)
EXCLUDED_SEASONS = (2022,)
SOURCE_QUALITY_QUARANTINE_SEASONS = (2018,)
REGULATION_PERIODS = (1, 2, 3)
REGULATION_SECONDS = 20 * 60
OVERTIME_SECONDS = 5 * 60
BOUNDARY_EVENTS = {"period-start", "period-end", "game-end", "shootout-complete"}
SHOOTOUT_ATTEMPT_TYPES = {"goal", "shot-on-goal", "missed-shot", "failed-shot-attempt"}
EVENT_CLOCK = re.compile(r"^(\d{1,2}):(\d{2})$")
TEAM_LABEL = re.compile(r"^[A-Za-z0-9_-]{1,24}$")


@dataclass
class PeriodSummary:
    number: int
    period_type: str
    event_counts: dict[str, int]
    goals: dict[str, int]
    sog_events: dict[str, int]
    interior_events: int
    shootout_attempts: int = 0
    ot_goal_event_index: int | None = None
    ot_goal_prefix_counts: dict[str, int] = field(default_factory=dict)
    ot_goal_prefix_goals: dict[str, int] = field(default_factory=dict)
    ot_goal_prefix_sog: dict[str, int] = field(default_factory=dict)
    ot_goal_prefix_events: int = 0


@dataclass
class GameSummary:
    game_id: str
    start_season: int
    compressed_sha256: str
    boxscore_compressed_sha256: str
    boxscore_source: str
    home_score: int
    away_score: int
    home_sog: int
    away_sog: int
    regulation_ot_goals: dict[str, int]
    source_last_period_type: str
    shootout_winner: str | None
    periods: dict[tuple[str, int], PeriodSummary]
    quality: dict[str, bool]
    reasons: list[str]

    @property
    def eligible(self) -> bool:
        return all(self.quality.values())

    @property
    def final_score(self) -> dict[str, int]:
        return {"home": self.home_score, "away": self.away_score}

    @property
    def reg_ot_score(self) -> dict[str, int]:
        return dict(self.regulation_ot_goals)


@dataclass
class Corpus:
    data_root: Path
    manifest_sha256: str
    boxscore_manifest_sha256: str
    manifest_games: int
    boxscore_manifest_games: int
    boxscore_source_counts: dict[str, int]
    games: dict[str, GameSummary]
    listed_by_season: dict[int, int]
    eligible_by_season: dict[int, int]
    quarantined_by_reason: dict[int, dict[str, int]]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_clock(value: Any) -> int:
    if not isinstance(value, str):
        raise ValueError(f"clock is not a string: {value!r}")
    match = EVENT_CLOCK.fullmatch(value)
    if not match:
        raise ValueError(f"clock has unsupported format: {value!r}")
    minutes, seconds = int(match.group(1)), int(match.group(2))
    if seconds >= 60:
        raise ValueError(f"clock seconds out of range: {value!r}")
    return minutes * 60 + seconds


def _period_limit(period_type: str) -> int | None:
    if period_type == "REG":
        return REGULATION_SECONDS
    if period_type == "OT":
        return OVERTIME_SECONDS
    if period_type == "SO":
        return 0
    return None


def _period_detail_counts(
    events: list[dict[str, Any]],
    period_type: str,
    side_by_id: dict[str, str],
) -> tuple[collections.Counter[str], collections.Counter[str], collections.Counter[str], int]:
    event_counts: collections.Counter[str] = collections.Counter()
    goals: collections.Counter[str] = collections.Counter()
    sog: collections.Counter[str] = collections.Counter()
    attempts = 0
    for event in events:
        event_type = event.get("typeDescKey")
        if event_type in BOUNDARY_EVENTS:
            continue
        details = event.get("details") or {}
        side = side_by_id.get(str(details.get("eventOwnerTeamId")))
        if period_type == "SO":
            if event_type in SHOOTOUT_ATTEMPT_TYPES:
                attempts += 1
            continue
        if not isinstance(event_type, str) or not event_type:
            continue
        event_counts[event_type] += 1
        if event_type == "goal":
            if side:
                goals[side] += 1
                sog[side] += 1
        elif event_type == "shot-on-goal" and side:
            sog[side] += 1
    return event_counts, goals, sog, attempts


def _validate_period_clocks(
    period_key: tuple[str, int], events: list[dict[str, Any]]
) -> bool:
    period_type, _ = period_key
    limit = _period_limit(period_type)
    if limit is None:
        return False
    previous_elapsed = -1
    previous_remaining: int | None = None
    for event in events:
        try:
            elapsed = parse_clock(event.get("timeInPeriod"))
            remaining = parse_clock(event.get("timeRemaining"))
        except ValueError:
            return False
        if elapsed < 0 or remaining < 0 or elapsed > limit or remaining > limit:
            return False
        if period_type != "SO" and elapsed + remaining != limit:
            return False
        if period_type == "SO" and (elapsed != 0 or remaining != 0):
            return False
        if elapsed < previous_elapsed:
            return False
        if previous_remaining is not None and remaining > previous_remaining:
            return False
        previous_elapsed = elapsed
        previous_remaining = remaining
    return True


def _period_has_required_markers(
    period_key: tuple[str, int], events: list[dict[str, Any]]
) -> bool:
    period_type, _ = period_key
    types = [event.get("typeDescKey") for event in events]
    if "period-start" not in types:
        return False
    if period_type in {"REG", "SO"}:
        return "period-end" in types
    if period_type == "OT":
        return "period-end" in types or "goal" in types
    return False


def _make_period_summary(
    number: int,
    period_type: str,
    events: list[dict[str, Any]],
    side_by_id: dict[str, str],
) -> PeriodSummary:
    counts, goals, sog, shootout_attempts = _period_detail_counts(
        events, period_type, side_by_id
    )
    interior = [event for event in events if event.get("typeDescKey") not in BOUNDARY_EVENTS]
    summary = PeriodSummary(
        number=number,
        period_type=period_type,
        event_counts=dict(counts),
        goals={"home": int(goals.get("home", 0)), "away": int(goals.get("away", 0))},
        sog_events={"home": int(sog.get("home", 0)), "away": int(sog.get("away", 0))},
        interior_events=len(interior) if period_type != "SO" else shootout_attempts,
        shootout_attempts=shootout_attempts,
    )
    if period_type == "OT":
        first_goal_index = next(
            (index for index, event in enumerate(interior) if event.get("typeDescKey") == "goal"),
            None,
        )
        if first_goal_index is not None:
            prefix_counts, prefix_goals, prefix_sog, _ = _period_detail_counts(
                interior[: first_goal_index + 1], period_type, side_by_id
            )
            summary.ot_goal_event_index = first_goal_index
            summary.ot_goal_prefix_counts = dict(prefix_counts)
            summary.ot_goal_prefix_goals = {
                "home": int(prefix_goals.get("home", 0)),
                "away": int(prefix_goals.get("away", 0)),
            }
            summary.ot_goal_prefix_sog = {
                "home": int(prefix_sog.get("home", 0)),
                "away": int(prefix_sog.get("away", 0)),
            }
            summary.ot_goal_prefix_events = first_goal_index + 1
    return summary


def _inspect_game(
    row: dict[str, str],
    raw_dir: Path,
    boxscore_row: dict[str, Any],
    boxscore_raw_dir: Path,
) -> GameSummary:
    game_id = row["game_id"]
    start_season = int(game_id[:4])
    path = raw_dir / f"{game_id}.json.gz"
    expected_size = int(row["bytes_gz"])
    if path.stat().st_size != expected_size:
        raise ValueError(f"{game_id}: compressed body size differs from manifest")
    compressed_sha = sha256_file(path)
    if compressed_sha != row["sha256_gz"]:
        raise ValueError(f"{game_id}: compressed body SHA differs from manifest")
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        document = json.load(handle)

    boxscore_path = boxscore_raw_dir / f"{game_id}.json.gz"
    expected_boxscore_size = int(boxscore_row["compressed_bytes"])
    if boxscore_path.stat().st_size != expected_boxscore_size:
        raise ValueError(f"{game_id}: boxscore compressed body size differs from manifest")
    boxscore_compressed_sha = sha256_file(boxscore_path)
    if boxscore_compressed_sha != boxscore_row["compressed_sha256"]:
        raise ValueError(f"{game_id}: boxscore compressed body SHA differs from manifest")
    with gzip.open(boxscore_path, "rt", encoding="utf-8") as handle:
        boxscore = json.load(handle)

    reasons: list[str] = []
    quality = {
        "game_type": str(document.get("gameType")) == "2",
        "game_id": str(document.get("id")) == game_id,
        "teams": False,
        "owners": True,
        "clocks": True,
        "periods": True,
        "boxscore": False,
        "score_sources_agree": False,
        "sog_sources_agree": False,
        "score": False,
        "sog": False,
        "complete_final": False,
    }
    if not quality["game_type"]:
        reasons.append("not_regular_season")
    if not quality["game_id"]:
        reasons.append("game_id_mismatch")

    home = document.get("homeTeam") or {}
    away = document.get("awayTeam") or {}
    box_home = boxscore.get("homeTeam") or {}
    box_away = boxscore.get("awayTeam") or {}
    home_id, away_id = home.get("id"), away.get("id")
    box_home_id, box_away_id = box_home.get("id"), box_away.get("id")
    quality["boxscore"] = (
        str(boxscore.get("id")) == game_id
        and str(boxscore.get("gameType")) == "2"
        and boxscore_row.get("status") == "OK"
        and boxscore_row.get("source") in {"official_gamecenter", "prior_official_audit_cache"}
    )
    if not quality["boxscore"]:
        reasons.append("independent_boxscore_identity_or_provenance_invalid")
    quality["teams"] = (
        home_id is not None
        and away_id is not None
        and str(home_id) != str(away_id)
        and str(home_id) == str(box_home_id)
        and str(away_id) == str(box_away_id)
    )
    if not quality["teams"]:
        reasons.append("team_identity_missing_conflicting_or_boxscore_disagreement")
    side_by_id = {str(home_id): "home", str(away_id): "away"}

    source_events = document.get("plays")
    if not isinstance(source_events, list) or not source_events:
        raise ValueError(f"{game_id}: missing PBP play list")
    ordered_events = sorted(
        enumerate(source_events),
        key=lambda pair: (int(pair[1].get("sortOrder", pair[0])), pair[0]),
    )
    by_period: dict[tuple[str, int], list[dict[str, Any]]] = collections.defaultdict(list)
    goals = collections.Counter(home=0, away=0)
    sog = collections.Counter(home=0, away=0)
    owner_valid = True
    for _, event in ordered_events:
        descriptor = event.get("periodDescriptor") or {}
        period_type = descriptor.get("periodType")
        number = descriptor.get("number")
        if not isinstance(period_type, str) or not isinstance(number, int):
            quality["clocks"] = False
            continue
        by_period[(period_type, number)].append(event)
        details = event.get("details") or {}
        owner = details.get("eventOwnerTeamId")
        if owner is not None and str(owner) not in side_by_id:
            owner_valid = False
        side = side_by_id.get(str(owner))
        event_type = event.get("typeDescKey")
        if event_type == "goal" and period_type in {"REG", "OT", "SO"} and side is None:
            owner_valid = False
        if event_type == "shot-on-goal" and period_type in {"REG", "OT", "SO"} and side is None:
            owner_valid = False
        if period_type in {"REG", "OT"} and side:
            if event_type == "goal":
                goals[side] += 1
                sog[side] += 1
            elif event_type == "shot-on-goal":
                sog[side] += 1
    quality["owners"] = owner_valid
    if not owner_valid:
        reasons.append("unknown_event_owner")

    for period_key, events in by_period.items():
        if not _validate_period_clocks(period_key, events):
            quality["clocks"] = False
        if not _period_has_required_markers(period_key, events):
            quality["periods"] = False
    required_reg = all(("REG", number) in by_period for number in REGULATION_PERIODS)
    outcome = document.get("gameOutcome") or {}
    last_period = outcome.get("lastPeriodType")
    has_ot = ("OT", 4) in by_period
    has_so = ("SO", 5) in by_period
    if not required_reg:
        quality["periods"] = False
    if last_period == "REG" and (has_ot or has_so):
        quality["periods"] = False
    elif last_period == "OT" and (not has_ot or has_so):
        quality["periods"] = False
    elif last_period == "SO" and (not has_ot or not has_so):
        quality["periods"] = False
    elif last_period not in {"REG", "OT", "SO"}:
        quality["periods"] = False
    if not quality["periods"]:
        reasons.append("incomplete_or_unsupported_period_sequence")
    if not quality["clocks"]:
        reasons.append("invalid_or_nonmonotonic_period_clock")

    try:
        pbp_home_score = int(home["score"])
        pbp_away_score = int(away["score"])
        pbp_home_sog = int(home["sog"])
        pbp_away_sog = int(away["sog"])
        official_home_score = int(box_home["score"])
        official_away_score = int(box_away["score"])
        official_home_sog = int(box_home["sog"])
        official_away_sog = int(box_away["sog"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{game_id}: missing PBP or independent boxscore score/SOG fields") from exc

    quality["score_sources_agree"] = (
        pbp_home_score == official_home_score and pbp_away_score == official_away_score
    )
    if not quality["score_sources_agree"]:
        reasons.append("pbp_vs_independent_boxscore_score_disagreement")
    quality["sog_sources_agree"] = (
        pbp_home_sog == official_home_sog and pbp_away_sog == official_away_sog
    )
    if not quality["sog_sources_agree"]:
        reasons.append("pbp_vs_independent_boxscore_sog_disagreement")

    shootout_winner: str | None = None
    expected_score = {"home": int(goals.get("home", 0)), "away": int(goals.get("away", 0))}
    if last_period == "SO":
        if expected_score["home"] != expected_score["away"]:
            score_ok = False
        elif official_home_score == official_away_score + 1:
            shootout_winner = "home"
            expected_score["home"] += 1
            score_ok = True
        elif official_away_score == official_home_score + 1:
            shootout_winner = "away"
            expected_score["away"] += 1
            score_ok = True
        else:
            score_ok = False
    else:
        score_ok = (
            expected_score["home"] == official_home_score
            and expected_score["away"] == official_away_score
            and official_home_score != official_away_score
        )
    quality["score"] = score_ok
    if not score_ok:
        reasons.append("goal_event_score_reconciliation_failed")
    quality["complete_final"] = official_home_score != official_away_score
    if not quality["complete_final"]:
        reasons.append("official_final_tied_or_incomplete")

    quality["sog"] = (
        int(sog.get("home", 0)) == official_home_sog
        and int(sog.get("away", 0)) == official_away_sog
    )
    if not quality["sog"]:
        reasons.append("event_sog_vs_independent_boxscore_sog_mismatch")

    periods: dict[tuple[str, int], PeriodSummary] = {}
    for (period_type, number), events in by_period.items():
        periods[(period_type, number)] = _make_period_summary(
            number, period_type, events, side_by_id
        )
    return GameSummary(
        game_id=game_id,
        start_season=start_season,
        compressed_sha256=compressed_sha,
        boxscore_compressed_sha256=boxscore_compressed_sha,
        boxscore_source=str(boxscore_row["source"]),
        home_score=official_home_score,
        away_score=official_away_score,
        home_sog=official_home_sog,
        away_sog=official_away_sog,
        regulation_ot_goals={"home": int(goals.get("home", 0)), "away": int(goals.get("away", 0))},
        source_last_period_type=str(last_period),
        shootout_winner=shootout_winner,
        periods=periods,
        quality=quality,
        reasons=reasons,
    )


def load_corpus(data_root: Path, seasons: Iterable[int]) -> Corpus:
    manifest_path = data_root / "manifests" / "hardened-v1" / "pbp_verified_manifest.csv"
    raw_dir = data_root / "raw" / "pbp"
    if not manifest_path.is_file() or not raw_dir.is_dir():
        raise FileNotFoundError(f"expected verified NHL PBP cache under {data_root}")
    manifest_sha = sha256_file(manifest_path)
    if manifest_sha != EXPECTED_MANIFEST_SHA256:
        raise ValueError(
            f"verified manifest SHA changed: expected {EXPECTED_MANIFEST_SHA256}, got {manifest_sha}"
        )
    boxscore_manifest_path = DEFAULT_BOXSCORE_ROOT / "manifest.jsonl"
    boxscore_raw_dir = DEFAULT_BOXSCORE_ROOT / "raw"
    if not boxscore_manifest_path.is_file() or not boxscore_raw_dir.is_dir():
        raise FileNotFoundError(
            f"expected independent NHL GameCenter boxscore cache under {DEFAULT_BOXSCORE_ROOT}"
        )
    boxscore_manifest_sha = sha256_file(boxscore_manifest_path)
    if boxscore_manifest_sha != EXPECTED_BOXSCORE_MANIFEST_SHA256:
        raise ValueError(
            "independent boxscore manifest SHA changed: "
            f"expected {EXPECTED_BOXSCORE_MANIFEST_SHA256}, got {boxscore_manifest_sha}"
        )
    boxscore_rows: dict[str, dict[str, Any]] = {}
    boxscore_source_counts: collections.Counter[str] = collections.Counter()
    with boxscore_manifest_path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            game_id = str(row["game_id"])
            if game_id in boxscore_rows:
                raise ValueError(f"duplicate independent boxscore manifest game ID {game_id}")
            if row.get("status") != "OK":
                raise ValueError(f"independent boxscore manifest row is not OK: {game_id}")
            if row.get("source") not in {"official_gamecenter", "prior_official_audit_cache"}:
                raise ValueError(f"unrecognized independent boxscore provenance for {game_id}")
            boxscore_rows[game_id] = row
            boxscore_source_counts[str(row["source"])] += 1
    if len(boxscore_rows) != 4876:
        raise ValueError(
            f"independent boxscore manifest lists {len(boxscore_rows)} games, expected 4876"
        )
    if dict(boxscore_source_counts) != {"official_gamecenter": 4576, "prior_official_audit_cache": 300}:
        raise ValueError(f"independent boxscore source counts changed: {dict(boxscore_source_counts)}")
    requested = set(seasons)
    all_rows: list[dict[str, str]] = []
    with manifest_path.open(newline="", encoding="utf-8") as handle:
        all_rows.extend(csv.DictReader(handle))
    pbp_rows = [row for row in all_rows if row.get("kind") == "pbp"]
    if len(pbp_rows) != 4876:
        raise ValueError(f"verified source manifest lists {len(pbp_rows)} PBP games, expected 4876")
    selected_rows = [
        row for row in pbp_rows if row.get("http_status") == "200" and int(row["game_id"][:4]) in requested
    ]
    if len(selected_rows) != sum({2018: 1271, 2019: 1082, 2020: 868, 2021: 1312}.get(y, 0) for y in requested):
        raise ValueError("selected season count differs from the frozen source-list summary")
    if any(row.get("http_status") != "200" for row in pbp_rows if int(row["game_id"][:4]) in requested):
        raise ValueError("requested season has a non-200 or unverified manifest entry")

    games: dict[str, GameSummary] = {}
    listed_by_season: collections.Counter[int] = collections.Counter()
    eligible_by_season: collections.Counter[int] = collections.Counter()
    quarantined: dict[int, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for row in sorted(selected_rows, key=lambda item: item["game_id"]):
        game_id = row["game_id"]
        start_season = int(game_id[:4])
        if game_id in games:
            raise ValueError(f"duplicate manifest game ID {game_id}")
        if game_id not in boxscore_rows:
            raise ValueError(f"no independent boxscore manifest row for PBP game {game_id}")
        listed_by_season[start_season] += 1
        game = _inspect_game(row, raw_dir, boxscore_rows[game_id], boxscore_raw_dir)
        games[game_id] = game
        if game.eligible:
            eligible_by_season[start_season] += 1
        for reason in game.reasons:
            quarantined[start_season][reason] += 1
    return Corpus(
        data_root=data_root,
        manifest_sha256=manifest_sha,
        boxscore_manifest_sha256=boxscore_manifest_sha,
        manifest_games=len(pbp_rows),
        boxscore_manifest_games=len(boxscore_rows),
        boxscore_source_counts=dict(boxscore_source_counts),
        games=games,
        listed_by_season=dict(listed_by_season),
        eligible_by_season=dict(eligible_by_season),
        quarantined_by_reason={season: dict(counts) for season, counts in quarantined.items()},
    )


def _eligible_game(game: GameSummary) -> bool:
    return game.eligible and all(("REG", period) in game.periods for period in REGULATION_PERIODS)


def _period_refs(corpus: Corpus, period_type: str, number: int) -> list[tuple[GameSummary, PeriodSummary]]:
    refs = []
    for game in corpus.games.values():
        if _eligible_game(game) and (period_type, number) in game.periods:
            refs.append((game, game.periods[(period_type, number)]))
    return refs


def _pick_period(
    rng: random.Random,
    refs: list[tuple[GameSummary, PeriodSummary]],
    used_game_ids: set[str],
    label: str,
) -> tuple[GameSummary, PeriodSummary]:
    if not refs:
        raise ValueError(f"no eligible donor period for {label}")
    # Rejection sampling is uniform over unused refs and avoids scanning the full
    # historical pool for each of the 10,000 aggregate development draws.
    for _ in range(100):
        candidate = rng.choice(refs)
        if candidate[0].game_id not in used_game_ids:
            return candidate
    candidates = [item for item in refs if item[0].game_id not in used_game_ids]
    if not candidates:
        raise ValueError(f"no eligible unused donor period for {label}")
    return rng.choice(candidates)


def _merge_counts(target: collections.Counter[str], counts: dict[str, int]) -> None:
    target.update(counts)


def _aggregate_game(
    rng: random.Random,
    corpus: Corpus,
    reg_refs: dict[int, list[tuple[GameSummary, PeriodSummary]]],
    ot_refs: list[tuple[GameSummary, PeriodSummary]],
) -> dict[str, Any]:
    used: set[str] = set()
    home_goals = away_goals = 0
    home_sog = away_sog = 0
    event_count = 0
    event_counts: collections.Counter[str] = collections.Counter()
    donor_refs: list[dict[str, Any]] = []
    for period_number in REGULATION_PERIODS:
        game, period = _pick_period(rng, reg_refs[period_number], used, f"REG {period_number}")
        used.add(game.game_id)
        home_goals += period.goals["home"]
        away_goals += period.goals["away"]
        home_sog += period.sog_events["home"]
        away_sog += period.sog_events["away"]
        event_count += period.interior_events
        _merge_counts(event_counts, period.event_counts)
        donor_refs.append({"game_id": game.game_id, "period_type": "REG", "period_number": period_number})

    shootout_winner = None
    if home_goals == away_goals:
        ot_game, ot_period = _pick_period(rng, ot_refs, used, "OT 4")
        used.add(ot_game.game_id)
        donor_refs.append({"game_id": ot_game.game_id, "period_type": "OT", "period_number": 4})
        if ot_period.ot_goal_event_index is not None:
            home_goals += ot_period.ot_goal_prefix_goals["home"]
            away_goals += ot_period.ot_goal_prefix_goals["away"]
            home_sog += ot_period.ot_goal_prefix_sog["home"]
            away_sog += ot_period.ot_goal_prefix_sog["away"]
            event_count += ot_period.ot_goal_prefix_events
            _merge_counts(event_counts, ot_period.ot_goal_prefix_counts)
        else:
            home_goals += ot_period.goals["home"]
            away_goals += ot_period.goals["away"]
            home_sog += ot_period.sog_events["home"]
            away_sog += ot_period.sog_events["away"]
            event_count += ot_period.interior_events
            _merge_counts(event_counts, ot_period.event_counts)
            if ot_game.source_last_period_type != "SO" or ot_game.shootout_winner is None:
                raise ValueError(f"{ot_game.game_id}: tied OT donor has no verified shootout")
            shootout = ot_game.periods.get(("SO", 5))
            if shootout is None or shootout.shootout_attempts < 1:
                raise ValueError(f"{ot_game.game_id}: verified shootout attempt sequence is empty")
            shootout_winner = ot_game.shootout_winner
            event_count += shootout.shootout_attempts
            event_counts["shootout-attempt"] += shootout.shootout_attempts
            donor_refs.append({"game_id": ot_game.game_id, "period_type": "SO", "period_number": 5})

    final_home = home_goals + (1 if shootout_winner == "home" else 0)
    final_away = away_goals + (1 if shootout_winner == "away" else 0)
    if final_home == final_away:
        raise ValueError("generated regular-season game did not reach a winner")
    return {
        "reg_ot_score": {"home": home_goals, "away": away_goals},
        "final_score": {"home": final_home, "away": final_away},
        "shootout_winner": shootout_winner,
        "home_sog_events": home_sog,
        "away_sog_events": away_sog,
        "nonboundary_event_count": event_count,
        "event_counts": dict(event_counts),
        "donor_refs": donor_refs,
    }


def _safe_details(event: dict[str, Any]) -> dict[str, Any]:
    details = event.get("details") or {}
    clean: dict[str, Any] = {}
    if details.get("shotType") is not None:
        clean["shot_type"] = details["shotType"]
    if details.get("zoneCode") is not None:
        clean["zone_code"] = details["zoneCode"]
    event_type = event.get("typeDescKey")
    if event_type in {"stoppage", "delayed-penalty"}:
        if details.get("reason") is not None:
            clean["reason"] = details["reason"]
        if details.get("secondaryReason") is not None:
            clean["secondary_reason"] = details["secondaryReason"]
    if event_type == "penalty":
        if details.get("descKey") is not None:
            clean["penalty_type"] = details["descKey"]
        if details.get("duration") is not None:
            duration = details["duration"]
            clean["duration_seconds"] = int(duration) if str(duration).isdigit() else duration
    return clean


def _read_verified_source_game(game: GameSummary, raw_dir: Path) -> dict[str, Any]:
    path = raw_dir / f"{game.game_id}.json.gz"
    if sha256_file(path) != game.compressed_sha256:
        raise ValueError(f"{game.game_id}: source changed between audit and generation")
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _source_period_events(
    document: dict[str, Any], period_type: str, number: int
) -> list[dict[str, Any]]:
    events = [
        event
        for event in document.get("plays", [])
        if (event.get("periodDescriptor") or {}).get("periodType") == period_type
        and (event.get("periodDescriptor") or {}).get("number") == number
    ]
    return sorted(
        events,
        key=lambda event: int(event.get("sortOrder", 0)),
    )


def _source_side_map(document: dict[str, Any]) -> dict[str, str]:
    return {
        str(document["homeTeam"]["id"]): "home",
        str(document["awayTeam"]["id"]): "away",
    }


def _state(score: dict[str, int], sog: dict[str, int]) -> dict[str, Any]:
    return {
        "score": {"home": score["home"], "away": score["away"]},
        "sog_event_count": {"home": sog["home"], "away": sog["away"]},
    }


def _append_event(
    output: list[dict[str, Any]],
    score: dict[str, int],
    sog: dict[str, int],
    *,
    period_number: int,
    period_type: str,
    event_type: str,
    team_side: str | None,
    time_in_period: str,
    time_remaining: str,
    details: dict[str, Any] | None = None,
    score_goal: bool = False,
    count_sog_event: bool = False,
) -> None:
    before = _state(score, sog)
    if score_goal:
        if team_side not in {"home", "away"}:
            raise ValueError("goal event has no home/away owner")
        score[team_side] += 1
    if count_sog_event:
        if team_side not in {"home", "away"}:
            raise ValueError("SOG event has no home/away owner")
        sog[team_side] += 1
    output.append(
        {
            "sequence": len(output) + 1,
            "period_number": period_number,
            "period_type": period_type,
            "time_in_period": time_in_period,
            "time_remaining": time_remaining,
            "clock_elapsed_seconds": parse_clock(time_in_period),
            "clock_remaining_seconds": parse_clock(time_remaining),
            "event_type": event_type,
            "team_side": team_side,
            "details": details or {},
            "state_before": before,
            "state_after": _state(score, sog),
        }
    )


def _emit_source_period(
    output: list[dict[str, Any]],
    score: dict[str, int],
    sog: dict[str, int],
    *,
    document: dict[str, Any],
    period_type: str,
    number: int,
    stop_after_first_goal: bool = False,
    shootout: bool = False,
) -> bool:
    side_by_id = _source_side_map(document)
    source_events = _source_period_events(document, period_type, number)
    saw_goal = False
    attempt_number = 0
    for event in source_events:
        source_type = event.get("typeDescKey")
        if source_type in BOUNDARY_EVENTS:
            continue
        details = event.get("details") or {}
        side = side_by_id.get(str(details.get("eventOwnerTeamId")))
        event_time = event.get("timeInPeriod")
        remaining = event.get("timeRemaining")
        clean_details = _safe_details(event)
        if shootout:
            if source_type not in SHOOTOUT_ATTEMPT_TYPES:
                continue
            if side is None:
                raise ValueError(f"{document.get('id')}: shootout attempt has no team owner")
            attempt_number += 1
            result = {
                "goal": "goal",
                "shot-on-goal": "saved",
                "missed-shot": "missed",
                "failed-shot-attempt": "failed",
            }[source_type]
            clean_details["attempt_number"] = attempt_number
            clean_details["attempt_result"] = result
            _append_event(
                output,
                score,
                sog,
                period_number=number,
                period_type=period_type,
                event_type="shootout-attempt",
                team_side=side,
                time_in_period=event_time,
                time_remaining=remaining,
                details=clean_details,
            )
            continue
        score_goal = source_type == "goal"
        sog_event = source_type in {"goal", "shot-on-goal"}
        _append_event(
            output,
            score,
            sog,
            period_number=number,
            period_type=period_type,
            event_type=source_type,
            team_side=side,
            time_in_period=event_time,
            time_remaining=remaining,
            details=clean_details,
            score_goal=score_goal,
            count_sog_event=sog_event,
        )
        if score_goal:
            saw_goal = True
            if stop_after_first_goal:
                break
    if shootout and attempt_number == 0:
        raise ValueError(f"{document.get('id')}: selected shootout has no attempts")
    return saw_goal


def _emit_boundary(
    output: list[dict[str, Any]],
    score: dict[str, int],
    sog: dict[str, int],
    *,
    period_number: int,
    period_type: str,
    event_type: str,
    elapsed: int,
    duration: int,
) -> None:
    _append_event(
        output,
        score,
        sog,
        period_number=period_number,
        period_type=period_type,
        event_type=event_type,
        team_side=None,
        time_in_period=f"{elapsed // 60:02d}:{elapsed % 60:02d}",
        time_remaining=f"{(duration - elapsed) // 60:02d}:{(duration - elapsed) % 60:02d}",
    )


def _make_generated_game(
    corpus: Corpus,
    home_label: str,
    away_label: str,
    seed: int,
) -> dict[str, Any]:
    rng = random.Random(seed)
    reg_refs = {period: _period_refs(corpus, "REG", period) for period in REGULATION_PERIODS}
    if any(not reg_refs[period] for period in REGULATION_PERIODS):
        raise ValueError("training pool lacks a complete eligible regulation period")
    ot_refs = [
        (game, game.periods[("OT", 4)])
        for game in corpus.games.values()
        if _eligible_game(game) and ("OT", 4) in game.periods
    ]
    if not ot_refs:
        raise ValueError("training pool has no eligible overtime templates")

    selected: list[tuple[GameSummary, str, int]] = []
    used: set[str] = set()
    for number in REGULATION_PERIODS:
        game, _ = _pick_period(rng, reg_refs[number], used, f"REG {number}")
        used.add(game.game_id)
        selected.append((game, "REG", number))

    score = {"home": 0, "away": 0}
    sog = {"home": 0, "away": 0}
    output: list[dict[str, Any]] = []
    for game, period_type, number in selected:
        document = _read_verified_source_game(game, corpus.data_root / "raw" / "pbp")
        duration = REGULATION_SECONDS
        _emit_boundary(output, score, sog, period_number=number, period_type=period_type,
                       event_type="period-start", elapsed=0, duration=duration)
        _emit_source_period(output, score, sog, document=document,
                            period_type=period_type, number=number)
        _emit_boundary(output, score, sog, period_number=number, period_type=period_type,
                       event_type="period-end", elapsed=duration, duration=duration)

    shootout_winner: str | None = None
    overtime_was_played = score["home"] == score["away"]
    if overtime_was_played:
        ot_game, _ = _pick_period(rng, ot_refs, used, "OT 4")
        used.add(ot_game.game_id)
        ot_document = _read_verified_source_game(ot_game, corpus.data_root / "raw" / "pbp")
        _emit_boundary(output, score, sog, period_number=4, period_type="OT",
                       event_type="period-start", elapsed=0, duration=OVERTIME_SECONDS)
        ot_goal = _emit_source_period(
            output, score, sog, document=ot_document, period_type="OT", number=4,
            stop_after_first_goal=True,
        )
        if ot_goal:
            winning_event = output[-1]
            _append_event(
                output, score, sog, period_number=4, period_type="OT", event_type="game-end",
                team_side=None, time_in_period=winning_event["time_in_period"],
                time_remaining=winning_event["time_remaining"],
            )
        else:
            if ot_game.source_last_period_type != "SO" or ot_game.shootout_winner is None:
                raise ValueError(f"{ot_game.game_id}: no-goal OT did not reach a verified shootout")
            _emit_boundary(output, score, sog, period_number=4, period_type="OT",
                           event_type="period-end", elapsed=OVERTIME_SECONDS,
                           duration=OVERTIME_SECONDS)
            so_summary = ot_game.periods.get(("SO", 5))
            if so_summary is None or so_summary.shootout_attempts < 1:
                raise ValueError(f"{ot_game.game_id}: shootout template is absent")
            _emit_boundary(output, score, sog, period_number=5, period_type="SO",
                           event_type="period-start", elapsed=0, duration=0)
            _emit_source_period(output, score, sog, document=ot_document,
                                period_type="SO", number=5, shootout=True)
            shootout_winner = ot_game.shootout_winner
            before = _state(score, sog)
            score[shootout_winner] += 1
            output.append(
                {
                    "sequence": len(output) + 1,
                    "period_number": 5,
                    "period_type": "SO",
                    "time_in_period": "00:00",
                    "time_remaining": "00:00",
                    "clock_elapsed_seconds": 0,
                    "clock_remaining_seconds": 0,
                    "event_type": "shootout-decision",
                    "team_side": shootout_winner,
                    "details": {"official_bonus_goal": 1, "player_goal": False},
                    "state_before": before,
                    "state_after": _state(score, sog),
                }
            )
            _emit_boundary(output, score, sog, period_number=5, period_type="SO",
                           event_type="period-end", elapsed=0, duration=0)
            _append_event(output, score, sog, period_number=5, period_type="SO",
                          event_type="game-end", team_side=None, time_in_period="00:00",
                          time_remaining="00:00")
    else:
        _append_event(output, score, sog, period_number=3, period_type="REG",
                      event_type="game-end", team_side=None, time_in_period="20:00",
                      time_remaining="00:00")

    if score["home"] == score["away"]:
        raise ValueError("generated game ended tied")
    reg_ot_goals = {
        "home": score["home"] - (1 if shootout_winner == "home" else 0),
        "away": score["away"] - (1 if shootout_winner == "away" else 0),
    }
    event_counts = collections.Counter(event["event_type"] for event in output)
    source_blocks: list[dict[str, Any]] = []
    for game, period_type, number in selected:
        source_blocks.append(
            {"game_id": game.game_id, "period_type": period_type, "period_number": number,
             "compressed_sha256": game.compressed_sha256,
             "boxscore_compressed_sha256": game.boxscore_compressed_sha256}
        )
    if overtime_was_played:
        source_blocks.append(
            {"game_id": ot_game.game_id, "period_type": "OT", "period_number": 4,
             "compressed_sha256": ot_game.compressed_sha256,
             "boxscore_compressed_sha256": ot_game.boxscore_compressed_sha256}
        )
        if shootout_winner:
            source_blocks.append(
                {"game_id": ot_game.game_id, "period_type": "SO", "period_number": 5,
                 "compressed_sha256": ot_game.compressed_sha256,
                 "boxscore_compressed_sha256": ot_game.boxscore_compressed_sha256}
            )
    _validate_generated_record(output, score, sog, reg_ot_goals, shootout_winner)
    return {
        "schema_version": "nhl-statistical-pbp-v0.1",
        "mode": "hypothetical_statistical_simulation",
        "simulation_id": f"nhlstat-v0.1-{home_label}-{away_label}-seed-{seed}",
        "model_version": MODEL_VERSION,
        "seed": seed,
        "teams": {"home": home_label, "away": away_label},
        "rules_profile": {
            "competition": "regular_season",
            "regulation_periods": 3,
            "regulation_period_seconds": REGULATION_SECONDS,
            "overtime_period_seconds": OVERTIME_SECONDS,
            "shootout_after_tied_overtime": True,
            "shootout_decider_adds_one_official_final_score_goal": True,
        },
        "provenance": {
            "source": "archived NHL GameCenter play-by-play with independent GameCenter boxscore validation",
            "source_manifest_sha256": corpus.manifest_sha256,
            "independent_boxscore_manifest_sha256": corpus.boxscore_manifest_sha256,
            "independent_boxscore_manifest_games": corpus.boxscore_manifest_games,
            "independent_boxscore_source_counts": corpus.boxscore_source_counts,
            "training_start_seasons": list(TRAIN_SEASONS),
            "development_start_seasons_excluded": list(DEVELOPMENT_SEASONS),
            "exposed_holdout_start_seasons_excluded": list(EXCLUDED_SEASONS),
            "source_quality_quarantined_start_seasons": list(SOURCE_QUALITY_QUARANTINE_SEASONS),
            "sampling_unit": "complete historical period event template",
            "template_reuse_within_game": "source game IDs are distinct across selected periods",
            "source_player_identity_fields_removed": True,
            "source_coordinates_removed": True,
            "donor_blocks_for_audit": source_blocks,
        },
        "events": output,
        "summary": {
            "regulation_overtime_score": reg_ot_goals,
            "official_final_score": dict(score),
            "shootout_winner": shootout_winner,
            "winner": "home" if score["home"] > score["away"] else "away",
            "sog_event_counts": dict(sog),
            "sog_event_count_definition": "generated goal and shot-on-goal events in regulation/overtime",
            "event_counts": dict(sorted(event_counts.items())),
            "event_count": len(output),
        },
        "record_complete": True,
        "limitations": [
            "League-level period-template bootstrap; does not condition event generation on the requested team labels.",
            "The event chronology is resampled from historical periods; this is not a learned next-event state machine.",
            "No player identities, roster decisions, goalie ratings, continuous movement, puck possession, or physical causality are modeled.",
            "A future viewer may display this event record but must label it hypothetical and must not imply a physical replay.",
        ],
    }


def _validate_generated_record(
    events: list[dict[str, Any]],
    final_score: dict[str, int],
    final_sog: dict[str, int],
    reg_ot_goals: dict[str, int],
    shootout_winner: str | None,
) -> None:
    if not events or [event["sequence"] for event in events] != list(range(1, len(events) + 1)):
        raise ValueError("generated event sequence is empty or noncontiguous")
    recalculated_score = {"home": 0, "away": 0}
    recalculated_sog = {"home": 0, "away": 0}
    previous_score = dict(recalculated_score)
    previous_sog = dict(recalculated_sog)
    last_period_clock: dict[int, int] = {}
    for event in events:
        period_number = event["period_number"]
        clock_elapsed = event["clock_elapsed_seconds"]
        if clock_elapsed < last_period_clock.get(period_number, -1):
            raise ValueError(f"generated period {period_number} clock moved backwards")
        last_period_clock[period_number] = clock_elapsed
        if event["state_before"]["score"] != previous_score:
            raise ValueError(f"score before-state does not reconcile at event {event['sequence']}")
        if event["state_before"]["sog_event_count"] != previous_sog:
            raise ValueError(f"SOG before-state does not reconcile at event {event['sequence']}")
        if event["event_type"] == "goal" and event["period_type"] != "SO":
            if event["team_side"] not in recalculated_score:
                raise ValueError("generated goal has no team side")
            recalculated_score[event["team_side"]] += 1
            recalculated_sog[event["team_side"]] += 1
        elif event["event_type"] == "shot-on-goal" and event["period_type"] != "SO":
            if event["team_side"] not in recalculated_sog:
                raise ValueError("generated SOG event has no team side")
            recalculated_sog[event["team_side"]] += 1
        elif event["event_type"] == "shootout-decision":
            recalculated_score[event["team_side"]] += 1
        if event["state_after"]["score"] != recalculated_score:
            raise ValueError(f"score state does not reconcile at event {event['sequence']}")
        if event["state_after"]["sog_event_count"] != recalculated_sog:
            raise ValueError(f"SOG event state does not reconcile at event {event['sequence']}")
        forbidden_fields = {
            key
            for key in event
            if key.lower().endswith(("playerid", "goalieid"))
            or key in {"xCoord", "yCoord", "discreteClip"}
        }
        for details_key in event.get("details", {}):
            if details_key.lower().endswith(("playerid", "goalieid")) or details_key in {
                "xCoord", "yCoord", "discreteClip"
            }:
                forbidden_fields.add(details_key)
        if forbidden_fields:
            raise ValueError(f"source identity/coordinate fields leaked: {sorted(forbidden_fields)}")
        previous_score = dict(recalculated_score)
        previous_sog = dict(recalculated_sog)
    periods = collections.defaultdict(list)
    for event in events:
        periods[event["period_number"]].append(event)
    for number in (1, 2, 3):
        period_events = periods.get(number, [])
        end_events = [event for event in period_events if event["event_type"] == "period-end"]
        if not period_events or period_events[0]["event_type"] != "period-start" or len(end_events) != 1:
            raise ValueError(f"regulation period {number} lacks complete boundaries")
        if period_events[0]["clock_remaining_seconds"] != REGULATION_SECONDS or end_events[0]["clock_remaining_seconds"] != 0:
            raise ValueError(f"regulation period {number} has an invalid boundary clock")
        end_index = period_events.index(end_events[0])
        if any(event["event_type"] != "game-end" for event in period_events[end_index + 1 :]):
            raise ValueError(f"regulation period {number} has events after period end")
    if 4 in periods:
        ot_events = periods[4]
        if not ot_events or ot_events[0]["event_type"] != "period-start":
            raise ValueError("overtime period lacks a start boundary")
        if not any(event["event_type"] == "goal" for event in ot_events) and (
            ot_events[-1]["event_type"] != "period-end" or ot_events[-1]["clock_elapsed_seconds"] != OVERTIME_SECONDS
        ):
            raise ValueError("scoreless overtime period did not reach 05:00")
    if 5 in periods:
        so_events = periods[5]
        if not so_events or so_events[0]["event_type"] != "period-start":
            raise ValueError("shootout period lacks a start boundary")
        if not any(event["event_type"] == "shootout-decision" for event in so_events):
            raise ValueError("shootout period lacks a deciding outcome")
    if recalculated_score != final_score:
        raise ValueError("final score does not reconcile with generated events")
    if recalculated_sog != final_sog:
        raise ValueError("SOG event totals do not reconcile with generated events")
    if final_score["home"] == final_score["away"]:
        raise ValueError("complete generated regular-season game has no winner")
    if shootout_winner and final_score[shootout_winner] != reg_ot_goals[shootout_winner] + 1:
        raise ValueError("shootout deciding-goal convention does not reconcile")


def _quantile(values: list[int | float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot compute quantile of empty values")
    index = round((len(ordered) - 1) * q)
    return float(ordered[index])


def _distribution_summary(values: list[int | float]) -> dict[str, float | int]:
    if not values:
        raise ValueError("cannot summarize an empty population")
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "variance": statistics.pvariance(values),
        "sd": statistics.pstdev(values),
        "p10": _quantile(values, 0.10),
        "p50": _quantile(values, 0.50),
        "p90": _quantile(values, 0.90),
    }


class EmpiricalDistribution:
    def __init__(self, values: list[int | float]):
        if not values:
            raise ValueError("empirical forecast distribution is empty")
        self.values = sorted(values)
        self.n = len(values)
        self.prefix = [0.0]
        for value in self.values:
            self.prefix.append(self.prefix[-1] + value)
        self.half_pair_distance = sum(
            (2 * (index + 1) - self.n - 1) * value
            for index, value in enumerate(self.values)
        ) / (self.n * self.n)

    def crps(self, observed: int | float) -> float:
        split = bisect.bisect_right(self.values, observed)
        lower_distance = observed * split - self.prefix[split]
        upper_distance = (self.prefix[self.n] - self.prefix[split]) - observed * (self.n - split)
        return (lower_distance + upper_distance) / self.n - self.half_pair_distance


def _bootstrap_mean_ci(values: list[float], seed: int, repetitions: int = 1000) -> list[float]:
    if not values:
        raise ValueError("cannot bootstrap an empty game population")
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(repetitions):
        means.append(math.fsum(values[rng.randrange(n)] for _ in range(n)) / n)
    return [_quantile(means, 0.025), _quantile(means, 0.975)]


def _energy_pair_term(samples: list[tuple[int, int]], seed: int, draws: int = 200_000) -> float:
    rng = random.Random(seed)
    n = len(samples)
    total = 0.0
    for _ in range(draws):
        x = samples[rng.randrange(n)]
        y = samples[rng.randrange(n)]
        total += math.hypot(x[0] - y[0], x[1] - y[1])
    return 0.5 * total / draws


def _evaluate(corpus: Corpus, simulations: int, seed: int) -> dict[str, Any]:
    train_games = [game for game in corpus.games.values() if game.start_season in TRAIN_SEASONS]
    dev_games = [game for game in corpus.games.values() if game.start_season in DEVELOPMENT_SEASONS]
    train_eligible = [game for game in train_games if _eligible_game(game)]
    dev_eligible = [game for game in dev_games if _eligible_game(game)]
    if len(train_eligible) < 1000 or len(dev_eligible) < 500:
        raise ValueError("eligible training or development population is unexpectedly small")
    reg_refs = {
        period: [(game, game.periods[("REG", period)]) for game in train_eligible]
        for period in REGULATION_PERIODS
    }
    ot_refs = [(game, game.periods[("OT", 4)]) for game in train_eligible if ("OT", 4) in game.periods]
    if not ot_refs:
        raise ValueError("no eligible OT templates in training population")

    rng = random.Random(seed)
    draws = [_aggregate_game(rng, corpus, reg_refs, ot_refs) for _ in range(simulations)]
    reg_home = [draw["reg_ot_score"]["home"] for draw in draws]
    reg_away = [draw["reg_ot_score"]["away"] for draw in draws]
    final_home = [draw["final_score"]["home"] for draw in draws]
    final_away = [draw["final_score"]["away"] for draw in draws]
    home_sog = [draw["home_sog_events"] for draw in draws]
    away_sog = [draw["away_sog_events"] for draw in draws]
    event_counts = [draw["nonboundary_event_count"] for draw in draws]
    simulated_score_pairs = list(zip(final_home, final_away))
    energy_pair_term = _energy_pair_term(simulated_score_pairs, seed + 1)

    observed_home_reg = [game.reg_ot_score["home"] for game in dev_eligible]
    observed_away_reg = [game.reg_ot_score["away"] for game in dev_eligible]
    observed_home_final = [game.home_score for game in dev_eligible]
    observed_away_final = [game.away_score for game in dev_eligible]
    observed_home_sog = [game.home_sog for game in dev_eligible]
    observed_away_sog = [game.away_sog for game in dev_eligible]
    observed_events = [
        sum(period.interior_events for period in game.periods.values())
        for game in dev_eligible
    ]
    dev_home_wins = [1 if game.home_score > game.away_score else 0 for game in dev_eligible]
    predicted_home_win = sum(
        1 for draw in draws if draw["final_score"]["home"] > draw["final_score"]["away"]
    ) / simulations

    reg_home_dist = EmpiricalDistribution(reg_home)
    reg_away_dist = EmpiricalDistribution(reg_away)
    final_home_dist = EmpiricalDistribution(final_home)
    final_away_dist = EmpiricalDistribution(final_away)
    home_sog_dist = EmpiricalDistribution(home_sog)
    away_sog_dist = EmpiricalDistribution(away_sog)
    reg_crps = [
        0.5 * (reg_home_dist.crps(game.reg_ot_score["home"]) + reg_away_dist.crps(game.reg_ot_score["away"]))
        for game in dev_eligible
    ]
    final_crps = [
        0.5 * (final_home_dist.crps(game.home_score) + final_away_dist.crps(game.away_score))
        for game in dev_eligible
    ]
    sog_crps = [
        0.5 * (home_sog_dist.crps(game.home_sog) + away_sog_dist.crps(game.away_sog))
        for game in dev_eligible
    ]
    score_energy = []
    for game in dev_eligible:
        first_term = statistics.fmean(
            math.hypot(home - game.home_score, away - game.away_score)
            for home, away in simulated_score_pairs
        )
        score_energy.append(first_term - energy_pair_term)
    winner_brier = [
        (predicted_home_win - actual) ** 2 for actual in dev_home_wins
    ]

    metric_values = {
        "regulation_overtime_goal_crps_per_team": reg_crps,
        "official_final_score_crps_per_team": final_crps,
        "final_score_energy": score_energy,
        "winner_brier": winner_brier,
        "sog_crps_per_team": sog_crps,
    }
    metrics = {
        name: {"mean": statistics.fmean(values),
               "ci95_game_bootstrap": _bootstrap_mean_ci(values, seed + 2 + index)}
        for index, (name, values) in enumerate(metric_values.items())
    }

    observed_counts = {
        "home_reg_ot_goals": observed_home_reg,
        "away_reg_ot_goals": observed_away_reg,
        "home_official_final_score": observed_home_final,
        "away_official_final_score": observed_away_final,
        "home_sog": observed_home_sog,
        "away_sog": observed_away_sog,
        "nonboundary_pbp_events": observed_events,
        "official_goal_margin_home_minus_away": [h - a for h, a in zip(observed_home_final, observed_away_final)],
    }
    simulated_counts = {
        "home_reg_ot_goals": reg_home,
        "away_reg_ot_goals": reg_away,
        "home_official_final_score": final_home,
        "away_official_final_score": final_away,
        "home_sog": home_sog,
        "away_sog": away_sog,
        "nonboundary_pbp_events": event_counts,
        "official_goal_margin_home_minus_away": [h - a for h, a in zip(final_home, final_away)],
    }
    count_calibration = {
        "observed_2021_development": {key: _distribution_summary(values) for key, values in observed_counts.items()},
        "simulated_from_2019_2020": {key: _distribution_summary(values) for key, values in simulated_counts.items()},
    }
    training_data = {
        "games_listed": {year: corpus.listed_by_season.get(year, 0) for year in TRAIN_SEASONS},
        "games_eligible": {year: corpus.eligible_by_season.get(year, 0) for year in TRAIN_SEASONS},
        "quarantine_by_reason": {year: corpus.quarantined_by_reason.get(year, {}) for year in TRAIN_SEASONS},
    }
    development_data = {
        "games_listed": {year: corpus.listed_by_season.get(year, 0) for year in DEVELOPMENT_SEASONS},
        "games_eligible": {year: corpus.eligible_by_season.get(year, 0) for year in DEVELOPMENT_SEASONS},
        "quarantine_by_reason": {year: corpus.quarantined_by_reason.get(year, {}) for year in DEVELOPMENT_SEASONS},
    }
    return {
        "schema_version": "nhl-statistical-pbp-development-v0.1",
        "model_version": MODEL_VERSION,
        "source_manifest_sha256": corpus.manifest_sha256,
        "independent_boxscore_manifest_sha256": corpus.boxscore_manifest_sha256,
        "independent_boxscore_manifest_games": corpus.boxscore_manifest_games,
        "independent_boxscore_source_counts": corpus.boxscore_source_counts,
        "training_start_seasons": list(TRAIN_SEASONS),
        "development_start_seasons": list(DEVELOPMENT_SEASONS),
        "excluded_exposed_start_seasons": list(EXCLUDED_SEASONS),
        "source_quality_quarantined_start_seasons": list(SOURCE_QUALITY_QUARANTINE_SEASONS),
        "forecast_scope": "one league-level home/away distribution reused for every eligible 2021 game; no team conditioning",
        "training_data": training_data,
        "development_data": development_data,
        "development_game_count": len(dev_eligible),
        "simulation_draw_count": simulations,
        "simulation_seed": seed,
        "energy_score_pair_draw_count": 200_000,
        "predicted_home_win_probability": predicted_home_win,
        "metrics": metrics,
        "count_calibration": count_calibration,
        "uncertainty": "95% intervals resample eligible 2021 development games; simulator draws are fixed common random numbers across every game because this model is team-independent; energy score uses the recorded Monte Carlo pair draw count",
        "limitations": [
            "This is a development diagnostic, not a fresh holdout or adoption test.",
            "The 2022 start-season slice is excluded because earlier NHL work exposed it and the local archive is partial.",
            "The model ignores requested team identities and therefore does not estimate a matchup-specific forecast.",
            "Scores and team SOG are checked against the separate archived GameCenter boxscore manifest and bodies; PBP scoreboard fields must agree with that source, and event SOG must reconcile to the boxscore SOG.",
            "Historical period blocks preserve event ordering but do not model causal possession, player choices, or physical motion.",
        ],
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("generate", "evaluate"))
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--home-team", default="HOME")
    parser.add_argument("--away-team", default="AWAY")
    parser.add_argument("--seed", type=int, default=31415)
    parser.add_argument("--simulations", type=int, default=10_000)
    args = parser.parse_args(argv)
    if args.simulations < 100:
        parser.error("--simulations must be at least 100")
    started = time.monotonic()
    if args.action == "generate":
        for label in (args.home_team, args.away_team):
            if not TEAM_LABEL.fullmatch(label):
                parser.error(f"invalid team label: {label!r}")
        if args.home_team == args.away_team:
            parser.error("home and away labels must differ")
        corpus = load_corpus(args.data_root, TRAIN_SEASONS)
        if not any(_eligible_game(game) for game in corpus.games.values()):
            raise ValueError("no eligible training games remain after quarantine")
        result = _make_generated_game(corpus, args.home_team, args.away_team, args.seed)
        _write_json(args.out, result)
        print(json.dumps({
            "output": str(args.out),
            "simulation_id": result["simulation_id"],
            "final_score": result["summary"]["official_final_score"],
            "shootout_winner": result["summary"]["shootout_winner"],
            "event_count": result["summary"]["event_count"],
            "eligible_training_games": corpus.eligible_by_season,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }, sort_keys=True))
        return 0

    selected = (*TRAIN_SEASONS, *DEVELOPMENT_SEASONS)
    corpus = load_corpus(args.data_root, selected)
    result = _evaluate(corpus, args.simulations, args.seed)
    result["runtime_seconds"] = round(time.monotonic() - started, 3)
    _write_json(args.out, result)
    print(json.dumps({
        "output": str(args.out),
        "development_games": result["development_game_count"],
        "simulations": args.simulations,
        "metrics": result["metrics"],
        "runtime_seconds": result["runtime_seconds"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
