import pandas as pd
import numpy as np

def enrich_product_dimensions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Enriches the dataset with three standardized product dimensions to bridge 
    the granularity gap between MTE (combined) and RedBull (granular) data.

    New Columns added:
        - PRODUCT_COMBINED: Normalised bucket name (e.g., 'ICD SC (Full)')
        - PRODUCT_GRAIN: 'Granular' or 'Combined'
        - IS_UNCONVENTIONAL: 'Yes', 'No', or 'Mixed'
    """
    
    # Work on a copy to avoid SettingWithCopy warnings
    out = df.copy()

    # 1. Initialize columns

    # --- PRODUCT_GROUP: strip misleading "Conventional" from groups that ---
    # --- actually bundle conventional + unconventional products together ---
    if "PRODUCT_GROUP" in out.columns:
        CANONICAL_PRODUCT_GROUP_MAP = {
            # Canonical suffixed names → parent
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
            # Raw MTE product names from MW MKT INTEL / Unconventional file
            "S-ICD": "ICD SC",
            "Single Chamber IPG - Leadless": "IPG SC",
            "Dual Chamber IPG - Leadless": "IPG DC",
            "IPG Leadless": "IPG SC",
            "IPG Single + Dual Chamber": "IPG SC",
            "ICD SC - Non-Transv.": "ICD SC",
            "ICD Single Chamber Non-Transvenous": "ICD SC",
            "IPG Single Chamber - Leadless": "IPG SC",
            # CRM long names
            "ICD Single Chamber": "ICD SC",
            "ICD Single Chamber Conventional": "ICD SC",
            "ICD Dual Chamber": "ICD DC",
            "IPG Single Chamber": "IPG SC",
            "IPG Single Chamber Conventional": "IPG SC",
            "IPG Dual Chamber": "IPG DC",
            "IPG Dual Chamber Conventional": "IPG DC",
            # EP long-form names from RedBull that need normalization
            "Catheters Diagnostic Advanced - Mapping High Density": "Catheters Diagnostic - Advanced",
        }
        out["PRODUCT_GROUP"] = out["PRODUCT_GROUP"].astype(str).str.strip().replace(CANONICAL_PRODUCT_GROUP_MAP)

    # Seed PRODUCT_COMBINED from the (now-corrected) PRODUCT_GROUP
    out["PRODUCT_COMBINED"] = out.get("PRODUCT_GROUP", "").astype(str).str.strip()
    out["PRODUCT_GRAIN"] = "Granular"
    out["IS_UNCONVENTIONAL"] = "No"

    # =========================================================================
    # 1.5 Canonical PRODUCT Synonym Normalization
    # =========================================================================
    # Resolves identical meaning strings that originate from different sources 
    # (e.g., MTE vs RedBull) so Qlik doesn't generate duplicate slices.

    # --- PRODUCT: unify synonymous raw PRODUCT strings ---
    if "PRODUCT" in out.columns:
        CANONICAL_PRODUCT_MAP = {
            # CRT
            "CRT - DEFIBRILLATORS": "CRT-D",
            "CRT - PACEMAKERS": "CRT-P",

            # ICD  ── MTE "Actual Full" bundles conventional + S-ICD together
            "ICD DUAL CHAMBER": "ICD Dual Chamber",
            "ICD SINGLE CHAMBER CONVENTIONAL + NON-TRANSVENOUS": "ICD SC (Conventional + S-ICD)",
            "ICD SINGLE CHAMBER CONVENTIONAL": "ICD SC (Conventional + S-ICD)",  # MTE combined
            "ICD SC": "ICD SC (Conventional)",              # RedBull granular — truly conv. only
            "ICD SINGLE CHAMBER NON-TRANSVENOUS": "S-ICD",

            # IPG SC ── MTE "Actual Full" bundles conventional + leadless together
            "IPG SINGLE CHAMBER CONVENTIONAL + LEADLESS": "IPG SC (Conventional + Leadless)",
            "IPG SINGLE CHAMBER CONVENTIONAL": "IPG SC (Conventional + Leadless)",  # MTE combined
            "IPG SC": "IPG SC (Conventional)",               # RedBull granular — truly conv. only
            "IPG SINGLE CHAMBER LEADLESS": "IPG SC (Leadless)",
            "Single Chamber IPG - Leadless": "IPG SC (Leadless)",
            "IPG Leadless": "IPG SC (Leadless)",

            # IPG DC ── MTE "Actual Full" bundles conventional + leadless together
            "IPG DUAL CHAMBER CONVENTIONAL + LEADLESS": "IPG DC (Conventional + Leadless)",
            "IPG DUAL CHAMBER CONVENTIONAL": "IPG DC (Conventional + Leadless)",  # MTE combined
            "IPG DC": "IPG DC (Conventional)",               # RedBull granular — truly conv. only
            "IPG DUAL CHAMBER LEADLESS": "IPG DC (Leadless)",
            "IPG Dual Chamber - Leadless": "IPG DC (Leadless)",       # RedBull granular
            "Dual Chamber IPG - Leadless": "IPG DC (Leadless)",       # MW MKT INTEL

            # Leads
            "LEADS - CRT": "Leads [CRT]",
            "LEADS - ICD": "Leads [ICD]",
            "LEADS - IPG": "Leads [IPG]",

            # ICM
            "ICM & Other Diagnostics": "ICM",
        }
        
        # Strip trailing/leading spaces from incoming payload to ensure hits
        out["PRODUCT"] = out["PRODUCT"].astype(str).str.strip().replace(CANONICAL_PRODUCT_MAP)
    
    # 2. Define our combined mappings
    # Mapping logic based on patterns in PRODUCT_GROUP
    
    # --- CRM: ICD ---
    # S-ICD
    mask_icd_sicd_conv = out["PRODUCT_COMBINED"].str.contains(r"ICD SINGLE CHAMBER CONVENTIONAL \+ NON-TRANSVENOUS", case=False, na=False)
    mask_icd_sc_conv = out["PRODUCT_COMBINED"].str.match(r"(?i)^ICD SC$", na=False)  # exact match after group rename
    mask_icd_sicd_only = out["PRODUCT_COMBINED"].str.contains("ICD SC S-ICD|S-ICD", case=False, na=False)
    
    out.loc[mask_icd_sicd_conv, "PRODUCT_COMBINED"] = "ICD SC (Full)"
    out.loc[mask_icd_sicd_conv, "PRODUCT_GRAIN"] = "Combined"
    out.loc[mask_icd_sicd_conv, "IS_UNCONVENTIONAL"] = "Mixed"
    
    out.loc[mask_icd_sc_conv, "PRODUCT_COMBINED"] = "ICD SC (Full)"
    out.loc[mask_icd_sc_conv, "PRODUCT_GRAIN"] = "Granular"
    out.loc[mask_icd_sc_conv, "IS_UNCONVENTIONAL"] = "No"

    out.loc[mask_icd_sicd_only, "PRODUCT_COMBINED"] = "ICD SC (Full)"
    out.loc[mask_icd_sicd_only, "PRODUCT_GRAIN"] = "Granular"
    out.loc[mask_icd_sicd_only, "IS_UNCONVENTIONAL"] = "Yes"

    # ICD DC
    mask_icd_dc = out["PRODUCT_COMBINED"].str.contains("ICD DC", case=False, na=False)
    out.loc[mask_icd_dc, "PRODUCT_COMBINED"] = "ICD DC (Full)"
    
    # --- CRM: IPG ---
    # IPG SC Leadless
    mask_ipg_sc_leadless_conv = out["PRODUCT_COMBINED"].str.contains(r"IPG SINGLE CHAMBER CONVENTIONAL \+ LEADLESS", case=False, na=False)
    mask_ipg_sc_conv = out["PRODUCT_COMBINED"].str.match(r"(?i)^IPG SC$", na=False)  # exact match after group rename
    mask_ipg_sc_leadless_only = out["PRODUCT_COMBINED"].str.contains("IPG SC Leadless", case=False, na=False)
    
    out.loc[mask_ipg_sc_leadless_conv, "PRODUCT_COMBINED"] = "IPG SC (Full)"
    out.loc[mask_ipg_sc_leadless_conv, "PRODUCT_GRAIN"] = "Combined"
    out.loc[mask_ipg_sc_leadless_conv, "IS_UNCONVENTIONAL"] = "Mixed"

    out.loc[mask_ipg_sc_conv, "PRODUCT_COMBINED"] = "IPG SC (Full)"
    out.loc[mask_ipg_sc_conv, "PRODUCT_GRAIN"] = "Granular"
    out.loc[mask_ipg_sc_conv, "IS_UNCONVENTIONAL"] = "No"

    out.loc[mask_ipg_sc_leadless_only, "PRODUCT_COMBINED"] = "IPG SC (Full)"
    out.loc[mask_ipg_sc_leadless_only, "PRODUCT_GRAIN"] = "Granular"
    out.loc[mask_ipg_sc_leadless_only, "IS_UNCONVENTIONAL"] = "Yes"

    # IPG DC Leadless
    mask_ipg_dc_leadless_conv = out["PRODUCT_COMBINED"].str.contains(r"IPG DUAL CHAMBER CONVENTIONAL \+ LEADLESS", case=False, na=False)
    mask_ipg_dc_conv = out["PRODUCT_COMBINED"].str.match(r"(?i)^IPG DC$", na=False)  # exact match after group rename
    mask_ipg_dc_leadless_only = out["PRODUCT_COMBINED"].str.contains("IPG DC Leadless|IPG Dual Chamber - Leadless", case=False, na=False)

    out.loc[mask_ipg_dc_leadless_conv, "PRODUCT_COMBINED"] = "IPG DC (Full)"
    out.loc[mask_ipg_dc_leadless_conv, "PRODUCT_GRAIN"] = "Combined"
    out.loc[mask_ipg_dc_leadless_conv, "IS_UNCONVENTIONAL"] = "Mixed"

    out.loc[mask_ipg_dc_conv, "PRODUCT_COMBINED"] = "IPG DC (Full)"
    out.loc[mask_ipg_dc_conv, "PRODUCT_GRAIN"] = "Granular"
    out.loc[mask_ipg_dc_conv, "IS_UNCONVENTIONAL"] = "No"

    out.loc[mask_ipg_dc_leadless_only, "PRODUCT_COMBINED"] = "IPG DC (Full)"
    out.loc[mask_ipg_dc_leadless_only, "PRODUCT_GRAIN"] = "Granular"
    out.loc[mask_ipg_dc_leadless_only, "IS_UNCONVENTIONAL"] = "Yes"

    # IPG SC + DC mega rollups
    # After PRODUCT_GROUP normalization, "IPG SC + Leadless" becomes "IPG SC".
    # Detect mega-rollup rows via PRODUCT column (contains "SINGLE + DUAL" pattern).
    if "PRODUCT" in out.columns:
        mask_ipg_mega = out["PRODUCT"].astype(str).str.contains(
            r"IPG SINGLE \+ DUAL|IPG SC \& DC", case=False, na=False
        )
    else:
        mask_ipg_mega = out["PRODUCT_COMBINED"].str.contains(r"IPG SC \+ Leadless", case=False, na=False)
    out.loc[mask_ipg_mega, "PRODUCT_COMBINED"] = "IPG (All)"
    out.loc[mask_ipg_mega, "PRODUCT_GRAIN"] = "Combined"
    out.loc[mask_ipg_mega, "IS_UNCONVENTIONAL"] = "Mixed"

    # --- CRM: CRT ---
    mask_crtp = out["PRODUCT_COMBINED"].str.contains("CRT-P", case=False, na=False) & ~out["PRODUCT_COMBINED"].str.contains(r"\+", na=False)
    mask_crtd = out["PRODUCT_COMBINED"].str.contains("CRT-D", case=False, na=False) & ~out["PRODUCT_COMBINED"].str.contains(r"\+", na=False)
    mask_crt_mega = out["PRODUCT_COMBINED"].str.contains(r"CRT-P \+ CRT-D", case=False, na=False)

    out.loc[mask_crtp, "PRODUCT_COMBINED"] = "CRT-P (Full)"
    out.loc[mask_crtd, "PRODUCT_COMBINED"] = "CRT-D (Full)"
    
    out.loc[mask_crt_mega, "PRODUCT_COMBINED"] = "CRT (All)"
    out.loc[mask_crt_mega, "PRODUCT_GRAIN"] = "Combined"

    # Unconventional catch-all flag
    # Any other groups with "Leadless" or "Non-Transvenous" or "S-ICD"
    unconv_kw = ["Leadless", "Non-Trans", "S-ICD"]
    for kw in unconv_kw:
        mask_kw = out["PRODUCT_COMBINED"].str.contains(kw, case=False, na=False) & (out["PRODUCT_GRAIN"] != "Combined")
        out.loc[mask_kw, "IS_UNCONVENTIONAL"] = "Yes"

    return out
