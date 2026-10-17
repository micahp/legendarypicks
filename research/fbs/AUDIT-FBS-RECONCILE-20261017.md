# FBS reconciliation - 2026-10-17

Read-only. Database `/root/legendarypicks/backend/data/picks.dev.db`. Fixtures file `/root/lp-fbs-audit/research/fbs/dev_linked_fixtures.json` (323 linked fixtures). Nothing was written.

## 1. Coverage of our prop fixtures

The denominator is the 323 NCAAF `prop_games` rows that carry an ESPN event id. That is the population we can actually grade, so coverage is measured against it and not against the publisher's whole season.

| release | season | games | of our fixtures | coverage |
|---|---|---|---|---|
| ESPN play-by-play | 2026 | 455 | 275 | 85.1% |
| stats.ncaa.org play-by-play (cfbfastR) | 2026 | 795 | 261 | 80.8% |
| ESPN player box scores | 2026 | 455 | 275 | 85.1% |
| ESPN game rosters | 2026 | 447 | 269 | 83.3% |
| ESPN team box scores | 2026 | 455 | 275 | 85.1% |

Every release above is a season-2026 file and our props are 2026, so coverage here is a real measurement rather than a season mismatch.

### Fixtures the release does not cover

| measure | count |
|---|---|
| fixtures the release does not cover | 48 |
| of those, kickoff is in the future | 45 |
| of those, kickoff has passed | 3 |

The two groups are different things and must not be read as one. A fixture whose kickoff has not happened yet has no box score anywhere, including in the release. A fixture whose kickoff HAS passed and is still absent is either in progress at the moment of this run or a coverage gap; the stored `final_home`/`final_away` tells which, because a game in progress has no stored score either.

Past-kickoff fixtures absent from the release:

| espn event id | kickoff | home | away | stored final | state at this run |
|---|---|---|---|---|---|
| 401858493 | 2026-10-17T00:00:00+00:00 | Purdue Boilermakers | Washington Huskies | None-None | no stored score, so in progress or not settled |
| 401862801 | 2026-10-16T23:30:00+00:00 | Tulane Green Wave | Memphis Tigers | None-None | no stored score, so in progress or not settled |
| 401869844 | 2026-10-17T00:00:00Z | Coastal Carolina Chanticleers | App State Mountaineers | None-None | no stored score, so in progress or not settled |

## 2. Does the release agree with the stored final score?

For every fixture where the release has a final score and our stored `prop_games` row has one, compare them. The stored score is the book's result, which is what the prop was settled against. A disagreement means the two publishers describe different games.

| measure | count |
|---|---|
| fixtures with both scores | 272 |
| agree | 272 |
| disagree | 0 |
| release has no score for the fixture | 48 |
| stored row has no score | 3 |

No disagreements in this run.

## 3. Player identity across publishers

The release carries an ESPN athlete id (`athlete_id`, or `rusher_player_id` / `passer_player_id` / `receiver_player_id` in play-by-play). Our spine carries `players.espn_id` from CFBD. The join is exact-id only; a name join would manufacture matches.

| measure | count |
|---|---|
| spine rows with an ESPN id | 23360 |

| measure | count |
|---|---|
| distinct athletes in the 2026 player box | 11887 |
| of those on our spine by ESPN id | 10359 |
| of those NOT on our spine | 1528 |

The unresolved athletes are a spine gap, not a release defect: the release publishes their box score and our roster ingest never created the row to join to. The count is reported, not repaired.

| measure | count |
|---|---|
| (game, athlete) pairs with any play attributed | 11435 |
| distinct games with attributed plays | 455 |

## 4. Props with a release box score vs without

Section 5 of the coverage audit measures whether the stored CFBD log exists. This section asks the same question of the release. The two differ: the release is a different publisher with a different coverage floor, so a prop gradeable against one may not be gradeable against the other.

| market | props | with a release box score | share | with an attributed play | share | no athlete id |
|---|---|---|---|---|---|---|
| receiving_yards | 28382 | 22238 | 78.4% | 23366 | 82.3% | 0 |
| rushing_yards | 16890 | 14150 | 83.8% | 14140 | 83.7% | 0 |
| passing_yards | 10552 | 9096 | 86.2% | 9096 | 86.2% | 0 |
| total_touchdowns | 5634 | 4264 | 75.7% | 4350 | 77.2% | 0 |
| receptions | 5450 | 4342 | 79.7% | 4502 | 82.6% | 0 |
| rushing_receiving_yards | 2902 | 2488 | 85.7% | 2488 | 85.7% | 0 |
| passing_touchdowns | 2756 | 2314 | 84.0% | 2314 | 84.0% | 0 |
| passing_rushing_yards | 1676 | 1468 | 87.6% | 1468 | 87.6% | 0 |
| rush_attempts | 1508 | 1402 | 93.0% | 1402 | 93.0% | 0 |
| kicking_points | 1188 | 980 | 82.5% | 0 | 0.0% | 0 |
| pass_attempts | 1076 | 1000 | 92.9% | 1000 | 92.9% | 0 |
| pass_completions | 924 | 828 | 89.6% | 828 | 89.6% | 0 |
| total_passing_touchdowns | 590 | 488 | 82.7% | 488 | 82.7% | 0 |
| extra_points_made | 184 | 136 | 73.9% | 0 | 0.0% | 0 |
| interceptions_thrown | 176 | 156 | 88.6% | 156 | 88.6% | 0 |
| rushing_receiving_touchdowns | 134 | 104 | 77.6% | 104 | 77.6% | 0 |
| field_goals_made | 30 | 30 | 100.0% | 0 | 0.0% | 0 |
| rushing_touchdowns | 6 | 6 | 100.0% | 6 | 100.0% | 0 |

`with a release box score` joins on the release's `game_id` and `athlete_id`. `with an attributed play` is the play-by-play's own attribution, which covers players who appeared without a box-score row (a player who played special teams only, for example). The two are different populations and the report shows both. `no athlete id` is a prop whose own player row has no ESPN id, which cannot be joined to anything.
