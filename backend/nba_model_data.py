"""Pinned, published NBA team-game releases used by the Phase 1 research ladder.

The ESPN team-box release has ESPN event IDs and box-score fields. The separate
NBA Stats schedule release supplies the league's published game phase. They do
not share a game ID, so this module builds a strict, one-to-one crosswalk from
date, canonical home/away codes, and both final scores; ambiguous rows fail.
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from team_codes import UnknownTeamCode, is_canonical, normalize

ROOT = Path(__file__).resolve().parents[1]
SOURCE_MANIFEST = ROOT / "research" / "nba-game-model" / "sources.json"
TEAM_BOX_RELEASE = "espn_nba_team_boxscores"
SCHEDULE_RELEASE = "nba_stats_schedules"
REGULAR_PHASES = {"regular-season", "regular season", "regular"}
POSSESSION_FIELDS = ("field_goals_attempted", "free_throws_attempted", "offensive_rebounds")


class NBADataError(RuntimeError):
    """A pinned release or its game-identity crosswalk failed validation."""


@dataclass(frozen=True)
class TeamGame:
    game_id: str  # ESPN's stable event ID from team_box_{season}.parquet
    season: int  # SportsDataverse release season key: ending year
    game_date: str  # NBA Stats schedule's local game date, not ESPN UTC date
    home_team: str  # canonical ESPN team code
    away_team: str
    home_score: int
    away_score: int
    home_fga: float
    home_fta: float
    home_orb: float
    home_tov: float
    away_fga: float
    away_fta: float
    away_orb: float
    away_tov: float
    schedule_game_id: str  # NBA Stats game ID, retained for crosswalk audit

    @property
    def home_possessions(self) -> float:
        return estimated_possessions(self.home_fga, self.home_fta, self.home_orb, self.home_tov)

    @property
    def away_possessions(self) -> float:
        return estimated_possessions(self.away_fga, self.away_fta, self.away_orb, self.away_tov)


@dataclass
class ReleaseData:
    games: list[TeamGame]
    coverage: list[dict[str, Any]]
    asset_hashes: dict[str, str]


def estimated_possessions(fga: float, fta: float, orb: float, turnovers: float) -> float:
    """Standard box-score estimate: FGA + 0.44*FTA - OREB + TOV."""
    value = float(fga) + 0.44 * float(fta) - float(orb) + float(turnovers)
    if value <= 0:
        raise NBADataError(f"non-positive estimated possessions: {value}")
    return value


def _manifest() -> dict:
    return json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))


def ensure_source_assets(directory: str | Path, download: bool = False) -> dict[str, str]:
    """Verify pinned source assets; optionally fetch missing files serially."""
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for asset in _manifest()["assets"]:
        path = target / asset["file"]
        if not path.exists() and download:
            release = TEAM_BOX_RELEASE if asset["kind"] == "team_box" else SCHEDULE_RELEASE
            url = ("https://github.com/sportsdataverse/sportsdataverse-data/releases/download/"
                   f"{release}/{asset['file']}")
            request = urllib.request.Request(
                url, headers={"User-Agent": "LegendaryPicks-NBA-Game-Model/1.0"}
            )
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = response.read()
            except Exception as exc:  # noqa: BLE001 - include the pinned asset in the failure
                raise NBADataError(f"failed downloading {url}: {exc}") from exc
            path.write_bytes(payload)
        if not path.is_file():
            raise NBADataError(f"missing {asset['file']}; rerun with --download")
        payload_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if path.stat().st_size != asset["bytes"] or payload_hash != asset["sha256"]:
            raise NBADataError(
                f"pinned asset mismatch for {asset['file']}: bytes={path.stat().st_size} "
                f"sha256={payload_hash}"
            )
        hashes[asset["file"]] = payload_hash
    return hashes


def _read_parquet(path: Path) -> list[dict[str, Any]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise NBADataError("pyarrow is required only for the research release loader") from exc
    try:
        return pq.read_table(path).to_pylist()
    except Exception as exc:  # noqa: BLE001
        raise NBADataError(f"invalid Parquet asset {path.name}: {exc}") from exc


def _team_code(value: Any, context: str) -> str:
    try:
        return normalize("nba", str(value or ""))
    except UnknownTeamCode as exc:
        raise NBADataError(f"{context}: {exc}") from exc


def _number(row: dict[str, Any], field: str, context: str) -> float:
    value = row.get(field)
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise NBADataError(f"{context}: missing/non-numeric {field}={value!r}") from exc
    if not result >= 0:
        raise NBADataError(f"{context}: invalid {field}={value!r}")
    return result


def _turnovers(row: dict[str, Any], season: int) -> float | None:
    """Use the release's aggregate TOV field, with the 2017-18 legacy field fallback."""
    if row.get("total_turnovers") is not None:
        return float(row["total_turnovers"])
    if season == 2018 and row.get("turnovers") is not None:
        # The 2017-18 asset predates the team_turnovers/total_turnovers split;
        # its sole published turnovers field is the team aggregate.
        return float(row["turnovers"])
    return None


def _phase(row: dict[str, Any]) -> str:
    return str(row.get("season_type") or "").strip().lower()


def _date(value: Any, context: str) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError) as exc:
        raise NBADataError(f"{context}: invalid game_date={value!r}") from exc


def _crosswalk_schedule(schedule_rows: list[dict[str, Any]], season: int):
    """Index NBA schedule rows by canonical team pair; reject ambiguous identities."""
    by_pair: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    regular_count = 0
    for row in schedule_rows:
        if int(row.get("season") or 0) != season:
            raise NBADataError(f"schedule row {row.get('game_id')} has wrong season key")
        phase = _phase(row)
        try:
            home = _team_code(row.get("home_team_abbreviation"), "NBA Stats schedule")
            away = _team_code(row.get("away_team_abbreviation"), "NBA Stats schedule")
        except NBADataError:
            # Unknown codes are acceptable only on published non-regular phases
            # such as preseason opponents and All-Star sides.
            if phase in REGULAR_PHASES or phase in {"nba-cup", "cup"}:
                raise
            continue
        if not is_canonical("nba", home) or not is_canonical("nba", away):
            if phase in REGULAR_PHASES or phase in {"nba-cup", "cup"}:
                raise NBADataError(
                    f"non-franchise code in competitive schedule game {row.get('game_id')}"
                )
            continue
        game_date = _date(row.get("game_date"), f"schedule {row.get('game_id')}")
        row = dict(row, _home=home, _away=away, _date=game_date)
        if phase in REGULAR_PHASES:
            if row.get("home_pts") is None or row.get("away_pts") is None:
                raise NBADataError(f"regular schedule game {row.get('game_id')} has no final score")
            regular_count += 1
        by_pair[(home, away)].append(row)
    seen_schedule_ids: set[str] = set()
    for rows in by_pair.values():
        for row in rows:
            game_id = str(row.get("game_id") or "")
            if not game_id or game_id in seen_schedule_ids:
                raise NBADataError(f"missing/duplicate NBA Stats game id {game_id!r}")
            seen_schedule_ids.add(game_id)
    return by_pair, regular_count


def _boxscore_games(box_rows: list[dict[str, Any]], season: int):
    """Pair franchise team rows by ESPN event ID; all-star games are excluded."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in box_rows:
        if int(row.get("season") or 0) != season:
            raise NBADataError(f"boxscore row {row.get('game_id')} has wrong season key")
        if int(row.get("season_type") or 0) != 2:
            continue
        grouped[str(row.get("game_id") or "")].append(row)

    games = {}
    for game_id, rows in grouped.items():
        if not game_id or len(rows) != 2:
            raise NBADataError(f"ESPN event {game_id!r} has {len(rows)} franchise team rows")
        sides = {str(row.get("team_home_away") or "").lower(): row for row in rows}
        if set(sides) != {"home", "away"}:
            raise NBADataError(f"ESPN event {game_id} does not have one home and one away row")
        home, away = sides["home"], sides["away"]
        try:
            home_code = _team_code(home.get("team_abbreviation"), f"ESPN event {game_id}")
        except NBADataError:
            home_code = None
        try:
            away_code = _team_code(away.get("team_abbreviation"), f"ESPN event {game_id}")
        except NBADataError:
            away_code = None
        home_is_franchise = bool(home_code and is_canonical("nba", home_code))
        away_is_franchise = bool(away_code and is_canonical("nba", away_code))
        if not home_is_franchise and not away_is_franchise:
            # SportsDataverse/ESPN file All-Star exhibitions under season_type=2.
            continue
        if not home_is_franchise or not away_is_franchise:
            raise NBADataError(f"ESPN event {game_id} mixes an NBA franchise and non-franchise side")
        home = dict(home, _team=home_code)
        away = dict(away, _team=away_code)
        if home["_team"] == away["_team"]:
            raise NBADataError(f"ESPN event {game_id} has the same team on both sides")
        home_score, away_score = int(home["team_score"]), int(away["team_score"])
        if (home_score != int(away["opponent_team_score"])
                or away_score != int(home["opponent_team_score"])):
            raise NBADataError(f"ESPN event {game_id} has inconsistent reciprocal scores")
        for row in (home, away):
            missing = [key for key in POSSESSION_FIELDS if row.get(key) is None]
            if missing:
                raise NBADataError(f"ESPN event {game_id} missing efficiency inputs {missing}")
        games[game_id] = (home, away)
    return games


def load_release_data(directory: str | Path, download: bool = False) -> ReleaseData:
    """Load and reconcile all pinned seasons, returning only schedule-confirmed REG games."""
    root = Path(directory)
    hashes = ensure_source_assets(root, download=download)
    box_manifest = {a["season"]: a["file"] for a in _manifest()["assets"]
                    if a["kind"] == "team_box"}
    schedule_manifest = {a["season"]: a["file"] for a in _manifest()["assets"]
                         if a["kind"] == "schedule"}
    if set(box_manifest) != set(schedule_manifest):
        raise NBADataError("team box and schedule release seasons do not line up")

    games: list[TeamGame] = []
    coverage: list[dict[str, Any]] = []
    for season in sorted(box_manifest):
        schedule_rows = _read_parquet(root / schedule_manifest[season])
        box_rows = _read_parquet(root / box_manifest[season])
        schedules, regular_schedule_count = _crosswalk_schedule(schedule_rows, season)
        boxes = _boxscore_games(box_rows, season)
        matched_regular = 0
        eligible_regular = 0
        missing_efficiency_inputs = 0
        matched_cup = 0
        offsets = Counter()
        used_schedule_ids: set[str] = set()
        for event_id, (home, away) in boxes.items():
            home_code, away_code = home["_team"], away["_team"]
            source_date = _date(home.get("game_date"), f"ESPN event {event_id}")
            score_pair = (int(home["team_score"]), int(away["team_score"]))
            candidates = []
            close_pair = []
            for schedule in schedules.get((home_code, away_code), []):
                offset = (schedule["_date"] - source_date).days
                if abs(offset) <= 1:
                    close_pair.append((schedule, offset))
                    if (int(schedule["home_pts"]), int(schedule["away_pts"])) == score_pair:
                        candidates.append((schedule, offset))
            if not candidates:
                if close_pair:
                    raise NBADataError(
                        f"score mismatch for ESPN event {event_id}: {score_pair}; "
                        f"nearby NBA Stats scores={[(r.get('game_id'), r.get('home_pts'), r.get('away_pts')) for r, _ in close_pair]}"
                    )
                raise NBADataError(
                    f"no NBA Stats schedule match within one day for ESPN event "
                    f"{event_id} {source_date} {away_code}@{home_code} {score_pair}"
                )
            if len(candidates) != 1:
                raise NBADataError(f"ambiguous crosswalk for ESPN event {event_id}: {len(candidates)} matches")
            schedule, offset = candidates[0]
            schedule_id = str(schedule["game_id"])
            if schedule_id in used_schedule_ids:
                raise NBADataError(f"two ESPN events crosswalk to NBA Stats game {schedule_id}")
            used_schedule_ids.add(schedule_id)
            offsets[offset] += 1
            phase = _phase(schedule)
            if phase not in REGULAR_PHASES:
                if phase in {"nba-cup", "cup"}:
                    matched_cup += 1
                continue
            matched_regular += 1
            home_fga = _number(home, "field_goals_attempted", event_id)
            home_fta = _number(home, "free_throws_attempted", event_id)
            home_orb = _number(home, "offensive_rebounds", event_id)
            home_tov = _turnovers(home, season)
            away_fga = _number(away, "field_goals_attempted", event_id)
            away_fta = _number(away, "free_throws_attempted", event_id)
            away_orb = _number(away, "offensive_rebounds", event_id)
            away_tov = _turnovers(away, season)
            if home_tov is None or away_tov is None:
                missing_efficiency_inputs += 1
                continue
            # Fail on implausible boxscore estimates before they reach a model.
            estimated_possessions(home_fga, home_fta, home_orb, home_tov)
            estimated_possessions(away_fga, away_fta, away_orb, away_tov)
            games.append(TeamGame(
                game_id=event_id, season=season, game_date=schedule["_date"].isoformat(),
                home_team=home_code, away_team=away_code,
                home_score=score_pair[0], away_score=score_pair[1],
                home_fga=home_fga, home_fta=home_fta, home_orb=home_orb, home_tov=home_tov,
                away_fga=away_fga, away_fta=away_fta, away_orb=away_orb, away_tov=away_tov,
                schedule_game_id=schedule_id,
            ))
            eligible_regular += 1
        if matched_regular > regular_schedule_count:
            raise NBADataError(
                f"season {season}: boxscores have {matched_regular} REG games, schedule has "
                f"{regular_schedule_count}"
            )
        coverage.append({
            "season": season,
            "regular_schedule_games": regular_schedule_count,
            "regular_boxscore_games_crosswalked": matched_regular,
            "regular_games_with_complete_efficiency_inputs": eligible_regular,
            "regular_schedule_games_without_boxscore": regular_schedule_count - matched_regular,
            "regular_games_missing_efficiency_inputs": missing_efficiency_inputs,
            "nba_cup_finals_excluded": matched_cup,
            "boxscore_to_schedule_date_offsets": {str(k): v for k, v in sorted(offsets.items())},
        })
    games.sort(key=lambda g: (g.game_date, g.game_id))
    if len({(g.season, g.game_id) for g in games}) != len(games):
        raise NBADataError("duplicate eligible ESPN event IDs")
    return ReleaseData(games=games, coverage=coverage, asset_hashes=hashes)


def games_to_dicts(games: list[TeamGame]) -> list[dict[str, Any]]:
    """Stable JSON/SQLite serialization used by the importer and tests."""
    return [asdict(game) for game in games]
