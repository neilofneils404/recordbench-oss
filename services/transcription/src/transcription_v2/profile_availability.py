"""Admission based on the same immutable ASR artifacts the worker accepts."""
from __future__ import annotations

import os
import stat

from .asr_models import approved_asr_snapshot, profile_model_metadata
from .alignment_models import ALIGNMENT_MODELS, approved_alignment_model
from .model_manifest import ModelManifestError, ModelReadiness, verify_model_manifest
from .profiles import TranscriptionProfile, get_profile, list_profiles
from .settings import Settings
from .tokenizer_resources import punkt_language_ready


class ProfileAvailability:
    """Hash once at API startup; reject changed artifacts until a clean restart.

    This checks model availability, not GPU capacity or whole-worker readiness.
    No model imports, downloads, or inference take place in the API.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._readiness: ModelReadiness | None = None
        self._manifest_identity: tuple[int, ...] | None = None
        if settings.pipeline_backend == "mock":
            return
        try:
            before = self._manifest_signature()
            verified = verify_model_manifest(
                settings.model_cache_dir, settings.approved_model_manifest_path,
            )
            if before == self._manifest_signature():
                self._readiness = verified
                self._manifest_identity = before
        except (ModelManifestError, OSError, ValueError):
            # Keep health/status available, but do not admit real jobs.
            pass

    def _manifest_signature(self) -> tuple[int, ...]:
        value = os.lstat(self.settings.approved_model_manifest_path)
        if not stat.S_ISREG(value.st_mode):
            raise ValueError("Approved inventory is unavailable")
        return (value.st_dev, value.st_ino, value.st_size,
                value.st_mtime_ns, value.st_ctime_ns)

    def available(self, profile: TranscriptionProfile, *, translate: bool = False) -> bool:
        if self.settings.pipeline_backend == "mock":
            return True
        if self._readiness is None:
            return False
        try:
            if self._manifest_signature() != self._manifest_identity:
                return False
            approved_asr_snapshot(self.settings.model_cache_dir, self._readiness, profile.asr_model)
            if translate:
                approved_asr_snapshot(self.settings.model_cache_dir, self._readiness,
                                      profile.translation_model, translate=True)
        except (OSError, ValueError):
            return False
        return True

    def public_profiles(self) -> list[dict[str, object]]:
        result = []
        for registered in list_profiles():
            profile = get_profile(registered.name, diarization_backend=self.settings.diarization_backend)
            available = self.available(profile)
            result.append({
                **profile_model_metadata(profile, self._readiness),
                "available": available,
                "unavailable_reason": None if available else "This processing option is not ready on this service.",
                "translation_available": self.available(profile, translate=True),
            })
        return result

    def languages(self) -> list[str]:
        if self.settings.pipeline_backend == "mock":
            return list(ALIGNMENT_MODELS)
        if self._readiness is None:
            return []
        try:
            if self._manifest_signature() != self._manifest_identity:
                return []
        except (OSError, ValueError):
            return []
        available = []
        for language in ALIGNMENT_MODELS:
            try:
                approved_alignment_model(self.settings.model_cache_dir, self._readiness, language)
            except ValueError:
                continue
            if punkt_language_ready(language):
                available.append(language)
        return available
