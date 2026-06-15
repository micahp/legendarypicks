# AGENTS.md — read this before editing legendarypicks

> **Guiding principle (read first).** Before trusting any result, define from first principles what
> "correct and complete" would actually require, then verify it against ground truth — the whole
> population, not a convenient sample; the real data, not a status code; an independent source, not the
> output you just produced — and assume an undiscovered gap remains until you've measured it.

This is a Next.js app with a shared **Layout** and an intentional **two-tone dark theme**. The rules below
come from real mistakes. Follow them literally; when unsure, look at how an existing page does it and copy that.

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
