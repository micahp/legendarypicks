---
name: honest-data-ui
description: MUST load before designing or building ANY Legendary Picks surface that shows numbers to a user — boards, player pages, cards, tables, charts, stat tiles, leaderboards, projections, or anything with a per-game average on it. Encodes Dieter Rams' honesty and restraint, Steve Krug's scan-don't-read rules, and the LP-specific bans learned the hard way: no conditional averages presented as unconditional, no fake precision, sample size always visible, rookies never zero, nothing labeled a projection that is not one. Triggers on draft board, sit/start, player card, stat tile, usage table, rankings, floor/ceiling, "how should we display", any new NFL/MLB/UFC/esports data surface.
---

# Honest data UI

Load this before designing any surface that puts numbers in front of a user.

It exists because the numbers we display are the product. "Legendary Picks" means
picks plus an earned record — a surface that flatters the data destroys the only
thing the brand is. Every rule here is a specific way that happens.

---

## 1. The governing principle

> "Good design is honest. It does not make a product appear more innovative,
> powerful or valuable than it is." — Dieter Rams

In a data UI, dishonesty is almost never a lie. It is a **true number displayed
without the condition that makes it true.**

The canonical case, measured off `picks.dev.db` on 2026-07-27:

| player | availability | PPR when he played | PPR per team game |
|---|---|---|---|
| Tyreek Hill | 4/17 | 13.4 | **3.2** |
| Joe Burrow | 8/17 | 16.8 | **7.9** |
| Brock Purdy | 9/17 | 19.7 | **10.4** |

Every fantasy site shows the middle column. It is an average over the games the
player was healthy enough to play — conditioned on the exact thing you were
trying to predict. It makes injury-prone players look safer than they are.

**Before shipping any average, name what it is conditional on.** A missed game
has no row in `player_game_logs`; absence is invisible unless you go get it. If
the condition matters, show both numbers, or show the condition next to the
number. Never only the flattering one.

## 2. Rams, applied

- **As little design as possible.** The data is the ornament. No chrome, no
  gradient behind a number, no card shadow doing the work a rule could do.
- **Unobtrusive.** These are instruments, not posters. A board is closer to a
  depth chart or a Braun measuring device than to a magazine spread.
- **Thorough to the last detail.** Tabular figures so columns align. Consistent
  decimal places. A dash for "no data" that is visibly different from a zero.
- **Long-lasting.** Avoid the visual language of the current season's marketing.
  A board built in 2026 should not look dated in 2027.
- **Honest > impressive.** If a number is weak, the design's job is to let the
  reader see it is weak, not to make the page feel authoritative anyway.

## 3. Krug, applied

- **We scan, we don't read.** A user should get the answer from shape and
  position before reading a single digit. If your surface requires reading to
  rank two players, redesign it.
- **We satisfice.** People take the first plausible option, not the best one.
  So the first plausible option had better not be the misleading one — this is
  why the flattering-average default is dangerous, not merely imprecise.
- **Omit needless words, then omit half of what's left.** No "Player Performance
  Analytics Dashboard." No helper text explaining what a column means when a
  better column name would do.
- **Self-evident beats self-explanatory; self-explanatory beats a legend.**
  Reach for a tooltip only after the layout has failed.
- **Name things by what the user controls**, never by how we compute it.
  "Games missed," not "row absence."

## 4. LP-specific bans

Each of these is from a real defect, not a style preference.

- **Never label something a projection that is not one.** A historical
  distribution is not `prob_over()`. Ship it as what happened, and say so.
- **Rookies read "no NFL sample," never zero and never a low floor.** Zero is a
  claim about the player. Absence is a claim about us.
- **Always show sample size.** p90 over ≤17 games is one or two games. A
  percentile without an n is fake precision.
- **Don't ship floor/ceiling/boom-bust as the differentiator.** It is standard
  fantasy vocabulary; ESPN player profiles already use it. It only earns its
  place with ADP/value overlay, positional replacement context, position-specific
  thresholds, and games-missed.
- **Declare the scoring contract on the surface itself.** PPR vs standard vs
  half changes every number. State which one, on the card, not in a doc.
- **A list must not download more than it renders.** Measure payload and time
  before shipping; see `docs/DEV-STANDARDS.md`.
- **Separate the three things people conflate:** performance given playing,
  availability, and current role. A single blended number hides which one moved.

## 5. Signature direction for the NFL board

Established 2026-07-27, when the availability finding above landed:

**The accent color marks absence, not achievement.**

Everything present renders quiet and neutral. The one saturated color on the page
is reserved for games a player did not play. Ink normally goes to the good stuff;
here it goes to the holes, because the holes are the information no competitor
shows. The rule is the thesis of the product expressed as a style rule — keep it
consistent across every surface that inherits from the board.

Vernacular to draw from: roster sheets, depth charts, box scores, injury reports.
Not "sports = aggressive italics and speed lines."

## 6. Before you call it done

- State what each average is conditional on. If you cannot, you do not understand
  the number well enough to display it.
- Check the empty and rookie states. They are where dishonesty hides.
- Verify the whole-page flow with a screenshot, not just the element you edited.
- Read it as a user who will spend four seconds: what do they conclude, and is it
  true?

Avoid the three looks AI design defaults into regardless of brief: cream + high
contrast serif + terracotta; near-black + one acid accent; broadsheet hairlines
with zero radius. They are defaults, not choices.

---

## 7. The sibling rule

This skill governs what a surface may *show*. `.claude/skills/fail-loudly/SKILL.md` governs
what happens upstream when the data is not there — the blank `position` that makes a game
log render a generic table instead of the sport's is a fail-loudly defect that arrives as
an honest-data-ui symptom. 6,818 players are in that state today.
