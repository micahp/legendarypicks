import csv, glob, json, os, statistics, sys
GAMES = sorted({os.path.basename(p).split("-n50")[0] for p in glob.glob("/root/ot-sim-out/sunday/*-n50.seeds.jsonl")})
RELAB = {("2026_09_GB_NE", 64), ("2026_09_GB_NE", 96), ("2026_09_GB_NE", 100), ("2026_09_GB_NE", 190), ("2026_09_ARI_SEA", 196), ("2026_09_ARI_SEA", 197)}
rows = []
for g in GAMES:
    seeds = {}
    for path in (f"/root/ot-sim-out/sunday/{g}-n50.seeds.jsonl", f"/root/ot-sim-out/sunday/{g}-s51-n150.seeds.jsonl"):
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            if "header" in r: continue
            o = r.get("outcome", r); seeds[o.get("seed")] = o
    complete = [o for o in seeds.values() if o.get("complete_game") and o.get("away_points") is not None]
    refused = [o for o in seeds.values() if o.get("error") and not o.get("blocker")]
    blocked = [o for o in seeds.values() if o.get("blocker")]
    refused_relabel = [s for s in seeds if (g, s) in RELAB and seeds[s].get("error")]
    away = sorted(o["away_points"] for o in complete); home = sorted(o["home_points"] for o in complete)
    band = lambda v: f"{v[int(0.1*(len(v)-1))]}-{v[int(0.9*(len(v)-1))]}" if len(v) > 1 else ""
    rows.append({"game_id": g, "requested": 200, "seeds_recorded": len(seeds), "validated_complete": len(complete),
                 "refused_validator": len(refused), "refused_pre_fix_now_pass": len(refused_relabel),
                 "blocked": len(blocked), "missing": 200 - len(seeds),
                 "away_median": statistics.median(away) if away else "", "home_median": statistics.median(home) if home else "",
                 "away_p10_p90": band(away), "home_p10_p90": band(home)})
out = "/root/ot-sim-out/sunday/matchup-table-n200.csv"
with open(out, "w", newline="") as h:
    w = csv.DictWriter(h, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
for r in rows: print(r["game_id"], r["validated_complete"], "of", r["requested"], "refused", r["refused_validator"], "now_pass", r["refused_pre_fix_now_pass"], "missing", r["missing"])
