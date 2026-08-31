import json
import wave

from case_intelligence.isolation import Catalog, MatterAccess
from tests.fixture_loader import ROOT, load_synthetic_fixture
from tests.support import ACTOR_ALPHA, ALPHA, BRAVO


def test_fixture_is_exactly_two_synthetic_multimodal_matters() -> None:
    fixture = load_synthetic_fixture()
    assert fixture["provenance"] == "synthetic"
    assert fixture["confidential_data"] is False
    assert fixture["requires_model"] is False
    assert fixture["requires_network"] is False
    assert {m["matter_id"] for m in fixture["matters"]} == {ALPHA, BRAVO}
    assert all({s["kind"] for s in m["sources"]} == {"text", "image", "audio"} for m in fixture["matters"])


def test_fixture_files_match_declared_size_and_digest() -> None:
    fixture = load_synthetic_fixture(verify_files=True)
    assert fixture["verified_file_count"] == 12


def test_fixture_ids_are_globally_unique_and_each_modality_has_its_matter_canary() -> None:
    fixture = load_synthetic_fixture(verify_files=True)
    ids = []
    for matter in fixture["matters"]:
        canary = matter["canary"]
        for source in matter["sources"]:
            ids.extend((source["source_id"], source["source_version_id"], source["representation"]["representation_id"], source["representation"]["segment_id"]))
            assert canary in source["searchable_text"]
            assert "shared red bicycle" in source["searchable_text"]
    assert len(ids) == len(set(ids))


def test_audio_transcript_timestamps_fit_deterministic_pcm_duration() -> None:
    fixture = load_synthetic_fixture()
    for matter in fixture["matters"]:
        audio = next(source for source in matter["sources"] if source["kind"] == "audio")
        with wave.open(str(ROOT / audio["path"]), "rb") as stream:
            assert stream.getparams()[:3] == (1, 2, 8000)
            duration_ms = stream.getnframes() * 1000 // stream.getframerate()
        transcript = json.loads((ROOT / audio["representation"]["path"]).read_text())
        assert all(0 <= segment["start_ms"] < segment["end_ms"] <= duration_ms for segment in transcript["segments"])


def test_shared_catalog_retrieval_is_matter_scoped() -> None:
    fixture = load_synthetic_fixture()
    catalog = Catalog.from_fixture(fixture)
    access = MatterAccess({ACTOR_ALPHA: {ALPHA}})
    unique = catalog.search(access, ACTOR_ALPHA, ALPHA, "CITRINE-FALCON-731")
    shared = catalog.search(access, ACTOR_ALPHA, ALPHA, "shared red bicycle")
    assert unique and shared
    assert {hit.matter_id for hit in unique + shared} == {ALPHA}
    with __import__("pytest").raises(Exception):
        catalog.search(access, ACTOR_ALPHA, BRAVO, "VIOLET-HARBOR-842")
