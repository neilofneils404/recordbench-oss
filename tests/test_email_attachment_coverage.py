from __future__ import annotations

from email.message import EmailMessage
import io
import time
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
    if kind == "message":
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


@pytest.mark.parametrize("kind,name", [("message", "forwarded.eml"), ("multipart", "bundle.mime"), ("unnamed", "unnamed"), ("inline", "unnamed"), ("text", "notes.txt")])
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


def test_uploaded_email_search_answer_export_and_matter_boundaries(tmp_path):
    app = create_workbench_app(tmp_path / "runtime", generator=EvidenceEchoGenerator(),
        auth_mode="test", malware_scanner=CleanScanner(), malware_scan_mode="extended")
    with TestClient(app) as client:
        slug = _matter(client, "Generated email attachment review")
        bench = app.state.workbench
        matter = bench.matter(slug, ACTOR)
        response = client.post(f"/matters/{slug}/uploads", files=[("files", ("generated.eml", generated_email(), "message/rfc822"))])
        assert response.status_code == 200
        store = bench.source_store(matter)
        document = next(iter(store.documents.values()))
        identity = document.document_id, document.version_id
        token = store.action_token(document)
        source = client.get(f"/matters/{slug}/sources/{token}")
        assert source.status_code == 200
        assert EMAIL_COVERAGE_NOTICE in source.text
        assert "forwarded.eml" in source.text
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
