# TASK — the NFL fantasy game log gets tabs, so no view scrolls sideways

Repo: `/root/legendarypicks`, branch `dev`, main tree (NOT a worktree).
Dev servers already running: backend `:8096`, frontend `:3096`. **Do not restart them.**

## The brief, in one line

The player overlay's game log still scrolls sideways. The fix is **not** a wider card and
**not** fewer stats — it is ESPN Fantasy's segmented control: one narrow table per tab.

## The reference, which is not a guess

Screenshots of the ESPN Fantasy iOS app, Bijan Robinson 2025 game log. What it does:

- Header line: `2025 REGULAR SEASON (ATL)`.
- A segmented pill row directly under it: `Rushing` | `Receiving` | `Misc TD`,
  active pill is a filled pill against a light track.
- The table under it re-renders per pill. Columns:
  - Rushing: `WK OPP FPTS ATT YDS TD`
  - Receiving: `WK OPP FPTS REC TAR YDS TD`
  - Misc TD: `WK OPP FPTS BLK INT FUM`
- **`WK`, `OPP` and `FPTS` repeat in every tab.** They are the anchor; only the stat
  columns change. That is what keeps every view under ~8 columns and off the scrollbar.

## Files you may change — and no others

1. `backend/routers/nfl_mock_draft.py` — **only** `_LOG_FIELDS`, `_DST_LOG_FIELDS`,
   `player_game_log()` and `_dst_game_log()`. Nothing else in that file.
2. `backend/test_nfl_mock_draft.py` — add tests.
3. `components/Leagues/PlayerGameLog.tsx` — the tab control.
4. `components/Leagues/PlayerDetailOverlay.tsx` — one line, see step 4.
5. `pages/player/[id].tsx` — one band removed, see step 5.

**Forbidden, without exception:** `verify-gates.sh`, any file under `lib/`, any other
router, any DB schema/migration, any ingest, `nfl_stat_derivations.py`, anything under
`/etc`, systemd, cron, and any `git push`. Do not create shared utility modules — if two
files need the same thing, duplicate it rather than widening the blast radius.

## Step 1 — the endpoint publishes tabs

`_LOG_FIELDS` becomes an ordered list of tabs per position. Response gains:

```json
"tabs": [ { "id": "rushing", "label": "Rushing", "fields": ["carries","rush_yds","rush_td"] }, ... ]
```

Keep `"fields"` in the response, set to the **union of all tab fields in order**, so the
contract string `nfl-player-game-log-v1` stays truthful and the row-building code below it
is unchanged. `games[].stats` still carries every field in the union — the tabs are a view,
not a second fetch.

**Hard budget: no tab may declare more than 5 stat fields.** `Wk`, `Opp` and `PPR` are
rendered by the component for every tab and must NOT appear in any tab's `fields`.

The tabs, in this order:

| Pos | tabs |
|---|---|
| QB | Passing `[cmp, att, pass_yds, pass_td, intc]` · Rushing `[carries, rush_yds, rush_td]` · Misc `[sacks_taken, fum_lost, misc_td]` · Usage `[off_pct, xfpts_ppr]` |
| RB / FB | Rushing `[carries, rush_yds, rush_td]` · Receiving `[targets, rec, rec_yds, rec_td]` · Misc `[fum_lost, misc_td]` · Usage `[off_pct, target_share, xfpts_ppr]` |
| WR / TE | Receiving `[targets, rec, rec_yds, rec_td]` · Rushing `[carries, rush_yds, rush_td]` · Misc `[fum_lost, misc_td]` · Usage `[off_pct, target_share, xfpts_ppr]` |
| PK | Kicking `[fg_made, fg_att, fg_long, pat_made, pat_att]` — one tab only |
| DEF | Defense `[sacks, interceptions, fumble_rec, safeties, points_allowed]` — one tab only |

Two notes you must respect:

- The tab is labelled **`Misc`, not `Misc TD`.** ESPN's Misc TD tab is BLK/INT/FUM meaning
  *touchdowns* off blocks, picks and fumble returns. Ours is a lost fumble and a
  return/recovery TD. Same neighbourhood, different definition — do not borrow the label
  for a column set that does not mean it.
- **PK and DEF anchor on their own points column,** not `fpts_ppr`: PK has no PPR field at
  all, and DEF's is `fantasy_pts`. Publish the anchor explicitly as
  `"anchor": "fpts_ppr"` (or `"fantasy_pts"`, or `null` for PK) at the top level of the
  response so the component never has to guess. When `anchor` is null the component
  renders no points column.

## Step 2 — the component renders the tab bar

In `PlayerGameLog.tsx`:

- Read `data.tabs` and `data.anchor`. `useState` for the active tab id, **reset to
  `tabs[0].id` whenever `playerId` changes** — a stale index on a QB after viewing a WR is
  the obvious bug here.
- **Render no tab bar at all when `tabs.length === 1`** (PK, DEF). A single pill is noise.
- The columns rendered are: `Wk`, `Opp`, the anchor (if non-null, header `PPR` for
  `fpts_ppr` and `Pts` for `fantasy_pts`), then the active tab's fields.
- `role="tablist"` / `role="tab"` / `aria-selected` on the pills, and they must be real
  `<button type="button">` elements so keyboard and screen readers work.
- Style the pills to match the app's existing dark surface — zinc track, active pill a
  lighter zinc with `text-zinc-100`, inactive `text-zinc-400`. Look at an existing pill row
  in `components/` and match it rather than inventing a new one.
- Keep the `overflow-x-auto` wrapper as a safety net, but **no tab may need it**: after
  this change the widest view is `Wk + Opp + PPR + 5 = 8` columns.
- The "did not play" row's `colSpan` must be computed from the columns actually rendered
  for the active tab, not from `data.fields.length`. Getting this wrong leaves a short row.

## Step 3 — headers

`HEAD` already has entries for every field above. Add nothing except what is missing.
`target_share` is `Tgt%`, `off_pct` is `Snap` — both already there.

## Step 4 — the card goes back to 520

`PlayerDetailOverlay.tsx` currently reads `max-w-[520px] sm:max-w-3xl`. That widening was
the previous attempt at this same problem and it did not solve it. With tabs, every view
fits. **Revert it to `max-w-[520px]`** and replace the comment block above it with a short
one saying the game log tabs are what keeps it in the box now.

## Step 5 — Misc comes off the player detail page

`pages/player/[id].tsx`, `NFL_GAMELOG_BANDS`: **delete the whole `Misc` band**
(`fum_lost`, `misc_td`, `pass_2pt`, `rush_2pt`, `rec_2pt`) and the comment above it. That
block was written for the fantasy game log, not for the player page, and ESPN's player game
log does not carry it.

**Keep `sacks_taken` in the `Passing` band** — ESPN's player game log does have a SACK
column, so that one belongs where it is. Change nothing else on that page.

## Step 6 — prove it

1. `cd /root/legendarypicks/backend && python -m pytest test_nfl_mock_draft.py -q`
   New tests, and they must be written before the code they check:
   - every position's tabs declare ≤5 fields each;
   - no tab's fields contain the anchor;
   - `fields` equals the ordered union of the tabs' fields;
   - a QB, an RB, a WR, a PK and a DEF each return a non-empty `tabs` with the labels above.
2. `npx tsc --noEmit -p tsconfig.json` clean on the three frontend files you touched.
3. Hit the live backend and paste the real output into your report:
   `curl -s localhost:8096/api/nfl/draft/player/469/game-log | python -m json.tool | head -40`
   (469 is Josh Allen — a QB, so you get the 4-tab case.)
4. Do **not** run `verify-gates.sh`. It is being changed in parallel; leave it alone.

## Step 7 — commit

One commit per logical slice, on `dev`, **do not push**:

- one for the endpoint + its tests,
- one for the component,
- one for the two removals (card width, player-detail Misc band).

Subject lines in the repo's existing voice — a sentence that states what is now true, not
`feat: add tabs`. No `Co-Authored-By`, no mention of any AI tool anywhere in the message.

## Report back

Paste: the `git log --oneline` of your commits, the pytest line, the tsc result, and the
curl output from step 6.3. If any step could not be done, say which and why — do not
silently narrow the task, and do not relax a test to make it pass.
