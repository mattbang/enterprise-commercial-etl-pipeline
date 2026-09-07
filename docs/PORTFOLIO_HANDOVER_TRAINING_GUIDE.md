# Turnkey Operations & Training Guide (Schulung & Handover Manual)
**Document Type:** Standard Operating Procedure (SOP) & Operator Training Manual
**Target Audience:** Junior Analysts, Operations Associates, Systems Support Engineers
**System:** Commercial BI & Data Pipeline Automation Engine

> *Confidentiality Notice: Organization identity, internal portal URLs, proprietary product identifiers, and commercial volumes have been anonymized or normalized for portfolio presentation while strictly preserving authentic technical architecture and business logic.*

---

## 🎯 Purpose & Training Objectives (Schulungsziel)

The primary design principle of this pipeline is **zero single-person operational dependency**.

By completing this 1-hour self-guided training document, any commercial analyst, intern, or support team member will be fully equipped to:
1. **Execute** the weekly commercial data update independently with a single command.
2. **Verify** end-to-end data integrity across upstream extracts and cloud dashboards.
3. **Perform routine business maintenance** (e.g., adding product lines or locking quarterly forecast baselines) via configuration files without writing Python code.
4. **Diagnose and resolve** operational anomalies using the 12-scenario incident response playbook.

---

## 🚀 Section 1: Operator Quick-Start (1-Command Execution)

### 1.1 Pre-Flight Checklist
Before launching the weekly execution, confirm the following prerequisites:
* [ ] **Network & VPN:** Approved network access to cloud BI and shared storage.
* [ ] **No File Locks:** Ensure no input or output `.xlsx` files in the `data/` directory are currently open in Microsoft Excel.
* [ ] **Browser State:** Ensure all background instances of Google Chrome under the automation profile are closed.

### 1.2 Execution Commands
Open your terminal (PowerShell, Bash, or Command Prompt) in the project directory and run:

```bash
# Standard Weekly Execution:
# Automated download of 4 data sources, transformation, cloud BI reload, 17 validation checks, and email dispatch
python orchestrate_update.py
```

### 1.3 Command-Line Flags (Operational Control)

| Operational Scenario | Command | Execution Behavior |
| :--- | :--- | :--- |
| **Standard Weekly Run** | `python orchestrate_update.py` | Full end-to-end cycle (~4 minutes total). |
| **Config/Mapping Update** | `python orchestrate_update.py --skip-downloads` | Skips web downloads; re-processes existing raw files (~1 minute total). |
| **Safe Dry-Run Simulation** | `python orchestrate_update.py --dry-run` | Tests transformations without triggering cloud BI reload or sending emails. |

---

## ✅ Section 2: Verification Protocol (How to Confirm Success)

Never infer success from a completion message alone. The process has three explicit terminal states:

```
                  ┌──────────────────────────────────────────────┐
                  │          3-POINT VERIFICATION GATE           │
                  └──────────────────────┬───────────────────────┘
                                         │
     ┌───────────────────────────────────┼───────────────────────────────────┐
     ▼                                   ▼                                   ▼
[1. CLI Terminal]              [2. Automated Email]           [3. Qlik Sense Evidence]
SUCCESS = exit 0               Subject matches terminal       Current-run verification
FAILED = exit 1                state and includes QA detail    timestamp and expected totals
UNVERIFIED = exit 2
```

1. **Terminal Console:** Trust only `ORCHESTRATION SUCCESS` with exit code `0`. Exit `1` means a blocking or downstream failure; exit `2` means the dashboard result could not be proven current.
2. **Automated Notification:** The subject is labeled `[SUCCESS]`, `[FAILED]`, or `[UNVERIFIED]` and includes the corresponding QA detail.
3. **Cloud Evidence:** Success requires a verification export created during the current run. Prior-run or missing files are never substituted.

---

## 🛠️ Section 3: Routine Maintenance Playbooks (Code-Free Administration)

The pipeline is intentionally decoupled into **code** (`core/`) and **configuration** (`config/`). Business analysts can execute routine operational updates without developer intervention.

### Playbook A: Adding a New Product Line or Therapy
* **When Needed:** Marketing launches a new therapy line, or an upstream system introduces a renamed product code (flagged as `Unmapped product: 'New_Product_Name'` in log files).
* **Step-by-Step Procedure:**
  1. Open [config/mappings.yaml](../config/mappings.yaml) in any standard text editor (VS Code, Notepad).
  2. Locate the `product_renames:` section.
  3. Add the new mapping in alphabetical order:
     ```yaml
     product_renames:
       "Source Naming Convention": "Standard Enterprise Reporting Category"
     ```
  4. Save the file and run: `python orchestrate_update.py --skip-downloads`.
  5. Confirm the warning banner disappears from `orchestrator.log`.

### Playbook B: Freezing a Strategic Forecast Baseline
* **When Needed:** Regional management approves an official planning baseline (e.g., *"H1-2026 Board Final"*), which must appear in cloud BI alongside live rolling estimates.
* **Step-by-Step Procedure:**
  1. Export the approved planning file from the forecasting portal.
  2. Drop the file into: `data/in/Forecast_Static_Versions/Forecast_H1_2026_Final.xlsx`.
     *(Note: The exact filename automatically becomes the scenario dimension name in BI dashboards).*
  3. Run: `python orchestrate_update.py --skip-downloads`.
  4. Open the cloud BI dashboard; the new version selector button will appear dynamically.

### Playbook C: Browser Session Refresh
* **When Needed:** Automated browser downloads fail with `TimeoutException` due to expired saved sign-in session.
* **Step-by-Step Procedure:**
  1. Run the interactive authenticator: `python scripts/setup_automation_profile.py`.
  2. A dedicated Chrome browser window will open displaying the enterprise sign-in portal.
  3. Log in with your standard identity verification flow.
  4. Close the browser window once the home landing page loads.
  5. The persistent profile is refreshed for another configured operational cycle.

---

## 🚨 Section 4: Incident Response & Troubleshooting Playbook

When an operational exception occurs, reference this structured diagnosis matrix before escalating:

| # | Observed Symptom | Primary Root Cause | Exact Resolution Procedure |
|---|:---|:---|:---|
| **1** | `TimeoutException` during download | Expired browser session or stale background browser process. | Kill orphan Chrome tasks in Task Manager; execute Playbook C above. |
| **2** | `PermissionError: [Errno 13]` | An Excel file in `data/` is locked by a user. | Close all local Excel windows; delete temporary `~$*.xlsx` lock files. |
| **3** | `[FAILED] ASP Checksum` | Qlik Sense data model totals differ from CSV. | Wait 2 minutes for BI indexing; re-run `orchestrate_update.py --skip-downloads`. |
| **4** | `KeyError: 'COLUMN_NAME'` | Upstream extract modified header format. | Compare raw extract headers with `core/schemas.py`; update column aliases. |
| **5** | `[FAILED] Check #7 Magnitude` | European comma/decimal format inversion. | Check source file for thousands formatting (`1.234,50` vs `1,234.50`); run regex parser. |
| **6** | `[FAILED] Check #3 Country Drop`| Unmapped territory or overseas code. | Add country code to `country_code_map` in `config/mappings.yaml`. |
| **7** | `[FAILED] Row Count Sanity` | Incomplete download or empty source file. | Inspect `data/in/`; confirm source extract file size is $>50\text{ KB}$. |
| **8** | `503 Service Unavailable` | Qlik Sense API undergoing service maintenance. | Inspect the appropriate service status page; retry execution once API restores. |
| **9** | `ModuleNotFoundError` | Virtual environment dependencies missing. | Execute `pip install -r requirements.txt` in terminal. |
| **10**| `UnicodeDecodeError` | Source CSV saved in non-standard encoding. | Re-save source extract in UTF-8 or update `read_csv(encoding='latin-1')`. |
| **11**| `[FAILED] Negative Units` | Large unapproved negative unit quantity. | Check `data/out/QA_Forecast_Plausibility.csv`; verify if return or formula error. |
| **12**| `Email Delivery Failure` | SMTP server routing timeout. | Pipeline outputs remain safe and intact in `data/out/`; verify SMTP credentials. |

---

## 🧪 Section 5: Engineering Rigor & Regression Verification

Before deploying any configuration or logic modification to production, operators run the automated stress testing suite:

```bash
pip install -r requirements-test.txt
python -m pytest -q
```

### Coverage Scope:
* **Numeric Normalization:** Handles US decimals, European comma decimals, apostrophe thousands separators (`1'234`), blanks, and dashes. Ambiguous values such as `1,234` require an explicit source policy and otherwise remain missing for validation.
* **Date & Quarter Consistency:** Validates quarterly tokens (`25Q1`), sequence continuity, and calendar year boundaries.
* **Dimensional Remapping:** 40+ therapy group variants, 21 country/export codes, and tax entity aliases.
* **Schema Validation:** Pandera typing guarantees that missing mandatory keys trigger explicit assertion messages rather than silent data corruption.
* **Publication Controls:** Failed QA reports preserve the last valid dataset; stale verification evidence produces an `UNVERIFIED` result.
* **Public Demo:** Both successful three-scenario generation and deliberately corrupted input are exercised end to end.
