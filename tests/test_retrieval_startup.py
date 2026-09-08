"""The Mac app can start only after its serving retrieval process is ready."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from case_intelligence import retrieval_worker as worker


@pytest.fixture
def synthetic_models(monkeypatch):
    class Embedding:
        def encode(self, texts, **kwargs):
            return [[1.0] + [0.0] * 767 for _ in texts]

    class Reranker:
        def predict(self, pairs):
            return [0.5 for _ in pairs]

    models = SimpleNamespace(embedding=Embedding(), reranker=Reranker())
    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(
        SentenceTransformer=lambda *args, **kwargs: models.embedding,
        CrossEncoder=lambda *args, **kwargs: models.reranker,
    ))
    monkeypatch.setattr(worker, "_embedding", None)
    monkeypatch.setattr(worker, "_reranker", None)
    return models


def test_warmup_makes_both_models_ready_in_the_process_that_serves(
    monkeypatch, synthetic_models, capsys
):
    monkeypatch.setattr(sys, "argv", ["retrieval", "--warm-models"])
    observations = []

    def serve(app, **kwargs):
        assert app is worker.app
        assert worker._embedding is synthetic_models.embedding
        assert worker._reranker is synthetic_models.reranker
        observations.append(worker.health())

    monkeypatch.setattr(worker.uvicorn, "run", serve)
    worker.main()
    assert observations == [{"status": "ok", "embedding_loaded": True, "reranker_loaded": True}]
    assert '"status": "ready"' in capsys.readouterr().out


@pytest.mark.parametrize("failure", ["missing_model", "invalid_output"])
def test_failed_warmup_never_opens_the_server(monkeypatch, synthetic_models, failure):
    if failure == "missing_model":
        def failed_encode(*args, **kwargs):
            raise RuntimeError("synthetic model unavailable")
        monkeypatch.setattr(synthetic_models.embedding, "encode", failed_encode)
    else:
        monkeypatch.setattr(synthetic_models.embedding, "encode", lambda *args, **kwargs: [[float("nan")]])
    monkeypatch.setattr(sys, "argv", ["retrieval", "--warm-models"])
    calls = []
    monkeypatch.setattr(worker.uvicorn, "run", lambda *args, **kwargs: calls.append(True))
    with pytest.raises(SystemExit) as exc:
        worker.main()
    assert exc.value.code == 1
    assert not calls


def test_default_startup_retains_existing_lazy_loading(monkeypatch, synthetic_models):
    monkeypatch.setattr(sys, "argv", ["retrieval"])
    observations = []
    monkeypatch.setattr(worker.uvicorn, "run", lambda *args, **kwargs: observations.append(worker.health()))
    worker.main()
    assert observations == [{"status": "ok", "embedding_loaded": False, "reranker_loaded": False}]


def test_warmup_does_not_bypass_the_bind_boundary(monkeypatch, synthetic_models):
    monkeypatch.delenv("RECORDBENCH_ALLOW_CONTAINER_BIND", raising=False)
    monkeypatch.setattr(sys, "argv", ["retrieval", "--host", "0.0.0.0", "--warm-models"])
    with pytest.raises(SystemExit) as exc:
        worker.main()
    assert exc.value.code == 2
    assert worker._embedding is None
    assert worker._reranker is None
