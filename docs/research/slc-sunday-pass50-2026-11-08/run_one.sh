#!/bin/bash
# usage: run_one.sh <game_id> <games> ; all seeds run and failures are recorded (--max-simulation-errors 1000)
g=$1; n=$2; S=/tmp/bench/snapshots; O=/root/ot-sim-out/sunday/$g-n$n
cd /root/lp-slc-v2-sim/scripts/nfl_sequence || exit 1
python3 simulate_pregame_batch.py --snapshot-file $S/$g.json --db /root/legendarypicks/backend/data/picks.dev.db --slc-profile v1_full_stack --playcall-artifact /root/lp-slc-v2-sim/docs/research/SLC-PLAYCALL-ARTIFACT-v1.json --playcall-streak-file /tmp/bench/wl-streaks-2026-11-07.json --slc-fg-ordinary-cutoff 60.0 --slc-blocker-fix run_scramble_backoff --slc-blocker-fix long_field_goal_feasibility --slc-blocker-fix blocked_kick_source_audit --slc-blocker-fix blocked_kick_geometry --slc-blocker-fix safety_free_kick_boundaries --games $n --seed-start 1 --export-boxscores --max-simulation-errors 1000 --out $O > $O.log 2>&1
echo "$g exit=$?" >> /root/ot-sim-out/sunday/status.txt
