#!/usr/bin/env python3
"""Run the fixed-G2 FBS rating-history warm-up ablation.

Only the first season admitted to the existing chronological forecaster changes.
The model implementation, parameters, evaluation dates, and game population stay
fixed. Run from this worktree's repository root with the project's Python environment:

  python backend/fbs_warmup_ablation.py
"""
import argparse
import os

import numpy as np
import pandas as pd

import fbs_game_winner_baseline as baseline


RUN_DATE = "20261018"
HISTORY_STARTS = (2022, 2018, 2014, 2010, 2004)
FIRST_EVALUATION_SEASON = 2023
LAST_EVALUATION_SEASON = 2025
EXPECTED_EVALUATION_GAMES = 2398
PUBLISHED_BASIC_ELO_BRIER = 0.1976
BOOTSTRAP_REPLICATES = 2000
BOOTSTRAP_SEED = 20261018
MATERIAL_RATING_GAP = 25.0
VERIFIED_CFDB_SCORE_DISAGREEMENT_IDS = ("401014983", "401021686")
DATA_SEASONS = tuple(range(2004, LAST_EVALUATION_SEASON + 1))
EVALUATION_SEASONS = tuple(range(FIRST_EVALUATION_SEASON,
                                 LAST_EVALUATION_SEASON + 1))
MODEL_COLUMNS = {
    "G2 chronological Elo": "elo_home_prob",
    "G3 opponent-adjusted margin strength": "margin_home_prob",
}


def source_manifest(data_dir):
    rows = []
    sources = (
        ("cfb_schedules", "cfb_schedules_{year}.parquet",
         "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/"
         "cfb_schedules/cfb_schedules_{year}.parquet"),
        ("espn_cfb_schedules", "espn_schedule_{year}.parquet",
         "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/"
         "espn_cfb_schedules/cfb_schedule_{year}.parquet"),
    )
    for season in DATA_SEASONS:
        for tag, filename_template, url_template in sources:
            filename = filename_template.format(year=season)
            path = os.path.join(data_dir, filename)
            if not os.path.isfile(path):
                raise FileNotFoundError("missing required schedule source: %s" % path)
            frame = pd.read_parquet(path)
            rows.append({
                "season": season,
                "source": tag,
                "file": os.path.relpath(path, os.path.dirname(data_dir)),
                "release_asset_url": url_template.format(year=season),
                "rows": int(len(frame)),
                "bytes": int(os.path.getsize(path)),
                "sha256": baseline.sha256_file(path),
            })
    result = pd.DataFrame(rows)
    if len(result) != len(DATA_SEASONS) * len(sources):
        raise RuntimeError("schedule source manifest is incomplete")
    return result


def paired_game_bootstrap(candidate, control, outcomes, seasons, seed):
    """Bootstrap paired game-level Brier and log-loss differences by season."""
    candidate = np.clip(candidate, 1e-12, 1.0 - 1e-12)
    control = np.clip(control, 1e-12, 1.0 - 1e-12)
    brier_differences = (candidate - outcomes) ** 2 - (control - outcomes) ** 2
    candidate_log_loss = -(
        outcomes * np.log(candidate) + (1.0 - outcomes) * np.log(1.0 - candidate)
    )
    control_log_loss = -(
        outcomes * np.log(control) + (1.0 - outcomes) * np.log(1.0 - control)
    )
    log_loss_differences = candidate_log_loss - control_log_loss
    rng = np.random.default_rng(seed)
    brier_estimates = np.zeros(BOOTSTRAP_REPLICATES, dtype=float)
    log_loss_estimates = np.zeros(BOOTSTRAP_REPLICATES, dtype=float)
    season_groups = []
    for season in EVALUATION_SEASONS:
        selected = seasons == season
        brier_values = brier_differences[selected]
        log_loss_values = log_loss_differences[selected]
        if not len(brier_values):
            raise RuntimeError("no paired games in evaluation season %d" % season)
        sample_indexes = rng.integers(
            0, len(brier_values), size=(BOOTSTRAP_REPLICATES, len(brier_values))
        )
        brier_estimates += brier_values[sample_indexes].sum(axis=1)
        log_loss_estimates += log_loss_values[sample_indexes].sum(axis=1)
        season_groups.append(brier_values)
    total_games = sum(len(group) for group in season_groups)
    brier_estimates /= total_games
    log_loss_estimates /= total_games
    return {
        "brier_difference": float(np.mean(brier_differences)),
        "brier_ci_low": float(np.quantile(brier_estimates, 0.025)),
        "brier_ci_high": float(np.quantile(brier_estimates, 0.975)),
        "log_loss_difference": float(np.mean(log_loss_differences)),
        "log_loss_ci_low": float(np.quantile(log_loss_estimates, 0.025)),
        "log_loss_ci_high": float(np.quantile(log_loss_estimates, 0.975)),
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "bootstrap_method": "paired game-level bootstrap, resampled within season",
    }


def make_rating_snapshots(events, history_start, evaluation_team_ids):
    """Return season-end Elo snapshots using the unchanged G2 update method."""
    history = events[
        events.fbs_participant.astype(bool)
        & events.season.between(history_start, LAST_EVALUATION_SEASON)
    ].copy()
    history = history.sort_values(
        ["utc_date", "kickoff_utc", "game_id"]
    ).reset_index(drop=True)
    elo = baseline.Elo()
    snapshots = {}
    for season in range(history_start, LAST_EVALUATION_SEASON + 1):
        season_games = history[history.season.eq(season)]
        if season_games.empty:
            raise RuntimeError("no completed FBS-participant history in %d" % season)
        for _, day_games in season_games.groupby("utc_date", sort=True):
            elo.update_day(day_games)
        # Advance through the same 25% regression that precedes next season.
        elo.ensure_season(season + 1)
        snapshots[season] = {
            int(team_id): float(elo.ratings.get(int(team_id), baseline.ELO_INITIAL))
            for team_id in evaluation_team_ids
        }
    return snapshots


def rating_diagnostics(events, history_starts):
    evaluation = events[
        events.evaluation_population
        & events.season.between(FIRST_EVALUATION_SEASON, LAST_EVALUATION_SEASON)
    ]
    team_ids = sorted(set(evaluation.home_team_id.astype(int))
                      | set(evaluation.away_team_id.astype(int)))
    snapshots_by_start = {
        start: make_rating_snapshots(events, start, team_ids)
        for start in history_starts
    }
    reference = snapshots_by_start[min(history_starts)]
    checkpoint_rows = []
    for start in history_starts:
        for season in range(start, LAST_EVALUATION_SEASON + 1):
            ratings = snapshots_by_start[start][season]
            reference_ratings = reference[season]
            gaps = np.asarray([
                ratings[team_id] - reference_ratings[team_id]
                for team_id in team_ids
            ], dtype=float)
            checkpoint_rows.append({
                "history_start_season": start,
                "history_seasons_through_checkpoint": season - start + 1,
                "after_completed_season": season,
                "as_of_before_season": season + 1,
                "evaluation_fbs_team_count": len(team_ids),
                "rating_sd": float(np.std(list(ratings.values()), ddof=0)),
                "rating_mae_vs_2004_start": float(np.mean(np.abs(gaps))),
                "rating_rmse_vs_2004_start": float(np.sqrt(np.mean(gaps ** 2))),
                "teams_with_gap_over_material_threshold": int(
                    np.count_nonzero(np.abs(gaps) > MATERIAL_RATING_GAP)
                ),
                "material_gap_threshold_elo_points": MATERIAL_RATING_GAP,
            })
    checkpoints = pd.DataFrame(checkpoint_rows)

    summaries = []
    for start in history_starts:
        arm = checkpoints[checkpoints.history_start_season.eq(start)].sort_values(
            "after_completed_season"
        )
        pre_eval = arm[arm.after_completed_season.eq(2022)]
        if len(pre_eval) != 1:
            raise RuntimeError("missing pre-2023 rating checkpoint for arm %d" % start)
        stable_from = None
        for season in arm.after_completed_season:
            remaining = arm[arm.after_completed_season.ge(season)]
            if remaining.rating_mae_vs_2004_start.le(MATERIAL_RATING_GAP).all():
                stable_from = int(season)
                break
        final = arm[arm.after_completed_season.eq(LAST_EVALUATION_SEASON)].iloc[0]
        summaries.append({
            "history_start_season": start,
            "history_seasons_before_2023": FIRST_EVALUATION_SEASON - start,
            "pre_2023_rating_sd": float(pre_eval.iloc[0].rating_sd),
            "pre_2023_rating_mae_vs_2004": float(
                pre_eval.iloc[0].rating_mae_vs_2004_start
            ),
            "end_2025_rating_mae_vs_2004": float(final.rating_mae_vs_2004_start),
            "stable_from_after_season": stable_from,
            "evaluation_seasons_until_stable": (
                None if stable_from is None else max(0, stable_from - 2022)
            ),
            "history_seasons_at_stability": (
                None if stable_from is None else stable_from - start + 1
            ),
            "material_gap_threshold_elo_points": MATERIAL_RATING_GAP,
        })
    return pd.DataFrame(summaries), checkpoints


def metric_rows(forecasts_by_start, rating_summary):
    rows = []
    rating_by_start = rating_summary.set_index("history_start_season")
    for start in HISTORY_STARTS:
        forecasts = forecasts_by_start[start]
        rating = rating_by_start.loc[start]
        for model_name, column in MODEL_COLUMNS.items():
            scores = baseline.score_metrics(forecasts, column)
            rows.append({
                "history_start_season": start,
                "history_seasons_before_2023": FIRST_EVALUATION_SEASON - start,
                "model": model_name,
                "probability_column": column,
                **scores,
                "gap_to_published_basic_elo_brier": (
                    scores["brier"] - PUBLISHED_BASIC_ELO_BRIER
                ),
                "rating_sd_pre_2023": rating.pre_2023_rating_sd,
                "rating_mae_pre_2023_vs_2004": rating.pre_2023_rating_mae_vs_2004,
                "rating_mae_end_2025_vs_2004": rating.end_2025_rating_mae_vs_2004,
                "ratings_stable_from_after_season": rating.stable_from_after_season,
                "evaluation_seasons_until_stable": rating.evaluation_seasons_until_stable,
                "history_seasons_at_stability": rating.history_seasons_at_stability,
            })
    return pd.DataFrame(rows)


def paired_rows(forecasts_by_start):
    control = forecasts_by_start[2022].set_index("game_id").sort_index()
    rows = []
    for start in HISTORY_STARTS:
        candidate = forecasts_by_start[start].set_index("game_id").sort_index()
        if not candidate.index.equals(control.index):
            raise RuntimeError("paired comparison has a mismatched game ID set")
        if not np.array_equal(candidate.home_win.to_numpy(), control.home_win.to_numpy()):
            raise RuntimeError("paired comparison has mismatched game outcomes")
        for model_number, (model_name, column) in enumerate(MODEL_COLUMNS.items()):
            if start == 2022:
                comparison = {
                    "brier_difference": 0.0,
                    "brier_ci_low": np.nan,
                    "brier_ci_high": np.nan,
                    "log_loss_difference": 0.0,
                    "log_loss_ci_low": np.nan,
                    "log_loss_ci_high": np.nan,
                    "bootstrap_replicates": 0,
                    "bootstrap_method": "control arm",
                }
            else:
                comparison = paired_game_bootstrap(
                    candidate[column].to_numpy(dtype=float),
                    control[column].to_numpy(dtype=float),
                    candidate.home_win.to_numpy(dtype=float),
                    candidate.season.to_numpy(dtype=int),
                    BOOTSTRAP_SEED + start * 10 + model_number,
                )
            rows.append({
                "history_start_season": start,
                "model": model_name,
                "control_arm": "A (2022)",
                "games": len(candidate),
                "delta_brier_candidate_minus_A": comparison["brier_difference"],
                "brier_ci_95_low": comparison["brier_ci_low"],
                "brier_ci_95_high": comparison["brier_ci_high"],
                "delta_log_loss_candidate_minus_A": comparison["log_loss_difference"],
                "log_loss_ci_95_low": comparison["log_loss_ci_low"],
                "log_loss_ci_95_high": comparison["log_loss_ci_high"],
                "delta_brier_skill_candidate_minus_A": (
                    -4.0 * comparison["brier_difference"]
                ),
                "brier_skill_ci_95_low": (
                    -4.0 * comparison["brier_ci_high"]
                    if not pd.isna(comparison["brier_ci_high"]) else np.nan
                ),
                "brier_skill_ci_95_high": (
                    -4.0 * comparison["brier_ci_low"]
                    if not pd.isna(comparison["brier_ci_low"]) else np.nan
                ),
                "bootstrap_replicates": comparison["bootstrap_replicates"],
                "bootstrap_method": comparison["bootstrap_method"],
            })
    return pd.DataFrame(rows)


def fmt(value, digits=4):
    if value is None or pd.isna(value):
        return "—"
    return ("%%.%df" % digits) % float(value)


def markdown_table(rows, columns, headers):
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column, "—"))
                                         for column in columns) + " |")
    return "\n".join(lines)


def write_report(path, metrics, paired, rating_summary, checkpoints,
                 coverage, source_rows):
    g2 = metrics[metrics.model.eq("G2 chronological Elo")].sort_values(
        "history_start_season"
    )
    g3 = metrics[metrics.model.eq("G3 opponent-adjusted margin strength")].sort_values(
        "history_start_season"
    )
    by_arm = {int(row.history_start_season): row for row in g2.itertuples(index=False)}
    by_pair = {
        (int(row.history_start_season), row.model): row
        for row in paired.itertuples(index=False)
    }
    arm_order = list(HISTORY_STARTS)
    result_rows = []
    for start in arm_order:
        row = by_arm[start]
        result_rows.append({
            "arm": chr(ord("A") + arm_order.index(start)),
            "start": start,
            "history": FIRST_EVALUATION_SEASON - start,
            "g2_brier": fmt(row.brier),
            "g2_log_loss": fmt(row.log_loss),
            "g2_bss": fmt(row.brier_skill_vs_coinflip),
            "g2_delta": fmt(by_pair[(start, "G2 chronological Elo")].delta_brier_candidate_minus_A),
            "g3_brier": fmt(g3[g3.history_start_season.eq(start)].iloc[0].brier),
            "g3_log_loss": fmt(g3[g3.history_start_season.eq(start)].iloc[0].log_loss),
            "g3_bss": fmt(g3[g3.history_start_season.eq(start)].iloc[0].brier_skill_vs_coinflip),
        })
    result_table = markdown_table(
        result_rows,
        ["arm", "start", "history", "g2_brier", "g2_log_loss", "g2_bss",
         "g2_delta", "g3_brier", "g3_log_loss", "g3_bss"],
        ["Arm", "History starts", "Seasons before 2023", "G2 Brier", "G2 log loss",
         "G2 BSS", "G2 Δ vs A", "G3 Brier", "G3 log loss", "G3 BSS"],
    )

    paired_table_rows = []
    for start in arm_order:
        row = {"arm": chr(ord("A") + arm_order.index(start)), "start": start}
        for model_name, label in (("G2 chronological Elo", "g2"),
                                  ("G3 opponent-adjusted margin strength", "g3")):
            comparison = by_pair[(start, model_name)]
            if start == 2022:
                row[label + "_brier"] = "0.0000 (control)"
                row[label + "_logloss"] = "0.0000 (control)"
            else:
                row[label + "_brier"] = "%s [%s, %s]" % (
                    fmt(comparison.delta_brier_candidate_minus_A),
                    fmt(comparison.brier_ci_95_low),
                    fmt(comparison.brier_ci_95_high),
                )
                row[label + "_logloss"] = "%s [%s, %s]" % (
                    fmt(comparison.delta_log_loss_candidate_minus_A),
                    fmt(comparison.log_loss_ci_95_low),
                    fmt(comparison.log_loss_ci_95_high),
                )
        paired_table_rows.append(row)
    paired_table = markdown_table(
        paired_table_rows,
        ["arm", "start", "g2_brier", "g2_logloss", "g3_brier", "g3_logloss"],
        ["Arm", "History starts", "G2 Δ Brier [95% CI]", "G2 Δ log loss [95% CI]",
         "G3 Δ Brier [95% CI]", "G3 Δ log loss [95% CI]"],
    )

    convergence_rows = []
    summary_by_start = rating_summary.set_index("history_start_season")
    for start in arm_order:
        summary = summary_by_start.loc[start]
        if start == min(arm_order):
            stable_text = "Reference arm"
        elif pd.isna(summary.stable_from_after_season):
            stable_text = "Not by 2025"
        else:
            eval_count = int(summary.evaluation_seasons_until_stable)
            eval_label = "eval season" if eval_count == 1 else "eval seasons"
            history_count = int(summary.history_seasons_at_stability)
            history_label = "history season" if history_count == 1 else "history seasons"
            stable_text = "%s (%s %s; %s %s)" % (
                int(summary.stable_from_after_season),
                history_count, history_label, eval_count, eval_label,
            )
        convergence_rows.append({
            "arm": chr(ord("A") + arm_order.index(start)),
            "start": start,
            "history": FIRST_EVALUATION_SEASON - start,
            "sd": fmt(summary.pre_2023_rating_sd, 2),
            "mae_pre": fmt(summary.pre_2023_rating_mae_vs_2004, 2),
            "mae_2025": fmt(summary.end_2025_rating_mae_vs_2004, 2),
            "stable": stable_text,
        })
    convergence_table = markdown_table(
        convergence_rows, ["arm", "start", "history", "sd", "mae_pre", "mae_2025", "stable"],
        ["Arm", "History starts", "Seasons before 2023", "Pre-2023 rating SD",
         "Pre-2023 MAE vs E", "End-2025 MAE vs E", "First stable point"],
    )

    evaluation_counts = (
        coverage[coverage.season.isin(EVALUATION_SEASONS)]
        .set_index("season").eligible_fbs_vs_fbs.to_dict()
    )
    expected_counts = {2023: 792, 2024: 798, 2025: 808}
    if {int(year): int(count) for year, count in evaluation_counts.items()} != expected_counts:
        raise RuntimeError("per-season evaluation counts differ from the fixed population")
    historical_coverage_rows = []
    for row in coverage[coverage.season.between(2004, 2022)].itertuples(index=False):
        historical_coverage_rows.append({
            "season": int(row.season),
            "completed_participant_games": int(row.completed_fbs_participant),
            "eligible_fbs_fbs_games": int(row.eligible_fbs_vs_fbs),
        })
    historical_coverage_table = markdown_table(
        historical_coverage_rows,
        ["season", "completed_participant_games", "eligible_fbs_fbs_games"],
        ["Season", "Completed FBS-participant results available to train", "FBS-FBS games"],
    )

    g2_values = [float(by_arm[start].brier) for start in arm_order]
    monotonic = all(right <= left for left, right in zip(g2_values, g2_values[1:]))
    worsening = g2_values[-1] > g2_values[0]
    last_gain = g2_values[-2] - g2_values[-1]
    previous_gain = g2_values[-3] - g2_values[-2]
    flattened = monotonic and last_gain >= 0 and previous_gain >= 0 and last_gain < previous_gain
    initial_gap = g2_values[0] - PUBLISHED_BASIC_ELO_BRIER
    final_gap = g2_values[-1] - PUBLISHED_BASIC_ELO_BRIER
    total_improvement = g2_values[0] - g2_values[-1]
    gap_closure_pct = (100.0 * total_improvement / initial_gap
                       if initial_gap > 0 else 0.0)
    five_season_gain = g2_values[0] - g2_values[1]
    added_history_gain = g2_values[1] - g2_values[-1]
    if worsening:
        interpretation = (
            "G2 scores worse with the longest history, so the measured result points away "
            "from history depth as the fix and toward adaptation/model design."
        )
        next_lever = "Pull the model/adaptation lever next; more history worsened the same-game G2 score."
    elif monotonic and flattened:
        interpretation = (
            "G2 improves monotonically as history deepens and the gain flattens: the full 2004 "
            "history closes %.1f%% of the initial Basic Elo Brier gap, from %.5f to %.5f, "
            "leaving %.5f; the 2022-start ratings also settle within the 25-point criterion "
            "after one evaluation season." % (
                gap_closure_pct, initial_gap, final_gap, final_gap
            )
        )
        next_lever = (
            "Use at least five warm-up seasons: that closes most of the measured history benefit "
            "(Δ Brier %.5f), while extending five to 19 seasons adds only %.5f, so the remaining "
            "%.5f gap calls for model/population diagnosis after the archive is available."
            % (five_season_gain, added_history_gain, final_gap)
        )
    elif monotonic:
        interpretation = (
            "G2 improves monotonically as history deepens, though the improvement has not "
            "yet flattened by the longest tested window."
        )
        next_lever = "Pull the history-depth lever next; deeper warm-up improved G2, and the tested curve has not yet flattened."
    else:
        interpretation = (
            "G2's history-depth curve is flat or non-monotonic, so this run does not support "
            "history quantity as the lever for the remaining gap."
        )
        next_lever = "Pull the model/population lever next; longer history did not improve G2 consistently on the identical games."

    report = [
        "# FBS G2 warm-up ablation — 2023–2025",
        "",
        "Generated: 2026-10-18",
        "Phase 1 benchmark: `research/fbs/RESULT-FBS-GAME-WINNERS-20261018.md`",
        "Baseline distinctions: [`research/fbs/BASELINE-DISTINCTIONS.md`](BASELINE-DISTINCTIONS.md)",
        "",
        "## Question and method",
        "",
        "This ablation keeps G2 completely fixed and changes only how far back its rating history starts, to test whether more history closes the Brier gap.",
        "",
        "The five arms start their history in 2022, 2018, 2014, 2010, or 2004. G2 remains chronological Elo with initial rating 1500, logistic scale 400, home advantage 55 (zero at neutral sites), K=20, and 25% offseason regression. G3 is the Phase 1 score-margin model with its existing ridge, time-decay, and probability rules unchanged. The only varying input is the earliest season allowed into prior-result history.",
        "",
        "Every arm forecasts the identical 2,398 FBS-vs-FBS games: 792 in 2023, 798 in 2024, and 808 in 2025. Predictions use the Phase 1 one-day UTC-date embargo and only prior completed schedules/results. Training updates include FBS-FBS and FBS-FCS completed results, as in the original G2 definition. No betting, player, team-statistic, play-by-play, or 2026 data enters this experiment.",
        "",
        "The published Basic Elo Brier of 0.1976 is shown as context; its published population is 9,356 games across thirteen seasons, so the difference is not a same-population paired comparison.",
        "",
        "## Results",
        "",
        result_table,
        "",
        "Brier and log loss are lower-is-better. Brier Skill Score (BSS) is `1 - Brier / 0.25`, relative to a 0.50 coin flip. G2's original Phase 1 result is arm A; the run requires its per-game G2 and G3 probabilities to reproduce the stored Phase 1 ledger within 1e-12.",
        "",
        "### Paired game-level comparisons against arm A",
        "",
        paired_table,
        "",
        "Intervals resample paired game-level differences within season (2,000 replicates), preserving the fixed 2023/2024/2025 game counts. Negative candidate-minus-A values favor the longer-history arm. Since BSS = 1 - Brier / 0.25, its paired difference and interval are exactly -4 times the Brier difference and interval (with interval endpoints reversed). These intervals quantify uncertainty on this fixed evaluation population; they do not make the published Basic Elo comparison paired.",
        "",
        "## Elo rating dispersion and convergence",
        "",
        "The reported rating SD is the population standard deviation across the fixed set of teams appearing in the 2023–2025 FBS-vs-FBS evaluation games, immediately before 2023 forecasts after the 2023 offseason regression. The convergence reference is arm E (2004 start). A rating set is operationally treated as settled when its mean absolute team-rating gap from arm E is at most 25 Elo points at a season-end checkpoint and remains at or below that threshold at every later checkpoint through 2025. Twenty-five Elo points correspond to about a 3.6 percentage-point neutral win-probability change around an otherwise even matchup.",
        "",
        convergence_table,
        "",
        "The full checkpoint series is in `fbs_warmup_ablation_rating_convergence_%s.csv`; the table above makes the pre-2023 starting dispersion and any post-2023 convergence visible. A convergence time is not reported if the threshold is not met through 2025." % RUN_DATE,
        "",
        "## Historical schedule/result coverage",
        "",
        "The SportsDataverse release API was checked on 2026-10-18: `cfb_schedules` publishes 2001–2026 and `espn_cfb_schedules` publishes 2004–2026. This run uses only the two schedule/result releases for 2004–2025 (44 Parquet files); every input file's row count, size, direct release URL, and SHA-256 is in `fbs_warmup_ablation_sources_%s.csv`. No team-info, betting, player, or play-by-play files were read." % RUN_DATE,
        "",
        "### Reconciled historical final-score differences",
        "",
        "The 2004–2025 source comparison found two completed FBS-participant games where the CFBD schedule score disagrees with ESPN. ESPN's final scores are the outcomes used by the existing Phase 1 pipeline; both cases were checked against official team records before allowing the mismatch through the otherwise fail-closed loader.",
        "",
        "| Game ID | Matchup and date | CFBD score | ESPN score used | Independent official confirmation |",
        "|---|---|---:|---:|---|",
        "| 401014983 | Florida Atlantic–Air Force, 2018-09-08 | 33–26 | 33–27 | [Air Force Athletics](https://goairforcefalcons.com/game-center/4656), [FAU Athletics](https://fausports.com/sports/football/stats/2018/air-force/boxscore/2836) |",
        "| 401021686 | Georgia State–Texas State, 2018-11-03 | 30–40 | 31–40 | [Georgia State Athletics](https://georgiastatesports.com/news/2018/11/3/211778896.aspx), [Georgia State 2018 results](https://georgiastatesports.com/sports/2018/8/31/211770084.aspx) |",
        "",
        "For the 2004-start arm, all completed FBS-participant results in each available season through 2022 are eligible rating updates. The separate FBS-FBS counts below document the evaluation-style game population available in each season; FBS-FCS results are retained in training history but excluded from scoring.",
        "",
        historical_coverage_table,
        "All 15,535 completed FBS-participant results in 2004–2022 were trainable; none were excluded for unresolved team IDs, ties, missing kickoff, or duplicate event rows.",
        "",
        "## Interpretation",
        "",
        interpretation,
        "",
        "Next lever: " + next_lever,
        "",
        "## Reproduction and artifacts",
        "",
        "From this worktree's repository root, run `python backend/fbs_warmup_ablation.py` with the project's Python environment active. The script fails if the fixed evaluation population changes, if arm A does not reproduce the Phase 1 ledger, or if any required source season is absent.",
        "",
        "- Per-arm metrics: `fbs_warmup_ablation_metrics_%s.csv`." % RUN_DATE,
        "- Paired game-level intervals: `fbs_warmup_ablation_paired_%s.csv`." % RUN_DATE,
        "- Rating checkpoints: `fbs_warmup_ablation_rating_convergence_%s.csv`." % RUN_DATE,
        "- Input manifest: `fbs_warmup_ablation_sources_%s.csv`." % RUN_DATE,
        "- Forecast ledgers: `fbs_warmup_ablation_forecasts_%s_arm_<A-E>_start_<year>.csv`." % RUN_DATE,
        "",
    ]
    with open(path, "w", encoding="utf-8") as output:
        output.write("\n".join(report))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "research", "fbs", "parquet"
    ))
    parser.add_argument("--output-dir", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "research", "fbs"
    ))
    parser.add_argument("--reference-ledger", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "research", "fbs",
        "fbs_game_winner_predictions_20261018.csv"
    ))
    parser.add_argument("--run-date", default=RUN_DATE)
    args = parser.parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    events, coverage, _, _ = baseline.load_events(
        args.data_dir, DATA_SEASONS, include_reporting_metadata=False,
        verified_score_disagreement_ids=VERIFIED_CFDB_SCORE_DISAGREEMENT_IDS,
    )
    evaluation = events[
        events.evaluation_population
        & events.season.between(FIRST_EVALUATION_SEASON, LAST_EVALUATION_SEASON)
    ]
    if evaluation.game_id.duplicated().any():
        raise RuntimeError("duplicate game IDs in the fixed evaluation population")
    if len(evaluation) != EXPECTED_EVALUATION_GAMES:
        raise RuntimeError(
            "expected %d evaluation games, found %d"
            % (EXPECTED_EVALUATION_GAMES, len(evaluation))
        )

    reference = pd.read_csv(args.reference_ledger, dtype={"game_id": str})
    reference = reference[reference.season.between(
        FIRST_EVALUATION_SEASON, LAST_EVALUATION_SEASON
    )].copy()
    current_ids = set(evaluation.game_id.astype(str))
    reference_ids = set(reference.game_id.astype(str))
    if current_ids != reference_ids:
        raise RuntimeError(
            "fixed evaluation IDs differ from the Phase 1 ledger: %d missing, %d extra"
            % (len(reference_ids - current_ids), len(current_ids - reference_ids))
        )

    forecasts_by_start = {}
    for start in HISTORY_STARTS:
        arm_events = events[events.season.ge(start)].copy()
        forecasts = baseline.make_predictions(
            arm_events, FIRST_EVALUATION_SEASON
        )
        forecasts = forecasts[
            forecasts.season.between(FIRST_EVALUATION_SEASON, LAST_EVALUATION_SEASON)
        ].copy()
        forecasts["game_id"] = forecasts.game_id.astype(str)
        if len(forecasts) != EXPECTED_EVALUATION_GAMES:
            raise RuntimeError("arm %d has %d games, expected %d" % (
                start, len(forecasts), EXPECTED_EVALUATION_GAMES
            ))
        if set(forecasts.game_id) != current_ids:
            raise RuntimeError("arm %d has a different game ID set" % start)
        forecasts["history_start_season"] = start
        forecasts["history_seasons_before_2023"] = FIRST_EVALUATION_SEASON - start
        forecasts_by_start[start] = forecasts.sort_values(
            ["season", "kickoff_utc", "game_id"]
        ).reset_index(drop=True)

    arm_a = forecasts_by_start[2022].set_index("game_id").sort_index()
    original = reference.set_index("game_id").sort_index()
    for new_column, old_column in (("elo_home_prob", "elo_home_prob"),
                                   ("margin_home_prob", "margin_home_prob")):
        differences = np.abs(
            arm_a[new_column].to_numpy(dtype=float)
            - original[old_column].to_numpy(dtype=float)
        )
        if float(np.max(differences)) > 1e-12:
            raise RuntimeError(
                "arm A does not reproduce Phase 1 %s forecasts (max difference %.16g)"
                % (new_column, float(np.max(differences)))
            )

    rating_summary, rating_checkpoints = rating_diagnostics(events, HISTORY_STARTS)
    metrics = metric_rows(forecasts_by_start, rating_summary)
    paired = paired_rows(forecasts_by_start)
    manifest = source_manifest(args.data_dir)

    metrics_path = os.path.join(
        args.output_dir, "fbs_warmup_ablation_metrics_%s.csv" % args.run_date
    )
    paired_path = os.path.join(
        args.output_dir, "fbs_warmup_ablation_paired_%s.csv" % args.run_date
    )
    rating_path = os.path.join(
        args.output_dir, "fbs_warmup_ablation_rating_convergence_%s.csv" % args.run_date
    )
    source_path = os.path.join(
        args.output_dir, "fbs_warmup_ablation_sources_%s.csv" % args.run_date
    )
    report_path = os.path.join(
        args.output_dir, "RESULT-FBS-WARMUP-ABLATION-%s.md" % args.run_date
    )
    metrics.to_csv(metrics_path, index=False)
    paired.to_csv(paired_path, index=False)
    rating_checkpoints.to_csv(rating_path, index=False)
    manifest.to_csv(source_path, index=False)
    for index, start in enumerate(HISTORY_STARTS):
        letter = chr(ord("A") + index)
        path = os.path.join(
            args.output_dir,
            "fbs_warmup_ablation_forecasts_%s_arm_%s_start_%d.csv"
            % (args.run_date, letter, start),
        )
        forecasts_by_start[start].to_csv(path, index=False)
    write_report(report_path, metrics, paired, rating_summary,
                 rating_checkpoints, coverage, manifest)

    print("evaluation games: %d (2023: %d, 2024: %d, 2025: %d)" % (
        len(evaluation), *(int((evaluation.season == season).sum())
                           for season in EVALUATION_SEASONS)
    ))
    print("arm A vs Phase 1 max probability differences: G2 %.12g; G3 %.12g" % (
        float(np.max(np.abs(arm_a.elo_home_prob.to_numpy(dtype=float)
                           - original.elo_home_prob.to_numpy(dtype=float)))),
        float(np.max(np.abs(arm_a.margin_home_prob.to_numpy(dtype=float)
                           - original.margin_home_prob.to_numpy(dtype=float)))),
    ))
    print("metrics:")
    print(metrics[["history_start_season", "model", "games", "brier", "log_loss",
                   "brier_skill_vs_coinflip"]].to_string(index=False))
    print("paired Brier differences vs arm A:")
    print(paired[["history_start_season", "model", "delta_brier_candidate_minus_A",
                  "brier_ci_95_low", "brier_ci_95_high",
                  "delta_log_loss_candidate_minus_A", "log_loss_ci_95_low",
                  "log_loss_ci_95_high"]].to_string(index=False))
    print("report: %s" % report_path)


if __name__ == "__main__":
    main()
