# Changelog

## v0.5.9 — 2026-07-22

### Design — Broadcast Rail live cards

- **LiveNow** (`pages/scores.tsx`): Replaced red-bordered opacity-hack card with solid zinc-900 surface + emerald left edge. Featured game gets team abbreviations and display-scale scores (text-5xl). All live games shown as compact inline chips — no toggle. Esports link demoted to quiet right-aligned text.
- **LiveDiscounts** (`components/LiveDiscounts.tsx`): Replaced amber-bordered opacity-hack wrapper with solid zinc-900 + amber static left edge. DiscountCards use subtle `border-zinc-800/40` instead of heavy card frames.
- **CSS** (`styles/globals.css`): Added `.live-edge` (emerald) and `.amber-edge` (amber) utility classes for the edge-bar design vocabulary.
- **Docs** (`docs/DESIGN-live-card-rail.md`): Design rationale and before/after.

## v0.5.8
