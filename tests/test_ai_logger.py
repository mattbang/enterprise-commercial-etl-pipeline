import pytest

import core.ai_logger as ai_logger


@pytest.fixture(autouse=True)
def isolated_log_file(monkeypatch, tmp_path):
    log_file = tmp_path / "ai_context.jsonl"
    monkeypatch.setattr(ai_logger, "LOG_FILE", log_file)
    ai_logger.ai_log_clear()
    return log_file


def test_basic_logging(isolated_log_file):
    ai_logger.ai_log(
        "unmapped_product",
        raw_value="Synthetic Product A",
        source="portfolio-test",
    )
    ai_logger.ai_log(
        "territory_remap",
        original="Synthetic Territory",
        mapped_to="Example Market",
    )
    ai_logger.ai_log("zero_units", country="Example", product="ICM", year=2025)

    summary = ai_logger.ai_log_summary()

    assert isolated_log_file.exists()
    assert summary["total_events"] == 3
    assert summary["by_type"] == {
        "unmapped_product": 1,
        "territory_remap": 1,
        "zero_units": 1,
    }
    assert summary["unmapped_products"] == ["Synthetic Product A"]


def test_exception_logging_returns_matching_fix_suggestions():
    try:
        raise KeyError("MKT")
    except KeyError as exc:
        column_suggestion = ai_logger.ai_log_exception(
            exc,
            context={"file": "synthetic_loader.py"},
        )

    try:
        raise FileNotFoundError("synthetic_input.xlsx not found")
    except FileNotFoundError as exc:
        file_suggestion = ai_logger.ai_log_exception(exc)

    assert column_suggestion["category"] == "column_missing"
    assert file_suggestion["category"] == "file_missing"
    assert ai_logger.ai_log_summary()["by_type"]["exception"] == 2


def test_decorator_logs_and_reraises_exception():
    @ai_logger.log_exceptions
    def failing_function():
        raise KeyError("COUNTRY_NAME")

    with pytest.raises(KeyError, match="COUNTRY_NAME"):
        failing_function()

    summary = ai_logger.ai_log_summary()
    assert summary["by_type"]["exception"] == 1
    assert summary["exceptions"][0]["category"] == "country_mapping"


def test_clear_removes_existing_events():
    ai_logger.ai_log("file_loaded", file="synthetic.csv", rows=3)
    assert ai_logger.ai_log_summary()["total_events"] == 1

    ai_logger.ai_log_clear()

    assert ai_logger.ai_log_summary()["total_events"] == 0
