# HANDOFF pt.13 — 2026-07-28

Supersedes pt.12. Written after the fact — **the session that did this work ended without
writing one**, so the first half of this document is reconstructed from the transcript
(`~/.claude/projects/-root/0537a57d-*.jsonl`) and re-verified against the box, not relayed.

**Branch `feat/dst-and-mock-draft` in `/root/lp-team-vocab`, 48 ahead / 0 behind `dev`.
Nothing merged. `dev` unchanged at `ede618b`. DB copy `/root/picks.hermes.db` intact.**

**Do not merge yet — see §4.** The frontend that landed last night shipped a crash.

---

## 1. One thing needs your hands

An interrupted `npm install` corrupted the **shared** `node_modules` at 01:54. It is still
corrupt. Everything JS — both frontends and the whole jest suite — is dead on it.

```
! cd /root/legendarypicks && npm install --no-save --no-audit --no-fund @next/swc-linux-x64-gnu@13.0.0
```

`--no-save` leaves `package.json` alone. I'm blocked from running installs by the permission
classifier and did not work around it.

**Why `:3096` looks fine anyway — this is the trap.** It serves 200 because it holds the *old,
good* binary mapped as `(deleted)`:

```
/proc/2486931/maps →  next-swc.linux-x64-gnu.node (deleted)
```

It is running on a freed inode. **It dies the moment it restarts**, and it can't compile a
route it hasn't already compiled. Do not read its 200 as health.

Evidence the on-disk file is truncated, not merely odd:

```
node -e "require('.../next-swc.linux-x64-gnu.node')"   →  Bus error, exit 135
file → ELF 64-bit LSB shared object ... missing section headers
28,866,048 bytes · 2026-07-28 01:54:19
```

**Provenance** (`/root/.npm/_logs/`, `cwd /root/legendarypicks`, both bare `npm install`):

| time | outcome |
|---|---|
| 01:53 | log ends mid-fetch, **no exit line — killed in flight**. This truncated the binary. |
| 01:58 | `exit 0`, but repaired nothing: npm saw the tree as satisfying `package.json`. npm does not verify file integrity. |

Hermes reported it ran no npm/npx/yarn commands from the worktree. The npm logs contradict
that. The worktree's `node_modules` is a **symlink** to the live install, so an install run
anywhere in it writes through to `:3096`'s tree. **Invoke binaries by absolute path only**
(`/root/legendarypicks/node_modules/.bin/jest`).

---

## 2. State of the work = one command

```bash
bash /root/lp-team-vocab/verify-gates.sh all
```

**As of `fd58708` this file is finally tracked in git.** pt.12 claimed it was committed so that
`git log -p verify-gates.sh` would show who weakened a gate — it was untracked the whole time,
so that property did not exist. It does now. A diff to an expected value is a finding.

Current output:

```
PASS A1   qb=Matthew Stafford gp=17 games_missed=1     (was: Stetson Bennett gp=0)
PASS A1b  Aubrey ppr=None pk_pts_per_game=10.6         (was: false 0.0)
PASS A2   no team_games>18, no negative games_missed
PASS A3   32 teams, byes across 9 distinct weeks       (was: endpoint absent)
PASS B1   POSITIONS includes DEF and PK
PASS B2   fields render in 4 components
FAIL B2b  frontend :3098 unreachable — gate could not run
PASS B4   scrollbar shown, games_missed from API
PASS REG-pool (300, DEF 32 @150-181, adp null) · PASS REG-dst (32 rows)
PASS REG-pytest  40 passed
FAIL REG-jest    SIGBUS 135 — NO frontend tests ran
FAIL REG-modules 538 packages BUT next-swc fails to load
```

**Both FAILs are the §1 incident, not the branch code.** They should go green on the repair
alone; if they don't, that's new information.

### Three gates were failing open (fixed in `fd58708`)

They passed while measuring nothing — the exact failure mode the gates exist to prevent:

- **REG-jest** grepped output for `^Tests:` and ignored the exit code. jest has been
  SIGBUS-ing since 01:54, printing nothing, so the grep matched nothing and the gate went
  *quiet* rather than red. **Consequence: every frontend commit after 01:54 — all six M3
  objects and the M5 overlay — has never had its tests run.** Re-run after the repair before
  trusting any of it.
- **REG-pytest** had the same shape (`| tail -1`). Now checks the exit code.
- **B2b** raised a `JSONDecodeError` traceback when `:3098` was down. Now reports an
  unreachable frontend as a FAIL, never a skip.
- **REG-modules is new**: package *count* is not package *integrity*. The count stayed 538 and
  `:3096` stayed 200 through the whole incident. It loads the binary instead of counting.

---

## 3. Roadmap, honestly scored

| item | pt.12 | now |
|---|---|---|
| M1 D/ST | backend only, UI renders none | **UI renders it** (4 components) |
| M2 availability from snaps | done | done |
| M3 familiar UX (6 objects) | **0 of 6** | **6 of 6 committed** — filters, queue, board grid, clock, next-pick counter, per-row Draft button |
| M4 resume/share | — | **scratched by Micah 2026-07-28. Out of scope.** |
| M5 overlay | endpoint only, wrong QB | overlay built; QB now Stafford 17gp |
| M6 camp card | — | out (was blocked on M4) |
| M7 polish | all three defects present | B4 green |
| B8 kicker data | **not fixed**, 0 rows | **fixed** — Aubrey 10.6 pts/game, ppr null not 0.0 |
| B9 position vocabulary | done | done |
| B10 playoff rows | partial | A1/A2 green |

**Caveat that governs all of the M3/M5 rows: they are green by *gate*, and the frontend gate
was inert when they landed.** The backend numbers are independently verified. The UI was not —
and when I read it (§4) the pool table turned out to crash on first render. Treat every M3/M5
row as *written*, not *working*, until it has been seen in a browser.

Kicker doctrine, still true: **nflverse does not score kickers.** The measurements are
published (`fg_made_*`, `pat_made`, `fg_long`); the scoring is a product rule we apply, like
the D/ST points-allowed tiers. Aubrey's real 2025: FG 36/42, PAT 47/48, 181 pts / 10.6 per game.

---

## 4. Frontend review — what the inert gate let through

jest can't run, so I read the diffs instead. **`tsc` is pure JS and runs fine on the corrupt
tree** — that is the verification path that still works while §1 is open:

```bash
/root/legendarypicks/node_modules/.bin/tsc --noEmit -p tsconfig.json
```

**26 errors on the branch, 21 on the pre-branch tree → 5 introduced by last night's work.**
`tsconfig.json` has **`strict: false`**, so null-safety is not enforced anywhere; the crash
below was not a compile error.

### FIXED — `74b34fd`: the mock draft pool crashed on first render

`DraftRoom.tsx` re-sorted `availablePool` with `a.adp - b.adp`. `DraftPlayer.adp` is
`number | null` and all 32 D/ST are null **by design**, so null coerced to 0:

```
before:  DEF SEA | DEF HOU | DEF JAX ...   → then dp.adp.toFixed(1) threw
         TypeError: Cannot read properties of null (reading 'toFixed')
after:   RB Gibbs | RB Robinson | WR Nacua, first DEF at 268, cell renders "—"
```

Every defense floated above the #1 overall pick, and then the first row took the whole table
down. The re-sort was also **redundant**: `createDraft` already sorts nulls last and
`applyPick` filters, preserving order. Removed rather than duplicated.

**Every gate was green while this was true.** B2 greps source for field names; REG-pool queries
the API; REG-jest was inert. Nothing in the suite renders React. That is the gap to close.

### Still open (not fixed — decide before merge)

| # | finding | evidence |
|---|---|---|
| 1 | **No D/ST roster slot.** `buildRosterSlots` builds QB/RB1/RB2/WR1/WR2/TE/FLEX/**K** — no DEF. Bots draft defenses in rounds 11–13, so a drafted D/ST silently lands on the bench. M1 "UI renders D/ST" is incomplete. | `DraftRoom.tsx:689-714` |
| 2 | **`team_games` is not on `PoolPlayer`** — `error TS2339`, and the field is absent from the pool payload. So `tg` always falls back to the hardcoded `TEAM_GAMES = 17`. **B4 passes anyway** because it greps for `"TEAM_GAMES - "` and this is `/{TEAM_GAMES}`. The gate's pattern is narrower than its claim. | `DraftRoom.tsx:631,764` |
| 3 | **3 × `TS2802`** — `[...new Set(...)]` under an ES5 target. `next dev` doesn't typecheck, `next build` does, so this likely **breaks a production build**. Verify after the §1 repair. | `DraftRoom.tsx:61,62,75` |
| 4 | `TS2322` — `{enabled: boolean}` not assignable to that component's `Props`. | `pages/leagues/[league].tsx:167` |
| 5 | **The clock is decorative.** It counts 30→0 and stops; nothing autopicks. `autopick()` exists in the engine and is documented for exactly this ("for user timeout, pass a zero-jitter rng"). A countdown with no consequence is a fake affordance. | `DraftRoom.tsx:127-146` |
| 6 | **Two deliberate orderings disagree.** Job 11 explicitly moved DEF to pool index 150 (from 268) and REG-pool asserts it; the engine's null-last sort puts them back at 268 in the draft room. Bot behaviour (rounds 11–13) is verified and comes from the *engine* order. Decide which one the displayed list should use — right now the API's intent is silently overridden. | `engine.ts:269-275` vs REG-pool |

## 5. Live surfaces

```
:3096 / :8096   your live dev + its cloudflared. 200, but see §1 — running on a freed inode.
:8098           backend, /root/picks.hermes.db, this branch. 200.
:3098           branch frontend — DOWN (SIGBUS). Its cloudflared (pid 2771803) is still up,
                so that tunnel URL serves an error. That is why "the new tunnel looks the same."
:8099           landing-zone backend — deliberately stopped, Job 12 complete. Do not revive.
```

Memory 1.1 GB free of 5.9 GB. `:3098` died once mid-session and I misread it as OOM; it was
the corrupt binary both times.

## 6. Open work

- `SPEC-backend-remaining.md`, `SPEC-frontend.md`, `TASK-job14-position-aware-surfaces.md` —
  all still **untracked** in the worktree. FE-4 (the M3 objects) is now done; the rest stands.
  IDP remains **Micah's call**.
- Nothing has been pushed. Review before push; the pre-push hook blocks an untagged version bump.

## 7. The pattern worth carrying forward

Three separate times in one night, **presence was mistaken for integrity**:

- a 20,627-row table that was 100% NULL,
- `next`'s files all *present* while one was truncated — I checked presence and declared the
  package intact,
- a gate suite that was *running* while two of its gates measured nothing.

The generalization: a count, a 200, a file listing, and a green suite are each a claim about
a thing, not the thing. Load the binary, read the value, check the exit code.

**And the fourth instance, found the same night:** eight green gates over a page that crashed
on first render. Every one of them was true. None of them rendered React. A gate suite is a
claim about the surfaces it touches — the pool table was never one of them.

## 8. First moves next session

1. Ask Micah to run the §1 npm command if it hasn't been run — `rc=135` means it hasn't.
2. `bash /root/lp-team-vocab/verify-gates.sh all` — the two FAILs should clear on the repair alone.
3. Re-run the jest suite that has never seen the M3/M5 code, and `tsc --noEmit` (§4 items 3–4).
4. Start `:3098` and **open the mock draft in a browser** — that surface has still never been
   looked at. Screenshot it. §4 items 1, 5, 6 are decisions Micah should make from the page,
   not from this document.
