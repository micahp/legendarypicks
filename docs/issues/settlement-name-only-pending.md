# Issue: name-only props are left pending in settlement

- **Status:** open. Opened 2026-10-28 with the MLS identity closure.
- **Owner:** not assigned. The owner needs to be chosen by the project lead.
- **Remote issue:** not created. Creating a GitHub issue is remote publication, which is blocked until authorized.

## What the problem is

A prop whose player has no ESPN id (`players.espn_id` is NULL) can only be matched to a box score by name. The matcher
then looks in the box-score section for the stored club, `players.team`. That field holds the player's last club. It is
today's club, not the club the player was on in the game being settled. A player who has moved clubs can therefore be
matched in the wrong section, or not found at all.

## What changed on this branch

- `backend/settlement/settle_game.py`: a prop with no ESPN id is counted as `pending` and skipped before any matching.
  Nothing is written for it, and it is not settled or voided.
- `backend/settlement/ncaaf_settle.py`: the same guard.
- Test: `backend/test_settlement_name_only.py`. A name-only prop stays pending even when the box score has the player. The
  same prop with an ESPN id still settles.
- The settlement suites give 20 failed and 124 passed on this branch, and 20 failed and 122 passed on origin/dev. The
  failing sets are identical. The 20 failures predate this change and come from the environment.

## Size, measured read-only on production on 2026-10-28

"Unsettled" here means the prop has no `prop_results` row. It does not show that the game has finished. The counts are an
upper bound on what the guard keeps pending.

| League | Name-only players (no ESPN id) | Unsettled props, name-only | Unsettled props, all |
|---|---|---|---|
| mls | 182 of 1,415 | 2,644 | 21,722 |
| mlb | 1,666 of 2,449 | 1,626 | 4,414 |
| nhl | 99 of 1,147 | 2,136 | 26,066 |
| nba | 278 of 927 | 14 | 21,758 |
| ufc | 34 of 528 | 142 | 703 |
| ligamx | 69 of 627 | 0 | 385 |
| nfl | 8,228 of 27,023 | 0 | 74,501 |
| ncaaf | 0 of 22,854 | 0 | 22,538 |

NFL has name-only players but no unsettled name-only props. NCAAF has none.

## Not changed here

- `backend/routers/props.py` (about line 408, NHL prop history): for a player with no ESPN id, the historical hit display
  matches the box score by the stored club. This is display of past outcomes, not settlement. It is listed here so it
  is decided with the rest.

## Decision needed before this can close

Choose one way to give each name-only prop a reliable match:
1. Fill `players.espn_id` for name-only players, from a publisher that is allowed as a source. Then the guard does not
   hold them back.
2. Anchor the club to the game: use the player's own game-log club for that `game_id`, when the log comes from that game.
   This never uses today's club.

Also decide what happens to a name-only prop that stays unmatched for a long time: stay pending, or void after a deadline.
No deadline has been chosen.

## Closing criteria

- No prop settles, or is voided, from the stored club alone.
- Every name-only prop in the table above is either matched by a player ID, matched by its game's own club, or listed as
  pending with the reason.
- The unsettled counts above are re-measured and reported.
