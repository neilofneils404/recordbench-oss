"""Bind installed ASR profiles to their verified immutable local snapshots."""
from __future__ import annotations

import re
from pathlib import Path

from .model_manifest import ModelReadiness

_ASR_REPOSITORIES = {
    "large-v3": "Systran/faster-whisper-large-v3",
    "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}


def approved_asr_snapshot(cache: str | Path | None, readiness: ModelReadiness,
                          model_name: str) -> Path:
    """Reject missing profiles, unapproved bytes and mutable cache references."""
    failure = "Selected ASR model is not approved and staged for offline use."
    model_id = _ASR_REPOSITORIES.get(model_name)
    artifacts = [a for a in readiness.artifacts if a.role == "asr" and a.model_id == model_id]
    if cache is None or model_id is None or len(artifacts) != 1:
        raise ValueError(failure)
    artifact = artifacts[0]
    if not re.fullmatch(r"[0-9a-f]{40}", artifact.revision):
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
