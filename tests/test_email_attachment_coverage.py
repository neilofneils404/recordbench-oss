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


@pytest.mark.parametrize("report_type", ["delivery-status", "disposition-notification"])
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


def test_investigation_refreshes_coverage_after_upload_between_live_passes(tmp_path, monkeypatch):
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
                ("files", ("generated.eml", generated_email(), "message/rfc822")),
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
        email = next(document for document in store.documents.values() if document.media_type == "message/rfc822")
        email_evidence = [item for item in job.result["evidence"] if item["document_id"] == email.document_id]
        assert email_evidence
        for item in email_evidence:
            assert item["source_version_id"] == email.version_id
            support = bench.support(matter, item["support_token"])
            assert support.source_name == "generated.eml"
        coverage = job.result["coverage"]
        assert coverage["mode"] == "partial"
        assert coverage["searchable_count"] == 2 and coverage["total_count"] == 2
        assert coverage["excluded_count"] == 0
        assert EMAIL_COVERAGE_NOTICE in coverage["notice"]
        page = client.get(f"/matters/{slug}/research", params={"job": job_id})
        assert EMAIL_COVERAGE_NOTICE in page.text
        for format_name in ("markdown", "json", "docx"):
            exported = client.get(f"/matters/{slug}/research/{job_id}/export", params={"format": format_name})
            assert exported.status_code == 200
            if format_name == "docx":
                with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
                    assert EMAIL_COVERAGE_NOTICE in archive.read("word/document.xml").decode()
            else:
                assert EMAIL_COVERAGE_NOTICE in exported.text
        bundle = client.get(f"/matters/{slug}/export")
        assert bundle.status_code == 200
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            entries = [name for name in archive.namelist() if name.startswith("investigations/")]
            assert entries and all(EMAIL_COVERAGE_NOTICE in archive.read(name).decode() for name in entries)


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
