from audit_source_descriptions import description_features, single_foul_evidence


def test_multiple_fouls_can_have_enforced_and_declined_markers():
    features = description_features('PENALTY on NO, Illegal Shift, enforced at ARI 38 - No Play. '
                                    'Penalty on NO, Illegal Formation, declined.')
    assert features['enforced'] and features['declined'] and features['no_play']
    assert features['multiple_penalty_mentions']


def test_missing_text_is_unknown_evidence_not_a_decision():
    assert not any(description_features(None).values())


def test_offsetting_marker_is_not_enforcement():
    features = description_features('PENALTIES offsetting - No Play.')
    assert features['offsetting'] and features['no_play']
    assert not features['enforced']


def test_single_foul_triage_rejects_multiple_or_conflicting_evidence():
    assert single_foul_evidence('PENALTY on NO, enforced at NO 34 - No Play.') == 'enforced'
    assert single_foul_evidence('Penalty on NO, declined.') == 'declined'
    assert single_foul_evidence('PENALTY on NO, enforced at NO 34; penalty on ARI, declined.') == 'ambiguous_or_no_foul_mention'
    assert single_foul_evidence('PENALTY enforced, then declined.') == 'ambiguous_or_no_disposition_marker'
