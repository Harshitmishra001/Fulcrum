# Fulcrum — MVP Build Spec

**Scope decision:** Build and tune entirely on Dataset B (India Macro: Economic Survey, RBI Annual Report, IMF Article IV). Dataset A (Delhivery) is a sealed holdout — do not open it, reference it, or tune anything against it until the generalization test at the end.

**Primary sources for MVP, in this priority order:**
1. RBI Annual Report — numeric ground truth anchor (clean tables, native text)
2. IMF Article IV — prose-heavy, independent verifier
3. Economic Survey — used mainly for the seeded failure case (chart-image gaps), not as a core extraction target

---

## Blocking Decisions (answered now, so nothing stalls)

These were flagged as open by review — deciding them here rather than leaving them ambiguous.

- **LLM**: pick one capable general-purpose model (Claude or GPT-4o class) and use it for *every* LLM step — extraction, entity resolution tiebreaks, reconciliation proposals. Do not mix models across steps in the prototype; it adds a variable you can't debug against when something goes wrong. Model swap is a one-line config change later if needed, not a day-one decision to agonize over.
- **Chunking for mixed tables + prose**: use `pdfplumber`'s table-detection per page. A table chunk = header row(s) + all body rows, re-attached as explicit context in *every* extraction call for that table (not extracted once and assumed inherited) — this is what prevents the "FY22 number labeled as FY24" failure mode raised in review.
  - **Multi-page table merge**: same column count alone is not enough — RBI routinely has back-to-back tables (e.g. a summary table and a detail table) with matching column counts but different metrics. Merge only if column count matches *and* the first row of the continuation page's table pattern-matches the last row of the previous page's table (both look like years, or both look like metric-name labels). If ambiguous, do not merge — treat as a separate table with lower `extraction_confidence`. A false merge silently corrupts data; a false split just loses a few rows of context, which is the safer failure direction.
  - **Detecting pdfplumber's silent bad-structure failures**: `pdfplumber` doesn't always know when it's failed — a mis-split merged cell can produce a structurally valid-looking table full of garbage. Before trusting a parsed table, run two cheap checks: (1) every body row's cell count matches the header row's cell count, (2) columns whose header looks numeric/year-like actually parse as numbers for most rows. Fail either check → treat as unparsed, fall back to raw text, set `extraction_confidence` low. This is two checks, not a validation framework — keep it cheap.
  - For genuinely unparseable tables (merged cells, rotated headers) after the above: fall back to raw text extraction for that page and set `extraction_confidence` low rather than guessing at structure.
- **UI — decided, not "or": FastAPI + server-rendered HTML (Jinja) with a bit of vanilla JS.** No React, no build step, no npm dependency tree. A single page: upload control + a list of argument cards. This is a demo-day reliability decision as much as a scope one — a prototype that needs a working bundler on demo day is a needless risk.
- **GDP/CPI divergence — verify before committing**: the dataset report *implies* RBI/IMF/GoI figures will diverge or match interestingly, but this hasn't been confirmed against actual document content yet. Before locking GDP growth as the flagship corroboration case and picking a contradiction candidate, do a 15-minute manual read of the actual stated figures (GDP growth, CPI, fiscal deficit, CAD) across all three docs. If they're identical everywhere, the contradiction case needs a different metric — find out now, not during the demo recording.
- **Four required cases**: yes, this framing comes directly from the assignment brief. There's no external judge to satisfy other than the hiring panel — which means the discipline of *only* claiming a case when the pipeline actually found it (Build Order step 7) is what makes the submission credible, since nothing else verifies it for you.

**Rough cost/latency budget (order-of-magnitude, not precise):**
- RBI report, chunked by table + paragraph: roughly 300–500 chunks → same number of extraction calls
- IMF report, prose-heavy, chunked by paragraph/section: roughly 150–250 chunks
- Total extraction for Tier 0 + Tier 1 core (RBI + IMF): call it **~500–750 LLM calls**, run once per extraction attempt
- Comparison engine calls are *not* all-pairs — they only fire for facts that already resolved to the same entity+attribute candidate, which after normalization and filtering should be dozens, not hundreds
- **Implication**: at even a few seconds per call, a full extraction run is many minutes, not seconds. Budget for this explicitly — batch calls where the API allows it, and do not plan to casually "just re-run everything" every time you tweak the prompt. This is exactly why the golden set (step 1) and `extraction_run_id` versioning (schema) matter: you want to validate prompt changes against a small fixed sample before burning a full 500+ call run on it.
- For the live demo itself: pre-run and cache results for the three known source documents. Only the "upload a new PDF" moment in the video should show a live run, and it should be a smaller or partial document if a full 100-page live run would eat demo time.
- **LLM call reliability — required, not optional**: 500+ sequential API calls will hit a rate limit or transient timeout before the run finishes. Without handling this, a single failure at call #412 aborts the run and wastes the preceding compute. Minimum required: exponential backoff with 3 retries per call, per-call timeout of 30s. Also required: save extracted facts to SQLite **after each chunk**, not at end of run — so a partial run is resumable by skipping chunks already in the DB for the current `extraction_run_id`. This turns a crash from "lose everything" to "resume from where it stopped." Both of these are under 20 lines of code each; skipping them is not a time saving.


---

## Tier 0 — Foundation (nothing else starts until this works)

Goal: prove extraction is *trustworthy* before building anything on top of it.

- [ ] PDF → text extraction for RBI report only, prose + tables separately
- [ ] Table extraction preserves row/column headers (year, metric name) attached to each cell — do not treat a table as a text blob
- [ ] Chunk by structural unit (paragraph, table, section) — never fixed token windows
- [ ] Run extraction prompt (see below) against ~15–20 chunks
- [ ] **Golden set, not a one-time eyeball pass**: before running extraction, manually pick and annotate ~30 facts from the RBI report yourself (value, unit, period, **assertion_type**, correct source quote) — this is your fixed answer key, written down, reusable every time you change the extraction prompt or chunking logic. Run extraction, then score against it: precision and recall on value/period/unit, **and separately, `assertion_type` accuracy**. This last one matters specifically because `assertion_type` is what the comparison engine uses to block false corroborations — if it's silently wrong, that guard is decorative. A single "17/20 looked right" pass doesn't tell you if a prompt change made things better or worse next time — the golden set does.
- [ ] **Entity alias smoke test**: hand-write 10–15 known alias pairs from the actual documents (e.g. "Government of India" / "GoI" / "the government"; "the Fund" / "IMF"; a couple of "the authorities" instances with their correct resolution from context). Run your embedding similarity + heuristic against these before trusting entity resolution on anything else. This is a 30-minute check, not a research eval — but skipping it means flying blind on the piece review flagged as hardest.
- [ ] Numeric noise filter: strip page numbers, table index/column labels, footnote markers, bare year-as-heading tokens from being treated as facts

**Exit criteria for Tier 0:** precision and recall against the golden set are both comfortably above what you'd trust to build on — there's no magic threshold, but "most facts right, and you know exactly which ones are wrong and why" is the bar. If accuracy is bad, fix extraction and re-score before proceeding — do not build the graph on top of unverified extraction.

---

## Tier 1 — MVP (this is what ships if nothing else gets built)

### Fact schema
```json
{
  "id": "uuid",
  "extraction_run_id": "uuid — every extraction run gets one; lets you tell fresh facts from stale ones after a prompt/chunking fix",
  "is_active": "bool — only the latest run's facts are active; comparison engine only ever reads active facts",
  "entity": "string (free text, not enum)",
  "attribute": "string (free text, not enum)",
  "value": "number or string",
  "unit": "string | null",
  "period": {
    "raw_text": "string, verbatim as written",
    "period_type": "fiscal_year | calendar_year | quarter | unspecified",
    "normalized": "e.g. FY2025 | CY2025 | null if unresolved"
  },
  "assertion_type": "stated | projection | opinion | hedge",
  "source_doc": "string",
  "source_quote": "verbatim span, <300 chars",
  "chunk_id": "string — encoded as '{doc_slug}__p{page:04d}__{type}__{index:04d}', e.g. 'rbi__p0047__table__003'. Page number is always recoverable from chunk_id without a separate column: source_page = int(chunk_id.split('__')[1][1:]). Do not use a bare UUID for chunk_id — the page must be embedded.",
  "extraction_confidence": "0-1, RULE-BASED not LLM self-reported. Scoring: +0.5 if source_quote found verbatim in source chunk, +0.3 if value parses as a clean number, +0.2 if period.raw_text is non-empty. CONFIDENCE_THRESHOLD = 0.5 (tune after golden set eval, but start here) — facts below this are excluded from the comparison engine entirely, not just displayed dimmer. Minimum bar: a fact must at least be grounded (quote found verbatim, +0.5) to enter comparison."
}
```

**Dedup at write time — versioning is per-document, not per-pipeline-run.** You will re-run extraction on a single document (e.g. fixing a chunking bug in RBI) far more often than you re-run the whole pipeline. So: `extraction_run_id` is scoped to a single document's extraction attempt. When RBI is re-extracted, only RBI's previous facts flip to `is_active: false` — IMF's facts, from a different run, are untouched. The comparison engine and UI always query `is_active: true` across whichever documents have been extracted, regardless of which ones were re-run most recently. This is what makes "just fix RBI's prompt and re-run RBI" a cheap, safe operation instead of one that risks silently invalidating unrelated data.

### 1. Extraction (LLM, schema-free)
- One prompt template, run per chunk (prose and table variants, same output schema)
- Model must output the `period.raw_text` exactly as written — no silent normalization at extraction time. Normalization happens in a separate deterministic step (below), so you can always audit what the model actually saw vs. what you inferred.
- Reject/flag any fact where `source_quote` cannot be found verbatim in the source chunk (cheap grounding check at extraction time, not just at comparison time)

### 2. Deterministic normalization layer (no LLM)
- **Fiscal year string normalizer**: regex table mapping `FY2024-25`, `FY2024/25`, `FY25`, `2024-25` → canonical `FY2025`. Small closed vocabulary — build this as a lookup, not a general parser.
- **Period-type check**: flag when two facts about the same metric have different `period_type` (fiscal vs. calendar) even if the raw numbers match. This is the single most important deterministic check — it directly protects your best corroboration case (GDP growth) from a false-positive contradiction or a false-positive corroboration caused by calendar/fiscal mismatch.
- **Unit normalizer**: ₹ Crore / ₹ Lakh / USD billion → one canonical unit for comparison purposes (keep original for display). Small fixed conversion table, not general-purpose.

### 3. Entity resolution
- Embedding similarity for candidate matching (e.g. "Government of India" ≈ "GoI" ≈ "the government")
- Special case, hand-written rule (not general logic): `the authorities` (IMF-speak) resolves to GoI or RBI based on sentence context. **Concrete rule — 3-sentence window, keyword vote:**
  - Look at the 3 sentences immediately before and 3 sentences immediately after the one containing "the authorities" (6-sentence window total, same paragraph preferred).
  - Monetary cues (→ RBI): `repo rate`, `monetary policy`, `inflation target`, `liquidity`, `MPC`, `reserve money`, `policy rate`
  - Fiscal cues (→ GoI): `fiscal deficit`, `budget`, `expenditure`, `revenue`, `subsidy`, `tax`, `GST`, `borrowing`
  - If monetary_hits > fiscal_hits → resolve to RBI, confidence = 0.70 (fixed lower score, it's a heuristic)
  - If fiscal_hits > monetary_hits → resolve to GoI, confidence = 0.70
  - If tied or zero hits on both → AMBIGUOUS, confidence = 0.40. At 0.40 this falls below the 0.65 threshold → no relation is created. Do not guess when the context is genuinely ambiguous.
  - Treat this as a documented heuristic with known failure modes, not a solved problem. Log every "the authorities" resolution with its keyword counts so misfires are visible during the alias eval check.
- **Every resolution carries a confidence score, and it propagates.** A match isn't just "resolved" or "not resolved" — store the similarity score (or, for the "the authorities" heuristic, a fixed lower confidence since it's a guess) on the resolution itself, and carry it onto any relation built from it. Starting thresholds (cosine similarity on embeddings) — tune after the alias eval smoke test, but start here rather than deciding this at 2am before the demo:
  - **High confidence, ≥0.85** → proceed to comparison engine normally
  - **Low confidence, 0.65–0.85** → still compare, but the resulting relation is labeled "possible match, entity resolution uncertain" — visible in the UI, not hidden. This directly answers review's point #2 and #7: a wrong "the authorities" resolution doesn't quietly produce a confident-looking phantom corroboration or contradiction — it produces a visibly-flagged one.
  - **Below threshold, <0.65** → facts are simply never compared; no relation is created. This is a silent miss by design (you can't compare everything against everything), but it's the honest failure mode — better than a wrong merge.
  - Record the alias eval set's actual scores against these three numbers as part of Build Order step 1/6 — if real alias pairs like "the authorities" → RBI cluster below 0.85, move the boundary based on that evidence, not intuition.

### 4. Comparison engine — three-way classification, not full argumentation graph
Given two facts that resolve to the same entity + attribute (see confidence bands above — this applies at any confidence level, with the label carried through):
- If `assertion_type` differs (e.g. one is `stated`, the other `projection`) → do NOT classify as corroboration or contradiction, regardless of whether the values match. Label it **"different claim type"** and show both. A projection matching a later stated figure is a mildly interesting observation, not evidence of agreement — collapsing the two was flagged by review as a likely source of a false corroboration, and it's a real risk given IMF commonly issues projections alongside RBI/GoI's stated figures.
- If `period_type` differs → do NOT compare directly; surface as "not comparable, different period basis" (this itself is a useful, honest output)
- If values match after normalization, same `assertion_type`, same `period_type` → **corroboration**
- If values differ after normalization, same `assertion_type`, same period → **contradiction**
- If values differ but a reconciling fact exists → **reconciled**, subject to the grounding rule below
- Everything else → **unresolved / insufficient context** (this is an honest, valid output — do not force a verdict)

**What "values match" means — numeric tolerance rule (strict equality will break on real data):**
RBI rounds to 1 decimal place; IMF often rounds to 2. The same underlying figure will frequently appear as `6.5%` in one source and `6.47%` in another. Strict equality misclassifies these as contradictions.
- **Percentage / rate values** (unit ends in `%` or `bps`): match if `abs(a - b) <= 0.1`. This catches rounding differences without swallowing genuinely different estimates — 6.4% vs 6.5% is a match; 6.4% vs 7.0% is not.
- **Large absolute values** (unit is ₹ crore, USD billion, etc.): match if `abs(a - b) / max(abs(a), abs(b)) <= 0.01` — i.e., within 1% relative. Handles rounding at different scales.
- **Strings, codes, ratios without a unit** (e.g. a policy rate expressed as a fraction): strict equality only.
- `value_type` is determined from the normalized unit field after the unit normalizer runs — this is a deterministic lookup, not an LLM call.

**Reconciliation grounding rule (this is the branch most likely to embarrass you live if left loose):**
- **"Adjacent" is defined concretely: within 15 chunks by document order, same document, of one of the two original facts.** Not embedding similarity, not "nearby" by feel — a fixed, checkable rule.
- **Known limitation, stated up front rather than discovered mid-build**: RBI/IMF reports often put the actual explanation for a revision (methodology change, provisional-vs-final vintage) in a separate statistical annex, which can be far more than 15 chunks away from the number it explains. A 15-chunk window will legitimately miss these. This is not a bug to quietly patch by widening the window until something matches — that's how you end up grounding a reconciliation in something coincidentally nearby rather than actually related. The correct response, in order:
  1. For MVP: if nothing is found within the window, the relation stays **"unresolved / insufficient context."** That's an honest output, not a failure of the spec.
  2. If you have time: this is exactly what Tier 2's chain-grounding item is for — widen the search to a full-document semantic search *restricted to chunks tagged as methodology/notes/annex sections*, with the same strict grounding requirements (verbatim quote, prose not table-cell).
  3. **This is also a legitimate, honest candidate for required case 4** — if you can show a real instance of "the reconciling explanation exists in the document but our retrieval window didn't find it, here's why, here's what we'd build next," that's a stronger failure case than a manufactured one, because it's a genuine limitation of a specific, defensible design choice.
- It must come from a prose chunk, not a raw table-cell extraction (a bare number/footnote-marker blob isn't an explanation).
- The retrieved sentence is stored and shown verbatim alongside the two facts it reconciles — the user sees exactly what justified "reconciled," not just the label. If you can't produce that sentence, the relation stays "unresolved," full stop — do not let the LLM assert a reconciliation without a quote backing it.
- If grounding is weak (sentence found but only loosely related), label it **"candidate reconciliation — unverified"** rather than a confident "reconciled." A hedged label that's honest is a better demo moment than a confident one that falls apart under a follow-up question.

**Reconciliation LLM call — output contract (retrieve → classify, never generate):**
The reconciliation step has the highest hallucination risk of any LLM call in the pipeline. Lock the contract here to prevent improvising at 2am.
1. **Step 1 — Deterministic retrieval**: fetch up to 3 candidate sentences from within the 15-chunk window, prose chunks only. Rank by BM25 / keyword overlap against both fact values + their units. No LLM involved here.
2. **Step 2 — LLM classification on the top candidate** (not generation):
   > *"Here are two facts reporting different values for the same metric:*
   > *Fact A: [value, period, source_quote]*
   > *Fact B: [value, period, source_quote]*
   > *Candidate explanation: [retrieved sentence]*
   > *Does this sentence explain why these two values differ? Answer only: YES / PARTIAL / NO. Do not generate an explanation. Only classify the one provided."*
3. **Step 3 — Deterministic outcome**:
   - `YES` → `relation_type = "reconciled"`, store retrieved sentence verbatim as `evidence_quote`
   - `PARTIAL` → `relation_type = "candidate reconciliation — unverified"`, store retrieved sentence
   - `NO` or no candidate found → `relation_type = "unresolved / insufficient context"`

If there is no candidate sentence from step 1, skip step 2 entirely — do not ask the LLM to propose a reconciliation from scratch. A grounded "unresolved" is always better than an ungrounded "reconciled."

This is a simplified version of the attack/support/undercut idea — same reasoning shape (three of your four required cases fall out of it directly), without needing the full graph fixpoint solver. That solver is Tier 2, not MVP.


### 5. Storage
- SQLite. Tables: `facts` (see schema above, including `extraction_run_id` / `is_active`), `relations` (fact_a, fact_b, relation_type, explanation, evidence_quotes, entity_resolution_confidence)
- No graph DB.
- Only `is_active: true` facts are ever read by the comparison engine or UI — this is the dedup mechanism, not a separate cleanup step.

### 6. API/UI
- FastAPI backend: upload endpoint, list-facts endpoint, list-relations endpoint
- Server-rendered HTML (Jinja templates) + vanilla JS for the upload interaction — no frontend framework, no build step (locked decision, see Blocking Decisions above)
- UI: one "argument card" per fact — the claim, its source quote (with doc + page), and any related facts with relation type. No force-directed graph visualization.

### Four required cases, mapped to MVP components
1. **Corroboration** — GDP growth ~6.5% FY2024/25, stated independently in RBI + IMF (+ Econ Survey if extractable). Comes from comparison engine step 4, case "values match."
2. **Contradiction** — any metric where RBI and IMF genuinely diverge after normalization, same period basis. Comparison engine, case "values differ, same period."
3. **Reconciled-via-context** — a figure that differs because of provisional vs. revised vintage, or base-year methodology, retrievable as a single grounding sentence. Comparison engine, "reconciled" branch.
4. **Failure case** — pick whichever actually happens: chart-embedded numbers in Economic Survey (near-certain), or a misfire in the "the authorities" heuristic (possible, more interesting if it happens). Do not force a fake one — use what's real.

---

## Tier 2 — Stretch (only after Tier 1 fully works and is demoed once, end to end)

In priority order — stop anywhere on this list if time runs out:

1. **Chain-grounding for reconciliation** (multi-hop, capped at 2 hops, each link must be a directly retrieved sentence, not a paraphrase) — upgrades case 3 from "lucky single-sentence match" to genuinely handling vintage/methodology reconciliations that need two facts combined
2. **Full attack/support/undercut graph with grounded-extension fixpoint** — upgrades the comparison engine from a flat classifier to the argumentation-theory version discussed earlier. Only worth doing if Tier 1's simplified version is solid and you have time to spare — this is the "stands out" layer, not the "works" layer.
3. **Incremental recompute** — bounded-depth (2-hop) recomputation of the fixpoint when a new document is added, instead of full rebuild. Explicitly document the bound; do not claim it's "free."
4. **Chart-vision pass** on Economic Survey images — only attempt if case 4 hasn't already been satisfied by something else; otherwise this is redundant effort
5. **Undecided-cycle explanation UI** — if the graph (from #2) ever produces an odd-cycle "undecided" result, render *why*, so it reads as principled rather than broken

---

## The Cut Line

**If you are running out of time, stop at Tier 1.** A working flat classifier over RBI + IMF that correctly produces all four required cases, with honest "unresolved" outputs where appropriate, is a complete, demoable, defensible submission. It directly satisfies the brief's own stated preference: *"a smaller, understandable prototype is better than a large system whose behavior is unclear."*

Do not start Tier 2 item 2 (the full graph) unless Tier 1 is fully working, spot-checked, and demoed once successfully end to end. Partial graph-theory code that doesn't run is worse than a flat classifier that does.

**Explicitly out of scope for this submission, regardless of time remaining:**
- General-purpose date parsing (only the closed fiscal-year vocabulary above)
- Economic Survey as a primary extraction target (holdout for case 4 only)
- Any Delhivery-specific tuning

---

## Generalization Test (do this once, near the end, on camera or pre-recorded)

**Write the prediction down before running anything, in a file, committed to the repo — not a mental note.** Create `GENERALIZATION.md` and write your prediction there before opening Dataset A: "We expect the Annual Report's multi-column layout to interleave text during extraction, because we haven't built column-aware parsing." (Or whatever your actual best guess is, given what you know your pipeline does and doesn't handle.) Commit this file *before* running the test — the git history timestamp is your proof the prediction came first, not after. Then append the actual result underneath it. Reference `GENERALIZATION.md` from the README's Approach or Limitations section. This turns the test into evidence you can defend — "we predicted this specific failure mode and here it is, committed before we ran it" — instead of a demo stunt that just happened to work or not work, and it's the difference between a claim and a claim with a receipt.

Then run the finished Tier 1 (or Tier 2, if reached) pipeline against Dataset A cold — no prior debugging against it. Expected outcomes, stated honestly either way:
- If the multi-column Annual Report garbles on extraction as predicted — that's your evidence for "what doesn't work yet," directly answering the README's Limitations section, and a legitimate demonstration you didn't hardcode anything.
- If it works cleanly — even better, show the AR FY24 ↔ Earnings Deck corroboration pair as a bonus case, and note that your prediction was wrong (also useful — it means your extraction is more robust than you assumed).

**Recommendation:** run this once ahead of the real recording to know which outcome you'll get, then narrate it honestly in the demo video either way. Don't gamble the only take on an unrehearsed live failure.

---

## Build Order (sequential, not parallel)

1. **(30 min, no code) — Manual figure cross-check first, before anything else.** Open all three PDFs and record these four figures from each source in a markdown table: GDP growth rate (FY2025), CPI inflation, fiscal deficit (% of GDP), CAD (% of GDP). Commit this table as `FIGURES.md`. This is step 0, not step 3, because: (a) it tells you which metrics actually diverge before you annotate the golden set, so you annotate the right facts; (b) if no contradiction exists across all four metrics, you need to find one now, not mid-build. 15 minutes of reading now saves a day of structural rework later.
2. Build the golden set (30 hand-annotated RBI facts) and the entity alias eval set (10–15 pairs) — informed by step 1's findings, before writing extraction code
3. Tier 0 (RBI only) → score against golden set → do not proceed until trustworthy
4. Extend extraction to IMF (prose-heavy — different chunking needs than RBI's tables)
5. Deterministic normalization layer (fiscal year, unit, period-type check)
6. Entity resolution incl. "the authorities" heuristic → check against alias eval set, adjust the 0.85/0.65 thresholds if the real scores warrant it
7. Comparison engine (flat classifier version, incl. assertion_type, numeric tolerance, and grounding rules above)
8. Storage + minimal API/UI
9. Find and confirm your actual instances of cases 1–4 from real output (don't pre-script them)
10. Write README, record demo
11. If time remains: Tier 2, in listed priority order
12. Generalization test against Dataset A, once, prediction written first, honestly reported
