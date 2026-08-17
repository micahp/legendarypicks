#!/usr/bin/env bash
# news-lib.sh — shared plumbing for news-collect.sh and news-x-collect.sh.
# Sourced, never executed. Both scripts run the same Python entrypoint against
# the same log, and both had the same defect, so they get one definition of how
# a step is run rather than two copies that will drift.
#
# Expects the caller to have set: PY, LOG.

log(){ printf '[%s] %s\n' "$(date -Is)" "$*" | tee -a "$LOG"; }

# run_step <budget-seconds> <script.py> [args...]
#
# Always returns 0. The caller must reach its next step regardless of how this
# one ended -- that is the contract these scripts always claimed and did not
# keep, because a step that HANGS never fails, it just never returns.
#
# 2026-08-17: `legendarypicks-news` printed its start line and nothing else for
# 15 minutes until the unit's TimeoutStartSec killed the job. Steps 2 and 3 were
# never reached. Result=timeout, no traceback, no partial output.
#
# It is not a rare state. None of the collector's fetchers is bounded: Bluesky
# is 100 requests at `retry_waits=(2,5)` on a 30s socket timeout -- ~150s
# healthy, over two hours against a refusing host -- and X is 17 handles on the
# same shape, a worst case near 1100s. The 08:19 x-only run shows nine handles
# at `<urlopen error timed out>` in a single pass, so the slow path is ordinary
# on this box, not a tail event.
#
# `-u` is load-bearing. The failed run produced NO journal output at all,
# because stdout through `tee` is block-buffered and the buffer died with the
# process. The one artifact that would have named the hung step never reached
# the disk. An unbuffered log is the diagnosis, not a nicety.
STEP_FAILURES=0
FAILED_STEPS=""

run_step(){
  local budget="$1"; shift
  local name="$1"
  local t0=$SECONDS
  local rc took
  timeout --signal=TERM --kill-after=30 "$budget" "$PY" -u "$@" 2>&1 | tee -a "$LOG"
  rc=${PIPESTATUS[0]}
  took=$(( SECONDS - t0 ))
  case "$rc" in
    0)       log "  OK: $name in ${took}s" ;;
    124|137) log "  TIMEOUT: $name hit its ${budget}s budget and was killed —"
             log "           later steps still run. The tail above names the"
             log "           host it was waiting on."
             STEP_FAILURES=$(( STEP_FAILURES + 1 )); FAILED_STEPS="$FAILED_STEPS $name(timeout)" ;;
    *)       log "  WARN: $name exited $rc after ${took}s"
             STEP_FAILURES=$(( STEP_FAILURES + 1 )); FAILED_STEPS="$FAILED_STEPS $name(exit $rc)" ;;
  esac
  return 0
}

# Call last. Runs every step, THEN reports -- "don't abort the next step" and
# "report the job as failed" are different requirements and the script owes both.
#
# Without this the job is green whenever the last line runs, which is always. On
# 2026-08-17 discover_topics.py was taught to exit 1 when its model stage writes
# nothing, and that exit code would have died right here in run_step's
# `return 0` -- a fix that reaches the process and not the operator.
finish(){
  if [ "$STEP_FAILURES" -gt 0 ]; then
    log "=== $STEP_FAILURES step(s) FAILED:$FAILED_STEPS"
    exit 1
  fi
  return 0
}
