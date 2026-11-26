# LP handoff — 2026-07-27 pt.11 (supersedes pt.10)

**Work queue: `/root/legendarypicks/docs/ROADMAP.md`.** This file is session state and
decisions only.

Nothing is broken. `:3096`, `:8096`, `:8098` all 200. **No code was written by me this
session** and **the live dev DB was never touched.** `dev` is unchanged at `ede618b`.

---

## 0. What this session was

Micah hit a session limit and delegated the entire roadmap to **Hermes** (DeepSeek,
tmux `hermes:0.0`) working in `/root/lp-team-vocab` against a **copy** of the DB. This
session is the **verification pass over that delegated run**, plus one repair job dispatched
back into it.

Micah's framing, and it was the right call: *"my advice is not to stop hermes but to start
verifying the work to see what to merge to dev."* Hermes kept building the whole time.

**Everything below marked ✅ was measured by me against the DB or the running API.** Hermes'
own reports were treated as claims, per `feedback_verify_agent_diagnoses` — and two of them
were wrong.

---

## 1. The branch, and why it cannot merge yet

**`feat/dst-and-mock-draft`** in `/root/lp-team-vocab`, at `cc755f3`, **14 commits,
unpushed, never merged.** (Hermes renamed the branch mid-run; pt.10 called it
`fix/team-vocabulary`.)

⛔ **The blocker is not code quality, it is that code and data are now coupled.** The branch
assumes a migrated DB — ESPN team codes, a `game_type` column, an `nfl_snap_counts` table,
and all-positions game logs. **Dev's `picks.dev.db` has none of those.** Verified directly:
no snap table, no `game_type` column, Aubrey still 1 row, `LA`/`WAS` still present.

**The landing zone is the next job and it does not exist yet:** copy `picks.dev.db` →
run migration + `--all-positions` ingest + snap ingest against the copy → **gate on a board
diff** → only then merge. This is the single thing standing between the branch and dev.

One open question that only the landing zone can answer: with the new `game_type` guard
falling through to empty on an un-migrated DB, the outer `WHERE` in
`_regular_season_aggregates` has **no week bound at all** — only the `primary_team` subquery
does. Whether playoff rows re-enter `games_played` then depends on the downstream
`weeks_played ∩ team_weeks` still catching them. **Verify it, do not assume it.** This is
pt.10's "incidental correctness" resurfacing.

---

## 2. What Hermes actually got right — verified, with numbers

| commit | claim | my measurement |
|---|---|---|
| `fe9d6a1` | `team_codes.py`, published vocabulary | ✅ **zero** legacy codes (`LA`/`WAS`/…) left in `player_game_logs`; migration moved 14,937 rows |
| `2c9cb52` | `team_weeks` from `nfl_schedule` | ✅ 285 games, **32 teams × 17** regular-season games each |
| `3c16d68` | all positions (R5/B8) | ✅ **the headline** — see below |
| `ba4ae0b` | `game_type` marks playoffs (B10) | ✅ REG 18,539 · WC 398 · DIV 280 · CON 137 · SB 67 |
| `def15fa` | `nfl_snap_counts` own table (M2) | ✅ 20,627 rows, 1,783 players, 2025 — **but shipped a defect, §3** |
| `8bf1e7c` | mock draft resume/share (M4) | ⚠️ merge hazard, §4 |
| `e40be76` | `normalize()` at 7 ingest boundaries | ❓ **not independently verified** — needs live ingest runs |

### The R5 result is the real win, and it closes pt.10 §1

Hermes ran the published `stats_player_week` file across **all positions** — the second
source, used exactly as `published-first` prescribes. 2025 log coverage:

```
LB   2 → 253      CB   0 → 205      DT   1 → 167      PK   1 → 32
```

**Brandon Aubrey now reads 17/17**, weeks 1–9 + 11–18 (week 10 = DAL bye), corroborated
independently by his snap-presence rows. pt.10's headline bug is closed — and closed the
right way: `player_game_logs` was **not** rewritten from snap counts. Micah's rejection of
that rewrite in pt.10 §1 held.

**Defender availability now has a believable distribution** — of 100 CBs: 27 at 17/17, then
12·16, 7·15, 7·14, tailing to 10. That shape is only producible from a real presence record.
Before this, the board had **zero** CBs with data.

Board went 522 → **1,787** eligible players.

---

## 3. Two defects I found in committed work — dispatched back as "Job 9", both now fixed

### 3a. The snap table was 100% empty and nobody noticed

`ingest_nfl_snap_counts.py:190` had an **inverted NaN guard** — the `continue` was dropped,
so the assignment body ran *only* for None/NaN:

```python
if v is None or v != v:   # NaN
    fv = float(v)         # ← unreachable for real values
    snap_add[col] = ...
```

All 20,627 rows had `off_snaps`/`def_snaps`/`st_snaps`/all three `_pct` columns **NULL**.
Availability survived only because it counts rows (presence), never values — so the bug was
invisible to every test and to the board.

⚠️ **The trap that would have made the fix look successful:** the insert was
`INSERT OR IGNORE` with a pre-loaded `existing_snap_keys` skip. A plain re-run reports
*"20,627 already present"* and repairs nothing. I put that in the spec; Hermes took the
better option and converted it to `ON CONFLICT … DO UPDATE`, so the ingest is now idempotent
and self-repairing.

**Verified after (`b3d2b29`):** 41,254 non-null values across 20,627 rows; all 17 Aubrey
weeks match his game-log `stats` JSON **exactly, zero mismatches** (wk1=8, wk2=15, wk3=6);
`off_pct`/`def_pct`/`st_pct` all 20,627 populated; values sane (st max 33, off max 96).

**Regression gate passed:** diffing my own pre-repair vs post-repair board captures, the
change was **additive only** — one new `games_missed` field per row, and *not a single*
`games_played` or `weeks_played` value moved. Presence untouched, exactly as required.

### 3b. An unguarded schema read that was the literal merge blocker

`nfl_offseason.py:560` had `AND game_type='REG'` hardcoded while every other
schema-dependent read in that file goes through `_table_columns`. Against dev's un-migrated
DB it raises `no such column: game_type` and 500s the draft board. Fixed in `348ff2b`.

---

## 4. Still open

- ~~**`games_missed` uses a hardcoded constant.**~~ **RESOLVED in `cc755f3`** — now
  `team_games_val - games_played`. `348ff2b` had shipped
  `_REG_SEASON_TEAM_GAMES - games_played`, the exact defect pt.10 §2e filed against
  `DraftRoom.tsx:255`, promoted into the backend where it becomes the API contract. Measured
  before the fix: `team_games` uniformly 17 across 407 rows, **zero current disagreements** —
  latent, not live, but it breaks under roadmap **B1**. Contract change also got split out
  properly into `aba2f79`.
- **`8bf1e7c` re-created `nfl_mock_draft.py` on a branch that does not contain `dev`.** Dev
  already has that file; the branch version is dev's content **+ ~120 lines** of M4
  resume/share. Git will flag an **add/add conflict**; "take branch" is the correct
  resolution, but check it deliberately rather than letting a merge tool pick.
- **D/ST (M1) is committed but not ingested.** `ab6aa12` ("D/ST fantasy stats + mock draft
  room — M1, M5, R7") is in, **but there is still no `nfl_dst_stats` table in the DB** — the
  ingest has not been run, so none of it is verified against data. This is the item Micah
  called the thing that makes the mock draft shippable. **Treat `ab6aa12` as unverified: it
  bundles M1 + M5 + R7 in one commit and arrived after the audit above.**
- **B9's data half is not done.** The migration rewrote **team** columns only.
  `position='K' AND active=1` still returns **0** — the two-vocabulary split in
  `players.position` persists in the data; `team_codes.py` only prevents *new* bad values.
- **`e40be76` is unverified** — the `normalize()` calls at ingest boundaries can only be
  confirmed by running those ingests.

---

## 5. Lessons

**1. A green count is not a verified value.** The snap table had 20,627 rows and a passing
test suite, and every value column was NULL. Row count answered "did it insert", which was
never the question. Ask what the *payload* looks like, not whether the operation ran.

**2. Hermes' own summary contained a false claim, in the same shape as pt.10 §5.** Its Job 9
entry says *"Board diff: IDENTICAL"*. Mine was **additive-only** — `games_missed` appeared on
every row, introduced by its own neighbouring commit. Identical would have meant nothing
changed, and something did. pt.10's lesson was *a changelog bullet is a claim too*; this is
the same failure in a job log. **Diff it yourself and keep your own pre-change capture** —
that saved artifact is what made the gate meaningful here.

**3. The right fix came from Micah's framing, twice over.** pt.10 records him rejecting the
game-log rewrite; this session proves that rejection correct — the published all-positions
file solved it with no migration and no risk to the stat table. And "don't stop Hermes,
verify in parallel" produced eleven commits *and* a full audit in the same hour.

**4. Delegation channel: `tmux send-keys`, file-mediated.** MCP `messages_send` remains
useless. Multi-line pastes submit line-by-line, so **write the spec to a `TASK-*.md` file and
send a one-line dispatch pointing at it** — that worked cleanly, including telling Hermes to
dispatch its own subagent. See `TASK-job9-snap-and-guard-fixes.md` for the shape: exact
files, forbidden paths, the trap, the verify queries, the regression gate.

---

## 6. State

- **`dev` = `ede618b`, unchanged this session.** Tag **v0.6.11** at `c05a7b9`. Prod is
  **v0.6.7**.
- **`feat/dst-and-mock-draft` = `cc755f3`** in `/root/lp-team-vocab` — 14 commits, unpushed.
  The last three (`aba2f79`, `ab6aa12`, `cc755f3`) landed after the audit; of those only
  `cc755f3` is verified.
- `feat/slice-D-mock-draft` = `3320d75` — checked out in the main repo, what `:3096` serves.
- Other worktrees: `/root/lp-nfl-allday` `825d116`, `/root/lp-nfl-usage` `0ced86f`,
  `/root/lp-slice-D-pass-2` `fadaf3a`.
- **Two DBs, do not confuse them.** Live dev = `/root/legendarypicks/backend/data/picks.dev.db`
  (**untouched, un-migrated**). Hermes' copy = `/root/picks.hermes.db` (**all the work is
  here**). The `picks.dev.db` in the repo root is still a 0-byte decoy; a schema-only
  `backend/data/picks.db` appeared in the worktree and is gitignored (harmless).
- Ports: `:3096` frontend, `:8096` backend, `:8098` Hermes' worktree backend (**its process —
  don't restart it**). Tunnel `https://someone-decorative-wearing-produce.trycloudflare.com`
  → 3096. **Don't touch cloudflared.**
- Hermes runs in tmux `hermes:0.0`, model `deepseek-v4-pro`, dispatching its own subagents.
  Its logs: `/root/lp-team-vocab/JOB-RESULTS.md` (jobs 1–9) and `HANDOFF-2026-07-28.md`.

---

## 7. Suggested order

1. **Build the landing zone** (§1) — copy dev's DB, migrate, board-diff gate. Nothing merges
   without it.
2. **Verify `ab6aa12`** (D/ST + M5 + R7 — unverified, bundled, landed after the audit) and
   **run the D/ST ingest** — no `nfl_dst_stats` table exists yet. D/ST is what makes the mock
   draft a real fantasy draft.
3. Resolve the `nfl_mock_draft.py` add/add deliberately, then **merge to dev** once the gate
   is green, and verify the board on `:3096`.
5. Then pt.10's order stands: familiar-UX room pass → board grid → player overlay →
   `injuries`.

Carried and still unstarted: **R4**, the other leagues' vocabulary migrations, and B9's data
half.
