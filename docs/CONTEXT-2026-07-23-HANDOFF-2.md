# CONTEXT HANDOFF — 2026-07-23 (evening, part 2): v0.6.0 promoted to prod, EV/CLV extended to NFL/NBA/NHL, UFC fighter detail shipped

Read first on reset. Supersedes `CONTEXT-2026-07-23-HANDOFF.md` (the pre-promotion state from
earlier the same day) — that doc's "next up" note is still accurate and still not started; this
doc covers everything that happened after prod got promoted.

## ⚑ WHAT SHIPPED THIS SESSION (all on `dev`, pushed, commit `bab94eb` HEAD)

1. **Prod promoted v0.5.5 → v0.6.0** (83 commits). Two real bugs caught+fixed post-deploy:
   `ingest_nfl_adp.py`'s pagination loop never terminated (ESPN ignores `limit`/`offset`, always
   returns the full pool — fixed by breaking on no-new-ids), and NFL Recent Trades showed empty
   (needed `--full` backfill to reach back to real trades, default incremental window had none).
   Full detail: [[reference_lp_prod_deploy]] memory / `docs/DATA-FRESHNESS-SPLIT-2026-07-23.md`.
2. **`docs/DATA-FRESHNESS-SPLIT-2026-07-23.md`** — catalogued the 3 freshness strategies already
   in this codebase (systemd timer / in-process lazy warmer+SWR / manual one-off script no
   scheduler). Result: NFL ADP + transactions now on new daily systemd timers (dev+prod, 4:10-4:25
   AM); retired the now-finished WC props timers (World Cup ended 2026-07-19).
3. **Docker/disk hygiene**: `docker image prune` + `docker builder prune -af` reclaimed 111.8GB
   (build cache 103GB→0, disk 112GB→220GB free). Confirmed this never touches containers —
   unrelated `plane-selfhost-*` stack verified untouched.
4. **EV/CLV generalized from MLB to NFL, then NBA, then NHL** (`backend/_core.py`
   `_LEAGUE_MARKET_STAT` dict, mechanical per-league market→stat mapping, both delegated to
   Hermes with a fully closed spec — exact source/market names verified by me first, not left for
   Hermes to guess). NFL/NBA/NHL are all off-season with zero live props right now, so verified
   against real historical `player_game_logs` (McCaffrey, Achane, Chase / LeBron, Jokic /
   McDavid, MacKinnon), not provable end-to-end until each season's props start flowing. NHL
   `saves` explicitly NOT mapped — zero goalie rows exist in `player_game_logs`, would need a
   separate goalie-specific ingestion.
5. **UFC fighter detail + per-fight stats** (`backend/ingest_ufc_fight_stats.py`, new) — real
   sig-strikes/takedowns/knockdowns/submissions/control-time data from ESPN's per-competitor
   statistics endpoint (free, unauthenticated, same family as everything else ESPN in this repo),
   backfilled into `player_game_logs` for the 42 UFC fighters we track. **Fixed a real search
   bug as a side effect**: UFC fighters only appeared in player search when they had a
   currently-live prop (search requires game_logs/props/stats — UFC had zero game_logs rows,
   ever, until this). Delegated to Hermes with a fully closed spec (exact stat-field names,
   exact source verified, exact scope).
   - **Found+fixed 3 separate instances of the same "raw 43-field ESPN dump" bug** afterward,
     each in generic code that assumed a curated per-league market list (works fine for
     MLB/NFL/NBA/NHL, breaks for UFC's uncurated blob): player-detail page's Projections table
     (fully suppressed for UFC), Props page Model tab's line-checker (curated to ~9 headline
     stats), Props page Matchups tab's `slice(0,6)` (prioritized headline stats in the existing
     `order` array so alphabetical noise like `advanceToBack` doesn't win the slice).
6. **`scripts/hermes-worktree.sh` real bug fixed**: `down()` killed processes by hardcoded port
   (`BPORT=8096`/`FPORT=3096`, same constants every task reuses), not by verifying they belonged
   to that task's worktree — **killed the live dev tunnel's backend/frontend twice in one
   session** as collateral damage before the fix. Now checks each candidate PID's actual `cwd`
   against the worktree path before killing; also dropped a dead `cloudflared` kill line that
   never had a legitimate target (`up` never starts a tunnel — "No auto-tunnel" by design).
7. **Props page**: Performance/Matchups/Model tabs now share one search (`sharedQuery`/
   `sharedPlayer` lifted to `PropsPage`) — switching tabs no longer resets the search box.
8. **Perf fix**: Recent Trades' significance lookup was rebuilding ~9.6k players + ~2.5k ADP rows
   into fresh dicts on every request (~200ms+, worse under load) — 5-min TTL cache added,
   deployed to prod too.
9. **Kick.com viewer counts fixed** (esports board) — `KICK_CLIENT_ID`/`KICK_CLIENT_SECRET`
   existed in `.hermes/.env` with real values but were never wired into `docker-compose.yml`'s
   env passthrough (same class of gap as the earlier PANDASCORE/GRID/YOUTUBE one). Fixed,
   redeployed prod backend, verified real counts (657/724 viewers) on live matches.
10. **Underdog Fantasy API recon** (`docs/UNDERDOG-API-RECON-2026-07-23.md` +
    `docs/UNDERDOG-PROPS-BOARD-AND-SETTLEMENT-2026-07-23.md`) — `api.underdogfantasy.com/beta/v5/
    over_under_lines` is real, live, and completely unauthenticated (PrizePicks' equivalent
    403'd). Confirmed real UFC/MLB/tennis/CS/VAL/LOL markets; MLB has a genuinely new 1st-inning
    market category we don't ingest at all today. **Checked and ruled out**: their NFL board is
    season-futures only, does not close the per-game-props off-season gap. Settlement
    feasibility varies hugely by sport — MLB/NBA/NHL/UFC already have durable actuals
    (`player_game_logs`), esports (GRID/Riot) has real live per-player data but nothing persists
    it past the live board view, tennis has zero actuals infrastructure at all. Not yet built —
    just scoped.

## ⚠ Version/release state — currently INCONSISTENT, explicitly parked

Cut `v0.6.1` + `v0.6.2` as GitHub Releases + git tags tonight (EV/CLV extension + UFC work).
**User then said "do not create bugfix releases, only feature releases" and deleted both GitHub
Releases** (v0.6.0 is Latest again). I deleted both git tags to match (confirmed gone locally +
on origin). **BUT**: `package.json` is still at `"0.6.2"` and `CHANGELOG.md` still has full
`v0.6.1`/`v0.6.2` entries at the top, with NO corresponding tag/release for either anymore —
i.e. a dangling version number and changelog entries that don't correspond to anything tagged.
I flagged this and offered to consolidate into one clean feature release; **user said "moving
on"** — this is a known, acknowledged loose end, not an oversight. Whoever picks this up next:
decide whether to (a) cut ONE new release (e.g. re-tag as `v0.6.1` covering all three real
features: NFL/NBA/NHL EV/CLV + UFC fighter detail, folding the fixes into that same changelog
entry per the new no-bugfix-releases rule), or (b) something else — not yet decided.

New standing rule going forward, saved to memory
([[feedback_feature_releases_only]]): **only cut a version bump / GitHub Release for an actual
new feature/capability, never for a fixes-only batch.** Fixes still commit/push to `dev`
normally, they just ride into the next real feature release's changelog instead of getting their
own.

## Current live state (verified at handoff time)

- Prod: v0.6.0 containers running (`legendarypicks-backend-1` up 38min, `-frontend-1` up 15h),
  all the fixes above are live (Kick keys, trades cache, NFL ADP/transactions data). Prod is
  NOT on the EV/CLV-extension or UFC-fighter-detail commits — those only landed on `dev`, never
  redeployed to prod this session (not asked to).
- Dev: backend `:8096` / frontend `:3096`, both healthy. Tunnel:
  **https://someone-decorative-wearing-produce.trycloudflare.com** (verified 200 at handoff
  time). Note: this box's local DNS resolver (127.0.0.53) sometimes lags 20-30s behind a
  freshly-minted `trycloudflare.com` subdomain — doesn't affect the user's own browser, only
  this shell's own `curl` checks; use `dig @1.1.1.1` + `--resolve` to verify from here if it
  looks down.
- Hermes tmux pane (`hermes:0.0`) — idle, ready for new dispatch. Successfully completed 3
  delegated tasks tonight (NFL EV/CLV, UFC fight-stats+detail, NBA/NHL EV/CLV), all reviewed
  and merged. One transient hiccup (empty model response mid-task on the NBA/NHL job) recovered
  with a one-line nudge, no data loss.
- `dev` pushed to `origin/dev` @ `bab94eb`. GitHub Releases: `v0.3.0` through `v0.6.0` now all
  exist (backfilled v0.4.0/v0.5.0 tonight from CHANGELOG.md's pre-truncation git history — that
  file lost ~467 lines in a past commit, `git show 4f29b2b:CHANGELOG.md` / `873a056:...` have
  the original content if needed again).

## NEXT UP (still not started — carried over from the pre-promotion handoff)

Per the prior handoff, still true: **weekly rankings per position + post-game weekly
performance tracking** for NFL (sit-start/waiver framing, `docs/SPEC-nfl-product-direction.md`).
Needs a weekly (not season-aggregate) projection view + real post-game box-score ingestion on a
cadence (still ad hoc). Also newly on the table from tonight's UFC/Underdog thread: (1) resolve
the v0.6.x release inconsistency above, (2) UFC fight-time capture (round+clock already fetched
by `ufc_fight_history()`, just not stored — small addition), (3) whether to build Underdog
ingestion for MLB 1st-inning props / tennis (real recon done, nothing built yet).

## Feedback/pattern notes from tonight worth remembering

- Delegate to Hermes with a **fully closed spec** — verify exact source/market names/API shapes
  myself first, leave zero decisions for Hermes to make. Explicitly corrected mid-task once
  tonight ("don't make Hermes make its own assumptions, it's not good at that") and it held for
  the rest of the session.
- tmux paste-buffer into Hermes's CLI **fragments on blank lines** in a multi-paragraph message
  (each blank-line-separated paragraph submits as its own turn) — collapsing the whole brief to
  ONE line before pasting avoids this reliably, used successfully 4+ times tonight.
- `hermes-worktree.sh up` still hardcodes ports 8096/3096 (collides with main dev + its tunnel
  every time) — `down` is now fixed (cwd-checked), `up` is not; still need to manually relaunch
  on free ports after every `up` call while a tunnel is live.
