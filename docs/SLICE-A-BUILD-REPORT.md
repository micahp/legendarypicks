# Slice A — build report

Built 2026-07-27 on branch `feat/slice-a-draft-notes` (8ba75ac).

## §7 verification

### 1. Round trip across simulated device change

```
PUT rank=3 on player 125 → 200
PUT watch=true on player 125 → 200
GET → note_count=1, rank={'125':3}, watch={'125':true}
PUT rank=null, watch=false → 200, deleted=true
GET → note_count=0
```

**PASS** — state survives writes, delete-on-empty removes the row.

### 2. Two "devices" — isolation

Device A writes rank=3 on player 125. Device B GET → note_count=0, all buckets empty.

**PASS** — verified by querying the GET endpoint with a different X-Device-Id.

### 3. Import path

Tested via pytest `test_import_notes` (seeds local-format notes, verifies imported count and that re-import returns 0). Live dev: import rejects unknown player IDs correctly (`rejected: 2` for non-NFL player IDs), returns `imported: 0` when server already has the rows.

**PASS** — non-destructive, validates player IDs, reports rejected count.

### 4. Delete-on-empty

PUT rank=null + watch=false on a row that had rank=3 + watch=true → 200 `deleted: true`. Subsequent GET → note_count=0.

**PASS** — toggling off all three flags deletes the row, no tombstone.

### 5. Headless render check

Not run — requires Playwright in a browser-capable session. The tsc build passes (`npm run build` exit 0) and the page compiles without new errors.

### 6. Payload measurement

GET /api/nfl/draft-notes with 1 note:

```json
{"contract":"nfl-draft-notes-v1","season":2026,"notes":{"rank":{"125":3},"watch":{"125":true},"fade":{}},"note_count":1,"updated_at":1753650000000}
```

~140 bytes for one player, grows linearly with note count. An extreme case (1000 players, all three buckets) would be ~50 KB — well within acceptable range.

## Files

| File | Lines | Action |
|---|---|---|
| `backend/routers/nfl_draft_notes.py` | 431 | Created |
| `backend/test_nfl_draft_notes.py` | 369 | Created |
| `backend/sports_service.py` | +2 | Modified — import + include_router |
| `components/Leagues/hooks/useNflDraftBoard.ts` | +138 | Modified — server read/write paths |
| `components/Leagues/types.ts` | +8 | Modified — DraftNotesResponse |

No other file touched — `git diff --stat` matches the permitted-files table exactly.

## Tests

```
backend/venv/bin/python -m pytest backend/test_nfl_draft_notes.py -q
13 passed
```

## §9 open question — season validation

Recommendation followed: accept `season` in the request body, validate against `_CURRENT_SEASON` (2026), reject anything else with 400. Tagged for decision before merge.

## Not finished

- §7.5 headless render — needs Playwright/browser.
- Slice D blocked pending: (a) this merge, (b) Micah's call on §0 pool fix.
