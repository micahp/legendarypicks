"""Normalise the SBR NHL odds archive into one row per game, for the seasons that carry all markets."""
import glob, json, re, openpyxl

OUT = "/root/lp-data/nhl-sbr/games_2018_2023.jsonl"

def num(v):
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.search(r"-?\d+(?:\.\d+)?", v)
        return float(m.group()) if m else None
    return None

games = []
for f in sorted(glob.glob("/root/lp-data/nhl-sbr/nhl-*.xlsx")):
    import os
    season = os.path.basename(f).replace("nhl-", "").replace(".xlsx", "")
    if season not in ("2018-19", "2019-20", "2020-21", "2021-22", "2022-23"):
        continue
    wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    it = ws.iter_rows(values_only=True)
    hdr = [str(c) if c else "" for c in next(it)]
    idx = {h.replace(" ", "").upper(): i for i, h in enumerate(hdr)}
    I = lambda *n: next(idx[x] for x in n if x in idx)
    iD, iR, iV, iT, iF = I("DATE"), I("ROT"), I("VH"), I("TEAM"), I("FINAL")
    iMO, iMC = I("OPEN"), I("CLOSE")
    iPL, iPP = I("PUCKLINE"), idx[[k for k in idx if k.startswith("PUCKLINE")][0]] + 1
    iUO, iUOP = I("OPENOU"), I("OPENOU") + 1
    iUC, iUCP = I("CLOSE OU".replace(" ", ""), "CLOSEOU"), I("CLOSE OU".replace(" ", ""), "CLOSEOU") + 1

    pending = {}
    for r in it:
        if len(r) < 16 or r[iT] is None:
            continue
        key = (r[iD], (int(r[iR]) + 1) // 2)
        side = "away" if str(r[iV]).upper().startswith("V") else "home"
        pending.setdefault(key, {"season": season, "date": r[iD], "rot": r[iR]})[side] = {
            "team": str(r[iT]).strip(), "final": num(r[iF]),
            "ml_open": num(r[iMO]), "ml_close": num(r[iMC]),
            "puck_line": num(r[iPL]), "puck_price": num(r[iPP]),
            "ou_open": num(r[iUO]), "ou_open_price": num(r[iUOP]),
            "ou_close": num(r[iUC]), "ou_close_price": num(r[iUCP]),
        }
    for key, g in pending.items():
        if "home" in g and "away" in g:
            games.append(g)
    wb.close()

with open(OUT, "w") as fh:
    for g in games:
        fh.write(json.dumps(g) + "\n")

full = sum(1 for g in games
           if all(g[s].get(k) is not None for s in ("home", "away")
                  for k in ("ml_open", "ml_close", "ou_open", "ou_close", "puck_line")))
print("games paired: %d" % len(games))
print("games with ML open+close, OU open+close and a puck line: %d (%.1f%%)" % (full, 100.0 * full / len(games)))
from collections import Counter
c = Counter(g["season"] for g in games)
for s in sorted(c):
    print("  %s: %d" % (s, c[s]))
print("wrote", OUT)
