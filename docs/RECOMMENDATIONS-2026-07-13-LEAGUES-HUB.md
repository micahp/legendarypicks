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
recent momentum crosses, active live-discount signals, and the next important event in a compact
chronological rail. This is specific to Legendary Picks and expresses the product's core idea:
show the moment that matters while it is changing.

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

## Sport-specific schedule behavior

A schedule cannot be one generic day of identical cards for every competition:

- **MLB, NBA, NHL:** calendar-day navigation with explicit local date and timezone.
- **NFL:** week selector and week context, with date navigation secondary.
- **World Cup:** date plus stage/round grouping, match venue when available, and direct bracket context.
- **UFC:** event-level cards showing event name, date, time, venue when available, and main-card/prelim grouping.
- **Empty dates:** explain that the selected date has no events and offer the next scheduled date when known.

The branch's immediate Schedule correction adds selected-date visibility, previous/next controls,
a native date picker, URL state, timezone context, date-aware empty/error states, chronological
ordering, UFC scheduled time, and grouping from API subtitles. That resolves the invisible-day bug,
but it does not replace the need for league-specific schedule models.

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
2. Add Overview using the existing games, standings, leaders, UFC rankings, and World Cup bracket APIs.
3. Make player, team, and game references consistently clickable.
4. Add Team pages; roster and strength endpoints already exist.
5. Integrate Props, Predict, momentum, and live discounts into Overview.
6. Replace generic tabs with the league-specific sets defined above.

## Bottom line

ESPN helps users understand a league. Legendary Picks should help users understand what is changing
inside that league—and give them a direct path to inspect the game, player, prop, signal, or pick.
