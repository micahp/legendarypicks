# Runbook: parallel dev servers, live-editing under HMR, and this box's resource limits

Written 2026-07-22 after a real incident during NFL Draft Room work (ADP + projections tasks
delegated to Hermes in parallel worktrees). Read this before spinning up more than one
`next dev` / `uvicorn` stack at once on this box.

## The setup

`scripts/hermes-worktree.sh` gives each delegated task its own git worktree with its own
branch, sharing `node_modules` and `backend/venv` via symlink and the dev DB
(`backend/data/picks.dev.db`) via symlink, so state stays consistent across worktrees. Each
worktree gets its own backend (uvicorn) + frontend (`next dev`) pair so an agent can verify its
own work in isolation.

**Known gotcha**: the script hardcodes `BPORT=8096 FPORT=3096` — the SAME ports as the main
dev environment (which serves the live `cloudflared` tunnel someone may be actively looking
at). If the main servers are already up on those ports, the worktree's `up` command silently
fails to bind (logs `Errno 98: address already in use` and the process exits) — it does NOT
kill or replace the main servers, but it also means the worktree has no working servers until
you notice the log and manually relaunch on different ports. Always pick free ports by hand
(`ss -ltnp | grep -E ':80[0-9][0-9]|:30[0-9][0-9]'` first) — this session used 8097/3097,
8098/3098, 8099/3099 for three concurrent worktrees. Verify with a `curl` to both ports after
launch; don't trust the script's printed "backend :8096 frontend :3096" message when those are
already occupied.

## Incident 1: inotify watcher exhaustion

Running 4 `next dev` instances at once (main + 3 worktrees), each watching the entire shared
`node_modules` tree (via symlink) plus its own directory, blew through
`fs.inotify.max_user_watches` (default on this box: 8192 — low for this workload).
Symptom: `Watchpack Error (watcher): Error: ENOSPC: System limit for number of file watchers
reached` spam in the frontend log, and the new worktree's frontend fails to start / hot-reload.

**Fix** (safe, reversible, host-level — did this directly as the operator, not from inside a
delegated worktree): `sysctl -w fs.inotify.max_user_watches=524288` and
`sysctl -w fs.inotify.max_user_instances=512`. Runtime-only (not written to
`/etc/sysctl.conf`), so it resets on reboot — bump it again if this recurs after a restart, or
persist it properly if this becomes routine.

**Residual risk**: even after raising the limit, a `next dev` process whose watcher was
already in the broken ENOSPC state doesn't self-heal — it needs a restart to reinitialize
clean watching. Raising the sysctl limit prevents NEW breakage; it doesn't fix an already-wedged
process.

## Incident 2: editing tracked files under a running dev server

The main frontend (`:3096`) serves directly from `/root/legendarypicks` — the same working
tree used for `git cherry-pick` / conflict resolution / `Edit` tool calls when merging Hermes's
worktree branches back in. Editing tracked files there is live-editing the running server's own
source, which triggers Next's HMR to recompile.

Symptom seen: a `curl` briefly got `ENOENT: .next/server/pages/_document.js` (mid-rebuild race,
resolved itself moments later — harmless), immediately followed by the frontend going
completely unresponsive (every route timed out at 25s+, process still alive per `ps` but not
serving). Root cause was **not** the file edits alone — it coincided with the box being under
severe memory pressure (swap 3.1/4GB used, <1GB RAM free) left over from Incident 1's 4 parallel
stacks plus Hermes's own headless-browser validation, which had already OOM-killed the Hermes
process once. The frontend was likely thrashing (page faults / GC under memory pressure), not
crashed outright — `ps` showed it in running state (`Rl`) the whole time.

**Fix**: free memory first (tear down any worktree dev-server pairs whose tasks are done — check
`git log <worktree> vs dev` to confirm the branch is either merged or its commits already
captured elsewhere before killing), THEN hard-restart the wedged process
(`kill -9`, `rm -rf .next`, relaunch) rather than waiting for it to recover on its own. A `kill`
(not `-9`) followed by a wait didn't unstick it in this incident; had to `-9` it.

**Takeaway — do this next time, in order**:
1. Before merging/cherry-picking Hermes's worktree branches into a feature branch that's
   checked out under a live dev server, consider whether the edit conflicts are trivial
   (rename/small addition) — if so it's fine to resolve directly, same as this session. If a
   conflict resolution is going to be large/iterative, consider doing it in a scratch clone
   instead of the live-served tree.
2. Watch memory (`free -h`) BEFORE spinning up additional parallel worktree stacks, not just
   when something breaks. On this box (5.8GB RAM), each `next dev` + `uvicorn` pair costs
   real headroom — 2 concurrent worktrees is comfortable, 3+ starts eating into swap.
2. Tear down a worktree's dev-server pair as soon as its delegated task is reviewed/merged —
   don't leave idle `next dev`/`uvicorn` processes running "just in case." Check `git log
   <worktree-branch> vs dev` — if the worktree's commits are already an ancestor of (or
   identical to) `dev`'s tip, its servers are pure waste.
3. After any restart of a shared dev process, verify with a real `curl` (not just "the port is
   listening") AND check the required env vars actually landed
   (`tr '\0' '\n' < /proc/<pid>/environ | grep LP_DB_PATH` etc.) — a process that's up but
   missing `LP_DB_PATH`/`GRID_API_KEY`/etc. degrades silently. See
   [[reference_lp_dev_backend_run]] memory for the exact required set.
4. The `cloudflared` tunnel process (`cloudflared tunnel --url http://localhost:3096`) doesn't
   need restarting when the thing behind it restarts — it just proxies to whatever's listening
   on that port. Confirmed in this incident: killed and relaunched the frontend on the same
   port, tunnel kept working with zero action needed on it.

## Quick reference: what was running at peak (this incident)

| Port (BE/FE) | What | Status after cleanup |
|---|---|---|
| 8096 / 3096 | Main dev (live tunnel) | kept, restarted twice (backend for code reload, frontend for the hang) |
| 8097 / 3097 | `lp-mlb-ev-clv` worktree | torn down — task's commits were already `dev`'s tip, fully redundant |
| 8098 / 3098 | `lp-projections-nfl` worktree | torn down after task committed + cherry-picked in |
| 8099 / 3099 | `lp-nfl-adp` worktree | torn down after task committed + cherry-picked in |
