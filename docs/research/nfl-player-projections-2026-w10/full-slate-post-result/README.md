# Week 10 2026, full slate, post-result

Projections for all 14 week 10 games (335 player games), made after the games were played.
Use for comparison with the SLC model family run only. Not a pregame forecast; not valid for grading.

- Model: nfl_player_projections_job.py (v2 engine), base scenario, 1,000 sims per player game.
- The job skips games that already have a final score. This run hides week 10 scores in a temporary view so every game is projected. Nothing was written to the database.
- Calibration: the week 10 forward Platt map (a 0.38668, b +0.17534, fit on 68,039 items) is in the JSON. The Platt step is applied per prop line at request time; this file stores simulated stats only.
- Stats per row: [mean, median, p10, p90] for each stat in the base scenario.
