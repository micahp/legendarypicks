# Fourth-down opportunity audit — 2026-11-11

## Finding

The available evidence points to **too many short-yardage situations**, rather than a clearly excessive number of fourth-down states overall. The most direct measured pathway is the distribution of third-down distances and the yards gained on failed third downs. The saved simulator replay also has fewer sacks and turnovers, which could extend drives, but this sample does not isolate their contribution to fourth-and-short frequency.

The simulator evidence is a 40-game SLC-v2 replay from commit `09a794f075947ed88973268e9535af6ad85c79d1`, across only BUF–MIN and ARI–SEA. It predates V1.6 and is not an independent matchup sample. The ordered-play artifact SHA-256 is `ba4414825ec83b0aa32f1fa047f17c9757c259a8295401c3c2bd7954dbf34ebe`. All 40 games validated and their scores matched the archived seeds.

Historical figures use regular-season weeks 1–18 in 2022–2025, 2,174 team-games and 23,599 drives. The read-only query result hash is `08265a1d5e1aa151b6c792807306dab3f6fc61976c9ed1ae9781a1db4af70d26`.

## Third downs

| Measure per team-game | Historical | Prior replay range |
| --- | ---: | ---: |
| Third-down attempts | 12.55 | 13.55–13.95 |
| Conversion rate | 39.7% | 46.5–49.6% |
| Attempts at 1–2 yards | 2.61 | 3.30–3.65 |
| Attempts at 3–5 yards | 3.14 | 4.10–4.55 |
| Attempts at 6–9 yards | 3.45 | 3.50–3.85 |
| Attempts at 10+ yards | 3.34 | 2.25–2.30 |

Historical conversion rates by distance were 63.8% (1–2 yards), 46.7% (3–5), 35.4% (6–9), and 18.8% (10+). Replay rates were above historical in every matchup-level aggregate, though these small samples cannot establish broad calibration. The replay encountered more short third downs and fewer long ones.

## Fourth-down opportunities and drive-ending events

| Measure | Historical | Prior replay range |
| --- | ---: | ---: |
| All fourth-down states per team-game | 6.82 | 6.55–7.05 |
| All fourth-down states per drive | 0.628 | 0.682–0.700 |
| Fourth-and-1–2 states per team-game | 1.37 | 1.75–2.10 |
| Sacks per team-game | 2.43 | 0.75–1.30 |
| Turnovers per team-game | 1.15 | 0.55–0.85 |
| Negative run/pass plays per team-game | 5.18 | 3.75–5.05 |

Total fourth-down frequency is close to historical in games per team-game, and modestly high per drive. The sharper gap is fourth-and-1–2: 28–54% above the historical rate. Fewer sacks and turnovers, and in some arms fewer negative plays, are plausible contributors to longer drives. This aggregate replay cannot quantify how much each contributes to short fourth-down states.

Among failed third downs that left fourth-and-1–2, historical partial positive gains occurred 0.80 times per team-game; the replay ranged from 0.85 to 1.55. This is close to historical in one arm and elevated in others. It is a plausible additional source of short fourth downs, especially in BUF–MIN, but it does not explain the entire cross-arm difference by itself.

## Correction selected for V1.6

Keep the fourth-down action policy unchanged. V1.6 enables the existing exact-yards-to-go yardage blend for run/pass outcomes:

- Use exact yards-to-go source rows when support is at least 50.
- Blend exact-distance and distance-bucket distributions with weight `n / (n + 25)`.
- Fall back to the distance bucket below minimum support.

This correction targets chain advancement and the gain distribution that determines whether a third-down failure leaves a short fourth down. On a 2025 holdout fitted on 2022–2024, the exact-distance blend improved line-to-gain Brier from 0.17894 to 0.17799 over 31,530 clean run/pass plays; the game-clustered 95% interval for the difference was −0.00135 to −0.00058. Third-down Brier changed from 0.21291 to 0.21213 over 6,527 plays, with 77.0% exact-distance support. These are modest offline gains, not proof of full-game correction.

The V1.6 profile requires this layer and records the decision and evidence in its model manifest. The saved replay is from an earlier model and cannot show whether V1.6 fixed the observed distance mix. Full-game V1.6 validation remains pending; do not describe the blocker as closed until that comparison reports third-down distance, yardage, sacks, turnovers, and fourth-down distance per drive on matched inputs.
