# TASK: retire /root/lp-league-mls-ncaaf — PRESERVE FIRST, then remove

Micah has authorised removing the `/root/lp-league-mls-ncaaf` worktree and stopping the
dev servers it runs (frontend 3098, backend 8098).

**You may not delete anything until Phase 1 is committed AND pushed AND verified.**

## Why this is not a simple `git worktree remove`

The branch (`feat/league-mls-ncaaf`) is merged into `dev` and 497 commits behind, so branch
ancestry says "finished". Ancestry is wrong here. The worktree holds **8 untracked files
that do not exist on `dev` at all** — verified file by file with `git cat-file -e dev:<path>`:

```
backend/ingest_rotowire_mls_props.py                    24K   ABSENT FROM DEV
backend/prop_source_identity.py                          8K   ABSENT FROM DEV
backend/test_ingest_rotowire_mls_props.py                8K   ABSENT FROM DEV
backend/test_props_source_policy.py                      8K   ABSENT FROM DEV
components/Props/MarketSlateBoardThreshold.test.tsx      4K   ABSENT FROM DEV
docs/PLAN-rotowire-mls-props-replacement-2026-08-16.md  12K   ABSENT FROM DEV
docs/RESEARCH-MLS-PLAYER-PROP-LINES-2026-08-16.md       12K   ABSENT FROM DEV
docs/ROTOWIRE-PICKS-RELAY.md                            12K   ABSENT FROM DEV
```

Plus **5 tracked modifications**, 216 insertions / 105 deletions:
`backend/_core.py`, `backend/data/esports_team_logos.json`,
`backend/ingest_underdog_props.py`, `backend/routers/props.py`,
`components/Props/MarketSlateBoard.tsx`.

`backend/venv` is a virtualenv — **exclude it**, never commit it.

Deleting this worktree today, without Phase 1, permanently destroys an entire RotoWire MLS
props ingest module, its two test files, a source-identity module, and three research and
planning documents. That is the whole reason this task exists.

## Phase 1 — PRESERVE, and land the additive work on `dev`

Micah wants this work on `dev`, not parked on a side branch. But the two kinds of change
here are **not** equally safe, and the difference is the crux of this task:

- **The 8 untracked files are purely additive.** They do not exist on `dev` at any path.
  Adding them cannot revert anything. **These go to `dev`.**
- **The 5 tracked modifications are built on a 497-commit-stale base.** `backend/routers/props.py`
  and `components/Props/MarketSlateBoard.tsx` are the two most-edited files in the repo this
  week (NCAAF props, Leagues Cup, alternate lines, the prop chart rebuild all landed on them
  since). Replaying this worktree's old versions onto `dev` would **revert** that work — the
  diff against `dev` is 174 insertions against **508 deletions**, and those deletions are
  live code. **These do NOT go to `dev`.** They are preserved on the branch for Micah to
  review hunk by hunk later.

If you find yourself about to `git checkout` an old version of `props.py` onto `dev`, stop:
that is the failure this section exists to prevent.

### 1a — preserve everything on a branch (the safety net)

Inside `/root/lp-league-mls-ncaaf`:

1. `git switch -c preserve/mls-ncaaf-worktree-20260902`
2. Stage **explicitly by path** — never `git add -A`, never `git add .`, never `backend/venv`.
   Stage the 8 untracked files AND the 5 tracked modifications.
3. Commit. Say plainly this is preserved worktree state captured before retirement, and list
   what it holds. Do not attribute the commit to any AI tool.
4. `git push -u origin preserve/mls-ncaaf-worktree-20260902`
5. **VERIFY or STOP:** `git ls-remote --heads origin preserve/mls-ncaaf-worktree-20260902`
   returns a sha, and `git show --stat origin/preserve/...` lists all 8 untracked files.

### 1b-MERGE — SUPERSEDES 1b BELOW. Merge `dev` in, then investigate.

Micah's call, and it is the better one: do not discard the 5 tracked edits unevaluated.
Instead bring the branch up to current `dev` and find out what those 216 insertions are
actually worth against today's code.

On `preserve/mls-ncaaf-worktree-20260902` (after 1a is pushed, so there is always a way back):

1. `git merge origin/dev` — expect conflicts in `backend/routers/props.py` and
   `components/Props/MarketSlateBoard.tsx` at minimum.
2. **This is an investigation, not a resolution race.** For EVERY conflicted hunk, classify it:
   - `SUPERSEDED` — dev already does this, better or equivalently. Take dev's side.
   - `UNIQUE` — the worktree does something dev genuinely does not. Keep it, and say what
     capability it adds.
   - `CONFLICTING` — both changed the same behaviour in incompatible ways. **Do not pick a
     winner.** Take dev's side to keep the merge moving, and write the worktree's version of
     the hunk into your report verbatim so Micah can decide.
3. Resolve so the merge completes with `dev`'s behaviour intact wherever there is doubt. The
   default is dev wins; the worktree only wins where it is provably additive.
4. `python3 -m py_compile` every changed `.py`, and `npx tsc --noEmit` for the two `.tsx`.
5. Commit the merge, push the branch.
6. **Do NOT merge this branch into `dev` yourself.** Report and stop; Micah decides.

Write the investigation to `/root/legendarypicks/docs/AUDIT-mls-ncaaf-merge-2026-09-02.md`:
a table of every conflicted hunk (file, lines, classification, one-line reason), then the
verbatim text of every `CONFLICTING` hunk. Raw, not summarised.

The question to answer: **is there anything in this worktree worth having on `dev`, or is it
all superseded?** Say so plainly either way. "All superseded" is a perfectly good answer and
means the worktree can be retired with nothing lost.

### 1b (original, now superseded by 1b-MERGE) — bring ONLY the 8 additive files to `dev`

Work in the main checkout `/root/legendarypicks` (branch `dev`).

1. `git status --short` first. **`dev` has substantial uncommitted work in progress — do not
   touch, stage, revert or stash any of it.** If that makes a clean commit impossible, STOP
   and report rather than working around it.
2. Copy the 8 files from the preserve branch by exact path:
   `git checkout origin/preserve/mls-ncaaf-worktree-20260902 -- <the 8 paths>`
   Those 8 paths only. Not `props.py`, not `MarketSlateBoard.tsx`, not `_core.py`, not
   `ingest_underdog_props.py`, not `esports_team_logos.json`.
3. Confirm with `git status --short` that exactly 8 files are staged and every one is an
   addition (`A`), not a modification (`M`). **A single `M` means you pulled a stale file —
   unstage it and report.**
4. Sanity-check before committing: `python3 -m py_compile` each new `.py` file. They were
   written against a 497-commit-old backend, so an import may no longer resolve. If a file
   does not compile, still commit it (it is preserved work, and it is additive so it breaks
   nothing that runs today) but **say so clearly in the commit body and in your report.**
5. Commit those 8 files alone. Do not push `dev` — Micah owns that push.

**Do not run the test suite as a gate here.** `WCContext.test.tsx` currently fails 2 tests on
`dev` for unrelated reasons; it is a known pre-existing failure, not something you introduced
and not something to fix.

Print: the preserve commit sha, the remote sha, and the `dev` commit sha.

## Phase 2 — stop the servers

Only after Phase 1 verification passes.

- Frontend: node, port 3098, cwd `/root/lp-league-mls-ncaaf`.
- Backend: uvicorn, port 8098, cwd `/root/lp-league-mls-ncaaf/backend`.

Confirm each PID's `cwd` via `readlink /proc/<pid>/cwd` **before** signalling it. There are
three other dev servers on this box (3096/8096 is the live managed dev environment, 3097/8097
is another worktree) plus ~90 live Kalshi data collectors. **Killing the wrong PID takes down
the environment Micah is actively using, or loses live market tape that cannot be recaptured.**
Match on cwd, not on port folklore and not on process name.

Before stopping, grep the repo for anything pointing at 3098 or 8098 (config, scripts, cron,
systemd, `.env*`). Report what you find; do not edit it.

Use `kill` (TERM). Do not use `kill -9` unless TERM fails, and say so if you do.

## Phase 3 — remove the worktree

- `git worktree remove /root/lp-league-mls-ncaaf` (from `/root/legendarypicks`).
- If it refuses because the tree is dirty, that means Phase 1 missed something. **STOP and
  report — do not use `--force`.**
- Then `git worktree prune`.
- Do **not** delete the `feat/league-mls-ncaaf` branch, and do **not** touch any other
  worktree or any stash.

## Phase 4 — backlog note

Append one short entry to `/root/legendarypicks/docs/ROADMAP.md` under section 10
("Queued, named by the user, not started"):

- `stash@{1}` holds WNBA enablement (scoreboard sweep, predictions `_SPORTS`) that is
  absent from dev. Not wanted right now — dev has `test_wnba_is_not_an_offered_prediction_league`
  explicitly asserting WNBA returns 404, so the stash is unique but was deliberately
  reversed. Logged so it is not rediscovered as a surprise. Do not drop stash@{1}.

Also note in the same entry that `preserve/mls-ncaaf-worktree-20260902` now holds the
retired worktree's unique MLS-props work, so it can be found later.

## Hard limits

- No `git stash` operations of any kind. There are 9 stashes on this box and they are shared
  across worktrees; a pop here can destroy another session's work.
- Do not remove or modify any other worktree.
- Do not touch the collectors, the 3096/8096 servers, or the 3097/8097 servers.
- Do not force-push anything.

## Report back

Phase 1 commit sha + remote sha, the two PIDs stopped (with their verified cwds), whether
the worktree removed cleanly, and anything you found referencing 3098/8098.
