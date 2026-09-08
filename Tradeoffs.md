# Core Engineering Traps & Trade-Offs

This document captures the real-world pitfalls, diagnostic lessons, and design trade-offs encountered while building the Fulcrum Fact Knowledge & Verification Layer. These insights serve as primary narrative material for presentation and technical defense.

---

### 1. The "Right Answer for the Wrong Reason" Problem (The CAD Math Trap)
* **What happened:** In the RBI report, it states Current Account Balance is **-1.3%** (a negative balance = deficit). The IMF report states Current Account Deficit is **0.6%** (a positive deficit).
* **The bug:** The comparison logic didn't understand the semantic inversion between "Balance" and "Deficit". It compared `-1.3` directly against `0.6`, noticed numeric divergence, and flagged a contradiction.
* **Why the reviewer rejected it:** If the RBI report had reported `-0.6%` (meaning both sources agreed on a 0.6% deficit), the system would have still flagged a false "Contradiction!" because `-0.6 != 0.6`. The system reached the intended classification by coincidence rather than true semantic polarity modeling.
* **The fix:** Explicitly normalize metrics to canonical representation families (e.g., `current-account net balance = -1 * deficit`) before performing numeric comparison.

---

### 2. The Broken Table Trap (Pages 91 & 92)
* **What happened:** In dense macro reports, multi-page appendix tables often have complex merged cells. On pages 91 and 92 of the RBI document, column alignment collapsed into an unaligned sequence of tokens:
  `"1.8 7.8 -7.9 6.6 -1.3 0.8 13.8 717.9..."`
* **The shortcut taken:** Rather than deterministically rejecting the collapsed table structure, the pipeline passed the raw text to the LLM. The model guessed header-value alignments, hallucinating an impossible value: **Gross Fiscal Deficit = 77.9%**. Furthermore, evidence cards on the dashboard displayed unreadable number strings instead of clean source citations.
* **The logical conflict:** The pipeline attempted to present page 92 as an evidence source for a flagship contradiction (Case 2), while simultaneously citing the table collapse on pages 91–92 as an extraction failure handling example (Case 4). A quarantined document region cannot reliably substantiate an active fact.
* **The fix:** Strictly validate table grid alignment. If row/column geometry cannot be proven, immediately quarantine the chunk into `extraction_failures` (Case 4), and source Case 2 from verified prose.

---

### 3. The "Dirty Database" & Duplicate Memory Bug
* **What happened:** Developer and evaluation scripts ingested test slices (`tier0_test_*`) directly into SQLite without triggering the deactivation routines executed during standard upload flows.
* **The result:** Multiple extraction runs remained concurrently marked as active (`is_active = 1`). The dashboard surfaced identical relation pairs with duplicate IDs, artificially inflating fact and relation tallies.
* **The fix:** Enforce deterministic document hashing (SHA-256) and database idempotency: re-uploading an identical PDF is a no-op; forced re-ingestion transactionally deactivates prior runs.

---

### 4. Over-treating Symptoms Instead of Fixing the Engine
* **What happened:** When early reviewers pointed out missing comparisons (e.g., actuals vs. projections or differing units), fixes were applied as localized heuristic relaxations—such as softening assertion guards or searching for generic variance terms like `"revision"`.
* **The consequence:** Patching symptoms created secondary failure modes. For instance, a sentence discussing agricultural revisions in one sector would trigger a false reconciliation for an unrelated deficit contradiction.
* **The fix:** Eliminate loose keyword-matching fallbacks. Require explicit, paired metadata (e.g., both facts citing verified vintage or scope indicators) before marking an apparent contradiction as reconciled; otherwise, preserve the item as requiring human review.
