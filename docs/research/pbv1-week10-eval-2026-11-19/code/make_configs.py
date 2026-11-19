import hashlib, json, os
W = "/root/tnf-batch/w10"
OUT = "/root/tnf-batch/w10-eval"
FIELD = "docs/research/participation-model-2026-11-02/outputs/field_v4_2022_2025.json"
FIELD_SHA = "b53b2566e3abf3874f738f1c26f3e2975c6f03d65887bad9590c276006c9a4c3"
PBV1 = "docs/research/pbv1-package-integration-2026-11-02/pbv1_training_plays.csv"
REF = "831ff0a0"
BLOCKERS = ["run_scramble_backoff", "long_field_goal_feasibility", "blocked_kick_source_audit", "blocked_kick_geometry",
            "safety_free_kick_boundaries"]
CHECKOUT = [
    "scripts", "backend", "docs/fixtures", "docs/espn-team-codes-2026-07-27.json", "docs/props-coverage-baseline.json",
    "docs/research/SLC-PLAYCALL-ARTIFACT-v1.json", "docs/research/SLC-PLAYCALL-ARTIFACT-FIT-2010-2023-v1.json",
    "docs/research/NFL-RULE-REGIME-REGISTRY-2010-2026.json", "docs/research/slc-week8-2026/wl-streaks-2026-10-29.json",
    "docs/research/slc-scoring-realism-ablation-A/obs_sack_cells.json", PBV1,
    "docs/research/participation-model-2026-11-02/outputs"]
games = sorted(d for d in os.listdir(f"{W}/snapshots") if d.startswith("2026_10_"))
assert len(games) == 14, games
for g in games:
    folder = f"{OUT}/{g}"
    os.makedirs(folder, exist_ok=True)
    streak = f"{W}/streaks/{g}.json"
    snap = f"{W}/snapshots/{g}/prospective-1.json"
    shared = ["--slc-profile", "v1_full_stack", "--playcall-artifact", "docs/research/SLC-PLAYCALL-ARTIFACT-v1.json",
              "--progress-every", "250", "--export-boxscores", "--playcall-streak-file", streak]
    field = ["--rng-protocol", "v2", "--participation-field", FIELD, "--participation-field-sha256", FIELD_SHA]
    cfg = {
        "out_dir": f"{folder}/out", "db": "/root/tnf-batch/picks.frozen.db", "snapshot_dir": f"{W}/snapshots",
        "game_glob": g, "source_repo": "/root/legendarypicks",
        "models": [
            {"name": "A-control", "ref": REF, "extra_args": ["--rng-protocol", "v2"]},
            {"name": "B-field", "ref": REF, "extra_args": field},
            {"name": "C-field-pbv1", "ref": REF, "extra_args": field + ["--playcall-pbv1-package", PBV1]},
        ],
        "shared_args": shared, "blocker_fixes": BLOCKERS,
        "pinned_files": [
            {"path": streak, "sha256": hashlib.sha256(open(streak, "rb").read()).hexdigest()},
            {"path": snap, "sha256": hashlib.sha256(open(snap, "rb").read()).hexdigest()}],
        "seeds": {"start": 300001, "total": 20, "chunk": 20}, "concurrency": 3, "checkout_paths": CHECKOUT,
    }
    open(f"{folder}/config.json", "w").write(json.dumps(cfg, indent=1) + "\n")
print("wrote", len(games))
