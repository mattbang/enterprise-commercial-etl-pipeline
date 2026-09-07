# -*- coding: utf-8 -*-
"""
Centralised path resolution for the QLIK ASP & MS Overview pipeline.

All production modules should import paths from here instead of
constructing their own absolute paths.  External (OneDrive) paths are
read from ``config/pipeline_config.yaml`` and can be overridden with
environment variables (see the YAML file for the variable names).

Usage::

    from core.path_resolver import get_project_root, resolve_config

    ROOT = get_project_root()
    cfg  = resolve_config()          # dict with all resolved paths
    midi_root = cfg["storage"]["midwest_root"]  # Path object
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict

import yaml

# ---------------------------------------------------------------------------
# Project root  (one level up from core/)
# ---------------------------------------------------------------------------
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent


def get_project_root() -> Path:
    """Return the absolute path to the project root directory."""
    return PROJECT_ROOT


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
_ENV_VAR_RE = re.compile(r"\$\{(\w+)\}")
_YEAR_RE = re.compile(r"\{YEAR\}")


def _expand_placeholders(value: str) -> str:
    """Replace ``${VAR}`` with env-var values and ``{YEAR}`` with current year.

    If an env-var is not set the placeholder is left *as-is* so that
    downstream code can detect unconfigured paths and warn the user.
    """
    from datetime import datetime

    def _env_replacer(match: re.Match) -> str:
        var = match.group(1)
        return os.environ.get(var, match.group(0))

    result = _ENV_VAR_RE.sub(_env_replacer, value)
    result = _YEAR_RE.sub(str(datetime.now().year), result)
    return result


def _resolve_value(value: Any) -> Any:
    """Recursively walk a YAML tree and expand env-var placeholders."""
    if isinstance(value, str):
        expanded = _expand_placeholders(value)
        # If it still contains an un-expanded placeholder, return as string
        if _ENV_VAR_RE.search(expanded):
            return expanded
        # Resolve relative paths against PROJECT_ROOT
        p = Path(expanded)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p
    if isinstance(value, dict):
        return {k: _resolve_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_value(item) for item in value]
    return value


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
_cached_config: Dict[str, Any] | None = None


def resolve_config(*, force_reload: bool = False) -> Dict[str, Any]:
    """Load and resolve ``pipeline_config.yaml``.

    The result is cached after the first call.  Pass *force_reload=True*
    to re-read the file (useful in tests).
    """
    global _cached_config
    if _cached_config is not None and not force_reload:
        return _cached_config

    config_path = PROJECT_ROOT / "config" / "pipeline_config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(
            f"Pipeline config not found at {config_path}.  "
            "Are you running from the correct project directory?"
        )

    with open(config_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    _cached_config = _resolve_value(raw)
    return _cached_config


def get_storage_path(key: str) -> Path:
    """Convenience: return a resolved path from the ``storage`` section.

    Raises *KeyError* if the key does not exist and *ValueError* if the
    path still contains an un-expanded ``${…}`` placeholder (meaning the
    required environment variable is not set).
    """
    cfg = resolve_config()
    value = cfg["storage"][key]
    if isinstance(value, str) and _ENV_VAR_RE.search(value):
        raise ValueError(
            f"storage.{key} contains an unresolved placeholder: {value!r}.  "
            f"Set the corresponding environment variable before running."
        )
    return Path(value)
