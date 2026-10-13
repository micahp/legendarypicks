# TASK: audit every stash and worktree — READ ONLY

## Hard scope lock — violating any of these is a failed task

**This task is READ-ONLY. You must not change one byte of repository state.**

FORBIDDEN, no exceptions, not even if you are confident it is safe:
- `git stash drop`, `git stash clear`, `git stash pop`, `git stash apply`
- `git worktree remove`, `git worktree prune`
- `git branch -d` / `-D`, `git checkout`, `git switch`, `git restore`, `git reset`
- `git clean`, `rm`, `mv`, or any deletion anywhere
- `git commit`, `git push`, `git merge`, `git rebase`
- Editing any file except the one output file named below
- Restarting, killing or signalling any process. Several dev servers and ~90 live data
  collectors are running on this box; do not touch them.

ALLOWED: `git stash list`, `git stash show`, `git show`, `git log`, `git diff`,
`git worktree list`, `git status`, `git ls-tree`, `git cat-file`, `ls`, `rg`, `cat`.
Read-only inspection only.

Why this matters concretely: earlier today a `git stash pop` in this repo hit a conflict
on `data/picks.dev.db` and partially applied a stash from a prior session. It was
recovered because the stash was kept. Some of these stashes are the only copy of work
that was never committed. **A dropped stash here is unrecoverable lost work.**

## Working directory

`/root/legendarypicks` (branch `dev`). There are 9 stashes and several worktrees.

## Output

Write findings to **`/root/legendarypicks/docs/AUDIT-stashes-worktrees-2026-09-02.md`**.
That is the ONLY file you may create or modify.

Write RAW findings — the actual file lists, the actual diffstats, the actual branch names.
Not a summary. If a table would be long, let it be long.

## Part 1 — the 9 stashes

`git stash list` currently shows:

```
stash@{0}: On sport-first-navigation: preserve sport-first local data DB before correct dev merge
stash@{1}: On sport-first-navigation: codex-preserve-before-dev-merge-2026-08-26
stash@{2}: On dev: generated caches, pre-merge
stash@{3}: On dev: wip: audit_league_stats + logos + consolidations + stat-gaps (pre-release)
stash@{4}: On league-mls-ncaaf: preserve-mls-residuals-before-consolidation-20260808
stash@{5}: On leagues-cup: preserve-leagues-cup-runtime-logo-before-consolidation-20260808
stash@{6}: On league-news-engine: preserve-runtime-files-before-managed-dev-checkout-20260808
stash@{7}: On league-news-engine: preserve-mixed-wip-before-dev-league-consolidation-20260808
stash@{8}: On player-game-log-away-markers: preserve-main-worktree-before-dev-switch-20260801
```

For EACH stash, report:

1. **Date created** and the branch it was made on.
2. **Full file list** with diffstat (`git stash show --stat stash@{N}`; use
   `--include-untracked` so untracked files in the stash are listed too).
3. **Classification** — the point of the whole exercise. Exactly one of:
   - `SUPERSEDED` — every change in it is already present on `dev` today. Show HOW you
     verified this per file (e.g. `git diff stash@{N} dev -- <path>` is empty, or the
     content is byte-identical). A claim of superseded without a per-file check is not
     acceptable.
   - `UNIQUE` — contains at least one change NOT on `dev`. Name every such file and quote
     the relevant hunk. This is the important category. Say what the change appears to do.
   - `RUNTIME-ONLY` — contains only generated artifacts: `*.db`, `*.db-wal`, `*.db-shm`,
     `*.log`, `__pycache__`, `node_modules`, logo/image caches, `data/` snapshots. These
     are recoverable by re-running, not real work.
   - `MIXED` — both real source and runtime artifacts. List which files fall in which.
4. **Size** of the stash content, and specifically flag any stash containing a `.db` file
   over 1MB (several of these exist and are the reason the stashes are awkward to pop).

Then a summary table: stash / date / branch / classification / file count / verdict.

**Do NOT act on any verdict.** Recommend only. Micah decides what gets dropped.

## Part 2 — the worktrees

`git worktree list` from `/root/legendarypicks`. Known ones include
`/root/lp-sport-first-nav` (port 3097) and `/root/lp-league-mls-ncaaf` (port 3098);
enumerate them all rather than trusting this list.

For EACH worktree report:

1. Path, branch, HEAD sha, and how far ahead/behind `origin/dev` it is
   (`git rev-list --left-right --count origin/dev...HEAD`).
2. **Every uncommitted modification** (`git status --short`), split into tracked
   modifications vs untracked (`??`) files.
3. **For every untracked `??` file: OPEN IT** and say in one line what it is and whether
   it looks like real work or a runtime artifact. Untracked files in worktrees have twice
   before turned out to be production code nobody had committed — this is the single most
   valuable part of this audit. Do not just list the paths.
4. Whether the branch is merged into `dev` (`git branch --merged dev`), i.e. whether the
   worktree is finished work or still in flight.
5. A live-server warning: note if a dev server is running out of that worktree
   (`ss -ltnp` shows 3097/3098 bound). If so, say so loudly in the report — that worktree
   must not be removed while it is serving.

Then a summary table: path / branch / ahead-behind / modified / untracked / merged? /
server running? / verdict.

## Definition of done

`/root/legendarypicks/docs/AUDIT-stashes-worktrees-2026-09-02.md` exists, every stash and
every worktree appears in it, every untracked file in every worktree has been opened and
described, and every `SUPERSEDED` verdict shows its per-file evidence.

Report back in the pane with: the count of stashes in each classification, the count of
untracked files you opened, and the single most surprising thing you found.
