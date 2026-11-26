# LP handoff — 2026-07-27 (supersedes CONTEXT-2026-07-26-HANDOFF-5.md)

Read this first. Section 0 is a task waiting on a permission gate, not on a decision.

---

## 0. ✅ DONE 2026-07-27 — history rewrite applied and pushed. Do not redo.

Applied `apply_local.py`, then force-pushed. **Verified against the remote, not the push
output:** `git log --remotes --tags --grep='Claude-Session'` = **0**, and a per-branch
loop over every `refs/remotes/origin/*` found none. `origin/dev` = `e48de53`.

Proof the rewrite was content-only: same commit count (584 both), `HEAD^{tree}` identical
before and after (`4ad9454`), `git diff f9eda06 dev` empty, working tree and the 3 dirty
Codex files untouched. 33 branches + 38 tags moved.

**The §0 loose end is closed:** `origin/main` and `origin/mvp-backend-scaffolding` were
checked directly — **0 trailers each**. Nothing left unscrubbed.

All 4 GitHub Releases (v0.3.0, v0.4.0, v0.5.0, v0.6.0) survived and still resolve — they
attach to tag *names*. (v0.6.7 has a tag but no GitHub Release; that predates this work.)

The three NFL commits rode along in the same push and are **no longer unpushed**. Their
SHAs changed: `08430f7 → 4075c2b`, `18e91c8 → 01f6c92`, `f9eda06 → e48de53`. Any older
note referring to the old SHAs means these.

Rollback, if ever needed: `git bundle unbundle` on
`scratchpad/lp-backup-20260726-234721.bundle` (81 original refs). The scratchpad is
session-scoped and will not survive indefinitely.

### The prevention half IS done and tested

The real finding: 83 commits sailed through **three** enforcement layers because
`/root/.config/git/hooks/{commit-msg,post-commit,pre-push}` only matched
`Co-authored-by: Claude`, `Generated with Claude`, `noreply@anthropic.com`.
**`Claude-Session:` matched none of them.** All three now also match `^Claude-Session:`
and `claude\.ai/code/session`. Verified in a throwaway repo: trailer stripped, body
preserved, no false alarm. `.bak` copies sit alongside each hook.

Note the standing conflict: the harness instructions tell each session to append that
trailer; `AGENTS.md:108` forbids AI attribution. The hooks now resolve it silently at
commit time, so just write commits normally.

---

## 1. THE BIG ONE: NFL numbers in prod are wrong, and now we can prove it

### There IS a second source. The docstring said there wasn't.

`ingest_nfl_pbp_logs.py` claimed nflverse's weekly summary 404s for 2025. **Stale.** The
release was renamed `player_stats` → `stats_player`:

```
https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2025.parquet
```

200, both 2024 and 2025. Every pbp-derived number is falsifiable. This killed the premise
of HANDOFF-5 §1, which said 2025 had "no second source" — that was **my error**, written
into a handoff as fact.

### What reconciliation found

The rollup read raw pbp *flags* as if they were *stat definitions*. Against the artifact,
5,377 player-games were wrong in four ways: `att` 514 rows, `targets` 88, `rec_yds` 18,
`rush_yds` 1.

- **`att`**: 432 of 514 explained *exactly* by `sacks_suffered` — pbp sets
  `pass_attempt=1` on sacks. The rest are two-point conversions.
- **`rec_yds`/`rush_yds`**: laterals. The pbp carries `lateral_receiver_player_id` /
  `lateral_receiving_yards`, ignored by the aggregation.

### Fixed in three commits on `dev` (unpushed)

| commit | what |
|---|---|
| `08430f7` | eligibility filter, laterals, `dropbacks`, stale sweep, retention 34→50 cols |
| `18e91c8` | `epa_per_db` divides by `dropbacks`, falls back to `att` for old rows |
| `f9eda06` | corrections after Codex review (see §2) |

**Verification standard to hold to:** reconciled on a *copy* of the dev DB — 12 box fields
+ `pass_epa` all **zero** differences, `dropbacks` zero against `attempts + sacks_suffered`.
Only 2 rows remain, both genuine multi-lateral plays (see §3).

### ⚠ THE CODE IS FIXED. THE DATA IS NOT.

Dev and prod still hold the wrong numbers. Prod is serving v0.6.7 off them right now.
Re-running the ingest is a real data mutation on a live feature — **do not do it
unasked**, and follow Codex's staged plan in §4.

---

## 2. Codex reviewed it and returned NO-GO. It was right about three things.

Verified each myself before acting — do the same with anything below.

1. **`dropbacks` was broken — my own regression, 20 minutes old.** I excluded two-point
   plays from `att` but left them in `dropbacks`. Verified: 82 passer-weeks disagreed.
2. **`pass_epa` summed non-pass plays** — three `no_play` rows and one `field_goal` row
   carry a `passer_player_id`. 3–4 passer-weeks.
3. **The stale sweep was the real danger.** It selected on *season alone*, so
   `--year 2024` would have stripped `pass_yds`/`fpts` from the 5,340 rows owned by
   `ingest_nfl_logs` — the identical destructive write this ingest was fixed for hours
   earlier, reintroduced by my fix for something else. No completeness gate either: a
   truncated download would make most of a season look "no longer produced" and cull it.

Also fair: my commit message claimed "every other field reconciles exactly" when I had
checked 12 box fields and never EPA, dropbacks, or fantasy points. Corrected in place.

### Where Codex was WRONG — do not follow this blindly

It recommended mirroring nflfastR's contract and **excluding two-point plays from EPA.
That makes it worse: 4 disagreements → 78.** Official `passing_epa` *includes* two-point
EPA. The right method is the one that produced every correct filter here: **derive it by
measurement against the artifact, don't reason about what ought to count.**

`f9eda06` fixes all three, sweeps only rows this ingest wrote, and gates on the run
looking complete (refuses loudly above threshold, leaving stale values rather than
destroying good ones).

---

## 3. Known residual — do not "fix" it

Two 2025 rows still differ, both traced to actual plays:
- `00-0034827` wk15, play 1934 — Burden → Moore → Monangai
- `00-0036252` wk18, play 4468 — Downs → Pittman → Leonard

The pbp schema has **one** lateral slot and it holds the *last* player, so the
intermediate one is unrepresentable. nflverse ships `multiple_lateral_yards.rds` for
exactly this — an R serialization this venv cannot read (`rdata`/`rpy2` absent).
Documented in the code with a "do not fudge the lateral sums" note.

---

## 4. Codex's rerun plan (sound — follow it)

1. Fix code first. **Do not run 2024.**
2. Pin one exact pbp artifact + weekly artifact + lateral supplement **with checksums**.
   Same bytes for dev and prod.
3. Run against an online-backup copy of dev. Compare every owned key row-by-row, not
   counts. Require zero unexplained differences.
4. Verify preexisting snap/NGS values are value-equivalent, unrelated tables unchanged,
   second run idempotent.
5. Back up main dev via the SQLite online backup API, quiesce competing writers, apply
   `--year 2025` only, verify the real usage endpoint.
6. Deploy the backward-compatible router **before** changing prod data.
7. Prod: pause writers, backup + integrity-check, record baselines, apply 2025 only,
   rerun the full reference diff and live endpoint checks, resume writers.

---

## 5. Audit result: the destructive pattern is STILL LIVE for NFL 2024

Five ingests still use bare `INSERT OR REPLACE INTO player_game_logs`:
`ingest_nfl_logs`, `ingest_mlb_logs`, `ingest_mlb_pitcher_logs`, `ingest_nba_logs`,
`ingest_nhl_logs`.

**NFL 2024 is a live defect.** `ingest_nfl_logs.py` owns all 5,340 rows of 2024, and
those rows carry snap-count keys on **5,329** and Next Gen keys on **1,253**, written by
other ingests. Re-running it wipes every one. Same bug as `866dbf1`, one season over,
same three-line shape of fix. **This is the next thing to fix**, and it blocks Codex's
2024 rename-migration recommendation.

**MLB — latent, not live.** 0 natural keys currently written by both sources. But
`statcast_pitcher` rows reuse batting key names (`H`, `HR`, `RBI`, `R`) to mean *allowed*,
with no role dimension in the natural key — exactly the collision Micah's own migration
spec warned about. Nothing broken today; the schema just cannot prevent it.

**NBA/NHL** — single writer each. Harmless now, a trap the moment anything enriches them.

---

## 6. Mistakes made this session — written down so they don't repeat

1. **HANDOFF-5 asserted 2025 had no second source.** It has one. I wrote an unverified
   claim into a handoff where the next session would inherit it as fact.
2. **The first history-rewrite filter was wrong.** An `awk` *added* a trailing newline to
   messages that never had one, silently rewriting all 630 commits back to 2025-06-06.
   Caught only because tags predating the first trailer commit moved. The correct filter
   is byte-exact and passes non-trailer messages through untouched
   (`scratchpad/msgfilter.py`).
3. **I verified the rewrite with `--all`**, which includes `refs/original/*`, and briefly
   concluded the rewrite had failed when it had worked. Check `--branches --tags`.
4. **`dropbacks` regression** — fixed one definition and broke a neighbouring one in the
   same commit, then shipped it before reconciling the field.
5. **A test that could not fail.** My first source-scoping test passed even with the
   scoping removed, because a redundant `UPDATE ... AND source=` guard covered for it.
   Mutation testing caught it; it now asserts the row is never *selected*.

---

## 7. State

- `dev` = `e48de53`, **pushed, in sync with origin.** Suite: 241 passed, 4 pre-existing
  failures (`test_league_stats_contract`, 3× `test_nfl_offseason_api`) — unrelated,
  present before this work.
- Prod: **v0.6.7, live**, serving the wrong NFL numbers described in §1.
- Codex's 3 WIP files still uncommitted (`espn_client.py`, `ingest_ufc_fight_stats.py`,
  `ingest_wc_logs.py`) — **it wants to land these itself**. Prod's UFC path depends on
  this dirty tree.
- **Codex is under 10% of its weekly limit.** Budget accordingly.

## 8. Open work, in the order I'd do it

1. ~~Finish §0 (apply + push), verify `origin/main`~~ — **done 2026-07-27.**
2. ~~Push the three NFL commits~~ — **done**, same push.
3. **NEXT: fix the NFL 2024 destructive write (§5)** — same shape as `866dbf1`.
4. Then, and only with Micah's go-ahead, the §4 rerun to correct the actual data.
   **Prod is still serving the wrong NFL numbers — the code fix is pushed, the data is not.**
5. Longer term: the integrity program from HANDOFF-5 §4/§7 — fact contract, raw source
   retention with checksums, constrained migrations, prop-outcome grain, MLB identity
   last. The retention rule this session proved: **retain every column the rollup reads,**
   or the plays cannot falsify the numbers derived from them.
