# Narrative relevance research — 2026-11-03

Database: /root/legendarypicks/backend/data/picks.dev.db (read-only; query_only=1).
Shared cutoff: 2026-11-03T00:32:27Z. Preview horizon: 48 hours.
External model requests: 66.

## Result

Prepared 1 NFL and 10 NBA targets. The three variants share each target and cutoff. NFL kickoff uses the Eastern-time schedule field converted to UTC; the nflverse schedule dictionary documents that field's timezone [here](https://nflreadr.nflverse.com/articles/dictionary_schedules.html).
The production core_stories.py file was not changed.

## Local coverage

- NFL PBP: 758,135 plays across 4,295 games (2010–2026); the 2026 partition has 21,018 plays across 120 games. The trend extractor selected 14,784 run/pass plays with non-null EPA.
- NFL final regular-season games available at cutoff: 120.
- NBA current-season completed regular games: 92.
- NBA previous-season regular-season baseline games: 1230.
- NBA team_game_stats: 2,462 populated rows joined to the 2025 regular season/Cup; no populated current-season team-game rows were found. Current scoring trends use schedule results.
- NBA player-box rows: 1,489 across 43 games; latest capture at cutoff: 2026-10-26T21:59:19.339706+00:00. The local schema audit found no NBA event-level play-by-play table (matching tables: []).
- Player-game-log lines are reconstructed as core input with actual capture timestamps for near-game snapshots. Isolated player lines are retained as rejected candidates.

## Selection

Selected candidates: {"team_relationship": 5, "team_streak": 4}.
Candidate inputs: {"player_form": 66, "selected:none": 2, "selected:team_relationship": 5, "selected:team_streak": 4, "team_relationship": 22, "team_streak": 9}.
Claim-level cutoff checks: 41 passed, 0 failed, 41 total.
Independent source-statistic audits: 11 of 11 targets passed; 0 failed. See statistic_audit.jsonl.
Rejected candidates retained with reasons and evidence IDs: 148.
- NFL EPA is stated as team efficiency across plays; no play is called game-winning.
- Drive, fourth-down, lead-change, and single-play game-winner categories are quarantined.
- Paired trend candidates need a same-metric offense/defense comparison, at least three recent and baseline games on both sides, both changes above threshold, recent evidence, and timestamps before the cutoff.

## Three-way generation and review

Generated 3 drafts for each of 11 targets with 66 openrouter requests using deepseek/deepseek-v4.1-flash.
The baseline uses the exact core_stories.py system prompt and reconstructed local inputs. The production ESPN matchup_context was unavailable. The event-only and combined system and user prompts differ for every target.
Event-only and combined output text differs for 11 of 11 targets; all three outputs are textually unique for 11 targets.
Blind packet: 33 drafts across 11 targets. No human ratings were entered, so the comparison does not establish a winner.

No automatic or human judgment of generated prose is claimed. The row-level statistic audit rechecks input metrics, not semantic use of those facts in model text.

## Target drafts

Full text and matched prompt hashes are in examples.jsonl and model_comparison.jsonl.

| League | Matchup | Kickoff UTC | Core baseline | Event-only | Combined |
| --- | --- | --- | --- | --- | --- |
| NFL | CHI at SEA | 2026-11-03T01:15:00Z | The 5-2 Bears, ranked #8 of 32, bring a two-game win streak to Seattle to face the 4-3 Seahawks, ranked #15. Jaxon Smith-Njigba has topped 100 receiving yards in four straight for… | Seattle's offense averaged 0.016 EPA per scrimmage play over its prior 4 games but -0.119 over its most recent 3, a downward trend. Chicago's opposing defense allowed -0.084 EPA p… | The supplied deltas move in opposite directions: Seattle's offense has seen its EPA per scrimmage play fall by 0.1349, while Chicago's defense has seen its EPA allowed per scrimma… |
| NBA | SAC at DAL | 2026-11-03T01:00:00Z | Dallas (4-2, ranked 10th of 30) brings a three-game win streak into its home game against Sacramento, which sits 0-6 and ranked 30th with a -19.0 run differential. Cooper Flagg ha… | Sacramento enters this game on a verified six-game losing streak. | Verified evidence shows Sacramento is on a six-game losing streak. No other verified relationship cleared the evidence gate. |
| NBA | NO at MEM | 2026-11-03T01:00:00Z | The 6-0 Grizzlies, ranked first in the league, put their perfect record on the line at home against a 2-4 Pelicans team riding a modest two-game win streak. Memphis's plus-15.17 r… | Over the last 3 games, MEM has averaged 123.33 points per game, up 8.66 from its 82-game baseline of 114.67. Over the same 3-game window, NO has allowed 107.67 points per game, do… | The supplied deltas move in opposite directions: Memphis's recent scoring is up (+8.66 points per game), while New Orleans's recent points allowed is down (-12.36 per game). For t… |
| NBA | MIL at MIN | 2026-11-03T01:00:00Z | Milwaukee's 1-5 start has it ranked 28th of 30 in quality, with a -13.17 run differential and a 1-5 mark over its last 10, while Minnesota sits 13th at 4-3 with an 11.29 different… | No preview is available for this matchup because no eligible evidence was supplied. | No verified relationship cleared the evidence gate for this matchup. |
| NBA | BOS at HOU | 2026-11-03T01:30:00Z | Houston hosts Boston with the two best records in the league on the line: the 6-1 Rockets rank #2 of 30 in quality, the 5-1 Celtics #4. Boston rides a five-game win streak, but Ho… | The Boston Celtics enter this matchup on a verified five-game winning streak. | Boston enters this game on a verified five-game winning streak. No other relationship cleared the evidence gate. |
| NBA | UTAH at SA | 2026-11-03T01:30:00Z | San Antonio's four-game win streak has coincided with Victor Wembanyama's hottest stretch of the season — 43, 36 and 29 points in his last three games — and the 4-2 Spurs (#8 in t… | San Antonio enters this game on a verified four-game winning streak. | San Antonio has a verified four-game winning streak. No other relationship cleared the evidence gate. |
| NBA | POR at DEN | 2026-11-03T02:00:00Z | Portland arrives at 4-1 and ranked sixth in the league, but Denver has won two straight and owns the home floor. Deni Avdija has scored at least 23 in four of his last five for th… | No preview. | No verified relationship cleared the evidence gate for this matchup. |
| NBA | PHX at GS | 2026-11-03T03:00:00Z | Golden State's four-game win streak meets a Phoenix side that has lost two straight and sits at 1-3 with a -12.5 run differential, 24th in the league against the Warriors' 14th. S… | Phoenix's points per game rose from a baseline mean of 112.59 over 82 games to 121.67 over its last 3. Golden State's points allowed per game fell from a baseline mean of 115.17 o… | The supplied evidence shows Phoenix's recent scoring trend moving up (+9.08 points per game) while Golden State's points allowed trend moves down (−8.17), meaning the two deltas p… |
| NBA | TOR at LAC | 2026-11-03T03:00:00Z | Toronto (3-3, ranked 15th of 30) arrives at LAC's home venue on a two-game skid, while the Clippers (1-5, ranked 25th) have lost five straight and own a -7.33 run differential. Sc… | The LA Clippers enter this game on a verified five-game losing streak. | The LA Clippers carry a verified five-game losing streak into this game. No other relationship cleared the evidence gate. |
| NBA | MIA at LAL | 2026-11-03T03:00:00Z | The 5-2 Lakers, ranked #7 in the competition, host a 2-4 Heat team riding a two-game win streak but carrying a -3.17 run differential. Luka Doncic has been scorching for Los Angel… | Miami's points per game rose from a 120.87 baseline over 82 games to 127.67 over its last 3 games. Meanwhile, the Lakers' points allowed per game fell from a 114.59 baseline over… | Miami's recent scoring is up by 6.8 points per game, while the Lakers' points allowed are down by 6.6 per game, so the two deltas move in opposite directions. That means Miami's o… |
| NBA | PHI at DET | 2026-11-05T00:00:00Z | Detroit hosts Philadelphia Wednesday with the East's early pecking order on the line: the 6-1 76ers rank #3 in the competition, the 5-1 Pistons #5. Detroit's plus-8.0 run differen… | Detroit's points per game dropped from a 117.77 baseline over 82 games to 101.33 over its last 3. Philadelphia's points allowed per game also fell, from a 116.06 baseline over 82… | Detroit's recent scoring is down by 16.4 points per game, while Philadelphia's points allowed is also down by 14.1 per game; both deltas move in the same direction, indicating red… |
## Remaining limitations

- NFL kickoff timestamps convert nflverse's Eastern gametime to UTC using America/New_York.
- Upcoming NBA schedule rows have no stored ESPN event crosswalk; no ESPN or publisher request was made.
- NBA team_game_stats has no populated current-season stat rows; this ranking uses local NBA schedule scores and prior-season nba_sportsdataverse_games scores.
- core_stories matchup_context from ESPN summary is marked unavailable in baseline manifests.
- Ranking weights are deterministic heuristics and have not been trained or independently human-validated.
- Fourth-down and drive classifications remain quarantined in their separate correctness workstream.
- The generated baseline uses reconstructed local records and player form; production ESPN matchup_context was unavailable.
- Source-statistic audits validate supplied input rows, not the semantic accuracy of model-generated prose.

Row-level artifacts: examples.jsonl, claim_audit.jsonl, statistic_audit.jsonl, rejected_facts.jsonl, database_coverage.json, baseline_generation_queue.jsonl, candidate_generation_queue.jsonl, model_comparison.jsonl, three_way_distinctness.jsonl, and the blind review files.
