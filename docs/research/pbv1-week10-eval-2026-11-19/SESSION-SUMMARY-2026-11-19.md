# Session summary, 2026-11-19: PBV1 Week 10 audit

Branch: `research/pbv1-pbp-fully-enabled-2026-11-18` (worktree `/root/lp-pbv1-pbp`). Latest pushed commit: `79ba4bfc`. Nothing merged to dev.

## What is pushed

| Commit | Content |
|---|---|
| `da42cca9` | Week 10 full-slate PBV1 evaluation (14 games, 3 arms, 20 seeds). Unchanged. |
| `48be82a7`, `e69fecc7` | RNG draw diagnostic (BUF at NYJ, seeds 300001 to 300003). |
| `9ff4bfce` | Audit rerun: choice harness, both runners, determinism check. |
| `6867f734` | Allocation audit (`audit/AUDIT.md`, `audit_analysis.py`, `analysis.json`). |
| `7e1ce326` | Follow-up: unlogged carriers and high-volume starters. |
| `79ba4bfc` | Corrected denominator (play-by-play), on-field decomposition, strict availability check. |

Not committed yet: `SESSION-SUMMARY-2026-11-19.md` (this file), `lead_rb_check.py`, `rb_slot_11.py`, `rb_stints.py`, `check_it.py` (scratchpad and fast host only).

## Audit rerun

- Arms B-field and C-field-pbv1, 14 games, 28 of 28 outputs complete. No job failed.
- Box scores are byte-identical to the original 20-seed runs (28 of 28).
- Records (586 MB) stay on the fast host at `/root/tnf-batch/audit/`. Not in git.
- `DONE_REST` marker written. The first runner's parent was stopped after HOU_CLE started. HOU_CLE finished, but its log line is missing from `run.log`.

## Main audit findings

1. **About a quarter of simulated carries (22 to 27%) go to players with no log row** in the real game. Only Achane's case is confirmed. The pregame snapshot has no availability status. The availability adapter only removes players with verified inactive status or an Out or Doubtful designation.
2. **Field arms cut volume for high-volume runners.** Signed error for the 29 player-games: -68 (control), -197 (field), -182 (PBV1 coupled).
3. **Share error among players who played falls about 7%** in both field arms. Once no-log-row players are included, the gain is offset.
4. **Scores:** paired margin differences are small, and all intervals include zero.
5. **Lineup eligibility:** zero violations per play (35,764 checked in B, 35,695 in C).
6. **Target gap:** receiver picks exceed box targets by exactly the sacks plus lost fumbles on those plays.

## Follow-up (corrected)

- **Denominator fixed.** Team offensive plays come from `nfl_pbp` (run, pass, no-play, kneel, spike). `team_game_stats` has no Week 10 rows. Simulated plays match the box score exactly for B (mean gap 0.0).
- **Earlier "relative rate" claim withdrawn.** It used the wrong denominator.
- **Six named starters** (one game each): the main gap is on-field rate. Carries per on-field play do not fall. Across all 29 high-volume player-games, on-field rate is 0.58 actual, 0.34 in B, 0.34 in C.
- **Availability (strict rule):** an injury article in the 7 days before the game's cutoff, naming the player, with an out status as a whole word. Verified: 0.25 carries (B), 0.15 (C). Not verified: 39.3 (B), 36.7 (C). The injury table was ingested 2026-11-17, after every cutoff, so it cannot date designations.
- **Sam Darnold (SEA, about 5 carries in B) needs a manual read.** Articles from 11-09 and 11-10 say Drew Lock started for an injured Darnold. The rule does not match "injured."

## Lead RB checks (today, after the paste)

- **Run share:** my first comparison (42.3% actual vs about 45% sim) used different definitions. Same definition: actual 44.9%, control 45.1%, field 45.4%, PBV1 45.3%. No run suppression. Corrected.
- **Lead RB on-field rate** (same 28 team-games): actual 64%, B 36%, C 37%.
- **By grouping:** in 11 personnel (60% to 65% of plays), the lead RB holds the single RB slot 34% (B) and 36% (C). In 21 and 22, about 60%.
- **Stints:** the RB holder changes on 23% of consecutive plays with the same grouping, and 39% to 41% when the grouping changes. Average stint is about 3 plays, for any back and for the lead.
- **Mechanism:** turnover comes mainly from the leave draw in `advance()` (`scripts/nfl_sequence/participation_field.py`). The bench draw decides who enters, weighted by each back's on-field rate for that team and grouping.
- **Not yet known:** whether the leave hazard is too high. The database has no real per-play personnel or stint data.

## Changing the order

- PBV1 already sets grouping before the call (arm C). Its lead RB on-field rate (0.37) is about the same as B (0.36). Scores did not move.
- Reordering alone would not change who stays on the field. The fix is in the leave step.
- Run calls by personnel are not measured against any actual source.

## Mistakes and corrections today

- Deleted audit output under `/root/tnf-batch/audit/` (BUF_NYJ, CAR_NO, `run.log`). These were rerun outputs I started, not the original Week 10 runs. The original runs (`w10-eval`, `w10-final`) are intact.
- Killed the first runner's parent process while its children kept running. HOU_CLE finished, but its log line is missing.
- Wrongly stated "most" carries go to no-log-row players. Corrected to "about a quarter."
- Team codes: `WSH`/`LAR` need normalizing against `WAS`/`LA`. Missed once, then fixed.
- Relative-rate denominator bug (player snaps summed instead of team plays). Withdrawn.
- Shell and quoting errors on the host (several). No data affected.

## Open items for Micah

1. Sam Darnold: manual read of the 11-09 and 11-10 articles before any "avoidable" label.
2. Whether to commit the lead RB and stint checks to the research folder.
3. Whether to push the summary and checks.
4. Whether to design a test for the leave step. Needs a new arm and a rerun. Not authorized yet. The full slate is untouched.
5. Source for real personnel or stint lengths. None in the database today.

## Where things are

- Research folder: `docs/research/pbv1-week10-eval-2026-11-19/` (REPORT.md, `audit/AUDIT.md`, `audit/code/`, `audit/results/`).
- Fast host: `root@89.117.145.232:/root/tnf-batch/audit/` (choices, `analysis/`, check scripts).
- Frozen DB: `/root/tnf-batch/picks.frozen.db`.
- Scratchpad: `/tmp/claude-0/-root/f1482f88-a0c5-4d01-ae23-395a1a954f9a/scratchpad/audit/`.
