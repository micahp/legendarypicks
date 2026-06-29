# SPEC — "Leagues" hub (Stats → per-league tabbed pages, ESPN-style)

**Spec by Claude (orchestrator). Implementation: DELEGATE to Hermes** (worktree + tmux). Verify-
before-merge by me. Read **`AGENTS.md` (esp. §10)** before coding — recent lessons apply directly here.

## Goal
Turn the single **Stats** page into a **Leagues hub**: pick a league, get an ESPN-style page with
tabs (Standings, Stats, Schedule, etc.). The "World Cup stats stuck on group stage" complaint is a
*symptom* — the real fix is this restructure + a WC standings tab that reflects the **current stage**
(knockout bracket, not stale group tables).

## Current state (reuse, don't rebuild)
`pages/stats.tsx` already is a proto-hub: league selector (MLB/NBA/NHL/NFL/WC/UFC), a Players|Teams
subview, standings (`/api/{lg}/standings`, WC = group tables w/ draws via `group_standings`), leaders
(`/api/{lg}/leaders`, MLB batting/pitching toggle), and a UFC rankings view (`/api/ufc/rankings`).
Nav "Stats" link is in `components/Layout.tsx`. Game-detail pages (box score/PBP/info tabs) now exist
for NBA/NHL/MLB/NFL/WC and are reachable from `/scores`.

## What to build
1. **Nav + routes.** Rename nav **Stats → Leagues**. Routes: `/leagues` (index — choose a league) and
   `/leagues/[league]` (the hub page). Keep `/stats` working (redirect to `/leagues`) so nothing breaks.
2. **Per-league hub page `/leagues/[league]`** with a tab bar. Tabs (show only those with data):
   - **Standings** — division/conference tables (existing `/standings`); **WC = knockout bracket /
     results** once group stage is over (see WC note). Records, W-L, win%, diff.
   - **Stats** — the existing leaders, with the Players | Teams subview (MLB batting/pitching toggle).
   - **Schedule** — the league's games (reuse the scoreboard `GameCard` list, league-filtered); cards
     link to the game-detail pages we built.
   - **Rankings** — UFC only (existing `/api/ufc/rankings`).
   - (Leave a slot for **Predictions** later — MSI/esports model + prop model; out of scope now.)
3. **League index `/leagues`** — a simple grid of the leagues (logo/name) linking into each hub.
4. Consistent with the app shell/design (Layout owns the shell — AGENTS.md §1; two-tone — §2).

## WC standings — the actual data fix
`group_standings('wc')` returns **group-stage tables**, which are stale now that the tournament is in
the knockout stage. The Standings tab for WC must show the **current stage**:
- Investigate what ESPN gives now: the `/standings` endpoint may still only have groups. The knockout
  **bracket/fixtures + results** come from the scoreboard (`soccer/fifa.world/scoreboard`, the
  knockout events) — build a bracket/results view from that if standings lacks knockout data.
- Acceptance: WC Standings shows the **knockout round** (Round of 32/16, results + upcoming), NOT the
  finished group tables. Confirm against the live tournament state.

## Acceptance criteria
- `/leagues` lists the leagues; each `/leagues/[league]` renders its tabs with **real data**, verified
  **visually in a headless browser per league** (NBA/MLB/NHL/NFL/WC/UFC) — 200 ≠ done.
- WC Standings = knockout bracket/results (not stale groups).
- Schedule tab cards link through to the game-detail pages.
- Nav shows "Leagues"; `/stats` redirects; **no regression** to `/scores` or game detail.
- Tennis (ATP/WTA) handled gracefully (they have scores + set data but limited stats — show what
  exists, clean N/A for the rest; or omit from the hub index for now and note it).

## Hermes execution requirements (per the feature-dev workflow + AGENTS.md §10)
- Delegate via `scripts/hermes-worktree.sh up leagues-hub`; tear down with `down leagues-hub`.
- Spawn **executor + validator subagents for BOTH backend and frontend**. The **frontend validator
  MUST load each league's hub in a real headless browser and assert ZERO `pageerror`s + real data**
  (the game-detail task shipped a build that crashed on WC because the validator didn't actually
  render it — do not repeat that).
- **ESPN `/summary` & `/standings` fields are OBJECTS, not strings** (extract `.abbreviation`,
  `.displayValue`, etc. before rendering — AGENTS.md §10). Parse defensively.
- Dev DB only; don't commit `__pycache__`/`venv` (targeted `git add`). Don't regress existing pages.
- I verify the result myself (load each league's hub + the WC knockout standings) **before merging**
  to `analytics-backbone`.
