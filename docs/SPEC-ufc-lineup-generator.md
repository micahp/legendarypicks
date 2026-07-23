# SPEC — UFC Lineup Generator (investigation + spec)

Status: spec + data-feasibility investigation, not built. Written 2026-07-22.

## What this is (and isn't)

Explicitly NOT a real draft against other people, where the fighter pool depletes based
on others' picks (that's the NFL mock-draft mechanic — see SPEC-nfl-mock-draft-simulator.md).
This is salary-cap fantasy, DraftKings/FanDuel-MMA style: pick N fighters from an
upcoming card within a fixed budget, optimizing for projected fantasy points. You're
playing against a cap and a scoring system, not against other drafters — closer to a
solitaire lineup-builder than a live draft. Whether to add a comparative leaderboard
(your lineup's score vs. other users' lineups on the same card) is a separate layer that
could sit on top of this later; not assumed here.

## Data investigation (verified 2026-07-22, dev DB)

What we actually have for UFC, checked directly against `picks.dev.db`:

- **`prop_games`** (league='ufc'): fight card entries — `home`/`away` (the two fighters),
  `date`. 11 rows currently (2026-07-18/19 card only — this table only holds whatever's
  been ingested for recent/upcoming cards, not a historical archive).
- **`props`** joined to the above: **method-of-victory odds only** —
  `win_by_ko` / `win_by_submission` / `win_by_decision`, each an "over 0.5" American-odds
  line per fighter. Confirmed via `bovada_scraper.py` comment (line 123): *"UFC has no
  per-fighter STAT props on Bovada; the fighter-attributed market is Method of Victory"* —
  this is an architectural fact about our data source, not a gap in what we built.
- **`ufc_rankings`**: division, rank, fighter name, is_champion flag. Point-in-time
  snapshot, no historical fight stats.
- **`ufc_picks`**: the existing pick'em feature — binary win/loss picks, crowd_share,
  settled results. Useful precedent for the settlement/grading pattern (see below), not a
  stats source.
- **`player_stats` / `player_game_logs` for league='ufc': zero rows.** No significant
  strikes, takedowns, control time, knockdowns — the actual inputs real DraftKings MMA
  scoring uses. This is the central gap.
- **No moneyline (fight-winner) odds anywhere in the pipeline.** Only the three
  method-of-victory markets exist.

## The two real gaps this creates

1. **No moneyline → no direct "market says fighter X is a 70% favorite" signal**, which
   is normally the natural input for salary pricing (favorites cost more). Workaround:
   derive an implied win probability by de-vigging and summing the three method-of-victory
   odds per fighter (P(win) ≈ P(KO) + P(Sub) + P(Decision) for that side), a legitimate
   standard technique, just not as clean as a direct moneyline.
2. **No strike/takedown/control-time data → can't replicate real DK MMA scoring**, which
   scores significant strikes landed, takedowns, control time, knockdowns, and finish
   bonuses. Building that for real would mean ingesting a genuine fight-stats feed
   (a real new data source, bigger lift, not assessed here) — not something we can fake
   from what we have.

## Proposed v1 scope, honest about the gap

A **finish-based scoring system**, not full DK parity:
- Points for a win (fixed base).
- Bonus for method (KO/TKO > Submission > Decision — matches how DK weights finishes,
  just without the underlying strike-volume detail DK has).
- Bonus decaying by round (an early finish scores higher than a late one) — derivable
  from ESPN's fight result data we already pull elsewhere (winner + method + round via
  `espn.ufc_fight_history`, already used in `ufc_picks.py`'s settlement path).
- **Salaries** from the de-vigged method-odds win-probability described above, scaled
  into a cap-friendly range (e.g. $10,000 cap, favorites priced higher).

This is honestly a simplified, self-consistent scoring system inspired by DK's shape, not
a claim of matching DK's actual formula — that would need the strike/takedown data we
don't have.

## Settlement / grading

`ufc_picks.py` already has a working pattern for this (`settle_finished()` — pulls
ESPN fight results after a card, grades picks). A lineup's score would settle the same
way: once a card's fights are final, look up each rostered fighter's result via the same
ESPN fight-history call, apply the scoring rules above, sum for the lineup total. No new
settlement infrastructure needed — extend the existing pattern.

## Effort tiers

1. **MVP**: one upcoming card at a time, fixed cap, finish-based scoring above, pick N
   fighters (needs a roster-size decision, e.g. 5-6), settle after the card using the
   existing ESPN fight-history pattern. Real, buildable today with data we have.
2. **+ Better pricing**: if a real moneyline source gets added later (a MMA odds
   provider, or scraping a different book that lists MMA moneylines directly), salaries
   improve without changing anything else in the engine.
3. **+ Real DK-parity scoring**: only possible with a genuine fight-stats feed
   (significant strikes, takedowns, control time) — a real new data source, out of scope
   until one is identified and evaluated on its own.
4. **+ Comparative leaderboard**: multiple users' lineups on the same card, ranked
   against each other — an optional layer on top of the same engine, not assumed as part
   of v1.

## Open questions before building

- Roster size (how many fighters per lineup) and salary cap total.
- Whether "one card at a time" (the realistic v1) is acceptable, or whether a
  multi-card/season-long mode matters — the latter needs a much deeper card-history
  archive than the 11-row snapshot currently in `prop_games`.
- Whether the self-consistent finish-based scoring is acceptable framing, or whether
  real DK-parity scoring (blocked on new data) is a hard requirement before shipping
  anything.
