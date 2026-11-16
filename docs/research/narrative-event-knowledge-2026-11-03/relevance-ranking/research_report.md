# Narrative relevance research — 2026-11-03

Database: /root/legendarypicks/backend/data/picks.dev.db (read-only; query_only=1).
Shared cutoff: 2026-11-03T00:32:27Z. Preview horizon: 48 hours.
External model requests: 98.

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

Generated 3 drafts for each of 11 targets with 98 openrouter requests using deepseek/deepseek-v4.1-flash.
The baseline uses the exact core_stories.py system prompt. The existing matchup_context.context_lines() logic derived shared pregame facts from timestamped, hashed ESPN summary snapshots for 10 of 11 targets. The other 1 target(s) have no cutoff-safe summary and remain reduced-context: PHI at DET (0022600173). For the captured summaries it emitted lastFiveGames form (20), leaders (20) (40 lines total). The snapshots produced no header.season phase, standings lines.
Production input fidelity: the replay did not invoke core_stories.generate_game_story. It rebuilt game state, matchup/date/host, team records, and player form from cutoff-filtered local rows; it supplied no stakes lines. Production reads runtime game_result/schedule and standings data, calls stakes.for_matchup, and prioritizes prop-board player form before player_form.lines. The replay fixes state=pre and infers current_season from reconstructed records; production derives both through its runtime game and records_stale checks.
Model path also differs: this run called openrouter directly with a 600-token completion limit; production dispatches through _core._llm_chat, whose code default is the LP_LLM_PROVIDERS chain and an 8000-token limit.
The event-only and combined system and user prompts differ for every target.
Event-only and combined output text differs for 10 of 11 targets; all three outputs are textually unique for 10 targets.
Blind packet: 33 drafts across 11 targets. No human ratings were entered, so the comparison does not establish a winner.

No automatic or human judgment of generated prose is claimed. The row-level statistic audit rechecks input metrics, not semantic use of those facts in model text.

## Target drafts

Full text and matched prompt hashes are in examples.jsonl and model_comparison.jsonl.

| League | Matchup | Kickoff UTC | Core baseline | Event-only | Combined |
| --- | --- | --- | --- | --- | --- |
| NFL | CHI at SEA | 2026-11-03T01:15:00Z | Chicago (5-2, ranked #8) brings a two-game win streak to Seattle, where the 4-3 Seahawks sit at #15. Jaxon Smith-Njigba has been Seattle's engine, topping 100 receiving yards in f… | Seattle's offense averaged 0.016 EPA per scrimmage play over its baseline 4 games but -0.119 over its most recent 3. Chicago's defense allowed -0.084 EPA per scrimmage play over i… | Seattle's recent offense and Chicago's recent defense are moving in opposite directions on EPA per scrimmage play: SEA's offensive EPA is down (-0.1349), while CHI's EPA allowed i… |
| NBA | SAC at DAL | 2026-11-03T01:00:00Z | The 0-6 Kings, ranked dead last in the league, visit a Dallas team riding a three-game win streak and sitting at 4-2. Sacramento rookie Darius Acuff Jr. has scored 38 and 34 in hi… | The Sacramento Kings have lost 6 straight games. | The verified evidence shows the Sacramento Kings are on a six-game losing streak. No other relationship cleared the evidence gate. |
| NBA | NO at MEM | 2026-11-03T01:00:00Z | Memphis puts the NBA’s only perfect record and its No. 1 quality rank on the line against a New Orleans team that has won two straight but sits just 2-4. Ty Jerome has powered the… | Memphis is averaging 123.3 points per game over its last 3 games, up from a full-season baseline of 114.7. New Orleans is allowing 107.7 points per game over its last 3 games, dow… | The supplied evidence shows Memphis's recent points-per-game offense moving up while New Orleans's recent points allowed per game moves down — opposite directions. That means Memp… |
| NBA | MIL at MIN | 2026-11-03T01:00:00Z | Milwaukee's 1-5 start has it at #28 of 30 in quality rank with a -13.17 run differential, and the Bucks have dropped two straight. Anthony Edwards' last five for Minnesota read 47… | No preview. | No verified relationship cleared the evidence gate for this matchup. |
| NBA | BOS at HOU | 2026-11-03T01:30:00Z | Two of the league's top four teams meet in Houston, where the 6-1 Rockets (No. 2) host the 5-1 Celtics (No. 4) with the NBA's two best run differentials on the line — Houston at p… | Boston Celtics have won 5 straight games. | The verified selected evidence shows the Boston Celtics have won 5 straight games. No other relationship cleared the evidence gate. |
| NBA | UTAH at SA | 2026-11-03T01:30:00Z | San Antonio has won four straight and sits at 4-2, while Utah arrives at 1-5 having dropped four in a row, including a 117-111 overtime loss to these same Spurs on Oct. 28. Victor… | The San Antonio Spurs have won four straight games. Utah has lost four straight. | The only verified relationship that cleared the evidence gate is San Antonio's four-game win streak. No other matchup claim is supported by the selected evidence. |
| NBA | POR at DEN | 2026-11-03T02:00:00Z | Portland brings a 4-1 record and the league's No. 6 quality rank into Denver, where the Nuggets have won two straight but sit at 3-2 with a minus-1.2 run differential. Deni Avdija… | No preview. | No verified relationship cleared the evidence gate for this matchup. |
| NBA | PHX at GS | 2026-11-03T03:00:00Z | Golden State has won four straight since a 131-122 loss at Phoenix on Oct. 24, and a win Monday at home pushes the Warriors to 5-3 while dropping the Suns — losers of two straight… | The Phoenix Suns' points per game is up by 9.0813 over a 3-game recent window (121.67) compared with an 82-game baseline (112.59), while the Golden State Warriors' points allowed… | The supplied evidence shows PHX's recent scoring is up relative to its baseline, while GS's recent points allowed is down relative to its baseline—opposite directions. That means… |
| NBA | TOR at LAC | 2026-11-03T03:00:00Z | The Clippers, 1-5 and losers of five straight, sit 25th of 30 in quality rank — and they host a Toronto team that is itself on a two-game skid at 3-3. Scottie Barnes is scoring 24… | The LA Clippers have lost 5 straight games. | The LA Clippers have lost 5 straight games. |
| NBA | MIA at LAL | 2026-11-03T03:00:00Z | The Lakers, ranked #7 in the competition at 5-2, host a Miami side sitting #21 at 2-4 — though the Heat arrive on a two-game win streak after beating Indiana 145-125. Luka Doncic… | Miami’s points per game averaged 127.67 over its last 3 games, up 6.80 from its 82-game baseline of 120.87. The Lakers’ points allowed per game averaged 108.0 over their last 3 ga… | Miami's recent scoring has moved up relative to its baseline, while the Lakers' points allowed have moved down relative to theirs — the two deltas point in opposite directions. Th… |
| NBA | PHI at DET | 2026-11-05T00:00:00Z | Detroit hosts Philadelphia Wednesday with the East's early pecking order on the line: the 6-1 76ers rank #3 in the competition, the 5-1 Pistons #5. Detroit's plus-8.0 run differen… | Over DET's last 3 games, their points per game is 101.33, down 16.44 from their 82-game baseline of 117.77. Over PHI's last 3 games, their points allowed per game is 102.0, down 1… | For this points-per-game relationship, DET’s recent offense is down 16.435 points versus its baseline, while PHI’s opposing defense is allowing 14.061 fewer points than its baseli… |
## Remaining limitations

- NFL kickoff timestamps convert nflverse's Eastern gametime to UTC using America/New_York.
- Upcoming NBA schedule rows have no stored ESPN event crosswalk; no ESPN or publisher request was made.
- NBA team_game_stats has no populated current-season stat rows; this ranking uses local NBA schedule scores and prior-season nba_sportsdataverse_games scores.
- Ranking weights are deterministic heuristics and have not been trained or independently human-validated.
- Fourth-down and drive classifications remain quarantined in their separate correctness workstream.
- Source-statistic audits validate supplied input rows, not the semantic accuracy of model-generated prose.
- Cutoff-safe ESPN summary snapshots were unavailable for 1 of 11 targets; those targets retain a reduced-context baseline.
- The full core_stories generator was not invoked; local records and player-form inputs remain reconstructed.

Row-level artifacts: examples.jsonl, claim_audit.jsonl, statistic_audit.jsonl, rejected_facts.jsonl, database_coverage.json, baseline_generation_queue.jsonl, candidate_generation_queue.jsonl, model_comparison.jsonl, three_way_distinctness.jsonl, espn_context_snapshots.jsonl, and the blind review files.
