"""Reviewer-facing Streamlit UI for the isolated transcription service.

Streamlit is imported only inside :func:`main` so API-client tests and static
tooling do not require Streamlit to be installed.
"""

from __future__ import annotations

import html
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

from transcription_v2.settings import load_api_token_from_env

try:  # Works both as ``python -m ui.streamlit_app`` and ``streamlit run ui/...``.
    from .api_client import ApiClient, ApiError, UploadPart
except ImportError:  # pragma: no cover - exercised by Streamlit's script loader
    from api_client import ApiClient, ApiError, UploadPart


APP_TITLE = "Transcript Studio"
MIB = 1024**2
DEFAULT_MAX_UPLOAD_BYTES = 5 * 1024**3
DEFAULT_MAX_REQUEST_BYTES = 5 * 1024**3
DEFAULT_MAX_FILES = 100
COMPACT_BATCH_THRESHOLD = 12
MACHINE_WARNING = (
    "AI-generated transcript — no manual review is required to download it. "
    "Verify critical quotations or speaker identity before relying on them."
)

ALL_LANGUAGES = {
    "Auto-detect (recommended)": None,
    "Afrikaans": "af",
    "Albanian": "sq",
    "Amharic": "am",
    "Arabic": "ar",
    "Armenian": "hy",
    "Assamese": "as",
    "Azerbaijani": "az",
    "Bashkir": "ba",
    "Basque": "eu",
    "Belarusian": "be",
    "Bengali": "bn",
    "Bosnian": "bs",
    "Breton": "br",
    "Bulgarian": "bg",
    "Burmese": "my",
    "Cantonese": "yue",
    "Catalan": "ca",
    "Chinese": "zh",
    "Croatian": "hr",
    "Czech": "cs",
    "Danish": "da",
    "Dutch": "nl",
    "English": "en",
    "Estonian": "et",
    "Faroese": "fo",
    "Finnish": "fi",
    "French": "fr",
    "Galician": "gl",
    "Georgian": "ka",
    "German": "de",
    "Greek": "el",
    "Gujarati": "gu",
    "Haitian Creole": "ht",
    "Hausa": "ha",
    "Hawaiian": "haw",
    "Hebrew": "he",
    "Hindi": "hi",
    "Hungarian": "hu",
    "Icelandic": "is",
    "Indonesian": "id",
    "Italian": "it",
    "Japanese": "ja",
    "Javanese": "jw",
    "Kannada": "kn",
    "Kazakh": "kk",
    "Khmer": "km",
    "Korean": "ko",
    "Lao": "lo",
    "Latin": "la",
    "Latvian": "lv",
    "Lingala": "ln",
    "Lithuanian": "lt",
    "Luxembourgish": "lb",
    "Macedonian": "mk",
    "Malagasy": "mg",
    "Malay": "ms",
    "Malayalam": "ml",
    "Maltese": "mt",
    "Maori": "mi",
    "Marathi": "mr",
    "Mongolian": "mn",
    "Nepali": "ne",
    "Norwegian": "no",
    "Nynorsk": "nn",
    "Occitan": "oc",
    "Pashto": "ps",
    "Persian": "fa",
    "Polish": "pl",
    "Portuguese": "pt",
    "Punjabi": "pa",
    "Romanian": "ro",
    "Russian": "ru",
    "Sanskrit": "sa",
    "Serbian": "sr",
    "Shona": "sn",
    "Sindhi": "sd",
    "Sinhala": "si",
    "Slovak": "sk",
    "Slovenian": "sl",
    "Somali": "so",
    "Spanish": "es",
    "Sundanese": "su",
    "Swahili": "sw",
    "Swedish": "sv",
    "Tagalog": "tl",
    "Tajik": "tg",
    "Tamil": "ta",
    "Tatar": "tt",
    "Telugu": "te",
    "Thai": "th",
    "Tibetan": "bo",
    "Turkish": "tr",
    "Turkmen": "tk",
    "Ukrainian": "uk",
    "Urdu": "ur",
    "Uzbek": "uz",
    "Vietnamese": "vi",
    "Welsh": "cy",
    "Yiddish": "yi",
    "Yoruba": "yo",
}


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_positive_int(name: str, default: int) -> int:
    """Read a positive UI limit without making malformed config fatal."""

    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _upload_limits() -> tuple[int, int, int]:
    """Return per-file bytes, aggregate bytes, and the technical part ceiling."""

    per_file = _env_positive_int(
        "TRANSCRIPTION_V2_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES
    )
    per_request = _env_positive_int(
        "TRANSCRIPTION_V2_MAX_BATCH_UPLOAD_BYTES",
        _env_positive_int(
            "TRANSCRIPTION_V2_MAX_REQUEST_BYTES", DEFAULT_MAX_REQUEST_BYTES
        ),
    )
    max_files = _env_positive_int("TRANSCRIPTION_V2_MAX_FILES", DEFAULT_MAX_FILES)
    return per_file, per_request, max_files


def _default_profile_index(profiles: dict[str, str]) -> int:
    """Prefer the highest-accuracy profile and fall back deterministically."""

    names = list(profiles)
    return names.index("Highest accuracy") if "Highest accuracy" in profiles else 0


def _selected_upload_size(uploaded: Any) -> int | None:
    size = getattr(uploaded, "size", None)
    if isinstance(size, int) and not isinstance(size, bool) and size >= 0:
        return size
    try:
        original = uploaded.tell()
        uploaded.seek(0, os.SEEK_END)
        size = uploaded.tell()
        uploaded.seek(original, os.SEEK_SET)
    except (AttributeError, OSError, ValueError):
        return None
    return int(size) if isinstance(size, int) and size >= 0 else None


def _upload_selection_error(
    files: Iterable[Any],
    *,
    max_file_bytes: int,
    max_request_bytes: int,
    max_files: int,
) -> str | None:
    """Return a staff-safe preflight error for an oversized selection."""

    selected = list(files)
    sizes = [_selected_upload_size(item) for item in selected]
    if any(size is None for size in sizes):
        return "One selected recording did not report a usable file size. Select it again."
    known_sizes = [int(size) for size in sizes if size is not None]
    if any(size > max_file_bytes for size in known_sizes):
        return f"Each recording must be {_format_bytes(max_file_bytes)} or smaller."
    if sum(known_sizes) > max_request_bytes:
        return (
            "The selected recordings exceed the combined upload limit of "
            f"{_format_bytes(max_request_bytes)}. Submit them in smaller groups."
        )
    if len(selected) > max_files:
        return (
            "This unusually large selection exceeds the service safety limit. "
            "Split it into two uploads."
        )
    return None


def _upload_widget_key(form_generation: int) -> str:
    """Tie retained browser uploads to the current submission generation."""

    return f"new-transcription-files-{form_generation}"


def _upload_selection_summary(files: Iterable[Any]) -> str | None:
    """Return a live count and aggregate size for the current selection."""

    selected = list(files)
    if not selected:
        return None
    sizes = [_selected_upload_size(item) for item in selected]
    summary = f"Selected: {len(selected)} recording(s)"
    if all(size is not None for size in sizes):
        total = sum(int(size) for size in sizes if size is not None)
        return f"{summary} · {_format_bytes(total)} total"
    return f"{summary} · total size unavailable"


def _available_languages() -> dict[str, str | None]:
    """Return only languages whose local alignment models are approved."""

    configured = os.getenv(
        "TRANSCRIPTION_V2_LANGUAGE_CODES",
        "auto,en,es",
    )
    allowed = {
        value.strip().lower()
        for value in configured.split(",")
        if value.strip()
    }
    available = {
        label: code
        for label, code in ALL_LANGUAGES.items()
        if ("auto" if code is None else code) in allowed
    }
    # A malformed operator value must never leave the form without a choice.
    return available or {"English": "en"}

ALL_PROFILES = {
    "Fast": "fast",
    "Balanced": "balanced",
    "Highest accuracy": "high_accuracy",
}


def _available_profiles() -> dict[str, str]:
    """Hide profiles whose exact offline model artifacts are not staged."""

    configured = os.getenv(
        "TRANSCRIPTION_V2_PROFILE_NAMES",
        "balanced,high_accuracy",
    )
    allowed = {
        value.strip().lower()
        for value in configured.split(",")
        if value.strip()
    }
    available = {
        label: name for label, name in ALL_PROFILES.items() if name in allowed
    }
    return available or {"Balanced": "balanced"}

RECORDING_TYPES = {
    "General recording": "general",
    "Interview": "interview",
    "Body-worn camera": "body_camera",
    "Jail call": "jail_call",
    "Telephone call": "telephone",
    "Hearing or courtroom": "court",
    "Meeting": "meeting",
    "Other": "other",
}

STATUS_LABELS = {
    "created": "Preparing",
    "queued": "Queued",
    "preparing": "Preparing",
    "running": "In progress",
    "transcribing": "Transcribing",
    "aligning": "Aligning timestamps",
    "diarizing": "Separating speakers",
    "review_ready": "Ready to download",
    "completed": "Completed",
    "succeeded": "Ready for delivery",
    "degraded": "Completed with warnings",
    "failed": "Failed",
    "canceling": "Canceling",
    "cancel_requested": "Cancel requested",
    "canceled": "Canceled",
    "processing": "Processing recordings",
    "ready": "Ready to download",
}

ACTIVE_STATUSES = {"created", "queued", "preparing", "running", "transcribing", "aligning", "diarizing", "canceling", "cancel_requested"}
DELIVERY_STATUSES = {"review_ready", "completed", "succeeded", "degraded"}
WORKSPACE_PAGES = ("Transcribe", "Jobs & downloads")
LEGACY_WORKSPACE_PAGES = {
    "New job": "Transcribe",
    "Active delivery queue": "Jobs & downloads",
}


def _markdown_text(value: Any) -> str:
    """Escape untrusted short text before passing it to Markdown widgets."""

    text = " ".join(str(value or "").splitlines())
    return re.sub(r"([\\`*{}\[\]()<>#+\-.!_|>])", r"\\\1", text)


def _format_seconds(value: Any) -> str:
    try:
        seconds = max(0, int(float(value)))
    except (TypeError, ValueError):
        return "Not available"
    if seconds < 60:
        return f"{seconds} sec"
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    return f"{hours} hr {minutes} min" if hours else f"{minutes} min"


def _format_timestamp(value: Any) -> str:
    try:
        seconds = max(0.0, float(value))
    except (TypeError, ValueError):
        seconds = 0.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _segment_seconds(segment: dict[str, Any], edge: str) -> float:
    value = segment.get(edge)
    if value is not None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
    try:
        return float(segment.get(f"{edge}_ms") or 0) / 1000.0
    except (TypeError, ValueError):
        return 0.0


def _segment_text(segment: dict[str, Any]) -> str:
    value = segment.get("text")
    if value is None:
        value = segment.get("edited_text")
    if value is None:
        value = segment.get("model_text")
    return str(value or "")


def _format_bytes(value: Any) -> str:
    try:
        amount = max(0.0, float(value))
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return ""


def _format_date(value: Any) -> str:
    if not value:
        return "Not available"
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%b %d, %Y at %I:%M %p")
    except (ValueError, OSError):
        return text[:40]


def _expiry_text(value: Any) -> str:
    if not value:
        return "Automatic deletion time is pending"
    try:
        expires = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        remaining = int((expires - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OSError):
        return f"Scheduled for automatic deletion: {_format_date(value)}"
    if remaining <= 0:
        return "Automatic deletion is due now"
    hours, remainder = divmod(remaining, 3600)
    minutes = max(1, remainder // 60)
    if hours >= 48:
        days, extra_hours = divmod(hours, 24)
        return f"Auto-deletes in {days} days {extra_hours} hr"
    if hours:
        return f"Auto-deletes in {hours} hr {minutes} min"
    return f"Auto-deletes in {minutes} min"


def _job_expiry(job: dict[str, Any]) -> Any:
    return job.get("delete_at") or job.get("expires_at")


def _accepted_job_ids(payload: dict[str, Any]) -> list[str]:
    accepted = payload.get("jobs") if isinstance(payload.get("jobs"), list) else None
    if accepted is None and isinstance(payload.get("job"), dict):
        accepted = [payload["job"]]
    if accepted is None:
        accepted = [payload]
    job_ids = [str(item.get("id") or item.get("job_id") or "") for item in accepted if isinstance(item, dict)]
    return [value for value in job_ids if value]


def _status(job: dict[str, Any]) -> str:
    return str(job.get("status") or "unknown").strip().lower()


def _stage(job: dict[str, Any]) -> tuple[str, str, float | None]:
    stage = job.get("stage")
    if isinstance(stage, dict):
        code = str(stage.get("code") or _status(job))
        label = str(stage.get("label") or STATUS_LABELS.get(code, code.replace("_", " ").title()))
        progress = stage.get("progress", job.get("progress"))
    else:
        code = str(stage or _status(job))
        label = {
            "ingest": "Receiving recording",
            "probe": "Checking media",
            "transcribe": "Transcribing",
            "align": "Aligning timestamps",
            "diarize": "Separating speakers",
            "identify": "Preparing speaker suggestions",
            "translate": "Creating English translation",
            "quality_control": "Checking quality",
            "export": "Building delivery files",
        }.get(code, STATUS_LABELS.get(code, code.replace("_", " ").title()))
        progress = job.get("progress")
    try:
        normalized = max(0.0, min(1.0, float(progress))) if progress is not None else None
    except (TypeError, ValueError):
        normalized = None
    return code, label, normalized


def _user_message(container: dict[str, Any]) -> str | None:
    """Return only the API field explicitly designated safe for staff display."""
    value = container.get("user_message")
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.replace("\x00", "").split())
    return cleaned[:600] or None


def _split_terms(value: str) -> list[str]:
    terms = []
    for line in value.replace(",", "\n").splitlines():
        cleaned = line.strip()
        if cleaned and cleaned not in terms:
            terms.append(cleaned)
    return terms[:500]


def _speaker_for(segment: dict[str, Any]) -> dict[str, Any]:
    speaker = segment.get("speaker")
    if isinstance(speaker, dict):
        cluster_id = str(speaker.get("cluster_id") or speaker.get("id") or "UNKNOWN")
        state = str(speaker.get("identity_state") or speaker.get("identity_status") or "cluster").lower()
        suggested_name = str(speaker.get("suggested_name") or "").strip()
        if state == "suggested" and not suggested_name:
            suggested_name = str(speaker.get("display_name") or "").strip()
        return {
            "cluster_id": cluster_id,
            "display_name": str(speaker.get("display_name") or cluster_id),
            "identity_state": state if state in {"cluster", "suggested", "confirmed"} else "cluster",
            "suggested_name": suggested_name,
            "suggestion_basis": str(speaker.get("suggestion_basis") or "").strip(),
            "revision": int(speaker.get("revision") or 0),
        }
    label = str(speaker or segment.get("speaker_key") or segment.get("speaker_id") or "UNKNOWN")
    return {
        "cluster_id": label,
        "display_name": label,
        "identity_state": "cluster",
        "suggested_name": "",
        "suggestion_basis": "",
        "revision": 0,
    }


def _identity_label(state: str) -> str:
    return {
        "confirmed": "Confirmed by staff",
        "suggested": "Suggested identity — not confirmed",
        "cluster": "Voice cluster — identity unknown",
    }.get(state, "Voice cluster — identity unknown")


def _load_styles(st: Any) -> None:
    css_path = Path(__file__).with_name("styles.css")
    if css_path.exists():
        st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def _get_client(st: Any) -> ApiClient:
    cache_key = "_transcription_v2_api_client"
    configured_url = os.getenv("TRANSCRIPTION_V2_API_URL", "http://127.0.0.1:8510")
    try:
        configured_token = load_api_token_from_env()
    except ValueError:
        st.error("The local service credential is not configured safely.")
        st.stop()
    fallback_user = os.getenv("TRANSCRIPTION_V2_USER_ID", "").strip()
    trusted_header = os.getenv(
        "TRANSCRIPTION_V2_TRUSTED_USER_HEADER", "X-Authenticated-User"
    ).strip()
    trusted_user = ""
    if trusted_header:
        try:
            trusted_user = str(st.context.headers.get(trusted_header) or "").strip()
        except (AttributeError, KeyError, TypeError):
            trusted_user = ""
    require_user_header = os.getenv("TRANSCRIPTION_V2_REQUIRE_USER_HEADER", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not trusted_user and require_user_header:
        st.error("Authenticated staff identity was not supplied by the trusted proxy.")
        st.stop()
    # A server-controlled proxy identity is authoritative whenever present.
    # TRANSCRIPTION_V2_USER_ID is only a loopback-development fallback and
    # cannot override an authenticated staff identity.
    configured_user = trusted_user or fallback_user or "local-reviewer"
    fingerprint = (configured_url, bool(configured_token), configured_user)
    if st.session_state.get("_api_fingerprint") != fingerprint:
        st.session_state[cache_key] = ApiClient(configured_url, configured_token, user_id=configured_user)
        st.session_state["_api_fingerprint"] = fingerprint
    return st.session_state[cache_key]


def _browser_delivery_url(st: Any, client: ApiClient, value: Any) -> str | None:
    """Make a signed relative path usable by browser-native media controls."""

    try:
        browser_origin = st.context.url
    except (AttributeError, RuntimeError, TypeError):
        browser_origin = None
    resolved = client.resolve_url(
        str(value) if value else None,
        browser_origin=browser_origin,
    )
    if not resolved:
        return None
    parsed = urlsplit(resolved)
    # Browser-native media widgets require an absolute URL. Fail closed when
    # there is no request context instead of letting Streamlit reinterpret a
    # root-relative signed path as a server-local filename.
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return resolved


def _set_selected_job(st: Any, job_id: str) -> None:
    st.session_state.pop("selected_batch_id", None)
    st.session_state.pop("_selected_batch_auto_refresh", None)
    st.query_params.pop("batch", None)
    st.session_state["selected_job_id"] = job_id
    st.session_state["_selected_job_auto_refresh"] = True
    st.query_params["job"] = job_id


def _set_selected_batch(st: Any, batch_id: str) -> None:
    """Open a submitted group as one live delivery workflow."""

    st.session_state.pop("selected_job_id", None)
    st.session_state.pop("_selected_job_auto_refresh", None)
    st.query_params.pop("job", None)
    st.session_state["selected_batch_id"] = batch_id
    st.session_state["_selected_batch_auto_refresh"] = True
    st.query_params["batch"] = batch_id


def _start_another_transcription(st: Any) -> None:
    """Return to a fresh upload form without retaining a delivery selection."""

    for key in (
        "selected_job_id",
        "selected_batch_id",
        "submitted_job_ids",
        "_selected_job_auto_refresh",
        "_selected_batch_auto_refresh",
        "_new_job_submission_notice",
    ):
        st.session_state.pop(key, None)
    st.query_params.pop("job", None)
    st.query_params.pop("batch", None)
    st.session_state["_workspace_redirect"] = "Transcribe"
    st.session_state["_new_job_form_generation"] = (
        int(st.session_state.get("_new_job_form_generation", 0)) + 1
    )


def _render_start_another_action(st: Any, *, key: str) -> None:
    if st.button(
        "← Transcribe more recordings",
        key=key,
        type="secondary",
        use_container_width=True,
    ):
        _start_another_transcription(st)
        st.rerun()


def _record_successful_submission(
    st: Any,
    job_ids: list[str],
    rejected_count: int,
    form_generation: int,
    batch_id: str | None = None,
) -> None:
    """Remember accepted work and route the next run to its live status."""

    if batch_id:
        _set_selected_batch(st, batch_id)
    else:
        _set_selected_job(st, job_ids[0])
    st.session_state["submitted_job_ids"] = job_ids
    st.session_state["_new_job_submission_notice"] = {
        "job_ids": job_ids,
        "rejected_count": rejected_count,
        "batch_id": batch_id,
    }
    # The workspace radio already exists during submission, so its widget key
    # cannot safely be changed until the next full app run.
    st.session_state["_workspace_redirect"] = "Jobs & downloads"
    # Changing the form key on the next run discards UploadedFile objects and
    # prior choices only after the API confirms acceptance.
    st.session_state["_new_job_form_generation"] = form_generation + 1


def _apply_workspace_redirect(st: Any) -> str | None:
    """Apply a pending route before the keyed sidebar radio is instantiated."""

    current = st.session_state.get("workspace_page")
    if current in LEGACY_WORKSPACE_PAGES:
        st.session_state["workspace_page"] = LEGACY_WORKSPACE_PAGES[current]
    destination = st.session_state.pop("_workspace_redirect", None)
    destination = LEGACY_WORKSPACE_PAGES.get(destination, destination)
    if destination in WORKSPACE_PAGES:
        st.session_state["workspace_page"] = destination
        return destination
    return None


def _render_submission_notice(st: Any) -> None:
    notice = st.session_state.pop("_new_job_submission_notice", None)
    if not isinstance(notice, dict):
        return

    job_ids = [str(value) for value in notice.get("job_ids", []) if value]
    rejected_count = int(notice.get("rejected_count") or 0)
    batch_id = str(notice.get("batch_id") or "")
    noun = "recording" if len(job_ids) == 1 else "recordings in one batch"
    st.success(
        f"Created {len(job_ids)} {noun}. Processing has started, and the current "
        "status is shown below."
    )
    if rejected_count:
        st.warning(
            f"{rejected_count} selected file(s) were not accepted. "
            "This can happen because of file size, media format, or current service "
            "capacity. The accepted recordings will continue below; select the others "
            "again after checking the files or when capacity is available."
        )
    if job_ids and not batch_id:
        st.caption(
            "Job reference" + ("s: " if len(job_ids) > 1 else ": ")
            + ", ".join(job_ids)
        )


def _render_sidebar(st: Any, client: ApiClient) -> str:
    st.sidebar.markdown("### Transcript Studio")
    st.sidebar.caption("Upload, process, and download")
    page = st.sidebar.radio("Workspace", WORKSPACE_PAGES, key="workspace_page")
    st.sidebar.divider()
    if st.sidebar.button("Check service status", use_container_width=True):
        try:
            health = client.readiness()
            health_status = str(health.get("status", "")).lower()
            if health_status == "ready":
                st.sidebar.success(
                    "Upload checks passed. Processing may still wait for the worker."
                )
            elif health_status == "degraded_ready":
                st.sidebar.warning(
                    "Transcription is ready; speaker diarization is temporarily unavailable."
                )
            else:
                st.sidebar.warning("Service responded but is not ready for new work")
        except ApiError as exc:
            st.sidebar.error(str(exc))

    return page


def _render_new_job(st: Any, client: ApiClient) -> None:
    st.header("Transcribe recordings")
    st.markdown(
        '<p class="page-lede">Upload audio or video for local processing. '
        "Finished files remain available only for the temporary delivery window.</p>",
        unsafe_allow_html=True,
    )

    max_file_bytes, max_request_bytes, max_files = _upload_limits()
    max_upload_mib = max(1, (max_file_bytes + MIB - 1) // MIB)

    form_generation = int(st.session_state.get("_new_job_form_generation", 0))
    files = st.file_uploader(
        "Choose recordings",
        type=["mp3", "wav", "m4a", "flac", "ogg", "opus", "wma", "mp4", "mkv", "avi", "mov", "wmv", "webm"],
        accept_multiple_files=True,
        max_upload_size=max_upload_mib,
        key=_upload_widget_key(form_generation),
        help=(
            "Choose as many audio or video recordings as fit within "
            f"{_format_bytes(max_request_bytes)} total. No single file can exceed "
            f"{_format_bytes(max_file_bytes)}."
        ),
    )
    st.caption(
        "Audio or video · select as many recordings as fit within "
        f"{_format_bytes(max_request_bytes)} total · "
        f"up to {_format_bytes(max_file_bytes)} per file"
    )
    selection_error = None
    selection_summary = _upload_selection_summary(files or [])
    if selection_summary:
        st.caption(selection_summary)
        selection_error = _upload_selection_error(
            files,
            max_file_bytes=max_file_bytes,
            max_request_bytes=max_request_bytes,
            max_files=max_files,
        )
        if selection_error:
            st.error(selection_error)

    with st.form(f"new-transcription-job-{form_generation}", clear_on_submit=False):
        st.markdown("#### Processing options")
        profiles = _available_profiles()
        profile_col, type_col = st.columns(2)
        with profile_col:
            profile_label = st.selectbox(
                "Accuracy",
                tuple(profiles),
                index=_default_profile_index(profiles),
                help="Highest accuracy uses a wider decoding search and may take longer.",
            )
        with type_col:
            recording_label = st.selectbox("Recording type", tuple(RECORDING_TYPES), index=0)

        languages = _available_languages()
        translation_enabled = _env_flag(
            "TRANSCRIPTION_V2_ENABLE_TRANSLATION", default=True
        )
        language_col, translation_col = st.columns(2)
        with language_col:
            language_label = st.selectbox(
                "Spoken language",
                tuple(languages),
                index=0,
                help="Only languages with approved local alignment models are shown.",
            )
        with translation_col:
            translate = st.checkbox(
                "Create an English translation",
                value=False,
                disabled=not translation_enabled,
                help="The source-language transcript is preserved; English is an additional output.",
            )

        diarize_speakers = st.toggle(
            "Separate speakers",
            value=True,
            help=(
                "Creates anonymous voice clusters and speaker-labelled transcript lines. "
                "Turn this off when speaker labels are not needed."
            ),
        )
        st.caption(
            "Speaker separation creates anonymous voice clusters; it does not identify a person."
        )

        with st.expander("Advanced options"):
            min_col, max_col = st.columns(2)
            with min_col:
                min_speakers = st.number_input(
                    "Minimum speakers (0 = estimate)",
                    min_value=0,
                    max_value=100,
                    value=0,
                    step=1,
                    disabled=not diarize_speakers,
                )
            with max_col:
                max_speakers = st.number_input(
                    "Maximum speakers (0 = estimate)",
                    min_value=0,
                    max_value=100,
                    value=0,
                    step=1,
                    disabled=not diarize_speakers,
                )

            roster = st.text_area(
                "Possible speaker roster (optional)",
                placeholder="Synthetic examples:\nSpeaker Alpha\nInterpreter\nFacilitator",
                help="Used only as unconfirmed suggestions when speaker separation is enabled.",
                disabled=not diarize_speakers,
            )
            glossary = st.text_area(
                "Glossary (optional)",
                placeholder="Synthetic examples:\nProject LANTERN\nSpeaker Delta\nAsset code VX-204",
                help="Include project names, places, acronyms, and uncommon terminology.",
            )
            hotwords = st.text_area(
                "Recognition hotwords (optional)",
                placeholder="One especially important spoken name or term per line",
                help="Use sparingly for terms the speech recognizer should favor.",
            )

        retention_label = st.selectbox(
            "Temporary delivery window",
            ("4 hours", "8 hours", "24 hours"),
            index=0,
            help="This is a maximum, not an archive period. Organization policy may shorten it.",
        )
        submitted = st.form_submit_button(
            "Start transcription",
            type="primary",
            disabled=selection_error is not None,
            use_container_width=True,
        )
        st.caption(
            "When complete, the ZIP contains Word, plain-text, subtitle, and provenance files for each recording."
        )

    if not submitted:
        return
    if not files:
        st.error("Choose at least one recording before creating the job.")
        return
    selection_error = _upload_selection_error(
        files,
        max_file_bytes=max_file_bytes,
        max_request_bytes=max_request_bytes,
        max_files=max_files,
    )
    if selection_error:
        st.error(selection_error)
        return
    if (
        diarize_speakers
        and min_speakers
        and max_speakers
        and min_speakers > max_speakers
    ):
        st.error("Minimum speakers cannot be greater than maximum speakers.")
        return

    retention_hours = {"4 hours": 4, "8 hours": 8, "24 hours": 24}[retention_label]
    options = {
        "profile": profiles[profile_label],
        "recording_type": RECORDING_TYPES[recording_label],
        "source_language": languages[language_label] or "auto",
        "translate_to_english": bool(translate),
        "diarize_speakers": bool(diarize_speakers),
        "min_speakers": (int(min_speakers) or None) if diarize_speakers else None,
        "max_speakers": (int(max_speakers) or None) if diarize_speakers else None,
        "roster": _split_terms(roster) if diarize_speakers else [],
        "hotwords": _split_terms(hotwords),
        "glossary": _split_terms(glossary),
        "retention_hours": retention_hours,
    }
    parts = [
        UploadPart(
            filename=uploaded.name,
            fileobj=uploaded,
            size=getattr(uploaded, "size", None),
            content_type=getattr(uploaded, "type", None),
        )
        for uploaded in files
    ]
    try:
        with st.spinner("Streaming recordings to the local transcription service…"):
            job = client.submit_job(parts, options)
        job_ids = _accepted_job_ids(job)
        if not job_ids:
            raise ApiError("The service accepted the upload but did not return a job identifier.")
        rejected = job.get("rejected") if isinstance(job, dict) else None
        _record_successful_submission(
            st,
            job_ids,
            len(rejected) if isinstance(rejected, list) else 0,
            form_generation,
            str(job.get("batch_id") or "") or None,
        )
        st.rerun()
    except ApiError as exc:
        st.error(str(exc))
        st.caption("Check service status or ask the installation administrator for help.")


def _render_status_chip(st: Any, status: str) -> None:
    label = STATUS_LABELS.get(status, status.replace("_", " ").title())
    tone = (
        "danger"
        if status == "failed"
        else "warning"
        if status in {"degraded", "canceled"}
        else "success"
        if status in DELIVERY_STATUSES or status == "ready"
        else "active"
    )
    st.markdown(
        f'<span class="status-chip status-{tone}">{html.escape(label)}</span>',
        unsafe_allow_html=True,
    )


def _render_job_summary(st: Any, job: dict[str, Any], client: ApiClient) -> None:
    job_id = str(job.get("id") or job.get("job_id") or "")
    status = _status(job)
    _, stage_label, progress = _stage(job)
    with st.container(border=True):
        title_col, status_col = st.columns([4, 1])
        with title_col:
            title = str(job.get("display_name") or job.get("primary_filename") or "Transcription job")
            st.markdown(f"**{_markdown_text(title)}**")
            st.caption(f"Created {_format_date(job.get('created_at'))} · Job {job_id}")
            st.caption(_expiry_text(_job_expiry(job)))
        with status_col:
            _render_status_chip(st, status)
        if progress is not None:
            st.progress(progress, text=stage_label)
        else:
            st.caption(f"Current stage: {stage_label}")
        queue_position = job.get("queue_position")
        eta = job.get("eta_seconds")
        if queue_position or eta:
            details = []
            if queue_position:
                details.append(f"Queue position {queue_position}")
            if eta:
                details.append(f"Estimated wait {_format_seconds(eta)}")
            st.caption(" · ".join(details))
        safe_message = _user_message(job)
        if status == "failed":
            st.error(safe_message or "This job failed before transcript files were produced.")
        elif status == "degraded" or job.get("degraded"):
            st.warning(safe_message or "A transcript was produced, but one or more requested stages were unavailable. Downloads are still available.")
        action_cols = st.columns([2, 1, 1])
        with action_cols[0]:
            action_label = "Open downloads" if status in DELIVERY_STATUSES else "Open job status"
            if st.button(action_label, key=f"open-{job_id}", use_container_width=True):
                _set_selected_job(st, job_id)
                st.rerun()
        with action_cols[1]:
            if status in ACTIVE_STATUSES and st.button("Cancel", key=f"cancel-{job_id}", use_container_width=True):
                try:
                    client.cancel_job(job_id)
                    st.rerun()
                except ApiError as exc:
                    st.error(str(exc))
        with action_cols[2]:
            if status in {"failed", "canceled"} and st.button("Retry", key=f"retry-{job_id}", use_container_width=True):
                try:
                    retried = client.retry_job(job_id)
                    next_id = str(retried.get("id") or retried.get("job_id") or job_id)
                    _set_selected_job(st, next_id)
                    st.rerun()
                except ApiError as exc:
                    st.error(str(exc))


def _group_queue_jobs(
    jobs: Iterable[dict[str, Any]],
    *,
    exclude_batch_id: str = "",
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Keep persisted multi-file submissions recoverable as one queue item."""

    batches: dict[str, list[dict[str, Any]]] = {}
    singles: list[dict[str, Any]] = []
    for job in jobs:
        batch_id = str(job.get("batch_id") or "")
        if batch_id:
            if batch_id != exclude_batch_id:
                batches.setdefault(batch_id, []).append(job)
        else:
            singles.append(job)
    return batches, singles


def _render_batch_queue_summary(
    st: Any,
    batch_id: str,
    jobs: list[dict[str, Any]],
) -> None:
    statuses = [_status(job) for job in jobs]
    is_active = any(status in ACTIVE_STATUSES for status in statuses)
    ready_count = sum(status in DELIVERY_STATUSES for status in statuses)
    failed_count = sum(status in {"failed", "canceled"} for status in statuses)
    batch_status = "processing" if is_active else "ready" if ready_count else "failed"
    progress_values = [
        progress
        for job in jobs
        for progress in [_stage(job)[2]]
        if progress is not None
    ]
    with st.container(border=True):
        title_col, status_col = st.columns([4, 1])
        with title_col:
            st.markdown(f"**Combined batch · {len(jobs)} recordings**")
            names = [
                str(job.get("display_name") or job.get("primary_filename") or "Recording")
                for job in jobs[:3]
            ]
            summary = " · ".join(_markdown_text(name) for name in names)
            if len(jobs) > len(names):
                summary += f" · +{len(jobs) - len(names)} more"
            st.caption(summary)
        with status_col:
            _render_status_chip(st, batch_status)
        if progress_values and is_active:
            st.progress(
                sum(progress_values) / len(jobs),
                text=f"{ready_count + failed_count} of {len(jobs)} recordings finished",
            )
        if failed_count and ready_count:
            st.caption(
                f"{ready_count} ready · {failed_count} not completed; the combined ZIP will include successful recordings."
            )
        label = "Open combined download" if batch_status == "ready" else "Open batch progress"
        if st.button(
            label,
            key=f"open-batch-{batch_id}",
            type="primary" if batch_status == "ready" else "secondary",
            use_container_width=True,
        ):
            _set_selected_batch(st, batch_id)
            st.rerun()


def _render_jobs(st: Any, client: ApiClient) -> None:
    st.header("Temporary queue")
    _render_submission_notice(st)
    lifecycle_notice = st.session_state.pop("_lifecycle_notice", None)
    if isinstance(lifecycle_notice, tuple) and len(lifecycle_notice) == 2:
        tone, message = lifecycle_notice
        (st.success if tone == "success" else st.warning)(message)
    refresh_col, hint_col = st.columns([1, 4])
    with refresh_col:
        if st.button("Refresh status now", type="primary", use_container_width=True):
            st.rerun()
    with hint_col:
        st.caption(
            "The open job or batch updates automatically about every 5 seconds while "
            "it is processing. Refresh status now also updates the full queue."
        )
        st.caption(
            "Items disappear automatically after their short delivery window; "
            "this is not an archive."
        )

    try:
        jobs = client.list_jobs(limit=100)
    except ApiError as exc:
        st.error(str(exc))
        jobs = []

    selected_batch_id = str(
        st.session_state.get("selected_batch_id")
        or st.query_params.get("batch")
        or ""
    )
    selected_id = str(
        st.session_state.get("selected_job_id")
        or st.query_params.get("job")
        or ""
    )
    if selected_batch_id:
        st.session_state["selected_batch_id"] = selected_batch_id
        st.query_params["batch"] = selected_batch_id
        _render_selected_batch_with_refresh(st, client, selected_batch_id)
        st.divider()
    elif selected_id:
        st.session_state["selected_job_id"] = selected_id
        st.query_params["job"] = selected_id
        _render_selected_job_with_refresh(st, client, selected_id)
        st.divider()

    batch_groups, individual_jobs = _group_queue_jobs(
        jobs,
        exclude_batch_id=selected_batch_id,
    )
    st.subheader("Other temporary jobs" if selected_batch_id else "Available for delivery")
    if not batch_groups and not individual_jobs:
        if selected_batch_id:
            st.caption("No other temporary jobs are waiting for delivery.")
            return
        st.info("No temporary jobs are currently available. Expired or deleted items cannot be recovered here.")
        return
    for batch_id, batch_jobs in batch_groups.items():
        _render_batch_queue_summary(st, batch_id, batch_jobs)
    for job in individual_jobs:
        _render_job_summary(st, job, client)


def _batch_progress(batch: dict[str, Any]) -> float | None:
    jobs = batch.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        return None
    progress_values: list[float] = []
    for item in jobs:
        if not isinstance(item, dict):
            continue
        status = _status(item)
        if status in DELIVERY_STATUSES or status in {"failed", "canceled"}:
            progress_values.append(1.0)
            continue
        _, _, progress = _stage(item)
        if progress is not None:
            progress_values.append(progress)
    return sum(progress_values) / len(jobs) if progress_values else None


def _use_compact_batch_layout(jobs: Iterable[Any]) -> bool:
    """Keep large submissions readable without changing small-batch controls."""

    return sum(isinstance(item, dict) for item in jobs) > COMPACT_BATCH_THRESHOLD


def _batch_recording_title(item: dict[str, Any], index: int) -> str:
    value = item.get("primary_filename") or f"Recording {index + 1}"
    return " ".join(str(value).replace("\x00", "").splitlines())[:240]


def _compact_batch_rows(jobs: Iterable[Any]) -> list[dict[str, Any]]:
    """Project a large batch into a compact, content-safe progress table."""

    rows: list[dict[str, Any]] = []
    for index, item in enumerate(jobs):
        if not isinstance(item, dict):
            continue
        item_status = _status(item)
        _, stage_label, item_progress = _stage(item)
        status_label = STATUS_LABELS.get(
            item_status,
            item_status.replace("_", " ").title(),
        )
        if item_status in ACTIVE_STATUSES and item_status not in {
            "created",
            "queued",
            "canceling",
            "cancel_requested",
        }:
            status_label = stage_label
        if item_status in DELIVERY_STATUSES or item_status in {"failed", "canceled"}:
            progress_percent: int | None = 100
        elif item_progress is None:
            progress_percent = None
        else:
            progress_percent = int(round(item_progress * 100))
        rows.append(
            {
                "Recording": _batch_recording_title(item, index),
                "Status": status_label,
                "Progress": progress_percent,
            }
        )
    return rows


def _batch_action_options(
    jobs: Iterable[Any],
    statuses: set[str],
) -> list[tuple[str, str]]:
    """Return stable job IDs and readable labels for one scoped batch action."""

    options: list[tuple[str, str]] = []
    for index, item in enumerate(jobs):
        if not isinstance(item, dict) or _status(item) not in statuses:
            continue
        item_id = str(item.get("job_id") or item.get("id") or "")
        if item_id:
            options.append((item_id, f"{index + 1}. {_batch_recording_title(item, index)}"))
    return options


def _render_batch_recording_cards(
    st: Any,
    client: ApiClient,
    jobs: Iterable[Any],
) -> None:
    """Render the established detailed controls for ordinary-sized batches."""

    for index, item in enumerate(jobs):
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("job_id") or item.get("id") or "")
        item_status = _status(item)
        _, stage_label, item_progress = _stage(item)
        with st.container(border=True):
            title_col, status_col = st.columns([4, 1])
            with title_col:
                st.markdown(
                    f"**{_markdown_text(_batch_recording_title(item, index))}**"
                )
            with status_col:
                _render_status_chip(st, item_status)
            if item_progress is not None and item_status in ACTIVE_STATUSES:
                st.progress(item_progress, text=stage_label)
            elif item_status in ACTIVE_STATUSES:
                st.caption(f"Current stage: {stage_label}")
            elif item_status == "failed":
                st.error(
                    "This recording could not be completed. Other successful "
                    "recordings can still be downloaded together."
                )
            elif item_status == "canceled":
                st.warning("This recording was canceled.")
            if item_id and item_status in ACTIVE_STATUSES:
                if st.button(
                    "Cancel this recording",
                    key=f"cancel-batch-item-{item_id}",
                    use_container_width=True,
                ):
                    try:
                        client.cancel_job(item_id)
                        st.session_state["_selected_batch_auto_refresh"] = True
                        st.rerun()
                    except ApiError as exc:
                        st.error(str(exc))
            elif item_id and item_status in {"failed", "canceled"}:
                if st.button(
                    "Retry this recording",
                    key=f"retry-batch-item-{item_id}",
                    use_container_width=True,
                ):
                    try:
                        client.retry_job(item_id)
                        st.session_state["_selected_batch_auto_refresh"] = True
                        st.rerun()
                    except ApiError as exc:
                        st.error(str(exc))


def _render_compact_batch_actions(
    st: Any,
    client: ApiClient,
    batch_id: str,
    jobs: Iterable[Any],
) -> None:
    cancelable = _batch_action_options(
        jobs,
        ACTIVE_STATUSES - {"canceling", "cancel_requested"},
    )
    retryable = _batch_action_options(jobs, {"failed", "canceled"})
    if not cancelable and not retryable:
        return

    with st.expander("Manage an individual recording"):
        st.caption(
            "Choose one affected recording below. The rest of the batch keeps "
            "processing normally."
        )
        if cancelable:
            cancel_labels = dict(cancelable)
            cancel_id = st.selectbox(
                "Recording to cancel",
                tuple(cancel_labels),
                format_func=cancel_labels.__getitem__,
                key=f"compact-batch-cancel-select-{batch_id}",
            )
            if st.button(
                "Cancel selected recording",
                key=f"compact-batch-cancel-{batch_id}",
                use_container_width=True,
            ):
                try:
                    client.cancel_job(str(cancel_id))
                    st.session_state["_selected_batch_auto_refresh"] = True
                    st.rerun()
                except ApiError as exc:
                    st.error(str(exc))
        if retryable:
            retry_labels = dict(retryable)
            retry_id = st.selectbox(
                "Recording to retry",
                tuple(retry_labels),
                format_func=retry_labels.__getitem__,
                key=f"compact-batch-retry-select-{batch_id}",
            )
            if st.button(
                "Retry selected recording",
                key=f"compact-batch-retry-{batch_id}",
                use_container_width=True,
            ):
                try:
                    client.retry_job(str(retry_id))
                    st.session_state["_selected_batch_auto_refresh"] = True
                    st.rerun()
                except ApiError as exc:
                    st.error(str(exc))


def _render_compact_batch_progress(
    st: Any,
    client: ApiClient,
    batch_id: str,
    jobs: Iterable[Any],
) -> None:
    job_items = list(jobs)
    rows = _compact_batch_rows(job_items)
    if rows:
        st.dataframe(
            rows,
            column_order=("Recording", "Status", "Progress"),
            column_config={
                "Recording": st.column_config.TextColumn("Recording", width="large"),
                "Status": st.column_config.TextColumn("Status", width="medium"),
                "Progress": st.column_config.ProgressColumn(
                    "Progress",
                    min_value=0,
                    max_value=100,
                    format="%d%%",
                    width="small",
                ),
            },
            hide_index=True,
            width="stretch",
            height=min(520, max(220, 35 * (len(rows) + 1))),
        )
        st.caption(
            f"Showing all {len(rows)} recordings in one compact list. "
            "Status updates automatically."
        )
    _render_compact_batch_actions(st, client, batch_id, job_items)


def _render_selected_batch_with_refresh(
    st: Any,
    client: ApiClient,
    batch_id: str,
) -> None:
    """Poll a multi-recording submission until its one delivery is ready."""

    auto_refresh = bool(st.session_state.get("_selected_batch_auto_refresh", True))

    @st.fragment(run_every="5s" if auto_refresh else None)
    def render_selected_batch() -> None:
        status = _render_selected_batch(
            st,
            client,
            batch_id,
            render_delivery=not auto_refresh,
        )
        if status is None:
            # A retryable transport/API error must not permanently disable the
            # timer that can recover on the next fragment run.
            st.session_state["_selected_batch_auto_refresh"] = auto_refresh
            return
        is_active = status == "processing"
        st.session_state["_selected_batch_auto_refresh"] = is_active
        if auto_refresh and not is_active:
            st.rerun()
        elif not auto_refresh and is_active:
            st.rerun()

    render_selected_batch()


def _render_selected_batch(
    st: Any,
    client: ApiClient,
    batch_id: str,
    *,
    render_delivery: bool = True,
) -> str | None:
    try:
        batch = client.get_batch(batch_id)
    except ApiError as exc:
        if exc.status_code == 404:
            st.info(
                "This temporary batch was already downloaded and removed, deleted, "
                "or reached its delivery deadline."
            )
            # Keep the same widget identity as the ready view. A one-shot ZIP
            # download can purge the batch between the user's click and this
            # rerun; changing keys there would discard the click and require a
            # confusing second press.
            _render_start_another_action(st, key=f"new-upload-batch-{batch_id}")
        else:
            st.error(str(exc))
            if not exc.retryable:
                _render_start_another_action(
                    st,
                    key=f"new-upload-batch-{batch_id}",
                )
        return None if exc.retryable else "unavailable"

    status = str(batch.get("status") or "processing").strip().lower()
    jobs = batch.get("jobs") if isinstance(batch.get("jobs"), list) else []
    st.session_state["submitted_job_ids"] = [
        str(item.get("job_id") or item.get("id") or "")
        for item in jobs
        if isinstance(item, dict) and (item.get("job_id") or item.get("id"))
    ]
    counts = batch.get("counts") if isinstance(batch.get("counts"), dict) else {}
    total = int(counts.get("total") or len(jobs))
    active = int(counts.get("active") or 0)
    succeeded = int(counts.get("succeeded") or 0)
    failed = int(counts.get("failed") or 0)
    canceled = int(counts.get("canceled") or 0)

    st.subheader("Your transcription batch")
    _render_status_chip(st, status)
    metric_columns = st.columns(4)
    metric_columns[0].metric("Recordings", total)
    metric_columns[1].metric("Processing", active)
    metric_columns[2].metric("Ready", succeeded)
    metric_columns[3].metric("Not completed", failed + canceled)

    progress = _batch_progress(batch)
    if progress is not None:
        st.progress(
            progress,
            text=(
                f"{succeeded + failed + canceled} of {total} recordings finished"
                if total
                else "Preparing recordings"
            ),
        )

    st.markdown("#### Recording progress")
    if _use_compact_batch_layout(jobs):
        _render_compact_batch_progress(st, client, batch_id, jobs)
    else:
        _render_batch_recording_cards(st, client, jobs)

    all_terminal = bool(batch.get("all_terminal"))
    download_ready = bool(batch.get("download_ready"))
    if not all_terminal or status == "processing":
        st.info(
            "This page updates automatically about every 5 seconds. The combined "
            "download will appear here as soon as every recording finishes."
        )
        return "processing"

    if download_ready:
        if failed or canceled:
            st.warning(
                f"{failed + canceled} of {total} recordings did not complete. The "
                f"combined package contains the {succeeded} successful recording(s)."
            )
        st.success("Your combined transcript package is ready")
        if render_delivery:
            _render_batch_download_center(st, client, batch_id)
        else:
            st.caption("Preparing the combined download…")
    else:
        st.error(
            "None of the recordings produced transcript files. Retry a recording "
            "above, or return to the upload page and try again."
        )
    if render_delivery or not download_ready:
        _render_start_another_action(st, key=f"new-upload-batch-{batch_id}")
    return status


def _render_batch_download_center(st: Any, client: ApiClient, batch_id: str) -> None:
    st.markdown("### Download all files")
    try:
        with st.spinner("Preparing one combined ZIP…"):
            package = client.create_batch_delivery_package(
                batch_id,
                purge_after_download=True,
            )
    except ApiError as exc:
        st.error(str(exc))
        st.caption("Refresh this page to request a new short-lived download link.")
        return
    item = dict(package)
    item["name"] = str(package.get("filename") or "transcripts.zip")
    _render_download_link(
        st,
        client,
        item,
        "Download all transcripts (.zip)",
        primary=True,
    )
    included = int(package.get("included_jobs") or 0)
    omitted = int(package.get("omitted_jobs") or 0)
    details = f"{included} completed recording(s) included" + (
        f" · {omitted} not completed" if omitted else ""
    )
    st.caption(
        details
        + ". Transcript files are together at the top level of the ZIP, with no "
        "folder per recording. Word, plain-text, subtitle, and provenance files "
        "remain named for their recording; safe numeric suffixes distinguish any "
        "collisions. Source recordings are never included. After a successful "
        "download, the temporary batch is removed from the service."
    )


def _render_selected_job_with_refresh(st: Any, client: ApiClient, job_id: str) -> None:
    """Keep an open, active job current without making staff hunt for refresh."""

    auto_refresh = bool(st.session_state.get("_selected_job_auto_refresh", True))

    @st.fragment(run_every="5s" if auto_refresh else None)
    def render_selected_job() -> None:
        status = _render_selected_job(
            st,
            client,
            job_id,
            render_delivery=not auto_refresh,
        )
        if status is None:
            st.session_state["_selected_job_auto_refresh"] = auto_refresh
            return
        is_active = status in ACTIVE_STATUSES
        st.session_state["_selected_job_auto_refresh"] = is_active
        # Rebuild the page once when processing ends so the interval timer is
        # removed and the completed download view is rendered in full.
        if auto_refresh and not is_active:
            st.rerun()
        elif not auto_refresh and is_active:
            st.rerun()

    render_selected_job()


def _render_selected_job(
    st: Any,
    client: ApiClient,
    job_id: str,
    *,
    render_delivery: bool = True,
) -> str | None:
    try:
        job = client.get_job(job_id)
    except ApiError as exc:
        if exc.status_code == 404:
            st.info(
                "This temporary job was already removed or reached its delivery deadline."
            )
            _render_start_another_action(st, key=f"new-upload-job-{job_id}")
        else:
            st.error(str(exc))
            if not exc.retryable:
                _render_start_another_action(
                    st,
                    key=f"new-upload-job-{job_id}",
                )
        return None if exc.retryable else "unavailable"

    batch_id = str(job.get("batch_id") or "")
    if batch_id:
        # A direct/old child-job link must retain the batch's coordinated
        # progress, delivery, and deletion semantics.
        _set_selected_batch(st, batch_id)
        st.rerun()
        return "processing"

    status = _status(job)
    _, stage_label, progress = _stage(job)
    title = str(job.get("display_name") or job.get("primary_filename") or "Selected job")
    st.subheader(_markdown_text(title))
    _render_status_chip(st, status)
    st.info(_expiry_text(_job_expiry(job)) + ". Download needed outputs and delete the job when finished.")
    if progress is not None:
        st.progress(progress, text=stage_label)
    else:
        st.caption(f"Current stage: {stage_label}")

    if status == "failed":
        st.error(_user_message(job) or "Processing failed. Transcript content is not included in this error.")
        _render_trust_panel(st, job, None)
        _render_delete_controls(st, client, job_id)
        return status
    if status in ACTIVE_STATUSES:
        st.info(
            "Processing continues on the service. Status updates automatically "
            "about every 5 seconds while this page remains open; you may also "
            "leave and return later."
        )
        queue_position = job.get("queue_position")
        if queue_position:
            st.caption(f"Queue position: {queue_position}")
        _render_trust_panel(st, job, None)
        _render_delete_controls(st, client, job_id)
        return status
    if status not in DELIVERY_STATUSES:
        st.warning(f"This job is {STATUS_LABELS.get(status, status)} and is not available for download.")
        _render_trust_panel(st, job, None)
        _render_delete_controls(st, client, job_id)
        return status

    if status == "degraded" or job.get("degraded"):
        st.warning(_user_message(job) or "The transcript is ready, but at least one requested processing stage was unavailable or skipped.")

    st.success("Transcript ready to download")
    if not render_delivery:
        st.caption("Preparing the download view…")
        return status
    st.write(
        "Download the AI-generated files as they are. Nothing needs to be saved segment by segment. "
        "Corrections are optional if you notice something you want to change."
    )
    _render_download_center(st, client, job_id)
    _render_start_another_action(st, key=f"new-upload-job-{job_id}")

    open_editor = st.toggle(
        "Preview or correct the transcript (optional)",
        value=False,
        key=f"open-optional-editor-{job_id}",
        help="Loads the source player and detailed segment and speaker tools only when needed.",
    )
    if open_editor:
        try:
            transcript = client.get_transcript(job_id)
        except ApiError as exc:
            st.error(str(exc))
            transcript = None
        if transcript is not None:
            media_url = _browser_delivery_url(
                st,
                client,
                transcript.get("media_url") or job.get("media_url"),
            )
            if media_url:
                st.markdown("#### Source recording")
                st.audio(media_url)
                st.caption("Use the timestamps below only if you choose to inspect or correct the transcript.")

            segments = transcript.get("segments") if isinstance(transcript.get("segments"), list) else []
            revision = int(transcript.get("revision") or 0)
            transcript_tab, speakers_tab, trust_tab = st.tabs(
                ("Optional corrections", "Optional speaker labels", "Trust and provenance")
            )
            with transcript_tab:
                _render_transcript_review(st, client, job_id, segments, revision)
            with speakers_tab:
                roster = transcript.get("roster") if isinstance(transcript.get("roster"), list) else []
                _render_speaker_review(st, client, job_id, segments, revision, roster)
            with trust_tab:
                _render_trust_panel(st, job, transcript, expanded=True)
    else:
        _render_trust_panel(st, job, None)
    _render_delete_controls(st, client, job_id)
    return status


def _render_transcript_review(
    st: Any,
    client: ApiClient,
    job_id: str,
    segments: list[dict[str, Any]],
    revision: int,
) -> None:
    st.markdown("#### Optional transcript corrections")
    st.caption("Only save a segment if you change its text. Unchanged transcript text is already included in every download.")
    st.warning(MACHINE_WARNING)
    if not segments:
        st.info("No transcript segments were returned for this job.")
        return

    filter_col, speaker_col = st.columns(2)
    with filter_col:
        query = st.text_input("Search transcript", key=f"search-{job_id}", placeholder="Search words or phrases")
    speaker_names = sorted({_speaker_for(segment)["display_name"] for segment in segments})
    with speaker_col:
        selected_speaker = st.selectbox("Speaker filter", ["All speakers", *speaker_names], key=f"speaker-filter-{job_id}")
    flag_col, page_col = st.columns(2)
    with flag_col:
        flag_filter = st.selectbox(
            "Quality filter",
            ("All segments", "Low confidence", "Overlapping speech"),
            key=f"quality-filter-{job_id}",
        )
    with page_col:
        page_size = st.selectbox("Segments per page", (10, 25, 50), index=1, key=f"page-size-{job_id}")

    filtered = []
    lowered_query = query.casefold().strip()
    for segment in segments:
        speaker = _speaker_for(segment)
        confidence = segment.get("confidence")
        try:
            low_confidence = bool(segment.get("low_confidence")) or (confidence is not None and float(confidence) < 0.75)
        except (TypeError, ValueError):
            low_confidence = bool(segment.get("low_confidence"))
        overlap = bool(segment.get("overlap"))
        if lowered_query and lowered_query not in _segment_text(segment).casefold():
            continue
        if selected_speaker != "All speakers" and speaker["display_name"] != selected_speaker:
            continue
        if flag_filter == "Low confidence" and not low_confidence:
            continue
        if flag_filter == "Overlapping speech" and not overlap:
            continue
        filtered.append(segment)

    if not filtered:
        st.info("No transcript segments match these filters.")
        return
    page_count = max(1, (len(filtered) + page_size - 1) // page_size)
    page = st.number_input("Page", min_value=1, max_value=page_count, value=1, step=1, key=f"page-{job_id}")
    start_index = (int(page) - 1) * page_size
    visible = filtered[start_index : start_index + page_size]
    st.caption(f"Showing {start_index + 1}–{start_index + len(visible)} of {len(filtered)} matching segments")

    for segment in visible:
        segment_id = str(segment.get("id") or segment.get("segment_id") or "")
        if not segment_id:
            continue
        speaker = _speaker_for(segment)
        state = speaker["identity_state"]
        confidence = segment.get("confidence")
        try:
            confidence_label = f"{float(confidence) * 100:.0f}% confidence" if confidence is not None else "Confidence unavailable"
            low_confidence = bool(segment.get("low_confidence")) or (confidence is not None and float(confidence) < 0.75)
        except (TypeError, ValueError):
            confidence_label = "Confidence unavailable"
            low_confidence = bool(segment.get("low_confidence"))
        overlap = bool(segment.get("overlap"))
        segment_revision = int(segment.get("revision") or 0)
        with st.container(border=True):
            st.markdown(
                f"**{_markdown_text(speaker['display_name'])}** · {_identity_label(state)}"
            )
            st.caption(
                f"{_format_timestamp(_segment_seconds(segment, 'start'))}–{_format_timestamp(_segment_seconds(segment, 'end'))} · {confidence_label}"
            )
            flags = []
            if low_confidence:
                flags.append("Low confidence — listen carefully")
            if overlap:
                flags.append("Overlapping speech")
            if flags:
                st.warning(" · ".join(flags))
            with st.form(f"segment-form-{job_id}-{segment_id}-r{segment_revision}-t{revision}"):
                original_text = _segment_text(segment)
                edited_text = st.text_area(
                    "Transcript text",
                    value=original_text,
                    key=f"segment-text-{job_id}-{segment_id}-r{segment_revision}-t{revision}",
                    label_visibility="collapsed",
                    height=100,
                )
                translated = segment.get("translated_text") or segment.get("translation_text")
                if translated:
                    st.caption("Separate English translation")
                    st.text(str(translated))
                save = st.form_submit_button("Save segment correction")
            if save:
                if edited_text == original_text:
                    st.info("No text change to save.")
                else:
                    try:
                        client.update_segment(
                            job_id,
                            segment_id,
                            text=edited_text,
                            expected_revision=segment_revision,
                        )
                        st.success("Correction saved with a new transcript revision.")
                        st.rerun()
                    except ApiError as exc:
                        st.error(str(exc))


def _unique_speakers(segments: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    speakers: dict[str, dict[str, Any]] = {}
    for segment in segments:
        speaker = _speaker_for(segment)
        speakers.setdefault(speaker["cluster_id"], speaker)
    return sorted(speakers.values(), key=lambda value: value["cluster_id"])


def _render_speaker_review(
    st: Any,
    client: ApiClient,
    job_id: str,
    segments: list[dict[str, Any]],
    revision: int,
    roster: list[Any],
) -> None:
    st.markdown("#### Speaker review")
    st.warning("A voice cluster is not proof of identity. Confirm a person only after checking the recording and case context.")
    roster_names = [str(value).strip() for value in roster if str(value).strip()]
    if roster_names:
        st.info(
            "Possible speakers supplied with this job: "
            + ", ".join(_markdown_text(value) for value in roster_names)
            + ". The roster does not establish which voice belongs to which person."
        )
    speakers = _unique_speakers(segments)
    if not speakers:
        st.info("No speaker clusters are available. Diarization may have been skipped or degraded.")
        return
    for speaker in speakers:
        cluster_id = speaker["cluster_id"]
        state = speaker["identity_state"]
        mapping_revision = int(speaker.get("revision") or 0)
        with st.container(border=True):
            st.markdown(f"**{_markdown_text(speaker['display_name'])}**")
            st.caption(f"Cluster {cluster_id} · {_identity_label(state)}")
            if speaker["suggested_name"]:
                st.info(
                    f"Service suggestion: {_markdown_text(speaker['suggested_name'])} — not confirmed"
                )
                if speaker["suggestion_basis"]:
                    st.caption(
                        f"Suggestion basis: {_markdown_text(speaker['suggestion_basis'])}"
                    )
            with st.form(f"speaker-form-{job_id}-{cluster_id}-r{mapping_revision}-t{revision}"):
                default_name = speaker["display_name"]
                if state == "suggested" and speaker["suggested_name"]:
                    default_name = speaker["suggested_name"]
                display_name = st.text_input("Speaker name or role", value=default_name)
                confirmed = st.checkbox(
                    "I verified this real-world identity and want to mark it confirmed",
                    value=state == "confirmed",
                )
                submitted = st.form_submit_button("Save speaker mapping")
            if submitted:
                if not display_name.strip():
                    st.error("Enter a speaker name, role, or cluster label.")
                    continue
                identity_state = "confirmed" if confirmed else "cluster"
                try:
                    client.update_speaker(
                        job_id,
                        cluster_id,
                        display_name=display_name.strip(),
                        identity_state=identity_state,
                        expected_revision=mapping_revision,
                    )
                    st.success("Speaker mapping saved with a new transcript revision.")
                    st.rerun()
                except ApiError as exc:
                    st.error(str(exc))


def _render_trust_panel(
    st: Any,
    job: dict[str, Any],
    transcript: dict[str, Any] | None,
    *,
    expanded: bool = False,
) -> None:
    transcript = transcript or {}
    provenance = transcript.get("provenance") or job.get("provenance") or {}
    quality = transcript.get("quality") or job.get("quality") or {}
    if not isinstance(provenance, dict):
        provenance = {}
    if not isinstance(quality, dict):
        quality = {}
    container = st.container(border=True) if expanded else st.expander("Trust and provenance")
    with container:
        st.markdown("#### Trust and provenance")
        st.warning(MACHINE_WARNING)
        rows = [
            ("Review status", transcript.get("review_state") or job.get("review_state") or "Machine draft"),
            ("Job ID", job.get("id") or job.get("job_id")),
            ("Source SHA-256", provenance.get("source_sha256") or job.get("source_sha256")),
            ("Outcome profile", provenance.get("profile") or job.get("profile")),
            ("Pipeline version", provenance.get("pipeline_version")),
            ("ASR model", provenance.get("asr_model")),
            ("ASR revision", provenance.get("asr_revision")),
            ("Alignment model", provenance.get("alignment_model")),
            ("Diarization model", provenance.get("diarization_model")),
            ("Detected language", quality.get("detected_language") or transcript.get("detected_language")),
            ("Language confidence", _percent(quality.get("language_confidence"))),
            ("Diarization status", quality.get("diarization_status") or job.get("diarization_status")),
            ("Speaker clusters", quality.get("speaker_count")),
            ("Low-confidence segments", quality.get("low_confidence_segments")),
            ("Overlapping-speech segments", quality.get("overlap_segments")),
            ("Created", _format_date(job.get("created_at"))),
            ("Delete after", _format_date(_job_expiry(job))),
        ]
        visible_rows = [{"Field": label, "Value": str(value)} for label, value in rows if value not in (None, "", "Not available")]
        if visible_rows:
            st.table(visible_rows)
        warnings = job.get("warnings") or transcript.get("warnings") or []
        safe_warnings = []
        for warning in warnings if isinstance(warnings, list) else []:
            if isinstance(warning, dict):
                message = _user_message(warning)
                if message:
                    safe_warnings.append(message)
        if safe_warnings:
            st.markdown("**Pipeline warnings**")
            for warning in safe_warnings:
                st.warning(warning)
        elif _status(job) == "degraded" or job.get("degraded"):
            st.warning("The job is marked degraded, but no staff-safe warning detail was provided.")


def _percent(value: Any) -> str | None:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return None


def _classify_download_exports(
    exports: Iterable[Any],
) -> tuple[
    dict[str, Any] | None,
    dict[str, Any] | None,
    dict[str, Any] | None,
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Return transcript DOCX, TXT, ZIP, translations, and other artifacts."""

    items = sorted(
        (
            item
            for item in exports
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ),
        key=lambda item: str(item.get("name") or "").casefold(),
    )
    package = next(
        (
            item
            for item in items
            if str(item.get("name") or "").casefold().endswith(".delivery.zip")
        ),
        None,
    )
    package_name = str((package or {}).get("name") or "")
    package_suffix = ".delivery.zip"
    main_stem = (
        package_name[: -len(package_suffix)]
        if package_name.casefold().endswith(package_suffix)
        else ""
    )
    transcript_docx = next(
        (
            item
            for item in items
            if main_stem
            and str(item.get("name") or "").casefold()
            == f"{main_stem}.docx".casefold()
        ),
        None,
    )
    if transcript_docx is None:
        transcript_docx = next(
            (
                item
                for item in items
                if str(item.get("name") or "").casefold() == "transcript.docx"
            ),
            None,
        )
    if transcript_docx is None and not main_stem:
        transcript_docx = next(
            (
                item
                for item in items
                if str(item.get("name") or "").casefold().endswith(".docx")
                and ".translation." not in str(item.get("name") or "").casefold()
            ),
            None,
        )
    transcript_txt = next(
        (
            item
            for item in items
            if main_stem
            and str(item.get("name") or "").casefold()
            == f"{main_stem}.txt".casefold()
        ),
        None,
    )
    if transcript_txt is None:
        transcript_txt = next(
            (
                item
                for item in items
                if str(item.get("name") or "").casefold() == "transcript.txt"
            ),
            None,
        )
    if transcript_txt is None and not main_stem:
        transcript_txt = next(
            (
                item
                for item in items
                if str(item.get("name") or "").casefold().endswith(".txt")
                and ".translation." not in str(item.get("name") or "").casefold()
            ),
            None,
        )
    translation_prefix = f"{main_stem}.translation.".casefold() if main_stem else ""
    translations = [
        item
        for item in items
        if (
            str(item.get("name") or "").casefold().startswith(translation_prefix)
            if translation_prefix
            else ".translation." in str(item.get("name") or "").casefold()
        )
        and str(item.get("name") or "").casefold().endswith((".docx", ".txt"))
        and item is not transcript_docx
        and item is not transcript_txt
    ]
    promoted = {
        id(item)
        for item in (transcript_docx, transcript_txt, package, *translations)
        if item is not None
    }
    remaining = [item for item in items if id(item) not in promoted]
    return transcript_docx, transcript_txt, package, translations, remaining


def _render_download_link(
    st: Any,
    client: ApiClient,
    item: dict[str, Any],
    label: str,
    *,
    primary: bool = False,
) -> None:
    download_url = _browser_delivery_url(
        st,
        client,
        item.get("download_url") or item.get("url"),
    )
    if not download_url:
        st.warning(f"{label} is temporarily unavailable. Refresh the page to request a new link.")
        return
    st.link_button(
        label,
        download_url,
        type="primary" if primary else "secondary",
        use_container_width=True,
    )
    details = []
    size = _format_bytes(item.get("size_bytes"))
    if size:
        details.append(size)
    name = str(item.get("name") or "")
    if name:
        details.append(name)
    if details:
        st.caption(" · ".join(_markdown_text(value) for value in details))


def _render_download_center(st: Any, client: ApiClient, job_id: str) -> None:
    st.markdown("### Download files")
    try:
        exports = client.get_exports(job_id)
    except ApiError as exc:
        st.error(str(exc))
        return
    if not exports:
        st.info("Transcript files are still being prepared. Refresh in a moment.")
        return

    transcript_docx, transcript_txt, package, translations, remaining = (
        _classify_download_exports(exports)
    )
    if package is not None:
        _render_download_link(
            st,
            client,
            package,
            "Download complete transcript package (.zip)",
            primary=True,
        )
    else:
        st.warning(
            "The complete ZIP package is unavailable. Individual transcript files "
            "may still be downloaded below."
        )

    promoted: list[tuple[dict[str, Any], str, bool]] = []
    if transcript_docx is not None:
        promoted.append((transcript_docx, "Download Word transcript (.docx)", package is None))
    if transcript_txt is not None:
        promoted.append((transcript_txt, "Download plain-text transcript (.txt)", False))
    for item in translations:
        suffix = str(item.get("name") or "").casefold()
        label = (
            "Download English translation (.docx)"
            if suffix.endswith(".docx")
            else "Download English translation (.txt)"
        )
        promoted.append((item, label, False))

    if promoted:
        with st.expander("Download individual files instead"):
            columns = st.columns(min(3, len(promoted)))
            for index, (item, label, primary) in enumerate(promoted):
                with columns[index % len(columns)]:
                    _render_download_link(st, client, item, label, primary=primary)
    elif package is None:
        st.warning(
            "The usual DOCX, TXT, and ZIP files are unavailable. Other generated "
            "formats may still be listed below."
        )

    st.caption(
        "The ZIP contains the Word transcript, other transcript formats, and "
        "provenance—not the source recording. Links are short-lived; refresh this "
        "page if a link expires. The job still follows its automatic deletion window."
    )
    if remaining and st.toggle(
        "Show individual and technical formats",
        value=False,
        key=f"show-other-downloads-{job_id}",
    ):
        for item in remaining:
            name = str(item.get("name") or "download")
            with st.container(border=True):
                _render_download_link(st, client, item, f"Download {name}")


def _render_delete_controls(st: Any, client: ApiClient, job_id: str) -> None:
    st.divider()
    with st.expander("Delete this temporary job now"):
        st.warning("Deletion permanently removes the uploaded source, transcript, review edits, and generated exports from this service.")
        confirmed = st.checkbox(
            "I have downloaded everything I need and want to delete this job now",
            value=False,
            key=f"delete-confirm-{job_id}",
        )
        if st.button(
            "Delete source and all artifacts now",
            disabled=not confirmed,
            key=f"delete-job-{job_id}",
            type="secondary",
        ):
            try:
                result = client.delete_job(job_id)
                outcome = str(result.get("status") or "").lower()
                deletion_confirmed = outcome in {"deleted", "purged"} or result.get("purged") is True
                if not deletion_confirmed:
                    st.session_state["_lifecycle_notice"] = (
                        "warning",
                        "Cancellation and purge were requested. The worker must stop safely before the service can confirm deletion.",
                    )
                else:
                    st.session_state.pop("selected_job_id", None)
                    st.session_state.pop(f"delivery-package-{job_id}", None)
                    st.query_params.pop("job", None)
                    st.session_state["_lifecycle_notice"] = (
                        "success",
                        "The service confirmed deletion of the job and its temporary artifacts.",
                    )
                st.rerun()
            except ApiError as exc:
                st.error(str(exc))


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title=APP_TITLE, page_icon="🎙️", layout="wide", initial_sidebar_state="auto")
    _load_styles(st)
    client = _get_client(st)
    workspace_redirect = _apply_workspace_redirect(st)

    # Streamlit sends query-param updates to the browser asynchronously. A
    # rerun triggered by the Home action can therefore briefly replay the old
    # ?job= or ?batch= route. The explicit redirect wins for this run and
    # clears that stale browser route before rendering the fresh upload form.
    if workspace_redirect == "Transcribe":
        st.query_params.clear()
    else:
        query_batch = st.query_params.get("batch")
        query_job = st.query_params.get("job")
        if query_batch:
            st.session_state["selected_batch_id"] = str(query_batch)
            st.session_state.pop("selected_job_id", None)
            st.session_state["workspace_page"] = "Jobs & downloads"
        elif query_job and not st.session_state.get("selected_job_id"):
            st.session_state["selected_job_id"] = str(query_job)
            st.session_state["workspace_page"] = "Jobs & downloads"
    st.markdown(
        '<div class="app-masthead"><span class="app-wordmark">Transcript Studio</span>'
        '<span class="app-purpose">Local transcription · temporary delivery</span></div>',
        unsafe_allow_html=True,
    )
    page = _render_sidebar(st, client)
    if page == "Transcribe":
        _render_new_job(st, client)
    else:
        _render_jobs(st, client)


if __name__ == "__main__":
    main()
