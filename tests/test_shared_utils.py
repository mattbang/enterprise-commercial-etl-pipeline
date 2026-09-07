import pytest

from core import midwest_pipeline, utils


@pytest.mark.parametrize(
    "name",
    [
        "num_smart",
        "quarter_to_numeric",
        "compute_asp_k",
        "canon_product",
        "assert_columns",
        "assert_not_empty",
    ],
)
def test_compatibility_module_reexports_shared_helpers(name):
    assert getattr(midwest_pipeline, name) is getattr(utils, name)


def test_legacy_dedupe_name_aliases_shared_implementation():
    assert midwest_pipeline.dedupe is utils.dedupe_columns


def test_compatibility_config_does_not_materialize_unresolved_placeholders():
    assert "${" not in str(midwest_pipeline.CFG.out_final_csv_qvd)
    assert "${" not in str(midwest_pipeline.CFG.qvd_source_path)
