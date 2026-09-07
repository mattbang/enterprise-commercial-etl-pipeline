# Enterprise Commercial BI & ETL Pipeline Suite
[![CI](https://github.com/mattbang/enterprise-commercial-etl-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/mattbang/enterprise-commercial-etl-pipeline/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![Demo](https://img.shields.io/badge/Demo-Self--Contained-2EA44F)](#-public-demo)
[![BPMN 2.0](https://img.shields.io/badge/BPMN-2.0%20Compliant-F05A28?logo=camunda&logoColor=white)](docs/pipeline_orchestration.bpmn)
[![Architecture](https://img.shields.io/badge/Control-Blocking%20Quality%20Gates-8A2BE2)](#-production-case-study-architecture--bpmn-20-process-map)
[![Status](https://img.shields.io/badge/Status-Public%20Portfolio%20Demo-brightgreen)](#-public-demo)

> **Sanitized production case study with a runnable synthetic demo** of a commercial-data pipeline that reconciles market and organization actuals, generates three reporting scenarios, and blocks invalid output before publication.

## Public Demo

The supported public path is local and self-contained. It requires no Qlik tenant, browser authentication, shared drive, email account, or unpublished integration package.

```bash
git clone https://github.com/mattbang/enterprise-commercial-etl-pipeline.git
cd enterprise-commercial-etl-pipeline
pip install -r requirements-demo.txt
python demo.py
```

The run writes a transformed dataset, scenario summary, quality report, and run summary to `demo_output/`.

### Inspect a completed run

| Scenario | Rows | Market units | Market revenue (K EUR) | Organization units | Organization revenue (K EUR) |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Actual Full | 10 | 3,790.0 | 21,440.0 | 997 | 5,692 |
| Actual Addressable | 9 | 3,670.0 | 21,200.0 | 997 | 5,692 |
| Actual Addressable weighted | 9 | 2,959.6 | 17,080.6 | 997 | 5,692 |

The constant organization totals are the central conservation result. Review the [demo output walkthrough](docs/DEMO_OUTPUT_WALKTHROUGH.md), [transformed dataset](docs/demo_output/transformed_dataset.csv), or [10-check quality report](docs/demo_output/data_quality_report.json) without running any code.

See [Public Demo Boundary](docs/PUBLIC_DEMO_BOUNDARY.md) for the exact production-versus-demo scope.

---

## 📌 30-Second Executive Summary

| Business Challenge (Before) | Technical Solution (Automated) | Reported Production Outcome |
| :--- | :--- | :--- |
| **Manual Wrangling:** Downloading extracts across 4 separate systems; 6–8 hours spent weekly standardizing inconsistent European number formats in Excel. | **Headless Selenium + Vectorized Pandas:** Automated ingestion with saved browser authentication; locale-aware parsing standardizing heterogeneous number formats. | The production case study recorded an approximately **98% runtime reduction**, from about 8 hours to under 4 minutes. These operational figures are contextual claims, not outputs of the public demo. |
| **Silent Data Corruption:** Risk of formula errors, dropped distributor territories, or misparsed currency formats reaching executive dashboards. | **17 checks across five quality tiers:** Active reconciliation gates ($Units_{in} = Units_{out}$), magnitude spike checks, and human-error heuristics. | **Blocking publication control:** A failed candidate preserves the last valid published dataset and exits non-zero; warning-level controller review drafts remain separate. |
| **Operational Knowledge Silo:** Process dependent on one person's knowledge of data quirks and manual mapping tables. | **Configuration-Driven Governance:** Product and country mappings externalized to YAML and supported by an operator handover guide. | Routine mapping maintenance can be performed without changing Python code. |

---

## 🗺️ Production Case Study Architecture & BPMN 2.0 Process Map

The pipeline executes a 4-lane orchestration sequence across the Operator, Master Orchestrator, Ingestion layer, and Cloud BI platform. The underlying process model is authored in standard **OMG BPMN 2.0** with hierarchical sub-processes:

*The editable BPMN 2.0 model is available at [`docs/pipeline_orchestration.bpmn`](docs/pipeline_orchestration.bpmn). It can be opened directly in [Camunda Modeler](https://camunda.com/download/modeler/) or viewed online in [bpmn.io](https://demo.bpmn.io). The sequence below is the current rendered summary.*

```mermaid
sequenceDiagram
    autonumber
    actor Op as Operator / Scheduler
    participant Orch as Master Orchestrator (Python)
    participant DL as Headless Ingestion (Selenium + Auth)
    participant BI as Qlik Cloud Engine
    actor Ctrl as Regional Controllers

    %% Pre-flight & Ingestion
    Op->>Orch: Weekly Trigger (python orchestrate_update.py)
    activate Orch
    Note over Orch: Sub-Process 1: Pre-Flight Environment & Lock Validation
    Orch->>DL: Sub-Process 2: Headless Ingestion (CRM, Diagnostics, Forecasts)
    activate DL
    DL-->>Orch: Staged 4 Raw Feeds in data/in/ (~140s)
    deactivate DL

    %% Transformation, blocking validation, and publication
    Note over Orch: Sub-Process 3: Transform candidate and generate 3 scenarios
    Orch->>Orch: Run blocking structural and reconciliation checks
    alt Blocking validation fails
        Orch-->>Op: FAILED (exit 1); retain last valid published dataset
    else Candidate passes
        Orch->>Orch: Atomically publish validated CSV to shared storage
        Orch->>BI: Sub-Process 4: Trigger Qlik Cloud app reload
        activate BI
        BI-->>Orch: Reload acknowledged
        BI-->>Orch: Export current-run verification dataset
        deactivate BI
        alt Fresh verification is missing or stale
            Orch-->>Op: UNVERIFIED (exit 2); do not accept prior-run evidence
        else Fresh verification received
            Orch->>Orch: Reconcile downstream totals against validated CSV
            alt Downstream reconciliation fails
                Orch-->>Op: FAILED (exit 1)
            else Reconciliation passes
                opt Field plausibility warnings detected
                    Orch->>Ctrl: Generate local controller review drafts
                end
                Orch-->>Op: SUCCESS (exit 0)
            end
        end
    end
    deactivate Orch
```

---

## 📚 Portfolio Documentation Suite

This repository includes a comprehensive 5-piece documentation package designed to demonstrate end-to-end data engineering, architecture, and stakeholder communication capabilities:

| Document | Focus Area | What It Demonstrates |
| :--- | :--- | :--- |
| 🏆 **[Executive Case Study](docs/PORTFOLIO_EXECUTIVE_CASE_STUDY.md)** | Business Strategy & ROI | Project brief in the STAR format, financial impact, operational ROI metrics, and architectural overview. |
| 🛡️ **[Data Quality & Governance Matrix](docs/PORTFOLIO_DATA_QUALITY_MATRIX.md)** | Reliability Engineering | Detailed 5-tier defense-in-depth classification of all 17 quality checks, real-world failure prevention case studies (1,000x inflation bug). |
| 📚 **[Turnkey Operations & Training Guide](docs/PORTFOLIO_HANDOVER_TRAINING_GUIDE.md)** | Enablement & Handover (Schulung) | Operator onboarding SOP, pre-flight checklists, code-free business maintenance playbooks, and 12-scenario incident response table. |
| 🌟 **[Technical Capability Showcase](docs/PORTFOLIO_TECHNICAL_CAPABILITY_SHOWCASE.md)** | Advanced Engineering | Deep dives into multi-scenario disaggregation, headless browser-session persistence, regex number coercion, and cloud BI verification. |
| 🗺️ **[BPMN 2.0 Process Model](docs/PORTFOLIO_BPMN_PROCESS_FLOW.md)** | Process Visualization | Full BPMN 2.0 hierarchical sub-process specifications and instructions for interactive inspection in Camunda Modeler. |

---

## 🔬 Core Technical Innovations

### 1. Dynamic Multi-Scenario Commercial Disaggregation
Commercial leadership evaluates performance through three distinct analytical perspectives:
* **Full Market:** Total procedure volume across all market competitors.
* **Addressable Market:** Market filtered exclusively to categories where the organization competes.
* **Addressable Weighted Market:** Opportunity-adjusted market using proprietary therapy weighting factors.

The engine dynamically synthesizes all three reporting scenarios while enforcing an automated **Mathematical Conservation Guard** ($Units_{BIO}$ remains invariant across all scenarios).

### 2. Locale-Aware Numeric Parser (`num_smart()`)
Ingests extracts from subsidiaries across Germany, France, the UK, and Switzerland containing conflicting numerical formats:
* German extracts: `6.170,00` (comma decimal, period thousand)
* US/UK extracts: `6,170.00` (period decimal, comma thousand)
* Swiss/Nordic extracts: `6'170.00` (apostrophe thousand separator)

The parser validates separator grouping before conversion and supports repeated thousands groups, Unicode apostrophes, accounting negatives, blanks, and dash placeholders. Intrinsically ambiguous values such as `1,234` return `NaN` by default; a source with a known format must explicitly select decimal or thousands interpretation.

### 3. Closed-Loop Cloud BI Handshake
Rather than pushing data blindly, the pipeline executes a bidirectional verification handshake:
1. Requires the current candidate's blocking QA report to pass before reload.
2. Atomically publishes the validated CSV and dispatches the authenticated Qlik reload.
3. Accepts only a current-run post-reload audit sheet (`MarketData_Add_Final_Qlik_Verified.csv`).
4. Compares cloud aggregate Net Revenue and Unit volumes against the validated Python master CSV ($Tolerance < 1.00\text{ EUR}$).

The terminal state is explicit: `SUCCESS` exits `0`, `FAILED` exits `1`, and missing or stale downstream evidence produces `UNVERIFIED` with exit `2`.

### 4. Automated Regional Governance Drafts
When soft plausibility anomalies are detected (copy-paste forecast inertia, suspiciously round figures like `500`, or unchanged baselines), the engine automatically compiles **responsive, pre-filled HTML review drafts** (`controller_drafts/{Country}_data_review.html`) customized for regional financial controllers.

---

## 🧪 Public Test Suite

Install the reproducible test dependencies and run the complete public suite:

```bash
pip install -r requirements-test.txt
python -m pytest -q
```

The suite covers parser edge cases, mappings, schema rejection, conservation invariants, three-scenario generation, blocking publication, terminal statuses, deliberately corrupted input, and the end-to-end synthetic demo. Optional checks tied to unpublished connectors or locally generated production outputs are identified explicitly and skip when those artifacts are absent.

GitHub Actions runs the same suite on Python 3.10 and 3.12 for every pull request and every push to `main`.

---

## 🚀 Public Demo Options

### Prerequisites
* Python 3.10+

### Installation
```bash
# Clone the repository
git clone https://github.com/mattbang/enterprise-commercial-etl-pipeline.git
cd enterprise-commercial-etl-pipeline

# Install the minimal public-demo dependencies
pip install -r requirements-demo.txt
```

### Run the supported public demo
```bash
python demo.py
```

`orchestrate_update.py` is retained as production-reference architecture. It depends on private connectors and environment-specific services that are intentionally excluded from this public repository.

---

## 🗺️ Interactive BPMN 2.0 Inspection

The raw XML process model is located at [`docs/pipeline_orchestration.bpmn`](docs/pipeline_orchestration.bpmn).

To inspect the model interactively:
1. **Desktop:** Open the file in [Camunda Modeler](https://camunda.com/download/modeler/) (v5.x+) and double-click any collapsed sub-process box to drill into its internal operations.
2. **Web Browser:** Drag and drop `pipeline_orchestration.bpmn` into the [bpmn.io Web Viewer](https://demo.bpmn.io).

---

## 🔒 Confidentiality & Data Governance Notice
*This repository represents an anonymized architectural showcase. Organization identity, internal corporate portal URLs, proprietary clinical product identifiers, and commercial revenue figures have been sanitized or normalized to protect intellectual property while preserving authentic technical architecture, mathematical logic, and unit conservation principles.*

---

## 📄 License
This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
