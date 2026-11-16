"""Blocker 3: drive_index in state_before and state_after equals the game-level drive index, on every play of every game.

The known findings are the 23 drives (280 play states) of the archived regression record lp-e2-game-seed1-5fcaa6bc.json, where
E1's drive_index 1 was never replaced. The engine writes the game-level index in game_state._drive_body. This module asserts it
over a corpus of game records and fails closed: any mismatch stops the caller.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import game_state as gs  # noqa: E402


def check_record(record):
    """(mismatched drives, mismatched states, play states checked) for one game record."""
    bad_drives, bad_states, _ = gs.drive_index_mismatches(record)
    checked = sum(2 for d in record['drives'] for _ in d['plays'])
    return len(bad_drives), bad_states, checked


def require_zero(drives, states, label):
    if drives or states:
        raise AssertionError(f'{label}: {drives} drives and {states} play states carry the wrong drive_index')
