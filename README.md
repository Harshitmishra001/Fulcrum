# Fulcrum — Fact Knowledge & Verification Layer

> **Hiring Assignment Submission**: Engineering Intern Hiring Assignment  
> Built by: Harshit Mishra

Fulcrum is a trustworthy, transparent fact knowledge layer that discovers, grounds, compares, and reconciles economic and financial claims scattered across messy documents.

Instead of treating documents as monolithic text blobs or relying on ungrounded generative summaries, Fulcrum:
1. **Chunks structurally**: Separates tabular data from prose, preserves table header context on every body row, and catches silent table parse failures.
2. **Extracts with verbatim evidence**: Extracts facts into a schema-free representation where every number or claim is tethered to a verbatim source quote, page number, and provenance.
3. **Guards comparisons**: Prevents false matches by checking assertion types (*stated outcomes vs projections/targets*) and period types (*fiscal vs calendar years*).
4. **Reasons transparently**: Identifies corroborations, contradictions, and reconciliations via context, presenting evidence in interactive **Argument Cards**.

---

## 📊 The Four Required Cases (Verified Against Ground Truth)

Every case in Fulcrum is grounded in verified document text, recorded in [`FIGURES.md`](FIGURES.md):

| Case Type | Source Documents | Metric & Period | Findings & System Reasoning |
| :--- | :--- | :--- | :--- |
| **1. Corroboration** | **RBI** (App Table 1, p. 91)<br>**IMF** (para 4, p. 10) | **Real GDP Growth** (FY2024-25) | Both independently state **6.5%**. System links claims, matches within 0.1pp tolerance, and marks verified agreement with verbatim quotes. |
| **1. Corroboration** | **RBI** (App Table 1, p. 91)<br>**IMF** (para 5, p. 10) | **Headline CPI Inflation** (FY2024-25) | Both independently report **4.6%** average inflation for the fiscal year. |
| **2. Contradiction** | **RBI** (App Table 1, p. 92)<br>**IMF** (para 10, p. 12) | **Current Account Deficit** (FY2024-25) | **RBI reports 1.3% of GDP** deficit, while **IMF staff reports 0.6% of GDP**. System flags genuine empirical divergence between central bank data and IMF staff projections. |
| **3. Reconciliation via Context** | **Economic Survey** (p. 14)<br>**RBI Report** (p. 8, 91) | **Real GDP Growth** (FY2024-25) | Economic Survey reports **6.4%** as per *First Advance Estimates*; RBI reports **6.5%** as per *Second Advance Estimates*. The document text itself reconciles the revision vintage. |
| **3. Reconciliation via Definition** | **RBI Report** (p. 70, 91)<br>**IMF Article IV** (p. 10, 15) | **Central Govt Fiscal Deficit** (FY2024-25) | RBI reports **4.7% (RE)**; IMF reports **4.9%**, explicitly explaining: *(4.8 percent of GDP per the authorities' definition)*. Discrepancy is reconciled by definition accounting. |
| **4. Failure Case** | **Economic Survey** (p. 20, 29) | **Quarterly Growth & Itemized CPI** | Economic Survey embeds quarterly numbers inside **vector chart images** (Charts I.29, I.46) without underlying text tables. System transparently exposes why text-based PDF parsers drop visual chart data. |

---

## 🚀 Quickstart (Inspect Pre-Cached Results)

The repository includes a pre-populated SQLite database ([`fulcrum.db`](fulcrum.db)) containing 220+ active facts and 100+ relations extracted from the starter macro datasets. **You do not need an API key to run or evaluate the UI.**

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Launch Dashboard
```bash
python -m src.app
```
Open your browser at **[http://127.0.0.1:8000](http://127.0.0.1:8000)**.

You will see:
- **Metrics Bar**: Live counts of active facts, corroborations, contradictions, and claim discrepancies.
- **Interactive Filter Tabs**: Filter by Corroboration, Contradiction, or Stated vs Projection.
- **Argument Cards**: Side-by-side claim comparisons with exact page numbers, verbatim source quotes, and reasoning.
- **Upload Form**: Upload any new PDF (e.g. corporate earnings reports) to process and cross-reference live.

---

## 🔑 Running Extraction on New PDFs (Optional)

To run live extraction on newly uploaded PDFs or re-run the extraction pipeline:
1. Create a `.env` file in the root directory:
```env
OPENROUTER_API_KEY=your_openrouter_api_key_here
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=openai/gpt-4o-mini
```
2. Upload any PDF through the web UI at `http://127.0.0.1:8000` or use the API:
```bash
curl -X POST "http://127.0.0.1:8000/api/upload" -F "file=@sample.pdf"
```

---

## 🏛 Architecture & Design Decisions

Every technical decision, rejected alternative, and accepted tradeoff is documented in [`DECISIONS.md`](DECISIONS.md). Key highlights:

- **No Graph DB Overhead (Decision 8)**: Uses SQLite with indexed relational pairing rather than complex graph databases. Flat classifier operating on fact pairs directly answers the core questions without graph traversal latency.
- **Local Embedding Resolution (Decision 18)**: Uses local `sentence-transformers` (`all-MiniLM-L6-v2`) for zero-cost entity similarity with 3 confidence bands (>=0.85 high, 0.65-0.85 uncertain, <0.65 reject).
- **The Authorities Heuristic (Decision 19)**: 3-sentence keyword vote resolving IMF's "the authorities" to RBI (monetary context) or GoI (fiscal context), failing safe to `AMBIGUOUS` (0.40) when uncertain.
- **Retrieve-Then-Classify Reconciliation (Decision 20)**: Retrieves candidate explanatory sentences within 15 chunks deterministically before asking the LLM only to classify (*YES / PARTIAL / NO*). The model is forbidden from hallucinating new explanations.
- **Deterministic Normalization (Decisions 10, 34, 35)**: Fiscal years (`FY2024-25` → `FY2025`) and units (₹ Crore, Lakhs, USD Bn, %) are normalized with deterministic regex and conversion tables, never unmonitored LLM transforms.

---

## 📂 Repository Layout

```
Fulcrum/
├── src/
│   ├── app.py                     # FastAPI application & server
│   ├── config.py                  # Centralized configuration & thresholds
│   ├── comparison/
│   │   ├── engine.py              # Three-way comparison & reconciliation engine
│   │   └── entity_resolver.py     # Local embeddings + 'the authorities' heuristic
│   ├── db/
│   │   └── database.py            # SQLite schema, active run tracking, and queries
│   ├── eval/
│   │   └── golden_eval.py         # Automated grading harness for extraction
│   ├── extractor/
│   │   └── extractor.py           # OpenRouter client with retry & confidence scoring
│   ├── normalizer/
│   │   ├── period_normalizer.py   # Deterministic fiscal year / quarter regex normalizer
│   │   └── unit_normalizer.py     # Unit conversion & tolerance matching logic
│   ├── parser/
│   │   └── pdf_chunker.py         # Structural PDF chunker with table validation
│   └── templates/
│       └── index.html             # Interactive Argument Cards dashboard
├── data/
│   ├── golden_set_rbi.json        # 30 hand-annotated ground truth facts for scoring
│   └── alias_eval_pairs.json      # 15 entity alias evaluation test pairs
├── starter-datasets/              # Starter PDFs (India Macro & Delhivery holdout)
├── DECISIONS.md                   # Complete architectural decision log (39 decisions)
├── FIGURES.md                     # Step 0 verified macroeconomic ground truth matrix
├── requirements.txt               # Dependencies manifest
└── README.md                      # This documentation
```

---

## 🧪 Running Automated Tests

```bash
# Test entity resolver against alias eval set
python scratch/test_entity_resolver.py

# Test golden set evaluation
python -c "from src.eval.golden_eval import GoldenEvaluator; from src.db.database import get_active_facts; GoldenEvaluator().print_report(GoldenEvaluator().evaluate_facts(get_active_facts('rbi')))"
```
