# NHL JC-DIAG8: cross-game identity feasibility

verified_cross_game_identity_source = none. The pair-identity question is closed permanently on this source.

This is a data-availability finding on ten inspected development games, not an independent evaluation. The DIAG7 Step 0 correction at `docs/research/NHL-JC-DIAG7-REPORT-2026-10-23.md` corrected the interpretation of its structural-zero intervals; DIAG8 applies that evidentiary framing. No network, provider, or database was accessed.

Source base: `e67c23f2ab65c4ae58498c58f4e6ef148c2dcef7`. Step 0 correction: `e9806e61d2e252a4d55eb7da85fe74c7993b4795`. Preregistration: `a834d153bf42f794079f9fb08c0b82fc4e6a44cd`.

## Provenance gate

**PASS** — 114/114 assertions. DIAG7 pinned result was 76,326 bytes; its 17 inherited source hashes were checked against disk. The source-release manifest's 54 assets and all three pinned movement-data artifacts were hash/size checked before Q1.

## Identity fields and semantics

Fields below are the union observed in DIAG7 player objects, the full normalized observation stream, the 200 rollout starts, and the archived scenarios.

| Observed player-object field | Local meaning / evidence | Stable athlete key across games? |
|---|---|---|
| `coordinate_missing` | Derived inverse of coordinate validity. | Not an athlete identifier |
| `coordinate_valid` | Whether source XY coordinates passed the local validity check. | Not an athlete identifier |
| `heading_rad` | Heading derived from past displacement. | Not an athlete identifier |
| `history` | Prior observed position history; not a person identifier. | No |
| `id` | Composite `game|period|team|raw_id` built by `prepare_movement_data.py`; scoped to game/period. | No; scoped composite |
| `identity_conflict` | Local quarantine flag for conflicting source identity mapping. | Not a persistent identity key |
| `jersey` | Source `Player Jersey Number`; recurring values are possible. | No; recurrence is not identity evidence |
| `kind` | Player/puck record type. | Not an athlete identifier |
| `past_displacement` | Displacement derived from past observations. | Not an athlete identifier |
| `past_kinematic_state` | Kinematic features derived from past observations. | Not an athlete identifier |
| `player_id_source` | Copied source `Player Id`; local track/actor ID. | No; local track identity |
| `raw_id` | Source `Player Id`; the kinematics report documents it as game/period-scoped. | No; local track identity |
| `row_visible` | Source row was present in the observation. | Not an athlete identifier |
| `team` | Anonymized source team or within-game Home/Away label. | No |
| `track_id` | Generated composite `game|period|team|raw_id`; scoped to game/period. | No; scoped composite |
| `visibility_confidence` | Confidence metadata; source value is unknown. | Not an athlete identifier |
| `x` | Rink X coordinate. | Not an athlete identifier |
| `y` | Rink Y coordinate. | Not an athlete identifier |

Raw event identity/game-context columns: `Away_Team`, `Date`, `Home_Team`, `Player_Id`, `Player_Id_2`, `Team`. Raw shift columns: `Away_Team`, `Date`, `Home_Team`, `Player_Id`, `Team`. Raw tracking columns: `Player Id`, `Player Jersey Number`, `Player or Puck`, `Team`. `Image Id` is separately recognized as an ordered observation identifier, not an athlete or canonical game identity. The local release bundle has no data dictionary defining these player IDs as persistent across games.

Among player-level fields, jersey is the only exposed human-facing label that could plausibly recur for the same person; it is not stable or unique identity evidence. Game labels are dates plus anonymized team labels; there is no NHL game ID or direct track-to-NHL-ID crosswalk.

Local documentation: the ten games are described as anonymized in `docs/research/NHL-TEN-GAME-KINEMATICS-REPORT-2026-10-22.md`; it states: “The release's `Player Id` is retained only as a game/period-scoped tracking identity; it is not merged across games or treated as a verified athlete identity.”

### Track-ID and jersey collision check

`id` is a non-numeric composite, so it has no numeric interval; its exact cross-game intersection is 0/45 game pairs by construction because its key embeds the game. `raw_id` numeric intervals overlap in 45/45 pairs; exact numeric values intersect in 45/45, and exact source-string values intersect in 45/45. Numeric jersey field values recur in 45/45 game pairs; raw field labels recur in 45/45. Non-numeric values are retained as raw labels and not assigned jersey semantics. These are collision diagnostics only; neither ID nor jersey recurrence is an identity match.

| Game | Numeric raw_id min–max | Distinct raw IDs | Composite id count | Raw Player Jersey Number field values |
|---|---:|---:|---:|---|
| 2025-10-11.Team.A.@.Team.D | 1–15132 | 3581 | 4169 | 3, 5, 8, 9, 12, 14, 17, 20, 25, 28, 29, 30, 32, 36, 37, 39, 42, 44, 45, 46, 48, 50, 51, 52, 59, 61, 63, 71, 72, 75, 77, 79, 84, 85, 88, 92, Go |
| 2025-10-17.Team.F.@.Team.L | 1–12481 | 3581 | 3847 | 1, 3, 4, 6, 8, 10, 11, 14, 15, 16, 17, 18, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 34, 36, 38, 42, 43, 46, 48, 72, 93, Go |
| 2025-10-24.Team.B.@.Team.A | 1–11520 | 3011 | 3404 | 1, 3, 8, 12, 14, 15, 17, 19, 20, 21, 26, 27, 29, 34, 37, 45, 46, 47, 48, 52, 55, 58, 59, 60, 61, 71, 72, 73, 78, 81, 86, 89, 90, 92, Go |
| 2025-10-24.Team.E.@.Team.D | 1–12880 | 2369 | 2557 | 2, 5, 6, 7, 8, 10, 11, 12, 15, 16, 18, 19, 21, 22, 25, 28, 31, 32, 36, 37, 38, 39, 42, 44, 46, 50, 51, 52, 59, 74, 75, 77, 78, 84, Go |
| 2025-10-28.Team.C.@.Team.A | 1–12198 | 2863 | 3200 | 2, 3, 6, 11, 14, 15, 17, 18, 19, 20, 21, 22, 26, 29, 36, 37, 39, 41, 44, 45, 46, 48, 50, 52, 56, 61, 72, 73, 92, Go |
| 2025-10-29.Team.G.@.Team.L | 1–9705 | 3431 | 3729 | 1, 2, 3, 4, 5, 7, 10, 11, 12, 13, 14, 16, 17, 18, 19, 20, 21, 24, 25, 26, 27, 28, 29, 32, 34, 36, 40, 41, 43, 44, 45, 47, 92, Go |
| 2025-11-02.Team.D.@.Team.A | 1–11939 | 2961 | 3281 | 3, 8, 9, 12, 14, 17, 21, 25, 28, 29, 32, 36, 37, 39, 42, 45, 46, 48, 51, 52, 53, 56, 59, 63, 71, 72, 73, 74, 75, 77, 78, 84, 85, 88, 89, 92, Go |
| 2025-11-16.Team.H.@.Team.K | 1–10861 | 2304 | 2452 | 1, 2, 3, 5, 8, 10, 11, 12, 13, 14, 16, 17, 18, 19, 20, 21, 22, 23, 25, 26, 32, 33, 34, 38, 42, 45, 49, 53, 62, 63, 67, 68, 75, 78, 92, 93, Go |
| 2025-11-19.Team.I.@.Team.K | 1–9706 | 3471 | 3710 | 3, 4, 11, 14, 19, 21, 22, 23, 25, 26, 27, 28, 31, 33, 34, 37, 38, 41, 42, 45, 47, 51, 53, 56, 58, 62, 63, 65, 67, 68, 75, 77, 78, 81, 92, 93, Go |
| 2025-11-28.Team.J.@.Team.K | 1–11160 | 1962 | 1963 | 5, 6, 8, 12, 13, 15, 18, 19, 22, 23, 25, 26, 30, 31, 32, 33, 36, 38, 41, 42, 43, 45, 47, 50, 53, 58, 62, 63, 65, 67, 68, 75, 76, 77, 78, 82, 88, 92, Go |

## Candidate local sources

Inspected 57 identity-source candidates: 53 raw Stathletes Events/Shifts/Tracking files and 4 repository identity/sample files. The local research-data inventory covered 69 files (1,586,547,032 bytes). The source-release manifest (`/root/lp-research-data/stathletes-big-data-cup-2026/download-manifest.json`, SHA-256 `6ca13bfa3503d9a86b7dde9589aba4988fd5e9599318e0b97f2f84e94cfcb437`) pins all 54 downloaded assets; the separate camera-orientation file is not an identity-source candidate.

| Candidate path | SHA-256 | Data rows / unit | Frozen-game coverage | Documented persistent athlete ID + game ID + direct tracking link? |
|---|---|---:|---|---|
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-11.Team.A.@.Team.D.Events.csv` | `36a9728df4f4c4988e5077a3c6dfb8ba7c570b5e52444f879d2d977e9b131ab7` | 1878 CSV data records excluding header | 2025-10-11.Team.A.@.Team.D | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-11.Team.A.@.Team.D.Shifts.csv` | `69f5b6a8875900cb644f802007297f238ef000e7316ceceb8013f1ddf8089265` | 748 CSV data records excluding header | 2025-10-11.Team.A.@.Team.D | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-11.Team.A.@.Team.D.Tracking_P1.csv` | `1be4697eba033349ff48baaa4e7a178ce2def8aa0698ac82cc9aaa38697585d6` | 331871 CSV data records excluding header | 2025-10-11.Team.A.@.Team.D | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-11.Team.A.@.Team.D.Tracking_P2.csv` | `200d60e4637681e686d2ce19facdd541bdbbfa6e670e9f839bb7f414d4566943` | 311241 CSV data records excluding header | 2025-10-11.Team.A.@.Team.D | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-11.Team.A.@.Team.D.Tracking_P3.csv` | `5a3f1726f3e625daf728048fabb39e40fc9ff85afff005414ff3b0a2a97d6a31` | 305961 CSV data records excluding header | 2025-10-11.Team.A.@.Team.D | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-17.Team.F.@.Team.L.Events.csv` | `b6a26edbbd235328041e8338ba5737a485d5490644e0a4e41f7598b374975f15` | 1931 CSV data records excluding header | 2025-10-17.Team.F.@.Team.L | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-17.Team.F.@.Team.L.Shifts.csv` | `693a894ca1960fc720c70a0e4319a0627407edc865d2a6eef288e98f6210d8fd` | 759 CSV data records excluding header | 2025-10-17.Team.F.@.Team.L | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-17.Team.F.@.Team.L.Tracking_P1.csv` | `fa657f46b963176d2cafb2a53c648224716bcce8293b96b7266ecaffe90b0675` | 287322 CSV data records excluding header | 2025-10-17.Team.F.@.Team.L | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-17.Team.F.@.Team.L.Tracking_P2.csv` | `54951f1b8e90b1fe8564851f49cbdde8e935756a1efda68951f47bec36c3cf58` | 289873 CSV data records excluding header | 2025-10-17.Team.F.@.Team.L | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-17.Team.F.@.Team.L.Tracking_P3.csv` | `4eb4599896f7631ee02119aa9b369662c65d6c106b103b95c9e8975ad60728b3` | 267314 CSV data records excluding header | 2025-10-17.Team.F.@.Team.L | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-24.Team.B.@.Team.A.Events.csv` | `7c27ebc2478d3afcb8f8f7e8bc64e434b6ecda8a472477f7796fe5d879d1666f` | 1949 CSV data records excluding header | 2025-10-24.Team.B.@.Team.A | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-24.Team.B.@.Team.A.Shifts.csv` | `7b5e79767d0d6a6e12582c1ca16149b7bc08fede8d508e4d2cb79e0671765476` | 907 CSV data records excluding header | 2025-10-24.Team.B.@.Team.A | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-24.Team.B.@.Team.A.Tracking_P1.csv` | `a8dda4a69bdc8de3c4fe57a04e3fd4401a32f240dfb7c9aa070212636f053bcc` | 322891 CSV data records excluding header | 2025-10-24.Team.B.@.Team.A | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-24.Team.B.@.Team.A.Tracking_P2.csv` | `3d55d095789abb4bf5e5a675efdfc5ab68c25682f95299eebc7d4d6993862785` | 310424 CSV data records excluding header | 2025-10-24.Team.B.@.Team.A | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-24.Team.B.@.Team.A.Tracking_P3.csv` | `2417cb5576635c4dcb1f8c7dd873ebdc786e3850e982491fe01ab4f04082a4dd` | 328154 CSV data records excluding header | 2025-10-24.Team.B.@.Team.A | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-24.Team.E.@.Team.D.Events.csv` | `45d162c4d1a9241699f71ce65e8b360afee4809e9e8f25ea9f5fb56e8445dfb3` | 1914 CSV data records excluding header | 2025-10-24.Team.E.@.Team.D | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-24.Team.E.@.Team.D.Shifts.csv` | `da4abff2e3f3b713d4d8fe03471b43dba2a60b515cd15dd1456815958920d1c9` | 722 CSV data records excluding header | 2025-10-24.Team.E.@.Team.D | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-24.Team.E.@.Team.D.Tracking_P1.csv` | `22ac34023b80a84c27e7471e2d3f7ca314ba67870896be5132aaf913a5b6a5f8` | 317533 CSV data records excluding header | 2025-10-24.Team.E.@.Team.D | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-24.Team.E.@.Team.D.Tracking_P2.csv` | `10268944442f8872ae57f8ec20c65ba004fbaa707d551723acf346f0be6e8086` | 225742 CSV data records excluding header | 2025-10-24.Team.E.@.Team.D | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-24.Team.E.@.Team.D.Tracking_P3.csv` | `08beb9b7be335010043390bd326c63db2efd0d4250676a02c35725e90ef4ec11` | 59699 CSV data records excluding header | 2025-10-24.Team.E.@.Team.D | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-24.Team.E.@.Team.D.Tracking_POT.csv` | `b6232a88c20cff1872a1c34a7de79c24a9685da9ce0d3fdee8b80e2d3bd065b2` | 56187 CSV data records excluding header | 2025-10-24.Team.E.@.Team.D | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-28.Team.C.@.Team.A.Events.csv` | `d22dfd636d04e8ee581c59183bbfa34c422d00ba7192822591c03cf9001032cc` | 1943 CSV data records excluding header | 2025-10-28.Team.C.@.Team.A | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-28.Team.C.@.Team.A.Shifts.csv` | `6de682dc7304d3039c73201daddabf50a291949adda753fe6e5f2e63997d6378` | 731 CSV data records excluding header | 2025-10-28.Team.C.@.Team.A | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-28.Team.C.@.Team.A.Tracking_P1.csv` | `74b18219161db70f0d512bd27bf8e39e6a11e08c0fcc2b84452e03f61a2cb809` | 321899 CSV data records excluding header | 2025-10-28.Team.C.@.Team.A | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-28.Team.C.@.Team.A.Tracking_P2.csv` | `87fdcc98a193af534b8628ec2dc2fcdb99b722dd527bca2ee3dd244e697eec42` | 311045 CSV data records excluding header | 2025-10-28.Team.C.@.Team.A | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-28.Team.C.@.Team.A.Tracking_P3.csv` | `e955a8abaa3015118f2e8fa25e4e1cc1e686436aa45fe3a2e99ee8151127681a` | 310870 CSV data records excluding header | 2025-10-28.Team.C.@.Team.A | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-29.Team.G.@.Team.L.Events.csv` | `e351f5010ff9c4434de490de0b3f9ddc81f2e0b712a4e6341c5c9a4361ecd9ce` | 1878 CSV data records excluding header | 2025-10-29.Team.G.@.Team.L | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-29.Team.G.@.Team.L.Shifts.csv` | `b433f3bd8c4f3be1cf74ef96b95bee6fa3c4c8c5512864e949d4c5e693e21285` | 925 CSV data records excluding header | 2025-10-29.Team.G.@.Team.L | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-29.Team.G.@.Team.L.Tracking_P1.csv` | `89c40c203d6d764dedb85e0bc4d72f0a783239695e2039e07fd61c1e62b83bfb` | 302762 CSV data records excluding header | 2025-10-29.Team.G.@.Team.L | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-29.Team.G.@.Team.L.Tracking_P2.csv` | `9bbb5b74798cf338b2f1cd07dbd978a030c6856a1413f1481b99a40da8ce3898` | 297746 CSV data records excluding header | 2025-10-29.Team.G.@.Team.L | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-10-29.Team.G.@.Team.L.Tracking_P3.csv` | `3e25f0a0daebd0ddddd0a09d84da269fcf5de2bf4c6bedc3dd21ed95067ac4d7` | 304454 CSV data records excluding header | 2025-10-29.Team.G.@.Team.L | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-11-02.Team.D.@.Team.A.Events.csv` | `5a413d1c799d040b5e80debc178053ce0e6b6472354900d5dc1255059e5265d1` | 1860 CSV data records excluding header | 2025-11-02.Team.D.@.Team.A | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-11-02.Team.D.@.Team.A.Shifts.csv` | `257966d57aedafd90f6f389bfef1fe8287cc2cb6357f5a945562e6c0fcda5ba3` | 715 CSV data records excluding header | 2025-11-02.Team.D.@.Team.A | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-11-02.Team.D.@.Team.A.Tracking_P1.csv` | `4e690de981053466906864005c56be0bd48e98924415aa49f184529faa7c5206` | 312079 CSV data records excluding header | 2025-11-02.Team.D.@.Team.A | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-11-02.Team.D.@.Team.A.Tracking_P2.csv` | `3cba41bfbaec873982ca21ea30a47fc063d07dbcfc931b9a8640b4efc9e21446` | 318160 CSV data records excluding header | 2025-11-02.Team.D.@.Team.A | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-11-02.Team.D.@.Team.A.Tracking_P3.csv` | `7cc12b5afc6bd6b919d3671d4d34158cc882c4c28d348e6f9515b79b055e6fe2` | 308717 CSV data records excluding header | 2025-11-02.Team.D.@.Team.A | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-11-16.Team.H.@.Team.K.Events.csv` | `1e0c57fbf142b687a4ca69f715e97324380e0813d07967a1b58eb17db8654b55` | 1963 CSV data records excluding header | 2025-11-16.Team.H.@.Team.K | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-11-16.Team.H.@.Team.K.Shifts.csv` | `a634f7c6125d2fe111aa9fdaf5593dc50fcd1500e34b76fad1ed9ea26f49c974` | 847 CSV data records excluding header | 2025-11-16.Team.H.@.Team.K | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-11-16.Team.H.@.Team.K.Tracking_P1.csv` | `9e88b07e8a2f7da64f21c31ef85b3f781f2d1013c0c4e7b12ebcf4982574f1c0` | 260127 CSV data records excluding header | 2025-11-16.Team.H.@.Team.K | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-11-16.Team.H.@.Team.K.Tracking_P2.csv` | `70523e278c4f32f44e8d1521e4e7e8c43d500c761236498bd6e1dca2cc3c2695` | 260234 CSV data records excluding header | 2025-11-16.Team.H.@.Team.K | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-11-16.Team.H.@.Team.K.Tracking_P3.csv` | `932a209d8630dd42d8cc327cd24c386acf9bd557f0a6aa50da724ed7af007d63` | 15486 CSV data records excluding header | 2025-11-16.Team.H.@.Team.K | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-11-16.Team.H.@.Team.K.Tracking_POT.csv` | `2e1d6a76b7f4086effd0b9602f7fbcf782408eec3e01710aa8847af30d5d14d1` | 53619 CSV data records excluding header | 2025-11-16.Team.H.@.Team.K | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-11-19.Team.I.@.Team.K.Events.csv` | `076ee0bec327ba8ee0c4e9d6abf518d28b6ab9b4341a4f522089972ab3950087` | 1933 CSV data records excluding header | 2025-11-19.Team.I.@.Team.K | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-11-19.Team.I.@.Team.K.Shifts.csv` | `c9a709b79a0f22f9a97611b1f15334fb45d6414021801bd830fbb32d8e84ad21` | 780 CSV data records excluding header | 2025-11-19.Team.I.@.Team.K | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-11-19.Team.I.@.Team.K.Tracking_P1.csv` | `189a1e9353c9e9317cb85842c0634d94abacb5193c5cd3b46fad4bc27d589505` | 312154 CSV data records excluding header | 2025-11-19.Team.I.@.Team.K | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-11-19.Team.I.@.Team.K.Tracking_P2.csv` | `13ea6955980d94f4c7d1ca0b29f380834225556217361a3325a120de3da78fb5` | 302040 CSV data records excluding header | 2025-11-19.Team.I.@.Team.K | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-11-19.Team.I.@.Team.K.Tracking_P3.csv` | `9640caef245b5f07a44a4550709eedf2bd4c50532c7dd9d63023f4868dd7a8df` | 319152 CSV data records excluding header | 2025-11-19.Team.I.@.Team.K | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-11-28.Team.J.@.Team.K.Events.csv` | `3fe466d4273da466cdb377bb7b0c97b9511b67a4cb7895ab07ea6b51e715cf93` | 1951 CSV data records excluding header | 2025-11-28.Team.J.@.Team.K | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-11-28.Team.J.@.Team.K.Shifts.csv` | `7137be5fea7679e724b014ab3de6f668ec75829f9e7ac78253b49cef2a50a0f3` | 727 CSV data records excluding header | 2025-11-28.Team.J.@.Team.K | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-11-28.Team.J.@.Team.K.Tracking_P1.csv` | `b469489e83ca98925ca011d25ac113e7e851932d3a837e3766fe9cc3a743fab2` | 307081 CSV data records excluding header | 2025-11-28.Team.J.@.Team.K | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-11-28.Team.J.@.Team.K.Tracking_P2.csv` | `5691dd0f4f3ac16e558535cd40b35f5e3dcb4b7a634c8d19a9c3b657c9f004a9` | 305057 CSV data records excluding header | 2025-11-28.Team.J.@.Team.K | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-11-28.Team.J.@.Team.K.Tracking_P3.csv` | `fd67da0405ec9e3bc543ca2c509602f00ad81c9509946f050c2caffe97c5d2d5` | 54922 CSV data records excluding header | 2025-11-28.Team.J.@.Team.K | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-research-data/stathletes-big-data-cup-2026/2025-11-28.Team.J.@.Team.K.Tracking_POT.csv` | `d3b47a2b573910a22aedb2dbb6095064b877889fd50ee32d534a2e3c3452d1a1` | 9786 CSV data records excluding header | 2025-11-28.Team.J.@.Team.K | No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk. |
| `/root/lp-nhl-multi-agent-movement-2026-10-23/backend/data/published-identity-names.json` | `1b23121b0b3919dc38c301fc1e74d72c94115bd75e3903aa9ebac2c1b731b6b2` | 1038 NHL publisher ID-to-name entries | none verified | No: athlete field `nhl_id`; game field `none`; direct track link: no. Publisher NHL ID/name snapshot; has no game key or documented mapping from anonymized tracking IDs to nhl_id. |
| `/root/lp-nhl-multi-agent-movement-2026-10-23/backend/data/name-aliases.json` | `e9a28cbc29b989d79809f2d75950088c2dd4ca81e4d1305aa5e42f43d19ed65e` | 12 NHL alias mapping entries | none verified | No: athlete field `none`; game field `none`; direct track link: no. Name-alias maintenance data; not a game roster or tracking-ID crosswalk. |
| `/root/lp-nhl-multi-agent-movement-2026-10-23/backend/data/identity-consolidations.jsonl` | `d0ad93020e7ba814e24dbe84634b4dcdc669963d6acc5f1cf1c89cfe539e308f` | 3 JSONL consolidation records | none verified | No: athlete field `none`; game field `none`; direct track link: no. Repository identity consolidation log has no NHL game-level tracking crosswalk. |
| `/root/lp-nhl-multi-agent-movement-2026-10-23/backend/data/sample_data.json` | `d6e68d47145171777bb308de11b2bfe0faa14a9790cbadfb2754bd4e7d3f9006` | 1 NHL sample fixture games | none verified | No: athlete field `none`; game field `none`; direct track link: no. Synthetic/sample game fixture, not an external roster or tracking identity source. |

No local roster/boxscore/gamebook or official NHL play-by-play file was found that supplies a direct mapping from these anonymized track IDs to persistent athlete IDs and source game IDs. The NHL publisher identity snapshot contains `nhl_id` plus names, but not the required game key or tracking crosswalk. Names, jersey matches, dates/team similarities, and numeric track-ID collisions were not used as joins.

`verified_cross_game_identity_source = none`.

## Q2 — not applicable

All 2,164 +45 pairs remain unmatched (100%); all 10 games are unmatched; each of the four frozen bins has 541/541 unmatched pairs (100%). The count retaining at least two LOOG training observations is not applicable and was not estimated.

## Decision

Registered reading applied (verbatim):

> `verified_cross_game_identity_source = none` → **the pair-identity question is closed permanently on this source.** No further diagnostics on these ten games; any resumption requires new data acquisition (an identity-bearing roster/boxscore feed or a tracking vendor with persistent athlete IDs), and that acquisition is a data question, not a modelling one.

This closes the identity question only for this source and these inspected games. DIAG2–DIAG6 persistence remains descriptive; this is not an independent evaluation.

## Reproduction

`OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 /usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/diagnose_jc_diag8_identity_feasibility.py`

`OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 /usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/diagnose_jc_diag8_identity_feasibility.py --output /tmp/jc-diag8-identity-feasibility-repeat.json --no-report`

Checks: `ast.parse`; `git diff --check`; deterministic rerun and `cmp` against the committed JSON.

Primary runtime: 173.682 seconds. Evaluator SHA-256: `70a4f43ecceceff885d342f600041aeb57f7b4e1d93a3381110f3ef9fc6844b6`. Result SHA-256: `5a7342f6ef63169b42390bf08ae3c216298bf45c649b8e414fddd8c6a61a34a8`; byte count: 1547298.
