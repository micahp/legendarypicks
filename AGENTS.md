# AGENTS.md — read this before editing legendarypicks

> **Guiding principle (read first).** Before trusting any result, define from first principles what
> "correct and complete" would actually require, then verify it against ground truth — the whole
> population, not a convenient sample; the real data, not a status code; an independent source, not the
> output you just produced — and assume an undiscovered gap remains until you've measured it.

This is a Next.js app with a shared **Layout** and an intentional **two-tone dark theme**. The rules below
come from real mistakes. Follow them literally; when unsure, look at how an existing page does it and copy that.

## 0. Current state — read these first

> ### Leagues that are NOT in play — do not spend time here
> **World Cup (`wc`) is OUT OF SEASON and stays that way.** The 2026 tournament is over; the next
> one is **2030**. `backend/ingest_wc_logs.py`, the WC pages, and anything else `wc`-scoped are
> **dormant code**. Do not build WC features, do not refactor WC ingest, do not "improve" it while
> passing through. Touch a `wc` file only when it is *blocking* the task you were actually given —
> and say so explicitly when you do.
>
> **The live calendar is NFL.** Fantasy football is the forced focus; NFL work outranks everything
> else. UFC and esports are the active secondary surfaces. MLB/NBA/NHL are maintenance-only.

- **Latest session handoff:** `docs/CONTEXT-2026-06-28.md` (most recent; supersedes earlier `CONTEXT-*`).
- **Backend is no longer one file (Jun-27 refactor).** `backend/sports_service.py` is now a thin app
  shell that `include_router`s `backend/routers/{games,players,props,analytics,game_extras}.py`. Shared
  DB/schema, `_helpers`, market maps, and Pydantic models live in `backend/_core.py`; routers pull them
  with `from _core import *` (core sets `__all__` so underscore names export). **Add a new endpoint to the
  matching router, not to `sports_service.py`.** Frontend game page is likewise split into `components/Game/*`.
- **Deploying / promoting to prod?** Read `docs/RUNBOOK-prod-promotion.md` FIRST. Prod is a docker
  stack on this host with its OWN DB (`backend/data/picks.db`), separate from dev (`picks.dev.db`).
  The trap: shipping code whose data isn't migrated into `picks.db` (200 ≠ working). Procedure +
  the `migrate_logs_to_prod.py` data step are in the runbook. **Current prod = v0.6.5 (deployed 2026-07-26);
  `dev` is at v0.6.7.** Cut releases with `scripts/release.sh <version>` only — never bump the version,
  write the tag, or push them separately by hand. That is what burned v0.6.1–v0.6.4.
- **v0.3.0 roadmap (the UI holes gating it):** `docs/SPEC-v0.3.0-ui-holes.md` — richer Stats (player/team,
  offensive/defensive), non-MLB game detail + the 3 empty tabs, post-game recap, prop outcomes on game
  detail, **UFC build-out** (props/stats/rankings + per-fight strike/takedown data for modeling), and a
  **World Cup/CoD bracket + pick'em** page.
- **Earlier next-phase spec:** `docs/SPEC-2026-06-27-next-phases.md` (NBA matchups, Stats-page leagues, UFC
  rankings — with acceptance criteria). **Engineering retro:** `docs/RETRO-2026-06-27.md`.

---

## 1. Layout owns the page shell — a page must NOT re-create it
`pages/_app.tsx` wraps **every** page in `components/Layout.tsx`, which already provides:
```jsx
<div className="min-h-screen bg-ink-900 text-zinc-100">   // page background + min height
  <header ... />
  <main className="mx-auto max-w-6xl px-4 py-8 space-y-6">{children}</main>  // width clamp + padding
```
So a page's returned JSX is **content only**. It must **never** set its own:
`min-h-screen`, `bg-*`, `text-zinc-100`, `max-w-*` (except a deliberate narrower column), `px-*`, `py-*` at the
top level. Doing so **double-wraps** the shell and **repaints the background**, which is exactly how the scores
and detail pages got broken.

❌ Wrong (what was there):
```jsx
if (loading) return <div className="min-h-screen bg-zinc-900 text-zinc-100 px-4 py-8"> ... </div>
return <div className="max-w-4xl mx-auto py-6 space-y-5"> ... </div>   // py-6 on top of Layout's py-8
```
✅ Right:
```jsx
if (loading) return <div className="max-w-4xl mx-auto animate-pulse space-y-3"> ... </div>
return <div className="max-w-4xl mx-auto space-y-5"> ... </div>   // max-w-4xl = intentional narrower detail column
```
Same rule for `pages/index.tsx` (it still violates this with `min-h-screen bg-zinc-950`).

## 2. The two-tone is the design — do NOT homogenize it
The contrast between page and card **is** the visual structure. Tokens (`tailwind.config.js`):
- **Page background = `bg-ink-900`** (`#0f0f11`) — set once, by Layout.
- **Cards / panels = `bg-zinc-900`** (`#18181b`, slightly lighter) with `border border-zinc-800`.
- **Skeletons / shimmer blocks = `bg-zinc-800`** (so they're visible on the page, not invisible on a card).

Never paint a page `bg-zinc-900` (that's the card color → cards vanish → "unpolished, no two-tone"). Never make
page and card the same color "to look clean" — they are *supposed* to differ. If you think you need a new
background color, you don't; reuse `ink-900` (page) / `zinc-900` (card).

## 3. Verify against the DESIGN INTENT, not against your own output
Two failures today both came from verifying the wrong thing:
- **Background:** ran `getComputedStyle` on page vs card, saw both `rgb(24,24,27)`, declared "uniform, verified."
  But the requirement was that they be **different**. Equal-is-not-the-goal — the design called for two-tone.
- **Score reconcile:** reported "113-111 FINAL, verified" by reading the same buggy DB query that produced it.
  The real final was 115-111.

Rules:
1. Verify against the **requirement** (here: "cards must read as distinct from the page"), not against "are
   these two values equal" or "did my code return something."
2. **Never confirm a derived value against the code/pipeline that produced it.** Check an *independent* source
   of truth (the real game's final score; a screenshot a human can sanity-check; the design mock).
3. A confident wrong "verified" is worse than saying "I'm not sure this looks right — please eyeball it."

## 4. When you fix a bug, sweep for the same mistake everywhere
A reported bug is almost always **one instance of a pattern**, not a one-off. After you fix the file someone
pointed at, grep the whole codebase for the same anti-pattern and fix (or flag) every other instance — don't
stop at the single symptom. Example from the wrapper bug: after fixing the detail page, this sweep
```bash
grep -rn "min-h-screen" pages/ --include=*.tsx | grep -E "bg-zinc|bg-ink"
```
surfaced `pages/index.tsx` doing the exact same thing. If you'd only fixed the one page you were told about,
the bug would still be live elsewhere. Do the sweep as part of the fix and report what else it found.

## 5. Smaller discipline
- **Read an existing example first.** Before adding a wrapper/component, open a working page (`pages/scores.tsx`)
  and copy its structure. Most "new" structure you add is already provided by Layout/components.
- **Minimal diffs.** Don't restructure wrappers to fix a color; change the one class that's wrong.
- **Backend is DB-first.** Serving a page must not call ESPN per request — read from our DB (`picks.db`); ESPN
  calls belong in the collection path (`/boxscore` snapshot) or an occasional out-of-band job, never per pageview.
- **No AI attribution** in commits or code. Plain, human commit messages.

---

# Ops / deploy / infra — read before deploying or touching the server

This server is **SHARED** (8+ sites behind one nginx). A mistake here can take down other sites.
Every rule below comes from a real mistake on 2026-06-15.

## 6. Deploy / server
- **Never assume a port is free.** 3000/8000 are taken. `ss -tlnp` first, pick a free port (e.g.
  3100/8100), and **bind `127.0.0.1` only** (`ports: ["127.0.0.1:3100:3000"]`) so only nginx reaches
  it. Use the same port in compose, the nginx `proxy_pass`, and any in-container proxy.
- **SQLite DB = BIND MOUNT, not a named volume.** Mount `./backend/data:/app/data`. A fresh named
  volume mounts EMPTY over the data dir and masks the real `picks.db` → UI shows "no data" (happened).
  Keep the dev DB out of the image (`.dockerignore: data/*.db`); never serve `data/` statically.
- **HTTP 200 ≠ working.** Before declaring anything live, curl the real data endpoints, confirm
  **non-empty content** + that the UI renders it. Tell "empty = expected state" from "empty = broken"
  by checking the DB, not by assuming. (Same spirit as §3: verify the requirement.)
- **Finish & verify the primary task before peripheral work.** Don't chase adjacent problems (other
  sites' certs, cleanup) while the thing you're shipping is unverified.
- **nginx:** `nginx -t` before EVERY reload — a bad reload takes down ALL sites. Check `nginx -t`'s
  **exit code directly**; never `nginx -t | tail && reload` (the pipe hides the failure). nginx here is
  old: use `listen 443 ssl http2;`, NOT `http2 on;`.
- **certbot:** system certbot (0.40.0) is BROKEN (pyOpenSSL). Issue/renew via **docker certbot +
  webroot** (keep an `acme-challenge` location in :80). Renewal cron must be **scoped per cert**
  (`--cert-name`) + reload nginx after — bulk `renew` fails on the 8 nginx-plugin certs.
- **Concurrent editing:** if another agent is editing the repo, **commit/checkpoint before dividing
  work**, split frontend vs backend ownership, don't build images from a half-edited tree.

## 7. Data sources
- **Resolve identity BEFORE you integrate sources. Join on stable IDs, never on display strings.**
  Any entity that arrives from more than one source (players, teams, games, props) needs ONE canonical
  surrogate ID plus a crosswalk of each source's native ID — established at ingest, *before* you wire
  the sources together. Joining on human-readable strings (names, team names, titles) silently drops
  every spelling/format mismatch, and the loss is **invisible until you measure against ground truth.**
  We joined players by name across Bovada/ESPN/Statcast/nflverse/nhle and roster coverage was 2–55%
  (whole leagues missing) while everything *looked* fine. Names are for humans; keys are for joins.
  Build the identity spine first, key all downstream data on the surrogate ID, and send unresolved
  records to a review queue — never silently create a names-only row or drop a mismatch. (This is the
  Guiding-principle "the whole population, not a convenient sample" applied to data modeling: a string
  join quietly *is* a convenient sample.)
  - **The miss case is where it breaks: resolve-or-QUEUE, never DUP.** When an ingest can't find a
    player by its source-id, it must link to the canonical row (backfill the id) or send it to the
    review queue — it must **never insert a second `players` row**. Doing so creates two rows for one
    human (e.g. props on the `espn_id` row, logs on a Statcast `mlbam_id` row) and every join silently
    splits. This actually happened: 317 MLB players split, prop charts showed no data for Freeman/Betts/
    Kurtz while coverage *looked* fine. See **`docs/IDENTITY-SPINE-STATE.md`** (as-built spine, the rule,
    per-league dup status) + `docs/SPEC-player-identity-spine.md` (design). Cleanup: `dedupe_mlb.py` /
    `dedupe_nfl.py` — merge by shared source-id only, never by name.
- **Don't live-scrape hostile endpoints.** `stats.nba.com` blocks **datacenter IPs** (not geo — this
  box is already US). A new/US VPS or free proxy won't help (all datacenter IPs); only paid residential
  proxies bypass it. Use **ESPN** + **published data releases** (`nfl_data_py`/nflverse,
  hoopR/sportsdataverse) — static files, never IP-blocked.
- **Heavy/optional deps OFF the request path.** `pybaseball`, `nfl_data_py`, etc. go in **ingest
  scripts** that populate `player_stats`; request handlers read the DB only. Never `import` a
  possibly-uninstalled lib in a request handler — it blanks on a clean rebuild (the `pybaseball` import
  was left in the request path but removed from requirements → MLB stats silently broke).
- **Persist; don't rely on in-memory caches.** An in-memory `_stats_cache` is wiped on every redeploy →
  cold-load latency (pybaseball's ~100MB Chadwick register = the 10s player load). Pattern:
  **ingest → `player_stats` → serve from DB → instant** for every league. (Reinforces §5 DB-first.)

## 8. Next.js build / wiring
- **Lint must not block a deploy.** `next.config.js`: `eslint.ignoreDuringBuilds` +
  `typescript.ignoreBuildErrors`. Lint/type style = quality item (POLISH-CHECKLIST), not a deploy gate.
- **In-container API proxy uses the service name, not localhost.** Next rewrites/SSR target
  `http://backend:8000` (compose service), not `localhost:8000` (= the frontend container itself).
  Make it env-driven (`API_PROXY_TARGET`).

## 9. Frontend UX patterns that bit us
- **Search dropdown:** setting `query` on select re-fires the search and re-opens the list. The search
  component must **own its open/close state** — close on select AND on click-outside.
- **Mobile:** a fixed `grid grid-cols-N` squashes on small screens. Use `overflow-x-auto` + `min-w`
  cells (or responsive breakpoints) so content scrolls instead of cramming.

## 10. Review lessons — game-detail tabs (2026-06-29)
Caught at review (orchestrator), should have been caught by the feature's own validators:
- **ESPN `/summary` fields are OBJECTS, not strings.** `position` = `{name,displayName,abbreviation}`,
  `clock` = `{value,displayValue:"45'+2"}`, `team` = `{name,displayName,abbreviation}`. **Extract the
  string** (`.abbreviation`, `.displayValue`) in the backend before putting it in a contract. Shipping
  `pos: p["position"]` (the object) crashed the WC page with *"Objects are not valid as a React child"*.
- **Never render an object as a React child — and the FRONTEND VALIDATOR MUST load each variant in a
  headless browser and assert ZERO `pageerror`s + real data.** The build "passed" but every WC tab
  crashed on load. A 200 from the endpoint is NOT acceptance; you must render the page. Screenshot
  one game PER league family (US-team-sport AND soccer) and per N/A league (tennis = hidden tabs).
- **Parse defensively:** clock displayValues include stoppage (`"45'+2"`) and empty (`""`). Take the
  leading number; don't `int(x.replace("'",""))` (breaks on `+`, gives `0`, mis-sorts the timeline).
- **Don't commit gitignored junk.** `__pycache__/` and `venv` got committed (use targeted `git add`,
  not `git add -A`) — they then block merges with dirty-tree errors.

## 11. Operating rules
- **`/root/legendarypicks` is the managed `dev` worktree. Do not switch it away from `dev` for
  feature development.** The `:3096` frontend and `:8096` backend read directly from this
  directory. Create feature branches in isolated worktrees instead, for example:
  `git worktree add /root/lp-<task> -b feat/<task> dev`. At the start of every task, verify
  `git -C /root/legendarypicks branch --show-current` prints `dev`. Running `git switch dev`
  here to restore the designated branch is allowed after preserving conflicting WIP. A deliberate
  switch away from `dev` requires explicit user authorization, a clean or recoverably preserved
  worktree, and coordination with the managed services. Prepare and verify feature merges in an
  isolated worktree; update the main worktree only after the merged `dev` result is ready.
- **Never run `npm`, `npx` or `yarn` from a worktree — not install, not build, not test.** A
  worktree's `node_modules` is a **symlink to `/root/legendarypicks/node_modules`**, so npm resolves
  against the shared install and prunes it: on 2026-07-27 an `npm exec next dev` and later an
  `npm run build`, both from worktrees, each emptied it to **zero packages** and took the main dev
  frontend and the public tunnel down. Run binaries directly instead —
  `/root/legendarypicks/node_modules/.bin/next`, `.../.bin/jest`, `.../.bin/tsc`.
  **If `npm run build` fails with `next: not found`, that is not a missing dependency — it is the
  install you just deleted. Stop and report it; do not retry and do not reinstall.** Recovery is
  `npm ci` in the MAIN repo (~45s), then relaunch the server from the binary.
- **Dev servers are externally managed.** A frontend is already running on `:3096` and a backend on
  `:8096`. Verify against those services and re-request a page or endpoint if it appears stale.
- **Never start, kill, or restart a dev server.** Never run `kill` or `pkill` against Node or uvicorn;
  duplicate processes and terminated servers corrupt the shared tunnel.
- **Skills live in `.claude/skills/`, and they are not optional reading.** Load
  **`published-first`** before writing anything that derives, aggregates, reconstructs or
  back-fills a value — including schedules, bye weeks and join keys; **`honest-data-ui`** before
  designing any surface that shows numbers; **`resource-check`** before batch work.
- **Backend agents (Codex, Hermes): the two questions, asked in this order, before you write a
  line.** They are siblings and they kill different things.
  1. **ponytail** — *"does this code need to exist?"*
     (https://github.com/DietrichGebert/ponytail). **Not installed on this box**; apply the
     question anyway. It is the cheapest review there is, because the fastest code is the code
     you delete before writing.
  2. **`published-first`** — *"does this value need to be computed?"* Walk its ladder. Rung 5 is
     the one that keeps getting skipped: **a definition — a schedule, a roster, a bye week, a
     team code, a draft position — is always published somewhere. Never infer it.**

  Both were violated by the same 40 lines. `nfl_mock_draft.py` grew a derived `dst_rank`, a
  reserved pool slot and a bespoke ordering behind the comment *"D/ST — no published ADP
  exists."* Measured 2026-07-28: **all 32 D/ST carry a published ADP, inside a payload
  `ingest_nfl_adp.py` already downloads.** ESPN keys them with negative ids
  (`-16000 - proTeamId`), so the `espn_id` join matched **0 of 32** — and a wrong join key does
  not raise, **it misses.** The derivation also disagreed on the merits: it ranked SEA #1 where
  ESPN ranks DEN #1 and SEA 4th. published-first would have caught the value; ponytail would
  have caught the code. Neither was asked.

  **Corollary, learned the same day: a comment asserting that data does not exist is a
  hypothesis, and it ages badly.** That one sentence was load-bearing for a derivation, a
  reserved slot, a gate assertion and an open product decision, and it was one HTTP call from
  being falsified. Check the claim before you build on it.
- **Follow `docs/DEV-STANDARDS.md`.** In particular, list endpoints must not download substantially
  more data than the UI renders, payload sizes must be measured, and an HTTP 200 alone is not proof
  that a feature works.
- **Reproduce before you fix.** Before writing (or being handed) a bug fix, pin the EXACT repro: which
  URL/surface, which element, expected vs actual — by opening the live page or hitting the endpoint.
  Never inherit a diagnosis from a task doc/handoff as fact; confirm the named code path actually
  produces the visible symptom. A wrong-surface fix wastes a whole run. (Jul-18: a "day grouping" bug
  was chased on `/esports` when the real bug was UTC date-bucketing on `/scores`.)

## 12. Don't let a process take over the box (added 2026-07-25)

**This box has 5.8GB RAM total and normally sits ~4-4.7GB used** — several dev servers, LSPs, and
background services across projects. Headroom is usually under 1.5GB. Assume you are sharing it with
a live dev server and tunnel a human is actively browsing.

- **Check BOTH load and memory before any batch job** — `uptime` AND `free -h`. `uptime` alone is
  not enough; the real ceiling here is RAM/swap, not CPU. If `available` is under ~1-1.5GB, don't
  start. Say the expected cost (CPU, memory, duration, subprocess/thread count) out loud BEFORE
  running, not after someone notices the site got slow.
- **Read the script's internals, not just its CLI flags.** A chunked `--start`/`--end` argument tells
  you nothing about what happens inside one call. (Jul-24: `ingest_mlb_logs.py` was "fixed" by
  chunking the date range, but `pybaseball.statcast()` defaults to `parallel=True` and spins a thread
  per day in the range, each holding a full day's pitch-level DataFrame, then concats them — a single
  7-day chunk drove load to **189** and swap to near-full, and starved the tunnel. Fix was one day at
  a time with `parallel=False`.) Go read a library call's source if its concurrency isn't obvious.
- **Throttle by default**: smallest real unit first (one day, one page) while watching `free -h`,
  brief pauses between units, single-process over any internal parallelism. A chunk size that
  "worked before" on a different code path is not evidence.
- **Verify a kill actually landed** (`ps`/`pgrep`) before reporting something stopped. A `pkill`
  exit code is not proof — a missed pattern kept a backfill running after it was reported dead.
- There is a **`resource-check` skill** at `.claude/skills/resource-check/SKILL.md` encoding the
  above. Load it before batch work.
- **Don't run parallel worktree dev-server stacks.** `scripts/hermes-worktree.sh up` hardcodes
  3096/8096 and collides with the main env; 3+ concurrent `next dev` stacks exhausted inotify
  watches and OOM-killed a running agent. See `docs/RUNBOOK-parallel-dev-servers-and-hmr.md`.

### The tunnel specifically
- A `cloudflared` quick tunnel points at a **port**, so it **never needs restarting** when the
  process behind it restarts. Don't touch it.
- **Never run `scripts/hermes-worktree.sh down <task>` while a tunnel is up on :3096/:8096.** It
  `pkill`s by hardcoded port and has killed the live tunnel as collateral even for a worktree whose
  own servers never bound (Cloudflare 1033 on the user's end). Quick tunnels get a **new URL** each
  restart, so this is not cheap to undo.
- If the frontend wedges — a route 500s with `ENOENT ... .next/server/pages/<route>.js` while the
  process still looks alive — **run `ls node_modules | wc -l` BEFORE touching `.next`.** If it is 0,
  the cause is a worktree `npm`/`npx` having pruned the shared install (§11), the server has been
  serving deleted inodes, and `rm -rf .next` alone fixes nothing: recover with `npm ci` in the main
  repo first. This exact symptom was misdiagnosed as build corruption twice on 2026-07-27. Only once
  `node_modules` is intact is the answer `kill` + `rm -rf .next` + relaunch — a corrupt cache (from
  memory pressure during a rebuild, or a branch checkout under the running server) presents the same
  way. **Ask first**, per §11 — it's externally managed.
- Relaunch is `./node_modules/.bin/next dev --port 3096`, run from `/root/legendarypicks`.
  **Not `npx next`** — that decides the pinned `next@13.0.0` is unsatisfying and fetches `next@16`.
  **Not `npm run dev`** from a worktree, per §11. If you do use `npm run dev` in the main repo, the
  `--` matters: `npm run dev --port 3096` silently passes `3096` as a positional and Next treats it
  as a project directory (`Invalid project directory provided, no such directory:
  /root/legendarypicks/3096`).
