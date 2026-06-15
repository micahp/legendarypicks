# Legendary Picks — Site Polish Checklist

Tailored to this stack (Next.js Flow dapp + FastAPI/ESPN backend). Work top-down; each item is a
concrete, shippable improvement.

## Performance
- [ ] `next.config.js`: set `output: 'standalone'`, enable `images` optimization; audit bundle with
      `ANALYZE=true` (next-bundle-analyzer) and code-split heavy components (charts, wallet libs).
- [ ] Lazy-load below-the-fold and modal components (`next/dynamic`, `ssr:false` for wallet UI).
- [ ] **Cache the ESPN backend** — `sports_service.py` hits ESPN live; add an in-memory/TTL cache
      (e.g. 60–300s per endpoint) so the site is fast and you don't hammer ESPN. Set HTTP
      `Cache-Control` on backend responses; let nginx micro-cache GETs.
- [ ] Use `next/image` for all imagery (logos, player/team art) with width/height to kill CLS.
- [ ] Lighthouse pass (mobile): target LCP < 2.5s, CLS < 0.1, TBT low.

## UX & states (biggest perceived-quality wins)
- [ ] **Loading skeletons** for every data view (picks, leaderboards, matchups) — no blank flashes.
- [ ] **Empty states** ("no picks yet", "no games today") with a clear next action.
- [ ] **Error states** — backend/ESPN failure shows a friendly retry, not a stack trace or spinner-forever.
- [ ] Mobile-first responsive pass; test 360px width; tap targets ≥ 44px; no horizontal scroll.
- [ ] Consistent spacing/typography via the Tailwind config; one type scale, one color scale.

## Web3 / Flow specifics (where dapps feel broken)
- [ ] **Wallet connect** flow: clear connect/disconnect, show truncated address + avatar.
- [ ] **Network-mismatch banner** — if `NEXT_PUBLIC_FLOW_NETWORK` ≠ the user's wallet network, warn
      and block actions.
- [ ] **Transaction lifecycle UI** — pending / sealed / error toasts with the tx id link to Flowscan.
- [ ] Human-readable errors (map FCL/cadence errors to plain text; never surface raw revert strings).
- [ ] Disable submit buttons during in-flight tx; optimistic UI where safe.

## SEO / meta / shareability
- [ ] Per-page `<title>` + meta description; Open Graph + Twitter card images (1200×630).
- [ ] Favicon set + apple-touch-icon + `manifest.json`; `robots.txt` + `sitemap.xml`.
- [ ] Canonical URLs; structured data (SportsEvent / BreadcrumbList) where relevant.

## Accessibility
- [ ] Alt text on all images; sufficient color contrast (WCAG AA); visible focus rings.
- [ ] Keyboard-navigable menus/modals; `aria-label`s on icon-only buttons.

## Reliability / ops
- [ ] Backend input validation (pydantic) + graceful ESPN timeout/retry with backoff.
- [ ] Health endpoint (`/health`) for nginx/docker healthchecks.
- [ ] Error tracking (Sentry) on frontend + backend; basic uptime monitor on legendarypicks.xyz.
- [ ] Rate-limit the public API (nginx `limit_req`) to protect the ESPN passthrough.

## Brand / final coat
- [ ] Consistent logo/wordmark, 404 + 500 pages on-brand, dark-mode parity.
- [ ] Microcopy pass (button labels, tooltips); remove placeholder/lorem text.
- [ ] Cross-browser check (Safari/iOS especially for wallet + flex layouts).

## Quick wins to do first
1. Loading skeletons + error/empty states (instant perceived quality).
2. ESPN response caching (speed + stability).
3. Network-mismatch banner + tx toasts (dapp trust).
4. OG images + favicon + titles (shareability).
