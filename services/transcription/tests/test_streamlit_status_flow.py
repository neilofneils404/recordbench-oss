from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ui.streamlit_app import (
    _apply_workspace_redirect,
    _batch_action_options,
    _compact_batch_rows,
    _group_queue_jobs,
    _record_successful_submission,
    _render_batch_download_center,
    _render_new_job,
    _render_selected_batch,
    _render_selected_batch_with_refresh,
    _render_selected_job,
    _render_selected_job_with_refresh,
    _render_submission_notice,
    _start_another_transcription,
    _upload_selection_error,
    _upload_selection_summary,
    _upload_widget_key,
    _use_compact_batch_layout,
)
from ui.api_client import ApiError


def _fragment_runs_immediately(*, run_every=None):
    del run_every

    def decorate(function):
        return function

    return decorate


def test_successful_submission_selects_job_and_schedules_queue_redirect() -> None:
    st = MagicMock()
    st.session_state = {}
    st.query_params = {}

    _record_successful_submission(
        st,
        ["job-123", "job-456"],
        rejected_count=1,
        form_generation=4,
    )

    assert st.session_state["selected_job_id"] == "job-123"
    assert st.session_state["_selected_job_auto_refresh"] is True
    assert st.session_state["submitted_job_ids"] == ["job-123", "job-456"]
    assert st.session_state["_workspace_redirect"] == "Jobs & downloads"
    assert st.session_state["_new_job_form_generation"] == 5
    assert st.query_params["job"] == "job-123"
    assert _upload_widget_key(4) != _upload_widget_key(5)


def test_multi_file_submission_opens_one_batch_workflow() -> None:
    st = MagicMock()
    st.session_state = {}
    st.query_params = {}

    _record_successful_submission(
        st,
        ["job-123", "job-456"],
        rejected_count=0,
        form_generation=2,
        batch_id="batch_abc123",
    )

    assert st.session_state["selected_batch_id"] == "batch_abc123"
    assert st.session_state["_selected_batch_auto_refresh"] is True
    assert "selected_job_id" not in st.session_state
    assert st.query_params == {"batch": "batch_abc123"}


def test_start_another_transcription_clears_delivery_route_and_upload_form() -> None:
    st = MagicMock()
    st.session_state = {
        "selected_job_id": "job-123",
        "selected_batch_id": "batch_abc123",
        "submitted_job_ids": ["job-123"],
        "_selected_job_auto_refresh": False,
        "_selected_batch_auto_refresh": False,
        "_new_job_form_generation": 7,
    }
    st.query_params = {"job": "job-123", "batch": "batch_abc123"}

    _start_another_transcription(st)

    assert "selected_job_id" not in st.session_state
    assert "selected_batch_id" not in st.session_state
    assert "submitted_job_ids" not in st.session_state
    assert st.query_params == {}
    assert st.session_state["_workspace_redirect"] == "Transcribe"
    assert st.session_state["_new_job_form_generation"] == 8


def test_queue_recovers_persisted_batches_as_one_item() -> None:
    batches, singles = _group_queue_jobs(
        [
            {"id": "job-1", "batch_id": "batch_a"},
            {"id": "job-2", "batch_id": "batch_a"},
            {"id": "job-3", "batch_id": "batch_b"},
            {"id": "job-4", "batch_id": None},
        ],
        exclude_batch_id="batch_b",
    )

    assert [item["id"] for item in batches["batch_a"]] == ["job-1", "job-2"]
    assert "batch_b" not in batches
    assert [item["id"] for item in singles] == ["job-4"]


def test_pending_queue_redirect_is_applied_before_sidebar_widget() -> None:
    st = MagicMock()
    st.session_state = {
        "_workspace_redirect": "Active delivery queue",
        "workspace_page": "New job",
    }

    destination = _apply_workspace_redirect(st)

    assert destination == "Jobs & downloads"
    assert st.session_state["workspace_page"] == "Jobs & downloads"
    assert "_workspace_redirect" not in st.session_state


def test_transcribe_redirect_is_explicit_so_stale_delivery_query_cannot_win() -> None:
    st = MagicMock()
    st.session_state = {
        "_workspace_redirect": "Transcribe",
        "workspace_page": "Jobs & downloads",
    }

    destination = _apply_workspace_redirect(st)

    assert destination == "Transcribe"
    assert st.session_state["workspace_page"] == "Transcribe"
    assert "_workspace_redirect" not in st.session_state


def test_submission_notice_explains_processing_status_is_below() -> None:
    st = MagicMock()
    st.session_state = {
        "_new_job_submission_notice": {
            "job_ids": ["job-123"],
            "rejected_count": 0,
        }
    }

    _render_submission_notice(st)

    message = st.success.call_args.args[0]
    assert "Processing has started" in message
    assert "status is shown below" in message
    assert "_new_job_submission_notice" not in st.session_state


def test_partial_submission_notice_includes_capacity_as_a_possible_reason() -> None:
    st = MagicMock()
    st.session_state = {
        "_new_job_submission_notice": {
            "job_ids": ["job-123", "job-456"],
            "rejected_count": 3,
            "batch_id": "batch_abc123",
        }
    }

    _render_submission_notice(st)

    message = st.warning.call_args.args[0]
    assert "current service capacity" in message
    assert "accepted recordings will continue" in message


def test_thirty_small_recordings_pass_the_five_gib_selection_preflight() -> None:
    gib = 1024**3
    files = [SimpleNamespace(size=1024) for _ in range(30)]

    assert (
        _upload_selection_error(
            files,
            max_file_bytes=5 * gib,
            max_request_bytes=5 * gib,
            max_files=100,
        )
        is None
    )


def test_thirty_file_selection_summary_reports_live_count_and_aggregate() -> None:
    files = [SimpleNamespace(size=1024) for _ in range(30)]

    assert (
        _upload_selection_summary(files)
        == "Selected: 30 recording(s) · 30.0 KiB total"
    )


def _new_job_test_streamlit(*, files, submitted: bool) -> MagicMock:
    st = MagicMock()
    st.session_state = {"_new_job_form_generation": 7}
    st.file_uploader.return_value = files
    st.form.return_value = nullcontext()
    st.columns.return_value = [MagicMock(), MagicMock()]
    st.selectbox.side_effect = [
        "Highest accuracy",
        "General recording",
        "Auto-detect (recommended)",
        "4 hours",
    ]
    st.checkbox.return_value = False
    st.toggle.return_value = False
    st.expander.return_value = nullcontext()
    st.number_input.return_value = 0
    st.text_area.return_value = ""
    st.form_submit_button.return_value = submitted
    st.spinner.return_value = nullcontext()
    return st


def test_invalid_live_selection_is_explained_and_disables_submit() -> None:
    gib = 1024**3
    files = [
        SimpleNamespace(
            name="too-large.wav",
            size=5 * gib + 1,
            type="audio/wav",
        )
    ]
    st = _new_job_test_streamlit(files=files, submitted=False)
    client = MagicMock()

    with (
        patch(
            "ui.streamlit_app._available_profiles",
            return_value={"Highest accuracy": "highest"},
        ),
        patch(
            "ui.streamlit_app._available_languages",
            return_value={"Auto-detect (recommended)": None},
        ),
    ):
        _render_new_job(st, client)

    st.file_uploader.assert_called_once()
    assert st.file_uploader.call_args.kwargs["key"] == "new-transcription-files-7"
    assert "5.0 GiB" in st.error.call_args.args[0]
    assert st.form_submit_button.call_args.kwargs["disabled"] is True
    client.submit_job.assert_not_called()


def test_failed_submission_preserves_selected_upload_generation() -> None:
    files = [
        SimpleNamespace(
            name="retry-me.wav",
            size=1024,
            type="audio/wav",
        )
    ]
    st = _new_job_test_streamlit(files=files, submitted=True)
    client = MagicMock()
    client.submit_job.side_effect = ApiError("Temporary submission failure")

    with (
        patch(
            "ui.streamlit_app._available_profiles",
            return_value={"Highest accuracy": "highest"},
        ),
        patch(
            "ui.streamlit_app._available_languages",
            return_value={"Auto-detect (recommended)": None},
        ),
    ):
        _render_new_job(st, client)

    assert st.session_state["_new_job_form_generation"] == 7
    assert st.file_uploader.call_args.kwargs["key"] == "new-transcription-files-7"
    assert st.form_submit_button.call_args.kwargs["disabled"] is False
    client.submit_job.assert_called_once()
    st.rerun.assert_not_called()


def test_selection_preflight_keeps_byte_limit_primary_and_count_limit_technical() -> None:
    gib = 1024**3
    over_bytes = [SimpleNamespace(size=3 * gib), SimpleNamespace(size=2 * gib + 1)]
    over_parts = [SimpleNamespace(size=1) for _ in range(101)]

    assert "5.0 GiB" in _upload_selection_error(
        over_bytes,
        max_file_bytes=5 * gib,
        max_request_bytes=5 * gib,
        max_files=100,
    )
    count_error = _upload_selection_error(
        over_parts,
        max_file_bytes=5 * gib,
        max_request_bytes=5 * gib,
        max_files=100,
    )
    assert "service safety limit" in count_error
    assert "100" not in count_error


def test_large_batches_use_compact_source_named_status_rows() -> None:
    jobs = [
        {
            "job_id": f"job-{index:02d}",
            "primary_filename": f"jail-call-{index:02d}.wav",
            "status": "queued",
            "stage": {"label": "Preparing", "progress": 0.03},
        }
        for index in range(30)
    ]
    jobs[0] = {
        "job_id": "job-00",
        "primary_filename": "active-call.wav",
        "status": "running",
        "stage": {"label": "Separating speakers", "progress": 0.72},
    }
    jobs[-1] = {
        "job_id": "job-29",
        "primary_filename": "finished-call.wav",
        "status": "review_ready",
        "stage": {"label": "Exporting", "progress": 1.0},
    }

    rows = _compact_batch_rows(jobs)

    assert _use_compact_batch_layout(jobs) is True
    assert _use_compact_batch_layout(jobs[:12]) is False
    assert len(rows) == 30
    assert rows[0] == {
        "Recording": "active-call.wav",
        "Status": "Separating speakers",
        "Progress": 72,
    }
    assert rows[-1] == {
        "Recording": "finished-call.wav",
        "Status": "Ready to download",
        "Progress": 100,
    }


def test_compact_batch_actions_are_scoped_to_actionable_recordings() -> None:
    jobs = [
        {"job_id": "job-ready", "primary_filename": "ready.wav", "status": "review_ready"},
        {"job_id": "job-active", "primary_filename": "active.wav", "status": "running"},
        {"job_id": "job-canceling", "primary_filename": "canceling.wav", "status": "canceling"},
        {"job_id": "job-failed", "primary_filename": "failed.wav", "status": "failed"},
    ]

    cancelable = _batch_action_options(
        jobs,
        {
            "created",
            "queued",
            "preparing",
            "running",
            "transcribing",
            "aligning",
            "diarizing",
        },
    )
    retryable = _batch_action_options(jobs, {"failed", "canceled"})

    assert cancelable == [("job-active", "2. active.wav")]
    assert retryable == [("job-failed", "4. failed.wav")]


def test_selected_batch_switches_to_compact_view_only_above_twelve_items() -> None:
    def batch_payload(total: int) -> dict:
        jobs = [
            {
                "job_id": f"job-{index}",
                "primary_filename": f"call-{index}.wav",
                "status": "queued",
                "stage": {"label": "Queued", "progress": 0.03},
            }
            for index in range(total)
        ]
        return {
            "status": "processing",
            "all_terminal": False,
            "download_ready": False,
            "counts": {
                "total": total,
                "active": total,
                "succeeded": 0,
                "failed": 0,
                "canceled": 0,
            },
            "jobs": jobs,
        }

    for total, compact_expected in ((12, False), (13, True)):
        st = MagicMock()
        st.session_state = {}
        st.columns.return_value = [MagicMock() for _ in range(4)]
        client = MagicMock()
        client.get_batch.return_value = batch_payload(total)
        with (
            patch("ui.streamlit_app._render_compact_batch_progress") as compact,
            patch("ui.streamlit_app._render_batch_recording_cards") as detailed,
        ):
            status = _render_selected_batch(st, client, "batch-abc")

        assert status == "processing"
        assert compact.called is compact_expected
        assert detailed.called is (not compact_expected)


def test_flat_batch_download_caption_and_single_package_request() -> None:
    st = MagicMock()
    st.spinner.return_value = nullcontext()
    client = MagicMock()
    client.create_batch_delivery_package.return_value = {
        "filename": "transcriptions.zip",
        "download_url": "/transcription-downloads/opaque",
        "included_jobs": 30,
        "omitted_jobs": 0,
    }

    with patch("ui.streamlit_app._render_download_link"):
        _render_batch_download_center(st, client, "batch-abc")

    client.create_batch_delivery_package.assert_called_once_with(
        "batch-abc",
        purge_after_download=True,
    )
    caption = st.caption.call_args.args[0]
    assert "top level of the ZIP" in caption
    assert "no folder per recording" in caption
    assert "safe numeric suffixes" in caption


def test_open_active_job_uses_five_second_fragment_refresh() -> None:
    st = MagicMock()
    st.session_state = {"_selected_job_auto_refresh": True}
    st.fragment.side_effect = _fragment_runs_immediately

    with patch(
        "ui.streamlit_app._render_selected_job",
        return_value="transcribing",
    ):
        _render_selected_job_with_refresh(st, MagicMock(), "job-123")

    st.fragment.assert_called_once_with(run_every="5s")
    assert st.session_state["_selected_job_auto_refresh"] is True
    st.rerun.assert_not_called()


def test_auto_refresh_stops_with_one_full_rerun_when_job_finishes() -> None:
    st = MagicMock()
    st.session_state = {"_selected_job_auto_refresh": True}
    st.fragment.side_effect = _fragment_runs_immediately

    with patch(
        "ui.streamlit_app._render_selected_job",
        return_value="review_ready",
    ):
        _render_selected_job_with_refresh(st, MagicMock(), "job-123")

    assert st.session_state["_selected_job_auto_refresh"] is False
    st.rerun.assert_called_once_with()


def test_active_batch_uses_five_second_fragment_refresh() -> None:
    st = MagicMock()
    st.session_state = {"_selected_batch_auto_refresh": True}
    st.fragment.side_effect = _fragment_runs_immediately

    with patch(
        "ui.streamlit_app._render_selected_batch",
        return_value="processing",
    ):
        _render_selected_batch_with_refresh(st, MagicMock(), "batch_abc123")

    st.fragment.assert_called_once_with(run_every="5s")
    assert st.session_state["_selected_batch_auto_refresh"] is True
    st.rerun.assert_not_called()


def test_batch_transitions_directly_to_download_with_one_full_rerun() -> None:
    st = MagicMock()
    st.session_state = {"_selected_batch_auto_refresh": True}
    st.fragment.side_effect = _fragment_runs_immediately

    with patch(
        "ui.streamlit_app._render_selected_batch",
        return_value="ready",
    ):
        _render_selected_batch_with_refresh(st, MagicMock(), "batch_abc123")

    assert st.session_state["_selected_batch_auto_refresh"] is False
    st.rerun.assert_called_once_with()


def test_retryable_batch_error_does_not_disable_existing_timer() -> None:
    st = MagicMock()
    st.session_state = {"_selected_batch_auto_refresh": True}
    st.fragment.side_effect = _fragment_runs_immediately

    with patch("ui.streamlit_app._render_selected_batch", return_value=None):
        _render_selected_batch_with_refresh(st, MagicMock(), "batch_abc123")

    assert st.session_state["_selected_batch_auto_refresh"] is True
    st.rerun.assert_not_called()


def test_manual_refresh_rearms_batch_timer_when_processing_recovers() -> None:
    st = MagicMock()
    st.session_state = {"_selected_batch_auto_refresh": False}
    st.fragment.side_effect = _fragment_runs_immediately

    with patch(
        "ui.streamlit_app._render_selected_batch",
        return_value="processing",
    ):
        _render_selected_batch_with_refresh(st, MagicMock(), "batch_abc123")

    assert st.session_state["_selected_batch_auto_refresh"] is True
    st.rerun.assert_called_once_with()


def test_purged_batch_still_offers_transcribe_more_action() -> None:
    st = MagicMock()
    st.session_state = {}
    st.query_params = {}
    client = MagicMock()
    client.get_batch.side_effect = ApiError(
        "This job or transcript is no longer available.",
        status_code=404,
    )

    with patch("ui.streamlit_app._render_start_another_action") as render_home:
        status = _render_selected_batch(st, client, "batch_abc123")

    assert status == "unavailable"
    render_home.assert_called_once_with(
        st,
        key="new-upload-batch-batch_abc123",
    )


def test_direct_batch_child_link_redirects_to_combined_workflow() -> None:
    st = MagicMock()
    st.session_state = {}
    st.query_params = {"job": "job-123"}
    client = MagicMock()
    client.get_job.return_value = {
        "id": "job-123",
        "batch_id": "batch_abc123",
        "status": "succeeded",
    }

    with patch("ui.streamlit_app._set_selected_batch") as select_batch:
        status = _render_selected_job(st, client, "job-123")

    assert status == "processing"
    select_batch.assert_called_once_with(st, "batch_abc123")
    st.rerun.assert_called_once_with()
