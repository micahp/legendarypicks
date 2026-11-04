# NFL Playbook Evolution and Play Ancestry (research plan)

Status: Phase 1 inventory and Phases 2–6 source-field measurements are complete with corrected snap denominators, a stationary-order null, controlled postseason usage comparisons, and matched forecast cohorts. Exact play/concept ancestry and closed-loop workload impact remain unresolved. Findings: [Phase 1 data inventory and play identity](../../research/nfl-playbook-ancestry/PHASE1-FINDINGS-2026-11-03.md), [Phase 2 weekly evolution](../../research/nfl-playbook-ancestry/PHASE2-WEEKLY-EVOLUTION-2026-11-03.md), and [corrected findings](../../research/nfl-playbook-ancestry/PHASE3-6-FINDINGS-2026-11-03.md). Source: research notes and local dev data, 2026-11-03.

Verification status: sources checked for Phases 3–6 are recorded with URLs, publication dates, confidence and scope notes in
[the external evidence table](../../research/nfl-playbook-ancestry/phase3_6_external_evidence_2026-11-03.csv). Some claims are verified or partially verified; the original unnamed NFL.com game-planning article remains unidentified and unverified. Unverified or partial claims are not used as play-identity labels.

## Hypothesis

NFL playbooks are evolving systems, not fixed team-season distributions. Current-season evidence becomes more important
as the season progresses, previous seasons provide priors, and postseason play calling may be a distinct regime.

The question underneath it: can we reverse-engineer not just which plays a team runs, but how its offensive identity
develops, where its concepts originated, and when it starts using them differently?

That would separate four things a conventional play-calling model tends to lump together:

1. a familiar play,
2. a familiar concept disguised with a new formation,
3. an actual new concept,
4. a familiar play being called much more frequently.

The model should learn both concept identity and how a concept is presented. The biggest shift: do not only predict the
next play from what a team has done. Model the menu of plays the team has revealed, how it disguises them, which ones it
favors today, and how that menu changes.

## 1. What coaches and analysts say (source status in evidence table)

- Current-season film gains importance as the season progresses. A September 2026 Fox Sports interview with Chargers
  defensive coordinator Chris O'Leary describes coaches studying historical film heavily early in the season, especially
  with new play-callers, then giving current-season film more weight while keeping older tendencies for context. **Verified,
  medium confidence:** this is one coach's account, not a league-wide measurement. (Fox Sports)
- The play often stays the same; its presentation changes. Coaches interviewed by American Football Quarterly kept core
  run and pass concepts largely intact while changing formations, personnel, motion and tempo for each opponent.
  **Partially verified, low confidence:** the cited interviews are with college and high-school coordinators, so NFL-wide
  generalization is unresolved. (American Football Quarterly)
- An NFL game-planning analysis makes the same distinction: one concept can appear to be several plays when run from
  different formations. **Unverified:** the specific NFL.com article in the original notes remains unidentified; a
  separate Ravens transcript corroborates a wide-zone example but does not identify that article. (nfl.com)
- Week 1 is not automatically a full reveal. Coaches script opening sequences, test defensive reactions and keep calls in
  reserve. **Partially verified:** PFF supports scripted opening calls and information gathering, but not the stronger
  claim that calls are held in reserve. The amount of novelty and uncertainty are separate things to measure. (PFF)

## 2. Seahawks case study

Three Seattle offenses to compare: 2024 under Ryan Grubb, 2025 under Klint Kubiak, and 2026 under Brian Fleury.

**2024 to 2025: personnel and play-action shift (source checked).** Seattle used three or more WRs on roughly 78% of snaps in
2024, falling to 44% in 2025. Two-tight-end usage roughly doubled. Play-action rate rose from about 19% to 28%.
(Sharp Football Analysis; verified as the article's claim, medium confidence). Local measurements closely match the
personnel shares; the local play-action tag has a different source and denominator, so it does not independently verify
the published play-action rate.

**2025 postseason to 2026: reported continuity with changes.** The Seahawks' July 2026 account describes Fleury's staff
continuity and shared Shanahan background. This verifies the reported coaching context, not exact play or concept reuse.
(seahawks.com; verified, high confidence for the team account)

- In Seattle's 2026 opener, analysts observed carryovers from 2025, including Jaxon Smith-Njigba lining up in the
  backfield and the familiar tight-end sneak package. They also identified different personnel usage and new formations.
  (NFL.com/The Athletic; verified article, medium confidence; qualitative observations, not charted play identities)
- A related Seattle Sports article dated October 19 discussed secondary receivers and Smith-Njigba. The cited October 22
  article instead focused on the rushing attack and its effect on passing; it does not support the specific receiver claim.
  (October 19 article verified, medium confidence; October 22 claim partially verified)

Question to investigate: did Fleury inherit Kubiak's concepts but change their frequency, sequencing, or the players they
were designed to feature? This can be studied separately from whether Seattle is winning.

**Postseason sequencing (qualitative).** A film review of Seattle's December 2025 comeback against the Rams describes
Kubiak changing second-half calls to exploit earlier defensive reactions: play-action, screens and misdirection. That is
adaptation within a single game. (Field Gulls)

## 3. Play ancestry

This is the priority project.

An earlier handoff referenced `formal_playcall.py` as a possible starting vocabulary. The Phase 1 source inventory did not
confirm that file or establish its fields and coverage; check the current repository before relying on that reference.

Classifications:

| Classification | Meaning |
|---|---|
| Exact repeat | Same identifiable play design and presentation |
| Same concept, different look | Same underlying concept with different motion, personnel or formation |
| Team-first observed | First time the concept has been observed for this team |
| Imported concept | Concept seen under this coordinator or in another team's offense |
| Previously unseen | No earlier match in the available evidence |
| Unresolved | Not enough information to identify the design with confidence |

Build a play ancestry graph that connects play executions to concepts, presentations, team usage, coaches and their
previous appearances. Illustrative shape only (not a verified match between specific snaps):

- Concept: outside-zone boot flood
  - 2025 regular season: observed
  - 2025 postseason: observed
  - 2026 regular season: to match

**What the data can recognize.**

- 2022 to 2025: historical participation and play-by-play support personnel and formation classification, with additional
  labeled attributes where available.
- 2026 so far: play-by-play and weekly snap counts support some comparisons. They do not provide full per-snap
  participation or exact route designs. The nflverse FTN participation release arrives after the postseason. (nflreadr)
- Film and charting: All-22 and reliable route or concept annotations are needed to establish that two plays with
  different presentations share a specific underlying design.

Current data supports matching observed source-field signatures only. Such overlap cannot establish an exact repeat, a
shared concept, or an imported concept. Concept-level classifications remain unresolved until annotated play designs
are linked to the game/play keys. A first-seen descriptor means first seen in this dataset, not new to the team's playbook.

## 4. Measurements, week by week

| Question | Measurement |
|---|---|
| How much changes in Week 1? | First-observed descriptor and presentation rates |
| Does the descriptor distribution stabilize by Week 2? | Week-to-week novelty and distribution change, compared with the stationary-order null |
| When do teams become predictable? | Forward predictive log loss as games accumulate |
| Does a coordinator change reset the offense? | Carryover rate by coaching continuity |
| What changes in the playoffs? | Context-adjusted personnel, formation, motion, shotgun, run/pass and tagged play-action usage; first-observed action descriptors |
| Do playoff descriptors return next season? | Postseason-to-next-season descriptor reuse rate |
| Does it affect workloads? | Player snap and opportunity-share changes; concept linkage requires annotated designs |

For novelty, compare observed descriptor novelty with a stationary-order control that jointly shuffles whole game-week
packages across played-week labels. Preserve each team-season's signature frequencies by family, game and play counts,
and cross-family co-occurrence. Keep descriptor novelty separate from concept novelty.

Run a control using the whole league independently of team history. That shows whether a change is an NFL-wide trend or
specific to one offense.

## 5. Agent instructions

Use the existing 2022 to 2025 historical play-call, participation and play-by-play datasets, plus available 2026
observations. Do not confuse coarse play-call classifications with exact play designs. Build a reproducible play ancestry
and evolution analysis.

### Phase 1: data inventory and play identity

- Audit all existing formation, personnel, run-gap, pass-depth, route, motion and play-concept fields.
- Establish which fields identify a concept and which merely describe the execution.
- Construct hierarchical play signatures with source provenance and confidence.
- Preserve unknowns, unsupported matches, OL6 formations and special-teams exceptions.
- Do not invent exact play names or concepts from incomplete play-by-play.

### Phase 2: weekly evolution

- For every team, season and week, compare observed play signatures against all previous weeks of that season.
- Compare against the previous season, older team history and league-wide history.
- Track first-observed descriptors, descriptor reuse, recorded presentation changes and shifting call frequencies.
- Evaluate Week 1 separately, then Weeks 2 to 3, 4 to 8, 9 to 13 and 14 to 18.
- Quantify descriptor novelty, distribution change, turnover and concentration; do not call these concept-level playbook stability.
- Test whether early-season uncertainty is higher and whether team identity becomes more identifiable as current-season
  games accumulate. Do not assume the hypothesis is true.

### Phase 3: coaching continuity

- Add head coach, offensive coordinator and play-caller tenure.
- Compare continuity seasons with seasons that have coordinator or QB changes.
- Investigate whether annotated concepts follow coaching staffs between franchises; raw signature overlap cannot answer this.
- Distinguish carryover of concepts from carryover of frequency and sequencing.

### Phase 4: postseason

- Treat the postseason as a distinct evaluation segment across all playoff teams.
- Compare postseason calls with the team's regular-season catalog through the playoff game cutoff.
- Measure first-observed descriptors and attribute usage changes, controlling for opponent and
  game state.
- Measure which postseason descriptors reappear during the following regular season; concept reuse needs annotated designs.
- Report uncertainty, because the postseason has small, selected samples.

### Phase 5: Seahawks case study

- Compare Seattle's 2024, 2025 regular season, 2025 postseason and available 2026 games.
- Examine the Grubb-to-Kubiak and Kubiak-to-Fleury transitions.
- Measure which recorded personnel packages and formations carried over, changed in frequency or first appeared; concept carryover needs annotated designs.
- Pay particular attention to Jaxon Smith-Njigba, secondary receiver usage, tight ends, running backs, heavy personnel and
  play-action.
- Use reputable film-analysis articles and coaching interviews as qualitative evidence, with URLs, publication dates and
  confidence levels.
- Do not promote an analyst's interpretation to a verified play label without supporting film or charting evidence.

### Phase 6: predictive and simulation evaluation

- Compare static previous-season, current-season expanding-window, last-N-game and adaptive models.
- Evaluate run/pass, personnel, formation and action-descriptor distributions separately.
- Use strict chronological cutoff rules. Report log loss, calibration, novelty prediction and uncertainty intervals.
- Evaluate whether the resulting personnel and play-call distributions improve closed-loop player workloads.
- Do not use winner prediction as the primary criterion.

## Deliverables

1. Data coverage and confidence audit.
2. Weekly playbook evolution dataset.
3. Source-field matching rules and regression tests; actual play ancestry remains unresolved.
4. Seahawks usage case study with raw descriptor matches, not identified play designs.
5. League-wide postseason usage study with supported context matches.
6. Model comparison and PASS/FAIL research report.

Preserve reproducible scripts and artifacts on the research branch. Do not activate a new simulation model until its
relevant evaluations pass.

## Why it matters for workloads

A playbook that increasingly features two tight ends, or calls designed to isolate a particular receiver, changes who gets
on the field and who gets the ball. That connects this work directly to the player-workload model.

Start with the Seahawks: they combine coaching changes, measurable personnel shifts, postseason film analysis and a new
season to compare against.
