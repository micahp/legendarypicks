# League schedule-date discovery v1

## GET `/api/{league}/schedule-dates?anchor=YYYY-MM-DD`

Contract: `league-schedule-dates-v1`

This bounded discovery contract supports the league-page Schedule default. The
client first checks the viewer's local current day. If that day has no games and
the URL did not explicitly select a date, it requests this contract, converts
the returned absolute event starts into the viewer's local calendar, and picks:

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
  "league": "nfl",
  "anchor_date": "2026-07-21",
  "event_start_timezone": "UTC",
  "future_event_starts": ["2026-08-07T00:00Z"],
  "past_event_starts": ["2026-02-09T01:30Z"],
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

The auto-resolution behavior is default-only. Explicit `?date=` URLs and dates
chosen with arrows, the date picker, or "Jump to today" must never be silently
redirected away from an empty day.
