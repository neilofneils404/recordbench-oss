"""Synthetic readiness contracts shared by Linux GPU and local Mac CPU clients."""
from pathlib import Path

import pytest

from case_intelligence.media_evidence import TranscriptionV2Client


@pytest.mark.parametrize('device', ['cpu', 'cuda'])
def test_explicit_offline_diarization_degradation_is_admitted(monkeypatch, device):
    client = TranscriptionV2Client('http://127.0.0.1:8510', Path('/tmp/synthetic-token'))
    payload = {'status': 'degraded_ready', 'checks': {
        'degraded_diarization_allowed': True, 'offline_runtime': True,
        'inference_device': device, 'gpu_required': device == 'cuda',
        'reserved_gpu_ready': device == 'cuda',
    }}
    monkeypatch.setattr(client, '_request', lambda *a, **kw: payload)
    assert client.ready('synthetic-owner')


@pytest.mark.parametrize('change', [
    {'status': 'not_ready'},
    {'checks': {'reserved_gpu_ready': True, 'offline_runtime': True}},
    {'checks': {'inference_device': 'cpu', 'gpu_required': False, 'offline_runtime': False, 'degraded_diarization_allowed': True}},
    {'checks': {'inference_device': 'cuda', 'gpu_required': True, 'reserved_gpu_ready': False, 'offline_runtime': True, 'degraded_diarization_allowed': True}},
])
def test_partial_flags_cannot_override_service_not_ready(monkeypatch, change):
    client = TranscriptionV2Client('http://127.0.0.1:8510', Path('/tmp/synthetic-token'))
    payload = {'status': 'degraded_ready', 'checks': {
        'reserved_gpu_ready': True, 'offline_runtime': True, 'degraded_diarization_allowed': True,
    }}
    payload.update(change)
    monkeypatch.setattr(client, '_request', lambda *a, **kw: payload)
    assert not client.ready('synthetic-owner')


def test_ready_service_preserves_existing_protocol(monkeypatch):
    client = TranscriptionV2Client('http://127.0.0.1:8510', Path('/tmp/synthetic-token'))
    monkeypatch.setattr(client, '_request', lambda *a, **kw: {'status': 'ready'})
    assert client.ready('synthetic-owner')
