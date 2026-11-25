#!/bin/bash
# V2 layer ablation batch (SLC-V2-LAYER-ABLATION-SPEC-2026-11-24, amendment 1). Two arms at a time, 3 workers each.
cd /root/v2-ablation
ARMS="A00_control A13_team_offense_defense_outcomes A14_player_conditioned_outcomes A17_no_event_multipliers A18_no_row_filters A19_no_multipliers_no_filters A22_league_outcomes A01_score_clock_playcalling A02_point_splits A03_team_streak_splits A04_league_streak_splits A05_current_streak_context A07_decision_labels A08_decision_row_filter A09_playbook_priors A10_formation_personnel_outcomes A11_defensive_coverage_outcomes A12_exact_yardline_outcomes A15_dirichlet_player_shares A16_target_role_priors A23_minimal_situational"
echo "start $(date -u +%FT%T)" >> out/batch.status
printf '%s\n' $ARMS | xargs -P 2 -I{} sh -c 'env OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 ABLATION_ARM={} /usr/bin/python3.12 runtime/run_arm.py --out out/batch --seeds 100 --workers 3 > out/batch-{}.log 2>&1; echo "{} exit=$? $(date -u +%T)" >> out/batch.status'
echo "ALL_DONE $(date -u +%FT%T)" >> out/batch.status
