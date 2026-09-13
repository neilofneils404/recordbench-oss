from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from case_intelligence import workbench
from case_intelligence.generation import UnavailableGenerator
from case_intelligence.malware_scan import MalwareScannerStatus
from case_intelligence.managed_storage import StoragePolicy


_worker_probe = workbench.CaseIntelligenceWorkbench._retrieval_worker_ready


class SyntheticScanner:
    state = "ready"

    def status(self, *, force=False):
        return MalwareScannerStatus(self.state, "synthetic")


@pytest.fixture(autouse=True)
def isolated_health_environment(monkeypatch):
    for name in (
        "MODEL_PROFILE", "GENERATOR_BACKEND", "GENERATOR_URL", "GENERATOR_MODEL",
        "RETRIEVAL_WORKER_URL", "TRANSCRIPTION_URL", "TRANSCRIPTION_TOKEN_FILE",
        "POSTGRES_DSN", "POSTGRES_DSN_FILE", "RELEASE_ID",
    ):
        monkeypatch.delenv("CASE_INTELLIGENCE_" + name, raising=False)
    monkeypatch.setenv("CASE_INTELLIGENCE_MODEL_PROFILE", "none")
    monkeypatch.setattr(workbench.CaseIntelligenceWorkbench, "_connect_postgres", staticmethod(lambda dsn: None))
    monkeypatch.setattr(workbench.CaseIntelligenceWorkbench, "_retrieval_worker_ready", staticmethod(lambda url: False))


def application(tmp_path, **options):
    return workbench.create_workbench_app(
        tmp_path / "runtime", auth_mode="test", answer_workers=1,
        storage_policy=StoragePolicy(reserve_bytes=0),
        malware_scanner=options.pop("malware_scanner", SyntheticScanner()), **options,
    )


def test_cpu_profile_with_compose_worker_address_reports_selected_set_ready(tmp_path, monkeypatch):
    # Compose retains this companion address even when its optional profile is off.
    monkeypatch.setenv("CASE_INTELLIGENCE_RETRIEVAL_WORKER_URL", "http://retrieval:8787")
    app = application(tmp_path)
    with TestClient(app) as client:
        payload = client.get("/health").json()
    assert payload["status"] == "ok"
    assert payload["selected_capabilities"] == {"answering": False, "meaning_search": False, "transcription": False}
    assert payload["capabilities"]["search"] == "word search only"
    assert all(payload["capabilities"][key] == "not selected" for key in payload["selected_capabilities"])


@pytest.mark.parametrize("value,expected", [
    ("0.1.0-alpha.2-aaaaaaaaaaaa", "0.1.0-alpha.2-aaaaaaaaaaaa"),
    ("1.2.3-0123456789ab", "1.2.3-0123456789ab"),
    ("", "development"),
    ("synthetic-private-release", "development"),
    ("0.1.0-alpha.2-aaaaaaaaaaaa\n", "development"),
])
def test_health_release_readback_never_echoes_arbitrary_environment(tmp_path, monkeypatch, value, expected):
    monkeypatch.setenv("CASE_INTELLIGENCE_RELEASE_ID", value)
    with TestClient(application(tmp_path)) as client:
        payload = client.get("/health").json()
    assert payload["release_id"] == expected
    assert "synthetic-private" not in str(payload)


@pytest.mark.parametrize("profile,selected", [
    ("review", {"answering", "meaning_search"}),
    ("transcription", {"transcription"}),
    ("all", {"answering", "meaning_search", "transcription"}),
])
def test_selected_profile_with_missing_clients_does_not_become_unselected(tmp_path, monkeypatch, profile, selected):
    monkeypatch.setenv("CASE_INTELLIGENCE_MODEL_PROFILE", profile)
    with TestClient(application(tmp_path)) as client:
        payload = client.get("/health").json()
    assert payload["status"] == "degraded"
    assert {key for key, enabled in payload["selected_capabilities"].items() if enabled} == selected
    assert all(payload["capabilities"][key] == "temporarily unavailable" for key in selected)


def test_configured_generation_backend_remains_selected_when_client_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("CASE_INTELLIGENCE_GENERATOR_BACKEND", "openai")
    monkeypatch.setattr(workbench, "generator_from_environment", lambda: UnavailableGenerator())
    with TestClient(application(tmp_path)) as client:
        payload = client.get("/health").json()
    assert payload["status"] == "degraded"
    assert payload["selected_capabilities"]["answering"] is True
    assert payload["capabilities"]["answering"] == "temporarily unavailable"


def test_configured_transcription_with_missing_token_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("CASE_INTELLIGENCE_TRANSCRIPTION_URL", "http://transcription-api:8510")
    with TestClient(application(tmp_path)) as client:
        payload = client.get("/health").json()
    assert payload["status"] == "degraded"
    assert payload["selected_capabilities"]["transcription"] is True
    assert payload["capabilities"]["transcription"] == "temporarily unavailable"


def test_legacy_node_with_configured_worker_does_not_hide_unavailable_retrieval(tmp_path, monkeypatch):
    monkeypatch.delenv("CASE_INTELLIGENCE_MODEL_PROFILE")
    monkeypatch.setenv("CASE_INTELLIGENCE_RETRIEVAL_WORKER_URL", "http://retrieval:8787")
    with TestClient(application(tmp_path)) as client:
        payload = client.get("/health").json()
    assert payload["status"] == "degraded"
    assert payload["selected_capabilities"]["meaning_search"] is True
    assert payload["capabilities"]["meaning_search"] == "temporarily unavailable"
    assert payload["capabilities"]["search"] == "word search only"


@pytest.mark.parametrize("field", ["generator", "media_processor"])
def test_supplied_clients_count_as_selected_and_can_report_recovery(tmp_path, field):
    supplied = SimpleNamespace(available=False)
    app = application(tmp_path, **{field: supplied})
    capability = "answering" if field == "generator" else "transcription"
    with TestClient(app) as client:
        failed = client.get("/health").json()
        assert failed["status"] == "degraded"
        assert failed["selected_capabilities"][capability] is True
        assert failed["capabilities"][capability] == "temporarily unavailable"
        supplied.available = True
        healthy = client.get("/health").json()
        assert healthy["status"] == "ok"
        assert healthy["capabilities"][capability] in {"ready", "local WhisperX v2"}


def test_selected_retrieval_tracks_database_and_current_remote_worker_readiness(tmp_path, monkeypatch):
    app = application(tmp_path, learned_retrieval=True)
    bench = app.state.workbench
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "degraded"
        bench.learned_retrieval = True
        bench.postgres_connection = SimpleNamespace(close=lambda: None)
        bench.postgres_ready = True
        bench._remote_retrieval_url = "http://retrieval:8787"
        bench._remote_retrieval_readiness = SimpleNamespace(ready=lambda: True, close=lambda: None)
        healthy = client.get("/health").json()
        assert healthy["status"] == "ok"
        assert healthy["capabilities"]["search"] == "word + meaning"
        bench._remote_retrieval_readiness = SimpleNamespace(ready=lambda: False, close=lambda: None)
        failed = client.get("/health").json()
        assert failed["status"] == "degraded"
        assert failed["capabilities"]["meaning_search"] == "temporarily unavailable"
        assert failed["capabilities"]["search"] == "word search only"
        bench._remote_retrieval_readiness = SimpleNamespace(ready=lambda: True, close=lambda: None)
        bench.postgres_ready = False
        assert client.get("/health").json()["status"] == "degraded"


def test_required_scanner_failure_degrades_even_when_generator_is_ready(tmp_path):
    scanner = SyntheticScanner()
    app = application(tmp_path, generator=SimpleNamespace(available=True), malware_scanner=scanner)
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        scanner.state = "unavailable"
        failed = client.get("/health").json()
        assert failed["capabilities"]["answering"] == "ready"
        assert failed["capabilities"]["malware_scan"] == "administrator setup required"
        assert failed["status"] == "degraded"


def test_explicitly_disabled_scanning_keeps_existing_policy_semantics(tmp_path):
    scanner = SyntheticScanner()
    scanner.state = "unavailable"
    with TestClient(application(tmp_path, malware_scanner=scanner, malware_scan_mode="disabled")) as client:
        payload = client.get("/health").json()
    assert payload["capabilities"]["malware_scan"] == "not required"
    assert payload["status"] == "ok"


def test_storage_attention_degrades_the_selected_cpu_set(tmp_path, monkeypatch):
    app = application(tmp_path)
    bench = app.state.workbench
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        projection = bench.storage_capacity_projection(include_managed_usage=False)
        projection["ready"] = False
        monkeypatch.setattr(bench, "storage_capacity_projection", lambda **kwargs: projection)
        failed = client.get("/health").json()
        assert failed["status"] == "degraded"
        assert failed["storage"]["reserve_satisfied"] is False
        assert failed["capabilities"]["answering"] == "not selected"


def test_public_health_reads_snapshot_without_worker_requests(tmp_path, monkeypatch):
    app = application(tmp_path, learned_retrieval=True)
    bench = app.state.workbench
    with TestClient(app) as client:
        bench.learned_retrieval = True
        bench.postgres_connection = SimpleNamespace(close=lambda: None)
        bench.postgres_ready = True
        bench._remote_retrieval_url = "http://retrieval:8787"
        bench._remote_retrieval_readiness = SimpleNamespace(ready=lambda: True, close=lambda: None)
        monkeypatch.setattr(bench, "_retrieval_worker_ready", lambda _: pytest.fail("health issued worker request"))
        for _ in range(20):
            assert client.get("/health").json()["status"] == "ok"


def test_worker_probe_bounds_response(monkeypatch):
    from contextlib import nullcontext
    from unittest.mock import Mock
    response = Mock()
    response.read.return_value = b"x" * 4097
    monkeypatch.setattr(workbench, "validate_service_endpoint", lambda *a, **kw: "http://retrieval:8787")
    monkeypatch.setattr(workbench.urllib.request, "urlopen", lambda *a, **kw: nullcontext(response))
    assert not _worker_probe("http://retrieval:8787")
    response.read.assert_called_once_with(4097)
