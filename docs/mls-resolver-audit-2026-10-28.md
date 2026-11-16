# Identity resolver audit: can a departed or transferred player still resolve?

Date: 2026-10-28. Development audit. Nothing here changes the serving path.

## What resolves a name at ingest

`_resolve_player_for_ingest` (`backend/_core.py`, around line 1085) is the one resolver for props ingest. Its
callers are `backend/routers/props.py` line 1442 (props ingest, which passes `game_id`) and line 1538 (bovada props,
which does not). Each step returns the first match:

| Step | What it reads | Checks current membership? | Checks a date? |
|---|---|---|---|
| 1. Exact name and league | `players.name` | No | No |
| 2. Normalized name, team and league | `players.name`, `players.team` | No | No |
| 2b. Folded name on both sides | `players.name` (folded index) | No | No |
| 3. Reviewed alias | `name_alias` | No | No |
| 4. Publisher roster | `published_roster` via `lookup_player` | No (stale rows match) | No |
| 5. No match | writes `unresolved_players` | n/a | n/a |

No step asks whether the person is on a club now, and no step takes an as-of date.

## Measured

- The real resolver, run on a scratch copy of the identity state, resolves **16 of 16** people who are not in the
  2026-10-28 squads, each with confidence `high`. Keegan Hughes (32676, stored club NE) and Bryce Duke (58967, SD) are
  examples.
- A transferred player resolves too. Marcos Zambrano (32334) has stored club NE. The publisher now says NYC, and the
  resolver still returns 32334 with confidence `high`.

## Findings

1. **Changing only `lookup_player` does not stop stale resolution.** Steps 1 to 3 match on names and return before
   step 4 is reached. A departed player is matched by name, and step 4 never runs.
2. **The stored club is not refreshed on a transfer.** `publish_identities` fills `players.team` only when it is
   empty (`COALESCE`). Step 2 compares the publisher's club with the stored club, so a transferred player falls
   through to the name-only steps. A departed player keeps the club he left.
3. **The resolver has no as-of date.** Only `routers/props.py:1442` passes `game_id`, and that is used for team
   tie-breaks, not for dates. A backfill of a past game resolves as of the day it runs.

## Why a plain filter would break history

A filter that checks only current membership would stop a player who has since left from matching a game he played
for that club. Settlement of his old props would then fail. So "current" and "as of the game" are two different
questions:

- **Current game** (the game is today or later, or no date is given): resolve through the binds in
  `player_source_ids`, then require the person to be in the latest verified snapshot (status `active` or `carried`).
  A bind with no current membership returns unresolved, and goes to the queue.
- **Historical game** (the game is before today): resolve through the binds, then the snapshot that was current on the
  game date. `roster_snapshots` keeps superseded rows with `captured_at`, so that snapshot exists. Binds in
  `player_source_ids` never expire, so an existing prop keeps its `player_id`.
- **Name-only steps (1, 2b, 3)** must not return a player for a current game unless that player is in the current
  membership. For a historical game they can stay, but only with the date check.

This is a design, not an implementation. It touches the serving path and settlement, so it needs its own change and
review.

## Not covered by this audit

- `players.team` is still written only by a manual script (`refresh_soccer_player_teams.py`). A fix to the resolver
  does not fix that field.
- The bovada path (`routers/props.py:1538`) passes no `game_id`, so it has no game date to use for history.
