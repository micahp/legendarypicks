# AGENTS.md — read this before editing legendarypicks

> **Guiding principle (read first).** Before trusting any result, define from first principles what
> "correct and complete" would actually require, then verify it against ground truth — the whole
> population, not a convenient sample; the real data, not a status code; an independent source, not the
> output you just produced — and assume an undiscovered gap remains until you've measured it.

This is a Next.js app with a shared **Layout** and an intentional **two-tone dark theme**. The rules below
come from real mistakes. Follow them literally; when unsure, look at how an existing page does it and copy that.

## 0. Current state — read these first
- **Latest session handoff:** `docs/CONTEXT-2026-06-28.md` (most recent; supersedes earlier `CONTEXT-*`).
- **Backend is no longer one file (Jun-27 refactor).** `backend/sports_service.py` is now a thin app
  shell that `include_router`s `backend/routers/{games,players,props,analytics,game_extras}.py`. Shared
  DB/schema, `_helpers`, market maps, and Pydantic models live in `backend/_core.py`; routers pull them
  with `from _core import *` (core sets `__all__` so underscore names export). **Add a new endpoint to the
  matching router, not to `sports_service.py`.** Frontend game page is likewise split into `components/Game/*`.
- **Deploying / promoting to prod?** Read `docs/RUNBOOK-prod-promotion.md` FIRST. Prod is a docker
  stack on this host with its OWN DB (`backend/data/picks.db`), separate from dev (`picks.dev.db`).
  The trap: shipping code whose data isn't migrated into `picks.db` (200 ≠ working). Procedure +
  the `migrate_logs_to_prod.py` data step are in the runbook. **Current prod = v0.2.2 (deployed 2026-06-28).**
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
- **Dev servers are externally managed.** A frontend is already running on `:3096` and a backend on
  `:8096`. Verify against those services and re-request a page or endpoint if it appears stale.
- **Never start, kill, or restart a dev server.** Never run `kill` or `pkill` against Node or uvicorn;
  duplicate processes and terminated servers corrupt the shared tunnel.
- **Follow `docs/DEV-STANDARDS.md`.** In particular, list endpoints must not download substantially
  more data than the UI renders, payload sizes must be measured, and an HTTP 200 alone is not proof
  that a feature works.
- **Reproduce before you fix.** Before writing (or being handed) a bug fix, pin the EXACT repro: which
  URL/surface, which element, expected vs actual — by opening the live page or hitting the endpoint.
  Never inherit a diagnosis from a task doc/handoff as fact; confirm the named code path actually
  produces the visible symptom. A wrong-surface fix wastes a whole run. (Jul-18: a "day grouping" bug
  was chased on `/esports` when the real bug was UTC date-bucketing on `/scores`.)
