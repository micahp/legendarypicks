"""Week 10, remaining game-arm blocks at 100 seeds each.

Picks up where the 1,000-seed family run stopped: every game-arm block that is
not already complete at 1,000 seeds is re-run at 100 seeds into runs100/, in
kickoff order, so the whole 12-game grid can be graded now rather than in
another 11 hours. Finished 1,000-seed blocks are detected, skipped, and left
untouched -- no chunk, ledger, JSON or manifest from that run is written to.

Main arms run 4 wide (the v1 family), the two v1.7 arms run 1 wide, same as the
1,000-seed queue. Each block is labelled tier=100-seed in manifest-100.json,
with the 1,000-seed tier recorded on the blocks that already have it.
"""
import concurrent.futures, importlib.util, json
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/root/ot-sim-out/week10-family-2026-11-15")
SEEDS = 100
SEED_START = 300001
MAIN_WORKERS = 4
V17_WORKERS = 1
MANIFEST = BASE / "manifest-100.json"
BIG_RUNS = BASE / "runs"
SMALL_RUNS = BASE / "runs100"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fam = load("run_week10_family", BASE / "run_week10_family.py")
v17 = load("run_week10_v17", BASE / "run_week10_v17.py")

for module, workers, manifest_name in ((fam, MAIN_WORKERS, "manifest-100.json"),
                                       (v17, V17_WORKERS, "manifest-v17-100.json")):
    module.TOTAL = SEEDS
    module.CHUNK = SEEDS
    module.SEED_START = SEED_START
    module.CONCURRENCY = workers
    module.RUNS = SMALL_RUNS
    module.MANIFEST = BASE / manifest_name


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def big_block_seeds(arm, game):
    """Seeds already produced by the 1,000-seed run for this game-arm block."""
    total, chunks = 0, 0
    for path in sorted((BIG_RUNS / arm).glob("%s-seed-*.json" % game)):
        chunks += 1
        try:
            summary = json.loads(path.read_text()).get("summary") or {}
        except json.JSONDecodeError:
            continue
        total += sum((summary.get("status_counts") or {}).values())
    return chunks, total


def main():
    order = fam.games_in_kickoff_order()
    for _, game, path in order:
        fam.GAMES[game] = path
        v17.GAMES[game] = path

    blocks, finished, jobs = [], [], []
    for (gameday, gametime), game, _path in order:
        for arm in fam.MODELS:
            chunks, seeds = big_block_seeds(arm, game)
            done = chunks == 4 and seeds == 1000
            block = {"arm": arm, "game_id": game, "kickoff_et": [gameday, gametime],
                     "queue": "main", "seed_start": SEED_START, "seeds": SEEDS}
            if done:
                block.update({"tier": "1000-seed", "status": "already_complete_1000",
                              "chunks_at_1000": chunks, "seeds_at_1000": seeds})
                finished.append(block)
            else:
                block.update({"tier": "100-seed", "status": "queued",
                              "carries_1000_seed_partial": {"chunks": chunks, "seeds": seeds}})
                blocks.append(block)
                jobs.append(("family", arm, game, SEED_START, SEEDS))
        for arm in v17.MODELS:
            chunks, seeds = big_block_seeds(arm, game)
            done = chunks == 4 and seeds == 1000
            block = {"arm": arm, "game_id": game, "kickoff_et": [gameday, gametime],
                     "queue": "v1.7", "seed_start": SEED_START, "seeds": SEEDS}
            if done:
                block.update({"tier": "1000-seed", "status": "already_complete_1000",
                              "chunks_at_1000": chunks, "seeds_at_1000": seeds})
                finished.append(block)
            else:
                block.update({"tier": "100-seed", "status": "queued",
                              "carries_1000_seed_partial": {"chunks": chunks, "seeds": seeds}})
                blocks.append(block)
                jobs.append(("v17", arm, game, SEED_START, SEEDS))

    manifest = {"status": "running", "started_at_utc": now(),
                "tier": "100-seed", "seeds_per_game_per_model": SEEDS,
                "seed_start": SEED_START, "runs_dir": str(SMALL_RUNS),
                "main_workers": MAIN_WORKERS, "v17_workers": V17_WORKERS,
                "order_kickoff_et": [[k[0], k[1], g] for k, g, _ in order],
                "blocks": blocks, "skipped_complete_1000": finished,
                "block_count": len(blocks), "skipped_count": len(finished),
                "results": [], "failures": []}
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    def run(job):
        queue, arm, game, start, count = job
        module = fam if queue == "family" else v17
        return queue, module.run_chunk((arm, game, start, count))

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAIN_WORKERS) as main_pool, \
         concurrent.futures.ThreadPoolExecutor(max_workers=V17_WORKERS) as v17_pool:
        futures = {}
        for job in jobs:
            pool = main_pool if job[0] == "family" else v17_pool
            futures[pool.submit(run, job)] = job
        for future in concurrent.futures.as_completed(futures):
            job = futures[future]
            queue, arm, game, start, count = job
            try:
                _queue, result = future.result()
                result.update({"arm": arm, "game_id": game, "tier": "100-seed",
                               "label": "100-seed %s %s" % (arm, game),
                               "kickoff_et": next(b["kickoff_et"] for b in blocks
                                                  if b["arm"] == arm and b["game_id"] == game)})
                manifest["results"].append(result)
                for block in blocks:
                    if block["arm"] == arm and block["game_id"] == game:
                        block["status"] = "complete"
            except Exception as exc:
                manifest["failures"].append({"job": list(job), "error": repr(exc)})
            MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    manifest.update({"status": "complete", "completed_at_utc": now(),
                     "completed_blocks": len(manifest["results"]),
                     "failed_blocks": len(manifest["failures"])})
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
