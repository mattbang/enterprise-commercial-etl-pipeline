# Enterprise Data Pipeline & Analytics Automation: Executive Case Study
**Domain:** Medical Technology / Cardiac Rhythm Management
**Role:** Lead Analytics Engineer / BI Developer
**Status:** Sanitized Production Case Study | Public Demo Verified

> *Confidentiality Notice: Organization identity, internal portal URLs, proprietary product identifiers, and commercial volumes have been anonymized or normalized for portfolio presentation while preserving the relevant technical architecture and business logic. Operational impact figures below describe the production case study; they are not generated or independently verified by the public demo.*

---

## 📌 Executive Summary

To serve regional finance across **9 countries**, commercial leadership required frequently refreshed Qlik Sense dashboards reconciling SAP sales actuals, MedTech Europe market data where available, separate diagnostics/ICM market inputs, Salesforce-entered forecast updates, and forward-looking sales and market-share forecasts maintained through an internal market-forecasting process I led during my tenure.

Previously, this process was performed manually: downloading raw sales, market, and forecast extracts, cleaning and standardizing varying European number formats in Excel, merging records, and hand-validating figures before Qlik Sense consumption. This manual workflow consumed **6 to 8 hours per cycle**, was vulnerable to human error, slowed the turnaround from forecast changes to updated management visuals, and created a critical single-person operational dependency.

This project engineered an automated Python ETL and orchestration pipeline covering ingestion, transformation, multi-scenario financial modeling, Qlik Sense reloading, and validation. The production case study records execution in **under 4 minutes**, helping management review updated goals, market-share movement, and performance benchmarks closer to the forecast update cycle. The public repository demonstrates the transformation rules and blocking publication controls with synthetic data; private connectors and production services are intentionally excluded.

The orchestrator's purpose was to make the full refresh repeatable and inspectable, from changing source inputs to refreshed visuals and quality follow-up. The reported runtime and manual baseline are historical operational estimates, not a controlled benchmark. Human review, investigation, and interpretation remain part of the reporting process.

## Source Decisions Behind the Result

| Challenge | Design decision | Reporting consequence |
| :--- | :--- | :--- |
| Annual ICM market estimates and quarterly company figures | Allocate market estimates but retain the separate native-quarterly company actuals | Make market-share calculations comparable without inventing quarterly sales detail |
| Gaps in standard market-reference coverage | Integrate separate diagnostics/ICM and supplementary market inputs | Include product categories that a single market source cannot describe |
| Different product labels and territorial ownership | Apply explicit mappings, regional groupings, and export treatment | Align the dataset with commercial responsibility and check for omissions |
| Changing forecasts and earlier planning targets | Preserve version labels and keep adjustments separate from source workbooks | Support variance analysis between actuals, live forecasts, and saved baselines |
| Full and addressable market definitions | Construct three market views and test conservation | Make the opportunity definition visible when interpreting market share |

Annual-to-quarter forecast allocation produces modeled values. Market views describe scope; forecast versions describe planning positions. Keeping those concepts distinct is central to making the integrated report interpretable.

---

## 📊 Key Impact & ROI Metrics

| Metric | Before (Manual Process) | After (Automated Pipeline) | Impact |
| :--- | :--- | :--- | :--- |
| **Forecast-to-Visual Turnaround** | Roughly 6-8 hours / update cycle, as reported in the case study | **Under 4 minutes reported in production** | Faster management visibility into revised goals, market share, and performance benchmarks |
| **Data Ingestion & Merge** | Manual download & Excel copy-paste | Headless Selenium + Vectorized Pandas | Fully automated multi-source ingestion |
| **Data Quality Verification** | Ad-hoc manual spot-checks | **17 checks across five quality tiers** | Blocking pre-publication failures preserve the last valid dataset; downstream mismatches fail the run |
| **Edge Case & Regression Coverage**| Zero formal test coverage | **Self-contained public unit, stress, and demo suite** | Handles European numbers, blanks, nulls, schema failures, and publication controls |
| **Field Anomaly Reporting** | Manual email drafting per country | Automated HTML discrepancy alerts | Instant controller review drafts |
| **Knowledge Transfer** | Undocumented specialist knowledge | Operations & Troubleshooting Manual | Repeatable handover and mapping-maintenance process |

---

## 🏗️ System Architecture & Data Flow

```
   ┌────────────────────────────────────────────────────────────────────────┐
   │                       MULTI-SOURCE INGESTION                           │
   │  SAP Sales Actuals     MedTech Europe Market   Diagnostics/ICM Source  │
   │  (Historical Sales)    (Market Where Avail.)   (Separate Market Input) │
   │  Salesforce Updates    Internal Forecasting                            │
   │  (Manual Edits)        (Sales & Market-Share Plans)                    │
   └───────────────────┬────────────────────────────────────────────────────┘
                       │ Automated Headless Browser Ingestion (Selenium + Auth)
                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │                  CORE ETL & FINANCIAL DISAGGREGATION                   │
   │  • Unified country and territory remapping for 9-country finance views  │
   │  • Robust numeric parsing (EU decimals `1.234,56` vs US formats)       │
   │  • Multi-scenario generation: Full Market, Addressable, Weighted Views │
   └───────────────────┬────────────────────────────────────────────────────┘
                       │ Candidate Dataset
                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │              BLOCKING PRE-PUBLICATION QUALITY GATES                   │
   │  Schema, conservation, dimensional integrity, and magnitude controls   │
   └───────────────────┬────────────────────────────────────────────────────┘
                       │ Passing Candidate Published Atomically
                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │              QLIK SENSE RELOAD & CURRENT-RUN VERIFICATION              │
   │  Reload dashboards, export fresh evidence, reconcile Python totals      │
   └───────────────────┬────────────────────────────────────────────────────┘
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
     [SUCCESS]      [FAILED]     [UNVERIFIED]
      Exit 0         Exit 1         Exit 2
```

---

## ⚙️ Core Technical Highlights

1. **Multi-Scenario Commercial Modeling:**
   Automated the dynamic disaggregation of SAP sales actuals, MedTech Europe market references where available, separate diagnostics/ICM market inputs, Salesforce-entered forecast updates, and internally led sales and market-share forecasts across three strategic views (**Full Market**, **Addressable Market**, and **Addressable Weighted Market**), eliminating error-prone manual Excel modeling.

2. **Defense-in-Depth Quality Assurance and Blocking Publication:**
   Engineered 17 independent automated checks categorized into:
   * **Reconciliation Checksums:** Comparing source, transformed, and downstream totals within the applicable metric tolerances; aggregate agreement does not prove every row is correct.
   * **Magnitude & Anomaly Detection:** Flagging sudden multi-factor spikes, including the class of decimal-format defect documented in the project history.
   * **Human-Error Detection:** Automatically scanning manual inputs for copy-paste duplicates, unchanged forecast baselines, and suspicious round figures.

3. **Self-Contained Public Test Suite:**
   Developed a reproducible pytest harness that injects edge cases such as mixed-case product strings, apostrophe thousands separators (`1'234`), malformed schemas, conservation failures, and non-standard country code aliases. Private connector checks skip explicitly when the unpublished integration package is absent.

4. **Self-Service Regional Governance:**
   Integrated an automated report generator that builds ready-to-forward HTML email drafts (`controller_drafts/{Country}_data_review.html`) customized for regional financial controllers whenever input plausibility warnings are triggered.

5. **Operational Handover & Maintainability:**
   Created a comprehensive **Training & Operations Guide** with documented recovery runbooks for 12 edge cases, environment configuration scripts, and an externalized YAML mapping architecture—allowing non-technical analysts to maintain product catalogs without altering production code.

---

## 💻 Technology Stack

The 17-item production quality framework groups structural checks, downstream reconciliation, and review heuristics. It is not the same as the public demo's 10 checks or the pytest test count. Blocking candidate validation preserves the prior dataset; a later Qlik discrepancy can still occur after publication. The [quality matrix](PORTFOLIO_DATA_QUALITY_MATRIX.md) separates these stages and their evidence.

* **Language & Core:** Python 3.10+, Pandas, NumPy, PyYAML
* **Automation & Orchestration:** Selenium WebDriver (Persistent Browser Profile Session), Custom Orchestrator
* **Data Validation & Testing:** Pytest, Pandera Schema Validation, temporary synthetic fixtures, custom anomaly rules
* **BI & Consumption:** Qlik Sense Analytics, Automated SMTP Reporting, Responsive HTML/CSS Email Templates
