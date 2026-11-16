# AGENT TASK: Historical Relationships, Rivalries & Sports Memory for Legendary Picks

**Project:** `micahp/legendarypicks`  
**Requested:** 2026-11-11  
**Scope:** deterministic pregame story engine and reusable content-feed facts; NBA first, extensible to other sports.  
**Implementation:** work on a new feature branch from current `dev`, open a **draft PR** for review. Do not deploy, merge, or mutate production data. Do not add a per-story LLM call or require a GPU.

## Product principle

**Sports have memory. Legendary Picks should understand why today's opponents have history.**

A game is more than today's records, season averages and projections. Rivalry and personal-history angles include player-team relationships, former teammates, reciprocal trades, franchise returns, coaches facing former teams, playoff elimination rematches, memorable prior matchups, and championship connections. An event can contain multiple overlapping storylines. The facts must be deterministic and cutoff-safe; ranking decides which are editorially important. Never equate a relationship with an unsourced assertion about revenge, hatred, bad blood or motivation.

The **July 6, 2025 seven-team Durant trade** is the core acceptance case: Phoenix sent Kevin Durant to Houston; Jalen Green and Dillon Brooks went from Houston to Phoenix as part of the deal. All three are connected to the same transaction event, but in opposite directions. This provides multiple valid angles depending on the opponent, venue, player availability and prior games. Official announcement: https://www.nba.com/rockets/news/rockets-complete-seven-team-trade-to-acquire-kevin-durant-and-clint-capela ; NBA reporting: https://www.nba.com/news/kevin-durant-joins-rockets-7-team-trade .

Also test *other* Houston opponents in 2025–26: Durant's prior time with Golden State and Oklahoma City, the Rockets' 2025 playoff loss to Golden State, and ordinary games where none of these connections warrant the lead. Different teams have different meaningful histories. **Do not print “revenge” in every matchup or imply every opponent disliked Houston.**

## First, inspect the existing code and report findings

Read current `dev` and the PR #30 / #35 work as appropriate:

- `backend/story_engine.py`: `collect_story_facts`, `_db_player_facts`, `select_story_angle`, `_lead`, `render_story`, `generate_story`.
- `backend/story_engine_audit.py`, `backend/story_engine_runtime.py`, `backend/story_rubric.py` and tests.
- `backend/core_stories.py` and story endpoint routing. Preserve `LP_DETERMINISTIC_STORY_ENGINE` existing semantics.
- `backend/ingest_nba_roster.py`, `backend/roster_membership.py`, NBA identities/player logs and team-code mappings.
- `backend/nfl_transactions_sync.py`, plus any verified transaction / team membership data sources that already exist.
- `backend/narrative_event_knowledge.py` and the editorial comparison in `docs/research/narrative-event-knowledge-2026-11-03/espn-editorial-benchmark/`.
- Postgame PR #35, in particular its content-feed adapter and fact provenance contract, **if it is still unmerged**. Keep a clean API boundary; do not stack unrelated unfinished PR code blindly.

**Known gap to confirm:** `_db_player_facts` uses only the latest qualifying team for a player, while story-angle selection has records, streaks, standings and a same-opponent rematch but no `former_team`, `former_teammates`, or reciprocal-trade category. That is fine for recent scoring form but inadequate for relationships. Do **not** change current-team stat calculation to include old-team games; add a separate history collector.

Before implementation, deliver a source inventory: table/view, league, player ID coverage, team history dates, availability/published time, source reliability, ability to build historical teammate or transaction edges, and missing fields. Reuse existing records where sufficient; ingest only what the demo truly needs.

## Deliverable A: canonical historical relationship graph (CPU + read-only source extraction)

Treat this as a small **versioned, evidence-backed sports graph**, not as thousands of hand-written “rivalry descriptions.” Suggested logical records (adapt to repo schema):

```json
{
  "relationship_id": "nba:trade:<canonical_event_id>:durant-phx-hou",
  "league": "nba",
  "relation_type": "trade_movement",
  "transaction_id": "<stable canonical transaction>",
  "player_id": "<canonical player ID>",
  "from_team_id": "PHX",
  "to_team_id": "HOU",
  "agreed_at": "2025-06-22T...",
  "effective_at": "2025-07-06T...",
  "published_at": "<original publication time>",
  "available_at": "<capture time>",
  "sources": [{"url":"https://www.nba.com/...","publisher":"NBA/Rockets","source_id":"..."}],
  "evidence_grade": "official_transaction",
  "confidence_state": "verified"
}
```

Dates shown are guidance: verify actual source timestamps. The agreement date and official completion date are distinct. A multi-team trade is **one canonical transaction node** with multiple player movements and assets, not unrelated fabricated one-for-one trades. Record reciprocal linkage without claiming every asset was directly exchanged for one specific other asset.

Required kinds of historical facts:

- **Player tenure:** player ID, team ID, start/end dates or season boundaries, sources and coverage; distinguish rostered versus actually appeared.
- **Shared team tenure:** intersection of two players' supported tenures; number of overlapping seasons only when sufficiently covered; championship teammate only with championship-roster evidence.
- **Transactions:** canonical event, involved teams, player movements, agreed/effective dates, multiple counterparties, original source and version.
- **Opponent history:** date-ordered historical matchups, playoff series, elimination result, venue, relevant year and source. Track **team** playoff revenge separately from an individual's return.
- **Coach relationships:** optional later, from supported team appointments; do not infer from headlines alone.
- **Event lifecycle:** scheduled matchup, played matchup, player available/active, player minutes/snaps recorded, cancellation, date, location and certainty.

Use stable player and team IDs, not text-name matching. Keep team identity history separate from current team names. Handle multi-team careers, a player returning twice to the same franchise, NBA Cup / regular season / playoffs, and relocations. Coverage and source timestamps must be explicit; an incomplete historical corpus means “first” is **unknown**, not “first.”

Potential DB implementation: read-only collection from existing canonical records, then a separately versioned relationship index / materialized archive as a planned migration. First demo can use pinned fixture JSON. No production schema migration until approved.

## Deliverable B: deterministic storyline candidate detector

Produce candidates from *game context + verified relationships + current roster/availability + dated results*:

```json
{
  "candidate_id": "nba:<game_id>:trade_reunion:<transaction_id>",
  "kind": "reciprocal_trade_reunion",
  "entities": {"teams":["HOU","PHX"], "players":["KD_ID","GREEN_ID","BROOKS_ID"]},
  "event_id": "<transaction_id>",
  "claim_scope": "scheduled_team_matchup",
  "headline_eligible": true,
  "as_of_utc": "<pre-tipoff cutoff>",
  "claims": ["<structured, audited claims>"],
  "evidence_ids": ["<immutable source references>"],
  "coverage": {"transactions":"complete","player_appearances":"partial"},
  "rank_features": {"recency":0,"role_prominence":0,"multi_party":0,"first_event":0},
  "reasons": ["<human-readable reason for reviewer, not public prose>"]
}
```

At minimum detect:

1. `former_team_matchup`: current player on Team A, documented past tenure on Team B.
2. `first_team_meeting_after_trade`: first *team-vs-team scheduled/game-played* matchup following a transaction, regardless of whether a traded player appears.
3. `first_return_to_former_arena`: former team's actual venue, only when a player's expected/actual participation supports the phrasing; mere scheduling can be named conditionally.
4. `first_actual_opponents_after_trade`: require both players **appearing on court** in the same game on opposite sides, and historical match coverage sufficient to establish first.
5. `reciprocal_trade_reunion`: both teams sent meaningful players in different directions in the *same transaction*, with optional trade counterparts named accurately.
6. `former_teammates_now_opponents`: verified shared tenure and current opponents; “first time” only with complete previous opponent-appearance history.
7. `playoff_series_rematch`: series identity, season and outcome, with sufficient source evidence.
8. `championship_or_franchise_milestone_connection`: supported team/player championship or notable tenure, never inferred from fame.
9. `historical_rivalry`: documented recurring head-to-head/series history; no invented emotional state.

The same game may generate several candidates but **one primary editorial lead**. Secondaries become context cards / paragraphs, not repetitive adjacent headlines.

**Critical lifecycle distinction:** 
- Nov. 24, 2025 HOU@PHX was the first *team meeting* after the Durant/Green/Brooks trade. Durant **did not play**. It must NOT be described as Durant playing his first game back in Phoenix. Official recap: https://www.nba.com/game/hou-vs-phx-0022500290 .
- Apr. 7, 2026 HOU@PHX was Durant's documented **playing return to Phoenix**. The postgame record can state the return and the result; a historical pregame replay may only state he is *expected* to return if availability supported it at that cutoff. Official preview: https://www.nba.com/suns/news/4-7-2026-suns-vs-rockets-game-preview ; NBA recap: https://www.nba.com/game/hou-vs-phx-0022501157 .

Never use postgame participation or outcomes in the pregame snapshot. A doubtful/inactive/scratch event must update or demote the candidate; preserve earlier pregame versions as historical records. Preserve status `scheduled`, `expected_to_play`, `active_confirmed`, `played`, `inactive`, `unknown`. Don't conflate traded-to-team with on-court opponent or presume everyone was traded to the same team by the same one-for-one transaction.

## Deliverable C: editorial ranking (more than statistical thresholds)

A relationship fact is not automatically the lead. Rank it alongside the existing story-angle candidates using an explicit, versioned rubric. The ranking is about **editorial importance**, never sports prediction accuracy, gambling EV or a psychological “revenge advantage.”

Suggested ranking features (deterministic, configurable):

| Feature | Intended effect |
| --- | --- |
| `relationship_strength` | Multi-season teammates, long team tenures or significant transaction connections usually matter more than a ten-day stint. |
| `event_prominence` | Major trade, multi-party roster shake-up, playoff elimination or championship history can outrank generic form. |
| `recency_and_decay` | First matchup after a major trade is highly salient; do not lead with the same old trade every meeting forever. |
| `novelty` | First *scheduled* meeting, actual player return, first *played* opposing appearance, first postseason meeting are different milestones. |
| `availability_certainty` | Do not hype a player-versus-player duel when either is out; use team-level framing or demote. |
| `matchup_stakes` | Actual postseason context, standings stakes and competitive relevance, verified independently. |
| `fan_relevance` | Optional favorite-team boost for display order, **not factual status**. |
| `evidence_quality` | Official source-backed claims preferred; incomplete/ambiguous coverage blocks strong milestones. |
| `prior_coverage_penalty` | A recently used storyline is not repeated verbatim at every game. |

Deterministic tie-breakers by priority, evidence strength, event time and candidate ID. Log all eligible/rejected candidates and the reason for selection. A genuine first meeting after a transformative trade can outrank generic “team X has won three straight”; it must not outrank an even bigger, better-supported angle by a rigid global rule. Assign complementary storylines to subhead/cards rather than printing two near-identical articles.

For 2025–26 Houston, test specifically that Phoenix's reciprocal trade receives a more specific headline than a generic "former team" mention, Golden State's playoff rematch and Durant's Warrior tenure can both appear without being conflated, and Oklahoma City's Durant relationship is separate from competitive standings stakes. Other ordinary Houston games should not be presented as bitter rivalry.

## Deliverable D: natural sports-language templates (plus anti-patterns)

Every claim must have: **who / relationship / previous team or event / relevant time / current matchup / certainty**. Prefer plain broadcast language. Relationship context should make the reader care about the matchup, not assert emotion without sourcing.

**Acceptable examples (as-of restrictions apply):**

> **More than a regular-season matchup:** Houston and Phoenix meet with the Durant trade still connecting both rosters. Durant came to the Rockets from the Suns, while Jalen Green and Dillon Brooks went to Phoenix in the same deal.

> **Durant's Phoenix return takes center stage.** He is scheduled to face the Suns, who traded him to Houston last summer, while former Rockets Green and Brooks now play for Phoenix. *(Only use “expected to play” when the cutoff-safe availability record supports it.)*

> **Houston meets a familiar playoff opponent.** The Warriors eliminated the Rockets in the previous postseason, and Durant's own history with Golden State adds another connection to the matchup. *(Use only with the verified prior series and valid current roster.)*

**Reject:**
- “Durant seeks revenge against a team that betrayed him” (unverified motive).
- “Green and Brooks seek to prove Houston wrong” (motive is not a transaction fact).
- “Durant makes his first Phoenix return on Nov. 24, 2025” (he was inactive).
- “First time facing the Suns since the trade” when only the teams met and Durant was absent.
- “Houston trades Durant for Green and Brooks” (direction reversed).
- “All 29 other NBA teams have bad blood with Houston” (unsupported generalization).
- “Former Rocket Jaylen Brown…” or other identity/team mistakes.
- Sentence collisions like “Phoenix offense scored 31 and 33 from him.”

Avoid habitual words like “revenge,” “bad blood,” “grudge match,” “personal,” “heated” unless there is **time-valid, attributed evidence**. Quotes from coaches/players can be stored as metadata with provenance, but do not fabricate quotations or copy publisher prose. Prefer a factual hook even when the story is compelling.

## Deliverable E: a single sports-memory fact powering several products

Expose one structured `storyline_event` with stable IDs and audit manifest. Reuse across:

- **Pregame preview:** lead paragraph + secondary context, linked to the real game.
- **Home feed:** 1–2-sentence “why tonight matters” card with label “Former teams / Trade reunion / Playoff rematch” and player/team images only when appropriately sourced.
- **Game detail:** three optional questions/polls derived from the matchup (e.g., “Which former Rocket will have the bigger night?” only if both players likely active). Local-only demo; do not fake vote counts.
- **Social graphic:** timeline of verified roster movements and two-side comparison; original LP design, no copyrighted team media used without a right.
- **Postgame recap:** callback to pregame history only when relevant to what actually happened; **not** “revenge achieved” based solely on a win.
- **Future SportsCenter-style rundown:** text segment referencing the same verified facts. Video sources are optional links/rights-cleared embeds only, not scraped highlights.

A daypart feed can resurface the same game as *pregame storyline → live result context → postgame consequence*, with each version pinned to an appropriate evidence cutoff and no duplicate spam.

## Suggested files and boundaries

Use existing project patterns, with names adjusted after inspection:

```text
backend/sports_relationships.py              # pure tenure, trade and shared-history graph logic
backend/sports_relationship_facts.py         # read-only historical facts, provenance/as-of filtering
backend/storyline_candidates.py              # deterministic candidate detection and ranking
backend/storyline_audit.py                   # independent relationship/wording/first-event checks
backend/story_engine.py                      # adapter only: collect, rank, render, preserve existing behavior
backend/test_sports_relationships.py
backend/test_storyline_candidates.py
backend/test_storyline_audit.py
backend/test_story_engine_relationships.py

docs/research/narrative-event-knowledge-2026-11-11-relationships/
  README.md
  source-inventory.md
  fixtures/*.json
  examples.jsonl
  evaluation.json
  decisions.md
```

Keep the relationship module independent from the postgame PR so it can later be consumed by PR #35 without coupling its publication gate to a draft branch. Provide the feed as a pure, versioned fact/format interface instead of hard-wiring it to one homepage page component.

## TDD requirements (tests first, before implementation)

1. **Trade direction:** 2025 official trade yields KD PHX→HOU, Green HOU→PHX, Brooks HOU→PHX. Reverse direction must fail.
2. **One transaction graph:** official seven-team transaction represented once, not false direct one-for-one player swaps; linked player movements retain identity.
3. **First team meeting ≠ first player appearance:** Nov. 24, 2025 team fixture may be “first meeting since the trade” but **not** Durant's on-court return.
4. **First playing return:** April 7, 2026 satisfies the historical Durant return once complete appearance records are established. A retrospective pregame story cannot use the postgame participation data.
5. **Unknown history:** missing older game/appearance coverage does not allow “first-ever” or “first time since” without a bounded, provable reference period.
6. **Availability updates:** late inactive scratches remove/suppress a player-duel claim, optionally keep trade-level team angle; original frozen preview remains unchanged.
7. **As-of:** later-sourced facts and future trades cannot enter a prior pregame preview; stable historical backfills need demonstrable original publication before cutoff.
8. **Historical teammates:** Brown/Tatum or any chosen verified case correctly identifies shared tenure and that opponents are now on different teams, with no unsupported “first on court” claim.
9. **Golden State:** Rockets' playoff elimination and Durant's prior team membership are separate, composable candidates with different evidence IDs.
10. **Oklahoma City:** Durant's former-team connection can coexist with standings context, without fictional rivalry/psychology.
11. **No fake universality:** a normal matchup with no meaningful connection leaves the current records/form story intact.
12. **Temporal decay:** later repeated games reduce novelty; original trade may remain context without dominating every lead.
13. **No current-form leakage:** old-team stats stay out of recent-current-team stat arrays. Historical tenure extraction does not modify `_db_player_facts` form definition.
14. **Team/player identity:** duplicate names, reused team aliases and multiple tenures remain correctly joined on stable IDs.
15. **Candidate transparency:** selected and omitted candidates, evidence, rationale, event/capture dates and rank features saved for internal audit.
16. **Postgame:** no future score/boxscore/PBP in a pregame preview; correct on-court story after final, if supported.
17. **Prose:** banned emotional claims, reversed trade phrasing and unstable “first” assertions are rejected; sport-specific broadcast language templates pass.
18. **Idempotence:** identical input facts, as-of and code version produce byte-for-byte stable stories and candidate ordering.
19. **Runtime:** pure engine makes zero network/model calls. Historical collector only uses allowed local read-only data; no writes or additional ESPN polling inside story generation.
20. **Regression:** all existing `story_engine`, audit, rubric, runtime and story endpoint tests still pass.

Use fixture-driven mutation tests: invert one trade direction, remove an appearance, insert a post-cutoff article, change venue, hide older seasons, swap player IDs, or scratch a player. Each must deterministically suppress the unsupported claim.

## Editorial evaluation and acceptance

- Minimum **12 real, independently sourced NBA test games** across trade reunions, former teammates, player returns, postseason rematches and boring controls. Include the HOU–PHX 2025-26 sequence and Brown–Tatum if both relationship and game data are independently confirmed.
- Preserve a **frozen held-out set of 50 NBA games** where archive coverage is good enough. Separate `supported storyline existed but not detected`, `detected but outranked`, `rendered awkwardly`, and `source was unavailable before cutoff`.
- Report precision of *claims*, relevant-storyline recall, correct milestone classification, lead-selection agreement with blinded human reviewers, repetitive-lead rate, and benchmark difference against current `select_story_angle`. Never conflate automated stylistic scores with fan judgment.
- Provide side-by-side **before vs after** pregame stories for 12 games, plus factual manifests and reasons why each angle won or lost.
- The new system must still perform in milliseconds-to-low-tens-of-ms on the existing CPU host for precomputed historical index lookups; measure actual median and p95, not guessed speed.
- Use the existing pastel rubric, but add **relationship claim integrity** and natural sports-language tests; don't change historical score interpretations silently.
- Commit to a reviewable feature branch, include exact reproducible commands and artifacts, open a draft PR. **Do not merge or deploy**. The user reviews copy and relationship evidence first.

### Definition of done

The agent can replay a past NBA game at an explicit *pregame* cutoff and explain why it was interesting **before the tip**, distinguishing transactions, former teammates, team playoff history, and actual player appearances. For the Rockets–Suns case it names Durant/Green/Brooks in the right trade directions, chooses a relevant lead, handles Durant's Nov. 24 absence, and carries the history forward appropriately to April 7 without leaking outcomes. The same verified event yields a preview, a home-feed card and an optional postgame callback, all without a per-story model.