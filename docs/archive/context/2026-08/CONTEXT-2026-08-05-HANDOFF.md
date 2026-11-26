# CONTEXT 2026-08-05 — the day the gates got built and then got audited

45 commits, tags **v0.7.7** and **v0.7.8** cut and pushed, **31 commits unpushed** at time of
writing. Prod backend rebuilt and deployed (291MB). All four leagues' audits are **0 FAIL on
prod**, 782 tests green, every leaders endpoint 200.

Read §1 and §7 first. §1 is what is true now; §7 is what is still open.

---

## 1. State of play

**Prod audit: green.** `audit_league_stats.py` reports 0 FAIL for mlb/nfl/nhl/nba against
`picks.db`. That is new today and it is load-bearing — `scripts/release.sh` now **blocks** a
release on any FAIL, so this is enforced rather than observed.

**Seven UNVERIFIED remain** and they are the whole of the outstanding gate work:

| gate | leagues | what it needs |
|---|---|---|
| `B/position-content` | mlb, nba, ufc, wc | a **decision**: what must a catcher's / guard's log record? NHL has one and it caught 78 goalies with zero saves |
| `G/published-identity` | ufc, wc | a **fetcher**: `fetch_identity_names.py` covers the big four only |
| `E/qualifier[season]` | nhl | a **re-ask**: see §7, this one is probably wrong |

**Prod data now holds** (all promoted today, all previously dev-only): NFL touchdown columns,
NBA 2025+2026 season stats, MLB counting stats (23 columns) and NHL goalie stats (11 columns),
NHL season keys migrated, NHL's 82 missing games, NHL boxscore enrichment, NFL 2026 schedule.

---

## 2. The defect class that ate the day

**Seven separate defects were correct in code and absent from production**, each found by
hand, one at a time. Both databases answered 200 throughout and the gates were green — against
dev. Written up as memory `feedback_dev_fix_prod_never_ran.md` and now structurally fixed
(§3).

The other recurring shape: **two writers, one column, no arbitration.** `players.position` was
written by three ingests in three vocabularies. That is what put ESPN's `SP`/`RP` on active MLB
rows and MLB's `P` on the rest, so neither query could return both.

**The five defect shapes are now a checklist** — `docs/DATA-COVERAGE-CONTRACT.md` **§7b**.
Every defect found across two days was an instance of one of five. Ordering matters: **shape 1
(an id names the wrong person) before shape 3 (two rows for one person)**, because a dedupe's
"a shared id is provably the same person" is false while identities are unverified.

---

## 3. What got built

* **`backend/diff_databases.py`** — prod vs dev on schema, seasons, row counts. SCHEMA and
  SEASONS **block** a release; VOLUME is advisory (live odds and dev-only mock drafts are
  legitimate drift, and failing on them trains people to skip the check).
* **Migration ledger** (`322b5e9`) — `schema_migrations` is load-bearing, **one invocation
  migrates both databases**, and the 20 legacy `migrate_*.py` scripts were adopted
  retroactively. The app now **refuses to serve an un-migrated database** (`758c82d`).
* **`backend/game_ids.py`** — the game-id vocabulary boundary, sibling of `season_keys.py` and
  `team_codes.py`. All three writers refuse to write into a season holding foreign-keyed rows.
* **`backend/data/name-aliases.json`** — the identity gate stays strict about *people* and
  learns accepted alternates (`Kenny`/`Kenneth Gainwell`) from a committed file. An id absent
  from the file has no alternates.
* **`backend/data/identity-consolidations.jsonl`** — append-only; every merge path logs what it
  consolidated. **A consolidation without a log line is a defect.**
* **`players.entity_type`** — 97 NFL rows are not people (32 D/ST, 32 TQB, 32 coaches, 1 `?`).
  ESPN signs their ids **negative**; we had stored that marker and ignored it for months.
* **Backup retention** (`b0bffae`) — `data/` had hit **15GB across 95 `.bak` files**.
  **`VACUUM INTO`, never `cp`**: a plain copy of a live database races writers and produces a
  torn snapshot (proved — the copy reported `malformed` while the source passed
  `integrity_check`). Every `.bak` taken by hand before that rule is untrustworthy.

---

## 4. Gates that were passing over broken data

Three checks were green on data that was wrong. All fixed today, and the pattern is the same
in each: **presence measured, coverage assumed.**

* **Check D** had no season predicate, so a log from three seasons ago counted as reachable.
  It read PASS twice while a season-scoped join returned **0** for NHL.
* **Check B** sampled 500 logs and passed if a key appeared **at all** — one row in 500. It
  read PASS at **30%** coverage.
* **Check A** failed only at exactly zero, so one populated row passed. It read PASS while
  **52% of MLB batting rows** had no counting stats.

**Check A's fix is worth reading before touching it.** Two floors were tried and both were
wrong: a flat 50% failed NHL `saves` (78/874) and NFL `pass_yds_g` (81/608), which are
**correct** — only goalies save, only quarterbacks throw. A 90% floor on MLB `pa` failed at
47%, also arguably correct. Coverage is now declared **per column** in the MANIFEST and
undeclared columns keep the non-zero test. **The lesson: a coverage floor asserts a
denominator, and asserting one you have not measured is the same error the gates exist to
catch.**

---

## 5. Root causes traced

* **223 MLB rows carried another player's `mlbam_id`.** Cause: Statcast's `player_name` is the
  **pitcher's** name on every pitch row, and the pre-`b03b9c9` batter fallback took it while
  `player_id` came correctly from `batter_id`. 201 of 203 wrong names are pitchers; 203 of 203
  true owners are position players. Repaired id-first.
* **The NFL draft board showed nobody as injured for ~18 hours.** `roster_sync` blanket-set
  `active=0` for the league; a D/ST is on no roster so all 32 stayed inactive;
  `ingest_nfl_adp.py` built its team map from `active=1`, got nothing, and its fail-closed
  preflight aborted **every run since** — stopping `injury_status` for all 6,486 NFL players.
  One flag on 32 non-human rows.
* **`OL -> G` in `team_codes.py` was a fabrication**, not a collapse. Every other alias maps a
  code to its own published parent; ESPN publishes `OL -> OFF` and gives `G` no parent. It
  asserted every unspecified lineman is a guard. **The test asserted the fabrication as the
  expectation**, which is why nothing caught it.

---

## 6. Working notes

* **Read the model off a tmux pane's STATUS LINE, never the pane name.** Both `reasonix` and
  `hermes` ran `deepseek-v4-flash` today; the name has been wrong before.
* **Hermes install was partially complete** — `agent-browser` had never installed because
  `npm install` hard-refuses on `node <22.22.0`. Fixed: node 22.19.0 → 22.22.0 via nvm.
  `HERMES_MAX_ITERATIONS` in `.env` **shadows `config.yaml`** — raising `max_turns` alone does
  nothing. Both now 150; `api_max_retries` 6.
* `browser-cdp` and `computer_use` stay unavailable **correctly** — the first gates itself off
  without an external Chrome CDP endpoint, the second needs a headed X11 session.
* Three Sonnet architecture audits were run and each found real defects, including two of my
  own wrong claims. Worth repeating; not worth repeating often — they are expensive.

---

## 7. Open, in priority order

1. **`E/qualifier[season]` for NHL reads "NONE PUBLISHED that this project could verify".**
   Re-ask it. Every previous instance of that phrasing in this repo was wrong — ERA, goalie
   saves, and MLB team/position were all "published nowhere" and all published. An independent
   audit flagged this same line.
2. **MLB Statcast, unexplained:** we hold 2026 batting rows for 767 players MLB's season
   endpoint does not publish a line for (it returns 689 hitters, `totalSplits: 689`, not
   truncated). Miles Mastrobuoni **is** published and our row still lacks PA — that is our join
   failing. Urshela and Bethancourt are not published at all, so **why do we have 2026 Statcast
   rows for them?** Statcast is MLB's own data. Third possible instance of that ingest
   misattributing.
3. **`PK` should render as `K`.** Storage is right (`PK` is ESPN's published code); the UI
   leaks it — `useNflDraftBoard.ts:10` puts `PK` in the filter chips, and `NflDraftRoom.tsx:93`,
   `PlayerDetailOverlay.tsx:78`, `MockDraft/columns.tsx:43` branch on the raw string. Display
   map at the UI boundary, not a data change.
4. **`B/position-content` for mlb/nba** — a decision about what a position's log must record.
5. **31 commits unpushed.** `TASK-P2-source-separation.md` is deferred to **November** on an
   auditor's recommendation: a half-migrated read surface during draft season would manufacture
   an eighth divergence. Do the `players_human` **view** first and measure whether the physical
   split is needed at all.

**The calendar is the constraint.** NFL drafts run the next 3–5 weeks and that is the one
validated use case. Everything in §7 above item 3 is data hygiene for leagues nobody asked for.
