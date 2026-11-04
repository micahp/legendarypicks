#!/bin/bash
# Sequential regression runs on the frozen 498 MB extract, seeds 1-3. Each run records its exit code in status.txt.
S=/tmp/claude-0/-root/744b1ddf-da1c-4751-b1ee-106793d5f525/scratchpad
O=$S/rng_regress
DB=$S/frozen/reference-inputs.sqlite
COMMON="--snapshot-file docs/research/slc-week8-2026/snapshots/2026_08_KC_DEN.json --game-id 2026_08_KC_DEN --as-of 2026-10-29T00:02:21Z --db $DB --games 3 --seed-start 1 --context-mode unconditioned --context-bandwidth 1.0 --context-min-source-games 10.0 --try-policy unconditional --progress-every 0 --playcall-artifact docs/research/SLC-PLAYCALL-ARTIFACT-v1.json --slc-profile v1_full_stack --playcall-point-splits --playcall-streak-splits --playcall-streak-file docs/research/slc-week8-2026/wl-streaks-2026-10-29.json --playcall-team-outcomes --playcall-formation --playcall-coverage --playcall-dirichlet-shares --playcall-exact-yardline --playcall-target-roles --playcall-decision --playcall-playbook --playcall-qb-decisions --playcall-player-outcomes --playcall-streak-league"
run() {  # name, tree, extra args...
  local name=$1 tree=$2; shift 2
  cd "$tree" && /usr/bin/python3 scripts/nfl_sequence/simulate_pregame_batch.py $COMMON "$@" --out $O/$name.json > $O/$name.log 2>&1
  echo "$name exit=$?" >> $O/status.txt
}
: > $O/status.txt
run legacy_v1_orig $S/headwt
run v2_orig $S/rngbase --rng-protocol v2
run v2_orig_repeat $S/rngbase --rng-protocol v2
run v2_wt_flagsoff /root/lp-slc-v1 --rng-protocol v2
run v2_wt_pbv1 /root/lp-slc-v1 --rng-protocol v2 --playcall-pbv1-package
echo DONE >> $O/status.txt
