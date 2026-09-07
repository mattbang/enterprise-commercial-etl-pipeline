try:
    import pandera.pandas as pa
    from pandera.pandas import Check, Column, DataFrameSchema
except ImportError:
    import pandera as pa
    from pandera import Check, Column, DataFrameSchema
import yaml
from pathlib import Path

# --- LOAD CONFIG FOR VALIDATION ---
try:
    # Resolve root relative to this file (core/schemas.py -> root)
    ROOT_DIR = Path(__file__).resolve().parent.parent
    CONFIG_PATH = ROOT_DIR / "config" / "mappings.yaml"
    
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        CFG = yaml.safe_load(f)
        
    VALID_COUNTRIES = set()
    if "countries" in CFG:
        for c in CFG["countries"]:
            if "CRM_COUNTRY_NAME" in c: VALID_COUNTRIES.add(c["CRM_COUNTRY_NAME"])
            if "VI_COUNTRY_NAME" in c: VALID_COUNTRIES.add(c["VI_COUNTRY_NAME"])
            
    VALID_TERRITORIES = set(CFG.get("territory_map", {}).keys())
    
    # Input can contain territories that will be remapped later
    ALL_VALID_INPUTS = VALID_COUNTRIES | VALID_TERRITORIES
    
except Exception as e:
    print(f"[Schemas] WARN: Could not load mappings.yaml for validation: {e}")
    VALID_COUNTRIES = set()
    ALL_VALID_INPUTS = set()

# Helper to create check only if we have data
def isin_check(allowed_set):
    if not allowed_set:
        return None # No check if config failed
    return Check.isin(allowed_set)

# Using DataFrameSchema directly for compatibility
InputSchemaCrm = DataFrameSchema({
    "Business Unit": Column(str, required=True),
    "Business Segment": Column(str, required=True),
    "Country Name": Column(str, checks=isin_check(ALL_VALID_INPUTS), required=True),
    "Quarter": Column(str, checks=Check.str_matches(r"^\d{2}Q[1-4]$"), nullable=True, required=False),
    "Market Units": Column(float, nullable=True, coerce=True, required=False),
}, strict=False) # strict=False allows extra columns

OutputSchema = DataFrameSchema({
    "COUNTRY_NAME": Column(str, checks=isin_check(VALID_COUNTRIES)),
    "Year": Column(int, checks=[Check.ge(2000), Check.le(2050)]),
    "Quarter": Column(str, checks=Check.str_matches(r"^\d{2}Q[1-4]$")),
    "Market Units": Column(float, checks=Check.ge(0), coerce=True),
}, strict=False)
