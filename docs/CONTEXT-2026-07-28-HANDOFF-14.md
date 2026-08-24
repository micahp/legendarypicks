# HANDOFF pt.14 — 2026-07-28 (later)

Supersedes pt.13. **Branch `feat/dst-and-mock-draft` in `/root/lp-team-vocab`, 55 ahead /
0 behind `dev`. Nothing merged, nothing pushed. `dev` unchanged at `ede618b`.**

pt.13's blocker is cleared. The mock draft has been opened in a browser. Two real bugs were
found there that eight green gates had not.

---

## 1. State of the work = one command

```bash
bash /root/lp-team-vocab/verify-gates.sh all
```

```
── gates against W=/root/lp-team-vocab B=http://127.0.0.1:8098 F=http://127.0.0.1:3098 ──
PASS A1 A1b A2 A3 · B1 B2 B2b B4
PASS REG-pool REG-dst REG-pytest REG-jest REG-modules
FAIL REG-adp-dst   ← RED ON PURPOSE. Expected values committed before the code (b8cc4b1).
```

**`REG-adp-dst` is the only red gate and it is supposed to be red** until job15 lands. Do not
make it green by editing it. `W`/`B`/`F` are now overridable (`LP_GATE_W/B/F`) so a delegated
worktree points at its own servers instead of silently verifying this one.

---

## 2. pt.13's blocker: fixed, and npm lied twice

The truncated `next-swc` is repaired. **The command pt.13 told you to run does not work** —
`npm install --no-save @next/swc-linux-x64-gnu@13.0.0` returns `up to date in 4s` and repairs
nothing, exactly as the 01:58 attempt did. npm checks the tree against `package.json`; it
never verifies file integrity.

What worked: `npm pack` the tarball, **load-test it in the scratchpad**, then copy it in.

| | bytes |
|---|---|
| on disk (truncated 01:54) | 28,866,048 |
| actual 13.0.0 binary | 82,195,976 |

`rc=135` → `LOADED OK`, and `/`, `/mock-draft`, `/leagues/nfl` all compile fresh — so it is a
real fix, not another freed inode. **jest ran for the first time since 01:54: 36/36.** Every
M3/M5 commit had landed against an inert gate; they are now actually tested.

---

## 3. What was fixed (5 commits, all verified in a browser)

- **`8234ecb` — D/ST has a starting roster slot.** `buildRosterSlots` stopped at K and padded
  to 7 bench. The engine's `STARTER_COUNT` has always included DEF, so a bot-drafted defense
  landed silently on the bench. Both builders (draft room *and* results screen — separate
  copies) fixed; bench 7→6 keeps the 15-man roster.
- **`1a46101` — the clock was a deadlock.** It hit 0:00 and nothing picked; the draft sat on
  pick 6 forever. Now autopicks from the queue first, else best-available zero-jitter, marked
  `auto: true`. Two traps, both found by watching a real draft: `userTurn` doesn't change
  between consecutive user turns (**one timeout cascaded through all 180 picks — a full draft
  in 40 seconds**), and a stale `seconds` on the turn-change render fired twice and skipped the
  back-to-back snake pick. Verified at seat 1: picks land at 1, 24, 25, 48.
- **`77de2f1` — the camp-tab draft board was dead.** `/leagues/nfl?tab=camp` showed "Draft
  board unavailable." `NflDraftRoom` is presentational but the page rendered
  `<NflDraftRoom enabled={…} />` and **`useNflDraftBoard` was never called at all.** pt.13 filed
  this as a cosmetic `TS2322`. It was the bug. tsc 26 → 25.
- **`b8cc4b1` — `REG-adp-dst`**, expected values written before the code exists.
- **`00b663d`** — gates retargetable to a worktree.

---

## 4. The finding that matters: we invented an ADP that is published

`backend/routers/nfl_mock_draft.py:314`:

```python
# D/ST — no published ADP exists. Derive ranking from fantasy totals.
```

**Measured 2026-07-28: false.** All 32 D/ST carry a published ADP, in the payload
`ingest_nfl_adp.py` **already downloads**:

```
Broncos D/ST   espn_id=-16007  adp=89.94   owned 98.7%
Texans D/ST    espn_id=-16034  adp=91.81   owned 98.9%
Rams D/ST      espn_id=-16014  adp=98.19   owned 92.5%
Seahawks D/ST  espn_id=-16026  adp=106.50  owned 98.3%
```

ESPN keys D/ST with **negative ids** (`-16000 - proTeamId`). All 32 `players.espn_id` are
empty, so the join matched **0 of 32** — it did not raise, it missed, and the miss was papered
over with `dst_rank` + a reserved pool slot at 150.

**The derivation is also wrong on the merits: it ranks SEA #1; ESPN ranks DEN #1, SEA 4th.**

⚠️ **This voids pt.13 finding #6.** Micah had answered "honor the API (~150)" before this was
measured — that question was a choice between two fabrications and no longer needs an answer.
The team map is published too (`?view=proTeamSchedules_wl` → `proTeams[]`, `id=14 abbrev=LAR`
→ `-16014`, verified against the id ESPN actually returned). Do not hardcode 32 rows.

Also note: `filterSlotIds` is **ignored** by that endpoint — `[0]`, `[0,16]`, `[16]` all return
the identical 11,513 rows. Don't "fix" the filter.

---

## 5. Delegated to Hermes — job15, ready to dispatch, NOT YET STARTED

`/root/lp-team-vocab/TASK-job15-dst-published-adp.md` (committed, scope-locked).

**The worktree has not been created yet.** When it is:

```bash
LP_WT_BPORT=8093 LP_WT_FPORT=3093 \
  /root/legendarypicks/scripts/hermes-worktree.sh up job15-dst-published-adp feat/dst-and-mock-draft
```

⚠️ **Do not use the script's default ports — `8097` is already occupied** (python pid 2342623).
The worktree backend would die on startup while the agent verifies against the main tree and
reports success. That is the exact failure the script's own header warns about.

Hermes owns `backend/` only. It must not touch `verify-gates.sh`, any `.tsx`/`.ts`, host
config, or run `npm`/`npx` (worktree `node_modules` is a **symlink** to the shared install —
this is what caused the 01:54 outage).

**Hermes MCP delegation is broken** (`messages_send` goes out as Hermes' own identity and the
agent never receives it as a prompt). Micah has to relay the task as a real user message.

---

## 6. Open, in priority order

1. **`REG-render` — the gate gap that outranks everything.** Eight gates were green while the
   pool table crashed on first render. Every one was true; **none of them rendered React.** Both
   bugs in §3 were found by hand-driving a browser. A Playwright smoke gate over `/mock-draft`
   and `/leagues/nfl?tab=camp` that fails on any console/page error is the highest-value
   un-started item. Playwright + chromium are installed at
   `/root/legendarypicks/node_modules/playwright`.
2. **B14** — `team_games` absent from the pool payload, so `DraftRoom.tsx` uses hardcoded 17.
   The payload **does** carry `team_weeks`, so it's a rename: use `team_weeks.length`. B4 passes
   anyway because it greps `"TEAM_GAMES - "` and the code is `/{TEAM_GAMES}` — the gate's
   pattern is narrower than its claim.
3. **B15** — `pages/mock-draft.tsx:107` does `adp: p.adp ?? 999`, rendering a fake `999.0` on
   D/ST. Banned by `honest-data-ui`. Dies with job15 but the coercion should go regardless.
4. **B16** — 2 pre-existing jest failures in `components/Game/WCContext.test.tsx`, invisible
   because jest was dead *and* `REG-jest` only runs `--testPathPattern='lib/mockDraft'`.
5. IDP (BE-5) remains **Micah's call**.

Still untracked in the worktree: `SPEC-backend-remaining.md`, `SPEC-frontend.md`,
`TASK-job14-*.md`, several older handoffs.

---

## 7. Live surfaces

```
:3096 / :8096   Micah's live dev + cloudflared → https://someone-decorative-wearing-produce.trycloudflare.com
                Still the process from Jul 23 running on the freed inode. The shared
                node_modules is repaired, so it will come back healthy when restarted —
                but do not restart it without asking.
:3098 / :8098   this branch → https://altered-era-sold-explain.trycloudflare.com
                Started this session (pid 2994591, cwd /root/lp-team-vocab). Serves 200.
                It was dead all night from the SIGBUS while its cloudflared stayed up —
                that is why "the new tunnel looked the same".
:8099           landing zone — deliberately stopped. Do not revive.
```

**Resources are tight: 2.0 GB available, swap 3404/4095 MB.** Each `next dev` is ~350–440 MB.
Run **one** delegated worktree at a time, not two.

---

## 8. The pattern, extended

pt.13's lesson was *presence is not integrity*. This session added the sharper form:

**A green gate is a claim about the surface it touches.** Eight were green over a page that
crashed on first render — all true, none rendering React. And the inverse showed up twice in
one morning: `npm install` reporting `up to date` over a truncated binary, and a `TS2322`
dismissed as cosmetic that was in fact a dead product surface.

The new one, from §4: **a comment asserting that data does not exist is a hypothesis, and it
ages badly.** "No published ADP exists" was load-bearing for a derivation, a reserved pool
slot, a gate assertion, and an open product decision — and it was one HTTP call from being
falsified. Check the claim before building on it.
