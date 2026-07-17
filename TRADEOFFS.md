# TRADEOFFS — what I cut and what it costs

The bar I set: an industrial coatings estimator bids six-figure jobs where a
missed containment clause eats the margin and a wrong DFT becomes a failed
holiday test on infrastructure. The riskiest assumption (from my own product
spec) is that estimators will trust page-cited extraction enough not to
re-read the whole spec. Every decision below serves that trust; nothing
trades it away.

## Citations are mandatory, not decorative

An extraction without a page citation is auto-flagged NEEDS REVIEW. This costs
recall — the model sometimes extracts something real but drops the marker,
and it lands on the review list anyway. I take that trade every time: the
product's only path to trust is that every line can be checked against the
spec in seconds. An unverifiable extraction is worse than no extraction.

## Validators over vibes: DFT numeric+sane, standards enum, min<=max

A guessed mil thickness is the unrecoverable failure, so numbers that don't
parse, ranges that invert, values outside 0-200 mils, and prep standards
outside the SSPC/NACE enum all flag rather than pass. False positive cost:
the estimator confirms a weird-but-real value once. False negative cost: a
bid built on a hallucinated number.
`kn: enum seeded with the common SSPC/NACE standards; extend from the pilot's spec library.`

## No LLM in the deliverables path

Cost-driver checklists come from deterministic rules over the validated
extraction; inspection docs are templated from the same record. An LLM
"smartly" drafting QC documents would occasionally invent a hold point, and a
QC document is audit evidence. The rules are crude (keyword-mapped) and the
checklist is deliberately over-inclusive — an estimator crossing off an
inapplicable line costs seconds; a missing confined-space line costs the margin.
`kn: 8 keyword rules; grow per pilot contractor's cost codes.`

## Prices are blank cells, not suggestions

The cost-driver CSV ships with empty unit-cost columns and the price guard
redacts any dollar figure the model emits (specs contain bid schedules; the
extractor is told to skip them AND the guard catches leaks). Pricing is the
estimator's edge and liability — the tool that suggests a price is the tool
that gets blamed for the losing bid.

## No OCR in v1 — scanned specs are rejected loudly

pypdf handles born-digital PDFs. A scanned spec returns a prescriptive error
("run OCR first") instead of silently extracting nothing and reporting an
empty spec as processed — silent emptiness would read as "no requirements,"
which is the worst possible lie. OCR (or vision-model page reading) is the
first paid upgrade if the pilot's spec library turns out to be scans.
`kn: MIN_TEXT_PER_PAGE=80 heuristic; tune against the pilot's real library.`

## Section-level fault isolation

Each ~3-4 page section extracts independently; a failed API call flags that
section for manual read and the rest of the spec continues. One hiccup never
kills a 300-page ingest, and the failure is visible in the same review list
the estimator already checks.

## Quantity takeoff explicitly not built

Square-footage measurement from drawings is a different, crowded problem
(Beam AI, Togal, On-Screen Takeoff all do it). SpecSentry reads the WORDS of
the spec, not the drawings — that's the unbundled gap the kill panel
verified. Integrating with a takeoff tool is a phase-2 conversation.

## Skipped entirely, and the trigger to add each

- **JobTread/Buildertrend integration** — CSV export only; add when a pilot
  contractor names the exact import they want.
- **In-memory job store** — jobs live in a dict + files on disk; restart loses
  the index but deliverables persist. SQLite at multi-estimator use.
- **Multi-user, roles, offline, mobile** — this sells to one estimator first.
- **NACE/SSPC full-text reference RAG** — v1 cites from a curated JSON library
  (names + one-line descriptions). Full standard texts are licensed documents;
  the contractor's own copies can be indexed per-pilot, on their infra.
