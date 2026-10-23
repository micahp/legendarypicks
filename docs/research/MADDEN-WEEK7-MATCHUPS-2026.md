# Madden 27 Week 7 matchup experiment (2026-10-23)

Research only. No trained model. Nothing here is a bet, a lock, or a change to the served NFL model, its
grading, production tables or public predictions. Frozen before the first kickoff (Sunday, Oct 25, 09:30 as
stored).

## Result in brief

- **Coverage is the binding constraint.** Of 736 starters identified from usage, 512 (70%) link to a
  Madden 27 row through a high-tier identity. Per team the share runs from 39% (MIA) to 91% (LAC).
- **Most Week 7 comparisons are not decision-grade.** After the 60% coverage rule and a paired net (below), 9
  of the 13 prospective games have at least one comparable dimension, and only 4 have three or more. Four
  have none: TB–CAR, IND–MIN, MIA–NYJ and CLE–TEN.
- **Direction is stable in three games with enough comparable dimensions:** CIN–BAL (ratings favor BAL, LP
  favors CIN, both runs), DEN–ARI (agree with LP, both runs), and KC–SEA (agree with LP, both runs). KC–SEA rests
  on quarterback dimensions only.
- **Two games flip between runs:** GB–DET and LAR–LV. Both depend on starters whose identity is still
  name-only.
- **The Patriots–Bears retrospective is not a fair test.** The Madden snapshot was scraped on Oct 22, the day
  of that game. The official lock missed the direction.

## Bundle update: 03:36 archive (sha256 642777…758)

The archive was rebuilt after the freeze. The v1 freeze (`a12eb4d9…`) and its outputs are unchanged. The v2 run
(`madden-week7-frozen-v2-2026-10-23.json`, `madden-week7-matchups-2026-v2.json`,
`madden-week7-sensitivity-2026-v2.json`) reflects the new bundle:

- **Ratings are unchanged.** No attribute cell differs from the previous bundle. Team units and game dimensions are
  identical.
- **Giants and Jets rows now carry team badges.** Four starters move from name-only review into name, team and
  position review. They stay out of the primary run.
- **One sensitivity result changes:** NYG @ HOU moves from -2.01 to -0.62 in the review-included run. The LP
  direction goes from conflict to neutral.
- **Team agreement with the snapshot** for the 512 matched starters: 509 agree, 3 disagree. Kayshon Boutte (NE vs HOU),
  Atonio Mafi (LV vs TEN) and Lucas Patrick (NYG vs WSH, newly filled) are the disagreements.

The Phase 1 rows below describe the v1 freeze. The Giants and Jets line is superseded by this note.

## Phase 1: verification

| Check | Result |
|---|---|
| Teams with coverage | 32 teams in the table. Lowest: MIA 9 of 23 (0.39), CAR, MIN, TEN 13 of 23 (0.57). Highest: LAC 21 of 23 (0.91) |
| Starter status (736) | 512 matched to a 2027 row; 101 high-tier identity but no 2027 row; 63 absent from the archive; 16 in an earlier release only; 35 name, team and position agree but no high-tier link; 9 name only in 2027 |
| Identity | High tier is name plus position, unique among NFL players, with a GSIS link. Review tiers are excluded from the primary run. Zero ambiguous GSIS links |
| Team membership | 477 matched starters agree with the snapshot team. 33 have a blank Madden team (Giants and Jets rows). 2 real moves: Kayshon Boutte (2027 row NE, snapshot HOU) and Atonio Mafi (2027 row LV, snapshot TEN). Ratings kept, team flagged |
| Roster freshness | Latest roster snapshot is Aug 4. 929 transactions since then (15 to 41 per team). Team membership uses snap team, weeks 1-5 |
| Week 7 inactives | None. No week 7 injury report in the database (weeks 1-6 only). Last known status is shown per starter |
| Giants and Jets | Rows exist with ratings (NYG 17 matched, NYJ 15 matched) but no team badge. Team attribution comes from the snapshot |
| Duplicates | One player appears twice in 2027 (Phidarian Mathis, Chiefs and Bills rows). The row matching the snapshot team is used. No unresolved stints |
| Attribute source | Site-published Madden 27 values; no calculated overall in the 2027 release. EA attribution is assumed, not verified |
| Snapshot timing | Unverified. The archive has no snapshot date. Post-launch updates are confirmed for Madden 27 (Sept 18 test) |

## Phase 2: profiles

Composites are fixed attribute lists, defined in `scripts/madden/week7/matchup_index.py`:

- QB: THP, TAS, TAM, TAD, PAC, TOR, TUP, AWR. Short, medium and deep accuracy are kept separate in the output.
- Receivers and TEs: SPD, ACC, AGI, SRR, MRR, DRR, RLS, CTH, CIT, SPC.
- RBs: SPD, ACC, COD, CAR, BCV, BTK, TRK, ELU.
- Pass blocking: PBK, PBP, PBF. Run blocking: RBK, RBP, RBF.
- Pass rush: PMV, FMV, ACC. Run defense: BSH, STR, TAK.
- Man coverage: MCV, PRS, PRC, SPD, ACC. Zone coverage: ZCV, SPD, ACC. Tackling: TAK, PUR, POW.

Reported but not composited: IBL (applies to both run and pass), TAC (historical label, never merged into
THA), and SRR/MRR/DRR (kept separate inside the receiver composite).

## Phase 3: matchup index

- **Starters** come from usage: average snap share over weeks 1-5, the weeks with full coverage. The week 6
  table covers only 28 teams. No week 7 production enters any weight.
- **Percentiles** are within each role's own Madden 27 population. A receiver's percentile is comparable to
  other receivers, and a coverage percentile to other defensive backs. Dimensions compare two relative
  positions, not two identical scales. That is a real limit on what the index means.
- **Dimension** = offense composite minus defense composite, in percentile points.
- **Coverage rule**, set before the first run: a dimension is flagged low when either side has under 60% of
  its expected players. Under this rule 93 of 182 dimensions are low.
- **Paired net** (corrected after the first run): for each game, average only the dimensions that are ok on
  both sides. An earlier version averaged each side over different subsets. That bug is fixed, and the
  reported numbers use the paired version.
- **Sensitivity**: a second run includes the 35 name, team and position matches that lack a high-tier link.
- **Agreement** with LP: neutral if the ratings net is under 2 points or the LP margin is under 1 point.

## Phase 4: game table

LP margin is LP's preview projection, home minus away (`nfl-preview-v1`, latest run). The official lock
exists only for NE–CHI. "Paired" is the number of comparable dimensions in each run.

| Game (away @ home) | Kickoff (as stored) | LP margin | Ratings net, primary (paired) | Ratings net, review-included (paired) | Agreement, primary / review-included |
|---|---|---|---|---|---|
| PIT @ NO | Sun 09:30 | -4.93 | +10.07 (1) | +13.45 (2) | conflict / conflict |
| SF @ ATL | Sun 13:00 | -5.50 | +1.00 (1) | +2.28 (1) | neutral / conflict |
| CIN @ BAL | Sun 13:00 | -1.30 | +33.02 (3) | +23.56 (5) | conflict / conflict |
| TB @ CAR | Sun 13:00 | +4.71 | not computable | not computable | not computable |
| NYG @ HOU | Sun 13:00 | +4.39 | -2.01 (4) | -2.01 (4) | conflict / conflict |
| IND @ MIN | Sun 13:00 | +8.96 | not computable | not computable | not computable |
| MIA @ NYJ | Sun 13:00 | +4.07 | not computable | not computable | not computable |
| CLE @ TEN | Sun 13:00 | -6.12 | not computable | not computable | not computable |
| DEN @ ARI | Sun 16:05 | -7.16 | -4.78 (2) | -11.86 (6) | agree / agree |
| GB @ DET | Sun 16:25 | -0.02 | -7.82 (4) | +14.83 (7) | neutral / neutral (sign flips) |
| LAR @ LV | Sun 16:25 | -0.58 | +6.18 (1) | -13.90 (5) | neutral / neutral (sign flips) |
| KC @ SEA | Sun 20:20 | -1.72 | -33.39 (2) | -27.08 (3) | agree / agree |
| DAL @ PHI | Mon 20:15 | +0.04 | +7.67 (4) | +0.82 (7) | neutral / neutral |

Sign convention: a positive ratings net favors the home team.

## Detailed studies

Dimension values are offense composite minus defense composite. "n" is the player count behind each side. The
usage-weighted variant is in the JSON.

### GB @ DET (Sun 16:25)

- **Primary (4 paired):** net -7.82, favoring GB. Only QB and receiver dimensions are comparable (QB vs man
  -5.99, QB vs zone -11.03, receivers vs man -4.62, receivers vs zone -9.66).
- **Why it is weak:** GB has 2 of 5 offensive linemen matched. Their pass-protection and run-blocking
  dimensions (-45.8 and -60.5) are flagged low. GB's RB Chris Brooks is a review-tier name match.
- **Sensitivity (7 paired):** net +14.83, favoring DET. Adding the review-tier GB starters changes the sign.
- **Read:** direction is undetermined. The result depends on GB's offensive line, which is mostly unmatched.

### KC @ SEA (Sun 20:20)

- **Primary (2 paired):** net -33.39, favoring SEA. Both dimensions are quarterback against coverage, paired
  (SEA minus KC): QB versus man -29.4 and QB versus zone -37.4. SEA's QB composite is 34.0.
- **Why it is weak:** each QB composite rests on a single player (n = 1). The other dimensions are flagged
  low, and KC's RB has no matched row.
- **Sensitivity (3 paired):** net -27.08, still favoring SEA.
- **Read:** the direction agrees with LP in both runs, but the evidence is one QB comparison.

### CIN @ BAL (Sun 13:00)

- **Primary (3 paired):** net +33.02, favoring BAL. Paired dimensions (BAL minus CIN): receivers versus man
  coverage +44.0, receivers versus zone coverage +41.2, RB versus tackling +13.9.
- **Why it is incomplete:** BAL's QB is Lamar Jackson, a review-tier name match with no high-tier link. No BAL
  QB composite exists in the primary run, so the QB dimensions are missing.
- **Sensitivity (5 paired), with Jackson included:** net +23.56, still favoring BAL. Two extra dimensions
  come from the BAL QB.
- **Read:** the ratings favor BAL, and LP favors CIN by 1.3. The comparison is stable across runs, and the
  QB side remains the largest uncertainty.

## Retrospective: NE @ CHI (Thu Oct 22, completed)

- **Final:** CHI 30, NE 24. Source: ESPN event 401873010 in the stored game summaries.
- **Official lock** (`nfl-lock-2026-w07`): CHI -1.5 (NE favored by 1.5), total 45.6. The lock missed the
  direction and the total (result 54).
- **Ratings:** primary +0.64 (1 paired dimension, neutral); review-included +2.40 (2 paired), favoring CHI.
- **Not a fair test:** the Madden snapshot was scraped on Oct 22, the same day as this game. Post-game
  information may be in the archive. It is not a prospective lock and must not be treated as evidence.

## Phase 5: receiver shortlist (research only)

File: `docs/research/data/madden-week7-receiver-shortlist-2026.json`. 74 matched receivers and TEs were
ranked by the largest difference against the opposing man or zone composite. Week 6 projections are stale
context only. The table has receiving stats only, and no Week 7 projection exists.

| Player | Matchup | Diff vs man / zone | Week 6 rec yds (stale) |
|---|---|---|---|
| Tyler Warren (IND, TE) | at MIN | +48.8 / +50.6 | 46.2 |
| Mark Andrews (BAL, TE) | vs CIN | +44.2 / +44.2 | 37.9 |
| George Kittle (SF, TE) | at ATL | +43.7 / +40.3 | 64.1 |
| Zay Flowers (BAL, WR) | vs CIN | +39.9 / +39.9 | 85.1 |
| Charlie Woerner (ATL, TE) | vs SF | -49.4 / -51.6 | 4.3 |

These are research prompts, not projections. They compare a receiver with an opposing unit across two
percentile pools, and each identity is a high-tier match with 9 of 10 REC attributes present.

## Phase 6: Gridiron Physics counterfactual

**Not run.** The prototype lives in a separate repository (`/root/gridiron-rating-audit`) with untracked data,
and a multi-body physics agent is active there. The brief asks for coordination before file changes. No
coordination channel is confirmed, and this phase is marked optional. Next step: agree a shared file boundary
with that agent, then run the counterfactual on one matchup with fixed seeds.

## Phase 7: reproducibility and freeze

- **Scripts:** `scripts/madden/week7/matchup_index.py` (matchup index, retrospective, coverage tables),
  `scripts/madden/week7/props_shortlist.py` (receiver shortlist).
- **Outputs:** `docs/research/data/madden-week7-matchups-2026.json` (team units, coverage, 14 games),
  `madden-week7-sensitivity-2026.json`, `madden-week7-receiver-shortlist-2026.json`,
  `madden-week7-frozen-2026-10-23.json`. Player-level rows stay in `/root/nfl-ratings-data/week7/`, outside
  git.
- **Freeze record:** archive sha256 `a12eb4d9…5f2958`; identity crosswalk sha256 recorded in the frozen JSON;
  roster snapshot Aug 4; transactions through Oct 21; depth chart Oct 19; player logs through Oct 19; LP
  preview runs `nfl-preview-v1`; the official lock covers NE–CHI only.
- **Read-only:** the picks database was opened with `mode=ro`. Nothing was written to production tables.
- **Commit:** the freeze record names the git revision at run time. See the final commit for the revision that
  contains these scripts.

## Limits

1. Coverage: 30% of starters are unmatched, and 93 of 182 dimensions are flagged low.
2. No Week 7 injury report and no Week 7 inactives in the database.
3. Roster snapshot dates from Aug 4; 929 transactions followed.
4. Snapshot timing is unverified for every release.
5. Percentiles compare relative positions across role pools.
6. Week 6 projections are stale and cover receiving stats only.
7. The Madden 27 release is 1,531 rows against 2,160 for 2026, so some 2026 starters have no 2027 row.

## Success criteria: what the data supports

- **Which team is stronger for specific responsibilities:** partly. Unit composites exist for all 32 teams,
  but coverage varies from 39% to 91% of starters.
- **Which individual players have advantages:** receivers and TEs only, with stale context.
- **How reliable the comparisons are:** the coverage flags and the review-tier sensitivity show where they
  are not.
- **Where results agree or disagree with LP:** shown in the game table. Agreement appears in three games
  with enough dimensions; conflict appears in CIN–BAL and NYG–HOU.
- **Which physical interactions to test next:** receiver percentiles against man coverage, once the 2027
  identities are reviewed and the Gridiron counterfactual is scoped with the physics agent.
