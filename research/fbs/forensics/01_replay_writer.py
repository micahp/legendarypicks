"""Step 1: run the committed phase3-g writer unchanged, into a scratch directory.

usage: 01_replay_writer.py {asis|pinned} OUT_DIR
  asis   = the writer as committed (its sys.path prepends lp-fbs-audit, so that baseline is used)
  pinned = the frozen Phase 1 baseline is imported first, so the frozen copy is the one used
Run with the frozen worktree as the working directory, so relative research/ paths resolve.
"""
import os
import runpy
import sys

import common

mode, out_dir = sys.argv[1], sys.argv[2]
if mode == "pinned":
    common.use_frozen_research()
sys.argv = ["fbs_phase3_increment_g.py", "--out-dir", out_dir, "--data-dir", common.AUDIT_DATA]
os.chdir(common.FROZEN)
runpy.run_path(os.path.join(common.FROZEN, "backend", "fbs_phase3_increment_g.py"), run_name="__main__")
