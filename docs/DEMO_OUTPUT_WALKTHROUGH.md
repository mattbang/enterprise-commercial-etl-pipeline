# Demo Output Walkthrough

This folder captures one successful run of the public synthetic demo and one controlled failure. It lets reviewers inspect the transformation and controls without installing the project.

## Successful run

The demo reconciled 20 source rows into 28 candidate output rows across three reporting scenarios. All 10 blocking checks passed, so the transformed dataset was published.

| File | What to inspect |
| :--- | :--- |
| [Scenario summary](demo_output/scenario_summary.csv) | The three reporting views side by side. Market scope changes while organization totals remain constant. |
| [Transformed dataset](demo_output/transformed_dataset.csv) | Row-level country, quarter, product, market, organization, and weighting evidence. |
| [Quality report](demo_output/data_quality_report.json) | Machine-readable results for source grain, reconciliation, numeric completeness, mappings, scenario generation, conservation, and capacity. |
| [Run summary](demo_output/run_summary.txt) | The compact operator-facing outcome. |

The scenario summary demonstrates the key business rule: organization volume remains 997 units and organization revenue remains 5,692 K EUR in every reporting view. Only the market scope changes.

## Controlled failure

The [failure quality report](demo_output/failure_example/data_quality_report.json) captures a deliberately injected case where organization units exceed the weighted market. Nine checks pass, the capacity check fails, and zero output rows are published. The accompanying [failure run summary](demo_output/failure_example/run_summary.txt) records the blocked outcome.

Reproduce it with:

```bash
python demo.py --simulate-capacity-failure --output-dir demo_output/failure_example
```
