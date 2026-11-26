# TASK — the mock-draft pool leads with the two numbers a drafter acts on

Branch `dev`, worktree `/root/legendarypicks`. Frontend `http://127.0.0.1:3096`,
backend `http://127.0.0.1:8096`. Do not restart either server; they are managed
outside this session.

## Why

`6ee27fc` removed `Exp PPR/G` from the pool and left `columns.tsx`'s
`ExpectedPts` + `EXPECTED_PTS_HEADER` exported with zero callers. That was
wrong and it is being reversed: opportunity (`Exp PPR/G`) and outcome (`Proj`)
only mean something together — a back who scored 21.8 on 19.3 of opportunity
beat his usage, and one column alone cannot tell you that. `columns.tsx`'s own
comment already says both ship on every mock-draft surface.

`REG-render` has been red on exactly this since `6ee27fc`. **The gate is
correct and pre-dates the work — do not edit `scripts/render-gate.js`'s
existing `xfpPool` / `xfpRoom` checks to agree with anything.** You add new
assertions below them; you do not touch those two.

Four changes, all on the same two tables:

1. **`Exp PPR/G` comes back**, immediately right of `Proj`.
2. **`Proj` becomes the first numeric column** — directly after `Player`, ahead
   of `Bye` and `ADP`. Order: `# · Player · Proj · Exp PPR/G · Bye · ADP ·
   Available` (the in-draft table keeps its trailing action column).
3. **Player names never wrap.** One line, always, on both tables.
4. **The subtitle under the name never wraps, and stops repeating itself.**
   It currently reads `BUF · RB · RB1`. `RB` and `RB1` are the same fact twice.

## Files you may touch — and only these

- `components/MockDraft/PoolList.tsx` (pre-draft pool, virtualized)
- `components/MockDraft/PlayersTab.tsx` (in-draft pool)
- `components/MockDraft/columns.tsx` (the shared cells for both)
- `scripts/render-gate.js` (**append** new checks only)
- `components/MockDraft/PlayersTab.test.tsx`
- a new `components/MockDraft/columns.test.tsx` if you want unit coverage

**Do not touch anything else.** Specifically forbidden:

- `lib/nfl/positionLabel.ts` — shared with the player overlay, the research
  board and the roster tabs. Its rules are already right (see below). Changing
  it changes three surfaces nobody asked you to change.
- `components/Leagues/**`, `pages/**`, `backend/**`, `verify-gates.sh`
- any host config: `/etc`, systemd units, cron, nginx, `package.json`,
  `next.config.js`. A worktree does not isolate these.
- the two existing `Exp PPR/G` checks in `render-gate.js`

## Gates first — write these before you touch a component

Per repo practice the expected values are committed **before** the code, so a
later weakening shows up in `git diff`. Commit the failing gate first, then the
fix, as two commits.

Append to `scripts/render-gate.js`, on both `/mock-draft` (pre-draft pool) and
the in-draft Players tab:

- **Column order.** From `table thead th`: index of `Proj` is exactly one less
  than index of `Exp PPR/G`, and both are less than the index of `Bye` and of
  `ADP`. Assert on the header text, not on ordinals like `nth(3)` — `REG-render`
  has already been broken twice by ordinal drift and no longer counts positions.
- **No wrapped name.** For every rendered row, the name element's rendered
  height is within one line-height (`<= 1.4 * lineHeight`), and
  `scrollWidth <= clientWidth + 1` so it is not silently ellipsised either.
  Report the offending name in the failure text.
- **No wrapped subtitle.** Same two measurements on the `TEAM · POS` line.
- **No sideways scroll.** The pool's scroll container satisfies
  `scrollWidth <= clientWidth + 1`. Adding a column must not buy itself width
  by pushing the table wider than the two-thirds grid column it sits in.
- **No repeated position.** No subtitle matches `/\b(QB|RB|WR|TE|FB)\b.*\b\1\d/`
  — i.e. never `RB · RB1`.

These are measurements, not opinions. If one fails, the layout is wrong; fix
the layout, not the number.

## The four changes

**1 + 2 — the columns.** `ExpectedPts` and `EXPECTED_PTS_HEADER` already exist
in `columns.tsx` and already render `—` for null (K and D/ST have no xFP series
at all — that is correct, not a gap to fill). Import and render them; do not
rewrite them. Header sub-labels follow the existing `Proj / 2026 PPR` pattern,
and `expectedPtsTitle(referenceSeason)` is the tooltip — the season comes from
the payload, never from a literal year. `PlayersTab.tsx`'s `COLUMNS = 7` is the
divider row's `colSpan`; it becomes 8, or the "your pick" divider stops
spanning the table.

**3 — names.** `whitespace-nowrap` on the name and on the subtitle. The width
has to come from somewhere: take it from `Bye` and `ADP`, which are three or
four characters in a `w-12`/`w-16` column, **never** from the Player column. If
the longest name in the pool still does not fit at 1280px, narrow the number
columns further. The gate above is what tells you whether you have succeeded;
do not eyeball it.

**4 — the subtitle.** `PlayerDetailOverlay.tsx:185` already has the rule this
needs and it has been live for weeks:

```
showsPositionalRank(position) ? positionRankLabel(position, posRank) : positionLabel(position)
```

The rank label already contains the position, so when a rank exists you print
`RB1` and nothing else; when it does not (K and D/ST, which have no meaningful
positional rank) you print `K` or `D/ST`. Both pools currently print the
position **and** the rank. Adopt the overlay's expression — do not invent a
third variant, and do not change the helper.

Both tables build this cell from near-identical JSX today. Lift it into
`columns.tsx` as one exported cell taking `{ name, team, position, posRank,
injuryStatus }` and call it from both. That file exists precisely because two
private copies of the same cell start disagreeing about a player — which is how
the roster builder ended up existing twice.

## Definition of done

1. `npx tsc --noEmit -p tsconfig.json` — no new errors in the touched files.
   (12 project-wide errors are standing: `@onflow/fcl` is not installed, plus
   the known TS2802 in `pages/scores.tsx`. Neither is yours.)
2. `npx jest components/MockDraft` green.
3. `bash verify-gates.sh REG-render` — its two `Exp PPR/G` checks must go from
   FAIL to PASS, and your new checks must pass.

   **The gate is currently red on a third, unrelated thing you must not touch:**
   `strict mode violation: locator('[role="dialog"]').locator('h2') resolved to
   2 elements`. That is `components/Leagues/StatRankCard.tsx` rendering an `h2`
   for a card nested inside the overlay whose title is already an `h2`. It is
   being fixed in parallel, outside your files. If REG-render still reports
   only that violation and no `Exp PPR/G` failure, your half is done — say so
   and quote the line. Do not "fix" it by editing the gate.
4. `bash verify-gates.sh OVL-width` still 28 passed / 0 failed — you must not
   regress the overlay.
5. A real browser at 1280px and at 390px on `/mock-draft`, and again after
   clicking Start Draft → Players tab: zero console errors, no wrapped name, no
   sideways scroll. Paste the measured numbers, not a description of them.
6. Separate commits per slice: (a) the gate, (b) the columns + order, (c) the
   name/subtitle cell. Do not push.

Report the measured values. "Looks right" is not a result.
