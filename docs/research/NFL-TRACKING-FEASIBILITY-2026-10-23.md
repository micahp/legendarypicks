# NFL player-tracking feasibility, Phase 0 (LP data side, 2026-10-23)

**Status:** Conditional post-throw tracking is now downloaded and verified for 2023 weeks 1–7 (see the verified section). Full-play, from-snap tracking is still not present in these files. The 2025 cohort is staged from an unofficial GitHub copy (see the 2025 section).

Source directive: gridiron-physics `docs/FOOTBALL-FIRST-AGENT-DIRECTIVE-2026-10-23.md` (`origin/main`), Phase 0 and the LP tracking owner role.

## What was searched, and what it returned

| Check | Command or source | Result |
| --- | --- | --- |
| Local filenames | `find /root /data /srv /mnt /home /opt /var/lib -xdev` for `*tracking*`, `*bigdatabowl*`, `*big-data-bowl*`, `*big_data_bowl*`, `tracking_week*`, `plays.csv`, `games.csv`, `player_play*` | Only NHL tracking: `/root/lp-research-data/stathletes-big-data-cup-2026/*Tracking_P*.csv` (hockey, not NFL). Other matches were unrelated package and cache files. |
| Kaggle access | `KAGGLE_API_TOKEN` in `/root/.hermes/.env` (added by the user, 2026-10-23; value not recorded here) | The token authenticates. Downloads returned HTTP 403 until the user accepted the competition's rules on kaggle.com; they succeeded after that (2026-10-23). |
| LP dev database, read-only | `/root/legendarypicks/backend/data/picks.dev.db` (126 tables) | No table has positional tracking columns. Columns checked for x, y, s, a, o, dir, frameId, nflId: none found in any NFL table. |

## Kaggle listings (metadata only, via the API)

| Competition | Listing | Notes |
| --- | --- | --- |
| `nfl-big-data-bowl-2025` | README only (78 bytes) | Tracking files are not listed through this token. |
| `nfl-big-data-bowl-2026-prediction` | 20 files listed, 334,797,422 bytes | The listing is **incomplete**. It omits `train/output_*` label files, which exist and download for weeks 1–7. Listed: 11 `kaggle_evaluation/` code files, `test.csv`, `test_input.csv`, `train/input_2023_w01.csv` to `w07.csv`. |

## NFL play-level tables that do exist (observed context, not frames)

| Table | Rows | Seasons | Coordinates | Notes |
| --- | --- | --- | --- | --- |
| `nfl_pbp` | 753,668 | 2010–2026 | none | `game_id`, `play_id`, down/distance, yardline, EPA, drive, `series_result`, outcome flags |
| `nfl_hist_participation` | 478,989 | 2016–2025 | none | `n_offense`, `n_defense`, personnel, box count, pressure, time to throw |
| `nfl_hist_ftn_charting` | 185,215 | 2022–2025 | none | charting booleans (play action, screen, RPO, blitzers, drop, contested) |

These are usable as the observed play-outcome and drive/game baseline, owned by LP. They cannot supply player trajectories.

## 2025 Big Data Bowl cohort, week 1, staged from a GitHub copy (2026-10-23)

**Why not Kaggle.** The 2025 competition's data was removed from Kaggle (user report, 2026-10-23). The token's account gets HTTP 403 for the files, and the listing shows only a README.

**Source (unofficial).** GitHub repository `b00nk3r/NFL-Big-Data-Bowl-2025`, commit `e28d3b25725799ef2213680016db5325f6f90014`, path `code/data/`, stored with Git LFS. The repository's Apache-2.0 licence covers its code, not the competition data. Permitted use: user-reported, not verified against a licence. This is a third-party re-hosting and not the official release.

**Season.** The data is the **2022 season, weeks 1–9** (136 games in `games.csv`), not the 2025 season. The name refers to the competition year.

**Staged files** (outside git, `/root/nfl-tracking-data/bdb2025/code-data/`; each verified by its LFS SHA-256 and size; full hashes in `SHA256SUMS.txt` and `PROVENANCE.json`):

| File | Bytes |
| --- | ---: |
| `tracking_week_1.csv` | 971,403,802 |
| `player_play.csv` | 52,533,762 |
| `plays.csv` | 6,892,353 |
| `players.csv` | 104,749 |
| `games.csv` | 7,128 |

**Week 1, tracking (all 7,104,700 rows read).**
- 16 games and 1,952 plays. `plays.csv` has 1,952 plays for the same 16 games, so the play counts reconcile.
- `frameType` is BEFORE_SNAP, SNAP and AFTER_SNAP. Frames per play: min 17, median 158.5, max 697. Pre-snap frames are included, so these are full plays.
- Frame interval 0.1 s (10 Hz), from the timestamps: median and IQR both 0.1 s.
- Coordinates: x 0.1 to 119.8 and y −2.5 to 57.5 (first 500k rows), consistent with yards on a 120 × 53.3 field. `playDirection` is a column; the file is not normalised by it.
- Ball rows: 308,900, with blank `nflId` and `displayName` `football`.
- Events: `tackle` 27,715 rows, `first_contact` 28,865, `out_of_bounds` 4,968.

**Tackle labels, week 1.**
- Plays with the exact `tackle` event: 1,205.
- Plays with a solo or assist flag in `player_play.csv` (`soloTackle`, `tackleAssist` or `assistedTackle` = 1): 1,479. Solo only: 1,097.
- Both: 1,199. Event only: 6. Label only: 280.
- The 280 label-only and 6 event-only plays are unresolved. The label-only plays may be assists where the tracking marks contact another way. That is not verified.
- The exact-event play list is at `/root/nfl-tracking-data/bdb2025/week1_tackle_event_plays.json`.

**All nine weeks (profiled 2026-10-24, `scripts/profile_bdb2025_weeks.py`).** Every week's play count matches `plays.csv`. Season totals: 136 games, 16,124 plays, 59,327,373 tracking rows, 2,579,451 ball rows.

| Week | Games | Plays | Exact `tackle` event | Event and label | Event only | Label only | Ball rows |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 16 | 1952 | 1205 | 1199 | 6 | 280 | 308,900 |
| 2 | 16 | 1809 | 1131 | 1126 | 5 | 237 | 291,493 |
| 3 | 16 | 1959 | 1197 | 1185 | 12 | 275 | 309,965 |
| 4 | 16 | 1830 | 1193 | 1187 | 6 | 209 | 293,372 |
| 5 | 16 | 1906 | 1182 | 1180 | 2 | 263 | 308,829 |
| 6 | 14 | 1697 | 1062 | 1057 | 5 | 230 | 271,282 |
| 7 | 14 | 1665 | 1055 | 1053 | 2 | 233 | 261,897 |
| 8 | 15 | 1771 | 1075 | 1073 | 2 | 297 | 287,118 |
| 9 | 13 | 1535 | 946 | 940 | 6 | 218 | 246,595 |

Season: 10,046 plays with the exact `tackle` event; 10,000 of them also carry a solo or assist label. 46 plays are event-only and 2,242 are label-only. Frames per play range from 12 to 1,010 across weeks. Per-week tackle-event play lists are at `/root/nfl-tracking-data/bdb2025/week<N>_tackle_event_plays.json`, and the full profile is at `/root/nfl-tracking-data/bdb2025/week_profiles.json`.

**Not verified.** The tackler identity on each `tackle` event against the labels; label-only and event-only plays are unresolved; any reconciliation beyond play counts and tackle flags.

**Reproduce.** `python3 scripts/fetch_bdb2025_week.py tracking_week_1.csv games.csv plays.csv player_play.csv players.csv`, then `sha256sum -c` against `SHA256SUMS.txt`.

## Verified after rules acceptance (2026-10-23)

Downloaded with `scripts/fetch_bdb2026_tracking.py` (token from the environment, never stored). Files are outside git at `/root/nfl-tracking-data/bdb2026-prediction/train/`. The sha256 manifest is `/root/nfl-tracking-data/bdb2026-prediction/SHA256SUMS.txt`. Permitted use: user-reported, not assessed here.

**Coverage, 2023 season weeks 1–7 (the only weeks downloaded):**

| Week | Games | Plays | Predicted player-tracks | Labels joined |
| --- | ---: | ---: | ---: | --- |
| 1 | 16 | 819 | 2,679 | 100% |
| 2 | 16 | 850 | 2,758 | 100% |
| 3 | 16 | 904 | 2,959 | 100% |
| 4 | 16 | 779 | 2,517 | 100% |
| 5 | 14 | 742 | 2,449 | 100% |
| 6 | 15 | 793 | 2,608 | 100% |
| 7 | 13 | 693 | 2,292 | 100% |
| **Total** | 106 game-weeks | 5,580 | 18,262 | 100% |

**Inputs (week 1 read in full).** 285,714 rows: 155,397 defensive-coverage rows and 130,317 offense rows. Roles present: Passer, Targeted Receiver, Other Route Runner, Defensive Coverage. Columns include `game_id`, `play_id`, `nfl_id`, `frame_id`, `x`, `y`, `s`, `a`, `dir`, `o`, `play_direction`, `absolute_yardline_number`, `player_to_predict`, `num_frames_output`, `ball_land_x`, `ball_land_y`. Every `nfl_id` is numeric, so there are **no ball rows** and no ball trajectory.

**Frames and timing.** `frame_id` starts at 1 on every play. The last input frame is 9–74 (median 27 frames per play). The frame rate is **10 Hz**, inferred from displacement over reported speed: median 0.1004 s between frames, IQR 0.0996–0.1013 s, 128,036 consecutive pairs. The columns do not state it.

**Missingness.** None in `x`, `y`, `s`, `a`, `dir`, `o`, `nfl_id`, `frame_id` for week 1. Labels were not checked for missingness, and other weeks' inputs were not checked either.

**Labels.** Output columns are `game_id`, `play_id`, `nfl_id`, `frame_id`, `x`, `y`. In week 1 every predicted player (2,679 of 2,679) has output rows equal to its `num_frames_output`. Output horizons run from 5 to 94 frames (median 10).

**Limits.** The inputs end before the throw, and post-throw positions exist only as labels for predicted players. So this is the conditional post-throw benchmark (directive A), not full-play tracking, and it cannot support a free-snap simulation claim. Whether frame 1 is the snap, and where the last input frame sits relative to ball release, is the competition's stated design. It is not verified here. The labels' missingness and the other weeks' label checks are not done.

**Reproduce.** `KAGGLE_API_TOKEN=... python3 scripts/fetch_bdb2026_tracking.py`, then `sha256sum -c` against `SHA256SUMS.txt`.

## Supplement: independent LP DB check, 2026-10-23

Source: gridiron-physics `research/m4d-str-contact-diagnosis` at `5790c8e992c0d01fc63e2068af2fa24a6e4b16b0`, file `research/physics-3d-evaluation/m4b/m4d/football-tracking-feasibility/LP-DB-SUPPLEMENT-2026-10-23.md`, sha256 `f74569bf86f9deff1616285e06eb24d55cb7e78ed755e88b5aa2cc20df1cb62c` (checked against the commit). Written by the 3D M4d agent. It does not repeat the Kaggle search.

Re-verified here, read-only, from `/root/legendarypicks` at `cdc32344`:

| Table | Rows (supplement = re-check) | Positional fields |
| --- | --- | --- |
| `nfl_pbp` | 753,668 = 753,668 | none: no x/y, frame or time, speed, orientation, or tackler ID |
| `nfl_hist_participation` | 478,989 = 478,989 | none |
| `nfl_hist_ftn_charting` | 185,215 = 185,215 | none |

Column lists match the supplement.

**Caveat, database hash.** The supplement records sha256 `54998d153e9d67a17821f8a5adfbf69b73adc7a9f138d7f1bb49b3ef5e288aa9` at 3,227,590,656 bytes. At this check `backend/data/picks.dev.db` was 3,227,607,040 bytes, mtime 23:09, sha256 `04d05e7eb22daff3a1b24a3e3f973860060f6023a42fe03fbf62c826fac7706c`. The file is live and was written after the supplement's inspection, so the recorded hash is stale. Row counts and columns are unchanged, so the conclusion stands. Future reproductions should record size and hash at the time they run.

**Conclusion (unchanged).** None of the three tables carries frame-level trajectories or tackler IDs. They cannot ground a physical tackle replay.

## Rights

The user stated on 2026-10-23 that the rights are already in place, and asked that the permitted-use assessment be set aside. Not verified against a licence text. Recorded as user-reported.

## Consequence for the directive

1. **Full-play, from-snap tracking:** not present in the 2026 prediction data. Inputs end at a last frame of 9–74, and labels cover predicted players only. The 2025 cohort is staged from an unofficial GitHub copy (see the 2025 section).
2. **Narrow fallback (2026 Big Data Bowl throw-to-arrival):** feasible. Inputs and labels for 2023 weeks 1–7 are downloaded and joined (below). Scoring against labels is the conditional post-throw benchmark only.
3. **Blocker resolved 2026-10-23:** the user accepted the competition rules and downloads succeeded. The 2025 cohort is staged from an unofficial GitHub copy (see the 2025 section).

## Fields the directive requires, status

Coverage, timestamp cadence, snap/throw/terminal events, orientation, missingness and source keys: verified for the 2026 prediction inputs and labels, weeks 1–7, in the section below. Snap and terminal events are **not verified** (the competition's event definitions were not read here). Team/field orientation is not normalised in these files. Other fields: not verified.

## Reproduce

```sh
find /root /data /srv /mnt /home /opt /var/lib -xdev \( -iname "*tracking*" -o -iname "*bigdatabowl*" -o -iname "*big-data-bowl*" -o -iname "plays.csv" -o -iname "games.csv" \) 2>/dev/null
python3 -c "import sqlite3; c=sqlite3.connect('file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro', uri=True); print([r[1] for r in c.execute('pragma table_info(nfl_pbp)')])"
```
