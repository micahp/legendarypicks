# HANDOFF 2026-07-26 — GA4 instrumentation shipped, v0.6.5 cut, release process fixed

**Read this first.** Supersedes `CONTEXT-2026-07-25-HANDOFF.md` for analytics, versioning and the
NFL usage renderer. The 07-25 doc's strategic section (§1) is still the current product direction
and is **not** superseded — re-read it for the brand-is-the-spec reframe, the fantasy-football
focus and the acquisition thesis.

---

## 1. FIRST ACTION NEXT SESSION — deploy to prod

**Micah explicitly deferred this to next session.** Everything is committed and pushed; nothing is
live. GA is recording **nothing** until the frontend is rebuilt, because `NEXT_PUBLIC_*` is inlined
at build time.

```
cd /root/legendarypicks
docker compose build frontend && docker compose up -d frontend
```

No env var needed — `G-ZZKRW6MMMM` is defaulted in `docker-compose.yml`. Prod frontend is host
`127.0.0.1:3100` → container `3000`.

**Verify after deploy, do not assume.** The GA tag is injected `afterInteractive`, so it is **not
in the served HTML** — grepping curl output finds nothing and is a false negative. That cost me a
wrong conclusion this session. Use a real browser; the working harness is
`/tmp/.../scratchpad/ga.js` pattern, reproduced here:

- Playwright, `page.route('**googletagmanager.com/**')` to stub Google and capture the loader URL
- read `window.dataLayer` — expect `js`, `config` (with `send_page_view:false`), then one
  `page_view`
- click a nav link, confirm **exactly one additional** `page_view` (duplicates = the enhanced
  measurement toggle came back on)

## 2. What shipped (all pushed to `origin/dev`, tag `v0.6.5`)

```
5378a3c chore: add scripts/release.sh to cut releases atomically
c5742f4 chore(release): v0.6.5
8f67918 feat(analytics): wire the GA4 events to their call sites
d919076 refactor(analytics): drop the GA4 user_id override
d95adf6 chore(analytics): set the GA4 measurement id
cc967f0 feat(analytics): add GA4 instrumentation
```

**GA4, measurement id `G-ZZKRW6MMMM`.** LP had zero analytics of any kind — verified, not assumed:
no dependency in `package.json`, no calls anywhere in `pages/`/`components/`/`lib/`, no script tags.

Deviation from the stock snippet, agreed with Micah: `send_page_view: false` plus a manual
`page_view` on `routeChangeComplete`, because LP's nav is client-side and GA4's own history-event
tracking reads `document.title` before React updates it. **Micah has turned off "Page changes based
on browser history events" in the GA4 stream settings** (only that toggle; the rest of enhanced
measurement stays on). If page views ever double, that toggle is the first suspect.

A `user_id` from `lp_device_id` was built and then **removed at Micah's direction** — GA4's own
`client_id` already persists per-device. Don't re-add it.

**Five events in `lib/analytics.ts`, four wired.** Each fires on a confirmed action, never on
render or click:

| event | call site | why there |
| --- | --- | --- |
| `pick_made` | `pages/predict.tsx` (esports) + `components/Leagues/hooks/useUfcPredictData.ts` (UFC) | two separate pick flows; both fire only after the POST succeeds. The esports path ignored its response entirely — now checks `res.ok` for the event, control flow unchanged |
| `player_viewed` | `pages/player/[id].tsx` | on resolved profile, so 404s aren't views |
| `prop_chart_opened` | `components/Props/PropChart.tsx` | keyed on `seriesKey`, **not** mount — callers swap `data` between prop buttons without remounting, mount-only undercounts |
| `stream_watched` | `pages/esports.tsx` `UpMatchRow.toggle` | the deliberate open click; an iframe nobody opened is not a watch |
| `usage_trend_viewed` | **NOT WIRED** | see §4 |

**`lib/analytics.ts` is a thin wrapper over `gtag`, nothing more.** It contains no network calls of
its own. Micah got confused into thinking it was a second analytics system — if that comes up
again, the answer is no, everything goes to GA4 and nowhere else. (He also noted the filename is
misleading and `lib/gtag.ts` would have been clearer. Not renamed.)

## 3. The version-drift failure and its fix — Micah was angry about this

v0.6.1–v0.6.4 were each written to `package.json` and `CHANGELOG.md` and **never tagged**. Last real
tag was v0.6.0. Four version numbers burned with no release behind them.

**Fixed the numbers:** `v0.6.5` cut and pushed, `package.json` and `git describe` now agree. The
0.6.1–0.6.4 changelog entries are deliberately **left untagged** — picking commits for them after
the fact invents a history that didn't happen.

**Fixed the process** (this is what he actually cared about — I initially said "fixed" when I'd only
reconciled the numbers, and he correctly called that out):

- **`/root/.config/git/hooks/pre-push`** — appended a block that refuses a push when
  `package.json`'s version has no matching `v<version>` tag. Scoped by remote URL to
  legendarypicks; other repos verified unaffected. Escape hatch: `ALLOW_UNTAGGED_VERSION=1 git push`
  (**never** `--no-verify`, that would bypass the attribution guard). The existing attribution logic
  in that hook is byte-identical — don't disturb it.
- **`scripts/release.sh <version> [--dry-run]`** — bump + commit + tag together. Preflight refuses
  before touching anything if: tag exists locally or on origin, tree dirty, no `## vX.Y.Z` section
  in CHANGELOG, or package.json already at that version. Deliberately does **not** generate release
  notes. On push failure it prints finish-or-undo commands rather than going quiet.

**Known limit:** the hook is local to this box. Pushing from any other machine has no protection.
The repo has **no CI at all** (`no .github/workflows`) — a GitHub Action is the only
machine-independent version of this guard. Offered, not built.

`package-lock.json` is **gitignored** (`.gitignore:41`) and untracked; it sits at `0.3.1`. I edited
it to 0.6.5 locally but it is not in the repo, so it does not matter and is not worth a commit.

## 4. NFL usage renderer — committed, verified, still not mounted

Commit **`3317a27`** on branch `feat/nfl-usage-renderer` in worktree `/root/lp-nfl-usage`.
**⚠ LOCAL ONLY — not pushed to origin.** One `rm -rf` from being lost.

Hermes' draft was reviewed by Codex, which **rejected it on (a),(b),(d),(e)**. I verified each
myself; **three of the four were artifacts**:

- **(a) scope** — false positive. `.claude` and `backend/venv` are my bootstrap symlinks;
  `esports_team_logos.json` is a generated cache untracked in the main repo too.
- **(b) forbidden writes** — non-issue. The `CREATE TABLE`s are in `_create_schema()` writing to a
  `tempfile.TemporaryDirectory()`. My spec's "no writes anywhere in the diff" was over-broad.
- **(d) tests** — **real, and the only real one.** Also: the pytest failure itself was an artifact —
  Codex used system python3. **`backend/venv` has pytest 8.3.5 and httpx 0.28.1.**
- **(e) tsc** — pre-existing baseline (21–26 errors in `@onflow/fcl`, `pages/scores.tsx` etc.), none
  naming a new file.

**The real defects, now fixed:** `test_target_share_sums_to_one` accumulated `total_share` and never
asserted it, and underneath called `weeks=1` then read `games[0]` — which is the player's *last*
game, not week 1. `test_target_share_full_sum` skipped forever on a hardcoded game id with no data.
`test_weeks_cap` bypassed the HTTP layer. Suite is now **10 passed, 0 skipped**, and the sum tests
are **mutation-verified** (a 10% error in `tgt_share` fails them).

**Also found and fixed a render bug:** the sparkline fed newest-first `games` straight to the bars,
so it read backwards in time while the ▲/▼ arrow beside it read forwards. `_trend` itself is
correct (`clean[:3]` is recent, matching the ordering).

**Rendered and verified against the real dev DB** (screenshot sent to Micah): Zay Flowers and Trey
McBride 2025 tables, plus the 404 and empty-season states.

**BLOCKED ON A DECISION — Micah has not answered.** Nothing imports `NflUsageTrend`; grep of
`components/`+`app/`+`pages/` is zero hits. The renderer gap is **not** closed, and
`usage_trend_viewed` cannot fire. Two options put to him:

- **A — `pages/player/[id].tsx`**, gated `p.league === 'nfl'`. ~10 lines, unblocks the event.
- **B — an NFL league-hub usage leaderboard.** My stated view: **B is probably the better product**,
  because sit/start is inherently comparative and a single-player view can't answer "who do I
  start." A doesn't foreclose B; the endpoint serves both.

Also note: merging that branch into `dev` puts the renderer in the prod build. He was asked whether
that ships in the same push as analytics — unanswered.

## 5. Operational notes

- **Never `npm run build` in `/root/legendarypicks`** — it writes `.next`, which the live dev server
  on `:3096` serves from. Use a throwaway worktree with symlinked `node_modules`. Verified pattern:
  `git worktree add --detach`, copy changed files in, build, `next start` on a free port, tear down.
- **Live servers: `:8096` + `:3096` = `/root/legendarypicks`, externally managed, leave alone.** I
  used `:8097`/`:3097`/`:3098` for verification and closed all three; confirmed `:3096` still 200
  before and after.
- **`:3095` is an orphan returning 500** — its cwd is `/root/lp-ufc-fight-stats (deleted)`, a
  worktree removed out from under a still-running dev server. Pre-existing, not caused by this
  session's work. Worth killing (pid was 3907514).
- Box: 5.9GB, ~2.2GB available, **19 `live_valuefade.py` processes** from
  `/root/prediction-market-trading`. A Next prod build fits but is the heaviest thing that runs here.
- Editing the global git hook was **blocked by the permission classifier** on first attempt and
  needed Micah's explicit go-ahead. Expect that for anything under `/root/.config` or `/etc`.

## 6. Open loose ends

- **Deploy to prod** (§1) — the deferred action.
- **`NflUsageTrend` placement, A or B** (§4) — blocks `usage_trend_viewed`.
- **Push `feat/nfl-usage-renderer`** — `3317a27` exists only locally.
- **No NFL pick surface exists.** Picks today are esports + UFC only. Fantasy football is the stated
  focus and "made a pick in week N, came back in week N+1" is the activation metric — but it
  **cannot measure NFL**, because there's nothing to pick on. Instrumentation does not fix this.
  This is the most important unresolved product gap and it surfaced from the call-site work.
- GitHub Action for the version guard (§3) — the only machine-independent version.
- Prod visitor figure "0–19 unique app-route visitors/day" is inherited from the 07-25 session and
  was **not** re-derived this session.
- Still open from 07-25 and untouched: `/strength` quality gate broken, `streams.py` decapi
  wobble, unexplained `state=live` with future start time, unexplored embed sources, Underdog
  fighter identity gap, Micah's unanswered Codex prompt.

## Closed from 07-25

Push of `4e37340`/`2980b33`/`33390c4` — done, `origin/dev` is in sync. Renderer Hermes/Codex round
trip — done, see §4; the `sports_service.py` vs `main.py` spec bug never bit (Codex confirmed
registration is correct and `main.py` untouched). Instrumentation blocker — closed, see §2.
