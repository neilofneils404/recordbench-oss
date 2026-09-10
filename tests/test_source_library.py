from __future__ import annotations

import re
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from case_intelligence.generation import UnavailableGenerator
from case_intelligence.malware_scan import MalwareScanResult
from case_intelligence.pilot_uploads import (
    MAX_UPLOAD_INTAKE_ITEMS,
    MAX_UPLOAD_SESSION_ITEMS,
)
from case_intelligence.workbench import create_workbench_app


ACTOR = "development-taylor-morgan"


class DetectedScanner:
    def scan(self, _path):
        return MalwareScanResult(
            "infected", "synthetic", signature="Synthetic.Detection.Check"
        )


class EvidenceEchoGenerator:
    available = True

    def generate(self, **kwargs):
        evidence = kwargs["evidence"]
        if not evidence:
            return {
                "answerable": False,
                "claims": [],
                "limitation": None,
                "missing_information": "No support was found.",
            }
        return {
            "answerable": True,
            "claims": [
                {
                    "text": evidence[0].excerpt,
                    "evidence_ids": [evidence[0].evidence_id],
                }
            ],
            "limitation": None,
            "missing_information": "",
        }


def _matter(client: TestClient, name: str = "Synthetic source library") -> str:
    response = client.post(
        "/matters",
        data={"name": name, "descriptor": "Generated large-matter acceptance"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return response.headers["location"].split("/")[2]


def _wait_ready(client: TestClient, slug: str, expected: int) -> None:
    bench = client.app.state.workbench
    matter = bench.matter(slug, ACTOR)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        ready = sum(
            document.state == "ready"
            for document in bench.source_store(matter).documents.values()
        )
        if ready == expected:
            return
        time.sleep(0.01)
    raise AssertionError("source processing did not finish")


def test_one_thousand_sources_are_grouped_and_only_one_page_is_rendered(tmp_path):
    app = create_workbench_app(
        tmp_path / "runtime", generator=UnavailableGenerator(), auth_mode="test"
    )
    with TestClient(app) as client:
        slug = _matter(client)
        bench = client.app.state.workbench
        matter = bench.matter(slug, ACTOR)
        store = bench.source_store(matter)
        sources = tuple(
            SimpleNamespace(
                relative_path=f"Production {ordinal // 100:02d}/record-{ordinal:04d}.txt",
                display_name=f"record-{ordinal:04d}.txt",
                media_type="text/plain",
                byte_size=64,
                stable_device=1,
                stable_inode=ordinal + 1,
                stable_mtime_ns=1_700_000_000_000_000_000 + ordinal,
            )
            for ordinal in range(1_000)
        )
        store.register_linked_sources(
            source_location_id="generated-review-share", sources=sources
        )

        overview = client.get(f"/matters/{slug}/setup")
        assert overview.status_code == 200
        assert "1,000 sources" in overview.text  # Aggregate readiness, never 1,000 rows.
        assert "1000 total" in overview.text
        assert overview.text.count('name="selected"') == 8
        assert "A short working view, not the complete receipt" in overview.text

        first_page = client.get(
            f"/matters/{slug}/setup",
            params={"view": "list", "page_size": 50, "page": 1},
        )
        assert first_page.status_code == 200
        assert first_page.text.count('name="selected"') == 50
        assert "Page 1 of 20" in first_page.text
        assert "1–50 of 1000" in first_page.text
        assert 'class="upload-zone' not in first_page.text
        assert "Upload sources" in first_page.text
        assert '<select name="kind">' in first_page.text
        assert 'page_size=100#source-library' in first_page.text

        last_page = client.get(
            f"/matters/{slug}/setup",
            params={"view": "list", "page_size": 50, "page": 20},
        )
        assert last_page.status_code == 200
        assert last_page.text.count('name="selected"') == 50
        assert "951–1000 of 1000" in last_page.text

        library = bench.source_library(matter, view="list", page=7, page_size=50)
        assert library.stats == {
            "total": 1_000,
            "ready": 0,
            "processing": 1_000,
            "attention": 0,
            "reviewed": 0,
            "flagged": 0,
        }
        assert len(library.items) == 50
        assert library.page == 7

        def full_inventory_forbidden(_matter):
            raise AssertionError("Matter Home must not build the complete manifest row set")

        bench._source_rows = full_inventory_forbidden
        home = client.get(f"/matters/{slug}/home")
        assert home.status_code == 200
        assert "Pick up where you left off" in home.text
        assert "Review queue" in home.text
        assert "1000 processing" in home.text


def test_ten_thousand_catalog_rows_remain_bounded_but_exceed_one_intake_batch(tmp_path):
    app = create_workbench_app(
        tmp_path / "runtime",
        generator=UnavailableGenerator(),
        auth_mode="test",
        background_ingestion=False,
    )
    with TestClient(app) as client:
        slug = _matter(client, "Synthetic ten-thousand source catalog")
        bench = client.app.state.workbench
        matter = bench.matter(slug, ACTOR)
        store = bench.source_store(matter)
        sources = tuple(
            SimpleNamespace(
                relative_path=f"Batch {ordinal // 1_000:02d}/record-{ordinal:05d}.txt",
                display_name=f"record-{ordinal:05d}.txt",
                media_type="text/plain",
                byte_size=64,
                stable_device=1,
                stable_inode=ordinal + 1,
                stable_mtime_ns=1_700_000_000_000_000_000 + ordinal,
            )
            for ordinal in range(10_000)
        )
        store.register_linked_sources(
            source_location_id="generated-ten-thousand", sources=sources
        )

        def full_inventory_forbidden(_matter):
            raise AssertionError("Paged catalog routes must not build every source row")

        bench._source_rows = full_inventory_forbidden
        home = client.get(f"/matters/{slug}/home")
        page = client.get(
            f"/matters/{slug}/setup",
            params={"view": "list", "page_size": 50, "page": 200},
        )
        assert home.status_code == 200
        assert "10000 processing" in home.text
        assert page.status_code == 200
        assert page.text.count('name="selected"') == 50
        assert "Page 200 of 200" in page.text
        assert "9951–10000 of 10000" in page.text
        assert MAX_UPLOAD_SESSION_ITEMS == 2_000

        def full_catalog_replacement_forbidden(*_args, **_kwargs):
            raise AssertionError("One source transition must not rebuild 10,000 catalog rows")

        bench.workspace.replace_source_catalog = full_catalog_replacement_forbidden
        changed = next(iter(store.documents.values()))
        store.mark_failed(changed.document_id, "Generated transition")
        projected = bench.workspace.source_catalog_record(
            matter.matter_id, changed.document_id
        )
        assert projected is not None
        assert projected.source_state == "failed"
        assert bench.workspace.source_catalog_page(
            matter.matter_id, limit=1
        ).stats["total"] == 10_000


def test_resumable_upload_offsets_finalize_review_and_range_content(tmp_path):
    app = create_workbench_app(
        tmp_path / "runtime",
        generator=UnavailableGenerator(),
        auth_mode="test",
        background_ingestion=True,
        ingestion_workers=1,
    )
    with TestClient(app) as client:
        slug = _matter(client)
        body = b"alpha notebook entry\nbeta line\n"
        manifest = {
            "collection_name": "Synthetic Batch 01",
            "files": [
                {
                    "name": "notes.txt",
                    "relative_path": "Witness/notes.txt",
                    "size": len(body),
                    "media_type": "text/plain",
                }
            ],
        }
        created = client.post(f"/matters/{slug}/upload-sessions", json=manifest)
        assert created.status_code == 201
        session = created.json()
        item = session["items"][0]

        first = client.put(
            item["chunk_url"],
            content=body[:7],
            headers={
                "Content-Type": "application/octet-stream",
                "X-Upload-Offset": "0",
            },
        )
        assert first.status_code == 200
        assert first.json()["items"][0]["received_size"] == 7

        wrong = client.put(
            item["chunk_url"],
            content=body[7:10],
            headers={
                "Content-Type": "application/octet-stream",
                "X-Upload-Offset": "0",
            },
        )
        assert wrong.status_code == 409
        assert "byte 7" in wrong.json()["message"]

        resumed = client.post(
            f"/matters/{slug}/upload-sessions",
            json={**manifest, "resume_session_id": session["upload_session_id"]},
        )
        assert resumed.status_code == 200
        assert resumed.json()["upload_session_id"] == session["upload_session_id"]
        assert resumed.json()["items"][0]["received_size"] == 7

        completed = client.put(
            item["chunk_url"],
            content=body[7:],
            headers={
                "Content-Type": "application/octet-stream",
                "X-Upload-Offset": "7",
            },
        )
        assert completed.status_code == 200
        item = completed.json()["items"][0]
        assert item["state"] == "uploaded"
        finalized = client.post(item["finalize_url"])
        assert finalized.status_code == 200
        assert finalized.json()["state"] == "complete"
        assert finalized.json()["queued_count"] == 1
        _wait_ready(client, slug, 1)

        bench = client.app.state.workbench
        matter = bench.matter(slug, ACTOR)
        document = next(iter(bench.source_store(matter).documents.values()))
        token = bench.source_store(matter).action_token(document)
        review = client.get(f"/matters/{slug}/sources/{token}")
        assert review.status_code == 200
        assert "alpha notebook entry" in review.text
        assert "Synthetic Batch 01" in review.text
        assert "Ask using this source" in review.text
        focused = client.post(
            f"/matters/{slug}/sources/{token}/ask", follow_redirects=False
        )
        assert focused.status_code == 303
        assert "source_set=source-set-" in focused.headers["location"]
        focused_workspace = client.get(focused.headers["location"])
        assert focused_workspace.status_code == 200
        focused_id = re.search(
            r"source_set=(source-set-[0-9a-f]{32})", focused.headers["location"]
        ).group(1)
        assert f'value="{focused_id}" selected' in focused_workspace.text
        assert "Only · Witness/notes.txt (1)" in focused_workspace.text
        reused = client.post(
            f"/matters/{slug}/sources/{token}/ask", follow_redirects=False
        )
        assert reused.headers["location"] == focused.headers["location"]
        assert len(bench.workspace.source_sets(matter.matter_id)) == 1
        ranged = client.get(
            f"/matters/{slug}/sources/{token}/content",
            headers={"Range": "bytes=0-4"},
        )
        assert ranged.status_code == 206
        assert ranged.content == b"alpha"
        assert ranged.headers["content-range"] == f"bytes 0-4/{len(body)}"


def test_upload_resume_mismatch_is_generic_and_write_free(tmp_path):
    app = create_workbench_app(
        tmp_path / "runtime",
        generator=UnavailableGenerator(),
        auth_mode="test",
        background_ingestion=True,
    )
    with TestClient(app) as client:
        first_slug = _matter(client, "First synthetic resume matter")
        second_slug = _matter(client, "Second synthetic resume matter")
        manifest = {
            "collection_name": "Synthetic resumable batch",
            "files": [
                {
                    "name": "notes.txt",
                    "relative_path": "Production/notes.txt",
                    "size": 12,
                    "media_type": "text/plain",
                }
            ],
        }
        created = client.post(f"/matters/{first_slug}/upload-sessions", json=manifest)
        assert created.status_code == 201
        session = created.json()
        workspace = client.app.state.workbench.workspace

        def durable_state(slug: str):
            matter = client.app.state.workbench.matter(slug, ACTOR)
            return (
                workspace.source_collections(matter.matter_id),
                workspace.recent_upload_sessions(matter.matter_id, ACTOR),
                workspace.pending_upload_bytes(matter.matter_id),
            )

        cases = (
            (
                second_slug,
                {**manifest, "resume_session_id": session["upload_session_id"]},
            ),
            (
                first_slug,
                {
                    **manifest,
                    "resume_session_id": "upload-session-ffffffffffffffffffffffffffffffff",
                },
            ),
            (
                first_slug,
                {
                    **manifest,
                    "resume_session_id": session["upload_session_id"],
                    "files": [{**manifest["files"][0], "size": 13}],
                },
            ),
            (
                first_slug,
                {
                    **manifest,
                    "resume_session_id": session["upload_session_id"],
                    "collection_id": "source-collection-ffffffffffffffffffffffffffffffff",
                },
            ),
        )
        for slug, payload in cases:
            before = durable_state(slug)
            response = client.post(f"/matters/{slug}/upload-sessions", json=payload)
            assert response.status_code == 409
            assert response.json() == {
                "code": "upload_resume_mismatch",
                "message": "The saved upload no longer matches this reviewed selection.",
            }
            assert durable_state(slug) == before

        cancelled = client.post(session["cancel_url"])
        assert cancelled.status_code == 200
        before_cancelled_resume = durable_state(first_slug)
        response = client.post(
            f"/matters/{first_slug}/upload-sessions",
            json={**manifest, "resume_session_id": session["upload_session_id"]},
        )
        assert response.status_code == 409
        assert response.json()["code"] == "upload_resume_mismatch"
        assert durable_state(first_slug) == before_cancelled_resume


def test_upload_metadata_caps_duplicates_and_actor_matter_scope(tmp_path):
    app = create_workbench_app(
        tmp_path / "runtime",
        generator=UnavailableGenerator(),
        auth_mode="test",
        background_ingestion=True,
    )
    with TestClient(app) as client:
        first_slug = _matter(client, "First generated upload matter")
        second_slug = _matter(client, "Second generated upload matter")
        files = [
            {
                "name": f"record-{ordinal:04d}.txt",
                "relative_path": f"Batch/record-{ordinal:04d}.txt",
                "size": 1,
                "media_type": "text/plain",
            }
            for ordinal in range(2_000)
        ]
        accepted = client.post(
            f"/matters/{first_slug}/upload-sessions",
            json={"collection_name": "Two thousand metadata rows", "files": files},
        )
        assert accepted.status_code == 201
        session = accepted.json()
        assert session["item_count"] == 2_000

        first_item = session["items"][0]
        delta = client.put(
            first_item["chunk_url"],
            content=b"x",
            headers={
                "Content-Type": "application/octet-stream",
                "X-Upload-Offset": "0",
            },
        )
        assert delta.status_code == 200
        assert delta.json()["delta"] is True
        assert len(delta.json()["items"]) == 1
        assert delta.json()["items"][0]["received_size"] == 1
        compact = client.get(f"{session['status_url']}?compact=1")
        assert compact.status_code == 200
        assert compact.json()["delta"] is True
        assert compact.json()["items"] == []
        assert compact.json()["item_count"] == 2_000

        next_batch = client.post(
            f"/matters/{first_slug}/upload-sessions",
            json={
                "collection_name": "Ignored for a continued collection",
                "collection_id": session["collection_id"],
                "files": [
                    {
                        "name": "record-2000.txt",
                        "relative_path": "Batch/record-2000.txt",
                        "size": 1,
                        "media_type": "text/plain",
                    }
                ],
            },
        )
        assert next_batch.status_code == 201
        continued = next_batch.json()
        assert continued["collection_id"] == session["collection_id"]
        matter = client.app.state.workbench.matter(first_slug, ACTOR)
        assert len(
            client.app.state.workbench.workspace.source_collections(matter.matter_id)
        ) == 1

        repeated_between_batches = client.post(
            f"/matters/{first_slug}/upload-sessions",
            json={
                "collection_id": session["collection_id"],
                "files": [files[0]],
            },
        )
        assert repeated_between_batches.status_code == 400
        assert "already in this upload collection" in repeated_between_batches.json()[
            "message"
        ]

        hidden = client.get(
            f"/matters/{second_slug}/upload-sessions/{session['upload_session_id']}"
        )
        assert hidden.status_code == 404

        duplicate = client.post(
            f"/matters/{first_slug}/upload-sessions",
            json={
                "collection_name": "Duplicate paths",
                "files": [files[0], dict(files[0])],
            },
        )
        assert duplicate.status_code == 400
        assert "relative path twice" in duplicate.json()["message"]

        too_many = client.post(
            f"/matters/{first_slug}/upload-sessions",
            json={"collection_name": "Too many", "files": files + [files[0]]},
        )
        assert too_many.status_code == 413

        cancelled = client.post(session["cancel_url"])
        assert cancelled.status_code == 200
        assert cancelled.json()["state"] == "cancelled"
        assert client.post(continued["cancel_url"]).status_code == 200

        workspace = client.app.state.workbench.workspace
        other = workspace.upsert_principal(
            "test", "generated-other-user", "Other User", "other.user"
        )
        with pytest.raises(KeyError):
            workspace.upload_session(
                matter.matter_id, other.principal_id, session["upload_session_id"]
            )


def test_ten_thousand_upload_metadata_rows_share_one_bounded_collection(tmp_path):
    app = create_workbench_app(
        tmp_path / "runtime",
        generator=UnavailableGenerator(),
        auth_mode="test",
        background_ingestion=True,
    )
    with TestClient(app) as client:
        slug = _matter(client, "Generated ten-thousand upload intake")
        collection_id = ""
        sessions = []
        for batch in range(MAX_UPLOAD_INTAKE_ITEMS // MAX_UPLOAD_SESSION_ITEMS):
            start = batch * MAX_UPLOAD_SESSION_ITEMS
            files = [
                {
                    "name": f"record-{ordinal:05d}.txt",
                    "relative_path": f"Production/record-{ordinal:05d}.txt",
                    "size": 1,
                    "media_type": "text/plain",
                }
                for ordinal in range(start, start + MAX_UPLOAD_SESSION_ITEMS)
            ]
            response = client.post(
                f"/matters/{slug}/upload-sessions",
                json={
                    "collection_name": "Generated production",
                    "collection_id": collection_id,
                    "files": files,
                },
            )
            assert response.status_code == 201
            projection = response.json()
            collection_id = projection["collection_id"]
            sessions.append(projection)

        bench = client.app.state.workbench
        matter = bench.matter(slug, ACTOR)
        assert len(sessions) == 5
        assert {session["collection_id"] for session in sessions} == {collection_id}
        assert sum(session["item_count"] for session in sessions) == 10_000
        assert len(bench.workspace.source_collections(matter.matter_id)) == 1
        assert bench.workspace.pending_upload_bytes(matter.matter_id) == 10_000

        for session in sessions:
            assert client.post(session["cancel_url"]).status_code == 200


def test_bulk_review_collections_and_scoped_answer_exclude_other_sources(tmp_path):
    generator = EvidenceEchoGenerator()
    app = create_workbench_app(
        tmp_path / "runtime", generator=generator, auth_mode="test", answer_workers=1
    )
    with TestClient(app) as client:
        slug = _matter(client)
        uploaded = client.post(
            f"/matters/{slug}/uploads",
            files=[
                (
                    "files",
                    (
                        "included.txt",
                        b"The notebook records the synthetic ALPHA-ONLY event.\n",
                        "text/plain",
                    ),
                ),
                (
                    "files",
                    (
                        "excluded.txt",
                        b"The notebook records the synthetic VIOLET-EXCLUDED canary.\n",
                        "text/plain",
                    ),
                ),
            ],
        )
        assert uploaded.status_code == 200
        bench = client.app.state.workbench
        matter = bench.matter(slug, ACTOR)
        rows = {row.name: row for row in bench.sources(matter)}

        flagged = client.post(
            f"/matters/{slug}/sources/bulk",
            data={"selected": rows["included.txt"].action_token, "action": "flagged"},
            follow_redirects=False,
        )
        assert flagged.status_code == 303
        assert next(
            item
            for item in bench.sources(matter)
            if item.name == "included.txt"
        ).review_state == "flagged"

        source_set = bench.workspace.create_source_set(
            matter.matter_id,
            "Notebook subset",
            (rows["included.txt"].document_id,),
            ACTOR,
        )
        scoped = bench.search(
            matter,
            "notebook synthetic event",
            document_ids=bench.workspace.source_set_document_ids(
                matter.matter_id, source_set.source_set_id
            ),
        )
        assert scoped
        assert {citation.source_name for citation in scoped} == {"included.txt"}
        assert all("VIOLET-EXCLUDED" not in citation.excerpt for citation in scoped)

        conversation = bench.workspace.get_conversation(matter.matter_id)
        submitted = client.post(
            f"/matters/{slug}/ask",
            data={
                "conversation": conversation.conversation_id,
                "question": "What event does the notebook record?",
                "request_key": "answer-request-" + "8" * 32,
                "source_set": source_set.source_set_id,
            },
            headers={"Accept": "application/json"},
        )
        assert submitted.status_code == 202
        job = submitted.json()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and job["state"] not in {
            "succeeded",
            "failed",
        }:
            time.sleep(0.01)
            job = client.get(job["status_url"]).json()
        assert job["state"] == "succeeded"
        messages = bench.workspace.messages(
            matter.matter_id, conversation.conversation_id
        )
        answer = messages[-1]
        assert "ALPHA-ONLY" in answer.content
        assert "VIOLET-EXCLUDED" not in answer.content
        assert answer.payload["source_scope"] == "Notebook subset"

        second_slug = _matter(client, "Scoped cross-matter denial")
        second_matter = bench.matter(second_slug, ACTOR)
        second_conversation = bench.workspace.get_conversation(second_matter.matter_id)
        denied = client.post(
            f"/matters/{second_slug}/ask",
            data={
                "conversation": second_conversation.conversation_id,
                "question": "What does the source say?",
                "request_key": "answer-request-" + "9" * 32,
                "source_set": source_set.source_set_id,
            },
            headers={"Accept": "application/json"},
        )
        assert denied.status_code == 409
        assert "empty or no longer available" in denied.json()["message"]


def test_invalid_resumable_signature_fails_without_queuing(tmp_path):
    app = create_workbench_app(
        tmp_path / "runtime",
        generator=UnavailableGenerator(),
        auth_mode="test",
        background_ingestion=True,
    )
    with TestClient(app) as client:
        slug = _matter(client)
        body = b"not-a-real-pdf"
        created = client.post(
            f"/matters/{slug}/upload-sessions",
            json={
                "collection_name": "Invalid source",
                "files": [
                    {
                        "name": "invalid.pdf",
                        "relative_path": "invalid.pdf",
                        "size": len(body),
                        "media_type": "application/pdf",
                    }
                ],
            },
        ).json()
        item = created["items"][0]
        uploaded = client.put(
            item["chunk_url"],
            content=body,
            headers={
                "Content-Type": "application/octet-stream",
                "X-Upload-Offset": "0",
            },
        )
        assert uploaded.status_code == 200
        failed = client.post(item["finalize_url"])
        assert failed.status_code == 400
        assert "valid PDF" in failed.json()["message"]
        status = client.get(created["status_url"]).json()
        assert status["state"] == "partial"
        assert status["failed_count"] == 1
        assert status["queued_count"] == 0


def test_detected_resumable_upload_is_terminal_after_quarantine_move(tmp_path):
    app = create_workbench_app(
        tmp_path / "runtime",
        generator=UnavailableGenerator(),
        auth_mode="test",
        background_ingestion=True,
        malware_scanner=DetectedScanner(),
        malware_scan_mode="extended",
    )
    with TestClient(app) as client:
        slug = _matter(client, "Generated detection ledger")
        body = b"generated,detection\n"
        created = client.post(
            f"/matters/{slug}/upload-sessions",
            json={
                "collection_name": "Detection check",
                "files": [
                    {
                        "name": "generated-check.csv",
                        "relative_path": "generated-check.csv",
                        "size": len(body),
                        "media_type": "text/csv",
                    }
                ],
            },
        ).json()
        item = created["items"][0]
        uploaded = client.put(
            item["chunk_url"],
            content=body,
            headers={
                "Content-Type": "application/octet-stream",
                "X-Upload-Offset": "0",
            },
        )
        assert uploaded.status_code == 200
        failed = client.post(item["finalize_url"])
        assert failed.status_code == 422
        assert "isolated" in failed.json()["message"]
        status = client.get(created["status_url"]).json()
        assert status["state"] == "partial"
        assert status["failed_count"] == 1
        assert status["queued_count"] == 0
        assert status["items"][0]["state"] == "failed"
        assert "isolated" in status["items"][0]["message"]
        bench = client.app.state.workbench
        matter = bench.matter(slug, ACTOR)
        assert bench.source_store(matter).malware_scan_status()["quarantined"] == 1


def test_source_removal_and_direct_grant_removal_have_distinct_labels(tmp_path):
    app = create_workbench_app(
        tmp_path / 'runtime', generator=UnavailableGenerator(), auth_mode='test'
    )
    with TestClient(app) as client:
        slug = _matter(client)
        bench = app.state.workbench
        matter = bench.matter(slug, ACTOR)
        source_store = bench.source_store(matter)
        source_store.register_linked_sources(source_location_id='synthetic-share', sources=(
            SimpleNamespace(relative_path='synthetic.txt', display_name='synthetic.txt',
                media_type='text/plain', byte_size=64, stable_device=1, stable_inode=1,
                stable_mtime_ns=1_700_000_000_000_000_000),
        ))
        document = next(iter(source_store.documents.values()))
        source_store.mark_failed(document.document_id, "Synthetic preparation failure")
        workspace = app.state.workbench.workspace
        person = workspace.upsert_principal('test', 'synthetic-teammate', 'Synthetic Teammate', 'synthetic-teammate')
        workspace.add_member(matter.matter_id, person.principal_id, ACTOR)
        response = client.get(f'/matters/{slug}/setup?view=list')
        assert response.status_code == 200
        forms = dict(re.findall(r'<form[^>]*action="([^"]+)"[^>]*>(.*?)</form>',
                                response.text, flags=re.S))
        source_forms = [body for action, body in forms.items()
                        if '/sources/' in action and action.endswith('/remove')]
        assert len(source_forms) == 1
        assert re.search(r'<button[^>]*>Remove</button>', source_forms[0])
        assert 'Remove direct grant' not in source_forms[0]
        member_form = forms[f'/matters/{slug}/members/{person.principal_id}/remove']
        assert re.search(r'<button[^>]*>Remove direct grant</button>', member_form)
