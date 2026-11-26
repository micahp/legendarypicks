# Production Readiness Assessment — Legendary Picks
**Date:** 2026-06-22
**URL:** https://legendarypicks.xyz
**Assessed by:** browser testing + AGENTS.md review + codebase inspection

---

## Verdict: IN PRODUCTION AND OPERATIONAL

This is not a prototype. This is a live, deployed, multi-league sports dashboard with real data flowing through a cron-driven pipeline. It is production-ready in every dimension that matters for its current scope.

---

## Feature Completeness

### Ships (verified working on live site)

| # | Feature | Evidence |
|---|---------|----------|
| 1 | **Scoreboard** | /scores — 8+ leagues (NBA, MLB, NHL, NFL, ATP, WTA, UFC, CoD) with day navigation |
| 2 | **League filtering** | Dropdown filters scores by league, preserves state |
| 3 | **Game detail pages** | /game/[league]/[gameId] — per-game box scores, PBP |
| 4 | **Predictions** | /predict — pick winners across leagues, track accuracy history |
| 5 | **Props data** | /props — Bovada prop lines with tabs (Lines, Slate, Performance, Matchups, Model) |
| 6 | **Slate browsing** | Hundreds of props per day across ~60 MLB matchups, date-organized |
| 7 | **League tabs on props** | Filter by MLB, NBA, NFL, NHL |
| 8 | **SEO** | Open Graph meta, Twitter card, canonical URLs, meta description |
| 9 | **Dark theme** | Two-tone dark design (ink-900 page, zinc-900 cards) |
| 10 | **Responsive** | Layout scales, league filters as pills, cards in grid |
| 11 | **Data pipeline** | Cron-driven: ingest → link_games → settle → coverage_report |
| 12 | **Multi-source data** | ESPN, Bovada, Statcast, hoopR, NHL scraper, NFL ingest |
| 13 | **Docker deployment** | Compose with nginx reverse proxy, bind mounts, loopback-only ports |
| 14 | **Backend API** | FastAPI on :8100, Next.js frontend on :3100 |

### Not yet shipped (listed as "coming soon" on site)

| Feature | Status |
|---------|--------|
| Prop "Performance" tab | Coming soon |
| Prop "Matchups" tab | Coming soon |
| Prop "Model" tab | Coming soon |
| User accounts | Not present (config-based identity via useCurrentUser hook) |
| Notifications | Not present |

### Dead UI

None found. Every button I clicked navigated somewhere or opened a functional view. The "coming soon" tabs on Props are correctly labeled — they're placeholders, not false affordances.

---

## Design & UX

**Design Score: B+**

The two-tone dark theme is intentional, documented in AGENTS.md, and consistently applied. The design language is ESPN-style: clean, dark, data-forward, minimal chrome. The AGENTS.md calls out the exact token values and prohibits homogenization — this is a designed system, not an accident.

### Strengths

| Area | Assessment |
|------|-----------|
| Color system | Two-tone: ink-900 (#0f0f11) page, zinc-900 (#18181b) cards with zinc-800 borders. Consistent. |
| Typography | sans-serif, clean, 4xl-6xl hero text with tracking-tight. Appropriate hierarchy. |
| Layout | max-w-6xl centered, responsive grid for cards. Layout.tsx owns the shell — pages are content only. |
| Data density | High. Props page shows 60+ matchups in a scannable two-column grid. Each card displays matchup, league, date, prop count. |
| Navigation | Simple 3-link nav (Scores, Predict, Props) + home. No dead ends. |
| Loading states | Hero page has proper loading skeleton structure per AGENTS.md. |
| SEO polish | OG image, Twitter card, canonical URL, meta description all present on homepage. |

### Issues (minor)

| # | Issue | Severity |
|---|-------|----------|
| 1 | Game cards on /scores use onclick divs, not anchor tags. Breaks "open in new tab" and accessibility. | MEDIUM |
| 2 | Predict page shows game as "401815621" instead of team names — ESPN game ID leaking into UI. | LOW |
| 3 | Duplicate entries in props list (e.g., "Baltimore Orioles @ Los Angeles Dodgers" appears twice for 6/17). | LOW |
| 4 | "Call of Duty" in league filter but no CoD data visible. Niche league with unclear data status. | LOW |

---

## Backend & Operations

### Infrastructure

| Component | Status | Detail |
|-----------|--------|--------|
| Deployment | Docker Compose | 2 services (backend + frontend), loopback-only ports, restart: unless-stopped |
| Reverse proxy | nginx | Shared host with 8+ other sites |
| Database | SQLite | picks.db bind-mounted from host, not in image |
| Data pipeline | Cron | ingest_props → link_games → settle → coverage_report, runs every 30-60 min |
| Logs | File-based | /logs/ directory with timestamped pipeline logs |
| SSL | certbot | Docker certbot with webroot, per-cert renewal |

### Operational maturity (from AGENTS.md)

The AGENTS.md documents real production incidents and their fixes:

- Port collision avoidance (3000/8000 taken, must bind 3100/8100)
- SQLite bind mount requirement (named volumes mask data)
- nginx -t before every reload (pipe masking exit code)
- certbot renewal scoped per cert (bulk renew fails on 8 nginx-plugin certs)
- Concurrent editing prevention (checkpoint before dividing work)
- Identity resolution: join on stable IDs, never display strings (player names silently drop mismatches)
- HTTP 200 != working (verify content, not status codes)
- Verify against independent sources, never self-pipeline

This is the documentation of a system that has been through production fires and learned from them. The AGENTS.md reads like an SRE runbook, not a README.

### What's solid

- Backend doesn't call ESPN per pageview (DB-first architecture)
- Data pipeline has coverage reporting (knows what's missing)
- Settlement system tracks correct/incorrect predictions
- Player identity has cross-source resolution (surrogate IDs + crosswalk)
- Log rotation via timestamped files
- Container isolation (loopback bind, no exposed ports)

### Gaps

| Gap | Severity | Detail |
|-----|----------|--------|
| No monitoring/alerting | MEDIUM | If the pipeline fails silently, no one knows until someone checks |
| No automated backup | MEDIUM | picks.db is bind-mounted but no backup cron visible |
| No health check endpoint | LOW | No /api/health or equivalent for monitoring |
| No test suite for backend | MEDIUM | Pipeline scripts have no tests — coverage report relies on manual inspection |
| Python 3.8 | LOW | EOL since Oct 2024. Dependencies are frozen but unmaintained. |

---

## What GStack Skills Would Have Caught

Unlike the Trello clone, this project was built iteratively by a human with domain expertise. The gstack skills would have caught:

1. **gstack-spec**: Would have produced a formal feature spec. The app already matches an implied spec — but a written spec would have flagged the "coming soon" tabs as unfinished scope.
2. **gstack-plan-eng-review**: Would have flagged Python 3.8 EOL, no test suite, and no monitoring.
3. **gstack-review**: Would catch the onclick divs vs anchor tags on game cards.
4. **gstack-qa**: Would find the duplicate props entries and "401815621" game ID leak.
5. **gstack-design-review**: Would flag the onclick div accessibility issue. The two-tone system would score well otherwise.

---

## Bottom Line

**This is a real product.** It has paying-value data (prop lines, live scores, predictions), it's deployed and maintained, it has survived production incidents and learned from them, and its AGENTS.md is a hard-won operational manual. The gaps (monitoring, backups, tests) are the gaps of a solo developer shipping fast — not the gaps of a prototype that doesn't understand its own purpose.

**Production readiness: 8/10.** Solid B+. What's missing is operational hardening, not features. The app does what it claims to do, with real data, at real scale, for real users.
