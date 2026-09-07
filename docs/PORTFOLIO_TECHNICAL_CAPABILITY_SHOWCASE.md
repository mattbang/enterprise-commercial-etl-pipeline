# Functionality & Technical Capability Showcase
**Document Type:** Technical Architecture & Feature Specification
**Domain:** Commercial Healthcare & MedTech Data Engineering
**System:** Enterprise Multi-Source Financial & Market ETL Pipeline

> *Confidentiality Notice: Organization identity, internal portal URLs, proprietary product identifiers, and commercial volumes have been anonymized or normalized for portfolio presentation while strictly preserving authentic technical architecture and business logic.*

---

## 🌟 Capability Matrix at a Glance

| # | Technical Capability | Real-World Business Problem Solved | Engineering Implementation | Tech Stack |
|---|:---|:---|:---|:---|
| **1** | **Dynamic Multi-Scenario Modeling** | Business requires 3 different strategic views of market share without manual Excel pivot models. | Vectorized quarterly disaggregation and synthetic row generation conserving organization volume. | Pandas, NumPy |
| **2** | **Headless Authenticated Ingestion Engine** | Upstream enterprise portals lack public REST APIs; require authenticated browser downloads. | Headless Selenium automation with persistent user profile, auto-wait conditions, and retry loops. | Selenium, Chrome WebDriver |
| **3** | **Heterogeneous EU/US Numeric Normalizer** | Source files mix European comma decimals (`1.234,50`), US dots (`1,234.50`), and apostrophe separators (`1'234`). | Validated locale-aware parser with explicit handling for ambiguous single separators. | Python regex, Custom Parser |
| **4** | **Closed-Loop Qlik Sense Orchestration** | Triggering BI reloads blindly risks dashboards displaying corrupted or incomplete loads. | Two-way handshake: triggers Qlik Sense reload, polls verification tables, and validates against CSV. | Qlik Sense, REST/DOM Polling |
| **5** | **Field Governance Email Generator** | Manually emailing 8 regional controllers about input data anomalies takes hours of back-and-forth. | Automatic compilation of anomaly logs into localized, ready-to-forward responsive HTML email drafts. | Jinja2/HTML templates, SMTP |
| **6** | **Synthetic Stress Harness** | Silent regressions occur when upstream systems tweak column names or insert unexpected nulls. | Self-contained pytest suite generates temporary corrupted spreadsheets and tests parser, schema, mapping, publication, and demo behavior. | Pytest, Pandera Schemas |

---

## 🔬 Feature Deep-Dives

### 1. Dynamic Multi-Scenario Commercial Modeling Engine

#### The Challenge
Executive leadership and regional country managers evaluate commercial performance through three distinct analytical lenses:
1. **Full Market View:** Total estimated procedure volumes across all competitor product categories.
2. **Addressable Market View:** Market volume filtered exclusively to clinical sub-segments where the organization offers competitive devices.
3. **Addressable Weighted Market View:** Segment volumes adjusted by proprietary weighting factors to reflect addressable clinical opportunity.

Manually maintaining three separate versions of quarterly reports previously required dozens of nested Excel formulas, creating high operational fragility.

#### The Solution (`core/midwest_pipeline.py`)
The pipeline loads raw actuals and external quarterly estimates, applies specialized clinical product splits (e.g., separating single-chamber from dual-chamber leadless lines), and automatically synthesizes all three reporting scenarios within a unified dataset:

```
[Raw CRM Actuals] + [Quarterly Diagnostics] + [Corporate Forecasts]
                              │
                              ▼
        ┌───────────────────────────────────────────┐
        │  Vectorized Disaggregation & Split Engine │
        └─────────────────────┬─────────────────────┘
                              │
     ┌────────────────────────┼────────────────────────┐
     ▼                        ▼                        ▼
[Actual Full]       [Actual Addressable]   [Addressable Weighted]
Total market size   Filtered to company    Weighted segment
for macro strategy  competitive scope      commercial index
     │                        │                        │
     └────────────────────────┼────────────────────────┘
                              ▼
        Conserved Unit Check: $Units_{BIO}$ identical across all 3
```

* **Conservation Law Enforcement:** An automated mathematical guard guarantees that while the market denominator shifts according to the scenario, organization revenue and unit totals remain strictly identical across all three views.

---

### 2. Resilient Headless Ingestion & Session Management

#### The Challenge
Data feeds originated from SAP sales downloads, MedTech Europe market reference files, Salesforce-entered employee forecast updates, and internally maintained sales forecast and market-share forecast inputs. The forecasting process was led by the pipeline owner during the production period and served regional finance reporting across 9 countries. Private source connectors are excluded from the public repository.

#### The Solution (`integration/downloaders/`)
Built an enterprise-grade web scraping and file ingestion layer using **Selenium WebDriver**:
* **Persistent Browser Profile:** Operates using an encrypted, persistent Chrome user data directory (`chrome_profile_path`), reducing repeated interactive sign-in prompts while keeping session handling configurable.
* **Intelligent Polling & Mutex Locks:** Instead of arbitrary sleep timers, the downloader monitors filesystem events in the OS download directory, detecting `.crdownload` temporary files and verifying file size stability before proceeding.
* **Self-Healing Process Recovery:** Automated teardown logic detects and terminates orphan background `chrome.exe` zombie processes before launching new runs, eliminating deadlocks on shared workstations.

---

### 3. European Heterogeneous Numeric & Dimensional Parser

#### The Challenge
The pipeline ingests extracts originating from subsidiaries across Germany, France, the UK, and the Netherlands. Spreadsheets arrive with conflicting numerical conventions:
* German extracts: `6.170,00` (comma decimal, period thousand)
* US/UK extracts: `6,170.00` (period decimal, comma thousand)
* Swiss/Nordic formats: `6'170.00` (apostrophe thousand separator)
* Accounting placeholders: `-`, `--`, `N/A`, ` ` (whitespace)

#### The Solution (`core/utils.py` and `num_smart()`)
The parser validates grouping patterns before conversion and fails closed when punctuation alone cannot establish the intended value:

```python
num_smart("1.234,56")                         # 1234.56
num_smart("1,234.56")                         # 1234.56
num_smart("6'170.00")                         # 6170.0
num_smart("1,234")                            # NaN: ambiguous
num_smart("1,234", ambiguous="thousands")    # 1234.0
num_smart("1,234", ambiguous="decimal")      # 1.234
```

Repeated grouping separators such as `1,234,567` are recognized as thousands groups. A value such as `3031.065` remains a decimal because its four-digit leading group cannot be valid thousands notation.

* **Dimensional Normalization:** Automatically reconciles country code aliases (`UK` &rarr; `GB`, `EL` &rarr; `GR`) and remaps 13 non-sovereign export territories into their legal standard parent entities.

---

### 4. Closed-Loop Qlik Sense Orchestration & Post-Reload Reconciliation

#### The Challenge
Traditional data pipelines push data into a BI platform and terminate. In this production case, Qlik Sense dashboards served regional finance and management users who used the visuals for goal setting, market-share review, and performance benchmarking. If the BI engine experienced an indexing failure, memory exhaustion, or load-script syntax issue, dashboards could silently display stale or partial data.

#### The Solution (`integration/helpers/reload_helpers.py` & `validation_helpers.py`)
Implemented a **blocking publication gate followed by a two-way verification handshake**:

```
[Candidate Dataset] -> [Blocking QA]
       | failed              | passed
       v                     v
[Retain Prior Dataset]  [Atomic Publication] -> [Qlik Sense Reload]
                                                  |
                                                  v
                                      [Current-Run Verification]
                                         |       |       |
                                      match   mismatch  stale/missing
                                         |       |       |
                                         v       v       v
                                      SUCCESS  FAILED  UNVERIFIED
                                      exit 0   exit 1    exit 2
```

1. **Blocking Publication:** The current QA report must pass before the candidate replaces the published CSV or triggers a cloud reload.
2. **Trigger and Acknowledgment:** The orchestrator dispatches the reload and waits for server-side processing.
3. **Fresh Verification Extraction:** The current run must produce `MarketData_Add_Final_Qlik_Verified.csv`; stale files are not copied as fallback evidence.
4. **End-to-End Cross-Check:** A difference above **€1.00** fails the run, while missing current-run evidence marks it `UNVERIFIED`.

---

### 5. Automated Field Governance: Local Controller Email Generator

#### The Challenge
When regional sales teams and employees submit quarterly sales and market-share forecast updates, including manual Salesforce updates, errors inevitably slip in (e.g., duplicated past-year numbers, unrefined placeholder numbers like `500`, or missing quarters). Tracking down finance controllers across 9 countries required days of manual email drafting.

#### The Solution
When the plausibility validation engine flags anomalies, it dynamically renders **tailored, responsive HTML email drafts** per country code (`controller_drafts/{Country_Code}_data_review.html`):
* Aggregates country-specific warnings into an intuitive bulleted list.
* Pre-populates the controller's email address and submission deadline.
* Formats tables with highlighted cells showing flagged values vs. historical benchmarks.
* Ready for the central analyst to review and forward with a single click.

---

### 6. Synthetic Stress Testing

#### The Challenge
Data pipelines frequently fail when exposed to real-world edge cases that were never observed during development.

#### The Solution (`tests/test_stress_pipeline.py`)
Engineered a comprehensive stress testing framework that synthesizes intentionally corrupted datasets to validate system resilience:

```
                  ┌──────────────────────────────────────────────┐
                  │          SYNTHETIC CORRUPTION SUITE          │
                  └──────────────────────┬───────────────────────┘
                                         │
     ┌───────────────────┬───────────────┴───────────────┬───────────────────┐
     ▼                   ▼                               ▼                   ▼
[Corrupted Types]   [Delimiter Chaos]           [Schema Breakers]     [Clinical Anomalies]
`"1'234"`, `"N/A"`, Mixed dots & commas,        Duplicate headers,    Zero market units with
`"--"`, all-NaN rows trailing whitespace        omitted columns       positive organization sales
```

* **Reproducible public suite:** Validates numeric parsing, quarter parsing, mappings, schema enforcement, data loaders, publication blocking, terminal statuses, and end-to-end demo behavior.
* **Hermetic fixtures:** Generated workbooks live in pytest temporary directories and do not leave commercial-looking artifacts in the repository.
