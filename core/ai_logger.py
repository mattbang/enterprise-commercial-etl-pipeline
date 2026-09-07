"""
AI Context Logger - Structured logging for AI-assisted debugging.

Logs events in JSONL format to help identify mapping issues, anomalies,
and pipeline events. The log file can be reviewed by AI to quickly
understand pipeline behavior and suggest fixes.

Usage:
    from core.ai_logger import ai_log, ai_log_exception

    ai_log("unmapped_product", raw_value="CRT Defibrillator", file="RedBull DL.xlsx")
    ai_log("zero_units", country="Belgium", product="ICM", year=2024)

    # Wrap exceptions to get fix suggestions:
    try:
        df["MKT"]  # KeyError
    except Exception as e:
        ai_log_exception(e, context={"file": "redbull_integration.py", "line": 264})
"""

from datetime import datetime
from pathlib import Path
import json
import threading
import traceback
import re

# Thread-safe file lock
_log_lock = threading.Lock()

# Log file location (next to orchestrator.log)
LOG_FILE = Path(__file__).resolve().parent.parent / "ai_context.jsonl"

# =============================================================================
# ERROR PATTERN DATABASE (Based on Historical Project Issues)
# =============================================================================
ERROR_PATTERNS = {
    # KeyError issues (common in pandas column access)
    r"KeyError: ['\"]?(MKT|BIO|Units|Market Units)['\"]?": {
        "category": "column_missing",
        "fix": "Check if RedBull file format changed. The column may be named differently. "
              "Look for 'BIO'/'MKT' columns vs 'Column1' with BIO/MKT values.",
        "related_file": "integration/redbull_integration.py",
        "past_resolution": "Conversation 2f1205c6: Fixed by detecting new vs old format in load_redbull_forecast()"
    },

    r"KeyError: ['\"]?(Country|CC|COUNTRY_NAME)['\"]?": {
        "category": "country_mapping",
        "fix": "Country column missing or renamed. Check CRM download format and mappings.yaml.",
        "related_file": "core/midwest_pipeline.py",
        "past_resolution": "Check territory_map in mappings.yaml for unmapped countries."
    },

    # Zero unit issues
    r"(units|Units).*[=:].*0|zero.*(units|Units)": {
        "category": "zero_units",
        "fix": "Units are zero. Check: 1) Source file has data for this segment, "
              "2) ICM_Market_DL.xlsx includes ORG metrics, 3) Mapping filters aren't excluding rows.",
        "related_file": "core/midwest_pipeline.py",
        "past_resolution": "Conversation 6425b4df: BIO units for ICM Belgium were missing because ICM_Market_DL.xlsx wasn't processed for BIO."
    },

    # File not found
    r"(FileNotFoundError|No such file|not found).*\.(xlsx|csv|qvd)": {
        "category": "file_missing",
        "fix": "Input file missing. Check: 1) Download completed, 2) File path in Config class, "
              "3) OneDrive sync status.",
        "related_file": "orchestrate_update.py",
        "past_resolution": "Ensure downloads complete before pipeline runs. Check data/in/ directory."
    },

    # Mapping issues
    r"(unmapped|not in mapping|mapping.*not found)": {
        "category": "mapping_gap",
        "fix": "Value not found in mapping file. Add to: config/mappings/map.market.ACCOUNTPOTENTIAL_ASPMSOVERVIEW.xlsx "
              "or config/mappings.yaml",
        "related_file": "config/mappings/",
        "past_resolution": "Conversation cb6f4bab: Added comprehensive CRT product variations to mappings."
    },

    # Duplicate key errors
    r"(duplicate|duplicated).*key": {
        "category": "duplicate_keys",
        "fix": "Duplicate rows detected in fact table. Check if source data has duplicates or "
              "if aggregation logic is missing a groupby column.",
        "related_file": "integration/redbull_integration.py",
        "past_resolution": "Add 'version' column to groupby if multiple versions are loaded."
    },

    # Schema validation
    r"SchemaError|validation.*failed|check.*failed": {
        "category": "schema_validation",
        "fix": "Data doesn't match expected schema. Check source file format changed or "
              "null values in required columns.",
        "related_file": "core/schemas.py",
        "past_resolution": "Run check_cols.py to compare actual vs expected columns."
    },
}


def ai_log(event_type: str, **details) -> None:
    """
    Log a structured event for AI analysis.

    Args:
        event_type: Category of event (e.g., 'unmapped_product', 'zero_units', 'mapping_applied')
        **details: Key-value pairs with event context

    Common event types:
        - unmapped_product: Product name not found in mapping
        - unmapped_territory: Country/region not in territory list
        - mapping_applied: A mapping rule was used (for traceability)
        - zero_units: Units dropped to zero for a country/product
        - validation_warning: QA check flagged an issue
        - file_loaded: Input file successfully loaded
        - file_missing: Expected file not found
        - exception: An exception was caught (use ai_log_exception instead)
    """
    entry = {
        "ts": datetime.now().isoformat(),
        "event": event_type,
        **details
    }

    with _log_lock:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def ai_log_exception(exc: Exception, context: dict = None) -> dict:
    """
    Log an exception with automatic fix suggestion based on error patterns.

    Args:
        exc: The exception that was caught
        context: Optional dict with additional context (file, function, line, etc.)

    Returns:
        dict with suggested fix if pattern matched, else empty dict
    """
    error_str = str(exc)
    error_type = type(exc).__name__
    tb = traceback.format_exc()

    # Try to match known error patterns
    suggestion = None
    for pattern, info in ERROR_PATTERNS.items():
        if re.search(pattern, error_str, re.IGNORECASE) or re.search(pattern, tb, re.IGNORECASE):
            suggestion = info
            break

    entry = {
        "ts": datetime.now().isoformat(),
        "event": "exception",
        "error_type": error_type,
        "error_message": error_str,
        "traceback_snippet": tb[-500:] if len(tb) > 500 else tb,  # Last 500 chars
        "context": context or {},
    }

    if suggestion:
        entry["matched_pattern"] = True
        entry["category"] = suggestion["category"]
        entry["suggested_fix"] = suggestion["fix"]
        entry["related_file"] = suggestion["related_file"]
        entry["past_resolution"] = suggestion["past_resolution"]

    with _log_lock:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return suggestion or {}


def ai_log_clear() -> None:
    """Clear the log file (call at start of pipeline run)."""
    with _log_lock:
        LOG_FILE.write_text("", encoding="utf-8")


def ai_log_summary() -> dict:
    """
    Generate a summary of logged events for quick review.

    Returns:
        dict with event counts, notable items, and any suggestions
    """
    if not LOG_FILE.exists():
        return {"total_events": 0, "by_type": {}}

    events = []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    by_type = {}
    for e in events:
        t = e.get("event", "unknown")
        by_type[t] = by_type.get(t, 0) + 1

    # Extract notable items
    unmapped_products = set()
    unmapped_territories = set()
    zero_units = []
    exceptions = []
    suggestions = []

    for e in events:
        evt = e.get("event")
        if evt == "unmapped_product":
            unmapped_products.add(e.get("raw_value", ""))
        elif evt == "unmapped_territory":
            unmapped_territories.add(e.get("raw_value", ""))
        elif evt == "zero_units":
            zero_units.append(f"{e.get('country')}/{e.get('product')}/{e.get('year')}")
        elif evt == "exception":
            exceptions.append({
                "type": e.get("error_type"),
                "message": e.get("error_message", "")[:100],
                "category": e.get("category"),
            })
            if e.get("suggested_fix"):
                suggestions.append({
                    "category": e.get("category"),
                    "fix": e.get("suggested_fix"),
                    "related_file": e.get("related_file"),
                })

    return {
        "total_events": len(events),
        "by_type": by_type,
        "unmapped_products": list(unmapped_products),
        "unmapped_territories": list(unmapped_territories),
        "zero_units_cases": zero_units[:10],
        "exceptions": exceptions[:5],
        "fix_suggestions": suggestions[:5],
    }


# =============================================================================
# CONVENIENCE DECORATORS
# =============================================================================
def log_exceptions(context_func=None):
    """
    Decorator to automatically log exceptions from a function.

    Usage:
        @log_exceptions
        def my_function():
            ...

        # Or with context:
        @log_exceptions(lambda: {"step": "loading"})
        def my_function():
            ...
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                ctx = {"function": func.__name__}
                if context_func:
                    ctx.update(context_func() if callable(context_func) else context_func)
                suggestion = ai_log_exception(e, context=ctx)
                if suggestion:
                    print(f"[AI Logger] Suggested fix: {suggestion.get('fix', 'N/A')}")
                raise
        return wrapper

    # Handle both @log_exceptions and @log_exceptions()
    if callable(context_func):
        func = context_func
        context_func = None
        return decorator(func)
    return decorator
