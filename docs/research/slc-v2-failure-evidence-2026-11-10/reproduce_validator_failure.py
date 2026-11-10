#!/usr/bin/env python3
"""Replay the saved DEN-CAR seed through the pinned game validator."""
import gzip
import hashlib
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
EVIDENCE = HERE / "failed-game-record.json.gz"
EXPECTED_SHA256 = "6e7531d0e5e828f7a43348142056423be66a4cb61f26b437cd8a6702d54e765c"
EXPECTED_ASSERTION = (
    "drive 12 play 102 state_after: a blocked kick hands over a first down; "
    "found down 1 and 1 to go at yardline 3"
)


def main():
    digest = hashlib.sha256(EVIDENCE.read_bytes()).hexdigest()
    if digest != EXPECTED_SHA256:
        raise SystemExit(f"failure-record hash mismatch: {digest}")

    sys.path.insert(0, str(REPO / "scripts" / "nfl_sequence"))
    import game_state  # noqa: E402
    from football_assertions import FootballAssertionError  # noqa: E402

    with gzip.open(EVIDENCE, "rt", encoding="utf-8") as handle:
        evidence = json.load(handle)
    if evidence.get("schema") != "lp.nfl.failed-game-record.v1":
        raise SystemExit(f"unexpected evidence schema: {evidence.get('schema')}")
    if evidence.get("seed") != 300786 or evidence["record"].get("game_id") != "2026_09_DEN_CAR":
        raise SystemExit("evidence is not DEN-CAR seed 300786")

    try:
        game_state.validate_game(evidence["record"])
    except FootballAssertionError as exc:
        if EXPECTED_ASSERTION not in str(exc):
            raise SystemExit(f"validator failed differently: {exc}") from exc
        print(f"Reproduced {type(exc).__name__} for {evidence['record']['game_id']} seed {evidence['seed']}:")
        print(str(exc))
        return
    raise SystemExit("validator accepted the preserved failed record")


if __name__ == "__main__":
    main()
