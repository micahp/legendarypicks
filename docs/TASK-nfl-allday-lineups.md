# TASK (Hermes): NFL All Day collection viewer — a Lineups tab on the NFL league page

Repo **/root/legendarypicks**. Work in the worktree you are given, on its branch. Do **not**
work in `/root/legendarypicks` itself.

## What this is

The original Legendary Picks idea was a Flow-blockchain fantasy contest built on NBA Top
Shot. Artifacts of it are still in the tree (`cadence/`, `services/nbaTopShot.ts`,
`flow.json`). We are reviving the thread against **NFL All Day** (Dapper Labs' NFL moment
NFTs on Flow) instead of Top Shot.

**v1 is deliberately tiny and is the whole task:**

> A **Lineups** tab on the NFL league page. You paste a Flow wallet address — **no sign-in,
> no wallet connect** — and it lists the NFL All Day moments that address owns, showing for
> each one **which NFL player it is and what position they play**.

That is it. No lineup construction, no scoring, no contests, no escrow, no transactions.

## Why it is scoped this way

Everything downstream (lineups, scoring, contests) depends on one unverified assumption:
**that an All Day moment can be resolved to an NFL player identity we can join to our own
`players` table.** If that join does not work, every later phase is dead. So v1 *is* the
kill-check, shipped as a usable page rather than a throwaway script.

**If the identity resolution turns out not to be possible, STOP and report that.** Do not
build UI around a join that does not exist. That is a successful outcome for this task, not
a failure.

---

## Architecture — read the chain from the BACKEND, not the browser

`@onflow/fcl` is **not installed and not in `package.json`** — the legacy Flow imports in
`services/*.ts` and `components/*.tsx` are dead code, which is why `tsc` errors on them.
**Do not install FCL and do not revive those files.** They are reference material for
Cadence script shape only.

Instead: Flow's public HTTP access API executes Cadence scripts directly. Verified reachable
from this box on 2026-07-27:

```
POST https://rest-mainnet.onflow.org/v1/scripts
  { "script": "<base64 cadence>", "arguments": ["<base64 json-cadence arg>"] }
GET  https://rest-mainnet.onflow.org/v1/network/parameters   -> 200 {"chain_id":"flow-mainnet"}
```

So the read lives in the **Python backend**, where it is server-side, cacheable, and — the
real reason — sits next to the `players` table the moments have to join against.

- Backend endpoint: `GET /api/nfl/allday/collection?address=0x...`
- Frontend: a tab that calls it. No blockchain code in the browser at all.

---

## Step 1 — verify against the live chain BEFORE writing any UI

Assume nothing about contract addresses, storage paths, or metadata field names. Every one
of these must be confirmed against mainnet and written into
`docs/FINDINGS-nfl-allday.md`:

1. **The AllDay contract address on Flow mainnet.** Do not take it from memory or from a
   blog post — confirm the account actually exposes the contract
   (`GET /v1/accounts/<address>?expand=contracts`).
2. **The public collection capability path** a wallet exposes its moments through (the Top
   Shot analogue is `/public/MomentCollection`; All Day's will differ — find it, don't guess).
3. **What metadata a moment actually resolves to.** We need, at minimum, the **player name**
   and **position**. Also record whatever else comes free: team, season, week, play type,
   series/set, edition/serial, tier.
4. **A real mainnet address that holds All Day moments**, to test against. Note it in the
   findings doc so the next person can re-run the check.
5. **Whether All Day publishes a fantasy-points rubric.** Micah believes one exists. Record
   what you find, **but do not build scoring on it** — out of scope for v1, and we already
   compute PPR ourselves from `player_game_logs`.

**Report findings before building.** If step 1 shows the metadata has no usable player
identity, stop there.

## Step 2 — the identity join

Moment metadata gives a player *name*. Our spine is `players` (`league='nfl'`, `active=1`).

- Join on normalized name + position. Expect misses; **measure and report the hit rate**
  against a real collection — "412 of 460 moments resolved" is the deliverable, not a vibe.
- **Report unmatched moments honestly in the UI** as unmatched. Never silently drop them and
  never guess a player.
- Relevant trap, already documented as **B7** in `docs/ROADMAP.md`: 651 active NFL players
  carry synthetic ESPN-style keys (`LOV121782`) in `players.nfl_gsis_id`. Do not try to
  repair that here — just be aware the id column is unreliable and join on name/position.
- Generational suffixes differ across sources (`Murvin Kenion` vs `Murvin Kenion III`).

## Step 3 — the UI

A new **Lineups** tab on `/leagues/nfl`, alongside Home / Standings / Stats / Schedule.

- An address input + submit. Validate the shape of a Flow address (`0x` + 16 hex) before
  calling. Remember the last address in `localStorage` so a reload does not lose it.
- Empty state before an address is entered, explaining what to paste and that nothing is
  stored server-side.
- The result: the moments that address owns, each showing **player name, position, team**,
  plus whatever else step 1 found (series/set, serial number, tier).
- Group or filter by position — this is going to become a lineup builder, so position must
  be a first-class axis from day one.
- An address that owns nothing must read **"No NFL All Day moments in this wallet"**, never
  an empty table and never an error.

**Load `.claude/skills/honest-data-ui/SKILL.md` before designing this surface** and follow
it. In particular: unmatched moments are an absence and must read as one, and no fabricated
zeros or made-up player identities.

Match the existing visual language — dark zinc + emerald, `tabular-nums` for numbers, the
app font (not monospace). Copy the patterns in `components/Leagues/NflDraftRoom.tsx`.

---

## Files you may touch

Create:
- `backend/routers/nfl_allday.py`
- `backend/test_nfl_allday.py`
- `components/Leagues/LineupsTab.tsx`
- `components/Leagues/hooks/useAllDayCollection.ts`
- `docs/FINDINGS-nfl-allday.md`

Modify, minimally:
- `backend/sports_service.py` — register the new router, nothing else
- `pages/leagues/[league].tsx` — render the tab
- `components/Leagues/types.ts` — add `'lineups'` to `HubTab` + the response types
- `components/Leagues/hooks/useLeagueRouteState.ts` — allow `lineups` in `validTabs` for NFL

## Do NOT touch

- **Anything host-level**: `/etc`, systemd units, cron, nginx. Worktree isolation does not
  cover these. If the task seems to need one, write what is needed in your summary and stop.
- `package.json` / `package-lock.json` — **no new dependencies**. If you believe you need
  one, stop and say why instead of installing it.
- `cadence/`, `flow.json`, `services/nbaTopShot.ts`, `services/contestService.ts`,
  `services/accountLinking.ts`, `config/fcl.ts` — read them for reference, change nothing.
- Any other league tab, the draft board, the props/esports/UFC surfaces, or any shared util
  outside the files listed above.
- The main dev environment on **:3096 / :8096** and its cloudflared tunnel. Your servers are
  on **:3097 / :8097**. Never kill a process by port alone — check `/proc/<pid>/cwd` first.
- `git push`, tags, and releases. Claude owns git history. Commit on your branch only.

## Resource limits — this box is tight

5.8GB total, and at handover time **~2.1GB available with swap already at 2.1/4.0GB**, a
live dev server and tunnel serving the user, and the main backend burning ~147% CPU.

- **No bulk chain scraping.** Query one wallet at a time, on demand, in response to a user
  action. Do not crawl All Day, do not enumerate collections, do not backfill a moments table.
- Cache a resolved address's response briefly in-process so a re-render is not a re-query.
- Before running anything that loops, check `free -h` and `uptime` and say the expected cost.
  See `.claude/skills/resource-check/SKILL.md`.

## Verify before reporting done

1. `backend/venv/bin/python -m pytest backend/test_nfl_allday.py -q` passes.
2. `npx tsc --noEmit` introduces **no new errors in the files you touched** (the repo has
   many pre-existing ones from the dead Flow imports — filter to your files).
3. The tab renders at `http://127.0.0.1:3097/leagues/nfl?tab=lineups` with a **real mainnet
   address**, showing real moments with real player names and positions. A headless browser
   runs on this box; screenshot it.
4. **No horizontal page overflow at 390px.**
5. Report: the match rate (matched / total moments), the address you tested with, and every
   metadata field you found — plus anything in step 1 that turned out different from what
   this document assumed.

Report a diff summary and the verify output. Do not commit to `dev`, do not push.
