# CONTEXT 2026-08-02 — league-0 built and green; NHL unblocked; provenance is now recorded

**Read this first, then `bash /root/legendarypicks/verify-gates.sh cov` with
`LP_GATE_B=http://127.0.0.1:8096`. The state of the work is the gates, not this file.**

Supersedes `CONTEXT-2026-07-28-HANDOFF-14.md` on data/coverage. Pt.14 is **still current**
on everything else (next-swc, mock draft, D/ST ADP, the `feat/dst-and-mock-draft` branch).

---

## 1. Where the code is

Branch `dev`, **48 commits ahead of origin, NOTHING PUSHED.** Today's are the last twelve:

```
435f5e9 fix(gates): a named gate that measured nothing exited 0
804f6d8 fix(gates): the defaults named a worktree that was deleted, so nothing ran
fa4dedb feat(gates): a phase nobody asked for is a phase nobody has — NHL postseason
860179c docs(data): the game-type boundary, and why the mapping is measured not declared
9529228 fix(data): NHL game_type, read back off the publisher instead of the request
22fe51a feat(gates): COV-gametype — a column that exists and holds NULL is not populated
730592f docs(data): the season-key migration, and provenance as the reason it was invisible
8d9e136 feat(data): every row says which publisher wrote it
25bdbb4 feat(gates): make the key split detectable — it was invisible, not merely unfixed
9efbb2a fix(data): both nhle ingests normalise at the boundary; migrate 49,737 historical rows
bdb9e16 feat(data): season_keys — the boundary where a publisher's season vocabulary becomes ours
d3455be fix(data): write_coverage passed NULL for both NOT NULL season columns
```

and the five from earlier in the session (`3173d84`..`f99f3db`) that are league-0 proper.

## 2. The gates

`verify-gates.sh` now defaults to the main tree and the pair it actually serves on
(`W=/root/legendarypicks B=:8096 F=:3096`), so **no env vars are needed** for a main-tree run.

```
bash verify-gates.sh cov
  PASS COV-nba      (1231 games, 28 teams at 82, NY/SA at 83)
  PASS COV-nhl      (1312 REG in both tables)
  PASS COV-honest   (3 coverage rows, none claiming more than its run supports)
  PASS COV-keys     (every league speaks one season vocabulary in every table)
  FAIL COV-source   (RED ON PURPOSE — see §6)
  FAIL COV-gametype (RED ON PURPOSE — nba 2026: 24086/24086 rows NULL)
  PASS COV-api      (3 rows, complete=['nfl', 'nhl'])
```

**`verify-gates.sh all` runs end to end again — 24 verdicts, 17 pass / 7 fail.** It had been
unrunnable since `/root/lp-team-vocab` was deleted: `W` defaulted to that worktree and `B`/`F`
to its servers on `:8098`/`:3098`. Two defects, both fixed:

- The suite reported `FAIL B1`, `FAIL B4`, `FAIL A1` — the shape of the code being broken,
  not of the harness pointing at nothing. Worse, `grep -c pattern /nonexistent` is `0` and
  three of B4's six sub-checks pass **on** `0`, so half of B4 agreed with itself over a
  deleted directory. `need_w` + `have_files` now refuse instead, naming the reason.
- A named gate that emitted no verdict at all exited **0**. `verify-gates.sh A1` against a
  dead backend printed a JSONDecodeError and `── 0 passed, 0 failed ──`, so
  `verify-gates.sh A1 && deploy` shipped off a backend that was not running. Zero verdicts
  is now a FAIL. (Rule 2 existed but was enforced only for `all`.)

The 7 reds are all real and all against `dev`. Four are the known-red set (`COV-source`,
`COV-gametype`, `REG-pytest`'s `test_nfl_dst.py` six, `REG-jest-all`'s two `WCContext`).
The other three — **`B4` (`schedule_users=2/3`), `REG-pool` (4507), `REG-render`
(no "Exp PPR/G" column, 8 position pills not 9)** — are the mock-draft work that lives on
`feat/dst-and-mock-draft` and has never been merged to `dev`. Those expected values were
written for that worktree; against `dev` they honestly report it absent. **Do not relax them
to make `all` green on `dev`.**

**pytest: 7 failed, 537 passed, 20 skipped, 25 errors.** Baselined against a clean worktree
at `d3455be`: **7 failed / 519 passed / 25 errors — identical failure set.** None of them
are from today's work; today added +18 passing. The `test_nfl_dst.py` six are the known-red
`REG-adp-dst` surface. The 25 `test_nfl_mock_draft.py` errors are test-order pollution —
every one of them passes in isolation.

## 3. league-0 is done, and both ingest defects are fixed

Both backfills completed clean: **NBA 1231 games / 30 teams / 0 failures, NHL 1312 / 32 / 0.**

Two defects, not one:

1. The known transaction bug (explicit `BEGIN` under the driver's implicit transaction).
2. **A second silent game-loss, found while fixing the first.** `enumerate_games()` filtered
   on `state == "post"` plus a non-null score — but **a POSTPONED game is `state="post"`
   with a score of `0`, not null.** All four would have been written as played 0–0 results,
   crediting two teams a game they never played and handing one a loss, while the makeup was
   written too under a different event id. The filter now reads `completed`.
   **Any new league's ingest must filter on `completed`.**

**What caught it was not a test.** It was the per-team distribution: 1235 does not divide
into a schedule. Keep a check whose arithmetic can only close one way.

`published_real_games()` was replaced by **`explain_gap()`** — diffs the published event-id
set against ours and classifies only the difference, so cost scales with the gap rather than
the season. New leagues get gap classification free; **do not write a per-league variant.**

## 4. The NHL season key — fixed, and the lesson is where it was fixed

`reconcile_totals` reported `nhl 2026 ... ours=0 published=1312` for a season whose 1,312
games were all present. They were keyed `20252026`, because `ingest_nhl_logs.py` sources
**nhle.com, not ESPN**, and stored nhle's 8-digit span verbatim. NHL sat `partial` —
unofferable — on a misspelled question.

- **`backend/season_keys.py`** is the boundary, called by both nhle ingests. It **refuses
  rather than guesses**: there is no general rule to apply, because ESPN has no league-wide
  convention (NBA/NHL key by end year, NFL/EPL by start year, MLB by calendar year).
- **`migrate_nhl_season_keys.py`** moved 49,737 rows. It moves the **whole league** on
  purpose: `league_stats.py` resolves the live season with `MAX(season)`, so translating
  only `20252026 -> 2026` leaves `20242025` as the maximum — a two-year-old season served
  as current, from a migration that reported success.
- `nhl 2026 player_game_logs` now reads **1312/1312 PASS**.

**NHL is still `partial`, and now for the right reason: `game_type` is NULL on all 48,017
rows.** That is the next real blocker and the contract already names it.

**MLB's `team_game_results.season` is empty for all 3,305 rows — still open.**

## 5. `write_coverage` had never successfully written a row

It passed `None, None` for `season_start`/`season_end`, both `TEXT NOT NULL`. It raised
`IntegrityError` on the first row it ever tried to write. `COV-honest` did not catch it
because that gate only reads rows that **exist**.

Repaired by reading the window off the publisher (`types[].startDate/endDate`, in the
document `season_types()` already fetches — no extra request). **Not** `MIN/MAX(game_date)`
over our own rows: that is the ingest describing its own output, the exact defect
`write_coverage` exists to prevent, and a season missing its first week would silently
redefine when the season began.

## 6. Provenance — the reason the split was invisible, and the biggest finding of the day

The key bug is usually filed as a vocabulary mismatch. It is more precisely a **provenance**
bug: `team_game_results` is ESPN, `player_game_logs` is nhle.com, and **nothing anywhere
said so.** Note what `team_stats_coverage.source` held throughout:
`reconcile_totals+espn_core_api` — the provenance of the **verdict**, not of the data. A
column that looks like an answer and answers a different question is worse than an empty one.

Measured today (`backend/provenance.py`):

| league | publishers |
|---|---|
| NFL | `espn_site_api`, `nflverse`, `nflverse_regular_season`, `nflverse_weekly`, `nflverse_snap_counts` |
| NBA | `espn`, `espn_site_api`, `hoopR` |
| MLB | `mlb_statsapi`, `statcast`, `statcast_pitcher` |
| NHL | `espn_site_api`, `nhle.com` |

**Every one is a season-key, team-code and game-id boundary, and all are reconciled against
ESPN's totals. NHL is not a special case — it is the one that got caught.**

Now enforced:

- `team_game_results` gained `source` + `run_id`. It is the spine of the coverage contract
  and until today recorded only *when* a row landed, never from whom.
- `backfill_team_parity` prints a provenance readout **at the end of every run** — the one
  moment someone is definitely looking — and flags any league with >1 publisher.
- `/api/coverage` carries `publishers` per league, measured from the data. **Live on :8096.**
- `stamp_team_result_source.py` attributed 5,630 historical rows **from recorded evidence
  only** (`team_game_stats.run_id` matching `<league>-parity-<ts>`). MLB's 3,305 and NFL's
  1,114 have no such run_id and **stay NULL on purpose** — an unattributable row must keep
  saying so.
- **`COV-source` is RED ON PURPOSE** and names exactly which rows remain unattributed. It
  goes green when MLB and NFL 2024/2026 are stamped, not before.

**`derived` is not a publisher.** `player_stats` holds 580 NBA and 841 NHL rows sourced
`derived` — ours, computed. Legitimate, and never independent corroboration of themselves.
Anything reconciling against an oracle must exclude them or it is grading its own work.

`provenance.py` reads the schema with `PRAGMA` rather than declaring it. The first draft
declared that `team_game_results` had no source column — true for about forty minutes, until
the column was added and the module went on reporting `UNRECORDED` over correctly-stamped
rows. **A hardcoded claim about a schema decays exactly like the coverage rows this whole
contract exists to distrust.**

## 7. Also measured today, for the league specs

**MLS publishes SEVEN season types with non-contiguous ids (0, 1, 2, 3, 4, 8, 12)** and files
its All-Star Game as its own type (id 2). NBA files All-Star *inside* type 2. Two leagues,
two answers, neither derivable. The contract's "MLS has one season type" note was **wrong**
and is corrected — it generalised from EPL. `for t in range(1, 6)` misses ids 8 and 12:
**iterate the published list, never a range.** `id 0 "Combined"` publishes 0 events — an
empty published collection is a fact, not a fetch failure.

## 7b. Later on 2026-08-02 — NBA closed out, and the NFL fantasy log reshaped

**`nba 2026 -> complete`.** `COV-gametype` and `COV-api` both green;
`complete=['nba','nfl','nhl']`. 24,086 rows stamped, 0 NULL, 0 games in
`team_game_results` missing from `player_game_logs`. Counts reconcile against
ESPN's published season types: **REG 1231 / POST 85 / PLAYIN 6 / ALLSTAR 3**,
and `reconcile_totals` derives the same split independently
(`1239 published -4 exhibition -4 not played`).

Three findings the stated task did not include:

1. **A postponed game was in the database as played.** `401810384` MIA @ CHI
   2026-01-08 — `completed=False`, `status="Postponed"`, 0.0-0.0 — held **ten
   all-zero stat lines**, each dragging a real player's per-game average down
   for a game that never happened. This is §3's defect, except NBA's instance
   was *written*, not lost. Deleted; `ingest_nba_logs` now filters `completed`,
   and `espn_client.games()` publishes that field for every league.
2. **The "121-game gap" was 216**, and it was a date range that never ran
   (2026-03-05 → 04-01, continuous). Backfilled.
3. **The two tables key the same game to different calendar days.**
   `401810656` DEN @ LAC is on ESPN's **02-19** scoreboard with timestamp
   `2026-02-20T03:30Z`; `team_game_results` keys it 02-20. Late West Coast tips
   will do this in every league. Know it before NCAAF.

**Vocabulary widened to `PRE|REG|POST|PLAYIN|ALLSTAR`.** NBA publishes a fifth
season type (play-in, id 5) and files All-Star *inside* type 2 — `WORLD @ STARS`
carries `season.type=2` exactly as opening night does, distinguishable only by
`competitions[0].type.abbreviation == "ALLSTAR"`. **A publisher's phase field can
be right about the calendar and wrong about the question we are asking it.** NHL
needed only the id; NBA needs the id *and* the competition. `PLAYIN` is kept
distinct because that is the reversible direction — `game_type IN
('REG','PLAYIN')` recovers the other reading; collapsing cannot be undone.

**`feat/dst-and-mock-draft` is 145 behind / 1 ahead**, and its parent is already
an ancestor of `origin/dev`. §2's claim that the mock-draft work "has never been
merged to `dev`" is **wrong** — all of it is on `dev`, and the one commit
(`19fa86e`, A1b/A1c) is already there in substance. **So §2's explanation for the
`B4` / `REG-pool` / `REG-render` reds is not the real one.** They need a
diagnosis, not that story.

**NFL fantasy log** — `sacks_taken`, `fum_lost` and Misc TD are stored and
rendered, all from `stats_player_week_2025.parquet` already on disk. `pt_return_tds`
is excluded on purpose: nflverse punting namespace, meaning punt-return TDs
*allowed*, all 15 nonzero 2025 rows punters. aDOT/Separation moved out of the
overlay to the player detail. The sideways scroll was `max-w-[520px]`, not the
column list.

## 7c. 2026-08-03 — MLB attributed, and the three "unmerged branch" reds diagnosed

**§2's explanation for `B4` / `REG-pool` / `REG-render` was wrong, and so was §7b's
correction of it.** None of the three had anything to do with a branch. All three
were gates whose *surface* had drifted away from the behaviour they assert, plus one
real regression a gate was correctly reporting.

- **`B4` → PASS.** `5f0e08c` split the 1,053-line `DraftRoom.tsx` into the shell plus
  PlayersTab/columns/RostersTab and moved every `games_played/team_games` fraction out
  of it. B4 still named DraftRoom (renders no fraction) and did **not** name
  `columns.tsx` or `RostersTab.tsx`, which render two of the four — either could have
  hardcoded 17 without moving the gate's number. Repointed at the four surfaces that
  render it: `columns.tsx:189`, `RostersTab.tsx:98`, `ResultsScreen.tsx:232`,
  `PoolList.tsx:324` via `lib/mockDraft/api.ts:100`. All four already derive it.
- **`REG-pool` → PASS (4507).** It was **unsatisfiable, not red**: `len==11515` AND six
  per-position counts summing to 4,506, so 7,009 players had to sit in positions it
  never named. `9895508` (08-01 09:16) constrained the query to `_DRAFT_POSITIONS` and
  the pool went 11,515 → 4,507; from that minute no state of the world satisfied both
  halves. **A total that contradicts its own breakdown is two expectations.** Rewritten
  as: no position outside the six, `len == sum(counts)`, `DEF == 32`, and a 3% band on
  the four that move with roster churn.
- **`REG-render` → still red, down to three sub-failures from five, and they are one
  real regression.** `6ee27fc` ("restore 2026 projections") replaced **Exp PPR/G** with
  the Proj column on both mock-draft surfaces and left `ExpectedPts` and
  `EXPECTED_PTS_HEADER` exported from `columns.tsx` with **zero callers**. The data is
  fine — the pool serves `xfp_per_game` for 579 players (Bijan 19.3). So the gate's
  "the boundary is nulling it again" is a misdiagnosis: no column found means 0 rows to
  inspect. **Whether Exp PPR/G returns next to Proj is a product call — do not edit the
  gate to agree with the removal.** The camp-tab half was pure ordinal rot: `5611af5`
  dropped `FB` and reordered K ahead of D/ST (9 pills → 8), and the position column
  moved into the Player cell's `TEAM · POS · rank` subtitle, so `nth(7)` and
  `td:nth-child(3)` both pointed at the wrong thing. Now asserts the pill **set** and
  the **row count**, no ordinals.

**MLB is attributed.** `ingest_team_results.py` wrote a nine-column INSERT and left
`season`/`status`/`source`/`run_id` NULL on every row it ever produced. **The season was
never missing from the source** — ESPN publishes `season.year` and `seasonType.id` on
every event and both were read into memory and dropped. Now through
`season_keys.normalize_season` (not `game_date[:4]`, right for baseball and wrong for
two other leagues) and `game_types` with a mapping measured 2026-08-03: MLB publishes
**1 Spring Training / 2 Regular / 3 Postseason / 4 Off**, no fifth phase, and files the
All-Star Game **outside** type 2 — hence the schedule document's separate
`allstarsgame` key. **No `_COMPETITION_PHASE` entry belongs to baseball**; one added by
analogy with NBA would be wrong.

Two more findings:

1. **One game held one team.** `401816347` ARI @ CLE 2026-08-01 existed for ARI, not
   CLE. Structural: the loop asks each team for its own schedule, `_get` caches 600s,
   thirty fetches are minutes apart, so a game ending mid-run lands from one side only.
   Each event now writes **both competitors** off the one document naming both.
   **Any per-team ingest that writes one side has this bug.**
2. **Nothing was filtering spring training** — ESPN publishes 451 type-1 events for
   2026 and we got none only because the endpoint chose not to return them that day.

Re-run: **3,364 rows / 1,682 games / 0 one-sided / 0 missing season or source**, and the
ingest reconciles both counts before reporting success.

**Then the evidence table turned out to have no provenance of its own.**
`stamp_team_result_source` reads `team_game_stats.run_id` to attribute
`team_game_results`, and never noticed `team_game_stats.source` was NULL on all 5,646
rows — hidden behind MLB's 3,305 the whole time. Stamped 5,630 from each row's own
run_id (no new inference). **`COV-source`: 6,776 rows → 1,130**, all of which have no
recorded evidence to attribute them from (MLB's 16 stats rows, NFL's 1,114 results).
`backfill_team_parity` already writes `source`, so no boundary fix was needed there.

**Note for any new league:** `team_game_results` has **no `game_type` column** — the
phase is filtered at ingest and not stored. Adding one would make every existing NBA /
NHL / NFL row a fresh NULL block, so it is deliberately deferred, not overlooked.

## 8. Next

1. ~~**NHL `game_type`**~~ **DONE, later on 2026-08-02.** `backend/game_types.py` is the
   boundary; `ingest_nhl_logs.py` reads `gameTypeId` back off the envelope rather than
   taking it from its own URL. All 48,017 rows `REG` over 1312 games, **and the 82
   postseason games it had never requested are now in** (3,126 rows, 2026-04-18..06-14,
   verified against the NHL's published season window). **`nhl 2026 -> complete`**, live on
   `/api/coverage`. New gate `COV-gametype`, now red for **nba 2026 only**. See
   `docs/DATA-COVERAGE-CONTRACT.md` §6.
2. ~~**NBA game_type**~~ **DONE, later on 2026-08-02 — see §7b.** `nba 2026 ->
   complete`. The gap was 216 games, not 121, and one row set belonged to a
   game that was never played.
3. ~~**MLB `team_game_results.season`**~~ **DONE, 2026-08-03 — see §7c.** `COV-source`
   is down to 1,130 rows from 6,776. What remains is **NFL `team_game_results` 2024 +
   2026 (1,114 rows)** and **MLB `team_game_stats` (16)**, neither of which carries a
   run_id to attribute it from. `COV-source` cannot go green by stamping; it needs
   those rows re-ingested under a recorded run, or it stays red honestly.
4. **NCAAF** — `TASK-league-ncaaf.md`, unblocked now that league-0 is green.
   Its ingest must filter `completed` and stamp `game_type` at the boundary; both
   are one-liners now that `espn_client.games()` publishes them. **And it must write
   both sides of every game** — see §7c finding 1.
5. ~~**`B4` / `REG-pool` / `REG-render`**~~ **DIAGNOSED, 2026-08-03 — see §7c.** B4 and
   REG-pool are green. **REG-render is red on one open product question: does
   `Exp PPR/G` come back next to `Proj`?** `6ee27fc` replaced it and left
   `columns.tsx`'s `ExpectedPts`/`EXPECTED_PTS_HEADER` exported with no callers, while
   that file's own comment argues opportunity and outcome "only mean something
   together, which is why both ship on every mock-draft surface".
6. ~~**The NFL fantasy game log gets ESPN's segmented tabs**~~ **DONE, 2026-08-03**
   (`TASK-reasonix-gamelog-tabs.md`, reasonix, 3 commits). Anchor `Wk|Opp|PPR`, ≤5 stat
   fields per tab, `max-w-[520px]` restored and 08-02's widening reverted. Tabs:
   QB `Passing|Rushing|Misc|Usage`, RB/WR/TE `…|Misc|Usage`, PK and DEF a single tab
   with no strip (PK `anchor: null`, DEF `anchor: fantasy_pts`). The `Misc` band came
   **off** `pages/player/[id].tsx` — written for the fantasy log, and ESPN's player
   game log does not carry it. `sacks_taken` stays in Passing; ESPN's has a SACK column.
   **The tab is `Misc`, not `Misc TD`** — ESPN's BLK/INT/FUM are *touchdowns* off
   blocks/picks/fumble returns; ours are a lost fumble and a return TD.
7. **`OVL-width` is the new gate and it is RED on one thing:** the Overview tab's
   **SEASON STATS table is 10 columns / 560px**, which is 254px past a phone and 92px
   past the desktop card — **and Overview is the tab that opens by default.** The
   scroll in the brief was never only the game log. A single season row, so tabs are
   the wrong instrument; **this needs a product decision, do not relax the gate.**
   The game log itself measures 308px in 308px and 470px in 470px across all four
   tabs at both widths — exact, not merely under.
8. **Nothing is pushed.** 17 commits on `dev`.
