from __future__ import annotations

from email.message import EmailMessage
from concurrent.futures import ThreadPoolExecutor
import html
import re
import io
import time
import threading
import zipfile

import pytest
from fastapi.testclient import TestClient

from case_intelligence.extended_extract import EMAIL_COVERAGE_NOTICE, extract_email
from case_intelligence.workbench import create_workbench_app
from tests.test_review_tools import ACTOR, CleanScanner, _matter


def generated_email(kind="message"):
    outer = EmailMessage()
    outer["From"] = "sender@example.test"
    outer["To"] = "reader@example.test"
    outer["Subject"] = "Generated attachment coverage"
    outer.set_content("ParentBodyCanary describes the generated meeting.")
    inner = EmailMessage()
    inner["Subject"] = "Generated attached message"
    inner.set_content("AttachmentOnlyCanary describes a different event.")
    if kind == "related":
        outer.clear_content()
        outer.set_type("multipart/related")
        outer.set_param("type", "text/html")
        root = EmailMessage()
        root.set_content("<p>ParentBodyCanary describes the generated meeting.</p>", subtype="html")
        root["Content-ID"] = "<body@example.test>"
        resource = EmailMessage()
        resource.set_content("AttachmentOnlyCanary")
        resource["Content-ID"] = "<resource@example.test>"
        resource["Content-Disposition"] = "inline"
        outer.attach(root)
        outer.attach(resource)
    elif kind.startswith("message/"):
        outer.make_mixed()
        encapsulated = EmailMessage()
        encapsulated.set_type(kind)
        encapsulated.set_payload([inner])
        outer.attach(encapsulated)
    elif kind == "message":
        outer.add_attachment(inner, filename="forwarded.eml")
    elif kind == "multipart":
        inner.add_alternative("<p>HiddenHtmlCanary</p>", subtype="html")
        inner["Content-Disposition"] = 'attachment; filename="bundle.mime"'
        outer.make_mixed()
        outer.attach(inner)
    elif kind == "unnamed":
        outer.add_attachment(b"AttachmentOnlyCanary", maintype="application", subtype="octet-stream")
    elif kind == "inline":
        outer.make_mixed()
        part = EmailMessage()
        part.set_content(b"AttachmentOnlyCanary", maintype="image", subtype="png")
        part["Content-Disposition"] = "inline"
        outer.attach(part)
    else:
        outer.add_attachment("AttachmentOnlyCanary", filename="notes.txt")
    return outer.as_bytes()


@pytest.mark.parametrize("kind,name", [("message", "forwarded.eml"), ("multipart", "bundle.mime"), ("unnamed", "unnamed"), ("inline", "unnamed"), ("text", "notes.txt"), ("related", "unnamed")])
def test_attachment_boundaries_and_explicit_inventory(tmp_path, kind, name):
    path = tmp_path / "generated.eml"
    path.write_bytes(generated_email(kind))
    sections = extract_email(path)
    text = "\n".join(section.text for section in sections)
    assert "ParentBodyCanary" in text
    assert "AttachmentOnlyCanary" not in text
    assert "HiddenHtmlCanary" not in text
    assert f"Attachment: {name}" in text
    assert "Attachment contents were not processed or searched" in text


@pytest.mark.parametrize("subtype", ["rfc822", "global", "news", "partial", "http", "external-body", "x-generated"])
def test_unnamed_encapsulated_message_subtypes_stay_out_of_parent(tmp_path, subtype):
    path = tmp_path / "generated.eml"
    path.write_bytes(generated_email("message/" + subtype))
    text = "\n".join(section.text for section in extract_email(path))
    assert "ParentBodyCanary" in text
    assert "AttachmentOnlyCanary" not in text
    assert f"Attachment: unnamed (message/{subtype})" in text
    assert "Attachment contents were not processed or searched" in text


def test_malformed_multipart_is_not_reported_as_ready(tmp_path):
    path = tmp_path / "broken.eml"
    path.write_bytes(b'Subject: Generated broken email\r\nContent-Type: multipart/mixed; boundary="missing"\r\n\r\nUnbounded body\r\n')
    with pytest.raises(ValueError, match="malformed"):
        extract_email(path)


def test_mime_and_body_limits_apply_beneath_attachment_boundaries(tmp_path, monkeypatch):
    import case_intelligence.extended_extract as module

    path = tmp_path / "generated.eml"
    path.write_bytes(generated_email())
    monkeypatch.setattr(module, "MAX_EMAIL_PARTS", 3)
    with pytest.raises(ValueError, match="too many MIME parts"):
        extract_email(path)
    monkeypatch.setattr(module, "MAX_EMAIL_PARTS", 500)
    monkeypatch.setattr(module, "MAX_EMAIL_BODY_BYTES", 8)
    with pytest.raises(ValueError, match="email body exceeds"):
        extract_email(path)


def test_html_alternative_and_unattached_message_text(tmp_path):
    message = EmailMessage()
    message["Subject"] = "Generated body alternatives"
    message.set_content("PlainBodyCanary")
    message.add_alternative("<p>AlternativeHtmlCanary</p>", subtype="html")
    path = tmp_path / "generated.eml"
    path.write_bytes(message.as_bytes())
    text = "\n".join(section.text for section in extract_email(path))
    assert "PlainBodyCanary" in text and "AlternativeHtmlCanary" not in text
    assert "Attachment:" not in text
    html = EmailMessage()
    html.set_content("<p>StandaloneHtmlCanary</p>", subtype="html")
    path.write_bytes(html.as_bytes())
    assert "StandaloneHtmlCanary" in extract_email(path)[0].text


class EvidenceEchoGenerator:
    available = True

    def generate(self, **kwargs):
        evidence = kwargs["evidence"]
        return {
            "answerable": bool(evidence),
            "claims": [{"text": evidence[0].excerpt, "evidence_ids": [evidence[0].evidence_id]}] if evidence else [],
            "limitation": None,
            "missing_information": "" if evidence else "No matching support.",
        }


@pytest.mark.parametrize("email_kind", ["message", "related", "message/news"])
def test_uploaded_email_search_answer_export_and_matter_boundaries(tmp_path, email_kind):
    app = create_workbench_app(tmp_path / "runtime", generator=EvidenceEchoGenerator(),
        auth_mode="test", malware_scanner=CleanScanner(), malware_scan_mode="extended")
    with TestClient(app) as client:
        slug = _matter(client, "Generated email attachment review")
        bench = app.state.workbench
        matter = bench.matter(slug, ACTOR)
        response = client.post(f"/matters/{slug}/uploads", files=[("files", ("generated.eml", generated_email(email_kind), "message/rfc822"))])
        assert response.status_code == 200
        store = bench.source_store(matter)
        document = next(iter(store.documents.values()))
        identity = document.document_id, document.version_id
        token = store.action_token(document)
        source = client.get(f"/matters/{slug}/sources/{token}")
        assert source.status_code == 200
        assert EMAIL_COVERAGE_NOTICE in source.text
        assert ("forwarded.eml" if email_kind == "message" else "Attachment: unnamed") in source.text
        assert "Attachment contents were not processed or searched" in source.text
        body = client.get(f"/matters/{slug}/sources/{token}?unit=2")
        assert "ParentBodyCanary" in body.text and "AttachmentOnlyCanary" not in body.text
        readiness = bench.workspace.matter_readiness(matter.matter_id)
        assert readiness.email_count == 1 and readiness.can_query and readiness.partial_query
        assert readiness.attention_count == 0
        search = client.get(f"/matters/{slug}", params={"mode": "search", "q": "AttachmentOnlyCanary"})
        assert EMAIL_COVERAGE_NOTICE in search.text
        assert 'class="search-result' not in search.text
        assert "No matching record found" in search.text
        conversation = bench.workspace.get_conversation(matter.matter_id)
        response = client.post(f"/matters/{slug}/ask", data={"conversation": conversation.conversation_id,
            "question": "What does ParentBodyCanary describe?", "request_key": "answer-request-" + "a" * 32},
            headers={"Accept": "application/json"})
        assert response.status_code == 202
        deadline = time.monotonic() + 10
        status_url = response.json()["status_url"]
        while True:
            status = client.get(status_url).json()
            if status["state"] in {"succeeded", "failed", "cancelled"}:
                break
            assert time.monotonic() < deadline
            time.sleep(.02)
        assert status["state"] == "succeeded"
        answer = bench.workspace.messages(matter.matter_id, conversation.conversation_id)[-1]
        assert answer.payload["source_coverage"]["notice"] == EMAIL_COVERAGE_NOTICE
        assert answer.payload["source_coverage"]["mode"] == "partial"
        assert answer.payload["source_coverage"]["excluded_count"] == 0
        root = f"/matters/{slug}/conversations/{conversation.conversation_id}"
        for route in [root + "/export", root + f"/messages/{answer.message_id}/export"]:
            exported = client.get(route, params={"format": "markdown"})
            assert exported.status_code == 200 and EMAIL_COVERAGE_NOTICE in exported.text
            docx = client.get(route, params={"format": "docx"})
            assert docx.status_code == 200
            with zipfile.ZipFile(io.BytesIO(docx.content)) as archive:
                assert EMAIL_COVERAGE_NOTICE in archive.read("word/document.xml").decode()
        reloaded = client.get(f"/matters/{slug}", params={"conversation": conversation.conversation_id})
        assert EMAIL_COVERAGE_NOTICE in reloaded.text
        foreign_slug = _matter(client, "Generated email boundary canary")
        foreign = bench.matter(foreign_slug, ACTOR)
        assert bench.workspace.matter_readiness(foreign.matter_id).email_count == 0
        assert client.get(f"/matters/{foreign_slug}/sources/{token}").status_code == 404
        assert client.get(root.replace(slug, foreign_slug) + "/export").status_code == 404
        assert (document.document_id, document.version_id) == identity


@pytest.mark.parametrize("report_type", ["delivery-status", "disposition-notification", "feedback-report", "x-generated-report"])
@pytest.mark.parametrize("explicit_attachment", [False, True])
def test_structured_delivery_report_is_not_an_invented_attachment(tmp_path, report_type, explicit_attachment):
    headers = 'Content-Disposition: attachment; filename="status.dat"\r\n' if explicit_attachment else ''
    details = ("Reporting-MTA: dns; mail.example.test\r\n\r\n"
        "Final-Recipient: rfc822; reader@example.test\r\nAction: failed\r\nStatus: 5.1.1\r\n")
    if report_type == "disposition-notification":
        details = ("Final-Recipient: rfc822; reader@example.test\r\n"
            "Disposition: manual-action/MDN-sent-manually; displayed\r\n")
    raw = (f'Subject: Generated delivery report\r\nMIME-Version: 1.0\r\n'
        f'Content-Type: multipart/report; report-type="{report_type}"; boundary="generated"\r\n\r\n'
        '--generated\r\nContent-Type: text/plain\r\n\r\nGeneratedDeliveryBodyCanary.\r\n'
        f'--generated\r\nContent-Type: message/{report_type}\r\n{headers}\r\n{details}'
        '\r\n--generated--\r\n')
    path = tmp_path / "generated-report.eml"
    path.write_bytes(raw.encode())
    text = "\n".join(section.text for section in extract_email(path))
    assert "GeneratedDeliveryBodyCanary" in text
    assert "Attachment: unnamed" not in text
    assert ("Attachment: status.dat" in text) is explicit_attachment
    assert ("Attachment contents were not processed" in text) is explicit_attachment


def test_investigation_retains_email_and_source_coverage_in_results_and_exports(tmp_path):
    app = create_workbench_app(tmp_path / "runtime", generator=EvidenceEchoGenerator(),
        auth_mode="test", malware_scanner=CleanScanner(), malware_scan_mode="extended")
    with TestClient(app) as client:
        slug = _matter(client, "Generated email investigation")
        bench = app.state.workbench
        matter = bench.matter(slug, ACTOR)
        uploaded = client.post(f"/matters/{slug}/uploads", files=[
            ("files", ("generated.eml", generated_email(), "message/rfc822")),
            ("files", ("damaged.pdf", b"%PDF-1.4\nGenerated damaged document.\n%%EOF\n", "application/pdf")),
        ])
        assert uploaded.status_code == 200
        workspace_page = client.get(f"/matters/{slug}")
        store = bench.source_store(matter)
        email = next(document for document in store.documents.values() if document.media_type == "message/rfc822")
        source_page = client.get(f"/matters/{slug}/sources/{store.action_token(email)}")
        coverage_links = re.findall(r'data-(?:conversation|assistant)-coverage-action href="([^"]+)"', workspace_page.text + source_page.text)
        assert len(coverage_links) == 2
        for link in coverage_links:
            assert "status=attention" not in link
            library = client.get(html.unescape(link))
            assert library.status_code == 200
            assert "generated.eml" in library.text and "damaged.pdf" in library.text
        conversation = bench.workspace.get_conversation(matter.matter_id)
        started = client.post(f"/matters/{slug}/ask", data={
            "conversation": conversation.conversation_id,
            "question": "What does ParentBodyCanary describe?", "review_task": "research",
            "request_key": "answer-request-" + "b" * 32,
        }, follow_redirects=False)
        assert started.status_code == 303
        job_id = bench.workspace.research_jobs(matter.matter_id, ACTOR)[0].job_id
        deadline = time.monotonic() + 10
        while True:
            job = bench.workspace.research_job(matter.matter_id, ACTOR, job_id)
            if job.state in {"succeeded", "failed", "cancelled"}:
                break
            assert time.monotonic() < deadline
            time.sleep(.02)
        assert job.state == "succeeded"
        coverage = job.result["coverage"]
        assert EMAIL_COVERAGE_NOTICE in coverage["notice"]
        assert "1 source needs attention" in coverage["notice"]
        assert "did not check every source" in coverage["notice"]
        assert coverage["excluded_count"] == 1
        page = client.get(f"/matters/{slug}/research", params={"job": job_id})
        assert EMAIL_COVERAGE_NOTICE in page.text
        for format_name in ("markdown", "json", "docx"):
            exported = client.get(f"/matters/{slug}/research/{job_id}/export", params={"format": format_name})
            assert exported.status_code == 200
            if format_name == "docx":
                with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
                    text = archive.read("word/document.xml").decode()
            else:
                text = exported.text
            assert EMAIL_COVERAGE_NOTICE in text and "did not check every source" in text
        bundle = client.get(f"/matters/{slug}/export")
        assert bundle.status_code == 200
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            entries = [name for name in archive.namelist() if name.startswith("investigations/")]
            assert entries and all(EMAIL_COVERAGE_NOTICE in archive.read(name).decode() for name in entries)
        foreign = _matter(client, "Generated investigation boundary")
        assert client.get(f"/matters/{foreign}/research/{job_id}/export?format=json").status_code == 404


@pytest.mark.parametrize("root_kind", ["first", "start", "named", "alternative"])
def test_related_root_is_selected_without_reading_other_text_resources(tmp_path, root_kind):
    from email.parser import BytesParser
    from email import policy
    message = BytesParser(policy=policy.default).parsebytes(generated_email("related"))
    root, resource = message.get_payload()
    if root_kind == "start":
        message.set_payload([resource, root])
        message.set_param("start", "<body@example.test>")
    elif root_kind == "named":
        root["Content-Disposition"] = 'inline; filename="body.html"'
    elif root_kind == "alternative":
        alternative = EmailMessage()
        alternative.set_content("ParentBodyCanary plain alternative.")
        alternative.add_alternative("<p>ParentBodyCanary HTML alternative.</p>", subtype="html")
        alternative["Content-ID"] = "<body@example.test>"
        message.set_payload([alternative, resource])
        message.set_param("type", "multipart/alternative")
    path = tmp_path / "related.eml"
    path.write_bytes(message.as_bytes())
    text = "\n".join(section.text for section in extract_email(path))
    assert "ParentBodyCanary" in text
    assert "AttachmentOnlyCanary" not in text
    assert "Attachment: unnamed (text/plain)" in text
    assert "Attachment: body.html" not in text


@pytest.mark.parametrize("invalid_root", ["missing", "ambiguous", "empty", "whitespace"])
def test_unresolvable_related_root_is_not_guessed(tmp_path, invalid_root):
    from email.parser import BytesParser
    from email import policy
    message = BytesParser(policy=policy.default).parsebytes(generated_email("related"))
    message.set_param("start", "<absent@example.test>" if invalid_root == "missing" else "<body@example.test>")
    if invalid_root in {"empty", "whitespace"}:
        message.set_param("start", "" if invalid_root == "empty" else "   ")
    if invalid_root == "ambiguous":
        resource = message.get_payload()[1]
        resource.replace_header("Content-ID", "<body@example.test>")
    path = tmp_path / "related.eml"
    path.write_bytes(message.as_bytes())
    with pytest.raises(ValueError, match="message body"):
        extract_email(path)


@pytest.mark.parametrize("encoded_body", ["UGFyZW50Qm9keUNhbmFyeQ==!", "UGFyZW50Qm9keUNhbmFyeQ"])
def test_invalid_base64_body_uses_processing_recovery(tmp_path, encoded_body):
    raw = ("Subject: Generated damaged encoding\r\nContent-Type: text/plain; charset=utf-8\r\n"
        "Content-Transfer-Encoding: base64\r\n\r\n" + encoded_body + "\r\n").encode()
    path = tmp_path / "generated.eml"
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="malformed"):
        extract_email(path)


@pytest.mark.parametrize("late_kind", ["email", "text"])
def test_investigation_refreshes_coverage_after_upload_between_live_passes(tmp_path, monkeypatch, late_kind):
    app = create_workbench_app(tmp_path / "runtime", generator=EvidenceEchoGenerator(),
        auth_mode="test", malware_scanner=CleanScanner(), malware_scan_mode="extended")
    first_pass = threading.Event()
    continue_search = threading.Event()
    with TestClient(app) as client:
        slug = _matter(client, "Generated changing investigation coverage")
        bench = app.state.workbench
        matter = bench.matter(slug, ACTOR)
        initial = client.post(f"/matters/{slug}/uploads", files=[
            ("files", ("generated.txt", b"ParentBodyCanary describes the generated meeting.", "text/plain")),
        ])
        assert initial.status_code == 200
        assert bench.workspace.matter_readiness(matter.matter_id).email_count == 0
        original_search = bench._answer_search

        def pause_after_first_pass(*args, **kwargs):
            found = original_search(*args, **kwargs)
            if not first_pass.is_set():
                first_pass.set()
                assert continue_search.wait(10), "Concurrent upload did not finish"
            return found

        monkeypatch.setattr(bench, "_answer_search", pause_after_first_pass)
        conversation = bench.workspace.get_conversation(matter.matter_id)
        started = client.post(f"/matters/{slug}/ask", data={
            "conversation": conversation.conversation_id,
            "question": "What does ParentBodyCanary describe?", "review_task": "research",
            "request_key": "answer-request-" + "e" * 32,
        }, follow_redirects=False)
        assert started.status_code == 303
        try:
            assert first_pass.wait(10)
            added = client.post(f"/matters/{slug}/uploads", files=[
                ("files", ("generated.eml", generated_email(), "message/rfc822") if late_kind == "email" else
                    ("late.txt", b"ParentBodyCanary describes a later generated meeting.", "text/plain")),
            ])
            assert added.status_code == 200
        finally:
            continue_search.set()
        job_id = bench.workspace.research_jobs(matter.matter_id, ACTOR)[0].job_id
        deadline = time.monotonic() + 10
        while True:
            job = bench.workspace.research_job(matter.matter_id, ACTOR, job_id)
            if job.state in {"succeeded", "failed", "cancelled"}:
                break
            assert time.monotonic() < deadline
            time.sleep(.02)
        assert job.state == "succeeded"
        store = bench.source_store(matter)
        email = next(document for document in store.documents.values() if document.display_name == ("generated.eml" if late_kind == "email" else "late.txt"))
        email_evidence = [item for item in job.result["evidence"] if item["document_id"] == email.document_id]
        assert email_evidence
        for item in email_evidence:
            assert item["source_version_id"] == email.version_id
            support = bench.support(matter, item["support_token"])
            assert support.source_name == email.display_name
        coverage = job.result["coverage"]
        assert coverage["mode"] == "partial"
        assert coverage["searchable_count"] == 2 and coverage["total_count"] == 2
        assert coverage["excluded_count"] == 0
        assert "changed after the search started" in coverage["notice"]
        notice = EMAIL_COVERAGE_NOTICE if late_kind == "email" else "changed after the search started"
        assert notice in coverage["notice"]
        page = client.get(f"/matters/{slug}/research", params={"job": job_id})
        # The ledger spans an availability change, so details must hide its
        # findings even though the retained export records partial coverage.
        assert "Saved findings and search proposals are no longer current" in page.text
        for format_name in ("markdown", "json", "docx"):
            exported = client.get(f"/matters/{slug}/research/{job_id}/export", params={"format": format_name})
            assert exported.status_code == 200
            if format_name == "docx":
                with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
                    assert notice in archive.read("word/document.xml").decode()
            else:
                assert notice in exported.text
        bundle = client.get(f"/matters/{slug}/export")
        assert bundle.status_code == 200
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            entries = [name for name in archive.namelist() if name.startswith("investigations/")]
            assert entries and all(notice in archive.read(name).decode() for name in entries)


@pytest.mark.parametrize("answer_mode", ["queued", "synchronous"])
def test_answer_coverage_includes_email_uploaded_before_live_retrieval(tmp_path, monkeypatch, answer_mode):
    app = create_workbench_app(tmp_path / "runtime", generator=EvidenceEchoGenerator(),
        auth_mode="test", malware_scanner=CleanScanner(), malware_scan_mode="extended")
    before_search = threading.Event()
    continue_search = threading.Event()
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        slug = _matter(client, "Generated changing answer coverage")
        bench = app.state.workbench
        matter = bench.matter(slug, ACTOR)
        uploaded = client.post(f"/matters/{slug}/uploads", files=[
            ("files", ("generated.txt", b"InitialSourceCanary contains unrelated housekeeping.", "text/plain")),
        ])
        assert uploaded.status_code == 200
        assert bench.workspace.matter_readiness(matter.matter_id).email_count == 0
        original_search = bench._answer_search

        def pause_before_retrieval(*args, **kwargs):
            before_search.set()
            assert continue_search.wait(10), "Concurrent upload did not finish"
            return original_search(*args, **kwargs)

        monkeypatch.setattr(bench, "_answer_search", pause_before_retrieval)
        conversation = bench.workspace.get_conversation(matter.matter_id)
        question = "What does ParentBodyCanary describe?"
        if answer_mode == "queued":
            started = client.post(f"/matters/{slug}/ask", data={
                "conversation": conversation.conversation_id, "question": question,
                "request_key": "answer-request-" + "f" * 32,
            }, headers={"Accept": "application/json"})
            assert started.status_code == 202
        else:
            future = executor.submit(bench.ask, matter, conversation, question)
        try:
            assert before_search.wait(10)
            added = client.post(f"/matters/{slug}/uploads", files=[
                ("files", ("generated.eml", generated_email(), "message/rfc822")),
            ])
            assert added.status_code == 200
        finally:
            continue_search.set()
        if answer_mode == "queued":
            deadline = time.monotonic() + 10
            while True:
                status = client.get(started.json()["status_url"]).json()
                if status["state"] in {"succeeded", "failed", "cancelled"}:
                    break
                assert time.monotonic() < deadline
                time.sleep(.02)
            assert status["state"] == "succeeded"
            answer = bench.workspace.messages(matter.matter_id, conversation.conversation_id)[-1]
        else:
            answer = future.result(timeout=10)
        assert answer.role == "assistant" and "ParentBodyCanary" in answer.content
        citations = [citation for claim in answer.payload["claims"] for citation in claim["citations"]]
        assert any(item["source_name"] == "generated.eml" for item in citations)
        for item in citations:
            assert bench.support(matter, item["support_token"]).source_name == item["source_name"]
        coverage = answer.payload["source_coverage"]
        assert coverage["mode"] == "partial"
        assert coverage["searchable_count"] == 2 and coverage["total_count"] == 2
        assert EMAIL_COVERAGE_NOTICE in coverage["notice"]
        root = f"/matters/{slug}/conversations/{conversation.conversation_id}"
        for route in [root + "/export", root + f"/messages/{answer.message_id}/export"]:
            for format_name in ("markdown", "docx"):
                exported = client.get(route, params={"format": format_name})
                assert exported.status_code == 200
                if format_name == "docx":
                    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
                        assert EMAIL_COVERAGE_NOTICE in archive.read("word/document.xml").decode()
                else:
                    assert EMAIL_COVERAGE_NOTICE in exported.text


@pytest.mark.parametrize('header', [b'Content-Type: message', b'Content-Disposition: attachment; filename', b'Content-Transfer-Encoding: base64 junk'])
def test_malformed_mime_classification_header_uses_processing_recovery(tmp_path, header):
    path = tmp_path / 'generated.eml'
    path.write_bytes(b'Content-Type: multipart/mixed; boundary="generated"\r\n\r\n'
        b'--generated\r\nContent-Type: text/plain\r\n\r\nParentBodyCanary\r\n'
        b'--generated\r\n' + header + b'\r\n\r\nSubject: AttachedCanary\r\n\r\n'
        b'AttachmentOnlyCanary\r\n--generated--\r\n')
    with pytest.raises(ValueError, match='malformed'):
        extract_email(path)


@pytest.mark.parametrize('source_change,answer_mode,pause_stage', [
    (change, mode, stage)
    for change in ('add', 'swap', 'pending', 'scope')
    for mode, stage in (('queued', 'generation'), ('synchronous', 'generation'), ('research', 'generation'), ('queued', 'finishing'), ('research', 'finishing'))
    if change != 'scope' or mode != 'synchronous'
] + [('scope', 'queued', 'before_search'), ('scope', 'research', 'before_search')])
def test_late_upload_during_final_generation_is_not_claimed_as_searched(tmp_path, monkeypatch, answer_mode, source_change, pause_stage):
    app = create_workbench_app(tmp_path / 'runtime', generator=EvidenceEchoGenerator(),
        auth_mode='test', malware_scanner=CleanScanner(), malware_scan_mode='extended',
        background_ingestion=source_change == 'pending', ingestion_workers=1)
    generating = threading.Event()
    continue_generation = threading.Event()
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        slug = _matter(client, 'Generated late source availability')
        bench = app.state.workbench
        matter = bench.matter(slug, ACTOR)
        assert client.post(f'/matters/{slug}/uploads', files=[
            ('files', ('initial.txt', b'ParentBodyCanary describes a generated meeting.', 'text/plain')),
        ]).status_code == 200
        if source_change == 'pending':
            deadline = time.monotonic() + 10
            while not bench.workspace.matter_readiness(matter.matter_id).can_query:
                assert time.monotonic() < deadline
                time.sleep(.02)
        if source_change == 'swap':
            assert client.post(f'/matters/{slug}/uploads', files=[
                ('files', ('unused.txt', b'Unrelated housekeeping instructions only.', 'text/plain')),
            ]).status_code == 200
            store = bench.source_store(matter)
            unused = next(item for item in store.documents.values() if item.display_name == 'unused.txt')
        store = bench.source_store(matter)
        source_set = None
        if source_change == 'scope':
            assert client.post(f'/matters/{slug}/uploads', files=[
                ('files', ('late.txt', b'ParentBodyCanary describes a later generated meeting.', 'text/plain')),
            ]).status_code == 200
            initial = next(item for item in store.documents.values() if item.display_name == 'initial.txt')
            late = next(item for item in store.documents.values() if item.display_name == 'late.txt')
            assert client.post(f'/matters/{slug}/sources/bulk', data={'action': 'create_set',
                'source_set_name': 'Generated selected scope', 'selected': store.action_token(initial)},
                follow_redirects=False).status_code == 303
            source_set = bench.workspace.source_sets(matter.matter_id)[0]
        if pause_stage == 'before_search':
            original_search = bench._answer_search
            def pause_before_search(*args, **kwargs):
                if not generating.is_set():
                    generating.set()
                    assert continue_generation.wait(10)
                return original_search(*args, **kwargs)
            monkeypatch.setattr(bench, '_answer_search', pause_before_search)
        original_answer = bench.generator.answer

        def pause_final_generation(question, *args, **kwargs):
            if pause_stage == 'generation' and (answer_mode != 'research' or question.startswith('Answer the original research objective')):
                generating.set()
                assert continue_generation.wait(10), 'Concurrent upload did not finish'
            return original_answer(question, *args, **kwargs)

        monkeypatch.setattr(bench.generator, 'answer', pause_final_generation)
        if pause_stage == 'finishing':
            coordinator = bench.answers if answer_mode == 'queued' else bench.research
            original_finish = coordinator.finish
            def pause_before_save(*args, **kwargs):
                generating.set()
                assert continue_generation.wait(10), 'Concurrent upload did not finish'
                return original_finish(*args, **kwargs)
            monkeypatch.setattr(coordinator, 'finish', pause_before_save)
        conversation = bench.workspace.get_conversation(matter.matter_id)
        question = 'What does ParentBodyCanary describe?'
        if answer_mode == 'synchronous':
            future = executor.submit(bench.ask, matter, conversation, question)
        else:
            data = {'conversation': conversation.conversation_id, 'question': question,
                'request_key': 'answer-request-' + 'd' * 32,
                **({'source_set': source_set.source_set_id} if source_set else {})}
            if answer_mode == 'research':
                data['review_task'] = 'research'
            started = client.post(f'/matters/{slug}/ask', data=data,
                headers={'Accept': 'application/json'}, follow_redirects=False)
            assert started.status_code == 202
        try:
            assert generating.wait(10)
            if source_change == 'swap':
                assert client.post(f'/matters/{slug}/sources/{store.action_token(unused)}/remove').status_code == 200
            if source_change == 'scope':
                before = bench.workspace.source_availability_fingerprint(matter.matter_id)
                assert client.post(f'/matters/{slug}/sources/bulk', data={'action': 'add_to_set',
                    'source_set_id': source_set.source_set_id, 'selected': store.action_token(late)},
                    follow_redirects=False).status_code == 303
                assert bench.workspace.source_availability_fingerprint(matter.matter_id) == before
                assert bench.workspace.source_set(matter.matter_id, source_set.source_set_id).source_count == 2
            elif source_change == 'pending':
                from tests.test_intake_receipt_http import descriptor, selection, upload
                files = [descriptor('Pending/late.txt', 128)]
                receipt = selection(client, slug, files, [0])
                upload(client, slug, receipt, files, [0])
                assert len(bench.source_store(matter).documents) == 1
                readiness = bench.workspace.matter_readiness(matter.matter_id)
                assert readiness.total_count == 2 and readiness.processing_count == 1
            else:
                assert client.post(f'/matters/{slug}/uploads', files=[
                    ('files', ('late.txt', b'LateSourceCanary describes a different meeting.', 'text/plain')),
                ]).status_code == 200
        finally:
            continue_generation.set()
        if answer_mode == 'synchronous':
            answer = future.result(timeout=10)
        else:
            deadline = time.monotonic() + 10
            while True:
                if answer_mode == 'research':
                    job = bench.workspace.research_jobs(matter.matter_id, ACTOR)[0]
                    state = job.state
                else:
                    state = client.get(started.json()['status_url']).json()['state']
                if state in {'succeeded', 'failed', 'cancelled'}:
                    break
                assert time.monotonic() < deadline
                time.sleep(.02)
            assert state == 'succeeded'
            if answer_mode != 'research':
                answer = bench.workspace.messages(matter.matter_id, conversation.conversation_id)[-1]
        if answer_mode == 'research':
            coverage = job.result['coverage']
            assert '_retrieval_source_fingerprint' not in job.result
            citations = job.result['evidence']
            route = f'/matters/{slug}/research/{job.job_id}/export'
        else:
            coverage = answer.payload['source_coverage']
            citations = [item for claim in answer.payload['claims'] for item in claim['citations']]
            assert 'searched 2' not in answer.payload['review_scope']['notice']
            assert answer.payload['review_scope']['searchable_source_count'] == (1 if source_change == 'pending' else 2)
            route = f'/matters/{slug}/conversations/{conversation.conversation_id}/messages/{answer.message_id}/export'
        assert citations and all(item['source_name'] == 'initial.txt' for item in citations)
        for item in citations:
            assert bench.support(matter, item['support_token']).source_name == 'initial.txt'
        assert coverage['mode'] == 'partial'
        assert coverage['total_count'] == 2
        assert coverage['searchable_count'] == (1 if source_change == 'pending' else 2)
        assert coverage['excluded_count'] == (1 if source_change == 'pending' else 0)
        assert 'changed after the search started' in coverage['notice']
        for format_name in ('markdown', 'docx'):
            exported = client.get(route, params={'format': format_name})
            assert exported.status_code == 200
            if format_name == 'docx':
                with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
                    assert 'changed after the search started' in archive.read('word/document.xml').decode()
            else:
                assert 'changed after the search started' in exported.text


@pytest.mark.parametrize('parameter', ['filename', 'name'])
@pytest.mark.parametrize('filename', ['', '   '])
def test_explicit_empty_filename_is_an_unnamed_attachment(tmp_path, parameter, filename):
    header = (f'Content-Disposition: inline; filename="{filename}"' if parameter == 'filename'
        else f'Content-Type: text/plain; name="{filename}"')
    path = tmp_path / 'generated.eml'
    path.write_bytes(('Content-Type: multipart/mixed; boundary="generated"\r\n\r\n'
        '--generated\r\nContent-Type: text/plain\r\n\r\nParentBodyCanary\r\n'
        '--generated\r\n' + header + '\r\n\r\nAttachmentOnlyCanary\r\n--generated--\r\n').encode())
    text = '\n'.join(section.text for section in extract_email(path))
    assert 'ParentBodyCanary' in text and 'AttachmentOnlyCanary' not in text
    assert 'Attachment: unnamed (text/plain)' in text
    assert 'Attachment contents were not processed or searched' in text


@pytest.mark.parametrize('content_id', [
    b'(generated) <body@example.test>',
    b'(before <not-the-root@example.test>) <body@example.test> (after)',
    b'(outer (inner))\n\t<body@example.test>',
])
def test_related_root_accepts_content_id_comments_and_folding(tmp_path, content_id):
    from email import policy
    from email.parser import BytesParser
    message = BytesParser(policy=policy.default).parsebytes(generated_email('related'))
    message.set_param('start', '<body@example.test>')
    raw = message.as_bytes().replace(b'Content-ID: <body@example.test>', b'Content-ID: ' + content_id)
    path = tmp_path / 'generated.eml'
    path.write_bytes(raw)
    text = '\n'.join(section.text for section in extract_email(path))
    assert 'ParentBodyCanary' in text and 'AttachmentOnlyCanary' not in text
    assert 'Attachment: unnamed (text/plain)' in text


def test_related_root_ambiguity_is_checked_after_content_id_normalization(tmp_path):
    from email import policy
    from email.parser import BytesParser
    message = BytesParser(policy=policy.default).parsebytes(generated_email('related'))
    message.set_param('start', '<body@example.test>')
    message.get_payload()[1].replace_header('Content-ID', '(same root) <body@example.test>')
    path = tmp_path / 'generated.eml'
    path.write_bytes(message.as_bytes())
    with pytest.raises(ValueError, match='ambiguous'):
        extract_email(path)


@pytest.mark.parametrize('checkpoint_kind', ['current', 'legacy'])
@pytest.mark.parametrize('source_change', ['upload', 'scope'])
def test_recovered_final_research_checkpoint_retrieves_new_sources(tmp_path, monkeypatch, checkpoint_kind, source_change):
    app = create_workbench_app(tmp_path / 'runtime', generator=EvidenceEchoGenerator(),
        auth_mode='test', malware_scanner=CleanScanner(), malware_scan_mode='extended')
    with TestClient(app) as client:
        slug = _matter(client, 'Generated final-pass recovery')
        bench = app.state.workbench
        bench.research.close()
        matter = bench.matter(slug, ACTOR)
        assert client.post(f'/matters/{slug}/uploads', files=[
            ('files', ('initial.txt', b'ParentBodyCanary describes a generated meeting.', 'text/plain')),
        ]).status_code == 200
        source_set = None
        if source_change == 'scope':
            assert client.post(f'/matters/{slug}/uploads', files=[
                ('files', ('late.txt', b'ParentBodyCanary also describes a later generated meeting.', 'text/plain')),
            ]).status_code == 200
            store = bench.source_store(matter)
            initial = next(item for item in store.documents.values() if item.display_name == 'initial.txt')
            late = next(item for item in store.documents.values() if item.display_name == 'late.txt')
            source_set = bench.workspace.create_source_set(matter.matter_id, 'Generated recovery scope', (initial.document_id,), ACTOR)
        job, created = bench.workspace.queue_research_job(matter.matter_id, ACTOR,
            'What does ParentBodyCanary describe?', 'Generated recovery', 'research-request-' + 'b' * 32,
            source_set_id=source_set.source_set_id if source_set else None)
        assert created
        claimed = bench.workspace.claim_research_job('generated-first-worker')
        assert claimed.job_id == job.job_id
        original_checkpoint = bench.workspace.checkpoint_research_job
        original_answer = bench.generator.answer

        class StoppedAfterPasses(Exception):
            pass

        def stop_before_final_generation(question, *args, **kwargs):
            if question.startswith('Answer the original research objective'):
                raise StoppedAfterPasses()
            return original_answer(question, *args, **kwargs)

        if checkpoint_kind == 'legacy':
            def legacy_checkpoint(job_id, result):
                result = dict(result)
                result.pop('retrieval_source_fingerprint', None)
                return original_checkpoint(job_id, result)
            monkeypatch.setattr(bench.workspace, 'checkpoint_research_job', legacy_checkpoint)
        monkeypatch.setattr(bench.generator, 'answer', stop_before_final_generation)
        with pytest.raises(StoppedAfterPasses):
            bench._process_research_job(claimed, lambda: False)
        stopped = bench.workspace.research_job(matter.matter_id, ACTOR, job.job_id)
        assert [step['query'] for step in stopped.result['passes']] == [
            stopped.plan['queries'][0], 'ParentBodyCanary']
        assert stopped.result['pending_searches'] == []
        if source_set:
            assert client.post(f'/matters/{slug}/sources/bulk', data={'action': 'add_to_set',
                'source_set_id': source_set.source_set_id, 'selected': store.action_token(late)},
                follow_redirects=False).status_code == 303
        else:
            assert client.post(f'/matters/{slug}/uploads', files=[
                ('files', ('late.txt', b'ParentBodyCanary also describes a later generated meeting.', 'text/plain')),
            ]).status_code == 200
        assert bench.workspace.recover_running_research_jobs() == 1
        resumed = bench.workspace.claim_research_job('generated-resumed-worker')
        monkeypatch.setattr(bench.generator, 'answer', original_answer)
        monkeypatch.setattr(bench.workspace, 'checkpoint_research_job', original_checkpoint)
        searches = []
        original_search = bench._answer_search
        def tracked_search(*args, **kwargs):
            searches.append(args[2])
            return original_search(*args, **kwargs)
        monkeypatch.setattr(bench, '_answer_search', tracked_search)
        result = bench._process_research_job(resumed, lambda: False)
        finished = bench.workspace.finish_research_job(job.job_id, result)
        assert finished.state == 'succeeded'
        assert searches == [stopped.plan['queries'][0], 'ParentBodyCanary']
        assert result['discarded_passes'] == 2
        assert result['budget']['counts']['completed_passes'] == 4
        assert any(item['source_name'] == 'late.txt' for item in result['evidence'])
        for item in result['evidence']:
            assert bench.support(matter, item['support_token']).source_name == item['source_name']
        assert result['coverage']['searchable_count'] == result['coverage']['total_count'] == 2
        for format_name in ('markdown', 'json', 'docx'):
            exported = client.get(f'/matters/{slug}/research/{job.job_id}/export', params={'format': format_name})
            assert exported.status_code == 200
            if format_name == 'docx':
                with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
                    assert 'late.txt' in archive.read('word/document.xml').decode()
            else:
                assert 'late.txt' in exported.text


def test_source_availability_boundary_is_matter_scoped_and_version_sensitive(tmp_path):
    app = create_workbench_app(tmp_path / 'runtime', generator=EvidenceEchoGenerator(),
        auth_mode='test', malware_scanner=CleanScanner(), malware_scan_mode='extended')
    with TestClient(app) as client:
        slug = _matter(client, 'Generated boundary owner')
        other_slug = _matter(client, 'Generated foreign boundary')
        bench = app.state.workbench
        matter = bench.matter(slug, ACTOR)
        fingerprint = lambda: bench.workspace.source_availability_fingerprint(matter.matter_id)
        initial = fingerprint()
        assert client.post(f'/matters/{other_slug}/uploads', files=[
            ('files', ('foreign.txt', b'ForeignBoundaryCanary', 'text/plain')),
        ]).status_code == 200
        assert fingerprint() == initial
        assert client.post(f'/matters/{slug}/uploads', files=[
            ('files', ('own.txt', b'OwnBoundaryCanary', 'text/plain')),
        ]).status_code == 200
        uploaded = fingerprint()
        assert uploaded != initial
        store = bench.source_store(matter)
        document = next(iter(store.documents.values()))
        with store.mutation_guard():
            document.version_id = 'f' * 32
            store._save((document.document_id,))
        assert fingerprint() != uploaded


@pytest.mark.parametrize('headers', [
    b'Content-Type: text/plain\r\nContent-Type: message/rfc822',
    b'Content-Disposition: inline\r\nContent-Disposition: attachment; filename="generated.txt"',
    b'Content-Transfer-Encoding: 7bit\r\nContent-Transfer-Encoding: quoted-printable',
    b'Content-ID: <first@example.test>\r\nContent-ID: <second@example.test>',
])
def test_duplicate_mime_classification_headers_use_processing_recovery(tmp_path, headers):
    path = tmp_path / 'generated.eml'
    path.write_bytes(b'Content-Type: multipart/mixed; boundary="generated"\r\n\r\n'
        b'--generated\r\nContent-Type: text/plain\r\n\r\nParentBodyCanary\r\n'
        b'--generated\r\n' + headers + b'\r\n\r\nAttachmentOnlyCanary\r\n--generated--\r\n')
    with pytest.raises(ValueError, match='malformed'):
        extract_email(path)


@pytest.mark.parametrize('container,report_type', [('mixed', ''), ('report', 'x-other-report')])
@pytest.mark.parametrize('subtype', ['feedback-report', 'delivery-status'])
def test_feedback_part_outside_matching_report_context_is_an_attachment(tmp_path, container, report_type, subtype):
    path = tmp_path / 'generated.eml'
    path.write_bytes((f'Content-Type: multipart/{container}; report-type="{report_type}"; boundary="generated"\r\n\r\n'
        '--generated\r\nContent-Type: text/plain\r\n\r\nParentBodyCanary\r\n'
        f'--generated\r\nContent-Type: message/{subtype}\r\n\r\nFeedback-Type: abuse\r\n\r\n'
        '--generated--\r\n').encode())
    text = '\n'.join(section.text for section in extract_email(path))
    assert f'Attachment: unnamed (message/{subtype})' in text
    assert 'Feedback-Type' not in text


def test_feedback_report_inventories_returned_message_but_not_report_metadata(tmp_path):
    path = tmp_path / 'generated.eml'
    path.write_bytes(b'Content-Type: multipart/report; report-type=feedback-report; boundary="generated"\r\n\r\n'
        b'--generated\r\nContent-Type: text/plain\r\n\r\nParentBodyCanary\r\n'
        b'--generated\r\nContent-Type: message/feedback-report\r\n\r\nFeedback-Type: abuse\r\nUser-Agent: Generated\r\nVersion: 1\r\n'
        b'--generated\r\nContent-Type: message/rfc822\r\n\r\nSubject: Generated returned email\r\n\r\nAttachmentOnlyCanary\r\n'
        b'--generated--\r\n')
    text = '\n'.join(section.text for section in extract_email(path))
    assert 'Attachment: unnamed (message/feedback-report)' not in text
    assert 'Attachment: unnamed (message/rfc822)' in text
    assert 'ParentBodyCanary' in text and 'AttachmentOnlyCanary' not in text


def test_selected_scope_fingerprint_ignores_other_sets_and_denies_foreign_scope(tmp_path):
    app = create_workbench_app(tmp_path / 'runtime', generator=EvidenceEchoGenerator(),
        auth_mode='test', malware_scanner=CleanScanner(), malware_scan_mode='extended')
    with TestClient(app) as client:
        slug = _matter(client, 'Generated scope boundary')
        foreign_slug = _matter(client, 'Generated foreign scope boundary')
        assert client.post(f'/matters/{slug}/uploads', files=[
            ('files', ('initial.txt', b'Generated first scope source.', 'text/plain')),
            ('files', ('second.txt', b'Generated second scope source.', 'text/plain')),
        ]).status_code == 200
        bench = app.state.workbench
        matter = bench.matter(slug, ACTOR)
        foreign = bench.matter(foreign_slug, ACTOR)
        documents = tuple(bench.source_store(matter).documents.values())
        selected = bench.workspace.create_source_set(matter.matter_id, 'Generated selected', (documents[0].document_id,), ACTOR)
        other = bench.workspace.create_source_set(matter.matter_id, 'Generated other', (documents[0].document_id,), ACTOR)
        fingerprint = lambda: bench.workspace.source_availability_fingerprint(matter.matter_id, selected.source_set_id)
        before = fingerprint()
        bench.workspace.add_sources_to_set(matter.matter_id, other.source_set_id, (documents[1].document_id,), ACTOR)
        assert fingerprint() == before
        bench.workspace.add_sources_to_set(matter.matter_id, selected.source_set_id, (documents[1].document_id,), ACTOR)
        assert fingerprint() != before
        with pytest.raises(KeyError):
            bench.workspace.source_availability_fingerprint(foreign.matter_id, selected.source_set_id)
