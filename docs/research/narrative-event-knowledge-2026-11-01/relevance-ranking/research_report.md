# Narrative relevance research — 2026-11-01

Database: /root/legendarypicks/backend/data/picks.dev.db (read-only; query_only=1).
Shared cutoff: 2026-11-01T09:00:00Z. External requests: 0. Model calls: 0.

## Result

Prepared 10 NFL and 10 NBA targets. Event-only and combined outputs are deterministic research drafts. The exact core_stories system prompt and its reconstructable local inputs are saved for a later opt-in model comparison.
The production core_stories.py file was not changed.
The core prompt's local team record and player-form fields are reconstructed at the shared cutoff. matchup_context is explicitly marked unavailable because the production path reads it from ESPN summary. NFL target timestamps use a game-date UTC lower bound because the local schedule has no timezone for gametime.

## Local coverage

- NFL PBP: 756,043 plays across 4,283 games (2010–2026); the 2026 partition has 18,926 plays across 108 games. The trend extractor selected 13,316 run/pass plays with non-null EPA.
- NFL final regular-season games available at cutoff: 108.
- NBA current-season completed regular games: 88.
- NBA previous-season regular-season baseline games: 1230.
- NBA team_game_stats: 2,462 populated rows joined to the 2025 regular season/Cup; no populated current-season team-game rows were found. Current scoring trends use schedule results.
- NBA player-box rows: 1,489 across 43 games; latest capture at cutoff: 2026-10-26T21:59:19.339706+00:00. The local schema audit found no NBA event-level play-by-play table (matching tables: []).
- Player-game-log lines are reconstructed as core input with actual capture timestamps for near-game snapshots. Isolated player lines are retained as rejected candidates.

## Selection

Selected candidates: {"team_relationship": 10, "team_streak": 5}.
Candidate inputs: {"player_form": 120, "selected:none": 5, "selected:team_relationship": 10, "selected:team_streak": 5, "team_relationship": 40, "team_streak": 13}.
Claim-level cutoff checks: 56 passed, 0 failed, 56 total.
Rejected candidates retained with reasons and evidence IDs: 269.
- NFL EPA is stated as team efficiency across plays; no play is called game-winning.
- Drive, fourth-down, lead-change, and single-play game-winner categories are quarantined.
- Paired trend candidates need a same-metric offense/defense comparison, at least three recent and baseline games on both sides, both changes above threshold, recent evidence, and timestamps before the cutoff.

## Human review status

The blind packet contains 30 deterministic candidate drafts across 15 targets. Original-generator output is absent because no model call was made. No independent human ratings were entered; no improvement claim is supported.

## Opt-in inference budget

Three variants for 20 targets require 60 calls. Proposed completion cap: 600 tokens per call; estimated prompt input 256,836 tokens by characters divided by four. At repository-noted model token rates the estimate is USD 0.060125. Provider call fees are separately listed: Nous USD 0.003000; OpenRouter USD 0.012000. The repository does not specify whether these schedules combine; rates were not reverified.

## Example drafts

### NFL · CHI at SEA · 2026-11-02

Event-only: The Seattle Seahawks' offense has averaged -0.12 EPA per scrimmage play over its last 3 games, down 0.13 from the previous 4. The Chicago Bears have allowed 0.06 EPA per opposing scrimmage play over their last 3 games, up 0.15 from their previous 4.
Combined: The Seattle Seahawks' offense has averaged -0.12 EPA per scrimmage play over its last 3 games, down 0.13 from the previous 4. The Chicago Bears have allowed 0.06 EPA per opposing scrimmage play over their last 3 games, up 0.15 from their previous 4.
Core baseline output: not generated offline; prompt and local evidence are in examples.jsonl.

### NFL · JAX at BAL · 2026-11-05

Event-only: The Baltimore Ravens' offense has averaged -0.05 EPA per scrimmage play over its last 3 games, down 0.23 from the previous 4. The Jacksonville Jaguars have allowed 0.02 EPA per opposing scrimmage play over their last 3 games, up 0.13 from their previous 3.
Combined: The Baltimore Ravens' offense has averaged -0.05 EPA per scrimmage play over its last 3 games, down 0.23 from the previous 4. The Jacksonville Jaguars have allowed 0.02 EPA per opposing scrimmage play over their last 3 games, up 0.13 from their previous 3.
Core baseline output: not generated offline; prompt and local evidence are in examples.jsonl.

### NFL · ARI at SEA · 2026-11-08

Event-only: [no eligible preview]
Combined: [no eligible preview]
Core baseline output: not generated offline; prompt and local evidence are in examples.jsonl.

### NFL · CIN at ATL · 2026-11-08

Event-only: The Cincinnati Bengals' offense has averaged 0.17 EPA per scrimmage play over its last 3 games, up 0.11 from the previous 3. The Atlanta Falcons have allowed 0.03 EPA per opposing scrimmage play over their last 3 games, up 0.08 from their previous 4.
Combined: The Cincinnati Bengals' offense has averaged 0.17 EPA per scrimmage play over its last 3 games, up 0.11 from the previous 3. The Atlanta Falcons have allowed 0.03 EPA per opposing scrimmage play over their last 3 games, up 0.08 from their previous 4.
Core baseline output: not generated offline; prompt and local evidence are in examples.jsonl.

### NFL · CLE at NO · 2026-11-08

Event-only: The New Orleans Saints' offense has averaged -0.11 EPA per scrimmage play over its last 3 games, down 0.10 from the previous 4. The Cleveland Browns have allowed -0.11 EPA per opposing scrimmage play over their last 3 games, down 0.14 from their previous 4.
Combined: The New Orleans Saints' offense has averaged -0.11 EPA per scrimmage play over its last 3 games, down 0.10 from the previous 4. The Cleveland Browns have allowed -0.11 EPA per opposing scrimmage play over their last 3 games, down 0.14 from their previous 4. The Cleveland Browns are 5-2; the New Orleans Saints are 2-5.
Core baseline output: not generated offline; prompt and local evidence are in examples.jsonl.

### NFL · DAL at IND · 2026-11-08

Event-only: The Indianapolis Colts have lost three straight games.
Combined: The Indianapolis Colts have lost three straight games.
Core baseline output: not generated offline; prompt and local evidence are in examples.jsonl.

### NFL · DEN at CAR · 2026-11-08

Event-only: The Carolina Panthers' offense has averaged -0.10 EPA per scrimmage play over its last 3 games, down 0.22 from the previous 4. The Denver Broncos have allowed -0.20 EPA per opposing scrimmage play over their last 3 games, down 0.26 from their previous 4.
Combined: The Carolina Panthers' offense has averaged -0.10 EPA per scrimmage play over its last 3 games, down 0.22 from the previous 4. The Denver Broncos have allowed -0.20 EPA per opposing scrimmage play over their last 3 games, down 0.26 from their previous 4. The Denver Broncos are 5-2; the Carolina Panthers are 3-4.
Core baseline output: not generated offline; prompt and local evidence are in examples.jsonl.

### NFL · DET at MIA · 2026-11-08

Event-only: [no eligible preview]
Combined: [no eligible preview]
Core baseline output: not generated offline; prompt and local evidence are in examples.jsonl.

### NFL · GB at NE · 2026-11-08

Event-only: The New England Patriots' offense has averaged 0.21 EPA per scrimmage play over its last 3 games, up 0.27 from the previous 4. The Green Bay Packers have allowed -0.11 EPA per opposing scrimmage play over their last 3 games, down 0.08 from their previous 5.
Combined: The New England Patriots' offense has averaged 0.21 EPA per scrimmage play over its last 3 games, up 0.27 from the previous 4. The Green Bay Packers have allowed -0.11 EPA per opposing scrimmage play over their last 3 games, down 0.08 from their previous 5.
Core baseline output: not generated offline; prompt and local evidence are in examples.jsonl.

### NFL · HOU at LAC · 2026-11-08

Event-only: The Houston Texans' offense has averaged 0.10 EPA per scrimmage play over its last 3 games, up 0.11 from the previous 4. The Los Angeles Chargers have allowed -0.09 EPA per opposing scrimmage play over their last 3 games, down 0.10 from their previous 3.
Combined: The Houston Texans' offense has averaged 0.10 EPA per scrimmage play over its last 3 games, up 0.11 from the previous 4. The Los Angeles Chargers have allowed -0.09 EPA per opposing scrimmage play over their last 3 games, down 0.10 from their previous 3. The Houston Texans are 2-5; the Los Angeles Chargers are 0-6.
Core baseline output: not generated offline; prompt and local evidence are in examples.jsonl.

### NBA · BOS at ORL · 2026-11-01

Event-only: The Boston Celtics have won four straight games.
Combined: The Boston Celtics have won four straight games.
Core baseline output: not generated offline; prompt and local evidence are in examples.jsonl.

### NBA · BKN at IND · 2026-11-01

Event-only: The Brooklyn Nets have lost five straight games.
Combined: The Brooklyn Nets have lost five straight games.
Core baseline output: not generated offline; prompt and local evidence are in examples.jsonl.

### NBA · LAC at GS · 2026-11-01

Event-only: The LA Clippers have averaged 96.3 points over their last 3 games, down 17.4 from their 2025-26 regular-season average of 113.8. The Golden State Warriors have allowed 107.7 points over their last 3 games, down 7.5 from their 2025-26 average of 115.2.
Combined: The LA Clippers have averaged 96.3 points over their last 3 games, down 17.4 from their 2025-26 regular-season average of 113.8. The Golden State Warriors have allowed 107.7 points over their last 3 games, down 7.5 from their 2025-26 average of 115.2. The LA Clippers are 1-4; the Golden State Warriors are 3-3.
Core baseline output: not generated offline; prompt and local evidence are in examples.jsonl.

### NBA · TOR at LAL · 2026-11-01

Event-only: [no eligible preview]
Combined: [no eligible preview]
Core baseline output: not generated offline; prompt and local evidence are in examples.jsonl.

### NBA · OKC at CLE · 2026-11-02

Event-only: [no eligible preview]
Combined: [no eligible preview]
Core baseline output: not generated offline; prompt and local evidence are in examples.jsonl.

### NBA · DET at CHA · 2026-11-02

Event-only: The Charlotte Hornets have averaged 90.7 points over their last 3 games, down 25.3 from their 2025-26 regular-season average of 116.0. The Detroit Pistons have allowed 98.0 points over their last 3 games, down 11.6 from their 2025-26 average of 109.6.
Combined: The Charlotte Hornets have averaged 90.7 points over their last 3 games, down 25.3 from their 2025-26 regular-season average of 116.0. The Detroit Pistons have allowed 98.0 points over their last 3 games, down 11.6 from their 2025-26 average of 109.6. The Detroit Pistons are 5-1; the Charlotte Hornets are 3-4.
Core baseline output: not generated offline; prompt and local evidence are in examples.jsonl.

### NBA · ATL at IND · 2026-11-02

Event-only: The Indiana Pacers have lost three straight games.
Combined: The Indiana Pacers have lost three straight games.
Core baseline output: not generated offline; prompt and local evidence are in examples.jsonl.

### NBA · BKN at NY · 2026-11-02

Event-only: The Brooklyn Nets have lost five straight games.
Combined: The Brooklyn Nets have lost five straight games.
Core baseline output: not generated offline; prompt and local evidence are in examples.jsonl.

### NBA · WSH at ORL · 2026-11-02

Event-only: [no eligible preview]
Combined: [no eligible preview]
Core baseline output: not generated offline; prompt and local evidence are in examples.jsonl.

### NBA · CHI at PHI · 2026-11-02

Event-only: The Philadelphia 76ers have averaged 107.0 points over their last 3 games, down 8.9 from their 2025-26 regular-season average of 115.9. The Chicago Bulls have allowed 130.7 points over their last 3 games, up 9.2 from their 2025-26 average of 121.5.
Combined: The Philadelphia 76ers have averaged 107.0 points over their last 3 games, down 8.9 from their 2025-26 regular-season average of 115.9. The Chicago Bulls have allowed 130.7 points over their last 3 games, up 9.2 from their 2025-26 average of 121.5. The Chicago Bulls are 1-5; the Philadelphia 76ers are 6-1.
Core baseline output: not generated offline; prompt and local evidence are in examples.jsonl.

## Remaining limitations

- NFL schedule has local gametime without a timezone; its UTC game-date lower bound is sufficient to prove the shared cutoff precedes the target date, but is not the kickoff instant.
- Upcoming NBA schedule rows have no stored ESPN event crosswalk; no ESPN or publisher request was made.
- NBA team_game_stats has no populated current-season stat rows; this ranking uses local NBA schedule scores and prior-season nba_sportsdataverse_games scores.
- core_stories matchup_context from ESPN summary is marked unavailable in baseline manifests.
- No original-generator model output exists in offline mode, so there is no fair baseline rating or improvement claim.
- Ranking weights are deterministic heuristics and have not been trained or independently human-validated.
- Fourth-down and drive classifications remain quarantined in their separate correctness workstream.

Row-level artifacts: examples.jsonl, claim_audit.jsonl, rejected_facts.jsonl, database_coverage.json, baseline_generation_queue.jsonl, candidate_generation_queue.jsonl, and the blind review files.
