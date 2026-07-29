# SPEC: drafter profiles — bots that draft like people

Status: **specified, not built.** Requested 2026-07-28. Follows the league-size /
draft-slot work in the same session, which is the prerequisite: profiles only matter once
the drafter chooses who they are drafting against and where they sit.

Parent: `SPEC-slice-D-mock-draft.md` §3 (bot picking logic), `SPEC-nfl-mock-draft-simulator.md`.

---

## §0 The problem, stated as a measurement

Every bot in the draft is the same bot. `lib/mockDraft/engine.ts:botPick` scores every
candidate as:

```
score = adp * (1 + jitter),  jitter ~ uniform(-0.10, +0.10)
```

plus two rules that are identical across all seats: bench-inclusive position ceilings
(`POSITION_MAX`), and a round-12 override that restricts to positions still missing a
starter.

So an 11-bot field is eleven draws from one distribution. The consequences are visible in
a real draft and they are the reason the room does not feel like a room:

- **No one ever reaches.** The widest possible deviation is ±10% of ADP, which at pick 30
  is ±3 picks. Nobody takes their guy a round early, because nothing in the model wants a
  particular guy.
- **No one ever runs a strategy.** Zero-RB, Hero-RB, early-QB, the manager who takes a
  kicker in round 11 — none are expressible. Positional runs, the single most common thing
  a human drafter has to react to, cannot happen, because there is no mechanism that makes
  three teams want a QB at the same time.
- **The draft is therefore unfalsifiable as practice.** The point of a mock is to rehearse
  decisions. A field with no variance rehearses one decision: take the top of ADP.

This spec adds *variance with structure*. It does not replace the scoring model — the ADP
term stays, the roster-legality rules stay — it multiplies it.

---

## ⛔ Guardrails

### Honesty (this is the part that is easy to get wrong)

1. **A profile is a simulated archetype, never a claim about a real person or a real
   league.** No profile may be labelled with, or imply, a measured population — not "this
   is how ESPN drafters behave", not "23% of managers go Zero-RB", not a win rate. If we
   ever want a claim like that, it gets measured first and published second, per
   `published-first`. Until then the UI says these are simulated opponents.
2. **No fabricated identity.** Bots are not given photographs, handles that read as real
   accounts, or records. `T4 · Zero-RB` is honest. `@dynastyDan (14-3 last year)` is a
   fabricated record and is forbidden.
3. **A profile must not silently change a published number.** Profiles bias *which player a
   bot takes*. They never touch ADP, xFP, availability, or anything on a player row.

### Determinism

The draft already replays from `seed`. Profile assignment **must derive from that same
seed** — `hash(seed, team_no) -> archetype` — so:

- the same seed produces the same field, forever;
- no schema migration is needed (nothing new is persisted on `nfl_mock_drafts`);
- a saved draft can be re-explained after the fact without having stored the explanation.

Do **not** add a `profile` column. If a future feature needs a field the user *chose*
(see §6 open question 2), that choice is what gets persisted, not the derived assignment.

### Files you may touch

```
lib/mockDraft/profiles.ts              (new — archetype table + assignment)
lib/mockDraft/engine.ts                (botPick scoring only)
lib/mockDraft/__tests__/profiles.test.ts   (new)
components/MockDraft/DraftRoom.tsx     (labels in the ledger + board header)
components/MockDraft/ResultsScreen.tsx (the field summary)
docs/SPEC-drafter-profiles.md          (this file)
```

Out of scope, do not touch: the pool endpoint, `nfl_mock_draft.py`, the schema, any
availability or scoring derivation, `verify-gates.sh` gate targets other than adding the
new jest file.

---

## §1 The model

One function, applied to the existing ADP score. Lower score picks earlier.

```
score(player, bot, state) =
    adp
  * (1 + jitter(bot.reach))                    // §2.1 — replaces the fixed ±0.10
  * bot.positionBias(player.position, round)   // §2.2
  * bot.availabilityBias(player)               // §2.3
  * bot.experienceBias(player)                 // §2.4
  * runPressure(player.position, state)        // §2.5 — shared, scaled by bot.herding
  * bot.homerBias(player.team)                 // §2.6
```

Every term is a multiplier centred on 1.0, so a bot with all-default parameters reproduces
today's behaviour exactly. **That identity is a gate** (§5.1): the "Field Average" archetype
must draft the same board as the current engine given the same seed, or the refactor
changed something it was not supposed to.

### §2.1 Reach — `jitter`
`jitter ~ uniform(-reach, +reach)`. Today's value is `0.10` for everyone.

### §2.2 Position bias — `positionBias(pos, round)`
A per-position multiplier, optionally windowed by round. `< 1` drafts the position earlier.

### §2.3 Availability bias — `availabilityBias(player)`
`1 + injuryAversion * missedRate`, where `missedRate = games_missed / team_games` from the
pool payload. `injuryAversion = 0` reproduces today. This is the term that uses the thing
LP actually measures better than anyone else, so at least two archetypes must sit at
opposite ends of it.

Null availability (`sample === 'none'`, or a null denominator) contributes **nothing** —
`missedRate` is treated as absent, not as zero. An unknown is not a clean bill of health.

### §2.4 Experience bias — `experienceBias(player)`
Keyed on `has_prior_nfl_sample`, which the pool publishes. `< 1` chases players with no NFL
sample; `> 1` fades them. Never keyed on an inferred "rookie" flag — that inference is the
exact defect `0212060` fixed.

### §2.5 Run pressure — shared, scaled per bot
When *k* of the last *n* picks were the same position, that position's score is multiplied
by `1 - herding * f(k)`. This is the mechanic that produces positional runs; it is shared
state, not a bot property, so a run started by one archetype pulls the herding archetypes
in behind it. `herding = 0` ignores runs entirely.

### §2.6 Homer bias
One NFL team drawn from `hash(seed, team_no)`; that team's players get a multiplier `< 1`.
Applies to at most one archetype.

---

## §3 The archetypes

Eight, so a 14-team field has variety without an obvious repeat. Parameters below are the
**starting** values and are expected to move once §5.2 measures them — they are a design
proposal, not a measurement.

| # | Archetype | reach | position bias | injuryAversion | experienceBias | herding |
|---|-----------|-------|---------------|----------------|----------------|---------|
| 1 | Field Average | 0.10 | — | 0 | 1.00 | 0 |
| 2 | Sharp | 0.04 | QB ×1.25, TE ×1.15, K/DEF ×1.4 until R13 | +0.6 | 1.00 | 0.1 |
| 3 | Zero-RB | 0.10 | RB ×1.35 (R1–6) then ×0.90, WR ×0.85 | +0.3 | 0.95 | 0.2 |
| 4 | Hero-RB | 0.10 | RB ×0.80 (R1–4) then ×1.10 | 0 | 1.05 | 0.2 |
| 5 | The Reacher | 0.22 | — | 0 | 0.95 | 0.3 |
| 6 | Homer | 0.12 | — | 0 | 1.00 | 0.2 | *(+ team bias ×0.75)* |
| 7 | Upside Hunter | 0.14 | — | 0 (ignores it) | 0.82 | 0.1 |
| 8 | Floor Merchant | 0.08 | — | +1.2 | 1.30 | 0.4 |

Assignment rule: derived from `hash(seed, team_no)`, subject to two constraints —
**at least one Field Average** in every draft (so the board always contains a normal
reference), and **no more than two** of any one archetype.

---

## §4 What the drafter sees

The draft is only better practice if the drafter can tell what they were up against.

- **During the draft**: the pick ledger and the board column header carry the archetype
  tag next to the team — `T4 · Zero-RB`. See §6 open question 3; this may become a reveal.
- **At results**: one line naming the field, e.g. *"You drafted against 2 reachers, a
  Zero-RB and a Floor Merchant."* Then the one fact that is actually actionable: which of
  your picks a specific archetype was about to take. That is a real "you got him one pick
  early" moment and it falls straight out of the score function — it is the runner-up in
  the next bot's ranking, not a new derivation.
- Copy states plainly that opponents are simulated.

---

## §5 Gates — written before the code, per `feedback_fix_gates_before_the_code`

Whoever builds this writes these **first** and watches them fail.

1. **The refactor changed nothing it should not.** An all-default `Field Average` field,
   given seed *s*, produces byte-identical picks to today's engine at seed *s*. Assert the
   full pick list, not a summary.
2. **The archetypes are actually different, by a stated margin.** Over 200 seeded drafts:
   the mean round of a Hero-RB's first RB is **at least 3.0 rounds earlier** than a
   Zero-RB's, and Zero-RB takes **at least 2 more** WRs in rounds 1–6. Numbers are asserted;
   if the tuning cannot hit them, the tuning is wrong, not the gate.
3. **Every bot still fields a legal roster.** At 10, 12 and 14 teams, across 200 seeds,
   every team ends with ≥1 QB, ≥2 RB, ≥2 WR, ≥1 TE, ≥1 K, ≥1 DEF and 6 RB/WR/TE for the
   FLEX. This is the gate most likely to catch a bad multiplier: a strong enough bias
   starves a position and the round-12 override cannot recover it.
4. **The pool does not starve.** At 14 teams (210 picks from 300) no draft throws the
   `no candidates` fallback in `botPick`, at any seed.
5. **Determinism.** Same seed, two runs, identical archetype assignment and identical picks.
   Different seed, different assignment.
6. **Assignment constraints hold.** ≥1 Field Average and ≤2 of any archetype, over 500 seeds
   at each league size.

---

## §6 Open questions for Micah — answer before building

1. **Names or tags?** `T4 · Zero-RB` is honest and readable. Persona names ("Dynasty Dan")
   add texture but drift toward fabricated identity, and the brand's whole position is that
   we do not fabricate. Recommendation: **tags only** for v1.
2. **Does the drafter choose the field?** A "sharp league / casual league" control is a
   small addition to the setup bar built today and turns the mock into a difficulty ladder.
   If yes, *that choice* persists on the draft row; the per-seat assignment stays derived.
3. **Visible during, or revealed at the end?** Visible during is a teaching tool — you
   learn to read a Zero-RB drafter. Hidden until results is the realistic version.
   Recommendation: **visible**, because this product is for practice, not immersion.
4. **Does this ship in v0.7.0 or after?** It is a feature, so it can carry a release on its
   own. Bundling it with league size delays league size.
