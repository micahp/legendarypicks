---
name: resumable-long-runs
description: Design or run any batch expected to take more than one minute. Require an explicit time and memory budget, visible progress, durable checkpoints, and resume behavior before a long run starts.
---

# Resumable long runs

Use this skill before writing or launching a batch that may take more than one minute, including simulations, backfills, validation sweeps and multi-seed experiments. A slow, silent, restart-from-zero job is not ready to run.

## Before implementing

- Estimate work as input units × work per unit, and state the expected input size. Identify repeated scans, nested loops, hidden subprocesses, threads and whole-dataset copies.
- Bound memory from the data representation and concurrency: reference data + largest in-flight unit + retained results + worker count. Stream rows and aggregate incrementally when possible.
- Time the smallest representative unit. Extrapolate full runtime, include setup/serialization cost, and compare the estimate with the user's deadline.
- If the estimate exceeds ten minutes, optimize or chunk the work before launch. If it still exceeds ten minutes, the job must checkpoint and resume, print progress while running, and have a bounded memory plan. Tell the user the estimate before launch.

## Required behavior for long jobs

- Emit a flushed progress line at least every 30 seconds and every configured work chunk. Include completed/total units, elapsed time, throughput, estimated remaining time, failures and current output/checkpoint path. Use unbuffered output when launched from a pane or redirected log.
- Persist each completed unit as it finishes. Use append-only records or atomic checkpoint replacement; do not keep all results only in memory or wait until process exit to write the first artifact.
- Give every unit a stable key, such as game and seed. On restart, validate a run fingerprint containing code/model version, inputs, configuration and seed range; skip completed units and retry only incomplete or failed units. Refuse to resume against a different fingerprint.
- Preserve failures and blocked units in the ledger. A final summary must distinguish completed, failed, blocked, skipped and pending work and link to the full log and checkpoint.
- Limit concurrency from measured memory, not CPU count. Each worker's data and subprocess memory must fit within the available headroom.

## Launch and verify

1. Report the measured pilot cost, extrapolated duration, peak memory plan, concurrency and checkpoint path before the full run.
2. Check current load and available memory using `resource-check`; run one process or an explicitly budgeted worker count.
3. Start with a small pilot and confirm live progress, durable output and successful resume before scaling up.
4. Monitor progress and memory during execution. If throughput, memory or deadline projections fail the budget, stop cleanly, preserve checkpoints, and report the remaining work.
5. After completion, verify the checkpoint fingerprint, ledger counts, output hashes and summary against the requested population.

Never report a long run as complete until its durable output exists and its pending count is zero.
