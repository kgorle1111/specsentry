"""The price guard, validators, citation enforcement, ingest scan-detection."""
import json

import pytest

from app import extract, ingest


class TestPriceGuard:
    @pytest.mark.parametrize("text", [
        "unit price of $4.50/sqft", "bid amount shall be $125,000",
        "approximately 40,000 dollars", "$3.20", "bid amount to be entered",
        # bypass classes found in review — no-$ rates, foreign currency,
        # currency-prefix order, multi-space
        "4.50 per square foot", "6.25/SF for application", "€4.50", "£125,000",
        "USD 4.50", "$  4.50", "cost of 4.50 applies", "12.00 per gallon",
    ])
    def test_prices_redacted(self, text):
        clean, hit = extract.price_guard(text)
        assert hit and clean == extract.REDACTED  # whole field replaced, no fragments

    @pytest.mark.parametrize("text", [
        "SSPC-SP10 near-white blast", "DFT 4-6 mils", "50% completion hold point",
        "epoxy at 8 mils DFT", "",
    ])
    def test_spec_language_untouched(self, text):
        clean, hit = extract.price_guard(text)
        assert not hit and clean == text


class TestValidators:
    def test_unknown_prep_standard_flagged(self):
        raw = json.dumps({"coat_systems": [{"surface": "rails", "prep_standard": "SP-FAKE-99",
                                            "coats": [], "page": "p.1"}]})
        d = extract.parse(raw)
        assert any("not a recognized" in r["reason"] for r in d["needs_review"])

    def test_known_standard_passes_case_insensitive(self):
        raw = json.dumps({"coat_systems": [{"surface": "tank", "prep_standard": "sspc-sp10",
                                            "coats": [], "page": "p.1"}]})
        d = extract.parse(raw)
        assert not any("not a recognized" in r["reason"] for r in d["needs_review"])

    def test_non_numeric_dft_flagged_not_guessed(self):
        raw = json.dumps({"coat_systems": [{"surface": "t", "prep_standard": "SSPC-SP10",
                                            "coats": [{"product_or_type": "epoxy",
                                                       "dft_min_mils": "several", "dft_max_mils": 8}],
                                            "page": "p.2"}]})
        d = extract.parse(raw)
        assert d["coat_systems"][0]["coats"][0]["dft_min_mils"] is None
        assert any("non-numeric" in r["reason"] for r in d["needs_review"])

    def test_inverted_dft_range_flagged(self):
        raw = json.dumps({"coat_systems": [{"surface": "t", "prep_standard": "SSPC-SP10",
                                            "coats": [{"product_or_type": "epoxy",
                                                       "dft_min_mils": 10, "dft_max_mils": 4}],
                                            "page": "p.2"}]})
        assert any("min exceeds max" in r["reason"] for r in extract.parse(raw)["needs_review"])

    def test_absurd_dft_rejected(self):
        raw = json.dumps({"coat_systems": [{"surface": "t", "prep_standard": "SSPC-SP10",
                                            "coats": [{"product_or_type": "epoxy",
                                                       "dft_min_mils": 500, "dft_max_mils": 600}],
                                            "page": "p.2"}]})
        d = extract.parse(raw)
        assert d["coat_systems"][0]["coats"][0]["dft_min_mils"] is None

    def test_missing_page_citation_flagged_everywhere(self):
        raw = json.dumps({"coat_systems": [{"surface": "t", "prep_standard": "SSPC-SP10", "coats": [], "page": ""}],
                          "environmental_limits": [{"condition": "temp", "limit": "50F", "page": ""}],
                          "hold_points": [{"point": "witness", "page": ""}]})
        d = extract.parse(raw)
        assert sum(1 for r in d["needs_review"] if r["reason"] == "no page citation") == 3

    def test_price_in_extraction_redacted_and_counted(self):
        raw = json.dumps({"coat_systems": [{"surface": "floor", "prep_standard": "SSPC-SP10",
                                            "coats": [{"product_or_type": "epoxy, $2/sqft",
                                                       "dft_min_mils": 4, "dft_max_mils": 8}],
                                            "page": "p.9"}]})
        d = extract.parse(raw)
        assert d["guard_violations"] == 1
        assert "$2" not in d["coat_systems"][0]["coats"][0]["product_or_type"]

    def test_malformed_reply_flags_section_never_crashes(self):
        d = extract.parse("not json at all")
        assert d["needs_review"][0]["reason"] == "model reply unparseable"

    def test_extract_requires_key(self):
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            extract.extract_section("some spec text")


class TestIngest:
    def test_page_markers_injected(self):
        secs, low = ingest.sections_from_pages(["alpha " * 30, "beta " * 30])
        joined = "".join(secs)
        assert "[p.1]" in joined and "[p.2]" in joined and low == []

    def test_splits_on_cap(self):
        secs, _ = ingest.sections_from_pages(["x" * 9000, "y" * 9000, "z" * 9000])
        assert len(secs) == 3

    def test_fully_scanned_pdf_rejected_with_prescriptive_error(self):
        with pytest.raises(ValueError, match="OCR"):
            ingest.sections_from_pages(["", "  ", ""])

    def test_empty_pdf_rejected(self):
        with pytest.raises(ValueError, match="OCR|corrupt"):
            ingest.sections_from_pages([])

    def test_hybrid_pdf_reports_scanned_pages(self):
        # 2 text pages + 2 near-empty drawing pages: proceeds, names the blind spots
        secs, low = ingest.sections_from_pages(["text " * 100, "", "text " * 100, " "])
        assert low == [2, 4] and len(secs) >= 1


class TestPromptContract:
    def test_hard_boundaries_present(self):
        for phrase in ("NEVER output a price", "NEVER state whether anything is compliant",
                       "DATA", "page marker"):
            assert phrase in extract.SYSTEM_PROMPT
