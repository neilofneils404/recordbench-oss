"""Reject unencodable capture metadata before any runtime observation or request."""
import socket

import pytest

from case_intelligence import claim_evaluation as evaluation
from case_intelligence import generation


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("Metadata encoding tests must not contact a model or network.")
    monkeypatch.setattr(generation.urllib.request, "urlopen", fail)
    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(socket.socket, "connect", fail)


def capture_metadata(field, value):
    pinned = evaluation.model_records("portable", generator_exercised=False)["components"][0]
    runtime = {"runtime_name": "synthetic", "runtime_version": "test-only",
        "accelerator": "none", "accelerator_memory_gib": 0, "driver": "none",
        "model_artifact_sha256": "a" * 64, "offline_readiness": "not_exercised",
        "offline_evidence_sha256": None, "upstream_model_id": pinned["model_id"],
        "upstream_revision": pinned["revision"], "license": pinned["license"]}
    events = []

    class SyntheticClient(generation.OpenAICompatibleGenerator):
        def generate(self, *, question, evidence):
            events.append("generate")
            return {"answerable": False, "claims": [], "limitation": None,
                    "missing_information": ""}

    model = value if field == "model" else "synthetic-metadata-only"
    client = SyntheticClient("http://127.0.0.1:11435", model)
    if field != "model":
        runtime[field] = value

    def identity():
        events.append("identity")
        return {"method": "api_model_id_snapshots", "model": client.model,
                "artifact_sha256": None}

    return runtime, client, identity, events


@pytest.mark.parametrize("field", ["runtime_name", "runtime_version", "accelerator", "driver", "model"])
@pytest.mark.parametrize("value", ["synthetic\ud800", "synthetic\udfff"])
def test_unencodable_metadata_is_rejected_before_identity_or_model_calls(field, value):
    runtime, client, identity, events = capture_metadata(field, value)
    with pytest.raises(ValueError):
        evaluation.capture(client, profile="portable", runtime=runtime,
                           repetitions=1, identity_check=identity)
    assert events == []


@pytest.mark.parametrize("field", ["runtime_name", "runtime_version", "accelerator", "driver", "model"])
def test_valid_unicode_metadata_retains_capture_and_grading(field):
    runtime, client, identity, events = capture_metadata(field, "synthetic-café-\U0001f50e")
    receipt = evaluation.capture(client, profile="portable", runtime=runtime,
                                 repetitions=1, identity_check=identity)
    assert events.count("generate") == 11
    assert events.count("identity") == 23
    assert receipt["generation"]["generated"] == receipt["generation"]["abstained"] == 11
    assert len(evaluation.grade_template(receipt)["samples"]) == 11
    if field == "model":
        assert receipt["configuration"]["model"] == client.model
    else:
        assert receipt["runtime"][field] == runtime[field]
