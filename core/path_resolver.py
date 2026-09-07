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
_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")

# Only these YAML values represent filesystem locations. Other strings such as
# app IDs, email addresses, selectors, and environment names must remain text.
_PATH_FIELDS = frozenset(
    {
        ("storage", "midwest_root"),
        ("storage", "onedrive_data_qvd"),
        ("storage", "onedrive_assets"),
        ("data_sources", "crm"),
        ("data_sources", "icm_market"),
        ("data_sources", "icm_bio"),
        ("data_sources", "unconventional_market"),
        ("data_sources", "redbull_live"),
        ("data_sources", "redbull_static_dir"),
        ("data_sources", "redbull_adjustments_dir"),
        ("data_sources", "map_country_export"),
        ("data_sources", "rb_mapping_xlsx"),
        ("data_sources", "communal_mapping_table"),
        ("data_sources", "qvd_source_file"),
        ("outputs", "final_csv"),
        ("outputs", "qa_report_json"),
        ("outputs", "qvd_target_dir"),
        ("selenium", "chrome_profile_path"),
    }
)


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


def _resolve_value(value: Any, key_path: tuple[str, ...] = ()) -> Any:
    """Expand placeholders and resolve only explicitly declared path fields."""
    if isinstance(value, dict):
        return {
            key: _resolve_value(item, key_path + (str(key),))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_resolve_value(item, key_path) for item in value]
    if isinstance(value, str):
        expanded = _expand_placeholders(value)
        if key_path not in _PATH_FIELDS or _ENV_VAR_RE.search(expanded):
            return expanded

        path = Path(expanded)
        is_external_absolute = (
            path.is_absolute()
            or bool(_WINDOWS_ABSOLUTE_RE.match(expanded))
            or expanded.startswith("\\\\")
        )
        return path if is_external_absolute else PROJECT_ROOT / path
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


def get_config_path(
    section: str,
    key: str,
    *,
    config: Dict[str, Any] | None = None,
) -> Path:
    """Return one declared path field and reject unresolved placeholders.

    Raises *KeyError* if the field does not exist and *ValueError* if the
    path still contains an un-expanded ``${…}`` placeholder (meaning the
    required environment variable is not set).
    """
    if (section, key) not in _PATH_FIELDS:
        raise KeyError(f"{section}.{key} is not a declared path field")

    cfg = resolve_config() if config is None else config
    value = cfg[section][key]
    if isinstance(value, str) and _ENV_VAR_RE.search(value):
        raise ValueError(
            f"{section}.{key} contains an unresolved placeholder: {value!r}.  "
            f"Set the corresponding environment variable before running."
        )
    if not isinstance(value, (str, Path)):
        raise TypeError(f"{section}.{key} is not path-like: {value!r}")
    return Path(value)


def get_storage_path(key: str) -> Path:
    """Convenience wrapper for a resolved path in the ``storage`` section."""
    return get_config_path("storage", key)
