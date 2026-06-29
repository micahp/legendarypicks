# DESIGN — Game-detail tabs: Box Score, Play-by-Play, Game Info

**Audience:** Frontend executor implementing SPEC-game-detail-tabs.md
**Status:** Design spec — no code, precise enough to implement without guessing
**Design system reference:** AGENTS.md §1–2 + CONTEXT-2026-06-29-esports.md + existing `components/Game/*`

---

## 0. Design token reference (do NOT deviate)

### Color palette
| Token | Tailwind | Hex | Usage |
|-------|----------|-----|-------|
| Page | `bg-ink-900` | `#0f0f11` | Layout owns this — never set in a page/component |
| Card | `bg-zinc-900` | `#18181b` | All tab content sits in this card |
| Card border | `border-zinc-800` | `#27272a` | Every card/panel gets this border |
| Skeleton | `bg-zinc-800` | `#27272a` | Shimmer bars — visible against ink-900 page |
| Primary text | `text-zinc-200` | `#e4e4e7` | Data values, player names |
| Label text | `text-zinc-400` | `#a1a1aa` | Row labels, secondary info |
| Muted text | `text-zinc-500` | `#71717a` | Section eyebrows, empty-state text |
| Subdued text | `text-zinc-600` | `#52525b` | Clock in PbP, tertiary info |
| Emerald | `text-emerald-500` | `#22c55e` | **RESERVED** — goals in soccer PbP only; never on stat tables |
| Amber | `text-amber-400` | `#fbbf24` | TD columns (NFL); multi-hit glow (MLB) |
| Amber muted | `text-amber-500` | `#f59e0b` | HR indicators (MLB) |
| Red (live) | `text-red-500` | `#ef4444` | LIVE badge, red cards (soccer) |
| Yellow (card) | `text-yellow-500` | `#eab308` | Yellow cards (soccer) |
| Blue (home) | `text-blue-400` | `#60a5fa` | Home team marker in PbP |
| Red (away) | `text-red-400` | `#f87171` | Away team marker in PbP |

### Typography
- **All numeric values:** `font-mono tabular-nums` — no exceptions
- **Section headers / eyebrows:** `text-[10px] tracking-widest text-zinc-500 uppercase`
- **Player names:** `text-sm font-medium text-zinc-200`
- **Stat labels:** `text-xs text-zinc-500`
- **Data cells:** `text-sm text-zinc-300` (table body), `text-zinc-200` (totals)
- **Clock / minute:** `font-mono text-xs text-zinc-600`
- **Play text:** `text-sm text-zinc-300 leading-snug`

### Spacing
- **Tab content card:** `bg-zinc-900 border border-zinc-800 rounded-xl p-6` (existing)
- **Inner section gap:** `space-y-4` within a table group, `mb-6` between table groups
- **Row padding:** `py-1.5` (standard), `py-2` (soccer timeline)
- **Horizontal rhythm:** `gap-3` (table columns), `gap-2` (PbP rows)

### Motion
- **Loading:** `animate-pulse` on shimmer bars (subtle breathing, not spin)
- **Tab switch:** no animation (instant swap — tab content is data, not a page transition)
- **Hover (interactive rows):** `hover:bg-zinc-800/50` on PbP rows

---

## 1. MLBBoxScore — batting + pitching tables

### What the user sees
A single card containing two stacked tables. The top table is **Batting** (the primary story in baseball), the bottom table is **Pitching** (secondary). Each table shows away-team players first, then home-team players, with a **team totals** row at the bottom of each team's section. Every numeric cell is mono + tabular. Home runs carry a small ◆ marker. The totals row is visually heavier (bold + border-top).

### Structure
```
┌─ Box Score card (bg-zinc-900, border-zinc-800, rounded-xl, p-6) ─────────┐
│                                                                          │
│  BATTING                    AB   R   H  RBI  HR  BB   K  AVG           │  ← eyebrow
│  ─────────────────────────────────────────────────────────────────────  │  ← border-b border-zinc-700
│                                                                          │
│  NYY (away)                                                              │  ← text-[11px] text-zinc-500 uppercase tracking-wide mb-1
│  Aaron Judge              4   2   3   2    ◆1   0   1  .312             │
│  Juan Soto                5   1   1   1         1   2  .287             │
│  ...                                                                     │
│  Totals                  38   5  11   5     2   3   9                   │  ← font-bold border-t border-zinc-700
│                                                                          │
│  BOS (home)                                                              │
│  Rafael Devers            4   0   1   0         2   1  .274             │
│  ...                                                                     │
│  Totals                  35   3   9   3     0   2   8                   │
│                                                                          │
│  ──  section gap (mb-6)  ──                                             │
│                                                                          │
│  PITCHING                    IP   H  ER  BB   K  ERA                    │  ← eyebrow
│  ─────────────────────────────────────────────────────────────────────  │
│                                                                          │
│  NYY                                                                     │
│  Gerrit Cole (W, 12-4)    7.0   6   2   1   9  2.85                     │
│  Clay Holmes (S, 28)      1.0   1   0   0   2  1.93                     │
│  Totals                   9.0   9   3   2   8                            │
│                                                                          │
│  BOS                                                                     │
│  Brayan Bello (L, 8-7)    5.1   7   4   2   5  4.12                     │
│  ...                                                                     │
│  Totals                   9.0  11   5   3   9                            │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### Column widths (batting)
Use a CSS grid: `grid-cols-[1fr_repeat(7,48px)_56px]` on desktop. The player name column flexes; stat columns are fixed-width for clean vertical scanning.

- **Player:** `1fr`, left-aligned, `text-zinc-200`, truncate with ellipsis
- **AB, R, H, RBI, BB, K:** `48px`, centered, `font-mono tabular-nums text-zinc-300`
- **HR:** `48px`, centered. If HR > 0, render `◆` prefix in `text-amber-500` before the number
- **AVG:** `56px`, centered, `font-mono tabular-nums`. Show 3 decimals (`.312`). If AVG ≥ .300, subtle glow: `text-amber-400/80`

These widths are `min-w-[48px]` (or `56px` for AVG) so the table scrolls horizontally on narrow mobile rather than cramming.

### Column widths (pitching)
- **Player:** `1fr`, left-aligned. Show `Name (decision)` — decision in `text-zinc-500 text-xs`: `(W, 12-4)`, `(L, 8-7)`, `(S, 28)`, `(H, 12)`
- **IP:** `48px`, centered, `font-mono tabular-nums`
- **H, ER, BB, K:** `48px`, centered
- **ERA:** `56px`, centered, `font-mono tabular-nums`. 2 decimals.

### Row styling
- **Player row:** `py-1.5 border-b border-zinc-800/30 text-sm`
- **Team label row:** `text-[11px] text-zinc-500 uppercase tracking-wide pt-3 pb-1` (first team), `pt-4` (after a gap)
- **Totals row:** `py-2 font-bold text-zinc-100 border-t border-zinc-700` — the heavier border visually signals "here's the summary"

### Sport-specific bold choice
The ◆ HR marker and the .300+ AVG glow. Baseball fans *scan* for homers and batting average — these two micro-highlights reward the scanning eye without shouting. The ◆ is baseball's own shape (the diamond). Amber (not emerald) — it's the color of the bat, the dirt, the stitching.

### Loading state (skeleton)
```
┌─ Card shape (bg-zinc-900 border-zinc-800 rounded-xl p-6) ───────────────┐
│                                                                            │
│  border-l-2 border-amber-500/40 pl-3  ← baseball's loading signature      │
│                                                                            │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░  ← h-4 bg-zinc-800 animate-pulse w-1/2       │
│                                                                            │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  ← h-3 bg-zinc-800 animate-pulse w-full  │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  ← h-3 bg-zinc-800 animate-pulse w-full  │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  ...                                   │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  ← 6 bars total (mimics player count)   │
│                                                                            │
│  ── gap (mt-8) ──                                                          │
│                                                                            │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░  ← h-4 bg-zinc-800 animate-pulse w-2/5       │
│                                                                            │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  ← 4 bars for pitching section         │
│  ...                                                                        │
└────────────────────────────────────────────────────────────────────────────┘
```
The `border-l-2 border-amber-500/40` on the loading state is the baseball signature — at 40% opacity it says "baseball stats are loading into this space" without competing with emerald (which is reserved). When content arrives, the border is removed (it's only a loading signal).

### Empty state
When the game is scheduled (not yet started):
```
┌─ Card ────────────────────────────────────────────────────────────────────┐
│                                                                            │
│                    text-zinc-500 text-sm text-center py-12                 │
│                    Box score available at first pitch.                     │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

### Mobile
- Table scrolls horizontally: `overflow-x-auto` on a wrapper div
- Player name column gets `min-w-[120px]` to prevent cramming
- No column dropping — baseball fans need all columns; horizontal scroll is the correct pattern (ESPN does this)

---

## 2. NFLBoxScore — passing / rushing / receiving tables

### What the user sees
Three stat groups side-by-side on desktop: **Passing** (left), **Rushing** (center), **Receiving** (right). Below them, a full-width **Defense** table. Each group has its own column headers. Player rows are compact — the three-column layout means each group is narrow, reinforcing the positional-specialist nature of football. Touchdown numbers glow subtly in amber.

### Structure (desktop)
```
┌─ Box Score card (bg-zinc-900, border-zinc-800, rounded-xl, p-6) ─────────┐
│                                                                          │
│  ┌─── PASSING ───────┐ ┌─── RUSHING ───────┐ ┌─── RECEIVING ─────────┐ │
│  │ C/ATT YDS TD INT  │ │ ATT YDS TD  LNG   │ │ REC YDS TD LNG TGT   │ │
│  │ ─────────────────│ │ ───────────────── │ │ ──────────────────────│ │
│  │                   │ │                   │ │                       │ │
│  │ P. Mahomes        │ │ I. Pacheco        │ │ T. Kelce             │ │
│  │ 24/38 312 3 1     │ │ 18  89  1  24     │ │ 7  92  1  31  9     │ │
│  │                   │ │                   │ │                       │ │
│  │ (away players)    │ │ C. Steele         │ │ R. Rice              │ │
│  │ ...               │ │ 6   22  0  11     │ │ 5  48  0  18  7     │ │
│  │                   │ │                   │ │                       │ │
│  │ ── home ──        │ │ ── home ──        │ │ ── home ──           │ │
│  │ J. Allen          │ │ J. Cook           │ │ S. Diggs             │ │
│  │ 21/35 245 2 2     │ │ 14  62  1  19     │ │ 6  78  1  28  11    │ │
│  │                   │ │                   │ │                       │ │
│  │ Totals            │ │ Totals            │ │ Totals               │ │
│  │ 45/73 557 5 3     │ │ 44 182  2  24     │ │ 18 218  2  31  27   │ │
│  └───────────────────┘ └───────────────────┘ └───────────────────────┘ │
│                                                                          │
│  ──  section gap (mt-6 pt-6 border-t border-zinc-800)  ──              │
│                                                                          │
│  DEFENSE                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │ PLAYER          TACK  SOLO  SACK  INT  FF                           ││
│  │ ─────────────────────────────────────────────────────────────────── ││
│  │ F. Warner        12     8    1.5    0   1                           ││
│  │ N. Bosa           5     3    2.0    0   0                           ││
│  │ ...                                                                  ││
│  │ Totals           68    42    3.0    2   2                           ││
│  └─────────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────────┘
```

### Column grid (each sub-table)
- **Player:** `1fr`, left-aligned, `text-sm text-zinc-200`, truncate
- **Stat columns:** `min-w-[44px]`, centered, `font-mono tabular-nums text-xs text-zinc-300`
- **TD column:** amber treatment — `text-amber-400` (not emerald; amber = pigskin, end zones, yard lines)
- **Header row:** `text-[10px] tracking-widest text-zinc-500 uppercase pb-1.5 border-b border-zinc-700`

### Desktop layout
```
grid grid-cols-[1fr_1fr_1fr] gap-4   ← three equal columns
```
Each column is a self-contained mini-table with its own header + rows.

### Row styling
- **Player row:** `py-1 border-b border-zinc-800/20 text-xs` (denser than MLB — NFL has more players)
- **Team separator:** a subtle divider row with team abbreviation: `text-[10px] text-zinc-500 uppercase tracking-wider py-1.5` centered, with horizontal rules on either side (or just centered text)
- **Totals row:** `py-1.5 font-bold text-zinc-100 border-t border-zinc-700 text-xs`

### Defense table (full-width, below)
- Uses a single grid: `grid-cols-[1fr_repeat(5,56px)]`
- Same styling conventions as the sub-tables above
- Only shown if the data includes defensive stats (ESPN provides them for NFL)

### Sport-specific bold choice
Three-column layout. This is the NFL's visual signature — football is a game of specialists (QB ≠ RB ≠ WR), and the side-by-side columns encode that truth structurally. Also: the TD glow in amber. Every football fan's eye goes straight to the TD column.

### Loading state (skeleton)
```
┌─ Card shape (bg-zinc-900 border-zinc-800 rounded-xl p-6) ───────────────┐
│                                                                            │
│  border-t-2 border-amber-400/40 pt-3  ← NFL's loading signature           │
│                                                                            │
│  ┌──────────────┬──────────────┬──────────────┐                            │
│  │ ▓▓▓▓▓▓▓▓▓▓▓ │ ▓▓▓▓▓▓▓▓▓▓▓ │ ▓▓▓▓▓▓▓▓▓▓▓ │  ← 3 column headers       │
│  │ ▓▓▓▓▓▓▓▓▓▓▓ │ ▓▓▓▓▓▓▓▓▓▓▓ │ ▓▓▓▓▓▓▓▓▓▓▓ │     (h-3, bg-zinc-800)    │
│  │ ▓▓▓▓▓▓▓▓▓▓▓ │ ▓▓▓▓▓▓▓▓▓▓▓ │ ▓▓▓▓▓▓▓▓▓▓▓ │  ← 4-5 player rows each   │
│  │ ▓▓▓▓▓▓▓▓▓▓▓ │ ▓▓▓▓▓▓▓▓▓▓▓ │ ▓▓▓▓▓▓▓▓▓▓▓ │                            │
│  │ ▓▓▓▓▓▓▓▓▓▓▓ │ ▓▓▓▓▓▓▓▓▓▓▓ │ ▓▓▓▓▓▓▓▓▓▓▓ │                            │
│  │ ▓▓▓▓▓▓▓▓▓▓▓ │ ▓▓▓▓▓▓▓▓▓▓▓ │ ▓▓▓▓▓▓▓▓▓▓▓ │                            │
│  └──────────────┴──────────────┴──────────────┘                            │
│                                                                            │
│  ── gap (mt-8) ──                                                          │
│                                                                            │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░  ← h-4 bg-zinc-800 animate-pulse w-1/3      │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  ← defense skeleton (4-5 bars)        │
│  ...                                                                        │
└────────────────────────────────────────────────────────────────────────────┘
```
`border-t-2 border-amber-400/40` — the amber top-border encodes "football" while remaining a subtle loading signal.

### Mobile
- Three columns become a **vertical stack**: Passing → Rushing → Receiving → Defense
- Each section gets a full-width table with `overflow-x-auto` for horizontal scroll within
- Section divider between each: `border-t border-zinc-800 pt-4 mt-4`

---

## 3. SoccerBoxScore (WC) — stat bars + lineups

### What the user sees
Two distinct panels. **Left panel:** a vertical list of team comparison stats, each rendered as a horizontal bar with the away team's value on the left side of a center divider and the home team's value on the right. This is a bar-chart-in-table form — soccer fans are used to seeing possession/shots as visual comparisons, not just numbers. **Right panel:** both team lineups, each showing the formation (e.g. "4-3-3") and list of players with their numbers and positions. Starting XI in bright text, substitutes in muted text.

On mobile, the two panels stack vertically.

### Structure (desktop)
```
┌─ Box Score card (bg-zinc-900, border-zinc-800, rounded-xl, p-6) ─────────┐
│                                                                          │
│  grid grid-cols-[1fr_280px] gap-6  ← left panel flexes, right panel fixed│
│                                                                          │
│  ┌─── LEFT: Team Stats (bar comparison) ──────────────────────────────┐  │
│  │                                                                     │  │
│  │  TEAM STATS                                                         │  │  ← eyebrow
│  │  ────────────────────────────────────────────────────────────────  │  │
│  │                                                                     │  │
│  │  Possession       ████████████ 58% │ 42% ██████████                │  │
│  │  Shots            ██████████   14  │ 8   ██████                    │  │
│  │  Shots on Target  ██████        6  │ 3   ███                       │  │
│  │  Corners          ██████        7  │ 2   ██                        │  │
│  │  Fouls            ████████     12  │ 15  █████████                 │  │
│  │  Offsides         ████          3  │ 1   █                         │  │
│  │  Yellow Cards     ██            1  │ 2   ███                       │  │
│  │  Red Cards        ░             0  │ 0   ░                         │  │
│  │                                                                     │  │
│  │  Team abbreviations centered below:  ARG  ·  FRA                   │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌─── RIGHT: Lineups ────────────────────────────────────────────────┐  │
│  │                                                                     │  │
│  │  LINEUPS                                                            │  │  ← eyebrow
│  │  ────────────────────────────────────────────────────────────────  │  │
│  │                                                                     │  │
│  │  ┌─ Argentina ──────────────────────────────────────────────────┐  │  │
│  │  │  4-3-3                                                         │  │  │  ← formation
│  │  │                                                               │  │  │
│  │  │  23 E. Martínez (GK)                                          │  │  │
│  │  │  26 N. Molina (RB)                                            │  │  │
│  │  │  13 C. Romero (CB)                                            │  │  │
│  │  │  19 N. Otamendi (CB)            ← players in text-zinc-200    │  │  │
│  │  │   3 N. Tagliafico (LB)                                        │  │  │
│  │  │   7 R. De Paul (CM)                                            │  │  │
│  │  │  24 E. Fernández (CM)                                         │  │  │
│  │  │  20 A. Mac Allister (CM)                                      │  │  │
│  │  │  10 L. Messi (RW) ⚽ 23' ⚽ 45+2'  ← goal minutes             │  │  │
│  │  │   9 J. Álvarez (ST)                                           │  │  │
│  │  │  11 Á. Di María (LW)                                          │  │  │
│  │  │                                                               │  │  │
│  │  │  Subs:  8 M. Acuña · 4 G. Montiel · 5 L. Paredes             │  │  │  ← muted
│  │  └───────────────────────────────────────────────────────────────┘  │  │
│  │                                                                     │  │
│  │  ┌─ France ─────────────────────────────────────────────────────┐  │  │
│  │  │  4-2-3-1                                                       │  │  │
│  │  │  ...                                                           │  │  │
│  │  └───────────────────────────────────────────────────────────────┘  │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### Team stat bars (left panel) — detailed

Each stat row is a horizontal bar comparison:

```
 [Stat label]   [away bar →] [away val] │ [home val] [← home bar]
```

Layout: `grid grid-cols-[120px_1fr_40px_8px_40px_1fr]` (or flex-based)

- **Label:** `120px`, `text-xs text-zinc-400`, right-aligned, vertically centered
- **Away bar:** fills right-to-left toward center. Bar color: `bg-zinc-600`. Width proportional to max(away, home).
  - If away > home, the away bar gets `bg-zinc-500` (brighter = winning side for this stat)
- **Away value:** `40px`, centered, `font-mono tabular-nums text-sm text-zinc-200`
- **Center divider:** `8px`, a subtle `border-l border-zinc-700` vertical rule
- **Home value:** `40px`, centered, `font-mono tabular-nums text-sm text-zinc-200`
- **Home bar:** fills left-to-right toward center. Bar color: `bg-zinc-600` (or `bg-zinc-500` if winning)
- Bar height: `h-4` (or `h-5`), `rounded-sm`

**Possession** is special: render as a single continuous bar with a center split marker rather than two separate bars. Label the segments with percentages.

**Special values:**
- If both teams have 0 for a stat (e.g. red cards), show both bars at minimal width (~2px) or a dash `—` in `text-zinc-600`
- Yellow cards: small `■` icon in `text-yellow-500` next to the number
- Red cards: small `■` in `text-red-500`

### Lineups (right panel) — detailed

Each lineup is a mini-card:
```
bg-zinc-800/50 border border-zinc-800 rounded-lg p-3
```

- **Team name header:** `text-xs font-bold text-zinc-400 uppercase tracking-wide mb-1`
- **Formation:** `text-sm font-bold text-zinc-300 mb-2` — e.g. "4-3-3"
- **Starting XI:** each player on its own line
  - Layout: `flex items-center gap-2 text-xs py-0.5`
  - Number: `font-mono text-zinc-500 w-6 shrink-0 text-right` — `23`
  - Name: `text-zinc-200 truncate` — `E. Martínez`
  - Position: `text-zinc-500` — `(GK)`
  - Goal scorers: append `⚽ 23' ⚽ 45+2'` in `text-emerald-500 text-[10px]` after the position. This IS the "moment that matters" — emerald is correct here.
  - Card recipients: append `🟨 67'` in `text-yellow-500 text-[10px]`
- **Substitutes:** below the XI, separated by a subtle `border-t border-zinc-800/50 pt-2 mt-2`
  - `text-[10px] text-zinc-500` — "Subs: 8 M. Acuña · 4 G. Montiel · 5 L. Paredes"
  - If a sub scored, show the goal marker here too

### Sport-specific bold choice
The bar comparison charts for team stats. Soccer doesn't have per-player box scores — the story is told through team-level comparisons (possession, shots, territory). The bars encode that visually, making it immediately distinct from the table-heavy US sports tabs. The lineups panel with ⚽ goal markers directly connects the team sheet to the events.

### Loading state (skeleton)
```
┌─ Card shape ─────────────────────────────────────────────────────────────┐
│                                                                            │
│  border-l-2 border-emerald-500/40 pl-3  ← soccer's loading signature      │
│                                                                            │
│  ┌── LEFT SKELETON ──────────┐ ┌── RIGHT SKELETON ────────────────────┐  │
│  │                            │ │                                       │  │
│  │ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░    │ │  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░  (header) │  │
│  │ ▓▓▓▓▓▓▓▓  ▓▓▓▓  ▓▓▓▓    │ │  ┌───────────────────────────┐        │  │
│  │ ▓▓▓▓▓▓▓▓  ▓▓▓▓  ▓▓▓▓    │ │  │ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ │        │  │
│  │ ▓▓▓▓▓▓▓▓  ▓▓▓▓  ▓▓▓▓    │ │  │ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓          │        │  │
│  │ ▓▓▓▓▓▓▓▓  ▓▓▓▓  ▓▓▓▓    │ │  │ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓          │        │  │
│  │ ▓▓▓▓▓▓▓▓  ▓▓▓▓  ▓▓▓▓    │ │  │ ...  (11 rows)          │        │  │
│  │ ▓▓▓▓▓▓▓▓  ▓▓▓▓  ▓▓▓▓    │ │  └───────────────────────────┘        │  │
│  │ (7-8 stat rows)          │ │  ┌───────────────────────────┐        │  │
│  │                            │ │  │ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ │        │  │
│  │                            │ │  │ ... (second lineup)      │        │  │
│  └────────────────────────────┘ │  └───────────────────────────┘        │  │
│                                  │                                       │  │
└──────────────────────────────────┴───────────────────────────────────────┘
```
`border-l-2 border-emerald-500/40` — emerald is *the* soccer loading signature. Soccer goals are the "moments that matter" beacon, so the loading accent can borrow emerald at 40% opacity. When data arrives, the border-l is removed (or remains only on the lineups panel where goals are marked).

### Mobile
- Stack: Team Stats on top, Lineups below
- Lineups become two mini-cards stacked vertically (away then home)
- Stat bars compress: label gets `min-w-[90px]`, values get `30px`

---

## 4. PlayByPlay — generalized timeline

### What the user sees
Two render paths depending on sport family:

**US sports (NBA/NHL/MLB/NFL):** Period-grouped vertical timeline. Each period has a sticky header. Each play is a row with clock, team indicator, play description, and live score. Scoring plays are visually elevated. Filter toggle switches between "Scoring" and "All."

**Soccer (WC):** Continuous minute-based timeline with a subtle left rail. Events hang off the rail: filled circle for goals, square for cards, diamond for substitutions. No score column — the match score lives in the header. Split into halves with a "Half Time" marker.

### US sports version (extends existing `PlayByPlay.tsx`)

**Existing pattern to KEEP:**
- Period header: `text-xs font-bold text-zinc-500 sticky top-0 bg-zinc-900/90 py-1 backdrop-blur`
- Play row: `flex items-start gap-2 py-1.5 border-b border-zinc-800/30 text-sm`
- Clock: `font-mono text-zinc-600 w-10 shrink-0 text-xs`
- Team indicator: `◆` in `text-blue-400` (home) or `text-red-400` (away)
- Play text: `text-zinc-300 flex-1 leading-snug`
- Score: `font-mono tabular-nums text-zinc-600 shrink-0 text-xs`

**Enhancements for generalization:**
1. **Period labels come from data**, not hardcoded "Q". ESPN returns `period_disp` (e.g. "1st Quarter", "Top 1st", "1st Period", "1st Half"). Always use `period_disp` if available; fallback to `Q{period}`.
2. **Scoring play elevation:** when `scoringPlay` is true, the play text gets `text-zinc-200` (brighter), the score column gets `text-zinc-300 font-bold`. A subtle left-border accent on the row: `border-l-2 border-amber-500/60` — amber because a score is a moment of impact (not emerald; that's soccer's domain).
3. **MLB-specific:** clock shows "Bot 3" / "Top 4" style labels. Scoring plays marked with a ◆ in `text-amber-500` replacing the blue/red team indicator — the diamond shape is baseball's score marker.
4. **NFL-specific:** clock shows "Q2 3:45". Touchdown plays get `text-amber-400` play text.
5. **Filter toggle:** keep the existing Scoring/All toggle. Style refinement:
   ```
   flex items-center gap-1 bg-zinc-800 rounded-lg p-0.5
   Active:   bg-white text-black px-3 py-1 rounded text-xs font-medium
   Inactive: text-zinc-400 hover:text-zinc-200 px-3 py-1 rounded text-xs font-medium
   ```

### Soccer version (new render path)

```
┌─ Play-by-Play card ──────────────────────────────────────────────────────┐
│                                                                          │
│  ┌─ left rail ─┐                                                        │
│  │             │                                                        │
│  │  ● 23'      │  GOAL! Lionel Messi (Argentina)                        │
│  │  │          │  Left-footed shot from outside the box. 1-0.           │
│  │  │          │                                                        │
│  │  ■ 36'      │  Yellow Card — N. Otamendi (Argentina)                 │
│  │  │          │  Tactical foul on Mbappé.                              │
│  │  │          │                                                        │
│  │  ● 45+2'    │  GOAL! Lionel Messi (Argentina)                        │
│  │  │          │  Penalty. 2-0.                                         │
│  │  │          │                                                        │
│  │  ─ 45' ─    │  Half Time                                             │  ← divider
│  │  │          │                                                        │
│  │  ◆ 58'      │  Substitution — Argentina                              │
│  │  │          │  IN: M. Acuña  OUT: N. Tagliafico                      │
│  │  │          │                                                        │
│  │  ● 68'      │  GOAL! Kylian Mbappé (France)                          │
│  │  │          │  Header from Giroud cross. 2-1.                        │
│  │  │          │                                                        │
│  │  ■ 82'      │  Yellow Card — A. Rabiot (France)                      │
│  │  │          │                                                        │
│  │  ▸ 88'      │  VAR Check — Possible penalty (Argentina)              │
│  │             │  Decision: no penalty.                                 │
│  │             │                                                        │
│  └─────────────┘                                                        │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

**Timeline rail:**
- Left side: a thin vertical line `border-l border-zinc-700` running the full height
- Event markers sit ON the line:
  - **Goal:** `<circle>` filled, `r=5`, `fill #22c55e` (text-emerald-500) — the beacon
  - **Yellow card:** `<rect>` filled, `4x4`, `fill #eab308` (text-yellow-500)
  - **Red card:** `<rect>` filled, `4x4`, `fill #ef4444` (text-red-500)
  - **Substitution:** `<polygon>` diamond, `fill #71717a` (text-zinc-500)
  - **VAR:** `<polygon>` right-arrow/triangle, `fill #60a5fa` (text-blue-400)
- If SVG shapes are too heavy, use Unicode with color classes: `●` for goal, `■` for cards, `◆` for subs, `▸` for VAR

**Event row layout:**
```
flex items-start gap-3 py-2
```

- **Icon + minute container:** `w-16 shrink-0` (or `w-14`)
  - Icon centered above minute: icon in `text-[14px]`, minute in `font-mono text-[10px] text-zinc-500 mt-0.5`
- **Event text:** `flex-1`
  - Title line: `text-sm text-zinc-200 font-medium` — "GOAL! Lionel Messi (Argentina)"
  - Description (optional, if available): `text-xs text-zinc-500 mt-0.5` — "Left-footed shot from outside the box."
- Team indicator: the team name is in the text itself. No separate column needed.

**Half-time divider:**
```
flex items-center gap-4 py-3
```
- `border-t border-zinc-700 flex-1` on left side of "Half Time"
- `text-xs text-zinc-500 font-medium uppercase tracking-wider` — "Half Time"
- `border-t border-zinc-700 flex-1` on right side
- (Like a `<hr>` with text in the middle)

### Empty state
```
┌─ Card ────────────────────────────────────────────────────────────────────┐
│                                                                            │
│                    text-zinc-500 text-sm text-center py-12                 │
│                    Play-by-play begins at kickoff / first pitch / tip-off. │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

### Loading state (skeleton)
```
┌─ Card shape ─────────────────────────────────────────────────────────────┐
│                                                                            │
│  ┌─ US sports skeleton ──────────────────────────────────────────────┐   │
│  │                                                                     │   │
│  │  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░  ← period header bar (h-5, bg-zinc-800)   │   │
│  │  ▓▓▓▓▓▓  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  ▓▓▓▓  ← row pattern     │   │
│  │  ▓▓▓▓▓▓  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  ▓▓▓▓          │   │
│  │  ...  (6-8 rows with varied text widths)                            │   │
│  │                                                                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                            │
│  ┌─ Soccer skeleton (alternate) ───────────────────────────────────────┐   │
│  │                                                                     │   │
│  │  border-l border-zinc-700 pl-4                                      │   │
│  │  ● ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ (icon + shimmer text row)            │   │
│  │  ■ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓                                               │   │
│  │  ● ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓                           │   │
│  │  ◆ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ (randomized widths for variety)   │   │
│  │  ...  (6-8 event rows)                                             │   │
│  │                                                                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────────┘
```

The skeleton renders the correct shape (period-grouped for US sports, rail-timeline for soccer) so the user sees the form immediately, even while data is loading.

### Mobile
- US sports: Play text line-height adjusts; score column stays pinned right
- Soccer: Rail narrows, text wraps; event row becomes `py-2.5` for touch targets
- Filter toggle: full-width on mobile, pill style

---

## 5. GameInfo — extended with odds, weather, broadcasts

### What the user sees
The existing GameInfo component (venue, attendance, officials, season records) extended with three new sections: **Game Odds** (a compact chip-based panel), **Weather** (NFL only — a single row with temperature, wind, condition), and **Broadcasts** (network names). The season records cards remain at the bottom as the visual anchor.

### Structure
```
┌─ Game Info card (bg-zinc-900, border-zinc-800, rounded-xl, p-6) ─────────┐
│                                                                          │
│  ┌── Venue & Details ────────────────────────────────────────────────┐  │
│  │                                                                     │  │
│  │  Venue           Yankee Stadium, Bronx, NY                          │  │
│  │  Attendance      42,583 (91% full)  ← capacity shown as fill %     │  │
│  │  Capacity        46,537  ← only shown if available                  │  │
│  │  Officials       J. Smith (HP), M. Davis (1B), ...                 │  │
│  │  Roof            Open  ← or "Closed" / "Retractable - Open"        │  │
│  │                                                                     │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌── Weather (NFL only) ─────────────────────────────────────────────┐  │
│  │                                                                     │  │
│  │  🌧  52°F  ·  Wind 14 mph NW  ·  Light rain                        │  │
│  │                                                                     │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌── Odds (if available) ────────────────────────────────────────────┐  │
│  │                                                                     │  │
│  │  ┌──────────┐  ┌──────────┐  ┌───────────────────┐                 │  │
│  │  │ SPREAD   │  │  O/U     │  │ FAVORITE           │                 │  │
│  │  │          │  │          │  │                    │                 │  │
│  │  │ KC -3.5  │  │  51.5    │  │ ● Kansas City      │  ← emerald dot │  │
│  │  └──────────┘  └──────────┘  └───────────────────┘                 │  │
│  │                                                                     │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌── Broadcast ───────────────────────────────────────────────────────┐  │
│  │                                                                     │  │
│  │  TV    ESPN, ABC, ESPN Deportes                                    │  │
│  │                                                                     │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌── Season Records (existing, keep) ─────────────────────────────────┐  │
│  │                                                                     │  │
│  │  ┌─ Away ──────────┐  ┌─ Home ──────────┐                          │  │
│  │  │ AWAY             │  │ HOME             │                          │  │
│  │  │ NYY (NYY)        │  │ BOS (BOS)        │                          │  │
│  │  │ 52-34            │  │ 48-38            │                          │  │
│  │  │ Win%: 60.5%      │  │ Win%: 55.8%      │                          │  │
│  │  │ Streak: W3       │  │ Streak: L1       │                          │  │
│  │  └──────────────────┘  └──────────────────┘                          │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### Venue & Details (extend existing)

**Layout:** `space-y-3` of label-value rows (existing pattern).

- **Row format:** `flex justify-between text-sm`
  - Label: `text-zinc-500`
  - Value: `text-zinc-200`
- **Attendance:** show as `42,583` if no capacity data; show as `42,583 (91% full)` if capacity is available. Percentage in `text-zinc-500`.
- **Capacity:** shown separately as a dedicated row: "Capacity" / "46,537"
- **Officials:** existing pattern — `officials.join(', ')`, `text-right` on value. Keep.
- **Roof:** only for MLB/NFL stadiums with roofs. Label "Roof", value "Open" / "Closed". Hide if not applicable (basketball/hockey arenas don't have this field).

### Weather (NFL only)

A single decorative row. Only rendered when `weather` data exists (NFL games almost always have it; other sports may not).

```
flex items-center gap-2 text-sm
```

- Weather emoji or icon: `text-base` — `☀️` / `🌧` / `❄️` / `💨` / `☁️` based on condition text
- Temperature: `text-zinc-200 font-medium` — `52°F`
- Separator: `text-zinc-700` — `·`
- Wind: `text-zinc-400` — `Wind 14 mph NW`
- Separator: `text-zinc-700` — `·`
- Condition: `text-zinc-400` — `Light rain`

Wrap in a subtle container: `bg-zinc-800/30 border border-zinc-800 rounded-lg px-3 py-2`

**Hide entirely** for indoor sports (NBA, NHL) and non-football outdoor sports where weather data is sparse.

### Odds section

Only rendered when at least one odds field is available.

**Layout:** three chips in a row on desktop, stacked on mobile.

```
flex flex-wrap gap-3
```

Each chip:
```
bg-zinc-800/50 border border-zinc-800 rounded-lg px-4 py-3 min-w-[100px]
```

- **Eyebrow:** `text-[10px] text-zinc-500 uppercase tracking-wider mb-1` — "SPREAD", "O/U", "FAVORITE"
- **Value:** `font-mono tabular-nums text-sm text-zinc-200` — `KC -3.5`, `51.5`, `Kansas City`
- **Favorite chip:** the value gets a subtle `●` prefix in `text-emerald-500` — emerald because the favorite *is* a "pick" in the context of Legendary Picks. This is the bridge between the info tab and the core product.

**States:**
- If favorite is "EVEN" or no favorite: show "Pick 'em" in `text-zinc-400` instead of a team name; no emerald dot
- If odds data is missing: hide the entire section (don't show empty chips)

### Broadcasts section

Simple label-value row. Only rendered when broadcast data exists.

```
flex justify-between text-sm
```
- Label: `text-zinc-500` — "TV"
- Value: `text-zinc-200` — "ESPN, ABC"

If multiple networks, join with commas (or show as two chips if 3+ networks).

### Season Records (existing)
Keep as-is. The two `bg-zinc-900 border border-zinc-800 rounded-xl p-4` cards are the correct visual anchor for this tab. They match the two-tone system.

### Sport-specific bold choice
The three-chip odds panel. It's compact, scannable, and directly connects to Legendary Picks' core product (picks/bets). The emerald dot on the favorite is the one place emerald can appear in the info tab — it ties the neutral game data to the "what to pick" thesis that defines the app.

### Loading state (skeleton)
```
┌─ Card shape ─────────────────────────────────────────────────────────────┐
│                                                                            │
│  ┌── Venue skeleton ──────────────────────────────────────────────────┐  │
│  │  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  (label/value)  │  │
│  │  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓               │  │
│  │  ...  (3-4 rows)                                                     │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                            │
│  ┌── Odds skeleton ───────────────────────────────────────────────────┐  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐                     │  │
│  │  │ ▓▓▓▓▓▓▓▓▓ │  │ ▓▓▓▓▓▓▓▓▓ │  │ ▓▓▓▓▓▓▓▓▓ │                     │  │
│  │  │ ▓▓▓▓▓▓▓▓▓ │  │ ▓▓▓▓▓▓▓▓▓ │  │ ▓▓▓▓▓▓▓▓▓ │  ← chip skeletons   │  │
│  │  └────────────┘  └────────────┘  └────────────┘                     │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                            │
│  ┌── Records skeleton (two card-shaped rectangles) ────────────────────┐  │
│  │  ┌──────────────┐  ┌──────────────┐                                  │  │
│  │  │ ▓▓▓▓▓▓▓▓▓▓▓ │  │ ▓▓▓▓▓▓▓▓▓▓▓ │                                  │  │
│  │  │ ▓▓▓▓▓▓▓▓▓▓▓ │  │ ▓▓▓▓▓▓▓▓▓▓▓ │                                  │  │
│  │  │ ▓▓▓▓▓▓▓▓▓▓▓ │  │ ▓▓▓▓▓▓▓▓▓▓▓ │                                  │  │
│  │  └──────────────┘  └──────────────┘                                  │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────┘
```

### Mobile
- Odds chips: stack vertically, each full-width
- Weather row: wrap if needed
- Records cards: stack vertically, two-column grid collapses
- Everything else flows naturally in the `space-y` structure

---

## 6. Tab gating logic

### Which leagues show which tabs

| League | Box Score | Play-by-Play | Game Info | Notes |
|--------|-----------|--------------|-----------|-------|
| NBA | ✅ NBABoxScore | ✅ (US) | ✅ GameInfo | Existing — no change |
| NHL | ✅ NHLBoxScore | ✅ (US) | ✅ GameInfo | Existing — no change |
| MLB | ✅ MLBBoxScore | ✅ (US) | ✅ GameInfo | New |
| NFL | ✅ NFLBoxScore | ✅ (US) | ✅ GameInfo | New |
| WC | ✅ SoccerBoxScore | ✅ (soccer) | ✅ GameInfo | New |
| ATP | ❌ | ❌ | ❌ | No tabs |
| WTA | ❌ | ❌ | ❌ | No tabs |
| UFC | ❌ | ❌ | ❌ | No tabs |
| COD | ❌ | ❌ | ❌ | No tabs |

### Implementation pattern

The `TabBar` component should accept an optional `tabs` array prop (defaulting to all three):

```typescript
// TabBar.tsx — modify to accept optional tab list
interface TabBarProps {
  active: Tab
  onChange: (t: Tab) => void
  tabs?: { key: Tab; label: string }[]  // NEW: optional; defaults to all three
}
```

The page computes `visibleTabs` per league and passes it down. For unsupported leagues (ATP/WTA/UFC/COD), pass an empty array → TabBar renders nothing → the page renders the "not available" message.

In the page (`[league]/[gameId].tsx`):

```typescript
const LEAGUES_WITH_TABS = new Set(['nba', 'nhl', 'mlb', 'nfl', 'wc'])
const showTabs = LEAGUES_WITH_TABS.has(detail.league)

// ... in the JSX:
{showTabs ? (
  <>
    <TabBar active={tab} onChange={setTab} tabs={TAB_DEFS} />
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
      {/* tab content dispatch */}
    </div>
  </>
) : (
  <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-12 text-center">
    <p className="text-zinc-500 text-sm">Detailed stats aren't available for this sport yet.</p>
    <p className="text-zinc-600 text-xs mt-2">Check back for future updates.</p>
  </div>
)}
```

### "Not available" message design

```
┌─ Card (bg-zinc-900, border-zinc-800, rounded-xl, p-12) ──────────────────┐
│                                                                            │
│                                                                            │
│              text-zinc-500 text-sm text-center                             │
│              Detailed stats aren't available for this sport yet.           │
│                                                                            │
│              text-zinc-600 text-xs mt-2                                    │
│              Check back for future updates.                                │
│                                                                            │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

- No icon, no graphic — just quiet, honest text. The page already has ScoreStrip + GameStory + GameProps above this card, so the user isn't staring at an empty page.
- `p-12` gives it breathing room — the empty state should feel intentional, not cramped.
- The text is direct, not apologetic. It describes the state without selling or over-promising.

---

## 7. Component contract summary

For the frontend executor: each new tab component should follow this shape:

### BoxScore
```typescript
// Route: use the new per-tab endpoint (see SPEC)
// /api/{league}/game/{id}/boxscore → { available, teams, players, ... }

interface BoxScoreProps {
  gameId: string
  league: string
}

// Internal: on mount, fetch from /api/{league}/game/{id}/boxscore
// Show sport-specific loading skeleton while fetching
// Show sport-specific empty state if !available
// Show sport-specific component (MLB/NFL/Soccer) if data present
```

### PlayByPlay
```typescript
// Route: /api/{league}/game/{id}/playbyplay → { available, periods/events, ... }

interface PlayByPlayProps {
  gameId: string
  league: string
}

// Internal: fetch, then dispatch to US sports path or soccer path
// based on league (or based on the shape of the response).
// The US path reuses the existing period-grouped render.
// The soccer path uses the rail-timeline render.
```

### GameInfo
```typescript
// Route: /api/{league}/game/{id}/gameinfo → { available, venue, odds, weather, ... }

interface GameInfoProps {
  gameId: string
  league: string
  // existing props (for backward compat during transition):
  ctx?: GameContext | null
  homeStrength?: StrengthRow
  awayStrength?: StrengthRow
}

// Internal: fetch from new endpoint on mount.
// Show loading skeleton while fetching.
// Merge existing strength data (from detail endpoint) with new info data.
```

Each component owns its own data fetching (lazy, on tab selection). This avoids a single huge fetch on page load and keeps the tab-switch fast for NBA/NHL (which may remain on the snapshot path per the spec's Option A).

---

## 8. Cross-cutting rules

1. **Never `return null` while loading.** Every async component MUST show its sport-specific skeleton during fetch. Use `.finally()` to ensure loading state resolves.

2. **Emerald is reserved.** Only three places can use `text-emerald-500`:
   - Soccer goal markers in PbP (●)
   - Soccer box score loading border (`border-emerald-500/40`)
   - Favorite indicator in GameInfo odds chip
   - (Existing: GameStory border-left. Do not add more.)
   Stat tables NEVER use emerald. Do not green-highlight stat leaders.

3. **Amber is for scoring.** TD columns in NFL, HR markers in MLB, scoring plays in PbP. Amber = points on the board.

4. **All numbers are mono + tabular.** `font-mono tabular-nums` on every numeric cell. Column scanning depends on this.

5. **Empty states are directional, not moody.** "Box score available at first pitch" — says what will happen and when. Never "No data" or "Nothing to see here."

6. **Mobile: scroll, don't cram.** Data tables use `overflow-x-auto` with `min-w-[...]` on cells. Never drop columns to fit.

7. **Do not repaint the page shell.** These components render inside the existing card (`bg-zinc-900 border border-zinc-800 rounded-xl p-6`). They do NOT set their own `bg-ink-900`, `min-h-screen`, `max-w-*`, or `px-*` at the top level. They are content children of the tab content div.

---

## 9. Sport → visual signature map (quick reference)

| Sport | Loading accent | Data accent | Signature element |
|-------|---------------|-------------|-------------------|
| MLB | `border-l-2 border-amber-500/40` | `◆` HR, .300+ glow | Batting + Pitching stack |
| NFL | `border-t-2 border-amber-400/40` | TD in amber | Three-column positional layout |
| WC (soccer) | `border-l-2 border-emerald-500/40` | ⚽ goal markers | Stat bar comparison + lineups |
| NBA | (existing) | (existing) | Two-column team stats |
| NHL | (existing) | (existing) | Two-column team stats |
| ATP/WTA | N/A | N/A | "Not available" message |
| UFC/COD | N/A | N/A | "Not available" message |
