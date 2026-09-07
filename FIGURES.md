# Macroeconomic Ground Truth & Cross-Check Matrix (Step 0)

> **Purpose:** Hand-verified anchor figures across the 3 starter PDFs in `starter-datasets/india-macroeconomy/`.
> This establishes ground truth *before* running full LLM extraction, guaranteeing that our four required cases are anchored in real document facts.

---

## 1. Summary Comparison Matrix

| Metric | Period | RBI Annual Report (2024-25) | IMF Article IV (2025) | Economic Survey (2024-25) | Verdict / System Case |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Real GDP Growth** | FY2024-25 | **6.5%**<br>*(p. 91, App Table 1)* | **6.5%**<br>*(p. 10, para 4)* | **6.4%**<br>*(p. 14, para 1.22)* | **Case 1 (Corroboration)** between RBI & IMF.<br>**Case 3 (Reconciled)** vs Econ Survey (1st vs 2nd Advance Estimates). |
| **CPI Headline Inflation (avg)** | FY2024-25 | **4.6%**<br>*(p. 91, App Table 1)* | **4.6%**<br>*(p. 10, para 5)* | N/A (reports Apr-Dec 4.9%) | **Case 1 (Corroboration)** between RBI & IMF. |
| **Current Account Deficit (CAD)** | FY2023-24 | **0.7% of GDP**<br>*(p. 92, App Table 1)* | **0.7% of GDP**<br>*(p. 12, para 10)* | N/A | **Case 1 (Corroboration)** between RBI & IMF. |
| **Current Account Deficit (CAD)** | FY2024-25 | **1.3% of GDP**<br>*(p. 92, App Table 1)* | **0.6% of GDP**<br>*(p. 12, para 10)* | 1.2% in Q2<br>*(p. 62, para 3.44)* | **Case 2 (Contradiction)**: RBI states 1.3% while IMF states 0.6%. |
| **Central Govt Fiscal Deficit** | FY2024-25 | **4.7% of GDP (RE)**<br>*(p. 70, 91)* | **4.9% of GDP**<br>*(p. 10, para 7)* | N/A | **Case 3 (Reconciled by Definition)**: IMF explicitly notes: *"4.9 percent of GDP (4.8 percent of GDP per the authorities' definition)"*. |
| **Central Govt Fiscal Deficit Target** | FY2025-26 | **4.4% of GDP (BE)**<br>*(p. 70, 71)* | **4.4% of GDP** (4.5% IMF def)<br>*(p. 15, 19)* | N/A | **Case 1 (Corroboration)** + **Case 3 (Definition adjustment)**. |

---

## 2. Verbatim Ground Truth Citations

### A. Real GDP Growth (FY2024-25)
- **RBI Annual Report (Page 91, Appendix Table 1)**:
  > `"I.1 Real GDP at Market Prices (% change)* ... 6.5"` (for 2024-25)  
  > Footnote 3 (Page 8): `"All references to GDP data in this Report are based on the Second Advance Estimates (SAE) of National Income 2024-25 released by the NSO..."`
- **IMF Article IV (Page 10, Paragraph 4)**:
  > `"India's real GDP grew by 6.5 percent in FY2024/25. Private consumption growth was buoyant at 7.2 percent on increasing rural demand..."`
- **Economic Survey (Page 14, Paragraph 1.22)**:
  > `"As per the first advance estimates released by the National Statistical Office, Ministry of Statistics & Programme Implementation (MoSPI), the real gross domestic product (GDP) growth for FY25 is estimated to be 6.4 per cent."`

### B. CPI Headline Inflation (FY2024-25)
- **RBI Annual Report (Page 91, Appendix Table 1)**:
  > `"II.1 Consumer Price Index (CPI) Combined (average % change) ... 4.6"`
- **IMF Article IV (Page 10, Paragraph 5)**:
  > `"Headline inflation has declined to 1.5 percent in September 2025, down from 4.6 percent (FY2024/25 average), reflecting lower domestic food prices from good harvests."`

### C. Current Account Deficit (CAD)
- **RBI Annual Report (Page 92, Appendix Table 1)**:
  > `"e) Current Account Balance/GDP (%) ... -0.7 (2023-24) ... -1.3 (2024-25)"`
- **IMF Article IV (Page 12, Paragraph 10)**:
  > `"The current account deficit (CAD) declined to 0.6 percent of GDP, from 0.7 percent of GDP in FY2023/24, as robust import demand was offset by strong services exports and remittances."`

### D. Central Government Fiscal Deficit
- **RBI Annual Report (Page 70 / Page 91)**:
  > `"X. Gross Fiscal Deficit ... 4.7 [2024-25 RE] ... 4.4 [2025-26 BE]"`
- **IMF Article IV (Page 10, Paragraph 7)**:
  > `"Building on the central government's recent track record in meeting fiscal targets, its deficit declined further to 4.9 percent of GDP (4.8 percent of GDP per the authorities' definition)."`
- **IMF Article IV (Page 15, Paragraph 20)**:
  > `"4.4 percent of GDP (4.5 percent of GDP, IMF definition) remains within reach."`

---

## 3. The Four Required Assignment Cases Mapped to Ground Truth

1. **Corroboration (Case 1)**:
   - Real GDP Growth FY2024-25 = **6.5%** stated in both RBI (App Table 1) and IMF (p. 10).
   - CPI Headline Inflation FY2024-25 average = **4.6%** stated in both RBI (App Table 1) and IMF (p. 10).
   - FY2023-24 CAD = **0.7% of GDP** in both RBI (App Table 1) and IMF (p. 12).

2. **Contradiction (Case 2)**:
   - FY2024-25 CAD: RBI reports **1.3% of GDP** deficit, whereas IMF staff report estimates it declined to **0.6% of GDP**. Both cover the identical metric and fiscal year.

3. **Reconciled via Context / Methodology / Vintage (Case 3)**:
   - **Vintage reconciliation**: Real GDP growth for FY25 is 6.4% in Economic Survey vs 6.5% in RBI/IMF. The text itself explains this: Economic Survey used **First Advance Estimates**, while RBI used **Second Advance Estimates (SAE)**.
   - **Scope / Definition reconciliation**: Fiscal deficit FY25 is 4.7% in RBI vs 4.9% in IMF. IMF p. 10 explicitly notes the definition gap (*"4.8 percent of GDP per the authorities' definition"* vs 4.9% IMF definition).

4. **Failure Case (Case 4)**:
   - Economic Survey Page 20 (Chart I.29) and Page 29 (Chart I.46): Data for quarterly GDP growth and CPI item-level breakdown are embedded purely inside raster/vector chart figures without text tables, so a text-based parser fails to capture the underlying numbers.
