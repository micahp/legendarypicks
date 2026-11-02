"""Cutoff-safe adapter for the 2025 depth-chart snapshot series (nflverse depth_charts_2025.parquet).

The file is a dated snapshot series, not a season and week table. Each row carries `dt`, the snapshot timestamp, and every
team shares the same snapshot times. A snapshot is used for a forecast only when its `dt` is at or before the cutoff. The
latest such snapshot for the team is the state. Nothing later is read.

Identity: GSIS ID when present and in the verified players index. ESPN ID only when it maps to exactly one verified GSIS ID.
No name matching. Unresolved identities are reported with their status, never guessed.

Roles: blank position fields are kept as UNKNOWN. A duplicate slot or a duplicate identity is flagged, never dropped.

Horizons: early (Tuesday 12:00 Eastern before the game day) and final (kickoff minus one hour).
"""
import bisect
import collections
import csv
import datetime as dt
import hashlib

UTC = dt.timezone.utc
UNKNOWN = 'UNKNOWN'
IDENTITY_STATUSES = ('gsis', 'gsis_unverified', 'espn_unique', 'ambiguous', 'unmatched')


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def parse_dt(text):
    return dt.datetime.strptime(text, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=UTC)


def _blank_to_none(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def load_snapshot_rows(path):
    import pyarrow.parquet as pq

    sha = sha256_file(path)
    table = pq.read_table(path).to_pydict()
    rows = []
    for i in range(len(table['dt'])):
        rank = table['pos_rank'][i]
        rows.append({
            'dt': parse_dt(table['dt'][i]),
            'team': table['team'][i],
            'player_name': table['player_name'][i],
            'espn_id': _blank_to_none(table['espn_id'][i]),
            'gsis_id': _blank_to_none(table['gsis_id'][i]),
            'pos_grp': _blank_to_none(table['pos_grp'][i]),
            'pos_slot': _blank_to_none(table['pos_slot'][i]),
            'pos_rank': None if rank is None else int(rank),
            'pos_abb': _blank_to_none(table['pos_abb'][i]),
            'pos_name': _blank_to_none(table['pos_name'][i]),
            'source_sha256': sha,
        })
    return rows


def identity_index(gsis_ids, espn_to_gsis):
    return {'gsis': set(gsis_ids), 'espn_to_gsis': {k: set(v) for k, v in espn_to_gsis.items()}}


def identity_index_from_players(path):
    gsis_ids = set()
    espn_to_gsis = collections.defaultdict(set)
    with open(path, newline='', encoding='utf-8') as handle:
        for record in csv.DictReader(handle):
            gsis = _blank_to_none(record.get('gsis_id'))
            espn = _blank_to_none(record.get('espn_id'))
            if gsis:
                gsis_ids.add(gsis)
            if gsis and espn:
                espn_to_gsis[espn].add(gsis)
    return identity_index(gsis_ids, espn_to_gsis)


def resolve_identity(record, index):
    gsis = record['gsis_id']
    if gsis:
        if gsis in index['gsis']:
            return 'gsis', gsis
        return 'gsis_unverified', None
    espn = record['espn_id']
    if not espn:
        return 'unmatched', None
    candidates = index['espn_to_gsis'].get(espn, set())
    if len(candidates) == 1:
        return 'espn_unique', next(iter(candidates))
    if len(candidates) > 1:
        return 'ambiguous', None
    return 'unmatched', None


class SnapshotStore:
    def __init__(self, rows):
        self.by_team_dt = collections.defaultdict(list)
        times = collections.defaultdict(set)
        for record in rows:
            self.by_team_dt[(record['team'], record['dt'])].append(record)
            times[record['team']].add(record['dt'])
        self.sorted_times = {team: sorted(values) for team, values in times.items()}
        self.series_times = sorted({record['dt'] for record in rows})


def _as_store(rows):
    return rows if isinstance(rows, SnapshotStore) else SnapshotStore(rows)


def latest_snapshot(rows, team, cutoff):
    times = _as_store(rows).sorted_times.get(team, [])
    position = bisect.bisect_right(times, cutoff) - 1
    if position < 0:
        return None, None
    snapshot = times[position]
    return snapshot, cutoff - snapshot


def depth_state(rows, team, cutoff, index, source_sha256):
    store = _as_store(rows)
    snapshot, staleness = latest_snapshot(store, team, cutoff)
    position = bisect.bisect_right(store.series_times, cutoff) - 1
    series_latest = store.series_times[position] if position >= 0 else None
    if snapshot is None:
        return {'team': team, 'cutoff': cutoff, 'snapshot_dt': None, 'staleness_seconds': None,
                'source_sha256': source_sha256, 'reason': 'no_snapshot_before_cutoff', 'entries': [],
                'counts': _counts([])}
    if snapshot != series_latest:
        return {'team': team, 'cutoff': cutoff, 'snapshot_dt': None, 'staleness_seconds': None,
                'team_latest_dt': snapshot, 'series_latest_dt': series_latest,
                'source_sha256': source_sha256, 'reason': 'team_snapshot_behind_series', 'entries': [],
                'counts': _counts([])}
    entries = []
    for record in store.by_team_dt[(team, snapshot)]:
        status, gsis = resolve_identity(record, index)
        entries.append({
            'team': team,
            'snapshot_dt': snapshot,
            'player_name': record['player_name'],
            'espn_id': record['espn_id'],
            'raw_gsis_id': record['gsis_id'],
            'gsis_id': gsis,
            'identity_status': status,
            'pos_grp': record['pos_grp'] or UNKNOWN,
            'pos_slot': record['pos_slot'] or UNKNOWN,
            'pos_rank': record['pos_rank'],
            'pos_abb': record['pos_abb'],
            'duplicate_slot': False,
            'duplicate_identity': False,
            'source_sha256': record['source_sha256'],
        })
    slot_counts = collections.Counter((e['pos_grp'], e['pos_slot'], e['pos_rank']) for e in entries)
    id_counts = collections.Counter(e['gsis_id'] for e in entries if e['gsis_id'])
    for e in entries:
        e['duplicate_slot'] = slot_counts[(e['pos_grp'], e['pos_slot'], e['pos_rank'])] > 1
        e['duplicate_identity'] = bool(e['gsis_id']) and id_counts[e['gsis_id']] > 1
    return {'team': team, 'cutoff': cutoff, 'snapshot_dt': snapshot,
            'staleness_seconds': int(staleness.total_seconds()), 'source_sha256': source_sha256,
            'reason': 'ok', 'entries': entries, 'counts': _counts(entries)}


def _counts(entries):
    counts = {status: 0 for status in IDENTITY_STATUSES}
    counts.update({'duplicate_slot': 0, 'duplicate_identity': 0, 'unknown_role': 0})
    for e in entries:
        counts[e['identity_status']] += 1
        counts['duplicate_slot'] += e['duplicate_slot']
        counts['duplicate_identity'] += e['duplicate_identity']
        counts['unknown_role'] += e['pos_grp'] == UNKNOWN or e['pos_slot'] == UNKNOWN
    return counts


def _nth_sunday(year, month, n):
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


def eastern_offset(day):
    start = _nth_sunday(day.year, 3, 2)
    end = _nth_sunday(day.year, 11, 1)
    return dt.timedelta(hours=-4) if start <= day < end else dt.timedelta(hours=-5)


def game_horizons(gameday, gametime):
    if not gametime:
        raise ValueError(f'kickoff time missing for game day {gameday}')
    day = dt.date.fromisoformat(gameday)
    hour, minute = (int(part) for part in gametime.split(':')[:2])
    kickoff = dt.datetime(day.year, day.month, day.day, hour, minute,
                          tzinfo=dt.timezone(eastern_offset(day))).astimezone(UTC)
    final = kickoff - dt.timedelta(hours=1)
    days_back = (day.weekday() - 1) % 7 or 7
    tuesday = day - dt.timedelta(days=days_back)
    early = dt.datetime(tuesday.year, tuesday.month, tuesday.day, 12, 0,
                        tzinfo=dt.timezone(eastern_offset(tuesday))).astimezone(UTC)
    return early, final
