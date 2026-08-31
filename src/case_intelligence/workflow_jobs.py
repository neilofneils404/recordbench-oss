"""Durable coordinators for multi-pass research and every-source review."""
from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from .workspace_store import (
    ResearchJobRecord,
    ReviewDecisionRecord,
    ReviewRunRecord,
    WorkspaceStore,
)


class WorkflowFailure(RuntimeError):
    """Expected staff-safe terminal workflow failure."""


class _WorkflowCancelled(RuntimeError):
    pass


ResearchProcessor = Callable[
    [ResearchJobRecord, Callable[[], bool]], Mapping[str, object]
]


@dataclass(frozen=True)
class ReviewDecisionResult:
    decision: str
    rationale: str
    citations: Sequence[Mapping[str, object]] = ()
    error_message: str = ""


ReviewProcessor = Callable[
    [ReviewRunRecord, ReviewDecisionRecord, Callable[[], bool]], ReviewDecisionResult
]


class ResearchCoordinator:
    """Fairly claim durable research jobs outside request threads."""

    def __init__(
        self,
        workspace: WorkspaceStore,
        *,
        process: ResearchProcessor,
        workers: int = 1,
    ) -> None:
        self.workspace = workspace
        self.process = process
        self.worker_count = min(max(int(workers), 1), 2)
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._threads: list[threading.Thread] = []
        self.workspace.recover_running_research_jobs()
        for ordinal in range(1, self.worker_count + 1):
            thread = threading.Thread(
                target=self._run,
                name=f"recordbench-research-{ordinal}",
                args=(f"research-worker-{ordinal}",),
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

    def notify(self) -> None:
        self._wake.set()

    def close(self) -> None:
        self._stop.set()
        self._wake.set()
        for thread in self._threads:
            thread.join(timeout=2)

    def _run(self, worker_id: str) -> None:
        while not self._stop.is_set():
            job = self.workspace.claim_research_job(worker_id)
            if job is None:
                self._wake.wait(timeout=0.5)
                self._wake.clear()
                continue
            cancelled = lambda: self.workspace.research_cancellation_requested(job.job_id)
            try:
                if cancelled():
                    raise _WorkflowCancelled()
                result = self.process(job, cancelled)
                if cancelled():
                    raise _WorkflowCancelled()
                self.workspace.finish_research_job(job.job_id, result)
            except _WorkflowCancelled:
                self._fail(job.job_id, "Research cancelled.")
            except WorkflowFailure as exc:
                self._fail(job.job_id, str(exc))
            except Exception:
                self._fail(
                    job.job_id,
                    "Research could not be completed. Saved sources and earlier runs are unchanged; try again.",
                )

    def _fail(self, job_id: str, message: str) -> None:
        try:
            self.workspace.fail_research_job(job_id, message[:240])
        except Exception:
            pass


class ReviewCoordinator:
    """Review frozen populations with bounded batching and per-source isolation."""

    def __init__(
        self,
        workspace: WorkspaceStore,
        *,
        process: ReviewProcessor,
        workers: int = 1,
        source_concurrency: int = 2,
    ) -> None:
        self.workspace = workspace
        self.process = process
        # Full review is intentionally conservative on a shared single host.
        self.worker_count = min(max(int(workers), 1), 2)
        self.source_concurrency = min(max(int(source_concurrency), 1), 2)
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._threads: list[threading.Thread] = []
        self.workspace.recover_running_review_runs()
        for ordinal in range(1, self.worker_count + 1):
            thread = threading.Thread(
                target=self._run,
                name=f"recordbench-full-review-{ordinal}",
                args=(f"review-worker-{ordinal}",),
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

    def notify(self) -> None:
        self._wake.set()

    def close(self) -> None:
        self._stop.set()
        self._wake.set()
        for thread in self._threads:
            thread.join(timeout=2)

    def _run(self, worker_id: str) -> None:
        while not self._stop.is_set():
            run = self.workspace.claim_review_run(worker_id)
            if run is None:
                self._wake.wait(timeout=0.5)
                self._wake.clear()
                continue
            self._process_run(run)

    def _process_run(self, run: ReviewRunRecord) -> None:
        cancelled = lambda: (
            self._stop.is_set()
            or self.workspace.review_cancellation_requested(run.run_id)
        )
        try:
            with ThreadPoolExecutor(
                max_workers=self.source_concurrency,
                thread_name_prefix=f"recordbench-source-{run.run_id[-8:]}",
            ) as executor:
                while not self._stop.is_set():
                    if cancelled():
                        raise _WorkflowCancelled()
                    batch = self.workspace.pending_review_decisions(
                        run.run_id, limit=self.source_concurrency
                    )
                    if not batch:
                        break
                    futures: dict[Future[ReviewDecisionResult], ReviewDecisionRecord] = {
                        executor.submit(self.process, run, decision, cancelled): decision
                        for decision in batch
                    }
                    for future in as_completed(futures):
                        decision = futures[future]
                        try:
                            result = future.result()
                        except _WorkflowCancelled:
                            raise
                        except WorkflowFailure:
                            if cancelled():
                                raise _WorkflowCancelled()
                            raise
                        except Exception:
                            result = ReviewDecisionResult(
                                "needs_attention",
                                "This source could not be classified automatically.",
                                (),
                                "Source-level review failed; other sources continued.",
                            )
                        self.workspace.record_review_decision(
                            run.run_id,
                            decision.document_id,
                            decision=result.decision,
                            rationale=result.rationale,
                            citations=result.citations,
                            error_message=result.error_message,
                        )
            if self._stop.is_set() or cancelled():
                raise _WorkflowCancelled()
            self.workspace.finish_review_run(run.run_id)
        except _WorkflowCancelled:
            self._fail(run.run_id, "Review cancelled.")
        except WorkflowFailure as exc:
            self._fail(run.run_id, str(exc))
        except Exception:
            self._fail(
                run.run_id,
                "Full review could not continue. Saved source decisions are preserved and the run can be resumed.",
            )

    def _fail(self, run_id: str, message: str) -> None:
        try:
            self.workspace.fail_review_run(run_id, message[:240])
        except Exception:
            pass
