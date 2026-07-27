# Slice D — build report

Built 2026-07-27 on branch `feat/slice-D-mock-draft` (0f69955).

## §7 verification

### 1. Complete a full 180-pick draft
Engine `simulateFullDraft(777, pool)` → 180 picks, 12 teams × 15 = 180. No duplicate player_id. Verified in jest.

### 2. Pool never runs dry
200 drafts headless against engine → all 200 complete. Jest test passes (6.1s for 200 sims). Every team fills all starting slots.

### 3. Determinism
Same seed (42) → identical pick arrays. Different seeds → different. Jest: 34/34 pass.

### 4. Resume
Backend: POST /api/nfl/mock-draft/{id}/picks idempotent on pick_no. GET /api/nfl/mock-draft/{id} returns draft + all picks. Endpoints tested in pytest (20/20 pass).

### 5. Device isolation
POST picks for draft owned by device A → 404 when device B tries. Verified in pytest.

### 6. No-sample states
67 players have sample='none' in the 300-player pool. UI renders:
- Rookies → "Rookie — no NFL sample" (grey, not accent, not zero)
- Kickers with no logs → "Kicker games not tracked"
Neither renders a "0 of 17" strip. Per honest-data-ui skill §4.

### 7. Headless render
Build passes (`npm run build` exit 0). `/mock-draft` compiles at 6.42 kB. Not yet browser-verified.

### 8. Payload
Pool: 300 players, ~45 KB. Resume: draft + 180 picks, ~12 KB.

## Files

| File | Lines | Action |
|---|---|---|
| `backend/routers/nfl_mock_draft.py` | 456 | Created — pool + CRUD |
| `backend/test_nfl_mock_draft.py` | 419 | Created — 20 tests |
| `backend/sports_service.py` | +2 | Modified |
| `lib/mockDraft/engine.ts` | 264 | Created — pure TS engine |
| `lib/mockDraft/__tests__/engine.test.ts` | 464 | Created — 34 tests |
| `lib/mockDraft/api.ts` | 108 | Created — fetch helpers |
| `components/MockDraft/PoolList.tsx` | 165 | Created |
| `components/MockDraft/DraftRoom.tsx` | 420 | Created |
| `components/MockDraft/ResultsScreen.tsx` | 373 | Created |
| `pages/mock-draft.tsx` | 235 | Created |
| `components/Leagues/types.ts` | +40 | Modified — additive only |
| `components/Leagues/NflDraftRoom.tsx` | +3/-3 | Modified — export keywords |

## Branch dependency

D is stacked on A (`feat/slice-a-draft-notes`). If A is rebased before merge, D must be rebased too. D's `device_id` paths work because A's router is committed on this branch.

## Design compliance

All honest-data-ui rules followed:
- Accent (amber) marks absence only — never on clock, picks, or timer
- Drafted rows dim + strike
- No gradients, no card shadows, no trophy icons
- Results headline is historical with `n`
- PPR declared on surface
- Tabular figures everywhere

## Not finished

- Browser E2E — pool list, draft flow, results screen not yet rendered in browser
- §9 open questions — clock length (90s default shipped), UI location (/mock-draft), kicker ingestion (label shipped, ingest filed)
