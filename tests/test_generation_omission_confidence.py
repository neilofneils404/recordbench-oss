"""Partial generated answers disclose text checks without changing acceptance."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib

import pytest

from case_intelligence import generation


CURRENT_NOTICE = (
    "Some generated statements were omitted because they did not pass citation and text checks."
)
LEGACY_NOTICE = (
    "Some generated statements were omitted because their source support could not be verified."
)


@pytest.mark.parametrize("sourced_limitation", [False, True])
def test_partial_answer_notice_preserves_verifier_results_and_source_basis(monkeypatch, sourced_limitation):
    evidence = (
        generation.EvidenceItem("S1", "Synthetic pressure log.txt", "Line 1",
            "The synthetic pressure log recorded 18 psi at 10:07.", document_id="synthetic-log"),
        generation.EvidenceItem("S2", "Synthetic pressure log.txt", "Line 2",
            "The synthetic pressure log did not identify the operator.", document_id="synthetic-log"),
    )
    source_snapshot = tuple((item, hashlib.sha256(item.excerpt.encode()).hexdigest()) for item in evidence)
    payload = {
        "answerable": True,
        "claims": [
            {"text": evidence[0].excerpt, "evidence_ids": ["S1"]},
            {"text": evidence[0].excerpt, "evidence_ids": ["S1"]},
            {"text": "The synthetic pressure log recorded 99 psi at 10:07.", "evidence_ids": ["S1"]},
            {"text": evidence[0].excerpt, "evidence_ids": ["S9"]},
        ],
        "limitation": {"text": evidence[1].excerpt, "evidence_ids": ["S2"]} if sourced_limitation else None,
        "missing_information": "",
    }
    original_payload = deepcopy(payload)

    class PartialClient:
        available = True

        def __init__(self):
            self.calls = []

        def generate(self, **kwargs):
            self.calls.append(kwargs)
            return deepcopy(payload)

    client = PartialClient()
    service = generation.GroundedGenerationService(client)
    stages = []
    answer = service.answer("What did the synthetic pressure log record?", evidence,
                            stage_callback=stages.append)

    assert answer.verification_notice == CURRENT_NOTICE
    assert generation.LEGACY_VERIFICATION_OMISSION_NOTICE == LEGACY_NOTICE
    assert answer.answerable and answer.model_called
    assert answer.claims == (generation.VerifiedClaim(evidence[0].excerpt, ("S1",)),)
    assert answer.omitted_claims == 2
    assert answer.duplicate_claims == 1
    assert answer.used_evidence_ids == (("S1", "S2") if sourced_limitation else ("S1",))
    expected_limitation = generation.VerifiedClaim(evidence[1].excerpt, ("S2",)) if sourced_limitation else None
    assert answer.source_limitation == expected_limitation
    expected_text = (evidence[1].excerpt + " " if sourced_limitation else "") + CURRENT_NOTICE
    assert answer.limitation == generation.VerifiedClaim(expected_text, ("S2",) if sourced_limitation else ())
    assert answer.text.count(CURRENT_NOTICE) == 1
    assert LEGACY_NOTICE not in answer.text
    assert service.requests_started == service.requests_completed == len(client.calls) == 1
    assert "verifying" in stages and "repairing" not in stages
    assert tuple(client.calls[0]["evidence"]) == evidence
    assert payload == original_payload
    assert tuple((item, hashlib.sha256(item.excerpt.encode()).hexdigest()) for item in evidence) == source_snapshot

    # The legacy notice changes only service-authored display fields. Run the
    # same real verifier under that historical constant to prove all accepted
    # claims, counts, source IDs and sourced qualifications stay identical.
    monkeypatch.setattr(generation, "VERIFICATION_OMISSION_NOTICE", LEGACY_NOTICE)
    legacy = generation.GroundedGenerationService(PartialClient()).answer(
        "What did the synthetic pressure log record?", evidence)
    legacy_limitation = replace(answer.limitation,
        text=answer.limitation.text.removesuffix(CURRENT_NOTICE) + LEGACY_NOTICE)
    assert replace(answer, elapsed_ms=0, verification_notice=LEGACY_NOTICE,
                   limitation=legacy_limitation) == replace(legacy, elapsed_ms=0)
