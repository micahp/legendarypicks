# Legendary Picks: Enhanced Deterministic Game Previews

**Status:** Implementation brief, not shipped  
**Date:** 2026-11-11  
**Owner:** Founder / Editor-in-Chief  
**Scope:** Move from 1–3 sentence pregame summaries to original, fact-checked, readable, matchup-specific previews that can compete on usefulness with ESPN / AP–Data Skrive automated previews while adding Legendary Picks' own historical and quantitative depth. No per-game LLM dependency and no production activation without approval.

## 1. Product and editorial objective

Generate **two products from the same pregame evidence bundle**:

1. **Compact preview:** 1–3 natural sentences for scoreboard/game cards, with one real hook and the most useful secondary fact. Keep the existing game-detail API contract unless a deliberate versioned change is approved.
2. **Full editorial preview:** A self-contained, clickable Legendary Picks article with headline, deck, 3–6 substantive short paragraphs or properly structured sections, player and team context, matchup questions, attributed facts, optional LP model view and a relevant statistical graphic.

This brief is for **automated baseline game coverage**, an additional desk within the larger Editorial Newsroom plan. Exceptional matchups can be promoted to enhanced feature treatment by the Managing Editor. Routine games still deserve accurate, helpful previews without artificially filling space.

Editorial quality = correct facts **AND** the right story **AND** naturally expressed sports language. The source's status and data coverage determine what the article may say; a larger dataset does not justify dumping every available number into prose.

Avoid ESPN visual imitation or recycling its text. Its automated previews are a useful **format/coverage benchmark**, not licensed training data or production source text.

## 2. Verified case study: Golden State Warriors at Houston Rockets, November 11, 2026

**Pinned evaluation moment:** November 11, 2026, **before scheduled tipoff**, with separately recorded `as_of` and evidence capture timestamps. This is a demonstration of what information a pregame generator should select, **not** permission to insert postgame results later.

**Game identity:** ESPN game 401909974; NBA game 0022600225; Wednesday, November 11, 2026, 9:30 p.m. ET (8:30 p.m. CT); Toyota Center, Houston; televised nationally on ESPN. Both clubs entered the matchup 8–3 according to ESPN's November 10 preview. Verify the LP/ESPN/NBA canonical game crosswalk before building the fixture.

**Warriors storyline:** Golden State lost its opening three games and then won eight straight. This is an especially striking **early-season turnaround**; it is not proof of long-term playoff strength after only 11 games.

**Stephen Curry:** Recognizable headline draw and current lead scorer; a November 10 wire preview reported 30.6 PPG. Verify this directly from pregame player logs before rendering the number.

**Yaxel Lendeborg is NOT undrafted.** Golden State drafted the Michigan forward **11th overall in the 2026 NBA Draft**. NBA's player page listed **21.4 points, 7.2 rebounds and 4.0 assists per game** through his first 11 NBA games, before this matchup. Recent verified game logs show 37 points against the Clippers on November 1 and 23 points in each of his two most recent games, November 7 (Orlando) and November 9 (New Orleans). This recent emergence is a major *supporting* storyline and may be the centerpiece if ranked above the streak by editorial review.

**Latest example:** Golden State beat New Orleans 138–87 on November 9. Curry and Brandin Podziemski each scored 25 points; Lendeborg had 23. Contemporary coverage highlights the team's improved depth and ball movement. Don't infer on-court cause from a box score alone.

**Houston counterpoint:** The Rockets also enter at 8–3. They beat Denver 110–100 on November 9 with Kevin Durant and Alperen Sengun contributing; verify actual lines from the same cutoff-safe box score. Adams and Capela injuries affect available frontcourt depth, subject to the latest pregame injury report and timestamp. Durant's Warriors history is another source-supported angle but must not displace current-team matchup context without editorial justification.

**National broadcast:** ESPN's official 2026–27 schedule confirms the 9:30 p.m. ET telecast. A nationally televised game is a **distribution/reach signal**, not automatic proof of playoff stakes, unusually high importance, or an available video license.

### Source references for the pinned fixture

These links are **research references and cross-check targets**, not blanket authorization to store/reproduce their article bodies.

- ESPN source preview: https://www.espn.com/nba/preview/_/gameId/401909974
- Official NBA game page: https://www.nba.com/game/GSW-vs-HOU-0022600225
- Official ESPN/ABC 2026–27 broadcast schedule: https://espnpressroom.com/press-release/espn-abcs-star-studded-2026-27-nba-regular-season-broadcast-schedule/
- NBA 2026 Draft: https://www.nba.com/draft/2026
- NBA Lendeborg player bio / game logs: https://www.nba.com/player/1642865/bio
- NBA Warriors official draft coverage: https://www.nba.com/warriors/news/yaxel-lendeborg-brings-championship-pedigree-and-do-it-all-approach-to-warriors-20260623
- NBA.com turnaround analysis published November 10: https://www.nba.com/news/4-takeaways-warriors-historic-turnaround
- November 10 wire pregame coverage: https://fieldlevelmedia.com/nba/streaking-warriors-having-fun-begin-road-trip-at-rockets/

**Evidence rules:** Reconstruct numerical values from LP's historical cutoff-safe data if available. Archive provider IDs, article publication metadata, source URL, fact ID and exact as-of. A third-party page edited later is not sufficient to prove historical availability before tipoff. Identify source gaps explicitly.

### Sample intended editorial output (illustrative, not a published article)

**Headline:** Curry, Lendeborg and the streaking Warriors bring a new look to Houston

**Deck:** Golden State's eight straight wins have turned an 0–3 start into one of the NBA's most interesting early-season stories. Now the Warriors face an 8–3 Rockets team on ESPN.

**Lead:** Eleven games into the season, Golden State has already lived through two very different starts. Three consecutive losses gave way to eight straight wins, and Wednesday's nationally televised game in Houston offers another look at a Warriors team getting help beyond Stephen Curry.

**Emerging player:** Rookie Yaxel Lendeborg has become part of the story. The 11th pick in June's draft entered the game averaging 21.4 points, with a 37-point outing against the Clippers and 23 points in each of Golden State's past two games. Those are eye-catching numbers for a player still in his first month in the NBA, though the early sample warrants perspective.

**Opponent and tension:** Houston is 8–3 itself, coming off a win over Denver. Kevin Durant and Alperen Sengun give the Rockets a different kind of offensive challenge, while the availability of Houston's injured centers is worth monitoring before tipoff.

**What to watch:** Whether Golden State's offense keeps its momentum on the road, how its rookie's opportunities hold up against Houston, and whether the Rockets can manage their frontcourt rotation will help frame the matchup. The teams meet at 9:30 p.m. ET on ESPN.

This is a **voice/angle target**. The production generator must rebuild each statement from fact IDs and may need to omit clauses where the full proof, availability or cutoff is missing. Do not hardcode this prose or this matchup.

## 3. Season-stage context is a mandatory input

Each preview must classify the **league-specific stage** from official competition calendar and completed-game counts. It must choose the relevant interpretation of team/player form rather than applying the same last-five and last-season rhetoric all year.

| Stage | NBA example | Editorial weighting |
|---|---|---|
| Preseason / opening games | Zero to a few regular-season games | New rosters, confirmed availability, offseason changes, previous-season references with explicit date labels. Very weak conclusions from current records. |
| Early regular season | First ~10–20 of 82 games | New player emergence, tentative role changes, current streaks, relative small samples; previous year as secondary context only. |
| Middle of season | Substantial current-season coverage | Repeatability, team trends, rotations, adjustments, playoff position, opponent splits with usable sample sizes. |
| Late regular season | Standings and qualification in focus | Clinching/elimination conditions (verified), seeding races, rest, injuries and meaningful stakes. |
| Playoffs / elimination | Series and competition rules determine stakes | Series state, previous matchups, game-to-game adjustments, availability; don't mix regular-season and postseason baselines without labels. |

**These boundaries are configurable examples, not universal fixed thresholds.** Implement a season-stage adapter per competition:
- NFL / NCAAF: week number, conference schedule, rivalry week, bowl/playoff boundaries; far fewer games than NBA.
- NHL: long regular season and postseason series; standings points and games-in-hand matter.
- MLS: league calendar, table, qualification format, multi-leg/knockout rules; differentiate regular season from playoff rounds.
- Tennis: tournament round, surface, best-of format, rest, recent matches and event importance; no team season record.
- NBA: games played / total scheduled, tournament/competition subset (NBA Cup vs regular season), playoffs and series status.

No "they are still figuring it out," "season-defining," "contender," "must-win" or "playoff implications" solely from a team's 11-game record. Confirm real stakes from rules and standings.

## 4. Story discovery: who and what matters *this* week?

Make competing, inspectable `PreviewStoryCandidate` records:

- `season_stage` — early-season sample and why the results are or are not meaningful.
- `team_momentum` — real W/L streak, shape and opponent context, with chronology.
- `emerging_player` — rookie, recent role/usage change, meaningful form and sample; **not only stars selected from preseason reputation**.
- `established_star` — Curry/Durant context when available and genuinely relevant.
- `lineup_shift` — injuries, absences, starter status and workload consequences, with publication cutoffs.
- `historical_relationship` — former teammates, old teams, trade links, previous playoff series; reuse the separate historical relationships spec, do not construct player-specific hardcoded rules.
- `national_broadcast` — event metadata for interest, never a surrogate for competitive stakes.
- `playoff_or_rankings_stakes` — only when season-stage and current evidence allow the claim.
- `statistical_matchup` — supported, sample-aware matchup comparisons, clearly naming the window/cohort.
- `model_perspective` — immutable pregame LP forecast lock only, with model version and uncertainty. May be omitted if not validated.

Store all candidates, strength features, source evidence, selected/rejected rationale, editorial override and result story plan. **The most famous player need not be the lead; the most unusual number need not be the lead either.** Require a coherent through-line.

### Story plan structure

```json
{
  "game_id": "canonical-game-id",
  "as_of": "2026-11-11T08:10:00Z",
  "season_stage": {
    "phase": "early_regular_season",
    "games_completed": 11,
    "games_scheduled": 82,
    "caveat": "limited sample"
  },
  "lead_angle": "early_season_turnaround",
  "supporting_angles": [
    "emerging_rookie_scoring",
    "opponent_current_form",
    "national_telecast"
  ],
  "sections": [
    "why_this_game",
    "what_changed",
    "players_to_watch",
    "opponent_context",
    "matchup_questions"
  ],
  "evidence_ids": ["fixture-evidence-id"],
  "quality_status": "needs-independent-audit"
}
```

Illustrative contract, not an official live data payload. Never use the values without a verified fixture.

## 5. Required data and what to ingest/derive

| Input | Needed fields | Likely source | Gate |
|---|---|---|---|
| Event identity | Canonical game ID, teams, date, venue, competition, round | LP scoreboard/schedule | Stable crosswalk and exact local tipoff |
| Broadcast context | Network/platform, national vs regional, start time | Official ESPN/league schedule | Provider-attributed, timestamped; do not infer network from hype |
| Season stage | Season type, game number, games completed, league format | Schedule/competition calendar | Correct denominator and competition boundary |
| Player form | Player ID, recent logs, points, usage, attempts, minutes, role | LP player-game logs | Cutoff-safe, no game-after-tipoff leakage |
| Rookies/draft | Draft year/round/overall pick, tenure, first season | Official draft, verified roster data | Guard undrafted vs drafted and year |
| Team form | Verified records, streak spans, home/away, opponents | LP schedule, results | Independently recomputed chronological streak |
| Availability | Injury designation, publication time, expected starters | Official injury reports / snapshots | Status may change; never assert participation |
| Relationships | Previous teams, teammates, playoff history, transactions | Historical relationship index | Typed evidence, season/appearance distinction |
| Recent matchup | Prior results, roles, relevant context | Historic scoreboards/player logs | Same teams and correct season, no stale-roster comparison |
| Models | Locked probabilities, projected distribution, model version and limits | LP pregame model outputs | Original immutable pre-tipoff lock; no retrofitted projections |
| Video/images | Licensed photo/embed URL and rights metadata | Rights-cleared sources | No unlicensed Getty/ESPN/game footage |

No hard dependency on full third-party article text. Use official fact feeds, permitted publisher metadata and LP-derived original analysis. Free access does not itself imply reuse rights.

## 6. Integration with current Legendary Picks code

Read before changing:
- `backend/story_engine.py`: `select_story_angle` currently selects a small group of team record/rematch/streak angles; `_lead` and `render_story` produce 1–3 sentences. Existing player-form logic currently has no coherent multi-paragraph preview article.
- `backend/story_engine_audit.py`: preserve the independent claims audit.
- `backend/story_engine_runtime.py`: production feature flag, append-only run history and stable caching.
- `backend/story_rubric.py`: existing heuristic fan voice; not human-certified writing.
- `backend/core_stories.py`: existing story endpoints / legacy fallback.
- `docs/LEGENDARY-PICKS-EDITORIAL-NEWSROOM-AND-EVENT-STORE-2026-11-11.md`: editorial roles, evidence store and approval.
- `docs/NATURAL-SPORTS-COMMENTARY-EVALUATION-2026-11-11.md`: separate naturalness evaluation.
- `docs/HISTORICAL-RELATIONSHIPS-RIVALRIES-2026-11-11.md`: relationship candidates.
- PR #35 postgame research (verify current status before integration).

Suggested pure modules (paths are adjustable after repo audit):
- `backend/preview_context.py`: season/competition stage, broadcast and roster/draft descriptors.
- `backend/preview_angle_candidates.py`: grounded, scored candidate discovery.
- `backend/preview_story_plan.py`: deterministic ordering/dedupe/coherence.
- `backend/preview_article_renderer.py`: typed, league-specific section templates and stable paragraphs.
- `backend/preview_article_audit.py`: independently recomputed claim/phase/context validation.
- `backend/test_preview_editorial.py`: all regression fixtures.

Do not force multi-paragraph articles into the existing one-to-three-sentence `render_story` contract. **Keep backward-compatible short preview output** and add a separate article representation with `headline`, `deck`, `sections`, `as_of`, `source_manifest`, `story_plan`, `template_version`, `editorial_status`. Store versions append-only; do not replace an archived preview with a recap.

The automated game coverage desk generates previews across eligible leagues. The Managing Editor flags enhanced/featured previews. Editor-in-Chief approves initial release classes; no autonomous production publishing until scoped permission.

## 7. TDD acceptance criteria (write tests first)

1. Historical fixture game ID and official 9:30 p.m. ET Nov. 11 ESPN telecast resolve to the same canonical matchup.
2. **Yaxel drafted 11th**, not “undrafted”; intentionally mutated draft record fails.
3. Pre-tipoff fixture includes Lendeborg's last two 23-point outings, 37-point Nov. 1 game, and 21.4-point season average only from eligible player-game logs.
4. Story plan may select early-season turnaround lead and Yaxel as a prominent supporting angle; the name **must appear** when complete high-quality evidence supports it.
5. Curry and Durant appear in a balanced, meaningful matchup context, with no unsupported motive or guarantee of participation.
6. Houston's 8–3 record, prior Denver result and injury status must be computed/retrieved **as of** the pinned cutoff. Missing or stale statuses are omitted, never assumed.
7. National ESPN broadcast mentioned correctly; changing fixture to a regional telecast must remove “nationally televised.”
8. `0-3 -> 8 straight wins` context interpreted as **early season**; no claim of playoff clinch, title favorite or sustained full-season dominance.
9. Older-season statistics are explicitly labeled as *last season* and lose default priority when current sample becomes adequate.
10. Removing rookie logs blocks Yaxel stat claims but preserves legal team-level storyline and grammatical fallback.
11. Postgame result, box-score data, future injury report or late feature must never enter this pregame fixture before its cutoff.
12. A player with an injured/out/uncertain status cannot be declared an actual participant; projected starters remain projected.
13. Identical evidence/model/template versions produce byte-identical content and stable story/candidate IDs.
14. No third-party full-body articles, unlicensed images or copied lines are needed to render a complete article.
15. NBA early-season and late-season fixtures produce materially different selection weights and appropriate sample qualifiers.
16. NFL week one/week 16, NCAAF regular season/CFP, MLS regular season/playoffs, NHL regular/playoffs and tennis first round/final each use proper competition-stage context.
17. Arbitrary charismatic/famous player without a meaningful fact must not displace a verified better storyline.
18. Missing LP model lock yields **no** invented win probability or projected score; model version and uncertainty display only when source is valid.
19. Independent claim audit must pass before review/publication; a copy editor cannot approve its own facts.
20. Naturalness regression: no Brunson-style “offense scored 31 and 33 from him,” wrong stat agents, awkward concatenation or unclear stat windows.
21. First 100 NBA historical fixtures produce both compact and full preview where sufficient data exist, with explicit decline/short-only outcomes when they do not.
22. Hold-out and frozen benchmarks compare fact integrity, story-hook recall, named relevant player coverage, freshness, naturalness and reading preference separately.
23. Website integration does not break current score/game APIs and produces one real clickable article, not a link to a source preview.
24. No per-game network requests, GPU inference or LLM call in the deterministic renderer; performance measured on LP's CPU host.

### Mandatory negative controls

- Ordinary matchup with no meaningful rivalry and low player signal.
- First scheduled vs first actual meeting after trade.
- Early breakout after only **one** game (must not overclaim a “season-long breakout”).
- Injured star at pregame cutoff.
- New rookie with a draft lookup mismatch.
- Wrong ESPN schedule day/time zone.
- Post-tipoff player stat injected into pregame fixture.
- Significant model forecast omitted or unavailable.

## 8. Benchmark and editorial evaluation

Compare on a **fixed, frozen, cutoff-aligned sample**:
- AP/Data Skrive/ESPN **automated preview format**: factual breadth, consistent coverage, league-appropriate background. Do not train on/reproduce bodies without permission.
- Existing LP compact deterministic preview.
- New LP full deterministic preview (and short summary).
- Authorized original/human editorial reference where available.

For story-hook evaluation, build independent human labels of **which real storyline should lead** and which players deserve mention. Use two knowledgeable human reviewers on a smaller blinded set. Human preference is **not** simulated or replaced by mechanical rubric. Measure additional content depth, broken phrasing, source coverage, percentage of distinct leads, readability, time-window/cutoff leakage and recurrence of named players.

Don't set a false “100% editor approved” figure based on test fixtures. Report exact counts, failures, blocked stories, abstentions, and human review size. Preset cases must not be in held-out preference evaluation; freeze held-out game IDs and outputs before reading their outcomes.

## 9. Deliverables / definition of done

- Read-only audit of source availability and actual current code/feature flags.
- One pinned GSW–HOU 2026-11-11 case-study fact bundle with per-claim source/time/ID manifest.
- Side-by-side current LP preview, independent human gold-angle notes, new compact preview and full editorial article.
- Ranked candidate ledger proving why Curry, Yaxel, the streak, Houston and the ESPN broadcast were included or omitted.
- Another dozen NBA counterexamples and a 100-game frozen evaluation; other-league phase-specific tests.
- TDD, no claim leakage, naturalness tests, and real CPU timing.
- Small dev-only article detail page consistent with LP typography, black/zinc/emerald system, with no giant stat-number story cards.
- Draft implementation PR for code only; **do not merge or deploy** without explicit review and publication authorization.

**Success condition:** Legendary Picks can generate a genuine pregame read from verified facts: not just the teams and last-season percentages, but the right people, current context, timing, history and actual reasons a fan might want to watch. The GSW–HOU case must naturally surface rookie Yaxel Lendeborg without hardcoding him or relying on a per-game LLM call.
