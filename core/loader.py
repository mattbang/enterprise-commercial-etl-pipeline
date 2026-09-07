import pandas as pd
import numpy as np
import yaml
import math
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import pandera as pa

# Internal imports
try:
    from core.schemas import InputSchemaCrm
except ImportError:
    from .schemas import InputSchemaCrm

from core.utils import num_smart, canon_product, dedupe_columns as dedupe, assert_columns, assert_not_empty
from core.row_lineage import add_row_key

class DataLoader:
    """Load all source data (CRM, ICM, unconventional)."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.country_map = None
        self.export_map = None
        self.rb_map = None
        self.territory_map = {}

    def load_maps(self) -> Dict[str, pd.DataFrame]:
        """Load countries, territory remaps, export flags, and RB product mappings."""
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

        # 3) Load RedBull Mapping
        rb = pd.read_excel(self.cfg.rb_map_xlsx, sheet_name="RBMAP")
        rb.columns = [c.strip() for c in rb.columns]
        assert_columns(rb, ["PRODUCT", "RB_PRODUCT_NAME"], "load_rb_map")

        # canonical product key used everywhere
        rb["PRODUCT_CANON"] = rb["PRODUCT"].map(canon_product)

        self.country_map = country
        self.export_map = export

        # Ensure Unconventional Leadless products are mapped to RedBull names
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
                new_row = pd.DataFrame([{"PRODUCT": canon, "RB_PRODUCT_NAME": rb_name, "PRODUCT_CANON": canon}])
                rb = pd.concat([rb, new_row], ignore_index=True)

        self.rb_map = rb
        return {"country": country, "export": export, "rb": rb}

    def load_crm(self) -> pd.DataFrame:
        """Load and clean the core CRM Market Tracker download."""
        df = pd.read_excel(self.cfg.crm_dl_xlsx, sheet_name="Sheet1")
        df.columns = [c.strip() for c in df.columns]

        # Territory Remapping
        if self.territory_map and "Country Name" in df.columns:
            df["Country Name"] = df["Country Name"].replace(self.territory_map)

        assert_columns(df, ["Business Unit","Business Segment","Country Name","Quarter","Market Units",
                            "Market Net Revenue (in K EUR)","ORG Units","ORG Net Revenue (in K EUR)"],
                       "load_crm")

        df = df[df["Business Unit"] != "VI"].copy()
        assert_not_empty(df, "load_crm (after filtering VI)")

        # Numerics
        df["Market Units"] = df["Market Units"].map(num_smart).round().astype("Int64")
        df["Market Net Revenue (in K EUR)"] = df["Market Net Revenue (in K EUR)"].map(num_smart)
        df["Units"] = df["ORG Units"].map(num_smart).round().astype("Int64")
        df["Net Revenue (in K EUR)"] = df["ORG Net Revenue (in K EUR)"].map(num_smart)

        # Schema Validation
        print("Validating CRM data against schema...")
        InputSchemaCrm.validate(df, lazy=True)

        # Time handling
        df["QTR"] = df["Quarter"].astype(str).str[-1].astype(int)
        df["NumericQuarter"] = (df["Quarter"].astype(str).str[:2] + df["QTR"].astype(str)).astype(int)

        # Standardize Names
        df.rename(columns={
            "Country Name": "COUNTRY_NAME",
            "Business Unit": "BUSINESS_UNIT",
            "Business Segment": "BUSINESS_SEGMENT",
            "Product Group": "PRODUCT_GROUP",
            "Product": "PRODUCT",
        }, inplace=True)

        df["PRODUCT"] = df["PRODUCT"].astype(str).str.upper().str.strip()
        df["SOURCE"] = "MTE"
        df["REGION"] = "MIDWEST"
        df["CURRENCY_NAME"] = "EUR"

        # Lineage
        df = add_row_key(df, source="CRM")
        return df

    def load_icm_market(self, crm_max_nq: int, cc_fix_map: Dict[str, str]) -> pd.DataFrame:
        """Load ICM annual market and split to quarters."""
        if not self.cfg.icm_market_dl_xlsx.exists():
            return pd.DataFrame()

        raw = pd.read_excel(self.cfg.icm_market_dl_xlsx, sheet_name="Sheet1")
        raw.columns = [c.strip() for c in raw.columns]

        # Robustness for updated exports
        if "YEAR" in raw.columns and "Year" not in raw.columns:
            raw = raw.rename(columns={"YEAR": "Year"})
        if "Business Unit" not in raw.columns:
            raw["Business Unit"] = "CRM incl. EP"

        mask_icm = raw["Product Category"].astype(str).str.contains("ICM", case=False, na=False)
        raw = raw[mask_icm].copy()

        raw["CC"] = raw["Country Code"].astype(str).str.strip().str.upper().map(lambda x: cc_fix_map.get(x, x))
        raw["Market_Units"] = raw["Market Units"].map(num_smart)
        raw["Market_Rev"]   = raw["Market Net Revenue"].map(num_smart)

        ann = raw.groupby(["CC", "Business Unit", "Product Segment", "Product Category", "Year"], as_index=False).agg(
            MarketUnits_Annual=("Market_Units", "sum"),
            MarketRevK_Annual=("Market_Rev", lambda s: s.sum() / 1000.0)
        )

        ann["MarketASP_Annual"] = np.where(ann["MarketUnits_Annual"] > 0, (ann["MarketRevK_Annual"] * 1000.0) / ann["MarketUnits_Annual"], np.nan)

        rows = []
        for _, r in ann.iterrows():
            mu_total = r.MarketUnits_Annual or 0
            base, rem = divmod(mu_total, 4)
            for q in range(1, 5):
                mu = base + (1 if q <= rem else 0)
                rows.append(dict(
                    CC=r.CC, Business_Unit=r["Business Unit"], ProductSegment=r["Product Segment"],
                    ProductCategory=r["Product Category"], Year=int(r.Year), Quarter=f"{int(r.Year)%100:02d}Q{q}",
                    QTR=q, NumericQuarter=int(f"{int(r.Year)%100:02d}{q}"), MarketUnits_Q=mu,
                    MarketRevK_Annual=r.MarketRevK_Annual, MarketASP_Annual=r.MarketASP_Annual
                ))

        qdf = pd.DataFrame(rows)
        qdf = qdf[qdf["NumericQuarter"] <= crm_max_nq].copy()

        # CC Mapping to Country
        country_cc = self.country_map.sort_values(["CC", "CRM_COUNTRY_NAME"]).drop_duplicates(subset=["CC"])
        cc_to_country = dict(zip(country_cc["CC"], country_cc["CRM_COUNTRY_NAME"]))
        cc_to_sorg = dict(zip(country_cc["CC"], country_cc["Sales_Organisation"]))

        qdf["COUNTRY_NAME"] = qdf["CC"].map(cc_to_country)
        qdf["SALES_ORG"] = qdf["CC"].map(cc_to_sorg)
        qdf["MarketRevK_Q"] = np.where(qdf["MarketUnits_Q"] > 0, (qdf["MarketUnits_Q"] * qdf["MarketASP_Annual"]) / 1000.0, 0.0)

        out = pd.DataFrame({
            "SOURCE": "ICM Market", "REGION": "MIDWEST", "COUNTRY_NAME": qdf["COUNTRY_NAME"],
            "CC": qdf["CC"], "SALES_ORG": qdf["SALES_ORG"], "CURRENCY_NAME": "EUR",
            "BUSINESS_UNIT": "CRM", "BUSINESS_SEGMENT": "ICM", "PRODUCT_GROUP": "ICM", "PRODUCT": "ICM",
            "Year": qdf["Year"], "Quarter": qdf["Quarter"], "QTR": qdf["QTR"], "NumericQuarter": qdf["NumericQuarter"],
            "Market Units": qdf["MarketUnits_Q"].round(), "Market Net Revenue (in K EUR)": qdf["MarketRevK_Q"],
            "Market ASP (in EUR)": qdf["MarketASP_Annual"], "Units": 0, "Net Revenue (in K EUR)": 0.0, "ASP (in EUR)": np.nan
        })
        return add_row_key(out, source="ICM Market")

    def load_icm_bio(self, crm_max_nq: int) -> pd.DataFrame:
        """Load ICM ORG performance data."""
        if not self.cfg.icm_bio_dl_xlsx.exists():
            return pd.DataFrame()

        raw = pd.read_excel(self.cfg.icm_bio_dl_xlsx, sheet_name="Sheet1")
        raw.columns = dedupe([str(c).strip() for c in raw.columns])

        mask = raw["Product Category"].astype(str).str.contains("ICM", case=False, na=False)
        raw = raw[mask].copy()

        # CC normalization (UK→GB, EL→GR) for consistent merge keys
        cc_fix_map = {"UK": "GB", "EL": "GR", "IR": "GB"}
        raw["CC"] = raw["Country Code"].astype(str).str.strip().str.upper().map(lambda x: cc_fix_map.get(x, x))

        raw["Year"] = raw["Year"].astype(int)
        raw["QTR"] = raw["Quarter"].astype(str).str.extract(r"(\d)").astype(int)
        raw["Quarter"] = raw.apply(lambda r: f"{int(r['Year']) % 100:02d}Q{int(r['QTR'])}", axis=1)
        raw["NumericQuarter"] = (raw["Year"] % 100) * 10 + raw["QTR"]
        raw = raw[raw["NumericQuarter"] <= crm_max_nq].copy()

        raw["Units_BIO"] = raw["Units"].map(num_smart).fillna(0.0)
        raw["NetRev_K_BIO"] = raw["Net Revenue EUR"].map(num_smart).fillna(0.0) / 1000.0

        return raw.groupby(["CC", "Year", "Quarter", "QTR", "NumericQuarter"], as_index=False).agg({
            "Units_BIO": "sum", "NetRev_K_BIO": "sum"
        })
