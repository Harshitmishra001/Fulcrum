# Independent Fifth Reviewer Audit — Fulcrum

## Final verdict: REJECT

This is a polished prototype with thoughtful documentation, but the delivered knowledge layer is not trustworthy. The pre-populated database contains demonstrably mis-extracted facts, false comparisons, and materially duplicated relation cards. Those are not edge cases: they compromise the exact four cases the assignment asks the candidate to show. I would not advance a candidate on the basis of a fact-verification system that confidently labels `77.9` million tonnes as a government fiscal-deficit percentage.

## Scope and verification performed

I reviewed every tracked source and test file, the README and design documents, the Git history, all six supplied PDFs at the metadata level, and the shipped `fulcrum.db`. I also:

- compiled `src/` and `tests/` with Python 3.12 (`compileall`: pass);
- inspected the live SQLite schema, indexes, foreign-key consistency, facts, chunks, and every stored relation;
- ran the supplied golden evaluator against the shipped RBI facts;
- exercised the period and unit normalizers directly; and
- parsed a real starter-PDF sample with `PDFChunker`.

The full pytest command could not be executed in this audit environment: `python` is not on PATH, and the available Python runtime has no `pytest`. More importantly, `pytest` is omitted from `requirements.txt`, so following the documented dependency installation does not install the tool needed for the README's advertised test command. This is a reproducibility defect, not a reason to disregard the static and database findings below.

The database is structurally intact: 275 active facts, 51 chunks, 131 relations, no SQLite foreign-key violations, and no orphaned relation rows. Structural integrity is not semantic integrity.

## Blocking findings

### P0 — The shipped facts are corrupt, especially from multi-row tables

`PDFChunker._format_table_chunk` serializes a table as one enormous first-column cell containing every metric label plus separate positional value columns ([`src/parser/pdf_chunker.py`](src/parser/pdf_chunker.py), lines 149–156). It does not turn each logical row into a metric/value/year record. That forces the LLM to reconstruct a many-to-many table from a flattened string, with no deterministic validation of the alignment it invents.

The shipped RBI page-91 chunk visibly contains all real-economy, prices, money, financial-market, and government-finance labels in one cell followed by a sequence of values. The database contains the predictable fallout:

| Stored fact | What the source chunk actually says | Why this is disqualifying |
|---|---|---|
| `Gross Fiscal Deficit = 77.9 % of GDP, FY2025` | `77.9` is the 2024–25 procurement value in the food-grains row. | A fiscal claim is fabricated by column/row misalignment. It produces downstream relations. |
| `Foodgrains Production = 330.9, FY2024` | The page header makes `330.9` the 2024–25 value. | The stored period is wrong. |
| `Food Stocks = 74.9, FY2024` | `74.9` is also in the 2024–25 column. | The stored period is wrong. |
| `Real GDP Growth = 6.4, FY2025` | `6.4` is the GVA value; real GDP is `6.5` in that column. | The stored attribute/value pairing is wrong. |

The same problem is visible on RBI page 92: the stored quote for many unrelated facts is the complete 24-number value run, for example for current-account balance, trade balance, external debt, import cover, and reserve changes. That is evidence that a number occurred somewhere in a table, not evidence that the claimed attribute, unit, and period are true.

This is a core pipeline failure. A knowledge layer must either preserve table cell coordinates/headers and validate every extracted value against them, or flag the table as non-machine-verifiable. Passing flattened tables to an LLM and accepting its answer is not a defensible grounding strategy.

### P0 — The relation set is inflated and includes plainly false results

The 131 saved relations reduce to only 73 unique content signatures when fact IDs are removed: **58 rows are duplicate semantic cards across 44 duplicate groups**. The relation uniqueness index only protects an ordered pair of opaque fact UUIDs. It does not deduplicate duplicate facts, reversed pairs under a race, or semantically identical claims. The dashboard's headline counts therefore overstate output.

More importantly, the relation engine persists visibly false conclusions. Examples found in the shipped DB include:

- `Capital Expenditure 4.0% of GDP` versus `grants-in-aid to states 1.6% of GDP` labelled a contradiction. These are different measures.
- `Capital Expenditure 4.3% of GDP` versus `Capital Expenditure Growth 10.1%` labelled a contradiction. A level and a growth rate are not competing values.
- `Gross Tax Revenue 11.6% of GDP` versus `Non-Tax Revenue Growth 32.2%` labelled a contradiction.
- `General Government Deficit 7.9% of GDP` versus the corrupted RBI `Gross Fiscal Deficit 77.9% of GDP` labelled reconciled by an unrelated IMF definition sentence.
- `Real Gross Value Added Growth 6.4%` versus `Real GDP Growth 6.5%` labelled reconciled. GVA and GDP are distinct aggregates, not alternate vintages of the same fact.

The direct causes are clear in [`src/comparison/engine.py`](src/comparison/engine.py): all percentages, including percent-of-GDP, levels, rates, and growth, are placed in one dimension bucket (lines 78–93); each bucket is still compared pairwise, so the claimed `O(N·K)` is worst-case `O(N²)` (lines 114–148); and attribute matching relies on embedding similarity plus very loose token overlap (lines 183–235). There is no metric ontology, denominator, polarity, aggregation-level, or measure-kind check.

### P0 — The mandatory four-case demonstration is not reliable

The README describes the cases as “verified against ground truth,” but the database does not support that assertion.

1. **Corroboration:** The advertised RBI-page-91/IMF-page-10 6.5% example is not represented correctly. The table-derived RBI page-91 `6.5` is stored as FY2024; its FY2025 GDP entry is wrongly stored as `6.4`. A different card links IMF page 10 with RBI page 8 at 6.5%, but labels the RBI reported historical sentence as a `projection`. Other corroborations use bare quotes such as `"6.4"`, which cannot prove entity, metric, period, or unit to a reviewer.
2. **Contradiction:** The claimed current-account example compares IMF's 0.6% *deficit* with RBI's -1.3% *balance*. The system neither models the deficit/balance polarity transformation nor preserves the RBI table row as grounded evidence. The RBI fact is marked `projection`, has unit `%` rather than `% of GDP`, and cites a long undifferentiated number run.
3. **Reconciliation:** An Economic Survey 6.4% / RBI 6.5% card does exist, but the selected reconciling text only states that the Survey uses First Advance Estimates. The paired RBI quote does not establish its second-estimate vintage. The fallback can return YES merely because a nearby candidate contains a variance keyword and overlaps two attribute tokens ([`engine.py`](src/comparison/engine.py), lines 434–443). Several unrelated reconciliations prove that this is not a trustworthy explanation mechanism.
4. **Failure case:** There is no failure-record schema, failure endpoint, or UI element. The failure is described in prose in `README.md`/`DECISIONS.md`; it is not a system result with source evidence and handling. The pipeline has no OCR, chart-extraction strategy, extraction-error persistence, or user-visible “unable to extract this chart” state.

The submission can show cards, but it cannot demonstrate the required cases with enough correctness to earn credit for them.

### P0 — “Verbatim grounding” does not ground a fact

The extractor verifies only that an LLM-supplied quote is present in the chunk. It does **not** verify that the entity, attribute, numeric value, unit, period, or assertion type is supported by that quote ([`src/extractor/extractor.py`](src/extractor/extractor.py), lines 101–184). A valid sentence from the same chunk can therefore support a fabricated value.

The relaxed rule is worse than documented. Rather than token overlap between quote and source spans, it counts whether each quote word occurs anywhere in the whole chunk using substring membership (lines 120–125). Of the 275 shipped facts, only 143 have an exact normalized quote substring. The remaining **132 facts (48%) pass only this bag-of-words rule**. Repeated common words are counted repeatedly, order and proximity are ignored, and a large table makes the check particularly weak.

The presence of `source_page` and `chunk_id` is useful provenance metadata, but it does not repair this semantic-evidence gap. Evidence needs a stable source-file identity plus a bounded text/cell span that directly proves each normalized field.

## Serious findings

### P1 — Semantic facts cannot survive the persistence boundary

`save_fact` stores nonnumeric values in `value_text` ([`src/db/database.py`](src/db/database.py), lines 117–126). After reload, the comparison engine reads only `value` and returns no relation when it is `NULL` ([`engine.py`](src/comparison/engine.py), lines 262–340); the UI also renders `fact.value`, not `value_text` ([`src/templates/index.html`](src/templates/index.html), lines 115–117). The unit test for categorical comparison passes in-memory dictionaries and therefore misses the database behavior. This fails the assignment's request for meaningful numerical **or semantic** facts.

### P1 — Incremental ingestion and reruns are not implemented

The upload route creates a fresh random document slug on every upload (`{safe_stem}_{file_id}`) then calls `deactivate_previous_runs` using that new slug ([`src/app.py`](src/app.py), lines 130–174). Uploading the same PDF twice never selects its prior facts, so it cannot deactivate them. The test named `test_reupload_deactivates_stale_facts` calls the database helper directly with an artificially stable document key; it does not exercise the endpoint's actual identity design.

Relations are not scoped to an extraction run and are never deleted or deactivated. `get_all_relations` returns every historical relation ([`src/db/database.py`](src/db/database.py), lines 264–270), while the dashboard silently skips relations whose facts are no longer active. The API nevertheless returns stale relation rows. There is no SHA-256 document fingerprint, document table, version model, run status, idempotency key, or fact fingerprint.

### P1 — New-document processing is synchronous, unbounded in work, and depends on two opaque remote services

The upload route parses the full document whenever `max_pages` is omitted; the UI currently sends 10 pages for its selected fast-demo option. Either path makes one or more remote LLM calls per chunk, sleeps between chunks, runs every comparison, and returns only at the end. There is no job queue, progress API, cancellation, deadline, retry classification, page cap, token cap, concurrency control, or durable failure state. A 50 MiB PDF can contain thousands of pages or pathological content. The arbitrary `max_pages` form field has no maximum.

Live extraction requires both an OpenRouter key and a cold `SentenceTransformer` model download. The README calls this optional, but the assignment explicitly requires a system that accepts new PDFs. No recording, mock provider, local fallback, deterministic fixture, cost estimate, data-sharing disclosure, or end-to-end upload test demonstrates that a reviewer can actually obtain a result. The app catches and hides reconciliation LLM failures, then can apply a heuristic anyway (lines 414–443), which is particularly dangerous for a fact-verification product.

### P1 — Parser quality gates do not detect the failures they claim to detect

The numeric-column validation only looks for a digit anywhere in a cell ([`pdf_chunker.py`](src/parser/pdf_chunker.py), lines 129–147); it cannot validate row/column semantics. It treats chart graphics extracted as garbled text as a normal table or prose chunk. A real Economic Survey chunk contains reversed chart labels and plot numbers, and a real RBI first-page parse sends an entire contents page to the LLM. There is no table-cell coordinate preservation, header hierarchy, reading-order check, chart detection, OCR routing, or confidence-based quarantine.

The parser's “fallback” merely joins broken cells as raw text and then still sends them through the same extractor. Lowering a hint to 0.5 has no effect because the extractor does not use `extraction_confidence_hint`.

### P1 — Reconciliation is keyword-triggered rather than evidence-led

Candidate evidence is gathered from neighboring pages or chunks based on a generic list of terms such as `advance`, `revised`, `definition`, and `methodology`. The deterministic fallback treats a candidate as a reconciliation if it contains one of those words and shares two tokens with the attributes. It does not demonstrate that the candidate applies to both facts or that it accounts for their values, units, scope, and periods. That design explains the false reconciliations above.

The LLM reconciliation prompt is also built from untrusted PDF content without the extraction route's document delimiter/instruction defense. The response's `reason` is discarded; only a truncated candidate sentence is stored. There is no auditable model output, prompt version, or human-review status.

### P1 — Security and operational controls are incomplete

The extension check, filename normalization, magic-byte check, and 50 MiB streaming limit are good starts. They are not sufficient for a public upload API:

- No authentication, authorization, ownership, rate limiting, request-size enforcement at the proxy, malware scanning, retention policy, or delete endpoint exists.
- `'%PDF-'` is not a meaningful safety validation of an adversarial PDF. `pdfplumber` is invoked in-process without CPU, page-count, decompression, or renderer isolation limits.
- `POST /api/run-comparison` is unauthenticated and can trigger expensive embedding and remote reconciliation work repeatedly.
- Chunks and LLM-bound source text can contain sensitive document content, but the README does not disclose sending it to OpenRouter.
- The template relies on `https://cdn.tailwindcss.com`, so the supposedly simple local UI is not fully self-contained or offline-reproducible.

### P2 — Storage and resource handling need production discipline

The schema has no migration version, document identity, normalized-unit field, evidence span, model/version provenance, error table, relation-review state, or database constraints for allowed relation/assertion types. `INSERT OR REPLACE` can delete-and-reinsert records rather than perform intentional updates. There is no unique fact fingerprint.

The normalizer also has untested calendar/fiscal edge cases. Direct execution maps `"fiscal year ended March 31, 2024"` to `FY2031`, because the fiscal-year regex captures the day (`31`) before the year. This is exactly the style of phrasing common in corporate filings. The UI presents only a source-doc slug and page number; it provides no link, preview, or highlighted source span in the original PDF, so a reviewer cannot inspect the claimed evidence in place.

`get_chunks_by_page`, `get_all_chunk_texts`, and `get_all_page_chunks` open connections but never close them ([`src/db/database.py`](src/db/database.py), lines 305–336). The thread-local “pool” is then regularly closed by callers, so it is neither a robust pool nor a clean request-lifetime connection strategy.

The blocking index does not provide the claimed scale guarantee: a corpus dominated by common `%` FY2025 facts, as financial corpora often are, remains quadratic within that block. Loading every chunk and every page group into memory per comparison is likewise not viable for many large PDFs.

## Test and submission-quality assessment

There are 41 test functions, not the 29 claimed by the README. That is not a problem by itself; the problem is what is and is not tested.

- No test runs the extraction pipeline on a supplied PDF with a fixture LLM response and asserts correct table field alignment.
- No test checks fact precision, relation precision, duplicate semantic relations, semantic facts after a DB round-trip, the real upload/rerun lifecycle, relation invalidation, OCR/chart failure reporting, or an actual evidence span.
- Several tests assert implementation text or helper behavior rather than user-visible behavior. `test_prompt_injection` inspects source code strings. The reconciliation tests explicitly encode the unsafe keyword fallback as desired behavior.
- The golden evaluator is not a precision evaluation. It does not check entity, source document, source quote, or grounding; allows a ±1 page window; treats absent page/period as a match; and accepts as little as 40% of the golden attribute tokens. Against the shipped RBI data it reports only **18/30 recall (60.0%)** and **77.8% assertion-type accuracy**, despite these permissive rules.
- `requirements.txt` has no pytest or pinned lockfile. The README lacks an explicit Python version, an actual demo-video link/file, and a concise limitations/next-steps section. I found no submitted video artifact.

The Git history is readable and uses reasonable commit messages. It cannot compensate for the absence of credible end-to-end validation or for incorrect shipped data.

## What is worth retaining

The candidate made several sound choices that should be retained in a redo: a compact FastAPI/Jinja interface, SQLite with foreign keys and indexes, PDF upload filename sanitization, bounded streamed writes, explicit source-page fields, stored chunks, a unit-normalization starting point, and a desire to separate corroboration from contextual reconciliation. The code is organized into understandable modules and compiles successfully. These are promising foundations, not evidence that the present fact layer is correct.

## Rubric outcome

| Assignment requirement | Assessment |
|---|---|
| Extract meaningful facts | Fails reliability gate. The shipped table facts are demonstrably wrong and duplicated. |
| Link every fact to source evidence | Fails. Page/chunk metadata exists, but many quotes are bare values or loose bag-of-words matches and do not support the represented fact. |
| Corroborate, contradict, reconcile, and explain | Fails. The comparison set contains false contradictions and false reconciliations; contextual explanations are keyword-driven. |
| Show four required cases | Fails as a trustworthy demo. Case 4 is documentation, not system output; the first three use flawed stored facts/cards. |
| Accept additional PDFs without document-specific rules | Partially implemented endpoint only. It requires an external paid key and unbounded synchronous work; no credible end-to-end validation exists. |
| Scale, dynamic schema, incremental documents | Not demonstrated. The fixed schema is not dynamic, reruns do not replace prior uploads, and comparison remains quadratic in common blocks. |
| Run instructions, demo, limitations, clean history | Incomplete. Test dependency is omitted, no video is provided, and required live functionality depends on external credentials. |

## Minimum bar for reconsideration

1. Redesign table extraction around cells, row labels, multi-level headers, coordinates, and deterministic value/header alignment. Quarantine ambiguous tables rather than asking an LLM to guess.
2. Make evidence field-level: immutable file hash, page, bounding box or character offsets, quoted source span, and deterministic validation that each extracted value/unit/period occurs in that span or is an explicit documented derivation.
3. Add measure semantics before comparison: value kind (level/rate/growth/count), denominator, polarity, scope, population, consolidation level, period coverage, vintage, and explicit units. Do not compare candidates absent compatibility proof.
4. Delete the keyword-only reconciliation fallback. Store a reviewable, structured explanation linking both facts to concrete source evidence; route uncertainty to `not_comparable`/manual review.
5. Introduce document fingerprints, runs, fact fingerprints, relation validity/versioning, and true idempotent re-ingestion. Recompute or invalidate affected relations transactionally.
6. Put parsing/extraction/comparison in a bounded background job with progress, page/token/resource limits, retry policy, audit logs, and an explicit remote-data/privacy policy.
7. Add deterministic fixture-based end-to-end tests on prose, clean tables, malformed tables, charts, repeated uploads, semantic facts, and known-positive/known-negative relation sets. Report precision and recall, not only recall under permissive matching.

Until those changes are made and independently re-evaluated on held-out PDFs, I would reject this submission for a fact-knowledge-layer assignment.
