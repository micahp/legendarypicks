# League schedule-date discovery v1

## GET `/api/{league}/schedule-dates?anchor=YYYY-MM-DD`

Contract: `league-schedule-dates-v1`

This bounded discovery contract supports the non-NFL league-page Schedule
default and previous/next navigation. The client converts the returned
absolute event starts into the viewer's local calendar and picks:

1. the earliest local date after the anchor that contains a game;
2. otherwise, the most recent local date before the anchor that contains a game;
3. otherwise, the unchanged anchor date and the honest empty state.

The endpoint returns at most 64 starts from the nearest non-empty future search
window and 64 from the nearest non-empty past search window. Search windows are
bounded to 370 days and recorded in the response. ESPN range responses are
cached for 15 minutes; the HTTP response is cacheable for five minutes.

Event starts remain ISO instants rather than backend-derived dates. The backend
cannot know the viewer's timezone, and an evening US game commonly begins on
the following UTC date. The browser is authoritative for the displayed local
day.

Example shape:

```json
{
  "contract": "league-schedule-dates-v1",
  "league": "nba",
  "anchor_date": "2026-07-21",
  "event_start_timezone": "UTC",
  "future_event_starts": ["2026-10-06T00:00Z"],
  "past_event_starts": ["2026-04-13T00:30Z"],
  "search": {
    "future": [
      {
        "start_date": "2026-07-21",
        "end_date": "2026-08-04",
        "event_starts_found": 0
      }
    ],
    "past": [],
    "max_horizon_days": 370
  }
}
```

Automatic resolution is default-only: an explicit `?date=` URL, a date-picker
choice, and "Jump to today" stay on the requested day even when it is empty.
Previous/next arrows are different, explicit user actions: they use this same
contract to jump directly to the nearest earlier or later date that contains a
game, skipping empty calendar days.

NFL does not use daily navigation. Its league page consumes the dedicated
`nfl-schedule-weeks-v1` and `nfl-schedule-week-v1` contracts documented in
`API-nfl-schedule-weeks-v1.md`.
