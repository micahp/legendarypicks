# Forward Platt candidate, 2026 weeks 3 to 10 (retrospective)

Run: `nfl_prop_forward_platt_candidate.py --season 2026 --boot 200`, read-only on prod, 2026-11-16 12:20 to 12:24 CST.

- Items: 54,444 calibrated (61,339 graded). Player games: 1,568. Weeks in evaluation: 3 to 10.
- Overall Brier: forward Platt 0.2463, market 0.2464, raw player V2 0.2641.
- Platt vs raw V2: improvement, interval above zero (established).
- Platt vs market: no established difference.
- Weekly fits: each week uses only earlier weeks (train_through_week = week - 1).

Limits (from the script's own report):
- Actual pre-kickoff projection and injury snapshots were not independently verified. Week 10 projections in prod were written after the games.
- Conditional-on-played subset is an observed-participation selection.
- No independent market increment is claimed.

Files: report.json (full output), graded.csv (scored rows, filter by week), run.log (stage timing).
