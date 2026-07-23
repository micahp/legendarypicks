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
BPORT=8096   # isolated backend
FPORT=3096   # isolated frontend
CMD="${1:-}"; TASK="${2:-}"; BASE="${3:-analytics-backbone}"
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
  pkill -f "uvicorn sports_service:app --port $BPORT" 2>/dev/null || true
  pkill -f "next dev -p $FPORT" 2>/dev/null || true
  pkill -f "cloudflared tunnel --url http://localhost:$FPORT" 2>/dev/null || true
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
