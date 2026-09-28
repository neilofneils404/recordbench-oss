"""Bind installed ASR profiles to their verified immutable local snapshots."""
from __future__ import annotations

import re
from pathlib import Path

from .model_manifest import ArtifactReadiness, ModelReadiness, MODEL_MANIFEST_SCHEMA_V2
from .profiles import TranscriptionProfile

_ASR_REPOSITORIES = {
    "large-v3": "Systran/faster-whisper-large-v3",
    "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}


_ASR_SLOTS = {"large-v3": "primary", "turbo": "fast"}


def approved_asr_artifact(readiness: ModelReadiness, model_name: str, *,
                          translate: bool = False) -> ArtifactReadiness:
    """Resolve a fixed processing slot, never a user-provided path or hub URL."""
    failure = "Selected ASR model is not approved and staged for offline use."
    revision = None
    if readiness.schema_version == MODEL_MANIFEST_SCHEMA_V2:
        binding = next((b for b in readiness.asr_bindings if b.slot == _ASR_SLOTS.get(model_name)), None)
        if binding is None or (translate and not binding.supports_translation):
            raise ValueError(failure)
        model_id, revision = binding.model_id, binding.revision
    else:
        model_id = _ASR_REPOSITORIES.get(model_name)
        if translate and model_name != "large-v3":
            raise ValueError(failure)
    artifacts = [a for a in readiness.artifacts if a.role == "asr" and a.model_id == model_id
                 and (revision is None or a.revision == revision)]
    if model_id is None or len(artifacts) != 1:
        raise ValueError(failure)
    return artifacts[0]


def profile_model_metadata(profile: TranscriptionProfile, readiness: ModelReadiness | None) -> dict:
    """Freeze selected identities in API/results without changing loader slots."""
    result = profile.to_dict()
    if readiness is None or readiness.schema_version != MODEL_MANIFEST_SCHEMA_V2:
        return result
    selected = {}
    for key, alias in (("asr", profile.asr_model), ("translation", profile.translation_model)):
        result[key + "_slot"] = _ASR_SLOTS[alias]
        try:
            artifact = approved_asr_artifact(readiness, alias, translate=key == "translation")
        except ValueError:
            result[key + "_model"] = None
            result[key + "_artifact"] = None
            continue
        result[key + "_model"] = artifact.model_id
        result[key + "_artifact"] = artifact.public_dict()
        selected[(artifact.model_id, artifact.revision)] = artifact
    # A compatible operator model does not inherit the reference weights' terms.
    result["components"] = [c for c in result["components"] if c["name"] != "OpenAI Whisper weights"]
    result["components"].extend({"name": "Operator-selected ASR weights", "model_id": a.model_id,
                                 "revision": a.revision, "license": a.license,
                                 "notes": "Operator-declared terms; compatibility and quality require evaluation."}
                                for a in selected.values())
    result["notes"] = ["ASR models are administrator-selected; profile names describe decoding settings, not measured quality.",
                       "English translation requires the separately approved primary model capability."]
    result["model_manifest_sha256"] = readiness.manifest_sha256
    return result


def approved_asr_snapshot(cache: str | Path | None, readiness: ModelReadiness,
                          model_name: str, *, translate: bool = False) -> Path:
    """Reject missing profiles, unapproved bytes and mutable cache references."""
    failure = "Selected ASR model is not approved and staged for offline use."
    artifact = approved_asr_artifact(readiness, model_name, translate=translate)
    model_id = artifact.model_id
    if cache is None or not re.fullmatch(r"(?:[0-9a-f]{40}|sha256-[0-9a-f]{64})", artifact.revision):
        raise ValueError(failure)
    try:
        root = Path(cache).expanduser().absolute()
        snapshot = root / ("models--" + model_id.replace("/", "--")) / "snapshots" / artifact.revision
        if any(path.is_symlink() for path in (root, snapshot.parent.parent, snapshot.parent, snapshot)):
            raise ValueError(failure)
        if not snapshot.is_dir():
            raise ValueError(failure)
        required = {"config.json", "model.bin", "tokenizer.json"}
        if not all((snapshot / name).is_file() for name in required):
            raise ValueError(failure)
        if not any((snapshot / name).is_file() for name in ("vocabulary.json", "vocabulary.txt")):
            raise ValueError(failure)
        for path in snapshot.rglob("*"):
            if path.is_dir():
                if path.is_symlink():
                    raise ValueError(failure)
                continue
            if (not path.resolve(strict=True).is_relative_to(root.resolve(strict=True))
                    or not readiness.authorizes_file(path, role="asr", model_id=model_id,
                                                    revision=artifact.revision)):
                raise ValueError(failure)
        return snapshot
    except (OSError, ValueError):
        raise ValueError(failure) from None
