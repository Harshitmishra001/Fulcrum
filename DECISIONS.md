# Fulcrum - Decision Log

> **Purpose:** Every significant decision made during design and build is recorded here with its tradeoffs, the alternatives considered, and why the tradeoff was accepted. When you are confused about why something works the way it does, start here.
>
> **How to read it:** Each decision has four parts: What we decided, What we rejected, The tradeoff, and Why we accepted it.

---

## Table of Contents

1. Scope and Dataset Strategy
2. LLM Choice and Usage Pattern
3. PDF Parsing Library
4. Chunking Strategy
5. Multi-Page Table Merging
6. pdfplumber Silent Failure Detection
7. UI Framework
8. Database
9. Fact Schema - Free-Text Entity and Attribute
10. period.raw_text Verbatim and Separate Normalization
11. extraction_confidence - Rule-Based, Not LLM-Reported
12. extraction_confidence Threshold = 0.5
13. extraction_run_id Scoped Per-Document
14. is_active Flag for Dedup
15. chunk_id Encodes Page Number
16. Numeric Tolerance for Value Matching
17. assertion_type Blocks Comparison
18. Entity Resolution - Embedding Similarity and Thresholds
19. The Authorities Heuristic - 3-Sentence Window
20. Reconciliation - Retrieve then Classify, Never Generate
21. Adjacent Context = Conflicting Fact Quotes and 2-Page Neighborhood
22. Comparison Engine - Flat Classifier, Not Full Graph
23. LLM API Reliability - Retry and Write-Per-Chunk
24. Golden Set - 30 Facts Including assertion_type
25. Alias Eval Set Before Coding Entity Resolution
26. Build Order - Sequential, Not Parallel
27. Manual Figure Cross-Check as Step 0
28. Economic Survey Ingestion and Chart Limitation Holdout
29. Delhivery as Sealed Generalization Holdout
30. Tiering with a Hard Cut Line
31. Generalization Test - Prediction Committed Before Run
32. API Key and Pre-Cached Results for Submission
33. No Force-Directed Graph Visualization
34. Fiscal Year Normalization - Lookup Table, Not Parser
35. Unit Normalization - Small Fixed Table
36. Model Selection - GPT-4o-mini via OpenRouter (Budget-Constrained)
37. Anchor Metrics Confirmed for the Four Required Cases (Step 0)
38. Hybrid Development Strategy — Assistant-Curated Ground Truth and Pre-Cached Database
39. Pipeline Autonomy & Division of Labor (Generalization Safeguard)
40. Negative Token Filters & Concept Cluster Guards for Financial Attribute Matching
41. Single-Batch Vector Embedding Precomputation with In-Memory Caching
42. Strict Verbatim Grounding Invariant in Fact Extractor
43. Multi-Dimensional Unit Normalization and Scale Multipliers
44. SQLite WAL Mode, Busy Timeout, and Relational Deduplication
45. Complete Three-Document Triangulation (Full Economic Survey Ingestion)

---

## 1. Scope and Dataset Strategy

**What we decided:** Build and tune entirely on Dataset B (India Macro: RBI Annual Report, IMF Article IV, Economic Survey). Treat Dataset A (Delhivery) as a sealed holdout for the final generalization test only.

**What we rejected:** Building against both datasets simultaneously.

**The tradeoff:** Less total data to tune against during development. Cannot pre-validate that the pipeline handles corporate documents (Delhivery format) before the final test.

**Why we accepted it:** Tuning against both datasets during development contaminates the generalization test - you would be testing on data you have already seen. The whole point of the generalization test is to show the pipeline is not hardcoded. Keeping Delhivery sealed is what gives that test credibility. The assignment brief also explicitly requires demonstrating generalization.

---

## 2. LLM Choice and Usage Pattern

**What we decided:** Pick one capable general-purpose model (Claude or GPT-4o class) and use it for every LLM step: extraction, entity resolution tiebreaks, reconciliation classification. Model choice lives in a single config constant, not scattered across the codebase.

**What we rejected:** Using different models for different steps. Using a local model (Ollama + Llama 3) as the primary engine.

**The tradeoff:** Single cloud model means you pay for GPT-4o-class compute on every call, including simpler ones. A local model would be free and fully self-contained but significantly less accurate on complex structured extraction tasks.

**Why we accepted it:** For a hiring panel submission where extraction quality is being evaluated directly, the accuracy gap between a cloud model and a local 7B model matters. The four required cases need to be crisp and defensible. Mixing models also introduces an undebuggable variable: if a relation is wrong, you cannot tell if it came from the extraction model or the reconciliation model. Single model equals single failure domain.

---

## 3. PDF Parsing Library

**What we decided:** pdfplumber for all PDF parsing: table detection, text extraction, and page-level structure.

**What we rejected:** PyMuPDF (better raw text speed but weaker table detection). pdfminer.six (lower-level, requires more custom logic). camelot (strong table extraction but poor prose handling). AWS Textract or Azure Document Intelligence (cloud OCR, additional paid API dependency).

**The tradeoff:** pdfplumber can silently return garbage for tables with merged cells or rotated headers. You have to explicitly validate its output (see Decision 6).

**Why we accepted it:** pdfplumber is already installed in the environment, handles both prose and table extraction in one library, and is good enough for native PDFs. The validation checks added in Decision 6 mitigate its failure modes directly.

---

## 4. Chunking Strategy

**What we decided:** Chunk by structural unit: paragraph, table, or section. Never fixed token windows. Re-attach table header rows as explicit context in every extraction call for that table, not just the first call.

**What we rejected:** Fixed token-window chunking (e.g., split every 512 or 1024 tokens regardless of structure).

**The tradeoff:** Structural chunking is harder to implement. You have to detect paragraph and table boundaries, handle continuation tables across pages, and produce variable-length chunks.

**Why we accepted it:** Fixed token windows break tables. A window that cuts a table mid-row produces chunks where the year headers are in one chunk and the values are in the next. The model extracts a value but does not know which year it belongs to. This is the FY22 number labeled as FY24 failure mode. Re-attaching headers to every table extraction call is the direct fix.

---

## 5. Multi-Page Table Merging

**What we decided:** Merge across pages only if: (1) column count matches AND (2) the first row of the continuation page pattern-matches the last row of the previous page (both look like years, or both look like metric-name labels). If ambiguous, do not merge. Treat as separate table with lower extraction_confidence.

**What we rejected:** Merge on column count alone.

**The tradeoff:** The conservative rule will false-split some genuinely continuous tables. A false split loses a few rows of context but the fact is still correct. A false merge silently attaches the wrong metric rows to a table, producing facts with the wrong entity or wrong year.

**Why we accepted it:** False split is the safer failure direction. A false merge produces a fact that is wrong and enters the comparison engine silently, potentially producing a phantom corroboration or contradiction.

---

## 6. pdfplumber Silent Failure Detection

**What we decided:** Before trusting any parsed table, run two cheap validation checks: (1) every body row cell count matches the header row cell count; (2) columns whose header looks numeric or year-like actually parse as numbers for most rows. Fail either check and fall back to raw text extraction, set extraction_confidence low.

**What we rejected:** Trusting pdfplumber output without validation. Adding a full structural validation framework.

**The tradeoff:** Two checks will occasionally reject a table that is actually fine. Raw text extraction on a rejected table produces lower-quality facts.

**Why we accepted it:** pdfplumber failure mode is dangerous specifically because it is silent. A mis-split merged cell can produce a structurally valid-looking table full of garbage. Two cheap checks catch the most common failure patterns at near-zero implementation cost.

---

## 7. UI Framework

**What we decided:** FastAPI backend plus server-rendered HTML (Jinja templates) plus vanilla JS for upload interaction. No React, no build step, no npm dependency tree.

**What we rejected:** React or any SPA framework.

**The tradeoff:** Jinja-rendered HTML has limited interactivity. The UI will look more basic than a React app.

**Why we accepted it:** This is a demo-day reliability decision. React requires a working Node.js environment, npm install, a bundler, and a dev server running in parallel to FastAPI. Each is a failure point on demo day. A Jinja template renders directly from the FastAPI server: one process, zero build step, zero npm. For a 3-minute demo video, the UI job is to show argument cards clearly, not to be a polished product.

---

## 8. Database

**What we decided:** SQLite. Tables: facts and relations. No graph database.

**What we rejected:** PostgreSQL (requires a running server process). Neo4j or similar graph DB (semantically appealing but adds significant dependency and setup burden). In-memory or flat files (not durable across re-runs).

**The tradeoff:** SQLite is single-writer. It does not natively support graph traversal queries.

**Why we accepted it:** The brief explicitly says a graph database or visualization alone is not the solution. SQLite is zero-setup, ships with Python standard library, is durable, and sufficient for this prototype scale. The comparison engine operates on fact pairs from a SQL JOIN, not a graph traversal.

---

## 9. Fact Schema - Free-Text Entity and Attribute

**What we decided:** entity and attribute are free-text strings, not enums or controlled vocabularies.

**What we rejected:** Pre-defining a fixed ontology of entities and attributes.

**The tradeoff:** Free-text means entity resolution is harder. "Government of India", "GoI", and "the government" are three different strings that mean the same thing.

**Why we accepted it:** A controlled ontology requires knowing in advance every entity and attribute type you will encounter. The brief explicitly requires the system to generalise to new PDFs with unknown fact types. A fixed enum breaks immediately on a new document type such as Delhivery. Entity resolution via embeddings handles the free-text alignment problem without requiring a pre-defined schema.

---

## 10. period.raw_text Verbatim and Separate Normalization

**What we decided:** The LLM outputs period.raw_text exactly as written in the source ("FY2024-25", "fiscal year ended March 2025"). A separate deterministic normalization step with no LLM maps these to a canonical form (FY2025).

**What we rejected:** Having the LLM silently normalize the period at extraction time.

**The tradeoff:** Two-step process is more code than one-step. The raw text takes up schema space.

**Why we accepted it:** If the LLM normalizes silently, you lose the ability to audit what the model actually read versus what you inferred. When a period mismatch causes a false contradiction, you cannot tell whether the documents genuinely disagree or whether the model mis-normalized. Keeping raw_text verbatim means every inference is traceable. Normalization is also the kind of thing LLMs silently get wrong on edge cases. A deterministic regex lookup is safer and fully testable.

---

## 11. extraction_confidence - Rule-Based, Not LLM-Reported

**What we decided:** extraction_confidence is computed deterministically from three signals: (1) source_quote found verbatim in chunk = +0.5, (2) value parses as a clean number = +0.3, (3) period.raw_text is non-empty = +0.2.

**What we rejected:** Asking the LLM to rate its own confidence on a scale of 0 to 1.

**The tradeoff:** The rule-based score is coarser. It cannot capture subtle cases where the quote is found verbatim but the LLM still hallucinated the value.

**Why we accepted it:** LLM self-reported confidence is notoriously miscalibrated. Models express high confidence on wrong answers. A model that fabricates a number will still give that fabrication a confidence of 0.9. The rule-based score is coarse but honest and auditable. The grounding check (quote found verbatim) is a hard signal that an LLM self-score cannot fake.

---

## 12. extraction_confidence Threshold = 0.5

**What we decided:** Facts with extraction_confidence below 0.5 are excluded from the comparison engine entirely. Starting value is 0.5; tune after golden set evaluation.

**What we rejected:** No threshold at all. A higher threshold like 0.8.

**The tradeoff:** Threshold too low means noisy facts pollute the comparison engine. Threshold too high means real facts are excluded, possibly losing one of the four required cases.

**Why we accepted it:** 0.5 means a fact must at minimum be grounded (quote found verbatim, +0.5) to enter comparison. A fact with no grounding could be a hallucination. This is the non-negotiable minimum bar. The threshold is a named constant so it can be tuned after golden set evaluation.

---

## 13. extraction_run_id Scoped Per-Document

**What we decided:** extraction_run_id is scoped to a single document extraction attempt. Re-extracting RBI only flips RBI facts to is_active false. IMF facts from a different run are untouched.

**What we rejected:** Scoping extraction_run_id to the full pipeline run where all documents share one ID.

**The tradeoff:** Per-document versioning means different documents can have facts from different run timestamps.

**Why we accepted it:** You will re-run extraction on a single document far more often than you will re-run everything. Full-pipeline scoping makes fixing RBI require re-extracting IMF too, wasting 150 to 250 LLM calls on a document that did not change. The practical cost of per-document versioning is far smaller than forced full re-runs at several dollars each.

---

## 14. is_active Flag for Dedup

**What we decided:** When a document is re-extracted, old facts are marked is_active false (not deleted). Comparison engine and UI only ever query is_active true facts.

**What we rejected:** Deleting old facts on re-extraction.

**The tradeoff:** Keeping inactive facts means the database grows over time. Querying must always filter WHERE is_active = true.

**Why we accepted it:** Without history you cannot compare old facts with new facts to understand what a prompt change did. Deletion loses that. Making is_active filtering a required convention is a small discipline cost for a large debugging benefit.

---

## 15. chunk_id Encodes Page Number

**What we decided:** chunk_id is encoded as {doc_slug}__p{page:04d}__{type}__{index:04d}, for example rbi__p0047__table__003. Page number is always recoverable from chunk_id without a separate column.

**What we rejected:** Using a bare UUID for chunk_id and adding a separate source_page column.

**The tradeoff:** The structured chunk_id format requires discipline. Every chunker must produce IDs in this exact format.

**Why we accepted it:** A separate column means you have to keep it in sync with chunk_id at every write. If they diverge due to a bug, you have two sources of truth that disagree. Encoding page number deterministically in the ID means it can never go out of sync. It is derived, not stored separately.

---

## 16. Numeric Tolerance for Value Matching

**What we decided:** Percentage and rate values (unit ends in percent or bps): match if abs(a - b) is at or below 0.1. Large absolute values (crore, billion): match if relative difference is at or below 0.01 (within 1 percent). Strings, codes, and ratios without a unit: strict equality only.

**What we rejected:** Strict equality for all numeric values.

**The tradeoff:** The 0.1pp tolerance for percentages means values that genuinely differ by up to 0.1pp will be classified as corroborations. This could hide a real 0.1pp disagreement.

**Why we accepted it:** RBI rounds to 1 decimal place; IMF often rounds to 2. The same underlying number such as 6.47 percent appears as 6.5 percent in RBI and 6.47 percent in IMF. Strict equality classifies this as a contradiction, breaking the flagship corroboration case. The 0.1pp threshold is narrow enough to catch only rounding differences. 6.4 vs 7.0 is 0.6pp apart and correctly classified as a contradiction. The threshold is explicitly documented so it can be changed.

---

## 17. assertion_type Blocks Comparison

**What we decided:** If two facts have different assertion_type (one is stated, the other is projection), they are NOT classified as corroboration or contradiction regardless of whether their values match. Label: "different claim type."

**What we rejected:** Comparing all facts on values alone regardless of assertion type.

**The tradeoff:** You will sometimes block a genuinely interesting comparison, for example an IMF projection that matched RBI stated figure.

**Why we accepted it:** IMF commonly issues projections alongside RBI or GoI stated figures for the same metric. If assertion_type is ignored, a projection matching a stated fact looks like corroboration. But a projection is a forecast and a stated figure is a reported outcome. Collapsing them produces a false corroboration that falls apart under a follow-up question during the demo.

---

## 18. Entity Resolution - Embedding Similarity and Thresholds

**What we decided:** Use sentence embedding cosine similarity to match entities across documents. Three bands: at or above 0.85 is high confidence and proceeds normally; 0.65 to 0.85 is low confidence and comparison proceeds but the relation is labeled uncertain; below 0.65 means no relation is created. Starting thresholds are tuned after the alias eval set smoke test.

**What we rejected:** String matching only (fails on semantic aliases like GoI versus Government of India). LLM-based entity resolution for every pair (too expensive at scale). Binary resolved or not-resolved with no confidence propagation (hides uncertainty).

**The tradeoff:** Off-the-shelf embeddings may not perfectly cluster domain-specific financial abbreviations. They may score GoI and Government of India below 0.85.

**Why we accepted it:** The confidence bands mean wrong matches do not produce confident-looking relations. They produce visibly flagged, uncertain ones. The alias eval set (Decision 25) validates whether thresholds work on actual document vocabulary before the full pipeline runs.

---

## 19. The Authorities Heuristic - 3-Sentence Window

**What we decided:** IMF phrase "the authorities" is resolved to RBI or GoI using a keyword vote in a 3-sentence window (3 before plus 3 after). Monetary cues (repo rate, MPC, liquidity, inflation target, reserve money, policy rate) resolve to RBI with confidence 0.70. Fiscal cues (fiscal deficit, budget, expenditure, revenue, subsidy, tax, GST, borrowing) resolve to GoI with confidence 0.70. Tied or zero hits resolve to AMBIGUOUS with confidence 0.40, which falls below the 0.65 threshold and creates no relation.

**What we rejected:** Always resolve to GoI. Ask the LLM to resolve every instance. Ignore all "the authorities" facts entirely.

**The tradeoff:** The 3-sentence window will miss context cues more than 3 sentences away. The keyword list is finite. A new cue word not in the list causes a wrong AMBIGUOUS result. The heuristic will misfire on paragraphs that discuss both monetary and fiscal policy simultaneously.

**Why we accepted it:** Ignoring "the authorities" loses a significant portion of IMF facts. The AMBIGUOUS path means that when the heuristic is genuinely unsure, it fails safe by creating no relation rather than a wrong one. Every resolution is logged with keyword counts so misfires are visible.

---

## 20. Reconciliation - Retrieve then Classify, Never Generate

**What we decided:** Three-step grounded reconciliation. Step 1 is deterministic retrieval: scan candidate explanatory text from the grounded source quotes of the conflicting facts and neighboring facts within a 2-page window of the same document in SQLite, matching explicit revision and definitional cues (advance estimate, revised estimate, provisional, definition, methodology, authorities). Step 2 is zero-generation LLM classification on the retrieved candidate sentence: YES, PARTIAL, or NO. Does this sentence explain why the two values differ? The LLM is strictly forbidden from hallucinating or generating new explanations. Step 3 is deterministic assignment: YES means reconciled; PARTIAL means candidate reconciliation; NO means contradiction.

**What we rejected:** Asking the LLM to freely generate an explanation without retrieved candidate evidence. Full-text document-wide BM25 indexing that exceeds prototype complexity.

**The tradeoff:** Contextual retrieval relies on explanatory notes appearing within the grounded quotes of the conflicting facts or neighboring page facts in the same document. Reconciliations buried in distant annexes without extracted facts are classified as unresolved contradictions.

**Why we accepted it:** If you ask an LLM to explain why two conflicting numbers differ without grounding, it will fabricate convincing-sounding economic reasons. Grounding the reconciliation strictly on retrieved document sentences ensures every explanation is directly traceable to the source PDF.

---

## 21. Adjacent Context = Conflicting Fact Quotes and 2-Page Neighborhood

**What we decided:** "Adjacent context" for reconciliation retrieval is scoped to the grounded source quotes of the conflicting facts, expanding to neighboring facts within a 2-page window of the same document in SQLite.

**What we rejected:** Full-document generative querying or broad cross-document hallucination.

**The tradeoff:** Narrow page-scoped context will miss methodological explanations located in appendices 50 pages away from the data tables.

**Why we accepted it:** Scoping context to neighboring grounded facts in the same document keeps retrieval fast, verifiable, and free of hallucination risk.

---

## 22. Comparison Engine - Flat Classifier, Not Full Graph

**What we decided:** The comparison engine is a flat classifier (corroboration, contradiction, reconciled, or unresolved) operating on fact pairs. Not a full argumentation graph with attack, support, and undercut relations and a fixpoint solver.

**What we rejected:** Building the full argumentation graph for Tier 1 MVP.

**The tradeoff:** The flat classifier cannot handle multi-fact chains. It cannot produce "undecided" outputs for odd cycles.

**Why we accepted it:** The brief explicitly states a smaller understandable prototype is better than a large system whose behavior is unclear. The flat classifier directly produces all four required cases. Partial graph-theory code that does not run is worse than a flat classifier that does.

---

## 23. LLM API Reliability - Retry and Write-Per-Chunk

**What we decided:** Two required reliability mechanisms. First: exponential backoff with 3 retries per call and a 30-second timeout per call. Second: write extracted facts to SQLite after each chunk so that if the run crashes at chunk 412, it resumes from chunk 413 next time.

**What we rejected:** Running without retry logic and writing to DB only at the end of a full run.

**The tradeoff:** Write-per-chunk means more SQLite write operations. The resume logic adds code complexity.

**Why we accepted it:** 500 to 750 sequential API calls will hit a rate limit or transient error before completing. Without retry, one error aborts the entire run and wastes the preceding compute and API cost. Both mechanisms are under 20 lines of code each. The cost of not having them is a full re-run at several dollars every time a transient error occurs.

---

## 24. Golden Set - 30 Facts Including assertion_type

**What we decided:** Before writing any extraction code, manually annotate approximately 30 facts from the RBI report: value, unit, period, assertion_type, and source quote. Score every extraction run against this set for precision and recall including assertion_type accuracy.

**What we rejected:** A one-time eyeball pass as the evaluation method.

**The tradeoff:** Building the golden set takes 1 to 2 hours upfront before writing any code.

**Why we accepted it:** Without a fixed answer key you cannot tell whether a prompt change made extraction better or worse. Including assertion_type in the golden set catches silent misclassification before the comparison engine is built. If the LLM tags projections as stated, the comparison engine guard is decorative.

---

## 25. Alias Eval Set Before Coding Entity Resolution

**What we decided:** Before implementing entity resolution, hand-write 10 to 15 known alias pairs from the actual documents and run embedding similarity against them. Adjust thresholds based on real scores.

**What we rejected:** Implementing entity resolution and tuning thresholds empirically on the full pipeline output.

**The tradeoff:** 30 minutes of manual work before coding.

**Why we accepted it:** Entity resolution was flagged as the hardest piece of the pipeline. Without a small validation set you do not know if off-the-shelf embeddings cluster GoI and Government of India above 0.85. Discovering this during full pipeline integration means debugging across two systems simultaneously.

---

## 26. Build Order - Sequential, Not Parallel

**What we decided:** Build in strict sequential order: figure cross-check, golden set, Tier 0, IMF extraction, normalization, entity resolution, comparison engine, storage and UI, demo, Tier 2 if time allows.

**What we rejected:** Building components in parallel.

**The tradeoff:** Sequential means you cannot parallelize work. If you get stuck on one step, everything downstream blocks.

**Why we accepted it:** Each step feeds the next. If extraction is wrong, entity resolution has wrong inputs. Any debugging at the entity resolution layer is wasted because the problem is upstream. The most expensive mistake is building the comparison engine on top of unverified extraction.

---

## 27. Manual Figure Cross-Check as Step 0

**What we decided:** Before writing any code, open all three PDFs manually and record four key figures from each source: GDP growth rate for FY2025, CPI inflation, fiscal deficit as percent of GDP, and CAD as percent of GDP. Commit this table as FIGURES.md.

**What we rejected:** Discovering whether contradictions actually exist in the documents during extraction.

**The tradeoff:** 30 minutes of manual reading before any code.

**Why we accepted it:** The entire build plan assumes a real contradiction exists in the datasets. If it does not, the build plan needs to change. Discovering this during demo recording is catastrophic. Discovering it in 30 minutes of reading before any code costs almost nothing and de-risks the entire build. This also informs which facts to prioritize in the golden set annotation.

---

## 28. Economic Survey Ingestion and Chart Limitation Holdout

**What we decided:** Ingest all native text and table sections of the Economic Survey excerpt into the active knowledge layer (yielding 46 high-confidence facts), while isolating its vector/raster charts (e.g., Charts I.29 and I.46) as the controlled demonstration for Required Case 4 (Failure Case).

**What we rejected:** Treating the entire Economic Survey as an unextracted holdout, or attempting to force text-based pdfplumber to parse complex vector chart images.

**The tradeoff:** Ingesting 46 additional facts expands the comparison space to 275 active facts, requiring efficient pairwise evaluation and neighborhood context linking.

**Why we accepted it:** All three starter documents must be active in the knowledge layer to achieve genuine triangulation. Ingesting the Economic Survey's native text uncovers the 6.4% First Advance Estimate for FY25, directly enabling empirical reconciliation against RBI's 6.5% Second Advance Estimate (Case 3). Simultaneously, preserving its visual charts as the Case 4 failure mode provides an honest, empirical demonstration of text parser limits without sacrificing document coverage.

---

## 29. Delhivery as Sealed Generalization Holdout

**What we decided:** Dataset A (Delhivery: Prospectus, Annual Report FY24, Q4 Earnings Deck) is not opened, referenced, or tuned against until the final generalization test. The test is run once with the prediction written first and committed to GENERALIZATION.md before running. Results are honestly reported.

**What we rejected:** Using Delhivery as a second training and development dataset.

**The tradeoff:** You cannot pre-validate that the pipeline handles corporate documents before the final test. You may discover a critical failure mode only during the final test with no time to fix it.

**Why we accepted it:** The generalization test is the only credible evidence that the system does not rely on hardcoded facts or document-specific rules. If you debug against Delhivery during development, the test proves nothing. A failure on Delhivery, honestly reported with a specific prediction and a clear next step, is a stronger submission than a system that appears to generalize but was secretly tuned on both datasets.

---

## 30. Tiering with a Hard Cut Line

**What we decided:** Three explicit tiers: Tier 0 (extraction verified trustworthy), Tier 1 (MVP flat classifier and all four required cases), Tier 2 (stretch features). Hard rule: do not start Tier 2 until Tier 1 is fully working and demoed once end to end.

**What we rejected:** Building optimistically toward Tier 2 features while Tier 1 is still incomplete.

**The tradeoff:** If Tier 1 takes longer than expected, you ship with a flat classifier instead of an argumentation graph.

**Why we accepted it:** The brief states a smaller understandable prototype is better than a large system whose behavior is unclear. Partial Tier 2 code that does not run is worse than a working Tier 1. Tiering forces you to ship something working at every cut point.

---

## 31. Generalization Test - Prediction Committed Before Run

**What we decided:** Before running the pipeline on Dataset A, write a specific failure prediction in GENERALIZATION.md and commit it to git. The git timestamp proves the prediction preceded the test. Run the test. Append the actual result.

**What we rejected:** Running the test, observing the result, then writing the prediction retrospectively.

**The tradeoff:** If the prediction is wrong in a positive direction (the pipeline handles Delhivery better than expected), the committed prediction looks overconfident in hindsight.

**Why we accepted it:** A prediction that was wrong in a positive direction is excellent evidence of a robust pipeline. A prediction written after the fact is not a prediction. It is narrative. The git timestamp converts the test from a demo stunt into evidence you can defend.

---

## 32. API Key and Pre-Cached Results for Submission

**What we decided:** Use a cloud LLM API during build. For submission: pre-run the full pipeline on all three India Macro PDFs, store results in SQLite, include the pre-populated database in the repository. The demo video shows the UI reading from pre-cached results. README documents how to re-run with your own key.

**What we rejected:** Local model only (fully self-contained, no key needed). Requiring evaluators to have their own API key to see any results.

**The tradeoff:** Evaluators who want to re-run the full pipeline need an API key. The submission is not fully self-contained for re-running.

**Why we accepted it:** The assignment brief explicitly states: if the project requires a paid service, include enough sample output and video footage for us to evaluate it without needing your account. Cloud model accuracy on structured extraction from dense financial PDFs is significantly better than a local 7B model. For a hiring panel evaluating extraction quality, this matters.

---

## 33. No Force-Directed Graph Visualization

**What we decided:** The UI shows argument cards: one per fact, with source quote, related facts, and relation type. No force-directed graph visualization.

**What we rejected:** A graph visualization using D3.js or vis.js showing facts and their relations as nodes and edges.

**The tradeoff:** A graph visualization is visually impressive and intuitive for showing relationships. Argument cards are less visually striking.

**Why we accepted it:** The brief explicitly states "a graph database or visualization alone is not the solution. The interesting part is how facts are discovered, grounded, compared, and explained." Argument cards force the UI to show the reasoning: the source quote, the relation type, the evidence. A node in a force-directed graph tells you nothing. An argument card shows you exactly what the system found and why.

---

## 34. Fiscal Year Normalization - Lookup Table, Not Parser

**What we decided:** Build a closed lookup table mapping known fiscal year string patterns to canonical form. FY2024-25, FY2024/25, FY25, and 2024-25 all map to FY2025. Not a general-purpose date parser.

**What we rejected:** Using a general date parsing library such as dateutil or arrow. Asking the LLM to normalize periods.

**The tradeoff:** The lookup table only handles patterns explicitly included. An unexpected format will produce period.normalized = null rather than normalizing correctly.

**Why we accepted it:** General date parsers are designed for calendar dates, not Indian fiscal year conventions. LLMs silently normalize edge cases incorrectly. A lookup table is fully testable, fails explicitly on unknown patterns rather than silently wrong, and covers most of the actual patterns in RBI and IMF documents.

---

## 35. Unit Normalization - Small Fixed Table

**What we decided:** Build a small fixed conversion table for the units that appear in these specific documents: Rupee Crore, Rupee Lakh, and USD billion converted to one canonical unit for comparison purposes, keeping the original for display.

**What we rejected:** A general-purpose unit conversion library or dynamic unit discovery.

**The tradeoff:** Only handles units explicitly included. A new document type with different units requires adding to the table manually.

**Why we accepted it:** The scope is three specific documents from Indian macroeconomic institutions. The unit vocabulary is small and known. A general-purpose library adds complexity without adding value for this scope. When a new document type arrives, the table may need additions but that is a one-line change, not a library swap.

---

---

## 36. Model Selection - GPT-4o-mini via OpenRouter (Budget-Constrained)

**What we decided:** Use GPT-4o-mini accessed through OpenRouter as the single LLM for all pipeline steps. Not GPT-4o, not Claude 3.5 Sonnet.

**What we rejected:** Frontier models (GPT-4o, Claude 3.5 Sonnet). Local models (Ollama + Llama 3).

**The tradeoff:** GPT-4o-mini is meaningfully less capable than GPT-4o on complex reasoning tasks. On structured extraction from financial PDFs, the quality gap is smaller than on open-ended tasks, but it exists. Edge cases in the extraction prompt (ambiguous assertion_type classifications, unusual period formats) are more likely to misfire on a smaller model. The golden set evaluation (Decision 24) will surface whether quality is acceptable before the full pipeline runs.

**Why we accepted it:** The available budget is  on OpenRouter. A full pipeline run (500-750 calls) on GPT-4o costs approximately .25 - over budget with nothing left for debugging iterations. GPT-4o-mini costs approximately .32 per full run, leaving .68 for golden set prompt tuning, re-runs after chunking fixes, and the Delhivery generalization test. This task (extract structured facts from dense financial prose into a fixed schema) is well-defined enough that a smaller model with a precise prompt performs adequately. If golden set evaluation reveals unacceptable quality, the model is a one-line config change.

**OpenRouter-specific note:** OpenRouter adds a small margin on top of provider prices. Actual costs may be 5-10% higher than the raw model prices above. Budget math still holds comfortably.

**If budget increases:** Swap to GPT-4o or Claude 3.5 Sonnet via the same OpenRouter integration - one config line change, no other code changes. This is why Decision 2 (single model, one config constant) matters.

**Models explicitly considered and rejected for this budget:**

DeepSeek V4 Pro 0813 (\.99 input / \.97 output per 1M): A strong MoE model, likely higher quality than GPT-4o-mini. Rejected because a full pipeline run costs approximately \.64, consuming 82% of the total \ budget in one shot. No headroom for re-runs after chunking fixes or prompt iterations. Quality gain does not justify the constraint.

Gemini 3.7 Flash (\.75 input / \.75 output per 1M): The only model with multimodal capability, which would be genuinely useful for Economic Survey chart extraction (Required Case 4). Rejected as the primary extraction model for the same budget reason (~\.61 per full run). Accepted as a targeted fallback: if Tier 2 is reached and chart extraction is pursued, run Gemini 3.7 Flash only over the Economic Survey PDF (~95 pages, ~\.10) rather than the full corpus. One config value change scoped to that single call.

---

---

## 37. Anchor Metrics Confirmed for the Four Required Cases (Step 0)

**What we decided:** Anchor the four required assignment cases around the specific metrics verified in FIGURES.md during Step 0:
1. Corroboration: Real GDP Growth FY2024-25 (6.5% in RBI and IMF) and Headline CPI Inflation (4.6% in RBI and IMF).
2. Contradiction: Current Account Deficit FY2024-25 (RBI reports 1.3% of GDP vs IMF staff reports 0.6% of GDP).
3. Reconciled via Context: Real GDP growth FY25 (6.4% in Economic Survey as First Advance Estimates vs 6.5% in RBI as Second Advance Estimates) and Fiscal Deficit FY25 (4.7% in RBI vs 4.9% in IMF with authorities definition footnote).
4. Failure Case: Economic Survey vector-rendered chart images (Charts I.29 and I.46 on pages 20 and 29) where quarterly data is locked in graphics without text tables.

**What we rejected:** Assuming metrics would diverge during pipeline execution or picking metrics arbitrarily without verifying they exist in all documents.

**The tradeoff:** We focus verification on these macroeconomic pillars rather than discovering random fact pairs during the demo.

**Why we accepted it:** Verifying the actual numbers in the source text before writing extraction code ensures our golden set and downstream rules test real document phenomena rather than hypothetical edge cases.

---

---

## 38. Hybrid Development Strategy — Assistant-Curated Ground Truth and Pre-Cached Database

**What we decided:** Use the IDE assistant (Gemini 3.8 Flash High) to directly curate the ground truth Golden Set (data/golden_set_rbi.json), the alias evaluation set (data/alias_eval_pairs.json), and perform local PDF inspection (FIGURES.md) at zero API cost. The standalone Python application connects to OpenRouter (openai/gpt-4o-mini) only for automated pipeline execution, and the starter dataset extractions are pre-cached in fulcrum.db.

**What we rejected:** Using automated LLM calls to discover facts, generate answer keys, or repeatedly re-extract the full corpus during development and demo recording.

**The tradeoff:** Hand-annotating the golden set requires upfront human/assistant curation rather than an end-to-end autonomous discovery pipeline.

**Why we accepted it:** Reduces runtime API spend from ~.80-.00 down to ~.31-.35 total (saving 75-85% of the .18 budget). It completely eliminates the risk of running out of credits during prompt tuning or demo recording, and ensures the demo video loads pre-cached SQLite data instantly without live latency bottlenecks.

---

---

## 39. Pipeline Autonomy & Division of Labor (Generalization Safeguard)

**What we decided:** The extraction, entity resolution, and comparison pipeline MUST be executed autonomously by code calling the LLM via OpenRouter. The IDE assistant only builds the plumbing (PDF chunker, database schema, deterministic normalizers, scoring scripts, and the evaluation answer key). The database is populated strictly by running the automated code, never by manual insertion.

**What we rejected:** Pre-populating or mocking extracted facts in the database to save API calls.

**The tradeoff:** Consumes API credits during testing and requires rigorous prompt tuning to achieve reliable extraction.

**Why we accepted it:** Mocking or manually curating the knowledge base creates a brittle system that immediately fails on unseen/foreign documents (Dataset A: Delhivery, or hiring manager test PDFs). True generalization requires that the code itself discovers, extracts, and resolves facts without human intervention. The golden set exists solely as an automated test suite (an answer key) to grade the pipeline code, not as a replacement for it.

---

## 40. Negative Token Filters & Concept Cluster Guards for Financial Attribute Matching

**What we decided:** In `ComparisonEngine._attributes_match`, guard attribute comparison using explicit negative token filters (`debt`, `deficit`, `trade balance`, `current account`, `tax`, `food`) to block cross-metric comparisons where one metric is a denominator or component of another (e.g., "Real GDP Growth" vs "Central Govt Debt (% of GDP)"). Require exact concept cluster matches for core macroeconomic indicators, and require high vector similarity (>= 0.88) for semantic variants.

**What we rejected:** Relying on unconstrained vector embedding similarity alone across all attributes.

**The tradeoff:** Explicit negative keywords and concept clusters require domain-specific definitions in the comparison engine. If a novel macroeconomic ratio appears outside the defined clusters, it falls back to the high threshold (0.88).

**Why we accepted it:** Embeddings treat terms like "GDP Growth" and "Debt-to-GDP" or "Trade Balance as % of GDP" as highly similar (~0.76-0.82) because they share heavy domain context tokens. Pure embedding matching causes the engine to compare a 6.5% growth rate against a 56.8% debt ratio, creating spurious contradictions. Negative token guards eliminate these denominator false-positives deterministically with zero latency.

---

## 41. Single-Batch Vector Embedding Precomputation with In-Memory Caching

**What we decided:** Collect all unique entity and attribute strings across all active facts and pre-compute their normalized embeddings via `sentence-transformers` (`all-MiniLM-L6-v2`) in a single batched tensor operation before entering pairwise comparison loops. Cache vectors in memory (`self.emb_cache`) for fast dot-product cosine similarity.

**What we rejected:** Calling `resolver.compute_similarity(s1, s2)` on-demand inside the nested O(N^2) candidate comparison loops.

**The tradeoff:** Allocates upfront memory for the embedding tensor of all unique vocabulary terms during the comparison lifecycle.

**Why we accepted it:** With 230 active facts, pairwise comparison evaluates thousands of entity and attribute pairs. On-demand inference in Python/PyTorch took 45+ seconds and caused high CPU utilization. Vectorizing all unique strings upfront in a single batch takes < 0.4 seconds, reducing the total comparison engine execution time from 45 seconds to ~2.2 seconds with zero loss of mathematical precision.

---

---

## 42. Strict Verbatim Grounding Invariant in Fact Extractor

**What we decided:** Enforce a strict, non-negotiable grounding precondition in `src/extractor/extractor.py`. A fact candidate is completely discarded (`return None`) if its normalized source quote does not appear verbatim in the source chunk text or fail to meet an 80% token overlap floor, regardless of how cleanly its numeric value or period string was parsed.

**What we rejected:** Allowing additive heuristic scoring where float validity (+0.3) and period validity (+0.2) alone could push an ungrounded fact above the 0.50 acceptance threshold.

**The tradeoff:** Discards approximately 3-5% of borderline LLM extraction outputs where the LLM paraphrased the source text instead of quoting verbatim.

**Why we accepted it:** Grounding is the fundamental trust anchor of a Fact Knowledge Layer. An ungrounded fact—even if numerically correct—is indistinguishable from a hallucination. Discarding ungrounded candidate facts at the ingestion gate guarantees that every fact in `fulcrum.db` can be audited against its source PDF page with verbatim textual evidence.

---

## 43. Multi-Dimensional Unit Normalization and Scale Multipliers

**What we decided:** Categorize all extracted units into distinct physical/financial dimensions (`PERCENTAGE`, `CURRENCY_INR`, `CURRENCY_USD`, `WEIGHT`, `POWER`) and attach scale multipliers (`1 Crore = 100 Lakh = 1e7`, `1 BPS = 0.01%`). Reject comparisons between incompatible dimensions, and normalize values to standard scale before evaluating numerical tolerances.

**What we rejected:** Comparing raw numeric values across arbitrary units, or treating intra-currency denominations (Lakhs vs Crores) as contradictions.

**The tradeoff:** Requires maintaining an explicit dimensional mapping dictionary in `UnitNormalizer`.

**Why we accepted it:** In financial documents, numbers without dimensional bounds produce absurd corroborations (e.g., USD 5.0 Billion falsely corroborating INR 5.0 Crore). Furthermore, Indian macro reports routinely switch between Lakhs and Crores; recognizing scale equivalence (`100 Lakh == 1 Crore`) eliminates false contradictions.

---

## 44. SQLite WAL Mode, Busy Timeout, and Relational Deduplication

**What we decided:** Configure SQLite with Write-Ahead Logging (`PRAGMA journal_mode = WAL;`) and a 5000ms busy timeout (`PRAGMA busy_timeout = 5000;`). Enforce unordered bidirectional pair uniqueness (`UNIQUE(fact_a_id, fact_b_id)`) on relations.

**What we rejected:** Default SQLite rollback journal with immediate lock errors under concurrent FastAPI requests; allowing inverted relation pairs `(A, B)` and `(B, A)` to duplicate in the relations table.

**The tradeoff:** WAL mode maintains `-wal` and `-shm` shared memory companion files alongside `fulcrum.db`.

**Why we accepted it:** When multiple users or threads trigger concurrent uploads and queries, standard SQLite locks immediately. WAL mode allows concurrent readers to proceed unblocked while a writer commits. Bidirectional deduplication eliminated 40 redundant inverted relation rows, keeping relationship counts clean and consistent.

---

## 45. Complete Three-Document Triangulation (Full Economic Survey Ingestion)

**What we decided:** Ingest 46 high-confidence, grounded facts from the native textual sections of `01-india-economic-survey-2024-25-excerpt.pdf` into `fulcrum.db`, completing genuine three-document triangulation across RBI, IMF, and the Economic Survey.

**What we rejected:** Leaving the third starter document empty in the database while claiming multi-document coverage in documentation.

**The tradeoff:** Expanded the active fact pool from 229 to 275 facts and total relations to 159.

**Why we accepted it:** The assignment explicitly provides three starter documents. Having zero facts for the Economic Survey left Case 3 (reconciliation across revision vintages) purely theoretical. Ingesting the Economic Survey's 6.4% First Advance Estimate (p.14) empirically pairs with RBI's 6.5% Second Advance Estimate (p.8, 91), generating 5 real `reconciled` relations directly in SQLite.

---

## Summary Table

| # | Decision | Alternative Rejected | Core Reason Accepted |
|---|----------|---------------------|----------------------|
| 1 | Dataset B only for dev | Both datasets | Preserve generalization test integrity |
| 2 | Single cloud LLM | Mixed models or local | Accuracy plus debuggability |
| 3 | pdfplumber | PyMuPDF, Camelot, cloud OCR | Already installed, handles prose and tables |
| 4 | Structural chunking | Fixed token windows | Fixed windows break tables |
| 5 | Conservative table merge two conditions | Column count alone | Silent false merge corrupts data |
| 6 | Two validation checks on pdfplumber | Trust output blindly | Silent bad-structure is the dangerous failure |
| 7 | FastAPI plus Jinja | React | Demo-day reliability |
| 8 | SQLite | PostgreSQL or Neo4j | Zero setup, sufficient scale |
| 9 | Free-text entity and attribute | Controlled ontology | Must generalize to unknown document types |
| 10 | period.raw_text verbatim | LLM normalizes silently | Auditability; LLMs mis-normalize edge cases |
| 11 | Rule-based confidence | LLM self-reported | LLM confidence is miscalibrated |
| 12 | Confidence threshold 0.5 | No threshold or high threshold | Grounding is the minimum bar |
| 13 | extraction_run_id per-document | Per-pipeline-run | Re-running one doc should not invalidate others |
| 14 | is_active flag keep history | Delete old facts | Debugging requires history |
| 15 | chunk_id encodes page | Separate source_page column | No sync risk; page always derivable |
| 16 | Numeric tolerance 0.1pp and 1 percent | Strict equality | RBI and IMF round the same number differently |
| 17 | assertion_type blocks comparison | Compare all values | Projection not equal to stated |
| 18 | Embeddings plus 3 confidence bands | String match or binary | Uncertainty must propagate not be hidden |
| 19 | 3-sentence keyword vote for authorities | Always GoI or LLM per instance | Cheap, logged, fails safe on AMBIGUOUS |
| 20 | Retrieve then classify YES PARTIAL NO | LLM generates explanation | Prevents hallucinated reconciliations |
| 21 | Multi-fact ±2-page neighborhood retrieval | Larger window or embedding search | Neighboring page context captures footnotes and notes |
| 22 | Flat classifier | Full argumentation graph | Working MVP better than partial impressive graph |
| 23 | Retry plus write per chunk | No retry or end-of-run write | 500+ API calls will fail; must resume not restart |
| 24 | Golden set including assertion_type | One-time eyeball pass | Repeatable; catches silent assertion_type errors |
| 25 | Alias eval before coding | Tune on full pipeline | Isolates entity resolution failure domain |
| 26 | Sequential build order | Parallel | Downstream bugs trace to wrong layer |
| 27 | Manual figure read as step 0 | Discover during extraction | 30 min now versus a day of rework later |
| 28 | Economic Survey Ingestion & Chart Holdout | Full holdout or forced vision OCR | Text enables Case 3; charts demo Case 4 failure |
| 29 | Delhivery sealed | Use as dev dataset | Preserves generalization test credibility |
| 30 | Tiering with hard cut line | Build toward Tier 2 throughout | Working Tier 1 better than broken Tier 2 |
| 31 | Prediction committed before test | Write prediction after | Git timestamp equals evidence not narrative |
| 32 | Cloud API plus pre-cached results | Local model or require evaluator key | Quality plus brief explicitly allows pre-cached |
| 33 | No graph visualization | Force-directed graph | Brief explicitly deprioritizes visualization |
| 34 | Fiscal year lookup table | General date parser | Parsers do not understand Indian fiscal conventions |
| 35 | Fixed unit table | General unit library | Small known vocabulary; failure is explicit |
| 36 | GPT-4o-mini via OpenRouter | Frontier models or local models | Budget: full run costs ~$0.32 not ~$0.25 |
| 37 | Verified anchor metrics for 4 cases | Speculative/unverified metrics | Guarantees all 4 required cases exist in data |
| 38 | Hybrid assistant curation & pre-cache | Naive automated re-runs | Saves 75-85% of API budget; instant demo load |
| 39 | Autonomous code execution (no mock facts) | Pre-populating facts manually | Guarantees pipeline works on foreign holdout PDFs |
| 40 | Negative token & cluster guards | Pure embedding similarity | Blocks denominator false-positives (Debt/GDP vs GDP growth) |
| 41 | Batch embedding precomputation | On-demand pair-by-pair encoding | Cuts engine runtime from 45s to 2.2s via single tensor batch |
| 42 | Strict Verbatim Grounding Invariant | Additive heuristic tolerance | Zero ungrounded hallucinations in knowledge layer |
| 43 | Multi-Dimensional Unit Normalization | Dimension-blind numeric matching | Prevents cross-currency errors; applies 100 Lakh = 1 Cr |
| 44 | SQLite WAL Mode & Deduplication | Rollback journal & duplicate pairs | High concurrency without database locks; clean relations |
| 45 | Complete Three-Document Triangulation | Partial starter dataset ingestion | Empirically grounds all 3 documents & Case 3 in DB |

