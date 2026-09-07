import json
from pathlib import Path

import pandas as pd
import pytest

from demo import DEFAULT_CONFIG, DemoValidationError, ROOT, run_demo


def test_demo_writes_three_scenarios_and_passes_checks(tmp_path: Path):
    output_dir = tmp_path / "output"

    report = run_demo(DEFAULT_CONFIG, ROOT / "data" / "demo", output_dir)

    assert report["status"] == "PASS"
    assert report["checks_passed"] == report["checks_total"]
    assert (output_dir / "data_quality_report.json").exists()
    assert (output_dir / "run_summary.txt").exists()
    assert (output_dir / "scenario_summary.csv").exists()

    output = pd.read_csv(output_dir / "transformed_dataset.csv")
    assert set(output["version"]) == {
        "Actual Full",
        "Actual Addressable",
        "Actual Addressable weighted",
    }

    totals = output.groupby("version")[["org_units", "org_revenue_keur"]].sum()
    assert totals["org_units"].nunique() == 1
    assert totals["org_revenue_keur"].nunique() == 1

    scenario_summary = pd.read_csv(output_dir / "scenario_summary.csv")
    assert scenario_summary["version"].tolist() == [
        "Actual Full",
        "Actual Addressable",
        "Actual Addressable weighted",
    ]
    assert scenario_summary["market_units"].tolist() == pytest.approx([3790.0, 3670.0, 2959.6])


def test_demo_capacity_failure_blocks_publication(tmp_path: Path):
    with pytest.raises(DemoValidationError, match="blocking output validation"):
        run_demo(
            DEFAULT_CONFIG,
            ROOT / "data" / "demo",
            tmp_path / "output",
            simulate_capacity_failure=True,
        )

    report = json.loads((tmp_path / "output" / "data_quality_report.json").read_text())
    assert report["status"] == "FAIL"
    assert report["candidate_rows"] == 28
    assert report["output_rows"] == 0
    assert not (tmp_path / "output" / "transformed_dataset.csv").exists()


def test_committed_demo_evidence_matches_current_generator(tmp_path: Path):
    success_output = tmp_path / "success"
    run_demo(DEFAULT_CONFIG, ROOT / "data" / "demo", success_output)

    committed_output = ROOT / "docs" / "demo_output"
    for filename in (
        "transformed_dataset.csv",
        "scenario_summary.csv",
        "data_quality_report.json",
        "run_summary.txt",
    ):
        assert (success_output / filename).read_bytes() == (committed_output / filename).read_bytes()

    failure_output = tmp_path / "failure"
    with pytest.raises(DemoValidationError):
        run_demo(
            DEFAULT_CONFIG,
            ROOT / "data" / "demo",
            failure_output,
            simulate_capacity_failure=True,
        )

    for filename in ("data_quality_report.json", "run_summary.txt"):
        assert (failure_output / filename).read_bytes() == (
            committed_output / "failure_example" / filename
        ).read_bytes()
