"""Controlled-clock checks of the existing temporary-workspace policy."""
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest

from case_intelligence.generation import UnavailableGenerator
from case_intelligence.workbench import CaseIntelligenceWorkbench
from tests.test_matter_retention_and_themes import FIXED, _principals


@pytest.mark.parametrize(
    ("age", "status", "due"),
    [(15, "scheduled", False), (16, "warning", False),
     (30, "grace", False), (36, "grace", False), (37, "due", True)],
)
def test_warning_grace_and_due_boundaries(tmp_path, monkeypatch, age, status, due):
    monkeypatch.setenv("CASE_INTELLIGENCE_MAINTENANCE_ENABLED", "0")
    bench = CaseIntelligenceWorkbench(tmp_path / "runtime", generator=UnavailableGenerator(),
                                      learned_retrieval=False)
    try:
        bench.workspace._clock = lambda: FIXED
        _principals(bench.workspace)
        matter = bench.create_matter("Synthetic scheduled review", "", "principal-owner",
                                     retention_days=30)
        bench.workspace._clock = lambda: FIXED + timedelta(days=age)
        projection = bench.retention_projection(matter)
        assert projection["status"] == status
        assert projection["show_warning"] == (status != "scheduled")
        assert bool(bench.workspace.due_matter_retentions()) is due
        # Merely reaching expiry/grace does not itself claim or close the matter.
        assert bench.workspace.matter_lifecycle(matter.matter_id).state == "active"
    finally:
        bench.close()


def test_extension_horizon_rolls_forward_beyond_original_creation(tmp_path, monkeypatch):
    monkeypatch.setenv("CASE_INTELLIGENCE_MAINTENANCE_ENABLED", "0")
    bench = CaseIntelligenceWorkbench(tmp_path / "runtime", generator=UnavailableGenerator(),
                                      learned_retrieval=False)
    try:
        now = [FIXED]
        bench.workspace._clock = lambda: now[0]
        _principals(bench.workspace)
        matter = bench.create_matter("Synthetic continuing review", "", "principal-owner",
                                     retention_days=30)
        for elapsed_days in (0, 300, 600):
            now[0] = FIXED + timedelta(days=elapsed_days)
            projection = bench.retention_projection(matter)
            assert projection["maximum_date"] == (
                now[0].astimezone(ZoneInfo("America/New_York")).date() + timedelta(days=365)
            ).isoformat()
            schedule = bench.retention_for_date(matter, "principal-owner",
                                               projection["maximum_date"])
            assert bench._parse_utc(schedule.purge_after) - bench._parse_utc(
                schedule.expires_at
            ) == timedelta(days=7)
            assert bench.workspace.due_matter_retentions() == ()
        assert bench._parse_utc(schedule.expires_at) > FIXED + timedelta(days=900)
    finally:
        bench.close()
