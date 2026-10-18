#!/usr/bin/env python3
"""Rebuild candidate populations with each frozen source revision, without fitting."""
import argparse
import hashlib
import importlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from pathlib import Path


SOURCES = {
    "v1": ("24d793c6fc10b0a0fee53b651aa1c8771eeca6db",
           ("backend/nfl_player_projection_v2.py", "backend/nfl_rushing_carries_dist_v1.py"),
           "nfl_rushing_carries_dist_v1"),
    "v2": ("a9a46bd05ee75456ee906a6f1254ab5176084f13",
           ("backend/nfl_player_projection_v2.py", "backend/nfl_rushing_participation_v2.py"),
           "nfl_rushing_participation_v2"),
    "v3": ("d7aaeb77c20793077f329c07bdd87e67b15c7fa8",
           ("backend/nfl_player_projection_v2.py", "backend/nfl_rushing_participation_v2.py",
            "backend/nfl_rushing_participation_v3.py"),
           "nfl_rushing_participation_v3"),
    "v4": ("fc6dba4b32341e7322ce5a8d0ae1facedd299ad1",
           ("backend/nfl_player_projection_v2.py", "backend/nfl_rushing_participation_v2.py",
            "backend/nfl_rushing_quantile_map_v4.py"),
           "nfl_rushing_quantile_map_v4"),
}
EXPECTED = {2025: (2500, 240), 2026: (489, 48)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="immutable SQLite snapshot")
    a = ap.parse_args()
    repo = Path(__file__).resolve().parents[3]
    results = {}
    key_sets = {2025: {}, 2026: {}}
    with tempfile.TemporaryDirectory(prefix="lp-population-replay-") as temp_root:
        for version, (commit, paths, module_name) in SOURCES.items():
            folder = Path(temp_root) / version
            folder.mkdir()
            archived = subprocess.run(["git", "archive", commit, *paths], cwd=repo,
                                      check=True, stdout=subprocess.PIPE)
            with tarfile.open(fileobj=io.BytesIO(archived.stdout), mode="r:") as tf:
                tf.extractall(folder)
            sys.path.insert(0, str(folder / "backend"))
            mod = importlib.import_module(module_name)
            if version in ("v1", "v2"):
                eng, builder = mod.eng, mod.build_items
            else:
                eng, builder = mod.v2.eng, mod.v2.build_items
            import sqlite3
            con = sqlite3.connect("file:%s?mode=ro" % Path(a.db).resolve(), uri=True)
            con.execute("PRAGMA query_only=ON")
            hist = eng.History.load(con, [2024, 2025, 2026])
            by_season = {}
            for season in (2025, 2026):
                items = builder(hist, season, weeks=set(range(3, 19)))
                keys = [(item["game_id"], item["pid"]) for item in items]
                n, games = len(items), len({item["game_id"] for item in items})
                if len(set(keys)) != n:
                    raise SystemExit("duplicate player-game key in %s %d" % (version, season))
                want = EXPECTED[season]
                if (n, games) != want:
                    raise SystemExit("population mismatch in %s %d: got %s expected %s" %
                                     (version, season, (n, games), want))
                key_hash = hashlib.sha256("".join(
                    "%s|%s\n" % (game_id, player_id)
                    for game_id, player_id in sorted(keys)).encode()).hexdigest()
                key_sets[season][version] = key_hash
                by_season[str(season)] = {"observations": n, "games": games,
                                          "unique_player_game_keys": len(set(keys)),
                                          "player_game_key_sha256": key_hash,
                                          "weeks_present": dict(sorted(Counter(
                                              item["week"] for item in items).items()))}
            con.close()
            results[version] = {"source_commit": commit, "seasons": by_season}
            for name in ("nfl_rushing_carries_dist_v1", "nfl_rushing_participation_v2",
                         "nfl_rushing_participation_v3", "nfl_rushing_quantile_map_v4",
                         "nfl_player_projection_v2"):
                sys.modules.pop(name, None)
            sys.path.pop(0)
    for season, versions in key_sets.items():
        if len(set(versions.values())) != 1:
            raise SystemExit("version population keys differ in %d: %s" % (season, versions))
    results["population_identity"] = {
        str(season): {"identical_across_v1_v4": True,
                      "player_game_key_sha256": next(iter(set(values.values()))),
                      "versions": values}
        for season, values in key_sets.items()
    }
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
