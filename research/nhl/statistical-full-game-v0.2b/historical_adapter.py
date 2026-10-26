"""Forward-only pregame inputs from the verified NHL GameCenter archive.

Target-day box scores are loaded only after that day's inputs and predictions have
been constructed. The module intentionally does not query Legendary Picks' live
forecast ledger or NHL databases for historical backtests.
"""

from __future__ import annotations

import collections
import datetime as dt
import gzip
import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


FORWARD_POSITIONS = {"C", "L", "R", "LW", "RW", "F"}
LEAGUE_SHRINK_GAMES = 10.0
GOALIE_PRIOR_SHOTS = 200.0
GOALIE_PRIOR_SAVE_PCT = 0.905


def _minutes(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value) / 60.0 if value > 100 else float(value)
    pieces = str(value).split(":")
    if len(pieces) != 2:
        raise ValueError(f"invalid NHL time-on-ice value {value!r}")
    return int(pieces[0]) + int(pieces[1]) / 60.0


def _number(value: Any, label: str) -> float:
    try:
        result = float(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid historical {label}: {value!r}") from exc
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"invalid historical {label}: {value!r}")
    return result


@dataclass
class PlayerHistory:
    nhl_id: str
    canonical_id: int
    name: str
    position: str
    team: str
    last_date: str
    last_game_id: str
    games: int = 0
    toi_minutes: float = 0.0
    shots: float = 0.0
    goals: float = 0.0
    assists: float = 0.0
    faceoff_pct_sum: float = 0.0
    faceoff_pct_games: int = 0
    games_started: float = 0.0
    saves: float = 0.0
    shots_against: float = 0.0
    goals_against: float = 0.0


@dataclass
class TeamHistory:
    rows: dict[str, list[dict[str, float]]] = field(
        default_factory=lambda: {"home": [], "away": [], "all": []}
    )


class ForwardOnlyHistory:
    """Accumulate only completed, eligible games with date < each target date."""

    def __init__(self) -> None:
        self.team_games: dict[str, TeamHistory] = collections.defaultdict(TeamHistory)
        self.players: dict[str, PlayerHistory] = {}
        self._player_game_days: set[tuple[str, str]] = set()
        self.games_added: list[str] = []
        self.latest_game_date: str | None = None

    def add_game(self, game: Any, manifest_row: dict[str, Any], boxscore: dict[str, Any]) -> None:
        game_id = str(game.game_id)
        game_date = str(manifest_row["game_date"])
        dt.date.fromisoformat(game_date)
        if game_id in self.games_added:
            raise ValueError(f"duplicate history game {game_id}")
        if self.latest_game_date is not None and game_date < self.latest_game_date:
            raise ValueError(f"history is not chronological: {game_date} follows {self.latest_game_date}")
        if not game.eligible:
            raise ValueError(f"ineligible game cannot update forward history: {game_id}")
        if str(boxscore.get("id")) != game_id or str(boxscore.get("gameDate")) != game_date:
            raise ValueError(f"{game_id}: verified boxscore identity/date mismatch")

        home = str(manifest_row["canonical_home_team"])
        away = str(manifest_row["canonical_away_team"])
        if home == away:
            raise ValueError(f"{game_id}: identical home/away team IDs")
        if str((boxscore.get("homeTeam") or {}).get("abbrev")) != home:
            raise ValueError(f"{game_id}: boxscore home team disagrees with manifest")
        if str((boxscore.get("awayTeam") or {}).get("abbrev")) != away:
            raise ValueError(f"{game_id}: boxscore away team disagrees with manifest")

        home_goals = float(game.reg_ot_score["home"])
        away_goals = float(game.reg_ot_score["away"])
        home_sog = float(game.home_sog)
        away_sog = float(game.away_sog)
        if min(home_goals, away_goals, home_sog, away_sog) < 0:
            raise ValueError(f"{game_id}: negative verified team outcome")
        self._add_team_row(home, "home", home_goals, away_goals, home_sog, away_sog)
        self._add_team_row(away, "away", away_goals, home_goals, away_sog, home_sog)

        by_game: set[str] = set()
        stats = boxscore.get("playerByGameStats") or {}
        for side, team in (("homeTeam", home), ("awayTeam", away)):
            groups = stats.get(side)
            if not isinstance(groups, dict):
                raise ValueError(f"{game_id}: missing {side} playerByGameStats")
            for group in ("forwards", "defense", "goalies"):
                players = groups.get(group)
                if not isinstance(players, list):
                    raise ValueError(f"{game_id}: missing {side}.{group} player list")
                for row in players:
                    raw_id = row.get("playerId")
                    if raw_id is None or not str(raw_id).isdigit():
                        raise ValueError(f"{game_id}: player row lacks stable NHL ID")
                    pid = str(raw_id)
                    if pid in by_game:
                        raise ValueError(f"{game_id}: player ID occurs more than once: {pid}")
                    by_game.add(pid)
                    key = (pid, game_date)
                    if key in self._player_game_days:
                        raise ValueError(f"player {pid} appears in multiple games on {game_date}")
                    position = str(row.get("position") or ("G" if group == "goalies" else "?"))
                    if group == "goalies" and position != "G":
                        raise ValueError(f"{game_id}: goalie group contains non-goalie {pid}")
                    name = str((row.get("name") or {}).get("default") or f"NHL-{pid}")
                    player = self.players.get(pid)
                    if player is None:
                        player = PlayerHistory(pid, int(pid), name, position, team, game_date, game_id)
                        self.players[pid] = player
                    # Latest prior appearance controls the projected team assignment and label.
                    if (game_date, game_id) >= (player.last_date, player.last_game_id):
                        player.team = team
                        player.position = position
                        player.name = name
                        player.last_date = game_date
                        player.last_game_id = game_id
                    player.games += 1
                    player.toi_minutes += _minutes(row.get("toi"))
                    if position != "G":
                        player.shots += _number(row.get("sog"), "player SOG")
                        player.goals += _number(row.get("goals"), "player goals")
                        player.assists += _number(row.get("assists"), "player assists")
                        raw_faceoff = row.get("faceoffWinningPctg")
                        if raw_faceoff is not None:
                            pct = _number(raw_faceoff, "faceoff percentage")
                            if pct > 1.0:
                                pct /= 100.0
                            if pct > 1.0:
                                raise ValueError(f"{game_id}: faceoff percentage outside [0,1]")
                            player.faceoff_pct_sum += pct
                            player.faceoff_pct_games += 1
                    else:
                        player.games_started += float(bool(row.get("starter")))
                        player.saves += _number(row.get("saves"), "goalie saves")
                        player.shots_against += _number(row.get("shotsAgainst"), "goalie shots against")
                        player.goals_against += _number(row.get("goalsAgainst"), "goalie goals against")
                    self._player_game_days.add(key)
        self.games_added.append(game_id)
        self.latest_game_date = game_date

    def _add_team_row(self, team: str, venue: str, gf: float, ga: float,
                      sog_for: float, sog_against: float) -> None:
        row = {"gf": gf, "ga": ga, "sog_for": sog_for, "sog_against": sog_against}
        self.team_games[team].rows[venue].append(row)
        self.team_games[team].rows["all"].append(row)

    def _league_rates(self) -> dict[str, float]:
        home = [row for history in self.team_games.values() for row in history.rows["home"]]
        away = [row for history in self.team_games.values() for row in history.rows["away"]]
        all_rows = [row for history in self.team_games.values() for row in history.rows["all"]]
        if not home or not away or not all_rows:
            raise ValueError("historical pregame rates require prior eligible games")
        return {
            "home_gf": math.fsum(row["gf"] for row in home) / len(home),
            "away_gf": math.fsum(row["gf"] for row in away) / len(away),
            "home_ga": math.fsum(row["ga"] for row in home) / len(home),
            "away_ga": math.fsum(row["ga"] for row in away) / len(away),
            "sog_for": math.fsum(row["sog_for"] for row in all_rows) / len(all_rows),
            "sog_against": math.fsum(row["sog_against"] for row in all_rows) / len(all_rows),
        }

    def _shrunk(self, team: str, venue: str, metric: str, prior: float) -> tuple[float, int]:
        rows = self.team_games[team].rows[venue]
        count = len(rows)
        value = (math.fsum(row[metric] for row in rows) + LEAGUE_SHRINK_GAMES * prior) / (
            count + LEAGUE_SHRINK_GAMES
        )
        return value, count

    def make_roster(self, team: str, sim: Any) -> Any:
        histories = [p for p in self.players.values() if p.team == team and p.games > 0]
        if not histories:
            raise ValueError(f"{team}: no prior-appearance NHL player pool")
        players: dict[str, Any] = {}
        for source in histories:
            usage = source.toi_minutes / max(1, source.games)
            usage = min(30.0, max(3.0, usage if usage > 0 else (8.0 if source.position in {"D", "G"} else 10.0)))
            if source.position == "G":
                save_pct = ((source.saves + GOALIE_PRIOR_SHOTS * GOALIE_PRIOR_SAVE_PCT) /
                            (source.shots_against + GOALIE_PRIOR_SHOTS))
            else:
                save_pct = GOALIE_PRIOR_SAVE_PCT
            faceoff_pct = (source.faceoff_pct_sum / source.faceoff_pct_games
                           if source.faceoff_pct_games else 0.5)
            players[source.nhl_id] = sim.Player(
                nhl_id=source.nhl_id, canonical_id=source.canonical_id, name=source.name,
                team=team, position=source.position, usage_minutes=usage,
                shots=source.shots, goals=source.goals, assists=source.assists,
                faceoff_pct=min(.85, max(.15, faceoff_pct)), games_played=source.games,
                games_started=source.games_started, saves=source.saves,
                shots_against=source.shots_against, goals_against=source.goals_against,
                save_pct=min(.97, max(.82, save_pct)), stats_missing=False,
                source="verified_prior_gamecenter_boxscores",
            )
        forwards = sorted((p for p in players.values() if p.position in FORWARD_POSITIONS),
                          key=lambda p: (-p.usage_minutes, -p.shots, p.nhl_id))
        defense = sorted((p for p in players.values() if p.position == "D"),
                         key=lambda p: (-p.usage_minutes, -p.shots, p.nhl_id))
        goalies = sorted((p for p in players.values() if p.position == "G"),
                         key=lambda p: (-p.games_started, -p.shots_against, p.nhl_id))
        if len(forwards) < 12 or len(defense) < 6 or not goalies:
            raise ValueError(f"{team}: prior appearance pool too small: F={len(forwards)}, D={len(defense)}, G={len(goalies)}")
        player_sog = sum(p.shots / max(1.0, p.games_played) for p in forwards[:12] + defense[:6])
        goalie_starts = [p for p in goalies if p.games_started > 0]
        if goalie_starts:
            sog_against = sum(p.shots_against for p in goalie_starts) / sum(p.games_started for p in goalie_starts)
        else:
            sog_against = 30.0
        payload = [[p.nhl_id, p.name, p.position, round(p.usage_minutes, 5),
                    round(p.shots, 5), round(p.goals, 5), round(p.save_pct, 7)]
                   for p in sorted(players.values(), key=lambda x: x.nhl_id)]
        profile_hash = hashlib.sha256(json.dumps(payload, separators=(",", ":"),
                                                   sort_keys=True).encode()).hexdigest()
        position_counts = collections.Counter(p.position for p in players.values())
        latest = max(p.last_date for p in histories)
        return sim.TeamRoster(
            team=team, players=players, expected_sog=min(42.0, max(20.0, player_sog)),
            expected_sog_against=min(42.0, max(20.0, sog_against)),
            goalie_ids=[p.nhl_id for p in goalies],
            goalie_weights=[max(.5, p.games_started) for p in goalies],
            profile_hash=profile_hash,
            coverage={"projection": "latest prior appearance by NHL player ID; not target lineup",
                      "source": "verified GameCenter boxscore manifest and bodies",
                      "prior_player_count": len(players), "forward_count": len(forwards),
                      "defense_count": len(defense), "goalie_count": len(goalies),
                      "players_with_prior_appearances": len(players),
                      "latest_prior_appearance_date": latest,
                      "prior_history_games": len(self.games_added),
                      "position_counts": dict(sorted(position_counts.items()))},
        )

    def make_inputs(self, *, sim: Any, game_key: str, game_date: str,
                    home: str, away: str) -> Any:
        dt.date.fromisoformat(game_date)
        if self.latest_game_date is None or self.latest_game_date >= game_date:
            raise ValueError(f"history cutoff violated for {game_key}: "
                             f"latest={self.latest_game_date}, target={game_date}")
        home_roster = self.make_roster(home, sim)
        away_roster = self.make_roster(away, sim)
        league = self._league_rates()
        h_gf, h_gp = self._shrunk(home, "home", "gf", league["home_gf"])
        away_ga, away_gp = self._shrunk(away, "away", "ga", league["home_gf"])
        a_gf, a_gp = self._shrunk(away, "away", "gf", league["away_gf"])
        home_ga, home_gp = self._shrunk(home, "home", "ga", league["away_gf"])
        mu_home = max(.1, (h_gf + away_ga) / 2.0)
        mu_away = max(.1, (a_gf + home_ga) / 2.0)
        home_sog_for, h_sog_games = self._shrunk(home, "all", "sog_for", league["sog_for"])
        home_sog_against, h_sa_games = self._shrunk(home, "all", "sog_against", league["sog_against"])
        away_sog_for, a_sog_games = self._shrunk(away, "all", "sog_for", league["sog_for"])
        away_sog_against, a_sa_games = self._shrunk(away, "all", "sog_against", league["sog_against"])
        sog_home = (home_sog_for + away_sog_against) / 2.0
        sog_away = (away_sog_for + home_sog_against) / 2.0
        cutoff_date = dt.date.fromisoformat(game_date) - dt.timedelta(days=1)
        cutoff = dt.datetime.combine(cutoff_date, dt.time(23, 59, 59), tzinfo=dt.timezone.utc)
        start = dt.datetime.combine(dt.date.fromisoformat(game_date), dt.time(0, 0), tzinfo=dt.timezone.utc)
        snapshot = {
            "schema": "PregameGameSnapshot-v0.2b-historical-forward-only",
            "game_key": game_key, "game_date": game_date,
            "scheduled_start_utc": start.isoformat().replace("+00:00", "Z"),
            "capture_cutoff_utc": cutoff.isoformat().replace("+00:00", "Z"),
            "home_team": home, "away_team": away, "neutral_site": False,
            "input_source": "verified independent NHL GameCenter PBP/boxscore archive",
            "history_games_before_target_date": len(self.games_added),
            "latest_history_date": max((p.last_date for p in self.players.values()), default=None),
            "same_day_results_excluded": True,
            "actual_target_game_stats_or_lineups_used": False,
            "historical_team_rate_model": {
                "shrinkage_games": LEAGUE_SHRINK_GAMES,
                "home_mu_components": {"home_gf_per_game": h_gf,
                    "opponent_away_ga_per_game": away_ga,
                    "team_games": h_gp, "opponent_games": away_gp},
                "away_mu_components": {"away_gf_per_game": a_gf,
                    "opponent_home_ga_per_game": home_ga,
                    "team_games": a_gp, "opponent_games": home_gp},
                "league_rates": league,
            },
            "home_roster_hash": home_roster.profile_hash,
            "away_roster_hash": away_roster.profile_hash,
            "home_roster_coverage": home_roster.coverage,
            "away_roster_coverage": away_roster.coverage,
            "team_model": {"model_version": "historical-forward-rates-v1",
                "training_cutoff_game_date_exclusive": game_date},
            "team_expected_goals": {"home": mu_home, "away": mu_away},
            "team_expected_sog": {"home": sog_home, "away": sog_away},
            "team_sog_model": {
                "source": "verified boxscore team SOG reconciled by frozen v0.1 corpus loader",
                "history_cutoff_game_date_exclusive": game_date,
                "shrinkage_games": LEAGUE_SHRINK_GAMES,
                "team_rates": {
                    home: {"games": h_sog_games, "shots_for_per_game": home_sog_for,
                           "shots_against_per_game": home_sog_against},
                    away: {"games": a_sog_games, "shots_for_per_game": away_sog_for,
                           "shots_against_per_game": away_sog_against}},
            },
            "team_sog_player_rate_diagnostic": {
                "home": {"player_rate_sog": home_roster.expected_sog,
                         "goalie_rate_sog_against": home_roster.expected_sog_against},
                "away": {"player_rate_sog": away_roster.expected_sog,
                         "goalie_rate_sog_against": away_roster.expected_sog_against},
            },
            "starting_goalie_status": "projected from prior starts only; target starter unknown",
        }
        return sim.PregameInputs(
            game_key=game_key, game_date=game_date,
            scheduled_start_utc=start.isoformat().replace("+00:00", "Z"),
            as_of_utc=cutoff.isoformat().replace("+00:00", "Z"),
            home_team=home, away_team=away, home_roster=home_roster, away_roster=away_roster,
            mu_home=mu_home, mu_away=mu_away, team_model=snapshot["team_model"], snapshot=snapshot,
        )


def read_verified_boxscore(game: Any, manifest_row: dict[str, Any], root: Path) -> dict[str, Any]:
    path = root / "raw" / f"{game.game_id}.json.gz"
    if path.stat().st_size != int(manifest_row["compressed_bytes"]):
        raise ValueError(f"{game.game_id}: boxscore size does not match independent manifest")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != str(manifest_row["compressed_sha256"]):
        raise ValueError(f"{game.game_id}: boxscore hash does not match independent manifest")
    if digest != str(game.boxscore_compressed_sha256):
        raise ValueError(f"{game.game_id}: boxscore hash disagrees with eligible corpus summary")
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        document = json.load(handle)
    if str(document.get("id")) != str(game.game_id):
        raise ValueError(f"{game.game_id}: boxscore body ID mismatch")
    if str(document.get("gameDate")) != str(manifest_row["game_date"]):
        raise ValueError(f"{game.game_id}: boxscore body date mismatch")
    return document


def load_boxscore_manifest(v01: Any) -> dict[str, dict[str, Any]]:
    path = v01.DEFAULT_BOXSCORE_ROOT / "manifest.jsonl"
    if v01.sha256_file(path) != v01.EXPECTED_BOXSCORE_MANIFEST_SHA256:
        raise ValueError("independent boxscore manifest hash differs from frozen v0.1 constant")
    result: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            game_id = str(row["game_id"])
            if game_id in result:
                raise ValueError(f"duplicate independent boxscore manifest ID {game_id}")
            if row.get("status") != "OK" or row.get("source") not in {
                "official_gamecenter", "prior_official_audit_cache"
            }:
                raise ValueError(f"unverified independent boxscore manifest row {game_id}")
            result[game_id] = row
    if len(result) != 4876:
        raise ValueError(f"boxscore manifest game count changed: {len(result)}")
    return result


def eligible_history_days(corpus: Any, manifest: dict[str, dict[str, Any]],
                          years: Iterable[int]) -> dict[str, list[Any]]:
    years = set(years)
    days: dict[str, list[Any]] = collections.defaultdict(list)
    for game in corpus.games.values():
        if game.start_season not in years or not game.eligible:
            continue
        row = manifest.get(str(game.game_id))
        if row is None:
            raise ValueError(f"{game.game_id}: no independent boxscore manifest row")
        game_date = str(row["game_date"])
        dt.date.fromisoformat(game_date)
        days[game_date].append(game)
    for game_date in days:
        days[game_date].sort(key=lambda game: game.game_id)
    return dict(sorted(days.items()))
