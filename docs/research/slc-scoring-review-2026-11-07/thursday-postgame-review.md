# Thursday postgame review: JAX 33, BAL 10 (2026-11-05)

| Field | Value |
|---|---|
| Matchup | `2026_09_JAX_BAL`, Week 9, JAX away at BAL (M&T Bank Stadium), Thursday 2026-11-05 |
| Actual result | JAX 33, BAL 10 (no overtime). Margin +23 JAX. Total 43. |
| Simulated arms | v1, v15, v2 "corrected rerun"; 1000 completed seeds per arm (seeds 1–1000) |
| Sim source commit | `9b5a1e43` (five-blocker rerun, 2026-11-05 15:01 CST) |
| Roster/identity | every seed predates the identity fix `2b13edac` (23:28 CST) |
| Actual data | `nfl_pbp` (156 plays), `nfl_team_game_totals`, `player_game_logs`, `player_game_shares`, schedule row |

Purpose: close the loop run → actual game → lesson, along the causal chain (possessions → play calls →
yards/drive endings → scoring → player opportunities), not by comparing final scores alone. Nothing was
re-simulated; every simulated number is a distribution over the 1000 seeds in each arm.

---

## 0. Provenance caveats that limit what these numbers mean

These are required, and they are material:

1. **All three arms are pre-identity-fix.** They were produced from `9b5a1e43` (five-blocker rerun),
   which predates the identity fix `2b13edac` by about 8.5 hours. The identity-fixed rerun exists only for
   V2 (`out-identity/v2` on the fast host) and is not in this bundle. Nothing here tests the identity fix.
2. **Every seed has `valid_full_game = false`** (1000/1000 in all arms). The input snapshot was built as
   `exploratory_replay` with `verified: false`; the manifest's unverified inputs are schedule `observed_at`
   (a loader import time), and away/home depth `snapshot_at` (nflverse artifact dates, not capture times).
   The percentages below are therefore model output on an **unverified input snapshot**, not a validated
   forecast. They describe what the simulator did, not what a verified pregame run would have produced.
3. **No per-play records were retained.** `game.json` `replay_examples` is empty, so starting field position,
   explosive plays, per-drive duration/outcome and drive-level time of possession cannot be compared between
   simulation and actual. This review is limited to box-score aggregates plus what the actual `nfl_pbp` lets
   me reconstruct.
4. **The actual pbp export is incomplete in ways that matter.** `fumble` and `fumble_lost` are blank on all
   156 rows and `penalty`/`penalty_team` are blank on all rows. Two possession changes have no recorded
   ending play: JAX drive 15 ends after 2nd down with no punt/score/turnover flagged, and BAL "drive" 20 is
   a kickoff-only entry (a kickoff-return turnover is consistent with the field position of the next drive,
   but unproven). So actual giveaways are a floor (2 interceptions for BAL, 0 for JAX) and drive-ending or
   turnover totals carry ±1 uncertainty. Team totals, score, carries and targets reconcile exactly to the
   exported team box, so the volume/yardage/scoring comparisons are not affected.
5. **Two exports disagree on status.** The box-score export says `status = incomplete` on all 2000 rows per
   arm, while the seed ledger says `complete_regulation` (956–965) or `complete_overtime` (35–44) for all
   1000 seeds. One of the fields is wrong; the box-score status cannot be used as a legality signal.
6. The original first-pass runs have no raw output files on disk; the arms reviewed here are the corrected
   rerun only.

---

## 1. The actual game

### 1.1 Team box (reconstructed from `nfl_pbp`, 156 plays)

| Stat | BAL (home) | JAX (away) |
|---|---|---|
| Drives / scrimmage plays | 12 / 54 | 12 / 56 |
| Pass attempts (excl. sack) | **19** | **26** |
| Rush attempts (incl. 1 kneel) | 34 | 30 |
| Run share | 64.2% | 53.6% |
| Completions | 11 | 16 |
| Gross passing yards | 57 | 242 |
| Rushing yards | 172 | 77 |
| Total yards | 227 | 319 |
| Sacks taken | 1 | 0 |
| Turnovers (recorded) | 2 INT | 0 |
| Punts | 5 | 3 |
| FG made / attempted | 1 / 1 | 4 / 4 |
| Red-zone trips / scoring drives | 1 / 1 | 5 / 5 |
| Scoring drives (TD or FG) | 2 | 7 |
| Possession (between-snap attribution) | 1845 s (51.2%) | 1755 s (48.8%) |
| Plays per drive | 4.50 | 4.67 |

Scoring: JAX 3 TD (1 pass, 2 rush) + 3 XP + 4 FG = 33; BAL 1 rush TD + 1 XP + 1 FG = 10.
Total: 4 TD and 5 made field goals.

Reconstruction rules (so the numbers are reproducible):
- `pass attempts` = `pass_attempt = 1` rows **excluding** the sack-scored attempt. The pbp has 20 BAL
  `pass_attempt` flags; play 1124 is the one sack, so 19 attempts — **18 by Joe Fagnano and 1 by Derrick
  Henry**, which is the "BAL 19 pass attempts includes a Henry pass" in the brief. Counting the sack as an
  attempt gives 20.
- `plays` = pass attempts + rush attempts + sacks (same convention the simulated box score uses).
- `drives` = distinct `drive` ids per team; red zone = drive minimum `yardline_100 <= 20`.
- `possession` = each interval between consecutive snaps credited to the team that snapped first in it
  (sums to the full 3600 s). The naive first-snap-to-last-snap method gives 1766/1707 = 3473 s and is not
  used because the simulated field's definition is not documented.
- `fumbles` cannot be counted (blank column); turnovers are interceptions only.

### 1.2 What actually decided the game

- BAL never led. JAX led 10–3 after Q1, 17–3 at half, 20–3 after Q3, and 33–10 after a Q4 exchange. BAL's
  only touchdown came after JAX had reached 33.
- BAL trailed from JAX's opening-drive touchdown onward (deficit 4–30 points) and still ran 34 times while
  throwing 19 passes; its passing game produced 57 gross yards (3.0 yards per attempt) with one sack and two
  interceptions. That is a run-first, low-volume script from a team playing from behind.
- JAX's last three scoring drives started at BAL 27, BAL 23 and BAL 32 (from the pbp's starting field
  position), i.e. the JAX scoring was helped by short fields; JAX converted 5 red-zone trips into 3 TD + 2 FG
  and added 2 longer field goals.
- The resulting shape — a near-median total (43) delivered as an asymmetric 33–10 split, with JAX scoring on
  7 of 12 drives and BAL on 2 of 12 — is the thing to test against the simulated distributions.

---

## 2. Causal chain: simulated vs actual

Reading convention for every table in this section and the appendix:
sim cells are **median (mean) [10th–90th percentile] · % of the 1000 seeds ≤ the actual value**.
`%≤` includes ties; a value at 0.0% is at or below every simulated seed. In §2.1–2.4 the sim column is the
**v2 arm** (the primary/current arm); §2.5 and the appendix give all three arms.

### 2.1 Possessions and clock

| | Actual BAL | Sim BAL (v2) | Actual JAX | Sim JAX (v2) |
|---|---|---|---|---|
| Drives | 12 | 10 (10.5) [9–12] · 92.1 | 12 | 10 (10.5) [9–12] · 92.1 |
| Plays | 54 | 66 (66.5) [55–78] · 9.0 | 56 | 68 (67.9) [57–79] · 9.9 |
| Plays per drive | 4.50 | 6.29 (derived from medians) | 4.67 | 6.48 |
| Possession | 1845 s | 1771.5 (1774.5) [1412.8–2123.1] · 59.3 | 1755 s | 1810 (1812.2) [1470.9–2163.2] · 43.3 |

- Both teams had **12 possessions**, at the 91st–92nd percentile of the simulated drive count (median 10).
- Yet both teams ran **fewer scrimmage plays than ~90–93% of simulated seeds** (BAL 54: 6.8–9.0% of seeds at
  or below; JAX 56: 9.9–10.5%). Plays per drive: actual 4.5–4.7 vs simulated 6.3–6.5.
- Time of possession split (51.2/48.8) is unremarkable (56th–58th percentile for BAL's share). The simulated
  `possession_seconds` field itself is suspect: across both teams it sums to 3575 s (median) in regulation,
  i.e. 25 s short of 3600 (see Bugs), so only the split and shape should be compared, not the level.
- Reading: the actual game had **more possessions and shorter drives** than the model produces. Because
  section 2.2 shows the rush volume matched, the shorter drives and lower play count are the clock
  consequence of ~24 fewer pass attempts, not an independent possession-model failure.

### 2.2 Play calls — the dominant divergence

| | Actual BAL | Sim BAL (v2) | Actual JAX | Sim JAX (v2) |
|---|---|---|---|---|
| Pass attempts | **19** | 35 (35.5) [27–45] · **0.3** | **26** | 33 (33.7) [25–43] · 15.9 |
| Rush attempts | 34 | 29 (29.7) [19–41] · 70.7 | 30 | 34 (33.6) [21–46] · 37.9 |
| Run share | 64.2% | 50% [30–60] · 98.0 | 53.6% | 50% [40–60] · 63.8 |
| Game total pass attempts | **45** | 69 (69.3) [59–80] · **0.0** | — | — |
| Game total rush attempts | 64 | 63 (63.3) [57–71] · 60.2 | — | — |
| Game total plays | 110 | 134 (134.5) [126–144] · **0.0** | — | — |

- **Combined pass attempts: 45 actual vs simulated median 69–70.** The simulated minimum is 45/46/47 for
  v1/v15/v2; only 2 of 3000 simulated games reached 45, and none went below the arm minimum. The actual game
  is at or below the edge of the model's play-calling support.
- **Rush attempts were at the median** (64 actual vs median 63). So the ~24 missing plays relative to the
  sim are entirely missing *pass* attempts: the actual game ran a 41.3% pass rate (45/109) against a
  simulated 47–48% run share mean. Actual run share 58.7% is the 98.6th–99.2nd percentile.
- The model is not blind to game state: team pass attempts correlate −0.40 to −0.46 with own margin in all
  three arms (trailing teams throw more; mean pass attempts 38–40 for teams trailing by 9+, 30–32 for teams
  winning big). That response pushed the wrong way on Thursday: BAL trailed from Q1 and ran 34 times.
  The miss is therefore a **range/conditional-shape miss**, not "no game-script logic" — the model's pass
  volume is too high and too narrow to generate a 41%-pass game in any game state.
- Caveat: nothing here establishes that the sim's average pass rate is wrong. Its median (~70 combined
  attempts) is in the range of modern NFL games and Thursday was an extreme run-first game. One game can
  place the actual outside the model's support; it cannot calibrate the model's average.

### 2.3 Yards and drive endings

| | Actual BAL | Sim BAL (v2) | Actual JAX | Sim JAX (v2) |
|---|---|---|---|---|
| Gross passing yards | 57 | 230.5 (232.9) [157–313] · **0.1** | 242 | 248 (250.8) [178.9–329.1] · 46.1 |
| Passing yards / attempt | 3.00 | 6.54 (6.63) [4.93–8.48] · 0.2 | 9.31 | 7.42 (7.57) [5.46–9.84] · 85.1 |
| Rushing yards | 172 | 132 (136.1) [73–201] · 76.1 | 77 | 134 (140.0) [76–212] · 10.9 |
| Total yards | 227 | 371 (369.0) [277.9–458.1] · 1.9 | 319 | 390 (390.8) [296–482.1] · 16.8 |
| Yards / play | 4.24 | 5.54 (5.55) [4.53–6.60] · 4.0 | 5.70 | 5.74 (5.76) [4.69–6.76] · 48.4 |
| Sacks taken | 1 | 1 (1.1) [0–2] · 68.0 | 0 | 0 (0.5) [0–2] · 58.2 |
| Turnovers (recorded) | 2 INT | 1 (0.9) [0–2] · 92.2 | 0 INT | 0 (0.6) [0–2] · 56.2 |
| Turnovers on downs | 1 | 1 (1.0) [0–2] · 77.2 | 0 | 1 (0.9) [0–2] · 37.3 |
| Punts | 5 | 3 (3.5) [1–6] · 88.4 | 3 | 3 (3.2) [1–5] · 58.7 |

- BAL's passing line is outside the simulated support: **57 gross passing yards, 0–1 of 3000 seeds at or
  below**; 3.0 yards per attempt at the 0.1–0.4th percentile. This is a direct consequence of 19 attempts
  and is not separable from the volume miss.
- BAL's rushing line (172 yards, 76th–78th percentile) and JAX's passing line (242 yards, 46th percentile)
  are ordinary; JAX's *efficiency* (9.31 Y/A, 85th percentile) is high but supported.
- BAL's total yards (227) are at the 1st–2nd percentile; JAX's (319) at the 14th–17th. So the yardage gap is
  mostly BAL's low volume, with JAX ordinary in total but efficient.
- Drive endings: BAL ran 5 punts (87th–93rd percentile), JAX 3 (56th–64th), and BAL's 2 INTs are at the 92nd
  percentile — all supported, all ordinary. The missing actual fumble records mean the real turnover total
  is unknown, so turnover differences are not a usable divergence in either direction.
- The pbp records 3 BAL pass attempts with no receiver (throwaways) out of 19; the simulated target totals
  make that impossible (see Bugs), so per-player targets are discussed in 2.5.

### 2.4 Scoring

| | Actual BAL | Sim BAL (v2) | Actual JAX | Sim JAX (v2) |
|---|---|---|---|---|
| Points | **10** | 20 (19.9) [10–31] · 14.9 | **33** | 24 (24.1) [13–35] · 84.9 |
| Touchdowns | 1 | 2 (2.1) [1–4] · 33.6 | 3 | 3 (2.6) [1–4] · 74.7 |
| Scoring drives (TD or made FG) | 2 | 4 (3.9) [2–6] · 16.6% of seeds ≤2 | 7 | 5 (4.5) [3–6] · 7.5% of seeds ≥7 |
| FG made | 1 | 2 (1.8) [0–3] · 43.3 | 4 | 2 (1.9) [0–3] · 98.4 |
| Red-zone trips | 1 | 3 (3.5) [2–5] · 6.1 | 5 | 4 (3.9) [2–6] · 87.8 |
| Red-zone scoring drives | 1 | 3 (2.8) [1–4] · 14.7 | 5 | 3 (3.2) [2–5] · 95.4 |

- **BAL scored 10 (10th–15th percentile by ≤ convention, i.e. lower 10–15%):** driven by 2 scoring drives
  (16.6% of seeds had ≤2) and 1 red-zone trip (6.1% had ≤1), all downstream of 19 pass attempts and 227 yards.
- **JAX scored 33 (85th–87th percentile) with 7 scoring drives (top 5–7%) and 4 made field goals (top
  1.6–1.9%):** the actual JAX scoring was FG-heavy. Five red-zone trips (84th–88th percentile) converted to
  3 TD + 2 FG, plus 2 longer field goals. This is an upper-tail but *supported* outcome (68–89 seeds per arm
  had ≥4 made JAX FGs; JAX's 5 red-zone trips are at the 84th–88th percentile).
- Game composition: actual 4 TD and 5 made FG; simulated median 5 TD and 3–4 made FG. Total points 43 is at
  the 45th–50th percentile — a perfectly ordinary total. The unusual part is the **split**, not the sum.

### 2.5 Where the actual result sits in the simulated distributions

| Quantity | Actual | v1: P(sim ≤ actual) [mean] | v15 | v2 |
|---|---|---|---|---|
| **JAX points** | 33 | **87.2%** [23.5] | 87.3% [23.4] | 84.9% [24.1] |
| **BAL points** | 10 | **9.9%** [21.7] | 14.1% [20.2] | 14.9% [19.9] |
| **Total points** | 43 | **44.9%** [45.2] | 50.0% [43.6] | 49.5% [44.1] |
| **Margin (JAX−BAL)** | +23 | **96.1%** [+1.8] | 95.3% [+3.2] | 95.6% [+4.2] |
| **BAL pass attempts** | 19 | **0.8%** [35.5] | 0.7% [35.7] | 0.3% [35.5] |
| **JAX pass attempts** | 26 | **13.0%** [35.0] | 13.3% [34.3] | 15.9% [33.7] |
| Total game pass attempts | 45 | **0.2%** [70.6] | 0.0% [70.0] | 0.0% [69.3] |
| Total game plays | 110 | **0.0%** [135.3] | 0.0% [134.9] | 0.0% [134.5] |
| Combined run share | 58.7% | **99.2%** [47.0%] | 99.1% [47.0%] | 98.6% [48.0%] |
| BAL gross passing yards | 57 | **0.0%** [242.9] | 0.0% [235.5] | 0.1% [232.9] |
| BAL red-zone trips | 1 | 5.7% [3.6] | 5.7% [3.6] | 6.1% [3.5] |
| JAX FG made | 4 | 98.1% [1.7] | 98.8% [1.7] | 98.4% [1.9] |
| P(JAX win) implied | actual JAX won | 57.4% | 61.5% | 65.7% |

Reading: **the final score sat in a moderate tail, not an extreme one** — the margin (+23) is a 95th–96th
percentile outcome (about 4–5% of seeds had a JAX win of 23 or more) and BAL's 10 points is a lower-10–15%
outcome; the total (43) is dead centre. But **the process metrics are far more extreme than the score**: pass
volume, BAL passing yards and total plays are at or below 0–2 seeds of 1000. The score only stayed in range
because JAX converted short fields and red-zone stalls into 4 field goals — the FG-heavy shape is itself an
upper-tail but supported outcome (top ~2% for JAX FG makes).

Note on direction: the simulator's central lean was **JAX**, not BAL (mean margin +1.8 to +4.2 JAX; P(JAX
win) 57–66%), while the market line in the schedule row was BAL −8.5 with a 40.5 total. The actual went JAX
by 23 at a total of 43, so on this one game the model backed the right side against the market and its total
was closer. That is one observation, not evidence of skill.

---

## 3. Player opportunities

Roster note: the brief lists "BAL (Henry, Hill, Abdullah)". Both the actual box score and the simulated
roster place **Ameer Abdullah on JAX**; BAL's third running back is Rasheen Ali. Abdullah is reported under
JAX below. Two of the 71 actual player-usage rows (source ids `00-0038562` BAL, `00-0037106` JAX) have no
match in the simulated roster, but both recorded zero carries and zero targets, so no usage figure is
affected. No simulated player appears on two teams and no name maps to two ids in the export.

### 3.1 Counts first (this is where the volume miss lands)

| | Actual BAL | Sim BAL (v2) | Actual JAX | Sim JAX (v2) |
|---|---|---|---|---|
| Team carries / targets | 34 / 16 | 29 / 35 | 30 / 26 | 34 / 33 |
| Players with ≥1 carry | 5 | 4.53 mean, 4 median | 4 | 4.53 mean, 4 median |
| Players with ≥1 target | 6 | 8.16 mean, 8 median | 9 | 8.16 mean, 8 median |
| Roster rows in the usage table | 35 (zeros included) | 62 | 36 (zeros included) | 62 |

The count of players who get at least one carry matches well (sim 4–5 vs actual 4–5). The count of players
with a target matches JAX but is high for BAL. Raw per-player target counts are **not evidence about
receiver usage**, because the simulated target total is identically the pass-attempt total (see Bugs): BAL's
sim targets are 35 because it threw 35 times, not because receivers were preferred. Shares are the fair
comparison.

### 3.2 BAL usage, v2 arm (median [10th–90th] · % of seeds with zero · % of seeds ≤ actual)

| Player | Actual car / tgt | Carries | Targets |
|---|---|---|---|
| Derrick Henry | 17 / 0 | 10 (10.8) [4–19] · 1% · 86 | 1 (0.9) [0–2] · 45% · 45 |
| Justice Hill | 9 / 3 | 9 (9.5) [0–19] · 10% · 52 | 4 (4.0) [1–7] · 5% · 45 |
| Mark Andrews | 2 / 2 | 0 (0.1) [0–0] · 91% · 100 | 7 (7.4) [4–11] · 0% · 3 |
| Zay Flowers | 3 / 6 | 0 (0.1) [0–1] · 86% · 100 | 11 (10.9) [5–17] · 0% · 17 |
| Rashod Bateman | 0 / 2 | 0 (0.1) [0–0] · 92% · 92 | 6 (6.0) [1–11] · 4% · 20 |
| Matthew Hibner | 0 / 2 | 0 (0.1) [0–0] · 95% · 95 | 0 (0.6) [0–2] · 60% · 97 |
| LaJohntay Wester | 0 / 1 | 0 (0.1) [0–1] · 89% · 89 | 0 (1.0) [0–3] · 59% · 76 |
| Rasheen Ali | 0 / 0 | 0 (2.6) [0–10] · 64% · 64 | 0 (0.4) [0–1] · 74% · 74 |
| Joe Fagnano | 3 / 0 | 5 (5.1) [2–8] · 0% · 26 | 0 (0.0) [0–0] · 100% · 100 |

### 3.3 JAX usage, v2 arm (same convention)

| Player | Actual car / tgt | Carries | Targets |
|---|---|---|---|
| Bhayshul Tuten | 12 / 0 | 16 (16.2) [7–26] · 0% · 32 | 2 (2.5) [1–5] · 10% · 10 |
| Chris Rodriguez Jr. | 10 / 2 | 3 (3.6) [0–8] · 16% · 96 | 0 (0.3) [0–1] · 78% · 99 |
| Ameer Abdullah | 7 / 0 | 6 (7.5) [0–17] · 11% · 59 | 1 (1.0) [0–3] · 48% · 48 |
| LeQuint Allen Jr. | 0 / 2 | 0 (1.4) [0–5] · 63% · 63 | 0 (0.7) [0–2] · 52% · 96 |
| Trevor Lawrence | 1 / 0 | 4 (3.9) [1–7] · 2% · 12 | 0 (0.0) [0–0] · 100% · 100 |
| Jakobi Meyers | 0 / 6 | 0 (0.1) [0–0] · 92% · 92 | 4 (4.7) [1–9] · 8% · 73 |
| Parker Washington | 0 / 7 | 0 (0.2) [0–1] · 84% · 84 | 9 (9.4) [4–16] · 1% · 38 |
| Brenton Strange | 0 / 2 | 0 (0.1) [0–0] · 91% · 91 | 6 (5.9) [3–9] · 0% · 8 |
| Nate Boerkircher | 0 / 3 | 0 (0.0) [0–0] · 96% · 96 | 0 (0.7) [0–2] · 52% · 98 |
| Travis Hunter | 0 / 1 | 0 (0.1) [0–1] · 87% · 87 | 1 (2.3) [0–6] · 32% · 53 |
| Tanner Koziol | 0 / 2 | 0 (0.0) [0–0] · 99% · 99 | 0 (0.2) [0–1] · 86% · 100 |
| Josh Cameron | 0 / 1 | 0 (0.1) [0–1] · 88% · 88 | 1 (1.9) [0–6] · 42% · 62 |

Reading the v2 counts: only Rodriguez (10 actual carries, 96th percentile) and Trevor Lawrence's 1 scramble
are upper-tail against v2; Henry (17, 86th), Hill (9, 52nd), Tuten (12, 32nd), Abdullah (7, 59th) and
Fagnano's 3 rushes (26th) are inside the v2 distributions. Target counts are inflated in the sim by the
pass-volume and target-equals-attempt issues; on **share**, where both sides are normalised, the v2 numbers
are close for the top receivers (Flowers 37% actual vs 31% sim; Washington 27% vs 28%; Bateman 12% vs 17%;
Meyers 23% vs 14%) and the biggest miss is tight-end depth: Boerkircher got 3 targets (12% share) in the
actual game, while the sim gave the third TE ~2% of targets and concentrated TE work on Strange (18% vs 8%
actual). With 16–26 actual targets, single-game share noise is large, so this is weak evidence at best.

### 3.4 Arm comparison: this is where v1/v15 differ from v2

Carry shares (mean across seeds) and v2 median carries / % zero-carry seeds:

| Player | Actual carry share | v1 | v15 | v2 | v2 median (10th–90th) · %zero |
|---|---|---|---|---|---|
| Derrick Henry (BAL) | 0.50 | **0.72** | **0.69** | 0.36 | 10 (4–19) · 1% |
| Justice Hill (BAL) | 0.26 | **0.04** | **0.08** | 0.32 | 9 (0–19) · 10% |
| Rasheen Ali (BAL) | 0.00 | 0.02 | 0.02 | 0.09 | 0 (0–10) · 64% |
| Bhayshul Tuten (JAX) | 0.40 | 0.60 | 0.57 | 0.48 | 16 (7–26) · 0% |
| Chris Rodriguez Jr. (JAX) | 0.33 | **0.03** | 0.19 | 0.11 | 3 (0–8) · 16% |
| Ameer Abdullah (JAX) | 0.23 | **0.04** | **0.08** | 0.22 | 6 (0–17) · 11% |
| LeQuint Allen Jr. (JAX) | 0.00 | 0.16 | 0.03 | 0.04 | 0 (0–5) · 63% |

- **V1 and V1.5 are single-back models**: Henry gets 0.69–0.72 of BAL carries and Hill is given zero carries
  in 69% (v1) / 49% (v15) of seeds; on JAX, Rodriguez and Abdullah are near-zero (Rodriguez zero in 74% of
  v1 seeds, carry share 0.03). This is a structural behaviour across 1000 seeds, not one-game noise — a
  genuine model miss in v1/v15.
- **V2 models a committee and matches Thursday's backfield well**: Hill 0.32 vs actual 0.26 and Abdullah
  0.22 vs 0.23 are close, Henry at 0.36 vs 0.50 and Tuten at 0.48 vs 0.40 are the remaining gaps (actual
  Henry at the 86th percentile of v2 means the actual game used Henry more than v2 usually does). The V2
  numbers for the actual players are almost all inside a single 10th–90th band.
- QB rushing is systematically high in all arms: Fagnano 5.0–5.2 carries per seed (17–18% of BAL carries
  after removing sack-adjusted attempts) vs 3 actual (9%); Lawrence 3.6–3.9 vs 1 actual.

### 3.5 Snaps: not usable

- V1 and V1.5 export no lineup record: `snaps` is null in 124000/124000 rows per arm.
- V2 exports snaps, but they are **not a snap count**: team-seed sum is 333 on average (10th–90th 277–389)
  against a theoretical minimum of 11 × 68 plays ≈ 740, i.e. about five players per offensive play, not eleven;
  only 14 players per team-seed have snaps > 0 of 62; and the quarterbacks have effectively zero snaps
  (Fagnano 0 on 995/1000 seeds, Lawrence 0 on 983/1000) even though both threw in 1000/1000 seeds.
  2712 of 124000 player-rows (2.2%) record carries/targets with snaps = 0. Snap data are therefore
  skill-position-only by construction and cannot be compared with a real snap count.
- Actual snap counts are not in this bundle (README "Missing" item 3), so **no snap comparison is possible**
  in either direction. Anything about snap share or route participation from these files would be wrong.

---

## 4. Distribution appendix (per arm)

Format: **median (mean) [10th–90th percentile] · % of 1000 seeds ≤ actual**.
"Total yards" = gross passing + rushing (derived); "possession" uses the between-snap attribution described in §1.1.
The v1/v15/v2 spread matters: the arms differ by up to ~2 points of team scoring and substantially on
running-back workload, so a 1-point difference from any single arm is not meaningful.

### v1

| Metric | BAL actual | BAL sim | JAX actual | JAX sim |
|---|---|---|---|---|
| Drives | 12 | 11 (10.5) [9–12] · 91.4 | 12 | 11 (10.5) [9–12] · 91.0 |
| Plays | 54 | 67 (67.3) [56–79] · 6.8 | 56 | 69 (68.0) [56–78] · 10.5 |
| Pass attempts | 19 | 35 (35.5) [25–46] · 0.8 | 26 | 34 (35.0) [26–45] · 13.0 |
| Rush attempts | 34 | 30 (30.9) [19–44] · 64.0 | 30 | 32 (32.2) [19–45] · 43.4 |
| Run share | 0.642 | 0.50 (0.50) [0.30–0.60] · 93.9 | 0.536 | 0.50 (0.50) [0.30–0.60] · 66.9 |
| Completions | 11 | 23 (23.4) [17–30] · 0.5 | 16 | 22 (22.0) [16–28] · 12.0 |
| Gross passing yards | 57 | 239 (242.9) [167–325] · 0.0 | 242 | 256 (259.2) [181–342] · 40.5 |
| Rushing yards | 172 | 133 (140.0) [71–213] · 71.3 | 77 | 133 (137.7) [71–207] · 13.8 |
| Total yards | 227 | 378 (382.9) [294–473] · 1.0 | 319 | 397 (396.9) [309–485] · 13.5 |
| Sacks taken | 1 | 0 (0.7) [0–2] · 85.0 | 0 | 0 (0.5) [0–1] · 59.0 |
| Turnovers | 2 | 1 (1.0) [0–2] · 92.1 | 0 | 1 (1.0) [0–2] · 35.7 |
| Turnovers on downs | 1 | 1 (1.0) [0–2] · 73.4 | 0 | 1 (0.9) [0–2] · 41.2 |
| Punts | 5 | 3 (3.2) [1–5] · 92.9 | 3 | 3 (3.1) [1–5] · 63.6 |
| FG attempts | 1 | 2 (2.0) [0–4] · 37.8 | 4 | 2 (1.9) [0–4] · 97.0 |
| FG made | 1 | 2 (1.7) [0–3] · 46.7 | 4 | 2 (1.7) [0–3] · 98.1 |
| Red-zone trips | 1 | 4 (3.6) [2–5] · 5.7 | 5 | 4 (4.1) [2–6] · 83.9 |
| Red-zone scoring drives | 1 | 3 (3.0) [1–5] · 13.9 | 5 | 3 (3.3) [2–5] · 95.1 |
| Points | 10 | 21 (21.7) [11.9–33] · 9.9 | 33 | 23 (23.5) [13–34] · 87.2 |
| Possession seconds | 1845 | 1796.5 (1808.7) [1455.8–2179.2] · 56.2 | 1755 | 1791.5 (1780.6) [1413.9–2139.1] · 45.2 |

Game-level v1: JAX 23.5 mean (median 23, 10th–90th 13–34), BAL 21.7 (21, 11.9–33), total 45.2 (45, 29–61),
margin +1.8 (3, −12.1 to +16), P(JAX win) 57.4%.

### v15

| Metric | BAL actual | BAL sim | JAX actual | JAX sim |
|---|---|---|---|---|
| Drives | 12 | 10 (10.4) [9–12] · 92.3 | 12 | 10 (10.5) [9–12] · 91.6 |
| Plays | 54 | 67 (67.2) [56–78] · 7.5 | 56 | 67 (67.7) [56–79] · 10.2 |
| Pass attempts | 19 | 35.5 (35.7) [26–45] · 0.7 | 26 | 34 (34.3) [25–44] · 13.3 |
| Rush attempts | 34 | 29 (30.3) [19–42] · 69.2 | 30 | 32 (32.7) [20–45] · 42.7 |
| Run share | 0.642 | 0.50 (0.50) [0.30–0.60] · 96.6 | 0.536 | 0.50 (0.50) [0.30–0.60] · 66.3 |
| Completions | 11 | 22 (22.6) [17–29] · 0.9 | 16 | 22 (22.0) [16–28] · 12.5 |
| Gross passing yards | 57 | 233 (235.5) [160–313] · 0.0 | 242 | 252 (253.6) [176.9–336.1] · 45.3 |
| Rushing yards | 172 | 129 (135.8) [73–207.1] · 78.0 | 77 | 132 (136.8) [70–208.1] · 13.3 |
| Total yards | 227 | 371 (371.3) [279–461] · 2.3 | 319 | 392 (390.4) [298–483] · 16.3 |
| Sacks taken | 1 | 1 (1.1) [0–3] · 68.5 | 0 | 0 (0.6) [0–2] · 56.8 |
| Turnovers | 2 | 1 (0.9) [0–2] · 94.7 | 0 | 0 (0.6) [0–2] · 54.2 |
| Turnovers on downs | 1 | 1 (1.0) [0–2] · 74.7 | 0 | 1 (0.9) [0–2] · 38.2 |
| Punts | 5 | 3 (3.5) [1–6] · 86.7 | 3 | 3 (3.3) [1–5] · 56.4 |
| FG attempts | 1 | 2 (2.0) [1–4] · 37.8 | 4 | 2 (2.0) [0–4] · 97.0 |
| FG made | 1 | 2 (1.7) [0–3] · 46.1 | 4 | 2 (1.7) [0–3] · 98.8 |
| Red-zone trips | 1 | 3 (3.6) [2–5] · 5.7 | 5 | 4 (3.9) [2–6] · 87.5 |
| Red-zone scoring drives | 1 | 3 (2.9) [1–5] · 14.1 | 5 | 3 (3.2) [1–5] · 95.6 |
| Points | 10 | 20 (20.2) [10–31] · 14.1 | 33 | 23 (23.4) [13–34] · 87.3 |
| Possession seconds | 1845 | 1802 (1798.5) [1433.9–2158.1] · 56.1 | 1755 | 1789 (1794.3) [1446–2145] · 44.7 |

Game-level v15: JAX 23.4 mean (median 23, 10th–90th 13–34), BAL 20.2 (20, 10–31), total 43.6 (43.5, 29–59),
margin +3.2 (4, −11.1 to +18), P(JAX win) 61.5%.

### v2

| Metric | BAL actual | BAL sim | JAX actual | JAX sim |
|---|---|---|---|---|
| Drives | 12 | 10 (10.5) [9–12] · 92.1 | 12 | 10 (10.5) [9–12] · 92.1 |
| Plays | 54 | 66 (66.5) [55–78] · 9.0 | 56 | 68 (67.9) [57–79] · 9.9 |
| Pass attempts | 19 | 35 (35.5) [27–45] · 0.3 | 26 | 33 (33.7) [25–43] · 15.9 |
| Rush attempts | 34 | 29 (29.7) [19–41] · 70.7 | 30 | 34 (33.6) [21–46] · 37.9 |
| Run share | 0.642 | 0.50 (0.50) [0.30–0.60] · 98.0 | 0.536 | 0.50 (0.50) [0.40–0.60] · 63.8 |
| Completions | 11 | 22 (22.5) [16–29] · 1.1 | 16 | 22 (21.8) [16–28] · 12.3 |
| Gross passing yards | 57 | 230.5 (232.9) [157–313] · 0.1 | 242 | 248 (250.8) [178.9–329.1] · 46.1 |
| Rushing yards | 172 | 132 (136.1) [73–201] · 76.1 | 77 | 134 (140.0) [76–212] · 10.9 |
| Total yards | 227 | 371 (369.0) [277.9–458.1] · 1.9 | 319 | 390 (390.8) [296–482.1] · 16.8 |
| Sacks taken | 1 | 1 (1.1) [0–2] · 68.0 | 0 | 0 (0.5) [0–2] · 58.2 |
| Turnovers | 2 | 1 (0.9) [0–2] · 92.2 | 0 | 0 (0.6) [0–2] · 56.2 |
| Turnovers on downs | 1 | 1 (1.0) [0–2] · 77.2 | 0 | 1 (0.9) [0–2] · 37.3 |
| Punts | 5 | 3 (3.5) [1–6] · 88.4 | 3 | 3 (3.2) [1–5] · 58.7 |
| FG attempts | 1 | 2 (2.1) [1–4] · 32.2 | 4 | 2 (2.2) [1–4] · 96.5 |
| FG made | 1 | 2 (1.8) [0–3] · 43.3 | 4 | 2 (1.9) [0–3] · 98.4 |
| Red-zone trips | 1 | 3 (3.5) [2–5] · 6.1 | 5 | 4 (3.9) [2–6] · 87.8 |
| Red-zone scoring drives | 1 | 3 (2.8) [1–4] · 14.7 | 5 | 3 (3.2) [2–5] · 95.4 |
| Points | 10 | 20 (19.9) [10–31] · 14.9 | 33 | 24 (24.1) [13–35] · 84.9 |
| Possession seconds | 1845 | 1771.5 (1774.5) [1412.8–2123.1] · 59.3 | 1755 | 1810 (1812.2) [1470.9–2163.2] · 43.3 |

Game-level v2: JAX 24.1 mean (median 24, 10th–90th 13–35), BAL 19.9 (20, 10–31), total 44.1 (44, 28–60),
margin +4.2 (4, −10 to +19), P(JAX win) 65.7%.

---

## 5. Lesson (what to carry into the next run)

1. **Grade the process one step before the score.** The final score here is a 95th–96th-percentile margin at
   a median total — easy to call "tail but plausible". The play-call layer underneath is at or outside the
   edge of a 1000-seed support (45 combined pass attempts, minimum 45/46/47). Any box-score or player-stat
   distribution for this game was generated under a play mix that could not occur, so differences in
   downstream stats are not evidence about those submodels until play volume matches.
2. **The model's one directional call was right and the market's was wrong** (sim leaned JAX 57–66%, market
   BAL −8.5, actual JAX +23, total 43 vs a 40.5 line). Record it; do not calibrate on it. One game.
3. **The arm progression did real work on usage.** V1/V1.5's single-back workload model (Hill zero-carry in
   69%/49% of seeds; Rodriguez near-zero) is a structural miss that V2's committee removed — V2's Hill/
   Abdullah carry counts land essentially on the actual game. Keep the V2-style lineup model; it is the only
   arm whose player-opportunity distributions are close enough to be informative.
4. **Fix the exports before the next review** (see Bugs): snaps, target=attempt, status flags, possession
   accounting. And retain per-play records in the next run — field position, explosive plays and drive
   outcomes are the three things this review could not test, and they are the likeliest explanation for a
   4.5-play-per-drive game and a passing line that sits at 0–1 of 3000 seeds.

---

## 6. Classification

### Confirmed bugs / data defects (mechanism visible in the data)

| # | Defect | Mechanism / evidence | Consequence |
|---|---|---|---|
| 1 | V2 `snaps` is not a snap count | Team-seed sum 333 vs ≥740 required for 11 players × ~68 plays; only 14 of 62 players have snaps > 0; QB snaps 0 on 995/1000 (Fagnano) and 983/1000 (Lawrence) seeds despite 1000/1000 seeds with pass attempts; 2712/124000 rows have production with snaps = 0 | No snap-share or participation analysis is possible from this bundle; the task's snap comparison cannot be made |
| 2 | `targets` ≡ `pass_attempts` in every row | 6000/6000 team rows across all arms; sum of player targets also equals team pass attempts in 6000/6000 team-seeds. The model cannot produce a pass attempt with no receiver; the actual game had 3 such BAL attempts out of 19 | Per-player and team target counts are mechanically pass volume; raw target counts are inflated by the 35-vs-19 pass-attempt gap and are not evidence about receiver usage |
| 3 | Box-score `status` contradicts the seed ledger | `status = incomplete` on 2000/2000 rows per arm vs `complete_regulation`/`complete_overtime` on 1000/1000 seeds | Box-score status cannot be used as a legality/completeness signal; provenance rests on the ledger alone |
| 4 | Duplicate red-zone FG columns | `red_zone.red_zone_field_goals` equals `red_zone.red_zone_field_goal_attempts` in 6000/6000 rows | Use `_made` for makes; the unsuffixed column is mislabelled |
| 5 | Possession time does not reconcile to the clock | In regulation seeds the two teams' `possession_seconds` sum to median 3575 s, i.e. 25 s short of 3600 (max shortfall 119–134 s; 3–7 seeds per arm short by >60 s) | Unclear whether this is an off-by-design definition (snap-to-snap) or a residual clock-accounting gap of the "clocks between possessions" kind; it blocks exact clock comparisons and needs a per-play rerun to settle |
| 6 | Actual pbp export is missing fields/plays | `fumble`, `fumble_lost`, `penalty`, `penalty_team` blank on all 156 rows; JAX drive 15 changes possession after 2nd down with no ending play; BAL "drive" 20 is a kickoff-only entry consistent with an unflagged return turnover | Actual giveaways are a floor (2 INT BAL, 0 INT JAX); drive-ending and turnover comparisons carry ±1 uncertainty and are not used as divergences |

Items 1–4 are simulator/export defects, not football outcomes. Item 5 is an open reconciliation gap. Item 6
is an actual-data defect. None of these is being called the cause of the Thursday score; they are the reasons
parts of this comparison cannot be made.

### Model misses (with the specific mechanism)

1. **Play-call volume and pass/run mix — the root divergence.** Mechanism: in all arms, team pass attempts are
   generated around ~35 per team (median) with a real but modest game-script response (−0.40 to −0.46
   correlation with own margin); the resulting game-level support is 59–82 combined pass attempts (10th–90th)
   with a floor of 45/46/47. Thursday's 45 combined attempts (41.3% pass) is at/below that floor, and its
   58.7% run share is the 98.6th–99.2nd percentile. The model's play-caller cannot generate a game script in
   which a team trailing by 4–30 points runs 34 times and throws 19; that is what happened. This is a
   distribution-range miss, not a demonstrated bias in the model's average pass rate (its median is close to
   modern NFL norms; Thursday was the outlier).
2. **V1/V1.5 running-back workload.** Mechanism: those arms allocate carries as a bell-cow (BAL Henry carry
   share 0.72/0.69, Hill zero in 69%/49% of seeds; JAX Rodriguez carry share 0.03/0.19, zero in 74%/18% of
   seeds). Thursday was a committee game (Henry 17, Hill 9; Tuten 12, Rodriguez 10, Abdullah 7), and V2's
   committee model reproduces the Hill, Abdullah and Tuten counts within the 10th–90th band. Classification:
   fixed in V2, still a miss in V1/V1.5.
3. **Downstream volume-dependent yardage.** Mechanism: BAL's 57 gross passing yards and 3.0 yards per attempt
   (0–1 of 3000 seeds at or below) is a direct function of the 19-attempt miss, not an independent passing
   model failure; likewise BAL's 227 total yards (1st–2nd percentile) and JAX's low total yards (14th–17th).
   These are consequences of miss #1 and should not be counted as three separate model errors.
4. **Weak/possible, not separable from one-game noise:** TE target distribution (the sim concentrates on
   TE1 and gives the third TE ~2% of targets; the actual game gave JAX's third TE, Boerkircher, 3 targets /
   12% share) and QB designed-run volume (Fagnano 5.0–5.2 carries per seed vs 3 actual). Both are inside the
   "one game cannot tell" zone and are listed only so they are not lost.

### Ordinary outcome variation (supported by, and inside, the simulated distributions)

- **Total points 43** (45th–50th percentile; means 43.6–45.2) — the scoring level was normal.
- **Margin +23** (95th–96th percentile; 4.2–5.4% of seeds had a larger JAX win) — a tail, but a supported one;
  42–54 of 1000 seeds per arm. Not a 1-in-1000 result.
- **BAL 10 points / JAX 33 points** (lower 10–15% / upper 13–15%) — both supported.
- **Rush attempts 64 total** (60th percentile; median 63) — exactly the model's expectation.
- **Drives 12/12** (91st–92nd percentile) and **possession split 51.2/48.8** (56th–58th percentile) — slightly
  more possessions than usual, normal clock split.
- **Sacks 1/0, turnovers 2 INT/0 (as recorded), punts 5/3, turnovers on downs 1/0** — all inside the arms'
  central masses (86th–93rd percentile at worst).
- **JAX touchdown count 3** (75th percentile), **JAX red-zone trips 5** (88th), **JAX field goals 4** (98th),
  **BAL red-zone trips 1** (6th) — upper/lower tails that are supported (68–89 seeds had ≥4 JAX FGs;
  57–61 seeds had ≤1 BAL red-zone trip). The FG-heavy, low-BAL-possession shape is unusual but not
  unsupported.
- **Per-player carry counts in V2**: Henry 17 (86th), Hill 9 (52nd), Tuten 12 (32nd), Abdullah 7 (59th),
  Fagnano 3 (26th) — all inside the distributions; only Rodriguez 10 (96th) and Lawrence's single scramble
  are tail, and both are single-game share noise at these sample sizes.

---

**Scope statement.** The score comparisons above are one actual game against 1000 seeds per arm. A single game
can expose a mechanism — for example, a snap field that never records a quarterback snap, or a pass attempt
with no receiver — but it cannot establish calibration. Nothing in this review says the simulator's scoring
distribution is miscalibrated, only that the process that produced this particular score was unlike anything
the simulator generates, so the score agreement (total 43) and the directional lean (JAX) should not be read
as skill until the play-call range and the data defects are addressed and the review is repeated on a sample
of games.
