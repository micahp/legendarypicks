# job16 — mock-draft pool payload must carry what the overlay already carries

**Owner:** Codex (backend). **Frontend is out of scope and owned by Claude — do not touch it.**
**Branch:** cut from `dev` @ `5af128e` (v0.6.12).

## The gap, measured 2026-07-28

Two endpoints describe the same 300 players. They do not agree on what a player is.

| field | `/api/nfl/mock-draft/pool?season=2026` | `/api/nfl/draft/player/{id}` |
|---|---|---|
| `player_id` `name` `position` `team` | ✅ | ✅ |
| `adp` `percent_owned` `sample` | ✅ | ✅ |
| `games_played` `games_missed` `weeks_played` `team_weeks` | ✅ | ✅ |
| `team_games` | ❌ **absent** | ✅ |
| `ppr_per_game_played` `ppr_per_team_game` | ❌ **absent** | ✅ |
| `xfp_per_game` | ❌ **absent** | ✅ |
| `snap_pct` `target_share` | ❌ **absent** | ✅ |
| `pk_pts_total` `pk_pts_per_game` | ❌ **absent** | ✅ |
| `dst_pts_total` `dst_pts_per_game` | ❌ **absent** | ✅ |

Consequence in the product: the draft pool renders `# · Player · Pos · Available · ADP` and
**not one production number**. To compare two backs a user must open a modal, read it, close
it, open another, and hold the first figure in their head. The data exists; it is one HTTP
call away from the row that needs it. `DraftRoom.tsx` also falls back to a hardcoded
`TEAM_GAMES = 17` purely because `team_games` is missing here — that is **B14** and this task
retires it.

`/api/nfl/draft-board` carries the same fields but caps at `limit=100`, so a client-side join
costs 3–7 requests and risks silently missing a player the pool guarantees (all 32 D/ST).
**The pool payload is the correct home. That is why this is backend work, not a frontend join.**

## What to do

Edit **`backend/routers/nfl_mock_draft.py`, the `pool()` endpoint only** (`:157`). Add these
ten fields to every row:

```
team_games
ppr_per_game_played   ppr_per_team_game
xfp_per_game
snap_pct              target_share
pk_pts_total          pk_pts_per_game
dst_pts_total         dst_pts_per_game
```

## Hard constraints

1. **Copy the derivation, do not write one.** `/api/nfl/draft/player/{id}` (`:537`) already
   computes every one of these. Reuse those helpers. If a helper is per-player, lift it to a
   set-based form — do **not** re-derive the statistic from a different source. A second
   implementation of the same number is the defect class we keep paying for.
2. **One value, two endpoints.** For any given `player_id`, the pool row and the player-detail
   row must be **byte-identical** on all ten fields. This is the acceptance test, not a nicety.
3. **No N+1.** The pool is 300 rows. It must not become 300 queries. Baseline measured today:
   **0.145 s / 77,836 bytes**, three runs. Budget: **≤ 0.40 s**. Record the measured number in
   the commit message.
4. **`null` stays `null`.** No zero-fill, no `0.0` substitution, no synthesised averages.
   Absence is a rendering concern and the frontend already handles it (`honest-data-ui` §6.3).
5. **Additive only.** Do not rename, reorder, retype, or remove an existing key. The frontend
   reads this payload today and I am editing it in parallel.
6. **Do not touch:** `backend/routers/nfl_offseason.py`, `_core.py`, any shared util, any other
   router, any migration, any test outside the one you add, anything under `/etc`, systemd,
   cron, or any running server. No schema changes — every field here is already derivable from
   the current schema, which is what makes this independent of your migration work.

## Acceptance — these values were measured BEFORE this task was written

`GET /api/nfl/mock-draft/pool?season=2026`, one row per position:

| player_id | name | pos | team_games | ppr/gp | ppr/tg | xfp/g | snap% | tgt% | pk_tot | pk/g | dst_tot | dst/g |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 469 | Josh Allen | QB | 17 | 21.4 | 21.4 | 20.4 | 98.0 | null | null | null | null | null |
| 7979 | Jahmyr Gibbs | RB | 17 | 21.6 | 21.6 | 18.0 | 67.0 | 16.1 | null | null | null | null |
| 16247 | Puka Nacua | WR | 17 | 23.4 | 22.1 | 19.0 | 68.0 | 30.1 | null | null | null | null |
| 11274 | Justin Jefferson | WR | 17 | 11.9 | 11.9 | 14.7 | 94.0 | 30.7 | null | null | null | null |
| 14572 | Trey McBride | TE | 17 | 18.6 | 18.6 | 17.8 | 91.0 | 27.9 | null | null | null | null |
| 882 | Brandon Aubrey | PK | 17 | null | 0.0 | 0.8 | null | null | 181.0 | 10.6 | null | null |
| 30103 | Denver Broncos D/ST | DEF | 17 | null | null | null | null | null | null | null | 139.0 | 8.2 |

Aubrey's `ppr_per_team_game: 0.0` / `xfp_per_game: 0.8` are the **B8 fake-punt artifact** — one
carry on a trick play. Reproduce them **exactly as the detail endpoint emits them**. They are
wrong upstream, not here, and suppressing them in this endpoint would hide a known defect
behind a second opinion. Rendering is mine to suppress.

## Test to add

One test file, `backend/test_mock_draft_pool_parity.py`. It must assert **cross-endpoint
agreement**, not field presence — a row that carries ten `null`s would pass a presence check
and that is exactly the failure mode we keep shipping:

- for at least one player of **each** of QB / RB / WR / TE / PK / DEF, every one of the ten
  fields equals `/api/nfl/draft/player/{id}` for the same id;
- the table above is encoded literally as expected values;
- a DEF row has `dst_pts_per_game` **non-null** and `ppr_per_game_played` **null**;
- a PK row has `pk_pts_per_game` **non-null**;
- pool row count is still 300 and all 32 D/ST are still present.

## Definition of done

- `backend/test_mock_draft_pool_parity.py` passes, exit code captured and pasted.
- Measured pool latency and payload size pasted, both before and after.
- `git diff --stat` shows exactly two files: the router and the new test.
- One commit, message names the measured latency.
- **Do not merge to `dev` and do not push.** Report the branch and SHA; Claude rebases the
  frontend onto it.
