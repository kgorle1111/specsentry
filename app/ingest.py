"""PDF ingestion: spec PDF -> page-marked text sections sized for extraction.

Deterministic and dumb on purpose: pypdf text extraction, page markers
injected inline ([p.N]), fixed-size sections split on page boundaries. No OCR
in v1 — scanned-image specs are detected (near-zero extractable text) and
rejected with a clear message instead of silently extracting nothing.
"""
from pathlib import Path

MAX_SECTION_CHARS = 12000   # ~3-4 pages per LLM call; big enough for a coat-system table
MIN_TEXT_PER_PAGE = 80      # below this average, the PDF is probably a scan


def pdf_to_pages(path: Path) -> list[str]:
    from pypdf import PdfReader  # deferred: import cost only on ingest
    reader = PdfReader(str(path))
    return [(page.extract_text() or "") for page in reader.pages]


def sections_from_pages(pages: list[str]) -> tuple[list[str], list[int]]:
    """Page-marked sections + the list of low-text page numbers.

    A fully scanned PDF is rejected outright; a HYBRID (text pages + scanned
    drawing pages) proceeds but reports every low-text page, because silently
    extracting nothing from 250 of 300 pages is the 'no requirements' lie."""
    if not pages:
        raise ValueError("PDF has no readable pages — file may be corrupt or image-only; run OCR first")
    low_pages = [n for n, p in enumerate(pages, 1) if len(p.strip()) < MIN_TEXT_PER_PAGE]
    if len(low_pages) == len(pages):
        raise ValueError(
            "PDF looks fully scanned (no page has extractable text) — "
            "run OCR first; v1 reads born-digital specs only")
    sections, current = [], ""
    for n, text in enumerate(pages, 1):
        chunk = f"\n[p.{n}]\n{text.strip()}"
        if current and len(current) + len(chunk) > MAX_SECTION_CHARS:
            sections.append(current)
            current = chunk
        else:
            current += chunk
    if current.strip():
        sections.append(current)
    return sections, low_pages


if __name__ == "__main__":
    pages = ["INTRO " * 40, "SSPC-SP10 near-white metal blast " * 30, "DFT 4-6 mils " * 30]
    secs, low = sections_from_pages(pages)
    assert "[p.1]" in secs[0] and low == []
    assert "".join(secs).count("[p.") == 3
    big = ["x" * 9000, "y" * 9000, "z" * 9000]
    assert len(sections_from_pages(big)[0]) == 3  # splits on page boundary at the cap
    # hybrid: text pages + scanned drawing pages -> proceeds, reports the scans
    secs, low = sections_from_pages(["text " * 100, "", "text " * 100, " "])
    assert low == [2, 4]
    for dead in ([], ["", " ", ""]):
        try:
            sections_from_pages(dead)
            raise AssertionError("accepted a scanned/empty PDF")
        except ValueError:
            pass
    print("ingest OK — page markers, cap splits, full-scan rejection, hybrid detection")
