# NFL schedule week contracts

The NFL league schedule is week-based. These contracts expose ESPN's own
preseason, regular-season, and postseason calendar rather than treating the
slate as a sequence of calendar days.

## Week catalog

`GET /api/nfl/schedule-weeks?season=2026&anchor=2026-07-21`

Contract: `nfl-schedule-weeks-v1`

The viewer supplies `anchor` as a local `YYYY-MM-DD` date. `season` is
optional; when omitted, January and February resolve to the prior NFL league
year and March through December resolve to the current year.

The response contains:

- `navigation: "week"`
- ordered `phases` with ESPN's phase labels
- a flat ordered `weeks` array for previous/next navigation
- stable week keys in `{season_type}:{week}` form
- ESPN labels such as `Hall of Fame Weekend`, `Preseason Week 1`, `Week 1`,
  and postseason round names
- `default_week_key`, selected as the current week, the next week before the
  season starts, or the latest week after the verified calendar ends
- `default_reason`: `current`, `next`, or `latest`

Each week carries absolute `start_time` and `end_time` values plus ESPN's
display `detail`. The frontend should render the supplied label and detail; it
must not reconstruct preseason or postseason labels from week numbers.

## One week's games

`GET /api/nfl/schedule-week?season=2026&season_type=2&week=1`

Contract: `nfl-schedule-week-v1`

The response contains `selected_week` metadata and `games` in the same raw
game shape used by `/api/{league}/games`. The client should run those games
through the existing shared game normalizer.

Valid ESPN season types are:

- `1`: preseason
- `2`: regular season
- `3`: postseason

The endpoint verifies the requested phase/week against the catalog before
fetching games. ESPN results are also filtered by season, season type, and week
so a broad or malformed upstream response cannot leak games from another
slate.

## Frontend behavior

- NFL Schedule uses week controls, not a date picker or daily arrows.
- Initial selection uses `default_week_key` unless a valid explicit week key
  is present in the URL.
- Previous/next traverses the ordered `weeks` catalog across phase boundaries.
- A selected week may contain games on several local dates; group them by the
  viewer's local date inside the week.
- An unavailable catalog or week is an error, not an empty slate.
