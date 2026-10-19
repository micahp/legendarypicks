#!/usr/bin/env python3
"""Render the per-target rolling-origin tables from rolling_summary.json.

Tables are generated from the JSON so that no number is retyped. Each target gets one table: rows are models,
columns are the evaluation years and the pooled value. Differences are candidate minus reference, with a
match-clustered 95% interval. Negative means the candidate is better, since every primary score is lower-is-better.

  python3 -I research/tennis/rolling/2026-10-18/render_rolling_tables.py \
      --summary research/tennis/rolling/2026-10-18/rolling_summary.json \
      --out research/tennis/rolling/2026-10-18/ROLLING-TABLES.md
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

YEARS = tuple(range(2015, 2027))
TITLES = {
    "winner": ("Match winner", "Brier per match", 5),
    "games": ("Total games", "CRPS on the total", 3),
    "counts_aces": ("Aces per player-match", "CRPS", 3),
    "counts_double_faults": ("Double faults per player-match", "CRPS", 3),
}
NAMES = {
    "M1": "M1 Elo (reference)",
    "M2_2000": "M2, 2000 history",
    "M2_live": "M2 as deployed (2020 history)",
    "B0": "Constant 0.5",
    "direct_format": "Direct, format only (reference)",
    "direct_surface": "Direct, format and surface",
    "direct_surface_competitive": "Direct, format, surface and competitiveness",
    "simulator": "Point simulator (exact scoring)",
    "C0": "C0 prior-year tour and surface mean, Poisson (reference)",
    "p0_poisson": "P0 Poisson",
    "p0_gamma_poisson": "P0 Gamma-Poisson",
    "p1_poisson": "P1 Poisson (exposure)",
    "p1_gamma_poisson": "P1 Gamma-Poisson (exposure)",
}


SECONDARY = {
    "winner": "Log loss",
    "games": "Log score (negative log probability of the observed total)",
    "counts_aces": "Log score (negative log probability)",
    "counts_double_faults": "Log score (negative log probability)",
}


def fmt(value: float | None, digits: int) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def interval(entry: dict, digits: int) -> str:
    lo, hi = entry["ci95"]
    return f"{entry['diff']:+.{digits}f} [{lo:+.{digits}f}, {hi:+.{digits}f}]"


def target_table(name: str, summary: dict) -> str:
    title, metric, digits = TITLES[name]
    reference = summary["reference"]
    models = list(summary["models"]["both_pooled"]["mean"].keys())
    ordered = [reference] + [m for m in models if m != reference]
    header = "| Model | " + " | ".join(str(y) for y in YEARS) + " | Pooled |"
    rule = "|---|" + "---:|" * (len(YEARS) + 1)
    lines = [f"#### {title}: {metric}, both tours, both sides of each row pooled", "", header, rule]
    for model in ordered:
        cells = [fmt(summary["models"][f"both_{y}"]["mean"][model], digits) for y in YEARS]
        pooled = fmt(summary["models"]["both_pooled"]["mean"][model], digits)
        lines.append(f"| {NAMES.get(model, model)} | " + " | ".join(cells) + f" | {pooled} |")
    lines += ["", "Paired difference against the reference (candidate minus reference; negative is better), "
              "with match-clustered 95% intervals:", ""]
    diff_header = "| Candidate | " + " | ".join(str(y) for y in YEARS) + " | Pooled, 95% interval | Years negative |"
    lines += [diff_header, "|---|" + "---:|" * (len(YEARS) + 2)]
    for model in ordered:
        if model == reference:
            continue
        cells = [f"{summary['paired'][f'both_{y}'][model]['diff']:+.{digits}f}" for y in YEARS]
        pooled = interval(summary["paired"]["both_pooled"][model], digits)
        negative = summary["paired"]["years_negative"][model]
        lines.append(f"| {NAMES.get(model, model)} | " + " | ".join(cells) + f" | {pooled} | {negative} of 12 |")
    lines += ["", "Pooled difference by tour, with match-clustered 95% intervals:", "",
              "| Candidate | ATP | WTA |", "|---|---:|---:|"]
    for model in ordered:
        if model == reference:
            continue
        atp = interval(summary["paired"]["atp_pooled"][model], digits)
        wta = interval(summary["paired"]["wta_pooled"][model], digits)
        lines.append(f"| {NAMES.get(model, model)} | {atp} | {wta} |")
    lines += ["", "Secondary metrics, pooled over both tours (not used for selection):", ""]
    secondary_name = SECONDARY[name]
    if "secondary_mae" in summary:
        lines += [f"| Model | {secondary_name} | Mean absolute error |", "|---|---:|---:|"]
        for model in ordered:
            lines.append(f"| {NAMES.get(model, model)} | {summary['secondary'][model]:.{digits}f} | "
                         f"{summary['secondary_mae'][model]:.3f} |")
    else:
        lines += [f"| Model | {secondary_name} |", "|---|---:|"]
        for model in ordered:
            lines.append(f"| {NAMES.get(model, model)} | {summary['secondary'][model]:.4f} |")
    lines.append("")
    return "\n".join(lines)


def tournament_block(name: str, summary: dict) -> str:
    """PROTOCOL sensitivity: the pooled difference with tournament clusters beside the match-clustered interval."""
    if "paired_tournament" not in summary:
        return ""
    digits = TITLES[name][2]
    reference = summary["reference"]
    models = [m for m in summary["models"]["both_pooled"]["mean"] if m != reference]
    lines = ["Sensitivity, pooled over both tours: tournament-clustered 95% interval beside the match-clustered one "
             "(PROTOCOL: sensitivity only).", "",
             "| Candidate | Match-clustered 95% | Tournament-clustered 95% |", "|---|---:|---:|"]
    for model in models:
        matched = summary["paired"]["both_pooled"][model]
        tournament = summary["paired_tournament"]["both_pooled"][model]
        lines.append(f"| {NAMES.get(model, model)} | {interval(matched, digits)} | {interval(tournament, digits)} |")
    return "\n".join(lines) + "\n\n"


def selection_block(name: str, summary: dict) -> str:
    sel = summary["selection"]
    lines = [f"**Selection ({name}).** {sel['reason']}. Incumbent: **{NAMES.get(sel['incumbent'], sel['incumbent'])}**."]
    if "margin_top_minus_runner_up" in sel:
        m = sel["margin_top_minus_runner_up"]
        lo, hi = m["ci95"]
        lines.append(
            f" Top candidate {NAMES.get(sel['top'], sel['top'])} against runner-up "
            f"{NAMES.get(sel['runner_up'], sel['runner_up'])}: difference {m['diff']:+.5f} "
            f"[{lo:+.5f}, {hi:+.5f}] over {m['clusters']} matches, negative in {m['years_negative']} of 12 years."
        )
        if "tournament_ci95" in m:
            tlo, thi = m["tournament_ci95"]
            lines.append(f" Tournament-clustered interval for the same margin: [{tlo:+.5f}, {thi:+.5f}] over "
                         f"{m['tournament_clusters']} tournaments.")
    lines.append(f" Clearly better than the reference: {', '.join(sel['clear_over_reference']) or 'none'}.")
    return "".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    data = json.loads(Path(args.summary).read_text())
    parts = ["<!-- generated by render_rolling_tables.py from rolling_summary.json; do not edit by hand -->", ""]
    for name in ("winner", "games", "counts_aces", "counts_double_faults"):
        parts.append(target_table(name, data[name]))
        parts.append(tournament_block(name, data[name]))
        parts.append(selection_block(name, data[name]))
    Path(args.out).write_text("\n".join(parts) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
