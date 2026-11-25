#!/bin/bash
# V2 mechanism ablation batch, 20 matched seeds, priority order (spec amendment 2; seeds reduced for time)
cd /root/v2-ablation
rm -rf out/batch
ORDER="A00_control G1_no_multipliers G2_no_filters G3_no_multipliers_no_filters G4_league_outcomes T1_team_event_weights U3_player_outcome_strength Q4_qb_decision_model L1_label_generation F1_formation_choice C1_coverage_choice K3_streak_context P1_score_clock_playcalling D1_dirichlet_player_shares L6_label_outcome_modifiers S1_participation_lineup S2_kicker_field_goals R1_target_role_priors X1_exact_yardline_row_filter P2_point_split_shift P3_team_streak_shift P4_league_streak_shift Q1_qb_scramble_probability Q2_qb_target_role_selection Q3_qb_target_role_row_filter L2_label_outcome_lift L3_label_conditional_pass_model L4_label_row_filter L5_label_participant_allocation L7_playbook_label_priors K1_streak_outcome_lift K2_streak_row_filter F2_formation_outcome_lift F3_formation_row_filter C2_coverage_outcome_lift C3_coverage_row_filter U1_player_event_weights U2_player_row_weights Z1_minimal_situational"
A=$(echo $ORDER | tr ' ' '\n' | awk 'NR%2==1' | paste -sd,)
B=$(echo $ORDER | tr ' ' '\n' | awk 'NR%2==0' | paste -sd,)
echo "start $(date -u +%FT%T) seeds=20" > out/batch.status
env OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 /usr/bin/python3.12 runtime/run_arm.py --out out/batch --arms "$A" --seeds 20 --workers 3 > out/batch-1.log 2>&1 &
p1=$!
env OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 /usr/bin/python3.12 runtime/run_arm.py --out out/batch --arms "$B" --seeds 20 --workers 3 > out/batch-2.log 2>&1 &
p2=$!
wait $p1; echo "list1 exit=$? $(date -u +%T)" >> out/batch.status
wait $p2; echo "list2 exit=$? $(date -u +%T)" >> out/batch.status
echo "ALL_DONE $(date -u +%FT%T)" >> out/batch.status
