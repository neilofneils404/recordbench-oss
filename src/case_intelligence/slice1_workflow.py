from __future__ import annotations

from dataclasses import dataclass

from .inventory import InventoryOutcome, InventoryService
from .jobs import JobService
from .retrieval import RetrievalService, SearchRequest, SearchResponse


@dataclass(frozen=True)
class IntakeResult:
    inventory: InventoryOutcome
    derived_job_ids: tuple[str, ...]


class Slice1Workflow:
    """Staff-shaped local seam; transport and generation deliberately absent."""

    def __init__(self, inventory: InventoryService, jobs: JobService,
                 retrieval: RetrievalService) -> None:
        self.inventory = inventory
        self.jobs = jobs
        self.retrieval = retrieval

    def intake(self, matter_id: str, source_location_id: str,
               idempotency_key: str) -> IntakeResult:
        outcome = self.inventory.inventory(matter_id, source_location_id, idempotency_key)
        completed: list[str] = []
        while job_id := self.jobs.run_next(matter_id):
            completed.append(job_id)
        return IntakeResult(outcome, tuple(completed))

    def search(self, actor_id: str, request: SearchRequest) -> SearchResponse:
        return self.retrieval.search(actor_id, request)
