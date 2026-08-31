import pytest

from case_intelligence.contracts import ContentOperation, MatterState, RetrievalResult, RetrievalRun, SourceReference
from case_intelligence.isolation import AuthorizationError, Catalog, MatterAccess, MatterStateRegistry, guard_content_operation, validate_retrieval_results
from tests.support import ACTOR_ALPHA, ALPHA, BRAVO, NOW, matter, source


def test_unknown_or_unauthorized_matter_fails_before_lookup() -> None:
    registry = MatterStateRegistry([matter(ALPHA), matter(BRAVO)])
    catalog = Catalog(registry, [source(ALPHA), source(BRAVO)])
    access = MatterAccess({ACTOR_ALPHA: {ALPHA}})
    with pytest.raises(AuthorizationError):
        catalog.source_for_actor(access, ACTOR_ALPHA, BRAVO, "version-matter-bravo")
    assert catalog.lookup_count == 0


def test_foreign_source_does_not_fallback_and_keys_are_scoped() -> None:
    registry = MatterStateRegistry([matter(ALPHA), matter(BRAVO)])
    catalog = Catalog(registry, [source(ALPHA), source(BRAVO)])
    access = MatterAccess({ACTOR_ALPHA: {ALPHA}})
    with pytest.raises(KeyError):
        catalog.source_for_actor(access, ACTOR_ALPHA, ALPHA, "version-matter-bravo")
    assert catalog.cache_key(ALPHA, "query") != catalog.cache_key(BRAVO, "query")


def test_mixed_retrieval_set_is_rejected_whole() -> None:
    run = RetrievalRun(run_id="run", matter_id=ALPHA, query="shared red bicycle", created_at=NOW)
    alpha_ref = SourceReference(reference_id="a", matter_id=ALPHA, source_version_id="version-matter-alpha", locator={"page": 1})
    bravo_ref = SourceReference(reference_id="b", matter_id=BRAVO, source_version_id="version-matter-bravo", locator={"page": 1})
    results = [
        RetrievalResult(run_id="run", matter_id=ALPHA, source_version_id="version-matter-alpha", reference=alpha_ref, rank=1, score=1.0),
        RetrievalResult(run_id="run", matter_id=BRAVO, source_version_id="version-matter-bravo", reference=bravo_ref, rank=2, score=0.5),
    ]
    with pytest.raises(AuthorizationError):
        validate_retrieval_results(run, results)


@pytest.mark.parametrize("state", [MatterState.CLOSING, MatterState.CLOSED])
@pytest.mark.parametrize("operation", list(ContentOperation))
def test_non_active_matter_denies_all_content_operations(state: MatterState, operation: ContentOperation) -> None:
    registry = MatterStateRegistry([matter(state=state)])
    with pytest.raises(AuthorizationError):
        guard_content_operation(registry, ALPHA, operation)
