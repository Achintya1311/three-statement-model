"""Every CLI prints the SEBI disclaimer as its first stdout line (S26)."""

import importlib

import pytest

import model

EXPECTED = (
    "Educational research on historical data. Not investment advice. "
    "Not a SEBI-registered research analyst."
)


def test_package_exports_the_plan_rule_1_disclaimer():
    assert model.DISCLAIMER == EXPECTED


@pytest.mark.parametrize(
    "module_name",
    ["build", "costs", "debt", "ingest", "revenue", "revolver", "sensitivity", "statements"],
)
def test_cli_prints_the_disclaimer_first(module_name, capsys, tmp_path):
    module = importlib.import_module(f"model.{module_name}")
    argv = ["--ticker", "GULFOILLUB"]
    if module_name == "build":
        argv += ["--export", str(tmp_path / "model.xlsx")]
    exit_code = module.main(argv)
    out = capsys.readouterr().out
    assert exit_code == 0
    assert out.splitlines()[0] == EXPECTED
