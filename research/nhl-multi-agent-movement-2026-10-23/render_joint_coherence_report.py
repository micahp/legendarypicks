#!/usr/bin/env python3
"""Render the JC research report from its frozen, deterministic results JSON."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HORIZONS = (1, 15, 30, 45)
MODELS = ("M0", "M1", "M2")


def fmt(mean, interval, digits=3):
    if mean is None or interval is None:
        return "not estimable"
    return f"{mean:.{digits}f} [{interval[0]:.{digits}f}, {interval[1]:.{digits}f}]"


def fmt_absolute(cell):
    return fmt(cell["equal_game_mean_available_games"], cell["bootstrap_95_percentile_interval"])


def fmt_delta(cell):
    return fmt(cell["candidate_minus_M0_equal_game_mean_available_games"],
               cell["paired_game_cluster_bootstrap_95_percentile_interval"])


def onset(result, model, metric):
    for step in range(1, 46):
        cell = result["per_horizon_ordinal_increment_not_seconds"][str(step)]["models"][model][metric]
        interval = cell["bootstrap_95_percentile_interval"]
        if interval is not None and (interval[0] > 0 or interval[1] < 0):
            direction = "positive" if interval[0] > 0 else "negative"
            return step, cell["equal_game_mean_available_games"], interval, direction
    return None


def render(data: dict) -> str:
    population = data["population"]
    lines = [
        "# NHL joint movement coherence (JC) report",
        "",
        "## Population and adoption boundary",
        "",
        f"This is a ten-game development study: {population['game_count']} leave-one-whole-game-out clusters, "
        f"{population['rollout_starts']} fixed rollout starts (20 per game), and "
        f"{population['eligible_one_skater_windows']:,} eligible one-skater windows. All horizons are "
        "Image Id suffix increments, not seconds. The ten inspected games are development data; no "
        "independent tracking population is available. **This milestone cannot license adoption, an NHL "
        "simulator claim, or a change to Legendary Picks probabilities.**",
        "",
        "JC scores the already archived M0 independent, M1 interaction, and M2 constrained paths. It "
        "does not refit or alter any policy, constraint, coefficient, or gate. Future labels are used "
        "only for evaluation. M0/M1/M2 keep their existing meanings; JC names the milestone.",
        "",
        "## Frozen sources and scoring coverage",
        "",
        f"The latest preregistration is `{data['preregistration']['legendarypicks_commit']}` on Legendary "
        f"Picks and `{data['preregistration']['gridiron_commit']}` on Gridiron Physics (file SHA-256 "
        f"`{data['preregistration']['sha256']}`). Prediction inputs are the frozen scenario archive "
        f"`{data['source_hashes']['scenario_archive']}` and the {data['scenario_count_scored']} exact start IDs "
        f"in the rollout-start manifest `{data['source_hashes']['rollout_starts']}`. The original input "
        f"archive contained {data['scenario_count_in_input_archive']} recorded scenarios; category-only "
        "examples were not added to the scored start population.",
        "",
        "A state scores only when at least two commonly labeled skaters remain on each team. No target "
        "coordinates are imputed. The complete-case group population declines with horizon:",
        "",
        "| Horizon (ordinal increments, not seconds) | Scored starts / 200 | Game clusters / 10 |",
        "|---|---:|---:|",
    ]
    for step in HORIZONS:
        cell = data["per_horizon_ordinal_increment_not_seconds"][str(step)]
        games = cell["models"]["M0"]["counts"]["represented_games"]
        lines.append(f"| +{step} ordinal increments (not seconds) | {cell['group_states']} | {games} |")
    lines.extend([
        "",
        "Every primary horizon has scored states in all ten games, so its game-cluster intervals use "
        "all ten clusters. Counts and pair denominators below are identical across M0/M1/M2 at a given "
        "horizon because the models are paired on the same common labels.",
        "",
        "## Individual and group dissociation",
        "",
        "Each estimate is an equal-game mean with a 95% whole-game bootstrap interval. One-step endpoint "
        "radial error is the frozen +15 ordinal-increment predictor result (not seconds); rollout radial "
        "error is the autonomous path endpoint at the row's ordinal horizon. Group metrics compare each "
        "generated group with the observed target group. Distances are in rink-coordinate feet.",
        "",
        "| Model | Horizon (ordinal increments, not seconds) | One-step radial error, ft | Rollout radial error, ft | Pooled centroid error, ft | Home / Away centroid error, ft | Team-spacing error, ft | All-pair error mean / P90, ft | Nearest-opponent quantile gap, ft | Scored states / games; common skaters; all pairs (total; mean/state); within-team pairs (total; mean/state) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ])
    one = data["one_step_endpoint_radial_error_plus_15_ordinal_increments_not_seconds"]["models"]
    rollout = data["rollout_endpoint_radial_error_by_primary_horizon_ordinal_increment_not_seconds"]
    group = data["per_horizon_ordinal_increment_not_seconds"]
    for step in HORIZONS:
        for model in MODELS:
            g = group[str(step)]["models"][model]
            c = g["counts"]
            cent_home = fmt_absolute(g["centroid_home_error_ft"])
            cent_away = fmt_absolute(g["centroid_away_error_ft"])
            pairs = f"{c['all_unique_pairs_total']} ({c['mean_all_unique_pairs_per_state']:.2f}/state)"
            within = f"{c['within_team_pairs_total']} ({c['mean_within_team_pairs_per_state']:.2f}/state)"
            state_counts = f"{c['scored_states']}/{c['represented_games']}; {c['mean_common_skaters_per_state']:.2f}; {pairs}; {within}"
            row = [
                model,
                f"+{step} ordinal increments (not seconds)",
                fmt(one[model]["equal_game_mean_ft"], one[model]["game_cluster_bootstrap_95_percentile_interval_ft"]),
                fmt(rollout[str(step)]["models"][model]["equal_game_mean"], rollout[str(step)]["models"][model]["bootstrap_95_percentile_interval"]),
                fmt_absolute(g["centroid_pooled_error_ft"]),
                f"{cent_home} / {cent_away}",
                fmt_absolute(g["team_spacing_error_ft"]),
                f"{fmt_absolute(g['pair_distance_error_mean_ft'])} / {fmt_absolute(g['pair_distance_error_p90_ft'])}",
                fmt_absolute(g["nearest_opponent_quantile_gap_ft"]),
                state_counts,
            ]
            lines.append("| " + " | ".join(row) + " |")

    lines.extend([
        "",
        "The pooled centroid error is the distance between simulated and observed group-mean "
        "displacement vectors. Team spacing is the equal-team mean absolute error in within-team mean "
        "pair distance. All-pair errors compare every unique within-team and opposing-team pair; the "
        "P90 is computed per scored state before equal-game aggregation. Nearest-opponent gap is the "
        "mean absolute difference across the five preregistered quantiles. The full 45-step profile and "
        "per-scenario player/group/pair denominators are in the versioned JSON artifact.",
        "",
        "## Paired differences versus M0",
        "",
        "Cells show candidate minus M0 with paired 95% game-cluster intervals; negative values improve "
        "agreement. The rollout radial column is individual endpoint error. Each horizon is an ordinal "
        "suffix increment, not seconds.",
        "",
        "| Candidate | Horizon (ordinal increments, not seconds) | Rollout radial Δ, ft | Pooled centroid Δ, ft | Home / Away centroid Δ, ft | Team-spacing Δ, ft | All-pair mean / P90 Δ, ft | Nearest-opponent gap Δ, ft |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ])
    for step in HORIZONS:
        for candidate in ("M1", "M2"):
            pd = data["paired_candidate_minus_M0_by_horizon_ordinal_increment_not_seconds"][str(step)][candidate]
            rd = rollout[str(step)]["paired_candidate_minus_M0"][candidate]
            def pair(metric):
                return fmt(pd[metric]["candidate_minus_M0_equal_game_mean_available_games"],
                           pd[metric]["paired_game_cluster_bootstrap_95_percentile_interval"], digits=4)
            row = [
                candidate,
                f"+{step} ordinal increments (not seconds)",
                fmt(rd["equal_game_mean_delta"], rd["bootstrap_95_percentile_interval"], digits=4),
                pair("centroid_pooled_error_ft"),
                f"{pair('centroid_home_error_ft')} / {pair('centroid_away_error_ft')}",
                pair("team_spacing_error_ft"),
                f"{pair('pair_distance_error_mean_ft')} / {pair('pair_distance_error_p90_ft')}",
                pair("nearest_opponent_quantile_gap_ft"),
            ]
            lines.append("| " + " | ".join(row) + " |")

    lines.extend([
        "",
        "## Exact-step spacing diagnostics",
        "",
        "The preregistered signed profile scans every +1 through +45 ordinal increment (not seconds). "
        "The onset below is the earliest unadjusted 95% game-cluster interval excluding zero; the 45 "
        "stepwise looks are descriptive and unadjusted for multiplicity. Positive team bias means the "
        "generated team's mean pair distance is larger than observed; negative means more compact. "
        "Positive nearest-opponent bias means generated nearest-opponent quantiles are farther apart.",
        "",
        "| Model | Signed diagnostic | Earliest step (ordinal increments, not seconds) | Bias, ft (95% game interval) |",
        "|---|---|---:|---:|",
    ])
    signed = (
        ("Home within-team spacing", "team_spacing_signed_home_bias_ft"),
        ("Away within-team spacing", "team_spacing_signed_away_bias_ft"),
        ("Equal-team spacing", "team_spacing_signed_equal_team_bias_ft"),
        ("Nearest-opponent quantiles", "nearest_opponent_signed_quantile_bias_ft"),
    )
    for model in MODELS:
        for label, metric in signed:
            onset_row = onset(data, model, metric)
            if onset_row is None:
                step_text, bias_text = "none through +45", "no unadjusted interval excluded zero"
            else:
                step, mean, interval, direction = onset_row
                step_text = f"+{step} (ordinal increments, not seconds; {direction})"
                bias_text = fmt(mean, interval)
            lines.append(f"| {model} | {label} | {step_text} | {bias_text} |")

    lines.extend([
        "",
        "At the first displayed steps, M1's nearest-opponent signed bias is negative at +1 ordinal "
        "increment (not seconds), while M2's is positive at +1; both interaction-based policies show "
        "negative equal-team spacing bias by +2 ordinal increments (not seconds). These are sub-foot "
        "descriptive biases with unadjusted stepwise intervals, not validated "
        "physical separation or confirmatory evidence. Use the viewer's scrubber and group-metric panel "
        "to inspect the same archived observed and generated frames.",
        "",
        "## JC rule and decision",
        "",
        "The frozen rule requires at least three of four group families to improve at both +1 and +45 "
        "ordinal increments (not seconds), with each paired interval wholly below zero, and no more "
        "than 2% one-step endpoint radial-error degradation.",
        "",
        "| Candidate | One-step radial change vs M0 | Families improved at +1 (ordinal, not seconds) | Families improved at +45 (ordinal, not seconds) | Verdict |",
        "|---|---:|---:|---:|---|",
    ])
    for candidate in ("M1", "M2"):
        decision = data["jc_decisions"][candidate]
        one_step_delta = data["one_step_endpoint_radial_error_plus_15_ordinal_increments_not_seconds"]["paired_candidate_minus_M0"][candidate]
        step1 = sum(v is True for v in decision["group_family_status_by_primary_horizon"]["1"].values())
        step45 = sum(v is True for v in decision["group_family_status_by_primary_horizon"]["45"].values())
        row = [candidate,
               f"{decision['relative_one_step_endpoint_change_percent']:+.2f}% "
               f"(Δ {one_step_delta['candidate_minus_M0_mean_ft']:+.3f} ft, "
               f"95% CI [{one_step_delta['paired_game_cluster_bootstrap_95_percentile_interval_ft'][0]:+.3f}, "
               f"{one_step_delta['paired_game_cluster_bootstrap_95_percentile_interval_ft'][1]:+.3f}])",
               f"{step1}/4", f"{step45}/4", decision["verdict"]]
        lines.append("| " + " | ".join(row) + " |")
    lines.extend([
        "",
        "Neither candidate passes. Both improve the frozen one-step endpoint benchmark, but neither "
        "improves any group family at +1; at +45, only pooled centroid error improves. Team-spacing "
        "error worsens at all four primary horizons for both candidates. Pairwise mean error also "
        "worsens throughout; its +45 P90 interval spans zero, so the all-pair family does not count. "
        "The individual endpoint gains therefore do not establish coherent joint movement.",
        "",
        "## Visual archive and limitations",
        "",
        "The Gridiron Physics branch registers the enriched archive under `jc-2026-10-23-v1`, leaving "
        "the prior `bc91d1610de5` and `43a81ff70918` archives, clips and validation records intact. The "
        "existing four-pane Observed/M0/M1/M2 viewer now shows per-step group metrics and preserves "
        "the 2D rink-side view as a camera projection, not measured 3D movement. Seven new category "
        "clips and screenshots are stored under the JC archive ID.",
        "",
        "The release provides no validated subsecond timebase, cross-game player identity, complete "
        "lineups, event alignment, possession labels, continuous puck flight, contact geometry, or "
        "tracking-error ground truth. Group spacing floors remain empirical 2D proxies. No physical "
        "speed, traction, reaction time, collision, or possession conclusion follows from these results.",
        "",
        "## Reproducibility",
        "",
        f"Evaluation JSON: `research/nhl-multi-agent-movement-2026-10-23/results/joint-coherence-jc-2026-10-23-v1.json`, "
        f"SHA-256 `{data['source_hashes'].get('result_json_sha256', 'see final report')}`. The exact "
        f"evaluator source SHA-256 is `{data['evaluation_code_sha256']}`. It reads the frozen start, "
        "scenario, one-step comparison and fold-model inputs; it does not simulate trajectories. "
        "The evaluation was rerun to a separate temporary path and compared byte-for-byte.",
        "",
        "The report values are equal-game means with 95% whole-game percentile bootstrap intervals "
        "(10,000 draws; seed 20261024). All horizons are ordinal suffix increments, not seconds. JC "
        "is a development diagnostic only; independent games are still required.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=ROOT / "research/nhl-multi-agent-movement-2026-10-23/results/joint-coherence-jc-2026-10-23-v1.json")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/research/NHL-JOINT-COHERENCE-REPORT-2026-10-23.md")
    args = parser.parse_args()
    data = json.loads(args.results.read_text(encoding="utf-8"))
    data["source_hashes"]["result_json_sha256"] = __import__("hashlib").sha256(args.results.read_bytes()).hexdigest()
    content = render(data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8")
    print(f"wrote {args.output} ({len(content.splitlines())} lines)")


if __name__ == "__main__":
    main()
