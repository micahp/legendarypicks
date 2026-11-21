"""Canonical identities and pinned source policies for the six SLC families.

Policy metadata is recorded for every family. The shared capture adapter is
enabled only for variants whose pinned inputs and policies are wired; a build
gate remains in place until each variant has completed its package smoke run.
"""
from __future__ import annotations


_V1_LAYERS = [
    "score_clock_playcalling", "team_offense_defense_outcomes",
    "formation_personnel_outcomes", "defensive_coverage_outcomes",
    "dirichlet_player_target_carry_shares",
    "qb_decisions", "player_conditioned_outcomes", "target_role_priors",
    "decision_labels", "decision_row_filter", "playbook_priors", "point_splits",
    "team_streak_splits", "league_streak_splits", "exact_yardline_outcomes",
    "current_streak_context",
]
_V16_LAYERS = [layer for layer in _V1_LAYERS if layer != "defensive_coverage_outcomes"]
_V16_LAYERS += ["season_adaptation", "exact_distance_yardage_outcomes", "conditional_pass_labels"]
_SHARED_BLOCKER_FIX_ARGS = [
    "--slc-blocker-fix", "run_scramble_backoff",
    "--slc-blocker-fix", "long_field_goal_feasibility",
    "--slc-blocker-fix", "blocked_kick_source_audit",
    "--slc-blocker-fix", "blocked_kick_geometry",
    "--slc-blocker-fix", "safety_free_kick_boundaries",
]


MODELS = {
    "v1": {
        "family": "v1", "code_commit": "58ef3861e5f3cc4006ab627102e55bd432ab399d",
        "source_root_env": "SLC_V1_SOURCE_ROOT", "profile": "v1_full_stack",
        "profile_model_id": "SLC_v1_full_stack",
        "build_inputs": [
            {"flag": "--playcall-artifact", "env": "SLC_V1_PLAYCALL_ARTIFACT"},
            {"flag": "--playcall-streak-file", "env": "SLC_V1_STREAK_FILE"},
        ],
        "build_args": [],
        "rules_policy": "nfl-2026-e2-successor", "enabled_layers": list(_V1_LAYERS),
        "experimental_flags": {}, "training_cutoff": "before_game_season_week_1",
        "training_cutoff_scope": "before_season_week_1",
        "required_components": ["play_pool", "kickoffs", "kick_outcomes", "overtime_drives",
                                "safety_kicks", "playcall_artifact", "streak_context"],
        "runtime_supported": True,
        "use_playcall_frame_cache": True,
        "build_supported": True,
    },
    "v1.5": {
        "family": "v1.5", "code_commit": "2eab8a89efffad23c00a1d451ac80e856579ac5a",
        "source_root_env": "SLC_V1_5_SOURCE_ROOT", "profile": "v1_full_stack",
        "profile_model_id": "SLC_v1_full_stack",
        "build_inputs": [
            {"flag": "--playcall-artifact", "env": "SLC_V1_5_PLAYCALL_ARTIFACT"},
            {"flag": "--playcall-streak-file", "env": "SLC_V1_5_STREAK_FILE"},
        ],
        "build_args": [],
        "rules_policy": "nfl-2026-e2-successor", "enabled_layers": list(_V1_LAYERS),
        "experimental_flags": {}, "training_cutoff": "before_game_season_week_1",
        "training_cutoff_scope": "before_season_week_1",
        "required_components": ["v1_full_stack", "season_cutoff_reference"],
        "runtime_supported": True, "build_supported": True,
        "use_playcall_frame_cache": True,
    },
    "v1.6": {
        "family": "v1.6", "code_commit": "a109bacfcba08dc68bf2b12cd3d0ac2d55306d16",
        "source_root_env": "SLC_V1_6_SOURCE_ROOT", "profile": "v1_6_candidate",
        "profile_model_id": "SLC_v1_6_candidate",
        "build_inputs": [
            {"flag": "--playcall-artifact", "env": "SLC_V1_6_PLAYCALL_ARTIFACT"},
            {"flag": "--playcall-streak-file", "env": "SLC_V1_6_STREAK_FILE"},
            {"flag": "--slc-materialized-history", "env": "SLC_V1_6_MATERIALIZED_HISTORY"},
        ],
        "build_args": ["--playcall-pass-label-mode", "conditional"],
        "rules_policy": "nfl-2026-e2-successor", "enabled_layers": list(_V16_LAYERS),
        "experimental_flags": {"coverage_outcomes": False, "season_adaptation": True,
                                "exact_distance_yardage": True, "pass_labels": "conditional"},
        "training_cutoff": "before_game_week",
        "training_cutoff_scope": "before_game_week",
        "required_components": ["v1_full_stack", "season_materialization", "exact_distance_yardage"],
        "runtime_supported": True, "use_playcall_frame_cache": True, "build_supported": True,
    },
    "v1.7": {
        "family": "v1.7", "code_commit": "1ca59e0d038b594b87c0dd5b4c78b0711b022043",
        "source_root_env": "SLC_V1_7_SOURCE_ROOT", "profile": "v1_7_candidate",
        "profile_model_id": "SLC_v1_7_candidate",
        "minimum_python": [3, 10],
        "build_inputs": [
            {"flag": "--playcall-artifact", "env": "SLC_V1_7_PLAYCALL_ARTIFACT"},
            {"flag": "--playcall-streak-file", "env": "SLC_V1_7_STREAK_FILE"},
            {"flag": "--slc-materialized-history", "env": "SLC_V1_7_MATERIALIZED_HISTORY"},
            {"flag": "--slc-penalty-model", "env": "SLC_V1_7_PENALTY_MODEL"},
            {"flag": "--slc-penalty-manifest", "env": "SLC_V1_7_PENALTY_MANIFEST"},
            {"flag": "--slc-penalty-source-manifest", "env": "SLC_V1_7_PENALTY_SOURCE_MANIFEST"},
        ],
        "build_args": ["--playcall-pass-label-mode", "conditional",
                       "--slc-penalty-ruling-policy", "research"],
        "rules_policy": "nfl-2026-e2-successor-v1.7-penalty-transitions",
        "enabled_layers": list(_V16_LAYERS) + ["penalty_proposal_and_enforcement"],
        "experimental_flags": {"penalty_layer": "candidate", "penalty_ruling_policy": "research"},
        "training_cutoff": "before_game_week",
        "training_cutoff_scope": "before_game_week",
        "required_components": ["v1_6_candidate", "penalty_fit", "research_ruling_policy"],
        "runtime_supported": True, "use_playcall_frame_cache": True, "build_supported": True,
    },
    "v2": {
        "family": "v2", "code_commit": "8a1d984229cdc20f5ad076ebd81edc7f1be90c75",
        "source_root_env": "SLC_V2_SOURCE_ROOT", "profile": "v1_full_stack",
        "profile_model_id": "SLC_v1_full_stack",
        "build_inputs": [
            {"flag": "--playcall-artifact", "env": "SLC_V2_PLAYCALL_ARTIFACT"},
            {"flag": "--playcall-streak-file", "env": "SLC_V2_STREAK_FILE"},
            {"flag": "--playcall-fg-kicker", "env": "SLC_V2_KICKER_TABLE"},
            {"flag": "--playcall-fg-kicker-sha256", "env": "SLC_V2_KICKER_SHA256", "kind": "value"},
            {"flag": "--participation-snap-counts", "env": "SLC_V2_SNAP_COUNTS"},
            {"flag": "--participation-snap-counts-sha256", "env": "SLC_V2_SNAP_COUNTS_SHA256", "kind": "value"},
        ],
        "build_args": ["--slc-v2", "--rng-protocol", "v2", "--playcall-pass-label-mode", "conditional",
                       "--playcall-decision", "--no-export-plays",
                       "--slc-blocker-fix", "run_scramble_backoff",
                       "--slc-blocker-fix", "long_field_goal_feasibility",
                       "--slc-blocker-fix", "blocked_kick_source_audit",
                       "--slc-blocker-fix", "blocked_kick_geometry",
                       "--slc-blocker-fix", "safety_free_kick_boundaries"],
        "rules_policy": "nfl-2026-e2-successor-v2",
        "enabled_layers": list(_V1_LAYERS) + ["season_adaptation", "participation_lineup",
                                              "snap_count_update", "team_kicker_field_goals",
                                              "blocker_fixes", "rng_protocol_v2"],
        "experimental_flags": {"slc_v2": True}, "training_cutoff": "before_game_week",
        "training_cutoff_scope": "before_game_week",
        "required_components": ["v1.5_stack", "v2_pinned_tables", "participation_snap_counts"],
        "runtime_supported": True, "use_playcall_frame_cache": True, "build_supported": True,
    },
    "pbv1": {
        "family": "pbv1", "code_commit": "8a1d984229cdc20f5ad076ebd81edc7f1be90c75",
        "source_root_env": "SLC_V2_SOURCE_ROOT", "profile": "v1_full_stack",
        "profile_model_id": "SLC_v1_full_stack",
        "build_inputs": [
            {"flag": "--playcall-artifact", "env": "SLC_PBV1_PLAYCALL_ARTIFACT"},
            {"flag": "--playcall-streak-file", "env": "SLC_PBV1_STREAK_FILE"},
            {"flag": "--playcall-pbv1-package", "env": "SLC_PBV1_PACKAGE"},
        ],
        "build_args": list(_SHARED_BLOCKER_FIX_ARGS),
        "rules_policy": "nfl-2026-e2-successor",
        "enabled_layers": list(_V1_LAYERS) + ["pbv1_personnel_package"],
        "experimental_flags": {"pbv1_package_sampler": True, "participation_field": False,
                                "slc_v2": False, "pbv1_integration": "label_only"},
        "training_cutoff": "before_game_season_week_1",
        "training_cutoff_scope": "before_season_week_1",
        "required_components": ["v1.5_stack", "pbv1_distribution"],
        "runtime_supported": True, "use_playcall_frame_cache": True, "build_supported": True,
    },
    "pbv1-off": {
        "family": "pbv1", "code_commit": "8a1d984229cdc20f5ad076ebd81edc7f1be90c75",
        "source_root_env": "SLC_V2_SOURCE_ROOT", "profile": "v1_full_stack",
        "profile_model_id": "SLC_v1_full_stack",
        "build_inputs": [
            {"flag": "--playcall-artifact", "env": "SLC_PBV1_OFF_PLAYCALL_ARTIFACT"},
            {"flag": "--playcall-streak-file", "env": "SLC_PBV1_OFF_STREAK_FILE"},
        ],
        "build_args": list(_SHARED_BLOCKER_FIX_ARGS),
        "rules_policy": "nfl-2026-e2-successor",
        "enabled_layers": list(_V1_LAYERS),
        "experimental_flags": {"pbv1_package_sampler": False, "participation_field": False,
                                "slc_v2": False, "pbv1_integration": "off"},
        "training_cutoff": "before_game_season_week_1",
        "training_cutoff_scope": "before_season_week_1",
        "required_components": ["v1.5_stack"],
        "runtime_supported": True, "use_playcall_frame_cache": True, "build_supported": True,
    },
}

ALIASES = {name: name for name in MODELS}
ALIASES.update({"v1.7-penalties-on": "v1.7", "pbv1-label-only": "pbv1"})


def get_model(model_id):
    try:
        return MODELS[ALIASES[model_id]]
    except KeyError as exc:
        raise ValueError(f"unknown SLC model {model_id!r}; choose one of {', '.join(MODELS)}") from exc
