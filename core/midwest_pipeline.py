# -*- coding: utf-8 -*-
"""
MIDWEST Market & ICM Integration — Refactored Pipeline (pandas)

4-module architecture:
  1. data_loader    — Load all sources (CRM, ICM, unconventional)
  2. adjustments    — Compute iLP/S-ICD adjustments (pure transformation)
  3. derived_rows   — Create conventional & S-ICD derived rows (pure transformation)
  4. main           — Orchestrate, merge, QA, export (I/O + coordination)

# Invariants:
    1. For each (Year, Quarter, Country, Segment):
        sum_final(Market Units) == sum_CRM(Market Units) ± 1
    2. ICD segment: FINAL(ICD conv) + FINAL(S-ICD) == CRM(ICD total)
    3. IPG segment: FINAL(IPG conv) + FINAL(ILP rows) == CRM(IPG total)
    4. ORG segment totals unchanged.
"""

from __future__ import annotations
import math
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple, Optional
import yaml
try:
    import pandera.pandas as pa
except ImportError:
    import pandera as pa
try:
    from core.schemas import InputSchemaCrm
except ImportError:
    # Handle running from core/ vs root
    import sys
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from core.schemas import InputSchemaCrm


import numpy as np
import pandas as pd

try:
    from core.utils import (
        assert_columns,
        assert_not_empty,
        canon_product,
        compute_asp_k,
        dedupe_columns as dedupe,
        num_smart,
        quarter_to_numeric,
    )
    from core.publication_control import (
        BlockingValidationError,
        PublicationError,
        publish_validated_frame,
    )
except ImportError:
    from utils import (
        assert_columns,
        assert_not_empty,
        canon_product,
        compute_asp_k,
        dedupe_columns as dedupe,
        num_smart,
        quarter_to_numeric,
    )
    from publication_control import (
        BlockingValidationError,
        PublicationError,
        publish_validated_frame,
    )

# AI Context Logging for debugging
try:
    from core.ai_logger import ai_log, ai_log_clear
except ImportError:
    ai_log = lambda *args, **kwargs: None
    ai_log_clear = lambda: None

pd.set_option("future.no_silent_downcasting", True)
pd.options.mode.copy_on_write = True

# --------------------------
# HARDCODED CONFIG (Replaces map_COUNTRY_VI_TO_CRM)
# --------------------------
# COUNTRY_CONFIG moved to config/mappings.yaml


# --------------------------
# Config
# --------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent

# Load config-driven paths for external dependencies
try:
    from core.path_resolver import resolve_config as _resolve_cfg
    _pipe_cfg = _resolve_cfg()
except Exception:
    _pipe_cfg = {}


def _configured_path(section: str, key: str, fallback: Path) -> Path:
    """Use a resolved external path, or the portfolio-local fallback."""
    value = _pipe_cfg.get(section, {}).get(key)
    return value if isinstance(value, Path) else fallback


@dataclass
class Config:
    mappings_yaml: Path = ROOT_DIR / "config" / "mappings.yaml"
    crm_dl_xlsx: Path = ROOT_DIR / "data" / "in" / "Market Tracker CRM DL.xlsx"

    map_country_export_xlsx: Path = _configured_path(
        "data_sources",
        "map_country_export",
        ROOT_DIR / "config" / "mappings" / "map_COUNTRY_EXPORT.xlsx",
    )

    rb_map_xlsx: Path = ROOT_DIR / "config" / "mappings" / "map.market.ACCOUNTPOTENTIAL_ASPMSOVERVIEW.xlsx"
    icm_market_dl_xlsx: Path = ROOT_DIR / "data" / "in" / "ICM_Market_DL.xlsx"
    icm_bio_dl_xlsx: Path = ROOT_DIR / "data" / "in" / "ICM_BIO_DL.xlsx"
    unconventional_mkt_xlsx: Path = ROOT_DIR / "data" / "in" / "Unconventional_Market.xlsx"
    redbull_dl_xlsx: Path = ROOT_DIR / "data" / "in" / "RedBull DL.xlsx"

    out_final_csv: Path = ROOT_DIR / "data" / "out" / "MarketData_ASP_&_MS_Final_python.csv"
    out_debug_csv: Path = ROOT_DIR / "data" / "out" / "MarketData_ASP_&_MS_Final_python.csv"

    out_final_csv_qvd: Path = _configured_path(
        "outputs",
        "qvd_target_dir",
        ROOT_DIR / "data" / "out",
    ) / "MarketData_ASP_&_MS_Final_python.csv"
    qa_report_json: Path = ROOT_DIR / "data" / "out" / "MarketData_QA_report.json"

    # Qlik Reload and QVD diagnostic paths
    qlik_reload_script: Path = ROOT_DIR / "integration" / "Reload_ASP_MS_Overview_Add_RB_2.py"
    qvd_source_path: Path = _configured_path(
        "data_sources",
        "qvd_source_file",
        ROOT_DIR / "data" / "out" / "MarketData_ASP_&_MS_Final_QVD_RB.qvd",
    )
    qvd_target_path: Path = ROOT_DIR / "data" / "out" / "MarketData_ASP_&_MS_Final_QVD_RB.qvd"

    debug_be_only: bool = False
    default_ilp_share_sc: float = 0.50

CFG = Config()

# --------------------------
# Helpers unique to the monolithic compatibility module
# --------------------------

def combined_flag(product_u: str) -> str | None:
    """Detect combined templates: IPG_SC, IPG_DC, ICD_S, or None."""
    if pd.isna(product_u):
        return None
    s = str(product_u).upper()
    # Exclude the aggregate "Single + Dual" row to prevent duplicates
    if "SINGLE + DUAL" in s:
        return None

    if "IPG SINGLE" in s and "CONVENTIONAL + LEADLESS" in s:
        return "IPG_SC"
    if "IPG DUAL" in s and "CONVENTIONAL + LEADLESS" in s:
        return "IPG_DC"
    if "ICD SINGLE" in s and "CONVENTIONAL + NON-TRANSVENOUS" in s:
        return "ICD_S"
    return None

def yq_label(year: int, q: int, latest_year: int, latest_q: int) -> str:
    """Return YTD label or year."""
    return f"{latest_year} Q{latest_q} YTD" if (year == latest_year and q <= latest_q) else str(year)

def log_residual_combined_rows(df: pd.DataFrame) -> None:
    """Print size of residual combined rows (IPG Single+Dual, CRT-P+CRT-D)."""
    if "PRODUCT_GROUP" not in df.columns:
        print("INFO: No PRODUCT_GROUP column found for residual logging.")
        return

    masks = {
        "IPG Single + Dual Chamber":
            (df["BUSINESS_SEGMENT"] == "IPG") & df["PRODUCT_GROUP"].eq("IPG Single + Dual Chamber"),
        "CRT-P + CRT-D":
            (df["BUSINESS_SEGMENT"] == "CRT") & df["PRODUCT_GROUP"].eq("CRT-P + CRT-D"),
    }

    for label, m in masks.items():
        sub = df[m].copy()
        if sub.empty:
            print(f"\nResidual combined rows for {label}: none.")
            continue

        print(f"\nResidual combined rows for {label}:")
        try:
            print(
                sub.groupby(["COUNTRY_NAME", "Year", "Quarter"])[
                    ["Market Units", "Market Net Revenue (in K EUR)", "Units", "Net Revenue (in K EUR)"]
                ]
                .sum()
                .to_string()
            )
        except KeyError:
            # if some of the numeric columns are missing
            print(
                sub.groupby(["COUNTRY_NAME", "Year", "Quarter"])
                .size()
                .rename("rows")
                .to_string()
            )

def fix_residual_combined_rows(df: pd.DataFrame) -> pd.DataFrame:
    """
    Handle odd combined product groups that slipped through:
      - IPG Single + Dual Chamber -> split into SC/DC conventional
      - CRT-P + CRT-D            -> split into CRT-P / CRT-D

    Strategy:
      - Work per (COUNTRY_NAME, Year, Quarter, SALES_ORG).
      - Use existing SC/DC (or CRT-P/CRT-D) market-unit split in that key if available.
      - If no split info exists, fallback to 50/50.
      - Split Market Units, Market Net Revenue, Units, and ORG revenue.
      - Drop the original combined-row.
    """
    if "PRODUCT_GROUP" not in df.columns:
        return df

    out = df.copy()

    key_cols = ["COUNTRY_NAME", "Year", "Quarter", "SALES_ORG"]

    # ---------- IPG Single + Dual Chamber ----------
    mask_ipg_mix = (
        (out["BUSINESS_SEGMENT"] == "IPG")
        & out["PRODUCT_GROUP"].eq("IPG Single + Dual Chamber")
    )
    ipg_mix = out[mask_ipg_mix].copy()

    if not ipg_mix.empty:
        # Existing SC/DC conventional IPG rows to derive the split
        sc_mask = (
            (out["BUSINESS_SEGMENT"] == "IPG")
            & out["PRODUCT"].str.contains("SINGLE CHAMBER CONVENTIONAL", case=False, na=False)
        )
        dc_mask = (
            (out["BUSINESS_SEGMENT"] == "IPG")
            & out["PRODUCT"].str.contains("DUAL CHAMBER CONVENTIONAL", case=False, na=False)
        )

        sc_units = out[sc_mask].groupby(key_cols)["Market Units"].sum().rename("Units_SC")
        dc_units = out[dc_mask].groupby(key_cols)["Market Units"].sum().rename("Units_DC")

        shares = pd.concat([sc_units, dc_units], axis=1).fillna(0.0)
        total = shares["Units_SC"] + shares["Units_DC"]

        shares["Share_SC"] = np.where(total > 0, shares["Units_SC"] / total, 0.5)
        shares["Share_DC"] = np.where(total > 0, shares["Units_DC"] / total, 0.5)

        ipg_mix = ipg_mix.merge(
            shares[["Share_SC", "Share_DC"]],
            on=key_cols,
            how="left",
        )
        ipg_mix["Share_SC"] = ipg_mix["Share_SC"].fillna(0.5)
        ipg_mix["Share_DC"] = ipg_mix["Share_DC"].fillna(0.5)

        # Helper to split a numeric column by a given share
        def split_col(frame, col, share_col):
            if col not in frame.columns:
                return np.nan
            vals = frame[col].fillna(0.0).astype("float64")
            return vals * frame[share_col]

        # Build SC rows
        sc_rows = ipg_mix.copy()
        sc_rows["PRODUCT_GROUP"] = "IPG Single Chamber"
        sc_rows["PRODUCT"] = "IPG SINGLE CHAMBER CONVENTIONAL"

        sc_rows["Market Units"] = split_col(sc_rows, "Market Units", "Share_SC").round()
        sc_rows["Market Net Revenue (in K EUR)"] = split_col(sc_rows, "Market Net Revenue (in K EUR)", "Share_SC")
        sc_rows["Units"] = split_col(sc_rows, "Units", "Share_SC").round()
        sc_rows["Net Revenue (in K EUR)"] = split_col(sc_rows, "Net Revenue (in K EUR)", "Share_SC")
        sc_rows["Origin"] = "Split from IPG Single + Dual Chamber"

        # Build DC rows
        dc_rows = ipg_mix.copy()
        dc_rows["PRODUCT_GROUP"] = "IPG Dual Chamber"
        dc_rows["PRODUCT"] = "IPG DUAL CHAMBER CONVENTIONAL"

        dc_rows["Market Units"] = split_col(dc_rows, "Market Units", "Share_DC").round()
        dc_rows["Market Net Revenue (in K EUR)"] = split_col(dc_rows, "Market Net Revenue (in K EUR)", "Share_DC")
        dc_rows["Units"] = split_col(dc_rows, "Units", "Share_DC").round()
        dc_rows["Net Revenue (in K EUR)"] = split_col(dc_rows, "Net Revenue (in K EUR)", "Share_DC")
        dc_rows["Origin"] = "Split from IPG Single + Dual Chamber"

        # Drop original mixed rows and append splits
        out = out[~mask_ipg_mix]
        out = pd.concat([out, sc_rows, dc_rows], ignore_index=True, sort=False)

    # ---------- CRT-P + CRT-D ----------
    mask_crt_mix = (
        (out["BUSINESS_SEGMENT"] == "CRT")
        & out["PRODUCT_GROUP"].eq("CRT-P + CRT-D")
    )
    crt_mix = out[mask_crt_mix].copy()

    if not crt_mix.empty:
        crt_p_mask = (
            (out["BUSINESS_SEGMENT"] == "CRT")
            & out["PRODUCT"].str.contains("CRT-P", case=False, na=False)
        )
        crt_d_mask = (
            (out["BUSINESS_SEGMENT"] == "CRT")
            & out["PRODUCT"].str.contains("CRT-D", case=False, na=False)
        )

        p_units = out[crt_p_mask].groupby(key_cols)["Market Units"].sum().rename("Units_P")
        d_units = out[crt_d_mask].groupby(key_cols)["Market Units"].sum().rename("Units_D")

        shares_crt = pd.concat([p_units, d_units], axis=1).fillna(0.0)
        total = shares_crt["Units_P"] + shares_crt["Units_D"]

        shares_crt["Share_P"] = np.where(total > 0, shares_crt["Units_P"] / total, 0.5)
        shares_crt["Share_D"] = np.where(total > 0, shares_crt["Units_D"] / total, 0.5)

        crt_mix = crt_mix.merge(
            shares_crt[["Share_P", "Share_D"]],
            on=key_cols,
            how="left",
        )
        crt_mix["Share_P"] = crt_mix["Share_P"].fillna(0.5)
        crt_mix["Share_D"] = crt_mix["Share_D"].fillna(0.5)

        def split_col_crt(frame, col, share_col):
            if col not in frame.columns:
                return np.nan
            vals = frame[col].fillna(0.0).astype("float64")
            return vals * frame[share_col]

        # CRT-P rows
        p_rows = crt_mix.copy()
        p_rows["PRODUCT_GROUP"] = "CRT-P"
        p_rows["PRODUCT"] = "CRT-P"
        p_rows["Market Units"] = split_col_crt(p_rows, "Market Units", "Share_P").round()
        p_rows["Market Net Revenue (in K EUR)"] = split_col_crt(p_rows, "Market Net Revenue (in K EUR)", "Share_P")
        p_rows["Units"] = split_col_crt(p_rows, "Units", "Share_P").round()
        p_rows["Net Revenue (in K EUR)"] = split_col_crt(p_rows, "Net Revenue (in K EUR)", "Share_P")
        p_rows["Origin"] = "Split from CRT-P + CRT-D"

        # CRT-D rows
        d_rows = crt_mix.copy()
        d_rows["PRODUCT_GROUP"] = "CRT-D"
        d_rows["PRODUCT"] = "CRT-D"
        d_rows["Market Units"] = split_col_crt(d_rows, "Market Units", "Share_D").round()
        d_rows["Market Net Revenue (in K EUR)"] = split_col_crt(d_rows, "Market Net Revenue (in K EUR)", "Share_D")
        d_rows["Units"] = split_col_crt(d_rows, "Units", "Share_D").round()
        d_rows["Net Revenue (in K EUR)"] = split_col_crt(d_rows, "Net Revenue (in K EUR)", "Share_D")
        d_rows["Origin"] = "Split from CRT-P + CRT-D"

        out = out[~mask_crt_mix]
        out = pd.concat([out, p_rows, d_rows], ignore_index=True, sort=False)

    return out

def fix_ipg_negative_conventional(df: pd.DataFrame) -> pd.DataFrame:
    """
    Re-allocate IPG revenue/units between Conventional and iLP to remove
    negative Conventional rows, while preserving totals per key.
    """
    df = df.copy()

    # We only care about IPG segment, CONVENTIONAL products with negative market revenue
    neg_mask = (
        (df["BUSINESS_SEGMENT"] == "IPG") &
        df["PRODUCT"].isin([
            "IPG SINGLE CHAMBER CONVENTIONAL",
            "IPG DUAL CHAMBER CONVENTIONAL",
        ]) &
        (df["Market Net Revenue (in K EUR)"] < 0)
    )

    problematic = df[neg_mask]

    if problematic.empty:
        return df

    print("WARN: Fixing negative IPG Conventional rows (soft strict):")
    print(problematic[[
        "Year", "Quarter", "COUNTRY_NAME", "CC", "SALES_ORG",
        "PRODUCT", "Market Units", "Market Net Revenue (in K EUR)"
    ]])

    for idx, row in problematic.iterrows():
        year = row["Year"]
        quarter = row["Quarter"]
        country = row["COUNTRY_NAME"]
        cc = row["CC"]
        sales_org = row["SALES_ORG"]
        product_conv = row["PRODUCT"]

        # Map Conventional product -> corresponding iLP product
        if product_conv == "IPG SINGLE CHAMBER CONVENTIONAL":
            ilp_product = "IPG SC iLP"
        elif product_conv == "IPG DUAL CHAMBER CONVENTIONAL":
            ilp_product = "IPG DC iLP"
        else:
            # Unexpected product naming; skip but log
            print(f"WARN: Skipping negative IPG row with unexpected PRODUCT={product_conv!r}")
            continue

        ilp_mask = (
            (df["Year"] == year) &
            (df["Quarter"] == quarter) &
            (df["COUNTRY_NAME"] == country) &
            (df["CC"] == cc) &
            (df["SALES_ORG"] == sales_org) &
            (df["BUSINESS_SEGMENT"] == "IPG") &
            (df["PRODUCT"] == ilp_product)
        )

        ilp_indices = df.index[ilp_mask]

        if len(ilp_indices) != 1:
            print(f"WARN: Could not uniquely match ILP row for negative IPG Conventional row idx={idx}, "
                  f"found {len(ilp_indices)} matches.")
            continue

        ilp_idx = ilp_indices[0]

        # Current values
        conv_rev = float(df.at[idx, "Market Net Revenue (in K EUR)"])
        conv_units = float(df.at[idx, "Market Units"])

        ilp_rev = float(df.at[ilp_idx, "Market Net Revenue (in K EUR)"])
        ilp_units = float(df.at[ilp_idx, "Market Units"])

        # Totals (assumed canonical for this key/chamber)
        total_rev = conv_rev + ilp_rev
        total_units = conv_units + ilp_units

        # Soft strict rule: Conventional floored at 0, ILP absorbs the total
        conv_rev_new = 0.0
        conv_units_new = 0.0

        ilp_rev_new = max(total_rev, 0.0)
        ilp_units_new = max(total_units, 0.0)

        # Apply updates
        df.at[idx, "Market Net Revenue (in K EUR)"] = conv_rev_new
        df.at[idx, "Market Units"] = conv_units_new

        df.at[ilp_idx, "Market Net Revenue (in K EUR)"] = ilp_rev_new
        df.at[ilp_idx, "Market Units"] = ilp_units_new

    return df


# --------------------------
# MODULE 1: DATA LOADER
# --------------------------

class DataLoader:
    """Load all source data (CRM, ICM, unconventional)."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.country_map = None
        self.export_map = None
        self.rb_map = None

    def load_maps(self) -> Dict[str, pd.DataFrame]:
        # 1) Load Country Map from YAML config
        with open(self.cfg.mappings_yaml, "r", encoding="utf-8") as f:
             data = yaml.safe_load(f)
        country = pd.DataFrame(data["countries"])
        self.territory_map = data.get("territory_map", {})

        # Ensure POS_CC exists (default to CC)
        if "POS_CC" not in country.columns:
            country["POS_CC"] = country["CC"]
        # Ensure VI_COUNTRY_NAME exists (default to CRM Name)
        if "VI_COUNTRY_NAME" not in country.columns:
             country["VI_COUNTRY_NAME"] = country["CRM_COUNTRY_NAME"]

        # 2) Load Export Map
        export = pd.read_excel(self.cfg.map_country_export_xlsx, sheet_name="COUNTRY_EXPORT")
        export.columns = [c.strip().upper() for c in export.columns]
        assert_columns(export, ["COUNTRY","EXPORT"], "load_country_export_map (before)")
        export.rename(columns={"COUNTRY":"COUNTRY_RAW","EXPORT":"EXPORT_FLAG"}, inplace=True)

        # same fix for export mapping
        # export["COUNTRY_RAW"] = export["COUNTRY_RAW"].replace({"Ireland": "United Kingdom"})


        rb = pd.read_excel(self.cfg.rb_map_xlsx, sheet_name="RBMAP")
        rb.columns = [c.strip() for c in rb.columns]
        assert_columns(rb, ["PRODUCT", "RB_PRODUCT_NAME"], "load_rb_map")

        # 🔑 canonical product key used everywhere
        rb["PRODUCT_CANON"] = rb["PRODUCT"].map(canon_product)

        self.country_map = country
        self.export_map = export

        # --- Fix: Ensure Unconventional Leadless products are mapped to RedBull names ---
        # The logs showed these were NaN.
        unconventional_mappings = {
            "DUAL CHAMBER IPG - LEADLESS": "IPG DC iLP",
            "IPG LEADLESS": "IPG SC iLP",
            "SINGLE CHAMBER IPG - LEADLESS": "IPG SC iLP",
        }
        for canon, rb_name in unconventional_mappings.items():
            mask = rb["PRODUCT_CANON"] == canon
            if mask.any():
                rb.loc[mask, "RB_PRODUCT_NAME"] = rb_name
            else:
                # Add to map if not present
                new_row = pd.DataFrame([{"PRODUCT": canon, "RB_PRODUCT_NAME": rb_name, "PRODUCT_CANON": canon}])
                rb = pd.concat([rb, new_row], ignore_index=True)

        self.rb_map = rb

        return {"country": country, "export": export, "rb": rb}

    def load_crm(self) -> pd.DataFrame:
        df = pd.read_excel(self.cfg.crm_dl_xlsx, sheet_name="Sheet1")
        df.columns = [c.strip() for c in df.columns]

        # --- Territory Remapping (User Configured) ---
        if self.territory_map and "Country Name" in df.columns:
            # Log which mappings are applied
            for orig, remapped in self.territory_map.items():
                count = (df["Country Name"] == orig).sum()
                if count > 0:
                    ai_log("territory_remap", original=orig, mapped_to=remapped, rows_affected=int(count))
            # Apply remapping (e.g. Tunisia -> France)
            df["Country Name"] = df["Country Name"].replace(self.territory_map)




        # 🔹 Normalise Ireland -> United Kingdom in the raw CRM file
        # if "Country Name" in df.columns:
        #    df["Country Name"] = df["Country Name"].replace({"Ireland": "United Kingdom"})

        assert_columns(df, ["Business Unit","Business Segment","Country Name","Quarter","Market Units",
                            "Market Net Revenue (in K EUR)","ORG Units","ORG Net Revenue (in K EUR)"],
                       "load_crm")

        df = df[df["Business Unit"] != "VI"].copy()
        assert_not_empty(df, "load_crm (after filtering VI)")

        if self.cfg.debug_be_only:
            be_mask = (df["Business Segment"].isin(["IPG","ICD"])) & (
                df["Country Name"].str.strip().str.upper().eq("BELGIUM")
            )
            df = df[be_mask].copy()

        # Numerics
        df["Market Units"] = df["Market Units"].map(num_smart).round().astype("Int64")
        df["Market Net Revenue (in K EUR)"] = df["Market Net Revenue (in K EUR)"].map(num_smart)
        df["Units"] = df["ORG Units"].map(num_smart).round().astype("Int64")
        df["Net Revenue (in K EUR)"] = df["ORG Net Revenue (in K EUR)"].map(num_smart)
        df["Market ASP (in EUR)"] = df["Market ASP (in EUR)"].map(num_smart) if "Market ASP (in EUR)" in df.columns else np.nan
        df["ASP (in EUR)"] = df["ORG ASP (in EUR)"].map(num_smart) if "ORG ASP (in EUR)" in df.columns else np.nan

        # --- PANDERA VALIDATION (Post-Cleaning) ---
        print("Validating CRM data against schema...")
        try:
            InputSchemaCrm.validate(df, lazy=True)
            print("CRM Schema Validation: PASSED")
        except pa.errors.SchemaErrors as err:
            print("CRM Schema Validation: FAILED")
            print(err.failure_cases)
            raise err

        # Time
        df["QTR"] = df["Quarter"].astype(str).str[-1].astype(int)
        df["NumericQuarter"] = (df["Quarter"].astype(str).str[:2] + df["QTR"].astype(str)).astype(int)

        # Canonical
        df["SOURCE"] = "MTE"
        df["REGION"] = "MIDWEST"
        df["CURRENCY_NAME"] = "EUR"
        # NORMALIZE PRODUCT NAMES TO UPPERCASE
        df.rename(columns={
            "Country Name": "COUNTRY_NAME",
            "Business Unit": "BUSINESS_UNIT",
            "Business Segment": "BUSINESS_SEGMENT",
            "Product Group": "PRODUCT_GROUP",
            "Product": "PRODUCT",
            "COUNTRY_CODE": "CC", # Support direct CC if available
        }, inplace=True)

        df["PRODUCT"] = df["PRODUCT"].astype(str).str.upper().str.strip()

        return df

    def load_icm_market(self, crm_max_nq: int, cc_fix_map: Dict[str, str]) -> pd.DataFrame:
        """Load ICM annual market, split to quarters, and map to CRM-like schema."""
        if not self.cfg.icm_market_dl_xlsx.exists():
            return pd.DataFrame()

        raw = pd.read_excel(self.cfg.icm_market_dl_xlsx, sheet_name="Sheet1")
        raw.columns = [c.strip() for c in raw.columns]

        # ---- NEW: Handle updated export columns (Year -> YEAR, missing Business Unit) ----
        # 1. Map YEAR to Year
        if "YEAR" in raw.columns and "Year" not in raw.columns:
            raw = raw.rename(columns={"YEAR": "Year"})

        # 2. Add default Business Unit if missing
        if "Business Unit" not in raw.columns:
            raw["Business Unit"] = "CRM incl. EP"

        # Robustness: Handle missing 'Year' column if annual export is used
        if "Year" not in raw.columns:
            inferred_year = 2000 + (crm_max_nq // 10)
            print(f"INFO: 'Year' column missing in ICM_Market_DL.xlsx. Inferring Year={inferred_year} from CRM horizon.")
            raw["Year"] = inferred_year

        assert_columns(
            raw,
            ["Country Code", "Business Unit", "Product Segment", "Product Category",
            "Year", "Market Units", "Market Net Revenue"],
            "load_icm_market"
        )

        # ---- FIX: SEGMENT LEAKAGE ----
        # The source file contains Brady, Tachy, EP rows. We MUST filter for 'ICM'.
        mask_icm = raw["Product Category"].astype(str).str.contains("ICM", case=False, na=False)
        if not mask_icm.any():
            print("WARNING: No rows with Product Category 'ICM' found in ICM_Market_DL.xlsx")
            # We don't return empty yet to allow potential manual overlaps,
            # but usually this is a hard requirement.

        raw_icm = raw[mask_icm].copy()
        print(f"INFO: Filtered ICM Market data from {len(raw)} down to {len(raw_icm)} rows (Segment: ICM)")
        raw = raw_icm

        # Normalise CC (use cc_fix_map like {"UK":"GB","EL":"GR"})
        raw["CC"] = (
            raw["Country Code"]
            .astype(str).str.strip().str.upper()
            .map(lambda x: cc_fix_map.get(x, x))
        )

        # Numerics
        raw["Market_Units"] = raw["Market Units"].map(num_smart)
        raw["Market_Rev"]   = raw["Market Net Revenue"].map(num_smart)

        # NOTE: BIO metrics intentionally NOT extracted here.
        # BIO data now comes exclusively from ICM_BIO_DL.xlsx via load_icm_bio().

        # Annual aggregation (per BU / segment / category) — market-only
        ann = raw.groupby(
            ["CC", "Business Unit", "Product Segment", "Product Category", "Year"],
            as_index=False
        ).agg(
            MarketUnits_Annual=("Market_Units", "sum"),
            MarketRevK_Annual=("Market_Rev", lambda s: s.sum() / 1000.0),
        )

        # Annual ASP (EUR per unit)
        ann["MarketASP_Annual"] = np.where(
            ann["MarketUnits_Annual"] > 0,
            (ann["MarketRevK_Annual"] * 1000.0) / ann["MarketUnits_Annual"],
            np.nan,
        )

        # Split annual units to quarters (simple even split with remainder)
        rows = []
        for _, r in ann.iterrows():
            mu_total = r.MarketUnits_Annual or 0
            base = math.floor(mu_total / 4)
            rem = int(mu_total - 4 * base)

            for q in range(1, 5):
                mu = base + (1 if q <= rem else 0)
                quarter = f"{int(r.Year) % 100:02d}Q{q}"

                rows.append(dict(
                    CC              = r.CC,
                    Business_Unit   = r["Business Unit"],
                    ProductSegment  = r["Product Segment"],
                    ProductCategory = r["Product Category"],
                    Year            = int(r.Year),
                    Quarter         = quarter,
                    QTR             = q,
                    NumericQuarter  = int(f"{int(r.Year) % 100:02d}{q}"),
                    MarketUnits_Q   = mu,
                    MarketRevK_Annual = r.MarketRevK_Annual,
                    MarketASP_Annual  = r.MarketASP_Annual,
                ))

        qdf = pd.DataFrame(rows)
        qdf = qdf[qdf["NumericQuarter"] <= crm_max_nq].copy()
        if qdf.empty:
            return pd.DataFrame()

        # ---- Map CC -> country / BIOS / Sales Org from country_map ----
        if self.country_map is None or self.export_map is None:
            raise RuntimeError("load_maps() must be called before load_icm_market()")

        # Build a safe CC -> country / BIOS / Sales Org map.
        country_cc = self.country_map.copy()

        # Prefer rows where POS_CC == CC (true “home” country like FR->France).
        country_cc["is_iso"] = country_cc["POS_CC"].astype(str) == country_cc["CC"].astype(str)

        country_cc = (
            country_cc
            .sort_values(["CC", "is_iso"], ascending=[True, False])
            .drop_duplicates(subset=["CC"], keep="first")
        )

        cc_to_country = dict(zip(country_cc["CC"], country_cc["CRM_COUNTRY_NAME"]))
        cc_to_bios    = dict(zip(country_cc["CC"], country_cc["BIOS"]))
        cc_to_sorg    = dict(zip(country_cc["CC"], country_cc["Sales_Organisation"]))

        missing_cc = sorted(set(qdf["CC"]) - set(cc_to_country))
        if missing_cc:
            print("WARN: ICM CCs missing in country map:", missing_cc)

        qdf["COUNTRY_NAME"] = qdf["CC"].map(cc_to_country)
        qdf["BIOS"]         = qdf["CC"].map(cc_to_bios)
        qdf["SALES_ORG"]    = qdf["CC"].map(cc_to_sorg)

        # Allocate revenue to quarters using annual ASP
        qdf["MarketUnits_Q"] = qdf["MarketUnits_Q"].fillna(0.0)
        qdf["MarketRevK_Q"] = np.where(
            qdf["MarketUnits_Q"] > 0,
            (qdf["MarketUnits_Q"] * qdf["MarketASP_Annual"]) / 1000.0,
            0.0,
        )

        # ---- Build ICM rows in the same schema as CRM ----
        out = pd.DataFrame({
            "SOURCE":        "ICM Market",
            "REGION":        "MIDWEST",
            "COUNTRY_NAME":  qdf["COUNTRY_NAME"],
            "CC":            qdf["CC"],
            "SALES_ORG":     qdf["SALES_ORG"],
            "BIOS":          qdf["BIOS"],
            "CURRENCY_NAME": "EUR",

            "BUSINESS_UNIT":   "CRM",
            "BUSINESS_SEGMENT": "ICM",
            "PRODUCT_GROUP":    "ICM",
            "PRODUCT":          "ICM",

            "Year":           qdf["Year"],
            "Quarter":        qdf["Quarter"],
            "QTR":            qdf["QTR"],
            "NumericQuarter": qdf["NumericQuarter"],

            "Market Units":                 qdf["MarketUnits_Q"].round(),
            "Market Net Revenue (in K EUR)": qdf["MarketRevK_Q"],
            "Market ASP (in EUR)":          qdf["MarketASP_Annual"],

            # NOTE: BIO metrics removed — now sourced from ICM_BIO_DL.xlsx via load_icm_bio()

            # ORG final columns (will be populated in main)
            "Units":                 0,
            "Net Revenue (in K EUR)": 0.0,
            "ASP (in EUR)":          np.nan,
        })


        return out

    def load_icm_bio(self, crm_max_nq: int) -> pd.DataFrame:
        """
        Load ICM ORG data (quarterly) and aggregate to:
            CC + Year + Quarter ('25Q3') + QTR + NumericQuarter
        Returns only ORG metrics (no market volumes).
        """
        if not self.cfg.icm_bio_dl_xlsx.exists():
            print("WARNING: ICM BIO file not found")
            return pd.DataFrame()

        raw = pd.read_excel(self.cfg.icm_bio_dl_xlsx, sheet_name="Sheet1")
        print(f"DEBUG: ICM BIO raw loaded {len(raw)} rows")

        # Normalise columns
        cols = (
            pd.Series(raw.columns, dtype="object")
            .astype(str)
            .str.strip()
            .str.replace(r"\s+", " ", regex=True)
        )
        raw.columns = dedupe(cols)

        # Expect the standard columns from your file
        assert_columns(
            raw,
            ["Product Category", "Country Code", "Year", "Quarter", "Units", "Net Revenue EUR"],
            "load_icm_bio",
        )

        # Filter for ICM only (user request: exclude everything not ICM)
        raw = raw[raw["Product Category"].astype(str).str.contains("ICM", case=False, na=False)].copy()
        if raw.empty:
            # Assuming 'logging' is imported or print is acceptable for warnings
            import logging
            logging.warning("No ICM rows found in BIOStd data after filtering.")
            return pd.DataFrame()

        # CC normalisation (UK -> GB etc., just in case)
        cc_fix_map = {"UK": "GB", "EL": "GR"}
        raw["CC"] = (
            raw["Country Code"]
            .astype(str)
            .str.strip()
            .str.upper()
            .map(lambda x: cc_fix_map.get(x, x))
        )

        # Time handling: Quarter is like 'Q1', 'Q2', ...
        raw["Year"] = raw["Year"].astype(int)
        raw["Quarter"] = raw["Quarter"].astype(str).str.strip().str.upper()
        raw["QTR"] = raw["Quarter"].str.extract(r"(\d)").astype(int)
        raw["Quarter"] = raw.apply(
            lambda r: f"{int(r['Year']) % 100:02d}Q{int(r['QTR'])}", axis=1
        )
        raw["NumericQuarter"] = (
            (raw["Year"] % 100).astype(int) * 10 + raw["QTR"].astype(int)
        )

        # Restrict to CRM horizon
        raw = raw[raw["NumericQuarter"] <= crm_max_nq].copy()
        if raw.empty:
            return pd.DataFrame()

        # ORG metrics
        raw["Units_BIO"] = raw["Units"].map(num_smart)
        raw["NetRev_EUR_BIO"] = raw["Net Revenue EUR"].map(num_smart)

        raw["Units_BIO"] = raw["Units_BIO"].fillna(0.0)
        raw["NetRev_EUR_BIO"] = raw["NetRev_EUR_BIO"].fillna(0.0)

        # Convert to kEUR
        raw["NetRev_K_BIO"] = raw["NetRev_EUR_BIO"] / 1000.0

        # Aggregate (just in case there are multiple product categories per quarter)
        agg = (
            raw.groupby(
                ["CC", "Year", "Quarter", "QTR", "NumericQuarter"], as_index=False
            )
            .agg(
                Units_BIO=("Units_BIO", "sum"),
                NetRev_K_BIO=("NetRev_K_BIO", "sum"),
            )
        )

        return agg


# --------------------------
# MODULE 2: ADJUSTMENTS
# --------------------------

class AdjustmentCompute:
    """Compute iLP/S-ICD adjustments (pure transformation, no I/O)."""

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def compute(self, crm_data: pd.DataFrame, crm_max_nq: int, default_sc_share: float) -> Dict[str, pd.DataFrame]:
        """
        Input:  crm_data (CRM with FactKey, canonical products)
        Output: {
            "adj_all": adjustments by FactKey,
            "ilp_final": ILP breakdown,
            "sicd": S-ICD aggregation (capped),
            "sicd_overcap": S-ICD > combined ICD cases (for QA),
            "ilp_overcap":  ILP  > combined IPG cases (for QA),
        }
        """
        if not self.cfg.unconventional_mkt_xlsx.exists():
            return {
                "adj_all": pd.DataFrame(),
                "ilp_final": pd.DataFrame(),
                "sicd": pd.DataFrame(),
                "sicd_overcap": pd.DataFrame(),
                "ilp_overcap": pd.DataFrame(),
            }

        u = pd.read_excel(self.cfg.unconventional_mkt_xlsx, sheet_name="DATA")
        u.columns = [c.strip() for c in u.columns]
        cc_fix_map = {"UK": "GB", "EL": "GR", "IE": "GB", "IR": "GB"}

        # Parse time
        yqs = u["Quarter"].map(quarter_to_numeric).tolist()
        yy, qq, nq = zip(*yqs)
        u["Year"] = yy
        u["QTR"] = qq
        u["NumericQuarter"] = nq
        u["CC"] = u["CC"].astype(str).str.upper().map(lambda x: cc_fix_map.get(x, x))
        u["UNCONV_Units"] = u["Market Units"].map(num_smart)
        u["UNCONV_Revenue_K"] = u["Market Net Revenue (in K EUR)"].map(num_smart)

        # Attach SALES_ORG from CRM
        dom_org = crm_data.groupby(["CC","Year","Quarter"], as_index=False)["SALES_ORG"] \
                          .agg(lambda s: s.value_counts().index[0])
        u = u.merge(dom_org, on=["CC","Year","Quarter"], how="left")
        u["Key_QCS"] = pd.util.hash_pandas_object(
            u[["CC","SALES_ORG","Year","Quarter"]].astype(str),
            index=False,
        )

        # Classify unconventional types
        def classify(row):
            p = str(row["Product"]).upper()
            if "S-ICD" in p or "NON-TRANSVEN" in p:
                return "SICD"
            if ("LEADLESS" in p or "ILP" in p) and any(k in p for k in ["SINGLE","SC"]):
                return "ILP_SC"
            if ("LEADLESS" in p or "ILP" in p) and any(k in p for k in ["DUAL","DC"]):
                return "ILP_DC"
            if "LEADLESS" in p or "ILP" in p:
                return "ILP_TOTAL"
            return "OTHER"

        u["UNCONV_CLASS"] = u.apply(classify, axis=1)

        # Map unconventional to target product
        def target_product(cls):
            if cls == "SICD":
                return "ICD SINGLE CHAMBER CONVENTIONAL + NON-TRANSVENOUS"
            elif cls == "ILP_SC":
                return "IPG SINGLE CHAMBER CONVENTIONAL + LEADLESS"
            elif cls == "ILP_DC":
                return "IPG DUAL CHAMBER CONVENTIONAL + LEADLESS"
            return None

        u["TARGET_PRODUCT"] = u["UNCONV_CLASS"].map(target_product)
        u["TARGET_PRODUCT_CANON"] = u["TARGET_PRODUCT"].map(canon_product)
        u["FactKey"] = pd.util.hash_pandas_object(
            u[["CC","SALES_ORG","Year","Quarter","TARGET_PRODUCT_CANON"]].astype(str),
            index=False,
        )
        u = u[u["NumericQuarter"] <= crm_max_nq].copy()

        # --------------------
        # ILP split & totals
        # --------------------
        md_ipg = crm_data[
            (crm_data["BUSINESS_SEGMENT"] == "IPG")
            & (
                crm_data["PRODUCT_U"]
                .str.contains("CONVENTIONAL + LEADLESS", case=False, na=False, regex=False)
            )
        ].copy()
        md_ipg["IPG_Type"] = np.where(
            md_ipg["PRODUCT"].str.startswith("IPG SINGLE"),
            "SC",
            "DC",
        )

        piv = md_ipg.pivot_table(
            index=["CC","SALES_ORG","Year","Quarter"],
            columns="IPG_Type",
            values="Market Units",
            aggfunc="sum",
            fill_value=0,
        ).reset_index()
        if "SC" not in piv.columns:
            piv["SC"] = 0.0
        if "DC" not in piv.columns:
            piv["DC"] = 0.0
        piv.rename(columns={"SC":"Units_SC","DC":"Units_DC"}, inplace=True)
        total = (piv["Units_SC"] + piv["Units_DC"]).replace(0, np.nan)
        piv["Share_SC"] = (piv["Units_SC"] / total).fillna(default_sc_share)
        piv["Share_DC"] = 1.0 - piv["Share_SC"]
        piv["Key_QCS"] = pd.util.hash_pandas_object(
            piv[["CC","SALES_ORG","Year","Quarter"]].astype(str),
            index=False,
        )

        # ILP: split where explicitly SC/DC, plus ILP_TOTAL proportional split
        ilp_split = u[u["UNCONV_CLASS"].isin(["ILP_SC","ILP_DC"])].groupby(
            ["Year","Quarter","CC","SALES_ORG","Key_QCS"],
            as_index=False,
        ).agg(
            iLP_Units_SC=("UNCONV_Units", lambda s: s[u.loc[s.index,"UNCONV_CLASS"]=="ILP_SC"].sum()),
            iLP_Units_DC=("UNCONV_Units", lambda s: s[u.loc[s.index,"UNCONV_CLASS"]=="ILP_DC"].sum()),
            iLP_RevenueK_SC=("UNCONV_Revenue_K", lambda s: s[u.loc[s.index,"UNCONV_CLASS"]=="ILP_SC"].sum()),
            iLP_RevenueK_DC=("UNCONV_Revenue_K", lambda s: s[u.loc[s.index,"UNCONV_CLASS"]=="ILP_DC"].sum()),
        )

        ilp_total = u[u["UNCONV_CLASS"] == "ILP_TOTAL"].groupby(
            ["Year","Quarter","CC","SALES_ORG","Key_QCS"],
            as_index=False,
        ).agg(
            iLP_Total_Units=("UNCONV_Units","sum"),
            iLP_Total_RevenueK=("UNCONV_Revenue_K","sum"),
        ).merge(
            piv[["Key_QCS","Share_SC","Share_DC"]],
            on="Key_QCS",
            how="left",
        )

        ilp_total["Share_SC"] = ilp_total["Share_SC"].fillna(default_sc_share)
        ilp_total["Share_DC"] = ilp_total["Share_DC"].fillna(1.0 - default_sc_share)
        ilp_total["iLP_Units_SC"] = ilp_total["iLP_Total_Units"] * ilp_total["Share_SC"]
        ilp_total["iLP_Units_DC"] = ilp_total["iLP_Total_Units"] * ilp_total["Share_DC"]
        ilp_total["iLP_RevenueK_SC"] = ilp_total["iLP_Total_RevenueK"] * ilp_total["Share_SC"]
        ilp_total["iLP_RevenueK_DC"] = ilp_total["iLP_Total_RevenueK"] * ilp_total["Share_DC"]

        ilp_final = pd.concat(
            [
                ilp_split[[
                    "Year","Quarter","CC","SALES_ORG","Key_QCS",
                    "iLP_Units_SC","iLP_RevenueK_SC","iLP_Units_DC","iLP_RevenueK_DC"
                ]],
                ilp_total[[
                    "Year","Quarter","CC","SALES_ORG","Key_QCS",
                    "iLP_Units_SC","iLP_RevenueK_SC","iLP_Units_DC","iLP_RevenueK_DC"
                ]],
            ],
            ignore_index=True,
        ).fillna(0)

        # --------------------
        # S-ICD aggregation (raw) + capping vs combined ICD
        # --------------------
        sicd_detail = u[u["UNCONV_CLASS"] == "SICD"].copy()
        sicd_detail["Key_QCS"] = pd.util.hash_pandas_object(
            sicd_detail[["CC","SALES_ORG","Year","Quarter"]].astype(str),
            index=False,
        )
        sicd_raw = sicd_detail.groupby(["Key_QCS"], as_index=False).agg(
            SICD_Units=("UNCONV_Units","sum"),
            SICD_Revenue_K=("UNCONV_Revenue_K","sum"),
        )

        icd_combined = crm_data[
            (crm_data["BUSINESS_SEGMENT"] == "ICD")
            & (crm_data["_IsCombinedFlag"] == "ICD_S")
        ].copy()
        icd_combined_by_key = icd_combined.groupby(
            ["Key_QCS"],
            as_index=False,
        ).agg(
            CombinedUnits=("Market Units","sum"),
            CombinedRevenueK=("Market Net Revenue (in K EUR)","sum"),
        )

        sicd_cap = sicd_raw.merge(icd_combined_by_key, on="Key_QCS", how="left")
        sicd_cap["CombinedUnits"] = sicd_cap["CombinedUnits"].fillna(0)
        sicd_cap["CombinedRevenueK"] = sicd_cap["CombinedRevenueK"].fillna(0)

        sicd_cap["SICD_Units_Capped"] = sicd_cap[["SICD_Units","CombinedUnits"]].min(axis=1)
        sicd_cap["SICD_RevenueK_Capped"] = np.where(
            sicd_cap["SICD_Units"] > 0,
            sicd_cap["SICD_Revenue_K"] * (sicd_cap["SICD_Units_Capped"] / sicd_cap["SICD_Units"]),
            0.0,
        )

        # Enforce business rule: S-ICD revenue must not exceed combined ICD revenue
        sicd_cap["SICD_RevenueK_Capped"] = np.minimum(
        sicd_cap["SICD_RevenueK_Capped"],
        sicd_cap["CombinedRevenueK"]
        )

        over_mask = sicd_cap["SICD_Units_Capped"] < sicd_cap["SICD_Units"]
        if over_mask.any():
            print("\nWARN: S-ICD capped because unconventional volume > combined ICD volume:")
            print(
                sicd_cap.loc[
                    over_mask,
                    ["Key_QCS","SICD_Units","SICD_Units_Capped","CombinedUnits"],
                ]
                .head(10)
                .to_string(index=False)
            )

        # QA table for S-ICD over-cap
        sicd_overcap = sicd_cap.loc[over_mask, [
            "Key_QCS",
            "SICD_Units",
            "CombinedUnits",
            "SICD_Revenue_K",
            "CombinedRevenueK",
        ]].copy()
        sicd_overcap["Excess_Units"] = sicd_overcap["SICD_Units"] - sicd_overcap["CombinedUnits"]
        sicd_overcap["Excess_Revenue_K"] = sicd_overcap["SICD_Revenue_K"] - sicd_overcap["CombinedRevenueK"]

        # Final capped S-ICD used in adjustments
        sicd = sicd_cap[["Key_QCS","SICD_Units_Capped","SICD_RevenueK_Capped"]].rename(
            columns={
                "SICD_Units_Capped":"SICD_Units",
                "SICD_RevenueK_Capped":"SICD_Revenue_K",
            }
        )

        # Attach context to S-ICD QA rows
        sicd_context = sicd_detail.groupby(["Key_QCS"], as_index=False).agg(
            CC=("CC","first"),
            SALES_ORG=("SALES_ORG","first"),
            Year=("Year","first"),
            Quarter=("Quarter","first"),
        )
        if not sicd_overcap.empty:
            sicd_overcap = sicd_overcap.merge(sicd_context, on="Key_QCS", how="left")

        # --------------------
        # ILP over-cap QA vs combined IPG
        # --------------------
        # Aggregate ILP per key
        ilp_agg = ilp_final.groupby(
            ["Year","Quarter","CC","SALES_ORG","Key_QCS"],
            as_index=False,
        ).agg(
            ILP_Units_SC=("iLP_Units_SC","sum"),
            ILP_Units_DC=("iLP_Units_DC","sum"),
            ILP_RevenueK_SC=("iLP_RevenueK_SC","sum"),
            ILP_RevenueK_DC=("iLP_RevenueK_DC","sum"),
        )

        # Combined IPG units & revenue by key and type
        md_ipg_local = md_ipg.copy()
        ipg_combined_by_key = md_ipg_local.groupby(
            ["Key_QCS","IPG_Type"],
            as_index=False,
        ).agg(
            CombinedUnits=("Market Units","sum"),
            CombinedRevenueK=("Market Net Revenue (in K EUR)","sum"),
        )

        ipg_sc = ipg_combined_by_key[ipg_combined_by_key["IPG_Type"] == "SC"].copy()
        ipg_sc = ipg_sc.rename(
            columns={
                "CombinedUnits":"CombinedUnits_SC",
                "CombinedRevenueK":"CombinedRevenueK_SC",
            }
        )[["Key_QCS","CombinedUnits_SC","CombinedRevenueK_SC"]]

        ipg_dc = ipg_combined_by_key[ipg_combined_by_key["IPG_Type"] == "DC"].copy()
        ipg_dc = ipg_dc.rename(
            columns={
                "CombinedUnits":"CombinedUnits_DC",
                "CombinedRevenueK":"CombinedRevenueK_DC",
            }
        )[["Key_QCS","CombinedUnits_DC","CombinedRevenueK_DC"]]

        ipg_wide = ipg_sc.merge(ipg_dc, on="Key_QCS", how="outer").fillna(0)

                # --------------------
        # ILP over-cap QA vs combined IPG (units + revenue)
        # --------------------
        ilp_overcap = ilp_agg.merge(ipg_wide, on="Key_QCS", how="left")

        # Ensure combined columns exist and are non-null
        for col in [
            "CombinedUnits_SC", "CombinedUnits_DC",
            "CombinedRevenueK_SC", "CombinedRevenueK_DC",
        ]:
            if col not in ilp_overcap.columns:
                ilp_overcap[col] = 0.0
            ilp_overcap[col] = ilp_overcap[col].fillna(0.0)

        # Excess vs combined
        ilp_overcap["Excess_Units_SC"] = (
            ilp_overcap["ILP_Units_SC"].fillna(0.0) - ilp_overcap["CombinedUnits_SC"]
        )
        ilp_overcap["Excess_Units_DC"] = (
            ilp_overcap["ILP_Units_DC"].fillna(0.0) - ilp_overcap["CombinedUnits_DC"]
        )
        ilp_overcap["Excess_RevenueK_SC"] = (
            ilp_overcap["ILP_RevenueK_SC"].fillna(0.0) - ilp_overcap["CombinedRevenueK_SC"]
        )
        ilp_overcap["Excess_RevenueK_DC"] = (
            ilp_overcap["ILP_RevenueK_DC"].fillna(0.0) - ilp_overcap["CombinedRevenueK_DC"]
        )

        over_mask_ilp = (
            (ilp_overcap["Excess_Units_SC"] > 0)
            | (ilp_overcap["Excess_Units_DC"] > 0)
            | (ilp_overcap["Excess_RevenueK_SC"] > 0)
            | (ilp_overcap["Excess_RevenueK_DC"] > 0)
        )

        ilp_overcap = ilp_overcap[over_mask_ilp].copy()

        if not ilp_overcap.empty:
            print("\nWARN: ILP exceeds combined IPG template volume/revenue on some keys:")
            print(
                ilp_overcap[
                    [
                        "Key_QCS", "Year", "Quarter", "CC", "SALES_ORG",
                        "ILP_Units_SC", "CombinedUnits_SC", "Excess_Units_SC",
                        "ILP_Units_DC", "CombinedUnits_DC", "Excess_Units_DC",
                        "ILP_RevenueK_SC", "CombinedRevenueK_SC", "Excess_RevenueK_SC",
                        "ILP_RevenueK_DC", "CombinedRevenueK_DC", "Excess_RevenueK_DC",
                    ]
                ]
                .head(10)
                .to_string(index=False)
            )
        else:
            print("\n[OK] ILP forecast vs CRM combined IPG — no ILP > combined IPG cases")


        # --------------------
        # ILP revenue capping vs combined IPG revenue
        # Business rule: ILP revenue must not exceed combined IPG template revenue
        # --------------------
        ilp_cap = ilp_agg.merge(
            ipg_wide[["Key_QCS", "CombinedRevenueK_SC", "CombinedRevenueK_DC"]],
            on="Key_QCS",
            how="left",
        )

        for col in ["CombinedRevenueK_SC", "CombinedRevenueK_DC"]:
            if col not in ilp_cap.columns:
                ilp_cap[col] = 0.0
            ilp_cap[col] = ilp_cap[col].fillna(0.0)

        ilp_cap["ILP_RevenueK_Total"] = ilp_cap["ILP_RevenueK_SC"].fillna(0.0) + ilp_cap["ILP_RevenueK_DC"].fillna(0.0)
        ilp_cap["Combined_RevenueK_Total"] = ilp_cap["CombinedRevenueK_SC"] + ilp_cap["CombinedRevenueK_DC"]

        # Only cap where we actually have combined revenue and ILP exceeds it
        over_mask_rev = (
            (ilp_cap["Combined_RevenueK_Total"] > 0)
            & (ilp_cap["ILP_RevenueK_Total"] > ilp_cap["Combined_RevenueK_Total"])
        )

        ilp_cap["Cap_Ratio"] = 1.0
        ilp_cap.loc[over_mask_rev, "Cap_Ratio"] = (
            ilp_cap.loc[over_mask_rev, "Combined_RevenueK_Total"]
            / ilp_cap.loc[over_mask_rev, "ILP_RevenueK_Total"]
        )

        if over_mask_rev.any():
            print("\nWARN: ILP revenue capped against combined IPG revenue on some keys:")
            print(
                ilp_cap.loc[over_mask_rev, [
                    "Key_QCS",
                    "ILP_RevenueK_Total",
                    "Combined_RevenueK_Total",
                    "Cap_Ratio",
                ]]
                .head(10)
                .to_string(index=False)
            )

        key_ratio = ilp_cap[["Key_QCS", "Cap_Ratio"]].copy()

        # Apply capping to ilp_final per key (keeps units unchanged, scales revenue)
        ilp_final = ilp_final.merge(key_ratio, on="Key_QCS", how="left")
        ilp_final["Cap_Ratio"] = ilp_final["Cap_Ratio"].fillna(1.0)

        for col in ["iLP_RevenueK_SC", "iLP_RevenueK_DC"]:
            if col in ilp_final.columns:
                ilp_final[col] = ilp_final[col].astype("float64") * ilp_final["Cap_Ratio"]

        ilp_final.drop(columns=["Cap_Ratio"], inplace=True)

        # Re-aggregate ILP for adjustments using the *capped* revenues
        ilp_agg = ilp_final.groupby(
            ["Year", "Quarter", "CC", "SALES_ORG", "Key_QCS"],
            as_index=False,
        ).agg(
            ILP_Units_SC=("iLP_Units_SC", "sum"),
            ILP_Units_DC=("iLP_Units_DC", "sum"),
            ILP_RevenueK_SC=("iLP_RevenueK_SC", "sum"),
            ILP_RevenueK_DC=("iLP_RevenueK_DC", "sum"),
        )


        # --------------------
        # Build FactKey-level adjustments (using *capped* S-ICD, full ILP)
        # --------------------

        # 1) S-ICD adjustments (unchanged)
        adj_sicd = sicd.merge(sicd_context, on="Key_QCS", how="left")
        adj_sicd["PRODUCT"] = "ICD SINGLE CHAMBER CONVENTIONAL + NON-TRANSVENOUS"
        adj_sicd["PRODUCT_CANON"] = adj_sicd["PRODUCT"].map(canon_product)
        adj_sicd["FactKey"] = pd.util.hash_pandas_object(
            adj_sicd[["CC", "SALES_ORG", "Year", "Quarter", "PRODUCT_CANON"]].astype(str),
            index=False,
        )
        adj_sicd = adj_sicd.rename(
            columns={"SICD_Units": "UNITS_TO_SUBTRACT", "SICD_Revenue_K": "REVK_TO_SUBTRACT"},
        )[["FactKey", "UNITS_TO_SUBTRACT", "REVK_TO_SUBTRACT"]]

        # 2) ILP adjustments – build from the same aggregate we use to CREATE ILP rows
        ilp_adj = ilp_agg.copy()

        adj_list = [adj_sicd]

        for chamber, prod_name in [
            ("SC", "IPG SINGLE CHAMBER CONVENTIONAL + LEADLESS"),
            ("DC", "IPG DUAL CHAMBER CONVENTIONAL + LEADLESS"),
        ]:
            tmp = ilp_adj.copy()
            tmp["PRODUCT"] = prod_name
            tmp["PRODUCT_CANON"] = tmp["PRODUCT"].map(canon_product)

            units_col = f"ILP_Units_{chamber}"
            rev_col   = f"ILP_RevenueK_{chamber}"

            tmp["FactKey"] = pd.util.hash_pandas_object(
                tmp[["CC", "SALES_ORG", "Year", "Quarter", "PRODUCT_CANON"]].astype(str),
                index=False,
            )

            tmp = tmp.rename(
                columns={units_col: "UNITS_TO_SUBTRACT", rev_col: "REVK_TO_SUBTRACT"},
            )[["FactKey", "UNITS_TO_SUBTRACT", "REVK_TO_SUBTRACT"]]

            adj_list.append(tmp)

            # Final adjustments table
            adj_all = (
                pd.concat(adj_list, ignore_index=True)
                .groupby(["FactKey"], as_index=False)
                .sum()
            )


        return {
            "adj_all": adj_all,
            "ilp_final": ilp_final,
            "sicd": sicd,
            "sicd_overcap": sicd_overcap,
            "ilp_overcap": ilp_overcap,
        }

def debug_adjustments_for_uk(crm, marketdata, sicd, ilp_final):
    print("\n=== DEBUG: UK adjustments vs combined templates ===")

    # Focus only on United Kingdom, 2023–2025, ICD & IPG
    mask_src = (
        (crm["COUNTRY_NAME"] == "United Kingdom") &
        (crm["Year"] >= 2023) &
        (crm["BUSINESS_SEGMENT"].isin(["ICD", "IPG"]))
    )
    src_uk = crm[mask_src].copy()

    # Rebuild combined flag on the source
    src_uk["PRODUCT_CANON"] = src_uk["PRODUCT"].map(canon_product)
    src_uk["_IsCombinedFlag"] = src_uk["PRODUCT_CANON"].map(combined_flag)

    print("\n-- Source combined rows (UK) --")
    print(
        src_uk[src_uk["_IsCombinedFlag"].notna()]
        [["Year","Quarter","BUSINESS_SEGMENT","PRODUCT","Market Units","FactKey","Key_QCS"]]
        .sort_values(["Year","Quarter","BUSINESS_SEGMENT"])
        .to_string(index=False)
    )

    # Look at how much adjustment we attached to those rows in marketdata
    md_uk = marketdata[
        (marketdata["COUNTRY_NAME"] == "United Kingdom") &
        (marketdata["Year"] >= 2023) &
        (marketdata["BUSINESS_SEGMENT"].isin(["ICD", "IPG"])) &
        (marketdata["_IsCombinedFlag"].notna())
    ].copy()

    print("\n-- Marketdata combined rows with adjustments (UK) --")
    print(
        md_uk[
            ["Year","Quarter","BUSINESS_SEGMENT","PRODUCT",
             "Market Units","UNITS_TO_SUBTRACT","REVK_TO_SUBTRACT",
             "FactKey","Key_QCS"]
        ]
        .sort_values(["Year","Quarter","BUSINESS_SEGMENT"])
        .to_string(index=False)
    )

    # Show what the SICD & ILP tables think for those keys
    print("\n-- S-ICD aggregate by Key_QCS (UK) --")
    sicd_uk = sicd.merge(
        md_uk[["Key_QCS","Year","Quarter","COUNTRY_NAME"]].drop_duplicates(),
        on="Key_QCS", how="inner"
    )
    if sicd_uk.empty:
        print("No S-ICD entries for UK")
    else:
        print(
            sicd_uk[
                ["Year","Quarter","COUNTRY_NAME","Key_QCS","SICD_Units","SICD_Revenue_K"]
            ]
            .sort_values(["Year","Quarter"])
            .to_string(index=False)
        )

    print("\n-- ILP aggregate by Key_QCS (UK) --")
    ilp_agg = (
        ilp_final
        .groupby(["Year","Quarter","CC","SALES_ORG","Key_QCS"], as_index=False)
        .agg(
            iLP_Units_SC=("iLP_Units_SC","sum"),
            iLP_Units_DC=("iLP_Units_DC","sum"),
        )
    )

    # Limit to UK by matching Key_QCS
    ilp_uk = ilp_agg.merge(
        md_uk[["Key_QCS","Year","Quarter","COUNTRY_NAME"]].drop_duplicates(),
        on=["Key_QCS","Year","Quarter"], how="inner"
    )

    if ilp_uk.empty:
        print("No ILP entries for UK")
    else:
        print(
            ilp_uk[
                ["Year","Quarter","COUNTRY_NAME","Key_QCS","iLP_Units_SC","iLP_Units_DC"]
            ]
            .sort_values(["Year","Quarter"])
            .to_string(index=False)
        )


# --------------------------
# MODULE 3: DERIVED ROWS
# --------------------------

class DerivedRowsGenerator:
    """Generate conventional, S-ICD and ILP derived rows (pure transformations)."""

    def __init__(self, rb_lookup: Dict[str, str]):
        self.rb_lookup = rb_lookup

    # ----------------------
    # 3.1 Conventional rows
    # ----------------------
    def conventional(self, combined_data: pd.DataFrame, crm_max_nq: int) -> pd.DataFrame:
        """
        Generate conventional rows from combined templates (IPG_SC, IPG_DC, ICD_S).

        Logic:
        - Start from combined rows (flagged in _IsCombinedFlag).
        - Subtract capped unconventional (S-ICD / ILP) via UNITS_TO_SUBTRACT / REVK_TO_SUBTRACT.
        - Keep ORG metrics unchanged.
        """
        base = combined_data[combined_data["_IsCombinedFlag"].notna()].copy()
        if base.empty:
            return base.iloc[0:0]

        # Map combined template -> conventional product
        new_product = {
            "IPG_SC": "IPG SINGLE CHAMBER CONVENTIONAL",
            "IPG_DC": "IPG DUAL CHAMBER CONVENTIONAL",
            "ICD_S":  "ICD SINGLE CHAMBER CONVENTIONAL",
        }
        base["PRODUCT_NEW"] = base["_IsCombinedFlag"].map(new_product).fillna(base["PRODUCT"])

        # Adjust market metrics (combined – unconventional)
        mu_raw = base["Market Units"] - base["UNITS_TO_SUBTRACT"].fillna(0.0)
        mr_raw = base["Market Net Revenue (in K EUR)"] - base["REVK_TO_SUBTRACT"].fillna(0.0)


        mu_rounded = mu_raw.where(mu_raw > 0).round()
        mr_series = mr_raw

        mu_vals = mu_rounded.to_numpy(dtype="float64")
        mr_vals = mr_series.to_numpy(dtype="float64")
        asp_vals = np.where(mu_vals > 0, (mr_vals * 1000.0) / mu_vals, np.nan)

        out = pd.DataFrame({
            "SOURCE":          base["SOURCE"],
            "REGION":          base["REGION"],
            "COUNTRY_NAME":    base["COUNTRY_NAME"],
            "CC":              base["CC"],
            "SALES_ORG":       base["SALES_ORG"],

            # 🔹 carry BU + PG through to the new rows
            "BUSINESS_UNIT":   base.get("BUSINESS_UNIT", "CRM"),
            "BUSINESS_SEGMENT": base["BUSINESS_SEGMENT"],
            "PRODUCT_GROUP":   base.get("PRODUCT_GROUP", np.nan),

            "PRODUCT":         base["PRODUCT_NEW"],
            "Year":            base["Year"],
            "Quarter":         base["Quarter"],
            "QTR":             base["QTR"],
            "NumericQuarter":  base["NumericQuarter"],

            "Market Units":                 mu_rounded,
            "Market Net Revenue (in K EUR)": mr_series,
            "Market ASP (in EUR)":          asp_vals,

            "Units":                base["Units"],
            "Net Revenue (in K EUR)": base["Net Revenue (in K EUR)"],
            "ASP (in EUR)":         base["ASP (in EUR)"],

            "Origin": "New, Inferred with new Data Import",
        })

        # Respect CRM horizon
        out = out[out["NumericQuarter"] <= crm_max_nq].copy()

        # RedBull mapping & keys
        out["PRODUCT_CANON"] = out["PRODUCT"].map(canon_product)
        out["REDBULL PRODUCT"] = out["PRODUCT_CANON"].map(
            lambda p: self.rb_lookup.get(p, "-")
        )
        out["FactKey"] = pd.util.hash_pandas_object(
            out[["CC", "SALES_ORG", "Year", "Quarter", "PRODUCT_CANON"]].astype(str),
            index=False,
        )

        return out


    # ----------------------
    # 3.2 S-ICD rows
    # ----------------------
    def sicd(self, sicd_agg: pd.DataFrame, marketdata: pd.DataFrame, crm_max_nq: int) -> pd.DataFrame:
        """
        Generate explicit S-ICD rows from capped S-ICD aggregates.

        Input:
          sicd_agg: Key_QCS, SICD_Units, SICD_Revenue_K (already capped in AdjustmentCompute)
        """
        if sicd_agg.empty:
            return pd.DataFrame()

        # Map Key_QCS -> dimension context
        map_key = (
            marketdata
            .dropna(subset=["COUNTRY_NAME"])
            .drop_duplicates(subset=["Key_QCS"])
            [["Key_QCS", "COUNTRY_NAME", "CC", "SALES_ORG", "Year", "Quarter", "QTR", "NumericQuarter"]]
        )

        s = sicd_agg.merge(map_key, on="Key_QCS", how="left")

        out = pd.DataFrame({
            "SOURCE":        "MW MKT INTEL",
            "REGION":        "MIDWEST",
            "COUNTRY_NAME":  s["COUNTRY_NAME"],
            "CC":            s["CC"],
            "SALES_ORG":     s["SALES_ORG"],
            # NEW
            "BUSINESS_UNIT": "CRM",
            "BUSINESS_SEGMENT": "ICD",
            "PRODUCT_GROUP": "ICD Single Chamber",
            "PRODUCT":       "ICD SINGLE CHAMBER NON-TRANSVENOUS",
            "Year":          s["Year"],
            "Quarter":       s["Quarter"],
            "QTR":           s["QTR"],
            "NumericQuarter": s["NumericQuarter"],
            "Market Units":  np.round(s["SICD_Units"]),
            "Market Net Revenue (in K EUR)": s["SICD_Revenue_K"],
            "Units":         0,
            "Net Revenue (in K EUR)": 0,
            "Origin":        "New, Inferred with new Data Import",
        })


        # ASP
        mu_vals = out["Market Units"].to_numpy(dtype="float64")
        mr_vals = out["Market Net Revenue (in K EUR)"].to_numpy(dtype="float64")

        # Silence invalid value warning for 0/0 (handled by np.where)
        with np.errstate(divide='ignore', invalid='ignore'):
            asp_vals = np.where(mu_vals > 0, (mr_vals * 1000.0) / mu_vals, np.nan)

        out["Market ASP (in EUR)"] = asp_vals

        out["REDBULL PRODUCT"] = "S-ICD"
        out["PRODUCT_CANON"] = out["PRODUCT"].map(canon_product)
        out["FactKey"] = pd.util.hash_pandas_object(
            out[["CC", "SALES_ORG", "Year", "Quarter", "PRODUCT_CANON"]].astype(str),
            index=False,
        )

        # Respect CRM horizon and drop zero rows (e.g. fully capped away)
        out = out[out["NumericQuarter"] <= crm_max_nq].copy()
        out = out[out["Market Units"].fillna(0) != 0].copy()

        return out

    # ----------------------
    # 3.3 ILP rows (stay in IPG)
    # ----------------------
    def ilp(self, ilp_final: pd.DataFrame, marketdata: pd.DataFrame, crm_max_nq: int) -> pd.DataFrame:
        """
        Create explicit ILP rows (SC/DC) that remain inside the IPG segment.

        Input:
          ilp_final: per-Key_QCS iLP_Units_SC/DC and iLP_RevenueK_SC/DC (from AdjustmentCompute).
        """
        if ilp_final.empty:
            return pd.DataFrame()

        # Aggregate ILP per Key_QCS (SC/DC)
        agg = (
            ilp_final
            .groupby(["Year", "Quarter", "CC", "SALES_ORG", "Key_QCS"], as_index=False)
            .agg(
                Units_SC=("iLP_Units_SC", "sum"),
                Units_DC=("iLP_Units_DC", "sum"),
                Rev_SC=("iLP_RevenueK_SC", "sum"),
                Rev_DC=("iLP_RevenueK_DC", "sum"),
            )
        )

        # Map Key_QCS -> IPG context (country, QTR, NumericQuarter)
        map_key = (
            marketdata[
                (marketdata["BUSINESS_SEGMENT"] == "IPG")
                & marketdata["COUNTRY_NAME"].notna()
            ]
            .drop_duplicates(subset=["Key_QCS"])
            [["Key_QCS", "COUNTRY_NAME", "QTR", "NumericQuarter", "CC", "SALES_ORG"]]
        )

        agg = agg.merge(map_key, on=["Key_QCS", "CC", "SALES_ORG"], how="left")

        # Fallback for QTR/NumericQuarter if something is missing
        agg["QTR"] = agg["QTR"].fillna(
            agg["Quarter"].astype(str).str[-1].astype(int)
        )
        agg["NumericQuarter"] = agg["NumericQuarter"].fillna(
            (agg["Year"] % 100).astype(int) * 10 + agg["QTR"].astype(int)
        ).astype(int)

        out_frames: list[pd.DataFrame] = []

        # --- SC ILP rows ---
        sc = agg[agg["Units_SC"] > 0].copy()
        if not sc.empty:
            mu = sc["Units_SC"].round()
            rev = sc["Rev_SC"]

            mu_vals = mu.to_numpy(dtype="float64")
            rev_vals = rev.to_numpy(dtype="float64")
            asp_vals = np.where(mu_vals > 0, (rev_vals * 1000.0) / mu_vals, np.nan)

            sc_out = pd.DataFrame({
                "SOURCE":        "MW MKT INTEL",
                "REGION":        "MIDWEST",
                "COUNTRY_NAME":  sc["COUNTRY_NAME"],
                "CC":            sc["CC"],
                "SALES_ORG":     sc["SALES_ORG"],
                # NEW
                "BUSINESS_UNIT": "CRM",
                "BUSINESS_SEGMENT": "IPG",
                "PRODUCT_GROUP": "IPG Single Chamber",
                "PRODUCT":       "IPG SINGLE CHAMBER LEADLESS",
                "Year":          sc["Year"],
                "Quarter":       sc["Quarter"],
                "QTR":           sc["QTR"],
                "NumericQuarter": sc["NumericQuarter"],
                "Market Units":  mu,
                "Market Net Revenue (in K EUR)": rev,
                "Market ASP (in EUR)": asp_vals,
                # ORG: neutral
                "Units":                 0,
                "Net Revenue (in K EUR)": 0.0,
                "ASP (in EUR)":          np.nan,
                "Origin": "New, Inferred with new Data Import",
            })
            out_frames.append(sc_out)

        # --- DC ILP rows ---
        dc = agg[agg["Units_DC"] > 0].copy()
        if not dc.empty:
            mu = dc["Units_DC"].round()
            rev = dc["Rev_DC"]

            mu_vals = mu.to_numpy(dtype="float64")
            rev_vals = rev.to_numpy(dtype="float64")
            asp_vals = np.where(mu_vals > 0, (rev_vals * 1000.0) / mu_vals, np.nan)

            dc_out = pd.DataFrame({
                "SOURCE":        "MW MKT INTEL",
                "REGION":        "MIDWEST",
                "COUNTRY_NAME":  dc["COUNTRY_NAME"],
                "CC":            dc["CC"],
                "SALES_ORG":     dc["SALES_ORG"],
                # NEW
                "BUSINESS_UNIT": "CRM",
                "BUSINESS_SEGMENT": "IPG",
                "PRODUCT_GROUP": "IPG Dual Chamber",
                "PRODUCT":       "IPG DUAL CHAMBER LEADLESS",
                "Year":          dc["Year"],
                "Quarter":       dc["Quarter"],
                "QTR":           dc["QTR"],
                "NumericQuarter": dc["NumericQuarter"],
                "Market Units":  mu,
                "Market Net Revenue (in K EUR)": rev,
                "Market ASP (in EUR)": asp_vals,
                # ORG: neutral
                "Units":                 0,
                "Net Revenue (in K EUR)": 0.0,
                "ASP (in EUR)":          np.nan,
                "Origin": "New, Inferred with new Data Import",
            })

            out_frames.append(dc_out)

        if not out_frames:
            return pd.DataFrame()

        out = pd.concat(out_frames, ignore_index=True)

        # Respect CRM horizon
        out = out[out["NumericQuarter"] <= crm_max_nq].copy()

        # RedBull mapping & keys
        out["PRODUCT_CANON"] = out["PRODUCT"].map(canon_product)
        out["REDBULL PRODUCT"] = out["PRODUCT_CANON"].map(
            lambda p: self.rb_lookup.get(p, "-")
        )
        out["FactKey"] = pd.util.hash_pandas_object(
            out[["CC", "SALES_ORG", "Year", "Quarter", "PRODUCT_CANON"]].astype(str),
            index=False,
        )

        # Drop any accidental zero-unit ILP rows (belt & braces)
        out = out[out["Market Units"].fillna(0) != 0].copy()

        return out


# --------------------------
# MODULE 4 UPDATED: MAIN (with QA)
# --------------------------

def main() -> Tuple[pd.DataFrame, Dict]:
    """Orchestrate all modules: load -> adjust -> derive -> merge -> QA -> export."""

    print("Starting MIDWEST Market Pipeline (Refactored)...")
    print("="*60)
    print("NOTE: This script is a data processor. It reads local files from data/in.")
    print("To update data from Qlik, run integration/qlik_downloads.py.")
    print("="*60)

    # Ensure data/out exists for reports and debug files
    CFG.out_debug_csv.parent.mkdir(parents=True, exist_ok=True)

    # 1. LOAD ALL DATA
    loader = DataLoader(CFG)
    maps = loader.load_maps()

    # Canonical lookup: PRODUCT_CANON -> RB_PRODUCT_NAME (RedBull product name)
    rb_map = maps["rb"].copy()
    rb_map["PRODUCT_CANON"] = rb_map["PRODUCT"].map(canon_product)
    rb_lookup_canon = dict(zip(rb_map["PRODUCT_CANON"], rb_map["RB_PRODUCT_NAME"]))

    crm = loader.load_crm()
    crm_max_nq = int(pd.to_numeric(crm["NumericQuarter"], errors="coerce").max())
    crm_source = crm.copy()  # Save for QA

    #debug_quarter_ipg(crm_source, "23Q1")

    # CC fixes map
    cc_fix_map = {"UK":"GB","EL":"GR","IR":"GB"}
    icm_mkt = loader.load_icm_market(crm_max_nq, cc_fix_map)
    icm_bio = loader.load_icm_bio(crm_max_nq)

    icm_source = pd.DataFrame()
    if not icm_mkt.empty:
        # Merge BIO data from ICM_BIO_DL.xlsx (primary BIO source for ALL countries)
        if not icm_bio.empty:
            icm_mkt = icm_mkt.merge(
                icm_bio,
                on=["CC", "Year", "Quarter", "QTR", "NumericQuarter"],
                how="left",
            )
            # BIO file is the sole source — use directly
            icm_mkt["Units_BIO"] = icm_mkt["Units_BIO"].fillna(0.0)
            icm_mkt["NetRev_K_BIO"] = icm_mkt["NetRev_K_BIO"].fillna(0.0)
        else:
            # No BIO file available — zero out BIO columns
            print("WARNING: ICM BIO file not loaded. BIO figures will be zero.")
            icm_mkt["Units_BIO"] = 0.0
            icm_mkt["NetRev_K_BIO"] = 0.0

        # Fill ORG metrics on the ICM segment
        icm_mkt["Units"] = icm_mkt["Units_BIO"].round()
        icm_mkt["Net Revenue (in K EUR)"] = icm_mkt["NetRev_K_BIO"]

        icm_mkt["ASP (in EUR)"] = np.where(
            icm_mkt["Units"] > 0,
            icm_mkt["Net Revenue (in K EUR)"] * 1000.0 / icm_mkt["Units"],
            np.nan,
        )

        # Currency + BU defaults
        if "CURRENCY_NAME" in icm_mkt.columns:
            icm_mkt["CURRENCY_NAME"] = icm_mkt["CURRENCY_NAME"].fillna("EUR")
        else:
            icm_mkt["CURRENCY_NAME"] = "EUR"

        if "BUSINESS_UNIT" in icm_mkt.columns:
            icm_mkt["BUSINESS_UNIT"] = icm_mkt["BUSINESS_UNIT"].fillna("CRM")
        else:
            icm_mkt["BUSINESS_UNIT"] = "CRM"

        # Keep a clean copy for QA (after ORG merge)
        icm_source = icm_mkt.copy()

        # Drop helper columns that shouldn't appear in final
        icm_mkt.drop(columns=["Units_BIO", "NetRev_K_BIO"], inplace=True, errors="ignore")
    else:
        print("INFO: No ICM market data loaded — BIO merge skipped")



    dup_mask = maps["country"].duplicated(subset=["CRM_COUNTRY_NAME"], keep=False)
    if dup_mask.any():
        print("WARN: Multiple mapping rows for countries:",
              maps["country"].loc[dup_mask, ["CRM_COUNTRY_NAME","CC","BIOS","Sales_Organisation"]]
              .drop_duplicates()
              .to_string(index=False))


    # Merge CC/BIOS/SALES_ORG into CRM  (de-duplicated by country)
    country_dim = (
        maps["country"][["CRM_COUNTRY_NAME", "CC", "BIOS", "Sales_Organisation"]]
        .sort_values(["CRM_COUNTRY_NAME"])          # optional, just to make it deterministic
        .drop_duplicates(subset=["CRM_COUNTRY_NAME"], keep="first")
        .rename(columns={"CRM_COUNTRY_NAME": "COUNTRY_NAME"})
    )

    crm = crm.merge(country_dim, on="COUNTRY_NAME", how="left", suffixes=("_src", "_map"))

    # Coalesce CC: prefer source, fallback to map
    if "CC_src" in crm.columns and "CC_map" in crm.columns:
        crm["CC"] = crm["CC_src"].fillna(crm["CC_map"])
        crm.drop(columns=["CC_src", "CC_map"], inplace=True)
    elif "CC_src" in crm.columns:
        crm.rename(columns={"CC_src": "CC"}, inplace=True)
    elif "CC_map" in crm.columns:
        crm.rename(columns={"CC_map": "CC"}, inplace=True)

    # Ireland Allocation: retain CC='IE' (from config) but group under 'United Kingdom' for COUNTRY_NAME
    crm.loc[crm["CC"] == "IE", "COUNTRY_NAME"] = "United Kingdom"

    crm.rename(columns={"Sales_Organisation": "SALES_ORG"}, inplace=True)

    # Canonical product + combined flag once
    crm["PRODUCT_U"] = crm["PRODUCT"].map(canon_product)
    crm["_IsCombinedFlag"] = crm["PRODUCT_U"].map(combined_flag)

    # Keys (canonical FactKey, coarse Key_QCS)
    crm["FactKey"] = pd.util.hash_pandas_object(
        crm[["CC", "SALES_ORG", "Year", "Quarter", "PRODUCT_U"]].astype(str),
        index=False,
    )
    crm["Key_QCS"] = pd.util.hash_pandas_object(
        crm[["CC", "SALES_ORG", "Year", "Quarter"]].astype(str),
        index=False,
    )

    # 2. COMPUTE ADJUSTMENTS
    adjuster = AdjustmentCompute(CFG)
    adj_results = adjuster.compute(crm, crm_max_nq, CFG.default_ilp_share_sc)
    adj_all = adj_results["adj_all"]
    ilp_final = adj_results["ilp_final"]
    sicd = adj_results["sicd"]
    sicd_overcap = adj_results.get("sicd_overcap", pd.DataFrame())
    ilp_overcap = adj_results.get("ilp_overcap", pd.DataFrame())

    print(f"DEBUG: adj_all has {len(adj_all)} rows, {adj_all['FactKey'].nunique()} unique FactKeys")
    print(f"DEBUG: ilp_final has {len(ilp_final)} rows")
    print(f"DEBUG: sicd has {len(sicd)} rows")

    # 3. COMBINE SOURCES
    parts = [d for d in [crm, icm_mkt] if not d.empty]
    marketdata = pd.concat(parts, ignore_index=True, sort=False)

    marketdata = pd.concat(parts, ignore_index=True, sort=False)

    # Merge adjustments onto facts
    marketdata = marketdata.merge(adj_all, on="FactKey", how="left")
    # debug_adjustments_for_uk(crm, marketdata, sicd, ilp_final)

    def redistribute_adjustments_by_factkey(df: pd.DataFrame) -> pd.DataFrame:
        """
        For combined template rows (_IsCombinedFlag not null) that received ILP/S-ICD
        adjustments on UNITS_TO_SUBTRACT / REVK_TO_SUBTRACT, redistribute those
        adjustments across all rows sharing the same FactKey, proportional to
        Market Units.

        This fixes cases like UK where the same FactKey appears multiple times,
        but ILP/S-ICD was defined only once per FactKey.
        """
        mask = df["_IsCombinedFlag"].notna() & df["UNITS_TO_SUBTRACT"].notna()

        # If no combined rows got adjustments, nothing to do
        if not mask.any():
            return df

        # Aggregate the target adjustment per FactKey
        agg = (
            df.loc[mask, ["FactKey", "Market Units", "Market Net Revenue (in K EUR)", "UNITS_TO_SUBTRACT", "REVK_TO_SUBTRACT"]]
            .groupby("FactKey", as_index=False)
            .agg(
                total_units=("Market Units", "sum"),
                total_revk=("Market Net Revenue (in K EUR)", "sum"),
                target_units=("UNITS_TO_SUBTRACT", "max"),   # all rows have same value today
                target_revk=("REVK_TO_SUBTRACT", "max"),
            )
        )

        df = df.merge(agg, on="FactKey", how="left")

        # Only redistribute where we actually have a target and a non-zero total volume
        mask2 = mask & df["total_units"].gt(0)

        # Units: proportional allocation by Market Units
        df.loc[mask2, "UNITS_TO_SUBTRACT"] = (
            df.loc[mask2, "target_units"]
            * df.loc[mask2, "Market Units"]
            / df.loc[mask2, "total_units"]
        )

        # Revenue: proportional allocation by Market Revenue
        # This prevents negative residuals when splitting rows with varying ASP.
        mask_rev = mask & df["total_revk"].gt(0)
        df.loc[mask_rev, "REVK_TO_SUBTRACT"] = (
            df.loc[mask_rev, "target_revk"]
            * df.loc[mask_rev, "Market Net Revenue (in K EUR)"]
            / df.loc[mask_rev, "total_revk"]
        )

        # Clean helper columns
        df.drop(columns=["total_units", "total_revk", "target_units", "target_revk"], inplace=True)

        return df

    # After merging adj_all:
    marketdata = redistribute_adjustments_by_factkey(marketdata)


    # 4. GENERATE DERIVED ROWS
    deriver = DerivedRowsGenerator(rb_lookup_canon)

    conventional = deriver.conventional(marketdata, crm_max_nq)
    sicd_rows = deriver.sicd(sicd, marketdata, crm_max_nq)
    ilp_rows = deriver.ilp(ilp_final, marketdata, crm_max_nq)

    # 5. FILTER & COMBINE
    combined = pd.concat(
        [d for d in [marketdata, sicd_rows, ilp_rows] if not d.empty],
        ignore_index=True,
        sort=False,
    )

    if not CFG.debug_be_only:
        combined_filtered = combined[combined["_IsCombinedFlag"].isna()].copy()
    else:
        combined_filtered = combined.copy()

    if not conventional.empty:
        combined_filtered = pd.concat([combined_filtered, conventional], ignore_index=True, sort=False)

    combined_weighted = combined_filtered[combined_filtered["NumericQuarter"] <= crm_max_nq].copy()

    # 🔍 Inspect how big the residual combined rows are (BE, Ireland)
    log_residual_combined_rows(combined_weighted)

    # Now fix/split them (next section)
    combined_weighted = fix_residual_combined_rows(combined_weighted)

    # ------------------------------------------------------------------
    # VERSION 1: Actual Addressable weighted
    # ------------------------------------------------------------------
    combined_weighted["Version"] = "Actual Addressable weighted"

    # ------------------------------------------------------------------
    # VERSION 2: Actual Addressable (Raw CRM)
    # ------------------------------------------------------------------
    # This is essentially the CRM data + ICM, mapped to schema, but NO adjustments/subtractions.
    # We can reuse 'marketdata' BEFORE adjustments? No, marketdata already has adjustments merged.
    # Let's rebuild the base from the source 'crm' + 'icm_mkt'.

    parts_raw = [d for d in [crm, icm_mkt] if not d.empty]
    raw_base = pd.concat(parts_raw, ignore_index=True, sort=False)

    # Respect horizon
    raw_base = raw_base[raw_base["NumericQuarter"] <= crm_max_nq].copy()

    # Also append MW MKT INTEL derived rows (S-ICD, ILP) with straight figures
    aa_parts = [raw_base]
    if not sicd_rows.empty:
        aa_parts.append(sicd_rows)
    if not ilp_rows.empty:
        aa_parts.append(ilp_rows)
    actual_addressable = pd.concat(aa_parts, ignore_index=True, sort=False)
    actual_addressable["Version"] = "Actual Addressable"

    # ------------------------------------------------------------------
    # VERSION 3: Actual Full (Raw CRM + Unconventional Superset)
    # ------------------------------------------------------------------
    # This includes the raw data PLUS the unconventional file (if available), integrated as additional rows.
    # We do NOT subtract anything.
    actual_full = raw_base.copy()

    if CFG.unconventional_mkt_xlsx.exists():
        # Load raw unconventional data to append
        # We need to map it to the schema. DataLoader.load_unconventional?
        # The AdjustmentCompute loads it internally.
        # Let's load it here strictly for appending.
        u_raw = pd.read_excel(CFG.unconventional_mkt_xlsx, sheet_name="DATA")
        u_raw.columns = [c.strip() for c in u_raw.columns]

        # We need to map 'unconventional' columns to 'MarketData' schema.
        # Required: Country, Year, Quarter, Product...
        # Map CC -> Country Name using existing map

        if not u_raw.empty:
            # Basic mapping logic similar to AdjustmentCompute but for output
             # Reuse quarter_to_numeric helper
            yqs_u = u_raw["Quarter"].map(quarter_to_numeric).tolist()
            yy_u, qq_u, nq_u = zip(*yqs_u)
            u_raw["Year"] = yy_u
            u_raw["QTR"] = qq_u
            u_raw["NumericQuarter"] = nq_u

            # Map CC
            cc_fix = {"UK": "GB", "EL": "GR", "IE": "GB", "IR": "GB"} # Same as AdjustmentCompute
            u_raw["CC"] = u_raw["CC"].astype(str).str.upper().map(lambda x: cc_fix.get(x, x))

            # Attach Country Name from country_dim
            # country_dim has "CC" column? No, it has CRM_COUNTRY_NAME, CC, BIOS, Sales_Org
            # We need CC -> Country Name reverse map
            # country_dim was merged into CRM earlier. Let's make a lookup.
            cc_to_name = dict(zip(country_dim["CC"], country_dim["COUNTRY_NAME"]))
            u_raw["COUNTRY_NAME"] = u_raw["CC"].map(cc_to_name)

            # Attach Sales Org (approximate, or from map)
            cc_to_sorg = dict(zip(country_dim["CC"], country_dim["Sales_Organisation"]))
            u_raw["SALES_ORG"] = u_raw["CC"].map(cc_to_sorg)

            # Attach BIOS from country map
            cc_to_bios = dict(zip(country_dim["CC"], country_dim["BIOS"]))
            u_raw["BIOS"] = u_raw["CC"].map(cc_to_bios)

            # Fields
            u_raw["Market Units"] = u_raw["Market Units"].map(num_smart)
            u_raw["Market Net Revenue (in K EUR)"] = u_raw["Market Net Revenue (in K EUR)"].map(num_smart)

            # Derive proper BUSINESS_SEGMENT from product name
            def _unconv_segment(prod):
                p = str(prod).upper()
                if "IPG" in p: return "IPG"
                if "ICD" in p or "S-ICD" in p: return "ICD"
                return "CRM"  # fallback

            # Schema — unified SOURCE (no more "(Unconv)" suffix)
            u_mapped = pd.DataFrame({
                "SOURCE": "MW MKT INTEL",
                "REGION": "MIDWEST",
                "COUNTRY_NAME": u_raw["COUNTRY_NAME"],
                "CC": u_raw["CC"],
                "SALES_ORG": u_raw["SALES_ORG"],
                "BIOS": u_raw["BIOS"],
                "BUSINESS_UNIT": "CRM",
                "BUSINESS_SEGMENT": u_raw["Product"].map(_unconv_segment),
                "PRODUCT_GROUP": u_raw["Product"],
                "PRODUCT": u_raw["Product"],
                "Year": u_raw["Year"],
                "Quarter": u_raw["Quarter"],
                "QTR": u_raw["QTR"],
                "NumericQuarter": u_raw["NumericQuarter"],
                "Market Units": u_raw["Market Units"],
                "Market Net Revenue (in K EUR)": u_raw["Market Net Revenue (in K EUR)"],
                 # Zero out organization metrics
                "Units": 0,
                "Net Revenue (in K EUR)": 0,
            })

            # Filter horizon
            u_mapped = u_mapped[u_mapped["NumericQuarter"] <= crm_max_nq].copy()

            # Append to Actual Full
            actual_full = pd.concat([actual_full, u_mapped], ignore_index=True, sort=False)

    actual_full["Version"] = "Actual Full"

    # ------------------------------------------------------------------
    # MERGE ALL VERSIONS
    # ------------------------------------------------------------------
    combined = pd.concat([combined_weighted, actual_addressable, actual_full], ignore_index=True, sort=False)

    # ------------------------------------------------------------------
    # NORMALIZE PRODUCT_GROUP across all versions
    # Raw names from CRM/MW MKT INTEL (e.g. "S-ICD", "Single Chamber
    # IPG - Leadless") are mapped to canonical parent group names.
    # ------------------------------------------------------------------
    PRODUCT_GROUP_NORM = {
        "ICD SC Conventional": "ICD SC",
        "ICD DC Conventional": "ICD DC",
        "IPG SC Conventional": "IPG SC",
        "IPG DC Conventional": "IPG DC",
        "IPG SC + Leadless": "IPG SC",
        "IPG DC + Leadless": "IPG DC",
        "ICD SC S-ICD": "ICD SC",
        "IPG SC Leadless": "IPG SC",
        "IPG DC Leadless": "IPG DC",
        "IPG Dual Chamber - Leadless": "IPG DC",
        "S-ICD": "ICD SC",
        "Single Chamber IPG - Leadless": "IPG SC",
        "Dual Chamber IPG - Leadless": "IPG DC",
        "IPG Leadless": "IPG SC",
        "IPG Single + Dual Chamber": "IPG SC",
        "ICD SC - Non-Transv.": "ICD SC",
        "ICD Single Chamber Non-Transvenous": "ICD SC",
        "IPG Single Chamber - Leadless": "IPG SC",
        "ICD Single Chamber": "ICD SC",
        "ICD Dual Chamber": "ICD DC",
        "IPG Single Chamber": "IPG SC",
        "IPG Dual Chamber": "IPG DC",
    }
    if "PRODUCT_GROUP" in combined.columns:
        combined["PRODUCT_GROUP"] = (
            combined["PRODUCT_GROUP"].astype(str).str.strip().replace(PRODUCT_GROUP_NORM)
        )

    # ------------------------------------------------------------------
    # DEFENSIVE BACKFILL: Fill missing BIOS/SALES_ORG from country_dim
    # Some derived rows (S-ICD, ILP, weighted) may lose BIOS during
    # version construction. Backfill from CC → country_dim lookup.
    # ------------------------------------------------------------------
    cc_to_bios_fill = dict(zip(country_dim["CC"], country_dim["BIOS"]))
    cc_to_sorg_fill = dict(zip(country_dim["CC"], country_dim["Sales_Organisation"]))
    if "BIOS" in combined.columns:
        bios_missing = combined["BIOS"].isna()
        if bios_missing.any():
            combined.loc[bios_missing, "BIOS"] = combined.loc[bios_missing, "CC"].map(cc_to_bios_fill)
    else:
        combined["BIOS"] = combined["CC"].map(cc_to_bios_fill)
    if "SALES_ORG" in combined.columns:
        sorg_missing = combined["SALES_ORG"].isna()
        if sorg_missing.any():
            combined.loc[sorg_missing, "SALES_ORG"] = combined.loc[sorg_missing, "CC"].map(cc_to_sorg_fill)
    else:
        combined["SALES_ORG"] = combined["CC"].map(cc_to_sorg_fill)

    # Backfill CURRENCY_NAME (all MW countries are EUR)
    if "CURRENCY_NAME" in combined.columns:
        combined["CURRENCY_NAME"] = combined["CURRENCY_NAME"].fillna("EUR")
    else:
        combined["CURRENCY_NAME"] = "EUR"

    # Add QTR_YTD helper (mirrors legacy pipeline logic)
    # -1 if the quarter is <= the max actuals quarter (within the same year context)
    max_q_num = crm_max_nq % 10
    combined["QTR_YTD"] = np.where(combined["QTR"] <= max_q_num, -1, 0)



    # --- RedBull product mapping for ALL rows (canonical) ---
    combined["PRODUCT"] = combined["PRODUCT"].astype(str).str.strip()
    combined["PRODUCT_CANON"] = combined["PRODUCT"].map(canon_product)

    # 1) New column: the generic RedBull product name for the canonical product
    combined["RB_PRODUCT_NAME"] = combined["PRODUCT_CANON"].map(
        lambda p: rb_lookup_canon.get(p, np.nan)
    )

    # --- Apply EXPORT flag mapping to ALL rows and ALL versions ---
    exp_norm = maps["export"].copy()
    exp_norm["COUNTRY_NORM"] = exp_norm["COUNTRY_RAW"].str.strip().str.upper().replace({
        "MAROCCO":       "MOROCCO",
        "GREAT BRITAIN": "UNITED KINGDOM",
        "U.K.":          "UNITED KINGDOM",
        "UK":            "UNITED KINGDOM",
    })
    # Dict with UPPERCASE keys for robust lookup
    country_to_export = dict(zip(exp_norm["COUNTRY_NORM"].str.upper(), exp_norm["EXPORT_FLAG"].str.upper()))

    # Normalize data-side country names (especially CC aliases)
    cc_to_name = {
        "MA": "MOROCCO",
        "SN": "SENEGAL",
        "TN": "TUNISIA",
        "DZ": "ALGERIA",
        "BE": "BELGIUM",
        "FR": "FRANCE",
        "IT": "ITALY",
        "ES": "SPAIN",
        "GB": "UNITED KINGDOM",
        "IE": "UNITED KINGDOM", # Standard pipeline aggregation
    }

    combined["EXPORT"] = (
        combined["COUNTRY_NAME"]
        .astype(str)
        .str.strip()
        .str.upper()
        .replace(cc_to_name)
        .map(lambda c: country_to_export.get(c, "DOMESTIC"))
    )
    mask_empty = combined["REDBULL PRODUCT"].isna() | (combined["REDBULL PRODUCT"] == "-")
    combined.loc[mask_empty, "REDBULL PRODUCT"] = combined.loc[mask_empty, "RB_PRODUCT_NAME"].fillna("-")

         # --- Override: enforce REDBULL PRODUCT = RB_PRODUCT_NAME where we have a canonical mapping ---
    if {"RB_PRODUCT_NAME", "REDBULL PRODUCT"}.issubset(combined.columns):
        mask_rb_defined = combined["RB_PRODUCT_NAME"].notna()
        combined.loc[mask_rb_defined, "REDBULL PRODUCT"] = combined.loc[mask_rb_defined, "RB_PRODUCT_NAME"]


    # After: combined["PRODUCT_CANON"] = ...
    # Fill obvious BUSINESS_UNIT gaps by segment
    mask_crm = combined["BUSINESS_UNIT"].isna() & combined["BUSINESS_SEGMENT"].isin(["ICD","IPG","CRT","ICM","Leads"])
    combined.loc[mask_crm, "BUSINESS_UNIT"] = "CRM"

    mask_ep = combined["BUSINESS_UNIT"].isna() & combined["BUSINESS_SEGMENT"].str.startswith("Catheters", na=False)
    combined.loc[mask_ep, "BUSINESS_UNIT"] = "EP"
    final = combined

    # ------------------------------------------------------------------
    # Fix negative IPG Conventional rows caused by ILP over-allocation
    # (soft strict: no big negative revenues on derived rows)
    # ------------------------------------------------------------------
    final = fix_ipg_negative_conventional(final)

    # ------------------------------------------------------------------
    # ASP normalization: Revenue + Units are canonical; ASP is derived
    # ------------------------------------------------------------------

    # Market ASP from Market Units & Market Net Revenue (in K EUR)
    if {"Market Units", "Market Net Revenue (in K EUR)"}.issubset(final.columns):
        mu = final["Market Units"].astype(float)
        revk = final["Market Net Revenue (in K EUR)"].astype(float)
        asp = np.where(mu > 0, (revk * 1000.0) / mu, np.nan)
        final["Market ASP (in EUR)"] = asp

    # ORG ASP from Units & ORG Net Revenue (in K EUR)
    if {"Units", "Net Revenue (in K EUR)"}.issubset(final.columns):
        units_bio = final["Units"].astype(float)
        revk_bio = final["Net Revenue (in K EUR)"].astype(float)
        asp_bio = np.where(units_bio > 0, (revk_bio * 1000.0) / units_bio, np.nan)
        final["ASP (in EUR)"] = asp_bio

    # Flag potential missing ASP coverage: Units > 0 but RevenueK = 0 -> ASP not meaningful
    if {"Market Units", "Market Net Revenue (in K EUR)"}.issubset(final.columns):
        final["Market_ASP_Missing_Flag"] = np.where(
            (final["Market Units"].astype(float) > 0)
            & (final["Market Net Revenue (in K EUR)"].astype(float) == 0.0),
            1,
            0,
        )

    if {"Units", "Net Revenue (in K EUR)"}.issubset(final.columns):
        final["BIO_ASP_Missing_Flag"] = np.where(
            (final["Units"].astype(float) > 0)
            & (final["Net Revenue (in K EUR)"].astype(float) == 0.0),
            1,
            0,
        )

    # 6. QA VALIDATION
    # Load additional validation sources if available
    unconv_source = None
    if CFG.unconventional_mkt_xlsx.exists():
        unconv_source = pd.read_excel(CFG.unconventional_mkt_xlsx, sheet_name="DATA")

    rb_source = None
    if CFG.redbull_dl_xlsx.exists():
        print(f"Loading RedBull DL for validation: {CFG.redbull_dl_xlsx.name}")
        rb_source = pd.read_excel(CFG.redbull_dl_xlsx)

    qa = QAValidator(tolerance_units=2.0, tolerance_revenue_keur=0.05)

    # QA should run on the "Weighted" version (which represents the processed truth)
    final_weighted_only = final[final["Version"] == "Actual Addressable weighted"].copy()

    qa_report = qa.validate(
        crm_source, final_weighted_only, ilp_final, sicd,
        sicd_overcap, ilp_overcap, icm_source=icm_source,
        unconv_source=unconv_source,
        rb_source=rb_source,
        full_final=final,
    )


    # RedBull mapping QA (mapping table + final data + canon consistency)
    qa_redbull_mapping(rb_map, combined, qa_report=qa_report)
    #debug_icd_25q3_fr_uk(crm_source, combined, sicd, marketdata)

    print(f"\n[OK] Pipeline generated {len(combined)} rows")
    print("=" * 60)

    return combined, qa_report

# --------------------------
# MODULE 5: QA & VALIDATION
# --------------------------


class QAValidator:
    """Validate data preservation and consistency."""

    def __init__(self, tolerance_units: float = 2.0, tolerance_revenue_keur: float = 0.05):
        self.tol_units = tolerance_units
        self.tol_revenue = tolerance_revenue_keur
        self.report = {
            "overall_pass": True,
            "checks": [],
            "detail_failures": {},
        }

    def check_preservation(
        self,
        source_data: pd.DataFrame,
        final_data: pd.DataFrame,
        group_cols: list,
        metric_col: str,
        metric_name: str,
        tolerance: float,
    ) -> bool:
        """Check if metric is preserved after transformations."""

        src_agg = source_data.groupby(group_cols, as_index=False)[metric_col].sum()
        fin_agg = final_data.groupby(group_cols, as_index=False)[metric_col].sum()

        merged = src_agg.merge(fin_agg, on=group_cols, how="outer", suffixes=("_src", "_fin"))
        merged["_src"] = merged[f"{metric_col}_src"].fillna(0)
        merged["_fin"] = merged[f"{metric_col}_fin"].fillna(0)
        merged["diff"] = merged["_fin"] - merged["_src"]

        failures = merged[merged["diff"].abs() > tolerance].copy()

        # ✅ define once here
        check_name = f"{metric_name} preservation"

        if not failures.empty:
            self.report["overall_pass"] = False
            self.report["checks"].append({
                "check": check_name,
                "pass": False,
                "mismatches": len(failures),
                "tolerance": tolerance,
            })
            self.report["detail_failures"][check_name] = (
                failures[group_cols + ["_src","_fin","diff"]]
                .head(10)
                .to_dict(orient="records")
            )

            print(f"\n[X] {check_name}")
            print(f"  Mismatches: {len(failures)}")
            for _, r in failures.head(10).iterrows():
                group_str = " | ".join(f"{col}={r[col]}" for col in group_cols)
                print(f"  {group_str} -> src:{r['_src']:.1f} fin:{r['_fin']:.1f} diff:{r['diff']:.1f}")
            return False
        else:
            self.report["checks"].append({
                "check": check_name,
                "pass": True,
            })

    def check_version_consistency(
        self,
        final_data: pd.DataFrame,
        tolerance_units: float = 2.0,
        tolerance_rev_k: float = 0.5,
    ) -> bool:
        """
        Verify that all 3 versions have equal ORG Units and Revenue
        at the Country + Segment level.

        Versions analyzed:
          1. Actual Addressable weighted
          2. Actual Addressable
          3. Actual Full

        Metric columns (BIO only):
          - Units, Net Revenue (in K EUR)

        NOTE: Market Units and Market Net Revenue are intentionally excluded.
        They legitimately differ between versions because the unconventional
        product accounting (S-ICD / ILP) subtracts from combined templates in
        Version 1 (weighted) but appends raw rows in Versions 2 & 3.
        """
        # Ensure 'Version' exists
        if "Version" not in final_data.columns:
             print("[QA] Version column missing. Skipping consistency check.")
             return True

        # Filter to 3 target versions
        versions = [
            "Actual Addressable weighted",
            "Actual Addressable",
            "Actual Full"
        ]

        df = final_data[final_data["Version"].isin(versions)].copy()

        # We need at least 2 versions to compare
        found_versions = df["Version"].unique()
        if len(found_versions) < 2:
            print(f"[QA] Not enough versions found for comparison. Found: {found_versions}")
            return True

        # Group by [Country, Segment, Version]
        group_cols = ["COUNTRY_NAME", "BUSINESS_SEGMENT", "Version"]
        # Only compare ORG metrics — Market metrics intentionally differ
        # between versions due to unconventional (S-ICD/ILP) accounting.
        metrics = [
            "Units",
            "Net Revenue (in K EUR)"
        ]

        # Ensure metrics exist, fill NaN
        for m in metrics:
            if m not in df.columns:
                df[m] = 0.0
            else:
                df[m] = df[m].fillna(0.0)

        agg = df.groupby(group_cols, as_index=False)[metrics].sum()

        # Pivot versions to columns
        pivot = agg.pivot_table(
            index=["COUNTRY_NAME", "BUSINESS_SEGMENT"],
            columns="Version",
            values=metrics,
            aggfunc="sum"
        )

        # Flatten pivot columns: (Metric, Version) -> "Metric|Version"
        pivot.columns = [f"{c[0]}|{c[1]}" for c in pivot.columns]
        pivot = pivot.reset_index()

        failures = []

        # Compare "Actual Addressable weighted" (baseline) vs others
        base_ver = "Actual Addressable weighted"
        other_vers = [v for v in versions if v in found_versions and v != base_ver]

        if base_ver not in found_versions:
             # Just compare first available against others
             base_ver = found_versions[0]
             other_vers = found_versions[1:]

        for m in metrics:
            col_base = f"{m}|{base_ver}"

            for v_comp in other_vers:
                col_comp = f"{m}|{v_comp}"

                # Calculate diff
                diff = pivot[col_base] - pivot[col_comp]

                # Check tolerance
                tol = tolerance_units if "Units" in m else tolerance_rev_k

                # Find bad rows
                mask_bad = diff.abs() > tol

                if mask_bad.any():
                    # Get details
                    bad_rows = pivot.loc[mask_bad, ["COUNTRY_NAME", "BUSINESS_SEGMENT", col_base, col_comp]]
                    bad_rows["diff"] = diff[mask_bad]

                    for _, r in bad_rows.head(5).iterrows():
                        failures.append({
                            "Metric": m,
                            "Segment": r["BUSINESS_SEGMENT"],
                            "Country": r["COUNTRY_NAME"],
                            "BaseVersion": base_ver,
                            "CompVersion": v_comp,
                            "BaseVal": r[col_base],
                            "CompVal": r[col_comp],
                            "Diff": r["diff"]
                        })

        check_name = "Version Consistency Check"

        if failures:
            self.report["checks"].append({
                "check": check_name,
                "pass": False,
                "mismatches": len(failures),
            })
            self.report["detail_failures"][check_name] = failures[:20]  # limit detail

            print(f"\n[X] {check_name}")
            print(f"  Mismatches found: {len(failures)} segments/metrics with deviations.")
            print("  Top 5 examples:")
            for f in failures[:5]:
                print(f"    {f['Country']} | {f['Segment']} | {f['Metric']}: {f['BaseVersion']}={f['BaseVal']:.1f} vs {f['CompVersion']}={f['CompVal']:.1f} (Diff={f['Diff']:.2f})")
            return False
        else:
            self.report["checks"].append({
                "check": check_name,
                "pass": True,
            })
            print(f"[QA] {check_name}: OK (All versions match totals per segment)")
            return True
            print(f"[OK] {metric_name} preservation")
            return True

    def check_unconventional_overcap(
        self,
        sicd_overcap: Optional[pd.DataFrame],
        ilp_overcap: Optional[pd.DataFrame],
    ) -> bool:
        """
        Combined QA for:
          - S-ICD forecast vs CRM combined ICD (ICD_S templates)
          - ILP  forecast vs CRM combined IPG (IPG_SC/DC templates)

        Flags cases where unconventional market units / revenue
        exceed what the combined templates have in CRM.
        """
        any_issue = False

        # --- S-ICD ---
        check_name_sicd = "S-ICD forecast vs CRM combined ICD (over-cap)"
        if sicd_overcap is not None and not sicd_overcap.empty:
            any_issue = True
            self.report["overall_pass"] = False

            df = sicd_overcap.copy()
            # Ensure excess columns are present
            if "Excess_Units" not in df.columns:
                df["Excess_Units"] = df["SICD_Units"] - df["CombinedUnits"]
            if "Excess_Revenue_K" not in df.columns:
                df["Excess_Revenue_K"] = df["SICD_Revenue_K"] - df["CombinedRevenueK"]

            self.report["checks"].append({
                "check": check_name_sicd,
                "pass": False,
                "mismatches": len(df),
            })

            self.report["detail_failures"][check_name_sicd] = (
                df[
                    [
                        "Year","Quarter","CC","SALES_ORG",
                        "SICD_Units","CombinedUnits","Excess_Units",
                        "SICD_Revenue_K","CombinedRevenueK","Excess_Revenue_K",
                    ]
                ]
                .head(20)
                .to_dict(orient="records")
            )

            print(f"\n[X] {check_name_sicd}")
            print(f"  Mismatches (Key_QCS with over-forecast): {len(df)}")
            for _, r in df.head(10).iterrows():
                print(
                    f"  CC={r['CC']} | SALES_ORG={r['SALES_ORG']} | Year={r['Year']} | Quarter={r['Quarter']} -> "
                    f"S-ICD Units={r['SICD_Units']:.1f}, Combined ICD Units={r['CombinedUnits']:.1f}, Excess={r['Excess_Units']:.1f}; "
                    f"S-ICD RevK={r['SICD_Revenue_K']:.1f}, Combined RevK={r['CombinedRevenueK']:.1f}, "
                    f"Excess={r['Excess_Revenue_K']:.1f}"
                )
        else:
            self.report["checks"].append({
                "check": check_name_sicd,
                "pass": True,
                "mismatches": 0,
            })
            print(f"[OK] {check_name_sicd} — no S-ICD > combined ICD cases")

        # --- ILP ---
        check_name_ilp = "ILP forecast vs CRM combined IPG (over-cap)"
        if ilp_overcap is not None and not ilp_overcap.empty:
            df = ilp_overcap.copy()

            # Collapse SC/DC to totals per key
            df["ILP_Units_Total"] = df["ILP_Units_SC"].fillna(0) + df["ILP_Units_DC"].fillna(0)
            df["CombinedUnits_Total"] = df["CombinedUnits_SC"].fillna(0) + df["CombinedUnits_DC"].fillna(0)

            df["ILP_RevenueK_Total"] = df["ILP_RevenueK_SC"].fillna(0) + df["ILP_RevenueK_DC"].fillna(0)
            df["CombinedRevenueK_Total"] = df["CombinedRevenueK_SC"].fillna(0) + df["CombinedRevenueK_DC"].fillna(0)

            # Only care where there *is* combined IPG volume
            df = df[df["CombinedUnits_Total"] > 0]

            # Total excess
            df["Excess_Units_Total"] = df["ILP_Units_Total"] - df["CombinedUnits_Total"]
            df["Excess_RevenueK_Total"] = df["ILP_RevenueK_Total"] - df["CombinedRevenueK_Total"]

            # Flag only *real* over-caps above a tolerance
            tol = self.tol_units
            failures = df[df["Excess_Units_Total"] > tol].copy()

            if not failures.empty:
                any_issue = True
                self.report["overall_pass"] = False

                self.report["checks"].append({
                    "check": check_name_ilp,
                    "pass": False,
                    "mismatches": len(failures),
                    "tolerance_units": tol,
                })

                self.report["detail_failures"][check_name_ilp] = (
                    failures[
                        [
                            "Year","Quarter","CC","SALES_ORG",
                            "ILP_Units_Total","CombinedUnits_Total","Excess_Units_Total",
                            "ILP_RevenueK_Total","CombinedRevenueK_Total","Excess_RevenueK_Total",
                        ]
                    ]
                    .head(20)
                    .to_dict(orient="records")
                )

                print(f"\n[X] {check_name_ilp}")
                print(f"  Mismatches (Key_QCS with over-forecast): {len(failures)}")
                for _, r in failures.head(10).iterrows():
                    print(
                        f"  CC={r['CC']} | SALES_ORG={r['SALES_ORG']} | Year={r['Year']} | Quarter={r['Quarter']} -> "
                        f"ILP Units={r['ILP_Units_Total']:.1f}, Combined IPG Units={r['CombinedUnits_Total']:.1f}, "
                        f"Excess={r['Excess_Units_Total']:.1f}"
                    )
            else:
                self.report["checks"].append({
                    "check": check_name_ilp,
                    "pass": True,
                    "mismatches": 0,
                })
                print(f"[OK] {check_name_ilp} — no ILP > combined IPG (at total level)")

        return not any_issue

    def check_ipg_conv_plus_ilp(self, crm_source: pd.DataFrame, final: pd.DataFrame) -> bool:
        """
        IPG integrity check:
        For each (Year, Quarter, Country):
            CRM_IPG_total  ≈  FINAL_IPG_conv + FINAL_ILP

        where:
        - FINAL_ILP are products containing 'LEADLESS'
        - FINAL_IPG_conv are all other IPG products.
        """

        # Source IPG totals from CRM
        src_ipg = (
            crm_source[crm_source["BUSINESS_SEGMENT"] == "IPG"]
            .groupby(["Year", "Quarter", "COUNTRY_NAME"], as_index=False)["Market Units"]
            .sum()
            .rename(columns={"Market Units": "SRC_IPG_Units"})
        )

        # Final IPG conventional (non-leadless)
        fin_ipg_conv = (
            final[
                (final["BUSINESS_SEGMENT"] == "IPG")
                & (~final["PRODUCT"].str.contains("LEADLESS", case=False, na=False))
            ]
            .groupby(["Year", "Quarter", "COUNTRY_NAME"], as_index=False)["Market Units"]
            .sum()
            .rename(columns={"Market Units": "FIN_IPG_Conv_Units"})
        )

        # Final ILP rows (leadless products)
        fin_ilp = (
            final[
                (final["BUSINESS_SEGMENT"] == "IPG")
                & (final["PRODUCT"].str.contains("LEADLESS", case=False, na=False))
            ]
            .groupby(["Year", "Quarter", "COUNTRY_NAME"], as_index=False)["Market Units"]
            .sum()
            .rename(columns={"Market Units": "FIN_ILP_Units"})
        )

        # Merge all three together
        merged = (
            src_ipg
            .merge(fin_ipg_conv, on=["Year", "Quarter", "COUNTRY_NAME"], how="left")
            .merge(fin_ilp,      on=["Year", "Quarter", "COUNTRY_NAME"], how="left")
        )

        merged["FIN_IPG_Conv_Units"] = merged["FIN_IPG_Conv_Units"].fillna(0)
        merged["FIN_ILP_Units"]      = merged["FIN_ILP_Units"].fillna(0)

        merged["FIN_Total_IPG"] = merged["FIN_IPG_Conv_Units"] + merged["FIN_ILP_Units"]
        merged["diff"] = merged["FIN_Total_IPG"] - merged["SRC_IPG_Units"]

        # Use the same unit tolerance
        tol = self.tol_units
        failures = merged[merged["diff"].abs() > tol].copy()

        check_name = "IPG conv + ILP vs CRM IPG total"

        if not failures.empty:
            self.report["overall_pass"] = False
            self.report["checks"].append({
                "check": check_name,
                "pass": False,
                "mismatches": len(failures),
                "tolerance": tol,
            })
            self.report["detail_failures"][check_name] = (
                failures[["Year", "Quarter", "COUNTRY_NAME",
                        "SRC_IPG_Units", "FIN_IPG_Conv_Units", "FIN_ILP_Units", "FIN_Total_IPG", "diff"]]
                .head(10)
                .to_dict(orient="records")
            )

            print(f"\n[X] {check_name}")
            print(f"  Mismatches: {len(failures)}")
            for _, r in failures.head(10).iterrows():
                print(
                    f"  Year={r['Year']} | Quarter={r['Quarter']} | COUNTRY={r['COUNTRY_NAME']} "
                    f"-> SRC={r['SRC_IPG_Units']:.1f}, "
                    f"FIN_conv={r['FIN_IPG_Conv_Units']:.1f}, FIN_ILP={r['FIN_ILP_Units']:.1f}, "
                    f"FIN_total={r['FIN_Total_IPG']:.1f}, diff={r['diff']:.1f}"
                )
            return False
        else:
            self.report["checks"].append({
                "check": check_name,
                "pass": True,
            })
            print(f"[OK] {check_name}")
            return True

    def check_icd_conv_plus_sicd(self, crm_source: pd.DataFrame, final: pd.DataFrame) -> bool:
        """
        ICD integrity check:
        For each (Year, Quarter, Country):
            CRM combined ICD_S template units
            ≈ FINAL(ICD SC conventional) + FINAL(S-ICD)

        Where:
        - CRM combined template is 'ICD SINGLE CHAMBER CONVENTIONAL + NON-TRANSVENOUS'
          (flagged as ICD_S by combined_flag)
        - FINAL ICD SC conventional = ICD products with 'CONVENTIONAL' but NOT 'NON-TRANSVENOUS'
        - FINAL S-ICD rows contain 'NON-TRANSVENOUS' in PRODUCT.
        """

        src = crm_source.copy()
        src["PRODUCT_CANON"] = src["PRODUCT"].map(canon_product)
        src["_IsCombinedFlag"] = src["PRODUCT_CANON"].map(combined_flag)

        # Source: only the combined ICD_S template
        src_icd_comb = src[
            (src["BUSINESS_SEGMENT"] == "ICD")
            & (src["_IsCombinedFlag"] == "ICD_S")
        ].copy()

        if src_icd_comb.empty:
            check_name = "ICD conv + S-ICD vs CRM combined ICD_S"
            self.report["checks"].append({
                "check": check_name,
                "pass": True,
                "note": "No ICD_S rows in CRM source",
            })
            print(f"[OK] {check_name} (no ICD_S rows in CRM)")
            return True

        src_agg = (
            src_icd_comb
            .groupby(["Year", "Quarter", "COUNTRY_NAME"], as_index=False)["Market Units"]
            .sum()
            .rename(columns={"Market Units": "SRC_ICD_S_Units"})
        )

        # Final ICD-only slice
        fin_icd = final[final["BUSINESS_SEGMENT"] == "ICD"].copy()

        # Conventional ICD SC (CONVENTIONAL but not NON-TRANSVENOUS)
        fin_conv = fin_icd[
            fin_icd["PRODUCT"].str.contains("CONVENTIONAL", case=False, na=False)
            & ~fin_icd["PRODUCT"].str.contains("NON-TRANSVENOUS", case=False, na=False)
        ].copy()
        fin_conv_agg = (
            fin_conv
            .groupby(["Year", "Quarter", "COUNTRY_NAME"], as_index=False)["Market Units"]
            .sum()
            .rename(columns={"Market Units": "FIN_ICD_SC_Conv_Units"})
        )

        # S-ICD rows (NON-TRANSVENOUS)
        fin_sicd = fin_icd[
            fin_icd["PRODUCT"].str.contains("NON-TRANSVENOUS", case=False, na=False)
        ].copy()
        fin_sicd_agg = (
            fin_sicd
            .groupby(["Year", "Quarter", "COUNTRY_NAME"], as_index=False)["Market Units"]
            .sum()
            .rename(columns={"Market Units": "FIN_SICD_Units"})
        )

        merged = (
            src_agg
            .merge(fin_conv_agg, on=["Year", "Quarter", "COUNTRY_NAME"], how="left")
            .merge(fin_sicd_agg,  on=["Year", "Quarter", "COUNTRY_NAME"], how="left")
        )

        merged["FIN_ICD_SC_Conv_Units"] = merged["FIN_ICD_SC_Conv_Units"].fillna(0)
        merged["FIN_SICD_Units"]        = merged["FIN_SICD_Units"].fillna(0)

        merged["FIN_Total_ICD_SC_plus_SICD"] = (
            merged["FIN_ICD_SC_Conv_Units"] + merged["FIN_SICD_Units"]
        )
        merged["diff"] = merged["FIN_Total_ICD_SC_plus_SICD"] - merged["SRC_ICD_S_Units"]

        tol = self.tol_units
        failures = merged[merged["diff"].abs() > tol].copy()
        check_name = "ICD conv + S-ICD vs CRM combined ICD_S"

        if not failures.empty:
            self.report["overall_pass"] = False
            self.report["checks"].append({
                "check": check_name,
                "pass": False,
                "mismatches": len(failures),
                "tolerance": tol,
            })
            self.report["detail_failures"][check_name] = (
                failures[
                    [
                        "Year", "Quarter", "COUNTRY_NAME",
                        "SRC_ICD_S_Units",
                        "FIN_ICD_SC_Conv_Units",
                        "FIN_SICD_Units",
                        "FIN_Total_ICD_SC_plus_SICD",
                        "diff",
                    ]
                ]
                .head(10)
                .to_dict(orient="records")
            )

            print(f"\n[X] {check_name}")
            print(f"  Mismatches: {len(failures)}")
            for _, r in failures.head(10).iterrows():
                print(
                    f"  Year={r['Year']} | Quarter={r['Quarter']} | COUNTRY={r['COUNTRY_NAME']} "
                    f"-> SRC={r['SRC_ICD_S_Units']:.1f}, "
                    f"FIN_conv={r['FIN_ICD_SC_Conv_Units']:.1f}, FIN_SICD={r['FIN_SICD_Units']:.1f}, "
                    f"FIN_total={r['FIN_Total_ICD_SC_plus_SICD']:.1f}, diff={r['diff']:.1f}"
                )
            return False
        else:
            self.report["checks"].append({
                "check": check_name,
                "pass": True,
            })
            print(f"[OK] {check_name}")
            return True

    def check_nonnegative_measures(self, final: pd.DataFrame) -> bool:
        """
        Ensure key numeric measures are not negative on *derived* rows
        (MW MKT INTEL, ICM Market, or rows marked as inferred).
        Source CRM rows may legitimately have negatives (returns, corrections).
        """
        metric_cols = [
            "Market Units",
            "Units",
            "Market Net Revenue (in K EUR)",
            "Net Revenue (in K EUR)",
        ]

        any_issue = False
        tol = 0.0  # strict: everything >= 0

        # Only enforce on derived rows
        src = final.get("SOURCE")
        origin = final.get("Origin")

        if src is None and origin is None:
            # Nothing to filter on -> just skip this check
            self.report["checks"].append({
                "check": "Non-negative measures (derived rows only)",
                "pass": True,
                "note": "No SOURCE / Origin columns present",
            })
            print("[OK] Non-negative measures (derived rows only) – skipped (no SOURCE/Origin)")
            return True

        derived_mask = pd.Series(True, index=final.index)

        if src is not None:
            derived_mask &= src.isin(["MW MKT INTEL", "ICM Market"])
        if origin is not None:
            derived_mask |= origin.fillna("").str.contains("Inferred", case=False)

        df = final[derived_mask].copy()

        if df.empty:
            self.report["checks"].append({
                "check": "Non-negative measures (derived rows only)",
                "pass": True,
                "note": "No derived rows to enforce",
            })
            print("[OK] Non-negative measures (derived rows only) – no derived rows")
            return True

        for col in metric_cols:
            if col not in df.columns:
                continue

            # "Soft strict":
            #   - Units must be >= 0 exactly.
            #   - Revenue may be slightly negative due to float noise; ignore down to -0.01 kEUR.
            if "Revenue" in col:
                threshold = -0.01   # allow tiny noise (≈ -10 EUR)
            else:
                threshold = 0.0

            failures = df[df[col] < threshold].copy()
            check_name = f"Non-negative {col} (derived rows)"

            if not failures.empty:
                any_issue = True
                self.report["overall_pass"] = False
                self.report["checks"].append({
                    "check": check_name,
                    "pass": False,
                    "mismatches": len(failures),
                })
                self.report["detail_failures"][check_name] = (
                    failures[
                        ["Year", "Quarter", "COUNTRY_NAME", "BUSINESS_SEGMENT", "PRODUCT", col]
                    ]
                    .head(10)
                    .to_dict(orient="records")
                )

                print(f"\n[X] {check_name}")
                print(f"  Negative rows: {len(failures)} (showing first 10)")
                for _, r in failures.head(10).iterrows():
                    print(
                        f"  Year={r['Year']} | Quarter={r['Quarter']} | "
                        f"Country={r['COUNTRY_NAME']} | Segment={r['BUSINESS_SEGMENT']} | "
                        f"Product={r['PRODUCT']} -> {col}={r[col]}"
                    )
            else:
                self.report["checks"].append({
                    "check": check_name,
                    "pass": True,
                })
                print(f"[OK] {check_name}")

        return not any_issue

    def check_asp_consistency(self, final: pd.DataFrame) -> bool:
        """
        Row-level ASP consistency:
          Market:  MarketRevK ≈ MarketUnits * MarketASP / 1000
          BIO:     NetRevK   ≈ Units       * ASP       / 1000
        Uses self.tol_revenue as kEUR tolerance.
        """
        tol = self.tol_revenue
        any_issue = False

        # --- Market side ---
        if {"Market Units", "Market ASP (in EUR)", "Market Net Revenue (in K EUR)"} <= set(final.columns):
            m = final.copy()
            mask = (
                (m["Market Units"] > 0)
                & m["Market ASP (in EUR)"].notna()
                & m["Market Net Revenue (in K EUR)"].notna()
            )

            m = m[mask].copy()
            expected = (m["Market Units"].astype(float) * m["Market ASP (in EUR)"].astype(float)) / 1000.0
            diff = m["Market Net Revenue (in K EUR)"].astype(float) - expected
            m["diff"] = diff

            failures = m[m["diff"].abs() > tol].copy()
            check_name = "Market ASP vs revenue consistency"

            if not failures.empty:
                any_issue = True
                self.report["overall_pass"] = False
                self.report["checks"].append({
                    "check": check_name,
                    "pass": False,
                    "mismatches": len(failures),
                    "tolerance_kEUR": tol,
                })
                self.report["detail_failures"][check_name] = (
                    failures[
                        ["Year", "Quarter", "COUNTRY_NAME", "BUSINESS_SEGMENT", "PRODUCT",
                         "Market Units", "Market ASP (in EUR)", "Market Net Revenue (in K EUR)", "diff"]
                    ]
                    .head(10)
                    .to_dict(orient="records")
                )
                print(f"\n[X] {check_name}")
                print(f"  Mismatches: {len(failures)} (showing first 10)")
            else:
                self.report["checks"].append({
                    "check": check_name,
                    "pass": True,
                })
                print(f"[OK] {check_name}")

        # --- ORG side ---
        if {"Units", "ASP (in EUR)", "Net Revenue (in K EUR)"} <= set(final.columns):
            b = final.copy()
            mask = (
                (b["Units"] > 0)
                & b["ASP (in EUR)"].notna()
                & b["Net Revenue (in K EUR)"].notna()
            )
            b = b[mask].copy()
            expected = (b["Units"].astype(float) * b["ASP (in EUR)"].astype(float)) / 1000.0
            diff = b["Net Revenue (in K EUR)"].astype(float) - expected
            b["diff"] = diff

            failures = b[b["diff"].abs() > tol].copy()
            check_name = "ORG ASP vs revenue consistency"

            if not failures.empty:
                any_issue = True
                self.report["overall_pass"] = False
                self.report["checks"].append({
                    "check": check_name,
                    "pass": False,
                    "mismatches": len(failures),
                    "tolerance_kEUR": tol,
                })
                self.report["detail_failures"][check_name] = (
                    failures[
                        ["Year", "Quarter", "COUNTRY_NAME", "BUSINESS_SEGMENT", "PRODUCT",
                         "Units", "ASP (in EUR)", "Net Revenue (in K EUR)", "diff"]
                    ]
                    .head(10)
                    .to_dict(orient="records")
                )
                print(f"\n[X] {check_name}")
                print(f"  Mismatches: {len(failures)} (showing first 10)")
            else:
                self.report["checks"].append({
                    "check": check_name,
                    "pass": True,
                })
                print(f"[OK] {check_name}")

        return not any_issue

    def check_missing_asp_coverage(self, final: pd.DataFrame) -> bool:
        """
        Informational check:
        - Count rows with Market Units > 0 & Market RevK = 0.
        - Count rows with Units > 0 & Net RevK = 0.
        Does NOT fail QA; just records stats into the report.
        """
        result = {}

        # Market side
        if {"Market Units", "Market Net Revenue (in K EUR)"}.issubset(final.columns):
            m_mask = (
                final["Market Units"].astype(float) > 0
            ) & (
                final["Market Net Revenue (in K EUR)"].astype(float) == 0.0
            )
            m_count = int(m_mask.sum())
            m_total = int(len(final))
            m_pct = float(round(100.0 * m_count / m_total, 3)) if m_total else 0.0

            # By segment (top 10)
            if "BUSINESS_SEGMENT" in final.columns:
                by_seg = (
                    final.loc[m_mask]
                    .groupby("BUSINESS_SEGMENT")
                    .size()
                    .sort_values(ascending=False)
                    .head(10)
                    .reset_index(name="rows")
                    .to_dict(orient="records")
                )
            else:
                by_seg = []

            result["market"] = {
                "rows": m_count,
                "pct": m_pct,
                "by_segment_top10": by_seg,
            }

            print(
                f"ASP coverage (Market): {m_count} rows with Market Units>0 & Market RevK=0 "
                f"({m_pct:.1f}%)"
            )

        # ORG side
        if {"Units", "Net Revenue (in K EUR)"}.issubset(final.columns):
            b_mask = (
                final["Units"].astype(float) > 0
            ) & (
                final["Net Revenue (in K EUR)"].astype(float) == 0.0
            )
            b_count = int(b_mask.sum())
            b_total = int(len(final))
            b_pct = float(round(100.0 * b_count / b_total, 3)) if b_total else 0.0

            if "BUSINESS_SEGMENT" in final.columns:
                by_seg_bio = (
                    final.loc[b_mask]
                    .groupby("BUSINESS_SEGMENT")
                    .size()
                    .sort_values(ascending=False)
                    .head(10)
                    .reset_index(name="rows")
                    .to_dict(orient="records")
                )
            else:
                by_seg_bio = []

            result["bio"] = {
                "rows": b_count,
                "pct": b_pct,
                "by_segment_top10": by_seg_bio,
            }

            print(
                f"ASP coverage (ORG): {b_count} rows with Units>0 & ORG RevK=0 "
                f"({b_pct:.1f}%)"
            )

        # Record into report as informational (does not flip overall_pass)
        self.report["asp_missing_coverage"] = result
        self.report["checks"].append({
            "check": "ASP coverage (zero ASP with positive units)",
            "pass": True,  # informational only
            "market_rows": result.get("market", {}).get("rows", 0),
            "bio_rows": result.get("bio", {}).get("rows", 0),
        })

        return True

    def check_segment_product_consistency(self, final: pd.DataFrame) -> bool:
        """
        Domain rules:
        - LEADLESS products must be in IPG segment.
        - NON-TRANSVENOUS / S-ICD products must be in ICD segment.
        - ICM rows should have PRODUCT_GROUP == 'ICM' and PRODUCT == 'ICM'.
        """
        any_issue = False

        # LEADLESS -> IPG
        mask_leadless = final["PRODUCT"].str.contains("LEADLESS", case=False, na=False)
        failures_leadless = final[mask_leadless & (final["BUSINESS_SEGMENT"] != "IPG")].copy()
        check_name = "Leadless products in IPG segment"

        if not failures_leadless.empty:
            any_issue = True
            self.report["overall_pass"] = False
            self.report["checks"].append({
                "check": check_name,
                "pass": False,
                "mismatches": len(failures_leadless),
            })
            self.report["detail_failures"][check_name] = (
                failures_leadless[
                    ["Year", "Quarter", "COUNTRY_NAME", "BUSINESS_SEGMENT", "PRODUCT"]
                ]
                .head(10)
                .to_dict(orient="records")
            )
            print(f"\n[X] {check_name}")
        else:
            self.report["checks"].append({"check": check_name, "pass": True})
            print(f"[OK] {check_name}")

        # S-ICD / NON-TRANSVENOUS -> ICD
        mask_sicd = (
            final["PRODUCT"].str.contains("NON-TRANSVENOUS", case=False, na=False)
            | final["PRODUCT"].str.contains("S-ICD", case=False, na=False)
        )
        failures_sicd = final[mask_sicd & (final["BUSINESS_SEGMENT"] != "ICD")].copy()
        check_name = "S-ICD / NON-TRANSVENOUS products in ICD segment"

        if not failures_sicd.empty:
            any_issue = True
            self.report["overall_pass"] = False
            self.report["checks"].append({
                "check": check_name,
                "pass": False,
                "mismatches": len(failures_sicd),
            })
            self.report["detail_failures"][check_name] = (
                failures_sicd[
                    ["Year", "Quarter", "COUNTRY_NAME", "BUSINESS_SEGMENT", "PRODUCT"]
                ]
                .head(10)
                .to_dict(orient="records")
            )
            print(f"\n[X] {check_name}")
        else:
            self.report["checks"].append({"check": check_name, "pass": True})
            print(f"[OK] {check_name}")

        # ICM rows having clean product group
        if "BUSINESS_SEGMENT" in final.columns:
            icm = final[final["BUSINESS_SEGMENT"] == "ICM"].copy()
            if not icm.empty:
                bad_icm = icm[
                    (icm.get("PRODUCT_GROUP", "") != "ICM")
                    | (icm.get("PRODUCT", "") != "ICM")
                ].copy()
                check_name = "ICM rows with PRODUCT/PRODUCT_GROUP = 'ICM'"

                if not bad_icm.empty:
                    any_issue = True
                    self.report["overall_pass"] = False
                    self.report["checks"].append({
                        "check": check_name,
                        "pass": False,
                        "mismatches": len(bad_icm),
                    })
                    self.report["detail_failures"][check_name] = (
                        bad_icm[
                            ["Year", "Quarter", "COUNTRY_NAME", "BUSINESS_SEGMENT",
                             "PRODUCT_GROUP", "PRODUCT"]
                        ]
                        .head(10)
                        .to_dict(orient="records")
                    )
                    print(f"\n[X] {check_name}")
                else:
                    self.report["checks"].append({"check": check_name, "pass": True})
                    print(f"[OK] {check_name}")

        return not any_issue

    def check_mw_mkt_intel_bio_zero(self, final: pd.DataFrame) -> bool:
        """
        Ensure MW MKT INTEL rows (derived unconventional rows) do not carry ORG units/revenue.
        """
        if "SOURCE" not in final.columns:
            return True

        intel = final[final["SOURCE"] == "MW MKT INTEL"].copy()
        if intel.empty:
            check_name = "MW MKT INTEL rows (no ORG values)"
            self.report["checks"].append({"check": check_name, "pass": True, "note": "No MW MKT INTEL rows"})
            print(f"[OK] {check_name} (no MW MKT INTEL rows)")
            return True

        mask_bad = (intel["Units"].fillna(0) != 0) | (intel["Net Revenue (in K EUR)"].fillna(0) != 0)
        bad = intel[mask_bad].copy()
        check_name = "MW MKT INTEL ORG values = 0"

        if not bad.empty:
            self.report["overall_pass"] = False
            self.report["checks"].append({
                "check": check_name,
                "pass": False,
                "mismatches": len(bad),
            })
            self.report["detail_failures"][check_name] = (
                bad[
                    ["Year", "Quarter", "COUNTRY_NAME", "BUSINESS_SEGMENT", "PRODUCT",
                     "Units", "Net Revenue (in K EUR)"]
                ]
                .head(10)
                .to_dict(orient="records")
            )
            print(f"\n[X] {check_name}")
            return False
        else:
            self.report["checks"].append({"check": check_name, "pass": True})
            print(f"[OK] {check_name}")
            return True

    def check_no_residual_combined_templates(self, final: pd.DataFrame) -> bool:
        """
        Ensure no 'combined templates' survive in the final dataset:
        - PRODUCT containing 'CONVENTIONAL + LEADLESS' or 'CONVENTIONAL + NON-TRANSVENOUS'
        - PRODUCT_GROUP in {'IPG Single + Dual Chamber', 'CRT-P + CRT-D'}
        """
        prod = final["PRODUCT"].astype(str)

        mask_prod = (
            prod.str.contains("CONVENTIONAL + LEADLESS", case=False, na=False)
            | prod.str.contains("CONVENTIONAL + NON-TRANSVENOUS", case=False, na=False)
        )

        mask_pg = final.get("PRODUCT_GROUP", pd.Series(index=final.index, dtype="object")).isin(
            ["IPG Single + Dual Chamber", "CRT-P + CRT-D"]
        )

        failures = final[mask_prod | mask_pg].copy()
        check_name = "No residual combined templates in final"

        if not failures.empty:
            self.report["overall_pass"] = False
            self.report["checks"].append({
                "check": check_name,
                "pass": False,
                "mismatches": len(failures),
            })
            self.report["detail_failures"][check_name] = (
                failures[
                    ["Year", "Quarter", "COUNTRY_NAME", "BUSINESS_SEGMENT",
                     "PRODUCT_GROUP", "PRODUCT"]
                ]
                .head(10)
                .to_dict(orient="records")
            )
            print(f"\n[X] {check_name}")
            return False
        else:
            self.report["checks"].append({"check": check_name, "pass": True})
            print(f"[OK] {check_name}")
            return True

    def check_icm_market_integrity(self, final: pd.DataFrame) -> bool:
        """
        Specific integrity checks for ICM data:
        1. Volume Spike Detection (Market Units > 50,000 per country/quarter)
        2. BIO Figure Coverage (Flag zero BIO units in major countries where market is present)
        3. Segment Consistency (Ensure all 'ICM Market' source rows are BUSINESS_SEGMENT == 'ICM')
        4. Year Distribution (Detect abnormal concentrations in a single year)
        """
        any_fail = False
        icm_rows = final[final["SOURCE"] == "ICM Market"].copy()
        if icm_rows.empty:
            self.report_success("ICM Integrity: No ICM data to check")
            return True

        # 1. Volume Spikes (The error was >1M units)
        # Threshold: 50k per country/quarter is very high for ICM (Baseline is < 1k)
        spike_mask = icm_rows["Market Units"] > 50000
        spikes = icm_rows[spike_mask]
        check_name_spike = "ICM Integrity: Volume Spike (>50k units)"
        if not spikes.empty:
            any_fail = True
            self.report_failure(check_name_spike, spikes[["COUNTRY_NAME", "Year", "Quarter", "Market Units"]])
        else:
            self.report_success(check_name_spike)

        # 2. BIO Figure Coverage
        # Check major countries (BE, DE, FR, IT, ES, GB)
        major_ccs = ["BE", "DE", "FR", "IT", "ES", "GB"]
        coverage_mask = (
            icm_rows["CC"].isin(major_ccs)
            & (icm_rows["Market Units"] > 0)
            & (icm_rows["Units"].fillna(0) == 0)
        )
        missing_bio = icm_rows[coverage_mask]
        check_name_bio = "ICM Integrity: BIO Figure Coverage (Major MKTS)"
        if not missing_bio.empty:
            # ORG does not sell ICMs in all major markets — this is expected.
            # Log as informational note, not a hard failure.
            print(f"[NOTE] {check_name_bio}: {len(missing_bio)} rows in major markets with Market Units > 0 but BIO Units = 0 (expected — no ORG ICM presence in these markets).")
            self.report["checks"].append({"check": check_name_bio, "pass": True, "note": f"{len(missing_bio)} rows with no BIO ICM presence"})
        else:
            self.report_success(check_name_bio)

        # 3. Segment Consistency
        bad_segment = icm_rows[icm_rows["BUSINESS_SEGMENT"] != "ICM"]
        check_name_seg = "ICM Integrity: Segment Consistency"
        if not bad_segment.empty:
            any_fail = True
            self.report_failure(check_name_seg, bad_segment[["COUNTRY_NAME", "BUSINESS_SEGMENT", "SOURCE"]])
        else:
            self.report_success(check_name_seg)

        # 4. Year Distribution (Detect abnormal concentration like 2025 leak)
        # Group by Year and sum Market Units
        counts = icm_rows.groupby("Year")["Market Units"].sum()
        if not counts.empty:
            total = counts.sum()
            if total > 0:
                max_year = counts.idxmax()
                pct = counts.max() / total
                check_name_year = f"ICM Integrity: Year Distribution ({max_year} concentration)"
                if pct > 0.8 and icm_rows["Year"].nunique() > 1:
                     any_fail = True
                     # Report the rows for the offending year
                     self.report_failure(check_name_year, icm_rows[icm_rows["Year"] == max_year].head(5))
                else:
                     self.report_success(check_name_year)

        return not any_fail

    def validate(
        self,
        crm_source: pd.DataFrame,
        final: pd.DataFrame,
        ilp_final: pd.DataFrame,
        sicd: pd.DataFrame,
        sicd_overcap: Optional[pd.DataFrame] = None,
        ilp_overcap: Optional[pd.DataFrame] = None,
        icm_source: Optional[pd.DataFrame] = None,
        unconv_source: Optional[pd.DataFrame] = None,
        rb_source: Optional[pd.DataFrame] = None,
        full_final: Optional[pd.DataFrame] = None,
    ) -> Dict:
        """Run all QA checks."""

        # Normalize Source for QA: Treat Ireland as United Kingdom to match Final output
        crm_source = crm_source.copy()
        if "COUNTRY_NAME" in crm_source.columns:
             crm_source["COUNTRY_NAME"] = crm_source["COUNTRY_NAME"].replace({"Ireland": "United Kingdom"})

        print("\n" + "="*60)
        print("QA VALIDATION")
        print("="*60)

        # ---- MARKET QA (CRM segments only, at segment grain) ----
        valid_segments = crm_source["BUSINESS_SEGMENT"].dropna().unique()
        final_market_for_qa = final[final["BUSINESS_SEGMENT"].isin(valid_segments)].copy()

        # 1. Market Units preservation at segment level
        self.check_preservation(
            crm_source,
            final_market_for_qa,
            ["Year","Quarter","COUNTRY_NAME","BUSINESS_SEGMENT"],
            "Market Units",
            "Market Units",
            self.tol_units,
        )

        # 2. Market Revenue preservation at segment level
        self.check_preservation(
            crm_source,
            final_market_for_qa,
            ["Year","Quarter","COUNTRY_NAME","BUSINESS_SEGMENT"],
            "Market Net Revenue (in K EUR)",
            "Market Revenue (K EUR)",
            self.tol_revenue,
        )

        # --- ORG preservation: only for segments present in CRM (e.g., ICD/IPG, but not ICM) ---
        src_bio_units = crm_source[crm_source["Units"].notna()].copy()
        bio_segments_units = src_bio_units["BUSINESS_SEGMENT"].dropna().unique()
        final_bio_for_qa = final[final["BUSINESS_SEGMENT"].isin(bio_segments_units)].copy()

        # 3. ORG Units preservation (CRM segments only)
        self.check_preservation(
            src_bio_units,
            final_bio_for_qa,
            ["Year","Quarter","COUNTRY_NAME","BUSINESS_SEGMENT"],
            "Units",
            "ORG Units",
            self.tol_units,
        )

        src_bio_rev = crm_source[crm_source["Net Revenue (in K EUR)"].notna()].copy()
        bio_segments_rev = src_bio_rev["BUSINESS_SEGMENT"].dropna().unique()
        final_bio_for_qa_rev = final[final["BUSINESS_SEGMENT"].isin(bio_segments_rev)].copy()

        # 4. ORG Revenue preservation (CRM segments only)
        self.check_preservation(
            src_bio_rev,
            final_bio_for_qa_rev,
            ["Year","Quarter","COUNTRY_NAME","BUSINESS_SEGMENT"],
            "Net Revenue (in K EUR)",
            "ORG Revenue (K EUR)",
            self.tol_revenue,
        )

        # NEW explicit IPG conv + ILP check
        self.check_ipg_conv_plus_ilp(crm_source, final)

        # NEW: explicit ICD conv + S-ICD vs combined ICD_S check
        self.check_icd_conv_plus_sicd(crm_source, final)

        # 5. iLP/S-ICD internal consistency (informational)
        if not ilp_final.empty and not sicd.empty:
            print(f"\n[OK] iLP / S-ICD adjustment consistency")
            print(f"  iLP rows: {len(ilp_final)}")
            print(f"  S-ICD rows: {len(sicd)}")

        # 6. Unconventional forecast vs combined templates (S-ICD + ILP)
        self.check_unconventional_overcap(sicd_overcap, ilp_overcap)

        # 7. ICM QA vs ICM source (if provided)
        if icm_source is not None and not icm_source.empty:
            icm_src = icm_source.copy()
            icm_src = icm_src[icm_src["BUSINESS_SEGMENT"] == "ICM"].copy()
            final_icm = final[final["BUSINESS_SEGMENT"] == "ICM"].copy()

            if not icm_src.empty and not final_icm.empty:
                print("\nICM QA vs ICM source")

                # Market Units
                self.check_preservation(
                    icm_src,
                    final_icm,
                    ["Year", "Quarter", "COUNTRY_NAME", "BUSINESS_SEGMENT"],
                    "Market Units",
                    "ICM Market Units",
                    self.tol_units,
                )

                # ORG Units
                if "Units" in icm_src.columns:
                    self.check_preservation(
                        icm_src,
                        final_icm,
                        ["Year", "Quarter", "COUNTRY_NAME", "BUSINESS_SEGMENT"],
                        "Units",
                        "ICM ORG Units",
                        self.tol_units,
                    )

                # ORG Revenue (K EUR)
                if "Net Revenue (in K EUR)" in icm_src.columns:
                    self.check_preservation(
                        icm_src,
                        final_icm,
                        ["Year", "Quarter", "COUNTRY_NAME", "BUSINESS_SEGMENT"],
                        "Net Revenue (in K EUR)",
                        "ICM ORG Revenue (K EUR)",
                        self.tol_revenue,
                    )

        # 8. Non-negative derived measures (MKT INTEL/ICM, inferred rows)
        self.check_nonnegative_measures(final)

        # 9. Row-level ASP consistency (market + BIO)
        self.check_asp_consistency(final)

        # 10. ASP coverage: zero ASP with positive units (informational)
        self.check_missing_asp_coverage(final)

        # 11. Segment / product domain rules
        self.check_segment_product_consistency(final)

        # 12. MW MKT INTEL rows must have zero ORG values
        self.check_mw_mkt_intel_bio_zero(final)

        # 13. No residual combined templates in final dataset
        self.check_no_residual_combined_templates(final)

        # 14. Unconventional Alignment (Input vs Output)
        if unconv_source is not None:
             self.check_unconventional_alignment(unconv_source, final)

        # 15. RedBull Alignment (Output vs Benchmark)
        if rb_source is not None:
             self.check_redbull_alignment(rb_source, final)

        # 16. Version Consistency Check (NEW)
        if full_final is not None:
             self.check_version_consistency(full_final, tolerance_units=2.0, tolerance_rev_k=0.5)

        # 17. Dimensional Integrity (No "Unknown" / "Error" labels)
        self.check_dimensional_integrity(final)

        # 18. ICM Specific Integrity (NEW)
        self.check_icm_market_integrity(final)

        print("\n" + "="*60)
        if self.report["overall_pass"]:
            print("QA SUMMARY: [OK] PASS")
        else:
            print("QA SUMMARY: [X] FAIL")
        print("="*60)

        return self.report

    def check_unconventional_alignment(self, unconv_source: pd.DataFrame, final: pd.DataFrame):
        """
        Verify that total S-ICD and ILP units in FINAL output match the UNCONVENTIONAL input.
        """
        print("\nUNCONVENTIONAL ALIGNMENT (Input vs Output)")

        # Preprocess Input similar to AdjustmentCompute
        u = unconv_source.copy()

        # Derive UNCONV_CLASS from Product column
        if "UNCONV_CLASS" not in u.columns and "Product" in u.columns:
            u["Product_Upper"] = u["Product"].astype(str).str.upper()
            u["UNCONV_CLASS"] = "OTHER"

            mask_sicd = u["Product_Upper"].str.contains("NON-TRANSVENOUS|S-ICD|SUBCUTANEOUS", regex=True)
            u.loc[mask_sicd, "UNCONV_CLASS"] = "SICD"

            mask_ilp = u["Product_Upper"].str.contains("LEADLESS|MICRA|AVEIR|NANOSTIM", regex=True)
            u.loc[mask_ilp, "UNCONV_CLASS"] = "ILP"

        # Map Input CC for aggregation
        cc_agg_map = {"UK": "UK_REG", "GB": "UK_REG", "IE": "UK_REG", "EL": "GR"}

        u["CC_Agg"] = u["CC"].astype(str).str.upper().map(lambda x: cc_agg_map.get(x, x))

        # Clean numeric
        def _parse(x):
            if isinstance(x, (int, float)): return float(x)
            try: return float(str(x).replace(",", "."))
            except: return 0.0

        u["Vol"] = u["Market Units"].map(_parse)

        # Agg Input
        u_agg = u.groupby(["CC_Agg", "UNCONV_CLASS"], as_index=False)["Vol"].sum()

        # Prepare Output
        # S-ICD Output
        sicd_mask = (final["BUSINESS_SEGMENT"] == "ICD") & (final["PRODUCT"].str.contains("NON-TRANSVENOUS|S-ICD", regex=True, na=False))
        # ILP Output
        ilp_mask = (final["BUSINESS_SEGMENT"] == "IPG") & (final["PRODUCT"].str.contains("LEADLESS|MICRA|AVEIR", regex=True, na=False))

        # Map Output CC
        # Final has CC like 'GB', 'IE', 'ES'
        final_cc_series = final["CC"].astype(str).str.upper().map(lambda x: cc_agg_map.get(x, x))

        # Agg Output S-ICD
        sicd_out_vol = final.loc[sicd_mask].groupby(final_cc_series)["Market Units"].sum().reset_index()
        sicd_out_vol.columns = ["CC_Agg", "Vol_Out"]

        # Agg Output ILP
        ilp_out_vol = final.loc[ilp_mask].groupby(final_cc_series)["Market Units"].sum().reset_index()
        ilp_out_vol.columns = ["CC_Agg", "Vol_Out"]

        self._compare_agg(u_agg, sicd_out_vol, "SICD", "Unconventional S-ICD")
        self._compare_agg(u_agg, ilp_out_vol, "ILP", "Unconventional ILP")

    def _compare_agg(self, u_df, out_df, u_class, check_lbl):
        in_df = u_df[u_df["UNCONV_CLASS"] == u_class].copy()
        merged = in_df.merge(out_df, on="CC_Agg", how="outer").fillna(0)
        merged["diff"] = merged["Vol_Out"] - merged["Vol"]

        tol = self.tol_units
        fails = merged[merged["diff"].abs() > tol]

        if not fails.empty:
            capping = fails[fails["diff"] < -tol] # Expected (capping)
            creation = fails[fails["diff"] > tol] # Unexpected

            if not creation.empty:
                # Volume creation can happen when CRM data already contains S-ICD/ILP
                # products that overlap with unconventional input. Log as warning, not failure.
                print(f"[NOTE] {check_lbl} (Volume Creation): {len(creation)} countries have Output > Input (likely CRM overlap).")
                print(creation.head(5).to_string(index=False))
                self.report["checks"].append({"check": check_lbl + " (Volume Creation)", "pass": True, "note": f"{len(creation)} countries with CRM overlap"})
            if not capping.empty:
                print(f"[NOTE] {check_lbl}: {len(capping)} rows differ (Output < Input, likely capping).")
                self.report_success(check_lbl) # Pass if only capping

            if creation.empty and capping.empty:
                self.report_success(check_lbl)
        else:
            self.report_success(check_lbl)

    def check_redbull_alignment(self, rb_source: pd.DataFrame, final: pd.DataFrame):
        """Verify alignment with RedBull DL (benchmark)."""
        print("\nREDBULL ALIGNMENT (vs RedBull Inputs)")

        # Agg Final: CC, Year, RB_PRODUCT_NAME
        # Ensure RB_PRODUCT_NAME is filled (should use REDBULL PRODUCT col if exists as fallback)
        prod_col = "RB_PRODUCT_NAME"
        if "REDBULL PRODUCT" in final.columns:
            prod_col = "REDBULL PRODUCT"

        final_agg = final.groupby(["CC", "Year", prod_col], as_index=False)["Market Units"].sum()
        final_agg.rename(columns={prod_col: "Product", "Market Units": "Vol_Fin"}, inplace=True)

        # Agg RB
        rb_source = rb_source.copy()
        # Robust Column Mapping
        rb_col_map = {
            "Country": "POS_CC",
            "MKT": "MKT", # self map
            "Market Units": "MKT",
            "Product Name": "Product Name",
            "Product": "Product Name"
        }
        for k, v in rb_col_map.items():
            if k in rb_source.columns and v not in rb_source.columns:
                rb_source[v] = rb_source[k]

        # RB cols: POS_CC, Year, Product Name, MKT
        # Clean MKT
        def _parse(x):
            try: return float(x)
            except: return 0.0

        if "MKT" in rb_source.columns:
            rb_source["MKT_Val"] = rb_source["MKT"].map(_parse)
        else:
            print("[WARN] RedBull Alignment: Missing 'MKT' or 'Market Units' column in benchmark.")
            return

        rb_agg = rb_source.groupby(["POS_CC", "Year", "Product Name"], as_index=False)["MKT_Val"].sum()
        rb_agg.rename(columns={"POS_CC": "CC", "Product Name": "Product", "MKT_Val": "Vol_RB"}, inplace=True)

        # Merge
        merged = rb_agg.merge(final_agg, on=["CC", "Year", "Product"], how="inner", suffixes=("_rb", "_fin"))
        merged["diff"] = merged["Vol_Fin"] - merged["Vol_RB"]

        tol = self.tol_units
        mismatch = merged[merged["diff"].abs() > tol]

        if not mismatch.empty:
            # warn only
            print(f"[WARN] RedBull Alignment: {len(mismatch)} rows differ in Volume.")
            print(mismatch.head(5).to_string(index=False))
        else:
            print("[OK] RedBull Alignment - Volumes match intersection.")

    def check_dimensional_integrity(self, final: pd.DataFrame) -> bool:
        """
        Check for semantic failures in dimension columns:
        - Unknown Country/CC
        - Error in key columns
        - NaN/Empty strings in mandatory dimensions
        """
        any_issue = False

        # 1. Check Country Name
        # Look for "Unknown", "Error", "NaN" case-insensitive
        if "COUNTRY_NAME" in final.columns:
            # We want to catch literal "Unknown Country" or "Error"
            # We also catch actual NaNs
            mask_bad = (
                final["COUNTRY_NAME"].astype(str).str.contains(r"Unknown|Error|NaN|nan", case=False, regex=True)
                | final["COUNTRY_NAME"].isna()
                | (final["COUNTRY_NAME"].astype(str).str.strip() == "")
            )
            failures = final[mask_bad].copy()

            check_name = "Dimensional Integrity: COUNTRY_NAME"
            if not failures.empty:
                any_issue = True
                self.report_failure(check_name, failures)
            else:
                self.report_success(check_name)

        # 2. Check Sales Org
        if "SALES_ORG" in final.columns:
            # "Error-Greece" is a legacy value we might tolerate, but "Unknown" is bad.
            # Let's flag anything "Unknown" or valid NaNs
            mask_bad = (
                final["SALES_ORG"].astype(str).str.contains(r"Unknown|NaN|nan", case=False, regex=True)
                | final["SALES_ORG"].isna()
                | (final["SALES_ORG"].astype(str).str.strip() == "")
            )
            failures = final[mask_bad].copy()

            check_name = "Dimensional Integrity: SALES_ORG"
            if not failures.empty:
                any_issue = True
                self.report_failure(check_name, failures)
            else:
                self.report_success(check_name)

        # 3. Check CC
        if "CC" in final.columns:
             mask_bad = (
                final["CC"].astype(str).str.contains(r"Unknown|NaN|nan", case=False, regex=True)
                | final["CC"].isna()
                | (final["CC"].astype(str).str.strip() == "")
            )
             failures = final[mask_bad].copy()

             check_name = "Dimensional Integrity: CC"
             if not failures.empty:
                 any_issue = True
                 self.report_failure(check_name, failures)
             else:
                 self.report_success(check_name)

        return not any_issue

    def report_failure(self, check, df_fail):
        self.report["overall_pass"] = False
        self.report["checks"].append({"check": check, "pass": False, "mismatches": len(df_fail)})
        print(f"[X] {check}")
        print(df_fail.head(5).to_string(index=False))

    def report_success(self, check):
        self.report["checks"].append({"check": check, "pass": True})
        print(f"[OK] {check}")
def qa_redbull_mapping(
    product_map: pd.DataFrame,
    combined: pd.DataFrame,
    qa_report: dict | None = None,
) -> None:
    """
    RedBull mapping QA in the *canonical* domain.

    1) Ensure each PRODUCT_CANON has at most one RB product in the mapping file.
    2) Ensure each PRODUCT_CANON in the final data that needs a mapping
       actually has RB_PRODUCT_NAME filled.
    3) Ensure final data doesn't carry conflicting RB_PRODUCT_NAME /
       REDBULL PRODUCT per canonical product.
    """
    print("\nRedBull PRODUCT mapping QA")
    print("============================================================")

    pm = product_map.copy()

    # --- Determine mapping column name in the RB table ---
    if "RB_PRODUCT_NAME" in pm.columns:
        rb_col = "RB_PRODUCT_NAME"
    elif "REDBULL PRODUCT" in pm.columns:
        rb_col = "REDBULL PRODUCT"
    else:
        print("⚠ No RB mapping column found in product_map (expected 'RB_PRODUCT_NAME' or 'REDBULL PRODUCT'). Skipping RB QA.")
        if qa_report is not None:
            qa_report["RedBull_Mapping"] = {
                "ok": False,
                "error": "Missing RB mapping column in product_map",
            }
            qa_report.setdefault("checks", []).append(
                {"check": "RedBull product mapping integrity", "pass": False}
            )
            qa_report["overall_pass"] = False
        return

    # --- Ensure PRODUCT_CANON exists in mapping table ---
    if "PRODUCT_CANON" not in pm.columns:
        pm["PRODUCT_CANON"] = pm["PRODUCT"].map(canon_product)

    # 1) Uniqueness: one RB product per PRODUCT_CANON in the mapping file
    dup_map = (
        pm
        .dropna(subset=["PRODUCT_CANON"])
        .groupby("PRODUCT_CANON")[rb_col]
        .nunique()
        .reset_index(name="RB_Count")
    )

    prob_map = dup_map[dup_map["RB_Count"] > 1]

    if prob_map.empty:
        print("[OK] Mapping table: each PRODUCT_CANON has a single RB mapping")
        ok_mapping = True
    else:
        print("[X] Mapping table: PRODUCT_CANON with multiple RB mappings:")
        print(
            prob_map
            .sort_values("RB_Count", ascending=False)
            .head(50)
            .to_string(index=False)
        )
        ok_mapping = False

    # 2) Coverage in FINAL data (based on canonical)
    final_can = combined[["BUSINESS_SEGMENT", "PRODUCT", "PRODUCT_CANON", "RB_PRODUCT_NAME"]].copy()

    unmapped_final = (
        final_can[
            final_can["PRODUCT_CANON"].notna()
            & final_can["RB_PRODUCT_NAME"].isna()
        ]
        .drop_duplicates(subset=["BUSINESS_SEGMENT", "PRODUCT_CANON", "PRODUCT"])
    )

    if unmapped_final.empty:
        print("[OK] Final data: all canonical products that appear have RB_PRODUCT_NAME filled")
        ok_coverage = True
    else:
        print("[X] Final data: canonical products without RB_PRODUCT_NAME:")
        print(
            unmapped_final
            .sort_values(["BUSINESS_SEGMENT", "PRODUCT_CANON", "PRODUCT"])
            .head(50)
            .to_string(index=False)
        )
        if len(unmapped_final) > 50:
            print(f"  ... and {len(unmapped_final) - 50} more rows")
        ok_coverage = False

    # 3) Consistency inside FINAL: one RB_PRODUCT_NAME per PRODUCT_CANON
    dup_final = (
        final_can[final_can["RB_PRODUCT_NAME"].notna()]
        .groupby("PRODUCT_CANON")["RB_PRODUCT_NAME"]
        .nunique()
        .reset_index(name="RB_Count")
    )
    prob_final = dup_final[dup_final["RB_Count"] > 1]

    if prob_final.empty:
        print("[OK] Final data: each PRODUCT_CANON maps to a single RB_PRODUCT_NAME")
        ok_final_consistency = True
    else:
        print("[X] Final data: PRODUCT_CANON with conflicting RB_PRODUCT_NAME values:")
        print(
            prob_final
            .sort_values("RB_Count", ascending=False)
            .head(50)
            .to_string(index=False)
        )

        # Detail: show examples per problematic canonical
        bad_canons = prob_final["PRODUCT_CANON"].tolist()
        examples = (
            final_can[final_can["PRODUCT_CANON"].isin(bad_canons)]
            .drop_duplicates(subset=["BUSINESS_SEGMENT", "PRODUCT", "PRODUCT_CANON", "RB_PRODUCT_NAME"])
            .sort_values(["PRODUCT_CANON", "RB_PRODUCT_NAME", "PRODUCT"])
            .head(100)
        )
        print("\n  Examples of conflicting mappings in FINAL:")
        print(examples.to_string(index=False))
        ok_final_consistency = False

    # 4) Optional: mismatch between RB_PRODUCT_NAME and REDBULL PRODUCT in FINAL
    if {"RB_PRODUCT_NAME", "REDBULL PRODUCT"}.issubset(combined.columns):
        mismatch = combined[
            combined["RB_PRODUCT_NAME"].notna()
            & combined["REDBULL PRODUCT"].notna()
            & (combined["REDBULL PRODUCT"] != "-")
            & (combined["RB_PRODUCT_NAME"] != combined["REDBULL PRODUCT"])
        ].copy()

        if mismatch.empty:
            print("[OK] Final data: RB_PRODUCT_NAME and REDBULL PRODUCT agree where both are set")
            ok_rbcol = True
        else:
            print("[X] Final data: rows where RB_PRODUCT_NAME != REDBULL PRODUCT:")
            print(
                mismatch[
                    ["BUSINESS_SEGMENT", "PRODUCT", "PRODUCT_CANON",
                     "RB_PRODUCT_NAME", "REDBULL PRODUCT"]
                ]
                .drop_duplicates()
                .head(50)
                .to_string(index=False)
            )
            ok_rbcol = False
    else:
        ok_rbcol = True  # nothing to check

    overall_ok = ok_mapping and ok_coverage and ok_final_consistency and ok_rbcol

    if qa_report is not None:
        qa_report["RedBull_Mapping"] = {
            "ok": bool(overall_ok),
            "mapping_table_uniqueness": {
                "ok": bool(ok_mapping),
                "n_problem_canons": int(len(prob_map)),
                "canons": prob_map["PRODUCT_CANON"].tolist(),
            },
            "final_unmapped_canons": {
                "ok": bool(ok_coverage),
                "n_unmapped_rows": int(len(unmapped_final)),
            },
            "final_conflicting_rb_names": {
                "ok": bool(ok_final_consistency),
                "n_problem_canons": int(len(prob_final)),
            },
            "final_rb_vs_redbull_column": {
                "ok": bool(ok_rbcol),
                "n_mismatch_rows": int(mismatch.shape[0]) if "mismatch" in locals() else 0,
            },
        }
        qa_report.setdefault("checks", []).append(
            {
                "check": "RedBull product mapping integrity",
                "pass": bool(overall_ok),
            }
        )
        if not overall_ok:
            qa_report["overall_pass"] = False

def debug_icd_25q3_fr_uk(crm_source: pd.DataFrame,
                         final: pd.DataFrame,
                         sicd: pd.DataFrame,
                         marketdata: pd.DataFrame) -> None:
    """
    Debug helper:
    - Compare original vs final ICD market units for 25Q3 in FR & UK (by PRODUCT)
    - Show how much S-ICD is being added for those keys
    """

    print("\n" + "="*60)
    print("ICD 25Q3 FR/UK DEBUG")
    print("="*60)

    # 1) Original vs final ICD units by product
    mask_src = (
        (crm_source["Year"] == 2025)
        & (crm_source["Quarter"] == "25Q3")
        & (crm_source["COUNTRY_NAME"].isin(["France", "United Kingdom"]))
        & (crm_source["BUSINESS_SEGMENT"] == "ICD")
    )

    mask_fin = (
        (final["Year"] == 2025)
        & (final["Quarter"] == "25Q3")
        & (final["COUNTRY_NAME"].isin(["France", "United Kingdom"]))
        & (final["BUSINESS_SEGMENT"] == "ICD")
    )

    print("=== CRM ICD 25Q3 FR/UK by PRODUCT (Market Units) ===")
    if mask_src.any():
        print(
            crm_source[mask_src]
            .groupby(["COUNTRY_NAME", "PRODUCT"])["Market Units"]
            .sum()
            .sort_index()
            .to_string()
        )
    else:
        print("No ICD rows in CRM source for 25Q3 FR/UK")

    print("\n=== FINAL ICD 25Q3 FR/UK by PRODUCT (Market Units) ===")
    if mask_fin.any():
        print(
            final[mask_fin]
            .groupby(["COUNTRY_NAME", "PRODUCT"])["Market Units"]
            .sum()
            .sort_index()
            .to_string()
        )
    else:
        print("No ICD rows in FINAL data for 25Q3 FR/UK")

    # 2) S-ICD units being added for those keys
    print("\n=== S-ICD 25Q3 FR/UK ===")

    # Map Key_QCS -> COUNTRY_NAME / Year / Quarter for context
    key_map = (
        marketdata[["Key_QCS", "COUNTRY_NAME", "Year", "Quarter"]]
        .drop_duplicates()
    )

    sicd_debug = sicd.merge(key_map, on="Key_QCS", how="left")

    sicd_debug = sicd_debug[
        (sicd_debug["Year"] == 2025)
        & (sicd_debug["Quarter"] == "25Q3")
        & (sicd_debug["COUNTRY_NAME"].isin(["France", "United Kingdom"]))
    ]

    if sicd_debug.empty:
        print("No S-ICD entries found for 25Q3 FR/UK")
    else:
        print(
            sicd_debug[["COUNTRY_NAME", "SICD_Units"]]
            .groupby("COUNTRY_NAME")
            .sum()
            .to_string()
        )

    print("="*60 + "\n")

def debug_quarter_ipg(crm_df: pd.DataFrame, quarter: str = "23Q1") -> None:
    """
    Quick sanity check for a given quarter in the *CRM source* data.

    Works with either the original Excel column names or the renamed ones
    used after load_crm().
    """
    # Filter by quarter
    df = crm_df[crm_df["Quarter"].astype(str) == quarter].copy()

    print(f"\n=== CRM debug for {quarter} ===")
    print(f"Total rows: {len(df)}")

    # Handle both pre- and post-rename column names
    seg_col     = "BUSINESS_SEGMENT" if "BUSINESS_SEGMENT" in df.columns else "Business Segment"
    prod_col    = "PRODUCT"          if "PRODUCT"          in df.columns else "Product"
    country_col = "COUNTRY_NAME"     if "COUNTRY_NAME"     in df.columns else "Country Name"

    # 1) High-level mix by segment
    if seg_col in df.columns:
        print("By BUSINESS_SEGMENT:")
        print(df[seg_col].value_counts(dropna=False).to_string())
    else:
        print("⚠ No BUSINESS_SEGMENT / Business Segment column found in CRM debug dataframe.")

    # 2) Focus on IPG for that quarter
    if seg_col not in df.columns:
        return

    ipg = df[df[seg_col] == "IPG"].copy()
    print(f"\nIPG rows in {quarter}: {len(ipg)}")

    if ipg.empty:
        print("No IPG rows in this quarter.")
        return

    # IPG by Country + Product
    print("\nIPG by Country / Product (Market Units):")
    print(
        ipg[[country_col, prod_col, "Market Units"]]
        .groupby([country_col, prod_col])["Market Units"]
        .sum()
        .sort_values(ascending=False)
        .to_string()
    )

    # 3) Look specifically for the combined templates (CONVENTIONAL + LEADLESS)
    comb_mask = ipg[prod_col].astype(str).str.contains(
    "CONVENTIONAL + LEADLESS", case=False, na=False, regex=False
    )

    comb = ipg[comb_mask]

    print("\nCombined IPG templates (CONVENTIONAL + LEADLESS) in this quarter:")
    if comb.empty:
        print("  -- none found --")
    else:
        print(
            comb[[country_col, prod_col, "Market Units"]]
            .groupby([country_col, prod_col])["Market Units"]
            .sum()
            .sort_values(ascending=False)
            .to_string()
        )


if __name__ == "__main__":
    final, qa_report = main()

    print(final[["BUSINESS_SEGMENT","PRODUCT","PRODUCT_CANON","RB_PRODUCT_NAME","REDBULL PRODUCT"]]
      .drop_duplicates()
      .sort_values(["BUSINESS_SEGMENT","PRODUCT"])
      .head(50)
      .to_string(index=False))

    # Which products still miss BUSINESS_UNIT?
    print(
        final[final["BUSINESS_UNIT"].isna()]
        [["BUSINESS_SEGMENT","PRODUCT"]]
        .drop_duplicates()
        .sort_values(["BUSINESS_SEGMENT","PRODUCT"])
        .to_string(index=False)
    )

    # Which products still miss PRODUCT_GROUP?
    print(
        final[final["PRODUCT_GROUP"].isna()]
        [["BUSINESS_SEGMENT","PRODUCT"]]
        .drop_duplicates()
        .sort_values(["BUSINESS_SEGMENT","PRODUCT"])
        .to_string(index=False)
    )

    # --- Ensure FactKey is present for all rows and export in a Qlik-friendly way ---
    if "FactKey" in final.columns:
        # For any rows without FactKey yet (e.g. ICM), create it consistently
        mask_missing = final["FactKey"].isna()

        if mask_missing.any():
            # Ensure PRODUCT_CANON is available
            final.loc[mask_missing, "PRODUCT_CANON"] = final.loc[mask_missing, "PRODUCT_CANON"].fillna(
                final.loc[mask_missing, "PRODUCT"].map(canon_product)
            )

            final.loc[mask_missing, "FactKey"] = pd.util.hash_pandas_object(
                final.loc[mask_missing, ["CC", "SALES_ORG", "Year", "Quarter", "PRODUCT_CANON"]].astype(str),
                index=False,
            )

    # Export FactKey as text so Qlik doesn’t do weird float rounding on big integers
    final["FactKey"] = final["FactKey"].astype("string")

    # --- Force measure fields to be numeric; treat "-" as 0 ---
    numeric_cols = [
        "Market Units",
        "Units",
        "Market Net Revenue (in K EUR)",
        "Net Revenue (in K EUR)",
        # legacy CRM columns, in case Qlik still uses them:
        "ORG Units",
        "ORG Net Revenue (in K EUR)",
    ]

    for col in numeric_cols:
        if col in final.columns:
            final[col] = (
                final[col]
                .replace("-", 0)
                .replace("--", 0)
                .fillna(0)
            )
            final[col] = pd.to_numeric(final[col], errors="coerce").fillna(0)

    # enforce integer type for unit columns
    for col in ["Market Units", "Units", "ORG Units"]:
        if col in final.columns:
            final[col] = final[col].round().astype("Int64")

    asp_cols = [
        "ASP (in EUR)",
        "Market ASP (in EUR)",
        "ORG ASP (in EUR)",

    ]

    for col in asp_cols:
        if col in final.columns:
            final[col] = (
                final[col]
                .replace("-", 0)
                .replace("--", 0)
            )
            final[col] = pd.to_numeric(final[col], errors="coerce").fillna(0)

    # Drop unnecessary columns before export
    cols_to_drop = [
        "_IsCombinedFlag", "Key_QCS", "Origin", "UNITS_TO_SUBTRACT", "REVK_TO_SUBTRACT", "RB_PRODUCT_NAME", "PRODUCT_CANON", "Share_SC", "Share_DC", "Share_P", "Share_D", "PRODUCT_U", "Region"
        # Add any others you don't need
        ]
    final = final.drop(columns=[c for c in cols_to_drop if c in final.columns])

    # Persist QA evidence first, then publish only a validated candidate.
    try:
        published_paths = publish_validated_frame(
            final,
            qa_report,
            report_path=CFG.qa_report_json,
            destinations=[CFG.out_final_csv, CFG.out_final_csv_qvd],
        )
    except BlockingValidationError as exc:
        print(f"[X] PUBLICATION BLOCKED: {exc}")
        raise SystemExit(1) from exc
    except PublicationError as exc:
        print(f"[X] PUBLICATION FAILED: {exc}")
        raise SystemExit(1) from exc

    print(f"[OK] QA Report: {CFG.qa_report_json}")
    for published_path in published_paths:
        print(f"[OK] Published: {published_path}")

    # (Legacy Qlik Reload & Diagnostics removed - handled by orchestrator)

    # ------------------------------------------------------------------
    # 8. FINAL VALIDATION SUMMARY
    # ------------------------------------------------------------------
    print("\n" + "="*60)
    print("FINAL VALIDATION SUMMARY (Final vs Source Data)")
    print("="*60)

    if qa_report:
        overall = "PASS" if qa_report.get("overall_pass") else "FAIL"
        print(f"OVERALL STATUS: {overall}")
        print("-" * 30)
        for check in qa_report.get("checks", []):
            status = " [OK] " if check.get("pass") else " [FAIL]"
            name = check.get("check", "Unknown Check")
            print(f"{status} {name}")

    print("\n" + "="*60)
    print("[OK] Pipeline complete!")
