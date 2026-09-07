"""
Safe Pipeline Test Environment

Creates sample test data and runs pipeline components in isolation
to validate AI logger integration without touching production files.

Usage:
    py test_pipeline_safe.py

This will:
    1. Create sample Excel/CSV files in data/test_sandbox/
    2. Run key pipeline functions with this data
    3. Display AI logger output showing what was captured
    4. Clean up test files (optional)
"""

import sys
import os
from pathlib import Path
import shutil
import tempfile

# Add project root
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np

# Import AI logger
from core.ai_logger import ai_log, ai_log_exception, ai_log_clear, ai_log_summary

# =============================================================================
# TEST DATA SETUP
# =============================================================================
SANDBOX_DIR = ROOT / "data" / "test_sandbox"


def create_sample_redbull_data() -> Path:
    """Create sample RedBull forecast data with some intentional issues."""

    # Mix of valid and problematic data
    data = {
        "Country": ["Belgium", "France", "Germany", "Tunisia", "Netherlands", "Belgium"],
        "Business Unit": ["CRM", "CRM", "CRM", "CRM", "CRM", "CRM"],
        "Product Name": [
            "IPG Single Chamber",      # Valid - should map
            "CRT Defibrillator",       # Issue: should be CRT-D (unmapped variant)
            "ICD Single Chamber",      # Valid
            "IPG Dual Chamber",        # Valid but Tunisia needs territory remap
            "ICM BIOMONITOR",          # Valid
            "IPG SC iLP Leadless NEW", # Issue: new variant not in mapping
        ],
        "Year": [2025, 2025, 2025, 2025, 2025, 2025],
        "BIO": [150, 200, 180, 50, 80, 0],    # Note: last row has 0 BIO
        "MKT": [500, 600, 550, 200, 250, 100],
    }

    df = pd.DataFrame(data)
    path = SANDBOX_DIR / "Test_RedBull_DL.xlsx"
    df.to_excel(path, index=False)
    print(f"  Created: {path.name} ({len(df)} rows)")
    return path


def create_sample_crm_data() -> Path:
    """Create sample CRM market tracker data."""

    data = {
        "Business Unit": ["CRM", "CRM", "CRM", "CRM", "CRM"],
        "Business Segment": ["IPG", "IPG", "ICD", "CRT", "ICM"],
        "Product Group": [
            "IPG Single Chamber",
            "IPG Dual Chamber",
            "ICD Single Chamber",
            "CRT-D",
            "ICM"
        ],
        "Product": [
            "IPG SINGLE CHAMBER CONVENTIONAL",
            "IPG DUAL CHAMBER CONVENTIONAL",
            "ICD SINGLE CHAMBER CONVENTIONAL",
            "CRT-D",
            "ICM"
        ],
        "Country Name": ["Belgium", "Belgium", "France", "Germany", "Belgium"],
        "Quarter": ["25Q1", "25Q1", "25Q1", "25Q1", "25Q1"],
        "Market Units": [450, 380, 520, 610, 0],  # Note: ICM has 0 units
        "Market Net Revenue (in K EUR)": [2250, 2280, 3120, 4270, 0],
        "ORG Units": [120, 95, 140, 165, 75],
        "ORG Net Revenue (in K EUR)": [600, 570, 840, 1155, 225],
        "Market ASP (in EUR)": [5000, 6000, 6000, 7000, 0],
        "ORG ASP (in EUR)": [5000, 6000, 6000, 7000, 3000],
    }

    df = pd.DataFrame(data)
    path = SANDBOX_DIR / "Test_CRM_DL.xlsx"
    df.to_excel(path, index=False, sheet_name="Sheet1")
    print(f"  Created: {path.name} ({len(df)} rows)")
    return path


def create_sample_mapping() -> Path:
    """Create sample product mapping file."""

    data = {
        "PRODUCT": [
            "IPG Single Chamber",
            "IPG Dual Chamber",
            "ICD Single Chamber",
            "CRT-D",
            "CRT-P",
            "ICM",
            "IPG SC iLP",
            "IPG DC iLP",
        ],
        "RB_PRODUCT_NAME": [
            "IPG Single Chamber",
            "IPG Dual Chamber",
            "ICD Single Chamber",
            "CRT-D",
            "CRT-P",
            "ICM BIOMONITOR",
            "IPG SC iLP",
            "IPG DC iLP",
        ],
    }

    df = pd.DataFrame(data)
    path = SANDBOX_DIR / "Test_Mapping.xlsx"
    df.to_excel(path, index=False)
    print(f"  Created: {path.name} ({len(df)} rows)")
    return path


# =============================================================================
# TEST RUNNER
# =============================================================================

def run_test_redbull_loader(redbull_path: Path, mapping_path: Path):
    """Test RedBull loader with sample data."""
    print("\n" + "-" * 50)
    print("TEST: RedBull Loader")
    print("-" * 50)

    try:
        # Load mapping
        map_df = pd.read_excel(mapping_path)
        mapping = dict(zip(map_df["RB_PRODUCT_NAME"], map_df["PRODUCT"]))
        print(f"  Loaded mapping with {len(mapping)} entries")

        # Import and run loader
        from integration.redbull_integration import load_redbull_forecast

        result = load_redbull_forecast(redbull_path, mapping)
        print(f"  [OK] Loaded {len(result.clean)} rows from RedBull file")

        # Show what products were found
        products = result.clean["product_group"].unique()
        print(f"  Products found: {list(products)}")

        return True

    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")
        ai_log_exception(e, context={"test": "redbull_loader", "file": str(redbull_path)})
        return False


def run_test_zero_units_detection(crm_path: Path):
    """Test detection of zero unit scenarios."""
    print("\n" + "-" * 50)
    print("TEST: Zero Units Detection")
    print("-" * 50)

    try:
        df = pd.read_excel(crm_path, sheet_name="Sheet1")

        # Find zero unit rows
        zero_mask = df["Market Units"] == 0
        zero_rows = df[zero_mask]

        if not zero_rows.empty:
            print(f"  [WARN] Found {len(zero_rows)} rows with zero Market Units:")
            for _, row in zero_rows.iterrows():
                country = row.get("Country Name", "Unknown")
                product = row.get("Product Group", "Unknown")
                ai_log("zero_units",
                       country=country,
                       product=product,
                       year=2025,
                       source="test_crm")
                print(f"    - {country} / {product}")
        else:
            print("  [OK] No zero unit rows found")

        return True

    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")
        ai_log_exception(e, context={"test": "zero_units_detection"})
        return False


def run_test_mapping_coverage(redbull_path: Path, mapping_path: Path):
    """Test mapping coverage - find unmapped products."""
    print("\n" + "-" * 50)
    print("TEST: Mapping Coverage")
    print("-" * 50)

    try:
        # Load RedBull products
        rb_df = pd.read_excel(redbull_path)
        rb_products = set(rb_df["Product Name"].unique())

        # Load mapping
        map_df = pd.read_excel(mapping_path)
        mapped_products = set(map_df["RB_PRODUCT_NAME"].unique())

        # Find gaps
        unmapped = rb_products - mapped_products

        if unmapped:
            print(f"  [WARN] Found {len(unmapped)} unmapped products:")
            for p in unmapped:
                ai_log("unmapped_product",
                       raw_value=p,
                       source="test_redbull",
                       file=str(redbull_path.name))
                print(f"    - '{p}'")
        else:
            print("  [OK] All products are mapped")

        return True

    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")
        ai_log_exception(e, context={"test": "mapping_coverage"})
        return False


def run_test_column_error_handling():
    """Test that KeyError exceptions are properly caught and logged."""
    print("\n" + "-" * 50)
    print("TEST: Column Error Handling")
    print("-" * 50)

    # Simulate a DataFrame missing expected column
    df = pd.DataFrame({"Country": ["BE", "FR"], "Units": [100, 200]})

    try:
        # This will fail - MKT column doesn't exist
        _ = df["MKT"]
        print("  [FAIL] Should have raised KeyError")
        return False

    except KeyError as e:
        suggestion = ai_log_exception(e, context={
            "test": "column_error",
            "available_columns": list(df.columns)
        })
        print(f"  [OK] KeyError caught and logged")
        if suggestion:
            print(f"  [OK] Fix suggestion: {suggestion.get('fix', 'N/A')[:60]}...")
        return True


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("SAFE PIPELINE TEST ENVIRONMENT")
    print("=" * 60)

    # Clear AI logger
    ai_log_clear()
    print("\n[SETUP] Cleared AI context log")

    # Create sandbox
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[SETUP] Created sandbox: {SANDBOX_DIR}")

    # Create test data
    print("\n[SETUP] Creating sample test data...")
    redbull_path = create_sample_redbull_data()
    crm_path = create_sample_crm_data()
    mapping_path = create_sample_mapping()

    # Run tests
    print("\n" + "=" * 60)
    print("RUNNING TESTS")
    print("=" * 60)

    results = {
        "Column Error Handling": run_test_column_error_handling(),
        "Mapping Coverage": run_test_mapping_coverage(redbull_path, mapping_path),
        "Zero Units Detection": run_test_zero_units_detection(crm_path),
        "RedBull Loader": run_test_redbull_loader(redbull_path, mapping_path),
    }

    # Show AI Logger summary
    print("\n" + "=" * 60)
    print("AI LOGGER SUMMARY")
    print("=" * 60)

    summary = ai_log_summary()
    print(f"\nTotal events logged: {summary['total_events']}")

    print("\nEvents by type:")
    for evt_type, count in summary['by_type'].items():
        print(f"  - {evt_type}: {count}")

    if summary.get('unmapped_products'):
        print(f"\nUnmapped products detected:")
        for p in summary['unmapped_products']:
            print(f"  - '{p}'")

    if summary.get('zero_units_cases'):
        print(f"\nZero unit cases:")
        for z in summary['zero_units_cases']:
            print(f"  - {z}")

    if summary.get('fix_suggestions'):
        print(f"\nFix Suggestions from AI Logger:")
        for sug in summary['fix_suggestions']:
            print(f"  [{sug['category']}] {sug['fix'][:70]}...")

    # Final results
    print("\n" + "=" * 60)
    passed = sum(results.values())
    total = len(results)
    print(f"TEST RESULTS: {passed}/{total} passed")
    for name, result in results.items():
        status = "[OK]" if result else "[FAIL]"
        print(f"  {status} {name}")
    print("=" * 60)

    # Cleanup prompt
    print(f"\nTest data created in: {SANDBOX_DIR}")
    print("You can delete this folder when done testing.")

    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
