#!/usr/bin/env python3
"""Run a disposable, loopback-only synthetic contributor preview."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import socket
import signal
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def preview_environment() -> None:
    # Do this before importing the application: some defaults are read on import.
    # This process is the preview; the invoking shell's environment is unchanged.
    for name in tuple(os.environ):
        if name.startswith(("CASE_INTELLIGENCE_", "CASE_REVIEW_", "RECORDBENCH_")):
            del os.environ[name]
    os.environ.update({
        "CASE_INTELLIGENCE_STORAGE_RESERVE_GIB": "0",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
    })


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8786,
                        help="loopback port (default: 8786; 0 chooses a free port)")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")

    def interrupt_startup(signum, frame):
        raise KeyboardInterrupt

    previous = {sig: signal.signal(sig, interrupt_startup)
                for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        return run_preview(args.port)
    except KeyboardInterrupt:
        return 0
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def run_preview(port: int) -> int:
    # main installs cleanup-aware signal handling before imports, temporary
    # state creation or application construction can begin.

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        try:
            listener.bind(("127.0.0.1", port))
        except OSError:
            print("Preview port unavailable. Stop its owner or choose --port 0.", file=sys.stderr)
            return 1
        preview_environment()
        sys.path.insert(0, str(ROOT / "src"))
        try:
            import uvicorn
            from case_intelligence.generation import UnavailableGenerator
            from case_intelligence.workbench import create_workbench_app
        except ImportError:
            print("Preview dependencies are unavailable. Run make bootstrap first.", file=sys.stderr)
            return 1

        with tempfile.TemporaryDirectory(prefix="recordbench-synthetic-preview-") as temporary:
            app = create_workbench_app(
                Path(temporary).resolve() / "runtime",
                auth_mode="preview", secure_cookie=False,
                generator=UnavailableGenerator(), learned_retrieval=False,
                background_ingestion=True, ingestion_workers=1,
                malware_scan_mode="disabled",
            )
            print("Synthetic contributor preview: temporary data is removed on exit.", flush=True)
            print("No passwords, malware scanner, model service or production storage. Use synthetic files only.", flush=True)
            print(f"Preview URL: http://127.0.0.1:{listener.getsockname()[1]}", flush=True)
            print("Choose Taylor Morgan at sign-in; see examples/synthetic-alpha. Stop with Ctrl-C.", flush=True)
            class PreviewServer(uvicorn.Server):
                @contextmanager
                def capture_signals(self):
                    # Uvicorn normally re-raises SIGTERM after shutting down.
                    # Own that lifecycle here so the temporary runtime is removed
                    # after workers stop, on both Ctrl-C and SIGTERM.
                    previous = {sig: signal.signal(sig, self.handle_exit)
                                for sig in (signal.SIGINT, signal.SIGTERM)}
                    try:
                        yield
                    finally:
                        for sig, handler in previous.items():
                            signal.signal(sig, handler)

            server = PreviewServer(uvicorn.Config(
                app, log_level="warning", access_log=False, ws="none",
            ))
            try:
                server.run(sockets=[listener])
            finally:
                # Also close construction-time workers if server startup failed
                # before its lifespan handler could run.
                app.state.workbench.close()
            return 0 if server.started else 1


if __name__ == "__main__":
    raise SystemExit(main())
