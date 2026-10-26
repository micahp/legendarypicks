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


ROOT = Path(__file__).resolve().parents[3]
V01_PATH = ROOT / "research/nhl/statistical-full-game-v0.1/nhl_statistical_game.py"
spec = importlib.util.spec_from_file_location("nhl_v01_frozen", V01_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load frozen v0.1 module at {V01_PATH}")
v01 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v01
spec.loader.exec_module(v01)

MODEL_VERSION = "nhl-team-conditioned-shift-player-v0.2-alpha2"
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
    path = SHIFT_RAW / f"{game_id}.json.gz"
    if path.stat().st_size != int(row["bytes_gz"]):
        raise ValueError(f"{game_id}: shift body compressed size differs from manifest")
    digest = sha256_file(path)
    if digest != row["sha256_gz"]:
        raise ValueError(f"{game_id}: shift body hash differs from manifest")
    with gzip.open(path, "rt", encoding="utf-8") as f:
        doc = json.load(f)
    if int(doc.get("total", -1)) != len(doc.get("data", [])):
        raise ValueError(f"{game_id}: shift response total does not reconcile")
    return doc


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


def load_b3_team_means(home: str, away: str, game_date: str, neutral_site: bool = False) -> tuple[float,float,dict[str,Any]]:
    if not FORECASTS.is_file() or not FROZEN_MODELS.is_file():
        raise FileNotFoundError("frozen NHL B3 model and prospective feature ledger are required")
    model = json.loads(FROZEN_MODELS.read_text())
    rows = []
    with FORECASTS.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row.get("model_name") != "B3_elo" or str(row.get("game_date", "")) >= game_date:
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
    mu_home,mu_away,team_model=load_b3_team_means(home,away,game_date,neutral_site)
    shot_home=(home_roster.expected_sog+away_roster.expected_sog_against)/2
    shot_away=(away_roster.expected_sog+home_roster.expected_sog_against)/2
    log_max_date=max(home_roster.coverage["pregame_log_max_date"] or "",
                     away_roster.coverage["pregame_log_max_date"] or "") or None
    snapshot={"schema":"PregameGameSnapshot-v0.2-alpha2","game_key":game_key,"game_date":game_date,
        "scheduled_start_utc":start.isoformat().replace("+00:00","Z"),"capture_cutoff_utc":cutoff.isoformat().replace("+00:00","Z"),
        "home_team":home,"away_team":away,"neutral_site":neutral_site,
        "roster_snapshot_id":home_roster.coverage["snapshot_id"],"roster_snapshot_source":"nhle.com:roster",
        "roster_snapshot_capture_utc":home_roster.coverage["snapshot_captured_at_utc"],
        "roster_snapshot_checksum":home_roster.coverage["snapshot_checksum"],
        "prior_player_stats_season":2026,"current_season_player_logs_used_through":log_max_date,
        "home_roster_hash":home_roster.profile_hash,"away_roster_hash":away_roster.profile_hash,
        "home_roster_coverage":home_roster.coverage,"away_roster_coverage":away_roster.coverage,
        "team_model":team_model,"team_expected_goals":{"home":mu_home,"away":mu_away},
        "team_expected_sog":{"home":shot_home,"away":shot_away},
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
    used_games=0
    events_used=0
    raw_dir=corpus.data_root/"raw"/"pbp"
    for game in corpus.games.values():
        if not v01._eligible_game(game):
            continue
        doc=v01._read_verified_source_game(game,raw_dir)
        sides=v01._source_side_map(doc)
        home_id=str(doc["homeTeam"]["id"])
        for event in doc.get("plays",[]):
            et=event.get("typeDescKey")
            pdesc=event.get("periodDescriptor") or {}
            if pdesc.get("periodType")=="SO" and et in ATTEMPT_EVENTS:
                shootout_attempts+=1
                shootout_goals+=int(et=="goal")
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
    return ShotQualityModel(global_p,probs,normalized_counts,open_p,reg_share,fivevfive_share,
                            fivevfive_sog_share,assist_probs,attempt_probs,so_rate,used_games,events_used)


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
    pbp=v01._read_verified_source_game(game,data_root/"raw"/"pbp")
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
    for raw in v01._source_period_events(donor.pbp,donor.period_type,donor.period_number):
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
                    goalie_goal_rate=max(.02,1.0-goalie.save_pct)
                    goalie_logit_delta=-.20*(_logit(goalie_goal_rate)-_logit(model.global_goal_rate))
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
            penalized=_choose_weighted(rng,candidates,[1/max(1,p.usage_minutes) for p in candidates])
            participants["penalized_player_id"]=penalized.nhl_id
            participants["penalized_player_name"]=penalized.name
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


def _emit_simulated_period(events: list[dict[str,Any]], score: dict[str,int], sog: dict[str,int],
                           team_totals: dict[str,dict[str,int]], player_totals: dict[str,dict[str,Any]],
                           goalie_totals: dict[str,dict[str,int]], plays: list[SimPlay],
                           inputs: PregameInputs, model: ShotQualityModel, rng: random.Random,
                           *, stop_after_goal: bool=False) -> bool:
    side_roster={"home":inputs.home_roster,"away":inputs.away_roster}
    saw_goal=False
    for play in plays:
        side=play.team_side
        event_type=play.event_type
        participants=copy.deepcopy(play.participants)
        details=copy.deepcopy(play.details)
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
            if side in team_totals:
                team_totals[side]["faceoffs_won"]+=1
        elif event_type=="penalty":
            pid=participants.get("penalized_player_id")
            if pid in player_totals:
                player_totals[pid]["penalties"]+=1
            if side in team_totals:
                team_totals[side]["penalties"]+=1
        elif event_type=="hit":
            pid=participants.get("hitter_id")
            if pid in player_totals:
                player_totals[pid]["hits"]+=1
            if side in team_totals:
                team_totals[side]["hits"]+=1
        event=_append_sim_event(events,score,sog,period_number=play.donor.period_number,
            period_type=play.donor.period_type,event_type=event_type,team_side=side,
            elapsed=play.elapsed,duration=REG_SECONDS if play.donor.period_type=="REG" else OT_SECONDS,
            details=details,on_ice=play.active,strength=play.strength,participants=participants,
            score_goal=event_type=="goal",count_sog=event_type in SHOT_EVENTS)
        if event_type=="goal" and stop_after_goal:
            _append_sim_event(events,score,sog,period_number=play.donor.period_number,
                period_type=play.donor.period_type,event_type="game-end",team_side=None,
                elapsed=play.elapsed,duration=OT_SECONDS,details={"reason":"sudden_death_overtime_goal"})
            return True
    return saw_goal


def _shootout(events: list[dict[str,Any]], score: dict[str,int], sog: dict[str,int],
              player_totals: dict[str,dict[str,Any]], goalie_totals: dict[str,dict[str,int]],
              inputs: PregameInputs, model: ShotQualityModel, goalie_plan: dict[str,list[str]],
              rng: random.Random) -> str:
    attempts_by_side={"home":0,"away":0}; goals_by_side={"home":0,"away":0}
    _append_sim_event(events,score,sog,period_number=5,period_type="SO",event_type="period-start",
                      team_side=None,elapsed=0,duration=0)
    for round_number in range(1,54):
        for side in ("home","away"):
            roster=side_roster=inputs.home_roster if side=="home" else inputs.away_roster
            skaters=[p for p in roster.players.values() if p.position!="G"]
            shooter=_choose_weighted(rng,skaters,[max(.01,p.shot_rate) for p in skaters])
            defending="away" if side=="home" else "home"
            goalie_id=goalie_plan[defending][0]
            goalie=inputs.away_roster.players[goalie_id] if defending=="away" else inputs.home_roster.players[goalie_id]
            pgoal=_sigmoid(_logit(model.shootout_goal_rate)+
                .15*(_logit(shooter.finish_rate)-_logit(model.global_goal_rate))-
                .15*(_logit(max(.02,1.0-goalie.save_pct))-_logit(model.global_goal_rate)))
            result="goal" if rng.random()<pgoal else rng.choice(["saved","missed"])
            attempts_by_side[side]+=1
            player_totals[shooter.nhl_id]["shootout_attempts"]+=1
            if result=="goal":
                goals_by_side[side]+=1
                player_totals[shooter.nhl_id]["shootout_goals"]+=1
            _append_sim_event(events,score,sog,period_number=5,period_type="SO",event_type="shootout-attempt",
                team_side=side,elapsed=0,duration=0,
                details={"round":round_number,"attempt_number":attempts_by_side[side],"attempt_result":result},
                participants={"shooter_id":shooter.nhl_id,"goalie_id":goalie_id})
        if round_number>=3 and goals_by_side["home"]!=goals_by_side["away"]:
            break
        if round_number>=3 and attempts_by_side["home"]==attempts_by_side["away"] and round_number>3 and \
                goals_by_side["home"]!=goals_by_side["away"]:
            break
    if goals_by_side["home"]==goals_by_side["away"]:
        raise ValueError("shootout did not produce a winner within 53 paired rounds")
    winner="home" if goals_by_side["home"]>goals_by_side["away"] else "away"
    _append_sim_event(events,score,sog,period_number=5,period_type="SO",event_type="shootout-decision",
        team_side=winner,elapsed=0,duration=0,details={"official_bonus_goal":1,"player_goal":False},
        score_goal=True)
    _append_sim_event(events,score,sog,period_number=5,period_type="SO",event_type="period-end",
        team_side=None,elapsed=0,duration=0)
    _append_sim_event(events,score,sog,period_number=5,period_type="SO",event_type="game-end",
        team_side=None,elapsed=0,duration=0)
    return winner


def _insert_goalie_substitutions(events: list[dict[str,Any]], shift_ledger: list[dict[str,Any]],
                                player_totals: dict[str,dict[str,Any]]) -> list[dict[str,Any]]:
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
                counts={s:sum(player_totals[pid]["position"]!="G" for pid in ids)
                        for s,ids in on_ice.items()}
                details={"reason":"sampled_shift_template_goalie_transition",
                         "transition_source":"verified shift-chart interval boundary"}
                additions.append({"period_number":period,"period_type":"REG" if period<4 else "OT",
                    "time_in_period":f"{elapsed//60:02d}:{elapsed%60:02d}",
                    "time_remaining":f"{(limit-elapsed)//60:02d}:{(limit-elapsed)%60:02d}",
                    "clock_elapsed_seconds":elapsed,"clock_remaining_seconds":limit-elapsed,
                    "event_type":"goalie-substitution","team_side":side,"details":details,
                    "participants":{"goalie_leaving_id":old,"goalie_entering_id":new},
                    "on_ice":on_ice,"strength":f"{counts['home']}v{counts['away']}"})
    combined=events+additions
    combined.sort(key=lambda e:(e["period_number"],e["clock_elapsed_seconds"],
                                0 if e["event_type"]=="goalie-substitution" else 1))
    score={"home":0,"away":0}; sog={"home":0,"away":0}
    for sequence,event in enumerate(combined,1):
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


def validate_generated_game(game: dict[str,Any]) -> None:
    events=game["events"]
    if not events or [e["sequence"] for e in events]!=list(range(1,len(events)+1)):
        raise ValueError("generated NHL event sequence is empty or non-contiguous")
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
            shooter=event.get("participants",{}).get("shooter_id")
            if shooter is None:
                raise ValueError(f"shot event {event['sequence']} has no simulated shooter")
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
                  quality_model: ShotQualityModel) -> dict[str,Any]:
    rng=random.Random(seed)
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
    team_totals={s:{"goals":0,"shots_on_goal":0,"shot_attempts":0,"faceoffs_won":0,
                    "penalties":0,"hits":0} for s in ("home","away")}
    goalie_totals={pid:{"team_side":side,"saves":0,"shots_against":0,"goals_against":0}
                   for side,r in (("home",inputs.home_roster),("away",inputs.away_roster))
                   for pid in r.goalie_ids}
    donor_blocks=[]
    for number,(game,donor,period) in zip((1,2,3),donors):
        _append_sim_event(events,score,sog,period_number=number,period_type="REG",event_type="period-start",
                          team_side=None,elapsed=0,duration=REG_SECONDS)
        period_plays=[p for p in plays if p.donor is donor]
        _emit_simulated_period(events,score,sog,team_totals,player_totals,goalie_totals,
                               period_plays,inputs,quality_model,rng)
        _append_sim_event(events,score,sog,period_number=number,period_type="REG",event_type="period-end",
                          team_side=None,elapsed=REG_SECONDS,duration=REG_SECONDS)
        _add_shift_totals(player_totals,donor)
        shift_ledger.extend([{**row,"period_type":"REG"} for row in donor.shift_ledger])
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
        ended=_emit_simulated_period(events,score,sog,team_totals,player_totals,goalie_totals,
                    ot_plays,inputs,quality_model,rng,stop_after_goal=True)
        _add_shift_totals(player_totals,ot_donor)
        shift_ledger.extend([{**row,"period_type":"OT"} for row in ot_donor.shift_ledger])
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
    events=_insert_goalie_substitutions(events,shift_ledger,player_totals)
    reg_ot_score={side:score[side]-(1 if shootout_winner==side else 0) for side in ("home","away")}
    event_counts=collections.Counter(e["event_type"] for e in events)
    summary={"regulation_overtime_score":reg_ot_score,"official_final_score":dict(score),
        "shootout_winner":shootout_winner,"winner":"home" if score["home"]>score["away"] else "away",
        "sog_event_counts":dict(sog),"team_totals":team_totals,"player_totals":player_totals,
        "goalie_totals":{pid:stats for pid,stats in goalie_totals.items() if stats["shots_against"] or
                         any(e.get("participants",{}).get("goalie_id")==pid for e in events)},
        "event_counts":dict(sorted(event_counts.items())),"event_count":len(events),
        "shot_conversion_calibration":offsets}
    result={"schema_version":"nhl-statistical-pbp-v0.2-alpha2",
        "mode":"hypothetical_team_and_player_conditioned_statistical_simulation",
        "simulation_id":f"nhlstat-v0.2-{inputs.game_key}-seed-{seed}","model_version":MODEL_VERSION,
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
            "sampled_period_templates":donor_blocks,"data_root_outside_repository":str(corpus.data_root),
            "donor_period_quarantine":{"rejected_count":sum(donor_quarantine_counts.values()),
                "reason_counts":dict(sorted(donor_quarantine_counts.items())),
                "examples":donor_quarantine_examples}},
        "goalie_plan":{"home":goalie_plan["home"],"away":goalie_plan["away"],
            "status":"uncertain sampled starter and backup from pregame roster/start history; not confirmed"},
        "events":events,"shift_ledger":shift_ledger,"summary":summary,"record_complete":True,
        "limitations":[
            "Shot opportunities, event clocks and special-team transitions still come from sampled historical period templates; score-state and penalty transitions are not fully re-simulated.",
            "Only 5v5 regulation attempt outcomes are resampled using pregame team SOG and goal priors. Other strengths retain sampled training-template outcomes.",
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
                     quality_model: ShotQualityModel) -> dict[str,Any]:
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
    for index in range(simulations):
        game_seed=seed+index
        game=generate_game(corpus,inputs,game_seed,shift_manifest,quality_model)
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
    return {"schema_version":"nhl-statistical-full-game-distribution-v0.2-alpha2",
        "model_version":MODEL_VERSION,"teams":{"home":inputs.home_team,"away":inputs.away_team},
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
