# NHL Model Grades & Pick Confidence — Design Spec

**Status:** Draft for review  
**Author:** Design  
**Date:** 2026-10-15  
**Scope:** `/leagues/nhl?tab=model` — ProjectionCard component and model pick display

---

## 1. Problem

The NHL model API returns a `grade` object on each model forecast when the game has been graded (final score + statistical grade). The API also returns a `grade` on the `result` field. However:

1. **ProjectionCard only shows LOCKED or UNLOCKED** — it never renders a GRADED status, even when the data is available. Users cannot tell at a glance which locked games have been settled.
2. **Model pick has no confidence rule** — the `modelPick()` function returns whichever candidate (home ML, away ML, Over, Under) has the largest edge. When the Vegas puck line is strong (|spread| > 1.0) but the model edge is weak (< 1.0 goals), the moneyline pick is unreliable and should be suppressed in favor of the spread/total pick or shown with a warning.
3. **Record view is the only place grades appear** — `RecordProjection` already renders `✓`/`✗` correctly, but projection cards don't surface the same signal.

This spec defines the visual design for graded projection cards and the confidence rule display. No code is written.

---

## 2. Design System Reference

| Token | Value | Usage |
|---|---|---|
| `--lp-bg` | `#0f0f11` | Page background |
| `--lp-panel` | `#18181b` (zinc-900) | Card / container surface |
| `--lp-hairline` | `border-zinc-800` | Hairline separators inside a container |
| `--lp-edge` | `border-zinc-800` | Card outer edge (current) |
| Emerald | `rgb(16 185 129)` | Positive / live edge accent |
| Amber | `rgb(245 158 11)` | Warning / suppressed accent |
| Red | `rgb(248 113 113)` | Negative result |
| Zinc-100 | `text-zinc-100` | Primary text |
| Zinc-400 | `text-zinc-400` | Secondary text |
| Zinc-500 | `text-zinc-500` | Tertiary / meta text |

**Edge-bar vocabulary** (from DESIGN-live-card-rail.md):  
- `.live-edge` — 3px breathing emerald left border for live/active state  
- `.amber-edge` — 3px static amber left border for functional tags / warnings

This spec introduces two new edge classes for graded states:
- `.graded-edge` — 3px static emerald left border (settled, neutral-positive)
- `.suppressed-edge` — 3px static amber left border (confidence rule triggered)

---

## 3. Graded Status on Projection Cards

### 3.1 Status Badge

The `ProjectionCardView` currently shows a single status pill (`LOCKED` or `UNLOCKED`). When a game is graded, the status area becomes a **dual-badge cluster**:

```
┌──────────────────────────────────────────────────────────┐
│ AWAY @ HOME                              [✓ GRADED] 7:00 PM │
│                                                          │
│ Away  2.3          Home  3.1                              │
│                                                          │
│ ───────────────────────────────────────────────────────  │
│ Vegas line  H -1.5    Model line  H -0.8    Edge  +0.7    │
│                                                          │
│ Model pick  Over 5.5  (+4.2%)                            │
│                                                          │
│ Vegas total  5.5    Model total  6.2    Edge  +0.7       │
└──────────────────────────────────────────────────────────┘
```

**Badge design:**
- Replaces the single `LOCKED` pill with a `GRADED` pill when `forecast.grade` is present
- Emerald text + emerald border (subtle): `text-emerald-400 border-emerald-400/30`
- Prefix with `✓` glyph (text, not icon font) to signal settled
- If the pick won, show `✓ GRADED` in emerald; if it lost, show `✗ GRADED` in zinc-400 (the grade is settled but the result is negative — the emerald edge-bar still signals "settled")
- If the game was decided in shootout, append `· SO` after `GRADED`

**Why not just a green card?** The edge-bar system already communicates state through the left border. A badge next to the time is consistent with the existing LOCKED/UNLOCKED pill placement and keeps the change minimal.

### 3.2 Card Edge Treatment

When graded, the card's left border transitions from the default zinc-800 to a **static emerald left edge** (3px, `rgb(16 185 129 / 0.6)`), matching the `.live-edge` pattern but without the breathing animation:

```css
.graded-edge {
  border-left: 3px solid rgb(16 185 129 / 0.6);
}
```

This gives the card a visual "settled" status that distinguishes it from locked-but-ungraded games. The rest of the card (surface, hairlines, typography) is unchanged.

**Transition:** When a game first grades, the edge animates from zinc-800 to emerald over ~300ms (CSS transition on `border-color`). No entrance animation beyond the color shift.

### 3.3 Result Indicator on the Pick

The model pick area currently shows:

```
Model pick
Over 5.5
+4.2% edge
```

When graded, the result is appended:

```
Model pick
Over 5.5  ✓
+4.2% edge · Won
```

- `✓` in emerald if the pick won
- `✗` in red if the pick lost
- `Won` / `Lost` in zinc-500 text below the edge percentage

The pick result is determined by the same logic already in `RecordProjection`:
- Moneyline pick: `pickHome = forecast.home_win_probability >= 0.5`; won if `grade.official_winner` matches
- Over/Under pick: won if the total went over/under the Vegas total line

### 3.4 Grade Detail on Expand (Optional Enhancement)

If the card is expandable (or on click), a grade detail row appears:

```
Projected  2.3–3.1   Final  2–4   Brier 0.142   Log-loss 0.512
```

This is a **progressive disclosure** — the badge and edge tell the story; the detail is available on demand. This row is NOT shown by default to keep the card compact.

---

## 4. Model Pick Confidence Rule

### 4.1 Rule Definition

The `modelPick()` function selects the candidate with the largest model-vs-market edge. The confidence rule adds a gate:

> **If |Vegas spread| > 1.0 goals AND the best candidate's edge < 1.0 goals, the pick is suppressed.**

Rationale: When the market has a strong opinion (spread > 1 goal) but the model's edge is marginal (< 1 goal), the moneyline pick is unreliable. The model is essentially saying "I agree with the market favorite but by a smaller margin than the market does." In this case, prefer the spread/total candidate if one exists with a positive edge, or suppress the pick entirely.

### 4.2 Display States

The model pick area has three display states:

#### State A — Normal Pick (edge ≥ 1.0 or |spread| ≤ 1.0)

```
Model pick
Over 5.5
+4.2% edge
```

Unchanged from current.

#### State B — Suppressed Pick (confidence rule triggered)

```
Model pick
Over 5.5  ⚠
+4.2% edge · Low confidence
```

- The pick label is shown but with an amber `⚠` suffix
- Edge percentage followed by `· Low confidence` in amber
- The card's left edge uses `.amber-edge` (3px static amber left border) instead of the default
- A tooltip on hover: "Model edge below 1.0 goal against a Vegas spread above 1.0 — pick may be unreliable"

#### State C — No Pick Available (no candidates or all edges negative)

```
Model pick
n/a
```

Unchanged from current.

### 4.3 Confidence Indicator Design

The `⚠` glyph is amber (`text-amber-400`), text-rendered (not an icon font). It sits inline after the pick label. The `· Low confidence` suffix is amber, tabular-nums, smaller than the edge number.

The amber left edge on the card (`.amber-edge`) is the persistent signal — it survives even if the user doesn't hover the pick area. This mirrors how `.amber-edge` is used for LiveDiscounts in the live-card-rail design.

### 4.4 Pick Label Override

When the confidence rule triggers, the pick label does NOT change — it still shows the best candidate. The user should see what the model wanted to pick, with the warning that it's unreliable. Changing the label would hide the model's actual output.

However, if there is a spread or total candidate with positive edge that is NOT the best candidate, show it as a secondary line:

```
Model pick
Over 5.5  ⚠
+4.2% edge · Low confidence
Alternative: H -0.5  (+1.8%)
```

This alternative line is zinc-400, smaller, and only appears when the best candidate is a moneyline pick but a non-moneyline candidate has a higher edge-to-confidence ratio.

---

## 5. CSS Classes & Styling

### 5.1 New Edge Classes

```css
/* Graded / settled card */
.graded-edge {
  border-left: 3px solid rgb(16 185 129 / 0.6);
  transition: border-color 300ms ease;
}

/* Confidence-suppressed pick */
.suppressed-edge {
  border-left: 3px solid rgb(245 158 11 / 0.6);
}

@media (prefers-reduced-motion: reduce) {
  .graded-edge {
    transition: none;
  }
}
```

### 5.2 Status Badge Classes

```
GRADED (won):     border-emerald-400/30 text-emerald-400
GRADED (lost):     border-zinc-600 text-zinc-400
LOCKED:            border-emerald-400/30 text-emerald-400   (unchanged)
UNLOCKED:          border-zinc-600 text-zinc-400            (unchanged)
```

### 5.3 Pick Result Glyphs

```
✓:  text-emerald-400
✗:  text-red-400
⚠:  text-amber-400
```

### 5.4 Type Scale

| Element | Class |
|---|---|
| Status badge | `text-xs font-semibold tracking-wide` (unchanged) |
| Pick label | `text-xl font-semibold text-zinc-100` (unchanged) |
| Pick edge | `text-xs tabular-nums text-zinc-400` (unchanged) |
| Confidence suffix | `text-xs tabular-nums text-amber-400` |
| Pick result | `text-xs tabular-nums` (emerald or red) |
| Alternative pick | `text-xs tabular-nums text-zinc-400` |
| Grade detail row | `text-xs tabular-nums text-zinc-500` |

---

## 6. Component State Matrix

| State | Status Badge | Card Edge | Pick Display |
|---|---|---|---|
| Preview (not locked) | `UNLOCKED` | zinc-800 (default) | Normal |
| Locked, not graded | `LOCKED` | zinc-800 (default) | Normal |
| Locked, not graded, confidence rule triggers | `LOCKED` | `.amber-edge` | Suppressed (⚠ + Low confidence) |
| Locked, graded, pick won | `✓ GRADED` | `.graded-edge` | Normal + ✓ Won |
| Locked, graded, pick lost | `✗ GRADED` | `.graded-edge` | Normal + ✗ Lost |
| Locked, graded, confidence rule triggers | `✓/✗ GRADED` | `.graded-edge` (emerald wins over amber) | Suppressed + result |
| Locked, no markets available | `LOCKED` | zinc-800 | n/a |

**Edge priority:** `.graded-edge` > `.amber-edge` > default. A graded card always shows the emerald edge regardless of confidence state — the grade is the more important signal.

---

## 7. Interaction & Accessibility

### 7.1 Tooltips

- Suppressed pick: `aria-label="Model pick suppressed: edge below 1.0 goal against Vegas spread above 1.0"`
- Grade detail (if implemented): `aria-label="Projected 2.3–3.1, Final 2–4, Brier 0.142, Log-loss 0.512"`

### 7.2 Keyboard

The card is an `<article>`, not interactive. No keyboard changes needed. If the card becomes expandable, use `aria-expanded` on a button.

### 7.3 Reduced Motion

The `.graded-edge` transition is disabled under `prefers-reduced-motion`. The badge and text changes are discrete (no animation).

### 7.4 Color Independence

The `✓`/`✗`/`⚠` glyphs always accompany color, never carry meaning alone. A colorblind user can read "GRADED", "Won", "Lost", "Low confidence" as text.

---

## 8. Data Dependencies

### 8.1 Required API Fields

The API at `/api/nhl/model/locks?season=2026` already returns:

- `forecast.grade` — present when the game has been graded (already in the TypeScript interface)
- `forecast.home_win_probability`, `forecast.projected_goal_differential_home` — for pick result calculation
- `line.home_puck_line`, `line.total_line` — for confidence rule spread check

No API changes are required. The design uses existing data.

### 8.2 Frontend Logic

The frontend needs to compute:

1. **`isGraded`** — `forecast.grade != null`
2. **`pickResult`** — `{ won: boolean } | null` if graded, `null` otherwise
3. **`isConfidenceSuppressed`** — `|vegasSpread| > 1.0 && bestPick.edge < 1.0`
4. **`alternativePick`** — the best non-moneyline candidate with positive edge, if the best overall candidate is a moneyline pick

These are pure functions of data already in the component's scope.

---

## 9. Out of Scope

- Changing the `modelPick()` algorithm or adding a new pick type
- Modifying the Record tab (`RecordProjection`) — it already handles grades correctly
- Adding a filter or sort by graded/locked status
- Changing the API response shape
- Animations beyond the border-color transition

---

## 10. Summary of Changes

| Area | Change |
|---|---|
| Status badge | Add `GRADED` variant (✓/✗ prefix, emerald or zinc) |
| Card edge | Add `.graded-edge` (emerald) and `.amber-edge` (amber) classes |
| Pick display | Add result glyph (✓/✗) and confidence warning (⚠ + "Low confidence") |
| CSS | Two new edge classes, two new badge color variants |
| Accessibility | `aria-label` on suppressed pick and grade detail |
| API | None — uses existing fields |
