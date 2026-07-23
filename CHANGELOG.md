# Changelog

## v0.6.0 — 2026-07-23

### NFL: Draft Room → Player Rankings

- **Real ADP** (`backend/ingest_nfl_adp.py`): ingests ESPN's own fantasy API (free, unauthenticated) for real 2026 average-draft-position data, joined on the existing `players.espn_id` spine. Always-visible column next to whatever stat you're sorted by, with owned% as a sanity check.
- **Season-projected fantasy points**: recency-weighted per-game projection (`analytics/projections.py`) × games assumed (capped at 17), surfaced as its own always-visible column. Fixed a bug where it was silently built from stale 2024 data only (2024/2025 ingests use different stat key names for the same stat).
- Sort row now leads with ADP + Season Proj (ADP is the default sort), instead of trailing after last-season per-game stats.
- Renamed "Draft Room" → "Player Rankings" and dropped the card wrapper — it's a ranked cheat-sheet, not an interactive draft experience.
- **Recent Trades** (`components/Leagues/NflOffseasonMovers.tsx`): replaced the full unfiltered transaction feed (mostly signings/waives/IR noise) with trades only. Bundled multi-sentence transactions are split so each trade gets its own line; mirrored entries (ESPN logs one row per team in a deal) are deduped by player names, keeping whichever side gave up the more significant player (real ADP as the significance signal). Player names bolded.

### Infra

- `docs/RUNBOOK-parallel-dev-servers-and-hmr.md`: resource limits and gotchas running multiple delegated-task dev-server stacks on this box (port collisions, inotify exhaustion, live-editing under a running server).

## v0.5.10 — 2026-07-22

- **LiveNow** (`pages/scores.tsx`): Reverted featured game to horizontal two-row layout (team name + score per row) — cleaner, closer to original.

## v0.5.9 — 2026-07-22

### Design — Broadcast Rail live cards

- **LiveNow** (`pages/scores.tsx`): Replaced red-bordered opacity-hack card with solid zinc-900 surface + emerald left edge. All live games shown as compact inline chips — no toggle. Esports link demoted to quiet right-aligned text.
- **LiveDiscounts** (`components/LiveDiscounts.tsx`): Replaced amber-bordered opacity-hack wrapper with solid zinc-900 + amber static left edge. DiscountCards use subtle `border-zinc-800/40` instead of heavy card frames.
- **CSS** (`styles/globals.css`): Added `.live-edge` (emerald) and `.amber-edge` (amber) utility classes for the edge-bar design vocabulary.
- **Docs** (`docs/DESIGN-live-card-rail.md`): Design rationale and before/after.

## v0.5.8
