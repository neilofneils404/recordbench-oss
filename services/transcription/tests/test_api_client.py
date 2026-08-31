from __future__ import annotations

import io
import ast
import json
import sys
import threading
import unittest
from contextlib import nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit
from urllib.request import urlopen as real_urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ui.api_client import ApiClient, ApiError, UploadPart  # noqa: E402
from ui.streamlit_app import (  # noqa: E402
    _accepted_job_ids,
    _available_languages,
    _available_profiles,
    _browser_delivery_url,
    _classify_download_exports,
    _markdown_text,
    _render_selected_job,
)


class _TestServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.requests: list[dict[str, Any]] = []
        self.responses: dict[tuple[str, str], tuple[int, dict[str, str], Any]] = {}


class _Handler(BaseHTTPRequestHandler):
    server: _TestServer

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _handle(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length) if content_length else b""
        path = urlsplit(self.path).path
        self.server.requests.append(
            {
                "method": self.command,
                "path": path,
                "raw_path": self.path,
                "headers": dict(self.headers),
                "body": body,
            }
        )
        status, headers, payload = self.server.responses.get(
            (self.command, path),
            (200, {}, {"ok": True}),
        )
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(raw)

    do_GET = _handle
    do_POST = _handle
    do_PATCH = _handle
    do_DELETE = _handle


class _GuardedStream(io.BytesIO):
    """Fails if a client attempts an unbounded or oversized read."""

    def __init__(self, payload: bytes, max_read: int) -> None:
        super().__init__(payload)
        self.max_read = max_read
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        if size < 0 or size > self.max_read:
            raise AssertionError(f"upload read was not bounded: {size}")
        self.read_sizes.append(size)
        return super().read(size)


class ApiClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = _TestServer()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.client = ApiClient(
            f"http://{host}:{port}",
            "pilot-token",
            user_id="staff-123",
            timeout=2,
            upload_timeout=2,
            chunk_size=64 * 1024,
        )

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    @staticmethod
    def _header(request: dict[str, Any], name: str) -> str | None:
        wanted = name.casefold()
        return next((value for key, value in request["headers"].items() if key.casefold() == wanted), None)

    def test_list_jobs_and_trusted_headers(self) -> None:
        self.server.responses[("GET", "/v1/jobs")] = (
            200,
            {},
            {"jobs": [{"id": "job-a", "status": "queued"}]},
        )

        jobs = self.client.list_jobs(limit=500)

        self.assertEqual(["job-a"], [item["id"] for item in jobs])
        request = self.server.requests[-1]
        self.assertEqual("/v1/jobs?limit=200", request["raw_path"])
        self.assertEqual("Bearer pilot-token", self._header(request, "Authorization"))
        self.assertEqual("staff-123", self._header(request, "X-User-ID"))

    def test_readiness_uses_the_authenticated_resource_check(self) -> None:
        self.server.responses[("GET", "/ready")] = (
            200,
            {},
            {"status": "not_ready", "checks": {"disk_admission_ready": False}},
        )

        result = self.client.readiness()

        self.assertEqual(result["status"], "not_ready")
        self.assertEqual(self.server.requests[-1]["path"], "/ready")
        self.assertEqual(
            "Bearer pilot-token",
            self._header(self.server.requests[-1], "Authorization"),
        )

    def test_untrusted_ui_labels_cannot_create_markdown_links(self) -> None:
        rendered = _markdown_text("[recording](https://invalid.example)\n# heading")
        self.assertIn(r"\[recording\]\(https://invalid\.example\)", rendered)
        self.assertIn(r"\# heading", rendered)
        self.assertNotIn("\n", rendered)

    def test_pilot_language_list_is_operator_bounded(self) -> None:
        with patch.dict(
            "os.environ",
            {"TRANSCRIPTION_V2_PILOT_LANGUAGE_CODES": "auto,en,es"},
            clear=False,
        ):
            available = _available_languages()

        self.assertEqual(
            {
                "Auto-detect (recommended)": None,
                "English": "en",
                "Spanish": "es",
            },
            available,
        )

    def test_unstaged_fast_profile_is_hidden_from_pilot(self) -> None:
        with patch.dict(
            "os.environ",
            {"TRANSCRIPTION_V2_PILOT_PROFILE_NAMES": "balanced,high_accuracy"},
            clear=False,
        ):
            available = _available_profiles()

        self.assertEqual(
            {"Balanced": "balanced", "Highest accuracy": "high_accuracy"},
            available,
        )

    def test_multipart_upload_is_chunked_and_restores_position(self) -> None:
        payload = (b"recording-data-" * 20_000) + b"end"
        stream = _GuardedStream(payload, 64 * 1024)
        stream.seek(11)
        self.server.responses[("POST", "/v1/jobs")] = (
            202,
            {},
            {"jobs": [{"id": "job-one"}, {"id": "job-two"}]},
        )

        response = self.client.submit_job(
            [UploadPart("../confidential call ü.wav", stream, size=len(payload), content_type="audio/wav")],
            {"profile": "balanced", "source_language": None, "retention_hours": 4},
        )

        self.assertEqual(["job-one", "job-two"], _accepted_job_ids(response))
        self.assertEqual(11, stream.tell())
        self.assertGreater(len(stream.read_sizes), 1)
        self.assertLessEqual(max(stream.read_sizes), 64 * 1024)
        request = self.server.requests[-1]
        self.assertIn("multipart/form-data; boundary=", request["headers"]["Content-Type"])
        self.assertIn(b'filename="confidential call ?.wav"', request["body"])
        self.assertIn(b"filename*=UTF-8''confidential%20call%20%C3%BC.wav", request["body"])
        self.assertIn(b'"profile":"balanced"', request["body"])
        self.assertIn(payload[:100], request["body"])
        self.assertEqual("staff-123", self._header(request, "X-User-ID"))

    def test_thirty_small_recordings_upload_in_one_request(self) -> None:
        client = ApiClient(
            self.client.base_url,
            "pilot-token",
            user_id="staff-123",
            timeout=2,
            upload_timeout=2,
            max_upload_bytes=64,
            max_batch_upload_bytes=64,
            max_files_per_request=100,
        )
        uploads = [
            UploadPart(f"call-{index:02d}.wav", io.BytesIO(b"x"), size=1)
            for index in range(30)
        ]

        response = client.submit_job(uploads, {})

        self.assertTrue(response["ok"])
        self.assertEqual(1, len(self.server.requests))
        self.assertEqual(
            30,
            self.server.requests[0]["body"].count(
                b'Content-Disposition: form-data; name="files"'
            ),
        )

    def test_upload_capacity_failures_do_not_open_a_network_request(self) -> None:
        client = ApiClient(
            self.client.base_url,
            "pilot-token",
            user_id="staff-123",
            timeout=2,
            upload_timeout=2,
            max_upload_bytes=10,
            max_batch_upload_bytes=12,
            max_files_per_request=2,
        )
        rejected_cases = (
            (
                [UploadPart("large.wav", io.BytesIO(b"x" * 11))],
                "file_too_large",
            ),
            (
                [
                    UploadPart("one.wav", io.BytesIO(b"x" * 7)),
                    UploadPart("two.wav", io.BytesIO(b"x" * 6)),
                ],
                "batch_too_large",
            ),
            (
                [
                    UploadPart("one.wav", io.BytesIO(b"x")),
                    UploadPart("two.wav", io.BytesIO(b"x")),
                    UploadPart("three.wav", io.BytesIO(b"x")),
                ],
                "too_many_files",
            ),
        )

        for uploads, expected_code in rejected_cases:
            with self.subTest(code=expected_code), self.assertRaises(ApiError) as caught:
                client.submit_job(uploads, {})
            self.assertEqual(caught.exception.code, expected_code)
            self.assertEqual([], self.server.requests)

        response = client.submit_job(
            [
                UploadPart("one.wav", io.BytesIO(b"x" * 6)),
                UploadPart("two.wav", io.BytesIO(b"x" * 6)),
            ],
            {},
        )
        self.assertTrue(response["ok"])
        self.assertEqual(1, len(self.server.requests))

    def test_upload_part_rejects_negative_declared_size(self) -> None:
        with self.assertRaisesRegex(ValueError, "negative"):
            UploadPart("recording.wav", io.BytesIO(), size=-1).byte_size()
        self.assertEqual([], self.server.requests)

    def test_http_error_never_exposes_response_detail(self) -> None:
        secret_phrase = "verbatim confidential transcript words"
        self.server.responses[("GET", "/v1/jobs/job-bad")] = (
            500,
            {"X-Request-ID": "req-safe-42"},
            {"code": "MODEL_FAILED", "detail": secret_phrase},
        )

        with self.assertRaises(ApiError) as caught:
            self.client.get_job("job-bad")

        rendered = str(caught.exception)
        self.assertNotIn(secret_phrase, rendered)
        self.assertIn("MODEL_FAILED", rendered)
        self.assertIn("req-safe-42", rendered)
        self.assertTrue(caught.exception.retryable)

    def test_optimistic_segment_update_and_url_escaping(self) -> None:
        self.server.responses[("PATCH", "/v1/jobs/job%2Fone/segments/seg%20one")] = (
            200,
            {},
            {"revision": 8},
        )

        result = self.client.update_segment(
            "job/one",
            "seg one",
            text="corrected text",
            expected_revision=7,
        )

        self.assertEqual(8, result["revision"])
        request = self.server.requests[-1]
        self.assertEqual("/v1/jobs/job%2Fone/segments/seg%20one", request["path"])
        self.assertEqual(
            {"text": "corrected text", "expected_revision": 7},
            json.loads(request["body"]),
        )

    def test_delete_and_one_time_delivery_package(self) -> None:
        self.server.responses[("DELETE", "/v1/jobs/job-1")] = (
            200,
            {},
            {"status": "deleted", "job_id": "job-1"},
        )
        self.server.responses[("POST", "/v1/jobs/job-1/delivery-package")] = (
            200,
            {},
            {"download_url": "/download/opaque", "purge_after_download": True},
        )

        delivery = self.client.create_delivery_package("job-1", purge_after_download=True)
        deleted = self.client.delete_job("job-1")

        self.assertTrue(delivery["purge_after_download"])
        self.assertEqual(deleted["status"], "deleted")
        package_request = self.server.requests[-2]
        self.assertEqual({"purge_after_download": True}, json.loads(package_request["body"]))
        self.assertEqual("staff-123", self._header(self.server.requests[-1], "X-User-ID"))

    def test_batch_status_and_aggregate_delivery_contract(self) -> None:
        batch_id = "batch_0123456789abcdef0123456789abcdef"
        self.server.responses[("GET", f"/v1/batches/{batch_id}")] = (
            200,
            {},
            {
                "batch_id": batch_id,
                "status": "ready",
                "download_ready": True,
                "jobs": [],
            },
        )
        self.server.responses[
            ("POST", f"/v1/batches/{batch_id}/delivery-package")
        ] = (
            200,
            {},
            {
                "batch_id": batch_id,
                "download_url": "/v1/delivery/opaque",
                "purge_after_download": True,
                "filename": "transcriptions.zip",
            },
        )

        status = self.client.get_batch(batch_id)
        with patch("ui.api_client.urlopen", wraps=real_urlopen) as opener:
            package = self.client.create_batch_delivery_package(
                batch_id, purge_after_download=True
            )

        self.assertTrue(status["download_ready"])
        self.assertEqual("transcriptions.zip", package["filename"])
        self.assertEqual(300.0, opener.call_args.kwargs["timeout"])
        self.assertEqual(
            {"purge_after_download": True},
            json.loads(self.server.requests[-1]["body"]),
        )

    def test_submission_response_shapes(self) -> None:
        self.assertEqual(["a", "b"], _accepted_job_ids({"jobs": [{"id": "a"}, {"job_id": "b"}]}))
        self.assertEqual(["c"], _accepted_job_ids({"job": {"id": "c"}}))
        self.assertEqual(["d"], _accepted_job_ids({"job_id": "d"}))
        self.assertEqual([], _accepted_job_ids({"status": "accepted"}))

    def test_browser_urls_are_same_origin_or_relative(self) -> None:
        self.assertEqual(
            "/v1/jobs/job-1/media",
            self.client.resolve_url("/v1/jobs/job-1/media"),
        )
        self.assertEqual(
            self.client.base_url + "/download/one",
            self.client.resolve_url(self.client.base_url + "/download/one"),
        )
        self.assertIsNone(self.client.resolve_url("https://external.example/confidential"))
        self.assertIsNone(self.client.resolve_url("javascript:alert(1)"))

        with patch.dict(
            "os.environ",
            {"TRANSCRIPTION_V2_BROWSER_DELIVERY_ORIGIN": "http://127.0.0.1:8510"},
            clear=False,
        ):
            self.assertEqual(
                "http://127.0.0.1:8510/v1/delivery/opaque",
                self.client.resolve_url("/v1/delivery/opaque"),
            )
        with patch.dict(
            "os.environ",
            {"TRANSCRIPTION_V2_BROWSER_DELIVERY_ORIGIN": "https://external.example"},
            clear=False,
        ):
            self.assertIsNone(self.client.resolve_url("/v1/delivery/opaque"))

    def test_browser_context_makes_relative_media_url_absolute(self) -> None:
        class _Context:
            url = "https://transcript.example.test:8512/transcription/review/"

        class _Streamlit:
            context = _Context()

        with patch.dict(
            "os.environ",
            {"TRANSCRIPTION_V2_BROWSER_DELIVERY_ORIGIN": ""},
            clear=False,
        ):
            resolved = _browser_delivery_url(
                _Streamlit(),
                self.client,
                "/transcription-downloads/signed-token",
            )

        self.assertEqual(
            "https://transcript.example.test:8512/transcription-downloads/signed-token",
            resolved,
        )

    def test_browser_media_url_fails_closed_without_safe_absolute_origin(self) -> None:
        with patch.dict(
            "os.environ",
            {"TRANSCRIPTION_V2_BROWSER_DELIVERY_ORIGIN": ""},
            clear=False,
        ):
            self.assertIsNone(
                _browser_delivery_url(
                    object(),
                    self.client,
                    "/transcription-downloads/signed-token",
                )
            )
            self.assertIsNone(
                self.client.resolve_url(
                    "/transcription-downloads/signed-token",
                    browser_origin="https://staff:secret@transcript.example.test:8512/",
                )
            )

        with patch.dict(
            "os.environ",
            {"TRANSCRIPTION_V2_BROWSER_DELIVERY_ORIGIN": "http://staff:secret@localhost:8510"},
            clear=False,
        ):
            self.assertIsNone(
                self.client.resolve_url("/transcription-downloads/signed-token")
            )

    def test_streamlit_module_is_lazy(self) -> None:
        # There must be no module-level Streamlit import. This keeps client
        # tests usable even if an unrelated test imported Streamlit earlier.
        source = (PROJECT_ROOT / "ui" / "streamlit_app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        top_level_imports = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                top_level_imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top_level_imports.append(node.module)
        self.assertNotIn("streamlit", top_level_imports)

    def test_create_job_has_no_manual_review_acknowledgement_gate(self) -> None:
        source = (PROJECT_ROOT / "ui" / "streamlit_app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        render_new_job = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_render_new_job"
        )
        submit_calls = [
            node
            for node in ast.walk(render_new_job)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "form_submit_button"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "Start transcription"
        ]
        self.assertEqual(1, len(submit_calls))
        disabled = next(
            keyword.value
            for keyword in submit_calls[0].keywords
            if keyword.arg == "disabled"
        )
        self.assertIn(
            "selection_error",
            {
                node.id
                for node in ast.walk(disabled)
                if isinstance(node, ast.Name)
            },
        )
        self.assertNotIn(
            "acknowledged",
            {
                node.id
                for node in ast.walk(render_new_job)
                if isinstance(node, ast.Name)
            },
        )

    def test_completed_job_is_download_first_and_editor_is_optional(self) -> None:
        source = (PROJECT_ROOT / "ui" / "streamlit_app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        selected_job = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_render_selected_job"
        )
        download_call = next(
            node
            for node in ast.walk(selected_job)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_render_download_center"
        )
        editor_gate = next(
            node
            for node in ast.walk(selected_job)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "open_editor"
        )
        transcript_calls = [
            node
            for node in ast.walk(selected_job)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get_transcript"
        ]
        gated_transcript_calls = [
            node
            for node in ast.walk(editor_gate)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get_transcript"
        ]
        self.assertLess(download_call.lineno, editor_gate.lineno)
        self.assertEqual(1, len(transcript_calls))
        self.assertEqual(transcript_calls, gated_transcript_calls)

    def test_download_exports_promote_word_plain_text_zip_and_translation(self) -> None:
        exports = [
            {"name": "transcript.vtt"},
            {"name": "transcript.translation.en.docx"},
            {"name": "transcript.translation.en.txt"},
            {"name": "transcript.delivery.zip"},
            {"name": "transcript.json"},
            {"name": "transcript.docx"},
            {"name": "transcript.txt"},
        ]

        word, transcript, package, translations, remaining = (
            _classify_download_exports(exports)
        )

        self.assertEqual("transcript.docx", word["name"])
        self.assertEqual("transcript.txt", transcript["name"])
        self.assertEqual("transcript.delivery.zip", package["name"])
        self.assertEqual(
            [
                "transcript.translation.en.docx",
                "transcript.translation.en.txt",
            ],
            [item["name"] for item in translations],
        )
        self.assertEqual(
            ["transcript.json", "transcript.vtt"],
            [item["name"] for item in remaining],
        )

    def test_download_classifier_uses_package_stem_for_translation_like_source_name(self) -> None:
        exports = [
            {"name": "transcript.translation.en.delivery.zip"},
            {"name": "transcript.translation.en.docx"},
            {"name": "transcript.translation.en.txt"},
            {"name": "transcript.translation.en.srt"},
            {"name": "transcript.translation.en.translation.en.docx"},
            {"name": "transcript.translation.en.translation.en.txt"},
        ]

        word, transcript, package, translations, remaining = (
            _classify_download_exports(exports)
        )

        self.assertEqual("transcript.translation.en.docx", word["name"])
        self.assertEqual("transcript.translation.en.txt", transcript["name"])
        self.assertEqual("transcript.translation.en.delivery.zip", package["name"])
        self.assertEqual(
            {
                "transcript.translation.en.translation.en.docx",
                "transcript.translation.en.translation.en.txt",
            },
            {item["name"] for item in translations},
        )
        self.assertEqual(
            {"transcript.translation.en.srt"},
            {item["name"] for item in remaining},
        )

    def test_default_completed_screen_offers_downloads_without_loading_editor(self) -> None:
        st = MagicMock()
        st.context = SimpleNamespace(
            url="https://transcript.example.test:8512/transcription/review/"
        )
        st.session_state = {}
        st.query_params = {}
        st.container.side_effect = lambda **_kwargs: nullcontext()
        st.expander.side_effect = lambda *_args, **_kwargs: nullcontext()
        st.columns.side_effect = lambda specification: [
            nullcontext()
            for _ in (
                range(specification)
                if isinstance(specification, int)
                else specification
            )
        ]
        st.toggle.return_value = False
        st.checkbox.return_value = False
        st.button.return_value = False

        client = MagicMock()
        resolver = ApiClient(
            "http://127.0.0.1:8510",
            "pilot-token",
            user_id="test-owner",
        )
        client.resolve_url.side_effect = resolver.resolve_url
        client.get_job.return_value = {
            "id": "job-ready",
            "status": "review_ready",
            "stage": "export",
            "display_name": "Synthetic recording",
        }
        client.get_exports.return_value = [
            {
                "name": "transcript.docx",
                "download_url": "/transcription-downloads/docx-token",
                "size_bytes": 150,
            },
            {
                "name": "transcript.txt",
                "download_url": "/transcription-downloads/txt-token",
                "size_bytes": 100,
            },
            {
                "name": "transcript.delivery.zip",
                "download_url": "/transcription-downloads/zip-token",
                "size_bytes": 200,
            },
        ]

        _render_selected_job(st, client, "job-ready")

        client.get_exports.assert_called_once_with("job-ready")
        client.get_transcript.assert_not_called()
        labels = [call.args[0] for call in st.link_button.call_args_list]
        self.assertIn("Download Word transcript (.docx)", labels)
        self.assertIn("Download plain-text transcript (.txt)", labels)
        self.assertIn("Download complete transcript package (.zip)", labels)
        st.audio.assert_not_called()
        st.tabs.assert_not_called()
        editor_toggle = next(
            call
            for call in st.toggle.call_args_list
            if call.args and call.args[0] == "Preview or correct the transcript (optional)"
        )
        self.assertIs(editor_toggle.kwargs.get("value"), False)


if __name__ == "__main__":
    unittest.main()
