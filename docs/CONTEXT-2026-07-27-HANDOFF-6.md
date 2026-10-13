# LP handoff — 2026-07-27 pt.6 (supersedes pt.5)

**Work queue: `/root/legendarypicks/docs/ROADMAP.md`.** This file is session state and
decisions only.

---

## 0. ✅ RESOLVED 2026-07-27 16:20 — and the diagnosis below was WRONG

`:3096`, `/leagues/nfl` and the tunnel are all **200** again.

**The real cause was not concurrent `.next` writes.** `/root/lp-nfl-allday/node_modules` is a
**symlink to `/root/legendarypicks/node_modules`**, and the `npm exec next dev -p 3097` run at
16:01 **emptied the shared install** (0 entries, dir mtime 16:01:29 matches the npm log exactly).
The live `:3096` process kept serving from deleted inodes until it needed a file — hence the
`ENOENT .next/server/pages/...` 500 that looked like build corruption.

Fix applied: killed 160173/160169, `rm -rf .next`, **`npm ci`** (868 pkgs, 42s), relaunched with
**`./node_modules/.bin/next dev --port 3096`**. Do **not** use `npx next` here — it resolves
next@16 over the pinned **13.0.0**. cloudflared was never touched; tunnel URL unchanged.

`:3097` was left **DOWN on purpose** — the worktree branch is pushed and has no active task, and
a second `next dev` is not free on a 5.9GB box (1.3GB available). Start it only when needed:
`cd /root/lp-nfl-allday && setsid nohup ./node_modules/.bin/next dev -p 3097 &`.

**Checked, not a regression:** LP pins `next: 13.0.0` and always has (`git log -S` on
`package.json` → only "first commit"). The 15.5.18 patch in memory was a *different* app on this
box, `finetuned-photo-gen`. Separate standing question, pre-existing and not caused here: 13.0.0
is four majors stale and carries its own advisories — worth a look before R6, not blocking it.

<details><summary>Original (incorrect) §0, kept for the record</summary>

**The main dev frontend `:3096` and the public tunnel both return 500.** Backends are fine.

**What I did:** I tried to restart the *worktree* frontend with `npx next dev -p 3097`, but the
shell's cwd had reset to **`/root/legendarypicks`** instead of `/root/lp-nfl-allday`. That
started a **second Next process in the main repo**, writing the same `/root/legendarypicks/.next`
directory as the live `:3096` server. Two `next dev` processes sharing one `.next` corrupts the
build artifacts. The result is `ENOENT ... .next/server/pages/leagues/[league].js` and a 500 on
every page. My stray process has since exited on its own (exit 1).

**I did NOT delete `/root/legendarypicks/.next`** — it is still there, dated Jul 24. The
corruption is from concurrent writes, not a deletion.

**The fix (I was blocked by the permission classifier from running it — it needs your approval):**

```bash
# 1. main dev frontend :3096
cd /root/legendarypicks
kill 160173 160169          # sh -c wrapper + node child; re-check PIDs, they may differ
rm -rf /root/legendarypicks/.next
setsid nohup npx next dev --port 3096 > /tmp/lp-3096.log 2>&1 < /dev/null &
# it needs NO special env — it reads /root/legendarypicks/.env.local (present, Jul 21)

# 2. worktree frontend :3097 — also down, same cause chain
cd /root/lp-nfl-allday
setsid nohup npx next dev -p 3097 > /tmp/hermes-wt-nfl-allday-frontend.log 2>&1 < /dev/null &
```

**Verify:** `curl -o /dev/null -w '%{http_code}' http://127.0.0.1:3096/leagues/nfl` → 200, then
the tunnel `https://someone-decorative-wearing-produce.trycloudflare.com/` → 200.

**Do NOT restart cloudflared** — the tunnel process itself is healthy and restarting it mints a
new URL. Only Next is broken.

**Unaffected and confirmed healthy:** `:8096` backend (now on WatchFiles, 0.9% CPU), `:8097`
backend (200, serving the alias-table code), all git state, everything pushed.

**Lesson for whoever picks this up:** always `cd` explicitly in the same command as a
`next dev` / `rm -rf .next`. The Bash tool's cwd resets between calls, and in a repo with a
worktree the same relative path exists in two places with very different consequences.

</details>

---

## 1. THE BUILD ORDER — this is what to do next

Set by Micah at the end of this session. It **splits the old single v0.7.0 cut into two
tagged releases** and defers monetisation until after the acquisition surface is in prod.

0. **Fix `:3096` / the tunnel — see §0. Nothing else matters until the dev env renders.**
1. ~~Push `feat/nfl-allday`~~ — **DONE**, `origin/feat/nfl-allday` at `825d116`. Still unmerged;
   merge it or leave it parked, Micah's call.
2. **Slice A** — draft notes to the server, keyed by `device_id`. → **tag a release.**
3. **Slice D** — single-player mock draft vs ADP bots. → **tag a release.**
4. **Prod deploy (R6).**
5. **Data subscription**, which **coincides with accounts (slice B)** — one auth build gives
   billing identity, the sign-up gate, **and multiplayer mock drafts**.

Scope of A and D is unchanged from pt.5; only the packaging changed. Use `scripts/release.sh`
for every tag — never tag by hand, a pre-push hook blocks an untagged version bump.

**Two things Micah has NOT decided — ask, do not assume:**
- **Version numbers.** Suggested A = v0.7.0, D = v0.8.0, accounts+subscription+multiplayer =
  v0.9.0. This renumbers what pt.5 called v0.8.0.
- **Where R4 (NFL schedule through the API) goes.** It was the third item in the old single
  cut; the new sequence does not mention it. It is unblocked and currently homeless.

**Deadline unchanged: ~Aug 22.** Drafts run mid-Aug → Labor Day (Sept 5–7). Prod is still on
**v0.6.7**, so nothing built since then is reachable by a real person.

## 2. Positioning — settled and written down

`docs/POSITIONING-2026-07-27.md` (committed `a5b4e8e`, pushed). Micah's reaction: *"it slides
in perfectly with what we've been doing."*

The load-bearing claims:

- **"Buying the mechanic, not the audience" was the right instinct with the wrong noun.** A
  mechanic is a UI pattern ESPN/Sleeper/Yahoo all ship. The All Day build proved the hard part
  was the **resolver** — hybrid custody, retired players, nickname variants, position
  vocabularies. A mechanic is copied in a weekend; a resolver compounds per source.
- **Micah's own framing, mid-session: "we are an aggregator at the end of the day."** Narrowed
  in the doc: aggregation theory is *demand-side*, and LP is supply-rich/demand-poor, so the
  sentence describes the half already won. The defensible version is **identity aggregation,
  not content aggregation** — content aggregation is commoditised and better funded elsewhere.
- **The regulator and sport.fun's P&L give the same instruction.** Being legally barred from
  the asset layer (the money-out tripwire) is a *subsidy*, not a handicap — it is the layer
  that consumed a year of sport.fun's attention. All Day is the proof case: **issuance halted
  2026-05-13 and the moments still resolve.**
- **Revised two earlier calls explicitly:** the `ESPORTS-POSITIONING` one-liner (a coverage
  claim) → **"Picks. But they're on the record."**; and the `ESPORTS-PRODUCT-DIRECTION` build
  order → **research subscription ahead of cosmetics**, because cosmetics monetise a retention
  LP does not have. Micah's build order in §1 is consistent with this.
- **Two different "records", never blur them:** Record A = what *players* did (valuable now,
  sellable, no users needed). Record B = what *you* picked and whether you were right
  (worthless at zero users). Lead with A as capability, B as promise.

Was told plainly: a positioning doc that ratifies everything you already do costs nothing.
The two places it actually disagrees are **subscription-before-cosmetics** and **R6**.

## 3. NFL All Day — shipped, corrected, alias table landed

**Branch `feat/nfl-allday` in worktree `/root/lp-nfl-allday`, 4 commits, PUSHED to
`origin/feat/nfl-allday`, NOT merged.** Servers **:3097 / :8097** (`:3097` down, see §0). `:8097` has **no `--reload`** — restart it after any
backend edit:

```
cd /root/lp-nfl-allday/backend && pkill -f "port 8097"; sleep 3
LP_DB_PATH=data/picks.dev.db nohup venv/bin/python venv/bin/uvicorn \
  sports_service:app --port 8097 --host 127.0.0.1 > /tmp/be8097.log 2>&1 &
```

- `9d4552e` — the Lineups tab. Verifying Hermes' work against **nine** real wallets instead of
  its single 6-moment sample found **five defects**, all fixed: no paging (Flow's script
  computation limit breaks between **572 and 1,254** moments, so the biggest holders 502'd);
  leaked upstream URLs in errors; three empty states rendering identically; a SQLite connection
  **per moment**; and every player link pointing at `/players/{id}` when the route is
  `/player/[id]`.
- `749c2fb` — **Hermes'** paging controls. Verified: 332 pages on the 66,396-moment wallet,
  last page renders, resets to page 1 on address change, no overflow at 390px or 1400px, zero
  console errors, stayed in scope.
- `38b4afa` — **the match-rate correction (see below).**

### The number I reported was wrong, and wrong in our favour

Told Micah ~94%. **It is 98.1%.** Measured across **1,591 moments from 8 real wallets**:

| | count | share |
|---|---|---|
| matched | 1,510 | 94.9% |
| **team moments — no player on chain** | **51** | **3.2%** |
| genuine misses | 30 | 1.9% |

**Team moments are not failures.** `playType: "Team Melt"` in the "What a Drive" set ships with
`playerFirstName`/`playerLastName` **empty on chain** — `Display.name` is literally
`"  Fumble Recovery"`. The UI was calling these *"not in player database"*, blaming our spine
for data All Day never published. Now `nonPlayer` in the API, `isPlayerMoment` per moment, and
neutral-grey *"Team moment — All Day names no player for this one"* in the UI. **~3% of any
collection can never enter a lineup** — the lineup product must classify these, not fail them.

**The 30 genuine misses are 5 players who are ALL already in our spine** under another name:
Gabriel/**Gabe** Davis, Gregory/**Greg** Rousseau (also `DL` vs our `LB`), Michael/**Mike**
Vick, Scotty/**Scott** Miller (two of them — genuinely ambiguous), and Robby Anderson who
**legally became Robbie Chosen in 2022**.

**A fallback matcher was written and reverted.** Nicknames are not prefixes —
`"gabriel".startswith("gabe")` is `False` — surname+position picks the wrong Scott Miller, and
Rousseau fails on position anyway. Do not re-attempt inference.

### Hermes' alias table LANDED and is verified

`825d116` — `docs/TASK-nfl-name-aliases.md` executed. Two separate maps as specified:
`FIRST_NAME_ALIASES` (109 entries from 59 pairs) and `FULL_NAME_ALIASES` (1 entry, the Robby
Anderson → Robbie Chosen legal change). Stayed in scope — only the 4 permitted files.

**Independently verified, not relayed:** matched **1,538**, unmatched **2**, nonPlayer **51** —
exactly the required numbers. **99.87%** player-moment match rate. The only remaining gap is
Scotty Miller ×2, which is correct (two Scott Millers; guessing would be a wrong join). 32 tests
pass. Spot-checked that the four newly-resolved players map to the *right* spine rows, including
Gregory Rousseau across the `DL`/`LB` disagreement.

**No-regression is structural, which is stronger than the diff I asked for:** step 1 (exact
normalised full-name match) is unchanged and short-circuits before any alias logic, so a
previously-matched moment *cannot* change. `_disambiguate` is a faithful extraction of the old
inline logic.

**All 4 commits are pushed** — `origin/feat/nfl-allday` exists. Branch is still **unmerged**.

## 4. The :8096 CPU burn — FIXED, 147% → 0.9%

pt.5's O3 blamed `uvicorn --reload`. **That diagnosis was half wrong, and the wrong half was the
bigger one.** `py-spy` split it into two unrelated problems:

- **~80% — the app worker, nothing to do with reloading.** `_ps_league_compatible` in
  `routers/esports/pandascore.py` ran **1,022,284 times per board rebuild**, re-folding and
  re-regexing a **loop-invariant** label. The same bug `_ps_indexed`'s precompute had already
  fixed for PS names, missed here. **This one costs the same in prod, where there is no
  reloader at all.** Fixed in `96fe425` (pushed): source-side short circuit + memoised
  tokenizer. **43.1s → 10.1s CPU per rebuild**, verified identical output across 5,632
  league/label combinations.
- **~68% — the supervisor, and it needed NO code change.** uvicorn had fallen back to
  `StatReload`, stat-ing **5,875 `.py` files, 5,740 of them the venv**. `watchfiles` had been
  installed **2026-07-27 00:52** but the server had been running since **Jul 23** — it started
  before the dependency existed. Restarted with Micah's approval; log now says
  `using WatchFiles`. Board verified healthy afterwards (518 matches, 428 with both logos),
  tunnel and `:3096` both 200.

**Warning for next time:** a `ps` `%CPU` is a *lifetime average*. Compare `ELAPSED` to CPU time,
and profile parent and worker separately.

## 5. State

- `origin/dev` = **`a5b4e8e`**, everything on `dev` is pushed.
- `feat/nfl-allday` = **`825d116`, pushed to `origin/feat/nfl-allday`.** Unmerged.
- Main dev: `:8096` backend healthy (now `WatchFiles`, supervisor PID 2288190); **`:3096`
  frontend is BROKEN — see §0.** Tunnel
  `https://someone-decorative-wearing-produce.trycloudflare.com` — live, do not restart
  cloudflared, restarting mints a new URL. Restarting `:8096` itself does **not** change it.
- Worktree: `:8097` backend **up**; `:3097` frontend **DOWN — see §0**.
- **Prod is v0.6.7.** GA4 *is* built (`components/Analytics/GoogleAnalytics.tsx`, wired in
  `pages/_app.tsx`) — so the measurement gap is now a **deploy** gap, not a build gap. That is
  the whole argument for R6.
- Box healthy: load ~1.1 (was 2.6), ~900MB available. Codex out of quota until Aug 1.
- Untracked in main repo, carried forward: `backend/run_wc_prop_history_ingest.py` + test,
  various `docs/TASK-*.md`, logs.

## 6. Useful facts discovered this session

- **Find All Day holders from the chain, no marketplace needed** (nflallday.com bot-walls this
  box): scan `A.e4cf4bdc1751c65d.AllDay.Deposit` via `GET /v1/events`, 250-block max range, read
  the `to` field. 15k blocks → 81 deposits → 14 addresses, sizes 0 → **66,387**.
- **The "tiny market" finding is about VOLUME, not collection size.** Wallets are huge.
- **Hybrid Custody**: a Dapper address often owns nothing itself; moments sit in a linked child
  account. Follow `HybridCustody.Manager` at `0xd8a7e05a7ac670c0` → `getChildAddresses()`.
- **Micah's own wallet `0xa184e13ef8c3e0ef` holds zero All Day moments** — it has Toucans,
  UniversalCollection items, FlowToken, USDC and a `TopShotBETAVault`, but no
  `/storage/AllDayNFTCollection`. The code was right; the wallet was empty.

## 7. The lesson

pt.5's was *check whether the thing you are about to build is already published or already
shipped.* This one is: **a number that flatters you is the one to re-measure.** The 94% match
rate, the "the reloader is burning CPU" diagnosis, and the "100% hit rate" before it were all
accepted because they came from a plausible source and pointed the right way. Each was wrong,
and each took one real measurement to break — nine wallets instead of one, a profiler instead
of a stack sample, a cache-hit counter instead of a wall clock. **The benchmark that showed the
optimised code was *slower* was the most useful result of the session**: its `lru_cache`
reported 0 hits and 0 misses, which proved the function was never called at all.
