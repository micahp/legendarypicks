---
name: priced-line-surfaces
description: MUST load before building or changing any surface that shows a priced prop line next to a result: the game-detail Props tab, a settled board, a player prop card, a prop chart, a "what decided it" panel, or any mock of one. Encodes the rules three design rounds paid for: a line is the only axis several markets share, our numbers never sit in the publisher's table, "no result" is two different facts, and the leaders ranking is published rather than invented. Triggers on props tab, settled lines, prop board, prop chart, box score plus props, "what decided it", leaders, margin, best line, over/under bar, DNP, ungraded.
---

# Priced-line surfaces

Load this with [honest-data-ui](../honest-data-ui/SKILL.md), not instead of it. That
skill governs any number we show; this one governs the specific surface where a
**line we priced** sits next to a **result a publisher reported**.

---

## 1. Where the data comes from

`GET /api/game/{league}/{game_id}/props` is the one endpoint behind all of it.

- `players[]` carries every priced line: player, market, line, actual, hit, cashed.
- `leaders[]`: **top three by raw margin**, `margin == abs(actual - line)`,
  `cashed` exactly over/under. QA'd across 106 games on 2026-08-11, 11 assertions,
  zero failures: `docs/RESULT-whatdecidedit-qa.md`. Not-started and no-settled-props
  games return `[]` and `settled_lines: 0`, never a placeholder.

A settled prop is only settled when `hit IS NOT NULL`. A row with `settled_at`
stamped and `hit`/`actual_value` null is a **failed** settlement that used to be
stored in the same shape as a landed one, which is how World Cup was reported at
100% while settling nothing. Any count you render must require `hit IS NOT NULL`.

---

## 2. The line is the only shared axis

Hits, outs recorded and strikeouts have no common numeric scale. A bar chart
across them is fake precision.

> **Every mark is the same width and its centre is that market's line.** The fill
> runs from the line to the result, so the mark encodes only *how far past or short
> of its own line* the result landed.

That is what makes a column of mixed markets scannable without reading a digit.
Never normalise several markets onto one shared value axis to make them comparable.

---

## 3. Two rankings exist and they disagree. Say which one you are showing

| ranking | definition | where it belongs |
|---|---|---|
| **raw margin** | `actual - line` | the published `leaders` key; "what decided it" |
| **normalised beat** | `margin / market range` | our own sort, labelled as ours |

They genuinely disagree. JJ Bleday went +0.5 total bases and +0.5 doubles in the
same game; normalised, the half-double is 17% of its market's range and the
half-base is 5%, so doubles ranks higher. Raw margin calls them equal.

Round 2 shipped a single "Best line" column that showed the normalised value while
reading like a raw one. Round 3 found the "what decided it" gauges showing a **+0.5
outs-recorded** line as one of three things that decided a 7-1 game, matching
neither ranking. **A ranked number must name its ranking**, and anything calling
itself `leaders` must reproduce the endpoint's own definition.

Ungraded rows sort **last** under every ranking. Never let a null result rank as
though the player came in at zero.

---

## 4. Our numbers do not go in the publisher's table

The box score is ESPN's. The lines are ours. Round 1 merged them and it read as one
undifferentiated pile of numbers; Round 2 labelled the seam with a band and the seam
was still there; Round 3 split them into two panes and the problem went away.

- The box score pane carries the publisher's columns, in the publisher's order.
- Everything we priced lives in its own panel, which **sorts on its own terms**.
  That independence is the entire reason to separate them.
- The most the box score may carry of ours is a **count** of lines on that player.
  A count is not a rating. No composite score in a box-score column.
- Selecting a player **filters** the panel. Do not hide a line behind a disclosure:
  if a prop needs expanding to be read, its market name did not fit, and the fix is
  room, not a tooltip. Three-letter market codes (`HRR`) exist only where there is
  no room for the real name; given room, spell it out.

---

## 5. "No result" is two different facts, and they must look different

Measured across every MLB prop stored with a null outcome:

| | share | what it is | treatment |
|---|---|---|---|
| never appeared | 77,553 (74%) | a fact about the **player** | row marked DNP, hollow bar |
| played, not graded | 27,597 (26%) | a fact about **us** | hatched in the absent colour |

Collapsing these into one blank-dash state hides our own failure inside the player's.

**Absence is never zero.** A player missing from a roster payload means the ingest
published nothing, not that he recorded nothing.

---

## 6. Backfilling a box-score cell

Allowed only where the box-score column and a priced market are **provably the same
real quantity**, and it must be marked. Brady Singer's row read `ER` with a blank dash while his
Earned runs prop, graded off the same game, settled at 3 four inches to the right:
the same quantity disagreeing with itself on one screen. The cell now reads `3†`,
the dagger meaning it came from the props pipeline rather than the box-score ingest.

Today that is **ER alone**. Batters genuinely lack AB and AVG, pitchers PC-ST and
ERA, because `player_game_logs` does not carry them, so they stay absent and marked.

---

## 7. Where the design lives

The worked reference is the artifact
<https://claude.ai/code/artifact/313f9a63-95cc-4181-a0f5-9b4de02309a6>, rounds 1
through 3, with each round's notes preserved and the superseded ones marked. Read it
before redesigning this surface.

**Its HTML lives nowhere else.** On 2026-10-02 a search of every repo, scratchpad and
session log found no copy and no design doc, and a prior agent had already failed the
same search in August. The artifact is the source. If you rebuild it, pull it with
the Artifact tool's `read` first, and keep its token set. The surface has one
palette (`--over` / `--under` / `--absent`), not a second one per round.
