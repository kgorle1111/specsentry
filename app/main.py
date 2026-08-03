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
import json
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse, JSONResponse

from app import deliverables, extract, ingest, receipt

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
MAX_BYTES = 40 * 1024 * 1024
# Spend + wall-clock ceiling: 80 sections ≈ 300 pages ≈ ~$2 of extraction. A
# bigger spec is almost certainly a merged bid package — split it, don't pay it.
MAX_SECTIONS = 80
UPLOADS = ROOT / "uploads"
DATA = ROOT / "data"                      # per-spec JSON snapshots (durable list)

_SPECS: dict[str, dict] = {}


def _persist(job: str) -> None:
    """Snapshot a processed spec to disk so the list survives a restart."""
    rec = _SPECS.get(job)
    if not rec:
        return
    DATA.mkdir(exist_ok=True)
    (DATA / f"{job}.json").write_text(json.dumps(rec))


def load_all() -> int:
    """Rehydrate processed specs from data/ on startup. No-op if absent."""
    if not DATA.exists():
        return 0
    n = 0
    for f in DATA.glob("*.json"):
        try:
            rec = json.loads(f.read_text())
            _SPECS[rec["job"]] = rec
            n += 1
        except (json.JSONDecodeError, KeyError):
            continue
    return n


def summarize(rec: dict) -> dict:
    """List-view summary of a processed spec."""
    return {
        "job": rec["job"],
        "title": rec.get("title") or rec["job"],
        "pages": rec.get("pages", 0),
        "sections": rec.get("sections", 0),
        "coat_systems": len(rec.get("coat_systems", [])),
        "environmental_limits": len(rec.get("environmental_limits", [])),
        "hold_points": len(rec.get("hold_points", [])),
        "review_flags": len(rec.get("needs_review", [])),
        "guard_violations": rec.get("guard_violations", 0),
        "created": rec.get("created"),
    }


@asynccontextmanager
async def lifespan(_app):
    load_all()  # rehydrate processed specs so the list survives a restart
    yield


app = FastAPI(title="specsentry", lifespan=lifespan)

# --- localhost guard -------------------------------------------------------
# Rejects requests whose Host or Origin isn't local. The Host check stops DNS
# rebinding (evil.com resolving to 127.0.0.1 arrives with Host: evil.com); the
# Origin check stops cross-origin browser POSTs — multipart/form bodies skip
# CORS preflight, so without it any webpage the operator visits could fire
# uploads that spend real API money. curl/httpx send no Origin and pass.
# "testserver" is starlette's TestClient default host.
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "testserver"}


def _guard_hostname(value: str) -> str:
    if "//" not in value:
        value = "//" + value
    return urlsplit(value).hostname or ""


@app.middleware("http")
async def localhost_guard(request: Request, call_next):
    if _guard_hostname(request.headers.get("host", "")) not in _LOCAL_HOSTS:
        return JSONResponse(
            {"detail": "unrecognized Host header — this server only answers as localhost"}, status_code=403
        )
    origin = request.headers.get("origin")
    if origin and _guard_hostname(origin) not in _LOCAL_HOSTS:
        return JSONResponse({"detail": "cross-origin requests are not accepted"}, status_code=403)
    return await call_next(request)



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
    title = re.sub(r"-[a-f0-9]{6}$", "", job).replace("_", " ").replace("-", " ").strip() or job
    _SPECS[job] = {"job": job, "title": title, "created": datetime.now(timezone.utc).isoformat(),
                   "pages": len(pages), "sections": len(sections), **merged}
    _persist(job)
    receipt.log_spec(job, len(pages), len(sections), len(merged["coat_systems"]),
                     len(merged["environmental_limits"]), len(merged["hold_points"]),
                     len(merged["needs_review"]), merged["guard_violations"])
    return _SPECS[job]


@app.get("/specs")
def list_specs():
    """Processed-spec list for the home view — newest first."""
    return sorted((summarize(r) for r in _SPECS.values()),
                  key=lambda s: s["created"] or "", reverse=True)


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


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})
