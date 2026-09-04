from __future__ import annotations

from fastapi.testclient import TestClient

from case_intelligence.generation import UnavailableGenerator
from case_intelligence.malware_scan import MalwareScanResult, MalwareScannerStatus
from case_intelligence.managed_storage import StoragePolicy
from case_intelligence.workbench import create_workbench_app


ACTOR = "development-taylor-morgan"


class UnavailableCountingScanner:
    def __init__(self) -> None:
        self.status_calls = 0
        self.scan_calls = 0

    def status(self, *, force: bool = False) -> MalwareScannerStatus:
        del force
        self.status_calls += 1
        return MalwareScannerStatus(
            "unavailable",
            "synthetic",
            message="Synthetic scanner is unavailable.",
        )

    def scan(self, _path) -> MalwareScanResult:
        self.scan_calls += 1
        return MalwareScanResult("unavailable", "synthetic")


class ReadyCountingScanner(UnavailableCountingScanner):
    def status(self, *, force: bool = False) -> MalwareScannerStatus:
        del force
        self.status_calls += 1
        return MalwareScannerStatus("ready", "synthetic")


def _matter(client: TestClient, name: str = "Synthetic preflight matter") -> str:
    response = client.post(
        "/matters",
        data={"name": name, "descriptor": "Generated loose-file preflight acceptance"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return response.headers["location"].split("/")[2]


def _app(tmp_path, scanner: UnavailableCountingScanner):
    return create_workbench_app(
        tmp_path / "runtime",
        generator=UnavailableGenerator(),
        auth_mode="test",
        background_ingestion=False,
        storage_policy=StoragePolicy(
            matter_quota_bytes=1_024,
            upload_session_bytes=512,
            media_file_bytes=256,
            document_file_bytes=128,
            reserve_bytes=0,
        ),
        malware_scanner=scanner,
        malware_scan_mode="extended",
    )


def test_selection_preflight_accounts_for_every_file_without_durable_writes(tmp_path):
    scanner = UnavailableCountingScanner()
    app = _app(tmp_path, scanner)
    with TestClient(app) as client:
        slug = _matter(client)
        bench = client.app.state.workbench
        matter = bench.matter(slug, ACTOR)
        before_collections = bench.workspace.source_collections(matter.matter_id)
        before_sessions = bench.workspace.recent_upload_sessions(matter.matter_id, ACTOR)
        before_reserved = bench.workspace.pending_upload_bytes(matter.matter_id)
        before_status_calls = scanner.status_calls

        response = client.post(
            f"/matters/{slug}/upload-preflight",
            json={
                "files": [
                    {
                        "name": "incident-notes.txt",
                        "relative_path": "ready/incident-notes.txt",
                        "size": 23,
                        "media_type": "text/plain",
                    },
                    {
                        "name": "damaged.pdf",
                        "relative_path": "ready/damaged.pdf",
                        "size": 19,
                        "media_type": "application/pdf",
                    },
                    {
                        "name": "scan.png",
                        "relative_path": "attention/scan.png",
                        "size": 68,
                        "media_type": "image/png",
                    },
                    {
                        "name": "messages.zip",
                        "relative_path": "unsupported/messages.zip",
                        "size": 4,
                        "media_type": "application/zip",
                    },
                    {
                        "name": "oversize.txt",
                        "relative_path": "over-limit/oversize.txt",
                        "size": 129,
                        "media_type": "text/plain",
                    },
                ]
            },
        )

        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        payload = response.json()
        assert payload["status"] == "partial"
        assert payload["selected_count"] == 5
        assert payload["counts"] == {
            "valid": 2,
            "needs_attention": 1,
            "unsupported": 1,
            "duplicate_candidate": 0,
            "over_limit": 1,
            "failed": 0,
        }
        assert [item["state"] for item in payload["items"]] == [
            "valid",
            "valid",
            "needs_attention",
            "unsupported",
            "over_limit",
        ]
        assert payload["eligible_indexes"] == [0, 1]
        assert payload["items"][0] == {
            "index": 0,
            "display_name": "incident-notes.txt",
            "state": "valid",
            "eligible": True,
            "supplied_type": "text/plain",
            "expected_type": "text/plain",
            "detected_type": None,
            "size": 23,
            "readability": "pending_upload",
            "source_version": "pending_upload",
            "scan": {
                "required": False,
                "capability": "not_required",
                "result": "not_required",
            },
            "duplicate": "not_evaluated",
            "message": "Ready to upload. File contents will be checked after transfer.",
        }
        assert payload["items"][2]["scan"] == {
            "required": True,
            "capability": "unavailable",
            "result": "not_run",
        }
        assert "not run" in payload["items"][2]["message"].lower()
        assert payload["items"][3]["expected_type"] is None
        assert payload["items"][3]["detected_type"] is None
        assert payload["items"][3]["size"] == 4
        assert scanner.status_calls == before_status_calls + 1
        assert scanner.scan_calls == 0
        assert bench.workspace.source_collections(matter.matter_id) == before_collections
        assert bench.workspace.recent_upload_sessions(matter.matter_id, ACTOR) == before_sessions
        assert bench.workspace.pending_upload_bytes(matter.matter_id) == before_reserved
        preflight_event = next(
            event
            for event in bench.workspace.audit_events(matter.matter_id)
            if event.action == "source.upload_preflight"
        )
        assert preflight_event.details == {"count": 5, "result_count": 2}


def test_selection_preflight_minimizes_unsafe_names_and_marks_repeated_paths(tmp_path):
    scanner = UnavailableCountingScanner()
    app = _app(tmp_path, scanner)
    with TestClient(app) as client:
        slug = _matter(client)
        escaped = "../private/secret.txt"
        response = client.post(
            f"/matters/{slug}/upload-preflight",
            json={
                "files": [
                    {
                        "name": "secret.txt",
                        "relative_path": escaped,
                        "size": 12,
                        "media_type": escaped,
                    },
                    {"name": "copy.txt", "relative_path": "Batch/record.txt", "size": 12},
                    {"name": "copy.txt", "relative_path": "batch/RECORD.txt", "size": 12},
                ]
            },
        )

        assert response.status_code == 200
        assert escaped not in response.text
        payload = response.json()
        assert [item["state"] for item in payload["items"]] == [
            "failed",
            "valid",
            "duplicate_candidate",
        ]
        assert payload["items"][0]["display_name"] == "Selected file 1"
        assert payload["items"][2]["duplicate"] == "selection_collision"
        assert payload["eligible_indexes"] == [1]
        assert scanner.scan_calls == 0


def test_selection_preflight_keeps_scan_policy_on_duplicate_and_over_limit_rows(tmp_path):
    scanner = UnavailableCountingScanner()
    app = _app(tmp_path, scanner)
    with TestClient(app) as client:
        slug = _matter(client)
        before_status_calls = scanner.status_calls
        response = client.post(
            f"/matters/{slug}/upload-preflight",
            json={
                "files": [
                    {"name": "scan.png", "relative_path": "Batch/scan.png", "size": 68},
                    {"name": "SCAN.png", "relative_path": "batch/SCAN.png", "size": 68},
                    {"name": "large.png", "relative_path": "large.png", "size": 129},
                ]
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert [item["state"] for item in payload["items"]] == [
            "needs_attention",
            "duplicate_candidate",
            "over_limit",
        ]
        assert all(
            item["scan"]
            == {
                "required": True,
                "capability": "unavailable",
                "result": "not_run",
            }
            for item in payload["items"]
        )
        assert scanner.status_calls == before_status_calls + 1
        assert scanner.scan_calls == 0


def test_selection_preflight_is_matter_scoped_and_never_claims_a_completed_scan(tmp_path):
    scanner = ReadyCountingScanner()
    app = _app(tmp_path, scanner)
    with TestClient(app) as client:
        slug = _matter(client)
        other = client.app.state.workbench.create_matter(
            "Other synthetic matter",
            "Isolation canary",
            "development-jordan-lee",
        )

        before_hidden_status_calls = scanner.status_calls
        hidden = client.post(
            f"/matters/{other.slug}/upload-preflight",
            json={"files": [{"name": "scan.png", "size": 68}]},
        )
        assert scanner.status_calls == before_hidden_status_calls
        before_allowed_status_calls = scanner.status_calls
        allowed = client.post(
            f"/matters/{slug}/upload-preflight",
            json={
                "files": [
                    {
                        "name": "scan.png",
                        "relative_path": "scan.png",
                        "size": 68,
                        "media_type": "image/png",
                    }
                ]
            },
        )

        assert hidden.status_code == 404
        assert allowed.status_code == 200
        item = allowed.json()["items"][0]
        assert item["state"] == "valid"
        assert item["scan"] == {
            "required": True,
            "capability": "ready",
            "result": "not_run",
        }
        assert item["detected_type"] is None
        assert item["source_version"] == "pending_upload"
        assert item["duplicate"] == "not_evaluated"
        assert scanner.status_calls == before_allowed_status_calls + 1
        assert scanner.scan_calls == 0


def test_selection_preflight_fails_closed_for_empty_or_malformed_entries(tmp_path):
    scanner = UnavailableCountingScanner()
    app = _app(tmp_path, scanner)
    with TestClient(app) as client:
        slug = _matter(client)
        response = client.post(
            f"/matters/{slug}/upload-preflight",
            json={
                "files": [
                    {"name": "empty.txt", "size": 0},
                    {"name": "missing-size.txt"},
                    ["not", "an", "object"],
                ]
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "blocked"
        assert payload["counts"]["failed"] == 3
        assert payload["eligible_indexes"] == []
        assert all(item["eligible"] is False for item in payload["items"])
        assert scanner.scan_calls == 0


def test_setup_exposes_review_before_upload_and_no_script_fallback(tmp_path):
    scanner = UnavailableCountingScanner()
    app = _app(tmp_path, scanner)
    with TestClient(app) as client:
        slug = _matter(client)
        response = client.get(f"/matters/{slug}/setup")

    assert response.status_code == 200
    assert f'data-preflight-url="/matters/{slug}/upload-preflight"' in response.text
    assert 'data-upload-preflight' in response.text
    assert 'data-upload-preflight-items' in response.text
    assert 'data-upload-preflight-confirm' in response.text
    assert "Review selected files" in response.text
    assert "Upload 0 ready files" in response.text
    assert "Without JavaScript, selected files use the retained direct upload path." in response.text
