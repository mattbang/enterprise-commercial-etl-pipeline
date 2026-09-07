# Changelog

## 1.0.0 - 2026-09-07

First Public Portfolio Edition.

### Added

- Standalone synthetic demo with three market scenarios and inspectable output.
- Controlled capacity failure with a quality report and non-zero exit.
- Public parser, configuration, publication, regression, and demo tests.
- GitHub Actions on Python 3.10 and 3.12, using pinned action commits.
- Project overview, contribution summary, LinkedIn contact, and Canva handout.

### Corrected

- Locale-aware parsing, including Swiss separators and explicit ambiguity handling.
- Shared helpers and configuration resolution for designated path fields.
- Blocking validation before publication and explicit downstream verification status.
- Claims that confused local validation with downstream verification.
- Public identifiers and workbook fixtures; reachable history starts from a sanitized baseline.

### Scope

The supported entry point is `demo.py`. Production connectors, authentication, cloud reloads, and notifications are excluded. Tests requiring those services skip explicitly. Dependencies use minimum version requirements rather than a lockfile. GitHub may retain old unreachable objects outside the rewritten branch history; server-side removal is a separate process.
