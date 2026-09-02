# RESULT — TASK-next-identity-queue.md (investigation pass)

**Status:** investigation-only pass, per instruction "continue investigating tasks and skip others"
**Date:** 2026-08-05
**DBs read:** `/root/legendarypicks/backend/data/picks.db` (prod, read-only), `data/picks.dev.db` (dev, read-only), plus pre-op backups
**Writes:** none to any database. Only repo change: identity artifact commit `3267fb5` (Part 3).
**Deliberately not done:** prod migration (`migrate_mlb_position_vocabulary.py` + spine ingest + `roster_sync mlb`), any crosswalk write, any repair, the prod 503 rebuild, `git push` (only the v0.7.6 release from the previous turn was pushed).

---

## Part 1 — MLB vocabulary: the 2 SP/RP rows and the 5 blank `position_group` rows (dev)

The task's premise — "both already have an mlbam_id, so the crosswalk is not the problem… MLB publishes no primaryPosition" — is **wrong for 3 of the 5 rows**. The spine fill (`ingest_mlb_spine_identity.py`) only visits spine rows whose `mlbam_id` appears in MLB's `sports/1/players?season=2026` list. Measured against statsapi.mlb.com:

- **id=27525 José Suárez ATH RP, mlbam=699027** — **wrong person.** 699027 is *José Suárez, OF, Peoria Chiefs (A-ball), never debuted*. The A's 2026 roster pitcher is **mlbam=660761**. The id predates the Aug 4 crosswalk (present in pre-crosswalk backup). Gate G is blind to it: both Suárezs fold to the same identity key.
- **id=28922 Jackson Wolf DET SP, mlbam=680232** — id is **correct** (MLB publishes him as P/Pitcher), but he's in AAA (Toledo) → not in the 2026 MLB player list → fill never visits him → the stale ESPN `SP` survives. **The task's fix applies here**: the stale value should be cleared, not kept.
- **id=12 Joe Mack MIA C, mlbam=118086** — **wrong person**: 118086 is a **1945 Boston Braves first baseman**.
- **id=94 Jacob Wilson ATH SS, mlbam=607111** — **wrong person**: A's SS is **805779**; 607111 is a different Jacob Wilson (2B, Sugar Land, 2021 debut).
- **id=32119 Kenneth Piper TB C** — **no mlbam at all**; crosswalk couldn't resolve (not in the 2026 list / no team match).

So of the 5 blank rows: 3 are wrong-person ids (Mack, Wilson, Suárez — all same-name collisions gate G cannot see), 1 is right-person-but-unpublished (Wolf), 1 is unresolved (Piper).

## Part 2 — the 2,980 no-publisher-id props

`id=28987` (name EMPTY, **2,393 props**) breaks down as:

| class | props | share |
|---|---|---|
| **game-level markets** that never needed a `player_id` (`total_hits,_runs_and_errors` 1396, `earned_runs` 176, `strikeouts` 136, `outs` 124, `hits_allowed` 120) | 1,952 | 81.6% |
| **single-player props, name unparsed in the market string** (`total_pitcher_walks___kohl_drake`, `total_hits,_runs_and_rbis___sean_keys`, …) — **20 distinct players**, all minor-league names | 296 | 12.4% |
| **genuine multi-player combos** — all one pairing: `cody_bellinger_&_ben_rice_combined` ×3 market types | 145 | 6.1% |

So `bovada_scraper.py` funnels game markets + unparsed A-ball player props + a combo into one nameless bucket. **Outman (29097) and Mastrobuoni (29152) are NOT cleanly crosswalkable by the Part 1 rule**: names are unique (`681546`/`670156`) but the team clause blocks both — Outman's row says MIN while MLB publishes DET; Mastrobuoni's MLB `currentTeam` is AAA Tacoma (no team match). Group A seeds (121–124) confirmed **0 references** across props/logs/stats/memberships/snap. Nothing deleted.

## Part 3 — identity correctness (measured, not repaired)

Ran `fetch_identity_names.py --season 2026` → all four leagues fetched clean, artifact committed (`3267fb5`): MLB 1,358 / NFL 25,035 / NHL 1,035 / NBA 541 pairs, **zero** provenance errors. Audits vs prod, gate lines **verbatim**:

```
PASS       mlb   G/published-identity         all 1324 checked mlbam_ids carry the published name
FAIL       nfl   G/published-identity         4 of 24344 rows carry an nfl_gsis_id belonging to a different player: id=4990 'Jalen Cropper' has nfl_gsis_id=00-0038740 which publishes as 'Jalen Moreno-Cropper'; id=7690 'Kenneth Gainwell' has nfl_gsis_id=00-0036919 which publishes as 'Kenny Gainwell'; id=22367 'Zach Tom' has nfl_gsis_id=00-0037817 which publishes as 'Zach Bako-Bewele'
FAIL       nhl   G/published-identity         11 of 840 rows carry an nhl_id belonging to a different player: id=25702 'Josh Dunne' has nhl_id=8482623 which publishes as 'Joshua Dunne'; id=25777 'Joe Veleno' has nhl_id=8480813 which publishes as 'Joseph Veleno'; id=25861 'Tommy Novak' has nhl_id=8478438 which publishes as 'Thomas Novak'
PASS       nba   G/published-identity         all 541 checked nba_ids carry the published name
```

Full lists (the gate previews 3): NFL's 4th is `id=22582 'JT Tuimoloau' → 'Jaylahn Tuimolaou'`; NHL's other 8 are `Max Shabanov→Maxim`, `Maxim Tsyplakov→Maksim`, `A.J. Greer→Anthony-John (AJ)`, `Jake Middleton→Jacob`, `Jeffrey Viel→Jeffrey Truchon-Viel`, `Frederick Gaudreau→Freddy`, `Joshua Mahura→Josh`, `Jamie Oleksiak→Jamieson`. **All 15 are the same human under a different published name form** (nickname / compound surname / legal-name change) — the gate is strict, not wrong. **Contrast with MLB's Aug 4 corruption: these are not wrong people.** Also measured, NBA: `FAIL nba F/identity-crosswalk 269 athletes split across two players.id rows via nba_id/espn_id -- their stats and their game logs are on different people`. Nothing repaired, per the task.

## Part 4 — NFL `rush_td`/`rec_td` (report only, nothing run against prod)

Per published-first §2b, this is a **surfacing gap, not acquisition**: nflverse's `stats_player_reg_YEAR.parquet` publishes `rushing_tds`/`receiving_tds`, and `ingest_nfl_season_stats.py` already maps them → `rush_td`/`rec_td`. Measured on prod: `player_stats` **has** the columns but all **608 NFL 2025 season rows are NULL** (ingested pre-columns, never re-ingested); `player_game_logs` on prod **lacks the columns entirely**; NFL 2026 has 0 rows anywhere because the season hasn't started (it's August — the "0 rows populated" is about 2025, not a missing 2026 ingest). The fix is a re-ingest with the current code (publisher's own totals — no log rollup, honoring published-first §3's eight defects); I did not run it.

---

## Also relevant (from this session's prod diagnostics)

- **prod MLB leaders 503 (live):** "canonical player stats disagree with the player index for mlb season 2026; rebuild required" — caused by the Aug 4/5 MLB dedupe repointing 242 `player_stats` rows (214 batting + 28 pitching; 215 case-only, 27 real name diffs) without rewriting `player_name`; the byte-exact guard 503s. Not the concurrent props-ingest race (that was a props-only hazard; orphan delta 0, verified — 78 props + 90 roster_snap orphans predate the dedupe). Dev clean (dedupe never ran on dev's current data). Fix = regenerate display copy from spine; not done.
- **dev now has 108 duplicate `mlbam_id` groups** re-created by the crosswalk work (`920eed3` backfilled mlbam onto second ESPN rows; 88 of 108 pairs both carry an espn_id, e.g. Ozuna 4417203/31668). "Dev is the clean reference" is no longer true.
- **v0.7.6 released** (previous turn): `e68209e chore(release): v0.7.6` + tag `v0.7.6` pushed; release notes at top of CHANGELOG.md.

---

```
git status --short (tracked): clean — only pre-existing untracked files (TASK-*.md, logs, sketches, picks.dev.db*)
git log --oneline -6:
3267fb5 data(identity): regenerate published id->name maps for all four leagues (2026)
e68209e chore(release): v0.7.6
01c22db docs(changelog): v0.7.6 release notes
9ec78e4 feat(identity): fetch NFL, NHL and NBA identity maps from the id's own issuer
920eed3 fix(mlb): resolve ESPN-only rows against MLB's published roster, both directions
405a41e fix(roster): stop overwriting MLB position with ESPN's role vocabulary
```

===END===

Stopped here per the task file ("Then stop and wait").
