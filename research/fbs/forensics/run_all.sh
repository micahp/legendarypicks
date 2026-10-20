#!/usr/bin/env bash
# Reproduce the NCAAF C2/G2h parity forensics end to end. See docs/RESULT-ncaaf-parity-forensics.md.
# Requires: the frozen worktree (see common.py), the archive PBP, the audit data dir, and the
# production backend (and optionally the candidate backend). Writes WORK/* and out/*.
set -euo pipefail
cd "$(dirname "$0")"
export FBS_FORENSICS_WORK="${FBS_FORENSICS_WORK:-/tmp/fbs-forensics-work}"
WORK="$FBS_FORENSICS_WORK"
PY="${PY:-/root/legendarypicks/backend/venv/bin/python}"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1   # one thread per process
PROD_BACKEND="${FBS_PROD_BACKEND:-/root/lp-ncaaf-integrity/backend}"
CANDIDATE_BACKEND="${FBS_CANDIDATE_BACKEND:-/root/lp-ncaaf-parity-candidate/backend}"
mkdir -p "$WORK/data" out

$PY 01_replay_writer.py asis "$WORK/replay-asis"
$PY 01_replay_writer.py pinned "$WORK/replay-pinned"
$PY 02_build_frames.py research
$PY 02_build_frames.py production "$PROD_BACKEND" prod_frame.pkl
$PY 03_regen_features.py full "$WORK/feat-full.csv"
$PY 03_regen_features.py prod "$WORK/feat-prod.csv"
$PY 04_block_forensics.py research "$WORK/blk-research"
$PY 04_block_forensics.py production "$WORK/blk-production"
$PY 05_analyze.py
$PY 06_decompose.py "$(cat "$WORK/first_block.txt")"
$PY 07_population_effect.py
$PY 08_path_equivalence.py research "$PROD_BACKEND" fix
$PY 08_path_equivalence.py production "$PROD_BACKEND" fix
$PY 09_production_gate.py "$PROD_BACKEND" "$WORK/data/prod_frame.pkl" fix
if [ -d "$CANDIDATE_BACKEND" ]; then
  $PY 02_build_frames.py production "$CANDIDATE_BACKEND" prod_frame_candidate.pkl
  $PY 09_production_gate.py "$CANDIDATE_BACKEND" "$WORK/data/prod_frame_candidate.pkl" candidate
  $PY 08_path_equivalence.py research "$CANDIDATE_BACKEND" candidate
  PROD_PICKLE="$WORK/data/prod_frame_candidate.pkl" $PY 08_path_equivalence.py production "$CANDIDATE_BACKEND" candidate
fi
echo "done: outputs in $(pwd)/out and $WORK"
