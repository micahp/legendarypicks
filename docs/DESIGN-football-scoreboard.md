# Football scoreboard: live and final

**Opened** 2026-10-03, from two screenshots Micah sent of the same live game (Memphis at
Charlotte, NCAAF): a betting app's "Happening now" card and ESPN's gamecast. Mockup (works on a phone):
https://claude.ai/artifact/BoeTo2QHtjB1wjmtqstPtp. Desktop-only design canvas of the same:
https://claude.ai/artifact/UTU9bMPzMTuF1re41ZoBV6. Both private until shared.

Governing docs, in order: `.claude/skills/honest-data-ui` (accent marks absence, quiet labels),
`docs/DESIGN-live-card-rail.md` (solid zinc surfaces, breathing emerald left edge, JetBrains Mono
scores, no red LIVE box), `docs/DESIGN-game-detail-tabs.md` (football box score in three columns),
`TASK-scores-schedule-espn-model.md` (the /scores rebuild this card lives inside, DB-primary).

## 1. What the screenshots specify

| element | betting-app card | ESPN gamecast | we take it? |
|---|---|---|---|
| score, clock, period | yes | yes | yes |
| possession marker | dots under score | ball on field | yes, a small ball glyph by the team |
| down & distance | "1st & 10" | in drive card | yes, mono, with the spot: `2nd & 5 · MEM 47` |
| field strip with ball spot | yes, yard numbers | yes, end zones in team color | yes: card size (30px) and page size (64px + numbers) |
| line to gain | yellow line | no | yes, a light line; none on goal-to-go |
| direction of travel | arrow | drive arrow | yes, a chevron at the ball |
| last play sentence | yes | yes, with clock | yes, with the time our feed first saw it |
| timeouts | no | no | yes, three ticks per team (the feed publishes them) |
| team records | no | yes (3-1, 0-4) | not stored; omitted |
| network (ESPN+) | no | yes | not stored; omitted |
| current drive (plays, yards, time) | no | yes | **not in our feed**; stated as absent |
| win probability | no | 96.9% | **not in our feed**; never shown as ours |
| touchdown takeover graphic | no | yes | no: a score reads as the last play, same place, same weight |
| odds buttons, handle, chat count | yes | no | no: priced lines live on their own surface (`priced-line-surfaces`) |

## 2. Where each field comes from

**Decided 2026-10-03: the ESPN scoreboard response we already fetch, then Kalshi as a fallback.**
ESPN's `/scoreboard` carries `competitions[0].situation` for every live football game: down,
distance, `yardLine` (yards from the HOME goal line), `downDistanceText`, `possessionText`,
`possession` (team id), `isRedZone`, timeouts, and `lastPlay` with `drive` (summary) and
`probability` (ESPN's win model). Parsed in `espn_client/scoreboard.py` `_football_situation`
(`5198428`); served on `/api/{league}/games` as `situation`, typed `FootballSituation` in
`services/sports.ts`. No new requests. Drive summary and ESPN win probability are therefore
available after all; the probability is carried with `source: "espn"` and is shown only as
ESPN's. The Kalshi fallback below is not built.

### Fallback: Kalshi (no ESPN)

Kalshi `GET /trade-api/v2/live_data/football_game/milestone/<id>`, provider **Stats Perform**,
measured 2026-10-03 on Memphis at Charlotte and Alabama at Mississippi St.:

- `situation.down`, `situation.yfd` (yards to first down), `situation.yardline`,
  `situation.side_team_id`, `situation.possession_team_id`, `situation.goal_to_go`
- `home_timeouts_remaining`, `away_timeouts_remaining`
- `last_play.description`, `last_play.occurence_ts` (`occurence_ts_source: first_seen`)
- `is_under_review`, `pending_try`, `quarter`, `clock`, points
- team ids map to sides through the milestone's `details.away_team_id` / `home_team_id`

A game before kickoff publishes every situation field as `null`: the card shows score and time
only. Score, clock and period already come from our scoreboard snapshot; the snapshot stores
none of the situation fields today (`espn_client/scoreboard.py` parses no `situation`).

Field geometry: ball position from the away goal line is `yardline` when `side_team_id` is the
away team, else `100 - yardline`; line to gain is that position plus `yfd` toward the
possession team's direction, capped at the goal line.

## 3. States

`live` (spot + line to gain) · `goal` (`1st & Goal`, no line to gain) · `review` (the words
"Under review" beside the clock, quiet) · `try` (after a touchdown, "Try" replaces down and
distance, no spot) · `final` (FINAL, winner full weight, loser muted, no field, no last play).
A live game the feed has no situation for says so in the accent color.

## 4. Other sports, same feed

| sport | Kalshi live_data publishes | card shows |
|---|---|---|
| baseball | `bases[]`, `balls`, `strikes`, `outs`, `inning`, `inning_half`, `period_scores` | base diamond, count, outs, inning half |
| basketball | `possession`, `period`, `period_remaining_time`, `last_event_is_timeout` | possession arrow; no court |
| hockey | `period`, `period_remaining_time` | score and clock only |

Football is the deepest; nothing else gets a field-sized graphic.

## 5. Not built

Nothing here is implemented. Building it needs: a collector that stores the football
`live_data` per game (the tennis collector, `prediction-market-trading/kalshi_live_points.py`,
is the pattern), a milestone-to-our-game join (date + teams), the API fields on `/games`, and
the frontend card. Measured lag for tennis: Kalshi's live data trails its own book by ~7-9s;
football is unmeasured.
