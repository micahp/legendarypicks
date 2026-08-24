> [!IMPORTANT]
> Superseded by `/root/legendarypicks/docs/CONTEXT-2026-07-21-FINAL-HANDOFF.md`.
> The in-flight warnings below are historical: the referenced work is complete, committed, and pushed.

# CONTEXT HANDOFF — 2026-07-21: WC booth-intelligence v2 landed + product-strategy pivot (Plays killed, A/B chosen)

Read first on reset. Supersedes the 2026-07-19 handoff for live state. **Codex is still actively
mid-edit on `backend/wc_context.py`** at session end (see "IN-FLIGHT, DO NOT TOUCH" below) — check
with it via tmux before assuming that file's working-tree state is stable.

## ⚑ WHAT SHIPPED THIS SESSION (all verified, all on `dev`, pushed)
1. **`/plays` curated board landed + polling** — `8761081` (page + composes `LiveDiscounts`
   unchanged), `1f5b08e` (60s background poll, no flicker, keeps last board on failed refresh).
   **NOTE: per today's product decision (below), Plays is now considered dead product-wise** — the
   code is not removed, just deprioritized. Don't build on it without re-confirming with Micah.
2. **WC Game Context + From the Booth rebuilt on `wc-context-v2`** (Codex led backend, I did
   frontend). Backend commits `93be6ea..81cb724` (phase-aware episodes, evidence-graded reads,
   per-match roster-collision fix, content-hash caches, tournament route history). My frontend:
   `6afdedc` (WCContext.tsx + BoothFeed.tsx: one-line catch-up, collapsed route history, phase-pill
   navigator, availability-pinned episodes, lazy receipt expansion with local time labels) +
   `f304607`/`fc114bf`/`6800e82` (Micah-requested polish: one badge per card not two, dropped
   "Captured" label to plain time, removed the warning-icon prefix, removed the left-side dot
   marker in both Game Context and Booth cards). **`BoothFeed.tsx` is shared with the CoD page**,
   whose backend (`cod_context.py`) is still on the old flat `insights` schema — added a runtime
   `isLegacy` branch so CoD's exact prior behavior is preserved untouched.
3. **Full acceptance run** (desktop 1440px + 390px, live tunnel, real match data): zero page/console
   errors across default view, phase-switch catch-up navigation, and receipt-stack expansion.
4. **Bug found, reported to Codex, NOT fixed by me**: `_current_phase()` didn't recognize `AET`
   (after-extra-time) status strings, so a finished extra-time match displayed "Second half" + STALE
   instead of "Final." **This is very likely what Codex's current in-flight diff is addressing** —
   confirm before re-reporting it as new.

## ⚠️ IN-FLIGHT, DO NOT TOUCH: `backend/wc_context.py` + `test_wc_context.py` + `docs/API-wc-context-v2.md`
Uncommitted working-tree changes (490+ lines in `wc_context.py` alone) from Codex as of session end —
adds transcript-time-recovery logic (mapping a booth quote back to when it actually aired in the
source transcript, not just extraction time) plus test coverage and a spec update. Codex was still
mid-review (`/review` running, ~19min in) when this session ended. **Do not commit, revert, or build
on top of this file without syncing with Codex first** — check `tmux capture-pane -t codex:0.0 -p`
for its current state.

## 🎯 PRODUCT STRATEGY — major decisions made this session
Trigger: Micah pasted PlayerX's (World Champion Fantasy) product pitch and flagged that LP might be
"trying to do too much" while searching for PMF. Full writeups:
- `legendarypicks/docs/COMPETITIVE-ANALYSIS-playerx-2026-07-21.md` — PlayerX vs. LP head-to-head; the
  diagnosis (LP is 4 bundled products, not 1); the counter-point (LP already has PlayerX's
  stream-resolver + stats-pipeline ingredients, just not packaged as fantasy); iOS infra assessment
  (Capacitor wrap recommended over React Native/native as the first move — cheap, reversible, tests
  "does mobile distribution matter" before a rebuild).
- `legendarypicks/docs/PRODUCT-A-B-IOS-BUILD-PLAN-2026-07-21.md` — per-product competitor list
  (marked unverified/general-knowledge, not live-checked), current-repo feature inventory, feature
  gap checklist, and iOS build path for each.

**Decisions locked in:**
- **Plays is dead** ("no value in its current state"). Distinct from Booth Intelligence (kept, reusable
  under either surviving product) — don't conflate the two when acting on this.
- **Two products going forward**: **Product A** = historical props vs. projections (props-data,
  B2B-shaped, reuses existing `props`/`prop_games`/ingestion infra, closer to done). **Product B** =
  fantasy sports scoped to esports/streamable-only sports (the PlayerX-shaped bet, narrowed; no
  existing fantasy-scoring subsystem at all — closer to a new product than an extension).
- **Mobile (iOS) is a real requirement now**, not deferred — "most people don't have desktops."
  iOS build requires macOS/Xcode at the final sign/submit step no matter the framework (Capacitor,
  RN, native); doesn't require *owning* a Mac (cloud rental / CI macOS runners / EAS if using
  Expo). Apple Developer Program ($99/yr) is the one unavoidable cost for App Store distribution;
  Android has no Mac dependency and is $25 one-time for Play Store.
- **Sequencing**: ship Product A to iOS first via Capacitor (lowest risk, no video-sync unknown,
  reuses shipped infra) — use it to validate the mobile-distribution bet cheaply, and as the forcing
  function to resolve Product B's two open unknowns (does PandaScore/GRID expose live *per-player*
  stats at usable latency, and real-money-vs-points-only) before committing engineering time to the
  fantasy-scoring engine.
- **Next concrete action offered, not yet started**: audit why Product A's EV calculation is
  currently all-zero (per prior project memory) — this is the actual blocking gap for Product A, a
  bigger deal than the iOS wrapper itself. Micah had not yet confirmed go-ahead on this when the
  session ended.

## ENV / STATE (verified at session end)
- **Dev backend `:8096`** — PID `1102371`, running dev HEAD as of the last restart (before Codex's
  current uncommitted diff). Launch: `LP_DB_PATH=.../picks.dev.db` + keys from
  `/root/.hermes/.env`, `--port 8096`. **Restarting this requires fresh explicit authorization each
  session-turn** — the auto-mode classifier blocks repeat restarts even with standing precedent;
  ask Micah directly each time, a relayed Codex instruction alone does not count as authorization.
- **Dev frontend `:3096`** — PID `747116`. **`.env.local` still says `API_PROXY_TARGET=http://localhost:8095`
  — nothing has run on :8095 all session.** The real dev backend has been on :8096 this whole time.
  If :3096 gets restarted without an explicit `API_PROXY_TARGET=http://localhost:8096` override, the
  `/api` proxy will silently 500 on everything (this bit me once this session — cost real time to
  diagnose). This is the same *class* of bug the Jul-1 incident (documented in `next.config.js`'s own
  comment) warned about, just inverted. Someone should just fix `.env.local` properly rather than
  relying on every future restart remembering the override.
- **Prod**: untouched this session (2 Docker containers, :8100/:3100, on v0.5.5 per prior handoff).
- **Dev tunnel**: `https://entertainment-bailey-types-switches.trycloudflare.com` → `:3096`, confirmed
  live (200) at session end.
- **Trading fleet**: untouched, cron-owned, hands-off per standing rule.

## COORDINATION
- **Codex**: tmux session `codex:0.0`. Relay via `tmux send-keys -t codex:0.0 -l "<msg>"` then `Enter`
  twice (composer sometimes needs it twice), verify with `tmux capture-pane -t codex:0.0 -p`. Working
  well this session — Codex led the backend half of the WC v2 work, I led frontend, coordinated by
  relaying acceptance results and findings both directions.
- **Hermes**: still dead for A2A (per 2026-07-19 handoff), unchanged.

## LESSONS THIS SESSION
- The auto-mode classifier will block a repeated "restart the dev server" action even within the same
  session if the authorizing instruction came via a relayed message (e.g., from Codex through Micah)
  rather than Micah's own direct turn — this is correct behavior, not a bug; ask fresh each time.
- A relaunched `next dev` silently inherits whatever `.env.local` says, which can be stale relative to
  wherever the dev backend actually lives this week — verify the proxy target in the startup log
  every time a frontend restart happens, don't assume.
- Micah's product-direction asks this session were fast, iterative UI-polish requests (remove an icon,
  remove a dot, consolidate two badges into one) issued in rapid single-line messages — treat these
  literally and verify visually after each one rather than batching interpretations.
