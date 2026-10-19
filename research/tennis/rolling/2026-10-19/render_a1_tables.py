#!/usr/bin/env python3
"""Render the A1 tables in docs/RESULTS-tennis-incumbent-a1-2026-10-19.md from the committed JSON.

Reads a1_per_tour.json (this directory) and research/tennis/lock-audit/2026-10-19/lock_audit.json, and writes
A1-TABLES.md. Numbers are formatted here and nowhere else, so the document cannot drift from the records.
  python3 -I research/tennis/rolling/2026-10-19/render_a1_tables.py
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[4]
YEARS = range(2015, 2027)
MODEL_NAMES = {"M1": "M1 Elo (reference)", "M2_2000": "M2 on 2000 history", "M2_live": "M2 as deployed (2020 history)",
               "B0": "Constant 0.5"}
CAL_NAMES = {"M1": "M1 Elo", "M2_2000": "M2 on 2000 history", "M2_live": "M2 as deployed"}


def signed(v: float) -> str:
    return f"{v:+.5f}"


def ci(pair: list[float]) -> str:
    return f"[{pair[0]:+.5f}, {pair[1]:+.5f}]"


def pad(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def main() -> int:
    a1 = json.loads((HERE / "a1_per_tour.json").read_text())
    locks = json.loads((ROOT / "research" / "tennis" / "lock-audit" / "2026-10-19" / "lock_audit.json").read_text())
    tours = a1["tours"]
    out: list[str] = []

    out.append("#### Population per tour (winner target: completed best-of-three main-tour matches with a surface, one forecast per match)\n")
    out.append(pad(["Year", "ATP", "WTA"]))
    out.append(pad(["---", "---:", "---:"]))
    for yr in YEARS:
        a = tours["atp"]["population"]["per_year"].get(str(yr), 0)
        w = tours["wta"]["population"]["per_year"].get(str(yr), 0)
        out.append(pad([str(yr), f"{a:,}", f"{w:,}"]))
    out.append(pad(["**Total**", f"**{tours['atp']['population']['matches']:,}**",
                    f"**{tours['wta']['population']['matches']:,}**"]))
    out.append("")

    for tour, label in (("atp", "ATP"), ("wta", "WTA")):
        t = tours[tour]
        out.append(f"#### {label}: Brier per match, by evaluation year (each year forecast from data before it)\n")
        out.append(pad(["Model"] + [str(y) for y in YEARS] + ["Pooled", "Log loss"]))
        out.append(pad(["---"] + ["---:"] * (len(YEARS) + 2)))
        for m in ("M1", "M2_2000", "M2_live", "B0"):
            row = [MODEL_NAMES[m]] + [f"{t['brier_per_year'][m][str(y)]:.5f}" if str(y) in t["brier_per_year"][m]
                                      else "" for y in YEARS]
            row += [f"{t['brier_pooled'][m]:.5f}", f"{t['log_loss_pooled'][m]:.5f}"]
            out.append(pad(row))
        out.append("")

        out.append(f"#### {label}: paired Brier difference against M1 (candidate minus M1; negative is better)\n")
        out.append(pad(["Candidate"] + [str(y) for y in YEARS] + ["Pooled, match-clustered 95%", "Years negative"]))
        out.append(pad(["---"] + ["---:"] * (len(YEARS) + 2)))
        for m in ("M2_2000", "M2_live", "B0"):
            row = [MODEL_NAMES[m]]
            row += [signed(t["paired_vs_M1"]["per_year"][str(y)][m]) if str(y) in t["paired_vs_M1"]["per_year"] else ""
                    for y in YEARS]
            p = t["paired_vs_M1"]["pooled"][m]
            row += [f"{signed(p['diff'])} {ci(p['ci95'])}", f"{t['paired_vs_M1']['years_negative'][m]} of "
                                                              f"{t['paired_vs_M1']['years_evaluated']}"]
            out.append(pad(row))
        out.append("")

    out.append("#### Summary: pooled paired differences against M1, per tour\n")
    out.append(pad(["Tour", "Candidate", "Diff", "Match-clustered 95%", "Tournament-clustered 95%",
                    "Years negative", "2020 to 2026 diff, 95%, years negative", "2023 to 2026 diff, 95%, years negative"]))
    out.append(pad(["---", "---", "---:", "---:", "---:", "---:", "---:", "---:"]))
    for tour, label in (("atp", "ATP"), ("wta", "WTA")):
        t = tours[tour]
        for m in ("M2_2000", "M2_live"):
            p = t["paired_vs_M1"]["pooled"][m]
            w20, w23 = t["windows"]["2020_2026"], t["windows"]["2023_2026"]
            out.append(pad([label, MODEL_NAMES[m], signed(p["diff"]), ci(p["ci95"]),
                            ci(t["paired_vs_M1"]["tournament_ci95"][m]),
                            f"{t['paired_vs_M1']['years_negative'][m]} of 12",
                            f"{signed(w20['pooled'][m]['diff'])} {ci(w20['pooled'][m]['ci95'])}, "
                            f"{w20['years_negative'][m]} of {w20['years_evaluated']}",
                            f"{signed(w23['pooled'][m]['diff'])} {ci(w23['pooled'][m]['ci95'])}, "
                            f"{w23['years_negative'][m]} of {w23['years_evaluated']}"]))
    out.append("")

    out.append("#### Calibration of the winner forecasts, per tour (logistic recalibration of the outcome on the forecast logit)\n")
    out.append("Slope 1 and intercept 0 are perfect calibration. Slope below 1 means the forecasts are too confident.")
    out.append("Intervals are match-clustered bootstrap (1,000 resamples). ECE is 10-bin expected calibration error.\n")
    out.append(pad(["Tour", "Window", "Model", "Slope [95%]", "Intercept [95%]", "ECE (10 bins)"]))
    out.append(pad(["---", "---", "---", "---:", "---:", "---:"]))
    for tour, label in (("atp", "ATP"), ("wta", "WTA")):
        for window in ("2015_2026", "2020_2026", "2023_2026"):
            for m in ("M1", "M2_2000", "M2_live"):
                c = tours[tour]["calibration"][window][m]
                out.append(pad([label, window.replace("_", " to "), CAL_NAMES[m],
                                f"{c['slope']:.3f} [{c['slope_ci95'][0]:.3f}, {c['slope_ci95'][1]:.3f}]",
                                f"{c['intercept']:+.4f} [{c['intercept_ci95'][0]:+.4f}, {c['intercept_ci95'][1]:+.4f}]",
                                f"{c['ece_10bin']:.4f}"]))
    out.append("")

    out.append("#### Lock table: which rule reproduces each locked probability\n")
    out.append("Each row is one `tennis_model_locks` row. The rule is the one whose probability matches the stored "
               "probability to 1e-9, with the Elo state rebuilt from 2020-01-01 up to the match day.\n")
    out.append(pad(["Database", "model_version (label)", "Rule that reproduces the row", "Rows", "First locked_at (UTC)",
                    "Last locked_at (UTC)"]))
    out.append(pad(["---", "---", "---", "---:", "---", "---"]))
    for db in locks["databases"]:
        groups: dict[tuple[str, str], list[dict]] = {}
        for r in db["records"]:
            groups.setdefault((r["model_version"], r["rule"]), []).append(r)
        for (version, rule), rows in sorted(groups.items()):
            stamps = sorted(r["locked_at"] for r in rows)
            label = {"unresolved": "no player identity stored in the row",
                     "blend_Hard": "blend, Hard surface"}.get(rule, rule)
            out.append(pad([db["db"], version, label, str(len(rows)), stamps[0][:19].replace("T", " "),
                            stamps[-1][:19].replace("T", " ")]))
    out.append("")

    (HERE / "A1-TABLES.md").write_text("\n".join(out) + "\n")
    print("wrote", HERE / "A1-TABLES.md", len(out), "lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
