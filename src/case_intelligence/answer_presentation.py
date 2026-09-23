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


def answer_content(value: str, introduction: str) -> str:
    """Update only a saved generated introduction at the beginning of its text."""
    corrected = answer_introduction(introduction)
    if corrected != introduction and (
        value == introduction or value.startswith(introduction + "\n")
    ):
        return corrected + value[len(introduction):]
    return value


def research_content(value: object, answer: object) -> str:
    """Present a saved summary/finding without altering its validated record."""
    text = value if isinstance(value, str) else ""
    introduction = answer.get("introduction", "") if isinstance(answer, Mapping) else ""
    return answer_content(text, introduction) if isinstance(introduction, str) else text
