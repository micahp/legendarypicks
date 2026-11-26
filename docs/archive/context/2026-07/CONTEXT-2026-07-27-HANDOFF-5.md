# LP handoff — 2026-07-27 pt.5 (supersedes pt.4)

**Work queue: `/root/legendarypicks/docs/ROADMAP.md`.** This file is session state and
decisions only.

**v0.6.10 shipped** — `176d584` on `origin/dev`, tag `v0.6.10` pushed via `scripts/release.sh`.

---

## 1. THE OPEN THREAD — pick this up first

**Micah wants the product position re-thought with three things in the frame at once:**

1. **sport.fun** — see `docs/SPORTFUN-ARTICLE-CORPUS-NARRATIVE-2026-07-13.md`, plus mentions
   in `CONTEXT-2026-06-27.md`, `PLAN-entity-ux-restructure.md`,
   `RECOMMENDATIONS-2026-07-13-LEAGUES-HUB.md`, `CONTEXT-2026-07-13-LEAGUES-STATS.md`,
   `KALSHI-INTEGRATION-2026-07-16.md`.
2. **PlayerX** — `docs/COMPETITIVE-ANALYSIS-playerx-2026-07-21.md`.
   ⚠ **This file is UNTRACKED in git.** Commit it before anything else or it can vanish.
3. **The regulatory doc** — he referred to "a doc that talks about regulatory stuff."
   Best match is `docs/ESPORTS-LEGALITY-PRESSURE-TEST.md`. Confirm that is the one he means
   before building on it; there may be another.

The trigger was the NFL All Day research (§4) landing on *"we are buying the mechanic, not
the audience"* — he found that framing interesting and wants it re-examined against those
competitors and the legal constraints. **Nothing has been written on this yet.** It is a
fresh analysis, not a continuation.

## 2. What shipped and what is decided

- **v0.6.10 — draft board name search.** Server-side `q` param narrowing in SQL (one player
  searched = one player returned), tokens match in any order (`ja gibbs` → Jahmyr Gibbs),
  LIKE wildcards escaped, 250ms debounce (verified: 1 request for a 4-char query), no-match
  state names the search it ran. 259 passed / 1 failed (pre-existing B5), no page overflow at
  1600px or 390px. Board search is labelled **"Search rankings"** to avoid colliding with the
  navbar's global "Search players…" which navigates to `/player/{id}`.
- **v0.7.0 scope locked**: slice A (draft notes → server, keyed by `device_id`) + slice D
  **single-player, ungated** (mock draft vs ADP bots, 12×15 snake, QB/RB/WR/TE/K + FLEX, no
  D/ST, no IDP) + R4 (NFL schedule through the API). **Prod deploy follows the cut.**
- **v0.8.0 scope**: accounts (magic link) + nudges + **multiplayer** mock draft, and the
  sign-up gate lands with them. Because D ships before B, **mock draft results must be saved
  against `device_id` on the server**, or claim-on-sign-in picks up notes but strands drafts.
- **Deadline: ~Aug 22.** Drafts run mid-Aug → Labor Day (Sept 5–7). A mock draft after that
  is a 2027 feature.
- Spec: `docs/SPEC-accounts-and-mock-draft.md`. "Notes" = rank/watch/fade, not free text.

## 3. B2/B3 resolved — nflverse publishes the ESPN id

The choice between "repull the schedule from ESPN" and "live with two key schemes" was a
false one. **`games.csv` carries an `espn` column, populated 285/285 for 2025**, and
`nfl_schedule` already stores it (285/285 for 2024). The bridge was being ingested all along.

Measured **with `league='nfl'` applied** — this matters, numeric ids in 2026 turned out to be
other leagues and made a season look broken that wasn't:

| season | keys | rows | joins `nfl_schedule`? |
|---|---|---|---|
| 2024 | nflverse | 570 | 285/285 |
| 2025 | **ESPN** | 544 | no — no 2025 rows exist there |
| 2026 | nflverse | 544 | yes |

**Only 2025 is broken.** Decision: nflverse stays canonical. Load 2025 into `nfl_schedule`
from `games.csv` (zero rows today, so no duplication), then **UPDATE — never INSERT** the 544
rows through the bridge; the same statement fixes B3's `LAR→LA`/`WSH→WAS`. R4 unblocked.

## 4. NFL All Day thread — Hermes is working it RIGHT NOW

**Origin**: Micah does not want to give up the fantasy-lineups thread, so we revived the
original Flow-blockchain idea — but against **NFL All Day** instead of NBA Top Shot.

**v1 scope (his, and it is deliberately tiny)**: a **Lineups** tab on `/leagues/nfl`. Paste a
Flow wallet address — **no sign-in, no wallet connect** — get the All Day Moments that address
owns, with each one resolved to **player name and position**. No lineups, no scoring, no
contests, no escrow.

**Research finding** (`docs/RESEARCH-nfl-allday-state-2026-07-27.md`): Dapper **halted primary
issuance 2026-05-13**; existing Moments stay tradeable and on-chain; new NFL licensing deal
signed with details due "as the season approaches." They already ship Playbook / One and Done
/ Pick'Em — but those are *rewards loops paying out in Moments*, not head-to-head fantasy.
**Market is tiny**: daily volume topped $10k only once ever, panic spike $53k, sellers
<100/week → 400. **Build for the mechanic, not the audience** — paste-an-identifier → roster →
lineup is the same flow for a wallet, Sleeper or ESPN, and All Day is the only source costing
no partner deal, no OAuth, no approval.

**Key technical facts:**
- **`@onflow/fcl` is NOT installed** and not in `package.json`. `cadence/`,
  `services/nbaTopShot.ts`, `config/fcl.ts` are **dead imports** and the source of most
  pre-existing tsc errors. Do not revive them.
- The chain read goes through **Flow's HTTP API from the Python backend**
  (`rest-mainnet.onflow.org`, verified 200 from this box) — next to the `players` table it
  must join against. No browser blockchain code.
- `nflallday.com` and `cryptoslam.io` **403 from this box** (datacenter-IP bot-wall).

**Hermes state as of handoff:** running in tmux session `hermes` (deepseek-v4-pro, **YOLO
on**), worktree `/root/lp-nfl-allday`, branch `feat/nfl-allday` off `dev`, servers **:3097 /
:8097**. It has created `backend/routers/nfl_allday.py`, `backend/test_nfl_allday.py`,
`components/Leagues/LineupsTab.tsx`, `components/Leagues/hooks/useAllDayCollection.ts` and
modified the four allowed files — **all in scope, nothing forbidden touched**. It reported
zero tsc errors in its files and was mid browser-verification against mainnet address
`0xa16b948ba2c9a858` when it **hit its 90-iteration budget**. It is idle at a prompt and needs
a nudge to finish verifying.

**Still unreported by Hermes**: the match rate (Moments resolved to our `players` spine), the
metadata fields it actually found, and the screenshot. `docs/FINDINGS-nfl-allday.md` was
specced and has not appeared yet. **Do not merge without those** — the whole task exists to
answer whether that join works.

Task spec: `docs/TASK-nfl-allday-lineups.md` (scope-locked; the "Do NOT touch" list is
load-bearing because YOLO is on).

## 5. Esports positioning settled

`docs/ESPORTS-POSITIONING-2026-07-27.md`. Research confirmed **no major esports tournament
carried live on US linear TV 2021–2026** (G4, Madden Bowl, X Games, BLAST, EWC Spotlight all
fail on inspection; last clean case is 2021 eNASCAR on FS1). So do **not** frame the product
around "esports on TV." Frame it as *every live competition you can legally watch right now,
whatever the platform* — the unified live data and discovery layer. One-liner:
**"Legendary Picks makes internet-native sports feel as trackable as an NBA game on ESPN."**
Esports remains **Layer 2**; this settles description, not timing.

## 6. Infrastructure fixed and still broken

- **FIXED — `scripts/hermes-worktree.sh` port collision.** It hardcoded `BPORT=8096` /
  `FPORT=3096`, *exactly* the main dev env's ports since O1 killed the 3095/8095 zombies. `up`
  would have bound over the live tunnel, or failed silently and left the agent verifying
  against the MAIN tree while believing it was isolated. Its own `down()` already documented
  the collision; only `up()` was never fixed. Now **3097/8097**, `LP_WT_BPORT`/`LP_WT_FPORT`
  overridable, default base branch `dev` instead of stale `analytics-backbone`.
- **STILL OPEN — O3.** `:8096` uvicorn `--reload` burns ~**147% CPU** across the supervisor
  (67%) and its forked worker (80%). Fix written, never run. Offered to Micah, not answered.
- **Box is tight**: 5.8GB total, **~1.7GB available with swap at 2.1/4.0GB** after starting
  the worktree servers. Do not start anything heavy without `.claude/skills/resource-check`.
- Stray: `/root/legendarypicks/picks.dev.db` is a **0-byte accident**; the real dev DB is
  `backend/data/picks.dev.db`. Leftover worktree `/root/lp-nfl-usage` on
  `feat/nfl-usage-renderer` may be stale.

## 7. State

- `origin/dev` = `176d584` + local commits through `cb27922`. **Local commits after the tag
  are NOT pushed.**
- Main dev: **:3096 → :8096**, tunnel
  `https://someone-decorative-wearing-produce.trycloudflare.com` (live, do not restart —
  restarting mints a new URL).
- Hermes worktree: `/root/lp-nfl-allday`, **:3097 → :8097**, both 200, verified by
  `/proc/PID/cwd` not by port.
- **Prod is on v0.6.7.** Deploy deferred to after v0.7.0 (R6).
- Codex out of quota until Aug 1.
- Untracked and unreviewed, carried from pt.4: `backend/run_wc_prop_history_ingest.py` + test,
  various `docs/TASK-*.md`, logs, **and `docs/COMPETITIVE-ANALYSIS-playerx-2026-07-21.md`
  which §1 needs.**

## 8. The lesson

pt.4's was *check whether the thing you were told is broken is actually broken.* Today's is
the inverse and it fired three times: **check whether the thing you are about to build is
already published, already bridged, or already shipped by someone else.** The B2/B3 decision
dissolved because nflverse publishes the ESPN id. The All Day lineup feature already exists as
Playbook. The worktree script's "isolated" ports were the live ones. In all three cases the
answer was in a column, a changelog or a comment that nobody had opened.
