"""
Test script for AI Context Logger functionality.

Run this to verify the logger works and see example output.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from core.ai_logger import (
    ai_log, 
    ai_log_exception, 
    ai_log_clear, 
    ai_log_summary,
    log_exceptions,
    LOG_FILE
)

def test_basic_logging():
    """Test basic event logging."""
    print("=" * 60)
    print("TEST 1: Basic Event Logging")
    print("=" * 60)
    
    # Clear previous logs
    ai_log_clear()
    print(f"[OK] Cleared log file: {LOG_FILE}")
    
    # Log some events
    ai_log("unmapped_product", raw_value="CRT Defibrillator", source="RedBull", file="test.xlsx")
    ai_log("unmapped_product", raw_value="IPG Leadless NEW", source="RedBull", file="test.xlsx")
    ai_log("territory_remap", original="Tunisia", mapped_to="France", rows_affected=15)
    ai_log("zero_units", country="Belgium", product="ICM", year=2024)
    ai_log("file_loaded", file="Market Tracker CRM DL.xlsx", rows=1500)
    
    print("[OK] Logged 5 test events")
    
    # Show log contents
    print("\nLog file contents:")
    print("-" * 40)
    with open(LOG_FILE, "r") as f:
        for line in f:
            print(f"  {line.strip()[:100]}...")
    
    return True


def test_exception_logging():
    """Test exception logging with pattern matching."""
    print("\n" + "=" * 60)
    print("TEST 2: Exception Logging with Fix Suggestions")
    print("=" * 60)
    
    # Simulate KeyError (common in your project)
    try:
        data = {}
        _ = data["MKT"]  # This will raise KeyError
    except Exception as e:
        suggestion = ai_log_exception(e, context={"file": "redbull_integration.py", "function": "load_redbull_forecast"})
        print(f"[OK] Caught KeyError: 'MKT'")
        if suggestion:
            print(f"  -> Category: {suggestion.get('category')}")
            print(f"  -> Fix: {suggestion.get('fix', 'N/A')[:80]}...")
            print(f"  -> Past Resolution: {suggestion.get('past_resolution', 'N/A')[:60]}...")
        else:
            print("  -> No matching pattern found")
    
    # Simulate mapping not found error
    try:
        raise ValueError("Product 'XYZ' unmapped - not in mapping file")
    except Exception as e:
        suggestion = ai_log_exception(e, context={"file": "test.py"})
        print(f"\n[OK] Caught ValueError: unmapped product")
        if suggestion:
            print(f"  -> Category: {suggestion.get('category')}")
            print(f"  -> Fix: {suggestion.get('fix', 'N/A')[:80]}...")
    
    # Simulate file not found
    try:
        raise FileNotFoundError("RedBull DL.xlsx not found")
    except Exception as e:
        suggestion = ai_log_exception(e, context={"step": "download"})
        print(f"\n[OK] Caught FileNotFoundError")
        if suggestion:
            print(f"  -> Category: {suggestion.get('category')}")
            print(f"  -> Fix: {suggestion.get('fix', 'N/A')[:80]}...")
    
    return True


def test_decorator():
    """Test the @log_exceptions decorator."""
    print("\n" + "=" * 60)
    print("TEST 3: @log_exceptions Decorator")
    print("=" * 60)
    
    @log_exceptions
    def failing_function():
        raise KeyError("COUNTRY_NAME")
    
    try:
        failing_function()
    except KeyError:
        print("[OK] Decorator caught and logged the exception")
    
    return True


def test_summary():
    """Test the summary generation."""
    print("\n" + "=" * 60)
    print("TEST 4: Summary Generation")
    print("=" * 60)
    
    summary = ai_log_summary()
    
    print(f"\nTotal events logged: {summary['total_events']}")
    print(f"\nEvents by type:")
    for evt_type, count in summary['by_type'].items():
        print(f"  • {evt_type}: {count}")
    
    if summary.get('unmapped_products'):
        print(f"\nUnmapped products: {summary['unmapped_products']}")
    
    if summary.get('exceptions'):
        print(f"\nExceptions caught:")
        for exc in summary['exceptions']:
            print(f"  • {exc['type']}: {exc['message'][:50]}... (category: {exc.get('category', 'N/A')})")
    
    if summary.get('fix_suggestions'):
        print(f"\n[!] Fix Suggestions:")
        for sug in summary['fix_suggestions']:
            print(f"  [{sug['category']}] {sug['fix'][:60]}...")
    
    return True


if __name__ == "__main__":
    print("\n[TEST] AI CONTEXT LOGGER TEST SUITE\n")
    
    tests = [
        ("Basic Logging", test_basic_logging),
        ("Exception Logging", test_exception_logging),
        ("Decorator", test_decorator),
        ("Summary", test_summary),
    ]
    
    passed = 0
    for name, test_fn in tests:
        try:
            if test_fn():
                passed += 1
        except Exception as e:
            print(f"\n[X] Test '{name}' failed: {e}")
    
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{len(tests)} tests passed")
    print(f"Log file location: {LOG_FILE}")
    print("=" * 60)
