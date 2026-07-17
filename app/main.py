"""SpecSentry — FastAPI surface.

Flow
    POST /specs                 upload spec PDF -> ingest -> per-section extraction -> merged record
    GET  /specs/{job}           the merged extraction + flags
    GET  /specs/{job}/requirements.csv
    GET  /specs/{job}/cost-drivers.csv     blank price columns — the estimator prices
    GET  /specs/{job}/inspection.docx      watermarked DRAFT
    GET  /rollup                the pilot scoreboard

Trust boundaries
    - PDFs only, <= 40 MB; scanned PDFs rejected with a clear message (no OCR in v1).
    - Spec text is DATA: the extractor never follows directives inside it; the
      price guard strips dollar figures from every output field.
    - Deliverables are deterministic code over the validated extraction — no LLM
      writes to a bid document or a QC form.
    - A section whose extraction call fails is logged as a whole-section review
      flag; the rest of the spec still processes — one bad section never kills
      a 300-page ingest.
"""
import asyncio
import re
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from app import deliverables, extract, ingest, receipt

load_dotenv()
app = FastAPI(title="specsentry")

MAX_BYTES = 40 * 1024 * 1024
# Spend + wall-clock ceiling: 80 sections ≈ 300 pages ≈ ~$2 of extraction. A
# bigger spec is almost certainly a merged bid package — split it, don't pay it.
MAX_SECTIONS = 80
UPLOADS = Path(__file__).resolve().parent.parent / "uploads"

_SPECS: dict[str, dict] = {}


def merge_sections(results: list[dict]) -> dict:
    merged = {"coat_systems": [], "environmental_limits": [], "hold_points": [],
              "needs_review": [], "guard_violations": 0}
    for r in results:
        for k in ("coat_systems", "environmental_limits", "hold_points", "needs_review"):
            merged[k].extend(r.get(k) or [])
        merged["guard_violations"] += r.get("guard_violations", 0)
    return merged


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/rollup")
def rollup():
    return receipt.rollup()


@app.post("/specs")
async def upload_spec(pdf: UploadFile = File(...)):
    if pdf.content_type != "application/pdf":
        raise HTTPException(422, "PDF only")
    data = await pdf.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(422, "spec exceeds 40 MB")
    job = re.sub(r"[^a-zA-Z0-9_-]", "", Path(pdf.filename or "spec").stem)[:40] or uuid.uuid4().hex[:8]
    job = f"{job}-{uuid.uuid4().hex[:6]}"
    UPLOADS.mkdir(exist_ok=True)
    path = UPLOADS / f"{job}.pdf"
    path.write_bytes(data)

    try:
        pages = await asyncio.to_thread(ingest.pdf_to_pages, path)
        sections, low_pages = ingest.sections_from_pages(pages)
    except ValueError as e:          # scanned/empty PDF — clear, prescriptive rejection
        raise HTTPException(422, str(e))
    except Exception:
        raise HTTPException(422, "could not read PDF — file may be corrupt")
    if len(sections) > MAX_SECTIONS:
        raise HTTPException(422, f"spec produced {len(sections)} sections (max {MAX_SECTIONS}) — "
                                 "this looks like a merged bid package; split it and upload the coatings spec")

    results = []
    for i, sec in enumerate(sections):
        try:
            # to_thread: the sync Anthropic call must not freeze the event loop
            # (and /health with it) for the whole ingest.
            results.append(await asyncio.to_thread(extract.extract_section, sec))
        except Exception:
            # One bad section never kills the ingest; it lands as a review flag.
            results.append({"coat_systems": [], "environmental_limits": [], "hold_points": [],
                            "needs_review": [{"entry": f"section {i + 1}",
                                              "reason": "extraction call failed — read manually"}],
                            "guard_violations": 0})
    merged = merge_sections(results)
    for n in low_pages:  # hybrid PDFs: scanned pages are visible, not silent
        merged["needs_review"].append({"entry": f"page {n}",
                                       "reason": "little/no extractable text — likely a scanned drawing; read manually"})
    _SPECS[job] = {"job": job, "pages": len(pages), "sections": len(sections), **merged}
    receipt.log_spec(job, len(pages), len(sections), len(merged["coat_systems"]),
                     len(merged["environmental_limits"]), len(merged["hold_points"]),
                     len(merged["needs_review"]), merged["guard_violations"])
    return _SPECS[job]


@app.get("/specs/{job}")
def get_spec(job: str):
    if job not in _SPECS:
        raise HTTPException(404, "job not found")
    return _SPECS[job]


@app.get("/specs/{job}/requirements.csv")
def requirements(job: str):
    if job not in _SPECS:
        raise HTTPException(404, "job not found")
    return FileResponse(deliverables.requirements_csv(_SPECS[job], job), filename=f"{job}-requirements.csv")


@app.get("/specs/{job}/cost-drivers.csv")
def cost_drivers(job: str):
    if job not in _SPECS:
        raise HTTPException(404, "job not found")
    path, _ = deliverables.cost_drivers_csv(_SPECS[job], job)
    return FileResponse(path, filename=f"{job}-cost-drivers.csv")


@app.get("/specs/{job}/inspection.docx")
def inspection(job: str):
    if job not in _SPECS:
        raise HTTPException(404, "job not found")
    return FileResponse(deliverables.inspection_docx(_SPECS[job], job), filename=f"{job}-inspection-draft.docx",
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


# kn: one-page demo UI — upload, see extraction + flags, grab the three deliverables.
@app.get("/", response_class=HTMLResponse)
def index():
    return """<!doctype html><html><head><meta charset="utf-8"><title>SpecSentry</title>
<style>body{font-family:system-ui;max-width:760px;margin:2rem auto;padding:0 1rem;color:#1a202c}
.flag{color:#b45309;font-weight:600}.box{border:1px solid #ddd;border-radius:8px;padding:1rem;margin:.6rem 0}</style>
</head><body><h1>SpecSentry</h1>
<p>Upload an industrial coatings spec PDF → page-cited requirements sheet, compliance cost-driver
checklist (you price it), and a draft inspection package. Extraction cites or flags — never guesses.</p>
<form id="f" enctype="multipart/form-data"><input type="file" name="pdf" accept="application/pdf" required>
<button>Process spec</button></form><div id="out"></div>
<script>
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
document.getElementById('f').onsubmit=async e=>{e.preventDefault();
 document.getElementById('out').innerHTML='processing…';
 const r=await fetch('/specs',{method:'POST',body:new FormData(e.target)});
 const j=await r.json();
 if(!r.ok){document.getElementById('out').innerHTML=`<p class="flag">${esc(j.detail)}</p>`;return;}
 let h=`<div class="box"><h2>${esc(j.job)} — ${j.pages} pages, ${j.sections} sections</h2>
 <p>${j.coat_systems.length} coat systems · ${j.environmental_limits.length} env limits ·
 ${j.hold_points.length} hold points · <span class="flag">${j.needs_review.length} review flags</span> ·
 ${j.guard_violations} price-guard catches</p>
 <p><a href="/specs/${j.job}/requirements.csv">requirements.csv</a> ·
 <a href="/specs/${j.job}/cost-drivers.csv">cost-drivers.csv</a> ·
 <a href="/specs/${j.job}/inspection.docx">inspection-draft.docx</a> · <a href="/rollup">rollup</a></p>`;
 for(const cs of j.coat_systems){h+=`<p><b>${esc(cs.surface)}</b> — ${esc(cs.prep_standard)} (${esc(cs.page)})<br>`+
  cs.coats.map(c=>`${esc(c.product_or_type)} ${c.dft_min_mils}-${c.dft_max_mils} mils`).join('; ')+`</p>`;}
 if(j.needs_review.length){h+=`<h3 class="flag">Needs human review</h3><ul>`+
  j.needs_review.map(r=>`<li>${esc(r.entry)}: ${esc(r.reason)}</li>`).join('')+`</ul>`;}
 h+=`</div>`;document.getElementById('out').innerHTML=h;};
</script></body></html>"""
