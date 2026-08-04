# Runbook: setting up for heavy feature work

Verified against the box on 2026-08-04. Companion to
`RUNBOOK-parallel-dev-servers-and-hmr.md`, which covers what goes wrong *while*
servers are running; this covers getting set up so it doesn't.

**Read `## The database` before pointing any backend anywhere.** It is the one
that fails silently.

---

## The database

Two real databases, both only in the **main tree**, both regular files — not
symlinks, not copies of each other:

| file | size | what it is |
|---|---|---|
| `/root/legendarypicks/backend/data/picks.db` | ~240 MB | **PROD.** The docker backend on `:8100` serves from it |
| `/root/legendarypicks/backend/data/picks.dev.db` | ~212 MB | dev. What `:8096` serves |

They have **diverged** and are not interchangeable — different player ids, and
dev has had migrations prod has not (and vice versa). A player id verified in dev
may be somebody else in prod: `30085` is the Buffalo Bills D/ST in prod and
Magomed Ankalaev in dev.

### The failure this section exists for

`scripts/hermes-worktree.sh` symlinks the dev DB into a new worktree. **As of
2026-08-04 that symlink exists in exactly one of ten worktrees.** Every other one
has either no `picks.dev.db` at all or a stub — and several carry a ~200 KB
`picks.db` that is not prod and never was.

A backend started in such a worktree comes up fine, answers 200, and serves an
empty database. Nothing raises. So:

```bash
# Before trusting any number from a worktree backend, ask what it opened:
tr '\0' '\n' < /proc/<pid>/environ | grep LP_DB_PATH
ls -la <worktree>/backend/data/picks.dev.db     # symlink, or a stub?
```

`LP_DB_PATH=data/picks.dev.db` is **relative to the process's cwd**, so the same
env var means a different file depending on where uvicorn was launched. Prefer an
absolute path.

### Running the dev backend by hand

`npm run dev:backend` sets neither `LP_DB_PATH` nor `GRID_API_KEY`, and both
degrade quietly:

```bash
cd /root/legendarypicks/backend
LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db GRID_API_KEY=... \
  venv/bin/uvicorn sports_service:app --port 8096 --host 127.0.0.1 --reload
```

### Touching prod data

Prod is `picks.db` and the rules are not negotiable:

- **Back up first.** `migrate_player_stats.py` takes its own backup and prints
  the path; ad-hoc scripts do not. `cp` it and run `PRAGMA quick_check` on the
  copy before believing the backup.
- **Dry-run against a copy of prod, not against dev.** Dev's shape differs, so a
  clean dev run proves nothing about prod. `repair_player_stats_identity.py`
  defaults to `--dry-run` for this reason.
- **Read the loop's break condition before running any ingest against prod.**
  "It worked in dev" has meant "a human pressed Ctrl-C".
- After any migration, run `verify-gates.sh COV-identity` and `COV-statset`
  against the **deployed file** (`LP_GATE_D`), not the branch.

---

## Worktrees

```bash
scripts/hermes-worktree.sh up   <task> [base-branch]   # base defaults to dev
scripts/hermes-worktree.sh down <task>
scripts/hermes-worktree.sh list
```

### `node_modules` is a symlink to the main install

Every worktree's `node_modules` points at `/root/legendarypicks/node_modules`.
**An `npm install` or an `npx` that decides to install inside a worktree mutates
the shared install**, and has emptied it — which then reads as "the main tree's
build is broken" and sends you looking at `.next`. Check the symlink before
blaming a cache.

### Ports

| pair | what |
|---|---|
| `3096` / `8096` | main dev tree. **Externally managed — do not restart** |
| `3097` / `8097` | `hermes-worktree.sh` defaults. **Verify they are free first** — `8097` was occupied by a `lp-nfl-allday` uvicorn on 2026-08-04 |
| `3100` / `8100` | prod, in docker |

A worktree whose servers fail to bind does not stop the agent: it verifies
against whatever is already on that port — the main tree — and reports success.
That is why `verify-gates.sh` requires `LP_GATE_W`, `LP_GATE_B` and `LP_GATE_F`
to be set **together**.

### Cleaning up

`git worktree list` showed **ten** on 2026-08-04, most on branches last touched
in July. A stale worktree is not free: it holds inotify watchers if anything is
running in it, and its stub databases are a trap for the next person who opens
one. `scripts/hermes-worktree.sh down <task>` when the branch is merged.

---

## Before you start heavy work

- [ ] Know which DB you are pointed at, by reading `LP_DB_PATH` off the process
- [ ] Confirm the ports you intend to bind are free (`ss -ltnp`)
- [ ] Check `node_modules` is the symlink you expect
- [ ] Check load before anything CPU-heavy — this box runs a live dev server and
      prod containers (`uptime`, `free -g`)
- [ ] Never `git checkout` / `git reset` under a running `next dev`
- [ ] `git status` after any delegated session — prod timers have run off
      uncommitted scripts before
