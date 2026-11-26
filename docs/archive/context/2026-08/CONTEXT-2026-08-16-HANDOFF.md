# CONTEXT 2026-08-16 — MLS/NCAAF merged both ways; v0.8.0 is NOT ready to cut

Session: merge `feat/league-mls-ncaaf` ⇄ `dev`, then prep v0.8.0. **Nothing pushed. Nothing
tagged. No prod write.** Suite: **1,445 passed / 4 skipped / 6 xfailed against BOTH
`picks.db` and `picks.dev.db`.**

> **⚠ READ FIRST — two corrections to what was believed at the start of the session:**
> 1. **`dev` was never pushed.** It is now **69 commits ahead of `origin/dev`**, 0 behind.
> 2. **The release gates FAIL on exactly the two leagues 0.8.0 would advertise.** See §4.
>    `scripts/release.sh` runs the audit and refuses on FAIL, so a tag attempt will stop.

---

## 1. What Micah asked for, and where it actually got to

| asked | state |
|---|---|
| merge `dev` → mls-ncaaf worktree | **done** (`c5cfc25`) |
| merge it back → `dev` | **done** (`5a91cc7`) |
| pull in Underdog props for MLS before cutting | **NOT STARTED** — §5 |
| cut v0.8.0 | **BLOCKED** — §4 |
| release notes honest about MLS/NCAAF | measured numbers in §3, notes not written |

## 2. Commits added to `dev` this session

In the worktree, then merged:
- `c74dc2c` feat(leagues): surface MLS and NCAAF on scores + leagues hub, NCAAF game-log columns
- `2ab0e12`-ish docs slice: NCAAF plan, MLS season-stats context, landing preservation
- `c5cfc25` merge `dev` → branch (4 conflicts, resolved — see §6)

On `dev`:
- `def56a3` gate(ncaaf): per-stat coverage floor for publisher-conditional stats
- `5a91cc7` merge branch → `dev` (1 doc conflict, both records kept)
- `2247336` fix(standings): restore `lg` binding, absent MLS data → honest 503

**Uncommitted, stashed:** two generated caches (`esports_team_logos.json`,
`identity-consolidations.jsonl`) — `git stash list`, message "generated caches, pre-merge".

## 3. What MLS and NCAAF actually have — measured 2026-08-16

This is the table the release notes have to be honest about.

| | MLS dev | MLS prod | NCAAF dev | NCAAF prod |
|---|---|---|---|---|
| `prop_games` | 15 | 15 | **0** | **0** |
| `props` | 714 | 710 | **0** | **0** |
| settled (real outcome) | 357 | 297 | 0 | 0 |
| prop sources | **bovada only** | bovada only | — | — |
| `player_game_logs` | 16,661 | 6,087 | 56,577 | 56,577 |
| `player_stats` (leaders) | **0** | **0** | 4,267 | **0** |
| `team_game_results` (standings) | 1,020 | **0** | 1,776 | **0** |

Read that carefully — **prod is not simply empty.** It has MLS props and both leagues' game
logs, but it has **no `team_game_results` for either league**, so the standings surfaces this
release adds will 503 on prod, and **no `player_stats` for either**, so there are no leaders.

**Micah's own framing was right and the numbers back it:** MLS props are thin — 15 games, one
book (Bovada), and that is the whole of it. **NCAAF has literally zero props**, so whatever the
notes say about NCAAF must not imply a props surface exists. His open question stands: when the
NCAAF season starts, check whether Bovada carries the props or whether Underdog is required.

## 4. Why v0.8.0 cannot be cut yet

`venv/bin/python audit_league_stats.py --db data/picks.dev.db` → **4 FAIL, 12 UNVERIFIED,
81 pass.** Every FAIL is in MLS or NCAAF:

- **FAIL `mls A/required-stats[season]`** — no `sot` column; `goals`, `assists`, `shots` exist
  but **0 rows populated**.
- **FAIL `mls C/vocabulary[position]`** — two levels of one vocabulary in one column (AM under
  M, CD under D, LB under D, …). Same defect shape as NCAAF below.
- **FAIL `mls D/leaders-reach-logs`** — no `player_stats` rows at all.
- **FAIL `ncaaf C/vocabulary[position]`** — C under OL, CB under DB, FB under RB, NT under DT,
  S under DB.

Plus the prod data gap in §3. **The release-blocking list in `docs/ROADMAP.md` is still open**
(prod news empty, MLS hidden on prod, settled props reachable, relink `prop_games`) — this
session did not touch it.

**A judgement, not a rule:** the two `C/vocabulary` FAILs are the same defect in two leagues and
are plausibly a mapping fix rather than an ingest rerun. The MLS `A` and `D` FAILs are real
absences — there are no MLS season stats at all. Shipping MLS as a *standings + schedule +
thin props* league is defensible **if the notes say exactly that**; shipping it as a stats
league is not.

## 5. NEXT: Underdog props for MLS (Micah's explicit ask, not started)

Everything needed is already in the repo:

- **Endpoint**: `api.underdogfantasy.com/beta/v5/over_under_lines` — unauthenticated,
  **18.7 MB** as of 08-14 (`docs/UNDERDOG-API-RECON-2026-07-23.md` says ~8 MB in July; it has
  more than doubled). `players[]` → `appearances[]` → `over_under_lines[]`.
- **Existing ingest**: `backend/ingest_underdog_props.py`, plus codex's UFC work on 08-15
  (`docs/CONTEXT-2026-08-15-PROPS-UFC.md`, commits `209b813`, `b375782`, `73d17d0`, `29f892d`,
  `316c654`). It persists source-native keys in `player_source_ids`.
- **A live timer already exists**: `legendarypicks-underdog-ufc-props.timer`, every 30 min,
  units committed under `ops/systemd/`. MLS would extend this path.
- **Codex's own rule, inherited — do not break it:** *never resolve a new Underdog player by
  fuzzy display-name matching, and never create a player from the feed.* MLS is the league
  where this bites hardest: Bovada and ESPN already spell 8 of 13 clubs differently, and the
  recorded vocabulary (34 spellings of 30 clubs) exists precisely because a normaliser
  mislinks silently.
- **Underdog is not a sportsbook.** Its lines carry no two-sided price, so they cannot enter
  the EV/CLV path the Bovada props use. Store as `source='underdog'` and keep them out of any
  de-vig math (`docs/UNDERDOG-API-RECON-2026-07-23.md` §"Open question").

Sanity target: MLS currently has **714 props from one book across 15 games**. State the
expected row delta before running, and reconcile the count after.

## 6. Merge decisions worth knowing (so nobody re-litigates them)

Four conflicts in `dev` → branch, one in branch → `dev`:

- **`backend/routers/games.py` standings** — kept the **branch**. Its MLS path is DB-first
  (`_mls_standings_from_db`, dated 08-13) and NCAAF has a dedicated
  `ncaaf_conference_standings`; dev's generic `espn.group_standings` dates to **2026-06-24**
  and taking it would have regressed the MLS draws fix and dropped conference grouping.
- **`backend/routers/games.py` live_score** — kept **dev**. `scores` is keyed by ESPN
  abbreviation; the branch looked it up by team *name* and fell back to a key that never
  existed, so the score silently came back `None`.
- **`backend/espn_client.py`** — took dev's file, then **restored `_parse_record` and
  `ncaaf_conference_standings`** from the branch. Taking either side wholesale would have
  broken the other; a plain `--theirs` silently dropped both while the code calling them stayed.
- **`pages/scores.tsx`** — took dev's shared `LEAGUE_KEYS` + `leagueKeyFor()` (W3 navigation
  depends on them) and added NCAAF into them, rather than keeping the branch's second inline
  league list. The fan-out now reads `LEAGUE_KEYS`, so what we render and what navigation asks
  cannot drift.
- **`TASK-league-mls.md`** — kept **both** status records with a bridge note; the 08-15 matrix
  marks standings RED and the 08-13 branch entry is the fix that closes it.

## 7. Three defects found by running the suite against BOTH databases

Worth repeating as method: the merge was green against `picks.dev.db` and broken against
`picks.db`. One ruler would have shipped all three.

1. `get_standings` lost its `lg = league.lower()` binding in my resolution → `NameError` for
   every non-WC league. **Mine, introduced and fixed in-session.**
2. `_mls_standings_season` guarded its first query but not its fallback → a DB with no
   `team_game_results` raised a bare `OperationalError` and reached the user as a 500. Now the
   documented 503.
3. `test_ingest_underdog_props_identity` read `os.environ["LP_DB_PATH"]` unconditionally;
   another module restores it to *absent* in a full run, so the result depended on collection
   order.

`test_group_standings_contract` asserted the superseded contract (MLS via
`espn.group_standings`). Rewritten to assert the stronger invariant — **MLS is served from our
own rows and calls no ESPN host** — plus the 503-on-no-rows case. `test_leagues_hub_assertions`
now distinguishes "this DB holds no MLS" from "the MLS surface is broken" instead of dying at
collection and taking the whole gate run with it.

## 8. Box state

- RAM reclaimed this session: **990 MB → ~1.5 GB available**. Stopped `lp-new-leagues`
  frontend+backend (systemd units, `systemctl stop`, not disabled) and the 18-day-old
  `lp-nfl-allday` backend. Killed 16 orphaned chromium processes (2 leaked agent browsers).
- **`:3105` is down and its tunnel `coat-develop-rooms-prague` therefore 502s.** Micah decided
  it is not worth restarting — that URL served `lp-new-leagues`, whose branch is **fully merged
  into dev (0 commits ahead)**. The live MLS/NCAAF work is on **`:3098`**, with no tunnel.
- Live and untouched: `:3096`/`:8096` dev pair, both prod containers, mls-ncaaf on `:3098`/`:8098`.

## 9. Also still open (not touched today)

- **DeepSeek peak pricing started 2026-08-16.** `TASK-deepseek-offpeak-scheduling.md`: 4 of 10
  scheduled runs/day land in peak, timers are in local time so DST will walk them further in,
  and `kick_game_stories()` bills `v4-pro` from the request path at any hour. Host config, so
  it needs Micah or an unblocked `systemctl`.
- `TASK-scores-schedule-espn-model.md` W2 (Top Events) and W4 (week model) — need Micah's §6
  answers.
- `ec5872e` scores-outage fix — still unmerged in `/root/lp-scores-prev-day`.
- Delete plan for 279,404 prod null-outcome rows — undecided.
- UFC story surface still not honest (12 near-empty previews, one leaked a raw `None`).
