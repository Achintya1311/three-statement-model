"""Day 6 tests: Excel export with live formulas.

Checks the structural guarantee Day 6 is actually about — every Forecast
cell past the Base column is a formula, never a Python float baked in —
plus the Assumptions sheet's resolved defaults, override wiring, and the
CLI's success/override/error paths. The formula *math* itself (does the
chain of references actually reproduce ``model.statements --no-circular``'s
own numbers) was verified by hand: the workbook was recalculated with
LibreOffice headless and the Forecast sheet's PASS/numbers matched
``python -m model.statements --ticker GULFOILLUB --no-circular`` to the
cent for all 3 real forecast years. That check is now automated in
``tests/test_excel_recalc.py`` (P77), which recalculates with LibreOffice
headless; this file still checks only that the formula strings are wired."""

from pathlib import Path

import pytest
from openpyxl import load_workbook

from model import build
from model.excel_export import (
    ASSUMPTIONS,
    BASE_FORMULA_ROWS,
    BASE_LITERAL_ROWS,
    FORECAST_ROWS,
    build_workbook,
    export_workbook,
)
from model.historical import load_historical_statements
from model.revenue_driver import load_segment_revenue

ROOT = Path(__file__).resolve().parent.parent
GULFOILLUB_CSV = ROOT / "data" / "GULFOILLUB" / "financials.csv"
SEGMENT_CSV = ROOT / "data" / "GULFOILLUB" / "segment_revenue.csv"


def _real_inputs():
    statements = load_historical_statements(GULFOILLUB_CSV)
    segments = load_segment_revenue(GULFOILLUB_CSV, SEGMENT_CSV)
    return statements, segments


# -- build_workbook structure ---------------------------------------------------


def test_build_workbook_has_the_three_sheets_in_order():
    statements, segments = _real_inputs()
    wb = build_workbook("GULFOILLUB", statements, segments, forecast_years=3)
    assert wb.sheetnames == ["Assumptions", "Historical", "Forecast"]


def test_assumptions_sheet_carries_the_sebi_disclaimer():
    statements, segments = _real_inputs()
    wb = build_workbook("GULFOILLUB", statements, segments, forecast_years=3)
    ws = wb["Assumptions"]
    disclaimer_text = " ".join(
        str(ws.cell(row=row, column=1).value or "") for row in range(1, 5)
    )
    assert (
        "Educational research on historical data. Not investment advice. "
        "Not a SEBI-registered research analyst." in disclaimer_text
    )


def test_assumptions_sheet_resolves_the_same_defaults_as_the_cli_modules():
    statements, segments = _real_inputs()
    wb = build_workbook("GULFOILLUB", statements, segments, forecast_years=3)
    ws = wb["Assumptions"]

    values = {}
    row = 5
    for key, _label, _note in ASSUMPTIONS:
        values[key] = ws.cell(row=row, column=3).value
        row += 1

    # Hand/CLI-checked against `python -m model.statements --ticker
    # GULFOILLUB --forecast-years 3 --no-circular`'s own printed defaults.
    assert values["tax_rate"] == pytest.approx(0.256534185173067, rel=1e-6)
    assert values["interest_rate"] == pytest.approx(0.0738304344485208, rel=1e-6)
    assert values["dividend_payout"] == 0.0
    assert values["amortization_rate"] == 0.10
    assert values["revolver_limit"] == pytest.approx(35699.83)


def test_assumptions_sheet_reflects_explicit_overrides_not_the_computed_default():
    statements, segments = _real_inputs()
    wb = build_workbook(
        "GULFOILLUB",
        statements,
        segments,
        forecast_years=3,
        tax_rate=0.30,
        dividend_payout=0.2,
        interest_rate=0.05,
    )
    ws = wb["Assumptions"]
    row_by_key = {key: 5 + i for i, (key, _, _) in enumerate(ASSUMPTIONS)}
    assert ws.cell(row=row_by_key["tax_rate"], column=3).value == 0.30
    assert ws.cell(row=row_by_key["dividend_payout"], column=3).value == 0.2
    assert ws.cell(row=row_by_key["interest_rate"], column=3).value == 0.05


def test_forecast_sheet_has_one_column_per_forecast_year_plus_base():
    statements, segments = _real_inputs()
    wb = build_workbook("GULFOILLUB", statements, segments, forecast_years=4)
    ws = wb["Forecast"]
    header_row = 4
    headers = [ws.cell(row=header_row, column=c).value for c in range(2, 7)]
    assert headers == ["Base (FY2023-24)", "FY2024-25", "FY2025-26", "FY2026-27", "FY2027-28"]


# -- nothing hardcoded inside a formula: the core Day 6 guarantee --------------


def test_every_forecast_year_cell_past_base_is_a_formula_not_a_pasted_value():
    """The Day 6 "done when": nothing in the forecast columns is a literal
    number — every cell either is blank (labels/fiscal-year text rows) or a
    formula string starting with '='."""
    statements, segments = _real_inputs()
    wb = build_workbook("GULFOILLUB", statements, segments, forecast_years=3)
    ws = wb["Forecast"]
    header_row = 4
    row_by_key = {key: header_row + 1 + i for i, (key, _label) in enumerate(FORECAST_ROWS)}

    non_formula_rows = {"fiscal_year"}
    for key, row in row_by_key.items():
        for col in range(3, 6):  # the three forecast-year columns
            value = ws.cell(row=row, column=col).value
            if key in non_formula_rows:
                assert isinstance(value, str) and not value.startswith("=")
            else:
                assert isinstance(value, str) and value.startswith("="), (
                    f"row {key!r} col {col}: expected a formula, got {value!r}"
                )


def test_base_column_only_holds_real_historical_facts_or_formulas_of_them():
    statements, segments = _real_inputs()
    wb = build_workbook("GULFOILLUB", statements, segments, forecast_years=3)
    ws = wb["Forecast"]
    header_row = 4
    row_by_key = {key: header_row + 1 + i for i, (key, _label) in enumerate(FORECAST_ROWS)}

    for key, row in row_by_key.items():
        value = ws.cell(row=row, column=2).value
        if key in BASE_LITERAL_ROWS:
            assert isinstance(value, (int, float))
        elif key in BASE_FORMULA_ROWS:
            assert isinstance(value, str) and value.startswith("=")
        elif key == "fiscal_year":
            assert value == "FY2023-24"
        else:
            assert value is None


def test_forecast_formulas_reference_assumptions_sheet_not_a_literal_rate():
    statements, segments = _real_inputs()
    wb = build_workbook("GULFOILLUB", statements, segments, forecast_years=3)
    ws = wb["Forecast"]
    header_row = 4
    row_by_key = {key: header_row + 1 + i for i, (key, _label) in enumerate(FORECAST_ROWS)}

    tax_rate_formula = ws.cell(row=row_by_key["tax_rate_used"], column=3).value
    assert tax_rate_formula.startswith("=Assumptions!$C$")
    interest_rate_formula = ws.cell(row=row_by_key["interest_rate_used"], column=3).value
    assert interest_rate_formula.startswith("=Assumptions!$C$")


def test_forecast_years_must_be_at_least_one():
    statements, segments = _real_inputs()
    with pytest.raises(ValueError):
        build_workbook("GULFOILLUB", statements, segments, forecast_years=0)


# -- Historical sheet ------------------------------------------------------------


def test_historical_sheet_carries_all_ten_real_fiscal_years():
    statements, segments = _real_inputs()
    wb = build_workbook("GULFOILLUB", statements, segments, forecast_years=3)
    ws = wb["Historical"]
    fiscal_years = [ws.cell(row=row, column=1).value for row in range(4, 14)]
    assert fiscal_years == sorted(fiscal_years)
    assert fiscal_years[-1] == "FY2023-24"
    assert len(fiscal_years) == 10


# -- export_workbook / round trip -----------------------------------------------


def test_export_workbook_writes_a_file_that_reopens_with_formulas_intact(tmp_path):
    statements, segments = _real_inputs()
    out = tmp_path / "model.xlsx"
    export_workbook("GULFOILLUB", statements, segments, 3, out)
    assert out.exists()

    reopened = load_workbook(out)
    ws = reopened["Forecast"]
    header_row = 4
    ebit_row = header_row + 1 + [k for k, _ in FORECAST_ROWS].index("ebit")
    assert ws.cell(row=ebit_row, column=3).value.startswith("=")


# -- CLI (model.build) -----------------------------------------------------------


def test_cli_run_success_writes_workbook(tmp_path):
    export_path = tmp_path / "out.xlsx"
    rc = build.run(
        "GULFOILLUB",
        GULFOILLUB_CSV,
        SEGMENT_CSV,
        3,
        export_path,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        3,
    )
    assert rc == 0
    assert export_path.exists()


def test_cli_run_missing_financials_file_is_an_error(tmp_path):
    rc = build.run(
        "NOPE",
        Path("does/not/exist.csv"),
        SEGMENT_CSV,
        3,
        tmp_path / "out.xlsx",
        None, None, None, None, None, None, None, None, None, None, None, 3,
    )
    assert rc == 1


def test_cli_run_rejects_zero_forecast_years(tmp_path):
    rc = build.run(
        "GULFOILLUB",
        GULFOILLUB_CSV,
        SEGMENT_CSV,
        0,
        tmp_path / "out.xlsx",
        None, None, None, None, None, None, None, None, None, None, None, 3,
    )
    assert rc == 1


def test_cli_main_default_export_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(build, "ROOT", ROOT)
    rc = build.main(["--ticker", "GULFOILLUB", "--years", "2", "--export", str(tmp_path / "x.xlsx")])
    assert rc == 0
    assert (tmp_path / "x.xlsx").exists()
