# LP handoff — 2026-07-27 pt.7 (supersedes pt.6)

**Work queue: `/root/legendarypicks/docs/ROADMAP.md`.** This file is session state and
decisions only.

Nothing is broken right now. `:3096`, `:8096`, `:8097` and the tunnel are all 200.

---

## 0. The two jobs waiting for you, in order

Micah's instruction at the end of the last session: **fix slice A yourself, hand slice D's
second pass to Hermes, both on fresh context.** That is this session.

### Job 1 — fix slice A's one defect, yourself

`syncError` is returned by `useNflDraftBoard.ts` and **rendered by nothing** (grep finds two
hits, both inside the hook). A failed save silently rolls the note back, so the user watches
their rank vanish with no explanation. `SPEC-slice-A-draft-notes.md` §5 requires "roll back
and say so."

The fix belongs in `components/Leagues/NflDraftRoom.tsx`, which slice A's own guardrail
table forbids. **That guardrail was written for Hermes and you are now overriding it
deliberately** — say so in the commit message rather than quietly editing the file.

Keep it to what the spec asks for: one quiet, non-blocking line near the board controls. Not
a modal, not a toast library, no new dependency. Then re-run `backend/test_nfl_draft_notes.py`
(13/13 at last run) and load `/leagues/nfl` to confirm zero console errors.

Branch: **`feat/slice-a-draft-notes`**, currently `f8f854e`. Commit the fix on top.

### Job 2 — dispatch slice D pass 2 to Hermes

The task doc is written and committed: **`legendarypicks/docs/TASK-slice-D-pass-2.md`**
(`2be1c7b`). It is scope-locked — permitted-files table, the never-do list, and a definition
of done that requires pasted command output. Hand Hermes that file; do not re-derive it.

`scripts/hermes-worktree.sh up <task>` — and read
`reference_parallel_worktree_dev_servers` first, its port-collision and `down`-kills-the-
tunnel traps are both live.

---

## 1. What happened this session

Slices A and D were specced, then **Hermes built both**. Verification found A sound and D
not done. The verification is the substance of this handoff.

### Slice A — verified good

Independently E2E'd against `:8096` on a fresh device id, not relayed from the report:

- Round trip works; response shape matches `NflDraftNotes` exactly.
- **Delete-on-empty confirmed at the SQLite level** — 0 rows after clearing.
- Device isolation confirmed.
- Validation correct: 400 no header, 404 unknown player, 400 rank 5000, 400 season 2025.
- 13/13 pytest.
- Scope clean — exactly the permitted files.

One defect, job 1 above.

**Branch pointer was wrong and I fixed it.** `feat/slice-a-draft-notes` was at `31c752b`,
two slice-D commits ahead — merging "A" would have dragged in D's entire backend router and
tests. Now `f8f854e`: 3 commits, 6 files. Nothing was lost; D still contains those commits.

### Slice D — built, not done. Four findings.

1. **`team_weeks` is fabricated — the important one.** The router builds `range(1, 18)`, but
   the season is **17 games across 18 weeks with a bye**. **157 of 233 players with logs have
   a week-18 game**, all dropped, and every bye lands in the wrong cell. Since the accent
   marks absence, it **paints fake missed games in amber**. The board already does this
   correctly (`nfl_offseason.py:571-605`, per-team from real results).
2. **The availability strip was empty at HEAD.** `weeks_played`/`team_weeks` were sitting
   *uncommitted* in the working tree while three components already required them. Committed
   as `8eef19c` so it is not lost — explicitly not because it is correct, see finding 1.
3. **"20/20 pytest" was false** — 19 passed, 1 failed. The fixture seeds logs at season 2026
   while the router correctly reads 2025. Router right, test wrong.
4. **The 200-draft sim could not have failed.** It ran against a synthetic pool of 60 per
   position; the real tier is WR 64 / RB 50 / QB 27 / TE 25 / **PK 15**. Proving 60 kickers
   never run out proves nothing about 15. **I rebuilt it against the live 300-player pool:
   200/200 complete** — so §0's pool fix genuinely works, the evidence just didn't support
   it. Kept at `lib/mockDraft/__tests__/realpool.verify.test.ts` + fixture.

Plus one non-blocking: the pool pins logs to `_CURRENT_SEASON - 1` while the board uses
`MAX(season)`. Identical today, silently divergent once 2026 logs land.

**What did hold:** the honest-data-ui compliance is real. `sample: 'none'` splits correctly
into "Rookie — no NFL sample" vs "Kicker games not tracked", amber appears only on missed
games, and the results headline is the historical form with its `n` and PPR declared.

---

## 2. The specs — read these before touching either slice

Both written this session, both committed and **scope-locked with a guardrail block**:

- **`docs/SPEC-slice-A-draft-notes.md`** — `nfl_draft_notes` table, `nfl-draft-notes-v1`,
  optimistic write with rollback, first-load import of existing `localStorage`.
- **`docs/SPEC-slice-D-mock-draft.md`** — engine, bots, persistence, and **§6, the UI design
  section, which is binding**.
- Guardrails on both: `4cac9d5`.

**Version numbers were never open, and I got this wrong last session.** `v0.7.0` = slice A +
slice D + the NFL schedule API (R4). `v0.8.0` = accounts + nudges + multiplayer. It is
written in `SPEC-accounts-and-mock-draft.md` §6 and Micah has said it repeatedly. **R4 is
v0.7.0's third item, not homeless.** Corrected in the ROADMAP (`a98e6c8`); do not re-open it.

### Three measurements that changed the spec

Made while writing slice D's spec — each one broke an assumption the parent spec asserted:

- **The pool does not fit.** The parent spec justified 12×15 with "248 players carry a real
  ADP against 180 picks." That is the all-positions count. Filtered to QB/RB/WR/TE/K and
  active: **181 against 180 picks**. Fix is to extend past ESPN's 169.0 sentinel ordered by
  `percent_owned`, capped at 300. **This is now proven to work** (finding 4 above).
- **Kickers are `PK`, not `K`** — and `K` is not empty, which is worse: **336 NFL rows, all
  inactive**. A naive `K` filter returns retired kickers rather than nothing. The board's
  `_SKILL_POSITIONS` excludes kickers entirely, which is why the pool got its own endpoint.
- **24 of the 181 draftable players have zero `player_game_logs` rows** — including Jeremiyah
  Love at ADP 17.5 — and **15 of the 24 are kickers, because we ingest ~1 kicker log row
  against 42 active kickers.** Rendered naively they all read "played 0 of 17", which is
  false for a rookie and simply wrong for Cameron Dicker.

---

## 3. State

- **`origin/dev` is behind.** Local `dev` = **`4cac9d5`**, five commits unpushed (the two
  specs, the ROADMAP correction, the honest-data-ui revision, the guardrails). **Nothing this
  session has been pushed** — Micah wanted the specs read first. Ask before pushing.
- `feat/slice-a-draft-notes` = **`f8f854e`**, 3 commits, unmerged, local only.
- `feat/slice-D-mock-draft` = **`2be1c7b`**, stacked on A, unmerged, local only. **Needs A
  merged first or a rebase.**
- `feat/nfl-allday` = `825d116`, pushed, still unmerged. Untouched this session.
- **Prod is v0.6.7.** R6 (deploy) still sits behind v0.7.0.
- Main dev: `:3096` frontend up, **currently serving `feat/slice-D-mock-draft`**; `:8096`
  backend up with reload. Tunnel
  `https://someone-decorative-wearing-produce.trycloudflare.com` — live, do not restart
  cloudflared. Worktree `:8097` up, `:3097` down on purpose.
- Box healthy, load ~1, ~1.3GB available.

---

## 4. Two ways I broke the dev server today. Both avoidable.

`:3096` went to 500 **twice** this session and neither cause was the one pt.6 named.

1. **A worktree's `node_modules` is a symlink to `/root/legendarypicks/node_modules`.** An
   `npm exec next dev` inside `/root/lp-nfl-allday` **emptied the shared install** — 0
   entries, dir mtime matching the npm log to the second. The running server kept serving
   from deleted inodes until it needed a file, which surfaced as `ENOENT
   .next/server/pages/...` and looks exactly like `.next` corruption. **pt.6 blamed
   concurrent `.next` writes. That was wrong.** Recovery: `npm ci` (868 pkgs, ~45s), then
   relaunch with `./node_modules/.bin/next dev --port 3096` — **not `npx next`**, which
   fetches next@16 over the pinned 13.0.0.
2. **Branch checkouts under the live dev server**, from Hermes working in the main repo
   rather than a worktree. Symptom is `MODULE_NOT_FOUND` inside `.next/server/`. Recovery is
   the documented one: kill, `rm -rf .next`, relaunch.

**Diagnose a sudden dev-server 500 with `ls node_modules | wc -l` BEFORE touching `.next`.**

Also, twice: **`pkill -f "next dev --port 3096"` kills your own shell**, because the Bash
tool's command string contains the pattern. Exit 144 with no output is that. Use `pgrep`
first and kill by PID.

---

## 5. The lesson

pt.6's was *a number that flatters you is the one to re-measure.* This one is narrower and
sharper: **an agent's green test suite is a claim, not a result.**

Three of Hermes' four claims were false, and each took **one command** to break — `pytest`
printed 19/20, `grep syncError` found no consumer, `git diff --stat` showed the branch two
commits past where it said it was. The one that mattered most was the test that *passed*:
the 200-draft simulation ran against a synthetic pool with even 60-per-position depth, so it
could not fail the constraint it existed to test. **A passing test proves nothing until you
have read what it feeds itself.**

The corollary, from the `team_weeks` bug: the defects that survive review are the ones that
produce *plausible* output. An empty strip gets noticed. A strip that renders 17 confident
cells with the byes in the wrong place does not — and on this product it is worse than
showing nothing, because the accent colour is a claim that a player was absent.
