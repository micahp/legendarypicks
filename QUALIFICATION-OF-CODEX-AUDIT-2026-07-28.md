# Qualification of Codex's audit — the frontend and devops findings

**By Claude, 2026-07-28, at Micah's instruction.** Codex's report is a claim like any other,
so every finding below was re-measured on this box before being accepted. Four confirmed,
one corrected, one extended past what the audit said, one answered outright.

Findings that land on the backend/DB are not qualified here — they are Codex's to own.

---

## CONFIRMED, and fixed · the gate runner exited 0 while printing FAIL

Codex's repro:

```
LP_GATE_W=/tmp/definitely-missing bash verify-gates.sh B1
  → "FAIL B1  ()"   exit 0
```

Reproduced exactly. **It is not one gate — it is all of them, including `all`.** `ok()` and
`no()` are both a bare `echo`, and the `case` block summed nothing, so the script's exit
status was whatever the last echo returned: always 0. Anything of the shape
`verify-gates.sh all && deploy` read a red suite as green, and `REG-adp-dst` is red on
purpose right now.

This is my file and it violated my own rule — *capture the exit code, "evidence
unavailable" is a FAIL and not a skip* — at the one place it mattered most, the runner
itself. Codex's second observation is the same defect from the other side: pointing
`LP_GATE_B` at a dead port produced `exit=1`, but only because a Python json parse happened
to raise last. The exit code was never a verdict; it was an accident.

**Fixed in `4827033`.** `exit` = number of `FAIL` lines, with no allowlist — not even for
`REG-adp-dst`, so `all` now honestly exits 1 until job15 lands. An allowlist is how a suite
gets quietly relaxed; a number that cannot be argued with is cheaper to trust.

The same commit adds the check for the *other* half of the failure. `ALL_IDS` names all 15
verdicts the suite can emit, and a missing one is counted as a failure. Earlier that day
`all` ran 14 gates and silently skipped `REG-render` because the function existed but was
never added to the dispatch — a full green suite while the only gate that renders React
never ran. That was fixed as an instance; this fixes it as a mechanism. The id list was
derived by grepping every verdict literal in the script, not from memory.

Verified: bogus worktree → exit 1; real worktree → exit 0; unknown gate name → exit 1.

---

## CORRECTED · "the user's URL does not serve this branch"

Substantially right, materially imprecise. **There are two tunnels**, and Codex saw one:

| URL | → port | → tree | branch | up |
|---|---|---|---|---|
| `someone-decorative-wearing-produce` | 3096 | `/root/legendarypicks` | `feat/slice-D-mock-draft` | 4d 18h |
| `altered-era-sold-explain` | 3098 | `/root/lp-team-vocab` | `feat/dst-and-mock-draft` | 9h 49m |

So the branch **is** externally reachable. The real problem is narrower and worse than
"not served": the URL Micah has had for four days shows him dev's tree, and the 66 commits
of work sit behind a nine-hour-old second URL he has to be told about each time. Delivery
isn't missing, it's ambiguous — and an ambiguous URL is how work gets reviewed against the
wrong tree. Mine to resolve at merge.

---

## CONFIRMED and EXTENDED · the engine's D/ST ordinal is not just unstable, it drifts 1 per pick

Codex reported that `createDraft()` moves nulls to 268–299 and `botPick()` then recomputes
against a shrinking pool. Both true. Measured:

```
backend pool:        300 players, DEF at indices 150–181 (32 nulls)
after createDraft(): DEF at indices 268–299
```

The comment at `engine.ts:208` asserted D/ST sit *"at indices ~150–181"* at the point
`botPick` reads them. They never do — `createDraft` has already re-sorted every null to the
end. **A comment asserting a fact about data, falsified by code twenty lines below it in
the same file.** Corrected in `0b70854`.

The consequence is bigger than an ordering mismatch. `poolIndex` is rebuilt on every
`botPick`, and `applyPick` removes one player per pick, so a defense's `effectiveAdp`
**improves by exactly 1 for every pick made**, while all real ADPs stay frozen. Measured
with zero jitter against the live pool:

| pick | pool | D/ST effective ADP | worst real ADP |
|---|---|---|---|
| 1 | 300 | 269 | 171 |
| 40 | 261 | 230 | 171 |
| 80 | 221 | 190 | 171 |
| 120 | 181 | 150 | 171 |
| 160 | 141 | *(already drafted)* | 171 |

It crosses the real-ADP tail around pick ~98 and defenses start going in round 9. **That
looks like a plausible draft and it is pure pool arithmetic** — a shrinking relative index
compared against fixed absolute values has no meaning at any point on that curve.

**Do not fix this in the engine.** The branch only executes because `p.adp` is null. Once
job15 publishes real D/ST ADP it is dead code and must be *deleted*, not tuned — which
makes it a job15 acceptance criterion: after job15, `engine.ts` contains no null-ADP
fallback. This is the ponytail question, and the answer is that the code should not exist.

---

## CONFIRMED · snap counts are still on the old team vocabulary

```sql
SELECT team, count(*) FROM nfl_snap_counts WHERE team IN ('LA','WAS','AZ','LAR','WSH','ARI') GROUP BY team;
  ARI|671   LA|648   WAS|651
```

`LA` and `WAS` are nflverse spellings; ESPN canonical — which the migrated core tables use —
is `LAR` and `WSH`. The live DB is genuinely mixed. Worth restating why this matters more
than it looks: **a wrong join key does not raise, it misses.** It already cost 178 players
silently once on this project.

Also measured, and relevant to anyone choosing a DB path: `/root/picks.hermes.db` (160 MB)
is the only live database. `/root/legendarypicks/picks.dev.db` is **0 bytes** — any process
launched with `LP_DB_PATH=picks.dev.db` reads an empty schema and will report zero rows
rather than fail.

---

## ANSWERED · 41 of 41 mock drafts are `status='active'`

I put this in Codex's queue and then found it sits on my side of the split. It is not a data
anomaly. **No code path in the system can produce any other status.**

- `nfl_mock_draft.py` inserts the literal `'active'` (line 413) and never updates it. The
  only `UPDATE` on the table touches `updated_at` (line 493).
- The router exposes six routes. None of them completes a draft.
- `lib/mockDraft/api.ts` exposes five calls — `fetchPool`, `createDraft`, `appendPicks`,
  `fetchDraft`, `listDrafts`. There is no finish call to make.
- `DraftRoom.tsx:205` renders **"Draft complete"** to the user off `draftState.completed`,
  a client-side flag that is never persisted anywhere.

So the user is told a draft is complete, the row stays `active` forever, and the backend
gates picks on `if status != 'active': 409` — a guard that can never fire. The column is
decorative and the guard is theatre. 1,645 picks across 41 drafts and not one finished
state was ever written.

Mine to fix (the frontend has to call something), but it needs a backend route that does not
exist yet, so it belongs in Codex's queue as a small spec: a completion endpoint plus the
`status` write. Flagging rather than building, since backend is now his.

---

## Not qualified here

Findings 3–10 were lost to tmux truncation before I could read them — which is why the
first instruction in the orchestration brief is to persist the report to a file. I will
qualify the frontend/devops ones among them once it exists.
