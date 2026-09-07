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
| **3** | **Heterogeneous EU/US Numeric Normalizer** | Source files mix European comma decimals (`1.234,50`), US dots (`1,234.50`), and apostrophe separators (`1'234`). | Algorithmic regex parser dynamically evaluating character positions to standardize floats. | Python regex, Custom Parser |
| **4** | **Closed-Loop Cloud BI Orchestration** | Triggering BI reloads blindly risks dashboards displaying corrupted or incomplete loads. | Two-way handshake: triggers Qlik Cloud reload, polls verification tables, and validates against CSV. | Qlik Cloud Engine, REST/DOM Polling |
| **5** | **Field Governance Email Generator** | Manually emailing 8 regional controllers about input data anomalies takes hours of back-and-forth. | Automatic compilation of anomaly logs into localized, ready-to-forward responsive HTML email drafts. | Jinja2/HTML templates, SMTP |
| **6** | **Chaos Testing & Synthetic Stress Harness** | Silent regressions occur when upstream systems tweak column names or insert unexpected nulls. | Test harness generating 7 corrupted synthetic spreadsheets validating 106 edge-case assertions. | Pytest, Pandera Schemas |

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
Data feeds originate from four disparate internal systems (Commercial CRM, Diagnostic Registries, and forecasting portals). None exposed public API endpoints; all required authenticated corporate enterprise sign-in.

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

#### The Solution (`core/schemas.py` & `_smart_parse()`)
Engineered a bulletproof numeric coercion algorithm that evaluates string character positions rather than blind string replacements:

```python
def _smart_parse(val: str) -> str:
    """Dynamically converts heterogeneous European and US strings to standard floats."""
    val = str(val).strip().replace("'", "")
    last_dot = val.rfind(".")
    last_comma = val.rfind(",")

    if last_dot >= 0 and last_comma >= 0:
        if last_comma > last_dot:
            # European format: 1.234,56 -> 1234.56
            return val.replace(".", "").replace(",", ".")
        else:
            # US format: 1,234.56 -> 1234.56
            return val.replace(",", "")
    elif last_comma >= 0:
        # Lone comma decimal: 1234,56 -> 1234.56
        return val.replace(",", ".")
    return val
```

* **Dimensional Normalization:** Automatically reconciles country code aliases (`UK` &rarr; `GB`, `EL` &rarr; `GR`) and remaps 13 non-sovereign export territories into their legal standard parent entities.

---

### 4. Closed-Loop Cloud BI Orchestration & Post-Reload Reconciliation

#### The Challenge
Traditional data pipelines push data into a cloud BI platform (like Qlik Cloud, Tableau, or PowerBI) and terminate. If the cloud engine experiences an indexing failure, memory exhaustion, or load-script syntax issue, dashboards silently display stale or partial data.

#### The Solution (`integration/helpers/reload_helpers.py` & `validation_helpers.py`)
Implemented a **Two-Way Closed-Loop Handshake**:

```
[Python Pipeline] ──── (1) Triggers Reload ────▶ [Qlik Cloud Engine]
        │                                                │
        │                                                ▼
        │                                    [Data Model Reloads]
        │                                                │
        │                                                ▼
        │                                    [Export Verification Sheet]
        │                                                │
[Python Pipeline] ◀─── (2) Download Sheet ───────────────┘
        │
        ▼
[Reconciliation Engine] ─── Compare: Qlik Model Totals == Python Master CSV
        │
        ├── Match (Diff < €1.00) ──▶ Pipeline Complete & Executive Email Sent
        └── Mismatch ──────────────▶ Trip Circuit Breaker & Send Urgent Alert
```

1. **Trigger:** The orchestrator dispatches an automated API/DOM reload command to Qlik Cloud.
2. **Server-Side Acknowledgment:** Polls for the server reload completion token (with a 45-second stabilization wait).
3. **Verification Extraction:** Automatically triggers an export of the Qlik Cloud summary audit table (`MarketData_Add_Final_Qlik_Verified.csv`).
4. **End-to-End Cross-Check:** The Python validation engine parses both the source CSV and the freshly generated Qlik summary sheet. If aggregate Net Revenue or Unit volumes differ by more than **€1.00**, the circuit breaker trips.

---

### 5. Automated Field Governance: Local Controller Email Generator

#### The Challenge
When regional sales subsidiaries submit quarterly forecasts, manual errors inevitably slip in (e.g., duplicated past-year numbers, unrefined placeholder numbers like `500`, or missing quarters). Tracking down controllers across 8 countries required days of manual email drafting.

#### The Solution
When the plausibility validation engine flags anomalies, it dynamically renders **tailored, responsive HTML email drafts** per country code (`controller_drafts/{Country_Code}_data_review.html`):
* Aggregates country-specific warnings into an intuitive bulleted list.
* Pre-populates the controller's email address and submission deadline.
* Formats tables with highlighted cells showing flagged values vs. historical benchmarks.
* Ready for the central analyst to review and forward with a single click.

---

### 6. Synthetic Chaos Engineering & Stress Testing (106 Tests)

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

* **106 Automated Tests Passing:** Validating numeric parsing (17 tests), quarter parsing (9 tests), product mappings (3 tests), country/territory rules (5 tests), schema enforcement (2 tests), data loaders (16 tests), product logic (8 tests), column safety (2 tests), and output sanity (9 tests).
* **Zero Breakage Guarantee:** The entire pipeline can ingest raw spreadsheets containing extreme edge cases without throwing unhandled exceptions or corrupting master reporting datasets.
