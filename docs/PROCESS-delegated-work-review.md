# Reviewing delegated work

How work produced by an agent (or by you) becomes work that is allowed onto `dev`.

Companion to `.claude/skills/falsify-before-merge`, which is the agent-facing version. This
doc is the human-facing one: why the process exists, what to paste, and what evidence it was
built from. Also see `docs/DEV-STANDARDS.md`, which this does not replace.

---

## 1. Why this exists

On 2026-08-19 a delegated agent built UFC method-of-victory parsing. It was competent work:
real tests, an honest report, and it shipped a defect anyway.

```
8 tests, all passing, five of them edge cases
ufc_outcome() labelled a fight "Decision" while it was still being fought
```

The parser derived `Decision` from `period == regulation.periods` plus a full-round clock, and
never checked that the fight was over. UFC rounds count down from 5:00, so a live fight at the
start of its final round publishes exactly what a decision publishes.

**The tests could not have caught it.** The code needed `status.type.completed`. The
hand-written fixture built `status.type` as `{"state": "post", "description": "Final"}` with no
`completed` key. Real ESPN always sends it:

```
{"id":"3","name":"STATUS_FINAL","state":"post","completed":true,...}
```

The same author wrote the code, the tests and the fixture from one idea of what the payload
looks like. The field the guard needed was the field the fixture had dropped.

### The conclusion that matters

> **"Check all the edge cases" would not have caught this.** That suite *was* edge cases:
> submission, KO/TKO, a mid-round stop with no detail, an unrecognised id, event-detail noise.
> Every one of them shared the fixture that made the defect unreachable.

More tests from the same author reinforce the same assumption. What finds the defect is one
real observation that can contradict it.

---

## 2. What was actually missing

The work was not bad. It was **unreviewable**. Ranked by leverage:

| missing | what it cost on 2026-08-19 |
|---|---|
| No PR existed at all | branch never pushed, no diff against a base ever read by a second reader |
| The author wrote its own fixtures | the test restated the code's assumption instead of testing it |
| No "what I did not cover" section | the report listed what passed, so the gaps were invisible |
| Verified in the state where it works | "verified against the live page" at 12:50, mid-slate only |

Every defect found in the review came from **reading the diff against `dev`**, not from the
report. The report was accurate throughout.

---

## 3. The contract

### 3a. Put this in the task spec, before the agent starts

This is the high-leverage half. It makes the agent falsify its own work before anyone else
sees it.

```
When you report DONE, state:

1. What you did NOT cover. Named specifically, not "comprehensive".
2. Which test fixtures you invented, and whether you checked each one against a
   real payload from the actual publisher.
3. Which states you actually exercised, versus reasoned about without running.
4. What else in the codebase reads any field you changed.
5. The base sha, and whether anything outside the repo (systemd, scripts, cron)
   points at a file you moved.

Any claim phrased as "verified" must say WHEN and IN WHAT CONDITION.

Load .claude/skills/falsify-before-merge before you write the tests, not after.
```

### 3b. When the work comes back

```
Load falsify-before-merge and audit <branch> against dev. Fix what you find, then merge.
```

Deliberately thin. The content lives in the skill so it does not decay into a phrase everyone
stops reading.

---

## 4. The five moves

Full versions in the skill. Ordered by how often they find something.

1. **Check every fixture against one real payload.** A fixture is a claim about the publisher.
   One request settles it. A fixture that omits a field does not fail; it defines a world in
   which the correct guard is unwritable.
2. **Enumerate the states, then ask what the code reads in each.** `pre`, `in`, postponed,
   cancelled, suspended, partial, empty. Gate a completion verdict on the publisher's own flag
   (`status.type.completed`), never on `state == "post"`: a postponed event is also `post`.
3. **Run it in the empty window.** Three defects this month survived because every check ran
   mid-slate. If you cannot wait for 09:50, construct the empty state and assert on it.
4. **Follow the value past the UI that hides it.** The bad `Decision` never reached the card,
   and still went into the normalized game and `scoreboard_snapshots` for every other reader.
   A UI guard is not a fix.
5. **Check what breaks outside the repo.** `git diff` cannot show a systemd unit. The 08-18
   split broke 7 callers outside the repo and props stopped refreshing on both databases for a
   day. Check ExecStart paths, `scripts/*.sh`, cron, Docker, and run `pyflakes` (expanding any
   `from _core import *` in a throwaway copy first, or it checks nothing).

---

## 5. The merge gate

Do not merge on a green suite alone. A suite is a claim about its own surface.

- [ ] Read the **diff against the base branch**, not the summary of it.
- [ ] Moves 1 and 2 done on every new derivation or parser.
- [ ] Suite run **on both databases** (`picks.dev.db` and `picks.db`).
- [ ] Test count compared to the baseline. A flat count alongside new test files means
      something is not being collected.
- [ ] `git status --porcelain` before committing. Explicit paths, **never `git add -A`** while
      another agent has the tree open.
- [ ] The branch is pushed and the base branch actually receives it. Work that exists only on
      an unpushed branch is not shipped, even when the host has been patched by hand.
- [ ] User-facing copy read for house rules (no em dashes in UI copy, titles, meta tags).

---

## 6. Limits of this document

Written from a sample of one defect plus this month's history, so treat it as provisional.

Move 1 is the one with direct evidence: it is what found the bug. Moves 3 through 5 are
generalisations from the split breakage and the mid-slate verifications, and each has caught
something once. **If several audits in a row find nothing in a given move, cut it.** A
checklist nobody believes is worse than no checklist, because it converts review into
paperwork.

The larger limit: none of this substitutes for reading the diff. Every defect found on
2026-08-19 came from reading code. The moves tell you where to look first; they do not replace
looking.
