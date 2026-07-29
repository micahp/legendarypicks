# TASK — mock draft room: tabbed shell, one action button, honest columns

Written 2026-07-28 as **SPEC ONLY — do not implement**, revised the same day against nine
screenshots of the ESPN iOS draft room (`/root/.hermes/cache/images/img_*.png`).

Status: **BUILT** on `feat/draft-room-espn-shell`, 2026-07-29. Everything below is kept
exactly as it was written; **§11 at the end** records what shipped and the four places the
build had to diverge from it.

**Sequencing, settled:** land `codex/nfl-release-readiness` into `dev` **first**, then this.
It touches `components/Leagues/NflDraftRoom.tsx` and `types.ts`; merging it underneath a
half-rebuilt draft room is the bad order. Injury-designation enrichment comes after both.
Surface: `/mock-draft` (Pages Router, `pages/mock-draft.tsx`).
Input data: **done.** Codex's `codex/nfl-release-readiness` hardened the pipeline; this task
changes no backend, adds no stat, derives no value.

---

## 0. What the screenshots actually show

Recorded from the ESPN app, 2026 draft, 12-team, user drafting from seat 12.

**Bottom tab bar** — `Players | Queue | Board | Rosters`. Active tab green. **Queue carries
a numeric badge** (9, then 8 after a pick). Note ESPN's is "Rosters" *plural* — it holds
every team, not just yours.

**Header, three distinct states:**
| state | header | sub-bar |
|---|---|---|
| pre-draft | `Draft starts in: 00:57` | `You pick 12th` |
| someone else on the clock | *their* team name + countdown | `Last Pick: Alejandro's Astounding Team pick Christian McCaffrey, RB, SF` |
| **you on the clock** | **entire header turns green**, `You are on the clock!` + countdown | `Your auto pick would be Ashton Jeanty, RB, LV` |

**Round strip** — horizontally scrolling pick cards: `Pick 12 (12)` (pick-in-round and
overall), team logo, team name, an `AUTO` flag on auto-drafting teams. Current pick is
filled green; the user's upcoming pick is green-outlined. The strip scrolls *through* the
round boundary — `Round 1 · Pick 12 (12) | Round 2 · Pick 1 (13) …`.

**Filter bar** — two dropdowns (`All Pos ▾`, `Proj Pts ▾`), `Reset`, search icon. Dropdowns,
not pills.

**Columns** — `RK | PLAYER | BYE | ADP | PROJ | [button]`. Player cell is a blue name over
`Team` + a colour-coded position chip (RB orange, WR cyan, TE teal), with a red injury
letter after it (`Q`, `O`).

**One action button per row, always** — `QUEUE` in white outline; the moment you are on the
clock **every** row's button becomes `DRAFT` in blue outline. ESPN's own walkthrough card
states it: *"When it's your turn to draft, the QUEUE button will be replaced with DRAFT
buttons that you will tap to make your pick."* This is exactly what Micah specified.

**`YOUR PICK (R1,P12)` / `YOUR PICK (R2,P1)` divider rows**, drawn as green rules *inside*
the player list at the point where the user's next picks fall. The single best idea on the
screen: it converts a list into "who will still be here when I'm up".

**Player card** — one `Queue` button, three tiles (`POS RANK` / `ADP` / `%ROST`), tabs
`Overview · News · Stats · Odds · Game Log · Projections`, and a SEASON STATS table whose
rows are `PROJ 2026` above `2025` across REC/TAR/YDS/TD/FPTS.

### The finding that changes the brief

**ESPN's list is NOT sorted by projected points.** It is ordered by `RK`, which is neither
projection order nor ADP order. Measured off the WR-filtered screenshot:

| RK | player | ADP | PROJ |
|---|---|---|---|
| 9 | CeeDee Lamb | 10.5 | 190.68 |
| 11 | Justin Jefferson | 11.9 | 182.78 |
| 13 | Drake London | 19.6 | 167.75 |
| 14 | Rashee Rice | 22.1 | **173.64** ← rises |
| 25 | Nico Collins | 27.7 | 163.02 |
| 26 | A.J. Brown | **26.1** ← falls | 162.39 |

RK ascends monotonically; PROJ and ADP both break. So `RK` is ESPN's own proprietary board
rank, `PROJ` is a displayed column, and the `Proj Pts ▾` pill selects *which stat the column
shows*, not the sort. Micah's "sorted by fantasy points" describes the intent — a board
ordered by value rather than by nothing — but the pane on the right does not implement it
that way, and the kicker problem he trailed off on is precisely why.

**We have neither of ESPN's two ordering inputs.** No proprietary rank, and no 2026
projection — only 2025 actuals and published xFP. See §5.

---

## 1. The rule this rebuild must not break

Matching ESPN's *shell* is the task. Matching ESPN's *content* would delete the only column
that is ours: **availability**. ESPN shows nothing about games missed; the accent-marks-absence
board is the product thesis (`.claude/skills/honest-data-ui`, §5). The availability strip
stays in the row. If a column has to go to make width, it is not that one.

## 2. D/ST (settled)

`lib/nfl/positionLabel.ts` gains `DEF → 'D/ST'`; it already maps `PK → 'K'`. Stored codes
stay canonical in `lib/mockDraft/engine.ts`, the API `position=` param, and roster-slot
construction.

Hand edits beyond the helper: the roster slot label (`addSlot('DEF', 'DEF', true)` in
`DraftRoom.tsx` and `ResultsScreen.tsx` — first arg is the display string), and the
positional rank, which would otherwise render `D/ST1`. **Suppress the positional rank for
D/ST and K** — nobody says "D/ST1" out loud, and ESPN shows no positional rank for them
either.

## 3. Tabs (settled)

`Players | Queue (n) | Board | Roster`. Tabs at every width — one implementation, one set
of gates, and the board wants the room.

- Queue tab carries a **count badge**, per ESPN.
- **Persistent above the tabs, never inside one:** the status header, in the three states of
  §0, including the green on-the-clock treatment and the `Your auto pick would be …` line.
  We can populate that line exactly — `pages/mock-draft.tsx:283` already computes it
  (top queued player, else `botPick`). Cheap, and it is the difference between a clock that
  threatens you and one that informs you.
- The `Last Pick: …` ticker replaces the Pick Ledger's role in the persistent chrome. Full
  pick history moves into the **Board** tab under the grid.
- **Round strip** (§0) sits under the status header, above the tabs.
- `role="tablist"`/`tab`/`tabpanel`, arrow-key nav, `aria-selected`. Tab state is local, not
  in the URL — the clock is running.

**Settled:** the fourth tab is **Rosters** — all teams, yours first — matching ESPN. The
engine already holds every pick, and seeing opponents' positional needs is the draft skill
the tab exists to serve.

## 4. One action button per row (settled)

| row state | on the clock | not on the clock |
|---|---|---|
| available, not queued | **Draft** | **Queue** |
| available, already queued | **Draft** | **Queued** — click removes |
| already drafted | none | none |

- Exactly one button, always. `+Q` / `−Q` are deleted from the codebase.
- Fixed button width so the column does not reflow when the turn flips.
- Draft renders in the accent outline, Queue in neutral outline — ESPN's blue/white split,
  in our vocabulary.
- `aria-label` names the player: `Draft Bijan Robinson`.
- Draft is absent (not disabled) once `draftState.completed`.
- On the clock, a queued player shows only **Draft**; removal happens in the Queue tab.
- Empty-queue copy loses the dead symbol. Current: `Add players with +Q`. Replace with
  `No players queued — use Queue on any player to line up your next picks.`
- `PlayerDetailOverlay` follows the same rule: one button, matching ESPN's single `Queue`.

## 4b. Position filter order (settled)

The mock draft's position filter currently reads **All · D/ST · K · QB · RB · TE · WR** —
defense and kicker before the quarterback. It is derived, not authored:

```ts
// DraftRoom.tsx:77
const posOptions = ['ALL', ...Array.from(new Set(pool.map(p => p.position).sort()))]
```

`.sort()` on the raw stored codes gives `DEF, PK, QB, RB, TE, WR` alphabetically, and the
display map (`DEF → D/ST`, `PK → K`) then hides *why* the order is wrong while leaving it
wrong. A drafter reads this control left to right in draft order; it must be authored, never
derived.

**Canonical order, one constant, both surfaces:**

    All · QB · RB · WR · TE · FLEX · K · D/ST

Skill positions in the order they come off the board, FLEX where it sits in a lineup, then
the two positions nobody drafts before round 13 — last. The camp board already hardcodes
almost exactly this (`components/Leagues/hooks/useNflDraftBoard.ts:5`, which also carries
`FB`); lift it into `lib/nfl/positionLabel.ts` alongside the display map so the order and the
labels live together, and have both surfaces import it. Positions the pool does not contain
are omitted, but the surviving ones keep this order — never re-sorted.

The same rule applies to the sort dropdown's own options: authored order, default first
(`ADP · 2025 Pts/G · Expected Pts/G · Availability · Bye`), not alphabetical.

## 5. Columns and ordering — where we cannot copy ESPN

ESPN's row is `RK | PLAYER | BYE | ADP | PROJ`. Ours maps as:

| ESPN | ours | note |
|---|---|---|
| RK | `#` | position in the ADP-ordered board — it is ADP's ranking, not ours, and the header must not imply otherwise |
| PLAYER | same | name, team, position chip. Injury letter **omitted for this tag** — we carry no published designation. The enrichment lands after codex's branch and this frontend work are both in, not before |
| BYE | same | already wired to the drafted season |
| ADP | same | |
| PROJ | **`2025 PTS/G`** | we have no 2026 projection; labelling an actual `PROJ` is the exact ban in the doctrine |
| — | **AVAILABLE** | ours, kept (§1) |
| %ROST | optional | `percent_owned` already ships on `PoolPlayer` |

**Ordering.** Default stays ADP-ascending — the published consensus, and the closest honest
analogue to ESPN's RK. A sort dropdown (ESPN's second pill) offers: `ADP · 2025 Pts/G ·
Expected Pts/G (xFP) · Availability · Bye`.

Sorting by `2025 Pts/G` under `All Pos` **will float kickers above most WR2s**, because the
column resolves to three different series (`HeadlineStat`, `DraftRoom.tsx:824`): PPR/game
for skill positions (5–22), kicking points/game for K (7–9), D/ST points/game (4–9). That is
not a sort bug — it is a true property of last season's actuals, and it is why ESPN sorts by
a projection-and-scarcity rank instead. We will not invent a projection to hide it. We
therefore: keep the position chip on every row so a kicker is visibly a kicker; put the
season in the header (`2025 Pts/G`, read from `reference_season`, never a literal); and sort
nulls last, always, never coerced to 0.

**`YOUR PICK (Rn,Pn)` dividers — build these.** Insert a rule into the ADP-ordered list at
each point where ADP crosses one of the user's upcoming pick numbers. Derived entirely from
`userNextPick` + ADP, so it is honest as long as it is labelled as an ADP expectation and not
a promise. It is the highest-value idea in the screenshots and it costs us one `useMemo`.

## 6. Files

Change:
- `lib/nfl/positionLabel.ts` — add `DEF → D/ST`; the rank-suffix rule.
- `pages/mock-draft.tsx` — queue handlers unchanged; surfaces the would-be autopick.
- `components/MockDraft/DraftRoom.tsx` — **1,053 lines and about to grow.** Split as part of
  this work: `DraftHeader.tsx` (three states + round strip), `DraftTabs.tsx`,
  `PlayersTab.tsx`, `QueueTab.tsx`, `BoardTab.tsx`, `RosterTab.tsx`,
  `PlayerActionButton.tsx`. `DraftBoardGrid`, `buildRosterSlots`, `HeadlineStat`,
  `ExpectedPts`, `noSampleLabel` move with their tabs.
- `components/MockDraft/ResultsScreen.tsx` — imports `noSampleLabel` from `DraftRoom`;
  follow it to its new home.
- `components/Leagues/PlayerDetailOverlay.tsx` — one action button.

Do not touch: `lib/mockDraft/engine.ts` position codes, any backend file, or
`components/Leagues/NflDraftRoom.tsx` logic — codex's branch has a pending change there.

## 7. Gates — written before the code

Per `feedback_fix_gates_before_the_code`, committed first so weakening shows in git. All
drive a real browser (`scripts/render-gate.js` pattern). Evidence unavailable = FAIL.

- **REG-tabs** — four tabs by accessible name; each mounts its panel and unmounts the
  others; the status header stays visible on all four; zero console errors per switch.
- **REG-one-button** — over 20 available rows the action cell holds **exactly one** button.
  Off the clock every label is `Queue`/`Queued`; on the clock every label is `Draft`. The
  strings `+Q` and `−Q` appear **zero** times in the DOM.
- **REG-labels** — zero standalone `PK`, zero standalone `DEF` in rendered text; `K` and
  `D/ST` both present. (The `PK` half is already true as of `8e6e7fc`.)
- **REG-position-order** — the position filter's rendered labels, read left to right, are
  exactly `All, QB, RB, WR, TE, FLEX, K, D/ST` (minus any position absent from the pool).
  Asserted on the **rendered text**, not on the source array: the bug shipped because the
  array looked sorted and the row looked wrong, and only one of those was being read.
- **REG-no-projection** — the string `PROJ` does not appear as a column header, and no
  header renders a season later than `reference_season`. This gate exists because the
  screenshots make copying ESPN's header the obvious mistake.
- **REG-sort** — each sort reorders the table; first value ≥ last for a descending sort;
  valueless rows land last and render `—`, never `0.0`.
- **REG-clock** — the countdown runs and still autopicks at 0:00 while a non-Players tab is
  open, and the clock effect does not remount on tab switch. A deadlocked clock has shipped
  on this surface once already.
- **REG-your-pick-divider** — with a seat-12 draft, a divider labelled `YOUR PICK (R1,P12)`
  exists in the list and sits between the rows whose ADP brackets pick 12.

## 8. Non-goals

No backend change. No new statistic. **No 2026 projection.** No scoring-settings UI. No
injury designations until a published source is wired. No change to bot behaviour or snake
order.


---

## 11. What shipped — 2026-07-29, `feat/draft-room-espn-shell`

Built off `dev` at `8e6e7fc`. Gates first (`4986574`), then the code. Verified in a real
browser: `scripts/draft-shell-gate.js` 9/9, `scripts/render-gate.js`, and
`scripts/e2e-mock-draft.js` all green; jest 85/87 (the two failures are the pre-existing
`WCContext.test.tsx` pair); tsc unchanged at 21 pre-existing errors, none in these files.

### The sequencing precondition was not needed

§0 said to land `codex/nfl-release-readiness` first because it touches
`components/Leagues/NflDraftRoom.tsx` and `components/Leagues/types.ts`. Measured: those
are the *only* two frontend files it touches, and neither is edited here. `useNflDraftBoard.ts`
is (§4b asked for it) and codex does not touch it. The branches are disjoint; codex can land
in either order.

### Four places the build diverged, and why

1. **The three header states are two.** §0's middle state — another manager on the clock,
   with their countdown — does not exist in this engine. `commitPick` runs every bot pick
   between your turns in one synchronous loop, so it is your turn from the moment the room
   opens until the draft ends. The header states what is true and keeps the `Last pick`
   line, which is the part of ESPN's middle state that carries information. There is also
   no pre-draft countdown, because there is no lobby: the pool screen is the pre-draft
   state and it has a button, not a timer.

2. **The player card keeps two buttons.** §4's last clause said the card follows the
   one-button rule. Applied together with (1), that leaves *nowhere at all to queue from* —
   the row is always Draft, so the card would be too, and the queue is what the 30-second
   clock drafts out of. One button on the row, both on the card.

3. **Draft renders neutral, not accent.** §4 asked for Draft in the accent outline. The
   accent marks absence and nothing else (`honest-data-ui` §5); spending it on "it is your
   turn" would put achievement in the one colour reserved for the games a player missed.
   Draft and Queue are separated by weight and fill instead.

4. **The row's Draft button now renders against `userPicking`, not `userTurn`.** Not in the
   spec at all — found while writing REG-one-button. `draftState` still says it is your turn
   through the whole window in which the client has already taken your pick and is running
   the bots, so a second click in that window applied a second pick against a stale state.
   That window is the only honest "not your turn" the engine has, and it now reads Queue.

### Found on the way, not fixed here

- **`Rashid Shaheed` renders `18/17`.** Traded NO→SEA mid-2025; he appeared in 18 games
  because the two teams' byes differ, while the denominator is his *current* team's game
  count. One row in 300, `games_missed` = 0, and the new Availability sort puts it at the
  top of the board. The number is arguably true and the fraction is certainly incoherent —
  availability needs a denominator that follows the player, not the roster. Backend, out of
  this task's file scope.
- **Both existing browser gates were red on `dev` before this branch**, neither for a
  product reason. Fixed in `f63862c`, with the diagnosis in the message.
- **`WCContext.test.tsx` has two failures** and `REG-jest` does not run it — pt.14's B16,
  still open.
- Queueing now costs two clicks (row → card → Queue). Acceptable, not good. The obvious fix
  is queueing from the pre-draft pool screen, which is where a queue actually gets built.
