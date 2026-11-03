# Phase 1: data inventory and play identity

Inventory date: 2026-11-03. The dev database was opened read-only with SQLite `query_only` enabled (schema version 433). Counts below describe the database snapshot recorded in the accompanying JSON artifact; they are not live counts.

## Reproduction

Run from the research worktree. The first command produces the coverage, schema, exact-join, field-coverage, key-quality, raw-label, provenance, and signature counts in this report. The second compares the local raw `pass_length` field with regular-season pass rows in the dev database.

```bash
python3 research/nfl-playbook-ancestry/phase1_inventory.py --db /root/legendarypicks/backend/data/picks.dev.db --out research/nfl-playbook-ancestry/phase1_inventory_dev_2026-11-03.json
```

```bash
python3 research/nfl-playbook-ancestry/phase1_pass_length_check.py --db /root/legendarypicks/backend/data/picks.dev.db --parquet-dir /root/lp-snapshots/nfl-backfill-2026-10-27/raw/pbp --out research/nfl-playbook-ancestry/phase1_pass_length_dev_vs_raw_2026-11-03.json
```

## Coverage measured

The play-by-play table contains regular-season rows only for these seasons. Participation and FTN charting include regular-season and postseason games. Snap-count rows are player-week records, not per-play participation.

| Season | PBP rows / games / weeks | Participation rows / games | FTN rows / games | Snap-count rows / weeks |
|---|---:|---:|---:|---:|
| 2022 | 47,157 / 271 / 1–18 | 50,150 / 284 | 41,643 / 284 | 0 / — |
| 2023 | 47,399 / 272 / 1–18 | 46,168 / 285 | 48,225 / 285 | 0 / — |
| 2024 | 47,274 / 272 / 1–18 | 45,919 / 285 | 48,031 / 285 | 25,357 / 1–18 |
| 2025 | 46,452 / 272 / 1–18 | 45,184 / 285 | 47,316 / 285 | 25,344 / 1–18 |
| 2026 | 21,191 / 121 / 1–8 | 0 / 0 | 0 / 0 | 11,252 / 1–8 |

The 2022–25 PBP total is 188,282 rows across 1,087 regular-season games. Schedule joins classify all PBP games as `REG`. Participation and FTN each cover 13 postseason games per season in addition to regular-season games. The 2026 tables currently provide PBP and weekly snap counts, with no participation or FTN rows.

## Exact joins and key quality

Joins use each source's game ID and native play ID, with no fuzzy matching. All three audited tables have zero null join keys and zero duplicate source game/play key pairs in each covered season. The PBP play IDs are stored as SQLite real values but are integer-valued; SQLite numeric equality was used for the exact joins.

On 2022–25 PBP run/pass rows, participation matched 134,138 of 134,138 rows. FTN matched 134,044 of 134,138. Its only run/pass misses are 94 rows in 2022: 69 pass and 25 run. FTN matched every run/pass row in 2023–25. Other full-event unmatched rows are null `play_type` or `no_play` rows (plus non-scrimmage types), and remain distinct from missing source records.

## Fields and their identity limits

| Field family | Available fields and source | What the fields support |
|---|---|---|
| Formation and personnel | `offense_formation`, `offense_personnel` in `nfl_hist_participation` | Recorded presentation labels and personnel strings. They do not identify an underlying route or play concept. Preserve original values and nulls. |
| Run/pass action descriptors | `run_gap`, `run_location`, `pass_location`, `air_yards` in `nfl_pbp` | Coarse execution or outcome descriptors. `air_yards` is not a route tree or named concept. |
| Motion and broad tags | `is_motion`, `is_play_action`, `is_screen_pass`, `is_rpo`, `is_trick_play`, `is_qb_sneak` and related context in `nfl_hist_ftn_charting` | Literal charted attributes where the source row joins; these are not exact design labels. |
| Play or concept name; route | No such field was found in the audited database schema. | These data cannot establish exact play identity or route ancestry by themselves. |
| Pass length | `pass_length` in local raw PBP parquet, not in the dev DB schema | A short/deep bucket, not a route or named concept. The supplemental exact-key audit found no raw-only or dev-only regular-season pass keys in 2022–25. |

The exact-key `pass_length` comparison covered 77,022 regular-season passes: 58,422 short, 12,929 deep, and 5,671 null. Per-season counts are 2022: 14,866 / 3,140 / 1,387; 2023: 14,937 / 3,310 / 1,488; 2024: 14,470 / 3,270 / 1,413; 2025: 14,149 / 3,209 / 1,383 (short / deep / null).

For the 134,138 historical run/pass rows, field coverage is: run gap 41,942; run location 56,534; pass location 71,351; air yards 71,352; formation 133,922; personnel 134,138. An FTN source row joins on 134,044 rows, including the motion and play-action fields. These are availability counts; null field values remain null and are not imputed.

The 2022 formation vocabulary includes `SHOTGUN`, `SINGLEBACK`, `EMPTY`, `I_FORM`, `PISTOL`, `JUMBO`, and `WILDCAT`; in 2023–25 the observed labels include `SHOTGUN`, `UNDER CENTER`, and `PISTOL`. This is a raw source-vocabulary difference and has not been harmonized. Personnel strings also change encoding: the common 2022 form is `1 RB, 1 TE, 3 WR`, while 2023–25 strings commonly enumerate offensive-line roles and quarterback, such as `1 C, 2 G, 1 QB, 1 RB, 2 T, 1 TE, 3 WR`. Distinct non-null raw personnel labels on run/pass rows are 89, 281, 274, and 257 in 2022–25.

OL6 was kept as a raw-field screen, not turned into a normalized personnel class: 998 matched 2022 run/pass rows have the literal `6 OL` label; the 2023, 2024, and 2025 raw C/G/T-token screen identifies 877, 973, and 1,786 rows with at least six such tokens. The original source strings remain authoritative. Raw personnel strings also include 31, 28, 23, and 15 rows with K/LS/P tokens in 2022–25. Special-teams and exceptional PBP types remain separate: 2022–25 includes 28,636 kickoff, punt, field-goal, and extra-point rows; 2026 includes 3,223. `no_play`, null `play_type`, kneels, and spikes were not relabeled as run/pass concepts.

## Hierarchical observed signatures

The reproducible signatures retain the source execution key, event fields, raw presentation values and source-join state, coarse action descriptors, and broad FTN tags. Context and outcome fields (hash, QB location, box/backfield counts, rushers, and air yards) are retained as attributes outside signature equality. Missing values remain distinct from an absent source join. Every concept ID remains null/unresolved.

| Season | Run/pass rows | Unique event tuples | Presentation tuples | Action tuples | Broad chart-tag tuples | Combined observed tuples |
|---|---:|---:|---:|---:|---:|---:|
| 2022 | 33,770 | 6 | 589 | 11 | 11 | 2,828 |
| 2023 | 33,957 | 6 | 1,334 | 12 | 11 | 5,185 |
| 2024 | 33,470 | 6 | 1,498 | 11 | 9 | 5,943 |
| 2025 | 32,941 | 6 | 1,296 | 13 | 12 | 5,035 |
| 2026 | 14,910 | 6 | 4 | 11 | 1 | 68 |

Each tuple count includes unknown values and represents equality of recorded fields only. It is not a count of distinct plays or concepts. In particular, 2026's much smaller presentation and combined tuple counts reflect the absence of per-play participation and FTN charting, so they are not directly comparable with 2022–25.

The local decision-layer inspection confirms that some existing features use role and execution/context categories (including short/deep pass length); these remain descriptors rather than exact concept IDs. The handoff's reference to `formal_playcall.py` was not confirmed in the local source search. No SLC model files were changed.

## Provenance and limits

The load manifest contains 12 entries for 2022–25 participation, FTN charting, and snap counts; each entry's source-file row count matches its stored-row count. The PBP table has no per-season entry in that manifest. Its in-repository producer is `backend/ingest_nfl_pbp_logs.py`, so per-season PBP source hashes are not established by this inventory.

All external claims in the handoff remain **unverified**. This phase did not check the cited articles, interviews, or statistics against their original sources. No play names or concepts have been inferred from the available fields. The six-phase research plan remains intact; only Phase 1 is marked complete.
