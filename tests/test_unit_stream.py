import io
import json

import pytest

from case_intelligence.pilot_uploads import PilotDocument, PilotStore
from case_intelligence.unit_stream import UnitRecordLimit, iter_unit_records


def test_stream_preserves_unicode_escapes_field_order_and_container_validation():
    rows = [{'number': i, 'text': ('🟠 synthetic \\" text ' * 200 if i == 2 else 'Synthetic')} for i in range(10)]
    class SmallReads(io.StringIO):
        def read(self, count=-1):
            assert 0 < count <= 65_536
            return super().read(min(count, 17))
    for payload in ({'version': 1, 'units': rows}, {'units': rows, 'version': 1}):
        for escaped in (True, False):
            assert list(iter_unit_records(SmallReads(json.dumps(payload, ensure_ascii=escaped)))) == rows
    for raw in ('{"version":2,"units":[]}', '{"version":1,"units":[]} trailing',
                '{"version":1,"units":[}', '{"version":1,"units":[],"units":[]}'):
        with pytest.raises(ValueError):
            list(iter_unit_records(SmallReads(raw)))


@pytest.mark.parametrize('closed', [True, False])
def test_record_bound_is_enforced_before_decoding_oversized_first_record(monkeypatch, closed):
    raw = '{"version":1,"units":[{"number":1,"text":"' + 'x' * 200_000
    if closed:
        raw += '"}]}'
    original = json.JSONDecoder.raw_decode
    decoded = []
    def decode(self, value, *args, **kwargs):
        decoded.append(len(value))
        assert len(value) <= 1024
        return original(self, value, *args, **kwargs)
    monkeypatch.setattr(json.JSONDecoder, 'raw_decode', decode)
    source = io.StringIO(raw)
    with pytest.raises(UnitRecordLimit):
        list(iter_unit_records(source, max_record_chars=1024))
    assert source.tell() == 65_536 and decoded


def test_callbacks_bound_input_and_check_deadline_before_decode(monkeypatch):
    class Expired(Exception):
        pass
    clock = [0]
    class SlowReads(io.StringIO):
        def read(self, count=-1):
            result = super().read(count)
            clock[0] += 2
            return result
    def check():
        if clock[0] > 1:
            raise Expired
    monkeypatch.setattr(json.JSONDecoder, 'raw_decode', lambda *args: pytest.fail('decoded after deadline'))
    with pytest.raises(Expired):
        list(iter_unit_records(SlowReads('{"version":1,"units":[]}'), budget_check=check))
    def charge(count):
        assert count == 65_536
        raise Expired
    with pytest.raises(Expired):
        list(iter_unit_records(io.StringIO(' ' * 200_000), read_check=charge))


def test_budgeted_document_refuses_materializing_loader_and_checks_inline():
    document = PilotDocument('a' * 32, 'Synthetic.txt', '', 'text/plain', 0, 'ready', '', [],
                             units_file='a' * 32 + '.json')
    called = []
    document._units_loader = lambda name: called.append(name) or ()
    with pytest.raises(RuntimeError, match='bounded derived text reader'):
        list(document.iter_parsed_units(budget_check=lambda: None))
    assert called == []
    assert list(document.iter_parsed_units()) == [] and len(called) == 1
    document.units = [{'number': 1, 'text': 'Synthetic'}]
    checkpoints = []
    assert len(list(document.iter_parsed_units(budget_check=lambda: checkpoints.append(1)))) == 1
    assert len(checkpoints) == 2


def test_store_streams_real_derived_file_without_whole_file_loader(tmp_path, monkeypatch):
    store = PilotStore(tmp_path / 'synthetic-store')
    source, _ = store.store_stream('Synthetic.txt', 'text/plain', io.BytesIO(b'Synthetic text'))
    assert source.units_file and not source.units
    monkeypatch.setattr(source, '_units_loader', lambda name: pytest.fail('whole file loader'))
    charged = []
    assert list(source.iter_parsed_units(read_check=charged.append))[0].text == 'Synthetic text'
    assert sum(charged) == len((store.derived / source.units_file).read_text())


def test_store_default_error_contract_and_budget_callback_identity(tmp_path, monkeypatch):
    from case_intelligence.exact_search_results import ExactSearchUnavailable
    from case_intelligence import unit_stream
    store = PilotStore(tmp_path / 'synthetic-error-contract')
    source, _ = store.store_stream('Synthetic.txt', 'text/plain', io.BytesIO(b'Synthetic'))
    for failure in (ValueError('synthetic callback'), ExactSearchUnavailable('synthetic budget')):
        def stop():
            raise failure
        with pytest.raises(type(failure)) as caught:
            list(source.iter_parsed_units(budget_check=stop))
        assert caught.value is failure
    (store.derived / source.units_file).write_text('{"version":1,"units":[')
    with pytest.raises(RuntimeError, match='could not be loaded'):
        list(source.iter_parsed_units())
    failure = UnitRecordLimit('synthetic record cap')
    def limited(*args, **kwargs):
        raise failure
    monkeypatch.setattr(unit_stream, 'iter_unit_records', limited)
    with pytest.raises(UnitRecordLimit) as caught:
        list(source.iter_parsed_units())
    assert caught.value is failure
