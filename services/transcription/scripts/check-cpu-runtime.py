"""Verify the CPU image's real dependencies and synthetic audio path, no weights.

WhisperX decodes with ffmpeg before supplying in-memory waveforms to pyannote.
Its CPU image deliberately omits the unavailable compatible ARM64 TorchCodec
wheel. This check must fail if that preloaded-waveform contract stops working.
"""

from __future__ import annotations

import importlib.util
import tempfile
import wave
import warnings
from pathlib import Path
from types import SimpleNamespace


def main() -> None:
    import torch
    import ctranslate2

    assert torch.version.cuda is None, "CPU image must not include CUDA Torch"
    assert importlib.util.find_spec("torchcodec") is None, "CPU image excludes TorchCodec"
    assert "float32" in ctranslate2.get_supported_compute_types("cpu")
    assert "int8" in ctranslate2.get_supported_compute_types("cpu")
    with warnings.catch_warnings():
        # The missing optional decoder emits a startup warning; this script
        # verifies the supported waveform path instead of suppressing failures.
        warnings.filterwarnings("ignore", message="\\ntorchcodec is not installed correctly")
        from pyannote.audio.core.io import Audio
        from pyannote.core import Annotation, Segment
        from whisperx.asr import load_model
        from whisperx.diarize import DiarizationPipeline
        from whisperx.audio import load_audio

    assert callable(load_model) and callable(DiarizationPipeline)
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "synthetic.wav"
        with wave.open(str(source), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16_000)
            output.writeframes(b"\x00\x00" * 16_000)
        decoded = load_audio(str(source))

        # Exercise WhisperX's actual filename-to-waveform adapter while
        # replacing only inference; no model is constructed or downloaded.
        def capture_waveform(audio, **_kwargs):
            assert set(audio) == {"waveform", "sample_rate"}
            assert audio["waveform"].shape == (1, 16_000)
            assert audio["sample_rate"] == 16_000
            annotation = Annotation()
            annotation[Segment(0.0, 1.0)] = "SPEAKER_00"
            return SimpleNamespace(speaker_diarization=annotation)

        diarizer = DiarizationPipeline.__new__(DiarizationPipeline)
        diarizer.model = capture_waveform
        rows = diarizer(str(source))
        assert list(rows["speaker"]) == ["SPEAKER_00"]

    audio = {"waveform": torch.from_numpy(decoded[None, :]), "sample_rate": 16_000}
    reader = Audio(sample_rate=16_000, mono=True)
    waveform, sample_rate = reader(audio)
    assert waveform.shape == (1, 16_000) and sample_rate == 16_000
    assert reader.get_duration(audio) == 1.0
    cropped, sample_rate = reader.crop(audio, Segment(0.0, 0.5))
    assert cropped.shape == (1, 8_000) and sample_rate == 16_000
    print("CPU runtime imports and synthetic FFmpeg/waveform decoding passed; no model inference performed.")


if __name__ == "__main__":
    main()
