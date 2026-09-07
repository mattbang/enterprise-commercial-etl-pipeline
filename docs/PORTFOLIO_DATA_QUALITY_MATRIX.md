# Data Quality and Reconciliation

The reporting workflow checks data before publication and reconciles downstream evidence after Qlik reloads. These stages address different risks. A failed candidate can be blocked locally; a discrepancy found after reload may already have affected the dashboard.

The production case study describes a **17-item quality framework**. The public demo has **10 checks** against synthetic inputs. Neither count is the pytest test count, and the public demo does not reproduce all private production-source checks.

## Publicly Inspectable Controls

| Control | Evidence | Behavior |
| --- | --- | --- |
| Source contracts, mappings, bounds, and conservation | [Demo validator](../core/validator.py), [demo tests](../tests/test_demo.py), and [sample report](demo_output/data_quality_report.json) | A failed demo candidate writes failure evidence and publishes no CSV outputs |
| Blocking QA report | [Publication helper](../core/publication_control.py) | Rejects failed, missing-pass, or internally inconsistent report status before writing a candidate dataset |
| Prior-dataset preservation | [Publication tests](../tests/test_publication_control.py) | A candidate rejected by validation leaves the existing published dataset untouched |
| Atomic file replacement | [Publication helper](../core/publication_control.py) | Uses a temporary sibling and replacement for each destination; does not provide a multi-file or BI transaction |
| Current-run readiness | [Production-reference orchestrator](../orchestrate_update.py) | Requires current candidate and passing QA artifacts before triggering reload |
| Downstream freshness and terminal status | [Orchestrator](../orchestrate_update.py) and [status helpers](../core/publication_control.py) | Missing or stale verification produces `UNVERIFIED`; reported validation failures produce `FAILED` |

The reference orchestrator depends on unpublished integrations. Public tests demonstrate the shared controls and modeled behavior; they do not establish that a live tenant or private connector currently behaves correctly.

## Production Quality Framework

The numbering below retains the case study's checklist. It groups structural controls, post-reload reconciliation, and review heuristics rather than describing 17 sequential blocking stages. Detailed source-specific thresholds depend on the production implementation and metric units.

| # | Check | Purpose and role |
| --- | --- | --- |
| 1 | Output presence and freshness | Identify absent, empty, or stale candidate artifacts before accepting them for use |
| 2 | Column and dimension completeness | Detect missing source, version, country, and product assignments |
| 3 | Country-level preservation | Identify losses or misallocation across reporting territories |
| 4 | Commercial actuals reconciliation | Compare source and transformed company and market contributions |
| 5 | Diagnostics/ICM reconciliation | Preserve annual market totals while retaining separate quarterly company figures |
| 6 | Cross-scenario consistency | Check the intended organization-total invariants across market views |
| 7 | Forecast magnitude comparison | Detect implausible live-versus-baseline differences, including possible parsing defects |
| 8 | Row-count sanity | Identify unexpectedly truncated or filtered datasets |
| 9 | Qlik checksum comparison | After reload, compare downstream aggregates with the expected dataset; missing current-run evidence is distinct from a mismatch |
| 10 | Negative-unit review | Distinguish suspicious negatives from documented returns or other permitted adjustments |
| 11 | Repeated forecast values | Flag possible copying across planning periods for review |
| 12 | Round-number patterns | Flag potential placeholders without assuming that every round forecast is invalid |
| 13 | Unchanged baseline | Identify forecasts that duplicate a historical reference |
| 14 | Quarter-over-quarter changes | Surface unusually abrupt movements for review |
| 15 | Year-over-year changes | Surface unusual annual changes in the reporting context |
| 16 | Time-series gaps | Identify missing periods in expected sequences |
| 17 | Stale reporting periods | Flag sources whose latest period lags the expected reporting horizon |

Checks 11-17 describe review heuristics. A flagged assumption can be commercially valid and still deserve discussion. Counting these as universal publication blockers would misstate their role.

## Reconciliation Limits

Source-to-output and output-to-Qlik comparisons check different parts of the reporting chain. Aggregate agreement is useful evidence but cannot prove that every row, product, country, and period is correct. Dimensional and source-specific checks provide complementary coverage.

A comparison tolerance must name the metric and its units. The public production-reference orchestrator delegates downstream comparisons to a private helper, so it does not establish a universal one-euro checksum tolerance. Revenue expressed in thousands of euros must not be described as though its numeric tolerance were denominated in euros.

The reference orchestrator waits after triggering reload and polls for current-run verification output; it does not receive a server completion token itself. Fresh evidence is a prerequisite for proceeding to downstream checks, not a substitute for those comparisons.

## Lessons from Source Problems

**European decimal parsing.** The project history records a 1,000-fold forecast inflation defect. A value such as `1,500` is ambiguous without a source-format policy: removing the comma can turn an intended decimal into a much larger value. The [shared parser](../core/utils.py) validates grouping and requires an explicit policy for ambiguous separators. This supports the defect class and its correction, without claiming that every historical affected refresh was blocked before publication.

**Territory preservation.** Regional groupings and export ownership require explicit mappings beyond a sovereign-country lookup. Country-level reconciliation helps expose records lost or assigned to the wrong reporting entity. The case study does not rely on an unverified exact loss percentage or a specific join-level incident reconstruction.

**Quarterly company figures.** Separate native-quarterly ICM company actuals addressed update-reliability problems in the company portion of an annual market feed. Choosing the appropriate source for each measure was itself a quality decision, alongside the subsequent arithmetic checks.

## Controller Review

The production workflow generates country-specific HTML drafts from significant plausibility findings and includes available reports in the configured summary notification. An analyst reviews the evidence and decides what to raise with regional controllers. The public demo does not send notifications or exercise those private report generators.

## Further Reading

- [Project overview](../README.md)
- [Technical showcase](PORTFOLIO_TECHNICAL_CAPABILITY_SHOWCASE.md)
- [Public demo boundary](PUBLIC_DEMO_BOUNDARY.md)
- [Controlled failure output](demo_output/failure_example/data_quality_report.json)
