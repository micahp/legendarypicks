# CPU-only deterministic story engine

**Status:** integrated behind `LP_DETERMINISTIC_STORY_ENGINE` on PR #30's research branch. The service environment flag defaults off and is checked for each story request. This change has not been deployed to production. Deterministic run artifacts are kept in this directory, while LLM comparison artifacts remain in the adjacent `../relevance-ranking/` directory.

**Historical note:** The six examples and initial measurements below document the first prototype, before the regression fixes and held-out evaluation in the final section. The held-out set is the current renderer evaluation.

The engine separates read-only fact collection, team-story selection, player selection, sentence rendering, and the internal evidence manifest. Published prose is returned as `story`; the separate `manifest` carries evidence IDs and omissions. Rendering made zero model calls, zero network calls, and zero database writes.

## Generated examples

### CHI at SEA

> The 5-2 Bears bring a two-game winning streak to Seattle, where the Seahawks sit at 4-3. Jaxon Smith-Njigba has been on a tear for Seattle, topping 100 receiving yards in four of his last five games, while Chicago counters with D'Andre Swift, who has rushed for 476 yards and seven touchdowns.

### SAC at DAL

> Dallas has won three straight entering its matchup with the winless Kings, who sit dead last in the NBA at 0-6. Cooper Flagg is averaging 26.8 points and 6.6 assists over his last five for Dallas, while Sacramento's Darius Acuff Jr. has scored 38 and 34 in his last two.

### NO at MEM

> Memphis puts its undefeated 6-0 start on the line against New Orleans, which has won two straight and sits at 2-4. Ty Jerome has powered the Grizzlies' hot start, averaging 25.8 points and 5.8 assists over his last five games, including a 45-point outing.

### BOS at HOU

> Two of the NBA's top four teams meet in Houston, where the 6-1 Rockets host the 5-1 Celtics. Houston's Jabari Smith Jr. has scored 30 and 22 in his last two, while Boston's Jayson Tatum has scored at least 23 in each of his last five, including a 40-point night.

### UTAH at SA

> San Antonio has won four straight at 4-2 and already beat Utah 117-111 on Oct. 28; the 1-5 visitors have lost four in a row. San Antonio's Victor Wembanyama has scored 43 and 36 in his last two, while Utah's Keyonte George has scored 20 or more in three of his last four, including 31, 26, 24.

### POR at DEN

> The 4-1 Blazers visit Denver, where the 3-2 Nuggets are riding a two-game winning streak. Denver's Jamal Murray has put up 39 and 42 in two of his last five, while Portland's Deni Avdija has scored at least 23 in four of his last five.

## Selection and omissions

The first sentence is chosen from team records and standings before player statistics are considered. Player facts then support that angle.

| Matchup | Story angle | Facts selected | Secondary facts omitted |
| --- | --- | --- | --- |
| CHI at SEA | records | Chicago Bears record 5-2; Seattle Seahawks record 4-3; Chicago Bears 2-game winning streak; Jaxon Smith-Njigba recent form; D'Andre Swift recent form | Caleb Williams' uneven PPR sequence and both teams' quality-rank labels. |
| SAC at DAL | winless_last | Dallas Mavericks 3-game winning streak; Sacramento Kings record 0-6; Sacramento ranks 30 of 30; Cooper Flagg recent form; Darius Acuff Jr. recent form | The Kings' minus-19.0 point differential and Dallas' 120-96 result against Oklahoma City. |
| NO at MEM | undefeated | Memphis Grizzlies record 6-0; New Orleans Pelicans record 2-4; New Orleans Pelicans 2-game winning streak; Ty Jerome recent form | Zion Williamson's uneven recent scoring and the event-only draft's points-allowed statistic. |
| BOS at HOU | top_four | Boston Celtics record 5-1; Houston Rockets record 6-1; Boston ranks 4 of 30; Houston ranks 2 of 30; Jabari Smith Jr. recent form; Jayson Tatum recent form | The teams' run-differential comparison and Alperen Sengun's season averages. |
| UTAH at SA | streak_clash | Utah Jazz record 1-5; San Antonio Spurs record 4-2; Utah Jazz 4-game losing streak; San Antonio Spurs 4-game winning streak; prior meeting result; Victor Wembanyama recent form; Keyonte George recent form | The No. 27 and No. 8 quality-rank comparison. |
| POR at DEN | records | Portland Trail Blazers record 4-1; Denver Nuggets record 3-2; Denver Nuggets 2-game winning streak; Jamal Murray recent form; Deni Avdija recent form | Portland's quality rank and Denver's minus-1.2 run differential. |

The machine-readable file lists selected facts, evidence IDs and timestamps, all player facts considered but omitted, and each saved LLM preview verbatim.

## Source and cutoff checks

The six frozen comparison examples come from `relevance-ranking/examples.jsonl`. The NBA standings snapshot contains all 30 teams and 92 scored regular-season games through Nov. 2; every supporting game row was captured by the shared cutoff. The full table verifies Sacramento as dead last and Memphis as the only undefeated team in that snapshot. Swift's 476 rushing yards and seven touchdowns are recomputed from all seven local player game logs in `swift_2026_logs.json`.

The read-only collector was also run directly against `picks.dev.db` for Boston at Houston at the saved cutoff. It rebuilt Boston at 5-1, Houston at 6-1, all 30 NBA team records, and considered 36 players. It returned no post-cutoff team evidence and generated the same top-four lead as the frozen example.

Chicago and Seattle records use the frozen, independently recomputed comparison facts and their conservative game-date-plus-one-day availability rule. The current `nfl_schedule` capture timestamps postdate this retrospective cutoff, so the engine does not treat today's database rows as historical captures. A direct historical collector call therefore falls back to cutoff-safe player facts until an archived NFL standings snapshot is supplied.

## Evaluation

| Measure | Result |
| --- | --- |
| Matchups | 6 total: 1 NFL and 5 NBA |
| Editorial acceptance criteria | 8 of 8 passed |
| Sentence count | 1 to 3 per preview |
| Model and external API calls | 0 |
| Human ratings | 0 |
| Renderer median | 2.229 ms per story on this host |
| Read-only SQLite collection plus render | 34.657 ms for one NBA matchup |
| Focused tests | 19 passed |

The deterministic outputs keep the requested headline and key player facts for all six fixtures. They are shorter than several LLM baselines and omit secondary detail, which prevents run differential, quality rank, and efficiency figures from competing with the central story. This is a structural comparison against saved baseline prose, not a claim that fans prefer the deterministic copy.

## Remaining narrative gaps

- The conditional templates have only been reviewed on these six matchups. More regular games are needed to judge repetition and tone.
- Playoff races, rivalries, and rematches without a source-backed prior score need dedicated fixtures and trusted facts.
- Player thresholds can still choose a different star than the LLM baseline. Houston and Portland need human review.
- Historical NFL standings need an archived, cutoff-safe snapshot before the database collector can reproduce them at this retrospective cutoff.
- Production integration remains untouched until editorial review accepts the examples.

See [evaluation.json](evaluation.json), [NBA standings evidence](nba_standings_2026-11-02.json), [Swift game logs](swift_2026_logs.json), and the original [saved LLM comparison examples](../relevance-ranking/examples.jsonl).

## Regression fixes and held-out evaluation

The renderer fixes losing-streak direction, last-game wording, the NFL "coming off" recency claim, league-specific team names, and causal NBA hot-start phrasing. The added regressions cover those cases. `python -m unittest test_story_engine` passes 36 tests.

The final sample contains 50 NFL and 50 NBA games. It was selected by sorting eligible game IDs with SHA-256 of `20261105|league|game_id`, taking the first 50 in each league. All 200 games in the two exposed diagnostic runs, all six coached comparison games, and the preflight fixtures were excluded. The remaining eligible population was 50 NFL and 992 NBA games. The sample cutoff is 2026-11-03 03:00:53 UTC, or 2026-11-02 9:00:53 PM Central. NFL schedule data has a published game date but no UTC kickoff, so the evaluator used midnight UTC on the published date as a conservative cutoff boundary. NBA rows used their published UTC start.

The earlier, exposed diagnostic sets are retained in [diagnostic run one](heldout_results.jsonl), [diagnostic run one's manifest](heldout_sampling_manifest.json), [diagnostic run two](heldout_v2_results.jsonl), and [diagnostic run two's manifest](heldout_v2_sampling_manifest.json). Manual review found surface-specific copy issues in the first set, and the independent player arithmetic audit found two NBA score-count mismatches in the second. Those games were all excluded from the final set.

The renderer hash is `2791cd0fd723de721859b5d64dacd50646b6b6aed7697d5dedc24b1fa1924e92`. Generation ran sequentially against the existing development database in read-only mode. The evaluator blocks attempted network connections during rendering. There were zero model calls, network calls, or database writes.

| Measure | Result |
| --- | ---: |
| Held-out previews | 100, 50 NFL and 50 NBA |
| Appropriate lead | 100 of 100 |
| Relevant selected player facts | 96 of 96 previews with a player fact; 4 had no player fact selected |
| Factual claims supported | 100 of 100 |
| Fan language | 79 pass, 21 borderline due to repeated player-stat sentence shapes |
| Incorrect or ambiguous player-team attribution | 0 |
| Cutoff violations | 0 |
| Empty previews | 0 |
| Record or streak claims that failed recomputation | 0 |
| Player stat claims that failed recomputation | 0 |
| League rank claims that failed recomputation | 0 |
| Normalized lead patterns | 93 unique; 14 previews reused a pattern; no pattern appeared more than twice |
| Repeated player-stat sentence shape within one preview | 21 previews |
| Median fact collection | 172.732 ms |
| Median render | 8.986 ms |
| Human fan ratings | 0 |

Every row preserves the schedule and source evidence, the selected and omitted facts, and the generation checks in [the result JSONL](heldout_final_results.jsonl). [The review JSONL](heldout_final_review.jsonl) has one editorial and evidence assessment per preview. [The post-render audit](heldout_final_post_audit.json) recomputes the record and streak phrases as written in the prose. The sampling population and exclusions are in [the sampling manifest](heldout_final_sampling_manifest.json); aggregate timing and mechanical checks are in [the generation summary](heldout_final_summary.json).

### Additional held-out examples

These are from the unseen sample, not the six coached examples above.

**49ers at Cowboys**

> San Francisco brings a 6-1 record into Dallas, where the 3-5 Cowboys look to protect home turf. Dallas's Javonte Williams has topped 100 rushing yards in one of his last four games, while San Francisco counters with Christian McCaffrey, who has rushed for 389 yards and eight touchdowns.

**Eagles at Giants**

> Philadelphia has dropped six straight at 2-6 entering its matchup with New York, which is 4-2-1. Malik Nabers has been on a tear for New York, topping 100 receiving yards in four of his last five games.

**Bills at Jets**

> Buffalo has won three straight and sits at 6-1, while New York has dropped three in a row at 2-6. New York's Braelon Allen has topped 100 rushing yards in one of his last four games, while Buffalo's James Cook has topped 100 rushing yards in one of his last four games.

**Mavericks at Grizzlies**

> Memphis puts its undefeated 6-0 start on the line against Dallas, which won three straight and sits at 4-2. Grizzlies star Ty Jerome is averaging 25.8 points and 5.8 assists over his last five games, including a 45-point outing, while Cooper Flagg is averaging 26.8 points and 6.6 assists over his last five for Dallas.

**Trail Blazers at Grizzlies**

> Memphis puts its undefeated 6-0 start on the line against Portland, which won its last game and sits at 4-1. Grizzlies star Ty Jerome is averaging 25.8 points and 5.8 assists over his last five games, including a 45-point outing, while Portland's Deni Avdija has scored at least 23 in four of his last five.

**Nuggets at Cavaliers**

> The 3-2 Nuggets bring a two-game winning streak to Cleveland, where the Cavaliers sit at 4-3. Denver's Jamal Murray has put up 39 and 42 in two of his last five.

### Remaining evaluation limits

The editorial scores are Codex's static review of the 100 outputs, not ratings from fans. Repeated player sentence shapes are the main visible quality gap: the prose remains grammatical, but paired players with the same threshold can make a preview feel templated. Exact normalized lead patterns repeat in 14 rows, including the same Boston and Oklahoma City pairing scheduled in both home-away orders. The sample contained no same-city NFL or NBA matchup, so attribution in those specific pairings remains unevaluated. No template changes were made after the final sample was drawn.

The correctness and cutoff checks pass. The CPU engine is now wired into the upcoming NBA and NFL preview path on this PR branch. The source change has not been deployed or applied to a live database. Human editorial review of repeated constructions and broader fan preference remains before a production release.

## App integration on PR #30

When enabled, upcoming NBA and NFL previews use `backend/story_engine.py` through `core_stories.py`. The app reads the local schedule, team results, and player logs, then renders and mechanically audits record, streak, ranking, head-to-head, player-stat, attribution, and cutoff claims without a model or network call. It records the six deterministic rubric scores and evidence in `game_story_deterministic_history`, updates the latest-story cache in `game_story_deterministic`, and records operational or factual failures separately in `game_story_deterministic_failures`. History inserts and latest-cache updates share one transaction; database triggers reject history updates and deletes. Audit failures do not replace the last accepted story; operational failures return a saved story when available and never fall through to DeepSeek while the flag is enabled. Existing `game_story` rows remain intact for the legacy path and postgame recaps. The deterministic multisport run and its grading artifacts are saved under [`multisport-2026-11-03/`](multisport-2026-11-03/). The LLM-based comparison remains under [`../relevance-ranking/`](../relevance-ranking/).

### Follow-up fixes and endpoint verification on 2026-11-03

The independent audit now excludes a two-team score from season-record parsing only when the complete head-to-head sentence, winner, score, date, and selected evidence all recompute successfully. An NFL Ravens-Bengals regression exercises a verified 24-20 rematch through the full audit.

Scoreboard ingestion and fresh ESPN scoreboard responses ask the warmer to recheck cached upcoming NBA/NFL previews. The latest-story row records `last_checked_at`; refresh work observes a 45-second cooldown and starts with never-checked or oldest-checked games so the three-worker limit progresses across a slate. Recollection still uses the existing kickoff cutoff. An unchanged evidence hash and engine version returns the saved story without adding a history row; changed evidence creates a new scored revision. A runtime regression inserts a newly completed result, requests the preview again, and verifies both the changed story and exactly one additional history row.

The focused suite passed **141 tests** across the renderer, audit, rubric, runtime, preview warmer, and scoreboard ingestion paths. A separate temporary Uvicorn process served `/api/game/nba/0022600173/story` from the PR branch using a filtered copy of current NBA schedule, standings, and player logs. The source development database was opened read-only; only the temporary copy was written. The endpoint returned HTTP 200 with a nonempty PHI at DET preview, an `eligible` gate at 99/100, all six rubric dimensions (fan voice 95; flow, freshness, grounding, headline, and players 100 each), no failed audit checks, and no operational failure rows. The DeepSeek callback was replaced with a function that raises, and the request succeeded, confirming no model fallback. This verifies the PR branch in an isolated running application, not deployment to the systemd dev or production service, and it is not a human editorial rating.

### Concurrent generation and failure cooldown on 2026-11-04

Accepted persistence now rechecks history inside its `BEGIN IMMEDIATE` transaction and records accepted keys in `game_story_deterministic_accepted_keys`, whose composite primary key is `(league, game_id, input_sha256, engine_version)`. The tuple is idempotent for eligible and review generations: simultaneous requests may render concurrently, but only one accepted history row is inserted. A thread-barrier regression forces two requests to pass the cache-miss check before either writes and verifies one history row, one key, and one latest-cache row.

Operational and audit failures update a separate per-game cooldown timestamp, including when the game has never had an accepted preview. Scoreboard evidence refreshes consult that timestamp alongside the latest story check and skip games checked within 45 seconds. The regression covers a recent failure with no accepted cache, an older failure that is due again, and a game never attempted. The focused suite passes **141 tests** after these changes.
