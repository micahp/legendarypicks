# CONTEXT HANDOFF — 2026-07-16 (part 2): CoD shipped to prod (v0.4.0) + featured-stream saga PARKED

Read first on a fresh context. Supersedes CONTEXT-2026-07-16-HANDOFF.md (still valid background:
design experiments, Class-A dupe fix, Kalshi doc, CoD spec). This session = shipped CoD to prod,
cut v0.3.3/v0.3.4/v0.4.0, launched a CDL Champs Whisper listener, then went deep on a
"featured stream persists between games" board feature that hit a real backend-data wall and is PARKED.

---
## RUNNING STATE (verify before trusting)
- **PROD = v0.4.0, UNTOUCHED and healthy.** `legendarypicks.xyz/esports` shows CoD. 2 containers up
  (`legendarypicks-{backend,frontend}-1`, :8100/:3100). Do NOT redeploy without cause.
- **dev HEAD = `c0362de`** (branch `dev`, pushed). = CoD-on-board (`46e7984`) + v0.4.0 release commits
  + featured-stream **v1** (`274edbb`, BUGGY — see below) + CoD specs (`c0362de`).
- **Working tree: `pages/esports.tsx` is UNCOMMITTED** — the featured-stream **v2** refactor (better
  than v1 but still blocked by the data problem below). Parked. Decide whether to keep, revert, or
  finish once the backend id exists.
- **Preview** = worktree `/root/lp-pick-desk`, `next dev` on :3096 (HMR), proxying to main-repo backend
  :8096. **Preview esports.tsx was REVERTED to the clean pre-feature board** (copied `4f29b2b`'s
  version in) so nothing half-baked shows. The worktree is NOT a git checkout of dev — I edit
  `/root/legendarypicks` and `cp` the file into the worktree (safe under the running dev server; never
  git-checkout under it). Tunnel was `https://ion-christ-florence-framing.trycloudflare.com` → :3096
  (trycloudflare URL rotates on restart; re-check).
- Tags pushed: **v0.3.3** (`1fbdfd6`, Leagues Hub + Pick Desk), **v0.3.4** (`9933394`, WC intelligence
  + Class-A dupe), **v0.4.0** (`4f29b2b`, rollup milestone + CoD). Prod-deploy safety net:
  `backend/data/picks.db.bak-premigrate-v0.4.0`, rollback images `*:rollback-pre-v0.4.0`.

---
## SHIPPED THIS SESSION
1. **CoD (CDL) on /esports — P1 LIVE ON PROD.** `46e7984`: registered "Call of Duty" title, PandaScore
   `codmw` per-title enrich (NB: match-endpoint alias is `codmw`, videogame slug is `cod-mw` — the
   spec's `/cod-mw/matches` 404s), Tier-0 (excl. Challengers), CoD-Champs-as-flagship stage, official
   CDL YouTube channel `UCbLIqv9Puhyp9_ZjVtfOy7w` (@CODLeague; decoy @CallofDutyLeague 76-subs = do
   NOT use). Verified live: 4 Champs matches, odds, YT embed, 18/18 matcher_assertions.
2. **Versioning caught up + v0.4.0 to prod.** Per-feature 0.3.x tags + v0.4.0 rollup; CHANGELOG +
   package.json=0.4.0. Guarded deploy (DB backup + rollback tags + `docker compose up -d --build` with
   keys sourced from /root/.hermes/.env). All pages 200, keys hydrated.
3. **CDL Champs Whisper listener LIVE.** `20260716_CDL_CHAMPS` capturing `twitch.tv/callofduty`
   (PandaScore `official=True,main=True`; the @CODLeague YouTube is BOT-WALLED from this datacenter box
   — use Twitch for CoD audio). ~450 signals. **The booth CAUGHT the Riyadh roster change live**
   ("let go of one, welcoming a rookie… filling Pred's shoes… everybody's writing these guys off") —
   the exact intel that repriced Falcons ~7%→~50%. This is the product receipt. See
   `reference_broadcast_watcher_launch` memory (updated with the CoD/Twitch launch one-liner).
4. **Specs** (`c0362de`): `docs/SPEC-cod-league-page-2026-07-16.md`, `docs/SPEC-cod-game-detail-2026-07-16.md`.

---
## ⚠️ THE FEATURED-STREAM FEATURE — PARKED, and WHY (the key learning)
**Goal (user's, refined over many turns):** on /esports, when a game on a broadcast ends, the featured
player should NOT cut — show **FINAL** in place, keep the **same stream** playing, show **Up Next** (the
next game on that stream) with a countdown; when the next game starts the countdown goes away. The slot
should **ride the marquee STREAM** through its games+gaps (a Tier-0 CoD Champs broadcast holds the slot
even while a lesser match is live elsewhere — that one stays in the grid). Must work on the MIXED board
(user explicitly rejected punting it to a CoD-only page). "It's simple" — conceptually yes.

**Correct data model (user taught me this, it's right):** a "stream" = games sharing the same stream
LINK **and** the same EVENT, running **sequentially** (one game at a time; concurrent same-link = not
one stream). Multi-arena = same event, two links = two streams (stay separate). streamKey =
`yt:<videoid>` / `twitch:<channel>`.

**WHY IT'S BLOCKED (a backend-data problem, NOT frontend):**
- A **finished** match's `watch` degrades to a bare web link (`@CODLeague/live`) → it **loses its
  stream key**, so you can't tell which stream the just-ended game was on from the finished row alone.
- The **league string is not stable across a match's life**: scheduled = `"Cdl Championship"` (Bovada),
  once finished = `"Call of Duty League — Championship 2026 (Playoffs)"` (PandaScore). So matching the
  finished game to its stream by event-string FAILS.
- Scheduled **start times are loose estimates** (a Champs series ran 87+ min; "next game" times are
  guesses) → a naive countdown showed a nonsensical **2h+** value (this is what the user angrily caught).
- Frontend workarounds tried: ref-based transition-hold (works ONLY while you watch the game end live,
  not on cold load), title-only fallback (unsafe — could grab a *Challengers* final). All patches on sand.

**THE FIX (do this FIRST if resuming): backend emits a STABLE per-match identity that survives
finishing** — a `streamKey` (from PandaScore `streams_list` raw_url, which persists on past matches)
and/or an `eventId` (PandaScore `serie.id`, also persists). Then the frontend groups by a stable id,
finds the just-ended game reliably, and the whole feature becomes simple + correct. `slate.py:302`
already has `ps_streams_by_id[m["id"]] = streams_list`; `serie` is on PS match objects. This is an
ADDITIVE output field — but slate.py is delicate (state machine), scope it carefully + assertions.

**v1 vs v2:** `274edbb` (committed, on dev) = event(title+league)-scoped, buggy (2h countdown, CoD lost
slot to live R6). Working-tree v2 = stream(link+event)-scoped, ref-based gap, countdown-only-in-gap,
marquee-holds-slot — better and verified-correct WHEN the ref is set (watching live), but cold-load
mid-gap can't recover the finished game (the data wall). If you revert, `git checkout pages/esports.tsx`
drops v2; consider `git revert 274edbb` to also pull v1 off dev (it's not on prod).

---
## PRODUCT DIRECTION (user's steer this session — capture it)
- **NOT a page per esports league** (doesn't scale). The user wants an **esports HUB** + the killer
  feature: **follow teams → get roster-change updates** (title-agnostic; `/esports` is already the hub
  skeleton). Roster changes are the alpha he missed (Riyadh dropped Pred → 7%→50%). The Whisper feed is
  a *source* for roster-change detection (it caught it on air) — the trade thread and the hub feature
  converge on roster intel.
- `/cod` page = first proof / desk template only, folds into the hub later.

## CODEX — building /cod, BLOCKED on 3 questions (answer to unblock)
Codex (tmux `codex:0.0`, cwd /root, scope-locked) correctly STOPPED and wrote
`docs/CODEX-QUESTIONS-cod-league.md` instead of guessing. It created NO files. Its 3 blockers (all
downstream of the SAME finished-match-loses-streamKey problem):
1. How should a **finished** CoD match (watch=web, streamKey null) appear in "Today on the stream"?
2. Minimum finished matches to show derived standings? (only 1 finished right now)
3. Exact `/predict` URL for the CoD CTA (predict.tsx has no CoD filter/anchor, and the task forbids
   editing it)?
→ Answer these (or fix the backend id first, which resolves #1) then tell Codex to resume.

## OPEN THREADS / NEXT CANDIDATES
1. **Backend stable event/stream id** (serie.id + streams raw_url per match) — unblocks BOTH the
   featured-stream feature AND Codex's /cod #1. Do this before more frontend work.
2. **Roster-change feed on the esports hub** (the real product ask) — extract from Whisper + confirm vs
   PandaScore rosters; title-agnostic; follow-teams. This is the thing the user actually wants.
3. Decide fate of featured-stream v1 (`274edbb` on dev)/v2 (working tree): finish-after-backend-id, or revert.
4. Answer Codex's 3 questions / re-scope /cod as a hub view.
5. Whisper/trade: mine the feed for the next mispriced team; grade the Champs upset calls (Zephyrani
   "Falcons 3-2" was live-correct).

## GOTCHAS
- CoD audio = **Twitch** (`twitch.tv/callofduty`), NOT YouTube (@CODLeague bot-walled from this box).
- Restart preview backend :8096 by PID/port, NEVER broad `pkill -f uvicorn` (hits prod :8000/:8100).
- Preview frontend = `next dev` in `/root/lp-pick-desk`; sync by `cp` the file, never git-checkout under it.
- PandaScore CoD: per-title feed path = `codmw` (no hyphen); videogame slug on match objects = `cod-mw`.
- tsc on esports.tsx: a pre-existing line-356 `downlevelIteration` warning is NOT yours (SWC build
  tolerates it); avoid `[...map.values()]` spread (use `Array.from`) to stay tsc-clean.
