# Technical Capability Showcase

This project combines source-specific commercial modeling with an orchestrated Qlik reporting workflow. The public repository exposes transformation and publication controls through a synthetic demo; private acquisition, reload, and notification connectors are excluded.

## Capability Map

| Capability | Reporting problem addressed | Inspectable evidence |
| --- | --- | --- |
| Reporting orchestration | Acquisition, processing, reload, checks, and follow-up need one run sequence | [Production-reference orchestrator](../orchestrate_update.py) |
| Multi-scenario modeling | Finance needs full, addressable, and weighted opportunity views | [Public demo](../demo.py), [core pipeline](../core/midwest_pipeline.py), and [demo outputs](DEMO_OUTPUT_WALKTHROUGH.md) |
| Numeric normalization | Conflicting decimal and thousands separators can change magnitudes silently | [Shared parser](../core/utils.py) and [parser tests](../tests/test_numeric_parser.py) |
| Publication controls | A failed candidate must not replace the last valid dataset | [Publication helper](../core/publication_control.py) and [control tests](../tests/test_publication_control.py) |
| Source reconciliation | Matching schemas do not establish conservation or correct mappings | [Validation logic](../core/validator.py) and [demo tests](../tests/test_demo.py) |
| Repeatable review | Portfolio visitors need a runnable example without company access | [Public demo boundary](PUBLIC_DEMO_BOUNDARY.md) and [CI workflow](../.github/workflows/ci.yml) |

## Modeling Sources at Different Grains

The production workflow combines SAP sales actuals, MedTech Europe market references where available, separate diagnostics/ICM inputs, Salesforce-entered updates, and internally maintained sales and market-share forecasts. These are source-system roles; they do not imply that each source used a direct API connector.

An important source decision was to use separate native-quarterly ICM company figures while allocating annual ICM market estimates to quarters. The annual market feed's company figures had update-reliability issues. Separating those sources preserved better sales detail while providing a comparable market denominator.

Forecast integration also required product mapping, regional and export treatment, saved planning versions, explicit adjustments, and annual-to-quarter allocation. These production capabilities provide context for the reporting model; the public two-source demo does not reproduce every private forecast-integration path.

The three actual-market views and forecast versions are separate dimensions. Full, Addressable, and Weighted views describe market scope. Live and saved forecasts describe planning positions. Allocated forecast quarters are modeled values, not observed quarterly sales.

The public demo checks organization-unit and revenue conservation across its three scenarios. Its [output walkthrough](DEMO_OUTPUT_WALKTHROUGH.md) shows retained organization totals and changing market denominators. This demonstrates the synthetic model's invariant; it should not be generalized to every revenue measure in every historical production view.

## Numeric and Dimensional Normalization

The shared parser validates grouping patterns and requires an explicit policy for ambiguous single separators:

```python
num_smart("1.234,56")                         # 1234.56
num_smart("1,234.56")                         # 1234.56
num_smart("6'170.00")                         # 6170.0
num_smart("1,234")                            # NaN: ambiguous
num_smart("1,234", ambiguous="thousands")     # 1234.0
num_smart("1,234", ambiguous="decimal")       # 1.234
```

The project history records a 1,000-fold forecast inflation defect involving European decimal interpretation. Parsing rules and magnitude comparisons address different parts of that risk: a successful numeric conversion alone does not establish the intended value.

Territory mappings also encode reporting ownership. Regional groupings and export assignments cannot always be resolved with a standard country-name lookup. Source and country-level reconciliation help detect omissions or misallocation during integration.

## Authenticated Acquisition

The private workflow used Selenium browser automation and configured Chrome-profile support to acquire extracts and trigger Qlik actions. Persistent profiles reduce repeated sign-in prompts; session validity still depends on the environment and authentication policies.

Those connectors are not included in the public repository. Browser authentication, download-completion handling, and reload behavior are outside the public demo's verification scope. No claim is made here of filesystem mutex locks, automatic orphan-process recovery, a guaranteed session duration, or a REST-based reload implementation.

## Publication and Downstream Verification

The [publication helper](../core/publication_control.py) persists QA evidence, rejects failed or inconsistent reports, and replaces each destination CSV using an atomic file operation. Atomic replacement applies to each file; it is not a transaction spanning multiple destinations and Qlik.

The production-reference orchestrator checks current-run candidate and QA artifacts before reload. After triggering reload, it waits for the configured interval and polls for fresh verification output. Missing or stale evidence produces `UNVERIFIED` (exit 2); returned validation failures produce `FAILED` (exit 1), and verified success uses exit 0. The orchestrator does not itself poll a Qlik server completion token.

The downstream comparison implementation is private. Its metric units and tolerances must be established by that connector's contract; the public reference code does not establish a universal one-euro tolerance. Post-reload reconciliation can detect discrepancies after publication, so it does not guarantee that a later BI discrepancy was never visible.

## Quality Reports and Human Review

The production-reference workflow calls private helpers to generate plausibility reports and country-specific HTML controller drafts, then attaches available artifacts to the configured summary. Drafts support analyst review and follow-up; generating them is different from independently sending each controller a message or accepting a forecast as correct.

Forecast review focuses on patterns such as unchanged baselines, suspiciously round inputs, gaps, and abrupt changes. These are investigation prompts, not automatic judgments that a commercial assumption is wrong.

## Testing and Reproducibility

The public pytest suite covers numeric parsing, mappings, schemas, scenario behavior, publication blocking, terminal statuses, and the synthetic demo. Temporary fixtures exercise malformed inputs. Checks requiring excluded connectors or production artifacts skip explicitly when those dependencies are absent.

Use [the README's demo and test commands](../README.md) for the supported workflow. A passing public run validates the covered local behavior; it does not verify authentication, a live Qlik tenant, or a historical processing-time comparison.

## Further Reading

- [Executive case study](PORTFOLIO_EXECUTIVE_CASE_STUDY.md)
- [Quality matrix](PORTFOLIO_DATA_QUALITY_MATRIX.md)
- [Public demo boundary](PUBLIC_DEMO_BOUNDARY.md)
