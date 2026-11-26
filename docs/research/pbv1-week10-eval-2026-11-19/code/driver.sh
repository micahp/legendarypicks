#!/bin/sh
# Week 10 three-arm evaluation: A control, B participation field, C field plus PBV1. 20 seeds per game, one game at a time.
W=/root/tnf-batch/w10-eval
cd /tmp
for cfg in $W/2026_10_*/config.json; do
  g=$(basename $(dirname "$cfg"))
  python3 /root/tnf-batch/runner/slc_family_runner.py "$cfg" > "$W/$g/run.log" 2>&1
  echo "$g rc=$? $(date -u +%H:%M:%S)" >> "$W/driver.log"
done
echo DRIVER_DONE >> "$W/driver.log"
