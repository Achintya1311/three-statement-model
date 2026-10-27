"""P122 (CRITIQUES.md): the forecast rolls other_assets by capex - D&A only.
Back-cast that rule on the historical years and report how far off it is."""

from pathlib import Path

import pytest

from model import statements
from model.historical import (
    BalanceSheetSummary,
    CashFlowSummary,
    HistoricalStatement,
    IncomeStatement,
    load_historical_statements,
)
from model.linkage import backcast_other_assets_roll

FINANCIALS = Path(__file__).resolve().parents[1] / "data" / "GULFOILLUB" / "financials.csv"


def _year(fy, total_assets, cash, nwc, capex, da):
    return HistoricalStatement(
        fiscal_year=fy,
        shares_outstanding=1.0,
        income=IncomeStatement(
            fiscal_year=fy, revenue=100.0, ebitda=20.0 + da, depreciation_amortization=da,
            ebit=20.0, interest_expense=0.0, tax_expense=5.0, net_profit=15.0,
        ),
        balance_sheet=BalanceSheetSummary(
            fiscal_year=fy, total_assets=total_assets, total_debt=0.0, cash_and_equivalents=cash, net_working_capital=nwc,
        ),
        cash_flow=CashFlowSummary(fiscal_year=fy, capex=capex, depreciation_amortization=da),
    )


def test_backcast_known_answer():
    # other_assets 50 -> 65 (+15); rule says capex 10 - D&A 4 = +6; residual 9.
    rows = backcast_other_assets_roll([_year("FY1", 100.0, 30.0, 20.0, 1.0, 1.0), _year("FY2", 120.0, 35.0, 20.0, 10.0, 4.0)])
    assert len(rows) == 1
    r = rows[0]
    assert r.fiscal_year == "FY2"
    assert r.actual_change == pytest.approx(15.0)
    assert r.rule_change == pytest.approx(6.0)
    assert r.residual == pytest.approx(9.0)


def test_backcast_on_the_fixture_shows_the_rule_misses_recent_years():
    rows = {r.fiscal_year: r for r in backcast_other_assets_roll(load_historical_statements(FINANCIALS))}
    assert rows["FY2022-23"].residual == pytest.approx(21145.0, abs=1.0)
    assert rows["FY2023-24"].residual == pytest.approx(23234.0, abs=1.0)
    # every one of the last five years grew faster than the rule allows
    recent = ["FY2019-20", "FY2020-21", "FY2021-22", "FY2022-23", "FY2023-24"]
    assert all(rows[fy].residual > 0 for fy in recent)


def test_cli_prints_the_backcast(capsys):
    assert statements.main(["--ticker", "GULFOILLUB", "--backcast-other-assets"]) == 0
    out = capsys.readouterr().out.split("other-assets roll back-cast", 1)[1]
    assert "FY2023-24" in out
    assert "23,234" in out
