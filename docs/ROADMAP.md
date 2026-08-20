# Roadmap

**This file is current state only.** History lives in **`docs/ROADMAP-ARCHIVE.md`** and is
never rewritten, only appended to. When an item here closes, it moves to the archive with the
date and the measurement that closed it.

Checked = shipped to **production**, not to dev.

**Rewritten 2026-08-20.** The previous version dated itself 2026-08-18, had grown to 1,520
lines, and had buried thirty unchecked items (`B1`-`B16`, `M1`-`M7`, `R1`-`R9`) underneath a
`# Ledger` heading that told readers not to rewrite what was below it. Open work was sitting
in the history section, which is why it stopped being read. That is fixed: history is in the
archive, open work is in section 13.

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
contention.** `legendarypicks-props-prod` exited 3 with "2 of 14 mlb games failed to POST"
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
      `journalctl -u legendarypicks-props-prod.service | grep "failed to POST"`. If any run
      exits 3, the busy timeout needs to reach past the two helpers changed so far
      (`_core._db`, `scoreboard_store._db`); 174 other `sqlite3.connect(` sites pass no
      timeout at all.

---

## 3. THE ONLY DATED ITEM: NCAAF opens 2026-08-29

**Nine days.** Everything else on this page can slip; this cannot.

- [ ] **Week-grouped navigation for NFL and NCAAF.** A drafter and a viewer both move through
      these sports by week, not by date.
      **Reuse, do not rebuild:** `docs/API-nfl-schedule-weeks-v1.md` already serves ESPN's own
      week calendar and is live on `pages/leagues/[league].tsx`.
- [ ] **Confirm NCAAF has anything to show on opening weekend.** NCAAF has **zero props** on
      both databases (measured 08-16, unchanged). A league that opens with an empty board is
      worse than a hidden one.

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

- [ ] **Render `PK` as `K`.** Storage is right; four files leak the publisher's code into the
      filter chips: `useNflDraftBoard.ts:10`, `NflDraftRoom.tsx:93`,
      `PlayerDetailOverlay.tsx:78`, `MockDraft/columns.tsx:43`.
- [ ] **Give the draft board its own route.** It is reachable only as a tab named `camp`
      inside the league hub. A drafter cannot link a friend to it.
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
      tennis. **The props exist and look healthy on the board.**
- [ ] **Link tennis `prop_games`.** 274 of 325 prod ATP/WTA rows have no `espn_event_id` (16%
      linked); dev is 132 of 299. The matcher and budget guards already landed (`b8886e9`);
      this needs a run, not a build. Note `reference_espn_folds_tennis_names`: ESPN folds
      accents in tennis names but not soccer ones.
- [ ] **Settle tennis.** 0 of 913 on prod, 0 of 979 on dev.
- [ ] **Grade or void the World Cup rows honestly.** 392 prod and 1,128 dev `prop_results`
      rows have `actual_value` NULL **and** `hit` NULL. A settled count that grades nothing is
      presence, not integrity.
- [ ] **Get UFC settlement onto dev.** Until then a green dev suite says nothing about UFC.
- [ ] **`team_game_stats` holds 16 MLB rows.** Find out whether that is a stalled ingest or a
      table nothing writes any more.
- [ ] **Promote MLS to prod parity:** game logs **10,603 prod vs 21,177 dev**, stories 0 vs 30,
      leaders stuck on 2025 while standings serve 2026. All data jobs, none needs a deploy.
- [ ] **MLS and NCAAF scoring plays: zero on both.** Confirm the publisher has them before
      recording it as a gap (`feedback_we_systematically_underread_publishers`).

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

- [ ] **Split the log surfaces:** game logs, player game logs, player stats, team stats are four
      different products rendered as one line today.
- [ ] **What YEARS are available**, per league per surface. Report the **set**, not a min-max
      range: the interesting case is a GAP, and a range hides it. Live example, not
      hypothetical: prod MLS standings serve 2026 while `/api/mls/leaders` offers
      `available_seasons: [2025]`.
- [ ] **What PROPS exist per league**, meaning distinct `props.market` values and counts. A book
      pricing a market our grader cannot map produces props that land, look healthy and never
      grade. **NFL's 1,080 unsettled props are that shape.**
- [ ] **WHERE the props come from.** `props.source` per league. We ingest from Bovada, Underdog,
      RotoWire and PrizePicks and render them as one number.
- [ ] **Are they RESOLVED**, split by source and by market. Key settlement on
      `actual_value IS NOT NULL`, **never `settled_at`**: settlement stamps a timestamp on props
      it could not map, so the timestamp records that something RAN, not that anything landed.
- [ ] **Are settled props REACHABLE.** One explicit ratio per league: of the props settled, how
      many hang off a `prop_games` row with an `espn_event_id`. Everything else is data we hold
      and nobody can see.

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

- [ ] **Bovada and Kalshi live games**, plus a game detail from each.
- [ ] **Daily RotoWire props dump.** Save everything that endpoint gives us to a directory once a
      day, in case we expand to those leagues.
- [ ] **Schedule the RotoWire relay ingest.** Built 2026-08-19
      (`backend/ingest_rotowire_props.py`), live on both databases, **nothing schedules it** and
      the cadence is an open decision. Still uncovered by it: NCAAF (opens Aug 29), WNBA (0 of
      17, in season), NBA, NHL.
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

## 13. Promoted out of the archive, ALL UNVERIFIED

**These were unchecked items sitting below the old `# Ledger` heading**, where the rule
"history, do not rewrite" kept them from being read or re-measured. They are listed here so
they are visible. Full original text is in `docs/ROADMAP-ARCHIVE.md`.

**Every one of them is UNVERIFIED as of 2026-08-20 and most predate 2026-08-11.** Rule 7
applies: re-measure before working one. Do not treat this list as a set of confirmed defects,
and do not treat it as noise either; `B8` is user-reported.

**User-facing, check these first:**

- [ ] **B8. The player page renders the wrong game-log columns for K and D/ST.**
      **User-reported.** A kicker's log showing skill-position columns is visibly wrong.
- [ ] **B8 (mock-draft series). Kicker game data does not exist; Brandon Aubrey renders a false
      figure.** A fabricated number is worse than a blank (`project_lp_honest_data_ui`).
- [ ] **B15. `adp: p.adp ?? 999` fabricates an ADP in the UI.** Same shape as above.
- [ ] **R7. Player search on the draft board.** Marked user-blocking when written.

**Correctness, unverified:**

- [ ] **B1.** Mid-season team change doubles the availability denominator.
- [ ] **B2.** `team_game_results` has two incompatible key schemes.
- [ ] **B3.** Team abbreviations disagree between tables.
- [ ] **B7.** `players.nfl_gsis_id` mixes two id schemes.
- [ ] **B9.** `players.position` has the same two-vocabulary split as `players.team`.
- [ ] **B10.** Playoff rows in `player_game_logs` are unmarked.
- [ ] **B11.** D/ST ADP is published; we derived it instead
      (`feedback_check_if_the_value_is_published`).
- [ ] **B14.** `team_games` absent from the mock-draft pool payload.
- [ ] **M2.** Availability computed from a table that cannot express it.

**Gates and tests, unverified:**

- [ ] **B4.** Three draft-board tests red for a fixture gap.
- [ ] **B5.** `test_league_stats_contract` failing.
- [ ] **B6.** The 16-row NFL cleanup is not reproducible.
- [ ] **B16.** Two jest suites fail and no gate covers them.

**Product decisions that need Micah, not us:**

- [ ] **R5.** `--all-positions` for IDP and kickers.
- [ ] **R9 / R8.** Accounts, with the mock draft as the reason to make one; draft notes fold into
      it.
- [ ] **M3-M7.** Mock draft familiar-UX objects, resume and share, player detail overlay, camp
      card resume state, room polish.

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
