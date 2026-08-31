"""Resource-bounded child process for born-digital PDF extraction."""
from __future__ import annotations

import json
import resource
import sys
from pathlib import Path

MAX_PDF_PAGES = 500
MAX_PDF_PAGE_CHARS = 250_000
MAX_PDF_TOTAL_CHARS = 5_000_000
MAX_PDF_CHUNKS = 2_000


def _limit_process() -> None:
    # The web process also enforces a wall timeout and bounded JSON validation.
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    memory = 512 * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))


def main() -> int:
    _limit_process()
    source = Path(sys.argv[1])
    try:
        from pypdf import PdfReader

        with source.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                raise ValueError("signature")
            stream.seek(0)
            reader = PdfReader(stream, strict=True)
            if reader.is_encrypted:
                print(json.dumps({"error": "encrypted"}))
                return 2
            page_count = len(reader.pages)
            if page_count > MAX_PDF_PAGES:
                print(json.dumps({"error": "page_limit"}))
                return 2
            pages: list[dict[str, object]] = []
            total = 0
            chunks = 0
            for number, page in enumerate(reader.pages, 1):
                text = (page.extract_text() or "").strip()
                if len(text) > MAX_PDF_PAGE_CHARS:
                    print(json.dumps({"error": "page_text_limit"}))
                    return 2
                total += len(text)
                if total > MAX_PDF_TOTAL_CHARS:
                    print(json.dumps({"error": "total_text_limit"}))
                    return 2
                if text:
                    chunks += 1
                    if chunks > MAX_PDF_CHUNKS:
                        print(json.dumps({"error": "chunk_limit"}))
                        return 2
                pages.append({"page_number": number, "text": text})
        print(json.dumps({"pages": pages}, ensure_ascii=False, separators=(",", ":")))
        return 0
    except Exception:
        print(json.dumps({"error": "malformed"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
