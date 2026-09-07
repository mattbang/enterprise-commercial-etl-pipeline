import re
from typing import Literal, Tuple, Optional

import numpy as np
import pandas as pd

AmbiguousPolicy = Literal["nan", "decimal", "thousands", "raise"]
_MISSING_MARKERS = {"", "-", "--", "n/a", "na", "null", "none"}
_APOSTROPHES = "'\u2018\u2019`"
_SPACES = " \u00a0\u202f\u2009"


def _invalid_number() -> float:
    return float("nan")


def _parse_grouped_integer(integer_part: str, separator: str) -> str | None:
    sign = ""
    unsigned = integer_part
    if unsigned.startswith(("+", "-")):
        sign, unsigned = unsigned[0], unsigned[1:]

    groups = unsigned.split(separator)
    if not groups or not 1 <= len(groups[0]) <= 3:
        return None
    if any(len(group) != 3 or not group.isdigit() for group in groups[1:]):
        return None
    if not groups[0].isdigit():
        return None
    return sign + "".join(groups)


def _resolve_ambiguous(value: str, separator: str, policy: AmbiguousPolicy) -> float:
    if policy == "nan":
        return _invalid_number()
    if policy == "decimal":
        return float(value.replace(separator, "."))
    if policy == "thousands":
        return float(value.replace(separator, ""))
    raise ValueError(
        f"Ambiguous numeric value {value!r}; choose ambiguous='decimal' or "
        "ambiguous='thousands'."
    )


def num_smart(x, *, ambiguous: AmbiguousPolicy = "nan"):
    """
    Parse common European, US, and Swiss numeric formats.

    A single separator followed by three digits is ambiguous when the leading
    group has one to three digits (for example, ``1,234``). Such values return
    NaN by default. Callers with a source-format contract can choose
    ``ambiguous='decimal'`` or ``ambiguous='thousands'`` explicitly.
    """
    if ambiguous not in {"nan", "decimal", "thousands", "raise"}:
        raise ValueError(f"Unsupported ambiguous-number policy: {ambiguous!r}")

    if pd.isna(x):
        return _invalid_number()
    if isinstance(x, (bool, np.bool_)):
        return _invalid_number()
    if isinstance(x, (int, float, np.integer, np.floating)):
        value = float(x)
        return value if np.isfinite(value) else _invalid_number()

    value = str(x).strip()
    if value.lower() in _MISSING_MARKERS:
        return _invalid_number()

    negative_parentheses = value.startswith("(") and value.endswith(")")
    if negative_parentheses:
        value = value[1:-1].strip()
        if value.startswith(("+", "-")):
            return _invalid_number()

    normalized_apostrophes = value.translate(
        str.maketrans({char: "'" for char in _APOSTROPHES})
    )
    if "'" in normalized_apostrophes:
        apostrophe_pattern = r"^[+-]?\d{1,3}(?:'\d{3})+(?:[.,]\d+)?$"
        if not re.fullmatch(apostrophe_pattern, normalized_apostrophes):
            return _invalid_number()
        value = normalized_apostrophes.replace("'", "")
    else:
        value = normalized_apostrophes

    if any(space in value for space in _SPACES):
        compact_spaces = re.sub(r"[\s\u00a0\u202f\u2009]+", " ", value).strip()
        space_pattern = r"^[+-]?\d{1,3}(?: \d{3})+(?:[.,]\d+)?$"
        if not re.fullmatch(space_pattern, compact_spaces):
            return _invalid_number()
        value = compact_spaces.replace(" ", "")

    sign = -1.0 if negative_parentheses else 1.0
    dot_count = value.count(".")
    comma_count = value.count(",")

    try:
        if dot_count and comma_count:
            decimal_separator = "." if value.rfind(".") > value.rfind(",") else ","
            grouping_separator = "," if decimal_separator == "." else "."
            if value.count(decimal_separator) != 1:
                return _invalid_number()

            integer_part, decimal_part = value.rsplit(decimal_separator, 1)
            grouped_integer = _parse_grouped_integer(integer_part, grouping_separator)
            if grouped_integer is None or not decimal_part.isdigit():
                return _invalid_number()
            parsed = float(f"{grouped_integer}.{decimal_part}")
            return sign * parsed

        separator = "." if dot_count else "," if comma_count else None
        if separator is None:
            if not re.fullmatch(r"[+-]?\d+(?:[eE][+-]?\d+)?", value):
                return _invalid_number()
            return sign * float(value)

        separator_count = value.count(separator)
        if separator_count > 1:
            grouped_integer = _parse_grouped_integer(value, separator)
            if grouped_integer is None:
                return _invalid_number()
            return sign * float(grouped_integer)

        integer_part, decimal_part = value.split(separator, 1)
        unsigned_integer = integer_part.lstrip("+-")
        if not decimal_part.isdigit() or (unsigned_integer and not unsigned_integer.isdigit()):
            return _invalid_number()

        if len(decimal_part) == 3 and 1 <= len(unsigned_integer) <= 3:
            return sign * _resolve_ambiguous(value, separator, ambiguous)

        decimal_value = f"{integer_part or '0'}.{decimal_part}"
        return sign * float(decimal_value)
    except (TypeError, ValueError, OverflowError):
        if ambiguous == "raise" and dot_count + comma_count == 1:
            raise
        return _invalid_number()

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
