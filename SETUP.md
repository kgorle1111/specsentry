# SETUP — zero to a live demo

## 1. Local

One command:

```bash
./install.sh   # venv + deps + .env scaffold + environment verification
```

Or manually:

```bash
uv venv && source .venv/bin/activate
uv pip install -r requirements-dev.txt
python -m app.extract && python -m app.ingest && python -m app.deliverables && python -m app.receipt
pytest        # all green, no keys needed
```

## 2. Keys

`cp .env.example .env` and add `ANTHROPIC_API_KEY`. For a pilot the key is the
contractor's — their console, their card. A 150-page spec costs them ~$1.

## 3. Run

```bash
uvicorn app.main:app --port 5090
```

Open http://localhost:5090 — upload a spec PDF, review the extraction and
flags, download the three deliverables.

## 4. Evals

```bash
python evals/run_evals.py     # 5 golden cases incl. price-leak + embedded-directive probes
```

Week one of a pilot: add 10-20 excerpts from the contractor's own past specs
to `evals/cases.json` with hand-labeled expectations. Every prompt change
gates on that set from then on.

## 5. Pilot hand-off checklist

- [ ] Contractor's Anthropic key in their `.env`
- [ ] `BASELINE_HRS_PER_SPEC` set from timing their estimator on one real spec
- [ ] Golden eval set seeded from their spec library
- [ ] Cost-driver rules reviewed against their actual cost codes (extend
      `deliverables.COST_DRIVER_RULES`)
- [ ] Reference library extended with the standards their specs actually cite
- [ ] One-page runbook: what it does, where files live, who to call when
- [ ] Show the estimator one flagged ambiguity live — "it refuses to guess"
      is the sentence that buys the bid-desk trust
