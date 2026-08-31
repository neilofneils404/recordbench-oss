from __future__ import annotations

from case_intelligence.video_frame_ocr import (
    DecodedVideoFrame,
    FrameOcrPolicy,
    FrameOcrStepError,
    plan_sample_times,
    run_sampled_frame_ocr,
)


def test_long_video_sample_plan_is_bounded_and_spans_the_timeline():
    policy = FrameOcrPolicy(sample_interval_ms=5_000, max_frames=5)
    points = plan_sample_times(60 * 60 * 1_000, policy=policy)
    assert points == (0, 900_000, 1_800_000, 2_699_999, 3_599_999)
    assert len(points) == policy.max_frames


def test_frame_text_keeps_decoder_timestamp_frame_and_matter_provenance():
    timeouts: list[float] = []

    def decode(requested_time_ms: int, *, timeout_seconds: float):
        timeouts.append(timeout_seconds)
        return DecodedVideoFrame(
            requested_time_ms=requested_time_ms,
            presentation_time_ms=requested_time_ms + 37,
            frame_number=412,
            width=640,
            height=360,
            image_bytes=b"synthetic-pixel-buffer",
        )

    def recognize(image_bytes: bytes, *, timeout_seconds: float):
        assert image_bytes == b"synthetic-pixel-buffer"
        timeouts.append(timeout_seconds)
        return "  GENERATED LABEL 17\r\n 09:14  "

    policy = FrameOcrPolicy(sample_interval_ms=10_000, max_frames=1)
    result = run_sampled_frame_ocr(
        matter_id="matter-synthetic-alpha",
        document_id="document-synthetic-video",
        source_version_id="version-synthetic-one",
        duration_ms=20_000,
        decode_frame=decode,
        recognize_frame=recognize,
        policy=policy,
    )

    assert result.state == "ready"
    assert result.searchable is False
    assert timeouts == [policy.step_timeout_seconds, policy.step_timeout_seconds]
    assert len(result.evidence) == 1
    frame = result.evidence[0]
    assert frame.matter_id == "matter-synthetic-alpha"
    assert frame.source_version_id == "version-synthetic-one"
    assert frame.presentation_time_ms == 37
    assert frame.frame_number == 412
    assert frame.location == "video frame 00:00:00.037 (frame 412)"
    assert frame.text == "GENERATED LABEL 17\n 09:14"
    assert frame.evidence_kind == "video_frame_ocr"
    assert any("not identification" in item for item in result.limitations)


def test_per_frame_failures_are_content_free_bounded_and_do_not_abort_other_frames():
    policy = FrameOcrPolicy(
        sample_interval_ms=10_000,
        max_frames=4,
        max_frame_bytes=32,
        max_frame_pixels=100,
        max_text_chars=12,
    )

    def decode(requested_time_ms: int, *, timeout_seconds: float):
        del timeout_seconds
        if requested_time_ms == 0:
            raise FrameOcrStepError("decode_timeout")
        if requested_time_ms == 10_000:
            return DecodedVideoFrame(
                requested_time_ms, requested_time_ms, 2, 11, 10, b"unsafe"
            )
        return DecodedVideoFrame(
            requested_time_ms,
            requested_time_ms,
            requested_time_ms // 1_000,
            4,
            4,
            b"pixels",
        )

    def recognize(image_bytes: bytes, *, timeout_seconds: float):
        del image_bytes, timeout_seconds
        return "text too long for this deliberately tiny cap"

    result = run_sampled_frame_ocr(
        matter_id="matter-synthetic-alpha",
        document_id="document-synthetic-video",
        source_version_id="version-synthetic-one",
        duration_ms=30_001,
        decode_frame=decode,
        recognize_frame=recognize,
        policy=policy,
    )

    assert result.state == "unavailable"
    assert result.planned_frame_count == 4
    assert result.decoded_frame_count == 2
    assert result.evidence == ()
    assert [item.category for item in result.failures] == [
        "decode_timeout",
        "unsafe_frame",
        "ocr_output_too_large",
        "ocr_output_too_large",
    ]
    assert all(not hasattr(item, "message") for item in result.failures)


def test_no_recognized_text_is_truthfully_not_searchable_and_not_a_failure():
    result = run_sampled_frame_ocr(
        matter_id="matter-synthetic-alpha",
        document_id="document-synthetic-video",
        source_version_id="version-synthetic-one",
        duration_ms=1_000,
        decode_frame=lambda requested_time_ms, timeout_seconds: DecodedVideoFrame(
            requested_time_ms, 0, 0, 1, 1, b"p"
        ),
        recognize_frame=lambda image_bytes, timeout_seconds: "",
        policy=FrameOcrPolicy(max_frames=1),
    )
    assert result.state == "no_text"
    assert result.searchable is False
    assert result.evidence == ()
    assert result.failures == ()
