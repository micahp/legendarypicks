"""Build the scoring-distribution deliverable: markdown report data, XLSX workbook, PNG chart."""
import json
import os

import numpy as np
import pandas as pd
import xlsxwriter
from PIL import Image, ImageDraw, ImageFont

SCRATCH = r"C:\Users\micah\OneDrive\Documents\deepseek-harness\default-workspace\scratch"
REPO = r"C:\Users\micah\OneDrive\Documents\deepseek-harness\default-workspace\slc"
DEST = os.path.join(REPO, "docs", "research", "slc-scoring-review-2026-11-07")
os.makedirs(DEST, exist_ok=True)

r1 = json.load(open(os.path.join(SCRATCH, "out", "summary.json")))
r2 = json.load(open(os.path.join(SCRATCH, "out", "summary2.json")))
freq = pd.read_csv(os.path.join(SCRATCH, "out", "team_score_freq.csv"), index_col=0)
team_means = pd.DataFrame(
    {
        "observed": pd.Series(r2["team_strength"]["observed_team_means"]),
        "v2_sim": pd.Series(r2["v2_discrimination"]["sim_team_means"]),
    }
).sort_values("observed")

OBS = r1["observed_points"]
ARMS = r1["arms_points"]
OG = r1["observed_game"]
AG = r1["arms_game"]
GB = {k.replace("_game_bins", ""): v for k, v in r2.items() if k.endswith("_game_bins")}
DISC = {a: r2[f"{a}_discrimination"] for a in ["v1", "v15", "v2"]}
CE = r2["compensating_errors"]

# ------------------------------------------------------------------ chart: score histogram
def build_png(path):
    W, H = 1240, 660
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    try:
        f_title = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 26)
        f_lab = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 17)
        f_small = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 14)
    except OSError:
        f_title = f_lab = f_small = ImageFont.load_default()

    L, R, T, B = 90, W - 40, 90, H - 90
    ymax = 0.072
    # axes
    d.line([(L, T), (L, B)], fill="#333", width=2)
    d.line([(L, B), (R, B)], fill="#333", width=2)
    d.text((L, 24), "Team score distribution: 2025 NFL observed vs SLC v2 simulated", font=f_title, fill="#111")
    d.text((L, 58), "share of team-games at each point total  (observed n=544 team-games; v2 n=15,726 seed-team-games)",
           font=f_small, fill="#555")

    for i in range(0, 8):
        yv = ymax * i / 7
        y = B - (yv / ymax) * (B - T)
        d.line([(L, y), (R, y)], fill="#e6e6e6", width=1)
        d.text((L - 55, y - 8), f"{yv*100:.0f}%", font=f_small, fill="#666")

    xs = list(freq.index)
    def X(p):
        return L + (p - 0) / 56 * (R - L)
    def Y(v):
        return B - (v / ymax) * (B - T)
    for p in range(0, 57, 4):
        d.line([(X(p), B), (X(p), B + 5)], fill="#999", width=1)
        d.text((X(p) - 8, B + 10), str(p), font=f_small, fill="#444")
    d.text(((L + R) / 2 - 40, B + 40), "points scored by one team", font=f_lab, fill="#333")

    def series(col, color, width, label, fill=None):
        pts = [(X(p), Y(freq[col].iloc[p])) for p in range(0, 56)]
        if fill:
            poly = pts + [(X(55), B), (X(0), B)]
            d.polygon(poly, fill=fill)
        d.line(pts, fill=color, width=width, joint="curve")
        return pts

    series("v2", "#1f6fb4", 3, "v2", fill=(31, 111, 180, 40))
    series("observed", "#d1495b", 3, "observed")

    # legend
    lx, ly = R - 300, T + 10
    d.line([(lx, ly + 8), (lx + 40, ly + 8)], fill="#d1495b", width=4)
    d.text((lx + 50, ly), "2025 observed", font=f_lab, fill="#333")
    d.line([(lx, ly + 38), (lx + 40, ly + 38)], fill="#1f6fb4", width=4)
    d.text((lx + 50, ly + 30), "SLC v2 simulated", font=f_lab, fill="#333")

    # annotations
    notes = [
        "v2 is 12% narrower (sd 8.78 vs 9.94).",
        "Shutouts: 1.29% observed vs 0.26% simulated.",
        "40+ points: 6.43% observed vs 3.23% simulated.",
    ]
    for i, t in enumerate(notes):
        d.text((L + 150, T + 20 + i * 24), t, font=f_small, fill="#444")
    img.save(path)


build_png(os.path.join(SCRATCH, "team_score_distribution.png"))

# ------------------------------------------------------------------ XLSX workbook
wb_path = os.path.join(SCRATCH, "slc-scoring-distribution-analysis.xlsx")
wb = xlsxwriter.Workbook(wb_path)
H1 = wb.add_format({"bold": True, "font_size": 15, "font_color": "#1a1a1a"})
HD = wb.add_format({"bold": True, "bg_color": "#1f3864", "font_color": "white", "border": 1, "valign": "vcenter", "text_wrap": True})
NUM = wb.add_format({"num_format": "0.00", "border": 1})
PCT = wb.add_format({"num_format": "0.0%", "border": 1})
INT = wb.add_format({"num_format": "0", "border": 1})
TXT = wb.add_format({"border": 1})
BAD = wb.add_format({"num_format": "0.00", "border": 1, "bg_color": "#fde2e2"})
GOOD = wb.add_format({"num_format": "0.00", "border": 1, "bg_color": "#e2f2e2"})
NOTE = wb.add_format({"italic": True, "font_color": "#555", "text_wrap": True, "valign": "top"})

# sheet: score bins
ws = wb.add_worksheet("1 score bins")
ws.set_column("A:A", 30)
ws.set_column("B:F", 15)
ws.write("A1", "Team scoring by bin: 2025 observed vs simulated", H1)
ws.write("A2", "Every completed seed counts as one team-game. Observed = 544 team-games from 272 real 2025 games.", NOTE)
hdr = ["measure", "observed", "v1", "v1.5", "v2", "v2 minus observed"]
for c, h in enumerate(hdr):
    ws.write(3, c, h, HD)
rows = [
    ("n team-games", OBS["n"], ARMS["v1"]["n"], ARMS["v15"]["n"], ARMS["v2"]["n"], None),
    ("mean points", OBS["mean"], ARMS["v1"]["mean"], ARMS["v15"]["mean"], ARMS["v2"]["mean"], None),
    ("sd points", OBS["sd"], ARMS["v1"]["sd"], ARMS["v15"]["sd"], ARMS["v2"]["sd"], None),
    ("under 17", OBS["lt17"], ARMS["v1"]["lt17"], ARMS["v15"]["lt17"], ARMS["v2"]["lt17"], None),
    ("17 to 27", OBS["b17_27"], ARMS["v1"]["b17_27"], ARMS["v15"]["b17_27"], ARMS["v2"]["b17_27"], None),
    ("over 27", OBS["gt27"], ARMS["v1"]["gt27"], ARMS["v15"]["gt27"], ARMS["v2"]["gt27"], None),
    ("shutout (0)", OBS["shutout"], ARMS["v1"]["shutout"], ARMS["v15"]["shutout"], ARMS["v2"]["shutout"], None),
    ("6 or fewer", OBS["le6"], ARMS["v1"]["le6"], ARMS["v15"]["le6"], ARMS["v2"]["le6"], None),
    ("35 or more", OBS["ge35"], ARMS["v1"]["ge35"], ARMS["v15"]["ge35"], ARMS["v2"]["ge35"], None),
    ("40 or more", OBS["ge40"], ARMS["v1"]["ge40"], ARMS["v15"]["ge40"], ARMS["v2"]["ge40"], None),
    ("p10", OBS["p10"], ARMS["v1"]["p10"], ARMS["v15"]["p10"], ARMS["v2"]["p10"], None),
    ("p50", OBS["p50"], ARMS["v1"]["p50"], ARMS["v15"]["p50"], ARMS["v2"]["p50"], None),
    ("p90", OBS["p90"], ARMS["v1"]["p90"], ARMS["v15"]["p90"], ARMS["v2"]["p90"], None),
    ("KS distance vs observed", None, ARMS["v1"]["ks_vs_observed"], ARMS["v15"]["ks_vs_observed"], ARMS["v2"]["ks_vs_observed"], None),
]
for i, (name, o, a, b, c, _) in enumerate(rows, start=4):
    ws.write(i, 0, name, TXT)
    for j, v in enumerate([o, a, b, c], start=1):
        if v is None:
            ws.write_blank(i, j, None, TXT)
        elif isinstance(v, int) and name.startswith("n "):
            ws.write_number(i, j, v, INT)
        elif name.startswith("under") or name.startswith("17") or name.startswith("over") or "or more" in name or "or fewer" in name or name.startswith("shutout"):
            ws.write_number(i, j, v, PCT)
        else:
            ws.write_number(i, j, v, NUM)
    if o is not None and isinstance(o, float):
        ws.write_number(i, 5, c - o, NUM)
    else:
        ws.write_blank(i, 5, None, TXT)

chart = wb.add_chart({"type": "column"})
chart.add_series({"name": "observed", "categories": ["1 score bins", 8, 0, 13, 0], "values": ["1 score bins", 8, 1, 13, 1], "fill": {"color": "#d1495b"}})
chart.add_series({"name": "SLC v2", "categories": ["1 score bins", 8, 0, 13, 0], "values": ["1 score bins", 8, 4, 13, 4], "fill": {"color": "#1f6fb4"}})
chart.set_title({"name": "Share of team-games by scoring bin"})
chart.set_y_axis({"num_format": "0%"})
chart.set_size({"width": 720, "height": 380})
ws.insert_chart("A21", chart)

# sheet: tail events
ws2 = wb.add_worksheet("2 game tails")
ws2.set_column("A:A", 34)
ws2.set_column("B:F", 15)
ws2.write("A1", "Game-level tails: what the engine cannot produce often enough", H1)
ws2.write("A2", "One seed = one simulated game. Observed = 272 real 2025 games.", NOTE)
for c, h in enumerate(["measure", "observed", "v1", "v1.5", "v2"]):
    ws2.write(3, c, h, HD)
tail_rows = [
    ("mean total points", "total_mean", "num"),
    ("sd of total points", "total_sd", "num"),
    ("total under 30", "total_lt30", "pct"),
    ("total 40 to 49", "total_40_49", "pct"),
    ("total 60 or more", "total_ge60", "pct"),
    ("both teams under 17", "both_lt17", "pct"),
    ("both teams over 27", "both_gt27", "pct"),
    ("a team under 10", "one_lt10", "pct"),
    ("blowout (margin 21+)", "blowout_ge21", "pct"),
    ("mean absolute margin", "abs_margin_mean", "num"),
    ("tie", "tie", "pct"),
]
for i, (label, key, kind) in enumerate(tail_rows, start=4):
    ws2.write(i, 0, label, TXT)
    for j, src in enumerate([GB["observed"], GB["v1"], GB["v15"], GB["v2"]], start=1):
        ws2.write_number(i, j, src[key], PCT if kind == "pct" else NUM)
chart2 = wb.add_chart({"type": "bar"})
chart2.add_series({"name": "observed", "categories": ["2 game tails", 9, 0, 12, 0], "values": ["2 game tails", 9, 1, 12, 1], "fill": {"color": "#d1495b"}})
chart2.add_series({"name": "SLC v2", "categories": ["2 game tails", 9, 0, 12, 0], "values": ["2 game tails", 9, 4, 12, 4], "fill": {"color": "#1f6fb4"}})
chart2.set_title({"name": "Tail events: observed vs SLC v2"})
chart2.set_x_axis({"num_format": "0%"})
chart2.set_size({"width": 760, "height": 380})
ws2.insert_chart("A18", chart2)

# sheet: team strength
ws3 = wb.add_worksheet("3 team strength")
ws3.set_column("A:A", 12)
ws3.set_column("B:C", 16)
ws3.write("A1", "Does the engine separate strong and weak offenses?", H1)
ws3.write("A2", "Team-season mean points, 2025. Observed means include 17-game sampling noise (sd about 2.41).", NOTE)
ws3.write(3, 0, "team", HD)
ws3.write(3, 1, "observed 2025", HD)
ws3.write(3, 2, "SLC v2 simulated", HD)
for i, (team, row) in enumerate(team_means.iterrows(), start=4):
    ws3.write(i, 0, team, TXT)
    ws3.write_number(i, 1, row["observed"], NUM)
    ws3.write_number(i, 2, row["v2_sim"], NUM)
last = 4 + len(team_means) - 1
ch3 = wb.add_chart({"type": "line"})
ch3.add_series({"name": "observed 2025", "categories": ["3 team strength", 4, 0, last, 0], "values": ["3 team strength", 4, 1, last, 1], "line": {"color": "#d1495b", "width": 2.5}})
ch3.add_series({"name": "SLC v2 simulated", "categories": ["3 team strength", 4, 4, last, 2], "values": ["3 team strength", 4, 2, last, 2], "line": {"color": "#1f6fb4", "width": 2.5}})
ch3.set_title({"name": "Team scoring strength, sorted by observed"})
ch3.set_size({"width": 760, "height": 420})
ws3.insert_chart("E4", ch3)
sf = 4 + len(team_means) + 3
ws3.write(sf, 0, "sd of team-season means", HD)
ws3.write(sf + 1, 0, "observed (raw)", TXT); ws3.write_number(sf + 1, 1, 4.15, NUM)
ws3.write(sf + 2, 0, "observed noise", TXT); ws3.write_number(sf + 2, 1, 2.411, NUM)
ws3.write(sf + 3, 0, "observed true strength", TXT); ws3.write_number(sf + 3, 1, 3.377, NUM)
ws3.write(sf + 4, 0, "v2 simulated", TXT); ws3.write_number(sf + 4, 1, DISC["v2"]["team_season_mean_sd_sim"], NUM)
ws3.write(sf + 5, 0, "v2 as share of true", TXT); ws3.write_number(sf + 5, 1, DISC["v2"]["sim_over_true_ratio"], PCT)
ws3.write(sf + 6, 0, "v1 as share of true", TXT); ws3.write_number(sf + 6, 1, DISC["v1"]["sim_over_true_ratio"], PCT)
ws3.write(sf + 7, 0, "v1.5 as share of true", TXT); ws3.write_number(sf + 7, 1, DISC["v15"]["sim_over_true_ratio"], PCT)
ws3.write(sf + 9, 0, "team-season correlation", TXT); ws3.write_number(sf + 9, 1, DISC["v2"]["team_season_corr"], NUM)
ws3.write(sf + 10, 0, "team-game correlation", TXT); ws3.write_number(sf + 10, 1, DISC["v2"]["team_game_corr"], NUM)

# sheet: mechanism
ws4 = wb.add_worksheet("4 mechanism")
ws4.set_column("A:A", 30)
ws4.set_column("B:E", 15)
ws4.write("A1", "Where the scoring shape is lost: drive-level mechanism", H1)
ws4.write("A2", "Per team-game means, 2025 observed vs v2. bias is sim minus observed; sd_bias is that bias in observed-sd units.", NOTE)
for c, h in enumerate(["metric", "observed", "v2", "bias", "bias in sd"]):
    ws4.write(3, c, h, HD)
mech = pd.DataFrame(r1["drive_half_totals"])
for i, row in enumerate(mech.itertuples(), start=4):
    ws4.write(i, 0, row.metric, TXT)
    ws4.write_number(i, 1, row.observed_mean, NUM)
    ws4.write_number(i, 2, row.v2_mean, NUM)
    ws4.write_number(i, 3, row.v2_bias, BAD if abs(row.v2_std_bias) > 0.4 else NUM)
    ws4.write_number(i, 4, row.v2_std_bias, NUM)
mstart = 4 + len(mech) + 2
ws4.write(mstart, 0, "derived efficiency", HD)
for c, h in enumerate(["measure", "observed", "v2"], start=0):
    pass
ws4.write(mstart + 1, 0, "yards per point", TXT); ws4.write_number(mstart + 1, 1, CE["yards_per_point_observed"], NUM); ws4.write_number(mstart + 1, 2, CE["yards_per_point_sim"], NUM)
ws4.write(mstart + 2, 0, "yards per play", TXT); ws4.write_number(mstart + 2, 1, CE["yards_per_play_observed"], NUM); ws4.write_number(mstart + 2, 2, CE["yards_per_play_sim"], NUM)
ws4.write(mstart + 3, 0, "points per play", TXT); ws4.write_number(mstart + 3, 1, CE["points_per_play_observed"], NUM); ws4.write_number(mstart + 3, 2, CE["points_per_play_sim"], NUM)
ws4.write(mstart + 4, 0, "plays per drive", TXT); ws4.write_number(mstart + 4, 1, CE["plays_per_drive_observed"], NUM); ws4.write_number(mstart + 4, 2, CE["plays_per_drive_sim"], NUM)
ws4.write(mstart + 5, 0, "yards per point inflation", TXT); ws4.write_number(mstart + 5, 2, CE["yards_per_point_inflation"], PCT)

# sheet: provenance
ws5 = wb.add_worksheet("5 provenance")
ws5.set_column("A:A", 34)
ws5.set_column("B:B", 90)
ws5.write("A1", "Provenance and limits of this evidence", H1)
prov = [
    ("source bundle", "docs/research/SLC-2025-REALISM-RESULTS-2026-11-05/ (already in the repo)"),
    ("games", "272 requested, 271 scored; 8,160 seeds per arm (30 per game), three arms"),
    ("observed side", "nflverse nfl_schedule 2025 official scores + nfl_pbp, regular season weeks 1-18"),
    ("observed games", "272 games, 544 team-games"),
    ("simulated side", "V2: 7,863 completed seeds of 8,160 (267 blocked, 30 simulation errors)"),
    ("valid_full_game", "0 in every arm: none of these seeds is a 'valid game' under the snapshot rule"),
    ("development exposure", "development_exposed = true in summary.json: 2025 outcomes were visible during development"),
    ("what that means", "these numbers are in-sample and therefore flattering; the real out-of-sample gap is likely worse"),
    ("what is missing", "per-play sim records, so field position and explosive plays cannot be attributed from this bundle"),
    ("blocked-seed bias", "blocked share 3.27%; uncorrelated with observed scoring extremity (r = -0.07), so blocking is not what truncates the tails"),
    ("hard failure", "2025_07_GB_ARI fails in all three arms for all 30 seeds: 'QB 00-0035228 has no eligible target roles on team ARI'"),
]
for i, (k, v) in enumerate(prov, start=3):
    ws5.write(i, 0, k, TXT)
    ws5.write(i, 1, v, TXT)

# sheet: history of the defect
ws6 = wb.add_worksheet("6 history")
ws6.set_column("A:A", 12)
ws6.set_column("B:B", 78)
ws6.set_column("C:C", 58)
ws6.write("A1", "The spread defect is 25 days old: what was known, and when", H1)
hist = [
    ("2026-10-13", "G4 gate set: team spread floor 0.80. Real-score option measures 0.791 and fails. Real spread 4.571, simulated 3.616.", "docs/RESULTS-nfl-sim-scores-2026-10-13.md"),
    ("2026-10-13", "Follow-up refutes the margin-source hypothesis and localises the cause to the sampler: M3 slope 0.723. Perfect pass-through would only reach ~0.905.", "docs/RESULTS-nfl-sim-g4-elo-2026-10-13.md"),
    ("2026-10-13", "Remedy pre-registered: raise the sampler pass-through (fewer neighbours or variance-restoring step). Branch feat/nfl-sim-g4b assigned.", "docs/CONTEXT-2026-10-13.md line 67"),
    ("2026-10-28", "Integration ledger: detailed offensive and defensive team splits are NOT connected. 'There is no defensive split.'", "docs/research/SLC-INTEGRATION-LEDGER-2026-10-28.md"),
    ("2026-10-29", "SLC team-strength ablation: 3 matchups x 40 seeds, contrasts on home_margin / total_points / home_win only. No variance estimand exists in the analyser.", "docs/research/slc-team-strength-passthrough-2026-10-29/"),
    ("2026-11-05", "2025 backtest, 271 games x 30 seeds x 3 arms: spread still 0.77 of true. Defect unchanged.", "docs/research/SLC-2025-REALISM-RESULTS-2026-11-05.md"),
    ("2026-11-07", "Slate work continues on snapshots, validator rules and one-seed smoke runs. The spread defect is not in the slate completion criteria.", "docs/research/slc-sunday-smoke-2026-11-08/"),
    ("2026-11-07", "Search result: feat/nfl-sim-g4b does not exist on origin. No G4b results document exists. The backend sampler has had no commit since 2026-10-13.", "git ls-remote, git log"),
]
for c, h in enumerate(["date", "what happened", "evidence"]):
    ws6.write(2, c, h, HD)
for i, (dt, what, where) in enumerate(hist, start=3):
    ws6.write(i, 0, dt, TXT)
    ws6.write(i, 1, what, TXT)
    ws6.write(i, 2, where, TXT)
wb.close()

print("wrote", wb_path)
print("wrote", os.path.join(SCRATCH, "team_score_distribution.png"))

# dump a compact numbers json for the report writer
compact = {
    "observed_points": OBS,
    "arms_points": ARMS,
    "observed_game": OG,
    "arms_game": AG,
    "game_bins": GB,
    "disc": DISC,
    "ce": CE,
}
json.dump(compact, open(os.path.join(SCRATCH, "out", "compact.json"), "w"), indent=1, default=str)
