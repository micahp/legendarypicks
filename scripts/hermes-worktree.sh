#!/usr/bin/env bash
# hermes-worktree.sh — isolated git worktree + dev servers + tunnel for a delegated task.
#
# Why: Hermes and Claude sharing one working tree race on git staging/commits. A worktree
# gives the delegated task its own checkout (own branch) while SHARING deps (node_modules,
# venv) and the dev DB, plus its own backend/frontend on isolated ports so the agent can
# verify in isolation (on localhost — no auto-tunnel). Merge the branch back when verified.
#
# Usage:
#   scripts/hermes-worktree.sh up   <task> [base-branch]   # default base: analytics-backbone
#   scripts/hermes-worktree.sh down <task>
#   scripts/hermes-worktree.sh list
#
# After `up`, point Hermes at the printed worktree dir + branch + preview URL.
set -euo pipefail

MAIN=/root/legendarypicks
DEV_DB="$MAIN/backend/data/picks.dev.db"
# Isolated ports. These MUST NOT be the main dev environment's ports -- `up` binds them,
# and if the main env is already there the worktree's servers die on startup while the agent
# happily verifies against the MAIN tree and reports success. 3096/8096 were the defaults
# here until 2026-07-27, by which point they were exactly what the main dev env was using
# (the 3095/8095 pair it used to sit on turned out to be zombies from a deleted checkout and
# was killed, promoting 3096/8096 to primary). Overridable so a second concurrent task can
# move again without editing this file.
BPORT="${LP_WT_BPORT:-8097}"
FPORT="${LP_WT_FPORT:-3097}"
CMD="${1:-}"; TASK="${2:-}"; BASE="${3:-dev}"
WT="/root/lp-$TASK"
BR="feat/$TASK"

up() {
  [ -n "$TASK" ] || { echo "usage: up <task> [base]"; exit 1; }
  echo "🌲 worktree '$TASK' off $BASE → $WT (branch $BR)"
  git -C "$MAIN" worktree add "$WT" -b "$BR" "$BASE" 2>/dev/null \
    || git -C "$MAIN" worktree add "$WT" "$BR"

  # Share deps (gitignored, not in the worktree): symlink instead of reinstalling.
  ln -sfn "$MAIN/node_modules"   "$WT/node_modules"
  ln -sfn "$MAIN/backend/venv"   "$WT/backend/venv"
  # Share the dev DB so data is consistent with the main tunnel (WAL allows concurrent reads).
  mkdir -p "$WT/backend/data"
  ln -sfn "$DEV_DB"              "$WT/backend/data/picks.dev.db"

  echo "▶ backend  :$BPORT  (LP_DB_PATH=$DEV_DB)"
  (cd "$WT/backend" && LP_DB_PATH="$DEV_DB" setsid nohup venv/bin/uvicorn sports_service:app \
      --port $BPORT --host 127.0.0.1 >/tmp/hermes-wt-$TASK-backend.log 2>&1 < /dev/null &)
  echo "▶ frontend :$FPORT  (proxy → :$BPORT)"
  (cd "$WT" && API_PROXY_TARGET="http://localhost:$BPORT" setsid nohup npx next dev -p $FPORT \
      >/tmp/hermes-wt-$TASK-frontend.log 2>&1 < /dev/null &)
  # No auto-tunnel. Agents verify on localhost (headless browser runs on this box), so a
  # public trycloudflare URL is only needed for a HUMAN to eyeball it off-box — and they pile
  # up and eat memory on a tight box. Start one on demand (printed below) or SSH-forward.
  echo
  echo "────────────────────────────────────────────────"
  echo "  worktree : $WT"
  echo "  branch   : $BR"
  echo "  frontend : http://127.0.0.1:$FPORT    backend: http://127.0.0.1:$BPORT"
  echo "  Tell Hermes: cd $WT and work there; verify on http://127.0.0.1:$FPORT (headless browser on the box)."
  echo "  Eyeball it off-box:  ssh -L $FPORT:localhost:$FPORT <this-box>  → open http://localhost:$FPORT"
  echo "    or a public preview on demand:  cloudflared tunnel --url http://localhost:$FPORT"
  echo "  Merge when done:  git -C $MAIN merge --ff-only $BR"
  echo "  Tear down:        scripts/hermes-worktree.sh down $TASK"
  echo "────────────────────────────────────────────────"
  echo "  ⚠ Isolation covers this git tree ONLY — it does NOT cover /etc, systemd units, cron,"
  echo "    or anything else host-level/shared. Never edit those from inside the worktree, even"
  echo "    if the task needs a scheduling change to fully take effect — describe what's needed"
  echo "    in the task summary instead and let the operator apply it after reviewing the diff."
  echo "────────────────────────────────────────────────"
}

down() {
  [ -n "$TASK" ] || { echo "usage: down <task>"; exit 1; }
  echo "🧹 tearing down '$TASK'"
  # Kill only processes actually running FROM this worktree's directory (checked via
  # /proc/$pid/cwd), never by hardcoded port alone. BPORT/FPORT are fixed constants
  # reused by every task — a blind `pkill -f "...port $BPORT"` kills the MAIN dev env
  # (or another task manually relaunched on those ports) whenever they happen to be
  # running there too, which is often, since collisions on these same hardcoded ports
  # are exactly why a task gets manually relaunched on different ports in the first
  # place. This killed the main dev tunnel's backend/frontend twice in one session
  # (2026-07-23) before this fix — always verify by cwd, not port.
  for pid in $(pgrep -f "uvicorn sports_service:app" 2>/dev/null); do
    [ "$(readlink -f "/proc/$pid/cwd" 2>/dev/null)" = "$(readlink -f "$WT/backend" 2>/dev/null)" ] && kill "$pid" 2>/dev/null
  done
  for pid in $(pgrep -f "next dev" 2>/dev/null); do
    [ "$(readlink -f "/proc/$pid/cwd" 2>/dev/null)" = "$(readlink -f "$WT" 2>/dev/null)" ] && kill "$pid" 2>/dev/null
  done
  # No cloudflared kill here: `up` never starts one ("No auto-tunnel" by design,
  # see above) — nothing for `down` to legitimately clean up, and killing by port
  # alone is exactly the mistake this function used to make.
  sleep 1
  git -C "$MAIN" worktree remove "$WT" --force 2>/dev/null \
    && echo "  worktree removed (branch $BR kept — merge or delete it)" \
    || echo "  worktree not found / had changes; rm -rf $WT manually if intended"
}

case "$CMD" in
  up)   up ;;
  down) down ;;
  list) git -C "$MAIN" worktree list ;;
  *)    echo "usage: $0 {up <task> [base] | down <task> | list}"; exit 1 ;;
esac
