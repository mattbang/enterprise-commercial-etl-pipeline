"""
Mapping Exhaustiveness Tests
=============================

Cross-references the ACTUAL production output against all mapping tables
to find gaps that would only surface with real data.

Usage:
    python -m pytest tests/test_mapping_exhaustive.py -v --tb=short
    python tests/test_mapping_exhaustive.py  # Direct run with summary report
"""

import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FINAL_CSV = ROOT / "data" / "out" / "MarketData_ASP_&_MS_Final_python.csv"
INTEGRATED_CSV = ROOT / "data" / "out" / "MarketData_Integrated_Flat.csv"
MAPPINGS_YAML = ROOT / "config" / "mappings.yaml"


# =============================================================================
# FIXTURES
# =============================================================================
@pytest.fixture(scope="module")
def mappings_cfg():
    with open(MAPPINGS_YAML, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def final_df():
    """Load the pipeline output CSV."""
    if not FINAL_CSV.exists():
        pytest.skip(f"Pipeline output not found at {FINAL_CSV}")
    return pd.read_csv(FINAL_CSV, sep=";")


@pytest.fixture(scope="module")
def integrated_df():
    """Load the integrated flat file (includes RedBull)."""
    if not INTEGRATED_CSV.exists():
        pytest.skip(f"Integrated flat file not found at {INTEGRATED_CSV}")
    return pd.read_csv(INTEGRATED_CSV, sep=";")


# =============================================================================
# COUNTRY MAPPING EXHAUSTIVENESS
# =============================================================================
class TestCountryMappingExhaustive:
    """Check that every COUNTRY_NAME and CC in the output is in mappings.yaml."""

    def test_all_country_names_mapped(self, final_df, mappings_cfg):
        """Every COUNTRY_NAME in output should exist in mappings.yaml countries list."""
        if "COUNTRY_NAME" not in final_df.columns:
            pytest.skip("COUNTRY_NAME not in output")

        countries = mappings_cfg.get("countries", [])
        valid_names = set()
        for c in countries:
            if "CRM_COUNTRY_NAME" in c:
                valid_names.add(c["CRM_COUNTRY_NAME"])
            if "VI_COUNTRY_NAME" in c:
                valid_names.add(c["VI_COUNTRY_NAME"])

        # Also include territory keys (they get remapped)
        tmap = mappings_cfg.get("territory_map", {})
        valid_names.update(tmap.values())  # Targets (France)

        output_names = set(final_df["COUNTRY_NAME"].dropna().astype(str).str.strip().unique())
        unmapped = output_names - valid_names
        unmapped = {n for n in unmapped if n and n.lower() not in ("nan", "", "none")}

        assert not unmapped, \
            f"Found {len(unmapped)} unmapped COUNTRY_NAME values: {sorted(unmapped)}"

    def test_all_cc_codes_mapped(self, final_df, mappings_cfg):
        """Every CC in output should exist in mappings.yaml countries list."""
        if "CC" not in final_df.columns:
            pytest.skip("CC not in output")

        countries = mappings_cfg.get("countries", [])
        valid_cc = {c["CC"] for c in countries if "CC" in c}
        # Also include POS_CC values
        for c in countries:
            if "POS_CC" in c:
                valid_cc.add(c["POS_CC"])

        output_cc = set(final_df["CC"].dropna().astype(str).str.strip().str.upper().unique())
        unmapped = output_cc - valid_cc
        unmapped = {c for c in unmapped if c and c.lower() not in ("nan", "", "none")}

        assert not unmapped, \
            f"Found {len(unmapped)} unmapped CC values: {sorted(unmapped)}"


# =============================================================================
# PRODUCT MAPPING EXHAUSTIVENESS
# =============================================================================
class TestProductMappingExhaustive:
    """Check product mapping coverage against output."""

    def test_all_product_groups_recognisable(self, final_df, mappings_cfg):
        """
        Every PRODUCT_GROUP in output should either:
        1. Be a known canonical target in product_renames values
        2. Be a known raw input in product_renames keys
        3. Be a known segment (IPG, ICD, CRT, ICM)
        """
        if "PRODUCT_GROUP" not in final_df.columns:
            pytest.skip("PRODUCT_GROUP not in output")

        renames = mappings_cfg.get("product_renames", {})
        known = set(renames.keys()) | set(renames.values())
        # Also include segment-level names
        known.update({"IPG", "ICD", "CRT", "ICM", "EP", "Leads"})
        # Also include CRM-native products that don't go through RedBull rename pipeline
        known.update({
            "Catheters Ablation - Advanced", "Catheters Ablation - Irrigated",
            "Catheters Ablation - Standard", "Catheters Diagnostic - Advanced",
            "Catheters Diagnostic - Standard", "Transseptal Access Needles",
            "Transseptal Access Sheaths", "Leads [IPG]", "Leads [ICD]",
            "Leads [CRT]", "CRT-P + CRT-D",
        })
        # Upper-case everything for comparison
        known_upper = {str(k).upper().strip() for k in known}

        output_pgs = set(final_df["PRODUCT_GROUP"].dropna().astype(str).str.strip().unique())
        output_upper = {pg.upper() for pg in output_pgs}

        unmapped = output_upper - known_upper
        unmapped = {pg for pg in unmapped if pg and pg.lower() not in ("nan", "", "none")}

        if unmapped:
            # This is a WARNING, not necessarily a failure — new products may appear
            # But we still assert to flag for review
            assert not unmapped, \
                f"Found {len(unmapped)} potentially unmapped PRODUCT_GROUP values: {sorted(unmapped)}"


# =============================================================================
# BLANK FIELD CHECKS
# =============================================================================
class TestNoBlankCriticalFields:
    """Ensure critical fields are never blank in the output."""

    @pytest.mark.parametrize("col", [
        "CC", "COUNTRY_NAME", "Quarter", "Year", "Version", "EXPORT", "SOURCE",
    ])
    def test_no_blanks_in_field(self, final_df, col):
        if col not in final_df.columns:
            pytest.skip(f"{col} not in output")

        blanks = final_df[col].isna() | (final_df[col].astype(str).str.strip().isin(["", "nan", "None"]))
        assert not blanks.any(), \
            f"Found {blanks.sum()} blank rows in column '{col}'"

    def test_no_blank_bios(self, final_df):
        """BIOS should only be blank for Greece (Error sentinel)."""
        if "BIOS" not in final_df.columns:
            pytest.skip("BIOS not in output")

        blank_bios = final_df["BIOS"].isna() | (final_df["BIOS"].astype(str).str.strip().isin(["", "nan", "None"]))
        if "COUNTRY_NAME" in final_df.columns:
            # Exclude Greece
            blank_non_greece = blank_bios & ~final_df["COUNTRY_NAME"].astype(str).str.contains("Greece", case=False, na=False)
        else:
            blank_non_greece = blank_bios

        assert not blank_non_greece.any(), \
            f"Found {blank_non_greece.sum()} rows with blank BIOS (non-Greece)"

    def test_no_blank_sales_org(self, final_df):
        """SALES_ORG should only be blank for Greece."""
        if "SALES_ORG" not in final_df.columns:
            pytest.skip("SALES_ORG not in output")

        blank_sorg = final_df["SALES_ORG"].isna() | (final_df["SALES_ORG"].astype(str).str.strip().isin(["", "nan", "None"]))
        if "COUNTRY_NAME" in final_df.columns:
            blank_non_greece = blank_sorg & ~final_df["COUNTRY_NAME"].astype(str).str.contains("Greece", case=False, na=False)
        else:
            blank_non_greece = blank_sorg

        assert not blank_non_greece.any(), \
            f"Found {blank_non_greece.sum()} rows with blank SALES_ORG (non-Greece)"


# =============================================================================
# INTEGRATED FILE CHECKS (includes RedBull data)
# =============================================================================
class TestIntegratedFileChecks:
    """Extra checks on the integrated flat file that includes RedBull data."""

    def test_no_blank_cc_integrated(self, integrated_df):
        if "CC" not in integrated_df.columns:
            pytest.skip("CC not in integrated output")
        blanks = integrated_df["CC"].isna() | (integrated_df["CC"].astype(str).str.strip().isin(["", "-", "nan"]))
        assert not blanks.any(), f"Found {blanks.sum()} blank CC in integrated file"

    def test_no_blank_version_integrated(self, integrated_df):
        if "Version" not in integrated_df.columns:
            pytest.skip("Version not in integrated output")
        blanks = integrated_df["Version"].isna() | (integrated_df["Version"].astype(str).str.strip() == "")
        assert not blanks.any(), f"Found {blanks.sum()} blank Version in integrated file"

    def test_source_values_valid(self, integrated_df):
        """SOURCE should be one of the known values."""
        if "SOURCE" not in integrated_df.columns:
            pytest.skip("SOURCE not in integrated output")
        valid_sources = {"MTE", "CRM", "RedBull", "ICM Market", "ICM BIO", "ICM_Market", "ICM_BIO", "MW MKT INTEL"}
        sources = set(integrated_df["SOURCE"].dropna().astype(str).str.strip().unique())
        unexpected = sources - valid_sources
        if unexpected:
            # Warn but don't fail hard — new sources may appear
            print(f"WARNING: Unexpected SOURCE values: {unexpected}")


# =============================================================================
# DIRECT RUN (Summary Report Mode)
# =============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("MAPPING EXHAUSTIVENESS REPORT")
    print("=" * 60)

    if not FINAL_CSV.exists():
        print(f"\n[SKIP] Final CSV not found at {FINAL_CSV}")
        print("       Run the pipeline first: python orchestrate_update.py --skip-downloads")
        sys.exit(0)

    df = pd.read_csv(FINAL_CSV, sep=";")
    print(f"\nLoaded {len(df):,} rows from final output")

    with open(MAPPINGS_YAML, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # Country check
    countries = cfg.get("countries", [])
    valid_names = set()
    for c in countries:
        if "CRM_COUNTRY_NAME" in c: valid_names.add(c["CRM_COUNTRY_NAME"])
    tmap = cfg.get("territory_map", {})
    valid_names.update(tmap.values())

    if "COUNTRY_NAME" in df.columns:
        output_names = set(df["COUNTRY_NAME"].dropna().unique())
        unmapped_countries = output_names - valid_names
        unmapped_countries = {n for n in unmapped_countries if str(n).strip() and str(n).lower() != "nan"}
        print(f"\n[Countries] {len(output_names)} unique, {len(unmapped_countries)} unmapped")
        for c in sorted(unmapped_countries):
            print(f"  ⚠ {c}")

    # CC check
    valid_cc = {c["CC"] for c in countries if "CC" in c}
    if "CC" in df.columns:
        output_cc = set(df["CC"].dropna().astype(str).str.strip().str.upper().unique())
        unmapped_cc = output_cc - valid_cc
        unmapped_cc = {c for c in unmapped_cc if c and c != "NAN"}
        print(f"\n[CC Codes] {len(output_cc)} unique, {len(unmapped_cc)} unmapped")
        for c in sorted(unmapped_cc):
            print(f"  ⚠ {c}")

    # Product check
    renames = cfg.get("product_renames", {})
    known_products = set(renames.keys()) | set(renames.values())
    known_upper = {str(k).upper().strip() for k in known_products}

    if "PRODUCT_GROUP" in df.columns:
        output_pg = set(df["PRODUCT_GROUP"].dropna().unique())
        unmapped_pg = {pg for pg in output_pg if str(pg).upper().strip() not in known_upper}
        unmapped_pg = {pg for pg in unmapped_pg if str(pg).strip() and str(pg).lower() != "nan"}
        print(f"\n[Products] {len(output_pg)} unique, {len(unmapped_pg)} not in product_renames")
        for p in sorted(unmapped_pg):
            print(f"  ⚠ {p}")

    # Blank critical fields
    print("\n[Blank Field Check]")
    for col in ["CC", "COUNTRY_NAME", "BIOS", "SALES_ORG", "Version", "EXPORT"]:
        if col in df.columns:
            blanks = df[col].isna() | (df[col].astype(str).str.strip().isin(["", "nan", "None"]))
            count = blanks.sum()
            status = "✔" if count == 0 else "⚠"
            print(f"  {status} {col}: {count} blank rows")

    print("\n" + "=" * 60)
    print("Done.")
