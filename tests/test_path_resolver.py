from datetime import datetime
from pathlib import Path, PureWindowsPath

import pytest

from core import path_resolver


@pytest.fixture(autouse=True)
def reset_config_cache(monkeypatch):
    monkeypatch.delenv("MIDWEST_ROOT", raising=False)
    path_resolver._cached_config = None
    yield
    path_resolver._cached_config = None


def test_only_declared_path_fields_become_paths():
    config = path_resolver.resolve_config(force_reload=True)

    assert config["environment"] == "production"
    assert config["email"]["recipient"] == "alerts@example.invalid"
    assert config["qlik_apps"]["asp_ms_addressable"]["id"] == "aaaaaaaaaaaaaaaaaaaaaaaa"
    assert config["selenium"]["selectors"]["reload_button"][0] == "//span[text()='Reload now']"
    assert config["thresholds"]["preservation"]["unit_tolerance"] == 1.5

    assert config["data_sources"]["crm"] == (
        path_resolver.PROJECT_ROOT / "data/in/Market Tracker CRM DL.xlsx"
    )
    assert config["outputs"]["final_csv"] == (
        path_resolver.PROJECT_ROOT / "data/out/MarketData_ASP_&_MS_Final_python.csv"
    )
    assert config["selenium"]["chrome_profile_path"] == (
        path_resolver.PROJECT_ROOT / "chrome_automation_profile"
    )


def test_unresolved_path_placeholders_remain_detectable():
    config = path_resolver.resolve_config(force_reload=True)

    assert config["storage"]["midwest_root"] == "${MIDWEST_ROOT}"
    assert config["outputs"]["qvd_target_dir"] == "${MIDWEST_ROOT}/DATA_QVD/ASP_MS_DATA"
    with pytest.raises(ValueError, match="unresolved placeholder"):
        path_resolver.get_storage_path("midwest_root")
    with pytest.raises(ValueError, match="outputs.qvd_target_dir"):
        path_resolver.get_config_path("outputs", "qvd_target_dir", config=config)


def test_path_accessor_rejects_non_path_fields():
    with pytest.raises(KeyError, match="email.recipient"):
        path_resolver.get_config_path("email", "recipient")


def test_environment_paths_expand_to_path_objects(monkeypatch, tmp_path):
    synthetic_root = tmp_path / "synthetic-org"
    monkeypatch.setenv("MIDWEST_ROOT", str(synthetic_root))

    config = path_resolver.resolve_config(force_reload=True)

    assert config["storage"]["midwest_root"] == synthetic_root
    assert config["storage"]["onedrive_data_qvd"] == synthetic_root / "DATA_QVD"
    assert config["outputs"]["qvd_target_dir"] == synthetic_root / "DATA_QVD/ASP_MS_DATA"
    assert path_resolver.get_storage_path("midwest_root") == synthetic_root
    assert path_resolver.get_config_path(
        "outputs", "qvd_target_dir", config=config
    ) == synthetic_root / "DATA_QVD/ASP_MS_DATA"


def test_external_windows_path_is_not_made_project_relative():
    config = path_resolver.resolve_config(force_reload=True)
    shared_mapping = config["data_sources"]["communal_mapping_table"]
    windows_mapping = PureWindowsPath(shared_mapping)

    assert isinstance(shared_mapping, Path)
    assert windows_mapping.drive == "S:"
    assert windows_mapping.parts[1:3] == ("Shared", "Finance")
    assert str(datetime.now().year) in str(shared_mapping)
    assert "{YEAR}" not in str(shared_mapping)
    assert not str(shared_mapping).startswith(str(path_resolver.PROJECT_ROOT))


def test_force_reload_refreshes_environment_expansion(monkeypatch, tmp_path):
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    monkeypatch.setenv("MIDWEST_ROOT", str(first_root))
    first = path_resolver.resolve_config(force_reload=True)

    monkeypatch.setenv("MIDWEST_ROOT", str(second_root))
    cached = path_resolver.resolve_config()
    refreshed = path_resolver.resolve_config(force_reload=True)

    assert cached["storage"]["midwest_root"] == first_root
    assert refreshed["storage"]["midwest_root"] == second_root
