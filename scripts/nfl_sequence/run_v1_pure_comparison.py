#!/usr/bin/env python3
"""Reproducible V1 vs V1-Pure research comparison on one immutable pregame snapshot.

V1-Pure is a MINIMAL statistical baseline, not a playbook/physics engine.
This runner changes no source model code and does not claim calibration or parity
with a V2 run. Both arms must receive the exact same snapshot, database, score-
clock artifact, seed range, and blocker fixes; the original V1 stays unchanged.

Use --execute to run; without it this tool only writes the experiment plan.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

BLOCKER_FIXES = (
    "long_field_goal_feasibility",
    "blocked_kick_source_audit",
    "blocked_kick_geometry",
    "safety_free_kick_boundaries",
)

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def get_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--snapshot-file", type=Path, required=True)
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--playcall-artifact", type=Path, required=True)
    ap.add_argument("--playcall-streak-file", type=Path, required=True,
                    help="Frozen pregame streak file required only for the historical V1 control")
    ap.add_argument("--seed-start", type=int, default=300001)
    ap.add_argument("--games", type=int, default=1)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--execute", action="store_true", help="Actually run both arms")
    return ap.parse_args(argv)

def main(argv=None):
    args = get_args(argv)
    if args.games < 1 or args.seed_start < 0:
        raise SystemExit("games must be positive and seed-start nonnegative")
    inputs = [args.snapshot_file, args.db, args.playcall_artifact, args.playcall_streak_file]
    for path in inputs:
        if not path.is_file():
            raise FileNotFoundError(path)
    snapshot = json.loads(args.snapshot_file.read_text())
    game_id = snapshot["schedule"]["game_id"]
    repo = Path(__file__).resolve().parents[2]
    batch = repo / "scripts/nfl_sequence/simulate_pregame_batch.py"
    if not batch.is_file():
        raise FileNotFoundError(batch)

    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    common = [
        sys.executable, str(batch),
        "--snapshot-file", str(args.snapshot_file.resolve()),
        "--db", str(args.db.resolve()),
        "--playcall-artifact", str(args.playcall_artifact.resolve()),
        "--seed-start", str(args.seed_start),
        "--games", str(args.games),
        "--export-boxscores",
        "--paired-randomness",
        "--progress-every", "1",
    ]
    for fix in BLOCKER_FIXES:
        common += ["--slc-blocker-fix", fix]
    arms = {
        "v1_original": [
            "--slc-profile", "v1_full_stack",
            "--playcall-streak-file", str(args.playcall_streak_file.resolve()),
            # run_scramble_backoff loads the QB decision table, a layer V1-Pure turns off; only the control keeps it
            "--slc-blocker-fix", "run_scramble_backoff",
        ],
        "v1_pure": [
            "--slc-profile", "custom",
            "--playcall-dirichlet-shares",
        ],
    }
    plan = {
        "schema": "lp-slc-v1-pure-comparison-1",
        "status": "planned",
        "model_identity": {
            "v1_original": "historical v1_full_stack, unmodified",
            "v1_pure": "research: score-clock + historical event sampler + Dirichlet usage; all other optional statistical layers off",
        },
        "game_id": game_id,
        "snapshot_declared_sha256": snapshot.get("snapshot_sha256"),
        "input_sha256": {
            "snapshot_file": sha256(args.snapshot_file),
            "playcall_artifact": sha256(args.playcall_artifact),
            "streak_file": sha256(args.playcall_streak_file),
        },
        "database": {"path": str(args.db.resolve()), "bytes": args.db.stat().st_size,
                     "sha256": None, "verification": "not hashed here; pin separately for a reproducible held-out result"},
        "seed_start": args.seed_start, "seed_count": args.games,
        "paired_rng_requested": True,
        "commands": {},
        "known_limits": [
            "Shared seed IDs do not prove aligned per-event RNG streams or causal pairing",
            "V1-Pure does not choose named football plays or model all 22 players",
            "This runner does not produce or compare any V2 trace",
            "Do not calibrate to the outcome of this one game",
        ],
    }
    commands = {}
    for arm, options in arms.items():
        target = out / f"{game_id}-{arm}.json"
        if target.exists():
            raise FileExistsError(f"will not overwrite an existing result: {target}")
        commands[arm] = common + options + ["--out", str(target)]
        plan["commands"][arm] = shlex.join(commands[arm])
    plan_file = out / "comparison-plan.json"
    if plan_file.exists():
        raise FileExistsError(f"will not overwrite an existing plan: {plan_file}")
    plan_file.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    for arm, command in commands.items():
        print(f"{arm}: {shlex.join(command)}")
    print(f"plan: {plan_file}")
    if not args.execute:
        return 0
    for arm, command in commands.items():
        log_file = out / f"{game_id}-{arm}.log"
        with log_file.open("x") as stream:
            subprocess.run(command, cwd=repo, stdout=stream, stderr=subprocess.STDOUT, check=True)
        print(f"completed {arm}: {log_file}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
