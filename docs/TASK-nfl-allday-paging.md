# TASK — paging controls for the NFL All Day Lineups tab

Branch `feat/nfl-allday` in worktree `/root/lp-nfl-allday`. Servers **:3097 (front) / :8097
(back)** are already running — do NOT start, stop or restart them, and do NOT touch :3096/:8096
(that is the live main dev env behind a public tunnel).

## Context

The Lineups tab works and is committed at `9d4552e`. The backend already supports paging:

```
GET /api/nfl/allday/collection?address=0x...&limit=200&offset=0
```

Response fields you need: `total` (whole collection), `returned` (this page), `offset`,
`limit`, `matched`, `unmatched`, `status`, `sources`, `moments[]`.

**The backend is done. This task is frontend only.** Right now the UI fetches one page and
prints "Showing 200 of 6,772" with a note saying paging controls are not built. Build them.

## Scope — the ONLY files you may modify

1. `components/Leagues/LineupsTab.tsx`
2. `components/Leagues/hooks/useAllDayCollection.ts`

## Do NOT touch — this list is load-bearing, YOLO is on

- **Anything under `backend/`.** The API contract is fixed. If you believe you found a backend
  bug, STOP and report it — do not fix it.
- `components/Leagues/types.ts` — the response type is already correct and complete.
- Any other component, hook, page, or shared util anywhere in the repo.
- `package.json` / lockfiles — install nothing.
- Host-level config: `/etc`, systemd units, cron, nginx, shell profiles. Worktree isolation
  does NOT protect these.
- Git branch operations: no checkout, no rebase, no reset, no merge, no push. Commit on
  `feat/nfl-allday` only.

## Requirements

1. **Paging control** below the moment list. Previous / Next is enough; a page indicator like
   "Page 2 of 34" is welcome. Disable Previous at offset 0 and Next on the last page.
2. **Never claim more than is on screen.** Keep the existing honest summary: when
   `returned < total`, say what is shown and out of how many. Remove the "paging controls are
   not built yet" note once they exist.
3. **Page size**: keep 200 as default. If you expose a size selector, cap it at 1000 — the
   backend rejects more, and larger pages get slow.
4. **Do not refetch on every render.** Changing page must abort any in-flight request (the hook
   already has an AbortController — extend that pattern, do not replace it).
5. **Reset to offset 0 when the address changes.** A stale offset against a smaller wallet must
   not show an empty page.
6. **Preserve the position grouping** (QB/RB/WR/TE/…) within each page.
7. **Keep the empty states intact** — `no_account` / `no_collection` / `empty` each render
   different copy today. Do not collapse them.
8. **Loading state between pages** must not blank the whole tab to the pre-search empty state.

## Verify before you report — do not skip this

Real mainnet addresses, all confirmed holders:

| address | moments | use it to test |
|---|---|---|
| `0xc2544e942028e947` | 6,772 | normal paging, 34 pages |
| `0xb09562a023f25262` | 66,387 | large-total formatting, last page |
| `0x5f3f7a1c61b09bab` | 18 | single page — controls should hide or disable |
| `0xa184e13ef8c3e0ef` | 0 | `no_collection` empty state still correct |

- Load `http://127.0.0.1:3097/leagues/nfl?tab=lineups`, paste each address, page forward and
  back. **Screenshot at 1400px and at 390px width.**
- Confirm **no horizontal page overflow** at either width
  (`document.documentElement.scrollWidth > window.innerWidth` must be false).
- Confirm the last page of `0xb09562a023f25262` renders (66,387 is not divisible by 200).
- `npx tsc --noEmit` — zero NEW errors in the two files you touched. There are ~21 pre-existing
  errors from dead Flow imports (`cadence/`, `services/nbaTopShot.ts`, `config/fcl.ts`);
  those are known, leave them alone.

## Report back

- The screenshots (paths).
- Whether match rate stayed ~94% across several pages, or drifted on later pages.
- Anything you found and did NOT fix because it was out of scope.

Commit on `feat/nfl-allday` with a clear message. Do not push.
