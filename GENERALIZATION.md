# Fulcrum V2 Generalization Test (Delhivery Holdout)

## Overview
Throughout the development of Fulcrum V2, the dataset **Dataset A (Delhivery)** was strictly sealed and quarantined. 

We enforced a **Zero-Mock Invariant** meaning we did not manually inject facts or hand-tune the extraction prompts using Delhivery documents. The prompts were neutralized to remove any hardcoded "RBI" or "IMF" assumptions (see Decision 52).

## Prediction
Because the engine now explicitly blocks `UNKNOWN` metric bucket explosions, relies on canonical metric polarities, and uses robust bounding-box structural extraction (`pdfplumber`):

1. **Extraction:** It should successfully identify corporate metrics like "EBITDA margin", "Revenue", and "Freight Tonnage" from the Delhivery prospectus and Q4 earnings deck.
2. **Reconciliation:** We predict it will identify `corroboration` when the Q4 Deck matches the Annual Report, and it will correctly flag differences between "Standalone" and "Consolidated" figures as `not_comparable_scope` (if properly extracted).
3. **Failures:** Highly graphical logistics charts in the Earnings Deck will likely be quarantined by the `pdfplumber` structural alignment checks, just like the RBI Appendix tables.

## Result
(To be populated after final run)
The E2E test runs completely unsupervised. Any failure modes discovered here represent genuine architectural limits of the current LLM extraction accuracy, rather than hardcoded pipeline biases.
