from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from case_intelligence.contracts import (
    IngestionJob,
    IngestionState,
    Matter,
    MatterState,
    RetrievalResult,
    RetrievalRun,
    SourceReference,
    SourceVersion,
)
from tests.support import ALPHA, BRAVO, NOW, matter, source


def test_models_are_frozen_and_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Matter(matter_id=ALPHA, display_name="Alpha", state=MatterState.ACTIVE, surprise=True)
    item = matter()
    with pytest.raises(ValidationError):
        item.state = MatterState.CLOSED


def test_blank_matter_and_naive_time_fail() -> None:
    with pytest.raises(ValidationError):
        Matter(matter_id=" ", display_name="Alpha", state=MatterState.ACTIVE)
    data = source().model_dump()
    data["discovered_at"] = datetime(2026, 8, 25, 12, 0)
    with pytest.raises(ValidationError):
        SourceVersion.model_validate(data)
    data["discovered_at"] = NOW.astimezone(timezone(timedelta(hours=1)))
    with pytest.raises(ValidationError):
        SourceVersion.model_validate(data)


@pytest.mark.parametrize("bad", ["", "/absolute.txt", "C:/drive.txt", r"\\host\share\x", "a//b", "a/./b", "a/../b", "CON", "a\x00b"])
def test_relative_path_rejects_malformed_values(bad: str) -> None:
    data = source().model_dump()
    data["relative_path"] = bad
    with pytest.raises(ValidationError):
        SourceVersion.model_validate(data)


def test_unicode_spaced_nested_relative_path_is_valid() -> None:
    data = source().model_dump()
    data["relative_path"] = "photos/été 2026/scene one.svg"
    assert SourceVersion.model_validate(data).relative_path == data["relative_path"]


def test_digest_is_lowercase_sha256() -> None:
    data = source().model_dump()
    for bad in ("a" * 63, "A" * 64, "z" * 64):
        data["sha256"] = bad
        with pytest.raises(ValidationError):
            SourceVersion.model_validate(data)


def test_source_datetime_ordering_fails_closed() -> None:
    data = source().model_dump()
    data["last_verified_at"] = NOW - timedelta(seconds=1)
    with pytest.raises(ValidationError):
        SourceVersion.model_validate(data)


def test_ingestion_and_retrieval_require_consistent_matter() -> None:
    job = IngestionJob(job_id="job-alpha", matter_id=ALPHA, source_version_id="version-alpha", state=IngestionState.QUEUED, created_at=NOW)
    assert job.matter_id == ALPHA
    ref = SourceReference(reference_id="ref-alpha", matter_id=ALPHA, source_version_id="version-alpha", locator={"page": 1})
    run = RetrievalRun(run_id="run-alpha", matter_id=ALPHA, query="red bicycle", created_at=NOW)
    result = RetrievalResult(run_id=run.run_id, matter_id=ALPHA, reference=ref, source_version_id="version-alpha", rank=1, score=0.9)
    assert result.matter_id == ALPHA
    with pytest.raises(ValidationError):
        RetrievalResult(run_id=run.run_id, matter_id=BRAVO, reference=ref, source_version_id="version-alpha", rank=1, score=0.9)
