# Week 10, all twelve games: SLC family grading

Per game, per arm. Tier says which batch the numbers come from: `1000-seed` for the
frozen blocks, `100-seed` for the blocks re-run after the stop. Tiers are never mixed
inside one arm.

**Read with [../GRADING-CAVEATS.md](../GRADING-CAVEATS.md):** two tiers - 1,000-seed
blocks and 100-seed blocks - never mixed inside one arm. The binding precision limit is Monte
Carlo error, not the 0.01 step: one game's win probability is a single Bernoulli draw, and the
12-game arm spread of ~0.04 is inside one standard error (~0.06). Two seeds are excluded as
simulation errors (HOU_CLE v1.7 seed 300055, JAX_TEN v1.7-pr43 seed 300088;
`sack_fumble_lost` past the goal line - repair in PR #49). The v1.7 arms are PR #42 `6ac6180c`
and PR #43 `984751d5` at `--slc-profile v1_full_stack`, not PR #47 `v1_7_candidate`, so these
numbers do not validate the PR #47 candidate.


## Game level

| Game | Tier | Arm | Seeds | P(home) | Home Brier | Score error |
|---|---|---|---:|---:|---:|---:|
| BUF_NYJ | 1000-seed | v1 | 1000 | 32.8% | 0.108 | 13.60 |
| BUF_NYJ | 1000-seed | v1.5 | 1000 | 32.1% | 0.103 | 13.77 |
| BUF_NYJ | 1000-seed | v1.6 | 1000 | 33.9% | 0.115 | 13.39 |
| BUF_NYJ | 1000-seed | v1.7 | 1000 | 32.4% | 0.105 | 13.13 |
| BUF_NYJ | 1000-seed | v1.7-pr43 | 1000 | 32.5% | 0.106 | 12.59 |
| BUF_NYJ | 1000-seed | v2 | 1000 | 38.4% | 0.147 | 15.39 |
| CAR_NO | 1000-seed | v1 | 1000 | 74.2% | 0.551 | 10.50 |
| CAR_NO | 1000-seed | v1.5 | 1000 | 76.2% | 0.581 | 11.30 |
| CAR_NO | 1000-seed | v1.6 | 1000 | 75.3% | 0.567 | 10.86 |
| CAR_NO | 1000-seed | v1.7 | 1000 | 73.9% | 0.546 | 10.23 |
| CAR_NO | 100-seed | v1.7-pr43 | 100 | 69.0% | 0.476 | 9.59 |
| CAR_NO | 1000-seed | v2 | 1000 | 67.6% | 0.457 | 8.29 |
| HOU_CLE | 1000-seed | v1 | 1000 | 27.8% | 0.521 | 12.38 |
| HOU_CLE | 1000-seed | v1.5 | 1000 | 30.6% | 0.482 | 12.26 |
| HOU_CLE | 1000-seed | v1.6 | 1000 | 30.3% | 0.486 | 9.82 |
| HOU_CLE | 100-seed | v1.7 | 99 | 28.3% | 0.514 | 14.69 |
| HOU_CLE | 100-seed | v1.7-pr43 | 100 | 36.0% | 0.410 | 13.96 |
| HOU_CLE | 1000-seed | v2 | 1000 | 31.5% | 0.469 | 14.32 |
| JAX_TEN | 1000-seed | v1 | 1000 | 25.8% | 0.067 | 19.86 |
| JAX_TEN | 1000-seed | v1.5 | 1000 | 26.8% | 0.072 | 19.56 |
| JAX_TEN | 1000-seed | v1.6 | 1000 | 24.3% | 0.059 | 16.30 |
| JAX_TEN | 100-seed | v1.7 | 100 | 20.0% | 0.040 | 20.34 |
| JAX_TEN | 100-seed | v1.7-pr43 | 99 | 20.2% | 0.041 | 18.99 |
| JAX_TEN | 1000-seed | v2 | 1000 | 29.9% | 0.089 | 22.31 |
| KC_ATL | 1000-seed | v1 | 1000 | 23.8% | 0.057 | 13.71 |
| KC_ATL | 100-seed | v1.5 | 100 | 21.0% | 0.044 | 12.66 |
| KC_ATL | 100-seed | v1.6 | 100 | 28.0% | 0.078 | 13.72 |
| KC_ATL | 100-seed | v1.7 | 100 | 17.0% | 0.029 | 11.59 |
| KC_ATL | 100-seed | v1.7-pr43 | 100 | 21.0% | 0.044 | 12.35 |
| KC_ATL | 100-seed | v2 | 100 | 23.0% | 0.053 | 13.34 |
| LA_ARI | 100-seed | v1 | 100 | 29.0% | 0.084 | 23.19 |
| LA_ARI | 100-seed | v1.5 | 100 | 40.0% | 0.160 | 24.30 |
| LA_ARI | 100-seed | v1.6 | 100 | 46.0% | 0.212 | 26.62 |
| LA_ARI | 100-seed | v1.7 | 100 | 37.0% | 0.137 | 24.98 |
| LA_ARI | 100-seed | v1.7-pr43 | 100 | 36.0% | 0.130 | 23.33 |
| LA_ARI | 100-seed | v2 | 100 | 29.0% | 0.084 | 23.07 |
| MIA_IND | 100-seed | v1 | 100 | 47.0% | 0.281 | 5.62 |
| MIA_IND | 100-seed | v1.5 | 100 | 49.0% | 0.260 | 3.57 |
| MIA_IND | 100-seed | v1.6 | 100 | 33.0% | 0.449 | 7.16 |
| MIA_IND | 100-seed | v1.7 | 100 | 40.0% | 0.360 | 5.11 |
| MIA_IND | 100-seed | v1.7-pr43 | 100 | 45.0% | 0.303 | 5.86 |
| MIA_IND | 100-seed | v2 | 100 | 34.0% | 0.436 | 8.30 |
| MIN_GB | 100-seed | v1 | 100 | 55.0% | 0.303 | 22.27 |
| MIN_GB | 100-seed | v1.5 | 100 | 60.0% | 0.360 | 23.90 |
| MIN_GB | 100-seed | v1.6 | 100 | 69.0% | 0.476 | 25.81 |
| MIN_GB | 100-seed | v1.7 | 100 | 57.0% | 0.325 | 23.49 |
| MIN_GB | 100-seed | v1.7-pr43 | 100 | 65.0% | 0.423 | 25.24 |
| MIN_GB | 100-seed | v2 | 100 | 73.0% | 0.533 | 25.93 |
| NE_DET | 1000-seed | v1 | 1000 | 58.2% | 0.175 | 22.68 |
| NE_DET | 1000-seed | v1.5 | 1000 | 57.8% | 0.178 | 22.77 |
| NE_DET | 1000-seed | v1.6 | 1000 | 58.7% | 0.171 | 22.35 |
| NE_DET | 1000-seed | v1.7 | 1000 | 65.4% | 0.120 | 20.56 |
| NE_DET | 1000-seed | v1.7-pr43 | 1000 | 63.0% | 0.137 | 20.65 |
| NE_DET | 1000-seed | v2 | 1000 | 57.8% | 0.178 | 22.43 |
| PIT_CIN | 100-seed | v1 | 100 | 68.0% | 0.102 | 14.73 |
| PIT_CIN | 100-seed | v1.5 | 100 | 64.0% | 0.130 | 15.80 |
| PIT_CIN | 100-seed | v1.6 | 100 | 68.0% | 0.102 | 13.85 |
| PIT_CIN | 100-seed | v1.7 | 100 | 65.0% | 0.122 | 15.16 |
| PIT_CIN | 100-seed | v1.7-pr43 | 100 | 58.0% | 0.176 | 17.04 |
| PIT_CIN | 100-seed | v2 | 100 | 65.0% | 0.122 | 17.36 |
| SEA_LV | 100-seed | v1 | 100 | 32.0% | 0.102 | 9.04 |
| SEA_LV | 100-seed | v1.5 | 100 | 30.0% | 0.090 | 12.41 |
| SEA_LV | 100-seed | v1.6 | 100 | 26.0% | 0.068 | 12.93 |
| SEA_LV | 100-seed | v1.7 | 100 | 32.0% | 0.102 | 10.84 |
| SEA_LV | 100-seed | v1.7-pr43 | 100 | 28.0% | 0.078 | 10.58 |
| SEA_LV | 100-seed | v2 | 100 | 45.0% | 0.203 | 8.91 |
| SF_DAL | 100-seed | v1 | 100 | 52.0% | 0.270 | 37.75 |
| SF_DAL | 100-seed | v1.5 | 100 | 58.0% | 0.336 | 38.64 |
| SF_DAL | 100-seed | v1.6 | 100 | 60.0% | 0.360 | 32.22 |
| SF_DAL | 100-seed | v1.7 | 100 | 50.0% | 0.250 | 38.46 |
| SF_DAL | 100-seed | v1.7-pr43 | 100 | 61.0% | 0.372 | 40.93 |
| SF_DAL | 100-seed | v2 | 100 | 44.0% | 0.194 | 39.31 |

## Prop level (pre-kickoff lines)

| Game | Arm | Tier | Items | Prop Brier | Market Brier |
|---|---|---|---:|---:|---:|
| BUF_NYJ | v1 | 1000-seed | 192 | 0.4029 | 0.2499 |
| BUF_NYJ | v1.5 | 1000-seed | 192 | 0.4004 | 0.2499 |
| BUF_NYJ | v1.6 | 1000-seed | 192 | 0.4068 | 0.2499 |
| BUF_NYJ | v1.7 | 1000-seed | 192 | 0.3736 | 0.2499 |
| BUF_NYJ | v1.7-pr43 | 1000-seed | 192 | 0.3798 | 0.2499 |
| BUF_NYJ | v2 | 1000-seed | 192 | 0.3115 | 0.2499 |
| CAR_NO | v1 | 1000-seed | 238 | 0.2991 | 0.2505 |
| CAR_NO | v1.5 | 1000-seed | 238 | 0.3053 | 0.2505 |
| CAR_NO | v1.6 | 1000-seed | 238 | 0.3060 | 0.2505 |
| CAR_NO | v1.7 | 1000-seed | 238 | 0.2730 | 0.2505 |
| CAR_NO | v1.7-pr43 | 100-seed | 238 | 0.2674 | 0.2505 |
| CAR_NO | v2 | 1000-seed | 238 | 0.2574 | 0.2505 |
| HOU_CLE | v1 | 1000-seed | 280 | 0.2645 | 0.2499 |
| HOU_CLE | v1.5 | 1000-seed | 280 | 0.2631 | 0.2499 |
| HOU_CLE | v1.6 | 1000-seed | 280 | 0.2604 | 0.2499 |
| HOU_CLE | v1.7 | 100-seed | 280 | 0.2985 | 0.2499 |
| HOU_CLE | v1.7-pr43 | 100-seed | 280 | 0.3058 | 0.2499 |
| HOU_CLE | v2 | 1000-seed | 280 | 0.2766 | 0.2499 |
| JAX_TEN | v1 | 1000-seed | 293 | 0.2171 | 0.2501 |
| JAX_TEN | v1.5 | 1000-seed | 293 | 0.2147 | 0.2501 |
| JAX_TEN | v1.6 | 1000-seed | 293 | 0.2080 | 0.2501 |
| JAX_TEN | v1.7 | 100-seed | 293 | 0.2264 | 0.2501 |
| JAX_TEN | v1.7-pr43 | 100-seed | 293 | 0.2354 | 0.2501 |
| JAX_TEN | v2 | 1000-seed | 293 | 0.2270 | 0.2501 |
| KC_ATL | v1 | 1000-seed | 213 | 0.3786 | 0.2482 |
| KC_ATL | v1.5 | 100-seed | 213 | 0.3695 | 0.2482 |
| KC_ATL | v1.6 | 100-seed | 213 | 0.3796 | 0.2482 |
| KC_ATL | v1.7 | 100-seed | 213 | 0.3889 | 0.2482 |
| KC_ATL | v1.7-pr43 | 100-seed | 213 | 0.3991 | 0.2482 |
| KC_ATL | v2 | 100-seed | 213 | 0.3982 | 0.2482 |
| LA_ARI | v1 | 100-seed | 279 | 0.3509 | 0.2493 |
| LA_ARI | v1.5 | 100-seed | 279 | 0.3521 | 0.2493 |
| LA_ARI | v1.6 | 100-seed | 279 | 0.3522 | 0.2493 |
| LA_ARI | v1.7 | 100-seed | 279 | 0.3254 | 0.2493 |
| LA_ARI | v1.7-pr43 | 100-seed | 279 | 0.3370 | 0.2493 |
| LA_ARI | v2 | 100-seed | 279 | 0.3410 | 0.2493 |
| MIA_IND | v1 | 100-seed | 231 | 0.3439 | 0.2466 |
| MIA_IND | v1.5 | 100-seed | 231 | 0.3536 | 0.2466 |
| MIA_IND | v1.6 | 100-seed | 231 | 0.3456 | 0.2466 |
| MIA_IND | v1.7 | 100-seed | 231 | 0.3231 | 0.2466 |
| MIA_IND | v1.7-pr43 | 100-seed | 231 | 0.3155 | 0.2466 |
| MIA_IND | v2 | 100-seed | 231 | 0.3035 | 0.2466 |
| MIN_GB | v1 | 100-seed | 193 | 0.3651 | 0.2479 |
| MIN_GB | v1.5 | 100-seed | 193 | 0.3561 | 0.2479 |
| MIN_GB | v1.6 | 100-seed | 193 | 0.3693 | 0.2479 |
| MIN_GB | v1.7 | 100-seed | 193 | 0.2749 | 0.2479 |
| MIN_GB | v1.7-pr43 | 100-seed | 193 | 0.3149 | 0.2479 |
| MIN_GB | v2 | 100-seed | 193 | 0.3228 | 0.2479 |
| NE_DET | v1 | 1000-seed | 237 | 0.2566 | 0.2506 |
| NE_DET | v1.5 | 1000-seed | 237 | 0.2585 | 0.2506 |
| NE_DET | v1.6 | 1000-seed | 237 | 0.2563 | 0.2506 |
| NE_DET | v1.7 | 1000-seed | 237 | 0.2393 | 0.2506 |
| NE_DET | v1.7-pr43 | 1000-seed | 237 | 0.2501 | 0.2506 |
| NE_DET | v2 | 1000-seed | 237 | 0.2391 | 0.2506 |
| PIT_CIN | v1 | 100-seed | 301 | 0.2310 | 0.2505 |
| PIT_CIN | v1.5 | 100-seed | 301 | 0.2323 | 0.2505 |
| PIT_CIN | v1.6 | 100-seed | 301 | 0.2282 | 0.2505 |
| PIT_CIN | v1.7 | 100-seed | 301 | 0.2273 | 0.2505 |
| PIT_CIN | v1.7-pr43 | 100-seed | 301 | 0.2479 | 0.2505 |
| PIT_CIN | v2 | 100-seed | 301 | 0.2605 | 0.2505 |
| SEA_LV | v1 | 100-seed | 224 | 0.2396 | 0.2498 |
| SEA_LV | v1.5 | 100-seed | 224 | 0.2578 | 0.2498 |
| SEA_LV | v1.6 | 100-seed | 224 | 0.2632 | 0.2498 |
| SEA_LV | v1.7 | 100-seed | 224 | 0.2565 | 0.2498 |
| SEA_LV | v1.7-pr43 | 100-seed | 224 | 0.2400 | 0.2498 |
| SEA_LV | v2 | 100-seed | 224 | 0.3086 | 0.2498 |
| SF_DAL | v1 | 100-seed | 243 | 0.4062 | 0.2508 |
| SF_DAL | v1.5 | 100-seed | 243 | 0.4148 | 0.2508 |
| SF_DAL | v1.6 | 100-seed | 243 | 0.3795 | 0.2508 |
| SF_DAL | v1.7 | 100-seed | 243 | 0.4221 | 0.2508 |
| SF_DAL | v1.7-pr43 | 100-seed | 243 | 0.4455 | 0.2508 |
| SF_DAL | v2 | 100-seed | 243 | 0.3553 | 0.2508 |
