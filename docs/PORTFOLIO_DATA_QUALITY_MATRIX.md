# Multi-Layer Data Quality & Governance Framework
**Document Type:** Technical Architecture & Quality Assurance Specification
**Domain:** Commercial Healthcare & MedTech Data Engineering
**System:** Automated Multi-Source Financial & Market ETL Pipeline

> *Confidentiality Notice: Organization identity, internal portal URLs, proprietary product identifiers, and commercial volumes have been anonymized or normalized for portfolio presentation while strictly preserving authentic technical architecture and business logic.*

---

## 🛡️ Architecture Overview: Defense-in-Depth

In enterprise commercial reporting, silent data corruption is catastrophic: executive decisions, territorial sales quotas, and revenue forecasts depend on accurate market data. Traditional ETL pipelines often rely on passive failure handling (e.g., throwing a Python exception only if a script crashes).

This pipeline implements an active **5-Tier Defense-in-Depth Data Quality Framework** featuring **17 independent automated validation gates**. The system operates as a **Circuit Breaker**: if any structural reconciliation check fails, the pipeline halts immediately, preventing corrupt or truncated data from ever reaching the production cloud BI dashboards.

```
 RAW EXTERNAL EXTRACTS (CRM, Forecasts, Registries, Ad-hoc Files)
                           │
                           ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │ TIER 1: Ingestion & File Health                                  │  Check 1
 │ • File freshness, zero-byte locks, I/O validation                │
 └─────────────────────────┬────────────────────────────────────────┘
                           │ Passed
                           ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │ TIER 2: Schema Conformance & Dimensional Completeness            │  Checks 2, 8
 │ • Pandera type coercion, primary key integrity, null-rate caps   │
 └─────────────────────────┬────────────────────────────────────────┘
                           │ Passed
                           ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │ TIER 3: Upstream-to-Downstream Reconciliation (Conservation Laws)│  Checks 3, 4, 5, 6, 9
 │ • Exact unit & revenue checksums, country preservation, BI match │
 └─────────────────────────┬────────────────────────────────────────┘
                           │ Passed
                           ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │ TIER 4: Statistical Plausibility & Outlier Detection             │  Checks 7, 10, 14, 15, 17
 │ • 10x magnitude spike catchers, negative units, velocity jumps   │
 └─────────────────────────┬────────────────────────────────────────┘
                           │ Passed
                           ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │ TIER 5: Human-Error & Field Heuristics (Local Governance)        │  Checks 11, 12, 13, 16
 │ • Copy-paste inertia, round placeholder numbers, missing gaps    │
 └─────────────────────────┬────────────────────────────────────────┘
                           │
            ┌──────────────┴──────────────┐
            ▼                             ▼
   [All Gates Clean]             [Soft Anomalies Flagged]
   Production Reloaded           Auto-Generated Review Drafts Sent
   Executive Status Broadcast    to Regional Financial Controllers
```

---

## 📋 The 17-Point Controls & Checks Matrix

| # | Check Name | Target Tier | Enforcement Level | Verification Mechanism | Real Failure Case Prevented |
|---|:---|:---:|:---:|:---|:---|
| **1** | **Pipeline Outputs & File Freshness** | Tier 1 | 🔴 **Critical Block** | Validates filesystem write timestamps & non-zero byte size for all output CSVs and master tables. | Catches silent disk-full errors or operating system file locks before downstream consumers poll. |
| **2** | **Column Completeness & Dimension Integrity** | Tier 2 | 🔴 **Critical Block** | Enforces strict maximum missing-value thresholds on core dimensions: `SOURCE` (0%), `Version` (0%), `Country Code` (<1%), `Product Group` (<1%). | Prevented unmapped records where Belgium sales figures entered the system without country keys. |
| **3** | **Country-Level Preservation** | Tier 3 | 🔴 **Critical Block** | Reconciles unit conservation per country code ($Units_{in} = Units_{out}$) across all transformations. | Discovered a subtle join filter that dropped overseas export territories and regional Ireland entities. |
| **4** | **Commercial Source Reconciliation (CRM/Actuals)** | Tier 3 | 🔴 **Critical Block** | Cross-validates source CRM input units against pipeline output units with absolute tolerance $\le 10$ units (rounding). | Prevents data loss during product reclassification and business unit exclusions. |
| **5** | **Diagnostics Source Reconciliation (Registry)** | Tier 3 | 🔴 **Critical Block** | Validates dual-feed inputs (quarterly organization figures + annual market estimates) against final disaggregated tables. | Ensures disaggregation algorithms correctly preserve total annual market volumes. |
| **6** | **Cross-Scenario Internal Consistency** | Tier 3 | 🔴 **Critical Block** | Cross-checks company units across all 3 reporting views (*Full Market*, *Addressable Market*, *Addressable Weighted*). | Enforces that organization baseline performance remains strictly identical across scenario models. |
| **7** | **Magnitude Spike & Formatting Outlier Check** | Tier 4 | 🔴 **Critical Block** | Compares Live vs. Static forecast ratios per year/country/product; flags any ratio $>10\times$. | **Caught a 1,000x volume inflation bug** caused by European comma vs. US period decimal string parsing. |
| **8** | **Minimum Row-Count Sanity Gate** | Tier 2 | 🔴 **Critical Block** | Enforces conservative minimum row thresholds per source and scenario (e.g., CRM Addressable $\ge 5,000$ rows). | Instantly halts the pipeline if a source file is truncated or an upstream filter drops an entire product family. |
| **9** | **End-to-End Cloud BI Checksum** | Tier 3 | 🔴 **Critical Block** | Headless browser exports aggregate totals from the live Qlik Cloud application and compares them against Python master CSV ($Tolerance < 1.0\text{ EUR}$). | Catches Qlik load-script formula bugs, server-side reload timeouts, or partial app cache corruptions. |
| **10** | **Negative Unit Threshold & Whitelist** | Tier 4 | 🔴 **Critical Block** | Flags any net unit value $< -100$; filters against an audited whitelist of verified accounting reversals (returns/EOL). | Catches formula inversion bugs in manual adjustment spreadsheets. |
| **11** | **Forecast Copy-Paste Detection** | Tier 5 | 🟡 **Warning Alert** | Scans multi-year forward projections for identical organization and market units across consecutive planning years. | Identifies field analysts who duplicated previous year forecasts without updating planning assumptions. |
| **12** | **Suspicious Round-Number Heuristics** | Tier 5 | 🟡 **Warning Alert** | Detects forecast figures rounded to exact hundreds/thousands when historical actuals exhibit organic variance. | Flags unrefined placeholder numbers entered by regional planning teams prior to finalized reviews. |
| **13** | **Unchanged Forecast Baseline Detection** | Tier 5 | 🟡 **Warning Alert** | Flags instances where forward-looking forecast inputs exactly equal prior-year historical actuals. | Catches regional submissions where the planning period was rolled over without analysis. |
| **14** | **Quarter-over-Quarter (QoQ) Velocity Jump** | Tier 4 | 🟡 **Warning Alert** | Identifies non-seasonal quarter-to-quarter unit changes exceeding $+50\%$ or $-50\%$. | Flags unexpected regional demand spikes or misallocated bulk orders before executive presentation. |
| **15** | **Year-over-Year (YoY) Velocity Jump** | Tier 4 | 🟡 **Warning Alert** | Flags multi-period trends where annual volume expands $>100\%$ without a corresponding product launch. | Detects structural market definition shifts or misclassified competitor movements. |
| **16** | **Time-Series Sequence Gap Detection** | Tier 5 | 🟡 **Warning Alert** | Analyzes quarterly sequences per country/therapy; verifies continuous chronological progression without omitted quarters. | Catches missing quarterly entries in regional field spreadsheets. |
| **17** | **Data Stagnation & Stale Sequence Gate** | Tier 4 | 🟡 **Warning Alert** | Verifies that the most recent available quarter is not $>2$ quarters behind the current execution date. | Alerts operations when upstream reporting teams fail to publish their quarterly data packages. |

---

## 🔍 Deep-Dive: Real-World Engineering Failure Modes Prevented

### Case 1: The "European Decimal 1,000x Inflation Bug" (Check #7)
* **The Root Cause:** In German and French operating extracts, numbers are formatted with period thousand separators and comma decimals (e.g., `1.234,50`). In US-formatted extracts, commas represent thousands (e.g., `1,234.50`). A standard `pd.to_numeric(val.replace(',', ''))` transformed `1,500` (1.5 units) into `1500` (fifteen hundred units)—a **1,000x inflation**.
* **The Governance Gate:** Check #7 evaluates the ratio between Live forecast submissions and verified Static planning baselines for every `(Year, Country, Product)` tuple.
* **The Circuit Breaker:** When the ratio hit `1000.0x`, Check #7 tripped immediately, generating an alert and blocking the Qlik Cloud reload. A specialized `_smart_parse()` regex function was engineered into the core ingestion engine to dynamically distinguish European from US number notations.

### Case 2: Silent Data Drop in Overseas Territories (Check #3)
* **The Root Cause:** During an ETL migration, a SQL-like merge condition `on=['COUNTRY_CODE']` dropped 13 export territories (e.g., French Overseas Departments and regional distributor codes) because the secondary lookup table only listed sovereign European nations.
* **The Governance Gate:** Check #3 calculates a country-by-country unit conservation hash before and after the pipeline transformation.
* **The Circuit Breaker:** The system flagged an 8.4% unit mismatch in the French commercial entity. The pipeline halted, allowing developers to implement a dedicated territorial alias dictionary in `config/mappings.yaml` without publishing flawed market-share figures.

---

## 📬 Automated Field Governance: Controller Review Drafts

To eliminate manual email coordination when field data quality warnings occur (Checks #11 through #17), the validation engine automatically constructs **pre-formatted, responsive HTML review drafts** saved to:
`controller_drafts/{Country_Code}_data_review.html`

```
┌────────────────────────────────────────────────────────────────────────┐
│ SUBJECT: Automated Data Review Notice: [Country] Q1 Planning Baselines │
│                                                                        │
│ Dear Financial Controller,                                             │
│                                                                        │
│ The automated quality engine flagged the following items in your       │
│ latest submission:                                                     │
│                                                                        │
│  • Therapy Line B: Unchanged forecast identical to 2024 Actuals (Check 13)
│  • Therapy Line D: Suspicious round value (500 units) entered (Check 12)│
│                                                                        │
│ Please confirm if these entries reflect intentional projections or     │
│ submit an adjustment before the final dashboard freeze at 17:00 CET.   │
└────────────────────────────────────────────────────────────────────────┘
```

This automates the loop between **data engineering** and **commercial business controllers**, transforming the pipeline from a passive data mover into an active corporate governance engine.
