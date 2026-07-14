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

- **MLB:** strongest advanced foundation. Build production, contact-quality, discipline, and form
  views first; add conventional pitching results where the current Statcast aggregates lack them.
- **NBA:** enough player box-score and efficiency data to ship meaningful categories now. Aggregate
  existing team game statistics for Team, Opponent, and Differential views.
- **NHL:** skater statistics are usable now. Do not expose a Goalies category until goaltending data
  is ingested and coverage is measured.
- **NFL:** start with offensive players. Defensive-player, special-teams, CPOE, and opportunity-share
  views require additional ingestion.
- **World Cup:** prioritize matches, group state, and bracket context before the competition has
  enough event data for meaningful trends.
- **UFC:** retain Rankings until per-fight fighter logs exist. Do not manufacture advanced fighter
  trends from ranking position alone.

A category should only appear when its intended population and recent history have measured,
high coverage. Missing categories should be omitted or labeled as unavailable rather than rendered
as an empty table that looks broken.

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

1. Finish and browser-verify the current Schedule UX correction.
2. Replace the current generic Stats table with league-specific categories and real team aggregates.
3. Add L5/L10/season comparisons and an evidence-backed "What changed" summary, beginning with MLB
   and NBA, then NHL skaters and NFL offense.
4. Add Overview using the existing games, standings, leaders, UFC rankings, and World Cup bracket APIs.
5. Make player, team, and game references consistently clickable.
6. Add Team pages; roster and strength endpoints already exist.
7. Integrate Props, Predict, momentum, and live discounts into Overview and Turn Tape actions.
8. Add the missing ingestion for NHL goalies, NFL defense/opportunity, World Cup events, and UFC
   fighter logs before exposing their advanced categories.
9. Replace generic tabs with the league-specific sets defined above.

### Scope boundary for the current branch

This branch should prove the complete loop without becoming a rewrite of every sports pipeline:

- Ship category-based, sortable player statistics.
- Replace "Teams" as a standings duplicate with real team statistical aggregates.
- Add L5/L10/season deltas from existing game logs.
- Surface one compact, evidence-backed "What changed" section above the tables.
- Connect its actions to existing player, game, Props, and Predict destinations.
- Implement the complete pattern first for MLB and NBA, then reuse it where current data is ready.

New NHL goalie, NFL defensive-player, World Cup event, and UFC per-fight ingestion should be
separately reviewable follow-up work. The current branch should define the interface and coverage
contract for those leagues, but it should not display placeholder or incomplete advanced data.

## Bottom line

ESPN helps users understand a league. Legendary Picks should help users understand what is changing
inside that league, show the evidence and uncertainty behind that judgment, and give them a direct
path to inspect the game, player, matchup, prop, projection, signal, or pick.
