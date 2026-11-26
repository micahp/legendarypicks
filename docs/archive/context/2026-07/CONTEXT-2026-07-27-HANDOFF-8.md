# LP handoff — 2026-07-27 pt.8 (supersedes pt.7)

**Work queue: `/root/legendarypicks/docs/ROADMAP.md`.** This file is session state and
decisions only.

Nothing is broken. `:3096`, `:8096`, `:8098` and the tunnel are all 200.

---

## 0. The jobs waiting for you, in order

### Job 1 — ask about pushing. `dev` is 14 commits ahead of `origin/dev`.

**Nothing has been pushed for two sessions.** Micah wanted the specs read before anything
left the box and never lifted that. The 14 include both slices, the ESPN normalisation, two
AGENTS.md corrections and the new skill. Ask before pushing; don't push on your own initiative.

### Job 2 — slice D's browser verification, which nobody has done

`docs/SPEC-slice-D-mock-draft.md` §7.6 requires a human-eyeballed screenshot check that
**no `sample: 'none'` player ever renders a "0 of 17" strip** — specifically Jeremiyah Love
(rookie, ADP 17.5) and any kicker. Hermes' own build report lists it under "Not finished."
I confirmed `/mock-draft` returns 200 with zero console errors, but **I did not walk the
draft flow**: setup → on the clock → results. That is the last gate before D merges.

### Job 3 — R4, the NFL schedule through the API

The third item of v0.7.0, and **much cheaper than it was this morning**: `nfl_schedule` now
holds 2025 (285 games) and 2026 (272), in ESPN vocabulary that joins to `players` 32-for-32.
The data is sitting there; R4 is now an endpoint, not an ingest.

### Job 4 — then merge D into dev and cut v0.7.0

v0.7.0 = slice A + slice D + R4. A is merged (`fd485e4`). D is one browser check away.

---

## 1. What happened this session

### Slice A — fixed and merged

`syncError` was returned by `useNflDraftBoard` and rendered by nothing, so a failed save
silently reverted the user's input. Now one quiet line under the sort controls, `role="status"`,
**red rather than the amber accent** — amber marks absence on this board and must not be
borrowed for chrome. Verified by forcing every PUT to 500 in a headless browser: the rank
rolls back to empty and the line renders. 13/13 pytest, `tsc` clean on both touched files.

`53830bf` deliberately edits `NflDraftRoom.tsx`, which slice A's own guardrail table forbids;
the commit message says so. Merged to dev as `fd485e4` after verifying **on the merged tree**,
not on the branch.

### Slice D — Hermes' pass 2 took three passes, and only the third was right

- **Pass 2** derived `team_weeks` from the logs but keyed it on the player's **2026** team
  while `weeks_played` came from **2025** logs. 56 of 243 mismatched the board.
- **Pass 3** (after I steered it) derives `primary_team` per player from the log season and
  keys on that, and **deletes the `range(1,18)` fallback** entirely.
- **Verified myself: 243 of 243 byte-identical to `/api/nfl/draft-board`, zero on the
  fallback.** pytest 20/20, jest 35/35. Merged into D as `bc3038d`.

Hermes reported "0 mismatches" *and* "Kyren Williams missed=[8]" in the same breath — those
cannot both be true. The result was right; the report was not. Check both halves.

### The ESPN vocabulary switch — Micah's call, and it was the root cause

`ESPN_ALIASES = {"LA": "LAR", "WAS": "WSH"}` had been **defined and never applied** since
`ingest_nfl_schedule.py` was written. So `players` said `LAR`/`WSH` and everything that script
wrote said `LA`/`WAS`. **178 active players silently failed to join**, which is what made the
mock draft fall back to a fabricated schedule in the first place.

Now applied at the ingest boundary (`a4a2136`):

| | before | after |
|---|---|---|
| `nfl_schedule` | 2024, 2026 | 2024, **2025 (285, new)**, 2026 |
| vocab vs `players` | 2 franchises off | **32 for 32** |
| `team_game_results` 2026 | 544 nflverse-keyed | 544 ESPN-keyed |

**The trap, if you ever re-run this:** a plain `--season 2025` also writes
`team_game_results`, where ESPN already owns 544 rows under different `game_id`s. It would
**not** upsert — it would double the season. Hence `--schedule-only`, which 2025 must use.
The 34 stranded 2026 `LA`/`WAS` rows were deleted after confirming each had a `LAR`/`WSH`
replacement on the same `game_id`.

Pre-change backup: **`/root/picks.dev.PRE-ESPN-2026-07-27.db`** (153MB).

**Validation worth keeping:** the published 2025 schedule puts the Rams' bye in week 8 —
exactly what the log-derived `team_weeks` produces. The derivation was right, and is now
falsifiable against a published source.

### New skill: `published-first`

`.claude/skills/published-first/SKILL.md`, registered in `AGENTS.md` §11 so a delegated agent
finds it unprompted. Micah's ask, generalised from ponytail
(github.com/DietrichGebert/ponytail): ponytail asks *does this code need to exist*, this asks
**does this value need to be computed**. Six rungs; the one that keeps getting skipped is
**rung 5 — a definition (schedule, roster, bye week, team code) is always published somewhere
and must never be inferred.**

---

## 2. State

- **`dev` = `07e7610`, 14 commits unpushed.** Nothing pushed all session.
- `feat/slice-D-mock-draft` = **`bc3038d`** — checked out in the main repo, what `:3096`
  serves. Contains A + D + pass 3 + dev merged in.
- `feat/slice-a-draft-notes` = `53830bf`, merged, kept (D was stacked on it).
- `feat/slice-D-pass-2` = `fadaf3a`, merged into D, worktree still up at
  `/root/lp-slice-D-pass-2` with **its own backend on `:8098`** (no reload — I restart it
  by hand). Tear it down when D is settled.
- `feat/nfl-allday` = `825d116`, pushed, untouched.
- **Prod is v0.6.7.** R6 (deploy) still behind v0.7.0.
- `:3096` frontend, `:8096` backend (reload), `:8098` worktree backend. Tunnel
  `https://someone-decorative-wearing-produce.trycloudflare.com` → 3096, cloudflared pid
  3928058. **Don't touch cloudflared.**
- Box: ~800MB available, load ~1.5. `node_modules` = 538 (see §3).

---

## 3. Traps

**`node_modules` was emptied AGAIN, by an agent typing `npm` directly.** Hermes ran
`npm run build` from its worktree at 18:34; npm resolved against the symlinked shared install
and pruned it to **zero packages**, taking `:3096` down. Second time in one day. Recovery is
`npm ci` in the main repo (~45s) then relaunch with `./node_modules/.bin/next dev --port 3096`.

Both process fixes are now in place — `scripts/hermes-worktree.sh` no longer shells out to
`npx` (`7c11568`), and `AGENTS.md` §11 bans npm/npx/yarn from worktrees outright (`5c98ad1`).
§11 also now says **`ls node_modules | wc -l` BEFORE touching `.next`**, and the tunnel section
no longer claims `ENOENT .next/server/pages/...` means a corrupt build cache — that is the
misdiagnosis this failure produces, twice now.

**Branch churn under the live dev server.** I did every merge in a throwaway worktree
(`git worktree add` on a scratch path, merge, remove) so the main tree never changed branch.
The one in-place merge — dev into D — was trial-merged in a scratch worktree first to prove
it was conflict-free. Keep doing it that way.

**Still outstanding, both deliberate:**
1. `player_game_logs` (131,962 rows) is **still nflverse vocabulary**. Nothing breaks — the
   log-derived path is internally consistent — but the split isn't closed, and migrating it
   moves the board's live numbers.
2. **Three copies of the same alias map** exist: `ingest_nfl_schedule.py`,
   `nfl_offseason.py:74-78`, `settlement.py:148`. `nfl_offseason`'s is load-bearing until
   (1) happens. Collapse them then, not before.

---

## 4. The lesson

pt.7's was *an agent's green test suite is a claim, not a result.* This session proved the
sharper version: **the claim and the evidence can both be present and still not match.**
Hermes reported "0 mismatches" alongside a Kyren Williams figure that contradicted it, and
pass 2's real defect — 56 of 243 wrong — took one command to find, the same command the task
document had already named as the acceptance bar.

The deeper one is why the bug existed at all. Three passes went into **reconstructing a
schedule that nflverse publishes**, against a join key nobody had ever measured. Not one of
those passes was wrong about the code; they were wrong about needing to write it. That is now
`published-first`, and the first thing it says is that the failures never announce themselves —
they produce numbers of the right shape, in the right column, that nobody can spot by looking.
