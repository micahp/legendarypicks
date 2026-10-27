# Safeguard proposal: the name-and-club binding path in published_roster.py

Status: proposal. Not built, not merged, not run on prod. Line numbers are from `backend/published_roster.py`
on `origin/dev` (7ce9ae4e).

## The path

`publish_identities` binds an unbound publisher key to a canonical player by name and club, at these points:

| Lines | What it does | Evidence it uses | Risk |
|---|---|---|---|
| 555 to 558 | A key's name matches one existing player at the same club, and that player holds no conflicting key from this publisher. The key is bound to that player. | Name and club only | This is the path that bound FotMob 1259117 (Paysandu) to the LAFC Thayllon on 7 Sept. Nothing checks birth date, game logs, or a second source. |
| 562 to 588 | A single name match at another club. Bound only if the game logs show the publisher's club, or the stored club, for that player. | Game logs | Acceptable: the bind needs dated evidence. Refused as `unverified_team` otherwise (line 587). |
| 594 to 598 | Name matches exist, but each is taken by a different key from the same publisher. The key becomes a new player. | Publisher key conflict | Acceptable. Creates a namesake only. |

Only the first row is unsafe. It is the only bind that rests on name and club alone.

## Proposed narrow safeguard

At lines 557 to 558, bind only if at least one of these holds:

1. The candidate's game logs include the publisher's club (the same test that line 582 already uses).
2. The candidate already holds a key from the other publisher, and that key's roster row names the same club.
   This is a cross-source pair. It is accepted only when the other key was bound by one of the evidence rules above.

Otherwise, refuse the key with a new reason, `unverified_same_club`, and count it as an unresolved identity.
The key is not bound and no player is created.

## What this does not change

- Keys that already have a bind are untouched.
- Keys with no name candidate still create a new player, as now.
- The game-log rules at lines 562 to 588 and the namesake rule at lines 594 to 598 are untouched.

## Expected effect on the current roster

- The 1,855 current keys are all bound already (checked read-only on 2026-10-27), so the safeguard changes no current binding.
- Its effect is on new keys only. Measure it on a production-shaped copy by replaying the last verified
  roster and counting `unverified_same_club` refusals before any run on prod.

## Tests to add before merge

- Same name and club, no game logs, no second source: refused, not bound.
- Same name and club, cross-source pair already bound with the same club: bound.
- Same name and club, logs show the published club: bound (existing behavior).
- Name matches a player who holds a different key from the same publisher: new player (existing behavior).
- Stale row with the same name and club as a current player: not bound, and it does not block the current player.

## Why this is narrow

It removes one name-only decision and keeps every decision that already has dated or cross-source evidence.
It does not stop the roster job or change how it reports blockers.
