"""Pre-match count and total-games distributions, frozen at lock time (research, CP4).

These are the verdict winners of research/tennis/counts-2026-10-20/RESULTS.md, computed by the
functions their replays used, not re-implemented:

- aces and double faults: P1 Gamma-Poisson (tennis_props_rate_backtest), best-of-three only;
- total games: direct surface plus competitiveness (tennis_total_games_backtest), best-of-three only.

Nothing reads these rows for a projection, a grade or a page. They exist so a later grader can
score the pre-match forecast against the settled result. Every row carries MODEL_VERSION.
"""
from __future__ import annotations

import json
from collections import defaultdict
from itertools import groupby
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import tennis_daily_projections as tdp
import tennis_point_model as tpm
import tennis_props_rate_backtest as rb
import tennis_total_games_backtest as tgb
from espn_client.scoreboard import major_for_event

MODEL_VERSION = "tennis-counts/2026-10-20"
# Both replays take their state from 2000. The total-games driver overrides the module default
# (tgb.HISTORY_START = 2022) to this value for its histograms, so the frozen games PMF does too.
HISTORY_START = 20000101
# Count PMFs are stored from the first to the last probability at or above this value.
PMF_TRIM = 1e-12
GRAND_SLAM_MAJORS = frozenset(tdp.FIVE_SET_MAJORS)


class LookAheadError(RuntimeError):
    """A source row is not strictly earlier than the match it would forecast."""


class History:
    """Replay state after every row dated before one model day, updated as the replays update it."""

    def __init__(self) -> None:
        self.aces = rb.WeightedTotals()
        self.double_faults = rb.WeightedTotals()
        self.first_in = rb.WeightedTotals()
        self.exposure = rb.DirectServiceExposure()
        self.elo: Dict[str, float] = defaultdict(lambda: tgb.ELO_START)
        self.direct = tgb.DirectGames()

    def target(self, name: str) -> rb.WeightedTotals:
        return self.aces if name == "aces" else self.double_faults


def yyyymmdd(model_day: str) -> int:
    return int(model_day.replace("-", ""))


def replay_rows(history: History, rows: Iterable[Sequence[Any]], cutoff: int) -> None:
    """Apply source rows in date order, mirroring the replays' update steps exactly.

    Row layout: tourney_date, tourney_name, tourney_level, surface, winner_id, loser_id,
    best_of, score, w_ace, w_df, w_svpt, w_1stIn, l_ace, l_df, l_svpt, l_1stIn.
    """
    for date, grouped in groupby(rows, key=lambda row: row[0]):
        day_rows = list(grouped)
        if int(date) >= cutoff:
            raise LookAheadError(f"source row dated {date} is not before the match day {cutoff}")
        day = tpm._ordinal(int(date))
        for row in day_rows:
            _, name, level, surface, winner_id, loser_id, best_of, score = row[:8]
            if best_of != 3 or not rb.is_complete(score):
                continue
            winner = {"id": str(winner_id), "aces": row[8], "double_faults": row[9],
                      "svpt": row[10], "first_in": row[11]}
            loser = {"id": str(loser_id), "aces": row[12], "double_faults": row[13],
                     "svpt": row[14], "first_in": row[15]}
            for player in (winner, loser):
                svpt, first = player["svpt"], player["first_in"]
                if not rb.valid_count(svpt) or svpt <= 0:
                    continue
                history.exposure.add(player["id"], surface, int(svpt), day)
                if rb.valid_count(first) and 0 <= first <= svpt:
                    history.first_in.add(player["id"], first, svpt, day)
                    if rb.valid_count(player["aces"]) and player["aces"] <= svpt:
                        history.aces.add(player["id"], player["aces"], svpt, day)
                    second_serves = svpt - first
                    if (rb.valid_count(player["double_faults"])
                            and player["double_faults"] <= second_serves and second_serves > 0):
                        history.double_faults.add(player["id"], player["double_faults"], second_serves, day)

        # Games histograms: the replay adds a result with the Elo gap as it stood before this date.
        for row in day_rows:
            _, name, level, surface, winner_id, loser_id, best_of, score = row[:8]
            if date >= HISTORY_START and best_of == 3 and tgb.is_complete(score):
                tagged = tgb.score_format(score, level, name, int(date))
                if tagged is not None:
                    format_key, _ = tagged
                    games = tgb.total_games_from_score(score, format_key)
                    if games is not None:
                        comp = tgb.competition_bucket(abs(history.elo[str(winner_id)] - history.elo[str(loser_id)]))
                        history.direct.add(format_key, surface, comp, games, day)

        rating_updates = []
        for row in day_rows:
            if tgb.is_complete(row[7]):
                winner, loser = str(row[4]), str(row[5])
                expected = 1.0 / (1.0 + 10 ** ((history.elo[loser] - history.elo[winner]) / 400.0))
                rating_updates.append((winner, loser, tgb.ELO_K * (1.0 - expected)))
        for winner, loser, delta in rating_updates:
            history.elo[winner] += delta
            history.elo[loser] -= delta


def build_history(con: Any, tour: str, model_day: str) -> History:
    """State from every main-tour row dated from 2000 up to, not including, the model day."""
    if tour not in tpm.TOUR_FILTER:
        raise ValueError(f"unknown tour {tour!r}")
    cutoff = yyyymmdd(model_day)
    rows = con.execute(
        "SELECT tourney_date,tourney_name,tourney_level,surface,winner_id,loser_id,best_of,score,"
        "w_ace,w_df,w_svpt,w_1stIn,l_ace,l_df,l_svpt,l_1stIn "
        f"FROM tennis_{tour}_matches WHERE {tpm.TOUR_FILTER[tour]} "
        "AND tourney_date>=? AND tourney_date<? AND surface IS NOT NULL "
        "AND winner_id IS NOT NULL AND loser_id IS NOT NULL ORDER BY tourney_date",
        (HISTORY_START, cutoff),
    ).fetchall()
    history = History()
    replay_rows(history, rows, cutoff)
    return history


def format_for_match(major: Optional[str], model_day: str) -> str:
    """Pre-match games format. The replay tags it from the score; here only the event is known."""
    if major in GRAND_SLAM_MAJORS and yyyymmdd(model_day) >= 20220101:
        return "grand_slam_final_tiebreak_10"
    return "standard_tiebreak_7"


def count_parameters(history: History, target: str, player: str, surface: str, model_day: str) -> Dict[str, Any]:
    """P1 Gamma-Poisson parameters for one player, from forecast_target in the props replay."""
    day = tpm._ordinal(yyyymmdd(model_day))
    direct_mean, direct_variance = history.exposure.moments(player, surface, day)
    first_rate, first_alpha, first_beta = rb.rate_mean(history.first_in, player, day, rb.FIRST_IN_PRIOR_POINTS)
    if target == "aces":
        exposure_mean, exposure_variance = direct_mean, direct_variance
        prior_opportunities = rb.P1_ACE_PRIOR_POINTS
    else:
        second_serve_rate = max(0.0, 1.0 - first_rate)
        first_rate_variance = (first_alpha * (first_beta - first_alpha)
                               / (first_beta * first_beta * (first_beta + 1.0)))
        second_moment = direct_variance + direct_mean * direct_mean
        exposure_mean = direct_mean * second_serve_rate
        exposure_variance = (
            direct_mean * second_serve_rate * first_rate
            + direct_variance * second_serve_rate * second_serve_rate
            + max(0.0, second_moment - direct_mean) * first_rate_variance
        )
        prior_opportunities = rb.P1_DF_PRIOR_SECOND_SERVES
    event_rate_mean, shape_rate, rate_rate = rb.rate_mean(history.target(target), player, day, prior_opportunities)
    mean = max(1e-12, event_rate_mean * exposure_mean)
    rate_variance = shape_rate / (rate_rate * rate_rate)
    extra = (exposure_variance * event_rate_mean * event_rate_mean
             + (exposure_variance + exposure_mean * exposure_mean) * rate_variance)
    if extra <= 1e-12:
        family, shape, rate = "poisson", None, None
    else:
        family = "gamma_poisson"
        shape = mean * mean / extra
        rate = shape / mean
    return {
        "variant": "p1_gamma_poisson", "target": target, "player_id": player, "surface": surface,
        "model_day": model_day, "family": family, "mean": float(mean), "shape": shape, "rate": rate,
        "extra_mean_variance": float(extra), "exposure_mean": float(exposure_mean),
        "exposure_variance": float(exposure_variance), "event_rate_mean": float(event_rate_mean),
        "histogram_source": f"BO3 complete main-tour rows, tourney_date {HISTORY_START}..day before model_day",
        "cap": "mean + 12*sqrt(variance + 1) + 30; no observed value enters the support",
    }


def count_pmf_from_parameters(parameters: Dict[str, Any]) -> List[float]:
    """The full count PMF from stored parameters. The only route from a frozen row to a PMF."""
    if parameters["family"] == "poisson":
        return rb.poisson_pmf(parameters["mean"], 0)
    return rb.gamma_poisson_pmf(parameters["shape"], parameters["rate"], 1.0, 0)


def games_distribution(history: History, format_key: str, surface: str, elo_gap: float,
                       model_day: str) -> Tuple[List[float], Dict[str, Any]]:
    """Direct surface plus competitiveness PMF over the games support for this format."""
    day = tpm._ordinal(yyyymmdd(model_day))
    comp = tgb.competition_bucket(elo_gap)
    support = tgb.support_for(format_key)
    pmf = history.direct.forecasts(format_key, surface, comp, day, support)["direct_surface_competitive"]
    return pmf, {
        "variant": "direct_surface_competitive", "format": format_key, "surface": surface,
        "competitiveness": comp, "elo_gap": float(elo_gap), "model_day": model_day,
        "support_start": support[0], "support_end": support[-1],
        "histogram_source": f"BO3 complete main-tour rows, format-tagged, tourney_date {HISTORY_START}..day before model_day",
        "truncation": "none; the PMF is stored over its full support",
    }


def _trim(pmf: List[float]) -> Tuple[int, List[float], float]:
    kept = [index for index, probability in enumerate(pmf) if probability >= PMF_TRIM]
    start, end = kept[0], kept[-1] + 1
    return start, pmf[start:end], sum(pmf[:start]) + sum(pmf[end:])


def match_distributions(history: History, tour: str, model_day: str,
                        match: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Rows to freeze for one match, or ([], reason) when the match has no candidate forecast."""
    major = major_for_event(tour, match.get("event"))
    best_of = 5 if tour == "atp" and major in tdp.FIVE_SET_MAJORS else 3
    if best_of != 3:
        return [], "not_best_of_three"
    surface = tdp.SURFACE_BY_EVENT.get(str(match.get("tournamentId") or "")) or tdp.SURFACE_BY_MAJOR.get(major or "")
    if not surface:
        return [], "surface_unmapped"
    identity = match.get("identity") or {}
    home = (identity.get("home") or {}).get("sackmann_player_id")
    away = (identity.get("away") or {}).get("sackmann_player_id")
    if not home or not away:
        return [], "identity_unmapped"
    home, away = str(home), str(away)

    rows: List[Dict[str, Any]] = []
    for target in ("aces", "double_faults"):
        for side, player in (("home", home), ("away", away)):
            parameters = count_parameters(history, target, player, surface, model_day)
            start, values, trimmed = _trim(count_pmf_from_parameters(parameters))
            rows.append({"cell": target, "side": side, "parameters": parameters,
                         "support_start": start, "pmf": values, "trimmed_mass": trimmed})

    format_key = format_for_match(major, model_day)
    pmf, parameters = games_distribution(history, format_key, surface,
                                         abs(history.elo[home] - history.elo[away]), model_day)
    parameters.update({"home_player_id": home, "away_player_id": away})
    rows.append({"cell": "total_games", "side": "match", "parameters": parameters,
                 "support_start": parameters["support_start"], "pmf": pmf, "trimmed_mass": 0.0})
    return rows, None


def store_distributions(con: Any, league: str, game_id: str, locked_at: str, rows: List[Dict[str, Any]]) -> None:
    con.executemany(
        "INSERT INTO tennis_model_lock_distributions"
        "(league,game_id,cell,side,model_version,locked_at,parameters,support_start,pmf,trimmed_mass) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        [(league, game_id, row["cell"], row["side"], MODEL_VERSION, locked_at,
          json.dumps(row["parameters"], sort_keys=True), row["support_start"],
          json.dumps(row["pmf"]), row["trimmed_mass"]) for row in rows],
    )
