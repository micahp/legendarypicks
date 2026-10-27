#!/usr/bin/env python3
"""Research NHL full-game sampler with team-conditioned shots and simulated rosters.

This version uses verified 2019-20 GameCenter period events as event/time/shift
templates. Pregame team priors condition template selection and shot conversion;
target-roster identities are assigned through position/usage ranks. It is a
statistical event simulator, not a possession or physical hockey engine.
"""

from __future__ import annotations

import argparse
import collections
import csv
import copy
import datetime as dt
import functools
import gzip
import hashlib
import importlib.util
import json
import math
import random
import re
import sqlite3
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from game_state import (PenaltyLedger, possession_after_event, shootout_decided,
                        shot_side_for_possession)


ROOT = Path(__file__).resolve().parents[3]
V01_PATH = ROOT / "research/nhl/statistical-full-game-v0.1/nhl_statistical_game.py"
spec = importlib.util.spec_from_file_location("nhl_v01_frozen", V01_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load frozen v0.1 module at {V01_PATH}")
v01 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v01
spec.loader.exec_module(v01)

MODEL_VERSION = "nhl-game-state-v0.2b-b1"
TRANSITION_MODEL_VERSION = "nhl-game-state-v0.2b-b2"
SHIFT_ROOT = Path("/root/lp-data/nhl-fullframe-event-audit-2026-10-21")
SHIFT_MANIFEST_SHA256 = "deba1a38d9f9c969139dc15ac57e7085988c05bcab36db43bd87fe5805f1c6f5"
SHIFT_MANIFEST = SHIFT_ROOT / "manifests/hardened-v1/shifts_verified_manifest.csv"
SHIFT_RAW = SHIFT_ROOT / "raw/shifts"
DEFAULT_DB = Path("/root/legendarypicks/backend/data/picks.dev.db")
FORECASTS = ROOT / "research/nhl/prospective-2026-27/forecasts.jsonl"
FROZEN_MODELS = ROOT / "research/nhl/prospective-2026-27/frozen_models_2026-27_v1.json"
REG_SECONDS = 20 * 60
OT_SECONDS = 5 * 60
CLOCK = re.compile(r"^(\d{1,2}):(\d{2})$")
SHOT_EVENTS = {"goal", "shot-on-goal"}
ATTEMPT_EVENTS = {"goal", "shot-on-goal", "missed-shot", "blocked-shot"}
BOUNDARY_EVENTS = {"period-start", "period-end", "game-end", "shootout-complete"}


class DonorDataError(ValueError):
    """A source-period quality failure that can be quarantined before sampling."""

    def __init__(self, reason: str, message: str):
        self.reason=reason
        super().__init__(message)


@dataclass
class Player:
    nhl_id: str
    canonical_id: int | None
    name: str
    team: str
    position: str
    usage_minutes: float = 12.0
    shots: float = 0.0
    goals: float = 0.0
    assists: float = 0.0
    faceoff_pct: float = 0.5
    games_played: float = 0.0
    games_started: float = 0.0
    saves: float = 0.0
    shots_against: float = 0.0
    goals_against: float = 0.0
    save_pct: float = 0.905
    stats_missing: bool = False
    source: str = ""

    @property
    def shot_rate(self) -> float:
        return max(0.02, self.shots / max(1.0, self.usage_minutes))

    @property
    def finish_rate(self) -> float:
        return min(0.35, max(0.025, (self.goals + 80 * 0.095) / (self.shots + 80)))


@dataclass
class TeamRoster:
    team: str
    players: dict[str, Player]
    expected_sog: float
    expected_sog_against: float
    goalie_ids: list[str]
    goalie_weights: list[float]
    profile_hash: str
    coverage: dict[str, Any]

    def role_players(self, group: str) -> list[Player]:
        if group == "F":
            values = [p for p in self.players.values() if p.position in {"C", "L", "R", "LW", "RW", "F"}]
        else:
            values = [p for p in self.players.values() if p.position == group]
        return sorted(values, key=lambda p: (-p.usage_minutes, -p.shots, p.nhl_id))


@dataclass
class PregameInputs:
    game_key: str
    game_date: str
    scheduled_start_utc: str
    as_of_utc: str
    home_team: str
    away_team: str
    home_roster: TeamRoster
    away_roster: TeamRoster
    mu_home: float
    mu_away: float
    team_model: dict[str, Any]
    snapshot: dict[str, Any]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_clock(value: str) -> int:
    m = CLOCK.fullmatch(str(value))
    if not m or int(m.group(2)) >= 60:
        raise ValueError(f"invalid NHL period clock: {value!r}")
    return int(m.group(1)) * 60 + int(m.group(2))


def _shift_interval(row: dict[str,Any], game_id: str) -> tuple[int,int]|None:
    start_raw=row.get("startTime"); end_raw=row.get("endTime")
    duration_raw=row.get("duration")
    try:
        duration=parse_clock(str(duration_raw)) if duration_raw not in (None,"") else None
    except ValueError as exc:
        raise DonorDataError("shift_interval_invalid",f"{game_id}: invalid shift duration {duration_raw!r}") from exc
    if start_raw in (None,"") and end_raw in (None,""):
        if duration not in (None,0):
            raise DonorDataError("shift_interval_invalid",f"{game_id}: positive-duration shift has no clock endpoints")
        return None
    if start_raw in (None,"") or end_raw in (None,""):
        if duration==0:
            return None
        raise DonorDataError("shift_interval_invalid",f"{game_id}: shift row has only one clock endpoint")
    try:
        start=parse_clock(str(start_raw)); end=parse_clock(str(end_raw))
    except ValueError as exc:
        raise DonorDataError("shift_interval_invalid",
            f"{game_id}: invalid shift clock endpoint {start_raw!r}..{end_raw!r}") from exc
    if end<=start:
        if duration not in (None,0):
            raise DonorDataError("shift_interval_invalid",f"{game_id}: shift duration disagrees with non-positive clock interval")
        return None
    if duration is not None and end-start!=duration:
        raise DonorDataError("shift_interval_invalid",f"{game_id}: shift duration does not match its clock endpoints")
    return start,end


def _to_minutes(value: Any) -> float:
    if not value:
        return 0.0
    if isinstance(value, (float, int)):
        return float(value)
    m = CLOCK.fullmatch(str(value))
    if not m or int(m.group(2)) >= 60:
        return 0.0
    return int(m.group(1)) + int(m.group(2)) / 60


def _logit(p: float) -> float:
    p = min(0.95, max(0.005, p))
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-min(x, 35))
        return 1 / (1 + z)
    z = math.exp(max(x, -35))
    return z / (1 + z)


def _goalie_logit_delta(save_pct: float | None, league_goal_rate: float) -> float:
    """Return the regularized goalie effect on a shot's goal log-odds."""
    if save_pct is None:
        return 0.0
    goalie_goal_rate=max(.02,1.0-float(save_pct))
    return .20*(_logit(goalie_goal_rate)-_logit(league_goal_rate))


def _shootout_goal_probability(shooter_finish_rate: float, goalie_save_pct: float,
                               model: "ShotQualityModel") -> float:
    goalie_goal_rate=max(.02,1.0-float(goalie_save_pct))
    logit=(_logit(model.shootout_goal_rate)
           +.15*(_logit(shooter_finish_rate)-_logit(model.global_goal_rate))
           +.15*(_logit(goalie_goal_rate)-_logit(model.global_goal_rate)))
    return _sigmoid(logit)


def load_shift_manifest() -> dict[str, dict[str, str]]:
    if sha256_file(SHIFT_MANIFEST) != SHIFT_MANIFEST_SHA256:
        raise ValueError("verified NHL shift manifest hash changed")
    rows: dict[str, dict[str, str]] = {}
    with SHIFT_MANIFEST.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("kind") != "shifts" or row.get("http_status") != "200":
                continue
            game_id = str(row["game_id"])
            if game_id in rows:
                raise ValueError(f"duplicate shift manifest game {game_id}")
            rows[game_id] = row
    if len(rows) != 4876:
        raise ValueError(f"shift manifest has {len(rows)} games; expected 4876")
    return rows


def read_verified_shift_game(game_id: str, manifest: dict[str, dict[str, str]]) -> dict[str, Any]:
    row = manifest.get(game_id)
    if row is None:
        raise ValueError(f"no verified shift manifest row for donor game {game_id}")
    doc = _read_verified_gzip_cached(str(SHIFT_RAW / f"{game_id}.json.gz"),
                                    int(row["bytes_gz"]),str(row["sha256_gz"]))
    if int(doc.get("total", -1)) != len(doc.get("data", [])):
        raise ValueError(f"{game_id}: shift response total does not reconcile")
    return doc


@functools.lru_cache(maxsize=512)
def _read_verified_gzip_cached(path_text: str, expected_bytes: int | None,
                               expected_sha256: str) -> dict[str, Any]:
    """Cache immutable, hash-verified source JSON to avoid repeated Monte Carlo decompression."""
    path=Path(path_text)
    if expected_bytes is not None and path.stat().st_size!=expected_bytes:
        raise ValueError(f"{path.name}: compressed body size differs from manifest")
    if sha256_file(path)!=expected_sha256:
        raise ValueError(f"{path.name}: compressed body hash differs from manifest")
    with gzip.open(path,"rt",encoding="utf-8") as handle:
        return json.load(handle)


def read_verified_pbp_game(game: Any, raw_dir: Path) -> dict[str, Any]:
    return _read_verified_gzip_cached(str(raw_dir / f"{game.game_id}.json.gz"),
                                     None,game.compressed_sha256)


def load_roster(db_path: Path, team: str, game_date: str, cutoff: dt.datetime) -> TeamRoster:
    if not db_path.is_file():
        raise FileNotFoundError(f"read-only roster database not found: {db_path}")
    uri = f"file:{db_path}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    try:
        snapshot = con.execute(
            "SELECT id,season,source,captured_at,published_at,source_checksum,player_count,status "
            # Status is mutable: a snapshot that was published before this cutoff may now be
            # superseded. Reconstruct the as-of published snapshot using its availability time.
            "FROM roster_snapshots WHERE league='nhl' AND status IN ('published','superseded') "
            "AND captured_at<=? AND published_at<=? ORDER BY published_at DESC LIMIT 1",
            (cutoff.isoformat(),cutoff.isoformat())
        ).fetchone()
        if snapshot is None:
            raise ValueError(f"no published NHL roster snapshot at or before {cutoff.isoformat()}")
        sid = int(snapshot["id"])
        season = int(snapshot["season"])
        prior_season = season - 1
        raw_rows = con.execute(
            "SELECT m.player_id,m.source_player_key,m.team,m.position,m.roster_status,m.display_name, "
            "p.player_name,p.games,p.goals,p.assists,p.shots,p.toi,p.faceoff_pct,p.games_started, "
            "p.saves,p.shots_against,p.goals_against,p.save_pct,p.source "
            "FROM roster_memberships m LEFT JOIN player_stats p "
            "ON p.player_id=m.player_id AND p.league='nhl' AND p.season=? AND p.stat_type='season' "
            "WHERE m.snapshot_id=? AND m.team=? AND m.roster_status='active' "
            "ORDER BY m.position,m.display_name", (prior_season, sid, team)
        ).fetchall()
        if not raw_rows:
            raise ValueError(f"roster snapshot {sid} has no active players for {team}")

        logs: dict[int, dict[str, float]] = collections.defaultdict(lambda: collections.defaultdict(float))
        log_rows = con.execute(
            "SELECT player_id,game_date,stats,source,ingested_at FROM player_game_logs "
            "WHERE league='nhl' AND season=? AND game_type='REG' AND game_date<? "
            "AND source='nhle.com:gamecenter/boxscore' "
            "AND ingested_at<=?", (season, game_date, cutoff.isoformat())
        ).fetchall()
        log_dates: list[str] = []
        for row in log_rows:
            pid = row["player_id"]
            if pid is None:
                continue
            blob = json.loads(row["stats"] or "{}")
            acc = logs[int(pid)]
            acc["games"] += 1
            for dest, keys in {
                "shots": ("sog", "shots"), "goals": ("goals",), "assists": ("assists",),
                "toi": ("toi",), "saves": ("saves",), "shots_against": ("shotsAgainst",),
                "goals_against": ("goalsAgainst",), "starts": ("gamesStarted",),
            }.items():
                val = next((blob.get(k) for k in keys if blob.get(k) is not None), None)
                if val is not None:
                    acc[dest] += _to_minutes(val) if dest == "toi" else float(val)
            log_dates.append(str(row["game_date"]))

        players: dict[str, Player] = {}
        for row in raw_rows:
            nhl_id = str(row["source_player_key"] or "")
            if not nhl_id.isdigit():
                continue
            canonical_id = int(row["player_id"]) if row["player_id"] is not None else None
            prior_games = float(row["games"] or 0)
            prior_toi_avg = _to_minutes(row["toi"])
            prior_minutes = prior_games * prior_toi_avg
            prior_shots = float(row["shots"] or 0)
            prior_goals = float(row["goals"] or 0)
            prior_assists = float(row["assists"] or 0)
            current = logs.get(canonical_id or -1, {})
            current_minutes = float(current.get("toi", 0))
            current_shots = float(current.get("shots", 0))
            current_goals = float(current.get("goals", 0))
            current_assists = float(current.get("assists", 0))
            current_games = float(current.get("games", 0))
            total_minutes = prior_minutes + current_minutes
            total_shots = prior_shots + current_shots
            usage = total_minutes / max(1.0, prior_games + current_games)
            if usage <= 0:
                usage = 8.0 if row["position"] in {"D", "G"} else 10.0
            total_goals = prior_goals + current_goals
            faceoff = float(row["faceoff_pct"] or 50.0) / 100.0
            goalie_sa = float(row["shots_against"] or 0) + float(current.get("shots_against", 0))
            goalie_saves = float(row["saves"] or 0) + float(current.get("saves", 0))
            goalie_ga = float(row["goals_against"] or 0) + float(current.get("goals_against", 0))
            raw_sp = row["save_pct"]
            if raw_sp is None:
                raw_sp = (goalie_saves / goalie_sa) if goalie_sa else 0.905
            raw_sp = float(raw_sp)
            if raw_sp > 1.0:
                raw_sp /= 100.0
            # Prior-season exposure supplies the shrinkage mass; current logs are strictly pregame.
            effective_sa = max(200.0, goalie_sa)
            prior_sp = float(row["save_pct"] or raw_sp)
            if prior_sp > 1.0:
                prior_sp /= 100.0
            save_pct = (prior_sp * max(200.0, float(row["shots_against"] or 0)) +
                        float(current.get("saves", 0))) / (max(200.0, float(row["shots_against"] or 0)) +
                        float(current.get("shots_against", 0)))
            if not math.isfinite(save_pct):
                save_pct = 0.905
            starts = float(row["games_started"] or 0) + float(current.get("starts", 0))
            player = Player(
                nhl_id=nhl_id, canonical_id=canonical_id,
                name=str(row["display_name"] or row["player_name"] or f"NHL-{nhl_id}"),
                team=team, position=str(row["position"] or "?"),
                usage_minutes=min(30.0, max(3.0, usage)), shots=total_shots, goals=total_goals,
                assists=prior_assists + current_assists, faceoff_pct=min(.85, max(.15, faceoff)),
                games_played=prior_games + current_games,
                games_started=starts, saves=goalie_saves, shots_against=goalie_sa,
                goals_against=goalie_ga, save_pct=min(.97, max(.82, save_pct)),
                stats_missing=(prior_games == 0 and current_minutes == 0), source=str(row["source"] or "position_prior"),
            )
            if nhl_id in players:
                raise ValueError(f"duplicate NHL-native roster identity {nhl_id} on {team}")
            players[nhl_id] = player
        if not players:
            raise ValueError(f"no NHL-native player IDs resolved for {team}")
        skaters = [p for p in players.values() if p.position != "G"]
        if sum(p.position in {"C", "L", "R", "LW", "RW", "F"} for p in skaters) < 9:
            raise ValueError(f"{team}: insufficient identified forward pool for projected lines")
        if sum(p.position == "D" for p in skaters) < 4:
            raise ValueError(f"{team}: insufficient identified defense pool for projected pairs")
        goalies = [p for p in players.values() if p.position == "G"]
        if not goalies:
            raise ValueError(f"{team}: no goalie in the frozen roster snapshot")
        goalie_ids = [p.nhl_id for p in goalies]
        goalie_weights = [max(0.5, p.games_started) for p in goalies]
        forwards = sorted([p for p in skaters if p.position in {"C", "L", "R", "LW", "RW", "F"}], key=lambda p: -p.usage_minutes)[:12]
        defense = sorted([p for p in skaters if p.position == "D"], key=lambda p: -p.usage_minutes)[:6]
        expected_sog = sum(p.shots / max(1.0, p.games_played) for p in forwards + defense)
        expected_sog = min(42.0, max(20.0, expected_sog))
        weighted_goalie_starts=sum(max(0.5,p.games_started) for p in goalies)
        supported_goalies=[p for p in goalies if p.games_started>0 and p.shots_against>0]
        if supported_goalies:
            goalie_weight=sum(p.games_started for p in supported_goalies)
            expected_sog_against=sum(p.games_started*(p.shots_against/p.games_started)
                                     for p in supported_goalies)/goalie_weight
        else:
            expected_sog_against=30.0
        expected_sog_against=min(42.0,max(20.0,expected_sog_against))
        p_hash_payload = [
            [p.nhl_id,p.name,p.position,round(p.usage_minutes,4),round(p.shots,4),round(p.goals,4),round(p.save_pct,6)]
            for p in sorted(players.values(), key=lambda x: x.nhl_id)
        ]
        profile_hash = hashlib.sha256(json.dumps(p_hash_payload,separators=(",",":"),sort_keys=True).encode()).hexdigest()
        return TeamRoster(
            team=team, players=players, expected_sog=expected_sog,
            expected_sog_against=expected_sog_against, goalie_ids=goalie_ids,
            goalie_weights=goalie_weights, profile_hash=profile_hash,
            coverage={"snapshot_id": sid, "snapshot_captured_at_utc":snapshot["captured_at"],
                      "snapshot_checksum":snapshot["source_checksum"], "active_players": len(players), "with_prior_stats": sum(not p.stats_missing for p in players.values()),
                      "goalies": len(goalies), "pregame_log_rows_league": len(log_rows),
                      "pregame_log_max_date": max(log_dates) if log_dates else None,
                      "position_groups": dict(collections.Counter(p.position for p in players.values()))},
        )
    finally:
        con.close()


def _nhl_db_season_key(game_date: str) -> int:
    date = dt.date.fromisoformat(game_date)
    return date.year + 1 if date.month >= 9 else date.year


def load_team_game_sog_rates(db_path: Path, teams: tuple[str, str], game_date: str,
                             cutoff: dt.datetime) -> dict[str, Any]:
    """Read paired, cutoff-valid team SOG histories using the DB's native game IDs."""
    if not db_path.is_file():
        raise FileNotFoundError(f"read-only team-stat database not found: {db_path}")
    target_season_key = _nhl_db_season_key(game_date)
    eligible_seasons = [target_season_key - 1, target_season_key]
    uri = f"file:{db_path}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in teams)
        rows = con.execute(
            "SELECT r.game_id,r.game_date,r.season,r.team,r.opponent,r.ingested_at, "
            "s.shots AS shots_for,s.captured_at AS stats_captured_at, "
            "COALESCE(s.source,r.source,c.source) AS stats_source, "
            "ro.ingested_at AS opponent_ingested_at,so.shots AS shots_against, "
            "so.captured_at AS opponent_stats_captured_at, "
            "COALESCE(so.source,ro.source,co.source) AS opponent_stats_source "
            "FROM team_game_results r "
            "JOIN team_game_stats s ON s.league=r.league AND s.game_id=r.game_id "
            "AND s.team_abbrev=r.team "
            "JOIN team_game_results ro ON ro.league=r.league AND ro.game_id=r.game_id "
            "AND ro.team=r.opponent AND ro.opponent=r.team AND ro.season=r.season "
            "AND ro.game_date=r.game_date AND ro.status='completed' "
            "JOIN team_game_stats so ON so.league=ro.league AND so.game_id=ro.game_id "
            "AND so.team_abbrev=ro.team "
            "LEFT JOIN team_stats_coverage c ON c.league=r.league AND c.season=r.season "
            "LEFT JOIN team_stats_coverage co ON co.league=ro.league AND co.season=ro.season "
            f"WHERE r.league='nhl' AND r.team IN ({placeholders}) "
            "AND r.status='completed' AND r.season IN (?,?) AND r.game_date<? "
            "AND julianday(r.ingested_at)<julianday(?) "
            "AND julianday(ro.ingested_at)<julianday(?) "
            "AND julianday(s.captured_at)<julianday(?) "
            "AND julianday(so.captured_at)<julianday(?) "
            "AND s.shots IS NOT NULL AND so.shots IS NOT NULL "
            "ORDER BY r.season,r.game_date,r.game_id,r.team",
            (*teams, *eligible_seasons, game_date,
             cutoff.isoformat(), cutoff.isoformat(), cutoff.isoformat(), cutoff.isoformat()),
        ).fetchall()

        accepted_sources = {
            "nhle.com:gamecenter/right-rail+landing",
            "espn_site_api:scoreboard+summary",
            "reconcile_totals+espn_core_api",
        }
        by_team: dict[str, list[dict[str, Any]]] = {team: [] for team in teams}
        source_quarantine: collections.Counter[str] = collections.Counter()
        seen: set[tuple[str, str]] = set()
        for raw in rows:
            row = dict(raw)
            source = str(row["stats_source"] or "unknown")
            opponent_source = str(row["opponent_stats_source"] or "unknown")
            key = (str(row["game_id"]), str(row["team"]))
            if key in seen:
                raise ValueError(f"duplicate team-game SOG row for {key}")
            seen.add(key)
            if source not in accepted_sources or opponent_source not in accepted_sources:
                source_quarantine[source + " / " + opponent_source] += 1
                continue
            if source != opponent_source:
                source_quarantine[source + " / " + opponent_source] += 1
                continue
            shots_for = float(row["shots_for"])
            shots_against = float(row["shots_against"])
            if not all(math.isfinite(value) and value >= 0 for value in (shots_for, shots_against)):
                raise ValueError(f"{key}: invalid team SOG values {shots_for}, {shots_against}")
            row["stats_source"] = source
            row["shots_for"] = shots_for
            row["shots_against"] = shots_against
            by_team[str(row["team"])].append(row)

        team_rates: dict[str, dict[str, Any]] = {}
        hash_rows: list[list[Any]] = []
        for team in teams:
            values = by_team[team]
            if not values:
                raise ValueError(
                    f"{team}: no paired, source-eligible team SOG records before "
                    f"{game_date} and {cutoff.isoformat()}"
                )
            season_counts = collections.Counter(int(row["season"]) for row in values)
            source_counts = collections.Counter(str(row["stats_source"]) for row in values)
            team_rates[team] = {
                "team": team,
                "games": len(values),
                "shots_for_per_game": statistics.fmean(row["shots_for"] for row in values),
                "shots_against_per_game": statistics.fmean(row["shots_against"] for row in values),
                "games_by_nhl_db_season_key": dict(sorted(season_counts.items())),
                "source_counts": dict(sorted(source_counts.items())),
                "first_game_date": min(str(row["game_date"]) for row in values),
                "last_game_date": max(str(row["game_date"]) for row in values),
                "latest_stat_capture_utc": max(str(row["stats_captured_at"]) for row in values),
            }
            hash_rows.extend([
                row["game_id"], row["game_date"], row["season"], row["team"], row["opponent"],
                row["shots_for"], row["shots_against"], row["stats_captured_at"], row["stats_source"],
            ] for row in values)
        hash_rows.sort(key=lambda row: (row[2], row[1], row[0], row[3]))
        digest = hashlib.sha256(
            json.dumps(hash_rows, separators=(",", ":"), sort_keys=False).encode()
        ).hexdigest()
        return {
            "schema": "NHLTeamGameSogRate-v1",
            "database_path": str(db_path),
            "target_date": game_date,
            "target_nhl_db_season_key": target_season_key,
            "eligible_season_keys": eligible_seasons,
            "cutoff_utc": cutoff.isoformat().replace("+00:00", "Z"),
            "filters": {
                "game_date_strictly_before_target": True,
                "completed_only": True,
                "result_ingest_and_both_stat_captures_strictly_before_cutoff": True,
                "reciprocal_teams_on_same_native_game_id": True,
                "same_day_target_excluded": True,
            },
            "matchup_formula": "mean(attacking_team_shots_for_rate, defending_team_shots_against_rate)",
            "team_rates": team_rates,
            "selected_team_game_rows_sha256": digest,
            "quarantined_source_pairs": dict(sorted(source_quarantine.items())),
        }
    finally:
        con.close()


def _aware_utc(value: str, field_name: str) -> dt.datetime:
    parsed=dt.datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    return parsed.astimezone(dt.timezone.utc)


def load_b3_team_means(home: str, away: str, game_date: str, as_of_utc: str,
                       neutral_site: bool = False) -> tuple[float,float,dict[str,Any]]:
    if not FORECASTS.is_file() or not FROZEN_MODELS.is_file():
        raise FileNotFoundError("frozen NHL B3 model and prospective feature ledger are required")
    model = json.loads(FROZEN_MODELS.read_text())
    cutoff=_aware_utc(as_of_utc,"pregame cutoff")
    rows = []
    with FORECASTS.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row.get("model_name") != "B3_elo" or str(row.get("game_date", "")) >= game_date:
                continue
            generated_at=row.get("forecasted_at_utc")
            feature_asof=(row.get("feature_snapshot") or {}).get("as_of_utc")
            if not generated_at or not feature_asof:
                raise ValueError("B3 forecast row is missing its generation or feature as-of timestamp")
            if _aware_utc(generated_at,"B3 forecasted_at_utc")>=cutoff:
                continue
            if _aware_utc(feature_asof,"B3 feature_snapshot.as_of_utc")>=cutoff:
                continue
            rows.append(row)
    ratings: dict[str, tuple[str,float,str]] = {}
    for row in sorted(rows, key=lambda x: (x.get("game_date",""),x.get("forecasted_at_utc",""))):
        snap = row.get("feature_snapshot") or {}
        elo = snap.get("elo_pre_game") or {}
        for side,team in (("home",row.get("home_team")),("away",row.get("away_team"))):
            value = elo.get(side)
            if team and value is not None:
                ratings[str(team)] = (str(row.get("game_date")),float(value),str(row.get("forecasted_at_utc")))
    if home not in ratings or away not in ratings:
        raise ValueError(f"no pregame B3 Elo snapshot for matchup {away}@{home} before {game_date}")
    h_date,h_elo,h_asof=ratings[home]
    a_date,a_elo,a_asof=ratings[away]
    params = model["poisson_models"]["elo"]
    coef=params["coef"]
    diff=(h_elo-a_elo)/400.0
    home_venue=0.0 if neutral_site else 1.0
    mu_home=math.exp(float(params["intercept"])+float(coef[0])*home_venue+float(coef[1])*diff)
    mu_away=math.exp(float(params["intercept"])+float(coef[1])*(-diff))
    info={"model_version":model.get("model_version"),"artifact_file_sha256":sha256_file(FROZEN_MODELS),
          "embedded_model_sha256":model.get("model_sha256"),"feature_ledger_sha256":sha256_file(FORECASTS),
          "home_elo":{"date":h_date,"rating":h_elo,"as_of_utc":h_asof},
          "away_elo":{"date":a_date,"rating":a_elo,"as_of_utc":a_asof},
          "home_venue_indicator":home_venue,"means_target":"regulation-plus-overtime team goals, excluding shootout deciding goal"}
    return mu_home,mu_away,info


def prepare_pregame(db_path: Path, *, game_key: str, game_date: str, start_utc: str,
                    as_of_utc: str, home: str, away: str, neutral_site: bool=False) -> PregameInputs:
    cutoff=dt.datetime.fromisoformat(as_of_utc.replace("Z","+00:00"))
    start=dt.datetime.fromisoformat(start_utc.replace("Z","+00:00"))
    if cutoff.tzinfo is None or start.tzinfo is None or cutoff>=start:
        raise ValueError("pregame cutoff must be timezone-aware and strictly before scheduled puck drop")
    home_roster=load_roster(db_path,home,game_date,cutoff)
    away_roster=load_roster(db_path,away,game_date,cutoff)
    team_sog_model=load_team_game_sog_rates(db_path,(home,away),game_date,cutoff)
    mu_home,mu_away,team_model=load_b3_team_means(home,away,game_date,as_of_utc,neutral_site)
    home_sog=team_sog_model["team_rates"][home]
    away_sog=team_sog_model["team_rates"][away]
    shot_home=statistics.fmean((home_sog["shots_for_per_game"],away_sog["shots_against_per_game"]))
    shot_away=statistics.fmean((away_sog["shots_for_per_game"],home_sog["shots_against_per_game"]))
    log_max_date=max(home_roster.coverage["pregame_log_max_date"] or "",
                     away_roster.coverage["pregame_log_max_date"] or "") or None
    snapshot={"schema":"PregameGameSnapshot-v0.2b","game_key":game_key,"game_date":game_date,
        "scheduled_start_utc":start.isoformat().replace("+00:00","Z"),"capture_cutoff_utc":cutoff.isoformat().replace("+00:00","Z"),
        "home_team":home,"away_team":away,"neutral_site":neutral_site,
        "roster_snapshot_id":home_roster.coverage["snapshot_id"],"roster_snapshot_source":"nhle.com:roster",
        "roster_snapshot_capture_utc":home_roster.coverage["snapshot_captured_at_utc"],
        "roster_snapshot_checksum":home_roster.coverage["snapshot_checksum"],
        "prior_player_stats_season":2026,"current_season_player_logs_used_through":log_max_date,
        "home_roster_hash":home_roster.profile_hash,"away_roster_hash":away_roster.profile_hash,
        "home_roster_coverage":home_roster.coverage,"away_roster_coverage":away_roster.coverage,
        "team_model":team_model,"team_expected_goals":{"home":mu_home,"away":mu_away},
        "team_sog_model":team_sog_model,
        "team_expected_sog":{"home":shot_home,"away":shot_away},
        "team_sog_player_rate_diagnostic":{"home":{"player_rate_sog":home_roster.expected_sog,
            "goalie_rate_sog_against":home_roster.expected_sog_against},
            "away":{"player_rate_sog":away_roster.expected_sog,
            "goalie_rate_sog_against":away_roster.expected_sog_against}},
        "starting_goalie_status":"uncertain; sampled from active-roster prior-season starts; no confirmed starter input",
        "actual_target_game_stats_or_lineups_used":False}
    return PregameInputs(game_key,game_date,start_utc,as_of_utc,home,away,home_roster,away_roster,
                         mu_home,mu_away,team_model,snapshot)


def _distance_bin(event: dict[str,Any], side: str, home_team_id: str) -> str:
    details=event.get("details") or {}
    x,y=details.get("xCoord"),details.get("yCoord")
    defending=event.get("homeTeamDefendingSide")
    if not isinstance(x,(int,float)) or not isinstance(y,(int,float)) or defending not in {"left","right"}:
        return "unknown"
    if side=="home":
        goal_x=-89 if defending=="right" else 89
    else:
        goal_x=89 if defending=="right" else -89
    distance=math.sqrt((float(x)-goal_x)**2+float(y)**2)
    if distance<15: return "0_15"
    if distance<30: return "15_30"
    if distance<50: return "30_50"
    return "50_plus"


@dataclass
class ShotQualityModel:
    global_goal_rate: float
    bin_probabilities: dict[tuple[str,str],float]
    bin_counts: dict[tuple[str,str],dict[str,int]]
    empty_net_rate: float
    regulation_goal_share: float
    fivevfive_goal_share: float
    fivevfive_sog_share: float
    assist_count_probabilities: dict[int,float]
    attempt_result_probabilities: dict[str,float]
    shootout_goal_rate: float
    shootout_first_home_probability: float
    games_used: int
    events_used: int

    def probability(self, raw_event: dict[str,Any], side: str, home_team_id: str) -> float:
        details=raw_event.get("details") or {}
        shot_type=str(details.get("shotType") or "unknown").lower()
        dbin=_distance_bin(raw_event,side,home_team_id)
        return self.bin_probabilities.get((shot_type,dbin),
               self.bin_probabilities.get(("unknown",dbin),self.global_goal_rate))


def fit_shot_quality(corpus: Any) -> ShotQualityModel:
    counts: dict[tuple[str,str],collections.Counter[str]]=collections.defaultdict(collections.Counter)
    global_counts=collections.Counter()
    open_counts=collections.Counter()
    reg_goals=0
    total_ro_goals=0
    fivevfive_goals=0
    fivevfive_sog=0
    all_ro_sog=0
    assists=collections.Counter()
    attempt_results=collections.Counter()
    shootout_attempts=0
    shootout_goals=0
    shootout_first_home=0
    shootout_order_games=0
    used_games=0
    events_used=0
    raw_dir=corpus.data_root/"raw"/"pbp"
    for game in corpus.games.values():
        if not v01._eligible_game(game):
            continue
        doc=v01._read_verified_source_game(game,raw_dir)
        sides=v01._source_side_map(doc)
        home_id=str(doc["homeTeam"]["id"])
        first_shootout_side=None
        for event in doc.get("plays",[]):
            et=event.get("typeDescKey")
            pdesc=event.get("periodDescriptor") or {}
            if pdesc.get("periodType")=="SO" and et in ATTEMPT_EVENTS:
                shootout_attempts+=1
                shootout_goals+=int(et=="goal")
                if first_shootout_side is None:
                    details=event.get("details") or {}
                    first_shootout_side=sides.get(str(details.get("eventOwnerTeamId")))
                continue
            if et in ATTEMPT_EVENTS:
                if et in {"goal","shot-on-goal"}:
                    attempt_results["on_target"]+=1
                elif et=="missed-shot":
                    attempt_results["missed"]+=1
                elif et=="blocked-shot":
                    attempt_results["blocked"]+=1
            if et not in SHOT_EVENTS:
                continue
            details=event.get("details") or {}
            owner=sides.get(str(details.get("eventOwnerTeamId")))
            if owner not in {"home","away"}:
                continue
            shot_type=str(details.get("shotType") or "unknown").lower()
            key=(shot_type,_distance_bin(event,owner,home_id))
            goal=int(et=="goal")
            if goal:
                assists[min(2,sum(details.get(k) is not None for k in ("assist1PlayerId","assist2PlayerId")))]+=1
            counts[key]["shots"]+=1
            counts[key]["goals"]+=goal
            global_counts["shots"]+=1
            global_counts["goals"]+=goal
            if not details.get("goalieInNetId"):
                open_counts["shots"]+=1
                open_counts["goals"]+=goal
            events_used+=1
            code=str(event.get("situationCode") or "")
            if len(code)==4 and code.isdigit() and int(code[1])==5 and int(code[2])==5 and code[0]=="1" and code[3]=="1":
                fivevfive_sog+=1
                fivevfive_goals+=goal
            all_ro_sog+=1
        if first_shootout_side in {"home","away"}:
            shootout_order_games+=1
            shootout_first_home+=int(first_shootout_side=="home")
        for number in (1,2,3):
            period=game.periods.get(("REG",number))
            if period:
                reg_goals += sum(period.goals.values())
        total_ro_goals += sum(game.regulation_ot_goals.values())
        used_games+=1
    if global_counts["shots"]==0:
        raise ValueError("no training shot-on-goal outcomes for conversion model")
    global_p=global_counts["goals"]/global_counts["shots"]
    shrink=60.0
    probs={}
    normalized_counts={}
    for key,c in counts.items():
        probs[key]=(c["goals"]+shrink*global_p)/(c["shots"]+shrink)
        normalized_counts[key]={"shots":int(c["shots"]),"goals":int(c["goals"])}
    open_p=(open_counts["goals"]+30*global_p)/(open_counts["shots"]+30) if open_counts["shots"] else min(.35,global_p*2)
    reg_share=min(.99,max(.90,reg_goals/max(1,total_ro_goals)))
    fivevfive_share=min(.9,max(.5,fivevfive_goals/max(1,total_ro_goals)))
    fivevfive_sog_share=min(.99,max(.5,fivevfive_sog/max(1,all_ro_sog)))
    total_assists=max(1,sum(assists.values()))
    assist_probs={n:assists[n]/total_assists for n in range(3)}
    total_attempts=max(1,sum(attempt_results.values()))
    attempt_probs={k:attempt_results[k]/total_attempts for k in ("on_target","missed","blocked")}
    so_rate=(shootout_goals+20*global_p)/(shootout_attempts+20) if shootout_attempts else .32
    so_first_home=(shootout_first_home+5.0)/(shootout_order_games+10.0)
    return ShotQualityModel(global_p,probs,normalized_counts,open_p,reg_share,fivevfive_share,
                            fivevfive_sog_share,assist_probs,attempt_probs,so_rate,so_first_home,
                            used_games,events_used)


def _poisson_log_likelihood(observed: int, mean: float) -> float:
    mean=max(.1,mean)
    return observed*math.log(mean)-mean-math.lgamma(observed+1)


def choose_weighted_period(rng: random.Random, refs: list[tuple[Any,Any]], used: set[str],
                           target_home_sog: float,target_away_sog: float,period_number: int) -> tuple[Any,Any]:
    available=[pair for pair in refs if pair[0].game_id not in used]
    if not available:
        raise ValueError(f"no unused donor period for REG {period_number}")
    per_home=max(1.0,target_home_sog/3)
    per_away=max(1.0,target_away_sog/3)
    logs=[]
    for game,period in available:
        oh=int(period.sog_events.get("home",0)); oa=int(period.sog_events.get("away",0))
        logs.append(_poisson_log_likelihood(oh,per_home)+_poisson_log_likelihood(oa,per_away))
    # Temper the likelihood so shot volume conditions sampling without collapsing onto one template.
    peak=max(logs)
    weights=[math.exp(max(-30.0,(v-peak)*0.35)) for v in logs]
    selected=rng.choices(available,weights=weights,k=1)[0]
    return selected


def _choose_weighted(rng: random.Random, players: list[Player], weights: list[float]) -> Player:
    if not players:
        raise ValueError("player selection has no eligible player")
    return rng.choices(players,weights=[max(.001,w) for w in weights],k=1)[0]


def _position_group(position: str) -> str:
    if position in {"C","L","R","LW","RW","F"}:
        return "F"
    if position=="D":
        return "D"
    if position=="G":
        return "G"
    return "?"


@dataclass
class DonorPeriod:
    game: Any
    period_type: str
    period_number: int
    pbp: dict[str,Any]
    shifts: dict[str,Any]
    source_side_by_team_id: dict[str,str]
    id_to_position: dict[str,str]
    id_to_side: dict[str,str]
    player_map: dict[str,str]
    source_shift_sha256: str
    shift_ledger: list[dict[str,Any]] = field(default_factory=list)
    shift_rows_quarantined: int = 0
    terminal_elapsed: int|None = None
    shift_intervals: dict[int,tuple[int,int]|None] = field(default_factory=dict)

    def active(self, elapsed: int) -> dict[str,list[str]]:
        state={"home":[],"away":[]}
        for row in self.shifts["data"]:
            if int(row.get("period",0))!=self.period_number:
                continue
            interval=self.shift_intervals.get(id(row))
            if interval is None:
                continue
            pid=str(row.get("playerId") or "")
            side=self.source_side_by_team_id.get(str(row.get("teamId")))
            pos=self.id_to_position.get(pid)
            mapped=self.player_map.get(pid)
            if side not in state or pos is None or mapped is None:
                continue
            start,end=interval
            if start<=elapsed<end:
                state[side].append(mapped)
        for side in state:
            state[side]=sorted(set(state[side]))
        return state


def prepare_donor_period(game: Any, period_type: str, period_number: int,
                         data_root: Path, shift_manifest: dict[str,dict[str,str]],
                         inputs: PregameInputs, selected_goalies: dict[str,list[str]]) -> DonorPeriod:
    pbp=read_verified_pbp_game(game,data_root/"raw"/"pbp")
    shifts=read_verified_shift_game(game.game_id,shift_manifest)
    source_period_events=v01._source_period_events(pbp,period_type,period_number)
    terminal_elapsed=None
    if period_type=="OT":
        goal_times=[parse_clock(str(event.get("timeInPeriod"))) for event in source_period_events
                    if event.get("typeDescKey")=="goal"]
        if goal_times:
            terminal_elapsed=min(goal_times)
    side_by_team=v01._source_side_map(pbp)
    id_to_position={str(row.get("playerId")):str(row.get("positionCode") or "?")
                    for row in pbp.get("rosterSpots",[]) if row.get("playerId") is not None}
    id_to_side={str(row.get("playerId")):side_by_team.get(str(row.get("teamId")))
                for row in pbp.get("rosterSpots",[]) if row.get("playerId") is not None}
    totals: dict[str,float]=collections.defaultdict(float)
    shift_intervals: dict[int,tuple[int,int]|None]={}
    ledger_intervals: dict[int,tuple[int,int]|None]={}
    quarantined=0
    for row in shifts["data"]:
        if int(row.get("period",0))!=period_number:
            continue
        # Rows beginning after an OT winner are outside the simulated game; they
        # cannot invalidate or extend the played-period shift ledger.
        start_raw=row.get("startTime")
        if terminal_elapsed is not None and start_raw not in (None,""):
            try:
                if parse_clock(str(start_raw))>=terminal_elapsed:
                    shift_intervals[id(row)]=None
                    ledger_intervals[id(row)]=None
                    continue
            except ValueError:
                pass
        interval=_shift_interval(row,game.game_id)
        shift_intervals[id(row)]=interval
        quarantined+=int(interval is None)
        ledger_interval=interval
        if interval is not None and terminal_elapsed is not None and interval[1]>terminal_elapsed:
            ledger_interval=(interval[0],terminal_elapsed)
        ledger_intervals[id(row)]=ledger_interval
    for row in shifts["data"]:
        if int(row.get("period",0))!=period_number:
            continue
        interval=ledger_intervals[id(row)]
        if interval is None:
            continue
        pid=str(row.get("playerId") or "")
        if pid not in id_to_position:
            # Zero-duration event annotations are not lineup shifts; positive unknowns are a hard data gap.
            raise DonorDataError("shift_identity_unresolved",
                f"{game.game_id}: shift player {pid} lacks same-game NHL position identity")
        start,end=interval
        totals[pid]+=end-start
    player_map: dict[str,str]={}
    target_rosters={"home":inputs.home_roster,"away":inputs.away_roster}
    shift_totals_by_side: dict[str,dict[str,float]]=collections.defaultdict(lambda:collections.defaultdict(float))
    for row in shifts["data"]:
        if int(row.get("period",0))!=period_number:
            continue
        pid=str(row.get("playerId") or "")
        if id_to_position.get(pid)!="G":
            continue
        interval=ledger_intervals[id(row)]
        if interval is None:
            continue
        side=id_to_side.get(pid)
        start,end=interval
        if side in {"home","away"} and end>start:
            shift_totals_by_side[side][pid]+=end-start
    for side in ("home","away"):
        for group in ("F","D"):
            source_ids=[pid for pid,src_side in id_to_side.items()
                        if src_side==side and _position_group(id_to_position.get(pid,"?"))==group and totals.get(pid,0)>0]
            source_ids.sort(key=lambda pid:(-totals[pid],pid))
            target_players=target_rosters[side].role_players(group)
            if len(target_players)<len(source_ids):
                raise DonorDataError("target_role_capacity",
                    f"{game.game_id} {side}: target {group} pool {len(target_players)} < donor shift identities {len(source_ids)}")
            for source_id,target_player in zip(source_ids,target_players):
                player_map[source_id]=target_player.nhl_id
        source_goalies=[pid for pid,src_side in id_to_side.items()
                        if src_side==side and id_to_position.get(pid)=="G" and
                        shift_totals_by_side[side].get(pid,0)>0]
        if not source_goalies:
            raise DonorDataError("donor_goalie_missing",f"{game.game_id}: no source goalie identity for {side}")
        source_goalies.sort(key=lambda pid:(-shift_totals_by_side[side].get(pid,0),pid))
        target_goalies=selected_goalies[side]
        if not target_goalies:
            raise DonorDataError("pregame_goalie_plan_empty",f"{game.game_id} {side}: sampled goalie plan is empty")
        for idx,source_id in enumerate(source_goalies):
            player_map[source_id]=target_goalies[min(idx,len(target_goalies)-1)]
    ledger=[]
    for row in shifts["data"]:
        if int(row.get("period",0))!=period_number:
            continue
        interval=ledger_intervals[id(row)]
        if interval is None:
            continue
        pid=str(row.get("playerId") or "")
        target=player_map.get(pid)
        side=side_by_team.get(str(row.get("teamId")))
        if target is None or side is None:
            continue
        start,end=interval
        ledger.append({"team_side":side,"player_id":target,"position":target_rosters[side].players[target].position,
                       "period_number":period_number,"start_seconds":start,"end_seconds":end,
                       "duration_seconds":end-start,"source":"remapped_verified_donor_shift"})
    if not ledger:
        raise DonorDataError("period_shift_ledger_empty",
            f"{game.game_id}: donor period {period_number} has no positive-duration shifts")
    shift_row=shift_manifest[game.game_id]
    return DonorPeriod(game,period_type,period_number,pbp,shifts,side_by_team,id_to_position,id_to_side,
                       player_map,shift_row["sha256_gz"],ledger,quarantined,
                       terminal_elapsed=terminal_elapsed,shift_intervals=shift_intervals)


def _lineup_strength(active: dict[str,list[str]], rosters: dict[str,TeamRoster]) -> tuple[str,dict[str,bool]]:
    counts={}
    goalie_present={}
    for side in ("home","away"):
        players=[rosters[side].players[x] for x in active[side] if x in rosters[side].players]
        counts[side]=sum(p.position!="G" for p in players)
        goalie_present[side]=any(p.position=="G" for p in players)
    label=f"{counts['home']}v{counts['away']}"
    return label,goalie_present


def _choose_shooter(rng: random.Random, roster: TeamRoster, active_ids: list[str]) -> Player:
    players=[roster.players[x] for x in active_ids if x in roster.players and roster.players[x].position!="G"]
    if not players:
        raise DonorDataError("active_shooter_pool_empty", "donor shot has no eligible simulated skater on ice")
    return _choose_weighted(rng,players,[max(.01,p.shot_rate) for p in players])


def _distance_and_type(raw_event: dict[str,Any], side: str, home_team_id: str) -> tuple[str,str,float|None]:
    details=raw_event.get("details") or {}
    stype=str(details.get("shotType") or "unknown").lower()
    dbin=_distance_bin(raw_event,side,home_team_id)
    x,y=details.get("xCoord"),details.get("yCoord")
    distance=None
    if isinstance(x,(int,float)) and isinstance(y,(int,float)) and dbin!="unknown":
        defending=raw_event.get("homeTeamDefendingSide")
        goal_x=(-89 if defending=="right" else 89) if side=="home" else (89 if defending=="right" else -89)
        distance=math.sqrt((float(x)-goal_x)**2+float(y)**2)
    return stype,dbin,distance


def _normalized_shot_location(raw_event: dict[str,Any], side: str) -> dict[str,Any]|None:
    details=raw_event.get("details") or {}
    x,y=details.get("xCoord"),details.get("yCoord")
    defending=raw_event.get("homeTeamDefendingSide")
    if not isinstance(x,(int,float)) or not isinstance(y,(int,float)) or defending not in {"left","right"}:
        return None
    goal_x=(-89 if defending=="right" else 89) if side=="home" else (89 if defending=="right" else -89)
    if goal_x<0:
        x,y=-float(x),-float(y)
    return {"x":int(x),"y":int(y),"coordinate_units":"NHL GameCenter rink coordinates",
            "transform":"rotated so this simulated attacking team attacks toward +x",
            "provenance":"sampled verified training donor; not target-game data"}


def _event_quality(raw_event: dict[str,Any], side: str, donor: DonorPeriod,
                   model: ShotQualityModel) -> float:
    details=raw_event.get("details") or {}
    if not details.get("goalieInNetId"):
        return model.empty_net_rate
    stype,dbin,_=_distance_and_type(raw_event,side,str(donor.pbp["homeTeam"]["id"]))
    return model.bin_probabilities.get((stype,dbin),
           model.bin_probabilities.get(("unknown",dbin),model.global_goal_rate))


def _supported_penalty(raw_details: dict[str,Any], game_id: str) -> tuple[str,int]:
    """Return a supported source penalty kind and clock seconds; fail closed otherwise."""
    raw_kind=str(raw_details.get("typeCode") or "").upper()
    try:
        duration_minutes=int(raw_details.get("duration"))
    except (TypeError,ValueError) as exc:
        raise DonorDataError("penalty_duration_missing",
            f"{game_id}: penalty has no integer source duration") from exc
    inferred={2:"MIN",4:"MIN",5:"MAJ",10:"MIS"}.get(duration_minutes)
    kind=raw_kind if raw_kind in {"MIN","MAJ","MIS"} else inferred
    if kind is None or (kind=="MIN" and duration_minutes not in {2,4}) or \
            (kind=="MAJ" and duration_minutes!=5) or (kind=="MIS" and duration_minutes!=10):
        raise DonorDataError("penalty_type_unsupported",
            f"{game_id}: unsupported penalty type/duration {raw_kind!r}/{duration_minutes} minutes")
    return kind,duration_minutes*60


def _transition_family(event_type: str) -> str | None:
    if event_type in BOUNDARY_EVENTS or event_type in {"shootout-complete","shootout-attempt"}:
        return None
    if event_type in ATTEMPT_EVENTS or event_type=="failed-shot-attempt":
        return "shot"
    if event_type in {"faceoff","giveaway","takeaway","penalty","hit"}:
        return event_type
    return "stoppage"


def _score_state_bucket(score: dict[str,int]) -> str:
    if score["home"]==score["away"]:
        return "TIED"
    return "HOME_LEADS" if score["home"]>score["away"] else "AWAY_LEADS"


def _strength_state_bucket(strength: str, possession: str|None) -> str:
    try:
        home,away=(int(value) for value in strength.split("v",1))
    except (ValueError,AttributeError):
        return "UNKNOWN"
    if home==away:
        return "EVEN"
    if possession not in {"home","away"}:
        return "SPECIAL"
    possessors=home if possession=="home" else away
    opponents=away if possession=="home" else home
    return "PP" if possessors>opponents else "PK"


def _transition_context(previous_family: str, possession: str|None,
                        strength: str, score: dict[str,int]) -> tuple[str,str,str,str]:
    return (previous_family,"KNOWN" if possession in {"home","away"} else "UNKNOWN",
            _strength_state_bucket(strength,possession),_score_state_bucket(score))


def _code_strength_bucket(situation_code: Any, possession: str|None) -> str:
    code=str(situation_code or "")
    if len(code)!=4 or not code.isdigit():
        return "UNKNOWN"
    away_skaters=int(code[1]); home_skaters=int(code[2])
    if home_skaters==away_skaters:
        return "EVEN"
    if possession not in {"home","away"}:
        return "SPECIAL"
    own=home_skaters if possession=="home" else away_skaters
    other=away_skaters if possession=="home" else home_skaters
    return "PP" if own>other else "PK"


@dataclass
class EventTransitionModel:
    exact: dict[str,collections.Counter[str]]
    previous_possession: dict[str,collections.Counter[str]]
    previous: dict[str,collections.Counter[str]]
    global_families: collections.Counter[str]
    owner_exact: dict[str,collections.Counter[str]]
    owner_family: dict[str,collections.Counter[str]]
    penalty_types: collections.Counter[str]
    eligible_games: int
    training_events: int
    source_manifest_sha256: str
    model_sha256: str

    @staticmethod
    def context_key(context: tuple[str,str,str,str]) -> str:
        return "|".join(context)

    def sample_family(self, context: tuple[str,str,str,str],
                      rng: random.Random) -> tuple[str,str,int]:
        exact_key=self.context_key(context)
        previous_key="|".join(context[:2])
        previous_family=context[0]
        for level,counts in (
            ("exact",self.exact.get(exact_key,collections.Counter())),
            ("previous_and_possession",self.previous_possession.get(previous_key,collections.Counter())),
            ("previous_family",self.previous.get(previous_family,collections.Counter())),
            ("global_training",self.global_families)):
            if counts and (level=="global_training" or sum(counts.values())>=25):
                families=sorted(counts)
                weights=[counts[family] for family in families]
                return rng.choices(families,weights=weights,k=1)[0],level,sum(weights)
        raise ValueError("transition model has no fitted event-family counts")

    def sample_owner(self, family: str, context: tuple[str,str,str,str],
                     possession: str|None, fallback_side: str|None,
                     rng: random.Random) -> tuple[str|None,str]:
        key=f"{self.context_key(context)}|{family}"
        known=possession in {"home","away"}
        counts=self.owner_exact.get(key,collections.Counter())
        level="exact"
        if not counts or sum(counts.values())<10:
            counts=self.owner_family.get(f"{family}|{'KNOWN' if known else 'UNKNOWN'}",collections.Counter())
            level="family"
        if not counts:
            return fallback_side,"source_side_fallback"
        relations=sorted(counts)
        relation=rng.choices(relations,weights=[counts[x] for x in relations],k=1)[0]
        if known:
            if relation=="same":
                return possession,level
            if relation=="opposite":
                return ("away" if possession=="home" else "home"),level
        if relation in {"home","away"}:
            return relation,level
        return fallback_side,"source_side_fallback"

    def sample_penalty(self, rng: random.Random) -> tuple[str,int]:
        if not self.penalty_types:
            return "MIN",120
        values=sorted(self.penalty_types)
        selected=rng.choices(values,weights=[self.penalty_types[v] for v in values],k=1)[0]
        kind,duration=selected.split("|",1)
        return kind,int(duration)

    def manifest(self) -> dict[str,Any]:
        return {"model":"event-family-markov-v0.2b","training_start_seasons":[2019,2020],
            "training_eligible_games":self.eligible_games,"training_transition_events":self.training_events,
            "source_pbp_manifest_sha256":self.source_manifest_sha256,
            "transition_counts_sha256":self.model_sha256,
            "clock_slots":"donor event clock and count scaffold retained"}


def fit_event_transition_model(corpus: Any) -> EventTransitionModel:
    """Fit state-conditioned event transitions from eligible 2019/2020 PBP only."""
    exact:dict[str,collections.Counter[str]]=collections.defaultdict(collections.Counter)
    previous_possession:dict[str,collections.Counter[str]]=collections.defaultdict(collections.Counter)
    previous:dict[str,collections.Counter[str]]=collections.defaultdict(collections.Counter)
    global_families:collections.Counter[str]=collections.Counter()
    owner_exact:dict[str,collections.Counter[str]]=collections.defaultdict(collections.Counter)
    owner_family:dict[str,collections.Counter[str]]=collections.defaultdict(collections.Counter)
    penalty_types:collections.Counter[str]=collections.Counter()
    eligible_games=training_events=0
    raw_dir=corpus.data_root/"raw"/"pbp"
    for game in sorted(corpus.games.values(),key=lambda item:item.game_id):
        if game.start_season not in v01.TRAIN_SEASONS or not v01._eligible_game(game):
            continue
        doc=v01._read_verified_source_game(game,raw_dir)
        sides=v01._source_side_map(doc)
        eligible_games+=1
        score={"home":0,"away":0}
        periods=[("REG",n) for n in (1,2,3)]
        if ("OT",4) in game.periods:
            periods.append(("OT",4))
        for period_type,period_number in periods:
            previous_family="start"
            possession=None
            for raw in v01._source_period_events(doc,period_type,period_number):
                raw_type=str(raw.get("typeDescKey") or "")
                family=_transition_family(raw_type)
                if family is None:
                    continue
                details=raw.get("details") or {}
                owner=sides.get(str(details.get("eventOwnerTeamId")))
                if family=="penalty":
                    try:
                        kind,duration=_supported_penalty(details,game.game_id)
                    except DonorDataError:
                        family="stoppage"
                    else:
                        penalty_types[f"{kind}|{duration}"]+=1
                context=(previous_family,"KNOWN" if possession in {"home","away"} else "UNKNOWN",
                         _code_strength_bucket(raw.get("situationCode"),possession),
                         _score_state_bucket(score))
                key=EventTransitionModel.context_key(context)
                exact[key][family]+=1
                previous_possession["|".join(context[:2])][family]+=1
                previous[previous_family][family]+=1
                global_families[family]+=1
                if owner in {"home","away"}:
                    relation=("same" if owner==possession else "opposite") if possession else owner
                    owner_exact[f"{key}|{family}"][relation]+=1
                    owner_family[f"{family}|{'KNOWN' if possession else 'UNKNOWN'}"][relation]+=1
                training_events+=1

                if raw_type=="goal" and owner in score:
                    score[owner]+=1
                if family=="faceoff":
                    possession=owner
                elif family=="giveaway" and owner in {"home","away"}:
                    possession="away" if owner=="home" else "home"
                elif family=="takeaway":
                    possession=owner
                elif family=="shot":
                    possession=None
                previous_family=family

    if not global_families:
        raise ValueError("no eligible training event transitions")
    payload={"source_manifest_sha256":corpus.manifest_sha256,
        "exact":{k:dict(sorted(v.items())) for k,v in sorted(exact.items())},
        "previous_possession":{k:dict(sorted(v.items())) for k,v in sorted(previous_possession.items())},
        "previous":{k:dict(sorted(v.items())) for k,v in sorted(previous.items())},
        "global":dict(sorted(global_families.items())),
        "owner_exact":{k:dict(sorted(v.items())) for k,v in sorted(owner_exact.items())},
        "owner_family":{k:dict(sorted(v.items())) for k,v in sorted(owner_family.items())},
        "penalty_types":dict(sorted(penalty_types.items()))}
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return EventTransitionModel(dict(exact),dict(previous_possession),dict(previous),global_families,
        dict(owner_exact),dict(owner_family),penalty_types,eligible_games,training_events,
        corpus.manifest_sha256,digest)


def _sample_transition_shot_quality(rng: random.Random,
                                    model: ShotQualityModel) -> dict[str,Any]:
    options=[(shot_type,distance_bin,int(values["shots"]))
             for (shot_type,distance_bin),values in model.bin_counts.items()
             if values.get("shots",0)>0]
    if not options:
        return {"shot_type":"unknown","distance_bin":"unknown",
                "provenance":"2019-2020 training population; fallback bin"}
    selected=rng.choices(options,weights=[row[2] for row in options],k=1)[0]
    return {"shot_type":selected[0],"distance_bin":selected[1],
            "provenance":"sampled from 2019-2020 training shot-quality bins"}


@dataclass
class SimPlay:
    raw: dict[str,Any]
    donor: DonorPeriod
    event_type: str
    team_side: str|None
    elapsed: int
    remaining: int
    active: dict[str,list[str]]
    strength: str
    goalie_present: dict[str,bool]
    details: dict[str,Any]
    participants: dict[str,Any]
    raw_goal_logit: float|None=None
    goalie_logit_delta: float=0.0
    sog_probability: float|None=None
    goal_probability: float|None=None


def _active_stats(active: dict[str,list[str]], rosters: dict[str,TeamRoster]) -> dict[str,dict[str,list[str]]]:
    result={}
    for side in ("home","away"):
        groups={"F":[],"D":[],"G":[]}
        for pid in active[side]:
            player=rosters[side].players.get(pid)
            if player is None:
                raise DonorDataError("target_roster_mapping",
                    f"active synthetic NHL ID {pid} is absent from frozen {side} roster")
            group=_position_group(player.position)
            if group in groups:
                groups[group].append(pid)
        result[side]=groups
    return result


def _live_on_ice(base_active: dict[str,list[str]], inputs: PregameInputs,
                 penalties: PenaltyLedger, period_type: str) -> tuple[dict[str,list[str]],str,dict[str,bool]]:
    """Reconcile donor shift candidates to the simulated penalty and goalie state."""
    rosters={"home":inputs.home_roster,"away":inputs.away_roster}
    goalie_pulled={side:not any(rosters[side].players[pid].position=="G"
                                for pid in base_active[side] if pid in rosters[side].players)
                   for side in ("home","away")}
    manpower=penalties.manpower(period_type,goalie_pulled=goalie_pulled)
    result={"home":[],"away":[]}
    for side in ("home","away"):
        roster=rosters[side]
        barred=penalties.penalized_players(side)
        base=[pid for pid in base_active[side] if pid in roster.players and pid not in barred]
        goalies=[pid for pid in base if roster.players[pid].position=="G"]
        skaters=[pid for pid in base if roster.players[pid].position!="G"]
        if goalie_pulled[side]:
            goalies=[]
        else:
            if not goalies:
                goalies=[pid for pid in roster.goalie_ids if pid not in barred][:1]
            else:
                goalies=goalies[:1]
            if not goalies:
                raise DonorDataError("live_goalie_unavailable",f"{side}: no eligible goalie in simulated state")
        target=manpower[side]
        if len(skaters)>target:
            skaters=sorted(skaters,key=lambda pid:(-roster.players[pid].usage_minutes,
                                                    -roster.players[pid].shots,pid))[:target]
        elif len(skaters)<target:
            available=[p.nhl_id for p in roster.role_players("F")+roster.role_players("D")
                       if p.nhl_id not in barred and p.nhl_id not in skaters]
            available.sort(key=lambda pid:(-roster.players[pid].usage_minutes,
                                           -roster.players[pid].shots,pid))
            needed=target-len(skaters)
            if len(available)<needed:
                raise DonorDataError("live_lineup_pool_short",
                    f"{side}: need {needed} replacement skaters, found {len(available)}")
            skaters.extend(available[:needed])
        result[side]=skaters+goalies
    strength=f"{manpower['home']}v{manpower['away']}"
    return result,strength,goalie_pulled


def _period_clock_from_absolute(absolute: int) -> tuple[int,int,str]:
    if absolute<=1200:
        return 1,absolute,"REG"
    if absolute<=2400:
        return 2,absolute-1200,"REG"
    if absolute<=3600:
        return 3,absolute-2400,"REG"
    if absolute<=3900:
        return 4,absolute-3600,"OT"
    raise ValueError(f"penalty expiry outside a supported game clock: {absolute}")


def _valid_active_lineup(groups: dict[str,dict[str,list[str]]]) -> bool:
    for side in ("home","away"):
        skaters=len(groups[side]["F"])+len(groups[side]["D"])
        goalies=len(groups[side]["G"])
        if skaters<3 or skaters>6 or goalies>1:
            return False
    return True


def prepare_source_period(donor: DonorPeriod, inputs: PregameInputs,
                          selected_goalies: dict[str,list[str]], model: ShotQualityModel,
                          rng: random.Random) -> list[SimPlay]:
    sides={"home":inputs.home_roster,"away":inputs.away_roster}
    home_team_id=str(donor.pbp["homeTeam"]["id"])
    plays=[]
    source_events=v01._source_period_events(donor.pbp,donor.period_type,donor.period_number)
    for raw in source_events:
        source_type=raw.get("typeDescKey")
        if source_type in BOUNDARY_EVENTS:
            continue
        clock=parse_clock(str(raw.get("timeInPeriod")))
        remaining=parse_clock(str(raw.get("timeRemaining")))
        raw_details=raw.get("details") or {}
        side=donor.source_side_by_team_id.get(str(raw_details.get("eventOwnerTeamId")))
        active=donor.active(clock)
        active_groups=_active_stats(active,sides)
        lineup_clock_adjustment=0
        if donor.period_type=="OT" and clock==donor.terminal_elapsed and not _valid_active_lineup(active_groups):
            # Shift charts can close every active interval at the same integer
            # second as the sudden-death goal. Use the immediately preceding
            # observed game-clock second for that terminal event only.
            active=donor.active(max(0,clock-1))
            active_groups=_active_stats(active,sides)
            if not _valid_active_lineup(active_groups):
                raise DonorDataError("on_ice_count_invalid",
                    f"{donor.game.game_id} P{donor.period_number} {clock}: no legal lineup at the OT terminal event or prior clock second")
            lineup_clock_adjustment=-1
        strength,goalie_present=_lineup_strength(active,sides)
        if not _valid_active_lineup(active_groups):
            raise DonorDataError("on_ice_count_invalid",
                f"{donor.game.game_id} P{donor.period_number} {clock}: implausible donor lineup")
        details=v01._safe_details(raw)
        if lineup_clock_adjustment:
            details["on_ice_interval_adjustment_seconds"]=lineup_clock_adjustment
        if raw.get("typeDescKey") in ATTEMPT_EVENTS:
            location=_normalized_shot_location(raw,side) if side in {"home","away"} and source_type!="blocked-shot" else None
            if location:
                details["shot_location"]=location
            stype,dbin,distance=_distance_and_type(raw,side or "home",home_team_id)
            details["shot_quality_bin"]={"shot_type":stype,"distance_bin":dbin,
                                          "distance_from_goal_numeric_gamecenter_units":distance}
        participants:dict[str,Any]={}
        raw_logit=None
        goalie_logit_delta=0.0
        if source_type in ATTEMPT_EVENTS and side in {"home","away"}:
            shooter=_choose_shooter(rng,sides[side],active[side])
            participants["shooter_id"]=shooter.nhl_id
            participants["shooter_name"]=shooter.name
            opposing="away" if side=="home" else "home"
            goalie_candidates=active_groups[opposing]["G"]
            goalie_id=goalie_candidates[0] if goalie_candidates else None
            participants["goalie_id"]=goalie_id
            participants["empty_net"]=goalie_id is None
            if donor.period_type in {"REG","OT"} and strength=="5v5":
                if source_type=="blocked-shot" or _distance_bin(raw,side,str(donor.pbp["homeTeam"]["id"]))=="unknown":
                    shot_type,_,_=_distance_and_type(raw,side,str(donor.pbp["homeTeam"]["id"]))
                    options=[(k[1],v["shots"]) for k,v in model.bin_counts.items()
                             if k[0]==shot_type and v["shots"]>0]
                    if not options:
                        options=[(k[1],v["shots"]) for k,v in model.bin_counts.items() if v["shots"]>0]
                    bins=[x[0] for x in options]
                    weights=[x[1] for x in options]
                    sampled_bin=rng.choices(bins,weights=weights,k=1)[0] if bins else "30_50"
                    q=model.bin_probabilities.get((shot_type,sampled_bin),model.global_goal_rate)
                    details["shot_quality_bin"]={"shot_type":shot_type,"distance_bin":sampled_bin,
                                                  "provenance":"sampled from 2019-2020 training distribution"}
                else:
                    q=_event_quality(raw,side,donor,model)
                if goalie_id is None:
                    q=model.empty_net_rate
                shooter_delta=.20*(_logit(shooter.finish_rate)-_logit(model.global_goal_rate))
                raw_logit=_logit(q)+shooter_delta
                if goalie_id is not None:
                    goalie=sides[opposing].players[goalie_id]
                    goalie_logit_delta=_goalie_logit_delta(
                        goalie.save_pct,model.global_goal_rate)
        elif source_type=="faceoff":
            centers={}
            for team_side in ("home","away"):
                ids=active_groups[team_side]["F"]
                candidates=[sides[team_side].players[pid] for pid in ids if sides[team_side].players[pid].position=="C"]
                if not candidates:
                    candidates=[sides[team_side].players[pid] for pid in ids]
                centers[team_side]=_choose_weighted(rng,candidates,[max(.01,p.usage_minutes*p.faceoff_pct) for p in candidates])
            ph=centers["home"].faceoff_pct
            pa=centers["away"].faceoff_pct
            home_wins=rng.random()<ph/max(.01,ph+pa)
            winner="home" if home_wins else "away"
            loser="away" if home_wins else "home"
            participants={"faceoff_winner_id":centers[winner].nhl_id,
                          "faceoff_loser_id":centers[loser].nhl_id}
            side=winner
        elif source_type=="penalty" and side in {"home","away"}:
            candidates=[sides[side].players[pid] for pid in active_groups[side]["F"]+active_groups[side]["D"]]
            if not candidates:
                raise DonorDataError("penalty_player_unavailable",
                    f"{donor.game.game_id}: penalty team has no active skater to serve")
            source_player_id=str(raw_details.get("committedByPlayerId") or "")
            mapped_player_id=donor.player_map.get(source_player_id)
            next_active=donor.active(min(REG_SECONDS if donor.period_type=="REG" else OT_SECONDS,clock+1))
            departing=set(active[side])-set(next_active[side])
            departing_candidates=[sides[side].players[pid] for pid in departing
                                  if pid in sides[side].players and sides[side].players[pid].position!="G"]
            mapped_is_on_ice=(mapped_player_id in active[side]
                              and mapped_player_id in sides[side].players
                              and sides[side].players[mapped_player_id].position!="G")
            if mapped_is_on_ice:
                simulated_penalty_player=sides[side].players[mapped_player_id]
            elif departing_candidates:
                server=_choose_weighted(rng,departing_candidates,
                    [1/max(1,p.usage_minutes) for p in departing_candidates])
                simulated_penalty_player=server
            else:
                simulated_penalty_player=_choose_weighted(
                    rng,candidates,[1/max(1,p.usage_minutes) for p in candidates])
            penalty_kind,penalty_duration=_supported_penalty(raw_details,donor.game.game_id)
            # Every synthetic penalty actor is on the ice and is the player
            # removed by the live penalty ledger. Keep the donor athlete as
            # source provenance instead of recording two conflicting actors.
            participants["penalized_player_id"]=simulated_penalty_player.nhl_id
            participants["penalized_player_name"]=simulated_penalty_player.name
            participants["serving_player_id"]=simulated_penalty_player.nhl_id
            details["penalty_kind"]=penalty_kind
            details["penalty_duration_seconds"]=penalty_duration
            details["source_committed_player_id"]=source_player_id or None
            details["source_player_mapped_to_active_skater"]=bool(mapped_is_on_ice)
        elif source_type=="hit" and side in {"home","away"}:
            candidates=[sides[side].players[pid] for pid in active_groups[side]["F"]+active_groups[side]["D"]]
            if candidates:
                hitter=_choose_weighted(rng,candidates,[1+max(0,p.usage_minutes-10)/30 for p in candidates])
                participants["hitter_id"]=hitter.nhl_id
                opposing="away" if side=="home" else "home"
                opp=[sides[opposing].players[pid] for pid in active_groups[opposing]["F"]+active_groups[opposing]["D"]]
                if opp:
                    hittee=_choose_weighted(rng,opp,[1.0]*len(opp))
                    participants["hittee_id"]=hittee.nhl_id
        elif source_type=="blocked-shot" and side in {"home","away"}:
            defending="away" if side=="home" else "home"
            defenders=active_groups[defending]["F"]+active_groups[defending]["D"]
            if defenders:
                blocker=_choose_weighted(rng,[sides[defending].players[x] for x in defenders],[1.0]*len(defenders))
                participants["blocker_id"]=blocker.nhl_id
        plays.append(SimPlay(raw,donor,source_type,side,clock,remaining,active,strength,goalie_present,
                             details,participants,raw_logit,goalie_logit_delta))
    penalties_by_clock:dict[int,list[SimPlay]]=collections.defaultdict(list)
    for play in plays:
        if play.event_type=="penalty":
            penalties_by_clock[play.elapsed].append(play)
    for elapsed,penalty_plays in penalties_by_clock.items():
        for index,left in enumerate(penalty_plays):
            for right in penalty_plays[index+1:]:
                if left.team_side==right.team_side:
                    continue
                left_sig=(left.details["penalty_kind"],left.details["penalty_duration_seconds"])
                right_sig=(right.details["penalty_kind"],right.details["penalty_duration_seconds"])
                if left_sig!=right_sig:
                    raise DonorDataError("coincident_penalty_state_unsupported",
                        f"{donor.game.game_id} P{donor.period_number} {elapsed}: opposing penalties differ")
                left.details["coincidental"]=True
                right.details["coincidental"]=True
    return plays


def calibrate_fivevfive_offsets(plays: list[SimPlay], inputs: PregameInputs,
                                model: ShotQualityModel) -> dict[str,Any]:
    """Set shot and goal offsets from pregame means, never from target-game outcomes.

    Non-5v5 outcomes remain sampled from verified training templates in this alpha.
    The offset shares a pregame team goal expectation across simulated 5v5 chances;
    an individual sampled goal remains the result of a generated shot outcome.
    """
    target_sog={"home":float(inputs.snapshot["team_expected_sog"]["home"]),
                "away":float(inputs.snapshot["team_expected_sog"]["away"])}
    target_mu={"home":inputs.mu_home,"away":inputs.mu_away}
    offsets={"goal_logit":{},"sog_probability":{},"diagnostics":{}}
    for side in ("home","away"):
        candidates=[p for p in plays if p.team_side==side and p.raw_goal_logit is not None
                    and p.donor.period_type=="REG" and p.strength=="5v5"]
        if not candidates:
            raise ValueError(f"no eligible 5v5 on-target opportunities for {side}")
        candidate_ids={id(p) for p in candidates}
        fixed_sog=sum(p.event_type in SHOT_EVENTS for p in plays
                      if p.team_side==side and id(p) not in candidate_ids)
        fixed_goals=sum(p.event_type=="goal" for p in plays
                        if p.team_side==side and id(p) not in candidate_ids)
        remaining_sog=max(0.0,target_sog[side]-fixed_sog)
        p_sog=min(.90,max(.05,remaining_sog/len(candidates)))
        for play in candidates:
            play.sog_probability=p_sog
        desired_goals=max(.10,target_mu[side]-fixed_goals)
        expected_candidate_sog=max(.1,p_sog*len(candidates))
        rate=min(.28,max(.025,desired_goals/expected_candidate_sog))
        logits=[float(p.raw_goal_logit) for p in candidates]
        lo,hi=-8.0,8.0
        for _ in range(70):
            mid=(lo+hi)/2
            avg=sum(_sigmoid(v+mid) for v in logits)/len(logits)
            if avg<rate: lo=mid
            else: hi=mid
        offset=(lo+hi)/2
        offsets["goal_logit"][side]=offset
        offsets["sog_probability"][side]=p_sog
        offsets["diagnostics"][side]={"fivevfive_attempts":len(candidates),"fixed_non5v5_sog":fixed_sog,
            "fixed_non5v5_goals":fixed_goals,"target_sog_mean":target_sog[side],
            "target_goal_mean":target_mu[side],"candidate_expected_sog":expected_candidate_sog,
            "candidate_goal_rate":rate,"calibration_goal_rate_capped":desired_goals/expected_candidate_sog>0.28 or desired_goals/expected_candidate_sog<0.025}
        for play in candidates:
            play.goal_probability=_sigmoid(float(play.raw_goal_logit)+offset+play.goalie_logit_delta)
    return offsets


def sample_goalie_plan(rng: random.Random, roster: TeamRoster) -> list[str]:
    """Sample an uncertain starter and backup from only pregame goalie evidence."""
    goalies=[roster.players[pid] for pid in roster.goalie_ids]
    starter=_choose_weighted(rng,goalies,roster.goalie_weights)
    backups=[p for p in goalies if p.nhl_id!=starter.nhl_id]
    if not backups:
        return [starter.nhl_id]
    backup=_choose_weighted(rng,backups,[max(.5,p.games_started) for p in backups])
    return [starter.nhl_id,backup.nhl_id]


def _score_state(score: dict[str,int], sog: dict[str,int]) -> dict[str,Any]:
    return {"score":{"home":score["home"],"away":score["away"]},
            "sog_event_count":{"home":sog["home"],"away":sog["away"]}}


def _append_sim_event(events: list[dict[str,Any]], score: dict[str,int], sog: dict[str,int], *,
                      period_number: int, period_type: str, event_type: str,
                      team_side: str|None, elapsed: int, duration: int,
                      details: dict[str,Any]|None=None,
                      on_ice: dict[str,list[str]]|None=None, strength: str|None=None,
                      participants: dict[str,Any]|None=None, score_goal: bool=False,
                      count_sog: bool=False) -> dict[str,Any]:
    before=_score_state(score,sog)
    if score_goal:
        if team_side not in {"home","away"}:
            raise ValueError("generated goal has no team owner")
        score[team_side]+=1
    if count_sog:
        if team_side not in {"home","away"}:
            raise ValueError("generated SOG has no team owner")
        sog[team_side]+=1
    remaining=max(0,duration-elapsed)
    event={"sequence":len(events)+1,"period_number":period_number,"period_type":period_type,
        "time_in_period":f"{elapsed//60:02d}:{elapsed%60:02d}",
        "time_remaining":f"{remaining//60:02d}:{remaining%60:02d}",
        "clock_elapsed_seconds":elapsed,"clock_remaining_seconds":remaining,
        "event_type":event_type,"team_side":team_side,"details":details or {},
        "participants":participants or {},"on_ice":on_ice or {"home":[],"away":[]},
        "strength":strength,"state_before":before,"state_after":_score_state(score,sog)}
    events.append(event)
    return event


def _empty_player_totals(inputs: PregameInputs) -> dict[str,dict[str,Any]]:
    totals={}
    for side,roster in (("home",inputs.home_roster),("away",inputs.away_roster)):
        for p in roster.players.values():
            totals[p.nhl_id]={"player_id":p.nhl_id,"canonical_player_id":p.canonical_id,
                "name":p.name,"team_side":side,"position":p.position,"goals":0,"assists":0,
                "shot_attempts":0,"shots_on_goal":0,"faceoffs_taken":0,"faceoffs_won":0,
                "faceoffs_lost":0,"penalties":0,"hits":0,"blocks":0,
                "shootout_attempts":0,"shootout_goals":0,"time_on_ice_seconds":0}
    return totals


def _sample_assists(rng: random.Random, play: SimPlay, shooter_id: str,
                    inputs: PregameInputs, model: ShotQualityModel) -> list[str]:
    count=rng.choices([0,1,2],weights=[model.assist_count_probabilities.get(i,0.0) for i in range(3)],k=1)[0]
    if count==0:
        return []
    roster=inputs.home_roster if play.team_side=="home" else inputs.away_roster
    ids=[pid for pid in play.active[play.team_side] if pid!=shooter_id and
         pid in roster.players and roster.players[pid].position!="G"]
    if not ids:
        return []
    weights=[max(.01,roster.players[pid].assists+10*roster.players[pid].shot_rate) for pid in ids]
    selected=[]
    for _ in range(min(count,len(ids))):
        p=_choose_weighted(rng,[roster.players[x] for x in ids],weights)
        idx=ids.index(p.nhl_id)
        selected.append(p.nhl_id)
        ids.pop(idx); weights.pop(idx)
    return selected


def _choose_blocker(rng: random.Random, play: SimPlay, inputs: PregameInputs) -> str|None:
    if play.team_side not in {"home","away"}:
        return None
    defending="away" if play.team_side=="home" else "home"
    roster=inputs.away_roster if defending=="away" else inputs.home_roster
    ids=[pid for pid in play.active[defending] if pid in roster.players and roster.players[pid].position!="G"]
    if not ids:
        return None
    return _choose_weighted(rng,[roster.players[x] for x in ids],[1.0]*len(ids)).nhl_id


def _faceoff_result(rng: random.Random, active: dict[str,list[str]],
                    inputs: PregameInputs) -> tuple[str,dict[str,str]]:
    centers={}
    for side,roster in (("home",inputs.home_roster),("away",inputs.away_roster)):
        eligible=[roster.players[pid] for pid in active[side]
                  if pid in roster.players and roster.players[pid].position=="C"]
        if not eligible:
            eligible=[roster.players[pid] for pid in active[side]
                      if pid in roster.players and roster.players[pid].position!="G"]
        centers[side]=_choose_weighted(rng,eligible,
            [max(.01,p.usage_minutes*p.faceoff_pct) for p in eligible])
    ph,pa=centers["home"].faceoff_pct,centers["away"].faceoff_pct
    winner="home" if rng.random()<ph/max(.01,ph+pa) else "away"
    loser="away" if winner=="home" else "home"
    return winner,{"faceoff_winner_id":centers[winner].nhl_id,
                   "faceoff_loser_id":centers[loser].nhl_id}


def _emit_rule_restart_faceoff(events: list[dict[str,Any]], score: dict[str,int],
                               sog: dict[str,int], team_totals: dict[str,dict[str,int]],
                               player_totals: dict[str,dict[str,Any]], inputs: PregameInputs,
                               rng: random.Random, state: dict[str,Any], *,
                               period_number: int, period_type: str, elapsed: int,
                               duration: int, active: dict[str,list[str]], strength: str,
                               goalie_pulled: dict[str,bool], causes: list[str]) -> None:
    """Emit a required restart from the live simulated state, not a donor slot."""
    side,participants=_faceoff_result(rng,active,inputs)
    details={"restart_required":True,"restart_causes":sorted(set(causes)),
             "restart_provenance":"generated_from_simulated_rule_state",
             "goalie_pulled":dict(goalie_pulled),
             "latent_possession_before":state["possession"]}
    if "goal" in causes or "period-start" in causes:
        details["faceoff_location"]="center-ice"
    else:
        details["faceoff_location_status"]="unassessed_without_zone_state"
    _append_sim_event(events,score,sog,period_number=period_number,period_type=period_type,
        event_type="faceoff",team_side=side,elapsed=elapsed,duration=duration,
        details=details,on_ice=active,strength=strength,participants=participants)
    winner=participants["faceoff_winner_id"]
    loser=participants["faceoff_loser_id"]
    for pid in (winner,loser):
        if pid in player_totals:
            player_totals[pid]["faceoffs_taken"]+=1
    player_totals[winner]["faceoffs_won"]+=1
    player_totals[loser]["faceoffs_lost"]+=1
    team_totals[side]["faceoffs_won"]+=1
    state["possession"]=side
    state["last_transition_family"]="faceoff"
    state["transition_family_counts"]["faceoff"]+=1
    state["rule_forced_faceoffs"]+=1


def _refresh_shot_participants(play: SimPlay, side: str, active: dict[str,list[str]],
                               inputs: PregameInputs, model: ShotQualityModel,
                               offsets: dict[str,Any], participants: dict[str,Any],
                               details: dict[str,Any], rng: random.Random) -> None:
    roster=inputs.home_roster if side=="home" else inputs.away_roster
    defending="away" if side=="home" else "home"
    goalie_roster=inputs.away_roster if defending=="away" else inputs.home_roster
    shooter_id=participants.get("shooter_id")
    if shooter_id not in active[side] or shooter_id not in roster.players:
        shooter=_choose_shooter(rng,roster,active[side])
        shooter_id=shooter.nhl_id
        participants["shooter_id"]=shooter_id
        participants["shooter_name"]=shooter.name
    shooter=roster.players[shooter_id]
    goalie_ids=[pid for pid in active[defending]
                if pid in goalie_roster.players and goalie_roster.players[pid].position=="G"]
    goalie_id=goalie_ids[0] if goalie_ids else None
    participants["goalie_id"]=goalie_id
    participants["empty_net"]=goalie_id is None
    if play.raw_goal_logit is None or side not in offsets.get("goal_logit",{}):
        return
    quality=details.get("shot_quality_bin") or {}
    stype=str(quality.get("shot_type") or "unknown")
    dbin=str(quality.get("distance_bin") or "unknown")
    q=model.bin_probabilities.get((stype,dbin),
        model.bin_probabilities.get(("unknown",dbin),model.global_goal_rate))
    if goalie_id is None:
        q=model.empty_net_rate
    raw_logit=_logit(q)+.20*(_logit(shooter.finish_rate)-_logit(model.global_goal_rate))
    goalie_delta=0.0
    if goalie_id is not None:
        goalie=goalie_roster.players[goalie_id]
        goalie_delta=_goalie_logit_delta(goalie.save_pct,model.global_goal_rate)
    play.raw_goal_logit=raw_logit
    play.goalie_logit_delta=goalie_delta
    play.sog_probability=float(offsets["sog_probability"].get(side,play.sog_probability or 0.0))
    play.goal_probability=_sigmoid(raw_logit+float(offsets["goal_logit"][side])+goalie_delta)


def _add_shift_totals(player_totals: dict[str,dict[str,Any]], donor: DonorPeriod) -> None:
    seen: dict[str,list[tuple[int,int,int]]]=collections.defaultdict(list)
    period_limit=REG_SECONDS if donor.period_type=="REG" else OT_SECONDS
    boundaries={0}
    for row in donor.shift_ledger:
        pid=str(row["player_id"])
        if pid not in player_totals:
            raise DonorDataError("target_roster_mapping",
                f"{donor.game.game_id}: shift ledger references ineligible simulated player {pid}")
        start=int(row["start_seconds"]); end=int(row["end_seconds"])
        if start<0 or end<=start or end>period_limit:
            raise DonorDataError("shift_interval_invalid",
                f"{donor.game.game_id}: invalid shift interval for {pid}: {start}..{end}")
        for previous_start,previous_end,previous_period in seen[pid]:
            if previous_period==row["period_number"] and max(start,previous_start)<min(end,previous_end):
                raise DonorDataError("overlapping_shift_intervals",
                    f"{donor.game.game_id} P{row['period_number']}: overlapping remapped shifts for player {pid}: "
                    f"{previous_start}-{previous_end} and {start}-{end}")
        seen[pid].append((start,end,int(row["period_number"])))
        player_totals[pid]["time_on_ice_seconds"]+=end-start
        boundaries.update((start,end))
    # A remapped shift ledger is also the source of generated goalie-change events.
    # Check each interval boundary before accepting the donor so a later inserted
    # substitution cannot create an impossible lineup from a gap in the chart.
    for boundary in sorted(boundaries):
        for elapsed in {max(0,boundary-1),boundary}:
            if elapsed>=period_limit:
                continue
            if donor.terminal_elapsed is not None and elapsed>=donor.terminal_elapsed:
                continue
            active_by_side={"home":[],"away":[]}
            for row in donor.shift_ledger:
                if int(row["start_seconds"])<=elapsed<int(row["end_seconds"]):
                    active_by_side[row["team_side"]].append(str(row["player_id"]))
            for side,ids in active_by_side.items():
                goalie_count=sum(player_totals[pid]["position"]=="G" for pid in ids)
                skater_count=len(ids)-goalie_count
                if goalie_count>1 or skater_count<3 or skater_count>6:
                    raise DonorDataError("shift_lineup_invalid_at_boundary",
                        f"{donor.game.game_id} {donor.period_type} P{donor.period_number} {elapsed}: "
                        f"remapped {side} lineup has {skater_count} skaters and {goalie_count} goalies")


def _state_reconciled_shift_ledger(donor: DonorPeriod, game_events: list[dict[str,Any]],
                                   inputs: PregameInputs,
                                   initial_penalties: PenaltyLedger) -> list[dict[str,Any]]:
    """Rebuild per-period TOI from donor shift boundaries plus simulated penalties."""
    period=donor.period_number
    limit=REG_SECONDS if donor.period_type=="REG" else OT_SECONDS
    period_events=[e for e in game_events if int(e["period_number"])==period
                   and e["period_type"]==donor.period_type]
    terminal=limit
    if donor.period_type=="OT":
        terminal_events=[e for e in period_events if e["event_type"]=="game-end"
                         and (e.get("details") or {}).get("reason")=="sudden_death_overtime_goal"]
        if terminal_events:
            terminal=min(int(e["clock_elapsed_seconds"]) for e in terminal_events)
    breakpoints={0,terminal}
    for row in donor.shift_ledger:
        for key in ("start_seconds","end_seconds"):
            value=int(row[key])
            if 0<value<terminal:
                breakpoints.add(value)
    event_groups:dict[int,list[dict[str,Any]]]=collections.defaultdict(list)
    for event in period_events:
        elapsed=int(event["clock_elapsed_seconds"])
        if 0<=elapsed<=terminal:
            event_groups[elapsed].append(event)
            if elapsed<terminal:
                breakpoints.add(elapsed)
            if event["event_type"]=="penalty":
                duration=int(event["details"]["penalty_duration_seconds"])
                if elapsed+duration<terminal:
                    breakpoints.add(elapsed+duration)
            if event["event_type"]=="goal" and elapsed+120<terminal:
                breakpoints.add(elapsed+120)
    for penalty in initial_penalties.active:
        expiry=initial_penalties._last_absolute_second+penalty.remaining_seconds
        period_abs=PenaltyLedger.absolute_second(period,0)
        local=expiry-period_abs
        if 0<local<terminal:
            breakpoints.add(local)
    ordered=sorted(breakpoints)
    ledger=initial_penalties.clone()
    if ledger._last_absolute_second is None:
        ledger.advance_to(period,0)
    rows_by_player:dict[tuple[str,str],list[dict[str,Any]]]=collections.defaultdict(list)
    for index,elapsed in enumerate(ordered[:-1]):
        ledger.advance_to(period,elapsed)
        at_time=sorted(event_groups.get(elapsed,[]),key=lambda e:int(e["sequence"]))
        for event in at_time:
            event_type=event["event_type"]
            side=event.get("team_side")
            if event_type=="penalty":
                participants=event.get("participants") or {}
                details=event.get("details") or {}
                ledger.start(str(side),str(participants["serving_player_id"]),
                             str(details["penalty_kind"]),
                             duration_seconds=int(details["penalty_duration_seconds"]),
                             coincidental=bool(details.get("coincidental",False)))
            elif event_type=="goal" and side in {"home","away"}:
                ledger.on_goal(str(side))
        next_elapsed=ordered[index+1]
        if next_elapsed<=elapsed:
            raise ValueError("state-reconciled shift interval is not positive")
        active,strength,pulled=_live_on_ice(donor.active(elapsed),inputs,ledger,donor.period_type)
        for side in ("home","away"):
            for pid in active[side]:
                position=(inputs.home_roster if side=="home" else inputs.away_roster).players[pid].position
                row={"team_side":side,"player_id":pid,"position":position,
                     "period_number":period,"start_seconds":elapsed,"end_seconds":next_elapsed,
                     "duration_seconds":next_elapsed-elapsed,
                     "source":"state_reconciled_remapped_donor_shift",
                     "strength":strength,"goalie_pulled":pulled[side]}
                player_rows=rows_by_player[(side,pid)]
                if player_rows and player_rows[-1]["end_seconds"]==elapsed:
                    player_rows[-1]["end_seconds"]=next_elapsed
                    player_rows[-1]["duration_seconds"]+=next_elapsed-elapsed
                else:
                    player_rows.append(row)
    output=[row for key in sorted(rows_by_player) for row in rows_by_player[key]]
    if not output:
        raise DonorDataError("state_reconciled_shift_ledger_empty",
            f"{donor.game.game_id}: no generated on-ice intervals in period {period}")
    return output


def _add_reconciled_shift_totals(player_totals: dict[str,dict[str,Any]],
                                 shift_ledger: list[dict[str,Any]]) -> None:
    for row in shift_ledger:
        pid=str(row["player_id"])
        if pid not in player_totals:
            raise ValueError(f"state-reconciled shift ledger references unknown player {pid}")
        player_totals[pid]["time_on_ice_seconds"]+=int(row["duration_seconds"])


def _emit_penalty_clock_events(events: list[dict[str,Any]], score: dict[str,int], sog: dict[str,int],
                               expired: list[Any], donor: DonorPeriod,
                               inputs: PregameInputs, penalties: PenaltyLedger) -> None:
    for penalty in sorted(expired,key=lambda p:(p.expired_at_absolute_second or 0,p.player_id)):
        if penalty.expired_at_absolute_second is None:
            raise ValueError("expired penalty lacks its exact game-clock second")
        number,elapsed,ptype=_period_clock_from_absolute(penalty.expired_at_absolute_second)
        base=donor.active(elapsed) if number==donor.period_number else {"home":[],"away":[]}
        if number!=donor.period_number:
            raise ValueError("penalty expiry was emitted into the wrong donor period")
        active,strength,pulled=_live_on_ice(base,inputs,penalties,ptype)
        _append_sim_event(events,score,sog,period_number=number,period_type=ptype,
            event_type="penalty-expiration",team_side=penalty.team_side,elapsed=elapsed,
            duration=REG_SECONDS if ptype=="REG" else OT_SECONDS,
            details={"penalty_kind":penalty.kind,"player_returned_id":penalty.player_id,
                     "clock_expired_at_absolute_second":penalty.expired_at_absolute_second,
                     "goalie_pulled":pulled},on_ice=active,strength=strength,
            participants={"player_id":penalty.player_id})


def _advance_penalties(events: list[dict[str,Any]], score: dict[str,int], sog: dict[str,int],
                       penalties: PenaltyLedger, donor: DonorPeriod, inputs: PregameInputs,
                       period: int, elapsed: int) -> None:
    target=PenaltyLedger.absolute_second(period,elapsed)
    if penalties._last_absolute_second is None:
        penalties.advance_to(period,0)
    if penalties._last_absolute_second>target:
        raise ValueError("penalty state clock is later than requested transition")
    while penalties._last_absolute_second<target:
        now=penalties._last_absolute_second
        deadlines=[now+p.remaining_seconds for p in penalties.active]
        next_expiry=min(deadlines) if deadlines else None
        if next_expiry is not None and next_expiry<=target:
            exp_period,exp_elapsed,_=_period_clock_from_absolute(next_expiry)
            if exp_period!=donor.period_number:
                raise ValueError("penalty expiry crossed a period without its period transition")
            expired=penalties.advance_to(exp_period,exp_elapsed)
            if not expired:
                raise ValueError("penalty expiry deadline did not expire a penalty")
            _emit_penalty_clock_events(events,score,sog,expired,donor,inputs,penalties)
        else:
            penalties.advance_to(period,elapsed)


def _emit_simulated_period(events: list[dict[str,Any]], score: dict[str,int], sog: dict[str,int],
                           team_totals: dict[str,dict[str,int]], player_totals: dict[str,dict[str,Any]],
                           goalie_totals: dict[str,dict[str,int]], plays: list[SimPlay],
                           inputs: PregameInputs, model: ShotQualityModel, rng: random.Random,
                           offsets: dict[str,Any], state: dict[str,Any],
                           *, transition_model: EventTransitionModel|None=None,
                           transition_rng: random.Random|None=None,
                           stop_after_goal: bool=False) -> bool:
    saw_goal=False
    penalties:PenaltyLedger=state["penalties"]
    pending_restart:dict[str,Any]|None=None
    if plays:
        first=plays[0]
        first_active,first_strength,first_pulled=_live_on_ice(
            first.donor.active(0),inputs,penalties,first.donor.period_type)
        pending_restart={"elapsed":0,"causes":["period-start"],"active":first_active,
                         "strength":first_strength,"goalie_pulled":first_pulled}
    for play in plays:
        pn=play.donor.period_number; ptype=play.donor.period_type
        limit=REG_SECONDS if ptype=="REG" else OT_SECONDS
        use_donor_restart_slot=bool(pending_restart
            and play.elapsed==pending_restart["elapsed"] and play.event_type=="faceoff")
        restart_causes=list(pending_restart["causes"]) if use_donor_restart_slot else []
        if pending_restart and not use_donor_restart_slot:
            restart_elapsed=int(pending_restart["elapsed"])
            if restart_elapsed<limit:
                _emit_rule_restart_faceoff(events,score,sog,team_totals,player_totals,inputs,rng,state,
                    period_number=pn,period_type=ptype,elapsed=restart_elapsed,duration=limit,
                    active=pending_restart["active"],strength=pending_restart["strength"],
                    goalie_pulled=pending_restart["goalie_pulled"],causes=pending_restart["causes"])
            pending_restart=None
        elif use_donor_restart_slot:
            pending_restart=None
        _advance_penalties(events,score,sog,penalties,play.donor,inputs,pn,play.elapsed)
        active,strength,goalie_pulled=_live_on_ice(play.active,inputs,penalties,ptype)
        side=play.team_side
        event_type=play.event_type
        participants=copy.deepcopy(play.participants)
        details=copy.deepcopy(play.details)
        transition_family=_transition_family(event_type) or "stoppage"
        if use_donor_restart_slot:
            # Use a source faceoff only when it occurs at the exact pending
            # restart clock. The winner is still sampled against live players.
            event_type="faceoff"
            transition_family="faceoff"
            participants={}
            details["event_transition"]={"family":"faceoff",
                "family_fallback_level":"rule_required_donor_slot",
                "context_training_count":None}
            details["restart_required"]=True
            details["restart_causes"]=sorted(set(restart_causes))
            details["restart_provenance"]="simulated_faceoff_at_donor_restart_slot"
            if any(cause in {"goal","period-start"} for cause in restart_causes):
                details["faceoff_location"]="center-ice"
            else:
                details["faceoff_location_status"]="unassessed_without_zone_state"
            state["rule_forced_faceoffs"]+=1
        elif transition_model is not None:
            trng=transition_rng or rng
            context=_transition_context(state.get("last_transition_family","start"),
                                        state.get("possession"),strength,score)
            transition_family,fallback_level,training_count=transition_model.sample_family(context,trng)
            state["transition_fallback_counts"][fallback_level]+=1
            details={"event_transition":{"family":transition_family,
                      "family_fallback_level":fallback_level,
                      "context_training_count":training_count}}
            participants={}
            if transition_family=="faceoff":
                event_type="faceoff"
            elif transition_family=="shot":
                event_type="shot-on-goal"
                if state.get("possession") in {"home","away"}:
                    side=state["possession"]
                    owner_level="latent_possession"
                else:
                    side,owner_level=transition_model.sample_owner(
                        transition_family,context,None,play.team_side,trng)
                details["shot_quality_bin"]=_sample_transition_shot_quality(trng,model)
                details["shot_type"]=details["shot_quality_bin"]["shot_type"]
                play.raw_goal_logit=0.0
                play.sog_probability=float(offsets["sog_probability"].get(side,0.0))
                details["event_transition"]["owner_source"]=owner_level
                state["transition_owner_fallback_counts"][owner_level]+=1
            else:
                event_type=transition_family
                side,owner_level=transition_model.sample_owner(
                    transition_family,context,state.get("possession"),play.team_side,trng)
                details["event_transition"]["owner_source"]=owner_level
                state["transition_owner_fallback_counts"][owner_level]+=1
                if transition_family=="penalty":
                    kind,duration=transition_model.sample_penalty(trng)
                    details["penalty_kind"]=kind
                    details["penalty_duration_seconds"]=duration
                elif transition_family=="stoppage":
                    side=None
            if transition_family in {"shot","giveaway","takeaway","penalty","hit"} \
                    and side not in {"home","away"}:
                raise DonorDataError("transition_owner_unresolved",
                    f"{play.donor.game.game_id} P{pn} {play.elapsed}: {transition_family} has no team owner")
        if event_type=="penalty" and side in {"home","away"}:
            omit_reason=None
            now=PenaltyLedger.absolute_second(pn,play.elapsed)
            if transition_model is not None and any(
                    p.started_at_absolute_second==now for p in penalties.active):
                omit_reason="simultaneous_penalty_transition_requires_explicit_pairing"
            active_units=sum(p.team_side==side and p.kind in {"MIN","MAJ"}
                             and not p.coincidental for p in penalties.active)
            penalty_kind=str(details.get("penalty_kind") or "")
            if (omit_reason is None and penalty_kind in {"MIN","MAJ"}
                    and active_units>=2 and not bool(details.get("coincidental",False))):
                omit_reason="third_concurrent_manpower_penalty_requires_queued_serving"
            if omit_reason is not None:
                details["unsupported_penalty_omitted"]={
                    "reason":omit_reason,"penalty_kind":penalty_kind,
                    "duration_seconds":details.get("penalty_duration_seconds")}
                if transition_model is not None:
                    details["event_transition"]["emitted_family"]="stoppage"
                transition_family="stoppage"
                participants={}
                side=None
                event_type="stoppage"
            else:
                active_skaters=[pid for pid in active[side]
                                if inputs.home_roster.players.get(pid,inputs.away_roster.players.get(pid)).position!="G"]
                penalty_actor=participants.get("penalized_player_id")
                if penalty_actor not in active_skaters:
                    if not active_skaters:
                        raise DonorDataError("penalty_serving_player_unavailable",
                            f"{play.donor.game.game_id}: no active simulated penalty server")
                    roster=inputs.home_roster if side=="home" else inputs.away_roster
                    candidates=[roster.players[pid] for pid in active_skaters]
                    penalty_actor=_choose_weighted(rng,candidates,
                        [1/max(1,p.usage_minutes) for p in candidates]).nhl_id
                participants["penalized_player_id"]=penalty_actor
                participants["serving_player_id"]=penalty_actor
                roster=inputs.home_roster if side=="home" else inputs.away_roster
                participants["penalized_player_name"]=roster.players[penalty_actor].name
                details["penalty_server_id"]=penalty_actor
        if event_type=="faceoff":
            side,participants=_faceoff_result(rng,active,inputs)
        elif event_type in ATTEMPT_EVENTS and side in {"home","away"}:
            side=shot_side_for_possession(state["possession"],side)
            _refresh_shot_participants(play,side,active,inputs,model,offsets,participants,details,rng)
        elif event_type=="hit" and side in {"home","away"}:
            hitters=[pid for pid in active[side]
                     if inputs.home_roster.players.get(pid,inputs.away_roster.players.get(pid)).position!="G"]
            if participants.get("hitter_id") not in hitters:
                participants["hitter_id"]=_choose_weighted(rng,
                    [(inputs.home_roster if side=="home" else inputs.away_roster).players[pid] for pid in hitters],
                    [1.0]*len(hitters)).nhl_id
            defending="away" if side=="home" else "home"
            opposing_skaters=[pid for pid in active[defending]
                              if inputs.home_roster.players.get(pid,inputs.away_roster.players.get(pid)).position!="G"]
            if participants.get("hittee_id") not in opposing_skaters and opposing_skaters:
                participants["hittee_id"]=_choose_weighted(rng,
                    [(inputs.home_roster if defending=="home" else inputs.away_roster).players[pid]
                     for pid in opposing_skaters],[1.0]*len(opposing_skaters)).nhl_id
        play.team_side=side
        play.active=active
        play.strength=strength
        if event_type in ATTEMPT_EVENTS and side in {"home","away"}:
            team_totals[side]["shot_attempts"]+=1
            shooter_id=str(participants["shooter_id"])
            player_totals[shooter_id]["shot_attempts"]+=1
            if play.sog_probability is not None:
                if rng.random()<play.sog_probability:
                    event_type="goal" if rng.random()<float(play.goal_probability or 0.0) else "shot-on-goal"
                else:
                    block_mass=model.attempt_result_probabilities.get("blocked",0.0)
                    miss_mass=model.attempt_result_probabilities.get("missed",0.0)
                    event_type="blocked-shot" if rng.random()<block_mass/max(.0001,block_mass+miss_mass) else "missed-shot"
            if event_type=="blocked-shot":
                blocker=_choose_blocker(rng,play,inputs)
                if blocker:
                    participants["blocker_id"]=blocker
                    player_totals[blocker]["blocks"]+=1
            else:
                participants.pop("blocker_id",None)
            if event_type in SHOT_EVENTS:
                team_totals[side]["shots_on_goal"]+=1
                player_totals[shooter_id]["shots_on_goal"]+=1
                goalie_id=participants.get("goalie_id")
                if goalie_id:
                    goalie_totals[goalie_id]["shots_against"]+=1
                    if event_type=="goal":
                        goalie_totals[goalie_id]["goals_against"]+=1
                    else:
                        goalie_totals[goalie_id]["saves"]+=1
            if event_type=="goal":
                player_totals[shooter_id]["goals"]+=1
                assists=_sample_assists(rng,play,shooter_id,inputs,model)
                participants["assist_player_ids"]=assists
                for pid in assists:
                    player_totals[pid]["assists"]+=1
                team_totals[side]["goals"]+=1
                saw_goal=True
        elif event_type=="faceoff":
            winner=participants.get("faceoff_winner_id")
            loser=participants.get("faceoff_loser_id")
            for pid in (winner,loser):
                if pid in player_totals:
                    player_totals[pid]["faceoffs_taken"]+=1
            if winner in player_totals:
                player_totals[winner]["faceoffs_won"]+=1
            if loser in player_totals:
                player_totals[loser]["faceoffs_lost"]+=1
            team_totals[side]["faceoffs_won"]+=1
        elif event_type=="penalty":
            pid=participants.get("penalized_player_id")
            if pid in player_totals:
                player_totals[pid]["penalties"]+=1
            team_totals[side]["penalties"]+=1
        elif event_type=="hit":
            pid=participants.get("hitter_id")
            if pid in player_totals:
                player_totals[pid]["hits"]+=1
            team_totals[side]["hits"]+=1
        if event_type=="penalty":
            details["coincidental"]=False
        details["goalie_pulled"]=goalie_pulled
        details["latent_possession_before"]=state["possession"]
        emitted_event=_append_sim_event(events,score,sog,period_number=pn,period_type=ptype,event_type=event_type,
            team_side=side,elapsed=play.elapsed,duration=limit,details=details,on_ice=active,
            strength=strength,participants=participants,
            score_goal=event_type=="goal",count_sog=event_type in SHOT_EVENTS)
        if event_type=="penalty":
            kind=str(details["penalty_kind"])
            duration=int(details["penalty_duration_seconds"])
            active_penalty=penalties.start(side,str(participants["serving_player_id"]),kind,
                            duration_seconds=duration,coincidental=False)
            emitted_event["details"]["coincidental"]=active_penalty.coincidental
            if active_penalty.coincidental:
                for prior in reversed(events[:-1]):
                    prior_details=prior.get("details") or {}
                    if (prior.get("event_type")=="penalty"
                            and prior.get("period_number")==pn
                            and prior.get("clock_elapsed_seconds")==play.elapsed
                            and prior.get("team_side")!=side
                            and prior_details.get("penalty_kind")==kind
                            and prior_details.get("penalty_duration_seconds")==duration):
                        prior_details["coincidental"]=True
        if event_type=="goal":
            released=penalties.on_goal(side)
            if released is not None:
                released_now=released not in penalties.active
                _append_sim_event(events,score,sog,period_number=pn,period_type=ptype,
                    event_type="penalty-release" if released_now else "penalty-segment-end",
                    team_side=released.team_side,elapsed=play.elapsed,duration=limit,
                    details={"penalty_kind":released.kind,"release_reason":"power_play_goal",
                             "player_returned_id":released.player_id,"goalie_pulled":goalie_pulled,
                             "penalty_fully_released":released_now},on_ice=active,
                    strength=strength,participants={"player_id":released.player_id})
        state["possession"]=possession_after_event(state["possession"],event_type,side)
        if transition_model is not None:
            state["last_transition_family"]=transition_family
            state["transition_family_counts"][transition_family]+=1
        else:
            observed_family=_transition_family(event_type) or "stoppage"
            state["last_transition_family"]=observed_family
            state["transition_family_counts"][observed_family]+=1
        if event_type=="goal" and stop_after_goal:
            _append_sim_event(events,score,sog,period_number=pn,period_type=ptype,event_type="game-end",
                team_side=None,elapsed=play.elapsed,duration=limit,
                details={"reason":"sudden_death_overtime_goal"})
            return True
        if event_type=="faceoff":
            pending_restart=None
        elif event_type in {"goal","penalty","stoppage"} and play.elapsed<limit:
            restart_active,restart_strength,restart_pulled=_live_on_ice(
                play.active,inputs,penalties,ptype)
            pending_restart={"elapsed":play.elapsed,"causes":[event_type],
                "active":restart_active,"strength":restart_strength,
                "goalie_pulled":restart_pulled}
    limit=REG_SECONDS if plays and plays[0].donor.period_type=="REG" else OT_SECONDS
    period=plays[0].donor.period_number if plays else 1
    if plays:
        if pending_restart and int(pending_restart["elapsed"])<limit:
            _emit_rule_restart_faceoff(events,score,sog,team_totals,player_totals,inputs,rng,state,
                period_number=period,period_type=plays[0].donor.period_type,
                elapsed=int(pending_restart["elapsed"]),duration=limit,
                active=pending_restart["active"],strength=pending_restart["strength"],
                goalie_pulled=pending_restart["goalie_pulled"],causes=pending_restart["causes"])
        _advance_penalties(events,score,sog,penalties,plays[-1].donor,inputs,period,limit)
    return saw_goal


def _shootout(events: list[dict[str,Any]], score: dict[str,int], sog: dict[str,int],
              player_totals: dict[str,dict[str,Any]], goalie_totals: dict[str,dict[str,int]],
              inputs: PregameInputs, model: ShotQualityModel, goalie_plan: dict[str,list[str]],
              rng: random.Random) -> str:
    attempts_by_side={"home":0,"away":0}; goals_by_side={"home":0,"away":0}
    first_side="home" if rng.random()<model.shootout_first_home_probability else "away"
    order=(first_side,"away" if first_side=="home" else "home")
    available_shooters={
        side:[p.nhl_id for p in roster.players.values()]
        for side,roster in (("home",inputs.home_roster),("away",inputs.away_roster))
    }
    _append_sim_event(events,score,sog,period_number=5,period_type="SO",event_type="period-start",
                      team_side=None,elapsed=0,duration=0,
                      details={"first_shooting_side":first_side,
                               "order_prior":"fit from eligible 2019-2020 shootout opening attempts"})
    winner=None
    for round_number in range(1,1001):
        for side in order:
            roster=inputs.home_roster if side=="home" else inputs.away_roster
            if not available_shooters[side]:
                available_shooters[side]=[p.nhl_id for p in roster.players.values()]
            shooter=_choose_weighted(rng,
                [roster.players[pid] for pid in available_shooters[side]],
                [max(.01,roster.players[pid].shot_rate) for pid in available_shooters[side]])
            available_shooters[side].remove(shooter.nhl_id)
            defending="away" if side=="home" else "home"
            goalie_id=goalie_plan[defending][0]
            goalie=inputs.away_roster.players[goalie_id] if defending=="away" else inputs.home_roster.players[goalie_id]
            pgoal=_shootout_goal_probability(shooter.finish_rate,goalie.save_pct,model)
            result="goal" if rng.random()<pgoal else rng.choice(["saved","missed"])
            attempts_by_side[side]+=1
            player_totals[shooter.nhl_id]["shootout_attempts"]+=1
            if result=="goal":
                goals_by_side[side]+=1
                player_totals[shooter.nhl_id]["shootout_goals"]+=1
            _append_sim_event(events,score,sog,period_number=5,period_type="SO",event_type="shootout-attempt",
                team_side=side,elapsed=0,duration=0,
                details={"round":round_number,"attempt_number":attempts_by_side[side],"attempt_result":result,
                         "shooting_order":order},
                participants={"shooter_id":shooter.nhl_id,"goalie_id":goalie_id})
            winner=shootout_decided(goals_by_side,attempts_by_side)
            if winner:
                break
        if winner:
            break
    if winner is None:
        raise ValueError("shootout did not produce a winner within 1000 rounds")
    _append_sim_event(events,score,sog,period_number=5,period_type="SO",event_type="shootout-decision",
        team_side=winner,elapsed=0,duration=0,details={"official_bonus_goal":1,"player_goal":False,
                                                        "attempts_by_side":attempts_by_side,
                                                        "shootout_goals_by_side":goals_by_side},
        score_goal=True)
    _append_sim_event(events,score,sog,period_number=5,period_type="SO",event_type="period-end",
        team_side=None,elapsed=0,duration=0)
    _append_sim_event(events,score,sog,period_number=5,period_type="SO",event_type="game-end",
        team_side=None,elapsed=0,duration=0)
    return winner


def _insert_goalie_substitutions(events: list[dict[str,Any]], shift_ledger: list[dict[str,Any]],
                                player_totals: dict[str,dict[str,Any]],
                                inputs: PregameInputs) -> list[dict[str,Any]]:
    """Materialize goalie changes from the sampled shift template as personnel events."""
    limits={1:REG_SECONDS,2:REG_SECONDS,3:REG_SECONDS,4:OT_SECONDS}
    additions=[]
    for period,limit in limits.items():
        period_rows=[r for r in shift_ledger if r["period_number"]==period]
        times=sorted({int(r[k]) for r in period_rows for k in ("start_seconds","end_seconds")
                      if 0<int(r[k])<limit})
        for side in ("home","away"):
            goalie_rows=[r for r in period_rows if r["team_side"]==side and r["position"]=="G"]
            if not goalie_rows:
                continue
            def goalie_at(t: int) -> str|None:
                active=[r for r in goalie_rows if int(r["start_seconds"])<=t<int(r["end_seconds"])]
                if not active:
                    return None
                active.sort(key=lambda r:(-int(r["start_seconds"]),-int(r["duration_seconds"]),r["player_id"]))
                return str(active[0]["player_id"])
            period_goals=[e["clock_elapsed_seconds"] for e in events
                          if e["period_number"]==period and e["event_type"]=="goal"]
            terminal=min(period_goals) if period==4 and period_goals else limit
            for elapsed in times:
                if elapsed>=terminal:
                    continue
                old=goalie_at(elapsed-1); new=goalie_at(elapsed)
                if old==new:
                    continue
                on_ice={"home":[],"away":[]}
                for row in period_rows:
                    if int(row["start_seconds"])<=elapsed<int(row["end_seconds"]):
                        on_ice[row["team_side"]].append(str(row["player_id"]))
                # On overlapping goalie intervals, the later-starting goalie is the selected active keeper.
                if new:
                    on_ice[side]=[pid for pid in on_ice[side] if player_totals[pid]["position"]!="G"]+[new]
                details={"reason":"sampled_shift_template_goalie_transition",
                         "transition_source":"verified shift-chart interval boundary"}
                additions.append({"period_number":period,"period_type":"REG" if period<4 else "OT",
                    "time_in_period":f"{elapsed//60:02d}:{elapsed%60:02d}",
                    "time_remaining":f"{(limit-elapsed)//60:02d}:{(limit-elapsed)%60:02d}",
                    "clock_elapsed_seconds":elapsed,"clock_remaining_seconds":limit-elapsed,
                    "event_type":"goalie-substitution","team_side":side,"details":details,
                    "participants":{"goalie_leaving_id":old,"goalie_entering_id":new},
                    "on_ice":on_ice,"strength":None})
    combined=events+additions
    # Expiry takes effect at its exact game-clock second; process it before a
    # same-second goalie transition can put the returning player back on ice.
    combined.sort(key=lambda e:(e["period_number"],e["clock_elapsed_seconds"],
                                0 if e["event_type"]=="penalty-expiration" else
                                1 if e["event_type"]=="goalie-substitution" else 2))
    score={"home":0,"away":0}; sog={"home":0,"away":0}
    penalties=PenaltyLedger()
    for sequence,event in enumerate(combined,1):
        if event["period_type"] in {"REG","OT"}:
            penalties.advance_to(int(event["period_number"]),
                                 int(event["clock_elapsed_seconds"]))
            if event["event_type"]=="goalie-substitution":
                active,strength,pulled=_live_on_ice(
                    event["on_ice"],inputs,penalties,event["period_type"])
                event["on_ice"]=active
                event["strength"]=strength
                event["details"]["goalie_pulled"]=pulled
            elif event["event_type"]=="penalty":
                details=event.get("details") or {}
                participants=event.get("participants") or {}
                penalties.start(str(event["team_side"]),
                    str(participants["penalized_player_id"]),
                    str(details["penalty_kind"]),
                    duration_seconds=int(details["penalty_duration_seconds"]),
                    coincidental=bool(details.get("coincidental",False)))
            elif event["event_type"]=="goal":
                penalties.on_goal(str(event["team_side"]))
        event["sequence"]=sequence
        event["state_before"]=_score_state(score,sog)
        if event["event_type"]=="goal" and event["period_type"]!="SO":
            score[event["team_side"]]+=1; sog[event["team_side"]]+=1
        elif event["event_type"]=="shot-on-goal":
            sog[event["team_side"]]+=1
        elif event["event_type"]=="shootout-decision":
            score[event["team_side"]]+=1
        event["state_after"]=_score_state(score,sog)
    return combined


def _event_absolute_second(event: dict[str,Any]) -> int:
    period=int(event["period_number"])
    elapsed=int(event["clock_elapsed_seconds"])
    if period<=3:
        return (period-1)*REG_SECONDS+elapsed
    if period==4:
        return 3*REG_SECONDS+elapsed
    raise ValueError("shootout events do not have a penalty-clock second")


def _validate_live_game_state(events: list[dict[str,Any]],
                              player_totals: dict[str,dict[str,Any]]) -> None:
    """Independently verify penalty clocks, manpower, and on-ice eligibility."""
    active: list[dict[str,Any]]=[]
    pending_expirations: set[tuple[str,str]]=set()
    pending_expiration_second: int|None=None

    def manpower(period_type: str, goalie_pulled: dict[str,bool]) -> dict[str,int]:
        base=3 if period_type=="OT" else 5
        units={side:sum(p["side"]==side and p["kind"] in {"MIN","MAJ"}
                        and not p["coincidental"] for p in active)
               for side in ("home","away")}
        counts={"home":base,"away":base}
        if period_type=="REG":
            counts={side:max(3,base-min(2,units[side])) for side in ("home","away")}
        else:
            difference=units["home"]-units["away"]
            if difference:
                short="home" if difference>0 else "away"
                number=min(2,abs(difference))
                counts[short]=max(3,base-number)
                other="away" if short=="home" else "home"
                counts[other]=min(5,base+number)
        for side,pulled in goalie_pulled.items():
            if pulled:
                counts[side]=min(6,counts[side]+1)
        return counts

    for event in events:
        event_type=event["event_type"]
        period_type=event["period_type"]
        if period_type=="SO":
            continue
        now=_event_absolute_second(event)
        returned_id=str((event.get("participants") or {}).get("player_id") or "")
        returned_side=str(event.get("team_side") or "")

        if pending_expirations:
            if event_type!="penalty-expiration" or now!=pending_expiration_second:
                raise ValueError("one or more simultaneous penalty expirations lack explicit events")
            key=(returned_side,returned_id)
            if key not in pending_expirations:
                raise ValueError("penalty-expiration does not match a simultaneously expired player")
            pending_expirations.remove(key)
        elif event_type=="penalty-expiration":
            due=[p for p in active if p["end"]<=now]
            due_keys={(p["side"],p["player_id"]) for p in due}
            key=(returned_side,returned_id)
            if key not in due_keys or not due:
                raise ValueError("penalty-expiration does not match a due active penalty")
            if any(p["end"]<now for p in due):
                raise ValueError("penalty expiration was emitted after its exact clock")
            pending_expirations=due_keys-{key}
            pending_expiration_second=now if pending_expirations else None
            active=[p for p in active if (p["side"],p["player_id"]) not in due_keys]
        elif any(p["end"]<=now for p in active):
            raise ValueError("active penalty reached expiry without a preceding expiration event")

        if pending_expirations and event_type!="penalty-expiration":
            raise ValueError("simultaneous penalty expiration sequence was interrupted")

        side=event.get("team_side")
        on_ice=event.get("on_ice") or {}
        for ice_side,ids in on_ice.items():
            for pid in ids:
                if player_totals[str(pid)]["team_side"]!=ice_side:
                    raise ValueError(f"on-ice player {pid} belongs to the wrong team at event {event['sequence']}")
                if any(p["side"]==ice_side and p["player_id"]==str(pid) and p["end"]>now
                       for p in active):
                    raise ValueError(f"penalized player {pid} remains on ice at event {event['sequence']}")

        details=event.get("details") or {}
        if event_type not in {"period-start","period-end","game-end","shootout-attempt",
                              "shootout-decision"}:
            goalie_pulled=details.get("goalie_pulled")
            if period_type in {"REG","OT"} and isinstance(goalie_pulled,dict):
                expected=manpower(period_type,goalie_pulled)
                actual={}
                for ice_side in ("home","away"):
                    ids=on_ice.get(ice_side,[])
                    goalie_count=sum(player_totals[str(pid)]["position"]=="G" for pid in ids)
                    skater_count=len(ids)-goalie_count
                    actual[ice_side]=skater_count
                    expected_goalies=0 if goalie_pulled.get(ice_side,False) else 1
                    if goalie_count!=expected_goalies:
                        raise ValueError(f"goalie presence disagrees with pull state at event {event['sequence']} ({ice_side})")
                if actual!=expected:
                    raise ValueError(f"penalty manpower does not reconcile at event {event['sequence']}: {actual} != {expected}")
                if event.get("strength")!=f"{actual['home']}v{actual['away']}":
                    raise ValueError(f"strength label disagrees with on-ice skaters at event {event['sequence']}")

        participants=event.get("participants") or {}
        if event_type=="penalty":
            player_id=str(participants.get("penalized_player_id") or "")
            server_id=str(participants.get("serving_player_id") or "")
            if side not in {"home","away"} or not player_id or player_id!=server_id:
                raise ValueError(f"penalty actor and server do not reconcile at event {event['sequence']}")
            if player_totals[player_id]["team_side"]!=side or player_totals[player_id]["position"]=="G":
                raise ValueError(f"penalty actor is not an eligible skater at event {event['sequence']}")
            if player_id not in on_ice.get(side,[]):
                raise ValueError(f"penalty actor was not on ice at event {event['sequence']}")
            kind=str(details.get("penalty_kind") or "")
            duration=int(details.get("penalty_duration_seconds") or 0)
            valid_durations={"MIN":{120,240},"MAJ":{300},"MIS":{600}}
            if kind not in valid_durations or duration not in valid_durations[kind]:
                raise ValueError(f"unsupported generated penalty state at event {event['sequence']}")
            coincidental=bool(details.get("coincidental",False))
            for prior in active:
                if prior["start"]==now and prior["side"]!=side:
                    if (prior["kind"],prior["duration"],prior["coincidental"])!=(kind,duration,coincidental):
                        raise ValueError("opposing same-clock penalties have inconsistent coincidental state")
            active.append({"side":side,"player_id":player_id,"kind":kind,
                           "duration":duration,"start":now,"end":now+duration,
                           "coincidental":coincidental})

        elif event_type in {"penalty-release","penalty-segment-end"}:
            player_id=str(participants.get("player_id") or "")
            matches=[p for p in active if p["side"]==side and p["player_id"]==player_id]
            if not matches:
                raise ValueError(f"penalty resolution has no active penalty at event {event['sequence']}")
            penalty=matches[0]
            if event_type=="penalty-release":
                active.remove(penalty)
            else:
                if penalty["kind"]!="MIN" or penalty["duration"]!=240:
                    raise ValueError("only an active double minor can end a segment early")
                penalty["end"]=now+120

    if pending_expirations:
        raise ValueError("game ended before all simultaneous penalty expirations were recorded")


def _validate_shootout_sequence(events: list[dict[str,Any]],
                                summary: dict[str,Any]) -> None:
    attempts={"home":0,"away":0}
    goals={"home":0,"away":0}
    decided=None
    decisions=[]
    for event in events:
        event_type=event["event_type"]
        if event_type=="shootout-attempt":
            if decided is not None:
                raise ValueError("shootout continued after a mathematical decision")
            side=event.get("team_side")
            result=(event.get("details") or {}).get("attempt_result")
            if side not in attempts or result not in {"goal","saved","missed"}:
                raise ValueError("shootout attempt has an invalid side or result")
            attempts[side]+=1
            goals[side]+=int(result=="goal")
            decided=shootout_decided(goals,attempts)
        elif event_type=="shootout-decision":
            decisions.append(event.get("team_side"))
    expected=summary.get("shootout_winner")
    if expected is None:
        if attempts["home"] or attempts["away"] or decisions:
            raise ValueError("shootout events exist without a shootout winner")
    elif decided!=expected or decisions!=[expected]:
        raise ValueError("shootout did not stop at or record its earliest decisive result")


def validate_generated_game(game: dict[str,Any]) -> None:
    events=game["events"]
    if not events or [e["sequence"] for e in events]!=list(range(1,len(events)+1)):
        raise ValueError("generated NHL event sequence is empty or non-contiguous")
    _validate_live_game_state(events,game["summary"]["player_totals"])
    _validate_shootout_sequence(events,game["summary"])
    score={"home":0,"away":0}; sog={"home":0,"away":0}; last_clock={}
    for event in events:
        pn=int(event["period_number"]); elapsed=int(event["clock_elapsed_seconds"])
        ptype=event["period_type"]
        limit=REG_SECONDS if ptype=="REG" else OT_SECONDS if ptype=="OT" else 0
        if elapsed<0 or elapsed>limit or event["clock_remaining_seconds"]!=limit-elapsed:
            raise ValueError(f"event {event['sequence']} has invalid {ptype} clock")
        if elapsed<last_clock.get(pn,-1):
            raise ValueError(f"period {pn} clock moved backwards")
        last_clock[pn]=elapsed
        if event["state_before"]!=_score_state(score,sog):
            raise ValueError(f"event {event['sequence']} before-state does not reconcile")
        et=event["event_type"]; side=event["team_side"]
        if et=="goal" and event["period_type"]!="SO":
            if side not in score: raise ValueError("goal without valid team side")
            score[side]+=1; sog[side]+=1
        elif et=="shot-on-goal":
            if side not in sog: raise ValueError("SOG without valid team side")
            sog[side]+=1
        elif et=="shootout-decision":
            if side not in score: raise ValueError("shootout decision lacks winner")
            score[side]+=1
        if event["state_after"]!=_score_state(score,sog):
            raise ValueError(f"event {event['sequence']} after-state does not reconcile")
        for ids in event.get("on_ice",{}).values():
            if len(ids)!=len(set(ids)):
                raise ValueError(f"duplicate on-ice player at event {event['sequence']}")
        pids=set(game["summary"]["player_totals"])
        for on_ice_side,ids in event.get("on_ice",{}).items():
            if any(pid not in pids for pid in ids):
                raise ValueError(f"event {event['sequence']} has an on-ice identity outside the pregame roster")
            if event["event_type"] not in {"period-start","period-end","game-end",
                                                "shootout-attempt","shootout-decision"}:
                goalies=sum(game["summary"]["player_totals"][pid]["position"]=="G" for pid in ids)
                skaters=len(ids)-goalies
                if goalies>1 or skaters<3 or skaters>6:
                    raise ValueError(f"event {event['sequence']} ({event['event_type']} {ptype} "
                        f"P{pn} t={elapsed}) has illegal on-ice counts for {on_ice_side}: "
                        f"{skaters} skaters, {goalies} goalies, ids={ids}")
        for key,value in event.get("participants",{}).items():
            if key.endswith("_ids"):
                ids=value
            elif key.endswith("_id"):
                ids=[value]
            else:
                continue
            for pid in ids:
                if pid is not None and str(pid) not in pids:
                    raise ValueError(f"event {event['sequence']} {key}={pid} is outside the pregame roster")
        if event.get("event_type") in {"goal","shot-on-goal","blocked-shot","missed-shot"} and \
                event.get("period_type")!="SO" and event.get("team_side") in {"home","away"}:
            participants=event.get("participants",{})
            shooter=participants.get("shooter_id")
            if shooter is None:
                raise ValueError(f"shot event {event['sequence']} has no simulated shooter")
            if game["summary"]["player_totals"][str(shooter)]["team_side"]!=side:
                raise ValueError(f"shot event {event['sequence']} shooter belongs to the wrong team")
            goalie=participants.get("goalie_id")
            defending="away" if side=="home" else "home"
            if goalie is None:
                if participants.get("empty_net") is not True:
                    raise ValueError(f"shot event {event['sequence']} omits goalie without an empty net")
            elif (game["summary"]["player_totals"][str(goalie)]["team_side"]!=defending
                  or game["summary"]["player_totals"][str(goalie)]["position"]!="G"
                  or str(goalie) not in event.get("on_ice",{}).get(defending,[])):
                raise ValueError(f"shot event {event['sequence']} goalie does not match defending on-ice state")
        if event.get("event_type")=="faceoff" and side in {"home","away"}:
            participants=event.get("participants",{})
            winner=participants.get("faceoff_winner_id")
            loser=participants.get("faceoff_loser_id")
            defending="away" if side=="home" else "home"
            if (winner is None or loser is None
                    or game["summary"]["player_totals"][str(winner)]["team_side"]!=side
                    or game["summary"]["player_totals"][str(loser)]["team_side"]!=defending):
                raise ValueError(f"faceoff participants do not match winning side at event {event['sequence']}")
    for number in (1,2,3):
        pe=[e for e in events if e["period_number"]==number]
        if not pe or pe[0]["event_type"]!="period-start" or \
                sum(e["event_type"]=="period-end" for e in pe)!=1:
            raise ValueError(f"regulation period {number} has incomplete boundaries")
        end_event=next(e for e in pe if e["event_type"]=="period-end")
        if pe[0]["clock_elapsed_seconds"]!=0 or end_event["clock_elapsed_seconds"]!=REG_SECONDS:
            raise ValueError(f"regulation period {number} has incorrect boundary clock")
        if pe[-1]["event_type"] not in ({"period-end"} if number<3 else {"period-end","game-end"}):
            raise ValueError(f"regulation period {number} has events after its terminal boundary")
    if sum(e["event_type"]=="game-end" for e in events)!=1:
        raise ValueError("generated game must have exactly one game-end event")
    summary=game["summary"]
    if score!=summary["official_final_score"] or sog!=summary["sog_event_counts"]:
        raise ValueError("generated score or SOG totals do not reconcile")
    if score["home"]==score["away"]:
        raise ValueError("generated regular-season game ended tied")
    for side in ("home","away"):
        team=summary["team_totals"][side]
        if team["goals"]!=summary["regulation_overtime_score"][side]:
            raise ValueError(f"{side} team goals disagree with reg/OT score")
        generated_attempts=sum(e["event_type"] in ATTEMPT_EVENTS and e["team_side"]==side for e in events)
        generated_sog=sum(e["event_type"] in SHOT_EVENTS and e["team_side"]==side and e["period_type"]!="SO" for e in events)
        generated_goals=sum(e["event_type"]=="goal" and e["team_side"]==side and e["period_type"]!="SO" for e in events)
        if team["shot_attempts"]!=generated_attempts or team["shots_on_goal"]!=generated_sog:
            raise ValueError(f"{side} team shot totals do not reconcile with event stream")
        if generated_goals!=team["goals"]:
            raise ValueError(f"{side} team goal total does not reconcile with event stream")
        player_goals=sum(p["goals"] for p in summary["player_totals"].values() if p["team_side"]==side)
        if player_goals!=team["goals"]:
            raise ValueError(f"{side} player goals do not reconcile with team score")
    player_goal_sum=sum(p["goals"] for p in summary["player_totals"].values())
    player_assist_sum=sum(p["assists"] for p in summary["player_totals"].values())
    player_attempt_sum=sum(p["shot_attempts"] for p in summary["player_totals"].values())
    player_sog_sum=sum(p["shots_on_goal"] for p in summary["player_totals"].values())
    if player_goal_sum!=sum(summary["regulation_overtime_score"].values()):
        raise ValueError("player goals do not reconcile with reg/OT team goals")
    if player_attempt_sum!=sum(t["shot_attempts"] for t in summary["team_totals"].values()):
        raise ValueError("player shot attempts do not reconcile with team attempts")
    if player_sog_sum!=sum(t["shots_on_goal"] for t in summary["team_totals"].values()):
        raise ValueError("player SOG do not reconcile with team SOG")
    if player_assist_sum>2*player_goal_sum:
        raise ValueError("player assists exceed two per generated goal")
    for pid,player in summary["player_totals"].items():
        if player["goals"]>player["shots_on_goal"] or player["assists"]>summary["team_totals"][player["team_side"]]["goals"]:
            raise ValueError(f"player scoring totals invalid for {pid}")
    for goalie in summary["goalie_totals"].values():
        if goalie["saves"]+goalie["goals_against"]!=goalie["shots_against"]:
            raise ValueError("goalie shots-against do not reconcile to saves plus goals")
    ledger_by_player=collections.Counter()
    for row in game.get("shift_ledger",[]):
        pid=str(row["player_id"])
        if pid not in summary["player_totals"]:
            raise ValueError(f"shift ledger has player outside the pregame roster: {pid}")
        ledger_by_player[pid]+=int(row["duration_seconds"])
    for pid,player in summary["player_totals"].items():
        if player["time_on_ice_seconds"]!=ledger_by_player[pid]:
            raise ValueError(f"player TOI does not reconcile with shift ledger for {pid}")


def generate_game(corpus: Any, inputs: PregameInputs, seed: int,
                  shift_manifest: dict[str,dict[str,str]],
                  quality_model: ShotQualityModel,
                  transition_model: EventTransitionModel|None=None) -> dict[str,Any]:
    rng=random.Random(seed)
    transition_rng=random.Random(seed ^ 0x9E3779B9)
    regs={n:v01._period_refs(corpus,"REG",n) for n in (1,2,3)}
    if any(not refs for refs in regs.values()):
        raise ValueError("training pool lacks a complete regulation period set")
    used:set[str]=set(); donors=[]; plays=[]
    donor_quarantine_counts=collections.Counter(); donor_quarantine_examples=[]
    goalie_plan={"home":sample_goalie_plan(rng,inputs.home_roster),
                 "away":sample_goalie_plan(rng,inputs.away_roster)}
    def quarantine_donor(game: Any, period_type: str, period_number: int, exc: DonorDataError) -> None:
        donor_quarantine_counts[exc.reason]+=1
        if len(donor_quarantine_examples)<20:
            donor_quarantine_examples.append({"game_id":game.game_id,"period_type":period_type,
                "period_number":period_number,"reason":exc.reason,"detail":str(exc)})
    for number in (1,2,3):
        while True:
            game,period=choose_weighted_period(rng,regs[number],used,
                float(inputs.snapshot["team_expected_sog"]["home"]),
                float(inputs.snapshot["team_expected_sog"]["away"]),number)
            used.add(game.game_id)
            try:
                donor=prepare_donor_period(game,"REG",number,corpus.data_root,shift_manifest,inputs,goalie_plan)
                _add_shift_totals(_empty_player_totals(inputs),donor)
                period_plays=prepare_source_period(donor,inputs,goalie_plan,quality_model,rng)
            except DonorDataError as exc:
                quarantine_donor(game,"REG",number,exc)
                continue
            plays.extend(period_plays); donors.append((game,donor,period))
            break
    offsets=calibrate_fivevfive_offsets(plays,inputs,quality_model)
    score={"home":0,"away":0}; sog={"home":0,"away":0}
    events=[]; player_totals=_empty_player_totals(inputs); shift_ledger=[]
    state={"penalties":PenaltyLedger(),"possession":None,
           "last_transition_family":"start",
           "transition_family_counts":collections.Counter(),
           "transition_fallback_counts":collections.Counter(),
           "transition_owner_fallback_counts":collections.Counter(),
           "rule_forced_faceoffs":0}
    team_totals={s:{"goals":0,"shots_on_goal":0,"shot_attempts":0,"faceoffs_won":0,
                    "penalties":0,"hits":0} for s in ("home","away")}
    goalie_totals={pid:{"team_side":side,"saves":0,"shots_against":0,"goals_against":0}
                   for side,r in (("home",inputs.home_roster),("away",inputs.away_roster))
                   for pid in r.goalie_ids}
    donor_blocks=[]
    for number,(game,donor,period) in zip((1,2,3),donors):
        state["possession"]=None
        state["last_transition_family"]="start"
        initial_penalties=state["penalties"].clone()
        _append_sim_event(events,score,sog,period_number=number,period_type="REG",event_type="period-start",
                          team_side=None,elapsed=0,duration=REG_SECONDS)
        period_plays=[p for p in plays if p.donor is donor]
        _emit_simulated_period(events,score,sog,team_totals,player_totals,goalie_totals,
                               period_plays,inputs,quality_model,rng,offsets,state,
                               transition_model=transition_model,transition_rng=transition_rng)
        _append_sim_event(events,score,sog,period_number=number,period_type="REG",event_type="period-end",
                          team_side=None,elapsed=REG_SECONDS,duration=REG_SECONDS)
        live_rows=_state_reconciled_shift_ledger(donor,events,inputs,initial_penalties)
        for row in live_rows:
            row["period_type"]="REG"
        _add_reconciled_shift_totals(player_totals,live_rows)
        shift_ledger.extend(live_rows)
        donor_blocks.append({"game_id":game.game_id,"period_type":"REG","period_number":number,
            "pbp_sha256":game.compressed_sha256,"boxscore_sha256":game.boxscore_compressed_sha256,
            "shift_sha256":donor.source_shift_sha256,
            "shift_rows_quarantined":donor.shift_rows_quarantined})
    shootout_winner=None; overtime=False
    if score["home"]==score["away"]:
        overtime=True
        while True:
            ot_refs=[(g,g.periods[("OT",4)]) for g in corpus.games.values()
                     if v01._eligible_game(g) and ("OT",4) in g.periods and g.game_id not in used]
            if not ot_refs:
                raise ValueError("training pool has no unused eligible overtime template after shift quarantine")
            ot_game,_=rng.choice(ot_refs); used.add(ot_game.game_id)
            try:
                ot_donor=prepare_donor_period(ot_game,"OT",4,corpus.data_root,shift_manifest,inputs,goalie_plan)
                _add_shift_totals(_empty_player_totals(inputs),ot_donor)
                ot_plays=prepare_source_period(ot_donor,inputs,goalie_plan,quality_model,rng)
            except DonorDataError as exc:
                quarantine_donor(ot_game,"OT",4,exc)
                continue
            break
        _append_sim_event(events,score,sog,period_number=4,period_type="OT",event_type="period-start",
                          team_side=None,elapsed=0,duration=OT_SECONDS)
        state["possession"]=None
        state["last_transition_family"]="start"
        initial_penalties=state["penalties"].clone()
        ended=_emit_simulated_period(events,score,sog,team_totals,player_totals,goalie_totals,
                    ot_plays,inputs,quality_model,rng,offsets,state,
                    transition_model=transition_model,transition_rng=transition_rng,
                    stop_after_goal=True)
        live_rows=_state_reconciled_shift_ledger(ot_donor,events,inputs,initial_penalties)
        for row in live_rows:
            row["period_type"]="OT"
        _add_reconciled_shift_totals(player_totals,live_rows)
        shift_ledger.extend(live_rows)
        donor_blocks.append({"game_id":ot_game.game_id,"period_type":"OT","period_number":4,
            "pbp_sha256":ot_game.compressed_sha256,"boxscore_sha256":ot_game.boxscore_compressed_sha256,
            "shift_sha256":ot_donor.source_shift_sha256,
            "shift_rows_quarantined":ot_donor.shift_rows_quarantined})
        if not ended:
            _append_sim_event(events,score,sog,period_number=4,period_type="OT",event_type="period-end",
                              team_side=None,elapsed=OT_SECONDS,duration=OT_SECONDS)
            shootout_winner=_shootout(events,score,sog,player_totals,goalie_totals,inputs,
                                      quality_model,goalie_plan,rng)
    else:
        _append_sim_event(events,score,sog,period_number=3,period_type="REG",event_type="game-end",
                          team_side=None,elapsed=REG_SECONDS,duration=REG_SECONDS)
    events=_insert_goalie_substitutions(events,shift_ledger,player_totals,inputs)
    reg_ot_score={side:score[side]-(1 if shootout_winner==side else 0) for side in ("home","away")}
    event_counts=collections.Counter(e["event_type"] for e in events)
    summary={"regulation_overtime_score":reg_ot_score,"official_final_score":dict(score),
        "shootout_winner":shootout_winner,"winner":"home" if score["home"]>score["away"] else "away",
        "sog_event_counts":dict(sog),"team_totals":team_totals,"player_totals":player_totals,
        "goalie_totals":{pid:stats for pid,stats in goalie_totals.items() if stats["shots_against"] or
                         any(e.get("participants",{}).get("goalie_id")==pid for e in events)},
        "event_counts":dict(sorted(event_counts.items())),"event_count":len(events),
        "unsupported_penalty_omissions":sum(bool((e.get("details") or {}).get("unsupported_penalty_omitted"))
                                             for e in events),
        "event_transition_diagnostics":{"sampled_family_counts":dict(sorted(state["transition_family_counts"].items())),
            "family_fallback_levels":dict(sorted(state["transition_fallback_counts"].items())),
            "owner_fallback_levels":dict(sorted(state["transition_owner_fallback_counts"].items())),
            "rule_forced_faceoffs":state["rule_forced_faceoffs"]},
        "shot_conversion_calibration":offsets}
    model_version=TRANSITION_MODEL_VERSION if transition_model is not None else MODEL_VERSION
    clock_limitation=(
        "B2 samples event families and acting sides conditionally at donor event slots; donor event count, clock slots, and shift intervals remain fixed scaffolding. Event-arrival intensity is not independently generated."
        if transition_model is not None else
        "B1 retains donor event families, event clocks, and shift intervals; only selected team, possession, penalty, goalie, and shot-outcome state is changed."
    )
    result={"schema_version":"nhl-statistical-pbp-v0.2b",
        "mode":"hypothetical_team_and_player_conditioned_statistical_simulation",
        "candidate_block":"B2" if transition_model is not None else "B1",
        "simulation_id":f"nhlstat-v0.2b-{inputs.game_key}-seed-{seed}","model_version":model_version,
        "seed":seed,"teams":{"home":inputs.home_team,"away":inputs.away_team},
        "pregame_snapshot":inputs.snapshot,
        "rules_profile":{"competition":"regular_season","regulation_periods":3,
            "regulation_period_seconds":REG_SECONDS,"overtime_period_seconds":OT_SECONDS,
            "three_on_three_overtime":True,"shootout_after_tied_overtime":True,
            "shootout_deciding_attempt_adds_one_official_final_score_goal":True},
        "provenance":{"pbp_manifest_sha256":v01.EXPECTED_MANIFEST_SHA256,
            "boxscore_manifest_sha256":v01.EXPECTED_BOXSCORE_MANIFEST_SHA256,
            "shift_manifest_sha256":SHIFT_MANIFEST_SHA256,
            "training_start_seasons":[2019,2020],"development_season_excluded":2021,
            "exposed_holdout_season_excluded":2022,"source_quality_quarantine_season":2018,
            "component_eligibility":"PBP and boxscore eligible under frozen v0.1 audit; shift body hash-verified; positive-duration shift identities must resolve through same-game PBP rosterSpots",
            "event_transition_model":transition_model.manifest() if transition_model is not None else None,
            "sampled_period_templates":donor_blocks,"data_root_outside_repository":str(corpus.data_root),
            "donor_period_quarantine":{"rejected_count":sum(donor_quarantine_counts.values()),
                "reason_counts":dict(sorted(donor_quarantine_counts.items())),
                "examples":donor_quarantine_examples}},
        "goalie_plan":{"home":goalie_plan["home"],"away":goalie_plan["away"],
            "status":"uncertain sampled starter and backup from pregame roster/start history; not confirmed"},
        "events":events,"shift_ledger":shift_ledger,"summary":summary,"record_complete":True,
        "limitations":[
            clock_limitation,
            "Only 5v5 regulation attempt outcomes are resampled using pregame team SOG and goal priors. Other strengths retain sampled training-template outcomes.",
            "Penalty queueing beyond two concurrent manpower penalties is unsupported; a third such donor event is preserved as a stoppage with an explicit omission record and count.",
            "Roster identities are remapped to the current pregame roster by role and usage rank; historical target-game lineups are not used.",
            "Goalie starter is uncertain. A sampled backup may enter only where the donor shift template contains a goalie change; no target-game starter is used.",
            "Possession, passing, tactics, fatigue, shot coordinates, and physics are not causally simulated; donor shot locations are illustrative training observations.",
            "This is a research prototype, not an independently validated NHL prediction model." ]}
    validate_generated_game(result)
    return result


def _quantile(values: list[float], probability: float) -> float:
    ordered=sorted(values)
    if not ordered:
        raise ValueError("cannot summarize an empty Monte Carlo sample")
    position=(len(ordered)-1)*probability
    lo=int(math.floor(position)); hi=int(math.ceil(position))
    if lo==hi:
        return ordered[lo]
    return ordered[lo]*(hi-position)+ordered[hi]*(position-lo)


def _wilson_interval(successes: int, n: int) -> list[float]:
    if n<=0:
        raise ValueError("Wilson interval requires at least one simulation")
    z=1.959963984540054; p=successes/n; denom=1+z*z/n
    center=(p+z*z/(2*n))/denom
    half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/denom
    return [max(0.0,center-half),min(1.0,center+half)]


def simulate_matchup(corpus: Any, inputs: PregameInputs, seed: int, simulations: int,
                     shift_manifest: dict[str,dict[str,str]],
                     quality_model: ShotQualityModel,
                     transition_model: EventTransitionModel|None=None) -> dict[str,Any]:
    if simulations<1:
        raise ValueError("simulation count must be positive")
    started=time.monotonic()
    examples=[]
    home_goals=[]; away_goals=[]; home_final=[]; away_final=[]
    home_sog=[]; away_sog=[]; total_attempts=[]
    overtime=shootouts=home_wins=0
    donor_quarantine_counts=collections.Counter(); donor_quarantine_examples=[]
    accepted_shift_rows_quarantined=0
    player_acc: dict[str,dict[str,Any]]=collections.defaultdict(lambda:collections.defaultdict(float))
    goalie_acc: dict[str,dict[str,Any]]=collections.defaultdict(lambda:collections.defaultdict(float))
    starter_counts=collections.Counter()
    transition_family_counts=collections.Counter()
    transition_fallback_counts=collections.Counter()
    transition_owner_fallback_counts=collections.Counter()
    unsupported_penalty_omissions=0
    for index in range(simulations):
        game_seed=seed+index
        game=generate_game(corpus,inputs,game_seed,shift_manifest,quality_model,transition_model)
        game_quarantine=game["provenance"]["donor_period_quarantine"]
        donor_quarantine_counts.update(game_quarantine["reason_counts"])
        accepted_shift_rows_quarantined+=sum(
            int(block["shift_rows_quarantined"])
            for block in game["provenance"]["sampled_period_templates"])
        for example in game_quarantine["examples"]:
            if len(donor_quarantine_examples)<20:
                donor_quarantine_examples.append(example)
        if index==0:
            examples.append(game)
        summary=game["summary"]
        transition_diagnostics=summary["event_transition_diagnostics"]
        transition_family_counts.update(transition_diagnostics["sampled_family_counts"])
        transition_fallback_counts.update(transition_diagnostics["family_fallback_levels"])
        transition_owner_fallback_counts.update(transition_diagnostics["owner_fallback_levels"])
        unsupported_penalty_omissions+=int(summary["unsupported_penalty_omissions"])
        h=summary["official_final_score"]["home"]; a=summary["official_final_score"]["away"]
        home_final.append(float(h)); away_final.append(float(a))
        home_goals.append(float(summary["regulation_overtime_score"]["home"]))
        away_goals.append(float(summary["regulation_overtime_score"]["away"]))
        home_sog.append(float(summary["sog_event_counts"]["home"]))
        away_sog.append(float(summary["sog_event_counts"]["away"]))
        total_attempts.append(float(sum(t["shot_attempts"] for t in summary["team_totals"].values())))
        home_wins+=int(summary["winner"]=="home")
        overtime+=int(any(e["period_type"]=="OT" for e in game["events"]))
        shootouts+=int(summary["shootout_winner"] is not None)
        for pid,stats in summary["player_totals"].items():
            agg=player_acc[pid]
            for key in ("goals","assists","shots_on_goal","shot_attempts","time_on_ice_seconds"):
                agg[key]+=float(stats[key])
            agg["name"]=stats["name"]; agg["team_side"]=stats["team_side"]; agg["position"]=stats["position"]
        for pid,stats in summary["goalie_totals"].items():
            agg=goalie_acc[pid]
            for key in ("saves","shots_against","goals_against"):
                agg[key]+=float(stats[key])
            agg["team_side"]=stats["team_side"]
        for side in ("home","away"):
            starter_counts[f"{side}:{game['goalie_plan'][side][0]}"]+=1
    n=simulations
    player_means=[]
    for pid,values in player_acc.items():
        player_means.append({"player_id":pid,"name":values["name"],"team_side":values["team_side"],
            "position":values["position"],"mean_goals":values["goals"]/n,
            "mean_assists":values["assists"]/n,"mean_shots_on_goal":values["shots_on_goal"]/n,
            "mean_shot_attempts":values["shot_attempts"]/n,"mean_toi_minutes":values["time_on_ice_seconds"]/n/60})
    goalie_means=[]
    for pid,values in goalie_acc.items():
        goalie_means.append({"goalie_id":pid,"team_side":values["team_side"],
            "mean_saves":values["saves"]/n,"mean_shots_against":values["shots_against"]/n,
            "mean_goals_against":values["goals_against"]/n,
            "save_rate":values["saves"]/max(1.0,values["shots_against"])})
    team_prediction={}
    for side,goals,sog_values in (("home",home_goals,home_sog),("away",away_goals,away_sog)):
        team_prediction[side]={"mean_goals":statistics.fmean(goals),
            "goal_predictive_interval_95":[_quantile(goals,.025),_quantile(goals,.975)],
            "mean_official_final_score_goals":statistics.fmean(home_final if side=="home" else away_final),
            "mean_sog":statistics.fmean(sog_values),
            "sog_predictive_interval_95":[_quantile(sog_values,.025),_quantile(sog_values,.975)],
            "pregame_goal_prior":inputs.mu_home if side=="home" else inputs.mu_away,
            "pregame_sog_prior":float(inputs.snapshot["team_expected_sog"][side])}
    top_players=sorted(player_means,key=lambda x:(-x["mean_goals"],-x["mean_assists"],x["player_id"]))
    summary={"simulation_count":n,"base_seed":seed,"seed_rule":"seed + zero-based simulation index",
        "winner_probability":{"home":home_wins/n,"away":1-home_wins/n,
            "home_95pct_monte_carlo_interval":_wilson_interval(home_wins,n)},
        "team_prediction":team_prediction,
        "total_goal_mean_regulation_overtime":statistics.fmean(home_goals)+statistics.fmean(away_goals),
        "total_goal_predictive_interval_95":[_quantile([h+a for h,a in zip(home_goals,away_goals)],.025),
                                               _quantile([h+a for h,a in zip(home_goals,away_goals)],.975)],
        "total_goal_mean_official_final_score":statistics.fmean(home_final)+statistics.fmean(away_final),
        "mean_total_sog":statistics.fmean(home_sog)+statistics.fmean(away_sog),
        "mean_shot_attempts":statistics.fmean(total_attempts),
        "overtime_probability":overtime/n,"shootout_probability":shootouts/n,
        "event_transition_diagnostics":{"sampled_family_counts":dict(sorted(transition_family_counts.items())),
            "family_fallback_levels":dict(sorted(transition_fallback_counts.items())),
            "owner_fallback_levels":dict(sorted(transition_owner_fallback_counts.items())),
            "unsupported_penalty_omissions":unsupported_penalty_omissions},
        "team_stat_priors":{"home_goals":inputs.mu_home,"away_goals":inputs.mu_away,
            "home_sog":inputs.snapshot["team_expected_sog"]["home"],
            "away_sog":inputs.snapshot["team_expected_sog"]["away"]},
        "top_player_projections":top_players[:20],"goalie_projections":sorted(goalie_means,key=lambda x:x["goalie_id"]),
        "sampled_starter_frequency":dict(sorted(starter_counts.items())),
        "donor_period_quarantine":{"rejected_period_count":sum(donor_quarantine_counts.values()),
            "reason_counts":dict(sorted(donor_quarantine_counts.items())),
            "examples_capped_at_20":donor_quarantine_examples},
        "accepted_donor_shift_rows_quarantined":accepted_shift_rows_quarantined,
        "monte_carlo_uncertainty_note":"Wilson interval applies only to simulated home-win frequency; goal/SOG quantiles describe the model's predictive distribution, not parameter uncertainty."}
    model_version=TRANSITION_MODEL_VERSION if transition_model is not None else MODEL_VERSION
    return {"schema_version":"nhl-statistical-full-game-distribution-v0.2b",
        "candidate_block":"B2" if transition_model is not None else "B1",
        "model_version":model_version,"teams":{"home":inputs.home_team,"away":inputs.away_team},
        "event_transition_model":transition_model.manifest() if transition_model is not None else None,
        "pregame_snapshot":inputs.snapshot,"simulation_count":n,"base_seed":seed,
        "summary":summary,"example_game":examples[0],
        "runtime_seconds":round(time.monotonic()-started,3)}


def _write_json(path: Path, value: dict[str,Any]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,sort_keys=True)+"\n",encoding="utf-8")


def main(argv: list[str]|None=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root",type=Path,default=v01.DEFAULT_DATA_ROOT)
    parser.add_argument("--db",type=Path,default=DEFAULT_DB)
    parser.add_argument("--game-key",required=True)
    parser.add_argument("--game-date",required=True)
    parser.add_argument("--start-utc",required=True)
    parser.add_argument("--as-of-utc",required=True)
    parser.add_argument("--home-team",required=True)
    parser.add_argument("--away-team",required=True)
    parser.add_argument("--seed",type=int,default=31415)
    parser.add_argument("--simulations",type=int,default=1)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args(argv)
    started=time.monotonic()
    corpus=v01.load_corpus(args.data_root,v01.TRAIN_SEASONS)
    if not any(v01._eligible_game(g) for g in corpus.games.values()):
        raise ValueError("no eligible training games remain")
    shift_manifest=load_shift_manifest()
    model=fit_shot_quality(corpus)
    inputs=prepare_pregame(args.db,game_key=args.game_key,game_date=args.game_date,
        start_utc=args.start_utc,as_of_utc=args.as_of_utc,home=args.home_team,away=args.away_team)
    result=simulate_matchup(corpus,inputs,args.seed,args.simulations,shift_manifest,model)
    result["runtime_seconds"]=round(time.monotonic()-started,3)
    _write_json(args.out,result)
    print(json.dumps({"output":str(args.out),"simulation_count":result["simulation_count"],
        "winner_probability":result["summary"]["winner_probability"],
        "mean_goals":{"home":result["summary"]["team_prediction"]["home"]["mean_goals"],
                      "away":result["summary"]["team_prediction"]["away"]["mean_goals"]},
        "training_eligible_games":corpus.eligible_by_season,"shift_manifest_games":4876,
        "runtime_seconds":result["runtime_seconds"]},sort_keys=True))
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (OSError,ValueError,KeyError,json.JSONDecodeError,sqlite3.Error) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        raise SystemExit(2)
