"""Deliverable determinism (blank prices, watermarks, citations) and the HTTP
surface with ingest+extraction mocked."""
import io

import pytest
from fastapi.testclient import TestClient

from app import deliverables, extract, ingest, main

client = TestClient(main.app)


class TestDeliverables:
    def test_requirements_csv_cites_standards(self, extraction):
        p = deliverables.requirements_csv(extraction(), "J1")
        body = p.read_text()
        assert "Near-White Metal Blast" in body and "p.12" in body

    def test_unknown_standard_gets_no_match_note(self, extraction):
        ex = extraction()
        ex["coat_systems"][0]["prep_standard"] = "SP-FAKE"
        assert "(no matching standard" in deliverables.requirements_csv(ex, "J2").read_text()

    def test_cost_driver_prices_are_blank(self, extraction):
        path, n = deliverables.cost_drivers_csv(extraction(), "J3")
        lines = path.read_text().splitlines()
        assert n >= 4
        assert all(line.endswith(",,,,") for line in lines[1:])  # every price cell empty

    def test_confined_space_rule_fires(self, extraction):
        ex = extraction()
        ex["coat_systems"][0]["surface"] = "tank interior (confined space entry)"
        _, n_with = deliverables.cost_drivers_csv(ex, "J4")
        ex2 = extraction()
        _, n_without = deliverables.cost_drivers_csv(ex2, "J5")
        assert n_with == n_without + 1

    def test_inspection_docx_watermarked(self, extraction):
        p = deliverables.inspection_docx(extraction(), "J6")
        from docx import Document
        text = "\n".join(par.text for par in Document(str(p)).paragraphs)
        assert deliverables.WATERMARK in text
        assert text.count("DRAFT") >= 2  # top and bottom

    def test_validator_flag_reaches_the_csv(self, extraction):
        # The reviewer-verified drop: a flagged DFT shipped unflagged. The entry-level
        # flag boolean must reach the deliverable's flag column.
        ex = extraction()
        ex["coat_systems"][0]["flag"] = True
        body = deliverables.requirements_csv(ex, "J7").read_text()
        assert "NEEDS REVIEW" in body

    def test_csv_formula_injection_neutralized(self, extraction):
        ex = extraction()
        ex["coat_systems"][0]["surface"] = '=HYPERLINK("http://evil","click")'
        ex["hold_points"][0]["point"] = "=cmd|' /C calc'!A0"
        body = deliverables.requirements_csv(ex, "J8").read_text()
        for line in body.splitlines()[1:]:
            first_cell = line.split(",")[1] if line.startswith(("coat_system", "hold_point")) else ""
            assert not first_cell.strip('"').startswith("=")

    def test_cost_rules_never_see_job_metadata(self, extraction):
        # A file named confined-waste-spec.pdf must not fire those cost drivers.
        ex = {"job": "confined-waste-spec-x1", "pages": 3, "sections": 1,
              "coat_systems": [], "environmental_limits": [], "hold_points": [],
              "needs_review": [], "guard_violations": 0}
        _, n = deliverables.cost_drivers_csv(ex, "J9")
        assert n == 0


@pytest.fixture
def mock_pipeline(monkeypatch, extraction):
    monkeypatch.setattr(ingest, "pdf_to_pages", lambda path: ["page one text " * 20] * 3)
    monkeypatch.setattr(extract, "extract_section", lambda sec: extraction())


PDF = ("pdf", ("spec.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf"))


class TestSpecTracking:
    def test_list_and_summary(self, mock_pipeline):
        client.post("/specs", files=[PDF])
        rows = client.get("/specs").json()
        assert len(rows) == 1
        s = rows[0]
        assert s["pages"] == 3 and s["coat_systems"] >= 1 and "review_flags" in s and s["title"]

    def test_persistence_survives_reload(self, mock_pipeline, isolate_files):
        job = client.post("/specs", files=[PDF]).json()["job"]
        assert (isolate_files / "data" / f"{job}.json").exists()
        main._SPECS.clear()
        assert main.load_all() == 1
        assert main.get_spec(job)["job"] == job

    def test_corrupt_snapshot_skipped(self, mock_pipeline, isolate_files):
        client.post("/specs", files=[PDF])
        (isolate_files / "data" / "broken.json").write_text("{bad")
        main._SPECS.clear()
        assert main.load_all() == 1

    def test_index_serves_html_shell(self):
        r = client.get("/")
        assert r.status_code == 200 and "SpecSentry" in r.text


class TestEndpoints:
    def test_upload_processes_and_merges(self, mock_pipeline):
        r = client.post("/specs", files=[PDF])
        assert r.status_code == 200
        j = r.json()
        assert j["pages"] == 3 and len(j["coat_systems"]) >= 1
        job = j["job"]
        assert client.get(f"/specs/{job}/requirements.csv").status_code == 200
        assert client.get(f"/specs/{job}/cost-drivers.csv").status_code == 200
        assert client.get(f"/specs/{job}/inspection.docx").status_code == 200

    def test_non_pdf_rejected(self):
        r = client.post("/specs", files=[("pdf", ("spec.txt", io.BytesIO(b"text"), "text/plain"))])
        assert r.status_code == 422

    def test_scanned_pdf_rejected_prescriptively(self, monkeypatch):
        monkeypatch.setattr(ingest, "pdf_to_pages", lambda path: ["", "", ""])
        r = client.post("/specs", files=[PDF])
        assert r.status_code == 422 and "OCR" in r.json()["detail"]

    def test_one_failed_section_does_not_kill_ingest(self, monkeypatch, extraction):
        monkeypatch.setattr(ingest, "pdf_to_pages", lambda path: ["x" * 9000, "y" * 9000])
        calls = {"n": 0}

        def flaky(sec):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("api hiccup")
            return extraction()
        monkeypatch.setattr(extract, "extract_section", flaky)
        r = client.post("/specs", files=[PDF])
        assert r.status_code == 200
        j = r.json()
        assert any("extraction call failed" in f["reason"] for f in j["needs_review"])
        assert len(j["coat_systems"]) == 1  # the surviving section still landed

    def test_rollup_counts(self, mock_pipeline):
        client.post("/specs", files=[PDF])
        r = client.get("/rollup").json()
        assert r["specs_processed"] == 1 and r["pages_read"] == 3

    def test_hybrid_pdf_scanned_pages_flagged(self, monkeypatch, extraction):
        monkeypatch.setattr(ingest, "pdf_to_pages",
                            lambda path: ["text " * 100, "", "text " * 100])
        monkeypatch.setattr(extract, "extract_section", lambda sec: extraction())
        j = client.post("/specs", files=[PDF]).json()
        assert any("scanned drawing" in f["reason"] for f in j["needs_review"])

    def test_section_cap_rejected_prescriptively(self, monkeypatch, extraction):
        monkeypatch.setattr(main, "MAX_SECTIONS", 2)
        monkeypatch.setattr(ingest, "pdf_to_pages", lambda path: ["x" * 9000] * 5)
        r = client.post("/specs", files=[PDF])
        assert r.status_code == 422 and "split it" in r.json()["detail"]

    def test_unknown_job_404(self):
        assert client.get("/specs/nope").status_code == 404
        assert client.get("/specs/nope/requirements.csv").status_code == 404
