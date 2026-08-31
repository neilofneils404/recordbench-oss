"""Durable, bounded background answering for the case workbench."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from .workspace_store import AnswerJobRecord, WorkspaceStore


@dataclass(frozen=True)
class AnswerResult:
    content: str
    payload: Mapping[str, object]
    citations: Sequence[object] = ()


class AnswerJobFailure(RuntimeError):
    """Expected staff-safe terminal failure for one answer attempt."""


class _AnswerCancelled(RuntimeError):
    pass


StageReporter = Callable[[str, str], None]
CancellationProbe = Callable[[], bool]
AnswerProcessor = Callable[
    [AnswerJobRecord, StageReporter, CancellationProbe], AnswerResult
]
AnswerFinisher = Callable[[AnswerJobRecord, AnswerResult], object]


class AnswerCoordinator:
    """Claim fair SQLite jobs and run grounded answering outside HTTP threads."""

    def __init__(
        self,
        workspace: WorkspaceStore,
        *,
        process: AnswerProcessor,
        finish: AnswerFinisher | None = None,
        workers: int = 2,
    ) -> None:
        self.workspace = workspace
        self.process = process
        self.finish = finish or (
            lambda job, result: self.workspace.finish_answer_job(
                job.job_id,
                content=result.content,
                payload=result.payload,
            )
        )
        self.worker_count = min(max(int(workers), 1), 4)
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._threads: list[threading.Thread] = []
        self.workspace.recover_running_answer_jobs()
        for ordinal in range(1, self.worker_count + 1):
            thread = threading.Thread(
                target=self._run,
                name=f"case-answer-{ordinal}",
                args=(f"answer-worker-{ordinal}",),
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
            job = self.workspace.claim_answer_job(worker_id)
            if job is None:
                self._wake.wait(timeout=0.5)
                self._wake.clear()
                continue
            self._process(job)

    def _process(self, job: AnswerJobRecord) -> None:
        def cancelled() -> bool:
            return self.workspace.answer_cancellation_requested(job.job_id)

        def stage(stage_key: str, message: str) -> None:
            if cancelled() or not self.workspace.update_answer_job_stage(
                job.job_id, stage_key, message
            ):
                raise _AnswerCancelled()

        try:
            if cancelled():
                raise _AnswerCancelled()
            result = self.process(job, stage, cancelled)
            if cancelled():
                raise _AnswerCancelled()
            self.finish(job, result)
        except _AnswerCancelled:
            self._finish_failure(job, "Answer cancelled.")
        except AnswerJobFailure as exc:
            self._finish_failure(job, str(exc))
        except Exception:
            self._finish_failure(
                job,
                "The answer could not be completed. Search and source review still work; try again.",
            )

    def _finish_failure(self, job: AnswerJobRecord, message: str) -> None:
        try:
            self.workspace.fail_answer_job(job.job_id, message[:240])
        except Exception:
            pass
