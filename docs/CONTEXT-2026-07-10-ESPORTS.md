# Context — 2026-07-10 — esports refactor, desktop UX, and v0.3.0

This is Codex's end-of-session context. Claude should append its work in the marked section at the
bottom rather than rewriting the verified history here.

## Repository snapshot when this file was written

- Repository: `/root/legendarypicks`
- Branch: `dev`
- Local HEAD: `be81737` — `feat(esports): show a "building the board" state during cold rebuild`
- `origin/dev`: `9e2110f` — `fix(deploy): pass esports source keys into the prod backend container`
- Release tag: annotated `v0.3.0` points to `a6a097f`
- GitHub Release: https://github.com/micahp/legendarypicks/releases/tag/v0.3.0
- The production deploy was **not** run by Codex. Claude reported that it completed the deploy while
  Codex was rate-limited. Codex explicitly stopped and did not redeploy after that report.

Current intentional uncommitted changes:

- `pages/esports.tsx`
- `docs/ESPORTS-EXPECTED-BEHAVIOR.md`

Those two files remove desktop Show-preview/Hide-preview behavior while retaining mobile inline
`watch here`. They still need to be committed and pushed by the next agent. All other untracked files
shown by `git status` predate this final adjustment or belong to the user; do not sweep them into a
commit.

## Codex work completed today

### 1. Session recovery and result-gap investigation

- Recovered the interrupted esports-results work and wrote
  `docs/HANDOFF-2026-07-09-ESPORTS.md` with exact code state, verification commands, and next tasks.
- Audited the four remaining result offenders against PandaScore coverage:
  - Prestige Esports/Västerås was a fixture-scoped Prestige Academy naming mismatch.
  - LEO/Prestige was a ~51-hour reschedule requiring stable PandaScore-id reconciliation.
  - Arch/Virtus.pro and Metanoia/Bounty Hunters were real RES Fall **2026 open qualifiers**, absent
    from PandaScore; adding a qualifier-results source remained explicitly deferred.
- Confirmed the four were not PandaScore-pagination failures.
- Earlier result fixes landed in `d465094` and `0137514`: minor-league/EWC result recovery, narrow
  aliases, per-side PandaScore matching, and scoped LP/largadosypelados deduplication.

### 2. Hermes retrospective review

- Read the complete Hermes tmux retrospective and checked its claims against current Git/API state.
- Verified its 70-commit metrics, but found the conclusion stale:
  - the 28 flipped crests had already been fixed by `01ffa3c`;
  - normal/swapped logo assertions already existed;
  - the real remaining test gap was stored-row repair, not basic PandaScore orientation;
  - the LEO/Prestige duplicate was still real in the live API;
  - `ESPORTS-EXPECTED-BEHAVIOR.md` still described the crest bug as deferred and was corrected later.

### 3. Cut `slate.py` in half

Commit: `2054e1e refactor(esports): split slate and improve live viewing`

- Reduced `backend/routers/esports/slate.py` from **1,222 to 582 lines** (52.4% smaller).
- Kept `slate.py` as the route, stale-while-revalidate cache, and rebuild orchestrator.
- Extracted cohesive ownership:
  - `match_identity.py` — team identity, metadata normalization, stored-crest repair.
  - `slate_sources.py` — Bovada parsing and GRID/Kalshi/frag/PandaScore stream adapters.
  - `slate_state.py` — carry rules, fixture clustering, result predicates, state derivation.
- Rewired `matcher_assertions.py` to test the owning modules directly.
- Repaired `zombie_fix_assertions.py`, which had been unusable because it imported deleted
  `slate.candidate.py`; it now tests `slate_state.py`.
- Updated `docs/ESPORTS-EXPECTED-BEHAVIOR.md` with module ownership and corrected stale behavior notes.

Behavior preservation evidence:

- 45/45 matcher assertions passed.
- 14/14 zombie-state assertions passed.
- Extracted pure behavior matched the pre-refactor implementation for identity, metadata, carry,
  clustering, state transitions, GRID lookup, and Bovada parsing.
- Controlled old/new live rebuilds produced identical core output and identical persisted results
  stores when the shared asynchronous broadcast cache was neutralized.
- Isolated real endpoint rebuild returned 294 matches, two honest `ended_unknown` results, and zero
  LMap contamination.

### 4. Desktop live-player UX

Included in `2054e1e`, with the final preview-removal adjustment still uncommitted.

- Selecting an Also-live match at desktop width promotes it into the full-width hero.
- The displaced hero returns to its unchanged prominence-ranked grid position.
- Selection is stable across polling through `psId`-first match keys.
- MSI participates in the same exchange:
  - MSI is the default marquee hero while live.
  - Selecting another match moves MSI into the first compact Also-live slot.
  - Selecting compact MSI restores the rich MSI hero.
- The hero scrolls into view after a desktop selection.
- Grid keys are stable match keys rather than array indexes, preventing component state leakage when
  ranking/order changes.
- The MSI Live game-state panel defaults **below** the full-width broadcast.
- An icon in the game-state header toggles between bottom-panel and 340px right-rail layouts.
- The explicit game-state layout choice persists in local storage.
- Responsive behavior after the final uncommitted adjustment:
  - Desktop (`sm` and wider): only `watch in featured player`; no inline preview control/player.
  - Mobile: retains `watch here` / `hide stream` inline playback.
  - Compact MSI follows the same responsive rule.

Final browser checks for the uncommitted responsive adjustment:

- Desktop: 6 visible Feature actions, 0 visible Watch actions, 0 preview labels, 0 grid iframes.
- Mobile: `watch here` visible, 0 visible Feature actions.
- `git diff --check` passed.

### 5. Blank tunnel incident and recovery

- Codex ran `npm run build` while the long-running `next dev` process used the same `.next` directory.
- That invalidated development artifacts: `/esports` returned HTML, but `main.js` and `_app.js`
  returned 404; Next's anti-FOUC `body{display:none}` therefore made the tunnel appear blank.
- Codex diagnosed the exact missing chunks, restarted the `:3095` Next dev process, and verified the
  page plus all required chunks returned 200 again.
- Operational lesson: stop `next dev` before `next build`, or isolate their build directories.

### 6. v0.3.0 release artifacts

- `a6a097f chore(release): 0.3.0`
- Updated `CHANGELOG.md` from the old roadmap block to actual shipped `0.3.0` release notes.
- Updated tracked `package.json` to `0.3.0`.
- `package-lock.json` is intentionally ignored by repository policy; its host copy was locally synced
  to `0.3.0` for Docker's `npm ci`, but it was not newly force-added as a large tracked file.
- Final production Next build passed at the tagged release commit.
- Pushed `dev`, created and pushed annotated tag `v0.3.0`, and published the GitHub Release with
  curated changelog-based notes.

Important release-provenance note: Claude subsequently added post-tag work. Production may therefore
contain commits that are not reachable from `v0.3.0`; Claude should document the exact deployed SHA
and decide whether a patch tag/release is needed.

### 7. Production database migration performed by Codex

Codex completed the runbook's database gate before its Docker access was rate-limited.

- The runbook's original one-shot migration was not rerun blindly because prod already contained
  117,585 logs and its plain `INSERT` would encounter uniqueness conflicts.
- Codex used an out-of-tree incremental migration at `/tmp/migrate_logs_incremental.py` with the same
  player-schema and identity-mismatch guards, null-safe business-key deduplication, and a pre-write
  backup.
- Five identity-mismatched shared player IDs were excluded.
- `player_game_logs`: **117,585 → 122,634** (+5,049).
- Re-derived prod player stats:
  - NBA 2026: 575 player rows processed.
  - NFL 2025: 605 player rows processed.
  - NHL 2025-26: 842 player rows processed.
- NBA opponent/home-away coverage was complete, so the optional NBA backfill was not run.
- Backup created:
  `backend/data/picks.db.bak-premigrate-20260710-032413` (about 59 MB).

Protected-table verification was exact before/after migration:

| Table | Rows | SHA-3 |
|---|---:|---|
| `props` | 90,205 | `ef6ca419da6a0daa53d32b13feccedd19ba34819ea8f627d29e8afe9` |
| `prop_results` | 81,212 | `50f882d1bb3c3f39fa7e6eeece54dec7e5fdae76521f60fc21fea090` |
| `prop_games` | 304 | `4dd8242bf63052cf23e3308efffec8070d35d35cf80bd16abfef658e` |
| `prop_odds_snapshots` | unchanged | `0168aaf8f752c1fb23aabf86afdc36f572bb641a6e7d3a51c946f538` |

The backup above is the database rollback point associated with this promotion.

## Known open or deferred items

- The final desktop-preview removal is uncommitted in the two files listed at the top.
- Local `be81737` was one commit ahead of `origin/dev` when this summary was written; Claude should
  reconcile/push and update this snapshot.
- `LEO v Prestige Academy` previously emitted a Bovada and PandaScore twin with the same `psId`; the
  stable-id clustering policy exists, but this exact live duplicate should be rechecked after the
  current match ages out/reappears.
- The two RES 2026 open-qualifier results remain without a sanctioned result source. Do not invent
  results or integrate DRAFT5/Liquipedia scraping without explicit approval.
- `resultUnknown` still needs a clear frontend “result unavailable” label if not already addressed
  by Claude's later work.
- Do **not** rerun the v0.3.0 Docker deployment merely from this file; Claude reported production is
  already deployed and healthy.

## Claude work — appended 2026-07-10 (deploy + esports fixes)

### Esports commits I landed this session
In `v0.3.0` (before tag `a6a097f`):
- `fe02dc0 fix(esports): single-flight the cold-cache rebuild path` — the outage fix. The cold path
  of `/api/esports/upcoming` (empty cache) called `_rebuild_upcoming()` inline with NO single-flight
  lock, so a burst of first requests each launched a full rebuild; under the GIL they thrashed the
  PandaScore canon index → 100% CPU, cache never warms, endpoint hangs. Now cold callers kick off one
  background rebuild and return `{"matches":[],"building":true}` immediately (same single-flight as the
  warm path). This is what Codex's refactor preserved in `slate.py:esports_upcoming`.
- `cc4c9f2 feat(esports): promote a scheduled match to live when its broadcast is on-air` — minor-
  circuit blind spot where no data feed flips a past-start match to running but its Twitch is live. A
  confirmed-on-air official channel now promotes state→live. Done OFF the rebuild path: liveness is
  cache-only + a background ThreadPool refresh (`streams._channel_online_cached`, mirrors the YouTube
  resolver). An inline sync probe here was what hung the first attempt; do not reintroduce it.
- `72787f8 feat(esports): trim redundant live indicators` — dropped the right-aligned "esports" meta
  on the Live-now header and the "● playing now" label on the featured/hero card.

Post-tag on `dev` (AFTER `v0.3.0`):
- `9e2110f fix(deploy): pass esports source keys into the prod backend container` — **IN PRODUCTION**.
- `be81737 feat(esports): show a "building the board" state during cold rebuild` — a `BoardBuilding`
  skeleton (match-row geometry, red signal-pulse eyebrow) shown while `building:true`; replaces the
  misleading "No matches" during the ~30-40s cold warm. **NOT yet in production** (committed after the
  deploy). Screenshot-verified in the dev tunnel.

### v0.3.0 production deployment (I ran it; Codex was rate-limited)
- **Deployed commit:** `dev @ 9e2110f` (working tree was clean at 9e2110f when I ran the build).
  Therefore production = `v0.3.0` (a6a097f) **+ 9e2110f**, and does **NOT** contain `be81737`.
- **Deployed images (current `:latest`):**
  - backend `legendarypicks-backend:latest` = `7d8c60656cb7` (built 2026-07-10 03:31)
  - frontend `legendarypicks-frontend:latest` = `54c969fdcc4b` (built 2026-07-10 03:35)
- **Container/env change:** `docker-compose.yml` backend `environment` now forwards
  `PANDASCORE_API_KEY` / `GRID_API_KEY` / `YOUTUBE_API_KEY` (host-shell pass-through like DEEPSEEK).
  Deploy MUST `source /root/.hermes/.env` first. Without this the esports board silently degrades —
  this was the exact blocker Codex flagged before its Docker access was cut. Compose validated, all
  four keys resolved.
- **Deploy command run:** `docker compose up -d --build` with the four keys sourced. Both containers
  rebuilt + recreated (brief restart). Ports unchanged: backend `127.0.0.1:8100→8000`, frontend
  `127.0.0.1:3100→3000`, behind host nginx.

### Production verification
- Backend started clean (no traceback; "Application startup complete").
- `127.0.0.1:8100/api/esports/upcoming` warmed to **295 matches** at deploy time (308 at time of
  writing) — keys working, board NOT degraded.
- `127.0.0.1:3100/esports` → 200; public `https://legendarypicks.xyz/esports` → **200** (first time
  esports is live on the public site).

### Rollback (both prepared before deploy)
- Images: `legendarypicks-backend:rollback-pre-v0.3.0` (`2b1beab361e9`),
  `legendarypicks-frontend:rollback-pre-v0.3.0` (`4ccfeb817297`) — the pre-v0.3.0 running images.
  To roll back: retag each `rollback-*` → `:latest`, then `docker compose up -d` (no `--build`).
- DB: `backend/data/picks.db.bak-premigrate-20260710-032413` (59 MB, Codex's pre-migration backup).

### Remaining follow-ups
- **Release provenance (Codex's concern, confirmed real):** prod = `v0.3.0 + 9e2110f`, not a clean
  tag; and `be81737` (loading indicator) + the uncommitted desktop-preview removal are on `dev` but
  NOT deployed. **Plan agreed with the user: cut `v0.3.1` = `dev` HEAD (compose fix + loading
  indicator + desktop Show-preview removal) and redeploy so prod == `v0.3.1` exactly.** The
  preview-removal commit + v0.3.1 release + redeploy are the open work; redeploy needs explicit user
  go (another brief prod restart).
- The pkill/port trap: prod backend container's uvicorn runs on `--port 8000` and shows in host
  `pgrep` as `uvicorn sports_service:app --host 0.0.0.0 --port 8000` (restart:unless-stopped revives
  it). A broad `pkill -f "uvicorn sports_service"` hits BOTH prod and the dev `:8095` backend — always
  scope to `--port 8095` for dev. (Cost me real time this session.)
- Deploy mechanism saved to Claude memory `reference_lp_prod_deploy.md`; full session handoff at
  `/root/legendarypicks/docs/CONTEXT-2026-07-10.md`.
