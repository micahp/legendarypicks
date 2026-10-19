#### Registered test (shared configuration, the verdict)

| Tour | Matches | M1 Brier | M2 on 2000 history Brier | M2 minus M1 | Match-clustered 95% | Years negative | Verdict |
| --- | ---: | ---: | ---: | ---: | --- | ---: | --- |
| ATP | 37,196 | 0.22475 | 0.22257 | -0.00218 | [-0.00273, -0.00164] | 12 of 12 | ATP: interval below zero, M2 beats M1 |
| WTA | 41,862 | 0.21658 | 0.21626 | -0.00032 | [-0.00079, +0.00016] | 9 of 12 | WTA: interval contains zero |

Deployed M2 (2020 history) minus M1, for reference: ATP +0.01385 [+0.01243, +0.01527]; WTA +0.01905 [+0.01770, +0.02033]

#### Diagnostic: per-tour K sensitivity (K tuned 2015 to 2019, evaluated 2020 to 2026)

| Tour | K for M1 | K for M2 | M1 Brier 2020 to 2026 | M2 Brier 2020 to 2026 | M2 minus M1 | Match-clustered 95% | Years negative (of 7) | M2 minus M1 at K 32, 2020 to 2026 |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- |
| ATP | 24 | 32 | 0.22780 | 0.22584 | -0.00196 | [-0.00264, -0.00129] | 7 | -0.00212 [-0.00293, -0.00127] |
| WTA | 32 | 40 | 0.21498 | 0.21437 | -0.00061 | [-0.00119, +0.00000] | 5 | -0.00014 [-0.00085, +0.00057] |

#### Tuning scores (mean Brier, 2015 to 2019)

| Tour | Model | K 16 | K 24 | K 32 | K 40 | K 48 | Chosen K |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ATP | M1 | 0.22202 | 0.22088 | 0.22102 | 0.22184 | 0.22307 | 24 |
| ATP | M2 on 2000 history | 0.22164 | 0.21953 | 0.21877 | 0.21877 | 0.21927 | 32 |
| WTA | M1 | 0.22119 | 0.21900 | 0.21834 | 0.21849 | 0.21914 | 32 |
| WTA | M2 on 2000 history | 0.22224 | 0.21925 | 0.21782 | 0.21729 | 0.21735 | 40 |
