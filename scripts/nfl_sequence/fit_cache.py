"""Opt-in disk memo for pure historical fits: the result is reused only for the exact same input, code and interpreter.

A fit is cached under a key that hashes its name, the source of every file its code reads, the Python build, and its input
values in their iteration order (the order can change float sums, so it is part of the input). There is no separate notion of
"the same cutoff" or "the same database": a fit is reused only when it would be handed byte-for-byte the same input again, so a
different cutoff, a changed historical row or a changed fit cannot return a stale table.

Set SLC_FIT_CACHE_DIR to enable it; unset, every fit is computed as before. Each use prints one line to stderr naming the fit
and whether it was a hit, a miss, or a rebuild of an unreadable entry. Entries are written to a per-process temp file and
renamed into place, so a concurrent reader sees the whole previous entry or the whole new one, never a partial file.
"""
import hashlib
import json
import os
import pickle
import sys
from pathlib import Path

SCHEMA = 'slc-fit-cache-1'


def _input_text(inputs):
    """repr of plain builtins (dict, list, tuple, range, str, int, float, bool, None): it keeps types and iteration order.
    An object whose repr carries a memory address (a defaultdict's factory, a class instance) would make a key that never
    repeats, so it is refused; callers pass plain copies."""
    text = repr(inputs)
    if ' at 0x' in text or 'Counter(' in text:  # a Counter's repr is ordered by count, not by iteration
        raise TypeError('fit cache inputs must be plain builtins; an object with an address or a reordered repr was passed')
    return text


def key(name, inputs, code_files):
    digest = hashlib.sha256()
    header = {'schema': SCHEMA, 'name': name, 'python': sys.version,
              'code': {Path(path).name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
                       for path in sorted({str(Path(p).resolve()) for p in (*code_files, __file__)})}}
    digest.update(json.dumps(header, sort_keys=True).encode())
    digest.update(_input_text(inputs).encode('utf-8', 'surrogatepass'))
    return digest.hexdigest()


def memo(name, inputs, compute, code_files):
    """compute() if the cache is off; otherwise the stored result for this exact (name, inputs, code), computing it once."""
    cache_dir = os.environ.get('SLC_FIT_CACHE_DIR')
    if not cache_dir:
        return compute()
    entry_key = key(name, inputs, code_files)
    path = Path(cache_dir) / f'{name}-{entry_key[:32]}.pkl'
    status = 'miss'
    if path.exists():
        try:
            with path.open('rb') as source:
                stored = pickle.load(source)
            if stored.get('key') == entry_key:
                print(f'fit-cache {name} {entry_key[:12]}: hit', file=sys.stderr)
                return stored['result']
            status = 'rebuilt (key mismatch)'
        except Exception as error:  # an unreadable entry is rebuilt, and said so
            status = f'rebuilt (unreadable: {type(error).__name__})'
    result = compute()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'{path.stem}.{os.getpid()}.tmp')
    with tmp.open('wb') as sink:
        pickle.dump({'key': entry_key, 'name': name, 'result': result}, sink, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, path)
    print(f'fit-cache {name} {entry_key[:12]}: {status}', file=sys.stderr)
    return result
