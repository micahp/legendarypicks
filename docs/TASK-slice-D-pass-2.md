# TASK: slice D, pass 2 — fix what verification found

Branch: **`feat/slice-D-mock-draft`** (already exists, stacked on `feat/slice-a-draft-notes`).
Spec: `docs/SPEC-slice-D-mock-draft.md` — its §6 and its guardrail block are binding and
unchanged. This file is the delta only.

Pass 1 built the right shape. Three things are wrong, one of them badly. Fix these four
items and nothing else.

---

## 1. `team_weeks` is fabricated, and it manufactures fake absences ← the important one

`backend/routers/nfl_mock_draft.py` builds:

```python
"team_weeks": list(range(1, _REG_SEASON_TEAM_GAMES + 1)),   # [1..17]
```

That is not a schedule. **The NFL regular season is 17 games across 18 weeks, with one bye
per team** — the constant is documented at `backend/routers/nfl_offseason.py:28-34`. The
consequences, measured on the live pool:

- **157 of 233 players with logs have a week-18 game.** All of them are dropped.
- Every team's bye lands in the wrong cell, so weeks played read as weeks missed.

Because the accent colour marks absence, this paints **fake missed games in amber**. That is
the single worst defect this product can ship — it is the opposite of the thing the board
exists to be trusted for.

**Fix: build `team_weeks` per team from real results, exactly as the board already does.**
`nfl_offseason.py:571-605` is the reference implementation — a `defaultdict(set)` keyed by
team, filled from the team's actual played weeks, then `sorted()`. Do not copy the function
out of that file and do not edit that file; write the equivalent inside
`nfl_mock_draft.py`.

Ground truth to check against — the board's own response for a player with a week-8 bye:

```
team_weeks   [1,2,3,4,5,6,7,9,10,11,12,13,14,15,16,17,18]     ← 17 entries, gap at 8
weeks_played [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18]
```

**Acceptance:** for at least five players spanning different teams, the pool endpoint's
`team_weeks` is **byte-identical** to `/api/nfl/draft-board`'s for the same player. Paste the
comparison into the report. The strip must render identically to the board — that is a spec
requirement (§6.1), not a preference.

## 2. The 2026-vs-2025 test fixture

`backend/test_nfl_mock_draft.py::test_pool_availability_data` fails at HEAD. **The router is
right and the test is wrong** — the fixture seeds `player_game_logs` at season **2026** while
the router correctly reads the prior season (2026 has not been played). Fix the fixture to
seed 2025. Do not change the router to make the test pass.

Pass 1 reported "20/20 pytest". It was **19 passed, 1 failed**. Run the suite and paste the
real output.

## 3. Pin the log season the way the board does

The router hardcodes `_log_season = _CURRENT_SEASON - 1`. The board uses
`MAX(season) FROM player_game_logs`. They agree today and will silently diverge the week
2026 logs start landing — the board rolls forward, the mock draft stays on 2025.

**Fix:** derive it the same way the board does, falling back to `_CURRENT_SEASON - 1` only if
the table is empty. One source of truth for "which season are we showing."

## 4. Leave the simulation alone, and read why

`lib/mockDraft/__tests__/realpool.verify.test.ts` and its fixture are already committed. They
are the §7.2 check run against the **real** pool shape — WR 64 / RB 50 / QB 27 / TE 25 /
**PK 15** in the real-ADP tier — rather than the synthetic 60-per-position pool in
`engine.test.ts`, which could not fail the constraint it was written to test. 200/200
complete. Keep both files. If you change the engine, both suites must still pass.

---

## Scope — binding

**Files you may modify:**

| file | permitted change |
|---|---|
| `backend/routers/nfl_mock_draft.py` | items 1 and 3 only |
| `backend/test_nfl_mock_draft.py` | item 2, plus a test asserting item 1 against the board |

**Everything else is off limits**, including `backend/routers/nfl_offseason.py` (read it as
reference, never edit it), `_core.py`, the engine, and every frontend file. The frontend is
already correct — it consumes `weeks_played`/`team_weeks` and does the right thing with them
once the backend sends real values.

**The full "Never, on this box" list in `SPEC-slice-D-mock-draft.md` still applies.** The
one that has already cost us twice: **never run `npx` / `npm install` / `npm ci` from a
worktree** — worktree `node_modules` is a symlink to the main repo's, and an `npm exec`
inside one empties the shared install and takes down the dev frontend and the public tunnel.
And **never start, kill or restart a dev server**; `:8096` reloads on its own.

## Definition of done

- The five-player `team_weeks` comparison against the board, pasted in.
- Real pytest output for `test_nfl_mock_draft.py`, and `jest lib/mockDraft` still green.
- `git diff --stat` against the table above. A diff touching anything else is a failed task.
- Separate commits per item. Plain commit messages, no AI attribution.
- Report anything you measured that disagrees with this document rather than matching it.

## One process note

Pass 1 reported three things that were not true: 20/20 tests (it was 19/20), a passing pool
simulation that could not have failed, and a build whose availability data was sitting
uncommitted in the working tree. Every one of them took a single command to check. **Before
reporting done, run the thing you are about to claim and paste its output.**
