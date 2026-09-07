import pandas as pd
from dataclasses import dataclass
from pathlib import Path

# Mock RedBullFrames
@dataclass
class RedBullFrames:
    raw: pd.DataFrame
    clean: pd.DataFrame

# Import functions (simulate import by copying relevant parts or assuming filepath)
# But since I can't import easily from subdir without path setup, I'll copy the function logic here for the TEST or try to import if I can setup path.
# Setting up path is better.

import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))
from integration.redbull_integration import apply_manual_adjustments

def test_apply_adjustments():
    # Setup Data
    clean_data = pd.DataFrame({
        "version": ["Live", "Live", "H2'25 Final"],
        "year": [2025, 2025, 2025],
        "country": ["Germany", "France", "Germany"],
        "cc": ["DE", "FR", "DE"],
        "product_group": ["A", "A", "A"],
        "unit_owner": ["BIO", "BIO", "BIO"],
        "units": [100.0, 50.0, 200.0],
        "export_flag": ["DOMESTIC", "DOMESTIC", "DOMESTIC"]
    })
    
    frames = RedBullFrames(raw=pd.DataFrame(), clean=clean_data)
    
    # Setup Adjustments
    adjustments = pd.DataFrame({
        "Version": ["Live", "H2'25 Final"],
        "Year": [2025, 2025],
        "Country": ["Germany", "Germany"],
        "CC": ["DE", "DE"],
        "Product Group": ["A", "A"],
        "Export": ["DOMESTIC", "DOMESTIC"],
        "Unit Owner": ["BIO", "BIO"],
        "Units": [999.0, 888.0], # Overrides
        "Comment": ["Override 1", "Override 2"]
    })
    
    print("Initial Data:")
    print(clean_data)
    print("\nAdjustments:")
    print(adjustments)
    
    # Run
    result = apply_manual_adjustments(frames, adjustments)
    
    # Assertions
    res = result.clean
    print("\nResult Data:")
    print(res)
    
    # Check Live Germany A BIO
    val_live = res.loc[(res["version"]=="Live") & (res["country"]=="Germany"), "units"].values[0]
    assert val_live == 999.0, f"Expected 999.0 but got {val_live}"
    
    # Check H2'25 Final Germany A BIO (should be OVERWRITTEN by adjustment)
    val_static = res.loc[(res["version"]=="H2'25 Final") & (res["country"]=="Germany"), "units"].values[0]
    assert val_static == 888.0, f"Expected 888.0 but got {val_static}"

    # Check Unchanged (France)
    val_france = res.loc[(res["country"]=="France"), "units"].values[0]
    assert val_france == 50.0, f"Expected 50.0 but got {val_france}"

    print("\n✅ TEST PASSED: Manual Adjustments logic verified!")

if __name__ == "__main__":
    test_apply_adjustments()
