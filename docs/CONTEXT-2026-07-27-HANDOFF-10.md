# LP handoff — 2026-07-27 pt.10 (supersedes pt.9)

**Work queue: `/root/legendarypicks/docs/ROADMAP.md`.** This file is session state and
decisions only.

Nothing is broken. `:3096`, `:8096`, `:8098` all 200. `dev` is pushed and clean.
**v0.6.11 is tagged and pushed.** No database was modified this session.

---

## 0. The headline: the mock draft is NOT shippable, and Micah said so

It renders, it completes a legal 180-pick draft, and it is now reachable from the app. It is
still a proof of concept. Two structural gaps and a pile of missing conventions, all listed
in §2. **Do not treat "slice D is merged" as "the mock draft is done."**

The two that block calling it a fantasy draft at all:

1. **There is no D/ST.** A 15-round roster with no defense is not a fantasy roster.
2. **Availability is computed from the wrong table** — see §1, this is the deep one.

---

## 1. `player_game_logs` is a "who touched the ball" table, not "who played"

This is the most important thing in this file. It was found by chasing one wrong number on
screen and it invalidates the assumption under the app's signature feature.

**How it surfaced.** Micah: "for brandon aubrey it says he missed like most of the weeks last
year which is not true."

```
Brandon Aubrey (id 882, PK, DAL, active) — 2025 game logs:
  ONE row. Week 15 vs MIN.
  stats: {"st_snaps": 16, "carries": 1, "rush_yds": 6, ...}
```

He is in the table because he **ran the ball once on a fake**. That single row is also the
*entire* kicking dataset: **1 row across all 42 active kickers.**

**2025 log coverage by position — the shape is unmistakable:**

| pos | active | with logs | | pos | active | with logs |
|---|---|---|---|---|---|---|
| WR | 391 | 196 | | **LB** | **385** | **2** |
| TE | 199 | 113 | | **CB** | **333** | **0** |
| RB | 192 | 120 | | **DT** | **272** | **1** |
| QB | 119 | 74 | | **OT** | **235** | **8** |
| FB | 18 | 11 | | **PK** | **42** | **1** |

The right-hand column is not sparse data, it is **contamination** — linemen with a fumble
recovery, punters who threw on a fake. The table only contains players who recorded a
passing, rushing or receiving stat. **Anyone who dressed and played every snap without
touching the ball reads as absent.**

### The fix — and note that MY first proposal was wrong

I proposed rewriting `player_game_logs` from snap counts. **Micah rejected it** ("i don't get
why we would rewrite the game log based on snap count") and he was right. That table's job is
stat lines; jamming presence into it formalises the exact conflation that caused the bug, and
costs a 131k-row migration that moves every live number on the board.

**Do this instead:** `nfl_snap_counts` as its **own table**, straight from the published file,
all positions, all weeks, no reshaping. The availability computation reads that for presence.
`player_game_logs` is not touched. If the presence data is wrong, the stat table is untouched
and it is revertible.

**The data is already being downloaded and thrown away.** `backend/ingest_nfl_snap_counts.py`:

- `:16` — *"This UPDATEs the `stats` JSON of rows that already exist; it never inserts."*
- `:101` — *"OL/DL and inactive skill players: snap row exists, no game log. Expected."*

We pull the whole snap-count file, decorate the ~5,360 skill rows that already exist, and
discard every other presence record as "expected." Aubrey's ~16 special-teams snaps are in
that file for all 17 of his games. We kept the one week he happened to run.

**This is `published-first` rung 5 for the third time this week** (after the nflverse rollup
and `team_weeks`): presence is published, and we are inferring it from stats.

### Two adjacent facts found in the same dig

- **Playoff rows are unmarked.** Weeks 19–22 sit in `player_game_logs` with no flag. They drop
  out of `games_played` *only* because they do not intersect `team_weeks` — there is no
  explicit filter. The correctness is incidental. Anything that counts rows directly gets 20
  games for Stafford. Mark them.
- **Snap counts filter `game_type == "REG"`**, so a season's regular rows carry `off_snaps`
  and its playoff rows do not. The two halves of a season have different shapes.

### Stafford was a false alarm, and that mattered

Micah reported "matthew stafford has weeks 3-18." He actually has weeks 1–7, 9–18 (week 8 =
Rams bye) plus 19/20/21, and the API returns `games_played 17, games_missed 0, sample full` —
**correct**. Checking it is what exposed the playoff rows and, by contrast, made the kicker
pattern obvious. The strip cells are right; what is missing is any on-screen indication of
*which week* each cell is (only a hover `title`).

---

## 2. Everything the mock draft still needs

### 2a. Blocking — it is not a fantasy draft without these

**D/ST does not exist.** No entity, no ADP, no roster slot. Investigated this session and it
is **smaller than it sounds** — every stat D/ST scoring needs is published:

```
stats_team_week_2025.parquet   570 rows, 133 cols   (HTTP 200, verified)
https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_2025.parquet
  def_sacks · def_interceptions · def_tds · def_safeties
  fumble_recovery_opp · special_teams_tds · pt_return_tds
```

Points allowed needs no derivation either — `team_game_results.score_against` already holds
it, ESPN-sourced. So the stat line is entirely published; **no pbp reconstruction** (our
`nfl_pbp` has 7 usable columns and none are sack/interception/fumble, so it was never an
option anyway).

What is actually missing is not stats:
1. **An entity** — 32 team defenses as draftable rows. ⚠️ **Check what ESPN publishes as the
   position code before inventing one.** We already have two columns poisoned by guessed
   vocabularies (§3); a third would be self-inflicted.
2. **ADP** — `nfl_adp` has zero D/ST rows; every row joins to a player position. ESPN
   publishes D/ST fantasy ADP. Ingest question, not availability question.

**Kicker data.** 1 row / 42 kickers, per §1. Until it lands, Aubrey renders a false
`1/17 — missed 16`. Roadmap **R5** (`--all-positions` for K/IDP) is the open decision;
Micah's "we're missing data" is effectively the call.

### 2b. Familiar UX — researched this session, and this is why it feels barebones

Micah: *"we have to have familiar ux. that's important or people will be offput."*

| genre standard | ours |
|---|---|
| **Draft board grid** — teams × rounds, every pick in a cell | absent |
| **Queue** — build a list, reorder, autopick pulls from it, drafted auto-remove | absent |
| **Position / team / bye filters** | absent |
| **"Your next pick" counter** | absent |
| **Selected-player panel + explicit Draft button** | whole `<tr>` is the click target |
| **Clock** | absent (SPEC §9.2 left it open, shipped without) |

Ours is a sorted list with a click handler; theirs is a room. Six load-bearing objects do not
exist.

**⛔ Familiar structure does NOT override SPEC §6.2.** Every one of those surfaces wants
colour — your turn, your picks, positional runs on the grid — and **amber is spoken for**
(it marks absence). Incumbents colour-code grid cells by position; ours uses position chips
and two-tone fills. Familiar *structure*, our restraint on colour.

### 2c. Micah's own product notes, verbatim intent

- **Draft button on the row**, not the whole row as the click target. Clicking the row opens
  an **overlay** with player detail: projections for this year, last year's game log, etc.
- **"i was looking at a WR and i was like damn i have no idea who his QB is."** The row shows
  a team code and nothing else. Who throws to him is the actual draft question, and we have
  the data — the QB's own availability row is right there. Belongs on the overlay, arguably a
  compact form on the row. Puka Nacua's 16/17 only means something next to Stafford's 17/17.
- **News = nflverse `injuries`.** pt.4 deferred it to in-season; Micah reopened it ("we can go
  ahead and do the news thing too"). **`import_injuries` is available in the installed
  library** — verified. Factual layer only (official injury report, republished 2009–2025).
  The prose blurbs are the licensed Rotowire/Sportradar half Micah said not to trust.
- **Entry point placement was his call and it is better than the spec's** — above transactions
  on the camp tab. His follow-on idea, not yet built: **once a draft is in progress the card
  becomes the resume state** ("Resume your mock draft — Round 4, pick 41") instead of the
  start pitch. The draft keeps its own route; it is a full-screen task and camp is a skim
  surface.

### 2d. Resume and share — both dead, for two different reasons

1. **The page ignores `?id=`.** `pages/mock-draft.tsx:70-79` fetches the draft, builds the
   engine player list from the response, then **discards it** behind a
   `// We need the full pool to resolve player names... complex.` comment — and returns early
   when `status === 'complete'`, i.e. every draft worth sharing. Verified in chromium: the URL
   renders the Mock Draft Pool.
2. **The read is device-scoped.** `GET /api/nfl/mock-draft/{id}` requires `X-Device-Id` and
   404s unless it matches the creating device (`nfl_mock_draft.py:355`). A shared link could
   **never** resolve for a recipient, and the client swallows it with `.catch(() => {})`.

**Shipped this session:** the auto-printed dead URL is gone. In its place, per Micah, a
**disabled "Get a link" button reading "Coming soon"** — a link generated on request, once
there is something to generate. He confirmed it looks right.

Fixes, different sizes:
- **Resume** — client-only, ~30 lines. Wait for the pool, rebuild engine state from
  `picks` + `seat` + `seed` (all persisted), set phase, delete the `status === 'complete'`
  early return.
- **Share** — needs a server change: a public read for **completed** drafts only. Precedent
  already in the same file (`nfl_mock_draft.py:133` marks the pool endpoint public read-only).
  In-progress stays device-scoped. **Or** gate it behind accounts — R9 already names the mock
  draft as the reason to sign up, and "sign up to keep your draft" lands hardest right after
  someone spent fifteen picks. **Product call, not technical — Micah's.**

### 2e. Smaller, all measured

- **`DraftRoom.tsx:111` hides the scrollbar** (`[scrollbar-width:none]`) on a 292-row list
  inside `max-h-[calc(100vh-300px)]`, on a page that does not itself scroll. It looks like the
  pool has 10 players. One-line fix, worst thing on the screen.
- **Roster panel spends 7 of 15 rows on empty bench slots**, pushing the pick ledger below the
  fold. Collapse the bench until it fills.
- **`DraftRoom.tsx:255` hardcodes `TEAM_GAMES - games_played`** instead of using the API's
  `games_missed`. Agrees today; will not survive roadmap **B1** (mid-season team change
  doubles the denominator).

---

## 3. The position column has the team-code disease (new, and it generalises §pt.9)

`PK` is **ESPN's** code for placekicker — confirmed from the live roster endpoint, not
inferred:

```
DAL roster position codes: C, CB, DT, FB, G, LB, LS, OT, P, PK, QB, RB, S, TE, WR
  PK -> Brandon Aubrey     P -> Bryan Anger (punter)     LS -> Trent Sieg
```

`PK` is placekicker; the punter is plain `P`. They are distinct.

| position | rows | active | espn_id |
|---|---|---|---|
| `PK` | 42 | **42** | 42 of 42 |
| `K` | 336 | **0** | 205 of 336 |

**Identical shape to `players.team`** — ESPN vocabulary on actives, the older ingest's on
inactives. `position='K' AND active=1` silently returns **nothing** (SPEC-slice-D §1 caught
this). Same for `OLB`/`FS`/`NT`/`ILB`/`MLB`/`SAF`/`OL`, all 0 active.

➡️ **`backend/team_codes.py` (pt.9 §2, still unwritten) should grow a `positions` sibling.**
Same module, same raising `normalize()`, same principle: the vocabulary is published, never
inferred.

---

## 4. What shipped this session

**v0.6.11 — tagged `c05a7b9`, pushed.** Cut via `scripts/release.sh 0.6.11`.

Micah chose v0.6.11 over v0.7.0 explicitly, so **v0.7.0 still means A + D + R4** and R4 is
still unstarted. I flagged that a feature landing under a patch number conflicts with
`feedback_feature_releases_only`; he chose it with that information. Do not relitigate.

| commit | what |
|---|---|
| `2be3f4e` | entry point card on the NFL camp tab, above transactions |
| `c8469e7` | merge slice D into dev |
| `c05a7b9` | chore(release): v0.6.11 |
| `722c932` | changelog correction — see below |
| `04611d6` | share link → disabled "Get a link / Coming soon" |
| `664b8f7` | merge that fix into dev |

**§7.6 passed — the first time anyone actually walked it.** Drove a full draft in chromium:

```
180 picks · 180 distinct players · pick_no 1–180 · 15 per team × 12 teams
zero console errors, zero page errors, results screen renders
Jeremiyah Love → "Rookie — no NFL sample"   Will Reichard (PK, 0 rows) → "Kicker games not tracked"
```

**Micah's decision on the Aubrey label: tag as-is, do not patch the display.** The changelog
carries a **Known gaps** section naming it instead. The honest fix is ingesting kicking data,
not relabelling a real player.

---

## 5. The lesson — I put a false claim in a release note

The v0.6.11 changelog said *"Every draft has a durable URL so it can be shared or resumed."*
I wrote that from **SPEC-slice-D §6.4** instead of from the running page. Micah asked "do we
save the link at the end?", I checked, and it was false in two independent ways (§2d).

Corrected on `dev` in `722c932`; **the tag still contains the wrong line** — a release note is
not worth retagging over, but the repo is right going forward and the gap is now listed.

pt.7's lesson was *a green test suite is a claim*. pt.8's was *the claim and the evidence can
both be present and still not match*. This one is the same failure aimed at myself:
**a changelog bullet is a claim too, and a spec is not evidence that a thing works.** Every
line in a release note has to be checked against the running product, the same as an agent's
build report.

The second lesson is Micah's, twice: **he rejected my game-log rewrite (§1) and my refusal to
add the share button, and he was right both times.** Push back with reasons — but when the
reason is "I think the simpler design is cleaner," that is a preference, not a finding.

---

## 6. State

- **`dev` = `664b8f7`, pushed, clean.** Tag **v0.6.11** at `c05a7b9`.
- `feat/slice-D-mock-draft` = `04611d6` — **checked out in the main repo, what `:3096` serves.**
  Fully merged into dev; nothing stranded.
- `fix/team-vocabulary` = `fc06a14` in worktree `/root/lp-team-vocab` — **pt.9's work, still
  the queued job.** `migrate_nfl_team_vocabulary.py` does **not run**: it imports
  `team_codes.py`, which nobody has written. Scope inside it is measured and correct.
- Other worktrees: `/root/lp-nfl-allday` `825d116`, `/root/lp-nfl-usage` `0ced86f`,
  `/root/lp-slice-D-pass-2` `fadaf3a` (its `:8098` backend still up — tear down when done).
- **Prod is v0.6.7.** R6 (deploy) still behind v0.7.0.
- DB backups: `/root/picks.dev.PRE-ESPN-2026-07-27.db`, `/root/picks.dev.PRE-VOCAB-2026-07-27.db`.
  **No DB writes this session** beyond mock drafts created by the browser verification runs.
- Live DB is `/root/legendarypicks/backend/data/picks.dev.db`. ⚠️ The `picks.dev.db` in the
  repo root is a **0-byte decoy** — querying it returns "no such table."
- Ports: `:3096` frontend, `:8096` backend (reload), `:8098` worktree backend. Tunnel
  `https://someone-decorative-wearing-produce.trycloudflare.com` → 3096, cloudflared pid
  3928058. **Don't touch cloudflared.** `node_modules` = 538.

---

## 7. Suggested order

Micah's framing: the mock draft is a PoC, and defense is what makes it not shippable.

1. **D/ST** — entity + ADP + roster slot. File confirmed published (§2a). Unblocks "is this a
   real fantasy draft."
2. **`nfl_snap_counts` own table** → availability from presence (§1). Foundation under the
   pool, the results screen and the overlay. Kicking stats ride along; closes Aubrey.
3. **Mark playoff rows** in `player_game_logs` (§1). Cheap, removes an incidental correctness.
4. **The room, familiar-UX pass** — position filter, queue, next-pick counter, Draft button on
   the row, restore the scrollbar. Fold **resume** in here (§2d).
5. **The board grid** (§2b) — its own slice, and the sharpest test of familiar-structure vs.
   §6.2.
6. **Player overlay** (§2c) — 2025 log, projections, the WR's QB.
7. **`injuries`** — the news layer, factual half only.

Carried from pt.9, not started: **`backend/team_codes.py`** (+ the `positions` sibling from
§3), the NFL vocabulary migration gated on a byte-identical draft board, **deleting the
`team_weeks` derivation**, the other leagues, and **R4**.
