"""Confidence language for generated work, including older saved answers."""

from collections.abc import Mapping

GENERATED_ANSWER_INTRODUCTION = "Generated answer for source review:"
GENERATED_TRANSCRIPT_INTRODUCTION = "Generated orientation from a machine transcript:"
GENERATED_REVIEW_NOTICE = (
    "Generated text can misstate a source or combine unrelated details. "
    "Citations and automated checks do not establish that a claim is correct. "
    "Check each claim against the original sources before relying on it."
)


def answer_introduction(value: str) -> str:
    """Replace known historical boilerplate for display without changing storage."""
    if value in {
        "The searchable sources support this answer:",
        "The searchable sources support these findings:",
    }:
        return GENERATED_ANSWER_INTRODUCTION
    if value in {
        "The machine transcript supports this orientation:",
        "The machine transcript supports these orientation points:",
    }:
        return GENERATED_TRANSCRIPT_INTRODUCTION
    return value


def answer_content(value: str, introduction: str, payload: object = None) -> str:
    """Project a known introduction and a provenance-bound final omission suffix."""
    corrected = answer_introduction(introduction)
    if corrected != introduction and (
        value == introduction or value.startswith(introduction + "\n")
    ):
        value = corrected + value[len(introduction):]
    if isinstance(payload, Mapping) and isinstance(payload.get("limitation"), Mapping):
        original = payload["limitation"].get("text")
        projected = answer_limitation(payload)
        suffix = "\nLimitation: " + original if isinstance(original, str) else ""
        if suffix and projected != original and value.endswith(suffix):
            value = value[:-len(suffix)] + "\nLimitation: " + projected
    return value


def research_content(value: object, answer: object) -> str:
    """Present a saved summary/finding without altering its validated record."""
    text = value if isinstance(value, str) else ""
    introduction = answer.get("introduction", "") if isinstance(answer, Mapping) else ""
    if not isinstance(answer, Mapping) or answer.get("answerable") is False:
        return rejected_answer_notice(text)
    return answer_content(text, introduction, answer) if isinstance(introduction, str) else text


def modality_coverage_notice(value: object) -> str:
    """Present exact historical generated notices without altering saved receipts.

    Only complete known boilerplate in the modality-notice field is replaced;
    quoted wording, extensions, and custom notices retain their original text.
    """
    if not isinstance(value, str):
        return ""
    for names in ("written", "spoken", "written and spoken"):
        if value == f"This answer includes source-verified {names} support.":
            return (f"This answer cites {names} passages. "
                "Check each claim against the original sources.")
        if value == (
            f"This result is partial: {names} evidence reached the answer packet, but "
            f"no source-verified {names} claim was retained. Review the matching source "
            "or refine the question before treating the comparison as complete."
        ):
            return (
                f"This result is partial: {names} evidence reached the answer packet, but "
                "no generated claim citing those passages was retained. Review the matching source "
                "or refine the question before treating the comparison as complete."
            )
        if value == (
            f"This result is partial: no matching {names} evidence was retrieved in "
            "the selected passages. Review the supported result and search that source "
            "type directly before treating the comparison as complete."
        ):
            return (
                f"This result is partial: no matching {names} evidence was retrieved in "
                "the selected passages. Review the generated result and search that source "
                "type directly before treating the comparison as complete."
            )
    return value


REJECTED_ANSWER_NOTICE = (
    "I found potentially relevant source passages, but no generated answer "
    "was retained after automated checks. Review the matches below or ask a narrower question."
)


def rejected_answer_notice(value: object) -> str:
    """Project complete known abstention boilerplate, never a quoted substring."""
    if not isinstance(value, str):
        return ""
    if value == (
        "I found potentially relevant source passages, but the generated "
        "answer did not pass source verification. Review the matches below "
        "or ask a narrower question."
    ):
        return REJECTED_ANSWER_NOTICE
    if value == (
        "Potential passages were found, but this research step did not "
        "produce a source-verified finding."
    ):
        return "Potential passages were found, but no generated finding was retained for this research step after automated checks."
    return value


def rejected_answer_content(value: str, payload: Mapping) -> str:
    """Do not reinterpret custom payload text after storage trims message content."""
    missing = payload.get("missing_information")
    if isinstance(missing, str) and missing and missing != value:
        return value
    return rejected_answer_notice(value)


def review_rejection_notice(value: object) -> str:
    """Project only generated source-screening rejection fields, not reviewer notes."""
    if not isinstance(value, str):
        return ""
    return {
        "Potentially relevant passages were found, but an inclusion decision did not pass source verification.":
            "Potentially relevant passages were found, but no inclusion decision was retained after automated checks.",
        "Source verification did not resolve an inclusion decision.":
            "Automated checks did not retain an inclusion decision. Review the source directly.",
    }.get(value, value)


def answer_limitation(payload: object) -> str:
    """Project a recognized omission suffix, retaining the source qualification.

    Explicit provenance fields bind modern notices to the original qualification.
    Older records require the producer's positive omitted-claim count and exact
    suffix shape. Nothing is inferred from wording in a source claim alone.
    """
    from .generation import LEGACY_VERIFICATION_OMISSION_NOTICE, VERIFICATION_OMISSION_NOTICE

    if not isinstance(payload, Mapping):
        return ""
    limitation = payload.get("limitation")
    text = limitation.get("text", "") if isinstance(limitation, Mapping) else ""
    if not isinstance(text, str):
        return ""
    old = LEGACY_VERIFICATION_OMISSION_NOTICE
    if payload.get("verification_notice") == old and "source_limitation" in payload:
        source = payload["source_limitation"]
        prefix = source.get("text") if isinstance(source, Mapping) else "" if source is None else None
        if isinstance(prefix, str) and text == (prefix + " " if prefix else "") + old:
            return (prefix + " " if prefix else "") + VERIFICATION_OMISSION_NOTICE
    omitted = payload.get("omitted_claims")
    if ("source_limitation" not in payload and not payload.get("verification_notice")
        and type(omitted) is int and omitted > 0):
        if text == old:
            return VERIFICATION_OMISSION_NOTICE
        if text.endswith(" " + old):
            prefix = text[:-len(old) - 1]
            if prefix and prefix == prefix.strip():
                return prefix + " " + VERIFICATION_OMISSION_NOTICE
    return text


def answer_failure_notice(value: str) -> str:
    """Present the one historical generated-answer failure message in job status."""
    if value == (
        "I could not verify enough source support for a reliable answer. "
        "Try a narrower question or search the matter."
    ):
        return "No generated answer was retained after automated checks. Try a narrower question or search the matter."
    return value
