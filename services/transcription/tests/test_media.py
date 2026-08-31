from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from transcription_v2.media import (
    MediaDurationExceeded,
    MediaProbeError,
    probe_media,
    validate_media_name,
)


class MediaTests(unittest.TestCase):
    def test_supported_extension_is_case_insensitive(self) -> None:
        validate_media_name("INTERVIEW.WAV")

    def test_rejects_unknown_extension(self) -> None:
        with self.assertRaises(MediaProbeError):
            validate_media_name("notes.pdf")

    @patch("transcription_v2.media.subprocess.run")
    def test_duration_limit_accepts_boundary_and_rejects_above_it(
        self, run: Mock
    ) -> None:
        def result(duration: float) -> Mock:
            return Mock(
                returncode=0,
                stdout=(
                    '{"streams":[{"codec_type":"audio","channels":1,'
                    '"sample_rate":"16000"}],"format":{"duration":"'
                    + str(duration)
                    + '","format_name":"wav"}}'
                ),
            )

        run.return_value = result(43_200)
        probe = probe_media(Path("recording.wav"), max_duration_seconds=43_200)
        self.assertEqual(43_200, probe.duration_seconds)

        run.return_value = result(43_200.001)
        with self.assertRaises(MediaDurationExceeded):
            probe_media(Path("recording.wav"), max_duration_seconds=43_200)


if __name__ == "__main__":
    unittest.main()
