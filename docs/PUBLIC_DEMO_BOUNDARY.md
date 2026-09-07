# Public Demo Boundary

This repository separates the original production case study from the supported public demonstration. The separation keeps private integrations and operational details out of the portfolio while leaving the transformation pattern and control logic directly verifiable.

## Supported public demonstration

Install `requirements-demo.txt`, then run `python demo.py` from the repository root. The demo:

- reads two committed synthetic CSV sources from `data/demo/`;
- joins market and organization actuals at a defined business grain;
- applies product-level addressability rules from `config/demo_config.yaml`;
- creates Full, Addressable, and Addressable weighted reporting views;
- blocks publication when source reconciliation, mappings, bounds, capacity, or conservation checks fail; and
- writes an inspectable dataset, scenario summary, JSON quality report, and text summary to `demo_output/`.

The public demo has no network calls and requires no browser profile, tenant, shared drive, email account, or private connector.

## Production case study

`orchestrate_update.py` and the detailed architecture documents describe the original production operating model. That path depended on private ingestion, cloud reload, authentication, notification, and downstream verification modules that are intentionally not published.

The production orchestrator is retained as architectural evidence. It is not the public Quick Start and is not expected to run without the private integration package and environment-specific configuration.

## What the demo proves

- source contracts and one-to-one reconciliation;
- externalized business rules;
- three-scenario transformation behavior;
- organization-volume and revenue conservation across scenarios;
- blocking validation with a non-zero process exit; and
- deterministic, locally inspectable outputs.

## What the demo does not claim

- access to or emulation of the original private systems;
- live Qlik reload or downstream tenant verification;
- browser authentication, shared-drive synchronization, or email delivery; or
- reproduction of original commercial data or organization-specific identifiers.

All public-demo inputs and rule values are synthetic portfolio fixtures.

## Controlled failure example

Run the command below to inject a synthetic capacity violation. The process exits non-zero, writes failure evidence, and does not publish either CSV output.

```bash
python demo.py --simulate-capacity-failure --output-dir demo_output/failure_example
```
