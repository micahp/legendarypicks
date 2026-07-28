# Audit brief for Codex — Legendary Picks NFL draft work, 2026-07-28

You are auditing a body of work that **has never been merged, never been pushed, and never
been seen by the user in a browser.** Assume nothing in it is correct because a test passed.

This brief exists because the same failure mode has now recurred at least six times across
four sessions: **a green signal that was a claim about something other than what it named.**
Your job is to find the instances we have not found yet.

---

## 0. What to audit

1. **The merge.** `feat/dst-and-mock-draft` → `dev`. 59 commits, 0 behind. `dev` is at
   `ede618b`. Nothing pushed.
2. **Everything done since pt.11** (2026-07-27) — jobs 9 through 15, the D/ST work, the
   mock draft engine, the ADP ingest.
3. **The database**, `/root/picks.hermes.db` (160 MB). This is the one the branch's backend
   reads. Treat every table as guilty until measured.
4. **The feature work as a product** — does the mock draft and the Player Rankings board
   actually do what the roadmap claims.

---

## 1. Ground truth — where everything lives

| thing | value |
|---|---|
| work tree | `/root/lp-team-vocab`, branch `feat/dst-and-mock-draft` |
| its servers | backend `:8098`, frontend `:3098` → `https://altered-era-sold-explain.trycloudflare.com` |
| user's live tunnel | `:3096`/`:8096`, tree `/root/legendarypicks`, branch `feat/slice-D-mock-draft` — **0 ahead / 9 BEHIND `dev`** |
| delegated worktree | `/root/lp-job15-dst-published-adp`, branch `feat/job15-dst-published-adp`, backend `:8093`, frontend `:3093` — Hermes, in flight |
| database | `/root/picks.hermes.db` |
| the scoreboard | `bash /root/lp-team-vocab/verify-gates.sh all` (`LP_GATE_W/B/F` retarget it) |

**Resource ceiling: ~1.9 GB available, swap 3.3/4.0 GB used.** Each `next dev` is 350–440 MB.
Do not start more servers. Do not run `npm`/`npx` in any worktree — `node_modules` there is a
**symlink to the shared install** and an `npx` empties it, taking down every dev server on the
box. That happened on 2026-07-28 and cost a morning.

---

## 2. The failure pattern — six confirmed instances

Read these before auditing. They are the shape of what you are looking for.

| # | The green signal | What it actually asserted | The truth |
|---|---|---|---|
| 1 | 8 gates PASS on the draft pool | grep'd source strings and HTTP 200s | the page **crashed on first render**; not one gate rendered React |
| 2 | `npm install …@next/swc` → `up to date in 4s` | the dep tree matches `package.json` | the binary on disk was **truncated to 28.8 MB of 82.2 MB**; npm never checks file integrity |
| 3 | `REG-jest` PASS | jest ran the `lib/mockDraft` path | jest had been **dead since 01:54**; every M3/M5 commit landed against an inert gate |
| 4 | gate `B4` PASS, claims "TEAM_GAMES rendered" | greps `"TEAM_GAMES - "` | code is `/{TEAM_GAMES}` — **the pattern is narrower than the claim** |
| 5 | `TS2322` triaged as "cosmetic" | a type mismatch | `useNflDraftBoard` **was never called**; the camp-tab board was a dead surface |
| 6 | code comment: *"D/ST — no published ADP exists"* | an assertion about the world | **false.** All 32 carry a published ADP in a payload we already download |

**The generalisation:** a comment, a gate name, a task spec, and a tool's success message are
all *claims*. Each was load-bearing. Each was one measurement from being falsified.

---

## 3. Contradictions found today — verify these, then look for siblings

### C1. Two endpoints disagree about the same entity (open — assigned to Hermes as B17)

```bash
curl -s "http://127.0.0.1:8098/api/nfl/draft-board?season=2026&position=DEF&limit=40" \
  | python3 -c "import sys,json;[print(p['name'],p['games_played'],p['sample']) for p in json.load(sys.stdin)['players'] if p['name'].startswith('SEA')]"
# -> SEA D/ST 17 full

curl -s "http://127.0.0.1:8098/api/nfl/draft/player/30116" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['name'],d['games_played'],d['sample'],d['dst_pts_per_game'])"
# -> SEA D/ST 0 none 9.6      <- 0 games played, 9.6 points per game
```

Root cause: `player_detail` (`backend/routers/nfl_mock_draft.py:617`) has **no D/ST branch**
and falls through to `games_played = len(log_rows)` over `player_game_logs`. Measured:

```sql
SELECT DISTINCT p.position FROM player_game_logs l JOIN players p ON p.id=l.player_id
WHERE l.league='nfl';
-- RB,QB,WR,TE,S,FB,CB,P,G,OT,LB,DE,ILB,FS,C,PK,DT,K,MLB,OLB,SAF,LS,DB,NT,OL
-- note: no DEF. Team defenses are not player rows in this table at all.
```

**Audit question: what else derives presence or availability from `player_game_logs`?**
That table's membership rule has changed at least once (it used to be touches-only; it now
carries OL/DB rows from the published all-positions file). Any code that treats "no row" as
"did not play" is wrong for some class of entity. Find all of them.

### C2. A task spec that instructs its own defeat

`TASK-job15-dst-published-adp.md` §3 told Hermes to *"delete the `dst_rank` block"* and, in
the same sentence, to *"keep `games_played`/`games_missed`/`weeks_played`/`team_weeks` for
D/ST exactly as they are."* **They are the same loop** (`nfl_mock_draft.py:332-351`).
Following it literally destroys the only correct source of D/ST availability in the codebase.
Amended in §6a of that file (`8220707`) before Hermes started. **Audit the other TASK specs
— job9 through job14 — for the same class of defect.** Several were executed as written.

### C3. Delivery — the user has been reviewing a stale branch for two days

The user reported "the roadmap from yesterday is still not done" and "I can't click a player,
the overlay doesn't show up." Both were accurate *for the URL he was given*:
`PlayerDetailOverlay.tsx` **does not exist as a file** in `/root/legendarypicks`. 59 commits
of work were invisible. **Audit question: is there anything in this branch that only ever
worked because it was verified against the wrong tree or the wrong port?** The gate runner
defaulted to fixed hosts until `00b663d`; before that, a delegated worktree could verify the
*main* tree's servers and report success. At least one job ran under that regime.

### C4. Database — measured, unresolved

```
players (nfl)                 24,678      distinct teams 32
espn_id NULL/empty (nfl)       7,889
D/ST rows                          32      of which espn_id set:  0     <- join matches 0 of 32
nfl_adp rows                    9,611      of which DEF:          0
player_game_logs (nfl)         25,062
```

The D/ST ADP join has always matched **0 of 32**. It did not raise — **a wrong join key
misses, it does not error.** The miss was papered over with a derived `dst_rank` and a
reserved pool slot, and the derivation ranks SEA #1 where ESPN ranks DEN #1 and SEA 4th.

Known related hazard, previously confirmed: **team-code vocabularies differ** (ESPN
`LAR`/`WSH` vs nflverse). A wrong join key silently missed 178 players once. The migration to
ESPN codes was applied to `picks.hermes.db` **only** — other databases on this box were not
migrated. **Audit every join between tables that carry a team code.**

Also verify, do not assume: `/root/legendarypicks/picks.dev.db` is **0 bytes with no tables**,
yet is named in the documented launch command for the `:8096` dev backend. Determine what
`:8096` is actually reading.

---

## 4. Specific things to check that we have NOT checked

1. **Does any gate in `verify-gates.sh` assert something narrower than its name?** #4 above is
   one confirmed case. Read each assertion against the claim in its label. A gate whose
   pattern is narrower than its name is a gate that fails open.
2. **`REG-render` does not exist.** No gate renders React. Two real bugs (a clock deadlock
   that ran a 180-pick draft in 40 seconds, and a dead camp-tab board) were found only by
   hand-driving a browser. Everything shipped before that has never been rendered under test.
3. **2 pre-existing jest failures** in `components/Game/WCContext.test.tsx`, invisible because
   `REG-jest` only runs `--testPathPattern='lib/mockDraft'`. Unknown age.
4. **`typescript.ignoreBuildErrors` is set.** 25 tsc errors do not break the production build.
   Four of them are in `components/MockDraft/DraftRoom.tsx`, including
   `Property 'team_games' does not exist on type 'PoolPlayer'` at :665 — a type the code reads
   at runtime anyway. Determine which of the 25 are real.
5. **`filterSlotIds` is ignored** by the ESPN endpoint we call — `[0]`, `[0,16]`, `[16]` all
   return the identical 11,513 rows. Do not "fix" the filter; do check whether anything
   downstream believes it worked.
6. **Untracked production-relevant files.** `git status` in `/root/lp-team-vocab` shows
   `SPEC-backend-remaining.md`, `SPEC-frontend.md`, several `TASK-job*.md` and older handoffs
   still untracked. A prior incident had prod timers running 11 uncommitted scripts.
7. **The mock draft as a product.** It is still a proof of concept. Verify against the
   roadmap's M1–M7 claims rather than against its own tests.

---

## 5. What "done" looks like for this audit

Counts and payloads, not adjectives. For every finding:

- the **command** that produces it, runnable on this box
- the **observed value** and the **expected value**, side by side
- whether it is **user-visible**, and on which URL

"Verified" is not a result. `REG-adp-dst` is currently RED **on purpose** — expected values
were committed before the code exists (`b8cc4b1`). **Making a gate green by editing the gate
is the one unacceptable outcome.** If a number genuinely disagrees with the source, say so and
stop: the measurement wins, and the gate changes in the same commit as the evidence.

Do not run `npm`, `npx`, `yarn`, or `pnpm` anywhere. Do not start new dev servers. Do not
restart `:3096`/`:8096` — that is the user's live tunnel and it is externally managed.
