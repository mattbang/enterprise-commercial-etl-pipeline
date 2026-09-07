"""Blocking publication and run-status controls shared by pipeline entry points."""

from __future__ import annotations

import json
import os
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

import pandas as pd


class RunStatus(str, Enum):
    """Terminal orchestration outcomes."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    UNVERIFIED = "UNVERIFIED"


EXIT_CODES = {
    RunStatus.SUCCESS: 0,
    RunStatus.FAILED: 1,
    RunStatus.UNVERIFIED: 2,
}


class BlockingValidationError(RuntimeError):
    """Raised when a candidate dataset is not eligible for publication."""


class PublicationError(RuntimeError):
    """Raised when a validated candidate cannot be written safely."""


def exit_code_for(status: RunStatus) -> int:
    """Return the documented process exit code for a terminal status."""
    return EXIT_CODES[status]


def failed_checks(report: Mapping[str, Any]) -> list[str]:
    """Return failed check names, including inconsistent report summaries."""
    failures = [
        str(check.get("check") or check.get("name") or "Unnamed validation check")
        for check in report.get("checks", [])
        if not bool(check.get("pass", check.get("status") == "PASS"))
    ]
    if not bool(report.get("overall_pass")) and not failures:
        failures.append("overall_pass")
    return failures


def require_passing_report(report: Mapping[str, Any]) -> None:
    """Reject missing, failed, or internally inconsistent QA reports."""
    failures = failed_checks(report)
    if not bool(report.get("overall_pass")) or failures:
        detail = ", ".join(failures) if failures else "overall_pass"
        raise BlockingValidationError(f"Blocking validation failed: {detail}")


def validation_result_failures(results: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """Normalize downstream validation failures for orchestration status logic."""
    return [
        f"{name}: {result.get('msg', 'validation failed')}"
        for name, result in results.items()
        if not bool(result.get("pass"))
    ]


def terminal_status(
    *,
    failures: Sequence[str] = (),
    verification_complete: bool = True,
) -> RunStatus:
    """Derive one unambiguous terminal status from failures and verification."""
    if failures:
        return RunStatus.FAILED
    if not verification_complete:
        return RunStatus.UNVERIFIED
    return RunStatus.SUCCESS


def _temporary_sibling(path: Path) -> Path:
    return path.with_name(f".{path.name}.{uuid4().hex}.tmp")


def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_sibling(path)
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_csv_write(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_sibling(path)
    try:
        frame.to_csv(
            temporary,
            index=False,
            sep=";",
            encoding="utf-8",
            decimal=",",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def publish_validated_frame(
    frame: pd.DataFrame,
    report: Mapping[str, Any],
    *,
    report_path: Path,
    destinations: Sequence[Path],
) -> list[Path]:
    """Persist QA evidence, then atomically publish only a passing candidate.

    Existing published datasets are left untouched when validation fails.
    Duplicate destination paths are written only once.
    """
    try:
        _atomic_json_write(report_path, report)
    except Exception as exc:
        raise PublicationError(f"Could not persist QA report: {exc}") from exc
    require_passing_report(report)

    unique_destinations = list(dict.fromkeys(Path(path) for path in destinations))
    if not unique_destinations:
        raise PublicationError("No publication destinations were configured.")

    published: list[Path] = []
    try:
        for destination in unique_destinations:
            _atomic_csv_write(frame, destination)
            published.append(destination)
    except Exception as exc:
        raise PublicationError(f"Could not publish validated dataset: {exc}") from exc
    return published


def load_fresh_validation_report(
    report_path: Path,
    *,
    not_before: float,
    timestamp_tolerance_seconds: float = 1.0,
) -> dict[str, Any]:
    """Load a current-run QA report and require all blocking checks to pass."""
    if not report_path.exists():
        raise BlockingValidationError(f"QA report is missing: {report_path}")
    if report_path.stat().st_size == 0:
        raise BlockingValidationError(f"QA report is empty: {report_path}")
    if report_path.stat().st_mtime + timestamp_tolerance_seconds < not_before:
        raise BlockingValidationError(f"QA report is stale: {report_path}")

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BlockingValidationError(f"QA report is unreadable: {report_path}") from exc

    require_passing_report(report)
    return report


def missing_or_stale_files(
    paths: Sequence[Path],
    *,
    not_before: float,
    timestamp_tolerance_seconds: float = 1.0,
) -> list[Path]:
    """Return artifacts that are absent, empty, or older than the current run."""
    rejected: list[Path] = []
    for path in paths:
        if not path.exists():
            rejected.append(path)
            continue
        stat = path.stat()
        if stat.st_size == 0 or stat.st_mtime + timestamp_tolerance_seconds < not_before:
            rejected.append(path)
    return rejected
