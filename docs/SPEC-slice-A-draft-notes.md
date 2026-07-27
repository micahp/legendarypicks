# SPEC: Slice A — draft notes on the server

Status: **specified 2026-07-27, not yet built.** Ships in **v0.7.0** with slice D
(`SPEC-accounts-and-mock-draft.md` §6). Closes **R8**.

Parent spec: `SPEC-accounts-and-mock-draft.md` — read §1 (we already have an identity
system) and §2 Phase 0 first. This file is the build-level detail for that phase.

---

## 1. What this is, in one paragraph

`rank` / `watch` / `fade` on the NFL draft board live in `localStorage` under
`lp_nfl_draft_notes` and have no server row at all
(`components/Leagues/hooks/useNflDraftBoard.ts:18`). They die on a cache clear and are
invisible between a phone and a laptop. Slice A gives them a server row keyed by the
`X-Device-Id` the browser already sends, and demotes `localStorage` to a cache. Nothing is
gated, nothing changes visually, and no account exists yet.

**Why it is first:** slice C's nudge says *"sign up to keep it."* That sentence is a lie
until the rows are already on the server and sign-up is just attaching a name to them. If
the gate ships before the storage, everyone who ranked players in week one loses their work
— and they are precisely the users who cared most.

---

## 2. Identity — do not invent one

`lib/deviceId.ts` mints a UUID into `localStorage` as `lp_device_id` and callers send it as
the `X-Device-Id` header. Two surfaces already key real rows to it: `ufc_picks` and
`esports_picks` (both `device_id TEXT NOT NULL`, verified in `backend/data/picks.dev.db`).
The draft board is the outlier. Copy `backend/routers/ufc_picks.py:84` `_device_id()` —
trim, empty means absent — rather than writing a second normaliser.

A missing or blank header is a **400**, not an anonymous bucket. There is no such thing as a
note that belongs to nobody, and a shared empty-string row would merge every device on
earth into one set of notes.

---

## 3. Data model

New table. `_init_db()` in the new router, same defensive pattern as
`backend/routers/ufc_picks.py:33` — a notes-table failure must not stop the sports API from
serving.

```sql
CREATE TABLE IF NOT EXISTS nfl_draft_notes (
    device_id  TEXT    NOT NULL,
    player_id  INTEGER NOT NULL,
    season     INTEGER NOT NULL,
    "rank"     INTEGER,          -- NULL = no custom rank; 1..999 when set
    watch      INTEGER NOT NULL DEFAULT 0,
    fade       INTEGER NOT NULL DEFAULT 0,
    user_id    INTEGER,          -- always NULL in slice A; see §3.2
    updated_at INTEGER NOT NULL, -- epoch ms
    PRIMARY KEY (device_id, player_id, season)
);
CREATE INDEX IF NOT EXISTS idx_nfl_draft_notes_device
    ON nfl_draft_notes(device_id, season);
```

**`rank` must be quoted in every statement.** `RANK` is a SQLite window function; an
unquoted bare `rank` in a `SELECT` list parses but does not mean the column.

### 3.1 `player_id` is `players.id`, and it is validated on write

`players.id` (INTEGER PK, 29,374 rows) is the surrogate the draft board already emits as
`player_id` (`backend/routers/nfl_offseason.py:700`, `SELECT p.id AS player_id`). Notes key
to it and to nothing else — never to a name. AGENTS.md §7 is explicit and was written after
a name-join split 317 MLB players across duplicate rows.

A write for a `player_id` that does not exist as an NFL row is **404**, not a silently
created orphan. This is the resolve-or-reject half of resolve-or-queue: there is no review
queue here because a note is user input, not an ingest — the only way to hit this is a
stale or forged client, and both should be told.

Do **not** require `active=1`. A player who retires between two page loads must not make a
user's existing note un-writable.

### 3.2 `user_id` is here in slice A on purpose

Slice B claims device-keyed rows on first sign-in. Adding the column now, nullable and
unused, means B is an `UPDATE ... WHERE device_id=? AND user_id IS NULL` instead of an
`ALTER TABLE` against a table with live user data.

This is a deliberate **deviation from the column list** in `SPEC-accounts-and-mock-draft.md`
§2 Phase 0, which names seven columns and not this one. The cost is one always-NULL column
for one release; the cost of the alternative is a migration on the one table whose whole
purpose is not losing anyone's work.

Per-row `user_id` rather than a `device_claims(device_id → user_id)` map: a device map makes
the *browser* belong to an account forever, so a second person signing in on the same
laptop writes rows that read back as the first person's. Per-row ownership gets the
behaviour the parent spec asks for — "a device that later signs into a second account does
not re-claim rows already owned" — as a `WHERE user_id IS NULL` clause rather than a rule
someone has to remember.

---

## 4. API

New router `backend/routers/nfl_draft_notes.py`, registered in
`backend/sports_service.py` (AGENTS.md §0: endpoints go in a router, never in the app
shell). Routers here declare full paths, so no prefix.

Payloads are **snake_case**, matching the adjacent `nfl-draft-board-v2` contract rather than
`ufc_picks`' camelCase. The board and the notes are read by the same component; two casings
in one screen is a bug waiting to happen.

Contract name: **`nfl-draft-notes-v1`**.

### `GET /api/nfl/draft-notes?season=2026`

Header `X-Device-Id` required.

```json
{
  "contract": "nfl-draft-notes-v1",
  "season": 2026,
  "notes": { "rank": {"4412": 3}, "watch": {"5591": true}, "fade": {} },
  "note_count": 2,
  "updated_at": 1753650000000
}
```

The `notes` object is byte-for-byte the shape the frontend `NflDraftNotes` type already uses
(`components/Leagues/types.ts:273`) — keys are stringified `player_id`, `rank` values are
ints, `watch`/`fade` values are always literal `true`. Rows that are all-default are never
returned (they are deleted, see below), so a `false` never appears.

`updated_at` is the max across the returned rows, or `null` when there are none. It is what
lets a client decide whether its cache is stale without diffing.

### `PUT /api/nfl/draft-notes`

One player, one call — mirrors the three UI actions, which each touch exactly one player.

```json
{ "season": 2026, "player_id": 4412, "rank": 3, "watch": false, "fade": false }
```

- `rank`: `null`, or an integer `1..999`. Same bounds the client already enforces
  (`useNflDraftBoard.ts:39`) — validate them again server-side; the client is not a
  validator.
- `watch`, `fade`: booleans. Absent means unchanged; explicit `null` is a 400.
- When the result is `rank IS NULL AND watch=0 AND fade=0`, **delete the row** instead of
  storing a row that means nothing. Un-watching a player must not leave a tombstone that
  counts toward §6's cap or the nudge threshold in slice C.

Returns the stored state for that player, or `{"player_id": 4412, "deleted": true}`.

### `POST /api/nfl/draft-notes/import`

The one-time adoption of notes that already exist in a browser's `localStorage`. Body is a
whole `notes` object plus `season`.

**Non-destructive: it only inserts rows the device does not already have on the server.** An
import can only ever be a browser replaying an older local copy — if the server already has
a row for that player, the server's is the same age or newer. Silently overwriting is how
someone's laptop resurrects a rank they deleted on their phone.

Returns `{"imported": n, "skipped": n, "rejected": n}`. `rejected` counts entries that
failed validation (unknown player, out-of-range rank), and it must be reported rather than
absorbed — a nonzero value in the log is the only way we learn the local format drifted.

---

## 5. Frontend

All changes in `components/Leagues/hooks/useNflDraftBoard.ts`. `NflDraftRoom.tsx` should not
need to change: it consumes `notes`, `setRank`, `toggleWatch`, `toggleFade`, and those
signatures stay identical.

**Write path — optimistic, then reconcile.** `setRank` / `toggleWatch` / `toggleFade` keep
updating React state and `localStorage` synchronously exactly as they do now, and fire the
`PUT` after. The board must never feel like it is waiting on a network round trip to toggle
a star.

**On failure, roll back and say so.** A silently-dropped write is worse than no server at
all, because the user believes it saved. Revert the optimistic state and surface one quiet
non-blocking line — this is the same honesty rule as the availability UI: absence gets
marked, not hidden.

**Read path on mount:**

1. Render from `localStorage` immediately (`loadNotes()` already does this, no flash).
2. `GET` the server copy.
3. If the server has rows, it wins — replace state and rewrite the cache.
4. If the server has **zero** rows and `localStorage` has some, `POST .../import` once, then
   adopt the response. This is the migration path for everyone who used the board before
   this ships, and it needs no separate script.
5. If the `GET` fails, keep running on `localStorage` exactly as today. The board is a
   research tool; losing note *sync* must not lose note *display*.

`sanitizeNotes()` stays and still runs on anything read from `localStorage`. It is now also
the shape guarantee for the server response — run it on both. The server validates its own
writes, but a client that trusts a response it did not validate is one bad deploy away from
rendering an object as a React child (AGENTS.md §10).

---

## 6. Limits and abuse

`X-Device-Id` is self-asserted, so this is an unauthenticated write endpoint.

- **1,000 rows per `(device_id, season)`.** The board serves roughly 520 eligible players;
  a thousand is far past any honest use and still trivially small. Over the cap, `409`.
- **`player_id` must resolve** (§3.1), which is what stops a device writing 29,374 junk rows
  for real-looking ids.
- Body size cap on `/import` — reject a `notes` object with more than 1,000 entries before
  parsing player ids, not after.
- No rate limiter in this slice. There is no existing one in the app to extend, and building
  one here would be the wrong place; revisit with slice B, which introduces the first
  endpoint worth attacking (email send).

---

## 7. Verification — what "done" means

Per AGENTS.md §3, verify against the requirement, and never against the code that produced
the value. A 200 is not acceptance.

1. **Round trip across a simulated device change.** Set a rank, a watch and a fade in the
   browser; clear `localStorage` entirely; reload. All three come back. This is R8's actual
   requirement and it is the only test that proves it.
2. **Two "devices."** Two different `X-Device-Id` values must not see each other's notes —
   assert by querying the table directly, not by reading the API that wrote them.
3. **The import path, on a real pre-existing cache.** Seed `lp_nfl_draft_notes` in the
   browser with the current format, load the board with an empty server table, confirm the
   rows land and that a second reload imports nothing (`imported: 0`).
4. **Delete-on-empty.** Toggle watch on and off; assert zero rows for that player in SQLite.
5. **Headless render check** — load `/leagues/nfl` in Playwright (already a dependency) and
   assert zero `pageerror`s with notes present. AGENTS.md §10: the build passing is not the
   page loading.
6. **Payload.** The `GET` for a heavy user must stay small; measure it and put the number in
   the commit message (`docs/DEV-STANDARDS.md`).

Backend tests go in `backend/test_nfl_draft_notes.py` — top-level `test_*.py` is the
convention here — pointing `LP_DB_PATH` at a `tempfile` **before importing the router**, as
`test_esports_predict_api.py:15` does. `conftest.py` restores the env var afterwards; do not
work around it.

---

## 8. Out of scope

Accounts, sign-in, any gate, any nudge (slices B and C). Cross-device merge conflict
resolution — a device owns its rows until an account owns them. Sharing or exporting a
board. Notes on any league other than NFL.

---

## 9. Open, needs a decision before merge

- **Does `season` come from the client or the server?** The board derives its reference
  season from the data (`MAX(season) FROM player_game_logs`) but drafts are for 2026, which
  is `_CURRENT_SEASON`. Sending it from the client is more flexible and lets a stale tab
  write to last season. Recommendation: accept it in the request, but validate against
  `_CURRENT_SEASON` and reject anything else — flexibility we cannot currently use is just
  an unvalidated input.
