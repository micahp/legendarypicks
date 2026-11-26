# TASK (Codex): clear the path to cutting v0.8.0

Repo **/root/legendarypicks**, branch `dev`. Written 2026-08-17. Every number in this document was
measured the day it was written — **re-measure before you act on any of them**, and say so when a
number has moved. A count in a task doc is a starting point, never evidence.

Micah, 2026-08-17: *"i've been trying to get a release for a week."* That is the whole point of this
task. Work that clears a release blocker outranks work that is merely correct.

---

## 0. OPERATING RULES — read before anything

- **Dev servers are externally managed and already running: frontend `:3096`, backend `:8096`.**
  **NEVER start, kill or restart a dev server, uvicorn, or node.** No `kill`, no `pkill`, no
  `systemctl restart`. If a page looks stale, re-request it — the backend runs `--reload` and
  recompiles on its own.
- **Do NOT touch host config.** Nothing in `/etc`, no `systemctl` unit files, no timers, no cron.
  A worktree does not isolate these; an agent installed a live timer on this box against that rule
  and it is still firing. If a task seems to need one, stop and report it instead.
- **Do NOT commit, tag, or push. Claude owns git.** Report files changed and how you verified.
  Leave the working tree readable: no stray scratch files in the repo root.
- **Do NOT run `scripts/release.sh`.** Cutting the release is Micah's call, not yours. Your job is
  to make its preflight pass.
- **Never write to `backend/data/picks.db` (PROD) without saying so first and getting a yes.**
  Prod's DB is bind-mounted and live — a write lands immediately. `picks.dev.db` is yours.
- **Read `AGENTS.md` and `docs/DEV-STANDARDS.md` first.** They are not optional context; the rules
  in them came from real incidents.
- **HTTP 200 is not proof.** Neither is a row count, a green suite, or a passing gate. Every one of
  those is a claim *about* a thing, and this repo's entire backlog is made of claims that were true
  while the thing was broken.

## 1. Load these skills — they are not documentation, they are constraints

Load a skill **before** writing code in its domain, not after something breaks. `ls .claude/skills/`
if you want the full list.

| skill | load it before |
|---|---|
| `published-first` | any value you are about to derive, aggregate, backfill or reconstruct — and before trusting any table you just ingested. **A definition is always published.** Item 2 below is squarely this. |
| `fail-loudly` | any ingest, any join that feeds a page, any `except: pass`, any "best-effort" step. This is the single shape behind every item in `docs/BACKLOG-holes.md`. |
| `espn-request-budget` | any code that calls an ESPN host, and before diagnosing a 403. ESPN's limit is a request **count per host**, not a rate — pacing does not save you. |
| `resource-check` | any backfill, bulk scrape, or multi-chunk loop. This is a shared box with a live dev server on it. |
| `honest-data-ui` | only if you end up touching a surface that shows numbers. Probably not needed here. |

## 2. WHAT "DONE" MEANS — the exit condition, exactly

**`scripts/release.sh 0.8.0 --dry-run` completes without dying.** That is the only definition. It
is not "the gates are green" — `verify-gates.sh` is the dev-side suite and several of its gates are
**red on purpose** (see §5). The release preflight is a different, shorter list:

1. Working tree clean, `v0.8.0` tag does not exist locally or on origin.
2. `CHANGELOG.md` has a `## v0.8.0` section. **Release notes must already exist — the script
   deliberately does not generate them.**
3. Nothing marked DEPRECATED/SUPERSEDED is still reachable.
4. `backend/diff_databases.py --quiet` reports **zero SCHEMA/SEASONS differences**. Volume
   differences are advisory and do not block.
5. `backend/audit_league_stats.py` against **prod** (`backend/data/picks.db`) reports **zero FAIL**.
   UNVERIFIED does not block.

Run 4 and 5 yourself before you start, and again when you think you are finished. They are the
scoreboard.

---

## 3. THE WORK, in the order I would take it

### Item A — 15 blocking prod/dev differences · **biggest item, do it first**

`backend/diff_databases.py` reports 15 blocking differences as of 2026-08-17. Every one is the same
sentence: *a promotion that did not happen.* Dev has been built on for a week; prod has not received
it.

**Schema — 3 tables and 8 columns missing from prod:**

```
table 'player_source_ids'        in DEV, missing from PROD
table 'prop_game_source_ids'     in DEV, missing from PROD
table 'source_probe_log'         in DEV, missing from PROD
game_story.form_suppressed       in DEV, missing from PROD
player_stats.att                 in DEV, missing from PROD
player_stats.intc                in DEV, missing from PROD
player_stats.pass_yds            in DEV, missing from PROD
player_stats.rec                 in DEV, missing from PROD
player_stats.rec_yds             in DEV, missing from PROD
player_stats.rush_yds            in DEV, missing from PROD
team_game_stats.stats            in DEV, missing from PROD
```

**Seasons — 4 (league, season) pairs on dev and absent from prod:**

```
player_game_logs      (mls, 2026)
player_stats          (ncaaf, 2025)
team_stats_coverage   (mls, 2025)
team_stats_coverage   (ncaaf, 2025)
```

**How to approach it:** `backend/migration_manifest.py` is the ledger — one invocation migrates
**both** databases, and the app refuses an un-migrated one. Find which registered migration owns
each table/column and run it against prod rather than hand-writing DDL. `docs/RUNBOOK-prod-promotion.md`
is the procedure. For the seasons, the promotion scripts already exist and are named in
`docs/BACKLOG-holes.md` row 43 (`migrate_mls_season_columns.py`, `ingest_mls_season_stats.py`,
`migrate_player_entity_type.py`, `backfill_ncaaf_positions_cfbd.py`), each taking
`--db data/picks.db --apply`.

**⚠ The trap that has already cost us once, 2026-08-17.** Prod's **code is baked into the container
image** (`legendarypicks-backend-1`, built 2026-08-12); only `backend/data` is bind-mounted. So a
schema change lands on prod *instantly* while the code that understands it does **not** land at all
until the release. Adding an index or a constraint that prod's frozen writer cannot satisfy strands
data silently. **Additive nullable columns and new tables are safe. Constraints, indexes and NOT NULL
are not — defer those to the release.** Before applying anything, ask: *which processes write this
table, and are they running from the image or from the working directory?*

**Done when:** `diff_databases.py --quiet` prints zero SCHEMA/SEASONS lines, and you have said which
migration you ran for each one.

### Item B — the one audit FAIL against prod

```
FAIL  mlb  A/required-stats[pitching]  column exists but 0 rows populated: innings, era, whip
```

**Load `published-first` before touching this**, because the obvious move is wrong. Do not compute
ERA. There is a standing finding in this repo that **no ERA and no goalie save value exists in any
publisher feed we read** — if that still holds, the honest resolution is that the audit's MANIFEST
requires a stat nobody publishes, and the fix is to the MANIFEST (with the evidence recorded), not a
derivation. Your first job is therefore to answer, with evidence: **does any publisher we already
call return innings/ERA/WHIP per player?** If yes, ingest it. If no, say so and propose the MANIFEST
change — do not quietly compute ERA from earned runs and innings and call the gate green.

**Done when:** either prod has real published values, or the MANIFEST no longer requires an
unpublished stat and the reasoning is written into `docs/LEAGUE-STAT-GAPS.md`.

### Item C — `COV-identity`: one orphan row on prod

```
migrate_player_stats.check_database('/root/legendarypicks/backend/data/picks.db')
  state: blocked   issues: {'orphan_players': 1}
```

The row: `player_stats.id=218214`, `player_id=32561`, `league='mls'`, `season=2025`,
`stat_type='season'`. There is no `players` row with `id=32561` on prod. Almost certainly a casualty
of the MLS shadow-player merge that ran on dev and not on prod (`BACKLOG-holes` row 42: 531 shadow
MLS players still on prod).

**Do not just delete it.** Find out which player it belonged to first — if it is a real athlete's
2025 season, deleting it loses data that a merge should have repointed. Check whether dev has the
surviving player and what `merge_mls_prop_players.py` did with that id.

**Done when:** the row is either repointed at the right player or deleted with a stated reason, and
`check_database` returns `ok`.

### Item D — `REG-jest-all`: 2 failing tests in `components/Game/WCContext.test.tsx`

```
✕ Game Context replaces the mounted snapshot after 30 seconds without loading flicker
✕ Game Context keeps the last good response on a failed background refresh and cleans up
```

Both die in `getByText` (lines 87 and 124) — the element the assertion looks for is not in the DOM.

**Read `AGENTS.md` §0 before you spend time here.** World Cup is out of season and `wc` code is
explicitly dormant; the next tournament is 2030. So the question to answer first is not "how do I fix
this component" but **"should this test still be asserting this?"** If the component's behaviour
changed deliberately, the test is stale and should be updated with a note saying why. If the
component actually regressed, fix the component. Either way, say which one it was — the two have very
different implications and "made the test pass" hides the difference.

### Item E — `COV-gametype`: 1,579 NULL `game_type` rows in mlb 2026

Of 53,895 rows. `game_type` is the column `routers/nfl_offseason.py` guards on for existence and then
filters on for value: where it is NULL, `AND game_type='REG'` matches nothing, `games_played` returns
0, and a healthy player renders "missed 82 games" in amber. That is the user-visible cost.

Find what wrote those 1,579 rows without stamping the column, fix the writer first, then backfill.
Fixing only the backfill guarantees the next ingest re-creates them.

### Item F — `REG-adp-dst`: HOU at 236, expected 223

```
FAIL REG-adp-dst (n=32 null_adp=0 off_expected=[('HOU', 236, 223)])
```

Read the gate's own comment in `verify-gates.sh` before touching anything: the expected values were
written 2026-07-31 **before the code**, measured directly from ESPN, and the comment says explicitly
**"Do not relax it to make it green — a diff to these numbers is a finding."** Tolerance is ±12 and
exists for ESPN drift only.

So the question is whether ESPN's published PPR rank for HOU actually moved, or whether our ingest is
reading the wrong field. **Go and read what ESPN publishes today.** If ESPN now says 236, that is
drift and the expected value gets updated *with the measurement recorded in the commit*. If ESPN
still says 223, the ingest has a bug and the gate is doing its job.

---

## 4. NOT IN SCOPE — do not spend time here

- **`BOARD-stale-prod`** is red and will stay red until the release ships. It is measuring the deploy
  skew itself: prod serves 2 finished games because `routers/props.py` is baked into an image built
  2026-08-12. Cutting the release is what fixes it. Do not try to fix it another way.
- **`COV-source` and `COV-statset` are RED ON PURPOSE.** Both gates say so in their own comments.
  COV-source stays red until unattributed rows can be attributed *from a recorded run_id* — never by
  guessing. COV-statset tracks 12 known-open items documented in `docs/LEAGUE-STAT-GAPS.md`.
- **World Cup anything** beyond item D. Dormant until 2030.
- **NCAAF surfaces.** Built and deliberately dark by decision (Micah, 2026-08-11).
- **Scores W2/W4 (Top Events, week model).** Deferred to the post-0.8.0 scoreboard redesign.
- **`test_story_form_season.py` mls-2026.** It asserts MLS logs stop at 2025 and they no longer do —
  it is failing because the data got *better*. Flipping that expectation is a two-line change but it
  is Micah's call, not a release blocker. Leave it.

---

## 5. THE ANTI-DRIFT PROTOCOL — run this, don't just intend to

Long tasks fail by forgetting, not by being wrong. The specific way it happens here: you measure
something in step 3, act on the memory of it in step 30, and by then the number has moved or the
thing you measured was a different database. Ground truth gets replaced by your own summary of it.

**Re-run this block every ~10 tool calls, and always before writing to any database or declaring an
item done.** Paste its output into your working notes. It costs seconds and it is the difference
between a report that is true and a report that was true an hour ago.

```bash
cd /root/legendarypicks
echo "=== branch / tree ==="; git rev-parse --abbrev-ref HEAD; git status --short | head -20
echo "=== which DB am I about to touch? ==="; echo "LP_DB_PATH=${LP_DB_PATH:-<unset — scripts will default to PROD picks.db>}"
echo "=== the release scoreboard ==="
backend/venv/bin/python backend/diff_databases.py --quiet 2>&1 | tail -3
backend/venv/bin/python backend/audit_league_stats.py --db backend/data/picks.db \
  --league nfl --league mlb --league nba --league nhl --quiet 2>&1 | tail -3
echo "=== servers still as I found them? ==="; ss -ltn 2>/dev/null | grep -cE ":(8096|3096)\b"
```

Then answer these four questions **in writing**, every time:

1. **Which item am I on, and what is its stated definition of done?** Not "roughly done" — the
   sentence from §3.
2. **What have I actually changed since the last checkpoint?** Files, not intentions. If `git status`
   shows something you did not expect, stop and explain it before continuing.
3. **Which database did my last write go to — `picks.db` or `picks.dev.db`?** If you cannot answer
   from evidence rather than memory, run the check again. Several of this repo's worst incidents are
   a correct fix applied to the wrong database.
4. **What is the newest number I have, and how old is it?** If a count you are reasoning about is
   more than a checkpoint old, re-measure it before it becomes the basis of a decision.

**If any answer is "I'm not sure" — stop and re-measure. That is the whole protocol.** An
"I'm not sure" that gets papered over becomes a confident sentence in your final report, and a
confident sentence in a report is what the next person builds on.

One more, specific to this repo: **when you run a check, name the database in the same breath as the
number.** "1,579 NULL rows" is not a finding. "1,579 NULL rows in `picks.dev.db`" is. A gate run
against the wrong DB has produced a confident wrong number here at least twice —
`verify-gates.sh` now refuses to run if `LP_DB_PATH` is set without `LP_GATE_D`, because of exactly
that.

---

## 6. HOW TO REPORT BACK

For each item you touched:

- **What you changed** — files, and the one-line reason for each.
- **The before and after measurement, through the same path.** Two numbers taken different ways are
  not a comparison. If you fixed a filter, measure through the filter that runs, not the function
  you edited.
- **What you did NOT do and why.** An item you skipped for a good reason is a finding; an item you
  skipped silently is a hole in the next person's picture.
- **Anything you found that is not on this list.** Especially anything that looks fine but that you
  could not prove is fine.

Finish with `git status --short` and the output of the §5 block, so Claude can see the tree exactly
as you left it.

**If you get blocked, say so early and specifically.** "Item A is blocked because migration X has no
registered owner" is useful in the first hour. Discovering it in the last one is not.
