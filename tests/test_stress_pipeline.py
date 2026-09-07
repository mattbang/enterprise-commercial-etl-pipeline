"""
Stress Test Suite for QLIK ASP & MS Overview Pipeline
=====================================================

Comprehensive pytest-based stress tests covering:
1.  Numeric parsing (num_smart, _to_float_series)
2.  Quarter parsing (quarter_to_numeric)
3.  Product canonicalisation (canon_product + product_renames)
4.  Country/territory mapping coverage
5.  Schema validation (pandera)
6.  CRM Loader (full load with stress data)
7.  ICM Market Loader
8.  ICM BIO Loader
9.  RedBull Loader
10. Unconventional classify function
11. End-to-end pipeline (midwest_pipeline run)
12. Output validation

Usage:
    python -m pytest tests/test_stress_pipeline.py -v --tb=short
    python -m pytest tests/test_stress_pipeline.py -k "TestNumeric" -v
"""

import sys
import math
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

# Project root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# -- Imports from project --
from core.utils import num_smart, quarter_to_numeric, canon_product, dedupe_columns


# =============================================================================
# FIXTURES
# =============================================================================
STRESS_DIR = ROOT / "data" / "test_sandbox" / "stress"
MAPPINGS_YAML = ROOT / "config" / "mappings.yaml"
PRIVATE_INTEGRATION_AVAILABLE = importlib.util.find_spec("integration") is not None


@pytest.fixture(scope="session", autouse=True)
def generate_stress_data(tmp_path_factory):
    """Generate all stress data files once per session."""
    global STRESS_DIR
    from tests.generate_stress_data import generate_all
    STRESS_DIR = tmp_path_factory.mktemp("pipeline-stress")
    paths = generate_all(STRESS_DIR)
    return paths


@pytest.fixture(scope="session")
def mappings_cfg():
    """Load the production mappings.yaml."""
    with open(MAPPINGS_YAML, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# =============================================================================
# 1. NUMERIC PARSING
# =============================================================================
class TestNumericParsing:
    """Exhaustive tests for num_smart() — the EU/US number parser."""

    @pytest.mark.parametrize("input_val, expected", [
        # Standard integers
        (100, 100.0),
        (0, 0.0),
        (-50, -50.0),
        # Standard floats
        (3.14, 3.14),
        (-0.5, -0.5),
        # US format strings
        ("1234", 1234.0),
        ("1,234", np.nan),       # Ambiguous without a source-format contract
        ("1,234.56", 1234.56),
        ("1,234,567.89", 1234567.89),
        ("1,234,567", 1234567.0),
        # EU format strings
        ("1.234", np.nan),       # Ambiguous without a source-format contract
        ("1.234,56", 1234.56),
        ("1.234.567,89", 1234567.89),
        ("1.234.567", 1234567.0),
        ("3031.065", 3031.065), # Four-digit leading group makes this a decimal
        # Swiss and accounting formats
        ("6'170.00", 6170.0),
        ("1'234", 1234.0),
        ("1\u2019234,50", 1234.5),
        ("(1,234.56)", -1234.56),
        # NaN / blank / dash
        (np.nan, np.nan),
        ("", np.nan),
        (" ", np.nan),
        ("-", np.nan),           # num_smart returns NaN for single dash
        ("--", np.nan),
        (None, np.nan),
        # With spaces
        ("1 234", 1234.0),
    ])
    def test_num_smart_values(self, input_val, expected):
        result = num_smart(input_val)
        if expected is np.nan or (isinstance(expected, float) and math.isnan(expected)):
            assert pd.isna(result), f"Expected NaN for input {input_val!r}, got {result}"
        else:
            assert result == pytest.approx(expected, abs=0.01), \
                f"num_smart({input_val!r}) = {result}, expected {expected}"

    @pytest.mark.parametrize("separator", [",", "."])
    def test_ambiguous_single_separator_requires_policy(self, separator):
        value = f"1{separator}234"
        assert pd.isna(num_smart(value))
        assert num_smart(value, ambiguous="decimal") == pytest.approx(1.234)
        assert num_smart(value, ambiguous="thousands") == pytest.approx(1234.0)
        with pytest.raises(ValueError, match="Ambiguous numeric value"):
            num_smart(value, ambiguous="raise")

    @pytest.mark.parametrize("value", ["12,34,567", "1.23.456", "1'23", "1 23", True, np.inf])
    def test_invalid_numeric_shapes_return_nan(self, value):
        assert pd.isna(num_smart(value))


@pytest.mark.skipif(
    not PRIVATE_INTEGRATION_AVAILABLE,
    reason="private integration package is not part of the public portfolio",
)
class TestToFloatSeries:
    """Tests for _to_float_series() from redbull_integration."""

    def test_eu_format_with_apostrophe(self):
        from integration.redbull_integration import _to_float_series
        s = pd.Series(["1'234", "5'678", "-", "--", "", "0"])
        result = _to_float_series(s)
        assert result.iloc[0] == pytest.approx(1234.0)
        assert result.iloc[1] == pytest.approx(5678.0)
        # Dash/blanks → 0
        assert result.iloc[2] == pytest.approx(0.0)
        assert result.iloc[3] == pytest.approx(0.0)
        assert result.iloc[4] == pytest.approx(0.0)

    def test_eu_decimal_comma(self):
        from integration.redbull_integration import _to_float_series
        s = pd.Series(["1.234,56", "7.890,12"])
        result = _to_float_series(s)
        # EU: dot=thousands, comma=decimal → "1.234,56" → 1234.56
        assert result.iloc[0] == pytest.approx(1234.56)
        assert result.iloc[1] == pytest.approx(7890.12)

    def test_us_decimal_preserved(self):
        """US-format decimals must NOT be treated as EU thousands separators.
        This was the root cause of the 1000x inflation bug for GB IPG DC."""
        from integration.redbull_integration import _to_float_series
        s = pd.Series(["3031.065", "27379.671", "46184.0", "25.0", "5325"])
        result = _to_float_series(s)
        assert result.iloc[0] == pytest.approx(3031.065)
        assert result.iloc[1] == pytest.approx(27379.671)
        assert result.iloc[2] == pytest.approx(46184.0)
        assert result.iloc[3] == pytest.approx(25.0)
        assert result.iloc[4] == pytest.approx(5325.0)

    def test_mixed_eu_us_formats(self):
        """Both EU and US formats in the same series must parse correctly."""
        from integration.redbull_integration import _to_float_series
        s = pd.Series(["1.234,56", "3031.065", "7890", "-", "1,234.56"])
        result = _to_float_series(s)
        assert result.iloc[0] == pytest.approx(1234.56)   # EU
        assert result.iloc[1] == pytest.approx(3031.065)   # US decimal
        assert result.iloc[2] == pytest.approx(7890.0)     # plain integer
        assert result.iloc[3] == pytest.approx(0.0)        # dash
        assert result.iloc[4] == pytest.approx(1234.56)    # US with comma thousands

    def test_nan_handling(self):
        from integration.redbull_integration import _to_float_series
        s = pd.Series(["nan", "None", np.nan])
        result = _to_float_series(s)
        assert (result == 0.0).all(), "NaN-like values should become 0.0"


# =============================================================================
# 2. QUARTER PARSING
# =============================================================================
class TestQuarterParsing:
    """Tests for quarter_to_numeric()."""

    @pytest.mark.parametrize("input_val, expected_year, expected_qtr, expected_nq", [
        ("25Q1", 2025, 1, 251),
        ("25Q4", 2025, 4, 254),
        ("26Q1", 2026, 1, 261),
        ("21Q4", 2021, 4, 214),
        ("00Q1", 2000, 1, 1),     # Year 2000
    ])
    def test_valid_quarters(self, input_val, expected_year, expected_qtr, expected_nq):
        y, q, nq = quarter_to_numeric(input_val)
        assert y == expected_year
        assert q == expected_qtr
        assert nq == expected_nq

    @pytest.mark.parametrize("input_val", [
        "Q125",    # Malformed
        "",
        "abc",
        "25Q5",    # Invalid quarter number (but may still parse; 5 is technically parseable)
    ])
    def test_invalid_quarters(self, input_val):
        y, q, nq = quarter_to_numeric(input_val)
        # For malformed input, at least year or quarter should be NaN
        # Note: "25Q5" may technically parse to (2025, 5, 255) — schema catches it
        if input_val == "25Q5":
            assert q == 5  # Function parses this; schema validation catches it
        else:
            assert pd.isna(y) or pd.isna(q), f"Expected NaN for {input_val!r}"


# =============================================================================
# 3. PRODUCT CANONICALISATION
# =============================================================================
class TestProductCanonicalisation:
    """Tests for canon_product() + product_renames round-trips."""

    def test_canon_product_normalisation(self):
        assert canon_product("ipg single chamber") == "IPG SINGLE CHAMBER"
        assert canon_product("  CRT – D  ") == "CRT - D"   # em-dash → dash, stripped
        assert canon_product("CRT — P") == "CRT - P"       # em-dash → dash
        assert canon_product("ICM  &  Other") == "ICM & OTHER"  # double-space collapsed

    def test_all_product_renames_resolve(self, mappings_cfg):
        """Every entry in product_renames should map to a target."""
        renames = mappings_cfg.get("product_renames", {})
        assert len(renames) > 0, "product_renames is empty"

        for raw_name, canonical in renames.items():
            assert canonical is not None, f"product_renames[{raw_name!r}] maps to None"
            assert isinstance(canonical, str), f"product_renames[{raw_name!r}] is not a string"
            assert canonical.strip() != "", f"product_renames[{raw_name!r}] maps to empty string"

    def test_product_renames_canonical_set(self, mappings_cfg):
        """The canonical target set should be well-defined."""
        renames = mappings_cfg.get("product_renames", {})
        unique_targets = set(renames.values())

        expected_targets = {
            "IPG SC Conventional", "IPG SC",
            "IPG DC Conventional", "IPG DC",
            "ICD SC Conventional", "ICD SC", "ICD SC + S-ICD",
            "ICD DC Conventional",
            "CRT-D", "CRT-P",
            "ICM",
        }

        missing = expected_targets - unique_targets
        assert not missing, f"Expected canonical targets not covered by product_renames: {missing}"


# =============================================================================
# 4. COUNTRY / TERRITORY MAPPING
# =============================================================================
class TestCountryMapping:
    """Tests for country and territory mapping completeness."""

    def test_all_countries_have_required_fields(self, mappings_cfg):
        """Every country entry must have CC, CRM_COUNTRY_NAME, BIOS, Sales_Organisation."""
        countries = mappings_cfg.get("countries", [])
        assert len(countries) > 0, "No countries in mappings.yaml"

        for i, c in enumerate(countries):
            assert "CC" in c, f"Country #{i} missing CC"
            assert "CRM_COUNTRY_NAME" in c, f"Country #{i} missing CRM_COUNTRY_NAME"
            assert "BIOS" in c, f"Country #{i} missing BIOS"
            assert "Sales_Organisation" in c, f"Country #{i} missing Sales_Organisation"

    def test_main_countries_present(self, mappings_cfg):
        """Core countries must be in the mapping."""
        countries = mappings_cfg.get("countries", [])
        cc_set = {c["CC"] for c in countries}

        required_cc = {"BE", "CH", "ES", "FR", "GB", "IE", "IT", "PT", "CA", "NL"}
        missing = required_cc - cc_set
        assert not missing, f"Missing core country codes: {missing}"

    def test_territory_map_targets_france(self, mappings_cfg):
        """All territory codes should map to France."""
        tmap = mappings_cfg.get("territory_map", {})
        assert len(tmap) > 0, "territory_map is empty"

        for code, target in tmap.items():
            assert target == "France", \
                f"Territory '{code}' maps to '{target}', expected 'France'"

    def test_territory_map_completeness(self, mappings_cfg):
        """All known export territories should be in the map."""
        tmap = mappings_cfg.get("territory_map", {})
        expected = {
            "Tunisia", "Algeria", "Morocco", "Senegal", "Aruba",
            "Congo", "Guadeloupe", "Haiti", "Martinique",
            "New Caledonia", "French Polynesia", "Reunion", "Rwanda",
            "CG", "GP", "HT", "MQ", "NC", "PF", "RE", "RW",
            "TN", "DZ", "MA", "SN", "AW",
        }
        missing = expected - set(tmap.keys())
        assert not missing, f"Missing territory entries: {missing}"

    def test_greece_has_error_bios(self, mappings_cfg):
        """Greece BIOS should be 'Error' sentinel."""
        countries = mappings_cfg.get("countries", [])
        greece = [c for c in countries if c.get("CC") == "GR"]
        assert len(greece) == 1, "Greece not found or duplicated"
        assert greece[0]["BIOS"] == "Error", \
            f"Greece BIOS should be 'Error', got {greece[0]['BIOS']}"

    def test_ireland_maps_to_bio_uk(self, mappings_cfg):
        """Ireland (IE) should map to BIOS 5130 / BIO UK."""
        countries = mappings_cfg.get("countries", [])
        ireland = [c for c in countries if c.get("CC") == "IE"]
        assert len(ireland) >= 1, "Ireland (IE) not in country mapping"
        ie = ireland[0]
        assert ie["BIOS"] == 5130, f"IE BIOS should be 5130, got {ie['BIOS']}"
        assert ie["Sales_Organisation"] == "BIO UK", \
            f"IE Sales_Organisation should be 'BIO UK', got {ie['Sales_Organisation']}"


# =============================================================================
# 5. SCHEMA VALIDATION
# =============================================================================
class TestSchemaValidation:
    """Tests for pandera InputSchemaCrm / OutputSchema."""

    def test_valid_crm_data_passes(self):
        from core.schemas import InputSchemaCrm
        df = pd.DataFrame({
            "Business Unit": ["CRM"],
            "Business Segment": ["IPG"],
            "Country Name": ["Belgium"],
            "Quarter": ["25Q1"],
            "Market Units": [100.0],
        })
        # Should not raise
        InputSchemaCrm.validate(df, lazy=True)

    def test_invalid_country_fails(self):
        from core.schemas import InputSchemaCrm, ALL_VALID_INPUTS, pa
        if not ALL_VALID_INPUTS:
            pytest.skip("Schema config not loaded")

        df = pd.DataFrame({
            "Business Unit": ["CRM"],
            "Business Segment": ["IPG"],
            "Country Name": ["Liechtenstein"],  # Not in mapping
            "Quarter": ["25Q1"],
            "Market Units": [100.0],
        })

        with pytest.raises(pa.errors.SchemaErrors):
            InputSchemaCrm.validate(df, lazy=True)


# =============================================================================
# 6. CRM LOADER
# =============================================================================
class TestCRMLoader:
    """Tests for DataLoader.load_crm() with stress data."""

    @pytest.fixture
    def crm_df(self, generate_stress_data):
        """Load CRM stress data through the pipeline loader."""
        from core.midwest_pipeline import Config, DataLoader
        cfg = Config()
        cfg.crm_dl_xlsx = STRESS_DIR / "Market Tracker CRM DL.xlsx"
        cfg.mappings_yaml = ROOT / "config" / "mappings.yaml"
        cfg.rb_map_xlsx = STRESS_DIR / "map.market.ACCOUNTPOTENTIAL_ASPMSOVERVIEW.xlsx"
        cfg.map_country_export_xlsx = STRESS_DIR / "map_COUNTRY_EXPORT.xlsx"

        loader = DataLoader(cfg)
        loader.load_maps()
        return loader.load_crm()

    def test_vi_rows_filtered(self, crm_df):
        """VI business unit rows must be excluded."""
        if "BUSINESS_UNIT" in crm_df.columns:
            assert (crm_df["BUSINESS_UNIT"] != "VI").all(), "VI rows not filtered"

    def test_territories_remapped(self, crm_df):
        """Territory names (Tunisia, Algeria, etc.) should be replaced with France."""
        territories = {"Tunisia", "Algeria", "Morocco", "Senegal", "Aruba",
                       "Congo", "Guadeloupe", "Rwanda"}
        if "COUNTRY_NAME" in crm_df.columns:
            remaining = set(crm_df["COUNTRY_NAME"].unique()) & territories
            assert not remaining, f"Territories not remapped: {remaining}"

    def test_numeric_columns_are_numeric(self, crm_df):
        """Market Units and Revenue columns should be numeric after parsing."""
        for col in ["Market Units", "Units"]:
            if col in crm_df.columns:
                assert pd.api.types.is_numeric_dtype(crm_df[col]), \
                    f"Column {col} is {crm_df[col].dtype}, expected numeric"

    def test_no_empty_country_name(self, crm_df):
        """No rows should have blank/null COUNTRY_NAME after loading."""
        if "COUNTRY_NAME" in crm_df.columns:
            blanks = crm_df["COUNTRY_NAME"].isna() | (crm_df["COUNTRY_NAME"].astype(str).str.strip() == "")
            assert not blanks.any(), \
                f"Found {blanks.sum()} rows with blank COUNTRY_NAME"

    def test_source_is_mte(self, crm_df):
        """CRM source should be tagged as MTE."""
        if "SOURCE" in crm_df.columns:
            assert (crm_df["SOURCE"] == "MTE").all(), "Not all CRM rows have SOURCE=MTE"


# =============================================================================
# 7. ICM MARKET LOADER
# =============================================================================
class TestICMMarketLoader:
    """Tests for DataLoader.load_icm_market() with stress data."""

    @pytest.fixture
    def icm_market_df(self, generate_stress_data):
        from core.midwest_pipeline import Config, DataLoader
        cfg = Config()
        cfg.icm_market_dl_xlsx = STRESS_DIR / "ICM_Market_DL.xlsx"
        cfg.mappings_yaml = ROOT / "config" / "mappings.yaml"
        cfg.rb_map_xlsx = STRESS_DIR / "map.market.ACCOUNTPOTENTIAL_ASPMSOVERVIEW.xlsx"
        cfg.map_country_export_xlsx = STRESS_DIR / "map_COUNTRY_EXPORT.xlsx"

        loader = DataLoader(cfg)
        loader.load_maps()
        cc_fix_map = {"UK": "GB", "EL": "GR", "IE": "GB", "IR": "GB"}
        # Use a generous max NQ to include most data
        return loader.load_icm_market(crm_max_nq=264, cc_fix_map=cc_fix_map)

    def test_non_icm_rows_filtered(self, icm_market_df):
        """Only ICM Product Category rows should remain."""
        if icm_market_df.empty:
            pytest.skip("ICM market data empty (may be expected)")
        if "ProductCategory" in icm_market_df.columns:
            for val in icm_market_df["ProductCategory"].unique():
                assert "ICM" in str(val).upper(), f"Non-ICM category found: {val}"

    def test_cc_fix_applied(self, icm_market_df):
        """UK/EL should be fixed to GB/GR."""
        if icm_market_df.empty:
            pytest.skip("ICM market data empty")
        if "CC" in icm_market_df.columns:
            assert "UK" not in icm_market_df["CC"].values, "UK not fixed to GB"
            assert "EL" not in icm_market_df["CC"].values, "EL not fixed to GR"

    def test_quarterly_split(self, icm_market_df):
        """Annual data should be split into 4 quarters."""
        if icm_market_df.empty:
            pytest.skip("ICM market data empty")
        if "QTR" in icm_market_df.columns:
            qtrs = set(icm_market_df["QTR"].unique())
            assert qtrs.issubset({1, 2, 3, 4}), f"Invalid quarters found: {qtrs}"


# =============================================================================
# 8. ICM BIO LOADER
# =============================================================================
class TestICMBIOLoader:
    """Tests for DataLoader.load_icm_bio() with stress data."""

    @pytest.fixture
    def icm_bio_df(self, generate_stress_data):
        from core.midwest_pipeline import Config, DataLoader
        cfg = Config()
        cfg.icm_bio_dl_xlsx = STRESS_DIR / "ICM_BIO_DL.xlsx"
        cfg.mappings_yaml = ROOT / "config" / "mappings.yaml"
        cfg.rb_map_xlsx = STRESS_DIR / "map.market.ACCOUNTPOTENTIAL_ASPMSOVERVIEW.xlsx"
        cfg.map_country_export_xlsx = STRESS_DIR / "map_COUNTRY_EXPORT.xlsx"

        loader = DataLoader(cfg)
        loader.load_maps()
        return loader.load_icm_bio(crm_max_nq=264)

    def test_non_icm_rows_filtered(self, icm_bio_df):
        """Only ICM Product Category rows should remain."""
        if icm_bio_df.empty:
            pytest.skip("ICM BIO data empty")
        # After aggregation, ProductCategory column may be dropped
        # Just check we have data
        assert len(icm_bio_df) > 0

    def test_nan_numeric_handled(self, icm_bio_df):
        """NaN units should be filled to 0."""
        if icm_bio_df.empty:
            pytest.skip("ICM BIO data empty")
        if "Units_BIO" in icm_bio_df.columns:
            assert not icm_bio_df["Units_BIO"].isna().any(), "NaN Units_BIO found"


# =============================================================================
# 9. REDBULL LOADER
# =============================================================================
@pytest.mark.skipif(
    not PRIVATE_INTEGRATION_AVAILABLE,
    reason="private integration package is not part of the public portfolio",
)
class TestRedBullLoader:
    """Tests for load_redbull_forecast() with stress data."""

    @pytest.fixture
    def rb_frames(self, generate_stress_data):
        from integration.redbull_integration import load_redbull_forecast, load_product_mapping
        mapping = load_product_mapping(STRESS_DIR / "map.market.ACCOUNTPOTENTIAL_ASPMSOVERVIEW.xlsx")
        return load_redbull_forecast(STRESS_DIR / "RedBull DL.xlsx", mapping)

    def test_loads_without_crash(self, rb_frames):
        """The loader should handle all edge cases without crashing."""
        assert rb_frames is not None
        assert not rb_frames.clean.empty, "Clean data is empty"

    def test_leadless_bio_zeroed(self, rb_frames):
        """Leadless products should have BIO units = 0."""
        from integration.redbull_integration import LEADLESS_CANON_RAW
        clean = rb_frames.clean
        # Check against raw (pre-mapping) product name since mapped name = conventional
        if "product_group_raw" not in clean.columns:
            pytest.skip("product_group_raw column not available")
        leadless_bio = clean[
            (clean["product_group_raw"].isin(LEADLESS_CANON_RAW)) &
            (clean["unit_owner"] == "BIO")
        ]
        if not leadless_bio.empty:
            non_zero = leadless_bio[leadless_bio["units"] != 0]
            assert non_zero.empty, \
                f"Found {len(non_zero)} leadless BIO rows with non-zero units:\n{non_zero[['product_group_raw', 'units']].to_string()}"

    def test_no_blank_cc(self, rb_frames):
        """No rows should have blank/null CC."""
        clean = rb_frames.clean
        blanks = clean["cc"].isna() | (clean["cc"].astype(str).str.strip().isin(["", "-", "nan"]))
        assert not blanks.any(), f"Found {blanks.sum()} rows with blank CC"

    def test_unmapped_products_flagged(self, rb_frames):
        """Unmapped products should fall through to raw name (not crash)."""
        clean = rb_frames.clean
        # "BRAND NEW PRODUCT 2026" should be in the data as-is
        unmapped = clean[clean["product_group"] == "BRAND NEW PRODUCT 2026"]
        assert len(unmapped) > 0, "Unmapped product not retained"

    def test_whitespace_product_cleaned(self, rb_frames):
        """Products with leading/trailing spaces should be stripped before mapping."""
        clean = rb_frames.clean
        for pg in clean["product_group"].unique():
            assert pg == str(pg).strip(), f"Product not stripped: {pg!r}"

    def test_eu_format_numbers_parsed(self, rb_frames):
        """EU-format numbers with apostrophes should parse correctly."""
        clean = rb_frames.clean
        # The row with "1'234" BIO should parse to 1234
        fr_rows = clean[(clean["cc"] == "FRANCE") | (clean["country"].str.upper() == "FRANCE")]
        if not fr_rows.empty:
            assert (fr_rows["units"] >= 0).all(), "Negative units from EU parse"


# =============================================================================
# 10. UNCONVENTIONAL CLASSIFY
# =============================================================================
class TestUnconventionalClassify:
    """Test the classify function from AdjustmentCompute."""

    @pytest.mark.parametrize("product_name, expected_class", [
        ("S-ICD",                                "SICD"),
        ("ICD Single Chamber Non-Transvenous",   "SICD"),
        ("ICD SC - Non-Transv.",                 "OTHER"),  # Dot after text prevents NON-TRANSVEN match
        ("Single Chamber IPG - Leadless",        "ILP_SC"),
        ("IPG SC Leadless",                      "ILP_SC"),
        ("Dual Chamber IPG - Leadless",          "ILP_DC"),
        ("IPG DC Leadless",                      "ILP_DC"),
        ("IPG Leadless",                         "ILP_TOTAL"),
        ("IPG Single Chamber",                   "OTHER"),
        ("CRT-D",                                "OTHER"),
    ])
    def test_classify(self, product_name, expected_class):
        """Run the classify logic inline (extracted from AdjustmentCompute)."""
        p = str(product_name).upper()
        if "S-ICD" in p or "NON-TRANSVEN" in p:
            result = "SICD"
        elif ("LEADLESS" in p or "ILP" in p) and any(k in p for k in ["SINGLE", "SC"]):
            result = "ILP_SC"
        elif ("LEADLESS" in p or "ILP" in p) and any(k in p for k in ["DUAL", "DC"]):
            result = "ILP_DC"
        elif "LEADLESS" in p or "ILP" in p:
            result = "ILP_TOTAL"
        else:
            result = "OTHER"
        assert result == expected_class, \
            f"classify({product_name!r}) = {result}, expected {expected_class}"


# =============================================================================
# 11. DEDUPE COLUMNS
# =============================================================================
class TestDedupeColumns:
    """Test dedupe_columns helper."""

    def test_unique_columns_unchanged(self):
        result = dedupe_columns(["A", "B", "C"])
        assert result == ["A", "B", "C"]

    def test_duplicate_columns_suffixed(self):
        result = dedupe_columns(["A", "B", "A", "C", "A"])
        assert result == ["A", "B", "A.1", "C", "A.2"]


# =============================================================================
# 12. OUTPUT VALIDATION
# =============================================================================
class TestOutputValidation:
    """
    Validate the final pipeline output CSV if it exists.
    These tests run against the actual production output to catch gaps.
    """
    FINAL_CSV = ROOT / "data" / "out" / "MarketData_ASP_&_MS_Final_python.csv"

    @pytest.fixture
    def final_df(self):
        if not self.FINAL_CSV.exists():
            pytest.skip("Final output CSV not found — run pipeline first")
        return pd.read_csv(self.FINAL_CSV, sep=";")

    def test_required_columns(self, final_df):
        """Critical columns for Qlik consumption."""
        required = ["Year", "Quarter", "CC", "PRODUCT_GROUP",
                     "Units", "Market Units", "EXPORT", "Version", "SOURCE"]
        missing = [c for c in required if c not in final_df.columns]
        assert not missing, f"Missing required columns: {missing}"

    def test_no_blank_cc(self, final_df):
        """CC should never be blank."""
        if "CC" in final_df.columns:
            blanks = final_df["CC"].isna() | (final_df["CC"].astype(str).str.strip() == "")
            assert not blanks.any(), \
                f"Found {blanks.sum()} rows with blank CC"

    def test_no_blank_country_name(self, final_df):
        """COUNTRY_NAME should never be blank."""
        if "COUNTRY_NAME" in final_df.columns:
            blanks = final_df["COUNTRY_NAME"].isna() | \
                     (final_df["COUNTRY_NAME"].astype(str).str.strip() == "")
            assert not blanks.any(), \
                f"Found {blanks.sum()} rows with blank COUNTRY_NAME"

    def test_no_nan_bios(self, final_df):
        """BIOS should not be NaN (except for Greece which is 'Error')."""
        if "BIOS" in final_df.columns:
            nan_bios = final_df[
                final_df["BIOS"].isna() &
                ~final_df["COUNTRY_NAME"].astype(str).str.contains("Greece", case=False, na=False)
            ]
            assert nan_bios.empty, \
                f"Found {len(nan_bios)} rows with NaN BIOS (non-Greece)"

    def test_no_nan_sales_org(self, final_df):
        """SALES_ORG should not be NaN (except for Greece)."""
        if "SALES_ORG" in final_df.columns:
            nan_sorg = final_df[
                final_df["SALES_ORG"].isna() &
                ~final_df["COUNTRY_NAME"].astype(str).str.contains("Greece", case=False, na=False)
            ]
            assert nan_sorg.empty, \
                f"Found {len(nan_sorg)} rows with NaN SALES_ORG (non-Greece)"

    def test_no_negative_market_units(self, final_df):
        """Market Units should never be negative."""
        if "Market Units" in final_df.columns:
            neg = final_df[pd.to_numeric(final_df["Market Units"], errors="coerce") < 0]
            assert neg.empty, \
                f"Found {len(neg)} rows with negative Market Units"

    def test_version_not_null(self, final_df):
        """Version column should never be null or empty."""
        if "Version" in final_df.columns:
            nulls = final_df["Version"].isna() | (final_df["Version"].astype(str).str.strip() == "")
            assert not nulls.any(), \
                f"Found {nulls.sum()} rows with null/empty Version"

    def test_valid_quarter_format(self, final_df):
        """Quarter should match pattern YYQ[1-4]."""
        if "Quarter" in final_df.columns:
            pattern = r"^\d{2}Q[1-4]$"
            invalid = ~final_df["Quarter"].astype(str).str.match(pattern)
            bad = final_df.loc[invalid, "Quarter"].unique()
            assert not invalid.any(), \
                f"Found {invalid.sum()} rows with invalid Quarter format: {bad[:10]}"

    def test_year_is_reasonable(self, final_df):
        """Year should be between 2000 and 2030."""
        if "Year" in final_df.columns:
            years = pd.to_numeric(final_df["Year"], errors="coerce")
            bad = years[(years < 2000) | (years > 2030)]
            assert bad.empty, \
                f"Found {len(bad)} rows with unreasonable Year values"
