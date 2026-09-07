# Enterprise Data Pipeline & Analytics Automation: Executive Case Study
**Domain:** Medical Technology / Cardiac Rhythm Management
**Role:** Lead Analytics Engineer / BI Developer
**Status:** Sanitized Production Case Study | Public Demo Verified

> *Confidentiality Notice: Organization identity, internal portal URLs, proprietary product identifiers, and commercial volumes have been anonymized or normalized for portfolio presentation while preserving the relevant technical architecture and business logic. Operational impact figures below describe the production case study; they are not generated or independently verified by the public demo.*

---

## 📌 Executive Summary

To monitor regional market share and commercial performance across **8 European markets and 13 export territories**, commercial leadership required weekly consolidated dashboards reconciling multi-source actuals with forward-looking corporate forecasts.

Previously, this process was performed manually: downloading raw extracts from 4 disparate enterprise systems, manually cleaning and standardizing varying European number formats in Excel, merging records, and hand-validating figures. This manual workflow consumed **6 to 8 hours per cycle**, was vulnerable to human error, and created a critical single-person operational dependency.

This project engineered an automated Python ETL and orchestration pipeline covering ingestion, transformation, multi-scenario financial modeling, cloud BI reloading, and validation. The production case study recorded execution in **under 4 minutes**, an approximately **98% reduction** from the manual baseline. The public repository demonstrates the transformation rules and blocking publication controls with synthetic data; private connectors and production services are intentionally excluded.

---

## 📊 Key Impact & ROI Metrics

| Metric | Before (Manual Process) | After (Automated Pipeline) | Impact |
| :--- | :--- | :--- | :--- |
| **Cycle Execution Time** | 6 – 8.5 hours / run | **~4 minutes reported in production** | **Approximately 98% reported reduction** |
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
   │  Commercial CRM        Corporate Planning      Diagnostics Feed        │
   │  (Historical Actuals)  (Live/Static Forecasts) (Quarterly Registry)    │
   └───────────────────┬────────────────────────────────────────────────────┘
                       │ Automated Headless Browser Ingestion (Selenium + Auth)
                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │                  CORE ETL & FINANCIAL DISAGGREGATION                   │
   │  • Unified country/territory remapping (8 core entities + 13 exports)   │
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
   │              BI CLOUD RELOAD & CURRENT-RUN VERIFICATION                │
   │  Reload, export fresh evidence, and reconcile against Python totals    │
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
   Automated the dynamic disaggregation of quarterly diagnostic and market volumes across three strategic views (**Full Market**, **Addressable Market**, and **Addressable Weighted Market**), eliminating error-prone manual Excel modeling.

2. **Defense-in-Depth Quality Assurance and Blocking Publication:**
   Engineered 17 independent automated checks categorized into:
   * **Reconciliation Checksums:** Comparing upstream raw extracts with downstream BI reporting sheets to guarantee 0 lost units or revenue.
   * **Magnitude & Anomaly Detection:** Flagging sudden multi-factor spikes (e.g., catching European decimal vs. thousands comma bugs before production release).
   * **Human-Error Detection:** Automatically scanning manual inputs for copy-paste duplicates, unchanged forecast baselines, and suspicious round figures.

3. **Self-Contained Public Test Suite:**
   Developed a reproducible pytest harness that injects edge cases such as mixed-case product strings, apostrophe thousands separators (`1'234`), malformed schemas, conservation failures, and non-standard country code aliases. Private connector checks skip explicitly when the unpublished integration package is absent.

4. **Self-Service Regional Governance:**
   Integrated an automated report generator that builds ready-to-forward HTML email drafts (`controller_drafts/{Country}_data_review.html`) customized for regional financial controllers whenever input plausibility warnings are triggered.

5. **Operational Handover & Maintainability:**
   Created a comprehensive **Training & Operations Guide** with documented recovery runbooks for 12 edge cases, environment configuration scripts, and an externalized YAML mapping architecture—allowing non-technical analysts to maintain product catalogs without altering production code.

---

## 💻 Technology Stack

* **Language & Core:** Python 3.10+, Pandas, NumPy, PyYAML
* **Automation & Orchestration:** Selenium WebDriver (Persistent Browser Profile Session), Custom Orchestrator
* **Data Validation & Testing:** Pytest, Pandera Schema Validation, temporary synthetic fixtures, custom anomaly rules
* **BI & Consumption:** Qlik Cloud Analytics Engine, Automated SMTP Reporting, Responsive HTML/CSS Email Templates
