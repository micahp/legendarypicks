#!/bin/bash
# usage: run_failures.sh <game> <seed> ; reruns one seed with the Sunday flags and saves the refused record if it refuses again
g=$1; s=$2; D=/root/ot-sim-out/failures/$g-seed$s; mkdir -p $D
cd /root/lp-slc-v2-sim/scripts/nfl_sequence || exit 1
rm -f /root/ot-sim-out/refused_record.json
timeout 900 python3 /root/ot-sim-out/dump_refused.py --snapshot-file /tmp/bench/snapshots/$g.json --db /root/legendarypicks/backend/data/picks.dev.db --slc-profile v1_full_stack --playcall-artifact /root/lp-slc-v2-sim/docs/research/SLC-PLAYCALL-ARTIFACT-v1.json --playcall-streak-file /tmp/bench/wl-streaks-2026-11-07.json --slc-fg-ordinary-cutoff 60.0 --slc-blocker-fix run_scramble_backoff --slc-blocker-fix long_field_goal_feasibility --slc-blocker-fix blocked_kick_source_audit --slc-blocker-fix blocked_kick_geometry --slc-blocker-fix safety_free_kick_boundaries --export-boxscores --max-simulation-errors 1000 --games 1 --seed-start $s --out $D/rerun > $D/rerun.log 2>&1
rc=$?
if [ -f /root/ot-sim-out/refused_record.json ]; then mv /root/ot-sim-out/refused_record.json $D/refused_record.json; echo refused > $D/reproduced.txt; else echo passed > $D/reproduced.txt; fi
echo "rc=$rc" >> $D/reproduced.txt
