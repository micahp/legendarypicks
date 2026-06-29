# Philosophy — The Moment That Matters

> One primitive: find the critical point, ride the trend. Everything we build is a different
> surface on that same idea.

## The thesis
There is exactly one thing this company is good at: **spotting the inflection and showing it while
it's still happening.** Not the box score after the fact. Not a season-long average. The *turn* —
the player heating up, the line about to break, the overreaction about to snap back. The moment
that matters, right now.

Two products fall out of that, and they're the same product wearing different clothes:

- **Prediction-market trading** — fade the overreaction, catch the swing at the bottom, ride it.
  The edge was never the asset; it's the *timing of the turn*. (Selection over a posted price;
  entry at the actual inflection, not mid-fall.)
- **Legendary Picks** — the player on a hot or cold run, the prop about to hit, the live game at
  its witching hour. Same turn, different arena.

When Micah says he loves how the **summary talks about the trend**, that's not a feature
preference — it's recognition. The hot/cold form-run line in a game story is the whole thesis in
miniature: *here is the trend, here is where it's bending.* The "about to hit" Live Now card is the
same computation made real-time. The trading entry signal is the same computation made tradeable.
**Inflection detection, three surfaces.**

## What that means for what we build
1. **One engine, many faces.** Player logs → projections → prop-outcomes is the spine. Every
   product (history API, projections page, Live Now overlay, alerts) is a *surface* on it, and
   every esport/sport is a *data adapter* behind it — never a bespoke pipeline. Hedge on which
   surface finds product-market fit; never fork the engine.
2. **The voice is the thesis.** Summaries, the Live Now overlay, notifications, and the marketing
   should all sound like one sentence: *"here's the moment that matters right now."* If a feature
   can't point at an inflection, it's the wrong feature.
3. **Own the derived layer, rent the raw.** Raw stats are a commodity (free or licensed — GRID,
   STRATZ, ESPN; ESPN itself rents its summaries from Data Skrive). The asset we own and sell is
   the layer on top: projections, hit-rates, prop-outcome history, the trend narratives. So we
   build on free data first and never own raw ingest until a surface is proven.
4. **Go where the turn is unwatched.** Major US leagues are saturated; the stream/data isn't our
   edge there. The inflection-detection engine is most valuable in underserved arenas — esports
   and niche sports — where no one has built the product. A "home for niche sports," riding trends
   nobody else is tracking.

## The test for any decision
Ask: *does this help someone see the moment that matters, sooner?* If yes, it's on-thesis. If it's
a static average, a post-hoc recap, or a feature that doesn't point at a turn — it isn't us, no
matter how much data it has.

---
*Companion docs:* `esports-opportunity-feedback.md` (the Layer-2 / Live-Now strategy),
`esports-data-recon.md` (free-vs-paid feeds + adapters), `PHASE-2-prop-outcome-data.md` (the
prop-outcome data product). Cross-project sibling: the prediction-market-trading repo — same
primitive, financial surface.
