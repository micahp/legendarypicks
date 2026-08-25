# Roadmap

**This file is what we intend to build.** `docs/BACKLOG-holes.md` is what is measurably
broken. **Both funnel into `CHANGELOG.md`, which is the only history of record**, and
`scripts/release.sh` generates the GitHub release notes from it and refuses to cut a release
without an entry.

**So there is no roadmap archive.** A closed item leaves this file and appears in the
changelog under the version that shipped it. A superseded roadmap is a git revision, not a
document: `git log -p docs/ROADMAP.md`. The 2026-08-18 version and the old `# Ledger` are at
`git show 0d2ec7c:docs/ROADMAP-ARCHIVE.md`.

Checked = shipped to **production**, not to dev.

**Rewritten 2026-08-20.** The previous version dated itself 2026-08-18, had grown to 1,520
lines, and had buried thirty unchecked items (`B1`-`B16`, `M1`-`M7`, `R1`-`R9`) underneath a
`# Ledger` heading that told readers not to rewrite what was below it. Open work was sitting
in the history section, which is why it stopped being read. That is fixed: the still-open items moved to
the backlog as P4, and the history is a git revision rather than a second file.

**Every number below was measured on 2026-08-20** against `backend/data/picks.db` (prod),
`backend/data/picks.dev.db` (dev) and the live prod API, spending **zero** ESPN requests.
Where a measurement contradicts what the 08-18 roadmap claimed, the correction is called out
in place, because this document has been confidently wrong before.

The constraint that orders all of it: **NFL fantasy drafts are happening now**, and NCAAF
opens **2026-08-29, nine days out**. That is the only hard date on the board.

---

## 1. What production is actually running

**v0.8.4 on the frontend; the backend is FOUR COMMITS AHEAD OF ANY TAG.** Read off the
containers rather than the tags:

```
legendarypicks-frontend   image built 2026-08-19 19:30   == v0.8.4 (tagged 19:21)
legendarypicks-backend    image built 2026-08-19 23:13   == v0.8.4 + 4 untagged commits
```

The four commits prod's backend carries beyond `v0.8.4`, all pushed to `dev`:

```
0473bc1  fix(props): the ingest filed a game on the UTC day, not the day it is played
2775169  fix(split): a caller that is not an import is a caller a split cannot see
8fc93a4  fix(clock): two more places comparing a local slate day against a UTC today
7013ef1  fix(db): prod served 500s because SQLite gave up on the lock after 5 seconds
```

**This was a deliberate rebuild, not drift, but it breaks the tag convention.** The container
was rebuilt on 2026-08-19 at 23:13 to carry the busy-timeout half of the SQLite contention
fix, which could not reach prod as data.

- [ ] **Cut `v0.8.5` so the running image has a name again.** Use `scripts/release.sh`, never
      by hand. Until then "what is on prod" cannot be answered by a tag, which is the one
      thing a tag exists for.

**`backend/data` is bind-mounted; code is baked into the image.** That single fact splits
every fix into two classes and it has not changed:

- **A data fix reaches prod the moment it runs.** No deploy.
- **A code fix cannot reach prod at all until a rebuild.** Size is irrelevant.

Corollary, which has cost us twice: **a schema change must never get ahead of the code that
understands it** (`feedback_schema_must_not_outrun_prod_code`). Additive nullable columns are
safe; constraints and indexes are not, because the writer that has to satisfy them is frozen
at image-build time.

---

## 2. Nothing is release-blocking as of 2026-08-20

The 08-18 roadmap led with "the scoreboard fix is written, tested, and not deployed" as the
one thing a visitor experienced as the site being broken. **All three faults are fixed and
deployed.** Re-measured against the live prod API today, not inferred from release notes:

| fault | 2026-08-18 | 2026-08-20 |
|---|---|---|
| `/api/mlb/games?date=<today>` | **60.06s** | **0.10s**, 9 games |
| `/api/mlb/games?date=<past day>` | **0 games** | **15 games** |
| `/api/mlb/schedule-dates` | `source=unavailable, available=false` | `source=local, available=true`, `future_event_starts` populated |

**A second production fault in the same area was found and closed on 2026-08-19: SQLite lock
contention.** The former `legendarypicks-props-prod` unit exited 3 with "2 of 14 mlb games failed to POST"
every 30 minutes, because `sqlite3.OperationalError: database is locked` came back out of the
API as an HTTP 500.

Cause: **prod was `journal_mode=delete` while dev was `wal`.** Under `delete` a writer takes
an exclusive lock on the whole database and every reader waits, so prod's API reads, the
per-minute `scoreboard_snapshots` writer and the 30-minute props ingest all serialised. Dev,
in WAL, could never reproduce it. **The two databases disagreed about a property nothing
measured, and the gap only showed under load.**

Fixed in `7013ef1`, live in the 23:13 rebuild. Both databases now report `wal`.

**Verification is honest but incomplete.** The guard fix is confirmed under a real production
write; WAL and the 30s busy timeout are confirmed present in the running container. What is
**not** proven is that the EXIT 3s are gone, because every props run since the flip has been a
quiet evening slate.

- [ ] **Watch a full daytime slate before calling the contention fix closed.**
      `journalctl -u legendarypicks-props-prod.service | grep "failed to POST"`. This name now
      refers to the registry runner's production unit. If any run
      exits 3, the busy timeout needs to reach past the two helpers changed so far
      (`_core._db`, `scoreboard_store._db`); 174 other `sqlite3.connect(` sites pass no
      timeout at all.

---

## 3. THE ONLY DATED ITEM: NCAAF opens 2026-08-29

**Nine days.** Everything else on this page can slip; this cannot.

- [ ] **Week-grouped navigation for NFL and NCAAF.** A drafter and a viewer both move through
      these sports by week, not by date.
      **Reuse, do not rebuild:** `docs/API-nfl-schedule-weeks-v1.md` already serves ESPN's own
      week calendar and is live on `pages/leagues/[league].tsx`. **Candidate 2026-08-24:**
      the shared week UI now covers both leagues. NCAAF uses ESPN's published week boundaries,
      not the capped `week=` response: Week 1 returned 99 verified games by range versus 25 by
      direct week query, and ESPN's postseason `CFP` key `3:999` is preserved. Unchecked until
      browser/release gates pass and it ships.
- [ ] **Confirm NCAAF has anything to show on opening weekend.** NCAAF has **zero props** on
      both databases (remeasured on the copied production DB 2026-08-24). ESPN currently
      publishes eight games for August 29, including UNC-TCU, San Jose State-USC, and
      NC State-Virginia; all eight were captured into the candidate DB. The runtime props
      navigation consequently withholds NCAAF because it has no stored props, while the league
      hub has a real Week 1 schedule. A league that opens with an empty props board is worse
      than a hidden one.

**The gate that was blocking this is now answered and should be removed.** The 08-18 roadmap
said "do not spec the remainder until the request-budget question is answered". It was
answered on 2026-08-19: **ESPN's limit is a burst rate, not a count**
(`reference_espn_limit_is_a_burst_rate`, measured over 27,801 requests; the 1-hour window is
flat at 1238 vs 1266). The gate no longer applies and must not keep blocking a dated item.

---

## 4. Draft window, ordered by whether a drafter notices

### Draft research is DONE. Closed 2026-08-18.

Confirmed by Micah: the draft board (`/leagues/nfl` camp tab), the player detail overlay and
the mock draft simulator **are** the draft research. Treat further work as sharpening a
shipped surface, not building a missing one, and do not re-open it without a user asking for
something specific.

### The list

- [ ] **Give the draft board its own route.** It is reachable only as a tab named `camp`
      inside the league hub. A drafter cannot link a friend to it. **Candidate 2026-08-24:**
      `/draft-board` is a stable standalone destination, wired through the exact same
      `NflDraftBoardSurface` hook/component owner as the embedded NFL hub board. The hub links
      to the full board, and the full board links back to NFL and into `/mock-draft`; notes,
      filters, search, pagination and player overlays therefore cannot drift by route.
      Unchecked until browser/release gates pass and it ships.
- [ ] **Decide what a drafter still cannot answer on the board.** The one piece of genuine
      product thinking left in the window, and it needs the user, not us. The board has eight
      sort dimensions; nobody has asked her which question it fails to answer.

**Fullbacks are not a fantasy position.** The `{QB,RB,WR,TE}` filter in
`ingest_nfl_season_stats.py:29` is correct. Recorded because it was corrected in conversation
more than once and kept coming back (`project_lp_fullbacks_not_fantasy`). Do not over-read it:
**kicker, defense and FLEX are all fantasy positions** and the board already offers them.

---

## 5. Props integrity, and the numbers moved a lot

The board shows a line and never says how it landed. Measured 2026-08-20:

| league | prod props | prod settled | dev props | dev settled |
|---|---|---|---|---|
| mlb | 54,110 | 44,191 | 60,099 | 48,047 |
| mls | 2,569 | 718 | 5,697 | 880 |
| **nfl** | **1,080** | **0** | 1,082 | 0 |
| atp | 536 | 0 | 552 | 0 |
| wc | 392 | 0 | 1,128 | 0 |
| wta | 377 | 0 | 427 | 0 |
| ufc | 142 | 112 | 466 | **0** |

**Three corrections to the 08-18 roadmap, all in the direction of the problem being smaller
or different than recorded:**

- It said **"2,475 tennis props cannot reach a game page"** and **"ATP 0 of 2,402, WTA 0 of
  2,119"**. Today prod holds **913 tennis props total** (ATP 536, WTA 377) and dev holds 979.
  The old figure cannot be reproduced. Some of the drop is the 08-19 dedupe, which removed
  4,355 prod props; the rest is unexplained. **Re-measure before quoting a tennis number.**
- It said **"dev has no UFC `prop_results` rows at all"**. Dev now holds **466 UFC props** and
  still settles **0** of them, against 112 of 142 on prod. The inversion is real; the "no
  rows" part is not.
- It said MLB `team_stats` is 16 rows. **There is no `team_stats` table.** The table is
  `team_game_stats`, and it holds **16 MLB rows on both databases** against 12,930 prod
  `team_game_results`. The finding stands; the name was wrong, so anyone grepping for it found
  nothing.

### The work

- [ ] **NFL props settle zero.** 1,080 on prod, 1,082 on dev, all from the 2026-08-19 RotoWire
      relay, none graded. New since the last roadmap and the largest unsettled block outside
      tennis. **The props exist and look healthy on the board. Copied-candidate proof
      2026-08-24:** the refreshed copy holds 1,774 NFL props, but 1,694 belong to Sept. 9-14
      games that have not happened. Of the 80 props on 13 completed preseason games, the
      case-insensitive ESPN stat-label repair plus `field_goals_made` mapping produced 76
      numeric outcomes, zero errors, and zero unmappable markets. Four receiving-yard props
      remain pending because Jack Bech and Chris Godwin have no published stat line. Future
      props received zero result rows. Candidate DB only; production and managed dev are
      unchanged.**
- [ ] **Link tennis `prop_games`.** 274 of 325 prod ATP/WTA rows have no `espn_event_id` (16%
      linked); dev is 132 of 299. The matcher and budget guards already landed (`b8886e9`);
      this needs a run, not a build. Note `reference_espn_folds_tennis_names`: ESPN folds
      accents in tennis names but not soccer ones. **Copied-candidate proof 2026-08-24:** after
      candidate ingest, 301 of 356 rows were unlinked and 706 of 1,253 props could not reach a
      game. The conservative two-player matcher linked 239 rows, folded duplicate slate rows
      without losing a prop, and left 62 of 289 rows unlinked; reachable props rose from 547 to
      945. Candidate DB only; production and managed dev are unchanged.
- [ ] **Settle tennis.** 0 of 913 on prod, 0 of 979 on dev. **Copied-candidate proof
      2026-08-24:** DB-first settlement from durable completed set-score snapshots produced 658
      numeric outcomes (ATP 386, WTA 272), zero void placeholders, and zero errors. It correctly
      left 38 props pending on one walkover and one suspended match; another 249 linked props
      lack a durable final snapshot and 308 remain behind unlinked games. Candidate DB only;
      production and managed dev are unchanged.
- [ ] **Grade or void the World Cup rows honestly.** 392 prod and 1,128 dev `prop_results`
      rows have `actual_value` NULL **and** `hit` NULL. A settled count that grades nothing is
      presence, not integrity. **Copied-candidate proof 2026-08-24:** all 392 rows belong to
      two completed matches. Durable ESPN player logs provide unique numeric evidence for
      267 (goals, assists, shots, and shots on target); the official final rosters mark all
      remaining 14 players as zero appearances/zero substitutions, accounting for the other
      125 rows as DNP voids. The guarded repair produced 267 numeric outcomes, retained 125
      voids, left zero unexplained rows, and was idempotent. The game API now distinguishes
      graded results, pushes, voids, and pending props instead of rendering every NULL verdict
      as pending. Candidate DB only; production and managed dev are unchanged.
- [ ] **Get UFC settlement onto dev.** Until then a green dev suite says nothing about UFC.
      **Copied-candidate proof 2026-08-24:** the refreshed copy holds 198 UFC props and now
      has 139 numeric outcomes after a bounded four-game run added three. Of the remainder,
      52 belong to the Aug. 29 card, six belong to an unlinked fight absent from ESPN, and
      one Aleksandr Rakić decision prop remains pending because the durable fight log contains
      only Marcin Tybura's side. Zero errors and zero unmappable markets. Candidate DB only;
      managed dev was not run or changed.
- [ ] **`team_game_stats` holds 16 MLB rows.** Find out whether that is a stalled ingest or a
      table nothing writes any more. **Copied-candidate diagnosis 2026-08-24:** these are
      obsolete residue, not a stalled MLB source. All 16 were written in one four-second
      burst on June 9; every typed stat, JSON blob, run id, and source is empty. The public
      team-stats route rejects MLB, MLB aggregates deliberately use `team_game_results`, and
      current snapshot/backfill writers do not target MLB. A fail-closed cleanup removed the
      16 empty rows on the copy and deleted zero on rerun; it refuses the whole operation if
      any MLB row carries data or provenance. Production and managed dev are unchanged.
- [ ] **Promote MLS to prod parity:** game logs **10,603 prod vs 21,177 dev**, stories **0 prod
      vs 45 dev** (30 at the original measurement),
      leaders stuck on 2025 while standings serve 2026. All data jobs, none needs a deploy.
      **Copied-candidate progress 2026-08-24:** a local rollup published 697 current-season
      leaderboard rows from the copied ESPN logs, so the candidate API now defaults to 2026,
      offers `[2026, 2025]`, and all 697 leaders reach a same-season game log. One paced,
      low-priority 80-summary catch-up chunk added 1,497 logs across 49 completed May games
      (10,603 -> 12,100 total; 2026 now 6,013 logs across 196 games), then hit ESPN's explicit
      request wall and stopped at its declared budget. A dry-run-first story promotion then
      copied all 45 DEV MLS stories into the candidate by stable `(league, game_id)` key;
      source and candidate field hashes match and a rerun planned zero writes. Held log
      coverage still ends Aug. 8 and production stories remain zero, so promotion remains
      open. The run also exposed two diagnostics
      bugs: Core type `1` and summary type `13846` both name the MLS regular season and must
      be compared semantically (now regression-tested), and a player-name variable must not
      overwrite the phase label. Production and managed dev are unchanged.
- [ ] **MLS and NCAAF scoring plays: zero on both.** Confirm the publisher has them before
      recording it as a gap (`feedback_we_systematically_underread_publishers`). **Confirmed
      and copied-candidate proof 2026-08-24:** the publisher has them in two league-specific
      collections the existing parser never read. A completed NCAAF summary publishes seven
      entries under `scoringPlays`; a completed MLS summary publishes four goals under
      `keyEvents`; both expose an empty `plays` array. The parser now reads the published
      collection, maps team identity without prose guessing, reconstructs soccer's running
      score from explicit home/away team ids, and records the first participant as scorer.
      A game-id-required backfill advertises its exact request count and is dry-run by default.
      The copy wrote 7 NCAAF + 4 MLS proof rows and wrote zero on rerun. Production and managed
      dev are unchanged; full historical backfill remains a separate bounded data operation.

**Not a defect, recorded so it is not "found" again:** grouping `props` by
`(game_id, player_id, market, line, side)` reports 240 duplicate groups on prod and 1,085 on
dev. Including `source` gives **0 on both**. Those rows are `rotowire:prizepicks`,
`rotowire:sleeper` and `rotowire:underdog` quoting one line, which is three books, not a
duplicate. The 08-19 dedupe holds. `prop_games` shared match keys: **0 on prod, 1 on dev**, and
the dev one is the real 07-27 Reds/Guardians doubleheader.

- [ ] **`props` still has no unique index**, which is why duplicates were possible at all. A
      doubleheader and a duplicate remain indistinguishable to the ingest's match key;
      `prop_game_merge.shared_match_keys` states the rule but the schema fix (kickoff instant
      or game number in the key) is unmade.

---

## 6. Scoreboard: what is still open after the ESPN-model rebuild

Spec: `docs/SPEC-featured-events-scoreboard.md`. Reuse `docs/API-nfl-schedule-weeks-v1.md` and
`docs/API-league-schedule-dates-v1.md` rather than rebuilding either.

- [ ] **Featured Events strip and the "Next up" collapse**, per the spec. §4 ranking, §6 empty
      state, §6b visual language.
- [ ] **Week-grouped navigation.** Promoted to section 3; it has a date now.
- [ ] **A request-count gate** enforcing the measured zero, so the property cannot silently
      regress.
- [ ] **Stop discarding ESPN's fields.** `competitions[].headlines[]`, records and probables
      arrive in payloads we already fetch and we drop them at zero cost. Measured 2026-08-19:
      headlines present on `mlb 12/15, mls 0/15, wnba 0/2, atp 0/1`, so it is an MLB-only win
      today. Use the publisher's headline as the **recap** where it exists; keep generation for
      **previews** and for every league that gets nothing; never fabricate a line when the
      field is absent. Cuts LLM volume with no quality loss.

---

## 7. The coverage matrix is too coarse

`backend/league_feature_matrix.py` answers "what do we have, for which league". Right idea, not
detailed enough to act on: every cell is a single count, and a count cannot say what it is OF.
Each item below is a question the matrix cannot currently answer.

- [x] **Split the log surfaces:** DONE 2026-08-24. The derived matrix now names and counts
      `player_game_logs`, `player_stats`, `team_game_results`, and `team_game_stats` as four
      distinct products instead of hiding their table identity behind “game logs”, “season
      stats”, and “game detail”. League discovery also reads every matrix table, so a league
      represented on only one of these surfaces is not silently omitted.
- [x] **What YEARS are available**, per league per surface. DONE 2026-08-24. Report the **set**, not a min-max
      range: the interesting case is a GAP, and a range hides it. Live example, not
      hypothetical: prod MLS standings serve 2026 while `/api/mls/leaders` offers
      `available_seasons: [2025]`. The candidate matrix now derives explicit season sets on
      every run and reports unassigned rows separately. It makes the remaining MLS split
      visible: player logs/stats `{2025, 2026}` versus team results/stats `{2025}`. Because
      `team_game_stats` has no season column, its years come only from a same-game
      `team_game_results` join; unmatched rows stay marked `+N?` rather than inheriting a
      calendar year from `captured_at`.
- [x] **What PROPS exist per league**, meaning distinct `props.market` values and counts. DONE
      2026-08-24: the matrix derives every source/market count; the default prints distinct
      market totals and `--props-detail` prints every stored value (kept opt-in because the
      copied MLB inventory alone has 1,435 distinct strings). A book
      pricing a market our grader cannot map produces props that land, look healthy and never
      grade. **NFL's 1,080 unsettled props are that shape.**
- [x] **WHERE the props come from.** DONE 2026-08-24. `props.source` is now a first-class
      grouping per league (including an explicit `(blank)` bucket), rather than Bovada,
      Underdog, RotoWire, and PrizePicks rendering as one number.
- [x] **Are they RESOLVED**, split by source and by market. DONE 2026-08-24. Key settlement on
      `actual_value IS NOT NULL`, **never `settled_at`**: settlement stamps a timestamp on props
      it could not map, so the timestamp records that something RAN, not that anything landed.
      Copied MLS evidence now separates Bovada `718 graded / 2,207 total` from RotoWire
      PrizePicks `0 / 478`, instead of hiding the latter behind the former.
- [x] **Are settled props REACHABLE.** DONE 2026-08-24. One explicit count per source and
      market now says: of the props graded, how
      many hang off a `prop_games` row with an `espn_event_id`. Everything else is data we hold
      and nobody can see. The query uses `EXISTS` so a malformed duplicate result row cannot
      inflate either the graded or reachable count.

Everything above must be **derived on the run**. Anything needing an ESPN request stays
`UNPROBED` rather than rendering as a zero, because a hand-maintained matrix is a claim that
outlives its code.

---

## 8. Measurement debt: checks that stay green by not being asked

- [ ] **`atp`, `wta`, `wnba` have no MANIFEST entry** (`audit_league_stats/cli.py:22`). The audit
      only fails a missing entry for a league that serves `player_stats`, and these three serve
      zero, so it stays green by never asking. WNBA does not exist in either database.
- [ ] **`DURING / live state` is UNPROBED for every league.**
- [ ] **`league_feature_matrix.py`'s docstring is stale:** it cites NCAAF as the example of a
      league hidden on prod, and NCAAF is OFFERED on both.
- [ ] **Dev's migration ledger is unreliable.** `legacy_merge_nba_identities` reports
      `unknown: registry row missing` on dev though dev's data is clean. A ledger that cannot
      answer "did this run" is not a ledger.
- [ ] **`docs/BACKLOG-holes.md` is dated 08-18** and its P0 list still leads with items this file
      has since falsified. Regenerate from the matrix or delete the P0 section rather than leave
      two documents contradicting each other.
- [ ] `B/position-content` for **mlb** and **nba**: what must a catcher's or a guard's log record?
- [ ] `DATA-COVERAGE-CONTRACT.md` §7 rewrite: what each of the 8 checks needs from a new league.
- [ ] `ufc` / `wc` UNVERIFIED x6, likely "no leaderboard surface to serve" rather than a missing
      fetcher. Confirm which.

---

## 9. In flight

- [ ] **Tournament games under their own league key.** Leagues Cup (`concacaf.leagues.cup`), CCC
      and Campeones Cup are separate ESPN slugs, so their logs must not inflate MLS
      regular-season denominators. **Props half shipped** (`a77ecb1`); **logs and denominators
      half is open.**
- [ ] **Player identity, steps 2 to 4** (`docs/TASK-next-release-player-identity.md`). Step 1
      done: `UNIQUE(espn_id, league)` on both DBs, 0 duplicate groups. Remaining: populate
      `player_source_ids` (10 rows today, all underdog/ufc, while Bovada and RotoWire still
      resolve by name), re-run promotion, reconcile diverged ids.
      `feedback_ambiguous_key_never_raises` is why this matters.
- [ ] **Player detail: year and league selectors**, keyed off `position_group` so a keeper surface
      shows saves, not shots.
- [ ] **Backend directory contract** (`docs/BACKEND-DATA-AUDIT-2026-08-18.md`). Proposed split is
      app data / seeds / cache / state / logs. The physical move is the open work.

---

## 10. Queued, named by the user, not started

- [x] **Un-park and replace the Bovada-only props timers.** DONE 2026-08-24. They were never deliberately
      parked: the former `legendarypicks-props{,-prod}.timer` pair used `OnBootSec=3min` +
      `OnUnitActiveSec=30min` and sat in `SubState=elapsed` with no next elapse from
      2026-08-21 11:08, while reporting `enabled` and `active` the whole time. A monotonic
      timer whose reference activation systemd has forgotten has nothing left to schedule.
      The replacement registry-runner timers are `OnCalendar`, staggered 15 minutes, and use
      one in-process host lock per publisher. It also exposed a real defect: Bovada files NBA team totals inside a display
      group called "Score Props", and "Highest Scoring Quarter Total Points O/U - Boston
      Celtics" splits on " - " exactly like a player market, so the club landed in
      `player_name`. All 120 NBA outcomes were rejected by the resolver, `resolved 0 of 120`
      raised exit 3, and the exit took the whole unit down -- on a day Bovada published no NBA
      player props at all. Team markets are now dropped at the parser and counted in the run
      report. Bovada currently publishes NBA game/team markets only.
- [ ] **Bovada and Kalshi live games**, plus a game detail from each.
- [ ] **Daily RotoWire props dump.** Save everything that endpoint gives us to a directory once a
      day, in case we expand to those leagues.
- [x] **Schedule the RotoWire relay ingest.** DONE 2026-08-24, shipped in v0.8.7. NFL and MLS
      now run through `run_props_ingest.py` on both databases; its DB-backed cadence is
      matched to the existing probe so no new request rate hits the publisher. Coverage went
      from 5 days stale to same-day; NFL had no other source at all since Bovada publishes
      none. The temporary per-provider units were retired into the provider runner
      (`/root/TASK-props-provider-runner.md`). Still uncovered by the relay: NCAAF (opens
      Aug 29), WNBA (0 of 17, in season), NBA, NHL.
- [ ] **Audit the RotoWire props we store and never use.** Named by Micah 2026-08-24, and the
      numbers are worse than "unused": **0.0% of RotoWire props are graded, in both databases**,
      against Bovada's 78.7%. Prod holds 2,034 RotoWire rows and 0 `prop_results`. Three
      distinct causes, measured, and they need separating before anything is deleted:
      (1) **894 of 2,034 sit on markets `settlement.market_mapping.resolve_market()` cannot
      resolve at all.** Every MLS market is in this bucket -- all 478 rows across
      `passes_attempted`, `saves`, `shots`, `chances_created`, `clearances`, `crosses`,
      `shots_on_target` -- plus NFL `interceptions_thrown` (102), `kicking_points` (82),
      `field_goals_made` (64), `total_touchdowns` (46), `passing_touchdowns` (34),
      `rushing_receiving_touchdowns` (32), `passing_rushing_yards` (30),
      `rushing_receiving_yards` (14), `extra_points_made` (12). These are exactly the depth
      markets RotoWire was brought in FOR, so an unmappable market is a market we paid to
      collect and cannot settle.
      (2) **10 of 25 RotoWire MLS fixtures carry an empty-string `espn_event_id`**, not NULL,
      so `settle_game()` returns `no espn_event_id, cannot pull boxscore` and every prop on
      them is unsettleable regardless of mapping. Note the shape: a coalesce-blind `IS NULL`
      count reports 0 missing on these rows. Count with `coalesce(espn_event_id,'')=''`.
      (3) The remaining 1,140 ARE mappable and simply have not been settled, because nothing
      schedules settlement over RotoWire-sourced games.
      Separately, on the collection side: the daily archive stores **the entire relay**, 3,191
      props on 2026-08-24, of which we ingest ~9%. Unused every day: MLB Game 1050, WNBA Game
      298, CFB Game 286, CS2 Game 205, NFL Season 743, NHL Season 81, CFB Season 59, MLB
      Season 42, NBA Season 18, Valorant 3. That is cheap to keep (3.7 MB total, ~600 KB/day)
      and deliberate per the dump item above, but it has **no retention policy**, and the
      NFL Season bucket is 743 props a day we discard at ingest for having no fixture -- those
      are season-long futures and want their own table rather than a daily drop.
      Also still dropped at ingest for want of a mapping entry, counted every run: NFL
      `Targets`, `Fantasy Score`, `Rushing Touchdowns`; MLS `Passes`, `Tackles`,
      `Fouls Committed`.

- [ ] **Props should leave the board at kickoff.** Named by Micah 2026-08-24: a prop stops
      being offerable once its game starts, *unless* the game has not actually started yet or
      is cancelled, in which case it stays. So the rule keys on the game's real state, not on
      the clock alone: `start_time` passed AND the game is not postponed/cancelled AND we have
      evidence it began. We already store `prop_games.start_time` and final scores, and
      `scoreboard_store` knows live state, so this is a serve-time filter plus a state source,
      not a new ingest. Two traps to design around: (1) 17 of 30 MLS rows carried NO
      `start_time` on 2026-08-19, so a missing start time must not silently expire a prop or
      silently keep it; (2) doing this as a batch sweep re-introduces the
      serve-path-enforcing-a-batch-budget shape. Efficient version is an indexed predicate on
      the existing serve query, not a job that walks the table.
- [ ] **Sport-first navigation on `/props` and `/leagues`** (`docs/DESIGN-sport-first-navigation.md`).
      Named by Micah 2026-08-24. The top-level entity becomes the SPORT; a competition row
      appears underneath only where we cover more than one competition in that sport. The
      trigger was Leagues Cup being unreachable on `/props`, which shows league chips, but
      adding an `lcup` chip returns the same question for Campeones Cup, CCC and every
      tournament after them.
      The measured argument is stronger than the aesthetic one: **RotoWire publishes soccer as
      ONE bucket.** In the 2026-08-24 relay archive the sport key is the literal string
      `Soccer`, there is no competition field on the market, the props carry no `eventID`, and
      the 113 soccer props were Chelsea/Fulham (EPL), Bologna/Fiorentina/Lazio/Roma (Serie A),
      Levante/Osasuna/Real Madrid/Real Sociedad (La Liga) and Deportivo/Málaga (Segunda).
      **Zero MLS**, and Underdog publishes none either (`reference_underdog_no_mls`). So a
      soccer tab whose contents are the two buttons `MLS` and `Leagues Cup` would have shown
      two competitions with no props that day and hidden four that had them.
      Decisions already made, so they are not re-argued: **football keeps NFL and NCAAF as two
      top-level chips** (a chip between a drafter and the NFL is a cost, not a tidy-up);
      **UFC stays UFC** until a second promotion is carried; storage keys (`atp`, `wta`,
      `mls`, `lcup`) do not change, this is the top of the page only. Derive the sport from
      the ESPN path in the complete `backend/espn_client/config.py` registry rather than a
      hand-kept slug map.
- [ ] **Consolidate ATP and WTA into one Tennis surface.** Falls out of the item above:
      `pages/props.tsx:36` offers `atp` and `wta` as separate chips, so a visitor who wants
      tennis must know to click two, which is the PrizePicks `EPL`-next-to-`Soccer` defect at
      small scale. Consolidating on `/props` forces a Tennis entry on `/leagues`, and there is
      no tennis hub today. Scope it to what tennis HAS: scores (`atp`/`wta` are in
      `BOARD_LEAGUES` and ingest per-day), props (`_parse_tennis_props`), and news. Game logs
      and season stats are declared not-applicable for both tours in
      `backend/league_feature_matrix.py:61`, which is why every tennis market in
      `core_markets.py:53` charts as `None`. A Draws tab for the current major is the one new
      build. **Measured 2026-08-24:** ESPN's existing tennis scoreboard response publishes
      the complete singles grouping as `groupings[].competitions[]`, including tournament id,
      round id/name, competitors, future TBD slots, and an official bracket link. The isolated
      candidate now validates and stores that whole draw from the already-fetched response,
      serves it DB-first at `/api/tennis/draws`, and adds `/leagues/tennis` with Scores,
      Draws, and News plus a Both/ATP/WTA toggle. This remains unchecked until the candidate
      passes the browser/release gates and is actually shipped. We cover majors, not the tour; Challengers, 250s and
      500s are not ingested and the hub says so on screen rather than looking like a tour page
      with holes in it.
- [ ] **A new league or promotion is only worth adding if we can get its props.** Named by
      Micah 2026-08-24 and recorded as a gate rather than re-argued per case. Props are the
      product, so a second MMA promotion (which is what would rename UFC to MMA), a second
      basketball league, or another soccer competition each has to clear this before it earns
      a chip. NCAAF is the standing counter-example already on this board: it opens 08-29 with
      **zero props on both databases**.
- [ ] **Ingest esports props from the RotoWire relay.** Named by Micah 2026-08-24, and the
      relay already carries them. Measured in the 2026-08-24 archive: **CS2 205 props** quoted
      by sleeper (158), underdog (149) and prizepicks (139), plus **Valorant 3** (prizepicks
      only). Markets are `Map 1 Kills`, `Map 1 Headshots`, `Maps 1+2 Kills`,
      `Maps 1+2 Headshots`, `Maps 1+2+3 Kills`. No LoL, Dota or COD that day. We discard all
      of it today, as the props-audit item above records.
      **The catch is which CS2.** The 22 teams quoted were tier-2 and academy sides:
      `Spirit Academy`, `CYBERSHOKE Prospects`, `ex-RUBY`, `Bushido Wildcats`,
      `Chinggis Warriors`. Real props on real matches, not the tier a visitor means by "CS2".
      Settlement needs an esports game spine these props can link to, which is the actual size
      of this item.
- [ ] **An option to hide esports props.** Named by Micah 2026-08-24. One account preference,
      default on, that removes esports from the props board. Not a per-title matrix. The
      reason is the uneven tier of the supply above, not the sport. **Do not build it before
      the ingest**: an option that hides an empty board is untestable.

- [ ] **Story generation deserves its own timer.** It rides on `ingest_scoreboards.py` only
      because that is where we now learn a game exists. Nothing ties it to the scoreboard.
      Related: story generation reaches `site.api.espn.com` through `stakes.py`, a host walled
      from this box since 2026-08-04, so every preview run spends a request that cannot succeed.

---

## 11. Post-draft: league news engine

The engine is live; prod carries **7,160** `news_items` (up from 5,526 on 08-18), dev 9,812.
What is left is editorial shape.

**Correction to the 08-18 roadmap.** It said "18.5% of prod rows (1,022) are still
`unclassified`". There is no `unclassified` value and no `category` column; the column is
`layer`, and the distribution on prod is:

```
other 5,172 | trade 507 | speculation 450 | narrative 412 | injury 411 | staff 139
```

**`other` is 72% of prod rows, not 18.5%.** Whether `other` means "unclassified" or is a
legitimate bucket is exactly the open question, and the old number understated it by a factor
of five.

- [ ] **Decide what `layer='other'` means**, then either classify those 5,172 rows or name the
      bucket honestly on screen.
- [ ] **Per-league AI news**, two layers: the league's dominant narrative, and the granular
      per-player items under it.
- [ ] **News page in top-level nav.**
- [ ] **POC first**, one or two leagues, before fanning out.
- [ ] Source allowlists stay keyed on more than a name
      (`feedback_trust_lists_never_keyed_on_name_alone`): a name-only allowlist let 855 tweets
      through as verified publishers.

---

## 12. Later, deferred on purpose

- [ ] **Source-separated tables** (`espn_core_*` / `espn_fantasy_*`). November, not now.
- [ ] **NFL 2024 game-id vocabulary migration.** Not shown in the frontend.
- [ ] **MLB: 767 Statcast batting rows** for players MLB publishes no 2026 line for. An open
      question, not obviously a defect.
- [ ] **168 pre-existing orphans** (`props` 78, `roster_snap` 90).
- [ ] **Soccer availability before kickoff.** Who is actually playing. Its own concern.

---

## 13. Where the other work lives

**This file is intent. `docs/BACKLOG-holes.md` is what is measurably broken.** The thirty
items carried out of the old Ledger (`B1`-`B16`, `M1`-`M7`) are defects or suspected defects,
so they moved there as **P4, all UNVERIFIED**. `B8` is user-reported and sits at the top.

What stayed here, because it needs a decision rather than a measurement:

- [ ] **`--all-positions` for IDP and kickers** (old `R5`). Needs Micah's call.
- [ ] **Accounts, with the mock draft as the reason to make one** (old `R9`); draft notes fold
      into it (old `R8`).
- [ ] **Mock draft: familiar-UX objects, resume and share, player detail overlay, camp card
      resume state, room polish** (old `M3`-`M7`).

---

## The rules this was learned under

1. **A fix on dev is not a fix.** Seven defects reached three releases because prod was never
   re-run, and both databases answered 200 throughout. It runs the other way too: UFC settles
   112 props on prod and 0 on dev. **2026-08-19 added the sharpest version yet:** prod and dev
   disagreed about `journal_mode` for months, nothing measured it, and prod served 500s under
   load that dev could never reproduce.
2. **Presence is not coverage.** The World Cup rows are "settled" and grade nothing.
3. **A gap is a statement about which endpoint you asked.** Every "nobody publishes this" here
   has been wrong.
4. **One column, one vocabulary, one publisher.** Two writers with no arbitration means whichever
   ran last owns the row.
5. **Never repair identity by name match.** That is what caused the damage in the first place.
6. **UNVERIFIED is a failure, not a skip.** ATP, WTA and WNBA are green today because the audit
   never asks them.
7. **A green gate is a claim about its surface.** Re-measure before working an item, and date
   what you measured.
8. **Check your own measurement before reporting a defect.** Added 2026-08-20. This rewrite
   nearly recorded "the ingest is re-minting duplicate props" because the grouping key omitted
   `source`; three books quoting one line is not a duplicate. It also found the old roadmap
   citing a `team_stats` table that does not exist and an `unclassified` news bucket that is not
   a value in the schema. **A wrong number in this file costs more than no number.**
