# TASK — name alias table for NFL player identity resolution

Branch `feat/nfl-allday` in worktree `/root/lp-nfl-allday`. Do **not** touch `:3096` / `:8096`
— that is the live main dev env behind a public tunnel.

## Context

`docs/FINDINGS-nfl-allday.md` (Addendum 2) measured the All Day → `players` join at **98.1%**
across 1,591 moments from 8 real mainnet wallets. The residual 1.9% is **30 moments / 5
players**, and every one of them **is already in our spine** under a different name form:

| AllDay ships | our `players` row | class |
|---|---|---|
| Gabriel Davis (WR) | Gabe Davis (WR/BUF) | formal → familiar |
| Gregory Rousseau (DL) | Greg Rousseau (**LB**/BUF) | formal → familiar **+ position disagreement** |
| Michael Vick (QB) | Mike Vick (QB/PIT) | formal → familiar |
| Scotty Miller (WR) | Scott Miller (WR/MIA) **and** Scott Miller (WR/CHI) | nickname, genuinely ambiguous |
| Robby Anderson (WR) | **Robbie Chosen** (WR/WAS) | legal name change, 2022 |

A prefix/initial matcher was already tried and **reverted** — it resolves none of these.
`"gabriel".startswith("gabe")` is `False`; same for Michael/Mike. Do not re-attempt inference.
**This task is an explicit table.**

## Scope — the ONLY files you may create or modify

1. **CREATE** `backend/routers/nfl_name_aliases.py` — the tables and lookup helpers.
2. **CREATE** `backend/test_nfl_name_aliases.py` — tests for the above.
3. **MODIFY** `backend/routers/nfl_allday.py` — **only** inside `PlayerResolver`. Do not touch
   the Cadence scripts, the cache, the endpoint signature, or the response shape.
4. **MODIFY** `backend/test_nfl_allday.py` — add cases only; do not weaken existing ones.

## Do NOT touch — load-bearing, YOLO is on

- Any frontend file. The API response shape does not change, so the UI needs no edit.
- `backend/sports_service.py`, any other router, any shared util, `backend/data/*`.
- The `players` table itself. **Do not INSERT, UPDATE or DELETE any row.** This is a
  read-side resolution fix, not a data migration.
- `package.json`, lockfiles, `requirements.txt` — install nothing.
- Host-level config: `/etc`, systemd, cron, nginx, shell profiles.
- Git branch operations: no checkout/rebase/reset/merge/push. Commit on `feat/nfl-allday`.

## Design — two tables, kept separate

Do **not** merge these into one map. They are different kinds of fact and they fail differently.

1. **`FIRST_NAME_ALIASES`** — familiar ↔ formal *first names*, general-purpose, not
   All Day-specific. Seed it with a standard English nickname list (Mike/Michael,
   Gabe/Gabriel, Greg/Gregory, Scott/Scotty, Rob/Robby/Robbie/Robert, Bill/William,
   Bob/Robert, Chris/Christopher, Matt/Matthew, Nick/Nicholas, Tony/Anthony, Joe/Joseph,
   Dan/Daniel, Ben/Benjamin, Jim/James, Steve/Stephen, Ken/Kenneth, Ron/Ronald, …).
   Treat it as an equivalence relation: `mike ≡ michael` must work in both directions.
2. **`FULL_NAME_ALIASES`** — whole-name → whole-name, for **legal name changes only**, where
   the surname itself moved. Seed with exactly one entry, `Robby Anderson → Robbie Chosen`,
   and comment it with the year (2022). Do not speculatively add others.

## Resolution order in `PlayerResolver.resolve`

Try in this order and stop at the first hit:

1. Exact normalised full-name match (existing behaviour — unchanged).
2. `FULL_NAME_ALIASES` lookup, then exact match on the aliased name.
3. First name expanded through `FIRST_NAME_ALIASES`, with the **surname matching exactly**.

**Rules that are not negotiable:**

- **Never guess.** If step 3 yields more than one candidate after position filtering, return
  `None`. `Scotty Miller` must stay unmatched — there are two Scott Millers and picking either
  is a wrong join.
- **Position disambiguates; it does not reject.** If a step-3 expansion produces exactly ONE
  candidate, accept it even when the position disagrees — All Day says `DL` for Gregory
  Rousseau where our spine says `LB`, and that is a real vocabulary difference, not a
  different human. If it produces several, use position to narrow, and if that still leaves
  more than one, return `None`.
- Keep including inactive players (`active=0`). Retired players hold moments.
- Build any new index **once in `__init__`**, like `_by_name`. Do not add a per-moment query —
  the whole point of `PlayerResolver` was killing the per-moment DB hit.

## Verify — exact numbers, do not skip

Restart the worktree backend (it has no `--reload`), from `/root/lp-nfl-allday/backend`:

```
pkill -f "port 8097"; sleep 3
LP_DB_PATH=data/picks.dev.db nohup venv/bin/python venv/bin/uvicorn \
  sports_service:app --port 8097 --host 127.0.0.1 > /tmp/be8097.log 2>&1 &
```

Then measure `limit=200&offset=0` against these 8 wallets and sum:

```
0xc2544e942028e947 0x379c2a0e88d8081f 0x6d9da560c16a2498 0x3d99869d46ecad15
0x7de2c3a8c5838385 0xf471482157b596fe 0xdc033ea7e143cf39 0x5191a7333fe8e63b
```

| | before (measured) | required after |
|---|---|---|
| `matched` | 1,510 | **1,538** |
| `unmatched` | 30 | **2** (the two Scotty Miller moments, and only those) |
| `nonPlayer` | 51 | **51** — unchanged |
| player-moment match rate | 98.1% | **~99.9%** |

**No-regression requirement:** no moment that already resolved may now resolve to a *different*
`player.id`. Prove it — capture `{momentId: player.id}` for all 8 wallets before your change,
compare after, and report the diff count (it must be 0 for previously-matched moments).

Run `cd backend && venv/bin/python -m pytest test_nfl_allday.py test_nfl_name_aliases.py -q`.
**16 tests pass today; all 16 must still pass**, plus yours.

## Report back

- The before/after table with your measured numbers.
- The no-regression diff count.
- Any name you added to `FIRST_NAME_ALIASES` that you could not verify against a real player,
  and anything you found but did not fix.

Commit on `feat/nfl-allday`. Do not push.
