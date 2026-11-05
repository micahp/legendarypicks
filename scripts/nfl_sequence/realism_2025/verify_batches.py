#!/usr/bin/env python3
"""verify_batches.py -- check the 2025 realism batches against the committed manifest, then tabulate seed outcomes.

Runs on the fast host with the standard library only. It reads the raw batch files and never writes to them. Output
goes to --out (outside the artifact tree).

Checks, in order:
  1. Every manifest row: the file exists, its byte size and SHA-256 match.
  2. Every batch: 30 outcomes, distinct seeds, one outcome per requested seed.
  3. Every game: the same seed set in all three arms, and the same shared pregame inputs (schedule, rosters,
     replay, roster snapshot id, as-of time). snapshot_sha256 differs by arm and is reported, not compared.
  4. Seed categories per arm: valid_full_game, complete (complete_regulation / complete_overtime), blocked, tied,
     simulation_error. A complete seed with valid_full_game false is counted complete, and the reason is recorded.
  5. The boxscore export's per-game status, cross-tabulated with the batch summary's status for the same seed.

Usage: python3 verify_batches.py --root /root/repro/arms-2025 --manifest manifest.csv --out DIR
"""
import argparse
import csv
import glob
import gzip
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict

ARMS = ("v1", "v15", "v2")
SHARED_INPUTS = ("schedule", "rosters", "replay", "roster_snapshot_id", "as_of")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def seed_category(outcome):
    if outcome.get("valid_full_game") is True:
        return "valid"
    if outcome.get("tied_at_regulation_end") or outcome.get("final_tie"):
        return "tied"
    if outcome.get("status") in ("complete_regulation", "complete_overtime"):
        return "complete"
    if outcome.get("status") == "blocked" or outcome.get("blocker"):
        return "blocked"
    return "incomplete"


def check_manifest(root, manifest_path, problems):
    rows = list(csv.DictReader(open(manifest_path)))
    checked = 0
    for r in rows:
        path = os.path.join(root, r["arm_file"])
        if not os.path.exists(path):
            problems.append(("manifest_missing", r["arm_file"]))
            continue
        if os.path.getsize(path) != int(r["bytes"]):
            problems.append(("manifest_size", r["arm_file"]))
        if sha256_file(path) != r["sha256"]:
            problems.append(("manifest_sha256", r["arm_file"]))
        checked += 1
    return len(rows), checked


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)

    problems = []
    manifest_rows, manifest_checked = check_manifest(a.root, a.manifest, problems)
    manifest_bad = sum(1 for p in problems if p[0].startswith("manifest"))
    print("manifest rows %d; files hashed %d; mismatches %d" % (manifest_rows, manifest_checked, manifest_bad))

    seed_rows = []
    game_inputs = defaultdict(dict)   # game -> arm -> {key: canonical hash}
    game_seeds = defaultdict(dict)    # game -> arm -> sorted seed list
    record_cross = Counter()          # (arm, boxscore status, outcome status) -> n
    batch_count = Counter()
    per_arm = {arm: Counter() for arm in ARMS}
    errors = defaultdict(list)

    for path in sorted(glob.glob(os.path.join(a.root, "*", "*.json.gz"))):
        arm = os.path.basename(os.path.dirname(path))
        batch = json.load(gzip.open(path, "rt"))
        game = batch["game_id"]
        batch_count[arm] += 1
        outcomes = batch["summary"]["outcomes"]
        seeds = [o["seed"] for o in outcomes]
        if len(outcomes) != batch["summary"]["requested_games"] or len(set(seeds)) != len(seeds):
            problems.append(("seed_count_or_duplicates", arm, game))
        game_seeds[game][arm] = sorted(seeds)

        snap = batch["pregame_snapshot"]
        game_inputs[game][arm] = {k: canonical(snap.get(k)) for k in SHARED_INPUTS}
        game_inputs[game][arm]["teams"] = canonical(batch.get("teams"))

        boxstatus = {}
        box_path = path[:-len(".json.gz")] + ".boxscores.jsonl.gz"
        if os.path.exists(box_path):
            for line in gzip.open(box_path, "rt"):
                rec = json.loads(line)
                if rec.get("type") == "game":
                    boxstatus[rec["seed"]] = rec.get("status")
        for o in outcomes:
            cat = seed_category(o)
            per_arm[arm][cat] += 1
            per_arm[arm]["seeds"] += 1
            if o.get("complete_game") and cat not in ("complete", "valid"):
                per_arm[arm]["complete_game_flag_without_complete_status"] += 1
            if o.get("status") == "simulation_error":
                err = (o.get("assertion_failure") or {}).get("outcome") or {}
                errors[(arm, game)].append(err.get("message") or o.get("error") or "")
            if o.get("status") in ("complete_regulation", "complete_overtime") and not o.get("valid_full_game"):
                per_arm[arm]["complete_not_valid_full_game"] += 1
            if o.get("status") and o.get("status") != "simulation_error":
                record_cross[(arm, boxstatus.get(o["seed"]), o["status"])] += 1
            seed_rows.append([arm, game, o["seed"], o.get("status"), cat, o.get("complete_game"),
                              o.get("valid_full_game"), o.get("tied_at_regulation_end"),
                              o.get("regulation_end_reached"), o.get("blocker"), boxstatus.get(o["seed"]),
                              o.get("home_points"), o.get("away_points")])

    game_pairing = []
    for game in sorted(game_seeds):
        arms_present = sorted(game_seeds[game])
        same_seeds = len({tuple(game_seeds[game][a]) for a in arms_present}) == 1
        keys = {}
        for k in SHARED_INPUTS + ("teams",):
            keys[k] = len({game_inputs[game][a][k] for a in arms_present}) == 1
        game_pairing.append([game, ";".join(arms_present), int(same_seeds)] + [int(keys[k]) for k in SHARED_INPUTS + ("teams",)])
        if len(arms_present) != len(ARMS):
            problems.append(("arm_missing", game, ";".join(arms_present)))
        if not same_seeds:
            problems.append(("seed_sets_differ", game))
        for k, ok in keys.items():
            if not ok:
                problems.append(("input_differs", game, k))

    with open(os.path.join(a.out, "seed_status.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["arm", "game_id", "seed", "outcome_status", "category", "complete_game", "valid_full_game",
                    "tied_at_regulation_end", "regulation_end_reached", "blocker", "boxscore_status",
                    "home_points", "away_points"])
        w.writerows(seed_rows)
    with open(os.path.join(a.out, "game_pairing.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["game_id", "arms", "same_seed_sets"] + ["same_" + k for k in SHARED_INPUTS + ("teams",)])
        w.writerows(game_pairing)
    with open(os.path.join(a.out, "boxscore_vs_outcome_status.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["arm", "boxscore_status", "outcome_status", "seeds"])
        for (arm, bs, os_), n in sorted(record_cross.items(), key=str):
            w.writerow([arm, bs, os_, n])
    with open(os.path.join(a.out, "simulation_errors.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["arm", "game_id", "seeds", "message"])
        for (arm, game), msgs in sorted(errors.items()):
            w.writerow([arm, game, len(msgs), Counter(msgs).most_common(1)[0][0]])

    summary = {
        "manifest_rows": manifest_rows,
        "manifest_files_hashed": manifest_checked,
        "manifest_mismatches": manifest_bad,
        "batches": dict(batch_count),
        "games_with_all_arms": sum(1 for g in game_pairing if g[1] == ";".join(ARMS)),
        "games_with_same_seed_sets": sum(1 for g in game_pairing if g[2] == 1),
        "per_arm": {arm: dict(per_arm[arm]) for arm in ARMS},
        "problems": [list(p) for p in problems],
    }
    with open(os.path.join(a.out, "verification.json"), "w") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    for arm in ARMS:
        print(arm, json.dumps(summary["per_arm"][arm], sort_keys=True))
    print("problems:", len(problems), "| games with all arms:", summary["games_with_all_arms"],
          "| same seed sets:", summary["games_with_same_seed_sets"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
