# Tennis coverage — which tournaments Legendary Picks tracks

What the tennis product follows, what it deliberately ignores, and how the schedule reaches the
database. Written 2026-10-18 because this rule previously existed only as code and a source comment.

**Source of truth:** `backend/espn_client/scoreboard.py`, `_is_major()`, `_ATP_MAJORS`,
`_WTA_MAJORS`. If this document and that code disagree, the code wins — then fix the document.

---

## 1. The rule

> `_is_major()` returns true if the ESPN event is a **Grand Slam, Masters/1000, or Finals**.

Anything else is filtered out before it can reach the database. Only **singles** draws pass: the
grouping slug must start with `mens` (ATP) or `womens` (WTA) and must not contain `doubles` or
`mixed`.

## 2. What we track — ATP

| category | events |
|---|---|
| **Grand Slams** | Australian Open · French Open (Roland Garros) · Wimbledon · US Open |
| **Masters 1000** | Indian Wells (BNP Paribas Open) · Miami · Monte-Carlo · Madrid (Mutua) · Italian Open (Rome) · Canadian Open (National Bank) · Cincinnati · **Shanghai** · **Paris** (Rolex Paris Masters) |
| **ATP 500 — one exception** | China Open (Beijing) |
| **Finals** | Nitto ATP Finals |

## 3. What we track — WTA

| category | events |
|---|---|
| **Grand Slams** | Australian Open · French Open (Roland Garros) · Wimbledon · US Open |
| **WTA 1000** | Qatar Open (Doha) · Dubai · Indian Wells · Miami · Madrid · Italian Open (Rome) · Canadian Open · Cincinnati · China Open (Beijing) · **Wuhan** |
| **Finals** | WTA Finals |

## 4. What we do not track

- **ATP 500s** other than Beijing — Vienna, Basel, Stockholm, Rotterdam, Doha, Dubai, Halle,
  Queen's, Tokyo and the rest
- **ATP 250s** — all of them
- **WTA 500s and 250s** — all of them
- **Challengers**, **ITF** and **futures** — present in the historical Sackmann data but never
  tracked live
- **Doubles and mixed doubles** — filtered at the grouping slug

The historical match tables contain far more than this (they include challengers and futures). That
is training data, not tracked competition. Do not read a tournament's presence in
`tennis_atp_matches` as evidence that we cover it.

## 5. Why the scope is what it is

The tracking rule is 1000s-and-above. There is exactly one exception and it is documented in the
code:

> *"ATP 500s Kalshi lists and the competition trades. ATP China Open (Beijing) is a 500, so the
> 1000-only list dropped it while WTA's China Open (a 1000) passed: added 2026-10-04."*

So Beijing is included on the men's side because the market lists it and the competition trades it,
not because it clears the 1000 bar. Any future exception should be recorded the same way, at the
reason, in the code.

## 6. Two different scopes — do not confuse them

**Tracking** (§2–3) is broad. **Surface-dependent outputs** are much narrower.

Surface-dependent projections — total games, and anything derived from the surface — require the
event to be in `SURFACE_BY_EVENT` in `backend/tennis_daily_projections.py`:

```python
SURFACE_BY_EVENT = {"315": "Hard", "381": "Hard"}  # Shanghai and Wuhan, reviewed event map.
```

`best_of` is hardcoded to `3` in that path. If the event is not mapped, the projection carries:

> `"Event surface is not mapped yet."`

**So today, total-games projections exist for Shanghai and Wuhan only.** Every other tracked event
— including all four Grand Slams — gets winner probabilities but no total-games target.

> **Documentation defect:** `docs/model-cards/tennis.md` states that total-games is available for
> *"Shanghai, Wuhan, and the four Grand Slams."* The code does not support the Grand Slams. The
> model card is wrong and should be corrected, or the code should be extended — those are different
> jobs and neither has happened.

## 7. How the schedule reaches the database

1. `ingest_scoreboards.py` fetches ESPN's scoreboard for a date.
2. `tennis_draws_from_payload()` keeps **complete major singles draws only**. Missing match ids,
   missing rounds, or duplicate ids invalidate the snapshot rather than publishing a partial
   bracket.
3. `current_tennis_draw()` picks **one** draw per tour when ESPN publishes several: among draws
   with a match not yet final, the one whose last match is soonest; when every draw is complete,
   the one that finished last.
4. `save_tennis_draws()` **replaces** the single stored draw per league. Empty or ambiguous
   publisher responses leave the last good snapshot alone — by design, so a malformed payload
   cannot look like an empty bracket.

### Consequence: the stored `status` field goes stale

Because the snapshot is only replaced when a complete draw is published, once an event ends the
snapshot freezes at its last good state — which can be **mid-match**. A `Suspended` or `open`
status in `tennis_draw_snapshots.payload` is a historical observation, not a live state.

**Always read `fetched_at` before treating any match status as current.** On 2026-10-18 the ATP
snapshot was 13.8 hours old and still reported the Shanghai final as in progress.

## 8. The 2026 calendar gap

Both tracked events ended on 2026-10-18:

| event | tour | result |
|---|---|---|
| Rolex Shanghai Masters | ATP | final snapshot 10:26Z, mid-match, never graded |
| Dongfeng Voyah Wuhan Open | WTA | final completed 10:35Z |

The next tracked events:

| event | tour | dates | start |
|---|---|---|---|
| Rolex Paris Masters | ATP 1000 | Nov 2–8 (qualifying Oct 31–Nov 1) | ~15 days |
| WTA Finals (Indian Wells) | WTA | Nov 8–15 | ~21 days |
| Nitto ATP Finals (Turin) | ATP Finals | Nov 15–22 | ~28 days |

Between Oct 19 and Nov 2 the **ATP tour is tracked as having no events at all**, because the
tournaments being played — Vienna, Stockholm and the 250s — are outside the coverage rule. The WTA
gap runs to Nov 8.

This is correct behaviour, not a broken feed. The Projections page showing nothing is the coverage
list working.

## 9. Adding an event

To track a tournament that is not on the list:

1. Add the ESPN short-name aliases to `_ATP_MAJORS` or `_WTA_MAJORS`, with a comment saying **why**
   (the same shape as the China Open entry).
2. If surface-dependent outputs are wanted, add the ESPN event id to `SURFACE_BY_EVENT` with its
   surface and verify the format (`best_of` is currently hardcoded to 3 — best-of-five events need
   more than a map entry).
3. Confirm the draw actually reaches `tennis_draw_snapshots` — a name match alone does not mean
   ESPN publishes a complete bracket for it.
4. Record the change in this document.

## 10. Open questions

- Whether Grand Slam total-games support was ever implemented and lost, or only ever planned.
- Whether 500s should be tracked to close the October/November gaps, and what that costs in surface
  mapping and validation.
- Whether the Projections page should state the next tracked event during a gap rather than
  rendering empty. That needs an event calendar this system does not currently hold.
