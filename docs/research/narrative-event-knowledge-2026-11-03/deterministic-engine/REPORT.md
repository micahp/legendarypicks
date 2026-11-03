# CPU-only deterministic story engine

**Status:** research only. The new engine is not wired into `core_stories.py` or production.

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
