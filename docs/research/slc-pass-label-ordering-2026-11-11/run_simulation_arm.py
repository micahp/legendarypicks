"""Run one experimental sampler arm against the pinned cutoff-safe input snapshot."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts' / 'nfl_sequence'))
pbp = os.environ.get('SLC_PBP_RELEASE_2026')
if not pbp:
    raise SystemExit('set SLC_PBP_RELEASE_2026 to the SHA-verified 2026 PBP parquet')
import season_layers
season_layers.PBP_RELEASE = pbp
import simulate_pregame_batch

simulate_pregame_batch.main()
