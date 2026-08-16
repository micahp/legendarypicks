# Changelog

## v0.8.0 — 2026-08-11

### Kick viewer counts, silently null since the keys were never hydrated

- **`KICK_CLIENT_ID` / `KICK_CLIENT_SECRET`** (`83bf00d`). `_hydrate_esports_keys()`
  self-hydrates missing esports keys from the dev secrets file at startup, but its
  allowlist omitted both Kick OAuth credentials. Liveness kept working, so nothing looked
  broken — the official viewer-count lookup just had no token and degraded to null with
  `token_unavailable`. Both keys are now on the allowlist. The shape is the familiar one:
  the surface answered, so the absence never surfaced.

### League news engine

The engine went from a POC to something that serves cards, and most of the work was
learning what it is allowed to say.

- **What it reads** — ESPN league feeds plus the story bodies the `www` host refuses
  (`71b094c`), RSS, Bluesky, 13 X accounts where the handle supplies the league
  (`54096e8`, `b87acb0`), and topic-matched Google News articles (`2c15559`). The
  sport-wide soccer rollup is collected but deliberately kept out of the nightly run
  (`e3b6433`) — it poisons the corpus with leagues and players we do not cover.
- **What a card is** — one topic, not a league roundup (`efcd60a`). Cards are organized by
  conversation (`e037bd5`), and the pool is ranked rather than gated (`c1e790e`): chatter
  ranked on the seed, anchors ranked on the seed plus the entities the best chatter
  actually mentions. Ranking cannot rescue an item that was never a candidate, so anything
  carrying a seed word is a candidate at any age.
- **Topic discovery** (`c8c956d`, `323545b`) — the seeds became training data rather than a
  fixed list, and each league is also sampled un-seeded so discovery is not anchored to
  topics we thought of first.
- **The trust model, after it failed in public.** A card asserted that Inter Miami had
  suspended Messi and Suárez over a racial-harassment probe. Suárez's six-game Leagues Cup
  ban is real and published; the cause is published nowhere; the Messi suspension is false
  — he was in Argentina after his father's death, which publisher items *in the same pool*
  reported. Not unsupported: contradicted. Fixes, in code rather than instruction:
  `x-search` unwired and its 1,056 unattributable rows purged (`d3d6ab6`), since Google
  hands over a post's words and a redirect and nothing else — no author, no handle, no
  permalink; `unsupported_allegation()` refuses to serve an allegation about a person with
  no publisher receipt; `had_publisher_material()` refuses a card whose pool holds no
  published reporting (`c7d13e4`). Where a publisher and a social post disagree, the
  publisher wins.
- **And the correction to that fix** (`6ae85e8`). Requiring the *model* to cite a publisher
  dropped 11 of 14 otherwise-good cards over a missing JSON field — trusting model output
  as a control, the same mistake in a new place. What is checked is whether a publisher
  item was in the pool, which we can verify ourselves. The safety wording in the prompt was
  then trimmed 1,536 → 585 characters after the long incident narrative pushed the desk to
  decline 10 of 14 conversations that each had 12 chatter items and 6 publisher anchors.
  Declining is not safety when there is real reporting to write from. Declines: 10 → 2.
- **Editor feedback loop** (`8dc19cf`) — run-level good/bad verdicts steer generation.
- Timestamps served as real UTC (`fe132cc`), publisher text and dates normalized at ingest
  (`114c914`), whole-word matching in the layer rules (`c63add6`), and a wide batch that
  will not parse now retries in chunks (`7f4a155`).

### Soccer: Leagues Cup and MLS

- **On the scoreboard** (`b0179d5`), with game-detail tabs (`61c87c6`), the live stream and
  From the Booth on the right feed (`5101dd7`, `2ccc59b`), the live minute on game detail
  (`f8620d4`), and suspended matches labelled SUSPENDED rather than FINAL (`e69188e`).
- **MLS on the hub** (`ad7a9df`). Standings, schedule-dates and coverage have vouched MLS
  for a while — it simply had no card on `/leagues`, so the only way in was to type the
  URL. It now carries its own name and crest rather than falling back to a generic trophy.
  Which tabs appear is still the coverage registry's call: team-stats is nba/nhl/nfl only.
- **NCAAF is deliberately absent** — see its own section below. The reason changed during
  this release and the earlier one is no longer true: the backend now answers for ncaaf
  (`/api/ncaaf/standings` and `/api/ncaaf/team-aggregates` both 200 on dev, 137 teams).
  It stays hidden by decision, not by absence.

### NCAAF: built, banked, and not shipped

College football was built end to end this cycle and **does not ship in this release**. It
is recorded here rather than left out, because the work is real and the next person needs
to know it exists and why it is dark.

- **What landed on dev** (`2d6ab86` and the league-ncaaf task): 20,926 players, 56,577
  player game logs across 888 games and 137 canonical FBS teams, 1,776 team results and
  1,776 team stat rows, and 4,267 season stat rows sourced from CFBD. Logs carry defensive
  stats — tackles, sacks, INTs — and every log has a non-NULL `game_type`.
- **FBS is a published group, not a filter.** ESPN's college-football `teams` collection is
  807; FBS is `types/2/groups/80/teams` = 146. Checking 911 games against 807 teams invents
  a 660-team gap. The group id is recorded as data in the league registry rather than
  sprinkled through queries. There is also no games-per-team constant — schedules are
  uneven, so any "N of M team games" line takes M from that team's own published count or
  does not render.
- **Conference standings** read the published sub-groups rather than a hand-maintained
  conference map, and omit the soccer-only fields instead of fabricating zeros.
- **Why it is dark** (Micah, 2026-08-11). Not a data verdict — the remaining work is in the
  surfaces and the schema, and other features outrank it. Narrowing to three conferences
  was considered and rejected: we already hold all 137 FBS teams, so a smaller scope saves
  nothing on the ingest and does not shrink what is actually left.
- **Known open, recorded so it is not rediscovered.** `league_stats.py`'s ncaaf contract
  never landed in main, so dev holds 4,267 rows its own code calls unsupported and
  `COV-identity` fails there. `player_stats` grew a second column family (`att`/`rec`
  duplicating `attempts`/`receptions`; `pass_yds` is a season total and is *not* a
  duplicate of the per-game `pass_yds_g`). `ncaaf_conference_standings()` lives only in the
  worktree and derives rank from array position. `C/vocabulary[position]` holds two levels
  of one vocabulary in one column.
- **Production is not empty of NCAAF, and search was serving it.** Measured 2026-08-11:
  prod holds **11,914 ncaaf players and 56,577 ncaaf game logs** (`player_stats`,
  `team_game_results`, `team_game_stats` and `team_stats_coverage` are all zero there).
  With no coverage row the hub correctly hid the league — and `/api/players/search`
  returned it anyway: `?q=Bates` gave 4 NFL players and **7 NCAAF**, each linking to a
  working player page. Having data for a league is not the same as offering it, and until
  now only the client asked which. `backend/league_offering.py` answers it on the server
  from `team_stats_coverage`, and search filters on it (UFC and WC are named as shape,
  since they are not team-stats leagues and will never have a row). It is derived, never a
  league list: a league turns on when its coverage row is promoted and off when it is not
  vouched. Prod now offers mlb/nba/nfl/nhl/ufc/wc; dev additionally offers mls and ncaaf,
  so development is unaffected. A database with no registry fails closed.

### Esports and EWC 2026

- The Esports league destination at `/leagues/esports` (`668a160`, `78eb91b`) with tabs, an
  inline all-esports board and interactive title filtering; `GET /api/esports/titles`
  (`ccbc866`); the EWC center moved out of the `/esports` page and into the hub
  (`0c74089`, `1dab7f7`).
- Club Championship standings from the Liquipedia MediaWiki API (`4d19ef0`) with club logos
  on every row — HTTPS-normalized publisher logos, local index reconciliation and a crest
  fallback (`2ce6c62`), loaded without hotlink referrers (`ba422ca`).
- Verified EWC title schedules and history from PandaScore and Lichess (`d6591ee`,
  `12ceef9`), data-derived title coverage (`ec70cd1`), and qualifier series excluded from
  event focus (`c64f6df`).
- **Logo index** (`8864af9`): 265 → 288 entries, append-only. Seven of the new teams
  resolve to a crest; the other sixteen are recorded as an empty string, which means
  "asked, none published" rather than "not asked yet".

### Backend and database, everything since v0.7.0

343 commits. Grouped by what actually changed underneath, because most of these are
invisible from the UI right up until they are not.

**Schema and migrations.** A migration *runner* replaced hand-application: one invocation
migrates both databases and adopts the 20 legacy scripts (`322b5e9`), each recorded in
`app_schema_migrations` with a hash and an explicit `applied` / `not_applicable` verdict —
"dev is the source; the script only writes the prod target" is now a recorded state rather
than a thing someone remembered. The app **refuses to serve an un-migrated database at
startup** (`758c82d`) instead of answering 200 over a missing column. Dev→prod copy scripts
are probed on the prod side of the ledger (`5924ab9`), after a run of fixes that landed on
dev and never reached prod.

New columns and tables across the cycle: `news_items` and the whole news store (`7dbf63c`),
`news_items.conv_id` and `team_game_results.result` (`597033b` — prod never got what dev
added), NFL TD columns (`047496b`, zero rows in prod through three releases), NHL goalie
columns, MLB counting stats (`pa/ab/hits/runs/rbi/era/innings/whip`), player injury columns,
player entity type, fantasy positions, and NFL/NBA `position_group` (`836083e`).

**team_game_stats moved to JSON** (`b227781`), matching `player_game_logs`. It was one wide
table encoding NBA's and NHL's idea of a game — NCAAF filled 5 of ~45 columns, MLS filled 2
by borrowing NHL's `shots`/`blocked_shots`. Additive and two-sided: writers fill the blob
and the frozen columns, readers prefer the blob and fall back, so a database migrated at a
different time from its code is redundant rather than wrong. 8,452 of 8,468 rows migrated;
the 16 mlb rows are skipped as UNVERIFIED rather than emptied. Verified by comparing the
pre-migration backup against the migrated file with the same code — every team's every
aggregate identical across all six leagues — then by proving the blob is the live source,
since identical numbers would also be what "the blob is ignored" looks like.

**Identity, which is where the real bugs were.** Props landing on the wrong same-named
player (`674f178`, `4edb64f`); MLB rows holding a same-named person's `mlbam_id` (`4f405db`,
one of them a man who debuted in 1945); publisher-sourced MLB team refresh with identity
invariant tests (`03d906b`); a promotion tool that matched on publisher id and then vetoed
on a raw name string, so Pedro Ramírez and Pedro Ramirez — one man, same ids in both
databases — refused an entire league's promotion (`7cb9fbd`). `player_stats` is keyed by
`player_id`. The shape repeats: **an ambiguous key never raises, it misses.**

**Settlement and grading.** MLB was skipping the finality gate and grading against live box
scores (`e20b736`); every MLB prop re-graded against a final (`53021ae`); a game matched by
its teams rather than the calendar day it was filed under (`651176e`); the final keyed on
`gamePk` rather than `(date, home, away)` (`989153e`); box-score athletes matched by ESPN id
rather than surname (`7c44f06`); an absent stat voids a prop instead of grading it 0.0
(`fb0927b`); a game is final when the publisher says `completed`, not `"post"` (`cbacc7a`);
home/away read off ESPN's own flag instead of matching names (`dac9fbf`). The player name
was stripped out of **561,543 market keys** and everything re-graded (`5bee747`).

**ESPN request budget.** The limit is a request *count* per host (~100), not a rate, so
pacing does not buy budget — only issuing fewer requests does. The relink repair obeys it
and fails loud (`c59e9b6`); `link_prop_games` now states its spend before issuing any of it
and refuses over 50 requests to one host, including on `--dry-run`, which skips the write
but not the HTTP (`b8886e9`). An unscoped run was 189 requests against a ~100 ceiling.

**Fail-closed reads, after a night of walled hosts.** Game detail had two independent
single-source dependencies on ESPN — `is_final` came only from a live call, and the final
score read only `scoring_plays`, which holds zero rows for ncaaf, nfl and mls. Both now ask
our own database first (`405ebe8`). `prop_games.start_time` backfilled from the published
scoreboard (`e634890`) and settlement allows for two publishers' clock drift (`f6fed51`).

**Build and gates.** Databases excluded from the Docker context **by name**, gated with a
test (`ad90392`) — `*.bak` never matched `data/*.bak`, which baked 7GB of backups into the
production image. The release preflight blocks on schema/season divergence and the data
audit (`f82bdd1`). `verify-gates.sh` refuses to run when `LP_DB_PATH` is set but `LP_GATE_D`
is not (`271534b`): it never read `LP_DB_PATH`, and its own default is **prod**, so pointing
the wrong knob produced a confident number about a database you did not mean to grade.

### Audit and contract

- **NHL qualifier was published all along** (`4ff583a`) — re-asked the right endpoint, now
  PASS. A gap is a statement about which endpoint we asked.
- Leagues with no leaderboard surface are UNVERIFIED rather than FAIL (`84cefac`);
  `B/position-content` declared for mlb/nba/ufc/wc (`01e6986`); section 7 of the coverage
  contract rewritten so adding a league is a declared, checkable path (`c0ca67d`).

### Docs

- **`docs/BROADCAST-CAPTURE-ECONOMICS.md`** (`58c0eb0`) — what it would cost to capture
  every audio feed and pay for the video subscriptions, plus the cross-league tournament
  gap: Leagues Cup and EWC do not sit inside one league's news section.
- **Roadmap: who is actually playing** (`13e031a`) — soccer availability before kickoff.
  The engine reports absences after the fact; the game detail page should say who is out
  before the match. Deferred to its own session.
- **The X account list, documented** (`3bfc32b`) — `docs/PLAN-league-news-engine.md` now
  records which accounts we cover and why each one is on the list.

### From the Booth is dev-only

`NEXT_PUBLIC_SHOW_BOOTH` (`bf36fcf`). Production does not run the broadcast capture the
feed reads from, so the tab opened onto nothing there. Off unless explicitly `true` —
absence must read as hidden, since a missing var is exactly what production looks like.
Dev sets it in `.env.local`, which is gitignored *and* excluded from the Docker build
context by `.dockerignore`, so the production bundle is built without it and the feature
compiles out. The render is gated as well as the tab list: hiding a tab does not unreach
it.

### MLS props reached the database but not the page

`b8886e9`. MLS game detail said "props aren't available" while the database held 714 props
across 15 games. The page joins on `prop_games.espn_event_id` and 13 of 15 MLS rows had
none, so the props existed and were unreachable. Two independent reasons the crosswalk
never matched:

- The name fallback read `displayName`, which the scoreboard payload does not publish —
  its team objects carry `abbrev`/`name`/`nickname` and no `displayName`. The branch
  compared against `None` for every game and was dead code.
- `_norm_team` has no MLS map and fell through to "first three letters", which for MLS
  manufactures collisions: "San Diego FC" and "San Jose Earthquakes" both become `SAN`.
  That is worse than a miss — a wrong link is invisible, hides the props from the game that
  was played, and settlement can never resolve it. Unmapped leagues now return "unknown"
  and match on the published name instead.

The rows are not linked yet: `site.web.api.espn.com` is refusing, and a spent host is not
restored by waiting. Re-run `link_prop_games.py --league mls` when it recovers.

### Version note

The version line had forked four ways: `package.json` read 0.7.7, `git describe` from dev
said v0.7.8, the tags at v0.7.9 and v0.7.10 sat on `release/ewc-v0.7.10` — not an ancestor
of dev — and this file already carried an untagged v0.7.11 section. `release/ewc-v0.7.10`
is now merged back, so dev's history contains every shipped tag and goes 0.7.10 → 0.8.0.

Two numbers had to be untangled. The position-vocabulary work above was written up as
"v0.7.9 — 2026-08-05" but `836083e` is in no tag at all, and the EWC CoD hotfix later took
the real v0.7.9 on 08-09; those notes are now a section of this release rather than a
number already spoken for. The esports files conflicted add/add because dev had
re-developed them further — `routers/esports/ewc.py` is 669 lines on dev against 321 on
the branch — so dev's versions were kept and the branch supplied only its release notes.

### Two players with one name: props landed on the wrong man

- **The resolver refuses to guess** (`674f178`). `_resolve_player_for_ingest` opened with
  `SELECT id FROM players WHERE name=? AND league=?` and `fetchone()`. Two men named Max
  Muncy play in MLB, so every Muncy prop collapsed onto whichever row the database yielded
  first — row 96, the Athletics one. Nothing raised; an ambiguous key never raises, it
  misses. A name matching more than one row is no longer a match: it is separated by the
  source's team, else by which candidate's team is actually in the game (`game_id` is now
  threaded through from the ingest and folded through the same published team map the ESPN
  crosswalk uses, because `prop_games` holds both `"Los Angeles Dodgers"` and `"LAD"`), and
  failing both it goes to `unresolved_players` instead of onto the wrong player. Step 2's
  `LIMIT 1` got the same treatment.
- **The repair** (`4edb64f`). `repair_mislinked_same_name_props.py` moves props off a
  same-named player who was not in the game, and deletes their results rather than
  rewriting them — they were graded against a box score the man never appeared in, and the
  grader decides the new value. On prod: **438 props** moved from the Athletics Muncy to
  the Dodgers Muncy across five Dodgers-only games, **276 wrong results dropped** and
  re-settled correctly against his real box score. Row 96 now holds 329 props and not one
  of them is on a game the Athletics did not play.
- **What it refuses to touch.** A row with no publisher id is a stub someone's ingest
  minted, not a second man; repointing props across it would hide a duplicate that wants
  deduping. Three same-name collisions are named by the script and still open: James
  Outman (row 29097, 584 props, no `mlbam_id`), Luis Castillo (row 27342, 266 props, none
  of them grading) and Jared Jones (row 27809, no team).

### Position vocabulary: the release gate is fully green

- **NFL/NBA `position_group`** (`836083e`). The last two release-blocking FAILs
  were `C/vocabulary[position]` — "two levels of one vocabulary in the same
  column: FB under RB" (NFL) and "PF under F" (NBA). Same shape MLB solved with
  `position_group`; this extends it. `migrate_league_position_groups.py` fills
  the column from the committed publisher vocabulary (the top-level ancestor's
  name: WR→Offense, CB→Defense, PK→Special Teams, PF→Forward, SG→Guard,
  C→Center). Additive, idempotent, VACUUM INTO backup first. Applied to both
  DBs: dev 27,274 rows, prod 27,652 rows, quick_check ok.
- **Gate scope** (`836083e`): NFL/NBA specs declare `position_group`; the
  fantasy-construct blank exemption extends to it (a D/ST has no position and
  no group, and entity_type keeps the populations distinct).
- **Ledger** (`836083e`): the migration is recorded in the both-DB runner.

**Audit vs prod: 0 FAIL, 40 passed, 3 UNVERIFIED (non-blocking).** The
release preflight now passes end-to-end.

## v0.7.10 — 2026-08-09

### The full EWC tournament center is live

- The Esports league destination now carries the EWC 2026 tournament center: live and upcoming
  matches across titles, results, title discovery, and the published Club Championship table with
  explicit source, freshness, stale, and unavailable states.
- EWC Call of Duty bracket slots are reconciled against the PandaScore bracket graph. Undecided
  participants render structurally as `Winner of ...` or `Loser of ...`, while completed clubs use
  their canonical identities; raw `TBD` values no longer reach the CoD scoreboard.
- `/esports` remains the broadcast-first live board, while `/leagues/esports` owns the EWC
  tournament-center experience and `/leagues` provides its entry point.
- This release is intentionally isolated from the unfinished news engine and the MLS/NCAAF work.

## v0.7.9 — 2026-08-09

### EWC CoD finals show the clubs that actually played

- Breaking Point's EWC match rows carry authoritative `team1` and `team2` objects even
  when those clubs are absent from its page-level `allTeams` dictionary. The CoD
  scoreboard now uses those embedded participants as its fallback, so completed EWC
  series render club names and scores instead of `TBD` versus `TBD`.
- This production hotfix is intentionally limited to the CoD scoreboard normalizer; the
  news engine and the broader new-leagues work are not included.

## v0.7.8 — 2026-08-05

### Migration ledger: one invocation, both databases

- **`backend/migrate_all.py`** (`322b5e9`). Six of the seven 2026-08-05 defects were
  "verified on dev, never shipped to prod" — two manual actions with nothing coupling
  them. The runner removes the second action: `--check` / `--apply` target **both**
  databases by default, apply every numbered migration through the ledger
  (`app_schema_migrations`), and record the 20 legacy hand-run migration scripts with
  an honest per-database status (applied / not_applicable / explicit unknown — never
  guessed). Re-running is a no-op.
- **Startup guard** (`758c82d`): the app refuses to serve an un-migrated database —
  `no such column: pa` is now impossible to reach in production. Tests opt out via
  `LP_SKIP_MIGRATION_CHECK=1`.
- **Backup policy** (`b0bffae`): every backup is `VACUUM INTO`, never `cp` (a plain
  copy of a live DB races writers — proved malformed 2026-08-05). `prune_backups.py`
  keeps the 10 most recent per prefix; doc-referenced baselines are never pruned.
  Applied: 98 files / 16GB → 24 files / 4.1GB.
- **diff_databases** (`089a014`): feature-not-deployed tables classify as advisory
  FEATURE drift; migration-owned SCHEMA/SEASONS is the only blocker. Zero SCHEMA and
  zero SEASONS differences between prod and dev.

### Identity: nickname aliases + consolidation artifact

- **NBA identity merge applied to prod** (`c177ff3`): 269 split pairs → 0 (was the
  F/identity-crosswalk FAIL), NBA players 1140 → 871 matching dev.
- **NFL team vocabulary promoted** (`73f4396`): nfl 2024 team-game-results window
  (570 rows) + the earlier 2,495 nflverse→ESPN code rewrites. `team_game_results` now
  serves all six league/season windows on prod.
- **`G/published-identity` nickname aliases** (`90e3bdd`): 16 rows across NBA/NFL/NHL
  were the same human under a different published name form (Kenny vs Kenneth
  Gainwell, Nate vs Jeenathan Williams). Decision: the market-facing nickname is
  canonical (ESPN fantasy and Yahoo both publish Kenny Gainwell) — rows stay, the gate
  learns accepted alternates from `data/name-aliases.json`. The gate stays strict
  about people; an id absent from the file has no alternates. G now PASSes on all four
  leagues on prod and dev (NBA 541 / NFL 24,344 / NHL 840 / MLB 1,346 ids checked).
- **Consolidation artifact** (`90e3bdd`): `data/identity-consolidations.jsonl`,
  append-only. Every merge path (merge_nba_identities, dedupe_mlb, MLB repair copy)
  logs what got consolidated — from/to names, repointed counts. A consolidation
  without a log line is a defect.

## v0.7.7 — 2026-08-05

### The v0.7.6 known regression is fixed — MLB leaders serves again

- **`repair_mlb_identity_names.py --exact`** (`7b571c3`). The prod dedupe repointed
  duplicate `player_stats` rows to their canonical `player_id` while keeping the
  duplicate's spelling, so 242 rows disagreed byte-for-byte with `players.name` and
  the leaders endpoint's raw-string guard **503'd in production**. Neither table was
  the authority — the spine held `Heriberto Hernandez`, the stats row held the
  published `Heriberto Hernández` — so `--exact` writes **both from the publisher**
  rather than copying one into the other. 310 renames + 65 display-copy re-syncs,
  remaining disagreements **0**, gate G still PASS. `/api/mlb/leaders` back to 200.

### `position` keeps what the publisher published

- **The `OF` → NULL rule from v0.7.6 was wrong and is reverted** (`5844413`). ESPN and
  MLB *both* publish `OF` for Cristian Pache; that is a fact about him, not a gap. The
  data had been bent to satisfy `C/vocabulary[position]`, which is backwards — **a gate
  is a check, not a spec.** `position` now holds the published abbreviation verbatim,
  `position_group` carries the parent, and **check C learned the parent/child model**:
  a published parent beside its children is legitimate when the league declares a group
  column, and still a defect when it does not.

### Identity maps for all four leagues, each from the id's own issuer

- `fetch_identity_names.py` fetches NFL (nflverse `players.parquet`, `gsis_id`), NHL
  (`api.nhle.com` skater **and** goalie summaries — separate reports, separate name
  keys), NBA (hoopR, newest published season) alongside MLB (`3267fb5`). A league whose
  fetch fails is omitted with the reason recorded in `_provenance.errors`, so it reports
  UNVERIFIED rather than silently shrinking the map.
- **Measured, and this is the point of the exercise:** MLB PASS (1346), NBA PASS (541),
  NFL 4 of 24344, NHL 11 of 840. **All 15 are the same human under a different published
  name form** — `Kenny`/`Kenneth Gainwell`, `Josh`/`Joshua Dunne`. The gate is strict,
  not wrong, and MLB's corruption was singular rather than systemic. Newly found in the
  same family: `Kenneth Piper` is MLB's `Kenny Piper` (`700652`) — recorded by two of us
  as "MLB does not publish him" when the truth was "our exact-key match could not see
  him."

### Docs — the five defect shapes

- `DATA-COVERAGE-CONTRACT.md` §7b (`983b633`). Every defect found across this work was
  one of **five shapes**: an id naming the wrong person; two publishers' vocabularies in
  one column; two rows for one person; a display copy diverged from its source; a value
  in the logs but not the season table. None of them raise. Ordered per league, with the
  rule that **shape 1 precedes shape 3** — a dedupe's "same id = same person" is false
  while identities are unverified — and the note that **diagnosis generalises and repair
  does not**, so audit every league and repair only what the product needs.
- Recorded as unmeasured, not passing: `atp`, `ufc`, `wc`, `wnba`, `wta` have no MANIFEST
  entry.

### Live in prod data (no code change)

- **The NFL board can now actually sort by touchdowns.** v0.7.3 shipped the columns and
  the ingest was never run against prod: `rush_td` and `rec_td` sat at **0 rows** through
  three releases. Republished 608 rows from the same nflverse artifact dev used —
  `rush_td` 137, `rec_td` 258, `attempts` 76, Jonathan Taylor 18 / Derrick Henry 16 /
  Josh Allen 14. `A/required-stats[season]` and `E/qualifier[season]` FAIL → PASS.
- MLB closed out on both databases: `C/vocabulary[position]`,
  `C/vocabulary[position_group]`, `C/vocabulary[team]` and `G/published-identity` all
  **PASS on prod and dev**.

## v0.7.6 — 2026-08-05

### MLB position now carries one publisher's vocabulary, one level per column

- **`players.position` held two publishers' vocabularies split by the `active`
  flag, plus two levels of one vocabulary** (`d68d3d2`, `da63c5a`). `roster_sync`
  wrote ESPN's `SP`/`RP` on active rows; `ingest_mlb_spine_identity.py` wrote
  MLB's `P` on the rest, so `WHERE position='P'` returned players who are all
  retired and `WHERE position IN ('SP','RP')` returned players who are all
  current — and MLB's group-level `OF` lived in the same column as `LF/CF/RF`,
  so `WHERE position='OF'` returned 1 of 129 outfielders. Nothing raised.
- **Fix: three columns, each exactly one level from exactly one publisher.**
  `position` = MLB `primaryPosition.abbreviation` (specific spots only; the
  group-level `OF` is written as NULL), `position_group` = MLB
  `primaryPosition.type` (Pitcher / Catcher / Infielder / Outfielder / Hitter /
  Two-Way Player), `pitcher_role` = ESPN's `SP`/`RP`, active MLB rows only.
  `migrate_mlb_position_vocabulary.py` is purely additive (ADD COLUMN only,
  idempotent, backup-first) and the two writers fill the columns.
- **`roster_sync` stopped overwriting MLB's published position with ESPN's role
  vocabulary** (`405a41e`); **ESPN-only rows are now resolved against MLB's
  published roster in both directions** (`920eed3`); **middle-initial homonyms
  are bucketed so team-narrowing can separate them** (`401a8e0`).

### Identity maps exist for all four leagues, each from the publisher that issued the id

- `fetch_identity_names.py` now fetches NFL (nflverse `players.parquet`,
  `gsis_id`), NHL (api.nhle.com skater **and** goalie summaries — goalies are a
  separate report with a separate name key) and NBA (hoopR, newest published
  season) on top of the existing MLB map (`9ec78e4`). The fetcher landed in this
  release; it has not yet been run against the served databases, so
  `G/published-identity` reports UNVERIFIED for NFL/NHL/NBA until it is.

### Dedupe no longer aborts on `player_stats` key collisions

- 188 of 317 duplicate-mlbam groups had **both** rows carrying a `player_stats`
  row for the same `UNIQUE(player_id, league, season, stat_type)` key — the
  repoint UPDATE would have raised. `dedupe_mlb.py` now keeps one row whole per
  key before repointing (higher `games`, else more non-NULL stat columns, else
  lower id), deletes the loser in the same transaction, drops `predictions`
  from `REF_TABLES` (game-level, no `player_id`), and lets a missing table
  raise instead of reporting a reassuring zero (`d869fa4`).

### Docs

- The identity-pairing defect (right id, stranger's name — Statcast's
  `player_name` is the pitcher's on every pitch row) and its measured
  fingerprint, recorded with the gate that would have caught it (`83c9588`);
  the dedupe's "identity-safe" claim corrected from property to verified state
  (`72b7ab4`).

### Known regression — MLB leaders 503 on prod after the dedupe run

- The prod MLB dedupe run (2026-08-04/05) repointed duplicate `player_stats`
  rows to their canonical `player_id` but kept each row's `player_name` — the
  duplicate's placeholder spelling (`max muncy`, `salvador pérez`), which the
  v0.7.5 identity repair deliberately left alone because its normalized key
  already matched. 242 canonical 2026 rows (214 batting, 28 pitching) now
  disagree byte-for-byte with `players.name` (215 case-only, 27 real: accents,
  middle-initial, `Jr.`), and the leaders endpoint's raw-string guard 503s:
  "canonical player stats disagree with the player index for mlb season 2026;
  rebuild required". Dev is clean. Regenerating the display copy from the spine
  is its own repair task.

## v0.7.5 — 2026-08-04

### An external id now has to name the right person

- **223 MLB players carried another player's `mlbam_id`, and nothing had ever
  checked** (`2947199`, `a53bb93`). `players` holds one id per publisher and
  every join runs through them, but no test asserted that the id and the name on
  a row describe the same human. `id=26551` read `Eiberson Castellano` against
  `mlbam_id=703607`, which MLB publishes as Henry Bolte. A wrong id does not
  raise — it mis-joins, silently. `COV-statset` check `G/published-identity`
  now fails on that state, against a committed snapshot of each publisher's own
  id → name map (`fetch_identity_names.py`, 1,358 MLB pairs). Leagues with no
  snapshot report UNVERIFIED, never PASS.
- **Root cause: Statcast's `player_name` column is the pitcher's name.** The
  pre-`b03b9c9` batter fallback took `player_name.iloc[0]` — whoever threw the
  first pitch of that batter's group — while `player_id` came correctly from
  `batter_id`. Right id, stranger's name. The fingerprint is unambiguous: 201 of
  203 resolvable wrong names belong to a pitcher, and 203 of 203 true owners are
  position players. Not a positional shift — offset 0 scores 1072 correct and
  every offset from −5 to +5 scores 0.
- **Repaired id-first, never by name match** (`1df987c`). Name matching is what
  produced this. `repair_mlb_identity_names.py` takes the published name for each
  `mlbam_id` and writes nothing else: 223 prod / 167 dev names changed, **0**
  `mlbam_id` writes, every row count in `players`, `player_game_logs`, `props`,
  `player_stats` and `predictions` identical before and after. Gate G green on
  both databases.
- **This is what was blocking the MLB dedupe.** `dedupe_mlb.py` documents a
  shared `mlbam_id` as "provably the same person"; 124 of 317 duplicate groups
  were in fact two different people, and a merge would have repointed 408,610
  prop rows and 26,491 game logs onto the wrong players before deleting the
  originals. A `player_stats` UNIQUE constraint aborted that run by luck, not by
  design. The count is now 0.

### The backend image is 292MB instead of 7.45GB

- **`.dockerignore` never excluded the database backups it named** (`c6b2728`).
  A bare `*.bak` does not cross a `/`, so it matched nothing under `data/`, and
  every build baked 7.7GB of DB backups into the image. `/app/data` is now 52MB
  and no backup ships. Docker reads `.dockerignore` only — `.gitignore` has no
  bearing on the build context, which is why the entries looked correct.

### Fixes

- **`roster_sync`'s pacing and disk cache applied only to `main()`** (`408b7b2`).
  Anything entering through `import roster_sync; sync_league(...)` — which is how
  the prod run gets in — got neither, and paid 128 requests over 188s against a
  cache that was right there. `sync_league` now configures them itself:
  0 requests, 1.7s over 124 rosters.
- **`dedupe_mlb.py` repoints `roster_memberships` and `roster_snap`** (`e7315a1`).
  Both carry a `player_id` and neither was in `REF_TABLES`. They hold 0 rows for
  duplicate-group players only because MLB `roster_sync` has never applied; the
  loop swallows `sqlite3.OperationalError`, so the omission would have orphaned
  them without a word.

## v0.7.4 — 2026-08-04

### One HTTP client instead of six copies

- **`paced_http.py` is now the single home for pacing, the per-host budget and
  the retry ladder.** Six modules each carried their own
  `_throttle` / `RETRY_WAITS` / `_RETRYABLE` block, and `espn_client.py` — the
  one every serving path and the heaviest batch job go through — had none at
  all. That asymmetry is what let `roster_sync.py` fire 128 requests back to
  back and trip ESPN's wall: the discipline existed in the repo, just not where
  the requests were. All five ingests, the NHL backfill and the vocabulary
  fetch now import it instead of writing their own.
- **A serving-path refusal no longer blocks a user for 155 seconds.** The retry
  ladder belongs to batch jobs; a caller with a stale payload in hand falls
  straight through to it. Measured: `test_espn_client_degradation` runs in
  0.006s with this, ~465s without.

## v0.7.3 — 2026-08-04

### The NFL board can be sorted by touchdowns

- **`rush_td`, `rec_td` and `attempts` were in a file we already download**
  (`c424c5f`). `stats_player_reg_2025.parquet` publishes 143 columns and the
  ingest's whitelist read 19 of them; these three were among the 124 discarded,
  on every run, before anyone looked. 608 rows filled — Jonathan Taylor 18
  rushing TD, Davante Adams 14 receiving, Josh Allen 460 attempts. Nothing new
  is fetched. `A/required-stats[season]` and `E/qualifier[season]` both go
  FAIL → PASS.

### Every league knows what team its players are on

- **`roster_sync` had never once been able to run** (`627a213`).
  `migrate_roster_snapshots.py` existed and had never been applied to either
  database, so the job died on a missing table before reaching a roster. That,
  not the matching logic, is why `team` was blank league-wide.
- **One unidentifiable player no longer blocks a league.** Any single identity
  failure applied nothing: one Connor Ungar, carried on two rosters, blocked all
  32 NHL teams, and one Max Muncy — there are two of them — blocked all 30 MLB
  ones. Systemic breakage still blocks, on the signals that indicate it: a team
  that produced no usable entry, and an unresolvable share above 2% where real
  rosters sit at 0.00–0.08%. Below that the odd player is queued for review,
  inside the apply transaction so a review row cannot outlive a rollback.
- Active players are now **100% populated for `espn_id`, `team` and `position`
  in all four leagues** — the MLB/NHL spine gap in `DATA-SPINE.md`.

### A defenceman is measured on blocks and hits again

- **The boxscore has been publishing them all along.** `ingest_nhl_logs.py`
  reads `player/{id}/game-log`, which carries ten skater keys and neither
  `blockedShots` nor `hits`. The same publisher's
  `gamecenter/{gameId}/boxscore` carries both for every skater, plus
  `takeaways`, `giveaways` and `sog`, and for goalies publishes `saves`
  directly — replacing a subtraction the log ingest's own comment marked
  INTERIM. One request per game rather than one per player per game type.

### Positions are judged against the vocabulary ESPN publishes

- **The gate was measuring string length** (`0afa1fa`). It called a
  one-character code coarse and a two-character code granular and failed any
  league holding both — wrong in three of four, since hockey's `C/D/G/LW/RW` is
  one vocabulary and football's `S/G/C/P` belong with `WR/LB/CB`. ESPN
  publishes `leaf` and `parent` per position, so the real question is now
  asked: a position and one of its own descendants both in use. NHL goes
  FAIL → PASS because it was never broken; MLB gains the check and fails it on
  `CF/LF/RF under OF`, which a length rule could not see.

### ESPN's limit is a request count per host, not a rate

- **Pacing, a per-host budget and a disk cache now live in the shared client**
  (`1c9e77c`, `9484908`), where five ingests had each written their own copy or
  none. At identical 1s spacing, `site.web.api` served 128 requests clean while
  `sports.core` refused at ~119 — both ~60/minute, so no rate ceiling explains
  either. The budget is 100 per host, then a cooldown; cache hits do not charge
  it, so a refused run resumes for free.
- `_CACHE` was per-process, so its TTLs had never survived a single run. A
  repeated job now costs **0 requests** instead of re-paying for bytes it
  already had, and because `backend/data` is bind-mounted into the container, a
  dev run and a prod run the same night share it.
- Two superseded ingests refuse to run rather than silently clobbering their
  replacements (`4865105`, `4970960`).

## v0.7.2 — 2026-08-04

### Three leagues were describing their players with the wrong stats

- **Hockey has three player types and `player_stats` had columns for one**
  (`76556d1`). Every goaltender in the database read `0 goals, 0 assists,
  0 shots` — a goalie described entirely by things goalies do not do — and a
  defenceman had nowhere to record a block or a hit. This was carried in
  `LEAGUE-STAT-GAPS.md` as a missing publisher. It never was: nhle.com
  publishes goalie and defensive stats league-wide and always has.
  `ingest_nhl_season_stats.py` reads the report that describes each type
  (`goalie/summary`, `skater/summary`, `skater/realtime`) — ~20 requests for
  the league against ~800 for the per-player endpoint. 78 goalies, 63,525
  saves. `A/required-stats[season]` and `B/position-content[G]` both go
  FAIL → PASS.
- **A season was being served that was actually the playoffs.** `ingest_nhl.py`
  took `seasonTotals[-1]` with no filter on which competition the row belonged
  to. Measured on Frederik Andersen, that row was the postseason (16 GP) while
  his published regular season was 35 GP, 16-14, .874; other players' last rows
  are AHL, Olympic or Swedish league lines. The new ingest asks for
  `gameTypeId=2` and fails closed on a short page.
- **MLB's counting stats were published the whole time** (`f07c841`). PA, hits,
  runs, RBI, ERA, innings and WHIP were recorded as absent, both published
  qualifier rules as unmeasurable, and AB and ERA as "published nowhere we
  hold". All wrong: we were reading Statcast, which publishes exit velocity and
  xwOBA and was never going to carry an RBI, and had never asked MLB.
  `statsapi.mlb.com` publishes both full lines in one request each. Statcast
  keeps the row — only columns it never had are written, and `counting_source`
  records which publisher filled which half, so nothing on the props page
  moved. Four gates go FAIL → PASS.
- **MLB team and position never needed an ESPN crosswalk** (`70a1dee`).
  `players.position` was 100% blank across every MLB player, blamed on the
  spine carrying no `espn_id`. MLB publishes both itself. On active players
  both are now 0% blank, in one vocabulary. Team codes are normalised, not
  copied — MLB publishes `AZ` and `CWS` where this database is `ARI` and `CHW`.

### The NBA leaderboard is current for the first time

- **The ESPN 403 was a request-count problem, not a rate problem** (`6098c2a`).
  `ingest_nba_stats.py` asked for one athlete at a time: 643 requests per
  refresh. That is what tripped ESPN — 143 athletes in at 1s spacing, 21 at 2s,
  and slowing down made it worse — which is why `espn_core` had published zero
  rows ever, for any league, and why this leaderboard served the 2022-23
  season. Pacing was never going to fix a total. ESPN publishes the same season
  in bulk: 578 athletes over 6 pages, same publisher, ~1% of the requests.
  `D/leaders-reach-logs` goes from *season 2023, 53 of 525 (10%)* to
  **season 2026, 576 of 576 (100%)**.
- The bulk payload is positional, with the stat names delivered once at the top
  level. One column inserted upstream would shift every stat after it, and
  every number would be someone else's while every row count stayed healthy. So
  values are zipped by name, never indexed by position, and a category whose
  name count disagrees with its value count raises rather than being read.

### Scores and standings stop blaming our data for ESPN's outage

- **Both surfaces moved off the host that was refusing us** (`7dc3b05`).
  `_SITE` and `_CORE` pointed at `site.api.espn.com`, which 403'd this box for
  a full day and took the live scores page and every standings tab with it —
  rendering "No data available for NBA", which reads as *we have no standings*.
  `site.web.api.espn.com` serves the identical paths: verified across all four
  leagues and both shapes, 8 of 8 return 200 for requests the old host refuses.
- **An upstream refusal no longer becomes a 500.** `_get` keeps the last good
  payload past its expiry and re-serves it when a refresh fails, retrying
  within the minute. With nothing cached it still raises — serving invented
  emptiness would be worse, since an empty standings table is
  indistinguishable from a real one with no rows.

### Gates and groundwork

- **COV-statset check F, identity-crosswalk** (`d4daffc`): can every publisher
  we depend on actually reach this league's players? It distinguishes `split`
  (one athlete on two `players.id` rows — the damage) from `disjoint` (two id
  columns populated, no row carrying both — the condition immediately before
  it).
- **`C/vocabulary` stops calling retired players a defect** (`70a1dee`). It
  counted a blank `team` against every player including those who stopped
  playing years ago, which asserts they should be on a roster. Now scoped to
  active players, with inactive blanks reported in the PASS note rather than
  dropped. Not a way to pass by marking rows inactive — a test fails if an
  active player has no team.
- **The MLB identity rebuild runs** (`7051d4b`, `1cce908`). Rescued from a
  worktree that was about to be deleted, it could not even import — its
  dependency was tracked on four `codex/*` branches. Both documented test
  failures were one gap in the fixture, not two bugs. Verified against a copy
  of prod: 317 duplicate MLBAM groups to 0, 517,008 props preserved. **Not in
  this release** — it archives all 2,653 MLB `player_stats` rows for
  regeneration, so it ships with its regeneration pass.

### Known, and deliberately not fixed here

- Everything above is verified **on dev**. Prod needs its own migration pass
  and a container rebuild for the host fix; there is no systematic dev → prod
  upgrade path yet, and that is the next release.
- `B/position-content[D]` is red on purpose. Blocks, hits and goaltender
  `saves` are all published per game — by `gamecenter/{gameId}/boxscore`, not
  by the endpoint the log ingest reads. Until that pass lands,
  `ingest_nhl_logs.py` derives `saves` and stamps every such row
  `saves_derived` so they can be found and replaced. A game can have two
  goalies, which is exactly where a derivation earns its mistakes.
- `mlb` and `nhl F/identity-crosswalk` cannot be brought to prod parity by
  running these scripts. They need `espn_id` on the spine, which only
  `roster_sync.py` produces, and against a copy of prod it fills zero: it is
  fail-closed on ambiguous names and prod has 420 ambiguous normalized names.
  Deduping removes most, but the survivors are genuinely different people who
  share a name.

## v0.7.1 — 2026-08-03

### A league can now be offered while its season is still being played

- **`in_progress` is a fourth coverage status** (`1973ed5`), and MLB 2026 is the
  first row to carry it: 1,682 of 1,682 published games, checked through
  2026-08-02. The three-value vocabulary had no way to say "complete so far" —
  a season five months from its last game measured against the full-season
  total reads as `partial`, and `partial` is not offerable, so a league nobody
  had any doubt about disappeared from `/leagues` every morning until the next
  ingest ran. `in_progress` says what is actually true, and carries a
  `checked_through` date so the claim can be falsified.
- **The rule is league-agnostic** (`reconcile_totals.py:869`): a season whose
  published end date has not passed is `in_progress` rather than `complete`.
  Nothing in it names a league. NFL 2026 will land there the first time
  reconcile runs against it after kickoff.
- **`in_progress` pays for itself** (`8523557`). COV-honest went red the moment
  the status existed — the gate doing its job — and now holds it to both of
  `complete`'s assertions (no ingestion failures, expected == fetched) plus one
  of its own: a row claiming `in_progress` without a `checked_through` is
  rejected, because a claim with no horizon cannot be checked.

### Reconciling a live season stops costing an hour

- **776 per-event fetches became 0** (`88d1811`). Classification fetched one
  event document per differing event, and a season still being played differs
  by its entire remaining schedule. Two runs died proving it: the first into a
  403 of its own making, the second into a 54-minute timeout with nothing to
  show. The site API publishes the same three fields the classifier reads —
  date, status, competition type — for a whole month at once. Seven requests
  return all 2,458 published MLB 2026 events and reconcile exactly against the
  core API's own `count`, including the single All-Star game hiding inside
  season type 2. Over an hour became 13 seconds.
- Best-effort by contract: anything the index misses falls back to its own
  fetch, so it can change how long a run takes and never what it concludes. A
  test asserts exactly that — same publisher, both paths, identical `Gap`, zero
  per-event fetches on the indexed one.

### MLB had no game-type boundary at all

- **`ingest_mlb_logs.py` now stamps `game_type` at the ingest** (`604d39d`).
  MLB was the one league whose logs went in unphased: 45,551 prod rows NULL,
  and dev's PRE/REG typed in by a human — correct, and reproducible by nothing.
  `AND game_type='REG'` over NULL does not raise, it returns zero, which reads
  as "this player did not play."
- The phase was always one column away: statcast publishes `game_type` on every
  pitch. The letters are mapped from two **finished** seasons rather than
  guessed (`S`/`E` → PRE, `R` → REG, `F`/`D`/`L`/`W` → POST, `A` → ALLSTAR), an
  unmeasured letter raises instead of defaulting to REG, and the cross-check is
  that this publisher's 2026 `R` count is 2,458 — the same number ESPN publishes
  for its own season type 2. Two independent publishers, one number.
- `backfill_mlb_game_types.py` re-derives the stamp for rows already written and
  is idempotent; `promote_mlb_to_prod.py` copies team results additively and
  refuses to copy a coverage verdict, which has to be earned by a reconcile run
  against the target.

### Fixed

- **The oracle stopped 403ing** (`c6f3bbd`): the ESPN core API rejects a
  default urllib user-agent from this host, and an unreachable oracle is a FAIL,
  not a skip — so every check went red for the wrong reason.
- `/api/coverage` stopped leaking `run_id` and any future column into the API;
  the explicit column list is back.

## v0.7.0 — 2026-08-03

### The mock-draft pool leads with the two numbers a drafter acts on

- **`Exp PPR/G` is back, immediately right of `Proj`.** `6ee27fc` replaced
  opportunity with outcome; the pool now ships both — `# · PLAYER · PROJ ·
  EXP PPR/G · BYE · ADP · AVAILABLE` — because a back who scored 21.8 on 19.3
  of opportunity beat his usage, and one column alone cannot tell you that.
- **Player names and subtitles never wrap**, and the subtitle stops repeating
  itself: `BUF · RB · RB1` is now `BUF · RB1`, matching the overlay's
  long-standing rule. The shared cell was lifted into `columns.tsx` so two
  private copies cannot disagree again.
- **REG-render is green for the first time since `6ee27fc`.** Three separate
  defects, all fixed: the missing column (above), `StatRankCard` claiming a
  heading level (`h2`) it does not own inside the overlay, and an xFP
  threshold (`>= 150`) that a virtualized pool table could never meet — now
  `rows >= 20` with a `populated/rows >= 0.6` ratio that catches the real
  regression (the boundary nulling the column) at any window size.

### The NFL data spine is complete and provenance is recorded

- **NFL 2025 is a full 285 games** — the postseason (13 games) was never
  ingested, and ESPN files the Pro Bowl inside postseason type 3 with no
  competition marker; its only tell is AFC/NFC competitors not in the 32-team
  list. New `backend/backfill_nfl_postseason.py` writes any past phase and
  refuses to duplicate a season.
- **Every row now says which publisher wrote it.** `team_game_results` gained
  `source` + `run_id`; `stamp_team_result_source.py` attributed 5,630
  historical rows from recorded evidence only, and the rows with no evidence
  (MLB 16, NFL 2024 + 2026) stay NULL on purpose — `COV-source` is red
  honestly until those are re-ingested under a recorded run.
- **NBA 2026 and NHL 2026 are `complete`.** Both backfills closed their gaps
  (NBA's was 216 games, not 121, plus a postponed game written as played);
  `game_type` is stamped at the boundary from the publisher's own phase
  fields, and `COV-gametype` gates it. A postponed game is no longer a
  played game in any league.
- **MLB `team_game_results.season` is populated** — the season was never
  missing from the source; ESPN publishes it on every event and the ingest
  was dropping it. 3,364 rows / 1,682 games / 0 one-sided / 0 missing.

### The gates measure the real surface

- `verify-gates.sh` runs end to end again (24 verdicts, 17 pass / 7 fail,
  all accounted for): the defaults pointed at a deleted worktree and a named
  gate that emitted no verdict exited 0 — a dead backend could ship. Both
  fixed.
- `REG-pool`'s 4,507 check was unsatisfiable, not red (11,515 total vs six
  counts summing to 4,506); it now asserts `len == sum(counts)`.
- `B4` asked the right question of a file that stopped answering it; it now
  names all four surfaces that render a fraction.
- `OVL-width` is new: the player overlay is measured at the width a phone
  gives it. The game log fits exactly at both widths; the Overview SEASON
  STATS table (10 columns / 560px) is still red pending a product decision.

### Player surfaces

- **The NFL game log renders one narrow table per tab** (Wk|Opp|PPR anchor,
  ≤5 stat fields), and `max-w-[520px]` is restored — the sideways scroll was
  the width, not the column list. Rushing columns read YDS and TD like the
  receiving tab.
- **The rankings card says the season once, in title case** — `2025 Regular
  Season` — with the sample size (`n=16 games`) on the hover instead of
  shouting beside the ranks.
- **The research board stops printing the position twice** and names/subtitles
  never wrap, measured on the live board at 390px and 1280px.

### Data notes for the prod promotion

- The projection snapshot is per database: publish the pinned
  `espn_2026_snapshot_page1.json` into the target DB before calling the 2026
  projections live.
- NFL 2024's `team_game_results` rows carry no `run_id` to attribute them
  from; they need a re-ingest under a recorded run (or a vocabulary
  migration), deferred past this release. `COV-source` stays red honestly.

## v0.6.14 — 2026-08-01

### Draft boards show the 2026 decisions

- **Published ESPN PPR rank and the 2026 LP PPR projection are first-class
  columns.** The pre-draft pool, in-draft Players tab, and NFL Player Rankings
  now share `RK | PLAYER | BYE | ADP | PROJ 2026 PPR | AVAILABLE`, with rank as
  the default order and projection as an explicit sort.
- **Projection nulls remain honest.** The API and UI preserve a missing ESPN
  source projection as `—`; they never turn missing data into a `0.0` season.
- **The full ESPN player universe is virtualized without widening the fantasy
  product.** The API can retain the source population while user-facing pools
  stay restricted to QB, RB, WR, TE, K, and D/ST, with no TQB or IDP leakage.
- **Prior-season PPR and xFP remain research evidence, not headline draft
  columns.** They remain available as secondary sorts and in player detail.

### Player context is available at the decision point

- **Injury status is visible wherever a player is evaluated.** Compact Q, D,
  O, and IR tags appear in pools and rankings without converting status into a
  score or hiding availability history.
- **Fantasy news is separated from general NFL news.** The player overlay has a
  dedicated RotoWire-backed News tab; fantasy blurbs no longer leak into the
  general-news surface, and external article links are not presented when the
  licensed payload does not publish one.
- **The overlay keeps research in Overview.** League Rankings sits inside the
  Overview tab, while Game log and News remain focused on their own evidence.
  Missed weeks render a centered, single-line `did not play` state.

### Projection and Team Stats publication stay guarded

- **The ESPN projection publisher is pinned, checksum-backed, identity-safe,
  and atomic.** It validates the complete snapshot and all 32 D/ST before one
  transaction, with position-aware PPR scoring and explicit null rows.
- **Existing databases have a scoped Team Stats migration path.** Approved
  NBA, NFL, and NHL windows are copied fail-closed without treating a proof DB
  or a code tag as evidence that a live database was migrated.

### Deployment note

- **The projection snapshot is per database.** This code release does not by
  itself populate another environment's `nfl_player_projections` table; publish
  and verify the pinned snapshot against that database before calling its 2026
  projections live.

## v0.6.13 — 2026-07-29

### The draft room reads like a draft

- **Players, Queue, Board, and Rosters are distinct tabs.** The room keeps one
  dense player table for decisions, a teams-by-rounds board for draft flow, and
  roster views that show every manager without making the pool carry three jobs.
- **Rows have one action.** On the clock they say Draft; off the clock they say
  Queue. The player card retains both actions because it is the only place a
  manager can deliberately pre-rank while the synchronous bot engine is between
  turns.
- **The clock survives tab changes and still autopicks.** Switching away from
  Players no longer remounts or deadlocks the countdown.
- **Draft labels use football vocabulary at the UI boundary.** Kicker renders
  as `K`, defense renders as `D/ST`, and both draft surfaces share one position
  ordering and label map while the database retains `PK` and `DEF`.

### The draft data path is promotion-safe

- **Published artifacts own published measurements.** Weekly box scores, team
  defense, snaps, expected points, depth charts, receiving metrics, schedule,
  and ESPN ADP each keep separate source contracts instead of being reconstructed
  from whichever table happens to contain a nearby field.
- **NFL refreshes fail closed and commit atomically.** Complete source data is
  materialized and validated before a short write transaction; partial D/ST,
  roster, ADP, snap, depth-chart, or transaction refreshes leave the prior data
  intact.
- **SQLite schema changes are explicit and versioned.** Release migrations are
  checksummed, backed up, transactional, independently checkable, and separate
  from the guarded NFL-only data copy.
- **Production prop data is protected during NFL promotion.** The migration
  names copied columns, preserves existing enrichment, and verifies count plus
  content hashes for `props`, `prop_results`, and `prop_games`.

### Known gap

- **Rashid Shaheed can render `18/17` availability.** His 2025 NO-to-SEA trade
  crosses two different bye weeks, while the denominator follows only his
  current roster. The data is real; the denominator must eventually follow the
  player across teams.

## v0.6.12 — 2026-07-28

### Defenses are draftable, at the ADP someone else published

- **All 32 D/ST are in the pool**, with a starting roster slot. The mock draft shipped
  without them, which meant it could not complete a real lineup.
- **Their draft position is ESPN's published ADP, not our arithmetic** — DEN 90.0, HOU 91.8,
  LAR 98.2, SEA 106.5. An earlier build ranked defenses by a `dst_rank` we derived ourselves
  and interleaved into the board; that is deleted, not corrected. Where a definition is
  published, we read it.
- **A defense with no published ADP shows `—`, not a number.** The pool used to map missing
  ADP to `999`, and because that same array feeds the draft board, all 32 defenses rendered
  a literal `999.0` as their draft position. A fabricated sentinel that reaches a user is a
  false measurement, not a default.
- **The ingest fails closed.** It resolves all 32 defenses through ESPN's published
  `proTeams` map or it writes nothing, because a missing row does not raise — it silently
  goes missing.

### The draft room is a draft room

Everything v0.6.11 listed as missing:

- **Position, team and bye-week filters** on the pool.
- **A queue** — pre-rank players, reorder them, and draft off the list when you are on
  the clock.
- **A board grid** showing teams × rounds, so you can read the picks that have already gone.
- **A 30-second clock** with tabular figures that bolds under ten seconds and never turns
  red, plus **autopick when it expires** so a draft cannot deadlock waiting on you.
- **A next-pick counter** in the status bar.
- **A Draft button on each row**, replacing a whole-row click target.
- **A player detail overlay** — click any row, from the pool or the rankings, for the full
  card.

### Player Rankings shows the stats the position actually has

- **Columns and sorts are position-aware.** A kicker and a wide receiver no longer share a
  column set, so the table stops printing blanks where a stat was never going to exist.
- **Kickers have scoring.** v0.6.11 shipped with one game-log row across 42 kickers, because
  `player_game_logs` is built from passing, rushing and receiving. Kicking lines are now read
  from the published weekly box score, and points-per-game is computed from the scoring
  buckets rather than left empty.
- **Team QBs rank by games played**, so a team's card shows the quarterback who actually
  played rather than a third-stringer.

### Both surfaces now agree about who played

- **`/mock-draft` and Player Rankings gave different answers about the same player** — Josh
  Allen 16 games on one and 17 on the other, CeeDee Lamb 13 against 14, and every D/ST 0
  against 17. 49 of 237 shared players disagreed on at least one availability figure.
- **The cause was reading the wrong table.** `player_game_logs` records touches, not presence:
  a player who dressed but recorded no pass, rush or reception has no row. The rankings board
  had always merged `nfl_snap_counts` and took team weeks from the published schedule; a
  hand-resolved merge silently reverted the pool to game logs alone.
- **Both surfaces now share one availability function**, rather than two implementations that
  agreed until they didn't. Measured after the change: 0 disagreements of 298.
- **Games-missed denominators come from the published schedule**, not a hardcoded 17. The
  constant was live in three files and rendered to the user in two of them; it was correct
  only because every team happened to play 17 games this season.

### Known gaps in this release

- **The mock draft has no completion state.** No route completes a draft, `status` is written
  as `active` at insert and never updated, and the backend's `status != 'active'` guard
  therefore cannot fire — while the results screen tells you "Draft complete" off a
  client-only flag.
- **The em-dash path for an unpublished ADP is currently unexercised.** All 32 defenses carry
  ESPN's published figure today, so the `—` fallback is correct but untested by real data.
- **The share URL still does not restore a draft.** Unchanged from v0.6.11: the picks are
  saved and the API returns them, but the page renders a fresh pool.
- **Kicking and weekly stats are a per-database ingest.** The data lives in the published
  nflverse weekly box score and has been loaded into dev; any other database needs the same
  ingest run against it, and needs the `game_type` column present before it will.

## v0.6.11 — 2026-07-27

### Mock draft: draft a roster off the availability board

- **A 12-team, 15-round PPR snake draft against ADP bots**, at `/mock-draft`. QB/RB/WR/TE/K
  plus FLEX and a bench, solo — no lobby to fill, no waiting on anyone.
- **You draft from the availability board, not from a name list.** Every player in the pool
  carries the same amber strip the board uses, so while you are on the clock you can see
  that the guy you are about to take played 8 of 17 last season. That is the whole reason
  to draft here rather than somewhere else.
- **The results screen states history, not a forecast** — "your picks missed N of a possible
  M games last season", with the same figure for the 12-team field so the number has
  something to sit against. Players with no NFL sample are excluded from the denominator and
  the count of exclusions is printed rather than hidden.
- **Best and worst value are shown as the two numbers** — picked at 81, ADP 92.1 — not as a
  computed score that hides its arithmetic.
- **Every draft is persisted server-side** and has its own URL.
- **The mock draft is reachable from the NFL hub.** It shipped as a route that nothing linked
  to; there is now a card above Recent Trades on `/leagues/nfl`.

### Draft notes tell you when a save fails

- **A failed save used to revert your input silently.** Ranking a player wrote to the server,
  and when that write failed the rank rolled back with nothing on screen to say so. The
  board now says so, in one quiet line under the sort controls.

### Known gaps in this release

- **Kickers have no game data.** `player_game_logs` holds one row across all 42 active
  kickers. Kickers therefore read "Kicker games not tracked" — except Brandon Aubrey, who
  reads "1/17, missed 16" because a fake-field-goal carry put a single row in a table built
  from passing, rushing and receiving stats. That figure is wrong and the fix is to ingest
  kicking data, not to relabel him.
- **The draft room has no position filter, no queue, no board grid and no clock.** The pool
  is a single scrolling list.
- **The share URL does not restore a draft yet.** The picks are saved and the API returns
  them, but the page discards them and renders a fresh pool, so `?id=` currently leads
  nowhere. The results screen offers the link regardless.

## v0.6.10 — 2026-07-27

### You can look up a player instead of paging to him

- **Search the draft board by name.** The board shipped with a position filter, a sort and
  prev/next across 522 players at 50 a page — but draft research is name-driven. You arrive
  wanting to know about one guy. Now you type him.
- **Every token has to appear in the name, in any order**, because people type fragments in
  whatever order they remember them: `ja gibbs` finds Jahmyr Gibbs, `rice` finds Rashee Rice.
- **Narrowing happens in SQL, not in the browser.** Searching for one player costs one
  player, not 522 rows filtered client-side. The input waits 250ms before asking, so typing
  a name is one request rather than one per keystroke.
- **A search that finds nothing says which search found nothing** — "No player named
  "…" on the board" — instead of rendering an empty table and leaving you to guess whether
  it broke.
- Typed `%` and `_` match themselves. LIKE wildcards are escaped, so a stray `%` finds
  nothing rather than returning the entire board.

## v0.6.9 — 2026-07-27

### The draft board is about availability now, not about who scored well when healthy

- **The board ranked on an average conditioned on the thing you were trying to predict.**
  `fantasy_ppr_g` is points per game *played* — it only counts the days a player was
  healthy enough to appear, which makes injury-prone players look safer than they are.
  Every fantasy site shows that column. Joe Burrow's 2025 reads **16.8 per game played and
  7.9 per team game** off the same season; Tyreek Hill's reads 13.4 and 3.2. Both numbers
  now ship together, always, because the gap between them *is* the information.
- **Availability is the headline: games played out of the team's 17.** A missed game has no
  row in `player_game_logs`, so absence is invisible unless you deliberately go get it. The
  denominator is a constant, verified as 32 teams × exactly 17 games in both 2024 and 2025
  — which sidesteps the `team_game_results` key-scheme problems entirely. Deriving it from
  that table is what made Joe Flacco read **13/34**; he now correctly reads 13/17.
- **Postseason weeks are excluded.** Weeks 19–22 are playoffs; counting them let a deep run
  report 21/17 and inflated both averages.
- **Expected fantasy points (xFP), from ffverse/ffopportunity.** A per-game average over a
  short sample is mostly touchdown variance; xFP prices the opportunity a player was given.
  Measured 2024 → 2025 on our own data, xFP/g predicts next season's actual PPR/g better
  than actual PPR/g does, and the margin is widest where the sample is thinnest — r=0.424
  vs 0.374 at ≤4 games, against r=0.778 vs 0.775 at 10+. Stated honestly: that makes a
  three-game sample *less misleading*, not reliable, so sample size stays on the surface.
- **Target share and the 2026 depth chart join snap share**, so a healthy player in a
  timeshare reads differently from an injured starter. Both are published values copied in,
  not derived here — nflverse already publishes `target_share` at 100% coverage.
- **Rookies read "No NFL sample" and never a zero.** A zero is a claim about the player;
  absence is a claim about us, and only the second one is true. They stay on the board on
  ADP and depth-chart rank. Jeremiyah Love — going 17th overall, 98% owned, Arizona's RB1 —
  was invisible under the old `games > 0` filter, along with 147 other ADP-ranked players.
- **ESPN's undrafted sentinel is no longer treated as a ranking.** 1,392 of 2,511 ADP rows
  sit at exactly 170.0; only 248 players carry a real ADP.
- **The accent colour marks absence, not achievement.** Every game played renders quiet;
  the one saturated colour on a row is the games missed. The availability strip shows one
  cell per game the team actually played — 17, not 18, because a bye is not an absence.
- **Nothing is labelled a projection any more**, because nothing on the board is one.
  `season_proj_pts` and its "games assumed" caption are gone.
- Three draft-board tests had been red long enough that nobody read them; they were a
  missing `nfl_adp` fixture. The suite goes from 249 passed / 4 failed to 256 passed / 1.

### Known

- `players.nfl_gsis_id` mixes two id schemes: 651 active players carry an ESPN-style
  synthetic key (`LOV121782`) in a column named for gsis, and all 651 have zero game logs.
  The depth-chart ingest works around it via `espn_id`; the spine itself is unrepaired.
  Recorded as ROADMAP B7 with the measured fix.

## v0.6.8 — 2026-07-27

### NFL: the numbers now come from the published source, and the calendar exists

- **Per-game NFL stats are copied from nflverse's maintained weekly box score instead of
  re-derived from play-by-play.** `ingest_nfl_pbp_logs.py` aggregated a 372-column
  play-by-play feed into per-player-game lines, justified by a docstring claiming the
  weekly summary "404s for 2025". It does not — the release was renamed `player_stats` →
  `stats_player`, returns 200 for both 2024 and 2025, and carries 145 columns including
  `passing_epa` and `passing_cpoe`. Every defect fixed in the previous release was a bug in
  a reimplementation of arithmetic nflverse already does correctly. Verification against a
  copied source is tautological; against a derivation it is a permanent project.
- **The 2025 postseason exists for the first time — 258 player-games.** Weeks 19–22 had
  zero rows. The play-by-play path had never produced playoff data at all, so no amount of
  fixing it would have surfaced Stafford's wk19–21 run or Rodgers' wk19.
- **Fantasy points are correct.** The hand-rolled scorer omitted fumbles lost (184 rows),
  two-point conversions (83) and special-teams touchdowns (15). All 5,635 stored rows now
  reconcile against the published artifact with zero mismatches.
- **The 2026 schedule is ingested** — 272 regular-season games from nflverse's `games.csv`,
  opener 2026-09-09, into a new `nfl_schedule` table plus reciprocal `team_game_results`
  rows at `status='scheduled'`. Nothing in the database previously held an NFL schedule:
  the only writer accepted games whose ESPN status was already `post`, so by construction
  it could never record a fixture that had not been played. With the season 44 days out,
  "who does this player face in week 1" was unanswerable.
- Schedule rows carry kickoff time, rest days, roof and surface, spread and total lines,
  coaches and starting-QB ids — the inputs a draft or sit/start board needs.
- **Play retention is unaffected.** `nfl_pbp` keeps its 46,452 plays; only the rollup half
  of that ingest was retired. Raw plays are additive, the derived summary was not.
- Guards on the schedule ingest, both mutation-tested: empty source cells read as NULL
  rather than 0, so an unplayed fixture is never stored as a completed 0–0 tie; and scores
  upsert through `COALESCE`, so re-running a season in progress cannot blank a result.
  No `team_stats_coverage` manifest is written for 2026 — the NFL aggregate is bounded by
  the newest manifest, and one would have pulled 272 unplayed games into season totals.
- Ingests print their artifact's sha256 on every run. nflverse rewrites files in place, so
  the digest is the only thing that makes a run reproducible.
- **+23 tests**, each assertion checked against a deliberately broken implementation rather
  than only a passing one.

### UFC: the fight-stats ingest can no longer lose data

- **Rebuilt as a planned, additive write.** The whole plan is fetched and validated before a
  writable connection is opened, then applied in one short transaction, with typed plan
  structures so what will be written is inspectable first.
- The only log write is `INSERT OR IGNORE`. There is no `DELETE`, no `DROP` and no
  `INSERT OR REPLACE` in the module, so a re-run cannot erase another ingest's enrichment —
  the failure mode that cost the NFL 2024 season its snap and Next Gen keys twice over.
- `--dry-run` and `--apply` are mutually exclusive with no default write, and `--apply`
  requires an integrity-checked pre-write backup path. Identity and game-link updates only
  fill blanks and raise rather than overwrite an existing link.
- A distinct `SourceUnavailable` error keeps an upstream failure from being recorded as
  "this fighter had no stats."

### World Cup

- **Clipped-nickname player names resolve.** Feeds can combine a nickname with a shortened
  surname while ESPN uses the formal first name ("Alex Grimald" vs "Alejandro Grimaldo").
  The new last-resort match requires same team, matching first initial and a five-character
  surname prefix identifying exactly one player, and declines rather than guessing.

> Data-layer release. The corrected numbers, the postseason and the 2026 schedule reach
> users on the next production deploy; prod continues to serve the previous data until then.

## v0.6.7 — 2026-07-26

### NFL player page: usage is now its own tab

- **Player page restructured into Overview │ Usage │ Game Log.** The usage card is role-driven —
  it reads the player's position first and picks columns off that, because the underlying feeds
  do not cover every position equally.
- **Four positional tile sets.** QB Snap%/Att-g/CPOE/EPA-per-dropback · RB Snap%/Car%/Tgt%/PPR
  (Rushing sorts before Receiving) · WR/TE Snap%/Tgt%/WOPR/Separation, plus the full Next Gen
  band. Share columns carry a magnitude bar.
- **Seven ingested-but-unrendered keys exposed** on `/api/nfl/usage`, plus a derived
  `epa_per_db` — `pass_epa` is stored as a game total, so a 40-attempt game and a 20-attempt
  game were not otherwise comparable.
- **Rushing usage added** (carries / carry share). Without it an RB's usage table was almost
  entirely dashes.
- **Two sparkline bugs fixed:** shares were forced onto a 0–100% axis, so a 21%→37% climb
  rendered as eight identical stubs; and a negative CPOE drew a short bar growing *upward*.
  Diverging metrics now hang below a zero line.
- **Season Stats zero wall removed.** Stat blocks are selected by position before values are
  pruned. Rendered zero/None tiles across all 1,217 NFL rows: **7,255 → 408**, with no player
  losing a section.
- **Performance:** the usage endpoint's team-wide target/carry sums had no covering index and
  scanned every NFL row twice per request. Two indexes on `player_game_logs`
  (`league,game_id,team` and `league,season,game_no,team` — the 2024 rows carry no `game_id`).
  Team-sum query 70–100ms → 0.5ms; full request **~180ms → ~13ms**. A response cache was
  considered and rejected: it would have hidden the scan rather than removed it.
- **`usage_trend_viewed`** (defined but unwired in v0.6.5) now fires on entry into the Usage tab.
- Verified at 1280px and 390px; the week column is pinned so a scrolled 14-column table keeps
  row identity.
- **+16 tests**, each assertion checked against a mutated implementation rather than only a
  passing one.
- **Test isolation fix:** `LP_DB_PATH` leaked between suites, so three real-DB tests failed in a
  whole-suite run but passed file-by-file. The full suite is usable as a gate again.
- New reference docs: `docs/NFL-DATA-INVENTORY.md`, `docs/NFL-CHART-CONTENT-RESEARCH.md`.

## v0.6.6 — 2026-07-26

### Esports: broadcast source reliability

- **Official simulcast siblings.** When a real per-match source attests a known official Twitch
  broadcaster whose organizer also simulcasts on YouTube, the backend adds that organizer's
  official YouTube channel as a candidate. The mapping is broadcaster-level and case-insensitive
  (VCT EMEA and BLAST Premier today), so it covers every event from that broadcaster rather than
  a single match or league label. Rule-only Twitch guesses cannot trigger it.
- The resolver checks YouTube's `/streams` page first at zero Data API quota; the budget-capped
  Data API search is only a fallback, and ambiguity still fails closed to Twitch/Kick.
- **Viewer counts persist between matches** instead of blanking during the gap.
- **Missing Kick viewer counts are retried** rather than left empty for the rest of the session.
- `docs/ESPORTS-EXPECTED-BEHAVIOR.md` updated in step, per the rule at the top of that file.

## v0.6.5 — 2026-07-26

### Analytics: GA4 instrumentation

- **The app had no analytics of any kind** — no dependency, no calls, no tags. The NFL season is
  the only large traffic event on the calendar, so arriving uninstrumented would have spent the
  one annual spike and learned nothing from it.
- **GA4 wired for the pages router**: `send_page_view` is off and `page_view` fires explicitly on
  `routeChangeComplete`. LP's nav is client-side, so `config` alone would only count hard loads.
  GA4 Enhanced measurement can pick up history events, but it double-counts against a manual
  handler — the "Page changes based on browser history events" toggle is turned off on the
  property to match.
- **Five custom events**, each fired on a confirmed action rather than on render or click:
  `pick_made` (both flows — esports pick'em and UFC — only after the POST succeeds),
  `player_viewed` (resolved profile only, so 404s aren't views), `prop_chart_opened` (keyed on
  series identity, since callers swap the chart's data without remounting), `stream_watched` (the
  deliberate open, not iframe render). `usage_trend_viewed` is defined but not yet wired.
- `NEXT_PUBLIC_GA_TRACKING_ID` threaded through the Dockerfile and compose build args.
  `NEXT_PUBLIC_*` is inlined at build time, so a runtime-only variable would have produced a
  build that looked instrumented but recorded nothing.
- Verified against a production build in a throwaway worktree: the id is inlined into the `_app`
  chunk, the loader requests it, and a client-side nav produces exactly one additional
  `page_view` with no duplicate.

### Housekeeping

- **Version reconciliation.** v0.6.1 through v0.6.4 were written to this changelog and to
  `package.json` but never tagged or released — the last real tag was `v0.6.0`, so four version
  numbers were burned without a release. `package.json` and the tag are now aligned at `0.6.5`.
  The 0.6.1–0.6.4 entries are left in place as the record of what shipped; they are deliberately
  not tagged retroactively, since choosing commits for them after the fact would invent a history
  that did not happen.

## v0.6.4 — 2026-07-24

### UFC: fight_time prop chart

- **New chartable market**: `fight_time` (Underdog's Over/Under total-fight-duration prop,
  lines in minutes e.g. 2.5/7.5/12.5/14.99) now has a real per-fighter history chart. The
  underlying data — round the fight ended in, and elapsed clock within that round — was already
  being fetched from ESPN's per-fight `/status` endpoint for the result/method fields, just never
  read. Total fight time = `(round-1)*300 + clock_seconds` (UFC rounds are a fixed 5 minutes).
- Backfilled all 49 tracked UFC fighters (77/78 fight rows now carry `fight_time`; the one gap is
  a pre-existing ESPN data hole, same class as fights that were already skipped for missing stats).
- Verified against the real `/api/props/history` endpoint with an actual Underdog prop line, not
  just a database read — correct hit/miss against the line.

## v0.6.3 — 2026-07-24

### MLB: hits_runs_rbis compound prop chart, full season

- **New compound chart** (`total_hits,_runs_and_rbis`, MLB's H+R+RBI prop): `_MARKET_STAT_KEY`
  now supports list-valued stat keys that sum across multiple `player_game_logs` fields, not just
  a single stat. R and RBI aren't derivable from Statcast's pitch-level event stream (they need
  whole-game baserunner tracking), so they're pulled separately from the MLB Stats API boxscore
  (same source `settlement.py` already uses) and merged onto the existing per-game rows.
- **R/RBI backfilled across the full 2026 season** (2026-03-15 → 07-23, ~44k game-logs) — verified
  day-by-day with zero real gaps (the only 3 empty days are the actual All-Star break).
- **Real fix**: the compound chart was wired under a clean `hits_runs_rbis` key, but the real
  Bovada market string normalizes to `total_hits,_runs_and_rbis` (comma + `total_` prefix) — so it
  never actually fired from the real UI despite testing clean via a hand-typed API param. Fixed by
  mapping the real market string too, verified against a live prop row through the actual
  `/api/props/history` endpoint the frontend calls.
- **Backfill script hardened**: `ingest_mlb_logs.py` now pulls one day at a time
  (`pybaseball.statcast(day, day, parallel=False)`) instead of a whole date range in one call —
  the library's default threaded parallelism across days in a range was blowing memory/load on
  this box regardless of how the caller chunked `--start`/`--end`.

## v0.6.2 — 2026-07-23

### EV/CLV: extended to NBA + NHL

Same generalization as NFL in v0.6.1, extended to the two other leagues with real per-game data
already sitting in `player_game_logs`: NBA (points, rebounds, assists, threes, blocks, steals,
turnovers) and NHL (goals, shots, assists — goalie stats like saves aren't ingested at all yet, so
left unmapped rather than guessed). Both leagues are off-season right now with zero live props, so
same caveat as NFL: verified against real historical game logs (LeBron James, Nikola Jokic,
Connor McDavid, Nathan MacKinnon), not provable end-to-end until their seasons resume.

### UFC: fighter detail + per-fight stats

- **Per-fight stats backfill** (`backend/ingest_ufc_fight_stats.py`): pulls ESPN's per-competitor
  statistics (sig strikes by target/position, takedowns, knockdowns, submissions, control time —
  43 fields) into `player_game_logs` for every UFC fighter we track. Fixes a real search bug as a
  side effect: UFC fighters only showed up in player search when they had a currently-live prop
  (search requires game_logs/props/stats, and UFC had zero game_logs rows ever); now permanent.
- **Fighter detail page**: UFC-specific Recent Fights table (opponent, date, W/L, sig strikes,
  takedowns) on the player detail page, replacing the generic per-league stats sections that don't
  apply to MMA.
- Curated the UFC stat list in the Props page's Model and Matchups tabs — those tabs generically
  iterate every stat key present, which for other leagues is a small curated set but for UFC is
  ESPN's full 43-field raw blob; restricted to the handful of headline stats (sig strikes,
  takedowns, knockdowns, submissions) instead of dumping everything.

### Props page

- Performance/Matchups/Model tabs now share one search — picking a player on one tab keeps it
  selected when you switch to another, instead of resetting the search box each time.

### Fixes

- Kick.com viewer counts were missing from the esports board on both dev and prod —
  `KICK_CLIENT_ID`/`KICK_CLIENT_SECRET` existed but were never forwarded through
  `docker-compose.yml`'s environment block (same class of gap as the PANDASCORE/GRID/YOUTUBE keys
  before it).
- `scripts/hermes-worktree.sh down` killed processes by hardcoded port instead of verifying they
  actually belonged to that task's worktree — took down the live dev tunnel's backend/frontend
  twice in one session as collateral damage. Now checks each candidate process's actual working
  directory first.

### Docs

- `docs/UNDERDOG-API-RECON-2026-07-23.md` / `docs/UNDERDOG-PROPS-BOARD-AND-SETTLEMENT-2026-07-23.md`:
  Underdog Fantasy's `over_under_lines` API is real and unauthenticated (PrizePicks' equivalent
  403'd). Confirms live UFC/MLB/tennis/esports markets and a new MLB 1st-inning market category we
  don't ingest today; what settlement would take per sport (MLB/NBA/NHL/UFC already have durable
  actuals, esports has live-only data with nothing persisted, tennis has no actuals pipeline at
  all yet).

## v0.6.1 — 2026-07-23

### EV/CLV: extended from MLB to NFL

The MLB EV/CLV fix (real per-game stats as an independent fair-probability source, landed
2026-07-22) only covered MLB — the market→stat mapping and game-log query were hardcoded to it.
Generalized to a per-league lookup and added the NFL mapping (passing/rushing/receiving
yards+TDs, receptions — matched exactly against `bovada_scraper.py`'s own market names and real
`nflverse` per-game data, not guessed). NFL has zero live props right now (off-season, Bovada
hasn't posted any) so this is verified against real historical game logs, not provable end-to-end
until props exist again in August.

### NFL: ADP ingest + data-freshness

- Fixed a real infinite-loop bug in `ingest_nfl_adp.py`: ESPN's fantasy-players endpoint ignores
  `limit`/`offset` and returns the full player pool on every call, so the old pagination
  termination check never tripped.
- `docs/DATA-FRESHNESS-SPLIT-2026-07-23.md`: catalogued the three data-freshness strategies
  already in the codebase (systemd timer, in-process lazy warmer, manual one-off script) and put
  NFL ADP + transactions on new daily timers as a result — closing the same class of gap that let
  Recent Trades ship empty to prod.
- Cached the Recent Trades significance lookup (was rebuilding ~9.6k players + ~2.5k ADP rows into
  fresh dicts on every request; that data now only changes once a day).

## v0.6.0 — 2026-07-23

### NFL: Draft Room → Player Rankings

- **Real ADP** (`backend/ingest_nfl_adp.py`): ingests ESPN's own fantasy API (free, unauthenticated) for real 2026 average-draft-position data, joined on the existing `players.espn_id` spine. Always-visible column next to whatever stat you're sorted by, with owned% as a sanity check.
- **Season-projected fantasy points**: recency-weighted per-game projection (`analytics/projections.py`) × games assumed (capped at 17), surfaced as its own always-visible column. Fixed a bug where it was silently built from stale 2024 data only (2024/2025 ingests use different stat key names for the same stat).
- Sort row now leads with ADP + Season Proj (ADP is the default sort), instead of trailing after last-season per-game stats.
- Renamed "Draft Room" → "Player Rankings" and dropped the card wrapper — it's a ranked cheat-sheet, not an interactive draft experience.
- Training Camp countdown card reworked into a scoreboard-style readout (milestone name, countdown, and a month/day date tile) instead of a generic status-pill widget.
- **Recent Trades** (`components/Leagues/NflOffseasonMovers.tsx`, replacing the old unfiltered "Offseason Movers" feed): shows trades only instead of every roster move (signings/waives/IR noise). Bundled multi-sentence transactions are split so each trade gets its own line; mirrored entries (ESPN logs one row per team in a deal) are deduped by player names, keeping whichever side gave up the more significant player (real ADP as the significance signal). Player names bolded.
- NFL sub-tabs: renamed the camp tab to "Home," dropped hardcoded years from tab labels, added a season toggle to the Stats tab (generic across all leagues, not NFL-only).

### MLB props: EV/CLV fix landed and verified

- `analytics/projections.py`'s `prob_over()` wired in as an independent fair-probability source for EV (previously fell back to a tautological single-side implied-vs-own-odds comparison that was always zero). CLV now derives "close" from real captured-odds timestamps instead of a never-set flag. Verified against real data: 72 props flipped from zero EV to positive, projection-backed.

### Esports

- Hid the esports card on the Leagues page — it linked straight into a sub-tab (Call of Duty) that can be empty, and there's no content-aware default yet.
- Added a "Make Picks" button on the esports page, linking directly to the pick desk (`/predict`).

### Fixes

- **Live Discounts widget**: stopped matching a live game's Kalshi price to a settled/finalized market from an earlier game the same day (doubleheader mismatch) — was showing a dead 1¢ "live" price on an actual 60¢+ market.
- Schedule nav: dropped a redundant loading spinner in favor of the existing skeleton state (two competing loading indicators doing the same job).
- Copy cleanup: removed em dashes from the Leagues page card descriptions.

### Docs / infra

- NFL product-direction spec (moat-adjacency framework: sit-start/waiver as props-as-fantasy, ranked feature priority) + the technical build-sequence spec, plus specs for a possible NFL mock draft simulator and a UFC lineup generator.
- `docs/RUNBOOK-parallel-dev-servers-and-hmr.md`: resource limits and gotchas running multiple delegated-task dev-server stacks on this box (port collisions, inotify exhaustion, live-editing under a running server).
- `hermes-worktree.sh`: documented that worktree isolation doesn't cover host-level config (`/etc`, systemd, cron).

## v0.5.10 — 2026-07-22

- **LiveNow** (`pages/scores.tsx`): Reverted featured game to horizontal two-row layout (team name + score per row) — cleaner, closer to original.

## v0.5.9 — 2026-07-22

### Design — Broadcast Rail live cards

- **LiveNow** (`pages/scores.tsx`): Replaced red-bordered opacity-hack card with solid zinc-900 surface + emerald left edge. All live games shown as compact inline chips — no toggle. Esports link demoted to quiet right-aligned text.
- **LiveDiscounts** (`components/LiveDiscounts.tsx`): Replaced amber-bordered opacity-hack wrapper with solid zinc-900 + amber static left edge. DiscountCards use subtle `border-zinc-800/40` instead of heavy card frames.
- **CSS** (`styles/globals.css`): Added `.live-edge` (emerald) and `.amber-edge` (amber) utility classes for the edge-bar design vocabulary.
- **Docs** (`docs/DESIGN-live-card-rail.md`): Design rationale and before/after.

## v0.5.8
