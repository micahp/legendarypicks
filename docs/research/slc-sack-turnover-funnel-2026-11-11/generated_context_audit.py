#!/usr/bin/env python3
"""Compare saved SLC dropback states with clean historical exact-cell event rates.

This is a descriptive C3 diagnostic over the already archived 40-game replay.
It does not simulate games and does not claim to reproduce the replay's sampler
probabilities. The saved transitions omit the selected players, modifier inputs,
and stage probabilities, so those effects cannot be reconstructed here.
"""
from __future__ import annotations

import collections
import gzip
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO / "scripts/nfl_sequence"), str(Path(__file__).resolve().parent)]
import audit as event_audit  # noqa: E402
import e0_single_play as e0  # noqa: E402

REPLAY = REPO / "docs/research/slc-down-conversion-replay-2026-11-10/ordered-play-transitions.jsonl.gz"
REPLAY_MANIFEST = REPLAY.with_name("run-manifest.json")
PBP_DIR = Path("/root/lp-snapshots/nfl-backfill-2026-10-27/raw/pbp")
OUT = Path(__file__).with_name("generated-context-results.json")
SEASONS = (2022, 2023, 2024, 2025)
EVENTS = ("sack", "interception", "fumble_lost", "pass_incomplete", "pass_complete")
MIN_CELL_SUPPORT = 10


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_generated():
    by_arm = collections.defaultdict(collections.Counter)
    cells_by_arm = collections.defaultdict(collections.Counter)
    games_by_arm = collections.Counter()
    replay_games = 0
    with gzip.open(REPLAY, "rt") as src:
        for line in src:
            game = json.loads(line)
            replay_games += 1
            arm = game["arm"]
            games_by_arm[arm] += 1
            for play in game["plays"]:
                if play.get("decision_type") != "dropback":
                    continue
                state = play["state_before"]
                cell = e0.pool_key(state["down"], state["yards_to_go"], state["yardline_100"])
                event = play["event_type"]
                if event not in EVENTS:
                    raise ValueError(f"unexpected saved dropback event: {event}")
                by_arm[arm][event] += 1
                cells_by_arm[arm][cell] += 1
    return replay_games, games_by_arm, by_arm, cells_by_arm


def historical_cell_rates():
    overlays, source_manifest = {}, {}
    rows = []
    for season in SEASONS:
        overlays[season], source_manifest[season] = event_audit.penalty_overlay(season)
        source_rows = event_audit.read_rows(season)
        clean, missing = event_audit.apply_overlay(source_rows, overlays[season])
        if missing:
            raise ValueError(f"{missing} {season} source identities lack penalty-overlay matches")
        rows.extend(clean)
    by_game = collections.defaultdict(list)
    for row in rows:
        by_game[row["game_id"]].append(row)
    pool, excluded = collections.defaultdict(collections.Counter), collections.Counter()
    for plays in by_game.values():
        for i, row in enumerate(plays):
            if row.get("season") not in SEASONS or row.get("play_type") != "pass":
                continue
            if row.get("qtr") is None or not 1 <= int(row["qtr"]) <= 4:
                excluded["overtime_or_unknown_quarter"] += 1
                continue
            if row.get("penalty") != 0 or row.get("qb_scramble") == 1:
                continue
            if any(row.get(k) is None for k in ("down", "ydstogo", "yardline_100")):
                excluded["missing_situation"] += 1
                continue
            nxt = plays[i + 1] if i + 1 < len(plays) else None
            hit = event_audit.e1.classify(row, nxt, excluded, include_qb_scrambles=False)
            if hit is None:
                continue
            event = hit[0]
            if event not in EVENTS:
                continue
            cell = e0.pool_key(int(row["down"]), row["ydstogo"], row["yardline_100"])
            pool[cell][event] += 1
    return pool, source_manifest, excluded


def main():
    replay_games, games_by_arm, simulated, simulated_cells = load_generated()
    history, sources, excluded = historical_cell_rates()
    output = {}
    for arm, counts in sorted(simulated.items()):
        total = sum(counts.values())
        supported_n = 0
        expected = collections.Counter()
        unsupported = 0
        for cell, n in simulated_cells[arm].items():
            event_counts = history.get(cell, {})
            support = sum(event_counts.values())
            if support < MIN_CELL_SUPPORT:
                unsupported += n
                continue
            supported_n += n
            for event in EVENTS:
                expected[event] += n * event_counts.get(event, 0) / support
        output[arm] = {
            "games": games_by_arm[arm],
            "dropbacks": total,
            "historical_cell_supported_dropbacks": supported_n,
            "unsupported_context_dropbacks": unsupported,
            "simulated_event_rate": {event: counts[event] / total for event in EVENTS},
            "historical_base_expected_rate_on_supported_generated_contexts": {
                event: expected[event] / supported_n if supported_n else None for event in EVENTS
            },
            "generated_situation_cells": len(simulated_cells[arm]),
        }
    result = {
        "audit": "generated SLC state distribution vs clean historical base exact-cell event rates",
        "scope": "descriptive only; no sampler-stage probabilities were preserved in the replay export",
        "seasons_for_base_rates": list(SEASONS),
        "minimum_historical_cell_support": MIN_CELL_SUPPORT,
        "events": list(EVENTS),
        "replay_games": replay_games,
        "replay_manifest": json.loads(REPLAY_MANIFEST.read_text()),
        "replay_sha256": sha256(REPLAY),
        "replay_manifest_sha256": sha256(REPLAY_MANIFEST),
        "source_penalty_overlays": sources,
        "source_files_sha256": {str(PBP_DIR / f"play_by_play_{season}.parquet"): sha256(PBP_DIR / f"play_by_play_{season}.parquet")
                                 for season in SEASONS},
        "source_exclusions": dict(excluded),
        "arms": output,
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    for arm, row in output.items():
        print(arm, row["dropbacks"], "support", row["historical_cell_supported_dropbacks"],
              "sim", {k: round(v, 4) for k, v in row["simulated_event_rate"].items()},
              "base", {k: round(v, 4) for k, v in row["historical_base_expected_rate_on_supported_generated_contexts"].items()})
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
