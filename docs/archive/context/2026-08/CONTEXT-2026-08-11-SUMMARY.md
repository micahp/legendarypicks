# 2026-08-11 — day summary

One day, three working sessions, one bug shape. This is the index; the detail stays
in the handoffs and they supersede this file where they disagree.

| pass | file | covers |
|---|---|---|
| 1 | `CONTEXT-2026-08-11-HANDOFF.md` | props audit, market keys, recaps, pregame context, release block |
| 2 | `CONTEXT-2026-08-11-HANDOFF-2.md` §1–3, §5–7 | MLB identity, dedupe, prop_games relink |
| 3 | `CONTEXT-2026-08-11-HANDOFF-2.md` §4a | finality gate closed live, postponed games, gamePk |
| 4 | `CONTEXT-2026-08-11-HANDOFF-2.md` §4b | the whole §5 defect list worked through |

---

## 1. The finding the whole day reduces to

**Every defect found today was one shape: an ambiguous key used where an exact key
was published on the same object.** Not a family of unrelated bugs — one habit,
repeated, in eleven places.

| ambiguous key | exact key, already published | measured |
|---|---|---|
| `date + teams` to link a game | `start_time` on the same row | 89 of 316 rows on the wrong game |
| `date±1 + teams` for a gamePk | `gameDate` on the same object | resolved an **unplayed** game; 7,827 props graded 0.0 |
| display name into an abbrev dict | ESPN `competitor.homeAway` | `final_home` NULL on every gated game |
| `state == "post"` for finality | `status.type.completed` | 11 postponed games, 4,078 grades on games never played |
| surname substring in a box score | `athlete.id` in the same object | 1,568 players keyed on `"jr."` |
| `(date, home, away)` for a final | the gamePk | 4 doubleheader groups sharing one score |
| label-set intersection for a stat group | a label only that group has | batting ∩ pitching = {BB,H,HR,K,R} |
| URL with the query stripped | the whole URL | 65 news items onto 3 keys |
| `round(SLG × AB)` for total bases | MLB's `totalBases` | a season rate × one game's at-bats |
| a same-named person's `mlbam_id` | the box score's own id | 3 rows, one debuted **1945** |
| our own name-keyed `players` join | `player_id` | one nameless row holding 3,729 props |

**A wrong key never raises. It misses, or it returns a plausible wrong row.** Nothing
was in the logs, no test was red, and the pages rendered. What made it visible was
Micah opening `/game/mlb/401816477` and seeing no props.

**And a wrong key alone is only half the damage.** It became *confident wrong
answers* rather than missing ones because a second rule filled the hole: a missing
stat graded as `0.0`. Every prop is over/under a line, so a zero does not fail — it
grades, and the UNDER cashes. Look for the amplifier whenever you find the key.

---

## 2. What is now true on dev

- **MLB prop grading matches the official box score.** The last two disagreements were
  a definitional gap in Statcast, not a defect (pass 1 §1).
- **Identity is clean.** 117 duplicate MLB player groups → 0; three rows holding a
  same-named person's `mlbam_id` repaired; **4,242 props that could never grade now
  grade**. 36 team assignments refreshed from the publisher; a re-run reports 0
  disagreements.
- **Nothing settles until the publisher says `completed`.** Postponed games are
  refused; a draw now settles; 74 real finals written where the column had been NULL.
- **The gamePk comes from first pitch, Final only**, and fails closed when ambiguous.
- **`start_time` backfilled for 251 rows** from ESPN's scoreboard — a copy, validated
  531/531 against rows that already had one before anything was written.
- **Every graded prop sits on a game with a recorded final.** 0 all-zero games, 0
  exact-duplicate props, `quick_check: ok`.
- **Suite: 1,142 passing, 0 failing.** It began the day with 8 red, 7 of which were a
  `test_news` import-order dependency old enough that the red line had stopped meaning
  anything.

Re-graded across the day: 614 games (pass 1), then 34,001 props over 299 games
(pass 4). Same-ruler check against the pre-run backup: **0 games lost all their
grades**; 560,788 → 560,018 graded, the difference being props the stricter void
rules now refuse to invent.

---

## 3. What is still open

0. **17 commits sit on `dev`, unpushed** (`dac9fbf..ae9878f`), and the working tree
   carries four modified tracked files (`backend/audit_league_stats.py`,
   `backend/data/esports_team_logos.json`, `backend/data/identity-consolidations.jsonl`,
   `docs/LEAGUE-STAT-GAPS.md`) plus ~15 untracked `TASK-*.md`/`RESULT-*.md` specs. Every
   fix below exists only in this local branch — see `feedback_dev_fix_prod_never_ran`.
1. **Prod has none of it.** ~600k props carry every defect above, and prod's news
   schema is what blocks the release (pass 1 §5) — 12 SCHEMA/SEASONS differences, none
   of them props. The version line has also forked; `v0.7.9`/`v0.7.10` were cut on a
   branch that is not an ancestor of dev.
2. **117 prop_games rows share 56 ESPN event ids** (8,774 props), every one with a
   blank `start_time`. Deliberately skipped by the backfill: copying a time through a
   wrong link launders a bad link into an exact-looking key. No published
   discriminator exists for them. 28 more rows have no ESPN link at all.
3. **3,713 props on player 28987**, a nameless placeholder row across 125 games, all
   `total_hits,_runs_and_errors` — a GAME total, not a player prop. None grade. This
   is a product decision, not a repair, and the ingest re-mints them every run.
4. **`total_pitcher_walks` has no grading rule** (pass 1 §6.5).
5. **Test rows in `prop_games`** ("Test Home"/"Test Away", ids 116–117).
6. **Design**: three artifacts published for review; the app still ships the old chip
   layout (pass 1 §7).

---

## 4. Process notes — what actually cost time today

**Load the project skill before writing code in its domain.** `ls .claude/skills/`.
Two anti-patterns shipped in one day — `honest-data-ui` and `espn-request-budget` —
both times having read only the memory file, which is not the skill.

**ESPN's limit is a request COUNT per host, not a rate.** Pacing buys nothing; a
retry ladder spends more of the budget to rediscover it is gone. The lever that
worked: one scoreboard request per DATE (55) instead of one per event (279).

**A 403 is a fact about one host at one moment.** Probe it; do not narrate a wait.

**Same ruler on both sides, or it is not a before/after.** Numbers I stated today that
were wrong, all from a ruler mismatch: "85 of 286 mislinked" (really 89 of 316), "0
corrected" (29 swallowed failures), "14 duplicate mlbam_ids" (really 117), "715,945
duplicate props" (props are odds SNAPSHOTS — the real figure was 16), and "0 event-id
collisions" (117 rows; the relink had only ruled on rows that already had the exact
key).

**A fix can carry its own defect, and the suite will not tell you.** `settle_game`'s
row query did not SELECT `start_time`, so the newly fail-closed resolver wrote nothing
for **248 games**. Diffing against the backup caught it; 1,100 passing tests did not.
The follow-up pin tests the query itself, not just the call.

**Two publishers, two vocabularies — including time.** Our `start_time` is ESPN's and
the gamePk candidates are MLB's, and they disagree by up to 35 minutes on a revised
first pitch. A 15-minute match window silently settled nothing for those games.

**Check for prior art before writing the second one.** A dedupe script already
existed, tracked, with better collision handling than the one I wrote.
