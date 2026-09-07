import math

import numpy as np
import pandas as pd
import pytest

from core.midwest_pipeline import num_smart as pipeline_num_smart
from core.utils import num_smart


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("6.170,00", 6170.0),
        ("6,170.00", 6170.0),
        ("6'170.00", 6170.0),
        ("1\u2019234,50", 1234.5),
        ("1,234,567.89", 1234567.89),
        ("1.234.567,89", 1234567.89),
        ("1,234,567", 1234567.0),
        ("1.234.567", 1234567.0),
        ("3031.065", 3031.065),
        ("(1,234.56)", -1234.56),
        ("1 234", 1234.0),
    ],
)
def test_supported_numeric_formats(raw, expected):
    assert num_smart(raw) == pytest.approx(expected)


@pytest.mark.parametrize("separator", [",", "."])
def test_ambiguous_values_require_an_explicit_policy(separator):
    raw = f"1{separator}234"

    assert math.isnan(num_smart(raw))
    assert num_smart(raw, ambiguous="decimal") == pytest.approx(1.234)
    assert num_smart(raw, ambiguous="thousands") == pytest.approx(1234.0)
    with pytest.raises(ValueError, match="Ambiguous numeric value"):
        num_smart(raw, ambiguous="raise")


@pytest.mark.parametrize(
    "raw",
    ["", "-", "--", "N/A", "12,34,567", "1.23.456", "1'23", "1 23", True, np.inf, None],
)
def test_invalid_or_missing_values_return_nan(raw):
    assert pd.isna(num_smart(raw))


def test_legacy_pipeline_uses_shared_parser_behavior():
    assert pipeline_num_smart("6'170.00") == pytest.approx(6170.0)
    assert pd.isna(pipeline_num_smart("1,234"))
    assert pipeline_num_smart("1,234", ambiguous="thousands") == pytest.approx(1234.0)
