from audit_penalty_clauses import parse_clauses


def test_mixed_fouls_are_separate_and_keep_text_dispositions():
    clauses = parse_clauses(
        'PENALTY on DET-23-R.Ya-Sin, Defensive Pass Interference, 23 yards, '
        'enforced at TB 17 - No Play. Penalty on DET-21-A.Robertson, '
        'Defensive Holding, declined.')

    assert len(clauses) == 2
    assert clauses[0]['type_text'] == 'Defensive Pass Interference'
    assert clauses[0]['team_text'] == 'DET'
    assert clauses[0]['text_markers'] == ['enforced_text']
    assert clauses[0]['disposition'] == 'accepted'
    assert clauses[1]['type_text'] == 'Defensive Holding'
    assert clauses[1]['text_markers'] == ['declined_text']
    assert clauses[1]['disposition'] == 'declined'


def test_text_without_team_player_and_placed_status_is_preserved():
    clauses = parse_clauses(
        'PENALTY on BAL, Kickoff Short of Landing Zone, placed at BUF 40.')

    assert len(clauses) == 1
    assert clauses[0]['team_text'] == 'BAL'
    assert clauses[0]['type_text'] == 'Kickoff Short of Landing Zone'
    assert clauses[0]['text_markers'] == ['placed_text']
    assert clauses[0]['disposition'] == 'accepted'
    assert clauses[0]['disposition_basis'] == 'explicit_placement_text'


def test_unresolved_clause_is_not_assigned_a_disposition():
    clauses = parse_clauses('PENALTY on BUF-55-J.Hughes, Face Mask, 5 yards.')

    assert len(clauses) == 1
    assert clauses[0]['text_markers'] == []
    assert clauses[0]['unclassified_text']
    assert clauses[0]['disposition'] == 'unknown'


def test_simple_declined_clause_without_foul_type_is_classified():
    clauses = parse_clauses('Penalty on STL-T.Horne, declined.')

    assert len(clauses) == 1
    assert clauses[0]['team_text'] == 'STL'
    assert clauses[0]['type_text'] is None
    assert clauses[0]['disposition'] == 'declined'


def test_offsetting_wins_over_enforcement_spot_wording():
    clauses = parse_clauses(
        'Penalty on JAX, Offensive Holding, offsetting, enforced at JAX 14.')

    assert len(clauses) == 1
    assert clauses[0]['text_markers'] == ['offsetting_text', 'enforced_text']
    assert clauses[0]['disposition'] == 'offsetting'
