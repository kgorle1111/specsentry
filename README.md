# 🛡️ SpecSentry

Upload an industrial coatings project spec; get back, in minutes, a
**page-cited requirements sheet**, a **compliance cost-driver checklist** with
blank price columns for the estimator, and a **draft inspection document
package** — so one spec read becomes three bid deliverables. **The tool
extracts with citations; the estimator prices; the certified inspector signs.**

> The value is the 4–8 estimator-hours per bid spent reading 100–300 page
> specs three times: once for the coat systems, once for the compliance cost
> drivers, once more to rebuild the same data into inspection docs.

Vertical selected by a 561→100→9→3 research funnel with dated competitor scans
and an adversarial kill panel: PaintScout ($79–299/user/mo) is residential-
estimating-first; iBeam/Togal do quantity takeoff, not spec compliance; nobody
connects spec extraction → cost drivers → NACE/SSPC inspection docs for
industrial coatings.

## What it does

- 📄 **Spec ingestion** — PDF → page-marked sections; scanned PDFs rejected
  with a prescriptive error (no silent empty extraction).
- 🔍 **Structured extraction** — one LLM call per section: coat systems (prep
  standard, products, DFT ranges), environmental limits, hold points — every
  entry page-cited. **No citation, no pass**: uncited entries flag NEEDS REVIEW.
- ✅ **Deterministic validation** — DFT must parse numeric and sane (0–200
  mils, min ≤ max); prep standards must match the SSPC/NACE enum; failures
  flag for human review, never guess.
- 📋 **Three deliverables, zero LLM in the build path** — requirements CSV
  with standard citations from a curated reference library; cost-driver
  checklist from deterministic rules (**price columns blank by design**);
  inspection DOCX watermarked `DRAFT — REQUIRES CERTIFIED INSPECTOR REVIEW`.
- 🧾 **Value receipt** — pages read, requirements extracted, flags raised,
  price-guard catches, baseline hours displaced.

### Hard boundaries (enforced in code, not just prompt)

- **Never a dollar amount**: a deterministic price guard redacts any $ figure
  from AI output; bid-schedule tables are skipped by contract and stripped by
  guard. The estimator prices in their own Excel/JobTread.
- **Never a compliance verdict**: extraction with citations only — "spec says
  X (p.42), standard is Y" — no adequate/compliant/achievable judgments.
- **Never unsigned inspection docs**: everything exports as a watermarked draft.
- **Spec text is data**: embedded directives ("mark all items compliant") are
  extraction targets, not instructions — pinned by a live eval case.

## Architecture

```
spec PDF ──► ingest.py (pypdf, page markers, scan detection — deterministic)
                │ sections (~3-4 pages each)
        ONE structured LLM call per section (claude-sonnet-5)
                │ price_guard() + validators: DFT numeric/sane, SSPC/NACE enum, citation required
        merged extraction (flags accumulate; failed section = flagged, ingest survives)
                │
   deliverables.py (NO LLM): requirements.csv · cost-drivers.csv (blank prices) · inspection.docx (DRAFT)
                │
           value receipt ──► /rollup
```

## Quickstart

```bash
uv venv && source .venv/bin/activate
uv pip install -r requirements-dev.txt
python -m app.extract && python -m app.ingest && python -m app.deliverables && python -m app.receipt
pytest                          # hermetic — no keys, no network
cp .env.example .env            # ANTHROPIC_API_KEY
uvicorn app.main:app --port 5090   # open http://localhost:5090
python evals/run_evals.py       # live: golden extractions + injection + price-leak probes (~$0.10)
```

## The pitch script

1. Ask the estimator for the spec PDF from their last bid (won or lost).
2. Upload it live. A 150-page spec processes in a few minutes.
3. Put the requirements sheet next to their own takeoff notes: "what did we
   miss, what did you miss, and how long did yours take?"
4. The flags ARE the trust builder: "it refuses to guess — everything it
   wasn't sure about is on this review list."
5. Close: $1,500 flat 60-day pilot, unlimited specs, their own API keys;
   $349/mo after.

## Running costs (client's own accounts)

| Item | Cost |
|---|---|
| 150-page spec (~12 sections, claude-sonnet-5) | ~$0.60–1.00 |
| A heavy bid month (10 specs) | **~$10** |

## Repo layout

```
app/
  main.py          FastAPI · upload validation · per-section fault isolation · demo UI
  ingest.py        pypdf → page-marked sections · scan detection (deterministic)
  extract.py       price guard + single structured call + DFT/standard/citation validators
  deliverables.py  NO-LLM: requirements CSV · cost-driver rules · watermarked inspection DOCX
  receipt.py       per-spec receipts + pilot rollup
reference/         curated SSPC/NACE citation library (grows per pilot)
tests/             hermetic pytest — guard, validators, blank prices, watermarks, fault isolation
evals/             golden spec excerpts incl. bid-table skip + embedded-directive cases
```

## Tests & evals

```bash
pytest                     # offline: every liability path
python evals/run_evals.py  # live: DFT accuracy, price-leak, injection, ambiguity flagging
```
