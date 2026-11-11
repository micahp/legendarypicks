"""Reproduction wrapper for the dated SLC C2 trace run.

Set SLC_PBP_RELEASE_2026 to the downloaded, SHA-verified nflverse parquet.
All remaining command-line arguments are passed to simulate_pregame_batch.
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO / 'scripts' / 'nfl_sequence'))

pbp = os.environ.get('SLC_PBP_RELEASE_2026')
if not pbp:
    raise SystemExit('set SLC_PBP_RELEASE_2026 to the SHA-verified 2026 PBP parquet')

import season_layers  # noqa: E402

season_layers.PBP_RELEASE = pbp

import simulate_pregame_batch  # noqa: E402

simulate_pregame_batch.main()
