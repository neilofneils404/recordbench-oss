from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ControlStateRepository(Protocol):
    """Narrow repository/unit-of-work boundary used by Slice 1A services."""

    path: Path

    def transaction(self, *, immediate: bool = False): ...
    def register_matter(self, matter_id: str, display_name: str) -> None: ...
    def close(self) -> None: ...
