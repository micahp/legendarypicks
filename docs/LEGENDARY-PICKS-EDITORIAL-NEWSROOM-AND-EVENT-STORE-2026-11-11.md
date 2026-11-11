# Legendary Picks Editorial Newsroom & Editorial Event Store

**Status:** Proposed implementation plan; not built by this document  
**Date:** 2026-11-11  
**Owner and Editor-in-Chief:** Legendary Picks founder  
**Repository:** `micahp/legendarypicks`  
**Scope:** Original, clickable sports articles; daily and weekly league editions; a shared evidence-backed editorial event store; newsroom role contracts; internal editorial controls.  
**Priority:** Reuse the existing news pipeline and sports data before adding new collectors or AI agents. No code, schema, production configuration, or deployment changes are authorized by this documentation alone.

## 1. Product thesis

Legendary Picks should be a living sports newsroom, not only a prediction dashboard or a collection of automatically generated box-score summaries.

The product must answer, on the homepage **without a required click**:

- What happened across the sport or league?
- What changed in the playoff race, rankings, rosters, standings or expectations?
- Why does it matter to people following the sport?
- What is likely to matter next, including where LP has a legitimate model-based perspective?
- Where can a reader open the original LP article, its supporting statistics and related games?

Readers can open a fully developed original article at an LP URL; the homepage shows headline, image (rights-cleared), useful excerpt, and context. **Editorial typography leads.** Do not make giant numerals compete with article headlines on small cards. Use numbers inside analysis, tables, annotated charts, or clearly subordinate metadata. One spacious lead card is acceptable; supporting stories should look like ordinary editorial teasers, not dashboard KPIs.

Coverage is **not restricted to individual games**. The newsroom publishes cross-game and non-game reporting:

- NBA nightly/morning league recap.
- NFL weekend review, trade-deadline developments and roster consequences.
- NCAAF weekend review, AP Top 25 versus CFP rankings, playoff projections clearly separated from official rankings, format changes with effective season.
- MLS matchday/weekend review, table and playoff implications.
- Ongoing conversations such as expansion, league policy, economics and historical rivalries.
- Original data reporting from LP's game logs, simulations, rankings, performance evaluations and event-level facts.

Editorial outputs are a reusable inventory for the homepage, article-detail pages, social graphics, newsletters, and **later** a personalized sports-show rundown. Video, branded anchor voices and game footage are outside this first iteration and require rights/permissions.

## 2. Existing implementation: preserve and extend

**Read the actual current branch before implementation.** `docs/PLAN-league-news-engine.md` is a history of changing design decisions, not proof that every described component is active. In particular, `scripts/news-collect.sh` says the formerly proposed league-summary pass was reverted. Reconfirm the live/development deployment state rather than assuming that `dev` equals production.

| Existing component | Value to reuse | Caveat |
|---|---|---|
| `backend/ingest_league_news/` | ESPN news-feed metadata, RSS and authorized social input collection; `news_items` | Provider access is not a license to republish/train on full article bodies; current fetcher has an optional ESPN full-story route requiring rights review. |
| `backend/discover_topics.py` | Discovery of recurring discussions; candidate/approval history | Ongoing conversation discovery is **not** enough for a one-day event-driven editorial agenda. |
| `backend/ingest_league_narratives/` | Source-linked narrative cards, editorial feedback examples, batch drafting | These are conversation summaries, not full original articles; review existing prompts and source rules. |
| `backend/news_quality.py` | Ranking, deduplication and source quality heuristics | Being newsworthy does not establish a factual claim. |
| `backend/routers/news.py`, `pages/news.tsx` | Existing News API and league-oriented surface | Add an article product alongside it; avoid breaking current endpoints. |
| `news_items`, `news_narratives`, `news_narratives_runs`, `news_conversations`, `news_topic_candidates`, `news_card_feedback` | Existing persistent source/candidate/edit-history data | Do not duplicate or overwrite this history. |
| `backend/ingest_scoreboards.py`, normalized box scores, PBP and player logs | Game and league fact inputs | Snapshot coverage and completeness must be explicitly checked by league. |
| `backend/story_engine.py`, `backend/story_engine_audit.py` | Deterministic pregame narrative and independent fact audits | Do not conflate a valid pregame claim with valid postgame writing. |
| Draft postgame PR #35 (`research/postgame-content-demo`) | Research postgame recaps/feed adapters and experiments | Verify head and review status; do not treat draft branch as deployed code. |
| `docs/NATURAL-SPORTS-COMMENTARY-EVALUATION-2026-11-11.md` | Separate human/structural prose evaluation plan | Naturalness is separate from source integrity and editorial relevance. |
| `docs/HISTORICAL-RELATIONSHIPS-RIVALRIES-2026-11-11.md` | Proposed relationship history and story selection rules | Reuse once implemented; preserve as-of and appearance distinctions. |

**Baseline requirement:** Produce an explicit inventory with exact file versions, DB coverage by league, available rights-safe source fields, current collection cadence, actual published surfaces, and development-vs-production differences. No speculative "we already have all the data."

## 3. Editorial organization and authority

Logical roles are **functions with typed inputs/outputs and permissions**, not necessarily separate autonomous LLM processes. The majority can be deterministic jobs or Python services.

### 3.1 Editor-in-Chief (human: founder)

- Sets the newsroom's coverage priorities, editorial policy, publication standards, house voice and league emphasis.
- Accepts/rejects article proposals; overrides story selection and homepage hierarchy.
- Reviews initial complete articles, features, consequential breaking news, interpretive columns and corrections.
- Can grant narrow future auto-publication permissions **by content class** after measurable QA.
- Reviews flagged missed storylines and provides positive/negative example feedback.
- Can pause a desk, require revision, unpublish an article with retained audit history, or initiate corrections.
- Receives a summary of **why** stories were recommended and what evidence is missing; should not be forced to inspect agent internals.

### 3.2 Managing Editor (coordinator)

**Inputs:** event candidates, topic/discovery signals, deadlines, league calendar, historical articles, QA outcomes and the EIC's current priorities.

**Outputs:** a versioned daily budget; `editorial_assignments` with article type, primary writer, research dependencies, desired angle, planned publish window, and status.

**Rules:** Prioritize noteworthy changes; dedupe overlapping stories; protect lead-story diversity; avoid an article whose source evidence is too thin; escalate controversies; never independently publish beyond delegated policy. The Managing Editor assigns tasks but doesn't manufacture reported facts.

### 3.3 Specialist desks

| Role | Responsibility | Output contract / important boundary |
|---|---|---|
| Breaking-News Reporter | Verified trades, official decisions, injuries, staff moves, rules, rankings releases | What happened, who confirmed it, when effective, affected entities and next steps. Reports require source receipts; no rumor elevated into a confirmed event. |
| Beat Reporter | Team/player context, availability, rosters, relationships, rivalry history | Context dossier tied to canonical player/team identities. No invented quotes, dressing-room access or insider sourcing. |
| League Analyst | Standings changes, competition dynamics, playoff/ranking implications, next slate | League context note using correct season/competition rules and ranked snapshots. Separate official rankings from LP projections. |
| Data Journalist | Outlier discovery, cross-game comparisons, model receipts, explainable visualizations | Reproducible query, denominator, cohort, source cutoff, chart spec and numerical claim IDs. No unvalidated model causality. |
| Features Writer | Player arcs, history, relationships, contextual explainers | Longer narrative arc built from sourced events, chronology and meaningful human context; no fictional interviews. |
| Columnist | Clearly labeled interpretation and competing views | Evidence-backed analysis, not ungrounded hot takes or manufactured consensus; editor approval required. |
| Copy Editor | Clarity, sports voice, grammar, composition, redundancy | Revision proposal with highlighted changes; no silent changes to factual meaning; follow naturalness evaluation spec. |
| Standards & Fact Editor | Independently recomputes claims and verifies sources, timing, identity and rights | Separate claim-by-claim audit and block/review decision; cannot trust writer's own self-check as independent verification. |

**Order of work:** A news event can be discovered once, enriched by several desks, and written by one primary author. Do not make every role re-fetch the same web articles. Any model-assisted draft must be attributed as LP editorial content; do not invent human journalist personas.

### 3.4 Agent execution model

- Default = scheduled batch collection → canonicalize events → candidate ranking → editorial assignments → evidence bundles → writing/templating → independent QA.
- Deterministic data extraction, arithmetic, entity joining, scoring and template rendering should run on CPU with no per-story LLM call.
- Where a nuanced original long-form draft benefits from an LLM, make that an **optional, budgeted drafting step**, not a dependency for game recaps, source gathering, or correctness gates.
- Reuse historical good/bad editorial marks as optional review examples with explicit versioning. A prompt is not an authority over structured evidence.
- Failed collectors or drafts should retain prior accepted content or show “awaiting verification,” never fabricate a new story to keep cadence.
- The EIC may edit the agenda or reject an article at any stage. Keep append-only decisions.

## 4. Editorial Event Store

The store is the **normalized factual layer between collectors and writers**, not a second sports database and not a warehouse of copied article text.

### 4.1 Bounded contexts

1. **Raw source observations:** immutable references to provider items, capture times, permitted excerpts, link/rights metadata, raw payload fingerprint (if retention allowed).
2. **Canonical events:** who/what/where/when/competition, type and current state.
3. **Canonical entities:** team, player, coach, conference, competition and event IDs; links to existing LP identities.
4. **Verified claims:** numerical/semantic assertions with claim type, supporting observations, computation and confidence/evidence status.
5. **Event relationships and storyline timelines:** connected trades, former-team returns, playoff history, recurring league debates, rankings progression.
6. **Assignments, editions and publications:** downstream versioned decisions and articles; do not force publication state into the event table.

### 4.2 Initial event types

`game_final`, `game_live_milestone`, `player_performance`, `team_streak`, `trade_confirmed`, `signing`, `release`, `injury_status`, `coach_change`, `rankings_release`, `playoff_field_change`, `rules_or_format_decision`, `playoff_result`, `historical_relationship`, `official_announcement`, `ongoing_conversation_update`.

Declare a subtype schema and mandatory source/verification gate for each; don't store unstructured free-text events as fact. Speculation and opinion may be tracked as **claims about what a named speaker said**, not promoted to confirmed events.

### 4.3 Recommended tables (design, not an immediate migration)

| Proposed entity | Primary purpose |
|---|---|
| `editorial_source_observations` | Provider IDs, URL, retrieval/publish timestamps, terms/rights, permitted metadata, source fingerprint and observation status |
| `editorial_events` | Event ID/type/league/status, effective time, announcement time, current version and source-of-record |
| `editorial_event_versions` | Append-only changes/corrections/supersessions with input/source fingerprints |
| `editorial_event_entities` | References to canonical LP players, teams and competitions, including role and direction for a transaction |
| `editorial_claims` + `editorial_claim_evidence` | Atomic claims, recomputation method, source links, status and cutoff |
| `editorial_event_links` | Relation typed edges, e.g., caused-by, updates, former-team, opponent-rematch, ranking-impact |
| `editorial_assignments` | Proposed story idea, lead angle, role assignments, EIC edits, deadline and status |
| `editorial_editions` + `editorial_edition_entries` | Daily/weekly/competition editorial budgets, included developments, dedupe and ordering |
| `editorial_articles` + `editorial_article_versions` | Stable article IDs/slugs, original authorship attribution, revisions, approval, publishing/corrections and provenance |
| `editorial_reviews` | Separate fact, angle, naturalness, rights and human-editor verdicts |

Keep `news_items.url` dedupe and existing game IDs as source references; do not copy all play-by-play and player logs into the editorial tables. Use SQLite first if appropriate to LP's host and load, with read-only extraction and a small transactional writer. Evaluate performance and concurrency before changing storage engines.

### 4.4 Temporal and identity contract

Every event/fact must distinguish as applicable:

- `occurred_at`: when the event occurred.
- `announced_at` / `published_at`: when its source first published the information.
- `effective_at`: when a transaction, policy or playoff rule takes effect.
- `observed_at`: when LP actually captured it.
- `as_of`: time of the article's evidence cutoff.
- `source_last_modified_at`: if publisher supplied it.
- `snapshot_id` / `input_sha256`: immutable replay linkage.

A historic backfill observed today is not proof that LP knew the information at yesterday's pregame cutoff. Allow reproducible historical claims when publication evidence supports them; keep `unknown` separate from false and zero.

Do not infer canonical entities from bare names if multiple identities or teams are plausible. Transactions require signed/directed moves and complete or explicitly partial trade-package representation. A first **team meeting** is not a first **player appearance**, and a scheduled return is not a completed on-court return.

### 4.5 Example (synthetic; not a real transaction)

```json
{
  "event_id": "nfl:trade:provider-event-id",
  "event_type": "trade_confirmed",
  "league": "nfl",
  "state": "confirmed",
  "occurred_at": "2026-11-10T20:00:00Z",
  "announced_at": "2026-11-10T20:05:00Z",
  "effective_at": "2026-11-10T20:00:00Z",
  "observed_at": "2026-11-10T20:11:00Z",
  "entities": [{"type": "player", "id": "canonical-player-id", "role": "moved"}],
  "evidence_ids": ["publisher-record-id"],
  "storyline_links": ["former-team-matchup-id"],
  "verification": "pending-independent-audit"
}
```

The numbers/timestamps are illustrative; do not seed production with this object.

### 4.6 Source hierarchy and rights policy

- **Primary:** Official league, team, committee, conference, competition and transaction records; permitted statistical data; original LP analysis.
- **Secondary:** Authorized news-feed metadata; independent beat reporting; licensed text; editorial references, with original links/bylines.
- **Social:** Leads, reaction or direct attribution when the original poster/source is verifiable. A viral post alone is not official confirmation.
- **Speculation:** Track separately, explicitly labeled, never presented as a completed trade or confirmed decision.
- **Conflicts:** Maintain both source claims, timestamp the disagreement, refuse a definitive headline until independently settled.

Free-to-read **does not make third-party article bodies, images, video, or AI training corpora free to reuse**. The existing ESPN full-text fetch capability is a technical possibility, not an authorization. For production retrieval/training, respect provider licenses/terms and seek permission where required. Use metadata/permitted feeds and source links for discovery, and write **original prose** from independently established facts. Do not imitate a named living journalist's distinctive style, invent quotes, republish full ESPN articles, or rehost unlicensed game footage. Review image licensing separately.

## 5. Story discovery and editorial decision

The Managing Editor combines two different queues:

- **Event queue:** verified changes (rankings release, trade, game outcomes, injury, schedule announcement) which need timely reporting.
- **Conversation queue:** recurring issues (expansion, realignment, media rights, historical rivalries) which may merit an explainer, feature or ongoing update.

Generate explicit candidate records such as:

```text
candidate_id
event_ids / conversation_id
league, edition_window, format
proposed_angle, why_now, affected_entities
evidence_coverage, missing_facts
news_impact, novelty, historical_significance, relevance
current_similar_articles, duplicate_risk
draftability_status, rights_status
proposed_priority, explaining_factors, editor_override
```

Prioritize a **story** rather than the largest number. A 24-team playoff format announcement may matter more than an ordinary final score. A Brown–Tatum first-opponents reunion can be a better pregame lead than either player's recent scoring average. No made-up “revenge” motivation or unsourced “everyone is talking about it.”

Ranking requirements:
- Do not conflate AP poll rank, CFP committee rank and LP-projected playoff seed.
- Do not conflate a projected CFP bracket with a confirmed format change; include `effective_season`.
- Rank stories across leagues without forcing a quota or generating fluff.
- Show the EIC why a lead was chosen and which stronger alternatives were rejected.
- Detect topic overlap across a trade-deadline roundup and separate deal-specific articles. Link them rather than publishing duplicate paragraphs.

## 6. Article and edition formats

### Individual article types

| Type | Required structure | Example |
|---|---|---|
| Breaking news | Direct headline, confirmed development, participants/terms, context, next update | Completed NFL trade |
| Matchup preview | True pregame hook, historical context, current form, model context with bounds | Former teammates meet as opponents |
| Postgame recap | Result, turning point **if proven**, standouts, consequences and what follows | NBA final |
| League analysis | Situation, ranked/compared evidence, implications, relevant caveats | AP vs. CFP comparison |
| Data feature | Question, method, source/cohort, chart, finding, limitations | NFL play-calling shifts |
| Explainer | What changed, effective dates, stakeholders, rules, open questions | CFP format change |
| Clearly labeled column | Specific supported thesis, relevant counterpoints, stated interpretation | Impact of a confirmed change |

### Recurring league editions

**NBA Morning Report:** all previous-night finals, chosen main story, genuinely notable individual performances, trends and tonight's slate.  
**NBA Pregame:** upcoming matchups, meaningful history, roster availability and model forecasts.  
**NFL Weekend Review:** results across the slate, standings/playoff implications, decisive events and next week's questions.  
**NCAAF Weekly:** important results, AP vs. CFP movement, conference context, legitimate implications and future fixtures.  
**CFP Rankings Edition:** frozen official rankings, movement from prior list, who is in/out, AP/committee disagreement, separate LP projections, official format effective year.  
**NFL News/Deadline Edition:** finalized transactions, trade terms, affected teams, player production, roster context, developments after the deadline.  
**MLS Round Review:** game outcomes, table and playoff changes, next matchups and verified competition rules.

**An edition is not an arbitrary concatenation of game recaps.** It selects a lead with a through-line and uses supporting sections with game links, statistics and official developments. A good league edition may link to three game articles and one breaking-news article while supplying original cross-game analysis.

### Publication data contract

At minimum: `article_id`, slug, league(s), content type, headline/deck, section blocks, actual underlying source and claim IDs, chart specifications, related event IDs, evidence cutoff, versions, publisher/byline policy, review statuses, approved-by human if applicable, published timestamp, updated timestamp, corrections list, and rights metadata.

Use stable `/news/articles/[slug]` (or another explicitly reviewed route), proper canonical URLs, open-graph/social summaries and accessible mobile layout. Links from the homepage lead to **actual LP article pages**, not a stub or a recycled source link. Related underlying box scores, model pages and data visualizations remain available.

## 7. Editorial production and permissions

```text
Collectors / sports DB / official schedules
    -> source observation + canonical event resolution
    -> independent evidence / identity / time checks
    -> candidate generation and Managing Editor assignment
    -> desk-specific evidence package
    -> structured story plan
    -> draft original article
    -> Copy Editor + independent Standards/Fact Editor
    -> Editor-in-Chief approval (initial policy)
    -> versioned publishing + homepage/league feed
    -> revisions, corrections, post-publication monitoring
```

Statuses: `proposed`, `assigned`, `researching`, `draft`, `copy_review`, `fact_review`, `needs_changes`, `awaiting_eic`, `approved`, `published`, `updated`, `corrected`, `withdrawn`.

Separate independent approvals:
- **Fact integrity:** blocked / needs-audit / passed.
- **Story selection:** weak hook / viable / preferred (human or clearly labeled rubric).
- **Naturalness:** structural issues + human ratings; never equate a heuristic proxy to human quality.
- **Rights:** authorized / limited / missing.
- **Publication:** explicitly human-approved for first releases.

Every claim-bearing text block must be traceable to a fact bundle or explicitly attributed opinion. No unsupported claims get published. Successful mechanical checks do not silently grant editorial approval.

**Corrections:** Never rewrite an old published record without a version. Show material corrections and the update date; retain the linked source and corrected claim.

## 8. Editor-in-Chief control surface

Create an internal newsroom surface (authenticated/authorized, not publicly writable) with:

1. **Newsroom:** live candidate list, what changed, desk assignment, evidence availability, publish deadline and clear suggested lead.
2. **Review:** full article preview, before/after copy, chart/data provenance, checks, coverage gaps, EIC approve/reject/reassign/rewrite note.
3. **Editorial performance:** false claims, missed hooks, repeated templates, reading quality, publication latency, corrections, clickthrough and user feedback; separate quality from traffic.
4. **Direction:** per-league priorities, approved example stories, negative examples, active controversies, production quotas (if any), allowed auto-publish classes.

The founder can override a rank or reject an entire edition without editing code. Approval/denial must be versioned and auditable. Do not make the system “learn” by unbounded unsupervised prompt mutation.

## 9. Acceptance plan and initial implementation sequence

### Phase 0 — Audit and preservation

- Confirm current `dev`, production, draft PR #35, actual news collectors and scheduling.
- Inventory schema/coverage for `news_items`, news narratives, ESPN metadata, game snapshots, player logs, PBP, ranking archives, transactions and source licensing.
- Freeze a known-good research corpus. Identify missing historical version/temporal fields.
- Deliver a gap matrix: **available / partial / absent / rights-limited** per article type.

### Phase 1 — Minimal Editorial Event Store

Implement normalized source observations, canonical event IDs, atomic evidence claims, as-of replay and append-only revisions using existing DB where practical. Initial types: `game_final`, `trade_confirmed`, `rankings_release`, `rules_or_format_decision`. No broad generic knowledge graph or new distributed infrastructure yet.

**Gate:** Can replay each event and verify source identity, direction, date, cutoff and corrections without contacting publishers during rendering.

### Phase 2 — Managing Editor and assignment queue

Use transparent rules to propose and rank article ideas, select editions and avoid duplicates. EIC can approve or override the assignment. Add no autonomous production publisher.

**Gate:** Explain why a ranking release outranks a routine score, why a trade-specific story belongs in a deadline roundup, and why an unsupported rumor is not eligible.

### Phase 3 — First three desk-produced article drafts

1. **NCAAF:** November 2026 AP Top 25 / CFP ranking differences and a distinct verified playoff-format explainer with correct effective year.
2. **NFL:** November 2026 trade-deadline roundup with confirmed player movement, terms, team history, and sourced impact comparisons.
3. **NBA:** November 10, 2026 league-wide nightly recap using actual finals and player/sequence evidence, with a relevant historical reunion if supported.

Each deliverable includes headline, deck, full body, at least one **meaningful** data table/chart, source appendix, selected/rejected story angles, and linked game/roster/model references when applicable.

**Gate:** Three substantially different original articles, not three templated restatements of the same game summary. Missing key facts are disclosed rather than invented.

### Phase 4 — Independent editorial QA and review UI

Integrate the fact-audit and `NATURAL-SPORTS-COMMENTARY-EVALUATION` specification as separate tracks. Human comparison against archived legacy writing or authorized source examples with matched cutoffs; record actual reviewer scores. No fake “human verified” labels.

**Gate:** No critical unsupported fact; coherent readable article; claim-and-section provenance; EIC review and correction path.

### Phase 5 — Actual clickable publication

Add public article pages and homepage teasers matching Legendary Picks `#0f0f11` / zinc / emerald design; feature headline and excerpt over decorative KPIs. Keep one full-size lead story; supporting cards use readable thumbnails and text. Wire accepted article IDs into the four homepage states and league editions.

**Gate:** Reader can open and read all three original articles on LP from homepage and News tab, and access the underlying supporting facts.

### Phase 6 — Expand roles and distribution

Add Beat Reporter, Features Writer and Columnist when the first writers and evidence flow work. Then reuse approved content for newsletters, statistical graphics, and eventually personalized show runbooks. Video/voice/footage licensing remains a separate product/legal gate.

## 10. Test-driven engineering checklist

Tests must be written before the corresponding new functionality, alongside existing news, pregame and postgame regression suites.

1. Two copies of the same source URL map to one observation/event without silently collapsing conflicting versions.
2. Repeated ingestion is idempotent; corrected publisher information creates an append-only event version.
3. As-of replay refuses future article/source facts and future rankings into earlier articles.
4. `announced_at`, `occurred_at`, `effective_at` and `observed_at` remain distinct.
5. Stable canonical IDs link players to correct teams at the correct date, including reciprocal multi-team trades.
6. Official CFP vs. AP ranking, historical rank movement, LP projection and format effective season cannot be swapped or mislabeled.
7. Pre- versus postgame narrative builders do not leak final scores or later injury information.
8. Game summaries only infer turning points from complete, reconciled PBP; otherwise use verified final/box-score level facts.
9. Score/numeric/statistical chart values independently recompute from pinned inputs with sample sizes.
10. News discovery keeps rumors, third-party social reposts and unverified allegations out of confirmed-event headlines.
11. Two related articles share an event but have different editorial purpose; dedupe blocks copy clones.
12. Explicit source rights metadata suppresses non-licensed images, clips, article bodies and forbidden stored excerpts.
13. Existing `/api/news` contract remains functional and old news history is unchanged.
14. Editorial roles cannot approve their own fact verification as an independent check.
15. A failed model/collector leaves prior approved content stable, not falsely “updated.”
16. Initial publication is rejected without EIC approval; status transitions are tested.
17. A material correction leaves published version history and visible correction note intact.
18. The Brunson-style semantically incoherent sentence fails the naturalness track even when its numerics are valid.
19. Brown–Tatum historical context gets considered as a lead candidate when sourced; absence/incomplete history suppresses unsupported “first.”
20. Desktop and mobile layouts have no overflow, headline/numeric visual collisions, unclickable article cards or empty article destinations.
21. Replaying same fixture+versions yields stable outputs, with volatile timestamps excluded from deterministic content hashes.
22. No network access or GPU dependency is required to render, fact-check or replay a pinned editorial fixture.

## 11. Measurements and stop/go criteria

- **Coverage:** eligible event-to-article ratio by type, missing-data reasons, league/day/week coverage and edition diversity.
- **Facts:** claim count, independent audit pass/blocks, source-conflict count, corrections and evidence completeness.
- **Editorial selection:** percent of major human-labeled developments surfaced, missed-hook rate, duplicate-angle rate and EIC overrides.
- **Naturalness:** structural errors, human reviewer preference, sentences requiring revision and repeated template patterns; do not manufacture human ratings.
- **Operations:** collection freshness, article generation p50/p95 on actual CPU host, estimated cost per *approved* article, failed job/recovery rate.
- **Engagement:** article opens, depth of reading, return visits and downstream exploration of LP statistical/model pages; interpret separately from article quality.

**Go/no-go for demo:** 3 completed, original, independently audited, source-backed articles with useful data graphics, substantive league context, correct cutoffs, distinct editorial structures, versioned drafts, EIC-controlled review, and functioning article URLs in an isolated development environment. No merge/deploy from this plan alone.

## 12. What NOT to do now

- Don't launch nine independently browsing/charging agents.
- Don't make arbitrary quotas that create artificial stories or needlessly pad an edition.
- Don't rebuild `news_items` or replace the existing News page to prototype article pages.
- Don't copy/rehost ESPN/AP articles or game clips as original LP work.
- Don't invent bylines, interviews, attributed fan opinions or video rights.
- Don't equate “free product” with permission to use third-party copyrighted material.
- Don't change live publishing gates, approve stories on the EIC's behalf or silently publish on a schedule.
- Don't change official rankings/format rules into LP forecasts without explicit labeling and validated models.
- Don't spend a PR on this document. Code implementation later can use normal review.

## 13. Adjacent specifications and handoff

- `docs/PLAN-league-news-engine.md` — existing editorial-news system history and initial business intent.
- `docs/NEWS-DISCOVERY.md`, `docs/NEWS-FEEDBACK.md` — conversation discovery and founder feedback.
- `docs/HISTORICAL-RELATIONSHIPS-RIVALRIES-2026-11-11.md` — historic player/team storylines.
- `docs/NATURAL-SPORTS-COMMENTARY-EVALUATION-2026-11-11.md` — separate semantic sports-voice QA.
- Draft PR #35 — postgame fact/story/feed research to integrate only once its claims, gates and status are reviewed.

**Implementation instruction:** Audit the actual repository, identify reusable modules, then implement the smallest Editorial Event Store and desk pipeline that can produce the three example articles. Report what was reused and what was missing. Return a reproducible demo, evidence manifests, exact replay commands, human-readable editorial review, and an honest list of unimplemented capabilities. Submit implementation as a reviewable code change later; do not merge or deploy without approval.
