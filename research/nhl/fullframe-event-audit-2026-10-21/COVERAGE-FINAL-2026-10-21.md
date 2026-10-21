# Full-frame event evidence coverage

Frame games: **4876** (300 in the 300-game sample).
Games with both sources verified: **4876** — COMPLETE.

## pbp

- manifest rows: 4876 (duplicates: 0)
- games covered: 4876 / 4876 (100.0%)
- failures: 0, missing: 0, ids outside frame: 0
- http statuses: {'200': 4876}
- units (plays): 1,510,104
- per season: {'2018': 1271, '2019': 1082, '2020': 868, '2021': 1312, '2022': 343}
- per season units: {'2018': 402616, '2019': 335749, '2020': 258119, '2021': 404656, '2022': 108964}

## shifts

- manifest rows: 4876 (duplicates: 0)
- games covered: 4876 / 4876 (100.0%)
- failures: 0, missing: 0, ids outside frame: 0
- http statuses: {'200': 4876}
- units (shift rows): 3,775,846
- per season: {'2018': 1271, '2019': 1082, '2020': 868, '2021': 1312, '2022': 343}
- per season units: {'2018': 984966, '2019': 833284, '2020': 672986, '2021': 1019521, '2022': 265089}


Every count above is re-derived by `report_event_coverage.py --verify` from the
manifests and raw bodies; a body counts only when it re-hashes and its payload row
count matches the manifest.
