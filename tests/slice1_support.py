from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from case_intelligence.contracts import Matter, MatterState
from case_intelligence.inventory import InventoryService
from case_intelligence.isolation import MatterAccess, MatterStateRegistry
from case_intelligence.sqlite_store import SQLiteStore

FIXTURE = Path(__file__).parent / "fixtures/synthetic/slice1-intake/v1"
NOW = datetime(2026, 8, 25, 20, 0, tzinfo=timezone.utc)


def make_environment(tmp_path):
    roots = {}
    for name in ("alpha", "bravo"):
        target = tmp_path / name
        shutil.copytree(FIXTURE / f"matter-{name}" / "input", target)
        roots[name] = target
    registry = MatterStateRegistry([
        Matter(matter_id="matter-alpha", display_name="Synthetic Alpha", state=MatterState.ACTIVE),
        Matter(matter_id="matter-bravo", display_name="Synthetic Bravo", state=MatterState.ACTIVE),
    ])
    store = SQLiteStore(tmp_path / "catalog.sqlite")
    inventory = InventoryService(store, registry, clock=lambda: NOW)
    for name in ("alpha", "bravo"):
        matter = f"matter-{name}"
        location = f"location-{name}"
        store.register_matter(matter, f"Synthetic {name.title()}")
        inventory.register_location(matter, location, f"Synthetic {name.title()} input",
                                    roots[name], f"\\\\synthetic\\{name}")
    access = MatterAccess({"actor-alpha": {"matter-alpha"}, "actor-bravo": {"matter-bravo"}})
    return store, registry, inventory, access, roots
