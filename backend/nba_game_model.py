"""Chronological research models for NBA game outcomes (Phase 1).

G1 is result-only Elo. G2 adds rolling pace and opponent-adjusted offense and
defense, returning point and winner forecasts. G3 samples a joint score model
from G2's means and pregame residual covariance; every winner, margin, and total
distribution metric comes from those same simulated integer scores.
"""
from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from nba_model_data import TeamGame

TRAIN_SEASONS = tuple(range(2017, 2022))
VALIDATION_SEASONS = (2022, 2023)
TEST_SEASONS = (2024, 2025)
REFIT_THROUGH_SEASON = 2026
SIMULATIONS = 2048
EPSILON = 1e-12

MODEL_INFO = [
    {"id": "G1", "label": "G1 Elo", "version": "nba-g1-elo-v1-k20-hca65-reg75",
     "projects_scores": False,
     "note": "Chronological team Elo with home-court adjustment and 25% offseason regression."},
    {"id": "G2", "label": "G2 Efficiency", "version": "nba-g2-efficiency-v1-ewma08-reg50-hca2",
     "projects_scores": True,
     "note": "Rolling pace plus opponent-adjusted offensive and defensive efficiency."},
    {"id": "G3", "label": "G3 Joint scores", "version": "nba-g3-joint-score-v1-ewma08-2048",
     "projects_scores": True,
     "note": "G2 score means with a pregame bivariate residual distribution."},
]

ELO_VERSION = MODEL_INFO[0]["version"]
EFFICIENCY_VERSION = MODEL_INFO[1]["version"]
JOINT_VERSION = MODEL_INFO[2]["version"]


def _elo_expectation(home_rating: float, away_rating: float, home_advantage: float) -> float:
    exponent = (away_rating - home_rating - home_advantage) / 400.0
    return 1.0 / (1.0 + 10.0 ** max(-20.0, min(20.0, exponent)))


class EloState:
    def __init__(self, k: float = 20.0, home_advantage: float = 65.0,
                 offseason_carry: float = 0.75) -> None:
        self.k = k
        self.home_advantage = home_advantage
        self.offseason_carry = offseason_carry
        self.ratings: dict[str, float] = {}
        self.season: int | None = None

    def begin_season(self, season: int) -> None:
        if self.season == season:
            return
        if self.season is not None:
            if season < self.season:
                raise ValueError("Elo replay received a prior season")
            carry = self.offseason_carry ** (season - self.season)
            self.ratings = {team: 1500.0 + carry * (rating - 1500.0)
                            for team, rating in self.ratings.items()}
        self.season = season

    def probability(self, home: str, away: str) -> float:
        return _elo_expectation(self.ratings.get(home, 1500.0),
                                self.ratings.get(away, 1500.0), self.home_advantage)

    def update(self, game: TeamGame) -> None:
        home_rating = self.ratings.get(game.home_team, 1500.0)
        away_rating = self.ratings.get(game.away_team, 1500.0)
        expected = _elo_expectation(home_rating, away_rating, self.home_advantage)
        actual = 1.0 if game.home_score > game.away_score else 0.0
        change = self.k * (actual - expected)
        self.ratings[game.home_team] = home_rating + change
        self.ratings[game.away_team] = away_rating - change


@dataclass
class TeamEfficiency:
    pace: float
    offense: float
    defense_allowed: float


class EfficiencyState:
    """Pre-game EWMA states; each new observation is applied only after its game date."""

    def __init__(self, alpha: float = 0.08, offseason_carry: float = 0.50,
                 home_court_points: float = 2.0) -> None:
        self.alpha = alpha
        self.offseason_carry = offseason_carry
        self.home_court_points = home_court_points
        self.league_pace = 98.0
        self.league_pp100 = 108.0
        self._pace_sum = 0.0
        self._pace_n = 0
        self._points_sum = 0.0
        self._possessions_sum = 0.0
        self.teams: dict[str, TeamEfficiency] = {}
        self.season: int | None = None

    def _team(self, team: str) -> TeamEfficiency:
        return self.teams.setdefault(
            team, TeamEfficiency(self.league_pace, self.league_pp100, self.league_pp100)
        )

    def begin_season(self, season: int) -> None:
        if self.season == season:
            return
        if self.season is not None:
            if season < self.season:
                raise ValueError("efficiency replay received a prior season")
            carry = self.offseason_carry ** (season - self.season)
            for team in self.teams.values():
                team.pace = self.league_pace + carry * (team.pace - self.league_pace)
                team.offense = self.league_pp100 + carry * (team.offense - self.league_pp100)
                team.defense_allowed = (self.league_pp100
                                        + carry * (team.defense_allowed - self.league_pp100))
        self.season = season

    def predict(self, home: str, away: str) -> tuple[float, float, float]:
        home_state, away_state = self._team(home), self._team(away)
        pace = max(75.0, (home_state.pace + away_state.pace) / 2.0)
        home_efficiency = max(80.0, home_state.offense + away_state.defense_allowed
                              - self.league_pp100)
        away_efficiency = max(80.0, away_state.offense + home_state.defense_allowed
                              - self.league_pp100)
        court = self.home_court_points / 2.0
        home_points = pace * home_efficiency / 100.0 + court
        away_points = pace * away_efficiency / 100.0 - court
        return home_points, away_points, pace

    def update(self, game: TeamGame) -> None:
        home_poss, away_poss = game.home_possessions, game.away_possessions
        pace = (home_poss + away_poss) / 2.0
        home_off = 100.0 * game.home_score / home_poss
        home_def = 100.0 * game.away_score / home_poss
        away_off = 100.0 * game.away_score / away_poss
        away_def = 100.0 * game.home_score / away_poss
        for code, offense, defense in (
            (game.home_team, home_off, home_def),
            (game.away_team, away_off, away_def),
        ):
            state = self._team(code)
            state.pace += self.alpha * (pace - state.pace)
            state.offense += self.alpha * (offense - state.offense)
            state.defense_allowed += self.alpha * (defense - state.defense_allowed)
        self._pace_sum += pace
        self._pace_n += 1
        self._points_sum += game.home_score + game.away_score
        self._possessions_sum += home_poss + away_poss
        self.league_pace = self._pace_sum / self._pace_n
        self.league_pp100 = 100.0 * self._points_sum / self._possessions_sum


class ResidualDistribution:
    """Recent G2 prequential score residuals, used only for later G3 forecasts."""

    def __init__(self, maxlen: int = 2000) -> None:
        self.rows: deque[tuple[float, float]] = deque(maxlen=maxlen)

    def add(self, home_error: float, away_error: float) -> None:
        self.rows.append((float(home_error), float(away_error)))

    def parameters(self) -> tuple[float, float, float]:
        if len(self.rows) < 30:
            return 12.0, 12.0, 0.20
        home = [r[0] for r in self.rows]
        away = [r[1] for r in self.rows]
        mean_home = sum(home) / len(home)
        mean_away = sum(away) / len(away)
        denom = max(1, len(home) - 1)
        var_home = sum((x - mean_home) ** 2 for x in home) / denom
        var_away = sum((x - mean_away) ** 2 for x in away) / denom
        covariance = sum((h - mean_home) * (a - mean_away)
                         for h, a in self.rows) / denom
        sd_home, sd_away = max(7.5, math.sqrt(max(0.0, var_home))), max(7.5, math.sqrt(max(0.0, var_away)))
        rho = max(-0.80, min(0.80, covariance / (sd_home * sd_away)))
        return sd_home, sd_away, rho


def _probability_from_margin(margin: float, scale: float) -> float:
    x = max(-40.0, min(40.0, margin / max(1.0, scale)))
    return 1.0 / (1.0 + math.exp(-x))


def simulate_joint_scores(game_id: str, mean_home: float, mean_away: float,
                          covariance: tuple[float, float, float],
                          n: int = SIMULATIONS) -> dict[str, Any]:
    """Sample one correlated score pair per draw and derive all G3 outputs from it."""
    sd_home, sd_away, rho = covariance
    seed = int(hashlib.sha256((JOINT_VERSION + "|" + str(game_id)).encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)
    orthogonal = math.sqrt(max(1e-9, 1.0 - rho * rho))
    homes: list[int] = []
    aways: list[int] = []
    for _ in range(n):
        z1, z2 = rng.gauss(0.0, 1.0), rng.gauss(0.0, 1.0)
        home = max(50, min(170, int(round(mean_home + sd_home * z1))))
        away = max(50, min(170, int(round(mean_away + sd_away * (rho * z1 + orthogonal * z2)))))
        homes.append(home)
        aways.append(away)
    margins = [h - a for h, a in zip(homes, aways)]
    totals = [h + a for h, a in zip(homes, aways)]
    win_mass = sum(1.0 if m > 0 else 0.5 if m == 0 else 0.0 for m in margins) / n
    return {
        "p_home": win_mass,
        "home_points": sum(homes) / n,
        "away_points": sum(aways) / n,
        "margin_mean": sum(margins) / n,
        "total_mean": sum(totals) / n,
        "margins": margins,
        "totals": totals,
        "covariance": {"home_sd": sd_home, "away_sd": sd_away, "correlation": rho},
    }


def _quantile(sorted_values: list[float], probability: float) -> float:
    position = (len(sorted_values) - 1) * probability
    lo = int(position)
    hi = min(len(sorted_values) - 1, lo + 1)
    return sorted_values[lo] + (position - lo) * (sorted_values[hi] - sorted_values[lo])


def _crps(samples: list[float], outcome: float) -> float:
    ordered = sorted(samples)
    n = len(ordered)
    first = sum(abs(x - outcome) for x in ordered) / n
    pair_half = sum((2 * i - n + 1) * value for i, value in enumerate(ordered)) / (n * n)
    return first - pair_half


def _joint_nll(home_error: float, away_error: float,
               covariance: tuple[float, float, float]) -> float:
    sd_home, sd_away, rho = covariance
    rho = max(-0.98, min(0.98, rho))
    denom = max(1e-6, 1.0 - rho * rho)
    zh, za = home_error / sd_home, away_error / sd_away
    quadratic = (zh * zh - 2.0 * rho * zh * za + za * za) / denom
    logdet = 2.0 * math.log(sd_home) + 2.0 * math.log(sd_away) + math.log(denom)
    return 0.5 * (2.0 * math.log(2.0 * math.pi) + logdet + quadratic)


def _calibration(rows: list[dict[str, float]]) -> dict[str, Any]:
    bins = []
    weighted_error = 0.0
    for index in range(10):
        low, high = index / 10.0, (index + 1) / 10.0
        items = [r for r in rows if low <= r["p_home"] < high
                 or (index == 9 and r["p_home"] == 1.0)]
        if not items:
            continue
        mean_p = sum(r["p_home"] for r in items) / len(items)
        observed = sum(r["outcome"] for r in items) / len(items)
        weighted_error += len(items) / len(rows) * abs(mean_p - observed)
        bins.append({"low": low, "high": high, "n": len(items),
                     "mean_probability": mean_p, "observed_home_win_rate": observed})
    return {"ece_10_bin": weighted_error if rows else None, "bins": bins}


def _score_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("cannot score an empty evaluation period")
    model_names = sorted({name for row in rows for name in row["models"]})
    results = {}
    for name in model_names:
        forecasts = [row["models"][name] for row in rows]
        p_rows = [{"p_home": item["p_home"], "outcome": row["outcome"]}
                  for row, item in zip(rows, forecasts)]
        brier = sum((r["p_home"] - r["outcome"]) ** 2 for r in p_rows) / len(rows)
        logloss = -sum(r["outcome"] * math.log(max(EPSILON, r["p_home"]))
                       + (1 - r["outcome"]) * math.log(max(EPSILON, 1 - r["p_home"]))
                       for r in p_rows) / len(rows)
        result: dict[str, Any] = {
            "games": len(rows), "winner_brier": brier, "winner_log_loss": logloss,
            "winner_accuracy": sum((r["p_home"] >= 0.5) == bool(r["outcome"])
                                    for r in p_rows) / len(rows),
            "calibration": _calibration(p_rows),
        }
        if all(item.get("home_points") is not None and item.get("away_points") is not None
               for item in forecasts):
            home_errors = [item["home_points"] - row["home_score"]
                           for row, item in zip(rows, forecasts)]
            away_errors = [item["away_points"] - row["away_score"]
                           for row, item in zip(rows, forecasts)]
            spread_errors = [item["home_points"] - item["away_points"]
                             - (row["home_score"] - row["away_score"])
                             for row, item in zip(rows, forecasts)]
            total_errors = [item["home_points"] + item["away_points"]
                            - row["home_score"] - row["away_score"]
                            for row, item in zip(rows, forecasts)]
            result.update({
                "home_points_mae": sum(map(abs, home_errors)) / len(rows),
                "away_points_mae": sum(map(abs, away_errors)) / len(rows),
                "team_points_mae": (sum(map(abs, home_errors)) + sum(map(abs, away_errors)))
                                   / (2 * len(rows)),
                "spread_mae": sum(map(abs, spread_errors)) / len(rows),
                "total_mae": sum(map(abs, total_errors)) / len(rows),
            })
        if name == "G3" and all("distribution_metrics" in item for item in forecasts):
            distributions = [item["distribution_metrics"] for item in forecasts]
            result["distribution"] = {
                "margin_crps": sum(d["margin_crps"] for d in distributions) / len(rows),
                "total_crps": sum(d["total_crps"] for d in distributions) / len(rows),
                "joint_score_gaussian_nll": sum(d["joint_score_gaussian_nll"]
                                                 for d in distributions) / len(rows),
                "margin_80pct_coverage": sum(d["margin_80_covered"]
                                             for d in distributions) / len(rows),
                "margin_80pct_width": sum(d["margin_80_width"]
                                          for d in distributions) / len(rows),
                "total_80pct_coverage": sum(d["total_80_covered"]
                                            for d in distributions) / len(rows),
                "total_80pct_width": sum(d["total_80_width"]
                                         for d in distributions) / len(rows),
                "simulation_count_per_game": SIMULATIONS,
            }
        results[name] = result
    return results


def _metric_row(game: TeamGame, predictions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "game_id": game.game_id, "season": game.season, "game_date": game.game_date,
        "home_score": game.home_score, "away_score": game.away_score,
        "outcome": int(game.home_score > game.away_score),
        "models": predictions,
    }


def backtest(games: Iterable[TeamGame], coverage: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Replay all games chronologically; report validation and untouched holdout metrics."""
    games = sorted(games, key=lambda g: (g.game_date, g.game_id))
    if not games:
        raise ValueError("no eligible regular-season games")
    train = [g for g in games if g.season in TRAIN_SEASONS]
    validation = [g for g in games if g.season in VALIDATION_SEASONS]
    test = [g for g in games if g.season in TEST_SEASONS]
    if not train or not validation or not test:
        raise ValueError("chronological train/validation/test split is incomplete")
    if max(g.game_date for g in train) >= min(g.game_date for g in validation):
        raise ValueError("training games are not strictly before validation")
    if max(g.game_date for g in validation) >= min(g.game_date for g in test):
        raise ValueError("validation games are not strictly before holdout")

    elo, efficiency = EloState(), EfficiencyState()
    residuals = ResidualDistribution()
    training_margin_errors: list[float] = []
    train_home_wins = 0
    train_home_score_sum = train_away_score_sum = 0.0
    eval_rows: dict[str, list[dict[str, Any]]] = {"validation": [], "test": []}
    g2_sigma = None
    validation_started = False
    index = 0
    while index < len(games):
        game_date = games[index].game_date
        date_games = []
        while index < len(games) and games[index].game_date == game_date:
            date_games.append(games[index])
            index += 1
        season = date_games[0].season
        if any(game.season != season for game in date_games):
            raise ValueError(f"different seasons share a date block: {game_date}")
        elo.begin_season(season)
        efficiency.begin_season(season)

        if season in VALIDATION_SEASONS and not validation_started:
            if not training_margin_errors:
                raise ValueError("training residuals unavailable for G2 probability scale")
            mean_error = sum(training_margin_errors) / len(training_margin_errors)
            g2_sigma = math.sqrt(sum((x - mean_error) ** 2 for x in training_margin_errors)
                                 / max(1, len(training_margin_errors) - 1))
            validation_started = True

        predictions_for_date = []
        for game in date_games:
            g1_p = elo.probability(game.home_team, game.away_team)
            home_points, away_points, _pace = efficiency.predict(game.home_team, game.away_team)
            if g2_sigma is None:
                g2_p = 0.5
            else:
                g2_p = _probability_from_margin(home_points - away_points,
                                                g2_sigma * math.sqrt(3.0) / math.pi)
            if season in VALIDATION_SEASONS or season in TEST_SEASONS:
                covariance = residuals.parameters()
                sim = simulate_joint_scores(game.game_id, home_points, away_points, covariance)
                margin_ordered = sorted(sim["margins"])
                total_ordered = sorted(sim["totals"])
                actual_margin = game.home_score - game.away_score
                actual_total = game.home_score + game.away_score
                margin_low, margin_high = (_quantile(margin_ordered, 0.10),
                                           _quantile(margin_ordered, 0.90))
                total_low, total_high = (_quantile(total_ordered, 0.10),
                                         _quantile(total_ordered, 0.90))
                distribution_metrics = {
                    "margin_crps": _crps(margin_ordered, actual_margin),
                    "total_crps": _crps(total_ordered, actual_total),
                    "joint_score_gaussian_nll": _joint_nll(
                        game.home_score - sim["home_points"],
                        game.away_score - sim["away_points"], covariance,
                    ),
                    "margin_80_covered": int(margin_low <= actual_margin <= margin_high),
                    "margin_80_width": margin_high - margin_low,
                    "total_80_covered": int(total_low <= actual_total <= total_high),
                    "total_80_width": total_high - total_low,
                }
                models = {
                    "G1": {"p_home": g1_p, "home_points": None, "away_points": None},
                    "G2": {"p_home": g2_p, "home_points": home_points,
                           "away_points": away_points},
                    "G3": {"p_home": sim["p_home"], "home_points": sim["home_points"],
                           "away_points": sim["away_points"],
                           "distribution_metrics": distribution_metrics},
                }
                period = "validation" if season in VALIDATION_SEASONS else "test"
                eval_rows[period].append(_metric_row(game, models))
            predictions_for_date.append((game, home_points, away_points))

        # All games on the same published local date share one pregame state.
        # Observations are applied only after every forecast for that date exists.
        for game, home_points, away_points in predictions_for_date:
            home_error, away_error = game.home_score - home_points, game.away_score - away_points
            margin_error = (game.home_score - game.away_score) - (home_points - away_points)
            residuals.add(home_error, away_error)
            if game.season in TRAIN_SEASONS:
                training_margin_errors.append(margin_error)
                train_home_wins += int(game.home_score > game.away_score)
                train_home_score_sum += game.home_score
                train_away_score_sum += game.away_score
            elo.update(game)
            efficiency.update(game)

    if not validation_started or g2_sigma is None:
        raise ValueError("validation did not follow training")
    expected_counts = {"validation": len(validation), "test": len(test)}
    for period, rows in eval_rows.items():
        if len(rows) != expected_counts[period]:
            raise ValueError(f"candidate eligibility differs in {period}: {len(rows)} != {expected_counts[period]}")
    baseline_home_p = train_home_wins / len(train)
    baseline_home_points = train_home_score_sum / len(train)
    baseline_away_points = train_away_score_sum / len(train)
    for rows in eval_rows.values():
        for row in rows:
            row["models"]["B0 Home-rate baseline"] = {
                "p_home": baseline_home_p, "home_points": None, "away_points": None,
            }
            point_base = {"p_home": baseline_home_p,
                          "home_points": baseline_home_points,
                          "away_points": baseline_away_points}
            row["models"]["B1 Training league-points baseline"] = point_base

    metrics = {period: _score_metrics(rows) for period, rows in eval_rows.items()}
    return {
        "protocol": {
            "train_seasons_end_year": list(TRAIN_SEASONS),
            "validation_seasons_end_year": list(VALIDATION_SEASONS),
            "holdout_seasons_end_year": list(TEST_SEASONS),
            "prospective_refit_through_end_year": REFIT_THROUGH_SEASON,
            "same_date_games_share_pregame_state": True,
            "parameters_fixed_before_evaluation": True,
            "g1": {"k": 20.0, "home_advantage_elo_points": 65.0,
                   "offseason_carry": 0.75},
            "g2": {"ewma_alpha": 0.08, "offseason_carry": 0.50,
                   "home_court_points": 2.0,
                   "possessions": "FGA + 0.44*FTA - OREB + TOV",
                   "winner_probability": "logistic margin scale set from prequential train residual SD"},
            "g3": {"simulations_per_game": SIMULATIONS,
                   "residual_window": 2000,
                   "distribution": "bivariate normal score residuals; rounded integer scores"},
            "baselines": {
                "B0": "fixed home-win rate from training seasons",
                "B1": "fixed home/away league points-per-game means from training seasons",
            },
            "no_pregame_market_odds_comparison": True,
        },
        "coverage": coverage or [],
        "eligible_games": {
            "train": len(train), "validation": len(validation), "test": len(test),
            "refit_through_2025_26": sum(1 for g in games if g.season <= REFIT_THROUGH_SEASON),
        },
        "training_baselines": {
            "home_win_rate": baseline_home_p,
            "home_points_mean": baseline_home_points,
            "away_points_mean": baseline_away_points,
            "g2_training_margin_residual_sd": g2_sigma,
        },
        "metrics": metrics,
        "model_info": MODEL_INFO,
    }


def build_state(games: Iterable[TeamGame], through_season: int = REFIT_THROUGH_SEASON) -> dict[str, Any]:
    """Fit pregame state through the declared cutoff for prospective forecasts."""
    rows = sorted((g for g in games if g.season <= through_season),
                  key=lambda g: (g.game_date, g.game_id))
    if not rows:
        raise ValueError("no historical games before forecast cutoff")
    elo, efficiency = EloState(), EfficiencyState()
    residuals = ResidualDistribution()
    margin_errors = []
    last_date = None
    index = 0
    while index < len(rows):
        day = rows[index].game_date
        day_games = []
        while index < len(rows) and rows[index].game_date == day:
            day_games.append(rows[index]); index += 1
        season = day_games[0].season
        elo.begin_season(season)
        efficiency.begin_season(season)
        preds = []
        for game in day_games:
            home_p, away_p, _ = efficiency.predict(game.home_team, game.away_team)
            preds.append((game, home_p, away_p))
        for game, home_p, away_p in preds:
            residuals.add(game.home_score - home_p, game.away_score - away_p)
            margin_errors.append((game.home_score - game.away_score) - (home_p - away_p))
            elo.update(game)
            efficiency.update(game)
        last_date = day
    mean_error = sum(margin_errors) / len(margin_errors)
    sigma = math.sqrt(sum((x - mean_error) ** 2 for x in margin_errors)
                      / max(1, len(margin_errors) - 1))
    return {"elo": elo, "efficiency": efficiency, "residuals": residuals,
            "g2_margin_residual_sd": sigma, "history_games": len(rows),
            "fitted_through": last_date}


def forecast_game(state: dict[str, Any], game_id: str, home: str, away: str,
                  season: int) -> dict[str, dict[str, Any]]:
    """Return all three current candidate forecasts from a frozen pregame state."""
    elo: EloState = state["elo"]
    efficiency: EfficiencyState = state["efficiency"]
    elo.begin_season(season)
    efficiency.begin_season(season)
    g1_p = elo.probability(home, away)
    home_points, away_points, pace = efficiency.predict(home, away)
    sigma = float(state["g2_margin_residual_sd"])
    g2_p = _probability_from_margin(home_points - away_points, sigma * math.sqrt(3.0) / math.pi)
    covariance = state["residuals"].parameters()
    simulation = simulate_joint_scores(game_id, home_points, away_points, covariance)
    common = {"fitted_through": state["fitted_through"],
              "history_games": state["history_games"]}
    return {
        "G1": {**common, "model_version": ELO_VERSION, "home_win_probability": g1_p,
               "projected_home_points": None, "projected_away_points": None,
               "score_forecast_available": False},
        "G2": {**common, "model_version": EFFICIENCY_VERSION, "home_win_probability": g2_p,
               "projected_home_points": home_points, "projected_away_points": away_points,
               "projected_margin_home": home_points - away_points,
               "projected_total": home_points + away_points, "pace": pace,
               "score_forecast_available": True},
        "G3": {**common, "model_version": JOINT_VERSION,
               "home_win_probability": simulation["p_home"],
               "projected_home_points": simulation["home_points"],
               "projected_away_points": simulation["away_points"],
               "projected_margin_home": simulation["margin_mean"],
               "projected_total": simulation["total_mean"],
        "margin_10_90": [
                   _quantile(sorted(simulation["margins"]), 0.10),
                   _quantile(sorted(simulation["margins"]), 0.90),
               ],
               "total_10_90": [
                   _quantile(sorted(simulation["totals"]), 0.10),
                   _quantile(sorted(simulation["totals"]), 0.90),
               ],
               "covariance": simulation["covariance"],
               "simulation_count": SIMULATIONS, "score_forecast_available": True},
    }
