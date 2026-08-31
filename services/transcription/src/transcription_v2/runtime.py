"""Construction of v2-owned runtime resources."""

from __future__ import annotations

from dataclasses import dataclass

from .settings import Settings
from .storage import FileStorage
from .store import SQLiteJobStore


@dataclass(frozen=True, slots=True)
class Runtime:
    settings: Settings
    store: SQLiteJobStore
    storage: FileStorage


def build_runtime(settings: Settings | None = None) -> Runtime:
    selected = settings or Settings.from_env()
    selected.prepare_runtime()
    return Runtime(
        settings=selected,
        store=SQLiteJobStore(selected.database_path),
        storage=FileStorage(selected.data_root, chunk_size=selected.upload_chunk_bytes),
    )

