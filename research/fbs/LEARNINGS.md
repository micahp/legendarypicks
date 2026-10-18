# FBS learnings

Append-only. One entry per thing we learned the hard way, with the evidence that proves it.
If an entry is later overturned, do not delete it — add a new entry that says so and links back.

Format:

```
## YYYY-MM-DD — one-line headline
**Learned:** what is now known.
**Evidence:** artifact, commit, or measured number.
**Consequence:** what we stop or start doing because of it.
```

Rules:
- A learning needs evidence. "It seems like" is not an entry.
- A null result is an entry. Knowing what does not work is the point.
- Numbers carry their population and sample size.
- Write it when you learn it, not at the end.

---

## 2026-10-18 — Elo warm-up depth is not what separates us from published Basic Elo
**Learned:** Holding G2 and its hyperparameters fixed and varying only the warm-up start
(2022 → 2018 → 2014 → 2010 → 2004) moves Brier from 0.2133 to 0.2103, a paired
Δ of −0.0030 [−0.0041, −0.0018] on the same 2,398 games. It flattens at 13 seasons and closes
only 18.9% of the gap to published Basic Elo (0.1976), leaving 0.01271.
**Evidence:** `RESULT-FBS-WARMUP-ABLATION-20261018.md`, commit `4f20e1fa`, five arm ledgers,
arm A reproduces Phase 1 G2 at 0.213269 exactly.
**Consequence:** five warm-up seasons is the right depth. Do not spend more effort on archive
history as a route to the baseline — the remaining gap is the model, the features, or the
population. Any future "we need more data" argument has to beat this result first.

## 2026-10-18 — A margin-aware rating does not beat plain Elo
**Learned:** G3 (margin-adjusted strength) scored 0.2155 against G2's 0.2133. Paired difference
+0.0023 with a 95% interval of [−0.0023, +0.0065] — spans zero.
**Evidence:** `RESULT-FBS-GAME-WINNERS-20261018.md`, commit `4a59cb6e`.
**Consequence:** keep G0–G2 as references. Do not re-run G3 as if it were untested, and do not
add team-stat inputs on the assumption that margin information must help.

## 2026-10-18 — Most of the published benchmark ladder is not comparable to ours
There are three distinct classes and mixing them produces false conclusions:
1. **Our market-blind baselines** — G0–G3, results only. **G2 is our chronological Elo and is
   not Glicko-2**; Glicko-2 is an unrelated published comparator at 0.1890.
2. **Published market-blind ratings** — Colley 0.2070, Basic Elo 0.1976 (**the only fair peer
   for G2**), Glicko-2 0.1890, Massey 0.1847, Margin Elo 0.1820, Simple ACR 0.1773.
3. **Market-derived** — the spread-implied line 0.1714 *is the market*, a ceiling not a rival;
   Blitzcast's 0.1813 **takes spread and market probability as input features**, so it largely
   encodes the market and cannot be compared to a results-only model as an equal.
**Evidence:** `BASELINE-DISTINCTIONS.md`; the brief's own warning about Blitzcast.
**Consequence:** every table names the class in the row, not a footnote. Never present a model
that ingests odds as evidence of independent predictive skill.

## 2026-10-18 — The betting release has no moneyline and no timestamp, in any year
**Learned:** `espn_cfb_betting` publishes 2004–2026, and every file checked (2014, 2019, 2025,
2026) carries `game_spread, over_under, home_favorite, home_team_spread,
game_spread_available, odds_source` — no two-sided moneyline and no quote timestamp.
**Evidence:** direct parquet schema inspection, 2026-10-18.
**Consequence:** the market benchmark can only ever be **spread-derived**, calibrated on prior
seasons and labelled as spread-derived. It will never give a de-vigged moneyline comparison.
Do not keep re-checking older years hoping the schema differs.

## 2026-10-18 — Prior-play form beats Elo, from pre-snap state only
**Learned:** Increment (b) — EPA, success rate, explosiveness and tempo recomputed from pre-snap
fields, fitted only on seasons strictly earlier than the target — beat G2 on walk-forward
2023–25 and was adopted.
**Evidence:** commit `886ffdf4`, `PHASE3-LADDER-20261018.md` pre-registration in `d7a197c1`.
**Consequence:** this is the first feature family that earned its place. Publisher EPA and wpa
stay banned — an allow-list guard and a BANNED regex enforce it.

## 2026-10-18 — Id type mismatches produce silent empty joins, and they bite twice
**Learned:** `cfb_schedules.game_id` is int64 while `ncaa_mfb_pbp.espn_game_id` is a string, so a
raw set intersection is empty and a coverage table reads zero without erroring. The same class of
bug hit the FBS feature build at the home/away join.
**Evidence:** caught mid-flight in `audit_fbs_game_coverage.py` and `reconcile_fbs_archive.py`;
previously bit the prop-join work.
**Consequence:** cast every id side to `str` before joining, and **assert a non-zero join count**
as a test. A zero should fail loudly, never render as a coverage number.

## 2026-10-18 — `season_type` is a string, so `!= 2` is a no-op
**Learned:** `cfb_schedules.season_type` holds `"regular"` / `"postseason"`, not an integer, so
the original `!= 2` filter admitted postseason games into a "regular season" population.
**Evidence:** fixed in the Phase 2 coverage audit, commit `aa6bd378`.
**Consequence:** inspect the dtype before filtering a categorical. Re-check any population count
produced before this fix.

## 2026-10-18 — Publisher-derived columns leak, and are not observations
**Learned:** `cfb_paper_index_games.paper_share` is fitted on who won. Weekly snapshots with
`through_week == W` include week W. `rolling_windows_2026` has one `as_of_date` of 2026-10-15,
an end-of-season snapshot that leaks in a mid-season backtest.
**Evidence:** Phase 2 leakage register, `AUDIT-FBS-ARCHIVE-20261018.md`.
**Consequence:** `paper_share` is banned from any pregame feature. To forecast week W use a
verified `W-1` snapshot. Keep publisher-scored features in a separate class from raw
observations, and check `as_of` against kickoff for every table that has one.

## 2026-10-18 — Prefix filters silently drop assets
**Learned:** A release-prefix filter excluded a 1,100 MB cfbfastR file with no error; separately,
multi-season files were labelled as 2025.
**Evidence:** both self-caught during Phase 2, recorded in `AUDIT-FBS-ARCHIVE-20261018.md`.
**Consequence:** reconcile downloaded bytes against the release asset list and fail on a
shortfall. Never infer a file's season from its name.

## 2026-10-18 — Day-block bootstrap makes a gate anti-conservative
**Learned:** The Phase 3 pre-registration specified UTC **calendar-week** blocks. The first
implementation grouped by `utc_date`, which understates dependence between games and inflates
significance for the one-sided gates.
**Evidence:** caught before adoption; the week-block re-run is what was adopted at `886ffdf4`.
**Consequence:** block on the pre-registered unit. If the harness and the ladder disagree, the
ladder wins and the run is redone — an interim number is not a result.

## 2026-10-18 — Two agents on one job looks like progress and is not
**Learned:** codex began Phase 2 archive work while hermes was already downloading the same
archive, after a manager dispatched Phase 2 to both. Nothing told the first agent to stop.
**Evidence:** `fbs_archive_phase2.py` and `research/fbs/archive/` appeared in
`/root/lp-fbs-audit` while hermes held `/root/lp-fbs-archive`.
**Consequence:** one owner per workstream, stated explicitly, and a reassignment includes an
explicit stop for the agent being moved. A reset does not fix this class of drift.

## 2026-10-18 — Finished work sits unpushed and therefore invisible
**Learned:** `feat/fbs-archive` was four commits ahead of origin and the tennis branch did not
exist on origin at all, while both were described as done.
**Evidence:** `git ls-remote` vs local tips, 2026-10-18.
**Consequence:** "done" means committed **and** pushed to a named branch. Report the branch, the
SHA and the push state every time.
