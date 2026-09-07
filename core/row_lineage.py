"""
Row Lineage Utility - Generate unique keys for tracking data through the pipeline.

This module provides functions to create deterministic row identifiers that can
survive transformations and help trace duplicates back to their source.

Usage:
    from core.row_lineage import add_row_key, GRAIN_COLS
    
    df = add_row_key(df, source="CRM")  # Adds 'row_key' column
"""

import hashlib
import pandas as pd
import numpy as np

# Standard grain columns for the pipeline
# This defines what makes a row unique at the most detailed level
GRAIN_COLS_ACTUALS = [
    "Year", 
    "Quarter",
    "CC",
    "PRODUCT_GROUP",
    "PRODUCT",       # Sub-product granularity (e.g., 4mm/5mm vs 8mm/10mm)
    "EXPORT",        # Domestic/Export
    "Version",       # Actual Full, Actual Addressable, etc.
]

GRAIN_COLS_FORECAST = [
    "year",
    "Quarter",
    "cc",
    "product_group",
    "product_group_raw",  # Original product name before mapping
    "export_flag",
    "version",
]


def _hash_row(row_values: list) -> str:
    """Create a short hash from row values."""
    # Normalize: lowercase, strip, handle NaN
    normalized = []
    for v in row_values:
        if pd.isna(v):
            normalized.append("_null_")
        else:
            normalized.append(str(v).lower().strip())
    
    combined = "|".join(normalized)
    # Use first 12 chars of SHA256 for readability
    return hashlib.sha256(combined.encode()).hexdigest()[:12]


def add_row_key(df: pd.DataFrame, source: str, grain_cols: list = None) -> pd.DataFrame:
    """
    Add a unique row_key column to the DataFrame.
    
    The row_key is a deterministic hash of the grain columns + source,
    allowing you to track the same logical row through transformations.
    
    Args:
        df: DataFrame to add key to
        source: Source identifier (e.g., "CRM", "RedBull", "ICM")
        grain_cols: List of columns to use for key generation.
                   If None, auto-detects based on available columns.
    
    Returns:
        DataFrame with 'row_key' column added
    """
    df = df.copy()
    
    # Auto-detect grain columns if not provided
    if grain_cols is None:
        # Try actuals grain first
        if all(c in df.columns for c in ["Year", "Quarter", "PRODUCT_GROUP"]):
            grain_cols = [c for c in GRAIN_COLS_ACTUALS if c in df.columns]
        else:
            grain_cols = [c for c in GRAIN_COLS_FORECAST if c in df.columns]
    
    # Only use columns that exist
    available_cols = [c for c in grain_cols if c in df.columns]
    
    if not available_cols:
        print(f"[row_lineage] WARNING: No grain columns found, using index as key")
        df["row_key"] = [f"{source}_{i}" for i in range(len(df))]
        return df
    
    # Generate keys
    def make_key(row):
        values = [source] + [row[c] for c in available_cols]
        return _hash_row(values)
    
    df["row_key"] = df.apply(make_key, axis=1)
    
    # Add source column for clarity
    if "source" not in df.columns:
        df["source"] = source
    
    return df


def check_duplicates(df: pd.DataFrame, key_col: str = "row_key") -> dict:
    """
    Check for duplicate keys and return summary.
    
    Returns:
        dict with duplicate count and examples
    """
    if key_col not in df.columns:
        return {"error": f"Column {key_col} not found"}
    
    dupe_mask = df.duplicated(subset=[key_col], keep=False)
    dupe_count = dupe_mask.sum()
    
    if dupe_count == 0:
        return {"duplicates": 0, "status": "clean"}
    
    # Get examples
    dupe_groups = df[dupe_mask].groupby(key_col).size()
    examples = dupe_groups.head(5).to_dict()
    
    return {
        "duplicates": dupe_count,
        "unique_duplicate_keys": len(dupe_groups),
        "examples": examples,
        "status": "has_duplicates"
    }


def explain_key(row_key: str, df: pd.DataFrame) -> pd.DataFrame:
    """
    Find all rows matching a given row_key.
    Useful for debugging why duplicates exist.
    """
    if "row_key" not in df.columns:
        raise ValueError("DataFrame has no 'row_key' column")
    
    return df[df["row_key"] == row_key]


def compare_keys(df1: pd.DataFrame, df2: pd.DataFrame, key_col: str = "row_key") -> dict:
    """
    Compare keys between two DataFrames to find:
    - Keys only in df1
    - Keys only in df2
    - Keys in both
    """
    keys1 = set(df1[key_col].dropna())
    keys2 = set(df2[key_col].dropna())
    
    return {
        "only_in_df1": keys1 - keys2,
        "only_in_df2": keys2 - keys1,
        "in_both": keys1 & keys2,
        "df1_total": len(keys1),
        "df2_total": len(keys2),
    }
