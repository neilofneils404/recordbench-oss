"""Synthetic real-process checks for OCR's enforced output-file boundary."""
from __future__ import annotations

import signal
import subprocess
import sys
from pathlib import Path

import pytest

from case_intelligence import ocr_process_helper, pilot_uploads

resource = pytest.importorskip("resource")
HELPER = Path(ocr_process_helper.__file__)
ENVIRONMENT = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "OMP_THREAD_LIMIT": "1"}
RASTER = b"P5\n1 1\n255\n\0"
# Python normally ignores SIGXFSZ; restore the exec-time default so this
# synthetic executable behaves like Tesseract when the kernel refuses a write.
WRITER = """
import pathlib, signal, sys
signal.signal(signal.SIGXFSZ, signal.SIG_DFL)
pathlib.Path(sys.argv[1]).with_suffix('.txt').write_text('synthetic body')
with open(sys.argv[1], 'wb', buffering=0) as output:
    for _ in range(257):
        output.write(b'x' * 65536)
"""


def test_real_ocr_child_cannot_write_past_file_cap(tmp_path):
    output = tmp_path / "synthetic.tsv"
    inherited = resource.getrlimit(resource.RLIMIT_FSIZE)
    result = subprocess.run(
        [sys.executable, "-I", "-S", str(HELPER), str(pilot_uploads.MAX_OCR_TSV_BYTES),
         sys.executable, "-I", "-S", "-c", WRITER, str(output)],
        capture_output=True, timeout=10, env=ENVIRONMENT,
    )
    assert result.returncode == -signal.SIGXFSZ
    assert 0 < output.stat().st_size <= pilot_uploads.MAX_OCR_TSV_BYTES
    assert resource.getrlimit(resource.RLIMIT_FSIZE) == inherited


def test_ocr_limit_is_classified_and_temporary_outputs_removed(monkeypatch):
    run = subprocess.run
    observations = []

    def synthetic_tesseract(command, **kwargs):
        index = command.index("/usr/bin/tesseract")
        base = Path(command[index + 2])
        # Keep the real helper, its exact cap and timeout; replace only the
        # unavailable platform executable with a synthetic oversized writer.
        result = run(command[:index] + [sys.executable, "-I", "-S", "-c", WRITER, str(base) + ".tsv"], **kwargs)
        observations.append((base.parent, base.with_suffix(".tsv").stat().st_size))
        return result

    monkeypatch.setattr(pilot_uploads.subprocess, "run", synthetic_tesseract)
    with pytest.raises(pilot_uploads._OcrStop) as raised:
        pilot_uploads._tesseract_reading(RASTER, "eng", "1", 10, ENVIRONMENT)
    assert raised.value.status == "output_limit"
    directory, actual_size = observations[0]
    assert actual_size <= pilot_uploads.MAX_OCR_TSV_BYTES
    assert not directory.exists()


def test_reached_file_cap_is_rejected_even_if_executable_reports_success(monkeypatch):
    run = subprocess.run
    observed_sizes = []
    # Python ignores SIGXFSZ itself; catch EFBIG to simulate an executable that
    # reports success despite its truncated output. The read must still fail.
    script = """
import pathlib, sys
try:
    with open(sys.argv[1] + '.tsv', 'wb', buffering=0) as output:
        for _ in range(257):
            output.write(b'x' * 65536)
except OSError:
    pass
pathlib.Path(sys.argv[1] + '.txt').write_text('synthetic body')
"""

    def synthetic_tesseract(command, **kwargs):
        index = command.index("/usr/bin/tesseract")
        base = Path(command[index + 2])
        result = run(command[:index] + [sys.executable, "-I", "-S", "-c", script, str(base)], **kwargs)
        assert result.returncode == 0
        observed_sizes.append(base.with_suffix(".tsv").stat().st_size)
        return result

    monkeypatch.setattr(pilot_uploads.subprocess, "run", synthetic_tesseract)
    with pytest.raises(pilot_uploads._OcrStop) as raised:
        pilot_uploads._tesseract_reading(RASTER, "eng", "1", 10, ENVIRONMENT)
    assert raised.value.status == "output_limit"
    assert observed_sizes == [pilot_uploads.MAX_OCR_TSV_BYTES]


def test_real_bounded_child_returns_small_reading_and_cleans_up(monkeypatch):
    run = subprocess.run
    directories = []
    script = """
import pathlib, sys
pathlib.Path(sys.argv[1] + '.txt').write_text('synthetic body')
pathlib.Path(sys.argv[1] + '.tsv').write_text('header\\n5\\t1\\t1\\t1\\t1\\t1\\t0\\t0\\t1\\t1\\t95\\tbody\\n')
"""

    def synthetic_tesseract(command, **kwargs):
        index = command.index("/usr/bin/tesseract")
        base = Path(command[index + 2])
        directories.append(base.parent)
        return run(command[:index] + [sys.executable, "-I", "-S", "-c", script, str(base)], **kwargs)

    monkeypatch.setattr(pilot_uploads.subprocess, "run", synthetic_tesseract)
    reading = pilot_uploads._tesseract_reading(RASTER, "eng", "1", 10, ENVIRONMENT)
    assert reading == pilot_uploads._OcrReading("synthetic body", (("body", 95.0),))
    assert not directories[0].exists()


def test_exec_preserves_parent_timeout_and_cleanup(monkeypatch):
    run = subprocess.run
    directories = []
    script = "import pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text('synthetic'); time.sleep(30)"

    def synthetic_tesseract(command, **kwargs):
        index = command.index("/usr/bin/tesseract")
        base = Path(command[index + 2])
        directories.append(base.parent)
        return run(command[:index] + [sys.executable, "-I", "-S", "-c", script, str(base) + ".txt"], **kwargs)

    monkeypatch.setattr(pilot_uploads.subprocess, "run", synthetic_tesseract)
    with pytest.raises(subprocess.TimeoutExpired):
        pilot_uploads._tesseract_reading(RASTER, "eng", "1", 0.2, ENVIRONMENT)
    assert not directories[0].exists()


def test_helper_preserves_a_tighter_inherited_file_limit(tmp_path):
    # Set the inherited limit in a separate launcher, never in pytest's process
    # or a threaded caller's preexec_fn.
    launcher = """
import os, resource, sys
resource.setrlimit(resource.RLIMIT_FSIZE, (1024, 1024))
os.execv(sys.executable, [sys.executable, '-I', '-S', *sys.argv[1:]])
"""
    output = tmp_path / "synthetic.tsv"
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", launcher, str(HELPER), str(pilot_uploads.MAX_OCR_TSV_BYTES),
         sys.executable, "-I", "-S", "-c", WRITER, str(output)],
        capture_output=True, timeout=10, env=ENVIRONMENT,
    )
    assert result.returncode == -signal.SIGXFSZ
    assert output.stat().st_size == 1024


@pytest.mark.parametrize("arguments", [[], ["invalid"], ["0", "/bin/echo"], ["-1", "/bin/echo"],
                                       [str(pilot_uploads.MAX_OCR_TSV_BYTES + 1), "/bin/echo"], ["1024", "relative"]])
def test_helper_refuses_invalid_limits_or_commands(arguments):
    result = subprocess.run([sys.executable, "-I", "-S", str(HELPER), *arguments],
                            capture_output=True, timeout=10, env=ENVIRONMENT)
    assert result.returncode == 125


def test_failed_limit_installation_never_executes(monkeypatch):
    def refuse_limit(*args):
        raise OSError("synthetic unsupported limit")

    def unexpected_exec(*args):
        raise AssertionError("unbounded executable must not run")

    monkeypatch.setattr(ocr_process_helper.resource, "setrlimit", refuse_limit)
    monkeypatch.setattr(ocr_process_helper.os, "execv", unexpected_exec)
    assert ocr_process_helper.main(["1024", "/usr/bin/tesseract"]) == 125
