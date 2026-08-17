# Roadmap

**The checklist below is the current state. Everything under "Ledger" is the history and the
reasoning — that section keeps its own rule: add, don't rewrite, mark superseded rather than
delete.**

Checked = shipped to **production**, not to dev. Checklist last updated **2026-08-14**;
current state and the deployment target are in the dated block below, updated **2026-08-17**.

The constraint that orders all of it: **NFL fantasy drafts run the next 3-5 weeks**, and NFL
draft research is the only use case a real user has said yes to (see "User evidence" below).
Anything that does not serve that window competes with it. *That window is now mostly spent
— set 2026-08-06, and it is 08-12. Weigh anything below against how few days are left in it.*

> **The defect list is not here.** `docs/BACKLOG-holes.md` holds 25 measured holes,
> severity-ranked, generated from `backend/league_feature_matrix.py`. Re-run the matrix
> before working any of them; every line is a count, and counts move:
>
> ```
> venv/bin/python league_feature_matrix.py --db data/picks.db --compare data/picks.dev.db
> ```
>
> The one-line summary of that list: **most P0s are the same defect.** Data lands, the link
> that makes it reachable does not, and nobody took the count that would have shown it —
> four items are `prop_games.espn_event_id`, two are settlement coverage.

---

## CURRENT — 2026-08-17: deployment target and what stands in front of it

### The deployment target is v0.8.0. Nothing has shipped to prod since v0.7.8.

What production is actually running, read off the containers rather than the tags:

```
legendarypicks-frontend-1   image built 2026-08-09
legendarypicks-backend-1    image built 2026-08-12
```

**`backend/data` is bind-mounted; code is baked into the image.** That single fact orders
everything below, because it splits every fix into one of two classes:

- **A data fix reaches prod the moment it runs.** 2026-08-17's tennis spine went from written
  to live on prod in four minutes, and `props-prod` went 0/384 → 347 props with no deploy.
- **A code fix cannot reach prod at all until a release.** It does not matter how small. The
  slate filter repaired on 08-17 is five lines and prod will keep serving finished games until
  v0.8.0 ships.

The corollary, which has cost us twice: **a schema change must never get ahead of the code that
understands it** (see `feedback_schema_must_not_outrun_prod_code`). Additive nullable columns are
safe; constraints and indexes are not, because the writer that has to satisfy them is frozen at
image-build time.

### Release gates — 7 red as of 2026-08-17

`./verify-gates.sh all` → 24 passed, 6 failed, plus one added the same day:

| gate | state | note |
|---|---|---|
| COV-source | FAIL | `team_game_results.nfl` 1114 rows; `team_game_stats.mlb` 16 |
| COV-gametype | FAIL | mlb 2026: 1,579 of 53,895 rows NULL |
| COV-identity | FAIL | blocked on `orphan_players=1` |
| COV-statset | FAIL | 12 of a known 21 open — **expected red**, see `docs/LEAGUE-STAT-GAPS.md` |
| REG-adp-dst | FAIL | `HOU` off expected (236 vs 223) |
| REG-jest-all | FAIL | 2 failing tests in 1 suite, not yet identified |
| BOARD-stale-prod | FAIL | **new 2026-08-17.** Prod serves 2 finished games as upcoming. Red *by design* until a release carries the fix — the redness is the deploy skew, reported rather than assumed. |

`BOARD-stale-dev` passes. That pairing is the point: the two are different code, so a green dev
gate says nothing about the deployed board.

### Release-blocking list from 2026-08-12 — remeasured 2026-08-17

Two of the four cleared themselves; the counts, not the intentions, are what changed.

- ~~**Prod news is empty** (#1)~~ — **CLOSED.** Prod `news_items` = 4,784, with 467 in the last
  24h. Bluesky search came back the same day (91/91 queries, 406 posts) once the credential was
  read under its real name.
- ~~**Tennis discards a working feed** (#2)~~ — **CLOSED on prod.** 1,022 tennis props on
  `picks.db`; the ATP/WTA spine is 150 per tour, every row carrying an ESPN id.
- **MLS is hidden on prod** (#6) — **still open, unchanged.** `team_stats_coverage` where
  `league='mls'` is **0 rows on prod, 1 on dev**. The release calls MLS out; nobody sees it.
  Promotion is a data job, so this one *can* land without a deploy.
- **Settlement writes failures in the shape of successes** (#21–23) — still open, and it is
  the most expensive item on this page. See the 08-14 correction below.

### Open work, consolidated 2026-08-17 from six sessions

Ordered by what blocks what, not by size. Detail for the defect rows is in
`docs/BACKLOG-holes.md` under the 08-17 block.

**All three answered 2026-08-17 — kept here with the decision, not deleted**

1. ~~**`start_time` write-once**~~ — **DECIDED: overwrite only when the publisher disagrees.
   DONE** (`3641992`). One helper in `link_prop_games.apply_start_time`, called from all three
   ingest sites so the rule cannot drift per league. Compares instants, not strings, so a
   re-scrape of an unchanged game does not rewrite the row; a real disagreement is written and
   announced in the run log.

   Micah asked first how the pipeline handles reschedules. **It does not handle them at all**,
   and that is now measured rather than assumed:
   - `team_game_results.status` holds exactly two values across all of 2026 — `completed`
     (8,450) and `scheduled` (544). **Zero** rows record postponed, canceled or suspended.
   - `prop_games` has no status column at all.
   - `reconcile_gap.py:94` knows `STATUS_POSTPONED`/`CANCELED`/`SUSPENDED`, but it is a one-off
     analysis script and is **on no timer**.
   - Every ingest path looks its row up by `(league, date, home, away)`, so a game moved to a
     new day creates a SECOND row while the original keeps its props — and ESPN issues makeups
     under a **new event id**, so the original can never link to one.

   So the policy change makes same-day revisions propagate, which is most of the class. Date
   moves stay open as backlog #46, and they are the reason drop-at-kickoff cannot ship yet.
2. ~~**Scores W2 / W4**~~ — **DEFERRED to the scoreboard redesign, post-0.8.0** (Micah,
   2026-08-17). Not release-blocking; do not re-raise before the release.
3. ~~**Bluesky account password vs app password**~~ — **RISK ACCEPTED** (Micah, 2026-08-17).
   `createSession` takes either. Noted here so a future reader does not "fix" it as an
   oversight: it was a decision.

**The release is the priority.** Micah, 2026-08-17: *"ive been trying to get a release for a
week."* Weigh anything below against whether it moves v0.8.0. Items that cannot ship without a
deploy are worth less right now than items that clear a red gate.

### Sequencing decided 2026-08-17 — cut v0.8.0 BEFORE the identity work

The next release after this one is about **player identity**, and it does not go first. Backlog
rows 54–56 hold the measurements; the ordering argument is:

- **The fix is a constraint, so it cannot precede the code.** `UNIQUE(league, espn_id)` is an
  assertion the *writer* has to satisfy, and prod's writer is frozen in the container image.
  Applying it now repeats the `ux_prop_games_event` mistake of 2026-08-17 on a bigger table.
  "Identity first, then release" inverts to "release, then constrain".
- **The code/DB gap is itself the thing that costs the backfills.** Prod is taking schema
  promotions right now while running 08-12 code. Closing that gap is what makes every later
  identity change verifiable against prod instead of only against dev.

**The test for any item claiming to be pre-release:** *does it need code or a constraint to be
correct?* Yes → it rides this release. No (a data promotion, a backfill) → it can land either side
of the cut and must not hold it.

**Guardrail while the cut is pending:** any merge that allocates fresh target ids widens the
prod/dev fork one-way. It must **record the mapping it used** — source id, target id, and the
publisher id justifying each — in a committed artifact, or the next pass re-derives it from names.

### POST-RELEASE ORDER, set 2026-08-17 — do these in this sequence

1. **gstack `retro`** (`/root/gstack/retro`) — engineering retrospective first, so the
   refactor below is aimed by it rather than guessed at.
2. **Break up every file of 1,000+ lines.** Measured 2026-08-17, 13 of them:

   ```
   2166  backend/wc_context.py              1232  pages/esports.tsx
   1817  backend/ingest_league_narratives.py 1196  backend/settlement.py
   1752  backend/routers/games.py           1182  backend/ingest_ufc_fight_stats.py
   1586  backend/routers/nfl_mock_draft.py  1169  backend/audit_league_stats.py
   1527  backend/routers/nfl_offseason.py   1160  backend/ingest_league_news.py
   1442  backend/routers/players.py
   1311  backend/espn_client.py
   1281  backend/bovada_scraper.py
   ```

   Note `wc_context.py` is the largest file in the repo and World Cup is dormant until 2030.

3. **A TOURNAMENT is not a LEAGUE — model the difference** (Micah, 2026-08-17). This is the
   modelling item behind a defect we hit today, not a cleanup.

   MLS props carry rows whose club is `AME`, `GDL`, `PUE`, `TOL`, `NFO` — Club América,
   Chivas, Puebla, Toluca, Nottingham Forest. They are filed under `league='mls'` because the
   props feed covered Leagues Cup fixtures and a friendly. They are not MLS players, so no
   MLS spine will ever resolve them, and the merge correctly refuses every one:

   ```
   cross-team 'Igor Jesus':      NFO  vs published LAFC
   cross-team 'Elias Achouri':   AME  vs published SD
   cross-team 'Vincent Janssen': PUE  vs published POR
   ```

   That is 38 unresolved shadow rows on prod and the reason MLS still reports 1 FAIL.

   **The distinction to build on:** a league has a fixed membership and a season-long table —
   a club plays only clubs in it. A tournament draws entrants FROM leagues, can be
   cross-league (MLS vs Liga MX) and cross-confederation, and its participants keep their
   league identity. So a tournament fixture needs its own competition key while its players
   stay resolvable against whichever league actually rosters them. Filing Leagues Cup under
   `mls` collapses both halves of that and produces players nobody can resolve.

   Already decided in this file 2026-08-06 for the LOGS side (Leagues Cup
   `concacaf.leagues.cup`, CCC `concacaf.champions`, Campeones Cup as separate ESPN slugs, so
   a Leagues Cup goal does not inflate MLS `games_played`). Today extends it to PROPS and to
   IDENTITY. Same shape, wider than first scoped.

4. **Player identity across databases** — the section below.

### NEXT RELEASE (v0.8.1 or v0.9.0) — player identity

Scope, in order. Full detail in `TASK-next-release-player-identity.md`.

1. Declare the natural key on `players` — it is already unique on both databases, 0 duplicate
   `(league, espn_id)` groups, so the migration has no conflicts to resolve.
2. Populate `player_source_ids` so Bovada/RotoWire/Underdog stop resolving by name every run.
3. Convert promotion from row-copy to re-running the ingest against prod, which is what already
   works — the 2026-08-17 tennis spine did it in 2 requests with zero id reconciliation.
4. Only then: reconcile the ids that have already diverged, using the mapping artifacts recorded
   under the guardrail above.

**Next code work**

4. **Drop props at kickoff, with a postponement exemption** (decided 2026-08-17). The board
   currently keeps a game for 3 hours past its start. Kickoff is the right rule for a pregame
   board, but it cannot ship until the board can tell *postponed* from *started*: `prop_games`
   has no status column at all. ESPN already publishes `state`/`completed`/`status` and
   `reconcile_gap.py:94` already knows `STATUS_POSTPONED`/`CANCELED`/`SUSPENDED`. Additive
   nullable column, populated via the linked `espn_event_id`, then the filter changes.
5. **MLS settlement returns 0 settled** on the four finished 08-15 games. Found, not diagnosed.
   ~5,300 props sit behind it.
6. **`props-freshness` self-heal blocks** — `systemctl start` on a `Type=oneshot` waits, the
   watchdog allows 15s. One-line `--no-block`. Masked now that `props-prod` is green, not fixed.
7. **Tennis spine source: rankings → tournament scoreboard.** Same 2 requests, 263–328 real
   entrants including qualifiers and wildcards, and it stops decaying every Monday. Recovers
   Monfils, Sloane Stephens, Lois Boisson — all genuine coverage misses, not spelling ones.
8. **Surname-first name order** in `_resolve_player_for_ingest` — Xinyu Wang ↔ Wang Xinyu. Same
   shape as Kim Kee-Hee in MLS, so it is one fix rather than a per-league patch.
9. **The unconfigured-ESPN-script gate is unwritten** — 20 of 27 scripts including
   `bovada_scraper.py`. `link_prop_games.py`'s budget guard is the model to generalise.

**Queued product work**

10. **Underdog-MLS** — the instruction before the last stop, never started.
11. **PrizePicks MLS probe** — hourly; the first read that can carry evidence is the 08-19
    slate. Would take MLS from 2/11 markets to 9/11.
12. **2026 MLS log backfill paused** at 147 of ~350 matches. Resumable.

**Host / cost, needs Micah to run**

13. **DeepSeek peak billing** — 4 of 10 scheduled runs/day land in peak window, both news timers
    at 100%. Retime three timers and pin them UTC (`TASK-deepseek-offpeak-scheduling.md` §4).
14. **279,404 prod null-outcome rows** — delete plan still un-run.
15. **`legendarypicks-underdog-ufc-props.timer` went onto the host against the ban**, firing
    every 30 min. Tracked under `ops/systemd/`, but it should not have been installed.

---

## PAST — done and live in prod

**Data correctness**
- [x] Identity gate: every external id must name the person on the row (`G/published-identity`)
- [x] 223 MLB rows repaired — they carried another player's `mlbam_id` (Statcast's `player_name` is the *pitcher's*)
- [x] MLB dedupe: 317 duplicate groups collapsed, 0 remain
- [x] NHL season keys migrated — 48,017 rows off the publisher's raw key
- [x] NHL 82 missing games ingested; reconciles against ESPN 1312/1312
- [x] NBA leaderboard serves 2026, not 2023
- [x] One spelling per NFL position (`K`->`PK`, `SAF`->`S`)
- [x] `OL`->`G` fabrication removed — it asserted every unspecified lineman was a guard
- [x] Fantasy constructs marked `entity_type` — 97 NFL rows are not people
- [x] `position_group` for MLB, NFL, NBA — the parent level in its own column

**Gates and process**
- [x] `audit_league_stats.py` — 8 checks, MANIFEST-driven, **0 FAIL on prod** across all four leagues
- [x] Gates **block** releases — `release.sh` runs the audit + prod/dev diff and refuses on FAIL
- [x] `diff_databases.py` — prod vs dev; schema/seasons block, volume advisory
- [x] Migration ledger — one invocation migrates **both** databases; app refuses an un-migrated one
- [x] Boundary modules: `season_keys.py`, `team_codes.py`, `game_ids.py`
- [x] Backup retention + `VACUUM INTO` (never `cp` — a live copy races writers)
- [x] `espn-request-budget` skill for Claude, hermes, reasonix

**Product**
- [x] NFL board sorts by touchdowns — shipped in v0.7.3, actually **live** 2026-08-05
- [x] Draft board shows injury status — 2,617 players (was 0 for ~18 hours)
- [x] NFL 2026 schedule in prod, first kickoff 2026-09-09
- [x] Prod backend 291MB (was 7.45GB — backups were being baked into the image)

## PRESENT — in flight

- [ ] `B/position-content` for **mlb** and **nba** — a declaration: what must a catcher's / guard's log record?
- [ ] `DATA-COVERAGE-CONTRACT.md` §7 rewrite — what each of the 8 checks needs from a new league
- [ ] `ufc` / `wc` UNVERIFIED x6 — likely "no leaderboard surface to serve", not a fetcher
- [~] **MLS + NCAAF pipelines** (`feat/league-mls-ncaaf`) — **superseded 2026-08-12, both built.**
      No longer blocked on the identity spine; that resolved. Current state, measured:
      - **NCAAF: built and deliberately DARK** (Micah, 2026-08-11). 20,926 players, 56,577 logs,
        888 games, 137 FBS teams, 4,267 season rows, 1,776 team results + stats on dev. Does not
        ship. Three-conference narrowing was considered and rejected — we hold all 137 FBS teams,
        so scope reduction saves nothing; the remaining work is surfaces and schema.
        `/root/lp-league-mls-ncaaf/.ralph/request.md` is the governing doc and §4 is now a
        *resumption* list, not a release gate.
      - **MLS: complete on dev, absent from prod.** Dev has coverage + game detail + team stats;
        prod has none of the three, so MLS is HIDDEN there. Promotion is a data job — the code
        already shipped.
      - **The one real gap in either league: MLS has zero `player_stats` on BOTH databases.**
        Everything else on the list is a promotion or a relink; this is the only item needing a
        publisher decision.
      Backlog items 6–12, 21–25.
- [ ] **Tournament games under their own league key** (decided 2026-08-06) — Leagues Cup
      (`concacaf.leagues.cup`), CCC (`concacaf.champions`), Campeones Cup are SEPARATE ESPN
      league slugs; file their logs under their own league key so MLS regular-season denominators
      stay clean (a Leagues Cup goal must not inflate `games_played` for REG). Schedule watcher for
      postponements/reschedules is a SEPARATE mechanism, deferred.
- [ ] **Player detail: year + league selectors** — on an MLS player's page, show one season at a
      time (pre/regular/post for that league) with dropdowns to switch year or league (MLS,
      Leagues Cup, CCC...). Keys off `position_group` so a GK surface shows saves, not shots.

## NEXT — before drafts (3-5 weeks), ordered by whether a drafter notices

- [ ] **Render `PK` as `K`** — storage is right; the UI leaks the publisher's code into the filter chips
      (`useNflDraftBoard.ts:10`, `NflDraftRoom.tsx:93`, `PlayerDetailOverlay.tsx:78`, `MockDraft/columns.tsx:43`)
- [ ] **Fullbacks missing from the board** — `ingest_nfl_season_stats.py:30` filters `{QB,RB,WR,TE}`,
      so Kyle Juszczyk has **zero** `player_stats` rows and an RB filter drops 18 active FBs
- [ ] **Draft-research screens** — what the one real user asked for, still unbuilt
- [ ] Only then: more data hygiene

### Release-blocking, added 2026-08-12

Not draft work, but v0.8.0 cannot honestly ship past them. Full detail in
`docs/BACKLOG-holes.md`; these are the ones where the release notes claim something
production does not have.

- [ ] **Prod news is empty** (#1). The release headlines the news engine; prod has 0 rows.
- [ ] **MLS is hidden on prod** (#6). The release calls out MLS; prod has no coverage row,
      no team results, no team stats — so nobody sees it.
- [ ] **Settled props are unreachable or absent** (#21–23). MLB has 57,392 settled props on
      dev that no game page can reach; UFC and MLS settle **zero** of their props. The board
      shows a line and never says how it landed, which is the half of the product that
      demonstrates the lines were worth reading.
- [ ] **Relink `prop_games`** (#3, #4, #5, #21) — one root cause behind four items. Blocked
      on the ESPN host recovering; the matcher and the budget guards already landed
      (`b8886e9`).

#### Corrected 2026-08-14 — the two items above were measured, and both were wrong

Kept as written above so the reasoning stays legible; read these instead.

- **"Blocked on the ESPN host recovering" is false, and was false when written.**
  `site.web.api.espn.com` answers 200 and is the host `link_prop_games.py` actually
  uses (`espn_client.py:97`). `sports.core.api.espn.com` is the one still 403, and
  the linker never touches it. Nothing was blocked; the linker had simply never been
  re-run after `b8886e9`.
- **MLS: now 15/15 linked** on dev (`025ee05`). The remaining cause was not the host
  but a vocabulary gap — Bovada and ESPN spell 8 of 13 clubs differently. A second
  vocabulary bug in the MLB map (`CWS` for a repo that is canonically `CHW`, plus a
  retired `OAK`) is fixed in `ece6b9d`.
- **"MLB has 57,392 settled props no game page can reach" misreads the number.**
  MLB settles 747,498 on dev and 690,106 of those ARE reachable; 57,392 is the 7.7%
  remainder. MLB was never the problem here.
- **The real finding is worse and applies to every league.** `settlement.py` stamps
  `settled_at` on a prop it could not map and leaves `hit`/`actual_value` NULL, so a
  FAILED settlement is stored in the same shape as a landed one. Every "settled
  props" count ever taken — this roadmap's, `league_feature_matrix.py`'s, and the
  report that produced this correction — counted failures as successes:

  | league | rows with `settled_at` | rows with a real outcome |
  |---|---|---|
  | wc | 1,128 | **0** |
  | mlb (dev) | 747,498 | 642,348 |
  | mlb (prod) | 700,549 | **421,145** |

  So the World Cup settles nothing and has been reported at 100% throughout, and
  40% of production MLB is empty. **MLB is the only league that settles anything at
  all.** The read side is fixed (`f1604e6` — the matrix now requires
  `hit IS NOT NULL`); the write side is open.
- **And an unmappable prop is currently unsettleable forever.** `settle_props.py`
  selects games `HAVING settled_props < total_props` against `prop_results`, so a
  prop stamped with a NULL outcome is permanently excluded from retry — adding the
  market mapping it was missing will not bring it back. This needs deciding before
  any league's settlement is called fixed.
- **ATP and WTA are empty shells**, not a linking gap: 206 `prop_games` between them
  and **zero** `props` rows. Both are HIDDEN, so not release-blocking, but the
  linked/total counts in this document read as partial coverage of something that
  does not exist.

### Added 2026-08-14 — the request path is doing expensive upstream work

Two tasks opened the same day from the same root cause: **work that should be scheduled is
happening on the page request instead.** One costs availability (ESPN), the other costs money
(DeepSeek).

- [ ] **`/scores` rebuilt on the ESPN model** → `TASK-scores-schedule-espn-model.md`.
      Measured: the schedule has **no DB path** and never has (`7668c5e`, June 2025). Every
      schedule read is a live ESPN call; the board fans out to **11 leagues × a two-day
      window = up to 22 upstream calls for one day change**; `schedule-dates` walks up to 8
      ranges sequentially (1.1s in-season, worse out of season). DB-backed `strength` answers
      in **0.10s** against 0.56–1.11s for anything touching ESPN — that gap is the finding.

      **Ten minutes of ESPN refusing on 08-14 took every past-date scores page down.** A
      finished game's score never changes; we should not ask ESPN for it twice. The work:
      completed days become **DB-primary** (not the fallback `ec5872e` added), an ESPN-style
      **Top Events** page with a show-all link and no date picker, date navigation that jumps
      to the next day the league **actually has games**, and **week-grouped navigation for
      NFL/NCAAF**. Target: **zero** ESPN requests to load a past date, enforced by a
      request-count gate.

      Two primitives already exist and must be reused, not rebuilt:
      `docs/API-nfl-schedule-weeks-v1.md` (ESPN's own week calendar, live today on
      `pages/leagues/[league].tsx`) and `docs/API-league-schedule-dates-v1.md` (neighbour
      dates that have games).

- [ ] **DeepSeek spend moved off peak — deadline 2026-08-16** →
      `TASK-deepseek-offpeak-scheduling.md`. DeepSeek introduces peak/off-peak billing on
      08-16: peak is **01:00–04:00 and 06:00–10:00 UTC**, and off-peak is **half price** on
      both `v4-flash` and `v4-pro` (verified against their pricing docs, not remembered).

      Measured: **4 of 10 scheduled DeepSeek runs/day land in peak**, including both news
      timers at 100% (08:35 and 09:20 UTC) and 3 of 8 `game-recaps` sweeps — the latter being
      our largest consumer (`deepseek-v4-pro`, `max_tokens=8000`, high reasoning effort, per
      game). Timers are written in **local** time, so the November CST switch will walk them
      into peak silently; they must be pinned in **UTC**.

      And scheduling alone is not enough: `kick_game_stories()` in `routers/games.py` fires
      `v4-pro` from the **request path** whenever a user loads a scoreboard, so page traffic
      generates uncontrolled spend at any hour. That moves to a queue.

      Not in scope, verified so nobody re-checks: `run_pipeline.py` has no LLM step, and
      `news-x` (`ingest_league_news.py --x-only`) makes no DeepSeek call.

- [x] **`/scores` previous-day bug + the 500** — fixed in `ec5872e` (`/root/lp-scores-prev-day`),
      **awaiting merge**, not in prod. Was not stale games persisting: the arrow moved the date
      correctly and all 11 fetches 500'd, rendering an empty board. `get_games` caught only
      `ValueError`, so any publisher refusal reached the user as `Internal Server Error`. Also
      fixed a date-only comparison that rolled the prior day backward in Central time. This is
      the floor the task above builds on, not a replacement for it.

## POST-DRAFT — league news engine (POC, decided 2026-08-06)

> **STATUS 2026-08-12 — BUILT, and empty in production.** This stopped being a POC: it
> ships in v0.8.0 with topic-matched cards, conversation grouping, topic discovery, an
> editor feedback loop, and a trust model rewritten after a card asserted a false Messi
> suspension. Dev holds **3,908 news items** across 7 leagues.
>
> **`news_items` on prod is empty for every league.** The headline feature of the release
> has nothing behind it there. Backlog #1, and it gates calling the release done.
>
> The bullets below are the original POC plan, kept for the reasoning. Read the v0.8.0
> CHANGELOG section for what was actually built — in particular the part the plan did not
> anticipate: most of the work was deciding what a card is *allowed to say*.

Not draft-serving — this window belongs to fantasy drafts. On the roadmap now
because the POC is small and the narrative signal is time-sensitive.

- [ ] **Per-league AI news** — two layers per league: (1) the league's dominant
      narrative — what actually matters right now (MLB: the Dodgers' "Avengers"
      superteam and the salary cap/floor debate — "does baseball need saving?";
      MLS: relegation/promotion, the post-Messi competitive-balance story; NCAAF:
      SEC vs Big Ten consolidation — "is the SEC about to lead the NCAA?");
      (2) granular events: trades, staff decisions (firings/hirings), injuries to
      key/notable players.
- [ ] **News page in top-level nav** — Home tab is the catch-all across leagues;
      per-league tabs (NFL, MLB, MLS, NCAAF…) land eventually. One feed, split
      by the classifier's league tag.
- [ ] **POC first** — prove narrative detection + granular capture on one or two
      leagues before building the pipeline. Judge against the signal, not the
      output.
- [ ] **Signal sources — verified 2026-08-06** — X/Twitter (the Underdog league
      accounts) is locked, but the ecosystem is on Bluesky: post search works
      without auth (narrative queries return real strategy chatter) and full
      author feeds pull unauth too. Active accounts: @awfulannouncing (37.9k
      posts), @theathletic.com (17k), @sbnation (1.3k). Underdog's own accounts
      are registered-but-dormant (0 posts); the live Underdog signal is
      @underdogtracker (280 posts) + Underdog CPO @wsul + keyword search. RSS
      verified: ESPN news API (nfl / mlb / usa.1 / college-football), SB Nation
      network (/rss/index.xml + team blogs), Awful Announcing (/feed), FanSided
      (/feed/), Deadspin (/rss — carries injuries/extensions/suspensions).
      Not usable: The Athletic (paywall + robots bans AI scraping), Bleacher
      Report (no RSS, /api disallowed), Yahoo (429). Google News RSS as the
      universal fallback. Pick the mix when the POC starts.

## LATER — deferred on purpose

- [ ] **Source-separated tables** (`espn_core_*` / `espn_fantasy_*`) — **November, not now.** Do the
      `players_human` *view* first and measure whether the physical split is needed at all. A
      half-migrated read surface during draft season manufactures the defect class it exists to prevent.
- [ ] NBA 269 split identities — `merge_nba_identities.py` written and tested; apply via the ledger
- [ ] NFL 2024 game-id vocabulary migration — deliberately deferred, not shown in the frontend
- [ ] MLB: 767 Statcast batting rows for players MLB publishes no 2026 line for. **An open question,
      not a known gap** — Statcast is MLB's own data, so why do we hold them?
- [ ] 168 pre-existing orphans (`props` 78, `roster_snap` 90)
- [ ] `atp`, `wnba`, `wta` — no MANIFEST entry, therefore unmeasured, not passing.
      **Root cause found 2026-08-12, and it is not the manifest.** Bovada serves ATP/WTA
      markets and `_parse_tennis_props` reads them correctly (moneyline, total games, set
      betting, win-a-set). Every prop is then discarded at ingest because `players` holds
      **zero atp/wta rows**, so `_resolve_player_for_ingest` cannot attach them to anyone and
      correctly refuses to invent a player. 169 names sit in `unresolved_players` — Swiatek
      rejected 244 times, Gauff 238. The result is 101 `prop_games` with **0 props**, and a
      scrape that reports `0 ingested` rather than an error. `espn_client` already has `atp`
      and `wta` configured, so the fix is one athlete-spine ingest, not a parser change.
      Backlog #2 and #20.
- [ ] **Who is actually playing — soccer availability before kickoff** (raised 2026-08-10, own
      session). The news engine surfaces absences after the fact; the game detail page should say
      who is out BEFORE the match. Soccer is the hard case and the valuable one: there is no
      questionable/doubtful convention the way the NFL has one and the NBA has an injury report, so
      an MLS or Leagues Cup starter can vanish at the last minute for an international call-up, a
      rest day, or something no one saw coming — Messi missing the Monterrey match after his
      father's death, Suárez serving a six-game Leagues Cup ban that Micah only discovered mid-match.
      Unknown whether ESPN simply does not display it, whether the reporting rules differ, or whether
      nobody publishes it via an API at all; establishing which of those is true is step one. The
      signal we already collect is close — @UnderdogNFL posts practice and availability notes all day
      — we file it as history instead of serving it as a heads-up.

## The rules this was learned under

1. **A fix on dev is not a fix.** Seven defects reached three releases because prod was never re-run,
   and both databases answered 200 throughout.
2. **Presence is not coverage.** Three checks passed on broken data — one row in 500, or one populated
   row out of thousands, read as green.
3. **A gap is a statement about which endpoint you asked.** Every "nobody publishes this" here has been wrong.
4. **One column, one vocabulary, one publisher.** Two writers with no arbitration means whichever ran last owns the row.
5. **Never repair identity by name match.** That is what caused the damage in the first place.
6. **UNVERIFIED is a failure, not a skip.** "Nobody wrote a manifest" and "the data is fine" must not look the same.

---

# Ledger

Running list. Add to it, don't rewrite it — mark items superseded rather than deleting,
so the reasoning stays readable.

Last updated 2026-08-06.

---

## League news engine — 2026-08-06

Micah wants AI-generated per-league news that (1) understands each league's
dominant narrative and (2) captures trades, staff decisions, and injuries to
notable players, bubbling per-league → homepage feed. Anchored on his own
Innovative Hype articles: the Messi/MLS piece (competitive balance, the
Jordan-style deal, a new era for MLS) and the CFB piece (playoff legitimacy,
bowl bloat, ESPN's bowl monopoly, super-conference consolidation). Status: POC.
The ideal strategy signal — X/Twitter's Underdog Sports league accounts — is
unreachable (search locked down); verified ESPN's news API per league as the
base source, Google News RSS as an auth-free narrative tracker. Full entry in
the POST-DRAFT section above.

**Update, same day — Bluesky verified as the X workaround.** Post search works
without auth and narrative queries return real strategy chatter; full author
feeds pull unauthenticated too. Active official accounts: @awfulannouncing
(37.9k posts), @theathletic.com (17k), @sbnation (1.3k). Underdog's own accounts
are registered-but-dormant (0 posts each) — the live Underdog signal is
@underdogtracker (280 posts, fan-run) + Underdog CPO @wsul + keyword search.
RSS article pull verified: SB Nation network, Awful Announcing, FanSided,
Deadspin (/rss, carries injuries/extensions/suspensions), plus the ESPN news
API. The Athletic (paywall + robots bans AI/LLM scraping), Bleacher Report (no
RSS, /api disallowed), and Yahoo (429) are not usable directly — Google News
RSS covers them as a fallback. Checklist entry updated accordingly.

**Nav model corrected same day (Micah):** the news surface is a top-level-nav
News page — Home tab is the catch-all across leagues, per-league tabs come
eventually. Not per-league pages + homepage feed. Updated the checklist bullet
and PLAN §1/§4.

**Wired to dev 2026-08-06:** `news_items` table + collector
(`backend/ingest_league_news.py` — ESPN/RSS/Bluesky, fail-fast per the ESPN
doctrine, disk-cached re-runs) + `/api/news`, `/api/news/narratives`,
`/api/news/{league}` + top-nav News page (Home catch-all + per-league tabs).
Live on :8096/:3096, 302 rows in picks.dev.db. 13/13 tests green. Caveats:
ESPN news returns ~1 article/league (thin but real); SB Nation is Atom (parser
handles it now); NBA/NHL narrative signal is weak so far — that's the test
Micah plans to run (he gives the narrative for some leagues, we find the rest).

---

## User evidence — 2026-07-26

First conversation with a potential user, and the first outside signal this roadmap has.

- Pitching **"the app" in general was hard. Pitching NFL was easy.** The framing problem is
  a scope problem.
- **She had no place she went to do draft research.** Not "she prefers a competitor" — no
  incumbent at all. That vacancy is what the board fills.
- **The v0.6.9 availability UX landed on a first-time viewer**: she could scan and see who
  misses games. Accent-marks-absence did its job on someone who'd never had it explained.

**Consequence: R6 moves up.** It was scheduled after v0.7.0, decided before anyone was
asking for the board. She cannot reach it — prod is v0.6.7 and the board is dev-only behind
a trycloudflare URL. Everything else on this list is an improvement to something no user
can open. See R7, R8.

---

## SUPERSEDED 2026-07-27 (later) — see "Build order" below

> **The single-cut plan below was replaced by Micah the same day.** A and D now ship as
> **two separate tagged releases**, and the prod deploy follows both. The scope of A and D
> themselves is unchanged — only the packaging and sequence. Read the next section first;
> everything under this heading is kept for the reasoning, not the plan.

## Build order — set 2026-07-27 (current)

1. **Push `feat/nfl-allday`** once Hermes' alias table lands.
2. **Slice A** — draft notes to the server, keyed by `device_id`. → **tag a release.**
3. **Slice D** — single-player mock draft vs ADP bots. → **tag a release.**
4. **Prod deploy (R6).**
5. **Data subscription**, which **coincides with accounts (slice B)** — the same auth build
   supplies billing identity, the sign-up gate, *and* **multiplayer mock drafts**.

Why the split: A and D are each a real feature, so each earns its own tag under the
feature-releases-only rule, and A reaching prod does not have to wait on D being finished.

**~~Open, not yet decided:~~ — neither of these was ever open. Corrected 2026-07-27.**

- ~~Version numbers.~~ **Already decided, and written in two places**: `SPEC-accounts-and-
  mock-draft.md` §6 ("v0.7.0 = A + D single-player + the NFL schedule API, then a prod
  deploy. v0.8.0 = B + C + multiplayer") and this file's own v0.7.0 section. **A and D both
  ship v0.7.0; B and C are v0.8.0.** The renumbering floated above (D = v0.8.0, accounts =
  v0.9.0) contradicted a decision Micah had already stated repeatedly — do not re-open it.
- ~~Where R4 goes.~~ **R4 is the third item of v0.7.0**, per the same section. Not homeless.

The two-tag split still stands for *packaging*: A can be tagged and deployed without waiting
on D. What it does not do is change what v0.8.0 means.

Sequencing note: this puts the **acquisition surface** (mock draft) in front of users before
the **monetisation** (subscription), which is what `POSITIONING-2026-07-27.md` §6 and §10
argue for — the subscription needs accounts anyway, and accounts are what make multiplayer
possible, so one auth build pays for all three.

---

## v0.7.0 — scope locked 2026-07-27 (SUPERSEDED as one cut — see above)

Cut as one release, then **deploy to prod (R6)**. Three things:

1. **Slice A** — draft notes to the server, keyed by `device_id`
   (`SPEC-accounts-and-mock-draft.md` §6). Closes R8.
2. **Slice D, single-player** — mock draft vs. ADP bots. 12×15 snake, QB/RB/WR/TE/K + FLEX,
   no D/ST, no IDP.
3. **NFL schedule 2026 through the API** — R4. Nothing loaded on 2026-07-27 is visible in
   the UI today.

v0.6.10 (draft board search) already shipped ahead of this and is not part of it.

### Two things this scope does not resolve

- **DECIDED 2026-07-27: the mock draft ships UNGATED in v0.7.0.** Accounts (slice B) ship
  with **multiplayer** mock draft as **v0.8.0**, and the sign-up gate arrives with them.
  This gets a single-player draft in front of people inside the draft window and measures
  whether anyone finishes one before we make it cost something.
- ~~R4 depends on the B2/B3 key-scheme decision~~ — **B2/B3 DECIDED 2026-07-27, see below.**
  nflverse stays canonical and 2025 gets migrated. R4 is unblocked.

### Calendar
Drafts run mid-Aug → **Labor Day, Sept 5–7**; week 1 opens **Sept 9**. v0.7.0 has to be in
prod by roughly **Aug 22** for the mock draft to matter this season.

---

## Now — v0.7.0 (detail)

### R7. Player search on the draft board — **user-blocking**
522 eligible players, 50 per page, and the only controls are a position filter, a sort, and
prev/next. Draft research is name-driven — "what about Rashee Rice" — and today that means
paging. A search input over the board is the smallest change that makes it usable for the
thing she described doing.

### R9. Accounts, with the mock draft as the reason to make one
Spec written 2026-07-27: **`docs/SPEC-accounts-and-mock-draft.md`**. Gate a mock draft behind
sign-up; nudge at the moments someone is already investing effort. Supersedes R8's "label it
and move on" option — R8 becomes slice A of the spec.

**Both decisions made 2026-07-27, nothing is blocked**: v1 is **solo vs. ADP bots** (an empty
lobby converts nobody, and realtime does not fit before Labor Day), drafting a **12×15 snake,
QB/RB/WR/TE/K + FLEX, no D/ST, no IDP** (**we have no D/ST entity at all**, and only 248
players carry a real ADP against 180 picks). Nudges follow the action, they do not block it.

**The calendar decides the scope**: drafts run mid-Aug → Labor Day (Sept 5–7). Anything that
cannot land by ~Aug 22 is a 2027 feature.

### R8. Decide what happens to a user's draft notes — **folded into R9**
`rank` / `watch` / `fade` persist to `localStorage` under `lp_nfl_draft_notes`. Device-local:
gone on a cache clear, invisible between phone and laptop. Doing the research *is* the
retention hook, so this is the wrong storage for it long-term. Two options — label it
honestly as this-device-only for now, or move it behind an account. **Needs Micah's call;**
the account path is much larger than the label.

### R1. Rebuild `/api/nfl/draft-board` around availability
**The board already exists** (`routers/nfl_offseason.py`, contract `nfl-draft-board-v1`,
511 eligible players). It ranks by `fantasy_ppr_g` — points per *game played* — which is an
average conditioned on the player being healthy enough to play, i.e. the exact thing you
were trying to predict. It also ships `season_proj_pts = projection * games_assumed`, so it
already calls itself a projection, and `games_assumed` — the availability variable — is
computed internally and never surfaced.

What availability actually is, per Micah: **injuries, suspensions, and legal absences.** The
board's job is to help someone draft accounting for those *and* for snap share. Not a
statistics exercise — a "will this guy be on the field" exercise.

- Surface availability as the headline, not an intermediate.
- Show both numbers: PPR when played, PPR per team game.
- Season strips with visible gaps for missed games; accent colour reserved for absence.
- Stop labelling it a projection.
- Fold in snap share (`off_pct`) — a healthy player in a timeshare is a different risk from
  an injured starter, and the board must distinguish them.
- Scope: QB/RB/WR/TE. See R5 before assuming IDP/K.

### R2. 2024 in the UI without availability
2024 data can render immediately; it does **not** need the availability calculation to be
useful. Don't block the 2024 display on R1.

---

## Bugs caught, not yet fixed

### B8. The player page renders the wrong game-log columns for K and D/ST — **user-reported**
Reported 2026-08-03 as "missing kicker/DEF game logs" and "Brandon Aubrey has 2 games".
**Not a data gap — the data is present and correct and the page renders the wrong columns.**

`pages/player/[id].tsx:191` `NFL_GAMELOG_BANDS` hardcodes four bands — Passing, Rushing,
Receiving, Fantasy. **No Kicking, no Defense.** Line 245 keeps only bands holding a
non-zero value, then `if (!bands.length) return null`. Measured on dev:

| player | returning | displaying |
|---|---|---|
| Aubrey (882, PK) | 17 games, `fg_made 4, fg_att 6, fg_long 41, pat 2/2` | 17 rows of `WK OPP CAR YDS TD FPTS PPR` — **rushing**; 16 rows all dashes, **one** populated (wk 15, 1 carry) |
| Borregales (2217, PK) | 17 games | **no table at all** — zero carries, so no band matches |
| NO D/ST (30116, DEF) | `recent_games: []` | **no Game Log section** — `player_game_logs` has zero DEF rows, ever |

The single populated row is the reported "2 games".

The backend already publishes the right contract — `/api/nfl/draft/player/{id}/game-log`
returns `tabs=[Kicking]` with `fg_made/fg_att/fg_long/pat_made/pat_att` for 882/2217 and
`tabs=[Defense]` with `sacks/interceptions/fumble_rec/safeties/points_allowed` for 30116.
The player page maintains a second, worse copy of the same idea. Two constraints on the
fix: the page renders **three phase tables** (post/regular/pre) that a wholesale swap to
`PlayerGameLog` would delete, and D/ST needs `/api/player/{id}` to read `nfl_dst_stats`
before any band change can matter.

Also surfaced: **`K` is a live second kicker vocabulary.** `players` holds 336 `K` vs 87
`PK`; 10 `K`-labelled players have 2025 logs (Carlson 17, Prater 17, McManus 15) and the
endpoint returns `tabs: []`, `fields: []`, `stats: {}` for every one. Only 3 names appear
under both labels, so it is a split, not duplication.

**Why the suite stayed green: `REG-render` drives the mock-draft overlay, not
`/player/[id]`.** The gate's surface never included the broken page — the same lesson as
[a green gate is a claim about its surface]. Fix ships with a player-page browser gate
asserting each position sees its own stats *and* that at least one row is non-empty (a
row-count-only assertion passes both failures above).

Delegated: `TASK-reasonix-nfl-gamelog-coverage.md`.

**Not in that task, flagged separately: kicker fantasy points are wrong.** Aubrey's wk-15
row reads `fpts 0.6 / fpts_ppr 0.6` for a game with 4 FG and 2 PAT (~16 kicking points) —
the scoring counts his one carry and ignores every kick, while `pk_pts_per_game` (10.6) is
computed correctly elsewhere. The log and the pool disagree about the same player.

### B1. Mid-season team change doubles the availability denominator
Joe Flacco reads `13/34` for 2025 because he changed teams and the denominator sums both
teams' full seasons. Denominator must be scoped to team games *while the player was on that
team*, or counted as distinct team-games in the season. Found while prototyping the
availability query — this would have shipped a visibly wrong number.

### B2. `team_game_results` has two incompatible key schemes
2025 rows use **ESPN event ids** (`401772718`); 2024 and 2026 rows use **nflverse ids**
(`2026_01_NE_SEA`). Consequences:
- 2025 rows do not join to `nfl_schedule` at all.
- Loading 2025 from `games.csv` naively would add 544 duplicate rows under the second
  scheme, giving 544 distinct game_ids each with 2 rows — **every 2025 game double-counted,
  breaking the team-stats aggregate** (34 games per team instead of 17). Do not do this
  without deduplicating first.

**RESOLVED 2026-07-27 — neither option was necessary. nflverse publishes the ESPN id.**

`games.csv` carries an `espn` column and it is populated for **285/285 of 2025's games**
(verified against the live file; our `nfl_schedule` already stores it, 285/285 for 2024).
The bridge between the two key schemes did not need to be built or repulled — we were
already ingesting it. See [[feedback_check_if_the_value_is_published]]; this is the fourth
time that check has paid off on this table.

Measured, with `league='nfl'` applied:

| season | `team_game_results` keys | rows | joins `nfl_schedule`? |
|---|---|---|---|
| 2024 | nflverse | 570 | **285/285** |
| 2025 | **ESPN** | 544 | no — `nfl_schedule` has no 2025 rows at all |
| 2026 | nflverse | 544 | yes |

**Only 2025 is broken — 544 rows, one season.** (An earlier read that 2026 was ESPN-keyed
was wrong: those numeric ids belong to other leagues. Always apply `league='nfl'`.)

**Decision: nflverse stays canonical; migrate 2025.** `player_game_logs` is nflverse
(11,232 rows), the draft board is nflverse, `nfl_schedule` is nflverse. ESPN is only the
roster/ADP side. Going ESPN-canonical would move the schedule to the opposite side of the
divide from every player number we compute, to avoid re-keying 544 rows.

Three steps, no repull, nothing lost:
1. Load 2025 into `nfl_schedule` from `games.csv` — zero rows there today, so no duplication
   risk. Brings 2025 rest days, roof/surface, spread/total lines, coaches and starting QBs,
   which we do not currently have, plus the `espn` bridge column.
2. **UPDATE** (never INSERT) the 544 `team_game_results` 2025 rows' `game_id` from the ESPN
   id to the nflverse one through that bridge. B2's "544 duplicate rows" trap is an INSERT
   failure mode and does not apply to an UPDATE.
3. The same statement closes **B3**: `LAR→LA`, `WSH→WAS`, using the `ESPN_ALIASES` map that
   already exists in `ingest_nfl_schedule.py`. Confirmed 2025 is the only season using the
   ESPN codes.

Two things found while measuring, neither blocking:
- 2025 holds **regular season only** (272 games); 2024 holds regular + postseason (285).
  Pre-existing inconsistency.
- **2026 carries no ESPN ids yet** — nflverse publishes them closer to gameday, like the
  betting lines in R3. Harmless here since 2026 is already nflverse-keyed, but it matters if
  live scores ever need a 2026 → ESPN mapping.

### B3. Team abbreviations disagree between tables
ESPN says `LAR`/`WSH`; nflverse says `LA`/`WAS`. `player_game_logs` is nflverse,
2025 `team_game_results` is ESPN. **The Rams and Washington already fail to join between
those tables.** Recorded as `ESPN_ALIASES` in `ingest_nfl_schedule.py`. Same decision as B2.

### B4. Three draft-board tests are red for a fixture gap
`test_nfl_offseason_api` × 3 all fail with `sqlite3.OperationalError: no such table:
nfl_adp` — the fixture DB lacks the table. Not a product bug, but they've been red long
enough that nobody reads them. Fix with R1.

### B7. `players.nfl_gsis_id` mixes two id schemes
**651 active NFL players carry an ESPN-style synthetic key** (`LOV121782`,
`TAT143045`) in a column named for gsis. A real gsis is `00-0041027`. Exactly **0**
of the 651 have game logs — they are the players nflverse has never seen through
our ingests, which is to say the rookies and no-signal players the draft board most
needs to say something about. Jeremiyah Love (ADP 17.5, 98% owned) joined to
nothing until this was found.

The pollution originates **upstream**: nflverse's own depth chart carries the same
synthetic keys for players without a gsis yet (e.g. Drew Allar → `ALL015451`), and
our spine was evidently populated from that feed.

`ingest_nfl_depth_charts.py` works around it by falling back to `espn_id`, which
resolves 914/914 rows. That is a workaround in one script, not a repair — every
other nflverse join still silently misses these players.

**Repair available and measured:** `espn_id` bridges 619 of the 651 to a real gsis
in the 2026 depth chart artifact. 26 more have only a synthetic key upstream too
(genuinely no gsis yet — never played a snap); 6 are absent from the artifact. Name
agreement across the bridge is exact but for 6 generational suffixes (`Murvin Kenion`
vs `Murvin Kenion III`), all the same player. Backfilling mutates the identity
spine, so it wants its own change and its own review rather than riding along with
a board feature.

### B5. `test_league_stats_contract` failing
`test_mlb_never_queries_game_logs_and_always_has_no_comparison`. Pre-existing, uninvestigated.

### B6. The 16-row NFL cleanup is not reproducible
The cleanup of 14 rows in 2024 (`source='nflverse'`) and 2 in 2025 (`source='nflverse_pbp'`)
was a one-off manual SQL operation with no script behind it. Documented in
`NFL-DATA-INVENTORY.md`, not repeatable. Confirm `migrate_nfl_stats_to_prod.py` copies dev
rows wholesale — if so the cleaned rows come along and nothing more is needed. **Check
before the prod deploy, not after.**

---

## Mock draft v1 — the gaps, set 2026-07-27 (pt.10)

Slice D is merged and tagged in v0.6.11. **Micah's verdict: it is a proof of concept, not
shippable.** Full detail and evidence in `/root/CONTEXT-2026-07-27-HANDOFF-10.md`.

### M1. D/ST does not exist — **blocking** ✅ **RESOLVED 2026-07-31**
D/ST entity + roster slot: **DONE** (`8234ecb` — SEA D/ST drafts into DEF slot).

D/ST ADP: **ESPN PUBLISHES IT** — all 32 teams carry PPR ranks (234–519) and ownership % (0.5%–98.9%)
in `kona_player_info` view. ESPN keys D/ST with negative IDs (`-16000 - proTeamId`).
Our `ingest_nfl_adp.py` joined on `espn_id` (empty for D/ST) → silent 0/32 match → derived ADP.
**Fix: ingest ESPN's published D/ST PPR ranks instead of deriving.**

*Supersedes ROADMAP B11 and pt.13 finding #6.*

### M2. Availability is computed from a table that cannot express it — **blocking**
`player_game_logs` only holds players who recorded a passing/rushing/receiving stat, so anyone
who played without touching the ball reads as absent. 2025 actives with logs: WR 196/391,
RB 120/192 — but LB 2/385, CB 0/333, DT 1/272, **PK 1/42**. Fix: **`nfl_snap_counts` as its own
table**, all positions, all weeks; availability reads that. **Do not rewrite
`player_game_logs`** — decided against 2026-07-27. `ingest_nfl_snap_counts.py:16,101` already
downloads the file and discards every non-skill presence row.

### M3. Familiar UX — six missing objects
Position/team/bye filters · queue · draft-board grid (teams x rounds) · "your next pick"
counter · Draft button on the row (today the whole `<tr>` is the click target) · clock.
⛔ **Familiar structure does not override SPEC-slice-D §6.2** — amber marks absence and may not
be borrowed for turn/pick/run highlighting. Incumbents colour-code grid cells by position;
ours uses position chips and two-tone fills.

### M4. Resume and share are both dead
`pages/mock-draft.tsx:70-79` fetches the draft then discards the response, and returns early
on `status === 'complete'`. Separately `GET /api/nfl/mock-draft/{id}` is device-scoped
(`nfl_mock_draft.py:355`), so a shared link could never resolve for a recipient. Resume is
~30 lines client-side. Share needs a public read for completed drafts (precedent:
`nfl_mock_draft.py:133`) **or** accounts per R9 — product call. The results screen now shows a
disabled "Get a link / Coming soon" instead of a dead URL.

### M5. Player detail overlay
Click the row for projections, last season's game log, injury status — **and the WR's QB**.
The row shows a team code and nothing else; who throws to him is the actual draft question.

### M6. Camp card becomes the resume state
Once a draft is in progress, the `/leagues/nfl` entry card should read "Resume your mock draft
— Round 4, pick 41" instead of the start pitch. Blocked on M4.

### M7. Room polish
`DraftRoom.tsx:111` hides the scrollbar on a 292-row list inside a fixed-height container on a
page that does not scroll — it looks like the pool has 10 players. Roster panel spends 7 of 15
rows on empty bench slots. `:255` hardcodes `TEAM_GAMES - games_played` instead of the API's
`games_missed` (will break under B1).

---

## Mock draft v1 — scored 2026-07-28 (pt.14)

Branch `feat/dst-and-mock-draft`, 55 ahead / 0 behind `dev`. Nothing merged, nothing pushed.
**State of the work is one command**, not this table:

```bash
bash /root/lp-team-vocab/verify-gates.sh all      # 14 gates; LP_GATE_W/B/F to retarget
```

The gate suite is the scoreboard. Where this document and a gate disagree, the gate wins.

| item | pt.13 | now | how it was checked |
|---|---|---|---|
| M1 D/ST | UI renders it | **UI renders it + has a starting roster slot** (`8234ecb`) | browser: drafting SEA D/ST lands in DEF, not the bench |
| M2 availability from snaps | done | done | A1/A2 |
| M3 six objects | 6/6 committed, **never tested** | 6/6 **and the tests actually ran** — 36/36 | jest was SIGBUS-dead 01:54→08:00 |
| M4 resume/share | scratched | scratched (Micah, 2026-07-28) | — |
| M5 overlay | built | built | B2 |
| M6 camp card | blocked on M4 | out | — |
| M7 polish | B4 green | scrollbar ✓, bench 7→6 ✓, **`TEAM_GAMES` still hardcoded** | see B14 |
| B8/B9/B10 | fixed | fixed | A1b / B1 / A1+A2 |

**The mock draft has now been opened in a browser** — for the first time. It works: pool,
filters, queue, board grid, ledger, roster, results screen, zero console errors.

### B11. D/ST ADP is published; we derived it instead — **open, delegated (job15)**
`nfl_mock_draft.py:314` says *"D/ST — no published ADP exists. Derive ranking from fantasy
totals."* **Measured 2026-07-28: false.** All 32 carry a published ADP in the payload
`ingest_nfl_adp.py` already downloads (DEN 89.94, HOU 91.81, LAR 98.19, SEA 106.50). ESPN keys
D/ST with **negative** ids (`-16000 - proTeamId`) and all 32 `players.espn_id` are empty, so the
join matched **0 of 32** — a silent miss, papered over with a derivation. The derivation also
disagrees with the published order: it ranks SEA #1, ESPN ranks DEN #1 and SEA 4th.
**This retires M1's "(b) D/ST ADP" gap and voids pt.13 finding #6** — the choice between pool
index 150 and 268 was a choice between two fabrications. Spec:
`TASK-job15-dst-published-adp.md`. Gate `REG-adp-dst` is committed **RED** with the expected
numbers written before the code (`b8cc4b1`).

### B12. The camp-tab draft board was never wired to its hook — **FIXED `77de2f1`**
`/leagues/nfl?tab=camp` rendered "Draft board unavailable." `NflDraftRoom` is presentational
and takes `data`/`loading`/`error`/…, but the page rendered `<NflDraftRoom enabled={…} />` and
**`useNflDraftBoard` was never called**. Filed in pt.13 as a cosmetic `TS2322`; it was the bug.
`next.config.js:9` sets `typescript: { ignoreBuildErrors: true }`, so the only signal that
would have caught it is configured off. **Corrects pt.13 §4 item 3:** the `TS2802` errors
cannot break a production build for the same reason — and the identical error already exists
pre-branch at `pages/scores.tsx:305`.

### B13. The draft clock was a deadlock, not a decoration — **FIXED `1a46101`**
The 30s countdown reached 0:00 and stopped; nothing picked. Measured: the draft sat on pick 6
indefinitely, so anyone who stepped away had a dead page. `autopick()` already existed in the
engine documenting this exact caller. Now picks from the queue first, else best-available with
zero jitter, recorded `auto: true`. Two ordering traps found only by watching a real draft:
`userTurn` does not change between consecutive user turns (one timeout cascaded through all 180
picks — a full draft in 40s), and a stale `seconds` on the turn-change render fired twice and
silently skipped the back-to-back snake pick.

### B14. `team_games` is absent from the mock-draft pool payload — **open, small**
`DraftRoom.tsx` falls back to hardcoded `TEAM_GAMES = 17`. The payload has no `team_games`
(`TS2339`) — but it **does** carry `team_weeks`, so this is a rename, not missing data: use
`team_weeks.length`. B4 passes anyway because it greps for `"TEAM_GAMES - "` and the code is
`/{TEAM_GAMES}` — **the gate's pattern is narrower than its claim.** This is M7's third bullet.

### B15. `adp: p.adp ?? 999` fabricates an ADP in the UI — **open, small**
`pages/mock-draft.tsx:107` coerces the API's honest `null` into `999`, which renders as
`999.0` on D/ST rows. The null-renders-as-"—" fix in `74b34fd` is dead code because null never
reaches it. Banned by `honest-data-ui`. Resolves itself once B11 lands a real ADP, but the
coercion should go regardless.

### B16. Two jest suites fail and no gate covers them — **open**
`components/Game/WCContext.test.tsx` — 2 failures in WC live-context polling. Pre-existing (the
import graph is disjoint from MockDraft) and invisible for two reasons at once: jest has been
dead since 01:54, **and** `REG-jest` only runs `--testPathPattern='lib/mockDraft'`.

### The gate gap that outranks all of the above
Eight gates were green while the pool table crashed on first render. Every one was true; none
of them rendered React. `REG-render` — a Playwright smoke gate that loads `/mock-draft` and
`/leagues/nfl?tab=camp` and fails on any console or page error — is the highest-value
un-started item on this list. Both bugs above (B12, B13) were found by hand-driving a browser,
which is exactly the thing no gate does.

---

## Tasks for Reasonix (v0.7.0 scope — Aug 22 deadline)

### T1. Fix D/ST ADP ingestion — use ESPN published PPR ranks
**Worktree:** `/root/lp-v0613-recut` (branch `recut/v0.6.13`)
**File:** `backend/ingest_nfl_adp.py`
**Problem:** Current code joins on `espn_id` which is empty for D/ST → 0/32 match → derives ADP from fantasy totals.
**Fix:** Join on ESPN's negative D/ST IDs (`-16000 - proTeamId`) to get published PPR ranks.
**Source:** `kona_player_info` view with `limit: 20000` — all 32 D/ST have `draftRanksByRankType.PPR.rank` and `ownership.percentOwned`.
**Gates:**
- `REG-adp-dst` (already RED in repo with expected numbers)
- 32/32 D/ST rows with `adp_ppr` column populated
- Pool endpoint returns D/ST with real ESPN ADP (DEN 234, SEA 239, etc.)

### T2. Expand mock draft pool to full ESPN player universe (11,515 players)
**Worktree:** `/root/lp-v0613-recut` (branch `recut/v0.6.13`)
**Files:** `backend/ingest_nfl_adp.py`, `backend/routers/nfl_mock_draft.py`
**Problem:** Current pool is ~300 players (only drafted/owned). ESPN `kona_player_info` returns 11,515 players including free agents.
**Fix:** 
1. Update `ingest_nfl_adp.py` to fetch with `limit: 20000` (no filter)
2. Store ALL players in `nfl_adp` table (including `percentOwned=0`)
3. Pool endpoint returns full universe; UI filters handle "available" vs "drafted"
**Gates:**
- `nfl_adp` table has ~11,515 rows for 2026
- Pool endpoint `GET /api/nfl/mock-draft/pool?season=2026` returns 11,515 players
- Position breakdown: QB 470, RB 1122, WR 1791, TE 882, K 209, D/ST 32
- Free agents (percentOwned=0) render as "—" in ADP column per honest-data-ui

---

## Bugs caught 2026-07-27 (pt.10)

### B8. Kicker game data does not exist; Brandon Aubrey renders a false figure
One row across all 42 active kickers, and it exists because Aubrey **ran the ball once on a
fake** (`{"carries": 1, "rush_yds": 6}`). He renders `1/17 — missed 16`, which is wrong. The
`sample === 'none'` guard that would show "Kicker games not tracked" is bypassed because one
row makes him `'thin'`. **Micah's call: do not relabel him — ingest kicking data.** Answers
the K half of R5. Listed under Known gaps in the v0.6.11 changelog.

### B9. `players.position` has the same two-vocabulary split as `players.team`
`PK` (42 rows, **all active**, all with espn_id) is ESPN's placekicker code — confirmed from
the live roster endpoint; the punter is plain `P`. `K` holds 336 rows, **0 active**. So
`position='K' AND active=1` silently returns nothing. Same for `OLB`/`FS`/`NT`/`ILB`/`MLB`/
`SAF`/`OL`. `backend/team_codes.py` (still unwritten) should grow a `positions` sibling.

### B10. Playoff rows in `player_game_logs` are unmarked
Weeks 19-22 sit alongside regular-season rows with no flag. They drop out of `games_played`
only because they do not intersect `team_weeks` — there is no explicit filter, so the
correctness is incidental. Anything counting rows directly gets 20 games for Stafford.

---

## Next

### R3. Snapshot betting lines and ADP daily
Two datasets that only become useful as a series:
- `nfl_schedule` has spread/total/moneylines for only **51 of 272** 2026 games (weeks 1–3
  plus 3 games in week 4) — books post the near slate only, and it fills in over time.
- `nfl_adp` is a single snapshot, so actual draft timing is still an assumption.

Snapshot both daily and draft timing becomes measurable in ~2 weeks, before the Labor Day
peak (Sept 5–7). Week 1 opens **2026-09-09**.

### R4. Expose `nfl_schedule` through the API
The table has **zero API exposure** — `/api/nfl/schedule-week[s]` call `espn.nfl_schedule_weeks`
live and never read it. So nothing loaded on 2026-07-27 is visible in the UI. Needed for
week-1 matchup context, rest days, roof/surface, and the weeks 1–3 lines. Depends on the
B2/B3 decision.

### R5. Decide `--all-positions` for IDP and kickers — **needs Micah's call**
`ingest_nfl_weekly_stats.py --all-positions` has never been run. The DB holds only offensive
skill positions in real volume (WR 4,489 / RB 2,804 / TE 2,317 / QB 1,389 / FB 161); the tail
(P 20, OT 15, S 14, CB 6, LB 4, PK 1, K 1) is linemen who caught a touchdown, not IDP
coverage. The 2025 artifact has **~19,400 player-weeks against our 5,635**, so ~13,800
defensive and kicking rows exist upstream. If IDP/K leagues are in scope this ingest run is
a prerequisite, not a UI change.

### R6. Deploy to prod — **after v0.7.0**, per Micah
Prod is on v0.6.7 serving pre-swap NFL numbers, no 2025 postseason, no 2026 schedule.
Needs `migrate_nfl_stats_to_prod.py` plus the `nfl_schedule` table, which does not exist in
prod. Blocked on B6 and R1.

---

## Ops

### O1. Reduce to two servers — **DONE 2026-07-27**
Four were running; we wanted **prod and dev**. Two of the four turned out to be zombies:
`/root/lp-ufc-fight-stats` had been **deleted from disk** while its servers kept running out
of the deleted directory (`readlink /proc/PID/cwd` → `(deleted)`). `:3095` was serving 500.

| port | pid | what | outcome |
|---|---|---|---|
| 8095 | 3916288 | uvicorn, cwd `/root/lp-ufc-fight-stats/backend` **(deleted)** | killed |
| 3095 | 3907514 | next dev, cwd `/root/lp-ufc-fight-stats` **(deleted)**, 500 | killed |
| 8096 | 3878741 | uvicorn, cwd `/root/legendarypicks/backend`, absolute `LP_DB_PATH` | **kept — dev backend** |
| 3096 | 160173  | next dev, cwd `/root/legendarypicks` | **kept — dev frontend** |

`:8000` (`--host 0.0.0.0`) is prod and was never in scope.

**Lesson:** a port table is not evidence of which checkout a server belongs to. Check
`/proc/PID/cwd` for `(deleted)` before treating a listening port as a real environment.

### O2. Tunnel — **NOT A BUG, closed 2026-07-27**
The premise ("points at the wrong frontend") was wrong. `:3096` is the *correct* frontend:
its proxy target comes from `.env.local` (`API_PROXY_TARGET=http://localhost:8096`), not the
process environment, which is why `/proc/PID/environ` showed nothing. `next.config.js` logs
the resolved target at startup — grep the dev log for `[next.config.js] API proxy target:`
instead of inferring it.

`https://someone-decorative-wearing-produce.trycloudflare.com` (pid 3928058, up since 07-23)
returns 200 with real app content and a working `/api/*` proxy. **Deliberately not
refreshed** — restarting would mint a new URL and break a working one. Micah was most likely
holding the dead `cf3095` URL from 07-14.

Note: a fresh trycloudflare URL returns NXDOMAIN *from this box* but is live externally —
verify with a pinned IP, don't restart cloudflared on that signal alone.

### O3. `:8096` CPU — **still open, and no longer moot**
67% CPU is uvicorn's `--reload` supervisor stat()ing 5,861 files 4×/sec, 5,733 of them in
`venv/`. `watchfiles==0.24.0` installed. Restart script written, **never run**. O1 did *not*
make this moot — `:8096` is the survivor, so this is now the dev backend burning the CPU.
`--reload-exclude` must be an **absolute** path; relative patterns silently exclude nothing.

---

## 2026-07-28 (09:1x) — user report from mobile, and why the roadmap "isn't done"

Micah, on a phone, reported: *the original roadmap from yesterday is still not done · player
rankings need relevant stats per position filter · on the draft room I can't click a player
and its overlay doesn't show up.*

### U0. The roadmap **is** largely done — he cannot see it. Branch/tunnel mismatch.

Measured, not inferred:

| tree | branch | vs `dev` | serves | `PlayerDetailOverlay.tsx` |
|---|---|---|---|---|
| `/root/legendarypicks` | `feat/slice-D-mock-draft` | 0 ahead / **9 behind** | `:3096` → `someone-decorative-wearing-produce` | **absent** |
| `/root/lp-team-vocab` | `feat/dst-and-mock-draft` | **55 ahead** / 0 behind | `:3098` → `altered-era-sold-explain` | present |

`feat/slice-D-mock-draft` is the branch the M1–M7 roadmap was *written* on and it has
received no work since. Every fix from pt.11–pt.14 — D/ST roster slot, the clock deadlock,
the camp-tab draft board, the overlay itself — lives only on `feat/dst-and-mock-draft`,
which is **unpushed and unmerged**. The tunnel Micah has been checking cannot show any of it.

**This is a delivery defect, not a build defect.** Per `deliverable-must-be-visible`: local
commits behind a URL nobody is looking at are not shipped. Fix is one of — merge to `dev`
and let `:3096` serve it, or hand him `altered-era-sold-explain`.

### U1. Position-relevant columns — this is **job14**, spec'd and NOT started
`TASK-job14-position-aware-surfaces.md` (untracked). `NflDraftRoom`'s table renders one
universal column set — PPR/g, PPR/team-game, games, ADP — for every value of the position
filter. A QB row and a K row are identical in shape. ESPN's published gamelog contract, which
job14 measured, shares **zero columns** between a QB and a K. Confirms the spec against a real
user; promote it above B14/B15.

### U2. `/mock-draft` has no player overlay at all — new, distinct from the camp tab
`components/MockDraft/DraftRoom.tsx`: **0 references** to `PlayerDetailOverlay`, and no row
`onClick`. The only clicks on a pool row are the draft and queue buttons. The overlay was
built for `NflDraftRoom` (camp tab, 2 references) and never carried across.

So U2 reproduces on **both** branches, for different reasons: on `:3096` the component does
not exist; on `:3098` it exists but was never wired into the mock draft room. Even after U0
is resolved, U2 stays broken. Owned by me (frontend); Hermes is backend-only.

### Dispatch state
`job15` (D/ST published ADP) worktree is **up**: `/root/lp-job15-dst-published-adp`, branch
`feat/job15-dst-published-adp` off `642259a`, backend `:8093` (`/health` 200), frontend
`:3093` (`/mock-draft` 200), `node_modules` symlink intact at 538 packages. Awaiting Micah's
relay — `messages_send` cannot prompt the agent.

### U1/U2 resolved · B17 opened · audit dispatched — same session

- **U2 fixed (`c92e5df`).** `MockDraft/DraftRoom.tsx` now opens `PlayerDetailOverlay` on a
  row tap. The overlay needed no change: `/api/nfl/draft/player/{id}` resolves the same id
  space the mock draft pool emits (7979 Gibbs 200, 30116 SEA D/ST 200). The row's Draft and
  +Q buttons already called `stopPropagation`, so the row handler was the intended design
  and was simply never added. Verified in chromium at 414×896 — real values, 0 console errors.
- **U1 fixed (`4b21d09`).** Columns and sort pills now come from the position filter.
  The board payload already carried `pk_pts_*`/`dst_pts_*` per position, so this was purely
  a rendering gap. Dead columns per filter, before → after: PK 5→0, DEF 5→1 (ADP, real
  absence), QB 1→0. Sort pills narrowed the same way — sorting 32 kickers by Target share
  reordered nothing — while never hiding the sort actually in effect.
  Verified across five filters in chromium, 0 console errors.
- **B17 opened, folded into job15 (`8220707`).** `/api/nfl/draft/player/30116` returns
  `games_played=0 sample=none` while `/api/nfl/draft-board?position=DEF` returns
  `17 full` for the same SEA D/ST — alongside `dst_pts_per_game=9.6`. `player_detail` has
  no D/ST branch and derives presence from `player_game_logs`, which contains no `DEF` rows
  at all (`SELECT DISTINCT position` over the join returns 25 positions, none of them DEF).
  U2 made this user-visible on all 32 defenses, so it is now urgent rather than latent.
- **job15 §3 was self-contradicting** — it ordered the `dst_rank` block deleted and its
  `games_played`/`weeks_played` fields kept; they are one loop (`nfl_mock_draft.py:332-351`).
  Amended in §6a before Hermes started. **The other TASK specs, job9–job14, have not been
  checked for the same defect and several were executed as written.**
- **Codex audit dispatched.** `AUDIT-BRIEF-FOR-CODEX-2026-07-28.md` (`b8002f9`) — the merge,
  the DB, and the six confirmed false-green failures, with runnable repros. Measured DB
  facts included: D/ST `espn_id` set on **0 of 32** rows, `nfl_adp` carries **0** DEF rows.

Gates after all of the above: 13 PASS, `REG-adp-dst` RED on purpose. No regression.

---

## 2026-07-29 — v0.6.13 re-cut and cross-league v1 data plan (CURRENT)

This section records the decisions and work from the two Codex sessions:

- `019fadbf-a05d-72d1-89c0-2de6d1718414` — whole-application readiness,
  other-league review, and backend-data implementation;
- `019fae3b-aa03-7fb0-b99d-9eb41c0253d3` — DEV landing, verification boundary,
  and decision to continue league by league.

Companion evidence:

- `/root/CODEX-V0.6.13-WHOLE-APP-READINESS-AUDIT-2026-07-29.md`
- `/root/CODEX-V0.6.13-OTHER-LEAGUE-DATA-PATH-REVIEW-2026-07-29.md`
- `/root/CODEX-V0.6.13-RECUT-PLAN-2026-07-29.md`
- `docs/V0613-PLAYER-IDENTITY-AND-LEAGUE-STATS.md`

### Decisions locked

1. **Re-cut v0.6.13; do not create v0.6.14 to hide an unworthy tag.**
   The current tag remains provisional and production remains NO-GO until the
   whole-application clone and browser gates pass.
2. **Acceptance is whole-application, not NFL-only.** Production is still on
   v0.6.7, so the re-cut must keep every exposed major surface alive across the
   accumulated release—not merely prove the mock-draft path.
3. **Build and verify the v1 contract, not obsolete v0 fixture assumptions.**
   Each new slice gets purpose-built v1 tests written with the feature, relevant
   regression tests, and production-shaped API/clone evidence where needed.
   An unrelated v0 test failure is not a blocker unless it reproduces against a
   required v1 behavior. Do not spend the schedule modernizing superseded tests.
4. **Proceed league by league in this order: NBA → NHL → NFL.** MLB's production
   identity repair is a separate data-migration gate and does not block building
   the other league slices. DEV already has zero duplicate MLBAM groups.
5. **Code landing, DEV data migration, and production promotion are separate
   states.** A green commit on `dev` does not authorize a live database write,
   tag move, push, service restart, or production deployment.

### Shared v1 backend foundation — **LANDED ON LOCAL `dev`**

Commit `4394bb8` (`fix(data): canonicalize league stats and roster identity`) was
fast-forwarded onto local `dev` on 2026-07-29. Local `dev` is one commit ahead of
`origin/dev`; it has not been pushed. No managed service or live database was
changed.

The landed contract is:

- `players.id` is the durable person identity.
- A source-native ID must resolve to that person before logs or stats are
  written; missing or ambiguous identities queue instead of creating a
  speculative player.
- `player_stats` is a published display table with one row per
  `(player_id, league, season, stat_type)`, not a multi-source raw lake.
- Leader names and links come from the canonical `players` row.
- The shared game-log reader applies `game_type` only to NFL and preserves
  MLB, NBA, NHL, UFC, and World Cup history.
- A roster is not the person index. `roster_snapshots` stores immutable,
  checksummed release metadata; `roster_memberships` stores canonical
  `players.id` membership. A partial or ambiguous refresh preserves the last
  published snapshot.
- Schema changes are explicit, backup-first migrations that refuse dirty data
  rather than guessing winners.

Published owner of each league's display stats:

| League / season | Canonical owner |
|---|---|
| MLB batting/pitching | Statcast |
| NBA through 2023 | hoopR |
| NBA after 2023 | ESPN published regular-season player table |
| NFL | nflverse weekly rollup |
| NHL | NHL API / nhle.com |

Purpose-built and relevant landed-tree verification passed. The verification
rule above supersedes spending time on unrelated v0 test-order, fixture, or
environment failures.

### Architecture boundary — do not force every product through one pipeline

| Product plane | Contract |
|---|---|
| MLB / NBA / NHL / UFC athletes | Shared canonical `players`, logs, stats, props, profiles |
| Teams and schedules | Stored team results/stats/coverage where published; some request-time ESPN adapters |
| World Cup | Partly shared athlete/log spine, currently dormant; preserve and regression-test |
| Esports | Separate event/match identity, result store, streams, and picks; athlete-spine gates do not apply |

An HTTP 200 from a request-time adapter does not prove the durable player joins
or profile history are correct. Live-source and stored-data evidence must remain
separate.

### Current data gates — code can continue, migration cannot

The canonical `player_stats` migration remains blocked by existing data:

| Gate | DEV | Production |
|---|---:|---:|
| display-name disagreements with `players` | 549 | 176 |
| duplicate canonical keys | 703 | 519 |
| duplicate MLBAM-ID groups | 0 | 317 |

There are also legacy invalid stat types and unowned sources in both databases.
Authoritative league refreshes must replace those populations before the
canonical table migration can apply.

The additive roster-snapshot migration passed on a disposable production clone:
backup verified, `quick_check=ok`, one migration record, and protected
`props`/`prop_results`/`prop_games` fingerprints unchanged. This proves the
schema operation; it does not authorize applying it to DEV or production.

A follow-on MLB repair prototype exists only as untracked work in
`/root/lp-v0613-backend-data` plus disposable `/tmp` artifacts. Its rollback
rehearsal changed no live data. It is parked until the migration/promotion phase
and is not part of commit `4394bb8`.

### Active build order

#### 1. NBA v1 slice — **NEXT**

- Publish current regular-season values from ESPN's
  `statistics/byathlete` table; do not recreate them from box scores when ESPN
  already publishes the season line.
- Keep hoopR as the historical owner through 2023 only.
- Resolve ESPN IDs into `players.id`; queue misses and duplicate source IDs.
- Publish a complete NBA roster snapshot before changing current membership.
- Preserve ESPN's explicit game phases: `PRE`, `REG`, `PLAYIN`, and `POST`;
  classify only the NBA Cup Championship as `CUP`, and require
  `completed=true` independently from a post-state status.
- Prove unique leader rows, canonical leader-to-profile links, recent games,
  matchup/projection evidence, and honest null handling.
- Make NBA Team Stats supported from a bounded, proof-backed season population.

2026-07-29 checkpoint:

- ESPN reports 582 regular-season player rows in one batch request. The
  disposable NBA clone first resolved 580; the explicit season-identity
  publisher then backfilled Markelle Fultz (`4066636`), inserted Andersson
  Garcia (`4702431`) as inactive, and enabled a 582/582 atomic
  `espn_site_stats` publication with zero unresolved rows.
- The identity merge rehearsal consolidated 272 split ESPN/hoopR pairs, moved
  264 historical stat rows, and published an idempotent 545-player, 30-team
  roster snapshot. DEV and production were not mutated.
- The guarded phase repair classified 1,017 regular-season games, 6 Play-In
  games, 85 postseason games, and one Cup final, and removed the postponed
  ten-row zero-box-score event on the clone. Logs remain intentionally
  insufficient to derive ESPN's published season table.
- ESPN standings require 30 teams at 82 games and 1,230 regular-season games.
  DEV still has the old 1,227-game population and now fails closed as
  `schedule_not_reconciled`. The clone's standings-backed publisher validated
  all 1,230 summaries and published 2,460 reciprocal result rows plus 2,460
  complete stat rows; NBA Team Stats returns 30 supported teams.
- The focused candidate suite passes 118 backend tests plus the NBA profile
  render test. The clone passes `quick_check`, produces unique leader links and
  regular-season-only history, and preserves byte-identical `props`,
  `prop_results`, and `prop_games`.

#### 2. NHL v1 slice

- Keep NHL API totals as the only season-display owner.
- Remove/rebuild the competing derived NHL population rather than choosing a
  duplicate at read time.
- Publish and verify the canonical NHL roster snapshot.
- Prove leader uniqueness, canonical profile links, durable game history, and
  Team Stats coverage.

#### 3. NFL v1 slice

- Keep nflverse as the canonical weekly/stat and schedule vocabulary.
- Load and expose the pinned 2026 schedule: 272 regular-season games, 32 teams,
  17 played weeks plus one bye per team.
- Finish complete 10-, 12-, and 14-team draft persistence.
- Ingest ESPN's published overall PPR rank and 2026 projected stat lines from
  the existing `kona_player_info` source. Coverage measured on 2026-07-29 was
  299/300 ranks and 283/300 projections, including 32/32 D/ST.
- Compute Legendary Picks PPR totals from the stored published stat line using
  one explicit tested formula; do not label unstable ESPN `appliedTotal` as the
  source and do not fabricate missing projections.
- Restore the intended `RK | PLAYER | BYE | ADP | PROJ | AVAILABLE` contract
  and the `PROJ 2026` player-card row.
- Make NFL Team Stats supported from a bounded, proof-backed season population.

#### 4. Parked MLB production repair and cross-league migration

- Rebuild MLB display stats from Statcast after identity-safe consolidation.
- Rehearse production's 317 duplicate MLBAM groups on a fresh disposable clone.
- Preserve props, re-resolve logs only from stable source keys, queue ambiguity,
  and verify every dependent reference and protected-table fingerprint.
- Apply partial unique native-ID indexes only after all conflicts are clean.
- Run the strict canonical-stat and roster migrations first on fresh clones,
  then on DEV only with explicit authorization.
- Publish one complete current roster snapshot for MLB, NBA, NFL, and NHL.

#### 5. Whole-application gate and tag re-cut

Before moving the v0.6.13 tag:

- every exposed league has unique canonical leaders and correct profile links;
- profiles, Matchups, projections, and recent history use the same
  league-correct log population;
- NBA/NFL/NHL Team Stats are supported and non-empty;
- the 2026 NFL schedule and bye UI work;
- 10/12/14-team drafts persist and reload completely;
- ESPN rank/projection provenance, formula, coverage, and honest nulls pass;
- UFC rankings/history/Predict, dormant World Cup regressions, esports match
  identity/results/streams/picks, props, and game detail pass their own gates;
- a fresh production clone passes backups, migrations, `quick_check`, data
  invariants, protected-table fingerprints, APIs, and the browser matrix.

Only after those gates pass may the existing v0.6.13 tag be re-cut and
production promotion be reconsidered. Production writes and deployment still
require explicit approval.

---

## 2026-07-31 — Fantasy news audit repair (CURRENT local candidate)

Commit `888fb51` repairs the RotoWire fantasy-news slice on local `dev`. It is
not pushed or deployed.

### Closed

- **Cross-player news assignment:** source/player IDs are retained. A persisted
  RotoWire crosswalk wins when present; until then, name is candidate discovery
  only and team + position must resolve exactly one canonical NFL player.
  Carlton Davis no longer leaks into Carl Davis, Marcus Harris resolves to the
  TEN corner rather than all three same-name rows, and suffixes such as Michael
  Penix Jr. resolve correctly.
- **False empty states:** source outage, stale cache, no news, unsupported
  league, and unresolved identity are separate API/UI states. A malformed or
  partial feed cannot replace the last validated snapshot.
- **Ordering and dates:** articles are newest-first before `limit`; date-only
  estimated returns remain on the source calendar day in viewer-local time.
- **Surface parity:** player page and mock-draft overlay use one shared news
  renderer with source attribution and identical error semantics.

### Measured boundary

- Live feed at verification: 172 updates, 157 unique RotoWire players.
- 135/157 resolve uniquely to canonical `players.id`; zero source-player IDs
  collide on one canonical player.
- 22 source players fail closed because the current DB disagrees on team or
  position, or lacks the person. Ten are fantasy positions (1 RB, 5 WR, 4 TE).
  Publishing `player_external_ids(source='rotowire')` can recover these only
  after stable-ID evidence exists; do not weaken matching to hide the gap.
- Gates: 10 focused backend news tests, 13 existing profile API tests, five
  React news tests under `America/Chicago`, public desktop player pages, and
  the 414×896 mock-draft overlay. Browser checks had zero console/page errors.

### Still separate

- The three feature commits ahead of `origin/dev` are `f4e05fb`, `3a5546d`, and
  `888fb51`, plus this context/roadmap documentation commit; no push occurred.
- This closes the local feature defect. It does not satisfy the whole-app
  v0.6.13 re-cut gates above and does not authorize DEV/production data writes,
  a tag move, service restart, or deployment.

---

## 2026-08-01 — Fantasy-news scope correction (supersedes 2026-07-31 surface parity)

Commits `fe1f296` and `9842792` correct the product boundary that `f4e05fb`
and `888fb51` got wrong:

- `/player/[id]` is a general player-detail surface. Its News tab again uses
  ESPN general reporting through `/api/player/{id}/news`; it does not render
  RotoWire fantasy analysis or ESPN's fantasy vertical.
- The mock-draft player overlay is the fantasy context. It alone consumes
  `/api/player/{id}/fantasy-news` and renders RotoWire notes and Fantasy Spin.
- ESPN search results are accepted only when ESPN resolves the query to exactly
  one NFL athlete with the profile's ESPN ID; same-name NFL players fail closed.
- RotoWire identity resolves from a persisted mapping when present, otherwise
  from Sleeper's published ESPN/GSIS-to-RotoWire crosswalk. Team changes do not
  break stable identity: Deebo Samuel resolves to RotoWire `13429` even while
  the local team row still says WSH and RotoWire says SF.
- The 172-update / 157-player league feed is a rolling snapshot, not complete
  player coverage. Public player-specific RotoWire history is merged with it;
  locked subscriber analysis is not copied. A true `no_news` state now requires
  a successfully loaded player history, not mere absence from the rolling feed.

DEV-tunnel evidence: Deebo's standalone page rendered ESPN reporting with no
RotoWire/Fantasy Spin; the in-draft overlay rendered six RotoWire updates,
including history, with no ESPN headline. Patrick Mahomes rendered five history
updates despite not relying on a current rolling-feed match. Both browser checks
had zero console/page errors. The focused gates pass 27 backend tests and five
React tests. This remains local/un-pushed and does not authorize production
deployment.

---

## 2026-08-01 — NFL player UI and news interaction completion

Commits `99553fb`, `1e48461`, and `9895508` close the remaining interaction and player-UI
requirements on the local DEV candidate:

- RotoWire fantasy-news cards in the mock-draft overlay are display-only. They
  expose no outbound links; the standalone ESPN general-news cards remain
  linked.
- Fantasy analysis follows the saved Gibbs reference as plain editorial copy:
  notes, then inline bold `SPIN:`, then date and source. The former nested green
  Fantasy Spin panel is removed.
- NFL pool rows render compact injury designations, and both the mock-draft
  detail overlay and standalone NFL player profile render the full designation.
  `ACTIVE` and null states do not produce warning tags; the stored
  `INJURY_RESERV` value is normalized to Injured reserve / IR.
- The four position-aware season metrics are one dark card with a full-width
  orange season header and four evenly divided value/rank columns, following
  the Joe Burrow ESPN reference saved from the Hermes Discord session.
- The season card is confined to Overview. The redundant
  `RB2 by ADP — not our ranking` sentence is removed, while the compact RB2
  badge remains.
- The player-profile contract now consumes `regular_season_games`, eliminating
  the rendered `undefined games` value.
- General ESPN results require the verified NFL athlete plus complete-name
  evidence in NFL article metadata. This preserves Deebo Samuel reporting while
  rejecting unrelated broad-name results such as Luke Fortner receiving darts
  or baseball headlines.
- The mock-draft pool API now enforces the supported position vocabulary:
  `QB`, `RB`, `WR`, `TE`, `PK`, and `DEF`. The measured DEV/public-tunnel
  population is 4,507 rows across exactly those six values; `TQB` and every
  IDP/coach/punter/lineman/blank value measure zero. The larger ESPN universe
  remains an ingest/source population, not a user-facing fantasy pool.

Evidence: 52 focused backend tests passed; eight Jest suites / 76 tests passed;
changed-file TypeScript diagnostics were empty; public mobile profile, pool,
detail overlay, general-news, and fantasy-news checks had zero console/page
errors. The fantasy overlay contained zero links, while Deebo's standalone ESPN
headline remained linked. This candidate is served by the managed DEV tunnel,
remains unpushed, and is not production.

### Correction: separate NFL league-page rankings pool

Commit `09fc934` closes a missed third pool surface. The `/leagues/nfl` Player
Rankings table is backed by `/api/nfl/draft-board`, not the mock-draft pool API.
It now:

- returns and renders the same compact NFL injury tags;
- restricts unfiltered and filtered results to `QB`, `RB`, `WR`, `TE`, `PK`,
  and `DEF`;
- removes `TQB` and unsupported-position pills; and
- rejects `position=TQB` instead of treating it as a valid board filter.

Fresh public-tunnel verification measured 772 eligible players across only the
six supported positions, zero `TQB` search results, and a rendered red `Q` tag
for Jahmyr Gibbs in the exact league-page Player Rankings table. The focused
backend suites passed 71 tests, the shared injury-tag suite passed three tests,
and the browser check had zero console/page errors. This correction is live on
managed DEV through auto-reload, remains unpushed, and is not production.
