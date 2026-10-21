# NHL V3 Phase 1 deterministic replay report

**Base:** `33c6b8fad5c36fd7749557c6b56bb21898e33135`

**Input schema:** approved full-frame event schema v1.

**Scope:** research only; no model fitting, probabilities, ROI evaluation, production writes, or historical source edits.

## Replay result

The source-pinned replay processed **4,876/4,876** games and **1,510,104/1,510,104** PBP events in publisher sort order. Full raw body verification succeeded for **4,876/4,876** PBP bodies and **4,876/4,876** shift bodies, including compressed/decompressed hashes, source ID, JSON shape, and payload count.

Accepted team scores: **4,876/4,876 exact**.

Accepted team SOG: **4,814/4,814 exact**; **62** games remain quarantined by the audited component disposition. IDs: `2018020090`, `2018020173`, `2018020276`, `2018020359`, `2018020414`, `2018020458`, `2018020541`, `2018020751`, `2018020952`, `2018020993`, `2018021130`, `2018021256`, `2019020016`, `2019020024`, `2019020092`, `2019020103`, `2019020109`, `2019020176`, `2019020195`, `2019020372`, `2019020575`, `2019020615`, `2019020670`, `2019020776`, `2019020809`, `2019020873`, `2019020876`, `2019020894`, `2019020993`, `2020020020`, `2020020056`, `2020020068`, `2020020220`, `2020020398`, `2020020414`, `2020020417`, `2020020444`, `2020020494`, `2020020702`, `2020020773`, `2021020219`, `2021020319`, `2021020345`, `2021020368`, `2021020443`, `2021020478`, `2021020620`, `2021020704`, `2021020744`, `2021020752`, `2021020811`, `2021020837`, `2021020919`, `2021020933`, `2021020971`, `2021021070`, `2021021106`, `2021021119`, `2021021267`, `2021021292`, `2022020158`, `2022020276`.
Ordinary shot attempts: **551,737**. Replayed ordinary SOG events: **304,611**. Ordinary goals: regulation **28,646**, overtime **715**. Shootout attempts **2,604** and shootout goals **812** remain separate from ordinary counts.

| Period type | Goals | Shot-on-goal events | Missed-shot events | Blocked-shot events | Shot-family rows |
|---|---:|---:|---:|---:|---:|
| REG | 28,646 | 271,595 | 111,839 | 132,849 | 544,929 |
| OT | 715 | 3,655 | 1,336 | 1,102 | 6,808 |
| SO | 812 | 1,343 | 449 | 0 | 2,604 |

| Season | Games | PBP events | Team scores exact / eligible | Team SOG exact / eligible | SOG games quarantined | Player SOG event-eligible / approved | Goalie GA event-eligible / approved | Goalie saves event-eligible / approved | Goalie SA event-eligible / approved |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2018 | 1271 | 402,616 | 1271/1271 | 1259/1259 | 12 | 45742/45755 | 2720/2720 | 2714/2720 | 2714/2720 |
| 2019 | 1082 | 335,749 | 1082/1082 | 1065/1065 | 17 | 38931/38949 | 2306/2306 | 2293/2306 | 2293/2306 |
| 2020 | 868 | 258,119 | 868/868 | 857/857 | 11 | 31215/31226 | 1852/1852 | 1845/1852 | 1845/1852 |
| 2021 | 1312 | 404,656 | 1312/1312 | 1292/1292 | 20 | 47188/47208 | 2817/2818 | 2802/2818 | 2801/2818 |
| 2022 | 343 | 108,964 | 343/343 | 341/341 | 2 | 12342/12344 | 721/721 | 721/721 | 721/721 |

## Target populations

Eligibility uses the approved NHL label reader's purpose-specific values and flags. The replay adds exact accepted event attribution, event-count agreement, and `event_disposition=ACCEPT`. A quarantined or not-applicable label never enters an eligible target count.

| Purpose | Statistic | Games with eligible targets | Approved label rows | Event-eligible player targets | Accepted attributed events | Excluded approved rows |
|---|---|---:|---:|---:|---:|---:|
| training | SOG | 4,876 | 175,482 | 175,418 | 304,362 | 64 |
| training | GOALS_AGAINST | 4,876 | 10,417 | 10,416 | 27,754 | 1 |
| training | SAVES | 4,876 | 10,417 | 10,375 | 273,946 | 42 |
| training | SHOTS_AGAINST | 4,876 | 10,417 | 10,374 | 301,535 | 43 |
| evaluation | SOG | 4,876 | 175,482 | 175,418 | 304,362 | 64 |
| evaluation | GOALS_AGAINST | 4,876 | 10,417 | 10,416 | 27,754 | 1 |
| evaluation | SAVES | 4,876 | 10,417 | 10,375 | 273,946 | 42 |
| evaluation | SHOTS_AGAINST | 4,876 | 10,417 | 10,374 | 301,535 | 43 |
| grading | SOG | 4,876 | 175,482 | 175,418 | 304,362 | 64 |
| grading | GOALS_AGAINST | 4,876 | 10,417 | 10,416 | 27,754 | 1 |
| grading | SAVES | 4,876 | 10,417 | 10,375 | 273,946 | 42 |
| grading | SHOTS_AGAINST | 4,876 | 10,417 | 10,374 | 301,535 | 43 |

<details><summary>Replay-excluded approved player targets by ID and reason</summary>

| Game | Player | Statistic | Event issue reason | Label quality reason | Accepted | Replayed | Audit count | Issue detail |
|---|---:|---|---|---|---:|---:|---:|---|
| `2018020090` | `8471215` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 4 | 5 | 5 | pbp_direct_event_count=5 accepted_label=4 status=VERIFIED |
| `2018020173` | `8478042` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 4 | 5 | 5 | pbp_direct_event_count=5 accepted_label=4 status=VERIFIED |
| `2018020276` | `8476434` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 9 | 10 | 10 | pbp_direct_event_count=10 accepted_label=9 status=VERIFIED |
| `2018020276` | `8476434` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 12 | 13 | 13 | pbp_direct_event_count=13 accepted_label=12 status=VERIFIED |
| `2018020276` | `8474207` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 1 | 2 | 2 | pbp_direct_event_count=2 accepted_label=1 status=VERIFIED |
| `2018020359` | `8471239` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 30 | 31 | 31 | pbp_direct_event_count=31 accepted_label=30 status=VERIFIED |
| `2018020359` | `8471239` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 35 | 36 | 36 | pbp_direct_event_count=36 accepted_label=35 status=VERIFIED |
| `2018020359` | `8478010` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 2 | 3 | 3 | pbp_direct_event_count=3 accepted_label=2 status=VERIFIED |
| `2018020414` | `8477933` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 3 | 4 | 4 | pbp_direct_event_count=4 accepted_label=3 status=VERIFIED |
| `2018020414` | `8471469` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 21 | 22 | 22 | pbp_direct_event_count=22 accepted_label=21 status=VERIFIED |
| `2018020414` | `8471469` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 22 | 23 | 23 | pbp_direct_event_count=23 accepted_label=22 status=VERIFIED |
| `2018020458` | `8478131` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 3 | 4 | 4 | pbp_direct_event_count=4 accepted_label=3 status=VERIFIED |
| `2018020458` | `8471239` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 32 | 33 | 33 | pbp_direct_event_count=33 accepted_label=32 status=VERIFIED |
| `2018020458` | `8471239` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 37 | 38 | 38 | pbp_direct_event_count=38 accepted_label=37 status=VERIFIED |
| `2018020541` | `8477940` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 5 | 6 | 6 | pbp_direct_event_count=6 accepted_label=5 status=VERIFIED |
| `2018020751` | `8473604` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 6 | 7 | 7 | pbp_direct_event_count=7 accepted_label=6 status=VERIFIED |
| `2018020751` | `8478440` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 1 | 2 | 2 | pbp_direct_event_count=2 accepted_label=1 status=VERIFIED |
| `2018020751` | `8474651` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 7 | 8 | 8 | pbp_direct_event_count=8 accepted_label=7 status=VERIFIED |
| `2018020751` | `8474651` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 11 | 12 | 12 | pbp_direct_event_count=12 accepted_label=11 status=VERIFIED |
| `2018020952` | `8475786` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 2 | 3 | 3 | pbp_direct_event_count=3 accepted_label=2 status=VERIFIED |
| `2018020993` | `8471698` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 3 | 4 | 4 | pbp_direct_event_count=4 accepted_label=3 status=VERIFIED |
| `2018021130` | `8471228` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 5 | 6 | 6 | pbp_direct_event_count=6 accepted_label=5 status=VERIFIED |
| `2018021256` | `8476434` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 44 | 45 | 45 | pbp_direct_event_count=45 accepted_label=44 status=VERIFIED |
| `2018021256` | `8476434` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 46 | 47 | 47 | pbp_direct_event_count=47 accepted_label=46 status=VERIFIED |
| `2018021256` | `8479336` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 6 | 7 | 7 | pbp_direct_event_count=7 accepted_label=6 status=VERIFIED |
| `2019020016` | `8470645` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 34 | 35 | 35 | pbp_direct_event_count=35 accepted_label=34 status=VERIFIED |
| `2019020016` | `8470645` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 38 | 39 | 39 | pbp_direct_event_count=39 accepted_label=38 status=VERIFIED |
| `2019020016` | `8478067` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 5 | 6 | 6 | pbp_direct_event_count=6 accepted_label=5 status=VERIFIED |
| `2019020024` | `8477406` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 0 | 1 | 1 | pbp_direct_event_count=1 accepted_label=0 status=VERIFIED |
| `2019020024` | `8476412` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 27 | 28 | 28 | pbp_direct_event_count=28 accepted_label=27 status=VERIFIED |
| `2019020024` | `8476412` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 29 | 30 | 30 | pbp_direct_event_count=30 accepted_label=29 status=VERIFIED |
| `2019020092` | `8475831` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 29 | 30 | 30 | pbp_direct_event_count=30 accepted_label=29 status=VERIFIED |
| `2019020092` | `8475831` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 32 | 33 | 33 | pbp_direct_event_count=33 accepted_label=32 status=VERIFIED |
| `2019020092` | `8479293` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 1 | 2 | 2 | pbp_direct_event_count=2 accepted_label=1 status=VERIFIED |
| `2019020103` | `8478585` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 3 | 4 | 4 | pbp_direct_event_count=4 accepted_label=3 status=VERIFIED |
| `2019020103` | `8470657` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 31 | 32 | 32 | pbp_direct_event_count=32 accepted_label=31 status=VERIFIED |
| `2019020103` | `8470657` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 36 | 37 | 37 | pbp_direct_event_count=37 accepted_label=36 status=VERIFIED |
| `2019020109` | `8468685` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 29 | 30 | 30 | pbp_direct_event_count=30 accepted_label=29 status=VERIFIED |
| `2019020109` | `8468685` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 33 | 34 | 34 | pbp_direct_event_count=34 accepted_label=33 status=VERIFIED |
| `2019020109` | `8471698` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 4 | 5 | 5 | pbp_direct_event_count=5 accepted_label=4 status=VERIFIED |
| `2019020176` | `8476434` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 44 | 45 | 45 | pbp_direct_event_count=45 accepted_label=44 status=VERIFIED |
| `2019020176` | `8476434` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 49 | 50 | 50 | pbp_direct_event_count=50 accepted_label=49 status=VERIFIED |
| `2019020176` | `8475913` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 0 | 1 | 1 | pbp_direct_event_count=1 accepted_label=0 status=VERIFIED |
| `2019020195` | `8477494` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 3 | 4 | 4 | pbp_direct_event_count=4 accepted_label=3 status=VERIFIED |
| `2019020195` | `8470594` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 24 | 25 | 25 | pbp_direct_event_count=25 accepted_label=24 status=VERIFIED |
| `2019020195` | `8470594` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 29 | 30 | 30 | pbp_direct_event_count=30 accepted_label=29 status=VERIFIED |
| `2019020372` | `8470612` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 2 | 3 | 3 | pbp_direct_event_count=3 accepted_label=2 status=VERIFIED |
| `2019020372` | `8471306` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 20 | 21 | 21 | pbp_direct_event_count=21 accepted_label=20 status=VERIFIED |
| `2019020372` | `8471306` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 23 | 24 | 24 | pbp_direct_event_count=24 accepted_label=23 status=VERIFIED |
| `2019020575` | `8480801` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 4 | 5 | 5 | pbp_direct_event_count=5 accepted_label=4 status=VERIFIED |
| `2019020615` | `8476434` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 38 | 39 | 39 | pbp_direct_event_count=39 accepted_label=38 status=VERIFIED |
| `2019020615` | `8476434` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 42 | 43 | 43 | pbp_direct_event_count=43 accepted_label=42 status=VERIFIED |
| `2019020615` | `8477949` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 1 | 2 | 2 | pbp_direct_event_count=2 accepted_label=1 status=VERIFIED |
| `2019020670` | `8474578` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 3 | 4 | 4 | pbp_direct_event_count=4 accepted_label=3 status=VERIFIED |
| `2019020670` | `8476412` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 27 | 28 | 28 | pbp_direct_event_count=28 accepted_label=27 status=VERIFIED |
| `2019020670` | `8476412` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 29 | 30 | 30 | pbp_direct_event_count=30 accepted_label=29 status=VERIFIED |
| `2019020776` | `8477424` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 29 | 30 | 30 | pbp_direct_event_count=30 accepted_label=29 status=VERIFIED |
| `2019020776` | `8477424` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 33 | 34 | 34 | pbp_direct_event_count=34 accepted_label=33 status=VERIFIED |
| `2019020776` | `8475209` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 2 | 3 | 3 | pbp_direct_event_count=3 accepted_label=2 status=VERIFIED |
| `2019020809` | `8475796` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 3 | 4 | 4 | pbp_direct_event_count=4 accepted_label=3 status=VERIFIED |
| `2019020873` | `8473994` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 3 | 4 | 4 | pbp_direct_event_count=4 accepted_label=3 status=VERIFIED |
| `2019020876` | `8474641` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 1 | 2 | 2 | pbp_direct_event_count=2 accepted_label=1 status=VERIFIED |
| `2019020876` | `8477964` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 2 | 3 | 3 | pbp_direct_event_count=3 accepted_label=2 status=VERIFIED |
| `2019020894` | `8480039` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 1 | 2 | 2 | pbp_direct_event_count=2 accepted_label=1 status=VERIFIED |
| `2019020894` | `8475839` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 25 | 26 | 26 | pbp_direct_event_count=26 accepted_label=25 status=VERIFIED |
| `2019020894` | `8475839` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 30 | 31 | 31 | pbp_direct_event_count=31 accepted_label=30 status=VERIFIED |
| `2019020993` | `8471233` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 1 | 2 | 2 | pbp_direct_event_count=2 accepted_label=1 status=VERIFIED |
| `2019020993` | `8474889` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 21 | 22 | 22 | pbp_direct_event_count=22 accepted_label=21 status=VERIFIED |
| `2019020993` | `8474889` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 23 | 24 | 24 | pbp_direct_event_count=24 accepted_label=23 status=VERIFIED |
| `2020020020` | `8480027` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 3 | 4 | 4 | pbp_direct_event_count=4 accepted_label=3 status=VERIFIED |
| `2020020020` | `8481519` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 25 | 26 | 26 | pbp_direct_event_count=26 accepted_label=25 status=VERIFIED |
| `2020020020` | `8481519` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 29 | 30 | 30 | pbp_direct_event_count=30 accepted_label=29 status=VERIFIED |
| `2020020056` | `8479977` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 0 | 1 | 1 | pbp_direct_event_count=1 accepted_label=0 status=VERIFIED |
| `2020020056` | `8475883` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 19 | 20 | 20 | pbp_direct_event_count=20 accepted_label=19 status=VERIFIED |
| `2020020056` | `8475883` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 21 | 22 | 22 | pbp_direct_event_count=22 accepted_label=21 status=VERIFIED |
| `2020020068` | `8478048` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 25 | 26 | 26 | pbp_direct_event_count=26 accepted_label=25 status=VERIFIED |
| `2020020068` | `8478048` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 28 | 29 | 29 | pbp_direct_event_count=29 accepted_label=28 status=VERIFIED |
| `2020020068` | `8477955` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 0 | 1 | 1 | pbp_direct_event_count=1 accepted_label=0 status=VERIFIED |
| `2020020220` | `8477498` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 1 | 2 | 2 | pbp_direct_event_count=2 accepted_label=1 status=VERIFIED |
| `2020020220` | `8474596` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 28 | 29 | 29 | pbp_direct_event_count=29 accepted_label=28 status=VERIFIED |
| `2020020220` | `8474596` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 31 | 32 | 32 | pbp_direct_event_count=32 accepted_label=31 status=VERIFIED |
| `2020020398` | `8476463` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 2 | 3 | 3 | pbp_direct_event_count=3 accepted_label=2 status=VERIFIED |
| `2020020414` | `8476434` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 32 | 33 | 33 | pbp_direct_event_count=33 accepted_label=32 status=VERIFIED |
| `2020020414` | `8476434` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 37 | 38 | 38 | pbp_direct_event_count=38 accepted_label=37 status=VERIFIED |
| `2020020414` | `8480113` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 1 | 2 | 2 | pbp_direct_event_count=2 accepted_label=1 status=VERIFIED |
| `2020020417` | `8478406` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 28 | 29 | 29 | pbp_direct_event_count=29 accepted_label=28 status=VERIFIED |
| `2020020417` | `8478406` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 33 | 34 | 34 | pbp_direct_event_count=34 accepted_label=33 status=VERIFIED |
| `2020020417` | `8480865` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 0 | 1 | 1 | pbp_direct_event_count=1 accepted_label=0 status=VERIFIED |
| `2020020444` | `8478493` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 0 | 1 | 1 | pbp_direct_event_count=1 accepted_label=0 status=VERIFIED |
| `2020020494` | `8477425` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 2 | 3 | 3 | pbp_direct_event_count=3 accepted_label=2 status=VERIFIED |
| `2020020494` | `8479193` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 26 | 27 | 27 | pbp_direct_event_count=27 accepted_label=26 status=VERIFIED |
| `2020020494` | `8479193` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 30 | 31 | 31 | pbp_direct_event_count=31 accepted_label=30 status=VERIFIED |
| `2020020702` | `8476458` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 2 | 3 | 3 | pbp_direct_event_count=3 accepted_label=2 status=VERIFIED |
| `2020020773` | `8476456` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 6 | 7 | 7 | pbp_direct_event_count=7 accepted_label=6 status=VERIFIED |
| `2021020219` | `8471418` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 31 | 32 | 32 | pbp_direct_event_count=32 accepted_label=31 status=VERIFIED |
| `2021020219` | `8471418` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 33 | 34 | 34 | pbp_direct_event_count=34 accepted_label=33 status=VERIFIED |
| `2021020219` | `8474037` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 3 | 4 | 4 | pbp_direct_event_count=4 accepted_label=3 status=VERIFIED |
| `2021020319` | `8476981` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 6 | 7 | 7 | pbp_direct_event_count=7 accepted_label=6 status=VERIFIED |
| `2021020345` | `8480806` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 2 | 3 | 3 | pbp_direct_event_count=3 accepted_label=2 status=VERIFIED |
| `2021020345` | `8471734` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 32 | 33 | 33 | pbp_direct_event_count=33 accepted_label=32 status=VERIFIED |
| `2021020345` | `8471734` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 36 | 37 | 37 | pbp_direct_event_count=37 accepted_label=36 status=VERIFIED |
| `2021020368` | `8477992` | GOALS_AGAINST | `PBP_GOALS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 3 | 4 | 4 | pbp_direct_event_count=4 accepted_label=3 status=VERIFIED |
| `2021020368` | `8477992` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 15 | 16 | 16 | pbp_direct_event_count=16 accepted_label=15 status=VERIFIED |
| `2021020368` | `8482116` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 3 | 4 | 4 | pbp_direct_event_count=4 accepted_label=3 status=VERIFIED |
| `2021020443` | `8478435` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 25 | 26 | 26 | pbp_direct_event_count=26 accepted_label=25 status=VERIFIED |
| `2021020443` | `8478435` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 27 | 28 | 28 | pbp_direct_event_count=28 accepted_label=27 status=VERIFIED |
| `2021020443` | `8475168` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 0 | 1 | 1 | pbp_direct_event_count=1 accepted_label=0 status=VERIFIED |
| `2021020478` | `8478007` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 35 | 36 | 36 | pbp_direct_event_count=36 accepted_label=35 status=VERIFIED |
| `2021020478` | `8478007` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 41 | 42 | 42 | pbp_direct_event_count=42 accepted_label=41 status=VERIFIED |
| `2021020478` | `8477496` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 2 | 3 | 3 | pbp_direct_event_count=3 accepted_label=2 status=VERIFIED |
| `2021020620` | `8475220` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 0 | 1 | 1 | pbp_direct_event_count=1 accepted_label=0 status=VERIFIED |
| `2021020704` | `8478498` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 4 | 5 | 5 | pbp_direct_event_count=5 accepted_label=4 status=VERIFIED |
| `2021020704` | `8477970` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 29 | 30 | 30 | pbp_direct_event_count=30 accepted_label=29 status=VERIFIED |
| `2021020704` | `8477970` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 33 | 34 | 34 | pbp_direct_event_count=34 accepted_label=33 status=VERIFIED |
| `2021020744` | `8477180` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 42 | 43 | 43 | pbp_direct_event_count=43 accepted_label=42 status=VERIFIED |
| `2021020744` | `8477180` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 47 | 48 | 48 | pbp_direct_event_count=48 accepted_label=47 status=VERIFIED |
| `2021020744` | `8480208` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 0 | 1 | 1 | pbp_direct_event_count=1 accepted_label=0 status=VERIFIED |
| `2021020752` | `8479351` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 2 | 3 | 3 | pbp_direct_event_count=3 accepted_label=2 status=VERIFIED |
| `2021020752` | `8475789` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 17 | 18 | 18 | pbp_direct_event_count=18 accepted_label=17 status=VERIFIED |
| `2021020752` | `8475789` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 20 | 21 | 21 | pbp_direct_event_count=21 accepted_label=20 status=VERIFIED |
| `2021020811` | `8479992` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 1 | 2 | 2 | pbp_direct_event_count=2 accepted_label=1 status=VERIFIED |
| `2021020837` | `8482124` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 2 | 3 | 3 | pbp_direct_event_count=3 accepted_label=2 status=VERIFIED |
| `2021020837` | `8473575` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 30 | 31 | 31 | pbp_direct_event_count=31 accepted_label=30 status=VERIFIED |
| `2021020837` | `8473575` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 34 | 35 | 35 | pbp_direct_event_count=35 accepted_label=34 status=VERIFIED |
| `2021020919` | `8477968` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 35 | 36 | 36 | pbp_direct_event_count=36 accepted_label=35 status=VERIFIED |
| `2021020919` | `8477968` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 40 | 41 | 41 | pbp_direct_event_count=41 accepted_label=40 status=VERIFIED |
| `2021020919` | `8478493` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 3 | 4 | 4 | pbp_direct_event_count=4 accepted_label=3 status=VERIFIED |
| `2021020933` | `8478470` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 31 | 32 | 32 | pbp_direct_event_count=32 accepted_label=31 status=VERIFIED |
| `2021020933` | `8478470` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 34 | 35 | 35 | pbp_direct_event_count=35 accepted_label=34 status=VERIFIED |
| `2021020933` | `8476826` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 2 | 3 | 3 | pbp_direct_event_count=3 accepted_label=2 status=VERIFIED |
| `2021020971` | `8478007` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 20 | 21 | 21 | pbp_direct_event_count=21 accepted_label=20 status=VERIFIED |
| `2021020971` | `8478007` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 23 | 24 | 24 | pbp_direct_event_count=24 accepted_label=23 status=VERIFIED |
| `2021020971` | `8481580` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 2 | 3 | 3 | pbp_direct_event_count=3 accepted_label=2 status=VERIFIED |
| `2021021070` | `8478402` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 8 | 9 | 9 | pbp_direct_event_count=9 accepted_label=8 status=VERIFIED |
| `2021021070` | `8471734` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 30 | 31 | 31 | pbp_direct_event_count=31 accepted_label=30 status=VERIFIED |
| `2021021070` | `8471734` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 33 | 34 | 34 | pbp_direct_event_count=34 accepted_label=33 status=VERIFIED |
| `2021021106` | `8477500` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 6 | 7 | 7 | pbp_direct_event_count=7 accepted_label=6 status=VERIFIED |
| `2021021106` | `8475215` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 26 | 27 | 27 | pbp_direct_event_count=27 accepted_label=26 status=VERIFIED |
| `2021021106` | `8475215` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 28 | 29 | 29 | pbp_direct_event_count=29 accepted_label=28 status=VERIFIED |
| `2021021119` | `8475311` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 41 | 42 | 42 | pbp_direct_event_count=42 accepted_label=41 status=VERIFIED |
| `2021021119` | `8475311` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 45 | 46 | 46 | pbp_direct_event_count=46 accepted_label=45 status=VERIFIED |
| `2021021119` | `8478542` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 5 | 6 | 6 | pbp_direct_event_count=6 accepted_label=5 status=VERIFIED |
| `2021021267` | `8475760` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 1 | 2 | 2 | pbp_direct_event_count=2 accepted_label=1 status=VERIFIED |
| `2021021267` | `8479496` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 42 | 43 | 43 | pbp_direct_event_count=43 accepted_label=42 status=VERIFIED |
| `2021021267` | `8479496` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 47 | 48 | 48 | pbp_direct_event_count=48 accepted_label=47 status=VERIFIED |
| `2021021292` | `8479356` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 2 | 3 | 3 | pbp_direct_event_count=3 accepted_label=2 status=VERIFIED |
| `2021021292` | `8476883` | SAVES | `PBP_SAVES_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 33 | 34 | 34 | pbp_direct_event_count=34 accepted_label=33 status=VERIFIED |
| `2021021292` | `8476883` | SHOTS_AGAINST | `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | `OFFICIAL_GOALIE_ARITHMETIC_PASS` | 37 | 38 | 38 | pbp_direct_event_count=38 accepted_label=37 status=VERIFIED |
| `2022020158` | `8478414` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 9 | 10 | 10 | pbp_direct_event_count=10 accepted_label=9 status=VERIFIED |
| `2022020276` | `8470966` | SOG | `PBP_SOG_VS_APPROVED_LABEL` | `OFFICIAL_SOG_TEAM_SUM_PASS` | 1 | 2 | 2 | pbp_direct_event_count=2 accepted_label=1 status=VERIFIED |

</details>


## Chronology, manpower, penalties, goalies, and shifts

- PBP events are consumed in increasing `publisher_sort_order`; source array index is retained for audit. No event is reordered by clock or ID. Period-number regressions remain marked and do not reset or rewrite score state.
- Valid four-digit situation codes retain raw digits and parse to recorded away/home skater counts and goalie-present bits. The replay reports **1,496,209** valid observations, **87,646** transitions, and **9,606** transitions into an empty-net state.
- Recorded situation/shift comparisons: **1,289,635 ACCEPT / 216,399 QUARANTINE**. Ordinary-shot shooter-on-ice joins: **467,900 ACCEPT / 83,837 QUARANTINE**. Direct goalie-to-shift comparisons: **380,951 ACCEPT / 34,290 QUARANTINE**. These gates do not affect team scoring or event-level goalie identity.
- Penalty calls retained: **35,417**; timing-disposition exclusions: **0**; duration-disposition exclusions: **0**. Durations stay in source minutes. The source contains **5,593** explicitly named delayed-penalty event types. A penalty call is not treated as a service clock; no unobserved delayed-call start, expiration, or penalty-to-manpower link is fabricated.
- Direct `goalieInNetId` values are present on **417,626** shot-family rows; **303,018** rows pass the goalie-event attribution disposition. For ordinary on-target events, **303,018** direct goalie IDs were accepted and **1,580** empty nets were directly indicated by the situation code. Observed goalie ID changes between accepted on-target events: **687**. Goalie targets use direct PBP event IDs only; shifts never assign saves, SA, or GA.
- Shift intervals by disposition: **3,448,108 ACCEPT**, **5,292 QUARANTINE**, **290,560 REJECT**. Accepted player-games by recorded type: `{'skater': 162310, 'goalie': 9578}`. Duplicated charts: **12** games; overlapping-shift games: **376**. Shift disposition is a separate component and never changes team scoring.

| Shift type | TOI within 30 seconds / compared | Over 30 seconds | Over 60 seconds |
|---|---:|---:|---:|
| skater | 173,765/175,482 | 1,717 | 1,176 |
| goalie | 10,316/10,432 | 116 | 104 |

Shift interval duration disagreed with `end_seconds - start_seconds` on **63** rows. Official boxscore TOI remains authoritative.

## Bounded regression cohort

| Game | Case | Score disposition / exact | SOG disposition / exact | Duplicate charts | Period regressions | Observed goalie ID changes |
|---|---|---|---|---:|---:|---:|
| `2018020001` | overtime_scoring, power_play_manpower | ACCEPT / True | ACCEPT / True | 0 | 0 | 0 |
| `2018020002` | goalie_substitution | ACCEPT / True | ACCEPT / True | 0 | 0 | 1 |
| `2018020003` | ordinary_regulation, team_and_player_shots | ACCEPT / True | ACCEPT / True | 0 | 0 | 0 |
| `2018020019` | shootout_exclusion, goalie_change | ACCEPT / True | ACCEPT / True | 0 | 0 | 1 |
| `2018020164` | period_number_regression, publisher_order_retained | ACCEPT / True | ACCEPT / True | 0 | 334 | 0 |
| `2018020751` | two_sided_sog_mismatch | ACCEPT / True | QUARANTINE / False | 0 | 0 | 1 |
| `2019020372` | original_sample_sog_mismatch | ACCEPT / True | QUARANTINE / False | 0 | 0 | 0 |
| `2020020056` | duplicated_shift_chart, score_independent_of_shifts | ACCEPT / True | QUARANTINE / False | 1 | 0 | 0 |

## Unresolved inherited discrepancies

The exhaustive input issue ledger remains unchanged at `unresolved_issues.csv.gz` (SHA-256 `b6b39dcb332963ff9f4a08d22ae6a4d958333a700db3daa32f489273e88614fb`). This replay verified **124,514** issue rows across the pinned frame. It is the complete ID-level discrepancy record for every component; the selected team SOG and player-target mismatches are expanded below, while the full immutable ledger remains available at the restore path in the README.

| Reason code | Rows |
|---|---:|
| `DIRECT_GOALIE_SHIFT_DEPLOYMENT_UNTRUSTED` | 31,893 |
| `DIRECT_GOALIE_VS_SHIFT_CHART_MISMATCH` | 327 |
| `DUPLICATE_SHIFT_CHART` | 467 |
| `DUPLICATE_SHIFT_INTERVAL` | 25,862 |
| `ON_TARGET_GOALIE_ID_MISSING_UNEXPLAINED` | 13 |
| `PBP_GOALS_AGAINST_VS_APPROVED_LABEL` | 1 |
| `PBP_PERIOD_NUMBER_SEQUENCE_REGRESSION` | 1,571 |
| `PBP_SAVES_VS_APPROVED_LABEL` | 42 |
| `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | 43 |
| `PBP_SOG_VS_APPROVED_LABEL` | 64 |
| `PBP_SOG_VS_OFFICIAL` | 63 |
| `PENALTY_COMMITTED_PLAYER_ID_UNRESOLVED` | 224 |
| `PENALTY_COMMITTED_PLAYER_MISSING` | 8 |
| `PENALTY_DRAWN_PLAYER_ID_UNRESOLVED` | 454 |
| `PLAYER_SHIFT_OVERLAP` | 14,940 |
| `SHIFT_DURATION_DISAGREES_WITH_INTERVAL` | 116 |
| `SHIFT_INTERVAL_INVALID` | 1,173 |
| `SHIFT_PLAYER_OFFICIAL_NONAPPEARANCE` | 13 |
| `SHIFT_TEAM_IDENTITY_MISMATCH` | 742 |
| `SHIFT_TOI_OUTSIDE_30S` | 1,833 |
| `SHOOTER_EVENT_SHIFT_DEPLOYMENT_UNTRUSTED` | 36,709 |
| `SHOOTER_REPORTED_OFF_ACCEPTED_SHIFT` | 67 |
| `SHOT_COORDINATES_MISSING_OR_INVALID` | 7 |
| `SHOT_EVENT_GOALIE_ID_NOT_IN_OFFICIAL_APPEARANCES` | 1 |
| `SHOT_SHOOTER_ID_NOT_IN_OFFICIAL_SKATERS` | 37 |
| `SITUATION_CODE_VS_SHIFT_CHART_MISMATCH` | 7,813 |
| `UNBLOCKED_SHOT_TYPE_MISSING` | 31 |

The exhaustive ID-level ledger is stored outside Git at `/root/lp-data/nhl-fullframe-event-audit-2026-10-21/derived/hardened-final/unresolved_issues.csv.gz`.

<details><summary>All official team SOG discrepancy rows (game, side, reason, observed values)</summary>

| Game | Side | Reason code | Detail |
|---|---|---|---|
| `2018020090` | away | `PBP_SOG_VS_OFFICIAL` | pbp=39 official=38 |
| `2018020173` | home | `PBP_SOG_VS_OFFICIAL` | pbp=29 official=28 |
| `2018020276` | home | `PBP_SOG_VS_OFFICIAL` | pbp=26 official=25 |
| `2018020359` | home | `PBP_SOG_VS_OFFICIAL` | pbp=36 official=35 |
| `2018020414` | away | `PBP_SOG_VS_OFFICIAL` | pbp=23 official=22 |
| `2018020458` | home | `PBP_SOG_VS_OFFICIAL` | pbp=38 official=37 |
| `2018020541` | away | `PBP_SOG_VS_OFFICIAL` | pbp=25 official=24 |
| `2018020751` | home | `PBP_SOG_VS_OFFICIAL` | pbp=30 official=28 |
| `2018020952` | home | `PBP_SOG_VS_OFFICIAL` | pbp=37 official=36 |
| `2018020993` | away | `PBP_SOG_VS_OFFICIAL` | pbp=29 official=28 |
| `2018021130` | home | `PBP_SOG_VS_OFFICIAL` | pbp=37 official=36 |
| `2018021256` | away | `PBP_SOG_VS_OFFICIAL` | pbp=47 official=46 |
| `2019020016` | home | `PBP_SOG_VS_OFFICIAL` | pbp=39 official=38 |
| `2019020024` | away | `PBP_SOG_VS_OFFICIAL` | pbp=30 official=29 |
| `2019020092` | home | `PBP_SOG_VS_OFFICIAL` | pbp=33 official=32 |
| `2019020103` | home | `PBP_SOG_VS_OFFICIAL` | pbp=37 official=36 |
| `2019020109` | home | `PBP_SOG_VS_OFFICIAL` | pbp=35 official=34 |
| `2019020176` | home | `PBP_SOG_VS_OFFICIAL` | pbp=50 official=49 |
| `2019020195` | away | `PBP_SOG_VS_OFFICIAL` | pbp=30 official=29 |
| `2019020372` | home | `PBP_SOG_VS_OFFICIAL` | pbp=24 official=23 |
| `2019020575` | home | `PBP_SOG_VS_OFFICIAL` | pbp=30 official=29 |
| `2019020615` | home | `PBP_SOG_VS_OFFICIAL` | pbp=44 official=43 |
| `2019020670` | away | `PBP_SOG_VS_OFFICIAL` | pbp=30 official=29 |
| `2019020776` | home | `PBP_SOG_VS_OFFICIAL` | pbp=34 official=33 |
| `2019020809` | away | `PBP_SOG_VS_OFFICIAL` | pbp=22 official=21 |
| `2019020873` | home | `PBP_SOG_VS_OFFICIAL` | pbp=37 official=36 |
| `2019020876` | home | `PBP_SOG_VS_OFFICIAL` | pbp=28 official=27 |
| `2019020876` | away | `PBP_SOG_VS_OFFICIAL` | pbp=38 official=37 |
| `2019020894` | home | `PBP_SOG_VS_OFFICIAL` | pbp=31 official=30 |
| `2019020993` | away | `PBP_SOG_VS_OFFICIAL` | pbp=24 official=23 |
| `2020020020` | away | `PBP_SOG_VS_OFFICIAL` | pbp=30 official=29 |
| `2020020056` | away | `PBP_SOG_VS_OFFICIAL` | pbp=23 official=22 |
| `2020020068` | home | `PBP_SOG_VS_OFFICIAL` | pbp=29 official=28 |
| `2020020220` | away | `PBP_SOG_VS_OFFICIAL` | pbp=32 official=31 |
| `2020020398` | home | `PBP_SOG_VS_OFFICIAL` | pbp=22 official=21 |
| `2020020414` | away | `PBP_SOG_VS_OFFICIAL` | pbp=38 official=37 |
| `2020020417` | home | `PBP_SOG_VS_OFFICIAL` | pbp=34 official=33 |
| `2020020444` | home | `PBP_SOG_VS_OFFICIAL` | pbp=35 official=34 |
| `2020020494` | home | `PBP_SOG_VS_OFFICIAL` | pbp=31 official=30 |
| `2020020702` | away | `PBP_SOG_VS_OFFICIAL` | pbp=26 official=25 |
| `2020020773` | away | `PBP_SOG_VS_OFFICIAL` | pbp=56 official=55 |
| `2021020219` | away | `PBP_SOG_VS_OFFICIAL` | pbp=34 official=33 |
| `2021020319` | away | `PBP_SOG_VS_OFFICIAL` | pbp=34 official=33 |
| `2021020345` | away | `PBP_SOG_VS_OFFICIAL` | pbp=37 official=36 |
| `2021020368` | home | `PBP_SOG_VS_OFFICIAL` | pbp=35 official=34 |
| `2021020443` | home | `PBP_SOG_VS_OFFICIAL` | pbp=28 official=27 |
| `2021020478` | home | `PBP_SOG_VS_OFFICIAL` | pbp=42 official=41 |
| `2021020620` | home | `PBP_SOG_VS_OFFICIAL` | pbp=23 official=22 |
| `2021020704` | home | `PBP_SOG_VS_OFFICIAL` | pbp=34 official=33 |
| `2021020744` | home | `PBP_SOG_VS_OFFICIAL` | pbp=48 official=47 |
| `2021020752` | away | `PBP_SOG_VS_OFFICIAL` | pbp=21 official=20 |
| `2021020811` | home | `PBP_SOG_VS_OFFICIAL` | pbp=24 official=23 |
| `2021020837` | home | `PBP_SOG_VS_OFFICIAL` | pbp=36 official=35 |
| `2021020919` | away | `PBP_SOG_VS_OFFICIAL` | pbp=41 official=40 |
| `2021020933` | away | `PBP_SOG_VS_OFFICIAL` | pbp=35 official=34 |
| `2021020971` | away | `PBP_SOG_VS_OFFICIAL` | pbp=34 official=33 |
| `2021021070` | home | `PBP_SOG_VS_OFFICIAL` | pbp=34 official=33 |
| `2021021106` | home | `PBP_SOG_VS_OFFICIAL` | pbp=29 official=28 |
| `2021021119` | home | `PBP_SOG_VS_OFFICIAL` | pbp=46 official=45 |
| `2021021267` | away | `PBP_SOG_VS_OFFICIAL` | pbp=48 official=47 |
| `2021021292` | home | `PBP_SOG_VS_OFFICIAL` | pbp=38 official=37 |
| `2022020158` | home | `PBP_SOG_VS_OFFICIAL` | pbp=45 official=44 |
| `2022020276` | home | `PBP_SOG_VS_OFFICIAL` | pbp=24 official=23 |

</details>


The original full-frame report remains [REPORT-FULLFRAME.md](../fullframe-event-audit-2026-10-21/REPORT-FULLFRAME.md); this report does not rewrite it. In particular, the 62 team SOG-mismatch games, player target mismatches, period regressions, and rejected/quarantined shifts remain component-specific exclusions.

## Reproducibility and limitations

- `SOURCE-PINS.json` binds all normalized ledgers, the canonical frame, official team SOG, and the approved label artifact. Input loading fails on a hash, source identity, game/team join, target-copy, or season-coverage mismatch.
- The raw-body pass validated both gzip and decompressed bytes, the NHL game ID and endpoint identity, and payload shape/count for every cached response.
- Deterministic transition and failure-injection tests are in `test_replay_engine.py`; the exact command and result are recorded after the run.
- The replay reconstructs observed events and approved targets. It does not observe player movement, puck possession, continuous puck position, actual delay-penalty start, or continuous deployment between recorded events. Shift charts are recorded deployment intervals, not tracking.
- Prospective simulation accepts only the validated `PregameSnapshot` interface. It receives no historical event stream or postgame target. Phase 2 proposals are in [PHASE2-STOCHASTIC-COMPONENTS.md](PHASE2-STOCHASTIC-COMPONENTS.md); no probability or model is fitted here.
