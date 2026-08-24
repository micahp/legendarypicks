# CONTEXT 2026-08-14 — props lifecycle: link, settle, story

Session ran ~09:00–12:30. Two delegated agents (codex on settlement, hermes on stories),
review and integration by Claude. **28 commits on `dev`, nothing pushed, prod code
untouched.** Suite on canonical dev: **1429 passed, 4 skipped, 6 xfailed, 0 failed.**

> **⚠ OPEN AND URGENT — start here:** `/root/legendarypicks/PLAN-scores-prev-day-2026-08-14.md`
> Micah reported the `/scores` previous-day arrow showing today's games. I also confirmed
> `/api/{league}/games?date=X` returns **500** for older dates. Neither is fixed.

---

## 1. The one-line summary

Every documented cause of the props gaps was wrong. Measuring instead of reading found the
real ones, and the biggest was that a **failed settlement was stored in the same shape as a
successful one**, so every "settled props" number anyone had ever quoted counted failures
as successes.

## 2. What the docs claimed vs what was true

| the roadmap / backlog said | measured reality |
|---|---|
| "blocked on the ESPN host recovering" (#3, #4) | host was up. `link_prop_games.py` had been **refusing every nightly run** and `run_pipeline.py` printed `link: ✅` over it, because a refusal returned exit 0 |
| "the story generator is wired for mlb/nba/nfl/nhl only" (#24) | `game-recaps.sh` already passed mls+lcup. The sweep was dying with a `NameError` on its first MLB game every 3h since `25391c7` (08-12) |
| "settlement path exists (WC settles 1,128/1,128) — wire ufc into it" (#22) | **WC settles zero.** All 1,128 rows have a NULL outcome |
| "MLB has 57,392 settled props no game page can reach" (#21) | inverted: MLB settles 747,498 and **690,106 were already reachable**; 57,392 was the 7.7% remainder |

Both docs were corrected in place (`8bd49ae`, `b4e3507`) — originals kept, corrections
appended, so the reasoning stays readable.

## 3. The core defect: `settled_at` was not an outcome

`settlement.py` stamped `settled_at` on props it could **not** map, leaving `hit` and
`actual_value` NULL. Consequences:

- Every count keyed on `settled_at IS NOT NULL` counted failures as successes.
- Worse: `settle_props.py` selects games `HAVING settled_props < total_props` against
  `prop_results`, so **any row written excludes that prop from every later run**. An
  unmappable prop was unsettleable *forever*, even after the missing mapping was added.

All **13** null-placeholder write sites are now gone (codex, `02b45ef`). The contract:
write a `prop_results` row **only for a numeric outcome**; every inability-to-grade state
(`unmappable`, `pending`) writes nothing and stays retryable.

Read-side fix in `league_feature_matrix.py`: filter on **`actual_value IS NOT NULL`**, not
`hit IS NOT NULL` — a push is a graded prop that legitimately stores `hit=NULL` beside a
real value. Changes no number today (zero pushes exist; these books price at .5) which is
exactly why it was worth fixing.

## 4. Measured before → after (canonical dev)

| | before | after |
|---|---|---|
| MLS `prop_games` linked | 2/15 | **15/15** |
| UFC linked (live window) | 0/13 | **13/13** |
| MLS props settled | 0 | **57**, zero empty |
| MLB posted props reachable | 5,148/7,000 | **7,000/7,000** |
| MLS stories | 0 | **11** |
| UFC stories | 0 | 12 (see §7 — not honest) |
| null-placeholder write sites | 13 | **0** |

`/api/game/mls/761469/props` now returns `actual 1.0, hit true, cashed "over"` — the first
time MLS has ever settled a prop.

## 5. Root causes worth remembering

- **Two publishers spell clubs differently.** MLS linking failed on word order
  (`New York Red Bulls` / `Red Bull New York`), punctuation (`DC United` / `D.C. United`),
  contraction (`Los Angeles FC` / `LAFC`) and dropped `FC`/`SC`/`CF` suffixes. Fixed with a
  **recorded vocabulary** (34 spellings of 30 clubs), not a normaliser — a suffix stripper
  also accepts "San Diego FC" for San Jose, and a mislinked game settles against the wrong
  boxscore invisibly.
- **One dead abbreviation in thirty.** The linker emitted `CWS` where ESPN publishes `CHW`
  (this repo is canonically `CHW`; `team_codes.py:43` already carried the correction). Found
  by diffing the **whole map** against the publisher, not by chasing the failing game — the
  set-based test also caught a retired `OAK` (the A's moved; ESPN serves `ATH`).
- **UFC ids are fight-competition ids, not event ids.** `espn.game_result('ufc', <id>)`
  404s, and so does the parent card on the summary endpoint. The working shape is the
  date's **scoreboard**, where the fight carries `status.type.completed` and athlete
  competitors. `espn_client.neighbor_dates()` is now shared by the linker and settlement so
  they cannot drift — UFC cards start late enough that ESPN's local date is routinely the
  day before the book's.
- **Stale logs presented as current form.** MLS/NCAAF/NFL `player_game_logs` stop at 2025.
  A 2026 preview read "Kelvin Yeboah has no goals in his last five matches" — those five
  were 2025-09-14…11-25. `player_form.py` labels the season correctly; the writer stripped
  the label. Now the whole form section is suppressed when the newest log predates the
  game's season (read from `header.season`, **not** kickoff year — an NFL January game
  belongs to the prior season), with a `form_suppressed` flag so the story regenerates
  once when logs catch up.

## 6. Still open

1. **`/scores` prev-day bug + the 500** — **FIXED, awaiting merge.** `ec5872e` in
   `/root/lp-scores-prev-day` (plan: `PLAN-scores-prev-day-2026-08-14.md`).

   What it actually was: **not** stale games persisting. The previous-day arrow moved the
   date correctly (header read Aug 13); all 11 Aug-13 fetches 500'd and the board rendered
   **empty**. Cause was the same ESPN 403 → 500 defect: `get_games` fetches the scoreboard
   live per request and only caught `ValueError`, so any publisher refusal reached the user
   as `Internal Server Error`. Measured on prod: 08-13→08-10 served (TTL cache), 08-09 and
   older 500'd.

   The fix serves **our own recorded games**, not invented ones: `team_game_results` where
   `status='completed'`, requiring a matched home/away pair with reciprocal scores
   (`home.score_against == away.score_for`) and **rejecting** partial or contradictory pairs
   rather than rendering them. Day-precision data stays day-precision. Also fixed a
   date-only comparison that rolled the prior day backward in Central time, made Scores date
   navigation strict so it clears stale cards, and surfaces partial vs full load failure.
   Tests: backend outage, local-date, and Scores page regressions. **backend 1433 passed**;
   two pre-existing unrelated `WCContext` copy failures on the frontend.
2. **Delete plan** (`215010c`, in `SETTLEMENT-DIAGNOSIS-2026-08-14.md`) — **awaiting Micah's
   decision, not run.** Removes pre-existing null-outcome rows so those props become
   retryable: dev mlb 105,150 / wc 1,128; **prod mlb 279,404 / wc 392**. Predicate verified
   push-safe (a push has a non-null `actual_value`, so it cannot match); zero pushes and
   zero orphans exist in either DB; preflight counts reproduce exactly. Codex rejected
   `hit = -1` as a void sentinel because `routers/game_extras.py` does `bool(hit)` and would
   turn a void into a **win**; the right shape is an explicit status column, deferred.
3. **NCAAF/UFC previews** never landed on canonical dev — ESPN 403. hermes has a standing
   task to retry when it lifts and to ping unprompted.
4. **UFC story surface is not honest** (hermes' own words). Its 12 previews are truthful but
   near-empty ("no reported records, streaks, or stakes on the sheet"), and **one leaked a
   raw `None`**: *"both G. Robertson and M. Dern carrying None-None records"*. Recommend
   deleting the 12 and gating UFC out of the sweep until the surface has something to say.
5. **`run_pipeline.py` changes run against PROD tonight** (`19-23,0-3` cron, `picks.db`).
   Scoped per-league linking with a `--days 3` window — an improvement, but it has never
   executed against prod. Worth watching the first run.

## 7. Process lessons (written to memory)

- **A refusal that exits 0 becomes a green step.** The linker printed `REFUSING:` and
  returned 0; the pipeline reported `link: ✅` every 30 minutes for months. It now exits 2.
- **I caused an outage.** Cumulative ESPN spend (my linker runs, vocabulary probes,
  settlement) got this box 403'd, and **prod shares the egress IP**, so production's
  schedule broke for older dates. I never loaded `espn-request-budget` before a day of
  fetching. hermes, which was told to read it, was the careful one — it added the disk
  cache and measured **32 req/run → 24 cold → 0 warm (256/day → ~24–48/day)**.
- **Agent DB copies must use `sqlite3 .backup`, not `cp`.** I handed both agents raw `cp`
  copies of a live DB; hermes' failed integrity on the `game_story` PK index. Canonical and
  prod verified `quick_check: ok`.
- **`pgrep -f "pytest backend"` matches your own monitoring command**, and
  `systemctl is-active --quiet` is false for a `Type=oneshot` service (it is `activating`).
  Both produced wrong readings I briefly reasoned from.

## 8. Key files

- `SETTLEMENT-DIAGNOSIS-2026-08-14.md` — codex's diagnosis, delete plan, verification
- `/root/lp-story-coverage/STORY-COVERAGE-REPORT.md` — hermes' evidence, cache measurements
- `backend/league_feature_matrix.py` — now renders the game-page lifecycle
  (BEFORE / DURING / AFTER) and the six surfaces it had always computed and never printed
- Worktrees `/root/lp-ufc-settlement`, `/root/lp-story-coverage` — both merged, safe to remove
