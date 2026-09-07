"""Run the self-contained public portfolio demonstration.

This entry point uses only synthetic files committed under ``data/demo``. It
does not import private connectors or contact external services.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from core.utils import canon_product, quarter_to_numeric


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config" / "demo_config.yaml"

KEY_COLUMNS = ["country", "quarter", "business_segment", "product_group"]
MARKET_COLUMNS = KEY_COLUMNS + ["market_units", "market_revenue_keur"]
ORG_COLUMNS = KEY_COLUMNS + ["org_units", "org_revenue_keur"]


class DemoValidationError(RuntimeError):
    """Raised when a blocking public-demo validation fails."""


def _load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    for section in ("inputs", "outputs", "product_rules"):
        if section not in config:
            raise DemoValidationError(f"Demo config is missing the '{section}' section.")
    return config


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "status": "PASS" if passed else "FAIL", "detail": detail}


def _require_columns(frame: pd.DataFrame, required: list[str], source: str) -> None:
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise DemoValidationError(f"{source} is missing required columns: {', '.join(missing)}")


def _load_sources(input_dir: Path, config: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    market_path = input_dir / config["inputs"]["market"]
    org_path = input_dir / config["inputs"]["organization"]

    if not market_path.exists() or not org_path.exists():
        missing = [str(path) for path in (market_path, org_path) if not path.exists()]
        raise DemoValidationError(f"Missing synthetic demo input: {', '.join(missing)}")

    market = pd.read_csv(market_path)
    organization = pd.read_csv(org_path)
    _require_columns(market, MARKET_COLUMNS, market_path.name)
    _require_columns(organization, ORG_COLUMNS, org_path.name)
    return market[MARKET_COLUMNS].copy(), organization[ORG_COLUMNS].copy()


def _normalize_keys(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    for column in KEY_COLUMNS:
        normalized[column] = normalized[column].astype(str).str.strip()
    normalized["product_group"] = normalized["product_group"].map(canon_product)
    normalized["business_segment"] = normalized["business_segment"].str.upper()
    return normalized


def _validate_sources(market: pd.DataFrame, organization: pd.DataFrame) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    market_duplicates = int(market.duplicated(KEY_COLUMNS, keep=False).sum())
    org_duplicates = int(organization.duplicated(KEY_COLUMNS, keep=False).sum())
    checks.append(
        _check(
            "Unique source grain",
            market_duplicates == 0 and org_duplicates == 0,
            f"market duplicate rows={market_duplicates}; organization duplicate rows={org_duplicates}",
        )
    )

    quarter_values = pd.concat([market["quarter"], organization["quarter"]], ignore_index=True)
    quarter_valid = quarter_values.map(lambda value: pd.notna(quarter_to_numeric(value)[0]))
    checks.append(
        _check(
            "Quarter format",
            bool(quarter_valid.all()),
            f"valid values={int(quarter_valid.sum())}/{len(quarter_valid)}",
        )
    )

    numeric_columns = ["market_units", "market_revenue_keur", "org_units", "org_revenue_keur"]
    combined = market.merge(organization, on=KEY_COLUMNS, how="outer", indicator=True)
    complete_match = bool((combined["_merge"] == "both").all())
    checks.append(
        _check(
            "Source key reconciliation",
            complete_match,
            f"matched rows={int((combined['_merge'] == 'both').sum())}/{len(combined)}",
        )
    )

    numeric_complete = True
    nonnegative = True
    for column in numeric_columns:
        converted = pd.to_numeric(combined[column], errors="coerce")
        numeric_complete = numeric_complete and bool(converted.notna().all())
        nonnegative = nonnegative and bool(converted.dropna().ge(0).all())

    checks.append(_check("Numeric completeness", numeric_complete, "all four measures must be numeric"))
    checks.append(_check("Non-negative measures", nonnegative, "market and organization measures must be >= 0"))
    return checks


def _build_scenarios(joined: pd.DataFrame, product_rules: dict[str, Any]) -> pd.DataFrame:
    normalized_rules = {canon_product(name): rule for name, rule in product_rules.items()}
    joined = joined.copy()
    joined["addressable"] = joined["product_group"].map(
        lambda product: normalized_rules.get(product, {}).get("addressable")
    )
    joined["addressable_weight"] = joined["product_group"].map(
        lambda product: normalized_rules.get(product, {}).get("weight")
    )

    full = joined.copy()
    full["version"] = "Actual Full"

    addressable = joined[joined["addressable"] == True].copy()  # noqa: E712
    addressable["version"] = "Actual Addressable"

    weighted = addressable.copy()
    weighted["market_units"] = weighted["market_units"] * weighted["addressable_weight"]
    weighted["market_revenue_keur"] = weighted["market_revenue_keur"] * weighted["addressable_weight"]
    weighted["version"] = "Actual Addressable weighted"

    output = pd.concat([full, addressable, weighted], ignore_index=True)
    return output[
        [
            "version",
            *KEY_COLUMNS,
            "market_units",
            "market_revenue_keur",
            "org_units",
            "org_revenue_keur",
            "addressable_weight",
        ]
    ]


def _validate_output(
    joined: pd.DataFrame,
    output: pd.DataFrame,
    product_rules: dict[str, Any],
    tolerance: float,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    normalized_rule_names = {canon_product(name) for name in product_rules}
    unmapped = sorted(set(joined["product_group"]) - normalized_rule_names)
    checks.append(
        _check(
            "Product rule coverage",
            not unmapped,
            "all products mapped" if not unmapped else f"unmapped products={len(unmapped)}",
        )
    )

    normalized_rules = {canon_product(name): rule for name, rule in product_rules.items()}
    weights = pd.to_numeric(joined["product_group"].map(
        lambda product: normalized_rules.get(product, {}).get("weight")
    ), errors="coerce")
    valid_weights = bool(weights.notna().all() and weights.between(0, 1).all())
    checks.append(_check("Weight bounds", valid_weights, "all scenario weights must be between 0 and 1"))

    versions = set(output["version"])
    expected_versions = {"Actual Full", "Actual Addressable", "Actual Addressable weighted"}
    checks.append(
        _check(
            "Three reporting scenarios",
            versions == expected_versions,
            f"generated scenarios={len(versions)}",
        )
    )

    org_totals = output.groupby("version")[["org_units", "org_revenue_keur"]].sum()
    unit_spread = float(org_totals["org_units"].max() - org_totals["org_units"].min())
    revenue_spread = float(org_totals["org_revenue_keur"].max() - org_totals["org_revenue_keur"].min())
    checks.append(
        _check(
            "Organization metric conservation",
            unit_spread <= tolerance and revenue_spread <= tolerance,
            f"unit spread={unit_spread:.6f}; revenue spread={revenue_spread:.6f} K EUR",
        )
    )

    weighted = output[output["version"] == "Actual Addressable weighted"]
    capacity_ok = bool(
        (weighted["org_units"] <= weighted["market_units"] + tolerance).all()
        and (weighted["org_revenue_keur"] <= weighted["market_revenue_keur"] + tolerance).all()
    )
    checks.append(
        _check(
            "Weighted market capacity",
            capacity_ok,
            "organization measures cannot exceed the weighted market",
        )
    )
    return checks


def _write_summary(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "PUBLIC PORTFOLIO DEMO",
        f"Status: {report['status']}",
        f"Source rows: {report['source_rows']}",
        f"Output rows: {report['output_rows']}",
        f"Blocking checks passed: {report['checks_passed']}/{report['checks_total']}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_scenario_summary(output: pd.DataFrame) -> pd.DataFrame:
    scenario_order = ["Actual Full", "Actual Addressable", "Actual Addressable weighted"]
    summary = (
        output.groupby("version", as_index=False)
        .agg(
            rows=("version", "size"),
            market_units=("market_units", "sum"),
            market_revenue_keur=("market_revenue_keur", "sum"),
            org_units=("org_units", "sum"),
            org_revenue_keur=("org_revenue_keur", "sum"),
        )
        .set_index("version")
        .reindex(scenario_order)
        .reset_index()
    )
    return summary


def run_demo(
    config_path: Path,
    input_dir: Path,
    output_dir: Path,
    *,
    simulate_capacity_failure: bool = False,
) -> dict[str, Any]:
    """Run the synthetic pipeline and write inspectable outputs."""
    config = _load_config(config_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = output_dir / config["outputs"]["dataset"]
    scenario_summary_path = output_dir / config["outputs"]["scenario_summary"]
    report_path = output_dir / config["outputs"]["quality_report"]
    summary_path = output_dir / config["outputs"]["run_summary"]
    for generated_data_path in (dataset_path, scenario_summary_path):
        generated_data_path.unlink(missing_ok=True)

    checks: list[dict[str, Any]] = []
    source_rows = 0
    candidate_rows = 0
    output_rows = 0

    try:
        market, organization = _load_sources(input_dir, config)
        market = _normalize_keys(market)
        organization = _normalize_keys(organization)
        source_rows = len(market) + len(organization)
        checks.extend(_validate_sources(market, organization))

        if any(check["status"] == "FAIL" for check in checks):
            raise DemoValidationError("A source validation check failed.")

        joined = market.merge(organization, on=KEY_COLUMNS, how="inner", validate="one_to_one")
        numeric_columns = ["market_units", "market_revenue_keur", "org_units", "org_revenue_keur"]
        joined[numeric_columns] = joined[numeric_columns].apply(pd.to_numeric)
        if simulate_capacity_failure:
            first_row = joined.index[0]
            joined.loc[first_row, "org_units"] = joined.loc[first_row, "market_units"] + 1

        output = _build_scenarios(joined, config["product_rules"])
        candidate_rows = len(output)
        tolerance = float(config.get("validation", {}).get("tolerance", 0.000001))
        checks.extend(_validate_output(joined, output, config["product_rules"], tolerance))

        if any(check["status"] == "FAIL" for check in checks):
            raise DemoValidationError("A blocking output validation check failed.")

        output = output.sort_values(["version", "country", "quarter", "product_group"]).reset_index(drop=True)
        output_rows = len(output)
        output.to_csv(dataset_path, index=False, float_format="%.2f")
        _build_scenario_summary(output).to_csv(scenario_summary_path, index=False, float_format="%.2f")
        status = "PASS"
        error = None
    except Exception as exc:
        status = "FAIL"
        error = str(exc)

    report = {
        "status": status,
        "source_rows": source_rows,
        "candidate_rows": candidate_rows,
        "output_rows": output_rows,
        "checks_passed": sum(check["status"] == "PASS" for check in checks),
        "checks_total": len(checks),
        "checks": checks,
    }
    if error:
        report["error"] = error

    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    _write_summary(summary_path, report)

    if status != "PASS":
        raise DemoValidationError(error or "The public demo failed validation.")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the self-contained synthetic portfolio demo.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--input-dir", type=Path, default=ROOT / "data" / "demo")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "demo_output")
    parser.add_argument(
        "--simulate-capacity-failure",
        action="store_true",
        help="Inject a synthetic capacity violation to demonstrate blocking behavior.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = run_demo(
            args.config,
            args.input_dir,
            args.output_dir,
            simulate_capacity_failure=args.simulate_capacity_failure,
        )
    except DemoValidationError as exc:
        print(f"Demo blocked: {exc}")
        return 1

    print(
        f"Demo passed {report['checks_passed']}/{report['checks_total']} blocking checks. "
        f"Outputs: {args.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
