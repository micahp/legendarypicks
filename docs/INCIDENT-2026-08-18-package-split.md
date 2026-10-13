# Incident: the 2026-08-18 package split broke callers that were not imports

**Status:** closed 2026-08-19. All live breakage repaired, one class-level check added.
**Severity:** low blast radius, long dwell time. Nothing user-facing went down. Two releases
shipped with their main data gate silently disabled, and one MLB ingest was dead for two days.
**Author:** written 2026-08-19 evening, after the v0.8.4 cut.

---

## 1. What happened

On 2026-08-18, ten backend modules over ~1,100 lines each were split into packages by a fleet
of subagents. The refactor itself was correct. Measured on 2026-08-19:

- `pyflakes` over every tracked backend `.py`: **0 undefined names, 0 import errors.**
- Test suite: green apart from one long-standing MLS failure.
- Every package imports, and every re-export the splits promised is in place.

And yet three things were broken the whole time, none of which any of that could see.

| Broken | Dwell | How it failed |
|---|---|---|
| `/etc/cron.d/legendarypicks-pipeline` ran `bovada_scraper.py mlb --ingest` | 08-18 to 08-19, 7 runs | `can't open file 'bovada_scraper.py'`, straight to a log nobody read |
| `scripts/release.sh` prod stats audit | 2 releases (v0.8.2, v0.8.3) | guarded by `[ -f backend/audit_league_stats.py ]`, so it **skipped in silence** |
| `verify-gates.sh` COV-statset | same | read python's exit 2 ("can't open file") as *2 failures against a known 21*, and printed that as **progress** |

## 2. Root cause

Not the agents. The dispatch specs. Recovered verbatim from
`~/.hermes/sessions/request_dump_20260818_101505_0a6626_*.json`:

> Split `backend/ingest_ufc_fight_stats.py` (1182 lines) into a package
> `backend/ingest_ufc_fight_stats/` **keeping the full external surface working** (names in
> context: ...). **Verify with import smoke test, the 2 UFC test files, and the importers
> check.** Report exact pass/fail counts.

Every verification named lives inside Python: an import smoke test, test files, an importers
check. The agents satisfied all three, correctly. **"External surface" meant the import
surface.** Cron, systemd, shell gates and Dockerfiles were never in scope, so a caller that
reaches the code through `argv` instead of through `import` was invisible to the task as
written.

That is the whole incident in one line: **a split cannot see a caller that is not an import,
and nothing in the spec asked it to look.**

### 2a. The aggravating factor: repo and host drifted

The cron is the sharpest case. The **repo** copy of that same cron had already been corrected
to `-m bovada_scraper`. The **installed** copy at `/etc/cron.d/` was never reinstalled. So:

- Reading git showed correct code.
- The thing that actually ran was wrong.
- No review of the repository could have caught it.

Identifying a job by its source file rather than by the file that executes is the same shape
as identifying a server by how good its data looks.

### 2b. Why the two gates hid it instead of reporting it

Both failed *open*, in different ways, and this is the more expensive half:

- `release.sh` wrapped the audit in `[ -f <path> ]`. A missing runner made the condition
  false, and a false condition means "skip", so the release preflight's single most important
  data check stopped running without printing a word. **v0.8.2 and v0.8.3 were both cut with
  it disabled.**
- `verify-gates.sh` captured python's exit status. `2` from "can't open file" landed in the
  `-le 21` arm meant for known-open stat gaps, so the gate announced **"2 of a known 21
  open"**, a *missing runner* rendered as an improvement against the gap list.

An absent measurement was reported as a good measurement. Twice, independently.

### 2c. Contributing: the split ran out of money mid-flight

The last three splits (`ingest_league_news` 10:12, `ingest_ufc_fight_stats` 10:15,
`routers/nfl_offseason` 10:20) each terminated on **HTTP 402 Insufficient Balance**. The
orchestrating session took 8x 429 and 4x 402 on top. So the tail of the sweep was cut off
before its own verification ran, which is consistent with what the sweep later found: the two
packages carrying a dead entry point are among those interrupted.

## 3. What the split actually cost

Nothing user-facing. The board stayed up, the API stayed 200, the suite stayed green. What it
cost was **two releases' worth of assurance**, plus an MLB ingest, plus the two days it took
for anyone to ask a question the checks were not built to answer.

Worth stating plainly: the gates being green is exactly why this lasted. A red gate gets
fixed. A gate that cannot run and says nothing gets trusted.

## 4. Fixes applied

| Fix | Commit |
|---|---|
| `audit_league_stats/__main__.py`; both shell callers moved to `-m`; an unrunnable audit now **fails loud** in both | `fe8c449` |
| Cron line removed (not repaired, see below); `espn_client/__main__.py` and `ingest_ufc_fight_stats/__main__.py`; `scripts/check_command_targets.py`; stale `release.sh` pointer | `2775169` |
| Stale `backend/narratives/__pycache__` removed (package itself was deliberately deleted in `ad6a0fa`) | working tree |

**The cron was removed rather than repaired**, deliberately. `legendarypicks-props.timer`
already runs `-m bovada_scraper all --ingest` every 30 minutes and `all` includes MLB.
Restoring the cron would have put a **second concurrent Bovada writer** against one database
and one publisher budget, which is the shape that 403'd all three ESPN hosts once before, and
plausibly related to the `database is locked` EXIT 3 failures seen on the props timer.

### The check that makes this class visible

`scripts/check_command_targets.py` asks the one question the split's own verification could
not: **does the thing this line runs exist?**

- Reads **installed** host config (`/etc/cron.d/legendarypicks*`,
  `/etc/systemd/system/legendarypicks-*.service`, root crontab), not the repo copy, because
  the gap between them *is* the defect.
- Expands shell variables from the file itself, so `$SCRIPTS/run_pipeline.py` resolves.
- Honours systemd `WorkingDirectory` for relative commands.
- Skips disabled lines. A gate that flags dead comments gets ignored, and an ignored gate is
  the thing this incident is about.

Exit 1 on any dead target. Green as of 2026-08-19 20:10.

## 5. What was checked and found clean

So the next reader does not redo it:

- **Python imports**: pyflakes over all tracked backend `.py`. 0 undefined names, 0 import
  errors, 0 syntax errors.
- **systemd units**: every `ExecStart` in `legendarypicks-*.service` resolves.
- **Repo callers**: every `.py` path named by any `.sh`, `.js`, `.json`, `.yml`, cron or
  Dockerfile in the repo. Remaining hits are prose in comments and historical
  `.context/retros/*.json`, not commands.
- **Package entry points**: all ten split packages import; `-m` verified working for
  `espn_client`, `ingest_ufc_fight_stats`, `audit_league_stats`, `bovada_scraper`.

## 6. Still open

**Updated 2026-08-19 21:00. Everything in the original list is now closed except one item.**

1. ~~`ingest_ufc_rankings.py` never installed.~~ **Closed.** Reviewed: stdlib only, one
   request, 30s timeout, validates the complete scrape and replaces the table in one
   transaction, so a malformed scrape leaves the last known-good rankings. Its real cost was
   worse than "never run": `GET /api/ufc/rankings` is **live in prod** and had been serving a
   **2026-06-30** scrape as current for seven weeks. **81 of 208 ranked slots were wrong**
   (no champion changed). Prod refreshed, weekly cron installed, installed copy now in sync
   with the repo copy.
2. ~~Two tests red for three hours a day.~~ **Closed, and neither was a test bug.** Both were
   the same local-vs-UTC defect in production code:
   - `scoreboard_store.needs_refresh` compared a **New York** `game_date` against the **UTC**
     date. The UTC date rolls over at 20:00 ET, so from 8pm to midnight Eastern an empty
     slate was told "day is over and published no games" and the backoff that exists to
     catch a late addition was skipped, during the four hours a late addition is most
     likely. Now uses `_slate_day`, the same function that decides `game_date`.
   - `routers/props._KICKOFF` fell back to `pg.date || 'T23:59:59Z'` for a timeless row.
     Once `pg.date` became the NY slate day that meant **7:59pm Eastern**, so such a row
     dropped off the board mid-evening and only looked right because the 3-hour grace pushed
     it to about 11pm. Now midnight Eastern. Still 2 such rows on prod, 28 on dev.

   Both tests are now pinned to the code's own idea of today. `dt.date.today()` was the
   second time bomb in that file after the date literal its own comment warns about: it is
   the **box's** date, Central here, which disagrees with New York for one hour a night.
3. ~~Four duplicate `prop_games` pairs.~~ **Closed.** Three were one game stored twice and
   were folded with `prop_game_merge.fold_prop_game` (prod 357 into 341, dev 563 into 560
   and 608 into 594), then `dedupe_props.py --apply` reconciled clean on both:
   prod props **62,835 to 58,480**, 250 redundant results dropped, 1,452 odds snapshots
   repointed; dev **69,069 to 68,697**. **Both databases now hold zero duplicate prop
   groups**, which they did not before any of this: 670 groups existed on prod and 170 on dev
   independently of the folds.
4. **A doubleheader and a duplicate are still indistinguishable to the ingest's match key.**
   Not closed, but no longer invisible. `prop_game_merge.shared_match_keys` now states the
   rule the codebase could not: the published final separates them and nothing else does, so
   finals that disagree between two settled rows mean a doubleheader and anything else means
   a duplicate. An **unsettled** pair is called a duplicate deliberately, because guessing
   "doubleheader" lets a real duplicate serve the same prop twice. Runnable as
   `LP_DB_PATH=... python prop_game_merge.py`; exits 1 on a duplicate or a dangling source
   mapping, 0 on a doubleheader. Prod: 0 shared keys. Dev: 1, and it is the real
   doubleheader (07-27 Reds/Guardians, Postponed and replayed as two on 07-28).

   **The underlying fix is a schema change and has not been made:** the key needs the kickoff
   instant, or a game number, to be unique. Left as a decision.

5. **`backend/narratives/` was a partial extraction, reverted the same morning.** Recorded
   here because "stale narratives" is not obvious from the name: a subagent created 532 lines
   across `constants`, `topic_words` and `anchor_routing` that **nothing ever imported**, and
   whose `_better_home` had already drifted from the original. Reverted in `ad6a0fa` at
   10:05. The revert removed the tracked sources; the untracked `__pycache__` survived on
   disk until 2026-08-19 and made the package look like it still existed to anything checking
   for a directory.

## 7. The lessons, in the order they cost the most

1. **A gate that cannot run must fail, never skip.** Both gates here failed open, and one
   dressed a missing runner as progress. "Evidence unavailable" is a FAIL.
2. **Scope a refactor by what CALLS the code, not by what imports it.** The next split spec
   should name cron, systemd, shell gates and Dockerfiles explicitly, or it will reproduce
   this exactly.
3. **Identify a job by the file that runs, not the file in git.** Repo-correct and
   host-stale look identical from inside a code review.
4. **A green suite plus clean pyflakes is a claim about the language, not about the system.**
   Both were true here for two days while three things were broken.
