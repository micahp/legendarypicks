"""Team codes are translated in one place: backend/team_codes.py (2026-11-04).

A hand-written alias table anywhere else is how a spelling gets missed: the simulator's streak table (LA, WAS) was
read with LAR and WSH and skipped both clubs, and the ESPN projection capture respelled LAR to LA and lost every Rams
and Washington player, in dev and prod, without an error. This test scans every tracked source file and fails on any
literal pair 'X': 'Y' where X and Y are two spellings of the same club in a league. Translate with team_codes
(normalize, to_source, same_team, TeamKeyed), or scripts/nfl_team_codes.py, which reads it.
"""
import re
import subprocess
from pathlib import Path

import team_codes

REPO = Path(__file__).resolve().parents[1]
OWNER = 'backend/team_codes.py'
# Codes are written in capitals, sometimes with dots (MoneyPuck's T.B). Lower- or mixed-case strings are names
# ({"utah": "UTA"} maps a city), which this test leaves to team_codes' callers.
PAIR = re.compile(r"""['"]([A-Z][A-Z.]{1,4})['"]\s*:\s*['"]([A-Z][A-Z.]{1,4})['"]""")
SUFFIXES = ('.py', '.js', '.jsx', '.ts', '.tsx')


def _same_club(a, b):
    """The leagues in which a and b are two different spellings of one club."""
    if a.upper() == b.upper():
        return []
    leagues = []
    for league in team_codes.CANONICAL:
        try:
            if team_codes.normalize(league, a) == team_codes.normalize(league, b):
                leagues.append(league)
        except team_codes.UnknownTeamCode:
            continue
    return leagues


def find_alias_tables():
    files = subprocess.run(['git', 'ls-files'], cwd=REPO, capture_output=True, text=True, check=True).stdout.split()
    hits = []
    for name in files:
        if name == OWNER or not name.endswith(SUFFIXES) or '/node_modules/' in name:
            continue
        try:
            text = (REPO / name).read_text(encoding='utf-8')
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for a, b in PAIR.findall(line):
                leagues = _same_club(a, b)
                if leagues:
                    hits.append(f'{name}:{number}: {a!r}: {b!r} ({", ".join(leagues)})')
    return hits


CODE = re.compile(r"""['"]([A-Z][A-Z.]{1,4})['"]""")


def find_two_spellings_on_one_line():
    """Non-test code holding two spellings of one club on a line ("in ('LA', 'LAR')", .replace('WAS', 'WSH'), a SQL
    list of legacy codes): a translation outside the interface, whatever its shape. Tests may name both spellings."""
    files = subprocess.run(['git', 'ls-files'], cwd=REPO, capture_output=True, text=True, check=True).stdout.split()
    hits = []
    for name in files:
        base = name.rsplit('/', 1)[-1]
        if (name == OWNER or not name.endswith(SUFFIXES) or '/node_modules/' in name
                or base.startswith('test_') or base.endswith(('_test.py', '.test.ts', '.test.tsx', '.test.js'))):
            continue
        try:
            text = (REPO / name).read_text(encoding='utf-8')
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            codes = sorted(set(CODE.findall(line)))
            for i, a in enumerate(codes):
                leagues = next((_same_club(a, b) for b in codes[i + 1:] if _same_club(a, b)), None)
                if leagues:
                    hits.append(f'{name}:{number}: {line.strip()[:120]} ({", ".join(leagues)})')
                    break
    return hits


def test_no_line_of_app_code_translates_a_team_by_hand():
    hits = find_two_spellings_on_one_line()
    assert not hits, ('two spellings of one club on a line of app code; use backend/team_codes.py:\n'
                      + '\n'.join(hits))


def test_no_team_alias_table_outside_team_codes():
    hits = find_alias_tables()
    assert not hits, ('team-code translation outside backend/team_codes.py; use the interface instead:\n'
                      + '\n'.join(hits))


def test_the_scan_catches_the_shapes_it_exists_for():
    for line in ("TEAM_FIX = {'LAR': 'LA', 'WSH': 'WAS'}", 'X = {"WAS": "WSH"}', "{'TBL': 'TB'}", "{'CWS': 'CHW'}",
                 '{"PHX":"ARI", "T.B":"TBL"}'):
        assert any(_same_club(a, b) for a, b in PAIR.findall(line)), line
    for line in ("{'NYJ': 'NYG'}", "{'K': 'PK'}", "{'LA': 'LA'}", '{"utah": "UTA"}'):
        assert not any(_same_club(a, b) for a, b in PAIR.findall(line)), line


def test_team_keyed_meets_both_spellings_and_refuses_unknowns():
    table = team_codes.TeamKeyed('nfl', [('LA', 1), (('WAS', 3), 2)][:1])
    assert table['LAR'] == 1 and 'STL' in table and dict(table) == {'LAR': 1}
    pairs = team_codes.TeamKeyed('nfl', [(('WAS', 3), 2)], team_at=0)
    assert pairs[('WSH', 3)] == 2
    nhl = team_codes.TeamKeyed('nhl', [('TBL', 1)])
    assert nhl['TB'] == 1
    for bad in (lambda: table['XYZ'], lambda: 'XYZ' in table, lambda: team_codes.TeamKeyed('nfl', [('XYZ', 1)])):
        try:
            bad()
        except team_codes.UnknownTeamCode:
            continue
        raise AssertionError('an unknown code passed through')


def test_same_team_is_league_scoped():
    assert team_codes.same_team('nfl', 'WAS', 'WSH')
    assert team_codes.same_team('nba', 'WAS', 'WSH')
    assert not team_codes.same_team('mlb', 'ATH', 'WSH')
    assert team_codes.to_source('nfl', 'nflverse', 'STL') == 'LA'
    assert team_codes.to_source('mlb', 'statsapi', 'ARI') == 'AZ'
