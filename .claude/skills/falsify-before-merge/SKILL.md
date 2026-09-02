---
name: falsify-before-merge
description: MUST load before merging any branch you or another agent produced, before reporting a task DONE, and before writing acceptance criteria into a task spec. Encodes the failure where an agent ships a green suite that could not have caught its own defect, because the same author wrote the code, the tests and the fixtures from one mental model. Triggers on "merge to dev", "audit the code it wrote", "is it done", "tests pass", "suite green", "ready to ship", any handoff from a delegated agent, any PR review, and any moment you are about to accept "N passed" as evidence.
---

# Falsify before merge

Load this when work arrives claiming to be done, whether it came from another agent or
from you.

It exists because on 2026-08-19 a delegated agent shipped UFC method-of-victory parsing
with **8 tests, all passing, five of them edge cases**, and a defect that labelled a fight
`Decision` while it was still being fought. The tests could not have found it. The code
needed `status.type.completed`; the hand-written fixture omitted `completed`; **the same
author wrote both from the same idea of what the payload looks like.**

---

## 1. The governing principle

> **A test written by the author of the code is a restatement of the author's assumptions.
> It fails when the code contradicts the author. It cannot fail when the author is wrong.**

This is why "more edge cases" does not help. The 2026-08-19 suite already covered
submission, KO/TKO, a mid-round stop with no detail, an unrecognised id, and event-detail
noise. Every one of those is an edge case. Every one shares the fixture that made the
defect unreachable.

You are not looking for more cases. You are looking for the **assumption the cases rest
on**, and one real observation that can contradict it.

---

## 2. The five moves

These are ordered by how often they find something. Do them against the diff, not against
the report.

### Move 1: check every fixture against one real payload

A hand-written fixture is a **claim about the publisher**, and it is falsifiable like any
other claim. One request settles it.

```
fixture   {"state": "post", "description": "Final"}
real      {"id":"3","name":"STATUS_FINAL","state":"post","completed":true,...}
                                            ^^^^^^^^^ the field the guard needed
```

A fixture that omits a field does not fail. It silently defines a world in which the
correct guard is unwritable. Diff the fixture's keys against a real response and ask what
the missing ones are for.

### Move 2: enumerate the states, then ask what the code reads in each

Find every field the new logic reads. For each, ask what it holds in the states nobody
tested: `pre`, `in`, postponed, cancelled, suspended, partial, empty, mid-write.

```
period == regulation.periods && clock == "5:00"
  final, decision       -> true    tested
  LIVE, start of R3     -> true    NOT tested, and wrong    <- the defect
```

A derived verdict must be gated on the publisher's own completion flag. In this repo that
is `status.type.completed`, **never `state == "post"`**: a postponed event is also `post`
and was never played.

### Move 3: run it in the empty window

Most surfaces here were verified mid-slate, in the one condition where they work. Three
defects this month survived that way. If the change touches anything live or
time-dependent, exercise it when nothing is on. If you cannot wait for 09:50, construct
the empty state and assert on it.

### Move 4: follow the value past the UI that hides it

A wrong value gated out of one component is still written everywhere else. The `Decision`
label never reached the card, because `GameCard` gates on `isUFCFinal`, and it still went
into the normalized game and into `scoreboard_snapshots`, for every other reader.

Ask: who else reads this field? Storage, settlement, stories, the API, the snapshot
tables. A UI guard is not a fix.

### Move 5: check what the change breaks outside the repo

`git diff` cannot show you a systemd unit. On 2026-08-18 a package split broke **7 callers
that live outside the repo** and props stopped refreshing on both databases for a day.

```
systemctl list-timers 'legendarypicks-*'   ExecStart paths still resolve?
scripts/*.sh  scripts/*.cron  Dockerfile   any path to a moved or deleted file?
pyflakes                                    dropped imports underneath
from _core import *                         expand it in a throwaway copy first,
                                            or pyflakes checks nothing
```

---

## 3. The done-report contract

An agent reporting DONE must state these. A report without them is not reviewable, and
asking for them costs one message.

1. **What I did not cover.** Named, not "comprehensive". The gaps are the review's
   starting point.
2. **Which fixtures I invented, and whether I checked them against a real payload.**
3. **Which states I exercised**, and which I reasoned about without running.
4. **What else reads the fields I changed.**
5. **The base sha, and whether anything outside the repo points at what I moved.**

Anything phrased as "verified" must name **when and in what condition** it was verified.
"Verified against the live page" at 12:50 on a Wednesday is a claim about a busy slate
only.

---

## 4. The merge gate

Do not merge on a green suite alone. A suite is a claim about its own surface.

- [ ] Read the **diff against the base branch**, not the summary of it.
- [ ] Moves 1 and 2 done on every new derivation or parser.
- [ ] Suite run **on both databases** (`picks.dev.db` and `picks.db`), not one.
- [ ] Test count compared to the baseline. New tests should raise it; a flat count with
      new test files means something is not collected.
- [ ] `git status --porcelain` before committing, **explicit paths, never `git add -A`**
      while another agent has the tree open.
- [ ] The branch is actually pushed, and the base branch actually receives it. Work that
      only exists on an unpushed branch is not shipped, even when the host is patched.
- [ ] User-facing copy read for house rules (no em dashes in UI copy, titles, meta tags).

---

## 5. What this skill is not

It is not a request for more tests. It is not a generic edge-case checklist, and it does
not ask "did you think of everything": an author who missed something answers yes
honestly.

Every move above replaces a judgement with an **observation**: a real payload, a state
table, an empty window, a grep for other readers, a resolved ExecStart path. Prefer the
one that produces a fact.

Related: `fail-loudly` (a defect that produces plausible output), `answer-is-already-here`
(the real payload is usually already on this box), `published-first`.
