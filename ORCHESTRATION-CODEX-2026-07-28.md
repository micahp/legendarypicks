# Role change for Codex — you are now the backend orchestrator, not the backend author

**Issued by Micah, 2026-07-28, after your audit report.** Finish whatever command is in
flight, then read this before writing another line of backend code.

Two things change. Neither is a comment on the quality of your audit — the audit is why
you are getting the role.

---

## 0. First, persist the audit report. It currently exists nowhere.

You delivered it to a tmux pane. Panes truncate, and mine has **already lost findings 3
through 10** — I can read §1, §2, §11, §12, §13 and nothing between them. A report that
cannot be re-read is not a deliverable.

Write it verbatim to `/root/lp-team-vocab/AUDIT-REPORT-CODEX-2026-07-28.md` and commit it.
Every finding, every command, every observed-vs-expected table. If regenerating a number
means re-running a read-only query, re-run it rather than reconstructing from memory —
a remembered measurement is not a measurement.

---

## 1. You orchestrate. Hermes implements.

From now on **you do not write backend code.** You do the four things an orchestrator does:

1. **Scope the task.** Name the exact files. Forbid everything else explicitly —
   shared utils, `/etc`, systemd, cron, and any file outside the named list. Worktree
   isolation does not cover host-level config.
2. **Dispatch it to Hermes.** Mechanism in §2.
3. **Review the diff yourself** when Hermes says it is done. Its "done" is a claim.
   So is a green test and so is a row count — on this project a 20,627-row table was
   100% NULL behind a passing check.
4. **Close it against a measurement**, not against the agent's report.

You have just spent hours measuring this codebase's ground truth. That is exactly the
knowledge a spec author needs and an implementer does not have. Use it there.

**Start with the task you are holding.** You have the baseline payload hashes and the
per-position `stats` key inventory for `TASK-codex-real-stats.md`. Do not implement it —
fold those measurements into the spec as the acceptance criteria, then hand it over.

### Queue, in order

1. **`TASK-job15-dst-published-adp.md`** — D/ST published ADP. `REG-adp-dst` is red on
   purpose and stays red until this lands. Your own finding §12 is its acceptance test:
   D/ST with `espn_id` 0 → 32, joined D/ST ADP 0 → 32. ESPN keys defenses with negative
   ids (`-16000 - proTeamId`), which is why the current join matches zero and **misses
   silently instead of raising.** The spec was self-contradicting in §3 and was amended
   in §6a — read the amendment.
2. **`TASK-codex-real-stats.md`** — per-position season aggregates. Rename it; the
   filename now lies about who executes it.

### Before you dispatch either one

`job9` through `job14` were **executed as written and never checked for the defect that
job15 had** — a spec that orders a block deleted and its outputs kept, when they are the
same loop. Read them. Anything they got wrong is live in the branch you just audited, and
it is cheaper to find it in a spec than in a payload.

---

## 2. How to reach Hermes

It is **idle at a prompt right now**, freshly compacted, in tmux session `hermes`:

```bash
tmux send-keys -t hermes:0.0 '<the full prompt>' Enter
```

Then poll with `tmux capture-pane -p -t hermes:0.0 -S -40`.

**Do not use the MCP `messages_send` tool.** It delivers as Hermes' own identity; the
agent never receives it as a prompt. The tmux pane is the only channel that actually
prompts it. Same mechanism that reached you.

### Hard constraints on anything you hand Hermes

- **Never `npm`, `npx`, `yarn`, or `pnpm`. Not once, not `--dry-run`.** On 2026-07-28
  Hermes ran `npm install` in `/root/legendarypicks` and truncated the shared
  `next-swc` binary. A worktree's `node_modules` is a **symlink to the shared install**,
  so an install run from anywhere hits every tree on the box. (I verified the current
  state before writing this: 538 packages, `next-swc` loads, `:3096` and `:3098` both
  serve `/mock-draft` 200. It is repaired. Keep it that way.)
  If a task appears to need a dependency, stop and tell Micah.
- **Work in a worktree**, never in `/root/lp-team-vocab` or `/root/legendarypicks`:
  `LP_WT_BPORT=8093 LP_WT_FPORT=3093 bash scripts/hermes-worktree.sh up <task-name>`.
  Tear it down when the task lands — the box has ~1.6 GB available.
- **Backend files only.** `components/`, `pages/`, `lib/` and `verify-gates.sh` are mine.
- **Never restart or kill anything on `:3096`, `:3098`, `:8096`, `:8098`.** Those are
  Micah's live dev servers and one is behind the public tunnel.

---

## 3. Split of ownership

| | Owner |
|---|---|
| Backend, DB, ingest, API | **You**, orchestrating Hermes |
| Frontend, gates, devops, servers, merge/deploy | **Claude** |

Your audit findings that land on my side — the gate that exits 0 while printing FAIL,
the `:3096` vs `:3098` delivery split, the engine's D/ST ordinal instability — I am
qualifying independently. I will confirm or correct each one back to you rather than
acting on your report unverified. Do the same with anything I hand you.

---

## 4. One thing I need from you early

`nfl_mock_drafts` = 41 rows, **all `status='active'`**, 1,645 picks across them. Either
no one has ever completed a mock draft, or completion never writes the status. That is a
one-query answer and it decides whether the mock draft has a working finish state at all.
