"""Export per-seed player draws from SLC boxscore JSONL to compact npz files.

For each (arm, game): one .npz with one int16 array per "<lp_player_id>|<stat>",
ordered by seed, plus a manifest.json. Only the stats the prop markets use.
Raw boxscores stay on the host that ran the sims; only these files are committed.

  export_draws.py RUNS_DIR OUT_DIR [--arms v1,v2,...]
"""
import glob, json, os, re, subprocess, sys
from collections import defaultdict
import numpy as np

STATS = {
    "rec": ("receiving", "rec"), "tgt": ("receiving", "tgt"),
    "rec_yds": ("receiving", "yds"), "rec_td": ("receiving", "td"),
    "att": ("passing", "att"), "cmp": ("passing", "comp"),
    "pass_yds": ("passing", "yds"), "pass_td": ("passing", "td"),
    "rush_att": ("rushing", "att"), "rush_yds": ("rushing", "yds"), "rush_td": ("rushing", "td"),
}

def block_key(path):
    m = re.match(r"(.+)-seed-(\d+)-(\d+)\.boxscores\.jsonl$", os.path.basename(path))
    return m.group(1), int(m.group(2)), int(m.group(3))

def read_block(path):
    rows = []
    config = None
    for line in open(path):
        d = json.loads(line)
        if d.get("type") == "manifest":
            continue
        config = d.get("configuration_hash", config)
        rows.append(d)
    return rows, config

def main(runs_dir, out_dir, arms=None):
    sha = subprocess.run(["git", "-C", os.path.dirname(os.path.dirname(os.path.abspath(runs_dir))), "rev-parse", "HEAD"],
                         capture_output=True, text=True).stdout.strip() or None
    for arm_dir in sorted(glob.glob(os.path.join(runs_dir, "*"))):
        arm = os.path.basename(arm_dir)
        if arms and arm not in arms:
            continue
        by_game = defaultdict(list)
        for path in glob.glob(os.path.join(arm_dir, "*.boxscores.jsonl")):
            game, a, b = block_key(path)
            by_game[game].append((a, path))
        for game, blocks in sorted(by_game.items()):
            seeds, cols, cfg, files = [], defaultdict(list), None, []
            for a, path in sorted(blocks):
                rows, config = read_block(path)
                cfg = config or cfg
                files.append(os.path.basename(path))
                for d in rows:
                    seeds.append(d["seed"])
                    for p in d.get("players", []):
                        pid = p.get("lp_player_id")
                        if pid is None:
                            continue
                        for stat, (group, field) in STATS.items():
                            val = ((p.get(group) or {}).get(field)) or 0
                            cols[(pid, stat)].append(int(val))
            if not seeds:
                continue
            n = len(seeds)
            # Each player is listed on every seed; a player with a short column is a data error.
            short = [k for k, v in cols.items() if len(v) != n]
            if short:
                raise SystemExit("%s %s: %d player columns do not match %d seeds" % (arm, game, len(short), n))
            os.makedirs(os.path.join(out_dir, arm), exist_ok=True)
            arrays = {"%d|%s" % k: np.array(v, dtype=np.int16) for k, v in cols.items()}
            arrays["seeds"] = np.array(seeds, dtype=np.int32)
            np.savez_compressed(os.path.join(out_dir, arm, game + ".npz"), **arrays)
            manifest = {"arm": arm, "game": game, "seeds": n, "configuration_hash": cfg,
                        "source_commit": sha, "source_files": files, "stats": sorted(STATS),
                        "players": len({k[0] for k in cols})}
            with open(os.path.join(out_dir, arm, game + ".manifest.json"), "w") as f:
                json.dump(manifest, f, indent=1)
            print(arm, game, n, "seeds", len({k[0] for k in cols}), "players", flush=True)

if __name__ == "__main__":
    args = sys.argv[1:]
    arms = None
    if "--arms" in args:
        i = args.index("--arms"); arms = set(args[i + 1].split(",")); del args[i:i + 2]
    main(args[0], args[1], arms)
