"""Small, dependency-free client for the Transcription v2 JSON API.

The Streamlit UI deliberately talks only to this module.  Keeping HTTP and
multipart details here makes the UI testable without importing Streamlit and,
more importantly, lets uploads be sent in bounded chunks instead of calling
``UploadedFile.getvalue()``.
"""

from __future__ import annotations

import http.client
import json
import mimetypes
import os
import re
import ssl
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:8510"
DEFAULT_CHUNK_SIZE = 1024 * 1024
DEFAULT_MAX_UPLOAD_BYTES = 5 * 1024**3
DEFAULT_MAX_BATCH_UPLOAD_BYTES = 5 * 1024**3
DEFAULT_MAX_FILES_PER_REQUEST = 100
DEFAULT_MAX_RETAINED_BYTES_PER_OWNER = 10 * 1024**3
DEFAULT_PACKAGE_TIMEOUT_SECONDS = 300.0
MAX_JSON_RESPONSE_BYTES = 8 * 1024 * 1024
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _configured_positive_int(
    environment_name: str,
    explicit_value: int | None,
    default: int,
) -> int:
    value: object = explicit_value
    if value is None:
        configured = os.getenv(environment_name)
        value = default if configured is None or not configured.strip() else configured
    if isinstance(value, bool):
        raise ValueError(f"{environment_name} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{environment_name} must be a positive integer") from None
    if parsed < 1:
        raise ValueError(f"{environment_name} must be a positive integer")
    return parsed


class ApiError(RuntimeError):
    """A privacy-safe error suitable for display to a staff user.

    Response bodies are intentionally never included: a backend error could
    contain transcript text, a filename, or another confidential value.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        request_id: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.request_id = request_id
        self.retryable = retryable

    @classmethod
    def from_status(
        cls,
        status_code: int,
        *,
        code: str | None = None,
        request_id: str | None = None,
    ) -> "ApiError":
        messages = {
            400: "The service rejected this request. Check the selected options and try again.",
            401: "The transcription service credentials are missing or invalid.",
            403: "You do not have permission to perform this action.",
            404: "This job or transcript is no longer available.",
            409: "This transcript changed after you opened it. Refresh before saving your edit.",
            413: "One or more recordings exceed the service upload limit.",
            415: "One or more files use an unsupported media format.",
            422: "The service could not validate these job settings.",
            429: "The transcription queue is busy. Wait briefly and try again.",
            500: "The transcription service encountered an internal error.",
            502: "The transcription worker is temporarily unavailable.",
            503: "The transcription service is temporarily unavailable.",
            504: "The transcription service timed out while handling the request.",
            507: "The transcription service is preserving required free disk space. Delete finished jobs or ask an administrator to review capacity.",
        }
        message = messages.get(status_code, f"The transcription service returned HTTP {status_code}.")
        suffixes = []
        if code:
            suffixes.append(f"code {code}")
        if request_id:
            suffixes.append(f"request {request_id}")
        if suffixes:
            message += " Reference: " + ", ".join(suffixes) + "."
        return cls(
            message,
            status_code=status_code,
            code=code,
            request_id=request_id,
            retryable=status_code in {408, 425, 429, 500, 502, 503, 504},
        )


@dataclass
class UploadPart:
    """One seekable media stream submitted as a multipart ``files`` field."""

    filename: str
    fileobj: BinaryIO
    size: int | None = None
    content_type: str | None = None

    def normalized_filename(self) -> str:
        # Do not allow a browser-supplied path or control character into a
        # multipart header.  Unicode is retained in the RFC 5987 parameter.
        name = Path(self.filename or "recording.bin").name
        name = name.replace("\r", "_").replace("\n", "_").replace('"', "_")
        return name[:240] or "recording.bin"

    def byte_size(self) -> int:
        if self.size is not None:
            size = int(self.size)
            if size < 0:
                raise ValueError("Upload size cannot be negative")
            return size
        try:
            original = self.fileobj.tell()
            self.fileobj.seek(0, os.SEEK_END)
            size = self.fileobj.tell()
            self.fileobj.seek(original, os.SEEK_SET)
        except (AttributeError, OSError) as exc:
            raise ValueError("Upload streams must be seekable or provide an explicit size") from exc
        size = int(size)
        if size < 0:
            raise ValueError("Upload size cannot be negative")
        return size

    def media_type(self) -> str:
        return self.content_type or mimetypes.guess_type(self.normalized_filename())[0] or "application/octet-stream"


class ApiClient:
    """HTTP client for the staff-facing v2 API contract documented in UX_NOTES."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        *,
        user_id: str | None = None,
        timeout: float = 30.0,
        upload_timeout: float = 3600.0,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        max_upload_bytes: int | None = None,
        max_batch_upload_bytes: int | None = None,
        max_files_per_request: int | None = None,
    ) -> None:
        configured_url = (base_url or os.getenv("TRANSCRIPTION_V2_API_URL") or DEFAULT_BASE_URL).strip()
        configured_url = configured_url.rstrip("/")
        parsed = urlsplit(configured_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("TRANSCRIPTION_V2_API_URL must be an http(s) URL")
        if parsed.query or parsed.fragment:
            raise ValueError("TRANSCRIPTION_V2_API_URL cannot include a query or fragment")
        self.base_url = configured_url
        self.token = token if token is not None else os.getenv("TRANSCRIPTION_V2_API_TOKEN", "")
        self.user_id = (user_id if user_id is not None else os.getenv("TRANSCRIPTION_V2_USER_ID", "local-reviewer")).strip()
        if not self.user_id or not re.fullmatch(r"[A-Za-z0-9_.@-]{1,128}", self.user_id):
            raise ValueError("TRANSCRIPTION_V2_USER_ID contains unsupported characters")
        self.timeout = float(timeout)
        self.upload_timeout = float(upload_timeout)
        self.chunk_size = max(64 * 1024, int(chunk_size))
        self.max_upload_bytes = _configured_positive_int(
            "TRANSCRIPTION_V2_MAX_UPLOAD_BYTES",
            max_upload_bytes,
            DEFAULT_MAX_UPLOAD_BYTES,
        )
        self.max_files_per_request = _configured_positive_int(
            "TRANSCRIPTION_V2_MAX_FILES",
            max_files_per_request,
            DEFAULT_MAX_FILES_PER_REQUEST,
        )
        owner_byte_limit = _configured_positive_int(
            "TRANSCRIPTION_V2_MAX_RETAINED_BYTES_PER_OWNER",
            None,
            DEFAULT_MAX_RETAINED_BYTES_PER_OWNER,
        )
        compatible_batch_default = max(
            self.max_upload_bytes,
            min(
                DEFAULT_MAX_BATCH_UPLOAD_BYTES,
                owner_byte_limit,
                self.max_upload_bytes * self.max_files_per_request,
            ),
        )
        self.max_batch_upload_bytes = _configured_positive_int(
            "TRANSCRIPTION_V2_MAX_BATCH_UPLOAD_BYTES",
            max_batch_upload_bytes,
            compatible_batch_default,
        )
        if self.max_batch_upload_bytes < self.max_upload_bytes:
            raise ValueError(
                "TRANSCRIPTION_V2_MAX_BATCH_UPLOAD_BYTES cannot be smaller than the per-file limit"
            )

    # ---- Public API -----------------------------------------------------

    def health(self) -> dict[str, Any]:
        return self._json_request("GET", "/health")

    def readiness(self) -> dict[str, Any]:
        return self._json_request("GET", "/ready")

    def submit_job(self, files: Sequence[UploadPart], options: Mapping[str, Any]) -> dict[str, Any]:
        if not files:
            raise ValueError("At least one recording is required")
        if len(files) > self.max_files_per_request:
            raise ApiError(
                "This unusually large selection exceeds the service safety limit. "
                "Split it into two uploads.",
                status_code=400,
                code="too_many_files",
            )
        total_bytes = 0
        for upload in files:
            size_bytes = upload.byte_size()
            if size_bytes > self.max_upload_bytes:
                raise ApiError(
                    "One or more recordings exceed the per-file upload limit.",
                    status_code=413,
                    code="file_too_large",
                )
            total_bytes += size_bytes
            if total_bytes > self.max_batch_upload_bytes:
                raise ApiError(
                    "The selected recordings exceed the total upload limit. "
                    "Reduce the selection and try again.",
                    status_code=413,
                    code="batch_too_large",
                )
        return self._multipart_request(
            "/v1/jobs",
            fields={"options": json.dumps(dict(options), ensure_ascii=False, separators=(",", ":"))},
            files=files,
        )

    def list_jobs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        payload = self._json_request("GET", f"/v1/jobs?limit={max(1, min(int(limit), 200))}")
        if isinstance(payload, list):
            return payload
        jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
        return jobs if isinstance(jobs, list) else []

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._json_request("GET", f"/v1/jobs/{self._id(job_id)}")

    def get_batch(self, batch_id: str) -> dict[str, Any]:
        payload = self._json_request("GET", f"/v1/batches/{self._id(batch_id)}")
        if not isinstance(payload, dict):
            raise ApiError("The transcription service returned an unexpected batch response.")
        return payload

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        return self._json_request("POST", f"/v1/jobs/{self._id(job_id)}/cancel", payload={})

    def retry_job(self, job_id: str) -> dict[str, Any]:
        return self._json_request("POST", f"/v1/jobs/{self._id(job_id)}/retry", payload={})

    def delete_job(self, job_id: str) -> dict[str, Any]:
        """Immediately purge source media and generated artifacts for a job."""
        return self._json_request("DELETE", f"/v1/jobs/{self._id(job_id)}")

    def get_transcript(self, job_id: str) -> dict[str, Any]:
        return self._json_request("GET", f"/v1/jobs/{self._id(job_id)}/transcript")

    def update_segment(
        self,
        job_id: str,
        segment_id: str,
        *,
        text: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        return self._json_request(
            "PATCH",
            f"/v1/jobs/{self._id(job_id)}/segments/{self._id(segment_id)}",
            payload={"text": text, "expected_revision": int(expected_revision)},
        )

    def update_speaker(
        self,
        job_id: str,
        cluster_id: str,
        *,
        display_name: str,
        identity_state: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        if identity_state not in {"cluster", "confirmed"}:
            raise ValueError("Staff updates may set speaker identity_state only to cluster or confirmed")
        return self._json_request(
            "PATCH",
            f"/v1/jobs/{self._id(job_id)}/speakers/{self._id(cluster_id)}",
            payload={
                "display_name": display_name,
                "identity_state": identity_state,
                "expected_revision": int(expected_revision),
            },
        )

    def get_exports(self, job_id: str) -> list[dict[str, Any]]:
        payload = self._json_request("GET", f"/v1/jobs/{self._id(job_id)}/exports")
        if isinstance(payload, list):
            return payload
        exports = payload.get("exports", []) if isinstance(payload, dict) else []
        return exports if isinstance(exports, list) else []

    def create_delivery_package(
        self,
        job_id: str,
        *,
        purge_after_download: bool = True,
    ) -> dict[str, Any]:
        """Create a short-lived package link, optionally purging after delivery.

        The backend is responsible for deleting only after it has successfully
        streamed the response.  Merely creating the link must not purge data.
        """
        return self._json_request(
            "POST",
            f"/v1/jobs/{self._id(job_id)}/delivery-package",
            payload={"purge_after_download": bool(purge_after_download)},
        )

    def create_batch_delivery_package(
        self,
        batch_id: str,
        *,
        purge_after_download: bool = True,
    ) -> dict[str, Any]:
        """Create one short-lived aggregate link for a multi-file submission."""

        payload = self._json_request(
            "POST",
            f"/v1/batches/{self._id(batch_id)}/delivery-package",
            payload={"purge_after_download": bool(purge_after_download)},
            timeout=max(self.timeout, DEFAULT_PACKAGE_TIMEOUT_SECONDS),
        )
        if not isinstance(payload, dict):
            raise ApiError("The transcription service returned an unexpected batch response.")
        return payload

    def resolve_url(
        self,
        value: str | None,
        *,
        browser_origin: str | None = None,
    ) -> str | None:
        """Resolve a backend-provided delivery URL for the staff browser.

        Streamlit treats a root-relative string passed to ``st.audio`` as a
        server-local filename. In a proxied deployment, use the browser's
        current origin to produce an absolute same-origin URL. The explicit
        loopback override remains available for the split-port development
        stack, where the browser-facing API is not on Streamlit's origin.
        """
        if not value:
            return None
        parsed = urlsplit(value)
        if parsed.scheme:
            configured = urlsplit(self.base_url)
            if parsed.scheme not in {"http", "https"}:
                return None
            # Media/export links cannot silently send a staff browser to a
            # third-party host. Deployments needing a public front-door origin
            # should have the API return a relative URL.
            return value if (parsed.scheme, parsed.netloc) == (configured.scheme, configured.netloc) else None
        # Relative paths are exposed only through the reviewed browser front
        # door, never by substituting the private JSON API origin.
        relative = "/" + value.lstrip("/")
        development_origin = os.getenv(
            "TRANSCRIPTION_V2_BROWSER_DELIVERY_ORIGIN", ""
        ).strip().rstrip("/")
        if development_origin:
            origin = urlsplit(development_origin)
            if (
                origin.scheme not in {"http", "https"}
                or origin.hostname not in LOOPBACK_HOSTS
                or origin.username is not None
                or origin.password is not None
                or origin.path not in {"", "/"}
                or origin.query
                or origin.fragment
            ):
                return None
            return development_origin + relative
        if browser_origin:
            origin = urlsplit(browser_origin)
            if (
                origin.scheme not in {"http", "https"}
                or not origin.hostname
                or origin.username is not None
                or origin.password is not None
            ):
                return None
            return urlunsplit((origin.scheme, origin.netloc, relative, "", ""))
        return relative

    # ---- JSON transport ------------------------------------------------

    def _json_request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        body = None
        headers = self._headers()
        if payload is not None:
            body = json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(self._url(path), data=body, method=method, headers=headers)
        try:
            with urlopen(
                request,
                timeout=self.timeout if timeout is None else float(timeout),
            ) as response:
                raw = self._read_limited(response, MAX_JSON_RESPONSE_BYTES)
        except HTTPError as exc:
            raise self._http_error(exc.code, exc.headers, exc) from None
        except (URLError, TimeoutError, OSError):
            raise ApiError(
                "Could not reach the local transcription service. The request can be retried safely.",
                retryable=True,
            ) from None
        return self._decode_json(raw)

    # ---- Streaming multipart transport --------------------------------

    def _multipart_request(
        self,
        path: str,
        *,
        fields: Mapping[str, str],
        files: Sequence[UploadPart],
    ) -> dict[str, Any]:
        boundary = "----transcription-v2-" + uuid.uuid4().hex
        field_parts = [self._field_part(boundary, name, value) for name, value in fields.items()]
        file_headers = [self._file_header(boundary, part) for part in files]
        closing = f"--{boundary}--\r\n".encode("ascii")
        total_length = sum(len(part) for part in field_parts)
        total_length += sum(len(header) + part.byte_size() + 2 for header, part in zip(file_headers, files))
        total_length += len(closing)

        parsed = urlsplit(self._url(path))
        connection_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        kwargs: dict[str, Any] = {"timeout": self.upload_timeout}
        if parsed.scheme == "https":
            kwargs["context"] = ssl.create_default_context()
        conn = connection_cls(parsed.hostname, parsed.port, **kwargs)
        target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        original_positions: list[int | None] = []
        try:
            conn.putrequest("POST", target)
            for name, value in self._headers().items():
                conn.putheader(name, value)
            conn.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
            conn.putheader("Content-Length", str(total_length))
            conn.endheaders()

            for part in field_parts:
                conn.send(part)
            for header, upload in zip(file_headers, files):
                try:
                    original_positions.append(upload.fileobj.tell())
                except (AttributeError, OSError):
                    original_positions.append(None)
                try:
                    upload.fileobj.seek(0)
                except (AttributeError, OSError) as exc:
                    raise ValueError("Upload streams must be seekable") from exc
                conn.send(header)
                remaining = upload.byte_size()
                while remaining:
                    chunk = upload.fileobj.read(min(self.chunk_size, remaining))
                    if not chunk:
                        raise ApiError("A recording ended before its declared upload size.")
                    if len(chunk) > remaining:
                        raise ApiError("A recording stream exceeded its declared upload size.")
                    conn.send(chunk)
                    remaining -= len(chunk)
                conn.send(b"\r\n")
            conn.send(closing)

            response = conn.getresponse()
            raw = self._read_limited(response, MAX_JSON_RESPONSE_BYTES)
            if not 200 <= response.status < 300:
                raise self._http_error(response.status, response.headers, raw)
            decoded = self._decode_json(raw)
            if not isinstance(decoded, dict):
                raise ApiError("The transcription service returned an unexpected response.")
            return decoded
        except ApiError:
            raise
        except (http.client.HTTPException, TimeoutError, OSError):
            raise ApiError(
                "The recording upload was interrupted. No transcript content was included in this error.",
                retryable=True,
            ) from None
        finally:
            for upload, position in zip(files, original_positions):
                if position is not None:
                    try:
                        upload.fileobj.seek(position)
                    except (AttributeError, OSError):
                        pass
            conn.close()

    # ---- Helpers -------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "transcription-v2-streamlit/0.1",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        headers["X-User-ID"] = self.user_id
        return headers

    def _url(self, path: str) -> str:
        parsed = urlsplit(self.base_url)
        base_path = parsed.path.rstrip("/")
        incoming = path if path.startswith("/") else "/" + path
        return urlunsplit((parsed.scheme, parsed.netloc, base_path + incoming, parsed.query, ""))

    @staticmethod
    def _id(value: str) -> str:
        if not str(value).strip():
            raise ValueError("Identifier cannot be blank")
        return quote(str(value).strip(), safe="")

    @staticmethod
    def _field_part(boundary: str, name: str, value: str) -> bytes:
        safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
        return (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{safe_name}"\r\n'
            "Content-Type: application/json; charset=utf-8\r\n\r\n"
        ).encode("ascii") + value.encode("utf-8") + b"\r\n"

    @staticmethod
    def _file_header(boundary: str, part: UploadPart) -> bytes:
        filename = part.normalized_filename()
        ascii_filename = filename.encode("ascii", errors="replace").decode("ascii")
        encoded_filename = quote(filename, safe="")
        return (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="files"; filename="{ascii_filename}"; '
            f"filename*=UTF-8''{encoded_filename}\r\n"
            f"Content-Type: {part.media_type()}\r\n\r\n"
        ).encode("ascii")

    @staticmethod
    def _read_limited(response: Any, limit: int) -> bytes:
        raw = response.read(limit + 1)
        if len(raw) > limit:
            raise ApiError("The transcription service returned an unexpectedly large response.")
        return raw

    @staticmethod
    def _decode_json(raw: bytes) -> Any:
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError("The transcription service returned an invalid JSON response.") from None

    @staticmethod
    def _safe_error_code(raw_or_response: Any) -> str | None:
        try:
            if hasattr(raw_or_response, "read"):
                raw = raw_or_response.read(64 * 1024)
            else:
                raw = bytes(raw_or_response)
            payload = json.loads(raw.decode("utf-8"))
            code = str(payload.get("code") or payload.get("error_code") or "")
            return code if re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", code) else None
        except Exception:
            return None

    @classmethod
    def _http_error(cls, status: int, headers: Any, raw_or_response: Any) -> ApiError:
        code = cls._safe_error_code(raw_or_response)
        request_id = None
        if headers:
            candidate = headers.get("X-Request-ID") or headers.get("X-Correlation-ID")
            if candidate and re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", str(candidate)):
                request_id = str(candidate)
        return ApiError.from_status(status, code=code, request_id=request_id)


__all__ = [
    "ApiClient",
    "ApiError",
    "UploadPart",
    "DEFAULT_BASE_URL",
    "DEFAULT_MAX_UPLOAD_BYTES",
    "DEFAULT_MAX_BATCH_UPLOAD_BYTES",
    "DEFAULT_MAX_FILES_PER_REQUEST",
]
