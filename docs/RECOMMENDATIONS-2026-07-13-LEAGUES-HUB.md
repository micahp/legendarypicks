# Leagues Hub product and design recommendations

**Date:** 2026-07-13
**Branch reviewed:** `feat/leagues-hub`

## Recommendation

The Leagues tab should become a league-specific command center, not a directory leading to
generic Stats pages.

ESPN's useful lesson is information architecture rather than its visual density. Each sport has
persistent league navigation and context-specific destinations. NFL exposes weekly leaders,
depth charts, injuries, and playoff information; MLB emphasizes teams, transactions, schedules,
and season-specific events. The league home changes with the current moment—offseason, draft,
playoffs, or trade deadline—instead of remaining a static template.

References:

- [ESPN NFL](https://www.espn.com/nfl/)
- [ESPN MLB](https://www.espn.com/mlb/)
- [ESPN NBA teams](https://www.espn.com/nba/teams)
- [ESPN World Cup schedule](https://www.espn.com/soccer/fixtures/_/league/FIFA.WORLD/fifa-world-cup)
- [ESPN MMA schedule](https://score-origin.espn.com/mma/schedule)
- Frontend design guidance: `/root/.claude/plugins/marketplaces/claude-plugins-official/plugins/frontend-design/skills/frontend-design/SKILL.md`

Legendary Picks should not attempt to reproduce ESPN's news operation. Its advantage is the
derived layer already present in the app: live discounts, momentum changes, projections, prop
history, game stories, predictions, and live esports state. A league page should answer:

> What matters in this league right now, and where is it turning?

The product standard should be:

> ESPN-grade breadth for understanding what is true. Legendary Picks-grade depth for
> understanding what is changing, why it matters, and what to do next.

The stats interface is not a separate reporting product. It is the human-readable surface of the
same identity, observation, feature, and prediction system that should power props research,
fantasy decisions, pregame forecasts, and live inference. A number shown in a league table and a
feature used by a model must resolve to the same player or team, use the same point-in-time input,
and carry the same definition, source, timestamp, coverage, and version.

The forecasting standard is calibrated probability rather than a single unexplained projection.
For each prediction, preserve the input and model versions, the as-of time, the predicted
distribution and uncertainty, and the evidence explaining why it differs from the prior forecast.
Backtests must reconstruct only information available at the historical prediction time. The UI
should expose enough of that lineage for a user to understand what changed without revealing
proprietary model internals.

## Turn league data into decisions

"What is changing" must have a concrete meaning. The league experience should detect and explain
four types of movement:

1. **Performance:** production or efficiency is moving relative to recent and season baselines.
2. **Opportunity:** minutes, usage, targets, carries, shots, line placement, or another role input
   changed.
3. **Matchup:** the next opponent materially strengthens or weakens the observed trend.
4. **Market divergence:** the app's projection or current evidence disagrees with a listed line or
   prop.

Every surfaced change should answer the same questions:

- Who or what changed?
- Which metrics demonstrate it?
- When did the change begin?
- Is the sample large and complete enough to trust?
- Why might the change persist or regress?
- What can the user inspect or do next?

The last question is important, but "act" should not be shorthand for "place a bet." An action can
open the supporting game log, inspect a player or team, compare a projection with a prop, evaluate
the next matchup, make a pick, or follow a live game. The interface should never leap from an
unexplained trend directly to a betting call to action.

## Recommended navigation

Replace the generic `Standings | Stats | Schedule` model with league-appropriate destinations:

| League | Recommended tabs |
|---|---|
| MLB, NBA, NHL | Overview · Games · Standings · Players · Teams |
| NFL | Overview · Week · Standings · Players · Teams |
| World Cup | Overview · Matches · Bracket · Groups · Pick'em |
| UFC | Overview · Events · Rankings · Fighters |
| Esports | Keep the immersive `/esports` experience, but represent it in the Leagues directory as Competitions |

`Stats` is too broad to communicate what a user will find. `Players` and `Teams` are recognizable
destinations and can expose league-appropriate category breakdowns.

## The essential new tab: Overview

Every league should open on an Overview that summarizes the current state of the competition:

```text
MLB                                      league switcher
─────────────────────────────────────────────────────────
THE TURN TAPE
[ LIVE: NYY rallying ] [ KC just turned hot ] [ Next: 7:10 ]

Tonight / Next up          What changed
game cards                 momentum crosses / live discounts

Standings race             Props to watch
division + cutline         line vs projection + recent form

League leaders             Teams
3 meaningful categories    divisions → team pages
```

The **Turn Tape** should be the page's one signature design element. It would combine live games,
recent momentum crosses, active live-discount signals, role changes, and the next important event
in a compact chronological rail. This is specific to Legendary Picks and expresses the product's
core idea: show the moment that matters while it is changing.

A Turn Tape item should be evidence-backed rather than written like a news headline:

```text
Anthony Edwards' scoring opportunity is rising
Shot attempts +18% over his last five; true shooting remains above his season rate.
Next: opponent context · Sample: 5 games
[View trend] [Open matchup] [Check points props]
```

The visible claim, evidence, comparison window, sample warning, and next actions should come from a
shared data contract. That prevents each league page from inventing a different definition of a
trend and keeps display-only signals distinct from validated model inputs.

Everything around that rail should remain quiet and disciplined. Keep the existing two-tone
`ink-900` page and `zinc-900` panel system. Do not compensate with more gradients, glowing cards,
or decorative league chrome.

## Connect the application's existing features

The league page should be the doorway into functionality that already exists:

- Game cards open box scores, play-by-play, game information, props, and the generated game story.
- Player names open profiles containing projections, recent game logs, and prop charts.
- Team names open a Team page containing roster, schedule, strength, and momentum.
- Upcoming games offer a **Make a pick** action that opens Predict with the league and game selected.
- Props to watch link into a Props view already filtered to that league.
- What changed consumes momentum crosses and active live-discount signals.
- World Cup exposes the bracket and eventually pick'em in the competition context.
- Esports retains its live broadcast, series state, player statistics, and model-versus-market view.

At present these capabilities feel like separate application experiments. The Leagues Hub can make
them feel like a single connected product.

## What the Sport.Fun corpus adds

The complete 25-article founder corpus is interpreted separately in
`docs/SPORTFUN-ARTICLE-CORPUS-NARRATIVE-2026-07-13.md`. Founder-stated facts and Legendary Picks
recommendations must remain distinct; the articles are product evidence, not authority for LP's
roadmap.

The durable founder-stated direction is:

- Complex machinery should produce a simple user experience
  (`crypto-natives-and-sports-fans-love-speculation-lets-build-them-a-paradise-1932099614204682564.md:14-20`).
- One account and one core feature spine should carry identity and progression across sports
  (`time-to-have-fun-1975652786701324715.md:29-56`,
  `founders-fun-based-1985662042074730850.md:42-54`).
- Skill needs visible receipts. Sport.Fun's first black-box skill system failed because users lacked
  clarity and control; the product moved toward explicit picks, leaderboards, divisions, badges, and
  status (`whos-gonna-carry-the-boats-2008566960842568018.md:55-76`,
  `now-execute-phase-2-2021207470526583114.md:143-153`).
- Research belongs beside the decision. The stated product direction puts injury, form, and
  transfer news alongside win percentages and odds in-game
  (`now-execute-phase-2-2021207470526583114.md:143-153`).
- The current free-to-play design uses meaningful constraints, squad depth, active picks,
  performance divisions, friends leagues, and greater progression rewards for successful
  unpopular picks (`official-strategy-guide-2062577274617209183.md:14-46`).
- The most recent UX framing gives each page a job: Home explains what matters now, Squad shows
  progress and eligibility, Transfers supports decisions with context, and Live combines real-time
  data, scoring, and social activity
  (`wc26-week-1-and-whats-next-2066972165480894766.md:59-92`).

The corpus also documents mechanics that changed or failed: the black-box Skill Rating lost its
main reward role, a dual-currency loop became TP-only, and the Development Squad was sunset
(`product-diary-1963932708276424774.md:58-71`,
`wen-wen-wen-soon-now-1967935255765016669.md:52-64`,
`sportfun-product-leaks-2014008101062820224.md:29-77`). The founder later warned users not to assume
specific mechanics would remain fixed
(`founder-thoughts-and-whats-next-for-sdf-2029982367083905277.md:23-57`).

Legendary Picks should therefore borrow the stable user needs, not the volatile economic layer:

- **Now:** make league changes inspectable, fix identity integrity, preserve point-in-time feature
  lineage, and connect every visible trend to the affected player and evidence.
- **Next:** create the props.cash-style path from change to player to game log to market line to LP
  probability and edge; add a free pick history with transparent scoring and friend comparison.
- **Later:** use the same calibrated projections for constrained fantasy lineups, skill divisions,
  progression, and lightweight onboarding minigames. Live play-by-play should update inference and
  explain forecast movement; audio/video remain later inputs when their incremental value justifies
  their cost.

Do not copy token issuance, tradable-player shares, liquidity management, buybacks, or
regulatory-driven reward mechanics into the near-term plan. Those mechanisms dominated much of the
founder communication and changed repeatedly; they are not required to deliver research, skill,
progression, or friend competition.

## Build advanced stats around each sport

ESPN is a useful reference for the statistical categories users already recognize. Its MLB pages
separate batting, pitching, and team statistics; NBA includes player views plus Team, Opponent, and
Differential team views; NFL separates offense, defense, and special teams; NHL separates skaters
and goaltenders; and World Cup statistics emphasize scoring, performance, and discipline.

References:

- [ESPN MLB player stats](https://www.espn.com/mlb/stats/player)
- [ESPN MLB team stats](https://www.espn.com/mlb/stats/team)
- [ESPN NBA player stats](https://www.espn.com/nba/stats/player)
- [ESPN NBA team stats](https://www.espn.com/nba/stats/team)
- [ESPN NFL player stats](https://www.espn.com/nfl/stats)
- [ESPN NFL team stats](https://www.espn.com/nfl/stats/team)
- [ESPN NHL player stats](https://www.espn.com/nhl/stats/player)
- [ESPN NHL team stats](https://www.espn.com/nhl/stats?view=team)
- [ESPN World Cup stats](https://global.espn.com/football/stats/_/league/fifa.world)

Legendary Picks should preserve those familiar reference categories, then add recent-versus-season
comparisons and decision context:

| League | Reference categories | Legendary Picks change layer |
|---|---|---|
| MLB | Hitting · Pitching · Contact quality · Discipline | xwOBA versus results, hard-hit/barrel movement, K%/BB% changes, pitcher contact suppression |
| NBA | Scoring · Playmaking · Rebounding · Defense · Efficiency | L5/L10 volume and efficiency, minutes or role changes, opponent and team differential context |
| NFL | Passing · Rushing · Receiving; later Defense | Target/carry share, EPA/CPOE, opportunity movement, matchup sensitivity |
| NHL | Skaters · Goalies · Special teams | Shots and ice time moving before goals, power-play role, recent-versus-season goalie form |
| World Cup | Scoring · Creation · Discipline | Shot creation, expected performance, tournament context, explicit small-sample labels |
| UFC | Rankings; then Striking · Grappling · Defense · Outcomes | Last-three-fights versus career, damage absorbed, takedown efficiency, defensive changes |

ESPN's MMA experience is principally useful for rankings, records, and upcoming-fight context. It
is not a sufficient model for advanced fighter statistics. UFCStats provides the more useful data
shape: significant strikes landed and absorbed, accuracy and defense, takedowns, submissions, and
per-fight results.

- [ESPN MMA rankings](https://www.espn.com/mma/story/_/id/21807736/mma-divisional-rankings-ufc-bellator-pfl-rankings)
- [UFCStats fighter example](https://ufcstats.com/fighter-details/e5549c82bfb5582d)

The Stats experience should contain real category navigation, sortable columns, URL-persisted
filters, and clear comparison windows. A compact "What changed" summary should sit above the full
table. The table establishes what is true; the summary identifies the important movement without
hiding its evidence.

Do not add low-value metadata merely because another sports site has it. Venue and location details
do not belong on ordinary score cards. Exhaustive archives, generic news, transactions, fielding,
and special-teams depth should only be added when they support a demonstrated user decision.

## Data readiness and honest coverage

The current data foundation is uneven, so the UI must not imply equal depth across every league:

- **MLB players:** strongest advanced-stat foundation, but not currently identity-safe. A read-only
  official comparison found 169 stored-name versus MLBAM identity mismatches among 2,397
  current-season referenced players. Recent-form evidence must continue to fail closed until a
  proposal-only identity repair is reviewed, tested on a database copy, and followed by
  authoritative stat regeneration.
- **MLB teams:** the only league with season-complete enough `team_game_results` for honest team
  aggregates. Build runs for, runs against, and run differential here first.
- **NBA:** enough player box-score and efficiency data to ship meaningful player categories now.
  Existing team-game-stat captures are partial, so do not present them as season team statistics.
- **NHL:** skater statistics are usable now, but team-game-stat captures are partial. Do not expose
  season team aggregates or a Goalies category until their intended populations have measured
  coverage.
- **NFL:** start with offensive players. There are no `team_game_results`; defensive-player,
  special-teams, CPOE, opportunity-share, and season team views require additional ingestion.
- **World Cup:** prioritize matches, group state, and bracket context before the competition has
  enough event data for meaningful trends.
- **UFC:** retain Rankings until per-fight fighter logs exist. Do not manufacture advanced fighter
  trends from ranking position alone.

A category should only appear when its intended population and recent history have measured,
high coverage. Missing categories should be omitted or labeled as unavailable rather than rendered
as an empty table that looks broken.

The current Teams subview is effectively another standings table. Replace it with measured MLB
aggregates and hide or remove it for leagues without sufficient coverage rather than filling the
same UI with partial data.

## Sport-specific schedule behavior

A schedule cannot be one generic day of identical cards for every competition:

- **MLB, NBA, NHL:** calendar-day navigation with an explicit selected date.
- **NFL:** week selector and week context, with date navigation secondary.
- **World Cup:** date plus stage/round grouping, match venue when available, and direct bracket context.
- **UFC:** event-level cards showing event name, date, time, venue when available, and main-card/prelim grouping.
- **Empty dates:** explain that the selected date has no events and offer the next scheduled date when known.

The branch's immediate Schedule correction adds selected-date visibility, previous/next controls,
a compact native date picker, URL state, date-aware empty/error states, chronological ordering, UFC
scheduled time, and grouping from API subtitles. That resolves the invisible-day bug, but it does
not replace the need for league-specific schedule models.

## Improve the `/leagues` directory

Replace emoji cards and permanent marketing descriptions with live competition state. Each league
entry should show:

- Current season or tournament stage
- Live-game count or next scheduled event
- A leading team, player, or fighter
- One meaningful current signal, such as `3 players heating up`, `Quarterfinals`, or `Next card Saturday`

ESPN's team directory also makes each team actionable through direct Statistics, Schedule, Roster,
and Depth Chart links. Legendary Picks should similarly make team names destinations rather than
plain text inside standings tables.

## Recommended build order

The schedule correction, league-specific player categories, sorting, URL state, and
recent-versus-earlier-season evidence are already implemented on this branch. Continue in this
order:

1. Build a proposal-only MLB identity repair planner. Require exact, unique, authoritative matches;
   queue ambiguity; test the application in one transaction on a database copy; and do not mutate
   the shared development database before the dry run is reviewed.
2. Replace the Teams standings duplicate with honest MLB aggregates, while hiding or removing the
   Teams destination in leagues without sufficient measured team-game coverage.
3. Run end-to-end verification against the real frontend/backend contract after those bounded data
   changes. Keep the existing dev tunnel and frontend process stable; do not use a mocked API as the
   only browser evidence.
4. Add Overview using the existing games, standings, leaders, UFC rankings, and World Cup bracket
   APIs, with an evidence-backed Turn Tape contract shared across leagues.
5. Make player, team, and game references consistently clickable and connect changes to game logs,
   projections, Props, and Predict.
6. Implement the props research path: change → affected player → history → line → LP distribution
   and probability → market edge, with feature and prediction versions visible in diagnostics.
7. Add free picks, transparent scoring, and friend comparison on the same user and prediction spine.
8. Add the missing ingestion for NHL goalies, NFL defense/opportunity, World Cup events, and UFC
   fighter logs before exposing their advanced categories.
9. Add constrained fantasy lineups, progression, and divisions only after identity integrity,
   calibration, point-in-time backtests, and coverage contracts are trusted.

### Scope boundary for the current branch

This branch has already shipped category-based, sortable player statistics and recent-form evidence.
Its remaining bounded proof should be:

- a reviewable, non-mutating MLB identity repair proposal;
- real MLB team aggregates with honest omission elsewhere;
- a compact, evidence-backed "What changed" contract that can connect to existing player, game,
  Props, and Predict destinations; and
- real-runtime verification of the resulting frontend/backend contract.

New NHL goalie, NFL defensive-player, World Cup event, and UFC per-fight ingestion should be
separately reviewable follow-up work. The current branch should define the interface and coverage
contract for those leagues, but it should not display placeholder or incomplete advanced data.

## Bottom line

ESPN helps users understand a league. Legendary Picks should help users understand what is changing
inside that league, show the evidence and uncertainty behind that judgment, and give them a direct
path to inspect the game, player, matchup, prop, projection, signal, or pick.
