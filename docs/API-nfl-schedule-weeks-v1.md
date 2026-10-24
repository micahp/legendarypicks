# Football schedule week contracts

NFL and NCAAF schedules are week-based. These contracts expose ESPN's own
phase/week calendar rather than treating either slate as a sequence of dates.
The NFL v1 names remain unchanged for compatibility; NCAAF uses the same shape
under its own contract name.

## Week catalog

`GET /api/nfl/schedule-weeks?season=2026&anchor=2026-07-21`

`GET /api/ncaaf/schedule-weeks?season=2026&anchor=2026-08-29`

Contract: `nfl-schedule-weeks-v1`

NCAAF contract: `ncaaf-schedule-weeks-v1`

The viewer supplies `anchor` as a local `YYYY-MM-DD` date. `season` is
optional; when omitted, January and February resolve to the prior football
league year and March through December resolve to the current year.

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

`GET /api/ncaaf/schedule-week?season=2026&season_type=2&week=1`

Contract: `nfl-schedule-week-v1`

NCAAF contract: `ncaaf-schedule-week-v1`

The response contains `selected_week` metadata and `games` in the same raw
game shape used by `/api/{league}/games`. The client should run those games
through the existing shared game normalizer.

Valid ESPN season types are:

- `1`: preseason
- `2`: regular season
- `3`: postseason

NCAAF games are read from our stored slates, one calendar day at a time, using
the published calendar boundaries of the requested week. A day we hold is served
from the store. A day we have never read that has already started is requested
from ESPN once, and a finished one is stored. A day that has not started and was
never read is not requested: its date is listed in `unread_days` and it adds no
games. `unread_days` is present on NCAAF responses only.

ESPN's own `week=` query caps NCAAF at 25 events (measured 2026-08-24), and its
date-range query returned HTTP 400 for NCAAF by 2026-10-24, so neither is used.
Games are kept only when their start falls inside the published week window and
their season type matches the request. Its CFP calendar entry uses ESPN's
special week value `999`, which the endpoint accepts only when that key exists
in the catalog. Season type `4` is off-season and omitted.

The endpoint verifies the requested phase/week against the catalog before
reading games. A day that cannot be read fails the request with HTTP 502 rather
than returning a week with that day missing.

## Frontend behavior

- NFL and NCAAF Schedule use week controls, not a date picker or daily arrows.
- Initial selection uses `default_week_key` unless a valid explicit week key
  is present in the URL.
- Previous/next traverses the ordered `weeks` catalog across phase boundaries.
- A selected week may contain games on several local dates; group them by the
  viewer's local date inside the week.
- An unavailable catalog or week is an error, not an empty slate.
