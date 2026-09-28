"""Bind supported alignment loaders to manifest-approved local checkpoints."""
from pathlib import Path
import re

from .model_manifest import ModelReadiness

ALIGNMENT_MODELS = {
    "en": ("WAV2VEC2_ASR_BASE_960H", "wav2vec2_fairseq_base_ls960_asr_ls960.pth"),
    "es": ("VOXPOPULI_ASR_BASE_10K_ES", "wav2vec2_voxpopuli_base_10k_asr_es.pt"),
}


def approved_alignment_model(cache: str | Path | None, readiness: ModelReadiness,
                             language: str, requested: str | None = None) -> str:
    failure = "The spoken language's alignment model is not approved and staged for offline use."
    try:
        bundle, filename = ALIGNMENT_MODELS[language]
        model_id, role = "torchaudio/" + bundle, "alignment_" + language
        artifacts = [a for a in readiness.artifacts if a.role == role and a.model_id == model_id]
        if cache is None or requested not in (None, bundle) or len(artifacts) != 1:
            raise ValueError(failure)
        artifact = artifacts[0]
        if not re.fullmatch(r"sha256-[0-9a-f]{64}", artifact.revision):
            raise ValueError(failure)
        root = Path(cache).expanduser().absolute()
        path = root / filename
        if root.is_symlink() or path.is_symlink() or not path.is_file():
            raise ValueError(failure)
        if not readiness.authorizes_file(path, role=role, model_id=model_id, revision=artifact.revision):
            raise ValueError(failure)
        return bundle
    except (KeyError, OSError, ValueError):
        raise ValueError(failure) from None
