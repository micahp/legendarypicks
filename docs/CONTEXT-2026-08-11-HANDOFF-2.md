# Handoff — 2026-08-11 (part 2, evening)

Supersedes `/root/legendarypicks/docs/CONTEXT-2026-08-11-HANDOFF.md` for anything about MLB identity,
prop_games linking, or settlement. Everything else in that file still stands.

Branch `dev`, 5 commits: `c59e9b6 03d906b 4f405db 2cbd371 dac9fbf`. Not pushed.
**Dev DB only. Prod has none of this.**

---

## 1. What this session was actually about

One bug shape, found in seven places: **matching on an ambiguous key when an
exact key is sitting right there**. Micah opened `/game/mlb/401816477` and it
served no props. The props were on the next game of the series, because the
linker matched `date + teams` while `start_time` sat unused on the same row.

Every item below is that same shape. If you find another, it is probably this.

---

## 2. Done and verified

**MLB player dedupe.** 117 duplicate groups over 234 rows → **0**. players
2,552 → 2,441. props/prop_results/game logs/season stats counts identical before
and after; 11,860 props and 2,064 logs repointed. Independently confirmed by the
pre-existing `dedupe_mlb.py`, which now reports 0.

**Three wrong identities repaired.** `Joe Mack` held mlbam 118086 (debuted
**1945**), `Jacob Wilson` held 607111 (inactive), `Luis Castillo` held 699127
(A-ball outfielder). MLB settlement keys the box score by mlbam_id, so theirs
never matched and 5,441 props settled to `hit=NULL` forever — failing closed, so
no wrong grade and no error, just props that could never grade.
**4,242 now grade with real values, up from 0.**

`repair_mlb_wrong_mlbam_ids.py` decides ONLY from the box score: repair when the
row's own id is absent and exactly one same-name sibling's is present, across
every sampled game. **`Jared Jones` is the control** — same collision list, looks
identical, already correct, left alone. Any resemblance-based rule corrupts him.

**prop_games relink.** 89 rows corrected, then 12 more cleared. Final: **280
correct, 0 event-id collisions, 24 unresolved.** `/game/mlb/401816477` now
resolves to row 747 and serves 20 players / 3,131 props.

---

## 3. Two rulers I got wrong — read before quoting any number

**"85 of 286 mislinked" was wrong.** That came from an ad-hoc query. The
script's own ruler says **89 of 316**. Use the script.

**"total CORRECTED: 0" was not a finding.** The first relink run swallowed every
fetch failure into an empty slate, so 29 blocked requests printed as a clean
zero. It now raises. If you see a suspiciously round zero from any repair
script, check whether it read anything at all before believing it.

**"14 duplicate mlbam_ids" was wrong** — that query only counted groups whose
NAMES differed, missing every identical-name duplicate. Real figure was 117.

---

## 4b. §5 WORKED THROUGH — 2026-08-11 late (part 4)

Commits `fb0927b 7c44f06 ee363bc 989153e ee9c943 e634890 f6fed51 d922754 ae9878f`.
**Suite: 1,142 passing, 0 failing** (was 8 red at the start of the session — 7 of
them a `test_news` import-order dependency that had made the red line meaningless).

| §5 item | state |
|---|---|
| 1 `_fetch_mlb_gamepk` | **fixed** (§4a) + two follow-ups below |
| 2 `regrade_props` finals by (date,home,away) | **fixed** — resolves the gamePk, reads the score off it |
| 3 surname-substring player matching | **fixed** — `athlete.id`, then exact name, else void |
| 4 stat-group by non-empty intersection | **fixed** — identity needs a label the other group lacks |
| 5 missing stat grades 0.0 | **fixed** — three sites, all void now |
| 6 TB = round(SLG x AB) | **deleted** — MLB publishes `totalBases`; ESPN's SLG is season-to-date |
| 7 news `_norm_url` collapse | **fixed** — 65 items onto 3 keys, confirmed on dev before the fix |
| 8 33 staged team corrections | **applied** — 36 rows; re-run reports 0 disagreements |
| 9 26 duplicate prop rows | **16 deleted** on the full key incl. `captured_at`/`odds`; 0 remain |

**Two defects I introduced and fixed in the same pass.** `settle_game`'s row query
did not SELECT `start_time`, so every MLB settle fell back to the ambiguous path
and the now-fail-closed resolver wrote **nothing for 248 games** — caught by
diffing against the backup, not by the suite, and now pinned by a test on the
query itself. And the 15-minute instant-match window was too tight: our
`start_time` is ESPN's and the candidates are MLB's, and they disagree by up to
**35 minutes** on a revised first pitch. Widened to 90 min, which still cannot
reach the other half of a doubleheader.

**start_time backfilled from the publisher.** 251 of 396 blank MLB rows filled from
ESPN's scoreboard — one request per DATE (55 total) rather than per event (279,
against a ~100 host budget). Validated first: 531 of 531 rows that already had one
agree with the publisher to within 60s, 0 disagreements. Script:
`backfill_prop_game_start_time.py`, idempotent, `--verify` reproduces the check.

**Re-graded on dev:** 34,001 props across 299 games. Same-ruler check against
`data/picks.dev.db.pre-regrade-20260811T215107Z.bak`: **0 games lost all their
grades**, total graded 560,788 -> 560,018, the difference being props the stricter
void rules now refuse to invent. Game 550 (2,052 grades, no ESPN link, never gated)
now records final 5-6 and re-grades to 1,996.

### Still open

1. **117 prop_games rows share 56 ESPN event ids** (8,774 props), every one with a
   blank `start_time`. The backfill deliberately skips them: copying a time through
   a wrong link would launder a bad link into an exact-looking key. Resolving them
   needs a discriminator we do not have published — `captured_at` is not usable, the
   window keeps running up to 20 h past first pitch. **28 more rows have no ESPN
   link at all.**
2. **3,713 props sit on player id 28987 — a nameless placeholder row** with no name,
   no mlbam_id, no espn_id, across 125 games. Every one is
   `total_hits,_runs_and_errors`, which is a GAME total, not a player prop. None
   grade (correctly). This is a product decision, not a repair: model it as a game
   market or stop ingesting it. The ingest re-mints them every run.
3. **Prod still has none of this**, and its ~600k props carry every defect above.
4. `data/picks.dev.db` has **test rows** in prop_games ("Test Home"/"Test Away", ids
   116-117).

---

## 4a. CLOSED 2026-08-11 evening (part 3) — read this before §4 and §5

§4 is closed and §5.1 is fixed. Commits `cbacc7a`, `6cf535b` on `dev`, unpushed.

**The finality gate is now verified end-to-end.** 74 real finals written across 99
past linked games; every past, played, linked game carries a final. The 27 still
empty are 16 not yet played and 11 postponed.

**But the first live probe found a second hole in the same gate.** ESPN files a
POSTPONED game as `state="post"` with `completed=false` and `0` on both sides, so
the gate admitted one, and `max(scores)` on 0-0 named a winner. `game_result` now
publishes `completed` and the gate requires it. Dropping the old `winner is None`
clause also lets an honest DRAW settle — MLS 726528 is completed 2-2 and could
never have settled before.

**§5.1 confirmed with damage, then fixed.** Measured an hour after the props timer
ran: `_fetch_mlb_gamepk('2026-08-11', ARI, COL)` returned `825046` — the
**2026-08-12** game, Pre-Game. An unplayed game publishes a lineup with zeroed
batting lines, so every prop graded 0.0: **every UNDER cashed**, 7,827 props over
6 games. It now resolves by `start_time` (15-min tolerance) and refuses any game
whose `abstractGameState` is not Final.

**Repairs applied to dev** (backup `data/picks.dev.db.pre-finality-20260811T212116Z.bak`,
`quick_check: ok`): the 6 games re-settled to 17,393 real grades (~40% genuine
zeros); 4,987 prop_results on the 11 postponed games voided, 4,078 of which held a
real hit/miss for a game never played. **The all-zero-game sweep now returns 0.**

**§2's "0 event-id collisions" is FALSIFIED.** 56 event ids are shared by 117
prop_games rows (8,774 props), all MLB — and all 117 have a **blank start_time**.
The relink reported 0 because it only ruled on rows that had the exact key. 396 of
712 MLB rows have no start_time, every one dated 2026-07-12 or earlier; the ingest
started recording it on 2026-07-17. Backfilling start_time on those 396 is the
next repair, and it is what unblocks the collisions.

**Still open, unchanged:** §5.2 (regrade_props keys finals on date+home+away, and
grades outside the gate — game 550 has 2,052 graded props and no ESPN link at all),
§5.3–5.9. §5.5 (missing stat → 0.0 instead of void) is what converted the wrong
gamePk into wrong grades rather than no grades; it is the amplifier for this whole
class and should be next after the start_time backfill.

**Ruler note:** "26 exact-duplicate prop rows" is right and mine was wrong — props
are odds SNAPSHOTS (`captured_at`, `odds`), so grouping by game/player/market/line/side
returns 715,945 rows by design, not a defect.

**Pre-existing, not caused here:** 7 `test_news.py` failures (`no such table:
news_items`) fail at `dac9fbf` too. Suite is otherwise 1,092 passing.

---

## 4. UNVERIFIED — do this first (§4a closes this)

**The finality gate fix is unit-proven but NOT verified end-to-end.**
`game_result` now reports `home/away/home_score/away_score` from ESPN's own
`homeAway` flag, and `settlement.py` writes those instead of
`scores.get(game["home"])` — a display name against an abbrev-keyed dict, which
could never hit, so `final_home` was written NULL on every game passing the
gate. 6 tests pass, 5 of which fail against the old client.

**I could not confirm it writes a real score, because ESPN 403'd.** To close it:

```bash
cd /root/legendarypicks/backend
# 101 linked prop_games still carry no final — that is the population
sqlite3 data/picks.dev.db "SELECT COUNT(*) FROM prop_games
  WHERE final_home IS NULL AND espn_event_id!='' AND espn_event_id IS NOT NULL"
LP_DB_PATH=data/picks.dev.db venv/bin/python -c "
import espn_client as e; print(e.game_result('mlb','401815805'))"
# expect home/away/home_score/away_score populated, then settle and re-count
```

---

## 5. Still broken — the audit findings, ranked

Full audit is in the session log; these are the live ones.

1. **`_fetch_mlb_gamepk` (settlement.py:305)** — searches day−1/day/day+1 on
   TEAMS ONLY while `prop_games.start_time` sits unused. Same defect as the
   linker, in the function that grades everything. **671 of 712 MLB rows are
   ambiguous; 601,824 settled props ride on them.** That is the population AT
   RISK, not a count of wrong grades — the exact date is tried first, so it only
   misfires on the UTC shift. Its own docstring concedes the doubleheader half.
   MLB publishes `gameDate` and `gameNumber` on the same object. Fix it the way
   the linker was fixed: prefer the instant, fail closed. **Bounding the real
   damage needs MLB Stats API, not ESPN — no ceiling there.**
   Also `except Exception: continue` at line 333 swallows a failed schedule
   fetch into "no game that day".

2. **`regrade_props.py:170`** keys finals on `(date, home, away)` — 4
   doubleheader groups collide, both rows take one final.

3. **Surname-substring player matching (settlement.py:190-197)** — LATENT, not
   live: MLS/UFC resolve to `None` for every market and settle zero props, so
   nothing reaches it today. It goes live the day NBA/NFL/NHL props ship. The
   fallback key for "Michael Porter Jr." is literally `"jr."`, matching the
   first suffixed athlete on the team. 1,568 players have a suffix as their
   match token; NFL has 2,619 same-team surname groups. ESPN publishes
   `athlete.id` in the same object.

4. **Stat-group identity by non-empty intersection (settlement.py:183-186)** —
   `batting ∩ pitching = {BB, H, HR, K, R}`, so a pitching group satisfies the
   "batting" test. Dead for MLB today (the MLB branch returns first), but loaded.

5. **Missing stat grades as 0.0, not void (settlement.py:230)** — "couldn't find
   it" and "genuinely zero" are the same value, so the UNDER cashes.

6. **`TB` derived as `round(SLG × AB)` (settlement.py:207)** — a derivation where
   the value is published. I suspect those AVG/OBP/SLG labels are season-to-date,
   which would make it a season rate times a game count. **UNVERIFIED** — I did
   not confirm it, and it is dead for MLB.

7. **News receipts collapse ESPN URLs.** `_norm_url` strips the query, but ESPN
   recap/preview/clip URLs carry identity ONLY there. **65 news_items collapse
   onto 3 keys** (35 previews, 21 recaps, 9 clips). `by_norm` keeps whichever
   landed last, so a near-miss cite can attach another game's recap as a receipt.

8. **33 staged team corrections**, unapplied, in `refresh_mlb_player_teams.py`.
   Dry-run first and read the skip list — `Joe Mack id=12` would have been set
   MIA→ATL because statsapi maps a 1945 player's club to the modern franchise.
   Gated on `active` now, skips 3.

9. **26 exact-duplicate prop rows** — pre-existing, NOT caused by the dedupe (26
   before, 26 after). Mostly game 422, plus a TEAM total ("total hits, runs and
   errors", line 27.5) misfiled as a player prop with a null player.

---

## 6. Process notes — I broke these rules today, twice each

**Load the project skill BEFORE writing code in its domain.** `ls
.claude/skills/`. I shipped the `honest-data-ui` anti-pattern and the
`espn-request-budget` anti-pattern in one day, both times having read only the
memory file. Micah had to ask "did you read the skill" to stop the second.

**ESPN's limit is a request COUNT per host (~100), not a rate.** Pacing does not
buy budget; a retry ladder spends more of it to rediscover it is gone. I wrote
both into a repair script. Also: **I declared the request count against the
wrong host** — "29 requests" was to localhost, and each cold one fans out to
ESPN behind the backend. Count the host that has the limit.

**A 403 is a fact about one host at one moment — probe, do not narrate a wait.**
I twice reported "waiting for ESPN's cooldown" as if it were a blocker. Micah:
"here you go talking about a cooldown again... we don't have to use ESPN."

**Walk published-first rung 1 FIRST: is the value already a column in our DB?**
I never checked before treating ESPN as the only source. (It turned out there is
no local MLB schedule table, so ESPN was needed — but I should have known that
before, not after.)

**Check for prior art.** I wrote a second dedupe script when `dedupe_mlb.py`
already existed, tracked, with better `player_stats` collision handling. Deleted
mine; the genuinely new part became `refresh_mlb_player_teams.py`.

---

## 7. Files

New: `repair_mlb_wrong_mlbam_ids.py` + test, `refresh_mlb_player_teams.py`,
`test_mlb_identity_invariants.py`, `test_game_result_home_away.py`.
Changed: `relink_prop_games_by_start_time.py`, `espn_client.py`, `settlement.py`,
`routers/games.py`.

Backups (all `quick_check: ok`): `picks.dev.db.pre-dedupe-20260811T201343Z.bak`,
`.pre-idrepair-20260811T203054Z.bak`, `.pre-relink-20260811T203321Z.bak`,
`.pre-relink-20260811T203500Z.bak`.

Slate cache (29 MLB slates, reuse at zero request cost):
`/tmp/claude-0/-root/a257cda4-136d-4df1-b109-f3f25cd2ac90/scratchpad/mlb_slates.json`

**Release is still BLOCKED** — everything in §5 is outstanding, prod has none of
these fixes, and prod's ~600k props still carry the original defect.
