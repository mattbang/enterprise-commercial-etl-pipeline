# Enterprise Data Pipeline & Analytics Automation: Executive Case Study
**Domain:** Medical Technology / Cardiac Rhythm Management
**Role:** Lead Analytics Engineer / BI Developer
**Status:** In Production | Fully Automated

> *Confidentiality Notice: Organization identity, internal portal URLs, proprietary product identifiers, and commercial volumes have been anonymized or normalized for portfolio presentation while strictly preserving authentic technical architecture and business logic.*

---

## 📌 Executive Summary

To monitor regional market share and commercial performance across **8 European markets and 13 export territories**, commercial leadership required weekly consolidated dashboards reconciling multi-source actuals with forward-looking corporate forecasts.

Previously, this process was performed manually: downloading raw extracts from 4 disparate enterprise systems, manually cleaning and standardizing varying European number formats in Excel, merging records, and hand-validating figures. This manual workflow consumed **6 to 8 hours per cycle**, was vulnerable to human error, and created a critical single-person operational dependency.

This project engineered a **fully automated, containerized Python ETL and orchestration pipeline** that executes the entire ingestion, transformation, multi-scenario financial modeling, cloud BI reloading, and validation cycle in **under 4 minutes**, reducing end-to-end processing time by **~98%** while establishing a 17-layer data governance safety net.

---

## 📊 Key Impact & ROI Metrics

| Metric | Before (Manual Process) | After (Automated Pipeline) | Impact |
| :--- | :--- | :--- | :--- |
| **Cycle Execution Time** | 6 – 8.5 hours / run | **~4 minutes** | **98% time reduction** (~40+ hrs saved/yr) |
| **Data Ingestion & Merge** | Manual download & Excel copy-paste | Headless Selenium + Vectorized Pandas | Fully automated multi-source ingestion |
| **Data Quality Verification** | Ad-hoc manual spot-checks | **17 automated runtime validation gates** | Halts deployment on discrepancy |
| **Edge Case & Regression Coverage**| Zero formal test coverage | **106 automated unit & stress tests** | Handles European numbers, blanks, nulls |
| **Field Anomaly Reporting** | Manual email drafting per country | Automated HTML discrepancy alerts | Instant controller review drafts |
| **Knowledge Transfer** | Tribal knowledge / single point of failure | Turnkey Operations & Troubleshooting Manual | **1–2 hour onboarding** for junior analysts |

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
                       │ Vectorized Processing & Master Export
                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │                   BI CLOUD ORCHESTRATION & RELOAD                      │
   │  Automated cloud trigger & reload confirmation via Qlik Cloud Engine   │
   └───────────────────┬────────────────────────────────────────────────────┘
                       │ Post-Reload Verification Data Extraction
                       ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │             17-STAGE DEFENSE-IN-DEPTH DATA QUALITY GATES               │
   │  [Layer 1: Schema & Completeness]  [Layer 2: Source Reconciliation]    │
   │  [Layer 3: Forecast Plausibility]   [Layer 4: Human Error Detection]   │
   └───────────────────┬────────────────────────────────────────────────────┘
                       │
         ┌─────────────┴─────────────┐
         ▼                           ▼
  [All Gates Pass]            [Anomaly Detected]
  Production Dashboard Live   Circuit Breaker Trips
  Executive Notification Sent Auto-Drafts Sent to Regional Controllers
```

---

## ⚙️ Core Technical Highlights

1. **Multi-Scenario Commercial Modeling:**
   Automated the dynamic disaggregation of quarterly diagnostic and market volumes across three strategic views (**Full Market**, **Addressable Market**, and **Addressable Weighted Market**), eliminating error-prone manual Excel modeling.

2. **Defense-in-Depth Quality Assurance (The Circuit Breaker):**
   Engineered 17 independent automated checks categorized into:
   * **Reconciliation Checksums:** Comparing upstream raw extracts with downstream BI reporting sheets to guarantee 0 lost units or revenue.
   * **Magnitude & Anomaly Detection:** Flagging sudden multi-factor spikes (e.g., catching European decimal vs. thousands comma bugs before production release).
   * **Human-Error Detection:** Automatically scanning manual inputs for copy-paste duplicates, unchanged forecast baselines, and suspicious round figures.

3. **Chaos-Tested Reliability (106 Automated Tests):**
   Developed a synthetic test harness that injects edge cases—such as mixed-case product strings, apostrophe thousands separators (`1'234`), missing quarter sequences, and non-standard country code aliases—ensuring 100% test pass rate under corrupted input conditions.

4. **Self-Service Regional Governance:**
   Integrated an automated report generator that builds ready-to-forward HTML email drafts (`controller_drafts/{Country}_data_review.html`) customized for regional financial controllers whenever input plausibility warnings are triggered.

5. **Operational Handover & Maintainability:**
   Created a comprehensive **Training & Operations Guide** with documented recovery runbooks for 12 edge cases, environment configuration scripts, and an externalized YAML mapping architecture—allowing non-technical analysts to maintain product catalogs without altering production code.

---

## 💻 Technology Stack

* **Language & Core:** Python 3.10+, Pandas, NumPy, PyYAML
* **Automation & Orchestration:** Selenium WebDriver (Persistent Browser Profile Session), Custom Orchestrator
* **Data Validation & Testing:** Pytest (106 tests), Pandera Schema Validation, Custom Anomaly Rules
* **BI & Consumption:** Qlik Cloud Analytics Engine, Automated SMTP Reporting, Responsive HTML/CSS Email Templates
