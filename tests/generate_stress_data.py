"""
Stress Test Data Generator
==========================
Creates synthetic Excel source files injected with every known edge case,
formatting quirk, and mapping-boundary scenario from the pipeline's history.

Usage:
    python tests/generate_stress_data.py          # Generate all files
    python tests/generate_stress_data.py --clean  # Delete previous sandbox data

Files are written to data/test_sandbox/stress/ — production data is never touched.
"""

import sys
import shutil
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
STRESS_DIR = ROOT / "data" / "test_sandbox" / "stress"


# =============================================================================
# CRM SOURCE  (Market Tracker CRM DL.xlsx) — Sheet1
# =============================================================================
def generate_crm(dest: Path) -> Path:
    """Generate CRM Market Tracker with comprehensive edge cases."""

    rows = [
        # --- Happy-path rows (main countries) ---
        ("CRM", "IPG", "IPG Single Chamber", "IPG SINGLE CHAMBER CONVENTIONAL", "Belgium",       "25Q1", 450, 2250, 120, 600, 5000, 5000),
        ("CRM", "IPG", "IPG Dual Chamber",   "IPG DUAL CHAMBER CONVENTIONAL",   "France",        "25Q1", 380, 2280, 95,  570, 6000, 6000),
        ("CRM", "ICD", "ICD Single Chamber",  "ICD SINGLE CHAMBER CONVENTIONAL", "Spain",         "25Q2", 520, 3120, 140, 840, 6000, 6000),
        ("CRM", "CRT", "CRT-D",               "CRT DEFIBRILLATORS",              "Italy",         "25Q2", 610, 4270, 165, 1155,7000, 7000),
        ("CRM", "ICM", "ICM",                 "ICM & OTHER DIAGNOSTICS",         "United Kingdom","25Q3", 200, 600,  75,  225, 3000, 3000),
        ("CRM", "IPG", "IPG Single Chamber", "IPG SINGLE CHAMBER CONVENTIONAL", "Switzerland",   "25Q3", 310, 1860, 82,  492, 6000, 6000),
        ("CRM", "IPG", "IPG Single Chamber", "IPG SINGLE CHAMBER CONVENTIONAL", "Portugal",      "25Q4", 190, 950,  55,  275, 5000, 5000),
        ("CRM", "ICD", "ICD Dual Chamber",    "ICD DUAL CHAMBER",                "Netherlands",   "25Q4", 410, 2870, 105, 735, 7000, 7000),
        ("CRM", "IPG", "IPG Single Chamber", "IPG SINGLE CHAMBER CONVENTIONAL", "Canada",        "26Q1", 600, 3000, 160, 800, 5000, 5000),

        # --- Edge #1: IRELAND → should map to CC=IE, BIOS=5130 ---
        ("CRM", "IPG", "IPG Single Chamber", "IPG SINGLE CHAMBER CONVENTIONAL", "Ireland",       "25Q1", 85,  425,  22,  110, 5000, 5000),

        # --- Edge #2: Export territory names (should remap to France) ---
        ("CRM", "IPG", "IPG Dual Chamber",   "IPG DUAL CHAMBER CONVENTIONAL",   "Tunisia",       "25Q2", 30,  180,  8,   48,  6000, 6000),
        ("CRM", "ICD", "ICD Single Chamber",  "ICD SINGLE CHAMBER CONVENTIONAL", "Algeria",       "25Q2", 25,  150,  5,   30,  6000, 6000),
        ("CRM", "CRT", "CRT-P",               "CRT PACEMAKER",                   "Morocco",       "25Q3", 15,  105,  3,   21,  7000, 7000),
        ("CRM", "IPG", "IPG Single Chamber", "IPG SINGLE CHAMBER CONVENTIONAL", "Senegal",       "25Q3", 5,   25,   1,   5,   5000, 5000),
        ("CRM", "IPG", "IPG Single Chamber", "IPG SINGLE CHAMBER CONVENTIONAL", "Aruba",         "25Q3", 3,   15,   1,   5,   5000, 5000),
        ("CRM", "IPG", "IPG Single Chamber", "IPG SINGLE CHAMBER CONVENTIONAL", "Congo",         "25Q4", 4,   20,   1,   5,   5000, 5000),
        ("CRM", "IPG", "IPG Single Chamber", "IPG SINGLE CHAMBER CONVENTIONAL", "Guadeloupe",    "25Q4", 6,   30,   2,   10,  5000, 5000),
        ("CRM", "IPG", "IPG Single Chamber", "IPG SINGLE CHAMBER CONVENTIONAL", "Rwanda",        "25Q1", 2,   10,   0,   0,   5000, 0),

        # --- Edge #3: Greece (BIOS="Error" sentinel) ---
        ("CRM", "IPG", "IPG Single Chamber", "IPG SINGLE CHAMBER CONVENTIONAL", "Greece",        "25Q1", 40,  200,  10,  50,  5000, 5000),

        # --- Edge #4: Business Unit = VI (must be filtered out) ---
        ("VI",  "IPG", "IPG Single Chamber", "IPG SINGLE CHAMBER CONVENTIONAL", "Belgium",       "25Q1", 999, 9999, 999, 9999,5000, 5000),

        # --- Edge #5: EU-format numbers stored as strings ---
        ("CRM", "IPG", "IPG Single Chamber", "IPG SINGLE CHAMBER CONVENTIONAL", "Belgium",       "25Q2", "1.234", "6.170,00", "328", "1.640,00", "5.000", "5.000"),

        # --- Edge #6: Dash/blank/space numeric placeholders ---
        ("CRM", "ICM", "ICM",                 "ICM & OTHER DIAGNOSTICS",         "France",        "25Q4", "-",  "--", 0,   0,    0,     0),
        ("CRM", "ICM", "ICM",                 "ICM & OTHER DIAGNOSTICS",         "Spain",         "25Q4", " ",  "",   0,   0,    0,     0),

        # --- Edge #7: Mixed case product names ---
        ("CRM", "IPG", "ipg single chamber",  "ipg single CHAMBER conventional", "Belgium",       "25Q3", 100, 500,  25,  125, 5000, 5000),

        # --- Edge #8: Zero Market Units with non-zero BIO (ASP edge) ---
        ("CRM", "ICM", "ICM",                 "ICM & OTHER DIAGNOSTICS",         "Belgium",       "25Q1", 0,   0,    75,  225, 0,    3000),

        # --- Edge #9: Negative Units (legitimate MTE adjustments) ---
        ("CRM", "IPG", "IPG Single Chamber", "IPG SINGLE CHAMBER CONVENTIONAL", "France",        "25Q3", 500, 2500, -15, -75,  5000, 5000),
    ]

    cols = [
        "Business Unit", "Business Segment", "Product Group", "Product",
        "Country Name", "Quarter",
        "Market Units", "Market Net Revenue (in K EUR)",
        "ORG Units", "ORG Net Revenue (in K EUR)",
        "Market ASP (in EUR)", "ORG ASP (in EUR)",
    ]

    df = pd.DataFrame(rows, columns=cols)
    path = dest / "Market Tracker CRM DL.xlsx"
    df.to_excel(path, index=False, sheet_name="Sheet1")
    print(f"  [OK] CRM: {path.name} ({len(df)} rows)")
    return path


# =============================================================================
# ICM MARKET SOURCE  (ICM_Market_DL.xlsx) — Sheet1
# =============================================================================
def generate_icm_market(dest: Path) -> Path:
    """Generate ICM Market data with edge cases."""

    rows = [
        # Standard ICM rows
        ("BE", "CRM incl. EP", "Diagnostics", "ICM & Other Diagnostics", 2025, 800, 2400000),
        ("FR", "CRM incl. EP", "Diagnostics", "ICM & Other Diagnostics", 2025, 650, 1950000),
        ("GB", "CRM incl. EP", "Diagnostics", "ICM & Other Diagnostics", 2025, 1200, 3600000),
        ("ES", "CRM incl. EP", "Diagnostics", "ICM & Other Diagnostics", 2025, 500, 1500000),
        ("IT", "CRM incl. EP", "Diagnostics", "ICM & Other Diagnostics", 2025, 700, 2100000),

        # Edge: CC needing fix (UK → GB, EL → GR, IR → GB)
        ("UK", "CRM incl. EP", "Diagnostics", "ICM & Other Diagnostics", 2025, 50,  150000),
        ("EL", "CRM incl. EP", "Diagnostics", "ICM & Other Diagnostics", 2025, 40,  120000),

        # Edge: Non-ICM row (should be filtered OUT)
        ("BE", "CRM incl. EP", "Brady",       "Brady Pacemaker",         2025, 9999, 9999000),
        ("FR", "CRM incl. EP", "Tachy",       "Tachy Defibrillator",     2025, 8888, 8888000),

        # Edge: EU-format number strings
        ("PT", "CRM incl. EP", "Diagnostics", "ICM & Other Diagnostics", 2025, "1.234", "3.702.000"),

        # Edge: Future year
        ("BE", "CRM incl. EP", "Diagnostics", "ICM & Other Diagnostics", 2026, 900, 2700000),
    ]

    cols = [
        "Country Code", "Business Unit", "Product Segment",
        "Product Category", "Year", "Market Units", "Market Net Revenue",
    ]

    df = pd.DataFrame(rows, columns=cols)
    path = dest / "ICM_Market_DL.xlsx"
    df.to_excel(path, index=False, sheet_name="Sheet1")
    print(f"  [OK] ICM Market: {path.name} ({len(df)} rows)")
    return path


# =============================================================================
# ICM BIO SOURCE  (ICM_BIO_DL.xlsx) — Sheet1
# =============================================================================
def generate_icm_bio(dest: Path) -> Path:
    """Generate ICM BIO data with edge cases."""

    rows = [
        # Standard rows
        ("ICM & Other Diagnostics", "BE", 2025, "Q1", 75, 225000),
        ("ICM & Other Diagnostics", "BE", 2025, "Q2", 80, 240000),
        ("ICM & Other Diagnostics", "FR", 2025, "Q1", 60, 180000),
        ("ICM & Other Diagnostics", "GB", 2025, "Q1", 110, 330000),

        # Edge: CC needing fix
        ("ICM & Other Diagnostics", "UK", 2025, "Q2", 15, 45000),

        # Edge: Non-ICM row (should be filtered)
        ("Brady Pacemaker",         "BE", 2025, "Q1", 9999, 9999000),

        # Edge: Quarter beyond likely CRM max (e.g. 26Q4 if CRM only goes to 26Q1)
        ("ICM & Other Diagnostics", "BE", 2026, "Q4", 100, 300000),

        # Edge: All-NaN numeric row
        ("ICM & Other Diagnostics", "ES", 2025, "Q3", np.nan, np.nan),
    ]

    cols = [
        "Product Category", "Country Code", "Year", "Quarter",
        "Units", "Net Revenue EUR",
    ]

    df = pd.DataFrame(rows, columns=cols)
    path = dest / "ICM_BIO_DL.xlsx"
    df.to_excel(path, index=False, sheet_name="Sheet1")
    print(f"  [OK] ICM BIO: {path.name} ({len(df)} rows)")
    return path


# =============================================================================
# REDBULL SOURCE  (RedBull DL.xlsx) — NEW FORMAT with BIO/MKT columns
# =============================================================================
def generate_redbull(dest: Path) -> Path:
    """Generate RedBull forecast data with comprehensive edge cases."""

    rows = [
        # --- Happy-path (main countries, standard products) ---
        ("Belgium",       "CRM", "IPG Single Chamber",                   2025, 150, 500),
        ("France",        "CRM", "IPG Dual Chamber",                     2025, 200, 600),
        ("Spain",         "CRM", "ICD Single Chamber",                   2025, 180, 550),
        ("Italy",         "CRM", "CRT Defibrillator",                    2025, 165, 610),
        ("United Kingdom","CRM", "ICM & Other Diagnostics",              2025, 80,  250),
        ("Switzerland",   "CRM", "CRT Pacemaker",                        2025, 90,  300),
        ("Netherlands",   "CRM", "ICD Dual Chamber",                     2025, 105, 410),
        ("Portugal",      "CRM", "IPG Single Chamber",                   2025, 55,  190),
        ("Canada",        "CRM", "IPG Single Chamber",                   2025, 160, 600),

        # --- Edge: ALL product_renames variants ---
        ("Belgium",       "CRM", "IPG SINGLE CHAMBER",                   2025, 10,  30),   # uppercase
        ("Belgium",       "CRM", "IPG SC Conventional",                  2025, 10,  30),   # already canonical
        ("Belgium",       "CRM", "IPG SC",                               2025, 10,  30),   # short form
        ("Belgium",       "CRM", "Single Chamber IPG - Leadless",        2025, 0,   20),   # leadless (BIO should be zeroed)
        ("Belgium",       "CRM", "SINGLE CHAMBER IPG - LEADLESS",        2025, 0,   20),   # uppercase leadless
        ("Belgium",       "CRM", "IPG Leadless",                         2025, 0,   15),   # generic leadless
        ("Belgium",       "CRM", "IPG SC Leadless",                      2025, 0,   15),   # canonical leadless
        ("Belgium",       "CRM", "IPG SC iLP",                           2025, 0,   10),   # iLP mapping
        ("Belgium",       "CRM", "IPG DUAL CHAMBER",                     2025, 10,  30),
        ("Belgium",       "CRM", "IPG DC Conventional",                  2025, 10,  30),
        ("Belgium",       "CRM", "IPG DC",                               2025, 10,  30),
        ("Belgium",       "CRM", "Dual Chamber IPG - Leadless",          2025, 0,   20),
        ("Belgium",       "CRM", "DUAL CHAMBER IPG - LEADLESS",          2025, 0,   20),
        ("Belgium",       "CRM", "IPG DC Leadless",                      2025, 0,   15),
        ("Belgium",       "CRM", "IPG DC iLP",                           2025, 0,   10),
        ("Belgium",       "CRM", "ICD SINGLE CHAMBER",                   2025, 10,  30),
        ("Belgium",       "CRM", "ICD SC Conventional",                  2025, 10,  30),
        ("Belgium",       "CRM", "ICD SC",                               2025, 10,  30),
        ("Belgium",       "CRM", "S-ICD",                                2025, 0,   25),
        ("Belgium",       "CRM", "ICD SC - Non-Transvenous",             2025, 0,   25),
        ("Belgium",       "CRM", "ICD SINGLE CHAMBER NON-TRANSVENOUS",   2025, 0,   25),
        ("Belgium",       "CRM", "ICD Single Chamber Non-Transvenous",   2025, 0,   25),
        ("Belgium",       "CRM", "ICD SC - Non-Transv.",                 2025, 0,   25),
        ("Belgium",       "CRM", "ICD SC Non-Transv.",                   2025, 0,   25),
        ("Belgium",       "CRM", "ICD SC + Non-Trans.",                  2025, 10,  30),   # combined
        ("Belgium",       "CRM", "ICD SC + S-ICD",                       2025, 10,  30),
        ("Belgium",       "CRM", "ICD DUAL CHAMBER",                     2025, 10,  30),
        ("Belgium",       "CRM", "ICD DC Conventional",                  2025, 10,  30),
        ("Belgium",       "CRM", "ICD DC",                               2025, 10,  30),
        ("Belgium",       "CRM", "CRT Defibrillators",                   2025, 10,  30),
        ("Belgium",       "CRM", "CRT DEFIBRILLATOR",                    2025, 10,  30),
        ("Belgium",       "CRM", "CRT DEFIBRILLATORS",                   2025, 10,  30),
        ("Belgium",       "CRM", "CRT - D",                              2025, 10,  30),
        ("Belgium",       "CRM", "CRT – D",                              2025, 10,  30),   # em-dash
        ("Belgium",       "CRM", "CRT - DEFIBRILLATORS",                 2025, 10,  30),
        ("Belgium",       "CRM", "CRT Pacemakers",                       2025, 10,  30),
        ("Belgium",       "CRM", "CRT PACEMAKER",                        2025, 10,  30),
        ("Belgium",       "CRM", "CRT PACEMAKERS",                       2025, 10,  30),
        ("Belgium",       "CRM", "CRT - P",                              2025, 10,  30),
        ("Belgium",       "CRM", "CRT – P",                              2025, 10,  30),   # em-dash
        ("Belgium",       "CRM", "CRT – P ",                             2025, 10,  30),   # trailing space + em-dash
        ("Belgium",       "CRM", "CRT - PACEMAKERS",                     2025, 10,  30),
        ("Belgium",       "CRM", "ICM and Other Diagnostics",            2025, 10,  30),
        ("Belgium",       "CRM", "ICM & OTHER DIAGNOSTICS",              2025, 10,  30),
        ("Belgium",       "CRM", "ICM",                                   2025, 10,  30),

        # --- Edge: Unmapped product (should be flagged but not crash) ---
        ("Belgium",       "CRM", "BRAND NEW PRODUCT 2026",               2025, 50,  100),

        # --- Edge: EU-format numbers as strings ---
        ("France",        "CRM", "IPG Single Chamber",                   2025, "1'234", "5'678"),

        # --- Edge: Dash/blank numeric placeholders ---
        ("Spain",         "CRM", "IPG Single Chamber",                   2025, "-",   "--"),

        # --- Edge: Territory countries (should remap) ---
        ("Tunisia",       "CRM", "IPG Single Chamber",                   2025, 8,   30),
        ("Congo",         "CRM", "IPG Single Chamber",                   2025, 4,   20),
        ("Aruba",         "CRM", "IPG Single Chamber",                   2025, 3,   15),

        # --- Edge: Ireland (CC=IE → United Kingdom) ---
        ("Ireland",       "CRM", "IPG Single Chamber",                   2025, 22,  85),

        # --- Edge: Product with leading/trailing whitespace ---
        ("Belgium",       "CRM", "  IPG Single Chamber  ",               2025, 10,  30),

        # --- Edge: Leadless product with BIO > 0 (should be zeroed) ---
        ("France",        "CRM", "IPG SC Leadless",                       2025, 999, 500),
    ]

    cols = ["Country", "Business Unit", "Product Name", "Year", "BIO", "MKT"]
    df = pd.DataFrame(rows, columns=cols)

    path = dest / "RedBull DL.xlsx"
    df.to_excel(path, index=False)
    print(f"  [OK] RedBull: {path.name} ({len(df)} rows)")
    return path


# =============================================================================
# UNCONVENTIONAL MARKET SOURCE  (Unconventional_Market.xlsx) — Sheet: DATA
# =============================================================================
def generate_unconventional(dest: Path) -> Path:
    """Generate Unconventional Market data with edge cases."""

    rows = [
        # Standard S-ICD rows
        ("25Q1", "BE", "S-ICD",                               50,  350),
        ("25Q2", "FR", "ICD Single Chamber Non-Transvenous",  30,  210),

        # Standard ILP rows
        ("25Q1", "BE", "Single Chamber IPG - Leadless",       40,  280),
        ("25Q2", "ES", "Dual Chamber IPG - Leadless",         20,  140),
        ("25Q3", "IT", "IPG Leadless",                        25,  175),

        # Edge: CC needing fix
        ("25Q1", "UK", "S-ICD",                               15,  105),
        ("25Q2", "EL", "S-ICD",                               10,  70),
        ("25Q3", "IE", "Single Chamber IPG - Leadless",       5,   35),
        ("25Q4", "IR", "S-ICD",                               8,   56),

        # Edge: Product matching multiple patterns (should use first)
        ("25Q1", "BE", "ILP SC Leadless NEW 2026",            12,  84),

        # Edge: Large values (potential overcap scenario)
        ("25Q1", "PT", "S-ICD",                               5000, 35000),

        # Edge: EU-format numbers
        ("25Q2", "NL", "S-ICD",                               "1.234", "8.638,00"),
    ]

    cols = ["Quarter", "CC", "Product", "Market Units", "Market Net Revenue (in K EUR)"]
    df = pd.DataFrame(rows, columns=cols)

    path = dest / "Unconventional_Market.xlsx"
    df.to_excel(path, index=False, sheet_name="DATA")
    print(f"  [OK] Unconventional: {path.name} ({len(df)} rows)")
    return path


# =============================================================================
# MAPPING FILE  (map.market.ACCOUNTPOTENTIAL_ASPMSOVERVIEW.xlsx)
# =============================================================================
def generate_rb_mapping(dest: Path) -> Path:
    """Generate RedBull product mapping file."""

    rows = [
        ("IPG Single Chamber",                  "IPG Single Chamber"),
        ("IPG Dual Chamber",                    "IPG Dual Chamber"),
        ("ICD Single Chamber",                  "ICD Single Chamber"),
        ("ICD Dual Chamber",                    "ICD Dual Chamber"),
        ("CRT-D",                               "CRT Defibrillator"),
        ("CRT-P",                               "CRT Pacemaker"),
        ("ICM",                                  "ICM & Other Diagnostics"),
        ("IPG SC iLP",                           "IPG SC iLP"),
        ("IPG DC iLP",                           "IPG DC iLP"),
        ("S-ICD",                                "S-ICD"),
        ("IPG SC Leadless",                      "Single Chamber IPG - Leadless"),
        ("IPG DC Leadless",                      "Dual Chamber IPG - Leadless"),
        ("ICD SC S-ICD",                         "ICD Single Chamber Non-Transvenous"),
    ]

    df = pd.DataFrame(rows, columns=["PRODUCT", "RB_PRODUCT_NAME"])
    path = dest / "map.market.ACCOUNTPOTENTIAL_ASPMSOVERVIEW.xlsx"
    df.to_excel(path, index=False, sheet_name="RBMAP")
    print(f"  [OK] RB Mapping: {path.name} ({len(df)} rows)")
    return path


# =============================================================================
# EXPORT MAP  (map_COUNTRY_EXPORT.xlsx) — Sheet: COUNTRY_EXPORT
# =============================================================================
def generate_export_map(dest: Path) -> Path:
    """Generate Country Export mapping file."""

    rows = [
        ("Belgium",        "DOMESTIC"),
        ("France",         "DOMESTIC"),
        ("Spain",          "DOMESTIC"),
        ("Italy",          "DOMESTIC"),
        ("United Kingdom", "DOMESTIC"),
        ("Great Britain",  "DOMESTIC"),
        ("Switzerland",    "DOMESTIC"),
        ("Portugal",       "DOMESTIC"),
        ("Canada",         "DOMESTIC"),
        ("Netherlands",    "DOMESTIC"),
        ("Ireland",        "DOMESTIC"),
        ("Greece",         "DOMESTIC"),
        ("Tunisia",        "EXPORT"),
        ("Algeria",        "EXPORT"),
        ("Morocco",        "EXPORT"),
        ("Marocco",        "EXPORT"),
        ("Senegal",        "EXPORT"),
        ("Aruba",          "EXPORT"),
        ("Congo",          "EXPORT"),
        ("Guadeloupe",     "EXPORT"),
        ("Haiti",          "EXPORT"),
        ("Martinique",     "EXPORT"),
        ("Rwanda",         "EXPORT"),
    ]

    df = pd.DataFrame(rows, columns=["COUNTRY", "EXPORT"])
    path = dest / "map_COUNTRY_EXPORT.xlsx"
    df.to_excel(path, index=False, sheet_name="COUNTRY_EXPORT")
    print(f"  [OK] Export Map: {path.name} ({len(df)} rows)")
    return path


# =============================================================================
# MAIN
# =============================================================================
def generate_all(dest: Path | None = None) -> dict:
    """Generate all stress-test source files. Returns dict of {name: Path}."""
    dest = STRESS_DIR if dest is None else Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    # RedBull sub-directories
    (dest / "RedBull Static Versions").mkdir(exist_ok=True)
    (dest / "RedBull Manual Adjustments").mkdir(exist_ok=True)

    paths = {
        "crm":              generate_crm(dest),
        "icm_market":       generate_icm_market(dest),
        "icm_bio":          generate_icm_bio(dest),
        "redbull":          generate_redbull(dest),
        "unconventional":   generate_unconventional(dest),
        "rb_mapping":       generate_rb_mapping(dest),
        "export_map":       generate_export_map(dest),
    }

    print(f"\n  All stress data generated in: {dest}")
    return paths


def clean():
    """Remove the stress sandbox."""
    if STRESS_DIR.exists():
        shutil.rmtree(STRESS_DIR)
        print(f"  Cleaned: {STRESS_DIR}")
    else:
        print(f"  Nothing to clean at {STRESS_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate stress-test data")
    parser.add_argument("--clean", action="store_true", help="Remove previous sandbox data")
    args = parser.parse_args()

    if args.clean:
        clean()
    else:
        print("=" * 60)
        print("STRESS TEST DATA GENERATOR")
        print("=" * 60)
        generate_all()
        print("=" * 60)
        print("Done.")
