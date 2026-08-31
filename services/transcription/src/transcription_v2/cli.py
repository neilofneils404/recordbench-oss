"""Operator CLI for the isolated v2 API, worker, and lifecycle checks."""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Sequence

from .model_manifest import ModelManifestError, verify_model_manifest
from .resources import readiness
from .runtime import build_runtime
from .settings import Settings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="transcription-v2")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("api", help="Run the loopback FastAPI service")
    subcommands.add_parser("worker", help="Run the durable local worker")
    subcommands.add_parser("check", help="Print a privacy-safe readiness report")
    subcommands.add_parser(
        "verify-models",
        help="Verify every pre-staged approved model artifact",
    )
    subcommands.add_parser("purge-expired", help="Purge all expired transient jobs")
    subcommands.add_parser("init", help="Create the private data directory and SQLite schema")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = Settings.from_env()
    if args.command == "api":
        import uvicorn

        from .api import create_app

        uvicorn.run(
            create_app(settings),
            host=settings.bind_host,
            port=settings.bind_port,
            access_log=False,
            log_level="info",
        )
        return 0
    if args.command == "worker":
        from .worker import run_worker

        run_worker(settings)
        return 0
    if args.command == "verify-models":
        try:
            report = verify_model_manifest(
                settings.model_cache_dir,
                settings.approved_model_manifest_path,
            ).public_dict()
        except ModelManifestError as exc:
            report = exc.public_dict()
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["ready"] is True else 1

    runtime = build_runtime(settings)
    if args.command == "check":
        report = readiness(settings)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["status"] in {"ready", "degraded_ready"} else 1
    if args.command == "purge-expired":
        purged = runtime.store.purge_expired(
            delete_files=runtime.storage.delete_job_tree,
            limit=1000,
        )
        purged.extend(
            runtime.store.purge_stale_unfinished(
                stale_before=datetime.now(timezone.utc)
                - timedelta(hours=settings.max_active_job_hours),
                delete_files=runtime.storage.delete_job_tree,
                limit=1000,
            )
        )
        wal_checkpointed = runtime.store.checkpoint_wal()
        print(
            json.dumps(
                {
                    "purged_jobs": len(purged),
                    "wal_checkpointed": wal_checkpointed,
                }
            )
        )
        return 0
    if args.command == "init":
        print(json.dumps({"status": "initialized", **settings.public_dict()}))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
