import pytest
import pandas as pd
from pathlib import Path
import sys
import logging

# Setup paths and logger
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))
DATA_OUT = ROOT_DIR / "data" / "out"
FINAL_FLAT_FILE = DATA_OUT / "MarketData_Integrated_Flat.csv"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("DataQuality")

@pytest.fixture
def integrated_data():
    """Load the integrated flat file for testing."""
    if not FINAL_FLAT_FILE.exists():
        pytest.skip(f"Integrated file not found at {FINAL_FLAT_FILE}")
    
    # Load with EU decimal support if needed, but standard pandas read_csv usually expects dot.
    # The pipeline exports with sep=';' and decimal='.' (in RedBull integration)
    df = pd.read_csv(FINAL_FLAT_FILE, sep=";", decimal=".")
    return df

def test_required_columns_present(integrated_data):
    """Verify that all critical columns for Qlik consumption are present."""
    required_cols = [
        "Year", "Quarter", "CC", "PRODUCT_GROUP", 
        "Units", "Market Units", 
        "EXPORT", "Version", "SOURCE"
    ]
    missing = [c for c in required_cols if c not in integrated_data.columns]
    assert not missing, f"Missing required columns: {missing}"

def test_no_negative_units(integrated_data):
    """
    Ensure no rows have negative Units, unless they are acceptable adjustments.
    - MTE source allows negative units (adjustments/returns).
    - Other sources (CRM, RedBull) should generally be positive.
    """
    # Filter for negative units
    neg_units = integrated_data[integrated_data["Units"] < 0]
    
    if neg_units.empty:
        return
        
    # Check if any strictly forbidden negatives exist (Non-MTE)
    # We normalized SOURCE to upper case in pipeline, but let's be safe
    # Sources: "MTE", "CRM", "RedBull", "ICM Market", "ICM BIO"
    
    unexpected_neg = neg_units[~neg_units["SOURCE"].astype(str).str.upper().str.contains("MTE")]
    
    if not unexpected_neg.empty:
        msg = f"Found {len(unexpected_neg)} unexpected negative unit rows (Non-MTE).\n"
        msg += unexpected_neg[["Year", "Quarter", "CC", "PRODUCT_GROUP", "Units", "SOURCE"]].head(10).to_string()
        assert False, msg
        
    # If we are here, all negatives are MTE. Log them but pass.
    log.info(f"Accepted {len(neg_units)} negative unit rows from MTE (legitimate adjustments).")

def test_no_negative_market_units(integrated_data):
    """Ensure no rows have negative Market Units."""
    negative_mkt = integrated_data[integrated_data["Market Units"] < 0]
    assert negative_mkt.empty, \
        f"Found {len(negative_mkt)} rows with negative Market Units."

def test_version_consistency(integrated_data):
    """Ensure Version column is not empty/null."""
    assert not integrated_data["Version"].isnull().any(), "Found rows with null Version"
    assert (integrated_data["Version"] != "").all(), "Found rows with empty string Version"

def test_row_lineage_keys(integrated_data):
    """
    If row_key functionality is active, every row should have a row_key.
    We check for the column existence first.
    """
    if "row_key" in integrated_data.columns:
        null_keys = integrated_data[integrated_data["row_key"].isnull()]
        assert null_keys.empty, f"Found {len(null_keys)} rows with missing row_key"
        
        # Uniqueness check (if the flat file is supposed to be unique by row_key)
        # The flat file might aggregate, but let's check duplicates
        assert integrated_data["row_key"].is_unique, \
            f"Found duplicate row_keys in final export! Count: {len(integrated_data) - integrated_data['row_key'].nunique()}"

if __name__ == "__main__":
    # Allow running directly for quick check
    try:
        df = pd.read_csv(FINAL_FLAT_FILE, sep=";", decimal=".")
        print(f"Loaded {len(df)} rows. Running manual checks...")
        
        # Manual run of logic
        req = ["Year", "Quarter", "Units"]
        for c in req:
            if c not in df.columns: print(f"[MISSING] {c}")
            
        neg = df[df["Units"] < 0]
        if not neg.empty: 
            print(f"[FAIL] Found {len(neg)} negative unit rows.")
            print("Sample of negative rows:")
            cols_to_show = ["Year", "Quarter", "CC", "PRODUCT_GROUP", "REDBULL PRODUCT", "Units", "SOURCE"]
            # Filter cols that exist
            cols = [c for c in cols_to_show if c in df.columns]
            print(neg[cols].head(10).to_string())
        else:
            print("[PASS] No negative units.")
            
        print("Done.")
    except Exception as e:
        print(f"Failed: {e}")
