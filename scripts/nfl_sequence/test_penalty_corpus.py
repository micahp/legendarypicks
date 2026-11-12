import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import json

from scripts.nfl_sequence.penalty_corpus import COLUMNS, annotate, build, digest


def test_disposition_markers_do_not_depend_on_penalty_flag():
    rows = pa.table({'desc': ['PENALTY on A, declined', 'PENALTY on B, enforced; PENALTY on A declined',
                              None, 'PENALTY on A, enforced'], 'penalty': [0, 1, None, 1]})
    result = annotate(rows).to_pydict()
    assert result['text_declined'] == [True, True, False, False]
    assert result['single_disposition_marker'] == [True, False, False, True]
    assert result['penalty'] == [0, 1, None, 1]


def test_build_preserves_rows_and_refuses_changed_input(tmp_path):
    source = tmp_path / 'source.parquet'
    fields = {name: [None, None] for name in COLUMNS}
    fields['desc'] = ['PENALTY on A, declined', None]
    fields['penalty'] = [0, None]
    pq.write_table(pa.table(fields), source)
    manifest = tmp_path / 'source.json'
    manifest.write_text(json.dumps({'seasons': {'2025': {'source_path': str(source), 'source_sha256': digest(source)}}}))
    output = tmp_path / 'out'
    build(manifest, output, [2025], batch_size=1)
    assert pq.read_table(output / 'penalty-source-rows-2025.parquet')['penalty'].to_pylist() == [0, None]
    assert json.loads((output / 'manifest.json').read_text())['seasons']['2025']['rows'] == 2
    with pytest.raises(FileExistsError):
        build(manifest, output, [2025])
    source.write_bytes(b'changed')
    with pytest.raises(ValueError, match='hash mismatch'):
        build(manifest, tmp_path / 'bad', [2025])
    assert not (tmp_path / 'bad').exists()
