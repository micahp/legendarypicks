"""Canonical identities and pinned source policies for the six SLC families.

Policy metadata is recorded for every family. Only V1 is enabled for package
build until its version-specific loader adapter and data-host parity gate exist.
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


MODELS = {
    "v1": {
        "family": "v1", "code_commit": "947cb2b836e16fd206e19133fa3d54df510cbb86",
        "source_root_env": "SLC_V1_SOURCE_ROOT", "profile": "v1_full_stack",
        "rules_policy": "nfl-2026-e2-successor", "enabled_layers": list(_V1_LAYERS),
        "experimental_flags": {}, "training_cutoff": "before_game_season_week_1",
        "required_components": ["play_pool", "kickoffs", "kick_outcomes", "overtime_drives",
                                "safety_kicks", "playcall_artifact", "streak_context"],
        "build_supported": True,
    },
    "v1.5": {
        "family": "v1.5", "code_commit": "77162c0172b56a9d9ffcc34ae85911fb5aa6b3d4",
        "source_root_env": "SLC_V1_5_SOURCE_ROOT", "profile": "v1_full_stack",
        "rules_policy": "nfl-2026-e2-successor", "enabled_layers": list(_V1_LAYERS),
        "experimental_flags": {}, "training_cutoff": "before_game_season_week_1",
        "required_components": ["v1_full_stack", "season_cutoff_reference"], "build_supported": False,
    },
    "v1.6": {
        "family": "v1.6", "code_commit": "d9655c8e9e32aadecd79a0ead5d9bf3038fd2b8f",
        "source_root_env": "SLC_V1_6_SOURCE_ROOT", "profile": "v1_6_candidate",
        "rules_policy": "nfl-2026-e2-successor", "enabled_layers": list(_V16_LAYERS),
        "experimental_flags": {"coverage_outcomes": False, "season_adaptation": True,
                                "exact_distance_yardage": True, "pass_labels": "conditional"},
        "training_cutoff": "before_game_season_week_1",
        "required_components": ["v1_full_stack", "season_materialization", "exact_distance_yardage"],
        "build_supported": False,
    },
    "v1.7": {
        "family": "v1.7", "code_commit": "547e9a29f3742a65a82c5a49f3fe3455d659c116",
        "source_root_env": "SLC_V1_7_SOURCE_ROOT", "profile": "v1_7_candidate",
        "rules_policy": "nfl-2026-e2-successor-v1.7-penalty-transitions",
        "enabled_layers": list(_V16_LAYERS) + ["penalty_proposal_and_enforcement"],
        "experimental_flags": {"penalty_layer": "candidate", "penalty_ruling_policy": "pinned_or_research"},
        "training_cutoff": "before_game_season_week_1",
        "required_components": ["v1_6_candidate", "penalty_fit", "penalty_rulings"],
        "build_supported": False,
    },
    "v2": {
        "family": "v2", "code_commit": "ff09078316dfc2b0deb7c2b28c694e5d01aa56ed",
        "source_root_env": "SLC_V2_SOURCE_ROOT", "profile": "v1_full_stack",
        "rules_policy": "nfl-2026-e2-successor-v2",
        "enabled_layers": list(_V1_LAYERS) + ["season_adaptation", "participation_lineup",
                                              "snap_count_update", "team_kicker_field_goals",
                                              "blocker_fixes", "rng_protocol_v2"],
        "experimental_flags": {"slc_v2": True}, "training_cutoff": "before_game_season_week_1",
        "required_components": ["v1.5_stack", "v2_pinned_tables", "participation_snap_counts"],
        "build_supported": False,
    },
    "pbv1": {
        "family": "pbv1", "code_commit": "ff09078316dfc2b0deb7c2b28c694e5d01aa56ed",
        "source_root_env": "SLC_V2_SOURCE_ROOT", "profile": "v1_full_stack",
        "rules_policy": "nfl-2026-e2-successor-v2",
        "enabled_layers": list(_V1_LAYERS) + ["pbv1_personnel_package"],
        "experimental_flags": {"pbv1_package_sampler": True, "participation_field": False},
        "training_cutoff": "before_game_season_week_1",
        "required_components": ["v1.5_stack", "pbv1_distribution"], "build_supported": False,
    },
}

ALIASES = {name: name for name in MODELS}
ALIASES.update({"v1.7-penalties-on": "v1.7", "pbv1-label-only": "pbv1"})


def get_model(model_id):
    try:
        return MODELS[ALIASES[model_id]]
    except KeyError as exc:
        raise ValueError(f"unknown SLC model {model_id!r}; choose one of {', '.join(MODELS)}") from exc
