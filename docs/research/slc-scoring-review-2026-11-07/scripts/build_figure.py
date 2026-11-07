"""Two-panel figure: score density (left) and team-strength spread (right)."""
import json
import os

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

SCRATCH = r"C:\Users\micah\OneDrive\Documents\deepseek-harness\default-workspace\scratch"
freq = pd.read_csv(os.path.join(SCRATCH, "out", "team_score_freq.csv"), index_col=0)
r2 = json.load(open(os.path.join(SCRATCH, "out", "summary2.json")))
tm = pd.DataFrame(
    {
        "observed": pd.Series(r2["team_strength"]["observed_team_means"]),
        "v2": pd.Series(r2["v2_discrimination"]["sim_team_means"]),
    }
).sort_values("observed")

W, H = 1560, 700
img = Image.new("RGB", (W, H), "white")
d = ImageDraw.Draw(img)
F = "C:/Windows/Fonts/"
f_title = ImageFont.truetype(F + "arialbd.ttf", 25)
f_sub = ImageFont.truetype(F + "arial.ttf", 15)
f_lab = ImageFont.truetype(F + "arial.ttf", 16)
f_bd = ImageFont.truetype(F + "arialbd.ttf", 17)
f_sm = ImageFont.truetype(F + "arial.ttf", 13)

OBS_C = "#d1495b"
SIM_C = "#1f6fb4"
GRID = "#e4e4e4"
INK = "#222"

d.text((50, 22), "SLC v2 compresses team strength: the middle is right, the spread is not", font=f_title, fill="#111")
d.text((50, 56), "2025 backtest: 271 games scored, 30 seeds per game, V2. Left: one team score is close to real. Right: the gap between teams is not.", font=f_sub, fill="#555")

# ---------------- left panel: team score density
L, R, T, B = 80, 740, 120, 600
xs = list(freq.index)
ymax = 0.072
d.line([(L, T), (L, B)], fill="#999", width=1)
d.line([(L, B), (R, B)], fill="#999", width=1)
for i in range(0, 8):
    yv = ymax * i / 7
    y = B - (yv / ymax) * (B - T)
    d.line([(L, y), (R, y)], fill=GRID, width=1)
    d.text((L - 46, y - 7), f"{yv*100:.0f}%", font=f_sm, fill="#666")
for p in range(0, 57, 7):
    x = L + (p / 56) * (R - L)
    d.line([(x, B), (x, B + 5)], fill="#999", width=1)
    d.text((x - 8, B + 9), str(p), font=f_sm, fill="#444")
X = lambda p: L + (p / 56) * (R - L)
Y = lambda v: B - (v / ymax) * (B - T)
for col, c, w in [("observed", OBS_C, 2), ("v2", SIM_C, 3)]:
    pts = [(X(p), Y(freq[col].iloc[p])) for p in range(0, 56)]
    d.line(pts, fill=c, width=w, joint="curve")
d.text((L, T - 34), "A. Every team's score, one game", font=f_bd, fill=INK)
d.text((L, B + 34), "points scored by one team", font=f_lab, fill="#444")
lx = R - 250
d.line([(lx, T + 14), (lx + 34, T + 14)], fill=OBS_C, width=3)
d.text((lx + 42, T + 5), "observed 2025", font=f_lab, fill=INK)
d.line([(lx, T + 44), (lx + 34, T + 44)], fill=SIM_C, width=3)
d.text((lx + 42, T + 35), "SLC v2", font=f_lab, fill=INK)
notes = [
    "Shutouts 1.29% vs 0.26%",
    "40+ points 6.43% vs 3.23%",
    "sd 9.94 vs 8.78",
]
for i, t in enumerate(notes):
    d.text((L + 14, T + 14 + i * 22), t, font=f_sm, fill="#666")

# ---------------- right panel: team strength spread
L2, R2, T2, B2 = 830, 1490, 120, 600
lo, hi = 12.0, 32.0
d.line([(L2, T2), (L2, B2)], fill="#999", width=1)
d.line([(L2, B2), (R2, B2)], fill="#999", width=1)
for v in range(12, 33, 4):
    y = B2 - (v - lo) / (hi - lo) * (B2 - T2)
    d.line([(L2, y), (R2, y)], fill=GRID, width=1)
    d.text((L2 - 42, y - 7), str(v), font=f_sm, fill="#666")
n = len(tm)
for i, (team, row) in enumerate(tm.iterrows()):
    x = L2 + 22 + i * (R2 - L2 - 40) / (n - 1)
    y_o = B2 - (row["observed"] - lo) / (hi - lo) * (B2 - T2)
    y_s = B2 - (row["v2"] - lo) / (hi - lo) * (B2 - T2)
    d.line([(x, y_o), (x, y_s)], fill="#cfcfcf", width=2)
    d.ellipse([x - 4, y_o - 4, x + 4, y_o + 4], fill=OBS_C)
    d.ellipse([x - 4, y_s - 4, x + 4, y_s + 4], fill=SIM_C)
    if i % 2 == 0:
        d.text((x - 13, B2 + 9), team, font=f_sm, fill="#444")
d.text((L2, T2 - 34), "B. Season scoring average, by team", font=f_bd, fill=INK)
d.text((L2, B2 + 30), "each tick is one team, sorted by observed average; grey line joins the pair", font=f_sm, fill="#666")
d.text((L2 + 20, B2 + 56), f"observed range {tm.observed.max()-tm.observed.min():.1f} points   vs   simulated range {tm.v2.max()-tm.v2.min():.1f} points",
       font=f_bd, fill="#7a1020")
img.save(os.path.join(SCRATCH, "scoring_compression.png"))
print("ok")

