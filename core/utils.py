import pandas as pd
import numpy as np
from typing import Tuple, Optional

def num_smart(x):
    """
    Parse European or US-formatted numeric values to float safely.
    Logic:
    1. If already numeric, return float.
    2. Remove spaces.
    3. Detect format: If both '.' and ',' exist, or if the rightmost punctuation 
       is followed by exactly 2 digits (e.g. ,99), we infer the decimal separator.
    """
    if pd.isna(x):
        return np.nan
    if isinstance(x, (int, float, np.integer, np.floating)):
        return float(x)
    
    s = str(x).strip().replace(" ", "")
    if not s:
        return np.nan

    # Heuristic for US vs EU formats
    if s.count(".") == 1 and "," not in s:
        return float(s)
    if s.count(",") == 1 and "." not in s:
        return float(s.replace(",", "."))
        
    try:
        last_dot = s.rfind(".")
        last_comma = s.rfind(",")
        
        if last_dot > last_comma:
            s_clean = s.replace(",", "").replace("'", "").replace(" ", "")
            return float(s_clean)
        elif last_comma > last_dot:
            s_clean = s.replace(".", "").replace("'", "").replace(" ", "").replace(",", ".")
            return float(s_clean)
        
        return float(s.replace(",", "."))
    except (ValueError, TypeError):
        return np.nan

def quarter_to_numeric(quarter_str: str) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """Convert '21Q4' -> (2021, 4, 214)."""
    q = str(quarter_str).strip().upper()
    if len(q) >= 3 and "Q" in q:
        try:
            yy = int(q[:2])
            qq = int(q.split("Q")[-1])
            return 2000 + yy, qq, int(f"{yy:02d}{qq}")
        except (ValueError, IndexError):
            pass
    return np.nan, np.nan, np.nan

def canon_product(p: str) -> str:
    """Canonical product string (uppercase, stripped, standard dashes)."""
    if pd.isna(p):
        return p
    s = str(p).upper().strip().replace("–", "-").replace("—", "-")
    while "  " in s:
        s = s.replace("  ", " ")
    return s

def compute_asp_k(units, rev_k):
    """Compute ASP in EUR from units and Revenue in K EUR."""
    units = units.astype("float64")
    rev_k = rev_k.astype("float64")
    return np.where(units > 0, (rev_k * 1000.0) / units, np.nan)

def dedupe_columns(names):
    """Ensure unique column names by appending .1, .2 etc."""
    seen = {}
    out = []
    for name in names:
        n = name
        if n in seen:
            seen[n] += 1
            n = f"{n}.{seen[n]}"
        else:
            seen[n] = 0
        out.append(n)
    return out

def assert_columns(df: pd.DataFrame, required_cols: list, context: str):
    """Assert that a DataFrame has the required columns."""
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        found = df.columns.tolist()
        raise AssertionError(f"{context}: missing {missing}\nFound columns: {found}")

def assert_not_empty(df: pd.DataFrame, context: str):
    """Assert that a DataFrame is not empty."""
    if df.empty:
        raise AssertionError(f"{context}: empty DataFrame")
