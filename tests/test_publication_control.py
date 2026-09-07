import json
import os
import time
from pathlib import Path

import pandas as pd
import pytest

from core.publication_control import (
    BlockingValidationError,
    RunStatus,
    exit_code_for,
    load_fresh_validation_report,
    missing_or_stale_files,
    publish_validated_frame,
    require_passing_report,
    terminal_status,
    validation_result_failures,
)


def passing_report() -> dict:
    return {
        "overall_pass": True,
        "checks": [
            {"check": "schema", "pass": True},
            {"check": "conservation", "pass": True},
        ],
    }


def test_failed_validation_preserves_last_published_datasets(tmp_path: Path):
    local = tmp_path / "local.csv"
    downstream = tmp_path / "downstream.csv"
    report_path = tmp_path / "qa.json"
    local.write_text("last valid local\n", encoding="utf-8")
    downstream.write_text("last valid downstream\n", encoding="utf-8")
    failed = {
        "overall_pass": False,
        "checks": [{"check": "conservation", "pass": False}],
    }

    with pytest.raises(BlockingValidationError, match="conservation"):
        publish_validated_frame(
            pd.DataFrame({"units": [999]}),
            failed,
            report_path=report_path,
            destinations=[local, downstream],
        )

    assert local.read_text(encoding="utf-8") == "last valid local\n"
    assert downstream.read_text(encoding="utf-8") == "last valid downstream\n"
    assert json.loads(report_path.read_text(encoding="utf-8"))["overall_pass"] is False


def test_passing_candidate_is_published_to_each_unique_destination(tmp_path: Path):
    local = tmp_path / "local.csv"
    downstream = tmp_path / "downstream.csv"
    report_path = tmp_path / "qa.json"
    frame = pd.DataFrame({"country": ["Example"], "units": [12.5]})

    published = publish_validated_frame(
        frame,
        passing_report(),
        report_path=report_path,
        destinations=[local, downstream, local],
    )

    assert published == [local, downstream]
    assert local.read_bytes() == downstream.read_bytes()
    assert "12,5" in local.read_text(encoding="utf-8")
    assert json.loads(report_path.read_text(encoding="utf-8"))["overall_pass"] is True


def test_inconsistent_report_summary_fails_closed():
    report = {
        "overall_pass": True,
        "checks": [{"check": "schema", "pass": False}],
    }

    with pytest.raises(BlockingValidationError, match="schema"):
        require_passing_report(report)


def test_fresh_report_is_required_for_current_run(tmp_path: Path):
    report_path = tmp_path / "qa.json"
    report_path.write_text(json.dumps(passing_report()), encoding="utf-8")
    now = time.time()

    assert load_fresh_validation_report(
        report_path,
        not_before=now,
        timestamp_tolerance_seconds=1.0,
    )["overall_pass"] is True

    old_time = now - 60
    os.utime(report_path, (old_time, old_time))
    with pytest.raises(BlockingValidationError, match="stale"):
        load_fresh_validation_report(
            report_path,
            not_before=now,
            timestamp_tolerance_seconds=0,
        )


def test_missing_empty_and_stale_artifacts_are_rejected(tmp_path: Path):
    missing = tmp_path / "missing.csv"
    empty = tmp_path / "empty.csv"
    stale = tmp_path / "stale.csv"
    fresh = tmp_path / "fresh.csv"
    empty.touch()
    stale.write_text("old\n", encoding="utf-8")
    fresh.write_text("new\n", encoding="utf-8")
    now = time.time()
    os.utime(stale, (now - 60, now - 60))

    rejected = missing_or_stale_files(
        [missing, empty, stale, fresh],
        not_before=now,
        timestamp_tolerance_seconds=1.0,
    )

    assert rejected == [missing, empty, stale]


def test_terminal_status_and_exit_codes_are_unambiguous():
    assert terminal_status() is RunStatus.SUCCESS
    assert terminal_status(verification_complete=False) is RunStatus.UNVERIFIED
    assert terminal_status(failures=["reload failed"], verification_complete=False) is RunStatus.FAILED
    assert exit_code_for(RunStatus.SUCCESS) == 0
    assert exit_code_for(RunStatus.FAILED) == 1
    assert exit_code_for(RunStatus.UNVERIFIED) == 2


def test_downstream_failures_are_normalized():
    results = {
        "checksum": {"pass": False, "msg": "totals differ"},
        "freshness": {"pass": True, "msg": "current"},
    }

    assert validation_result_failures(results) == ["checksum: totals differ"]


def test_mapping_audit_participates_in_blocking_report():
    from core.midwest_pipeline import qa_redbull_mapping

    product_map = pd.DataFrame(
        {
            "PRODUCT": ["Product A", "Product A"],
            "RB_PRODUCT_NAME": ["Mapped A", "Conflicting A"],
        }
    )
    candidate = pd.DataFrame(
        {
            "BUSINESS_SEGMENT": ["IPG"],
            "PRODUCT": ["Product A"],
            "PRODUCT_CANON": ["PRODUCT A"],
            "RB_PRODUCT_NAME": ["Mapped A"],
            "REDBULL PRODUCT": ["Mapped A"],
        }
    )
    report = {"overall_pass": True, "checks": []}

    qa_redbull_mapping(product_map, candidate, qa_report=report)

    assert report["overall_pass"] is False
    assert report["checks"][-1] == {
        "check": "RedBull product mapping integrity",
        "pass": False,
    }
