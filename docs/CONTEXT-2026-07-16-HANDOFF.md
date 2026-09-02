# CONTEXT HANDOFF — 2026-07-16 (design experiments, Class-A dupe fix, Kalshi + CoD specs)

Read first on a fresh context. Supersedes CONTEXT-2026-07-15-HANDOFF-2.md (that session = WC booth /
The Read / discount play; still valid background). This session = design experiments + a shipped
board fix + two specs.

---
## RUNNING STATE (verify before trusting)
- **legendarypicks dev HEAD = `9933394`** (branch `dev`), pushed to `origin/dev`. Clean except
  pre-existing untracked debris + the NEW uncommitted CoD spec (see below).
- **Preview** = worktree `/root/lp-pick-desk`, FF'd to `9933394`. Backend `:8096` (relaunched WITH
  full keys — GRID/PANDASCORE/YOUTUBE/DEEPSEEK, `LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db`),
  frontend `:3096`. **Prod `:3100`/`:8100` untouched.**
- **Dev tunnel URL = https://entertainment-bailey-types-switches.trycloudflare.com** (had DIED this
  session; restarted cloudflared → this NEW url; verified /, /esports, /predict = 200, API = 207
  matches live). ⚠️ trycloudflare quick-tunnels mint a NEW hostname every restart — old links are dead.
  User may want a NAMED tunnel for stability (offered, not done).

---
## SHIPPED THIS SESSION

### 1. Class-A display-dupe suppressor (committed `a86f893`, pushed, LIVE on preview)
- **Problem the user raised:** team-name casing dupes on the live board (`PARIVISION` vs `Parivision`).
  Checked the logs: `esports-state-ANOMALIES.log` fires `POSSIBLE_DUPLICATE` **471×**; dupes persist
  **10 min–1 hr** (recur every 5-min rebuild), NOT a flash. Two classes:
  - **A — pure casing/spacing/punct twins at the SAME start time** (`TheBoys`/`The Boys`,
    `JUMBO TEAM`/`Jumbo Team`) → safe to collapse.
  - **B — same names, different start times** (rematch risk) OR name-variant (`9z` vs `9Z Globant`,
    extra token) → deliberately LEFT logged-not-merged (near_ms guard is load-bearing).
- **Fix:** `_suppress_display_dupes()` in `backend/routers/esports/slate_state.py`, called in
  `slate.py` right before the `out_matches` loop. Keys on `_strip_name` (case/space/punct/accent
  ONLY — not `_canon_team`'s generic/alias collapse) for BOTH sides + start times within
  `_START_SLACK_MS` (15min). Keeps most-informative twin (has-result > live > scheduled > origin
  prio); surviving `matchKey` untouched so picks/crowd continuity holds.
- **Verified:** 6/6 unit cases on real dup shapes + **18/18 `matcher_assertions`** + clean compile/import
  + **live board audit = 0 residual Class-A dupes / 196 matches**. Rolled onto preview.
- **Parked (separate polish, NOT this fix):** a *lone* all-caps org with no twin (e.g. PARIVISION
  when it's the only spelling) is still shown as-is. A "preferred-display casing override" (canonical
  id → curated spelling) for the few shouting orgs is the follow-up. Do NOT blanket-lowercase (breaks
  FaZe/Virtus.pro/NAVI/G2).

### 2. Kalshi integration doc (committed `9933394`, pushed) — `docs/KALSHI-INTEGRATION-2026-07-16.md`
- User asked what "embed Kalshi liquidity" is. Researched (web): Kalshi is productizing **embedded
  trading** (moomoo, Tradeweb partners). **3 tiers:** (1) free API/data → **display** the live Kalshi
  contract + deep-link out, no permission, buildable NOW; (2) own-account trading (doesn't scale to
  users); (3) **embedded trade-for-users = CFTC Introducing-Broker registration + NFA membership** —
  a licensing project, not code. Rev-share NOT public (contact institutional@kalshi.com).
- **Product framing locked:** LP stays free **picks + lineup, no book, no securities** (the legal
  moat). "LP does the picks; Kalshi does the money." Tier-1 display+deep-link is the buildable-now,
  fits-everything version. Tier-3 is a deliberate business decision, gated behind broker licensing.

---
## SPECS WRITTEN (design deliverables)

### 3. CoD spec — `docs/SPEC-add-call-of-duty-2026-07-16.md` ⚠️ **UNCOMMITTED** (on /root/legendarypicks dev)
- **Add Call of Duty (CDL) to /esports.** RECON DONE LIVE, de-risked to a 3–4 file WIRING job:
  - Bovada lists `call-of-duty/cdl-championship` **RIGHT NOW** (Championship is on) → schedule+odds+live
    flow once slug added to `_ESPORTS_TITLES`.
  - PandaScore covers CoD via game slug **`cod-mw`** → same enrich as CS2/Dota (scores/winner/logos).
  - `league_tier.py` ALREADY reserves CDL at Tier 0. Picks come FREE (flows via `/api/esports/upcoming`
    → /predict + board). Closes the loop w/ ESPORTS-PRODUCT-DIRECTION (CoD desk = the model).
  - Changes: `common.py` (register title), `pandascore.py` (`cod-mw` in `_PS_VG_TITLE`+`_PS_TITLES`),
    `league_tier.py` (map "Cdl Championship"/CDL → Tier 0), `streams.py` (official CDL YouTube channel).
  - Watch-item: CDL team-name spellings (Bovada vs PS) → harvest aliases from live board, run
    matcher_assertions. GRID has no CoD (fine).
- **3 open decisions for user:** (1) display title "Call of Duty" (rec) vs "CoD"; (2) which official
  CDL YouTube channel; (3) ship P1 vs live Championship NOW (timely) vs wait for regular season.
- **NEXT:** commit/push the spec if wanted; implement P1 (small, timely).

---
## DESIGN EXPERIMENTS (this session's exploration — mostly for direction, not shipped)
- **Folder-tab redesign** (game-detail tabs looked "too stock AI"): built a "scout's DOSSIER" folder-tab
  artifact w/ angled + then basic (squared) folder tabs. **User SCRAPPED the folder-tab idea** (didn't
  like the angle; "more basic folder" then "scrap it"). **KEEPER:** user liked the **case-file HEADER**
  styling — `CASE · 760515 — GROUP F` mono eyebrow + clean score line + `FULL TIME` pill. Worth adopting
  on the WC/game-detail header. (Artifacts were throwaway; palette = ink neutrals + brand emerald
  `#22c55e`/neon `#84ff00`/punch `#ff3d71` from tailwind.config.js.)
- **Esports picks-on-the-board mockup** (per `docs/SPEC-esports-board-picks-2026-07-15.md` + product
  direction): showed pick surface in 3 states (live-locked / unpicked / contrarian-picked) w/ you-vs-
  desk-vs-crowd header. **User REJECTED the multiplier/odds framing** ("we're not doing betting, it's
  just picks + your lineup"). So: keep the contrarian idea as **record/streak flavor only, NO odds
  numbers** (`2.4×` etc. are OUT). This is the still-unbuilt SPEC — build minus the multipliers.

---
## OPEN THREADS / NEXT CANDIDATES
1. **CoD P1** — implement (small, Championship live NOW). Needs the 3 user decisions above.
2. **Esports picks on the board** — build SPEC-esports-board-picks Phase 1 (extract `<MatchPick>` +
   `useEsportsPicks()`, render on featured LiveCard display-only). NO multiplier framing.
3. **Case-file header** — adopt the liked `CASE · … / FULL TIME` header treatment on game detail.
4. **Kalshi Tier-1** — display live Kalshi contract + deep-link on a matching pick (free, no partner).
5. **Preferred-display casing override** — lone all-caps org polish (parked).
6. **Named cloudflare tunnel** for a stable preview URL (offered).
7. Rotate PandaScore/YouTube/GRID keys (leaked+scrubbed last session; still recommended).

## GOTCHAS reconfirmed this session
- Restart the `:8096` preview backend by **PID/port, never broad `pkill -f uvicorn`** (hits prod :8000).
  It was running DEGRADED (only DEEPSEEK key) — relaunch sources `/root/.hermes/.env` for all keys.
- Cold `/api/esports/upcoming` returns `building:true` instantly (single-flight async rebuild); poll
  with real waits (python `time.sleep`, NOT the blocked foreground `sleep` binary).
- Board dedup is per-rebuild deterministic; the monitor (`monitor_esports_state.py`) DETECTS dupes but
  logs-not-merges — the new suppressor is the render-time resolver for Class A only.
