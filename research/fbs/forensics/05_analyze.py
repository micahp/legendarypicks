"""Step 5: compare every replay and production variant with the committed phase3-g artifact.

usage: 05_analyze.py  -> prints and writes out/analysis.txt
"""
import os
import sys

import pandas as pd

import common

OUT = os.path.join(common.HERE, "out")
blk = {v: os.path.join(common.WORK, "blk-" + v) for v in ("research", "production")}
C = pd.read_csv(common.COMMITTED_WF, dtype={"game_id": str})[["game_id", "season", "p_c2", "p_g2h"]]
C = C.rename(columns={"p_c2": "c_c2", "p_g2h": "c_g2h"})
lines = []


def say(text):
    print(text, flush=True)
    lines.append(text)


per = {v: pd.read_csv(os.path.join(d, "per_game.csv"), dtype={"game_id": str}) for v, d in blk.items()}
blocks = {v: pd.read_csv(os.path.join(d, "blocks.csv")).fillna("") for v, d in blk.items()}
for v in per:
    m = per[v].merge(C, on="game_id", suffixes=("", "_c"))
    ev = m.season.between(2023, 2025)
    for model, ccol in (("p_c2", "c_c2"), ("p_g2h", "c_g2h")):
        d = (m[model] - m[ccol]).abs()
        say("%-11s inputs  %-6s vs committed: 2022-26 max=%.3g | 2023-25 max=%.3g, rows>1e-6=%d of %d" % (
            v, model, d.max(), d[ev].max(), int((d[ev] > 1e-6).sum()), int(ev.sum())))

mm = blocks["research"].merge(blocks["production"], on="block", suffixes=("_r", "_p"))
say("blocks=%d; training membership identical in all blocks: %s; n_train identical: %s" % (
    len(mm), bool((mm.train_ids_sha_r == mm.train_ids_sha_p).all()), bool((mm.n_train_r == mm.n_train_p).all())))
nonempty = mm[mm.n_train_r > 0]
bad = nonempty[nonempty.train_feat_sha_r != nonempty.train_feat_sha_p]
say("non-empty training blocks=%d; with differing training feature values=%d" % (len(nonempty), len(bad)))
MIN_TRAIN_GAMES = 200  # fbs_phase3_increment.MIN_TRAIN_GAMES
fitted = mm[mm.n_train_r >= MIN_TRAIN_GAMES]
first_fit = fitted.iloc[0]
say("first fitted block (n_train>=200): %s cutoff=%s n_train=%d" % (first_fit.block, first_fit.cutoff_r, first_fit.n_train_r))
say("first block with differing training feature values: %s (n_train=%d)" % (bad.iloc[0].block, bad.iloc[0].n_train_r))
for model, ccol in (("p_c2", "c_c2"), ("p_g2h", "c_g2h")):
    mp = per["production"].merge(per["research"][["game_id", model]], on="game_id", suffixes=("_p", "_r"))
    mp = mp.merge(C[["game_id", ccol]], on="game_id")
    d = (mp[model + "_p"] - mp[model + "_r"]).abs()
    first = mp.assign(d=d).sort_values(["utc_date", "game_id"])
    first = first[first.d > 1e-6].iloc[0]
    rows = mp[mp.block == first.block]
    if model == "p_c2":
        with open(os.path.join(common.WORK, "first_block.txt"), "w") as handle:
            handle.write(first.block + "\n")
    say("%s first divergent block %s (cutoff %s): %d test games; first game %s research=%.6f production=%.6f "
        "diff=%.4f; block max diff=%.4f; divergent rows %d of %d" % (
            model, first.block, first.utc_date.split(" ")[0], len(rows), first.game_id,
            first[model + "_r"], first[model + "_p"], first.d, d[rows.index].max(), int((d > 1e-6).sum()), len(mp)))
mm.to_csv(os.path.join(OUT, "blocks_research_vs_production.csv"), index=False)

# Feature provenance: regenerated frozen-code features vs the committed CSV and vs production.
committed_feats = pd.read_csv(os.path.join(common.FROZEN, "research/fbs/phase3/game_features_c.csv"), dtype={"game_id": str})
feat_lines = []
for tag in ("full", "prod"):
    path = os.path.join(common.WORK, "feat-%s.csv" % tag)
    if not os.path.exists(path):
        continue
    reg = pd.read_csv(path, dtype={"game_id": str})
    m = committed_feats.merge(reg, on="game_id", suffixes=("_c", "_r"))
    worst = max(float((m[c + "_c"] - m[c + "_r"]).abs().max()) for c in common.FEATS)
    feat_lines.append("regenerated features (%s seasons) vs committed game_features_c.csv: rows=%d, max|diff|=%.3g" % (
        tag, len(m), worst))
prod_feat = pd.read_pickle(common.data_path("prod_frame.pkl"))
prod_feat["game_id"] = prod_feat["game_id"].astype(str)
pm = committed_feats.merge(prod_feat[["game_id"] + common.FEATS], on="game_id", suffixes=("_c", "_p"))
feat_lines.append("production build_frame features vs committed game_features_c.csv: rows=%d, rows with any |diff|>1e-9=%d" % (
    len(pm), int(sum(((pm[c + "_c"] - pm[c + "_p"]).abs() > 1e-9) for c in common.FEATS).gt(0).sum())))
for line in feat_lines:
    say(line)

# The writer's own outputs, replayed unchanged, against the committed artifacts.
for mode in ("asis", "pinned"):
    rdir = os.path.join(common.WORK, "replay-" + mode)
    if not os.path.isdir(rdir):
        continue
    for name, key in (("forecasts_walk_forward.csv", "game_id"), ("forecasts_holdout_2025.csv", "game_id"),
                      ("metrics.csv", None), ("paired.csv", None)):
        ours = pd.read_csv(os.path.join(rdir, name), dtype={"game_id": str} if key else None)
        theirs = pd.read_csv(os.path.join(common.FROZEN, "research/fbs/phase3-g", name),
                             dtype={"game_id": str} if key else None)
        if key:
            m = ours.merge(theirs, on=key, suffixes=("_r", "_c"))
            cols = [c[:-2] for c in m.columns if c.endswith("_r") and c[:-2] + "_c" in m.columns and c[:-2] in ("p_g2", "p_c2", "p_g1", "p_g2h")]
            worst = {c: float((m[c + "_r"] - m[c + "_c"]).abs().max()) for c in cols}
            say("replay %-6s %-27s rows=%d: %s" % (mode, name, len(m), ", ".join("%s max=%.2g" % kv for kv in worst.items())))
        else:
            num = ours.select_dtypes("number").columns
            say("replay %-6s %-27s shape=%s, max numeric |diff|=%.2g" % (
                mode, name, ours.shape, float((ours[num] - theirs[num]).abs().max().max())))
open(os.path.join(OUT, "analysis.txt"), "w").write("\n".join(lines) + "\n")
