# ESPN historical field-goal source audit

**Observed:** 2026-11-01 10:52 UTC

**Endpoint:** `https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={game_id}`

**Normalizer:** `backend/pixel_red_zone.py::normalize_summary`, `mode="replay"`

Eight archived NFL summaries were fetched directly from ESPN through the same site API host used by the project. The normalizer found **34 field-goal attempts** with one explicit published yardage phrase each, across eight games. Distances ranged from **21 to 60 yards**. Every audited event had an ESPN play ID and a 64-character SHA-256 revision of the raw play payload. Distances came from the publisher's play text; field position was not used as a distance fallback.

## Sample plays

| Published distance | ESPN game | ESPN play/event ID | Canonical raw-play SHA-256 |
| ---: | --- | --- | --- |
| 21 yd | `401772827` | `401772827:ESPN:4017728271103` | `4b3a824a7e02d218858cdbd44728079e4f67ec468548a5eeaeef954560a0b05f` |
| 24 yd | `401772719` | `401772719:ESPN:401772719263` | `8cefa65160a1633331f92d5ecf9672871cd1bb41d49dad7dbb8c5c37d52d28ba` |
| 28 yd | `401772718` | `401772718:ESPN:4017727184166` | `8408787624f58e4a5a4c7d87cfaedff7caa931cc3915c2ba044da4e171739f8f` |
| 35 yd | `401772719` | `401772719:ESPN:4017727191800` | `158af13f4569c46773bd6c133699509afcf186d9698184282573115d4c869ca1` |
| 42 yd | `401772718` | `401772718:ESPN:401772718645` | `077f28e675a48faa9d832bdba506a9910048f5bd6b0fedfc9f195db5c7965de9` |
| 45 yd | `401772829` | `401772829:ESPN:4017728291916` | `6a839348abfdac49961c514d0c30784d1126d0e9680246723157ae741583ace7` |
| 48 yd | `401772719` | `401772719:ESPN:4017727193400` | `7485526ce2df8f0131e9eb9f4737b6aaf2bd3ab393e9b427c6d24188b0ed3330` |
| 50 yd | `401772718` | `401772718:ESPN:4017727182488` | `f192207e580282270f01400b149ace1d345a985b4048ebeb56f2ef0665dc372b` |
| 58 yd | `401772720` | `401772720:ESPN:4017727202283` | `bae7436c7114e32b79510f7d52202aa3f5b388fb910002b2ec2f549dee3ee6bc` |
| 60 yd | `401772721` | `401772721:ESPN:4017727213861` | `376d539aa018c236db48e87351cd8ff38e00acfcb5aff8e6a8c53149fc289815` |

## Snapshot coverage and request timing

| Game | Teams | ESPN `meta.lastUpdatedAt` | Summary request |
| --- | --- | --- | ---: |
| `401772718` | ARI at NO | 2025-09-07 20:01:40 UTC | 0.214 s |
| `401772719` | MIA at IND | 2025-09-07 19:47:30 UTC | 0.256 s |
| `401772720` | LV at NE | 2025-09-07 20:05:53 UTC | 0.224 s |
| `401772721` | PIT at NYJ | 2025-09-07 20:07:43 UTC | 0.257 s |
| `401772827` | NYG at WSH | 2025-09-07 20:13:40 UTC | 0.203 s |
| `401772828` | CAR at JAX | 2025-09-07 21:12:49 UTC | 0.222 s |
| `401772829` | CIN at CLE | 2025-09-07 20:01:19 UTC | 0.197 s |
| `401772830` | TB at ATL | 2025-09-07 20:27:04 UTC | 0.226 s |

These are request round-trip times for archived summaries in this environment. They do not measure live event-to-challenge latency or prove service-level availability.

At 10:52:05 UTC, ESPN's November 1, 2026 NFL scoreboard listed 12 scheduled games and marked each `pre`; no in-progress game was available for a live freshness or publisher-correction pilot. The API read confirms operational access and historical field coverage. API reachability alone does not establish a broader redistribution license.

## Remaining source validation

- Observe a live field-goal attempt through the production-intended ESPN ingestion path and verify source timestamp, play identity, distance, and time-to-Arcade listing.
- Observe or inject a real publisher correction into that path; verify the original challenge stays frozen and a revised challenge supersedes it.
- Confirm applicable data-use rights for the intended product surface before release.
