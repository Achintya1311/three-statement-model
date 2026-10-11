"""Day 7 tests: sensitivity ranking and the two-variable grid, checked
against the real committed fixture, plus the ``forecast_full_linkage``
growth/margin overrides this day's module needed added to Day 5's own
linkage function."""

from pathlib import Path

import pytest

from model import sensitivity
from model.historical import load_historical_statements
from model.linkage import ForecastLinkageYear, forecast_full_linkage
from model.revenue_driver import load_segment_revenue
from model.sensitivity import (
    LEVER_ORDER,
    NO_FLOOR,
    SHOCKS,
    net_debt_to_ebitda,
    rank_levers,
    resolve_base_assumptions,
    run_scenario,
    sensitivity_grid,
    shocked_value,
)

ROOT = Path(__file__).resolve().parent.parent
GULFOILLUB_CSV = ROOT / "data" / "GULFOILLUB" / "financials.csv"
SEGMENT_CSV = ROOT / "data" / "GULFOILLUB" / "segment_revenue.csv"


def _real_inputs():
    statements = load_historical_statements(GULFOILLUB_CSV)
    segments = load_segment_revenue(GULFOILLUB_CSV, SEGMENT_CSV)
    return statements, segments


# -- forecast_full_linkage's new growth/margin overrides (needed by this day) --


def test_forecast_full_linkage_default_matches_omitted_overrides():
    statements, segments = _real_inputs()
    with_none = forecast_full_linkage(
        statements, segments, 3, domestic_growth=None, export_growth=None,
        ebitda_margin=None, da_margin=None, capex_margin=None, nwc_margin=None,
    )
    without = forecast_full_linkage(statements, segments, 3)
    assert [f.revenue for f in with_none] == [f.revenue for f in without]
    assert [f.ebitda for f in with_none] == [f.ebitda for f in without]


def test_forecast_full_linkage_domestic_growth_override_changes_revenue():
    statements, segments = _real_inputs()
    base = forecast_full_linkage(statements, segments, 1)
    bumped = forecast_full_linkage(statements, segments, 1, domestic_growth=0.50, export_growth=0.0)
    assert bumped[0].revenue > base[0].revenue


def test_forecast_full_linkage_ebitda_margin_override_changes_ebitda():
    statements, segments = _real_inputs()
    base = forecast_full_linkage(statements, segments, 1)
    bumped = forecast_full_linkage(statements, segments, 1, ebitda_margin=0.90)
    assert bumped[0].ebitda > base[0].ebitda
    assert bumped[0].revenue == pytest.approx(base[0].revenue)


# -- net_debt_to_ebitda ---------------------------------------------------------


def _year(**overrides) -> ForecastLinkageYear:
    fields = dict(
        fiscal_year="FY2024-25", revenue=100.0, ebitda=20.0, depreciation_amortization=2.0,
        ebit=18.0, interest_expense=1.0, tax_expense=4.0, net_income=13.0, dividends=0.0,
        capex=3.0, delta_nwc=1.0, scheduled_amortization=0.0, revolver_draw=0.0,
        revolver_repayment=0.0, ending_total_debt=50.0, cash=30.0, net_working_capital=10.0,
        other_assets=40.0, total_assets=80.0, equity_and_other_liabilities=30.0,
        total_liabilities_and_equity=80.0, balance_difference=0.0, balance_check_passed=True,
        debt_converged=True, tax_converged=True,
    )
    fields.update(overrides)
    return ForecastLinkageYear(**fields)


def test_net_debt_to_ebitda_hand_computed():
    year = _year(ending_total_debt=50.0, cash=30.0, ebitda=20.0)
    assert net_debt_to_ebitda(year) == pytest.approx((50.0 - 30.0) / 20.0)


def test_net_debt_to_ebitda_none_for_non_positive_ebitda():
    assert net_debt_to_ebitda(_year(ebitda=0.0)) is None
    assert net_debt_to_ebitda(_year(ebitda=-5.0)) is None


# -- shocked_value ---------------------------------------------------------------


def test_shocked_value_floors_non_growth_levers_at_zero():
    assert shocked_value("dividend_payout", 0.0, -1) == 0.0
    assert shocked_value("amortization_rate", 0.02, -1) == 0.0  # 0.02 - 0.05 would be negative


def test_shocked_value_allows_negative_growth():
    name = "domestic_growth"
    assert name in NO_FLOOR
    assert shocked_value(name, 0.02, -1) == pytest.approx(0.02 - SHOCKS[name])


def test_shocked_value_up_direction():
    assert shocked_value("tax_rate", 0.25, +1) == pytest.approx(0.25 + SHOCKS["tax_rate"])


# -- resolve_base_assumptions ----------------------------------------------------


def test_resolve_base_assumptions_matches_prior_days_cited_figures():
    statements, segments = _real_inputs()
    base = resolve_base_assumptions(statements, segments)
    assert set(base) == set(LEVER_ORDER)
    # Day 2's README: domestic +13.93%, export +34.21% (FY2014-15 to FY2023-24).
    assert base["domestic_growth"] == pytest.approx(0.1393, abs=5e-4)
    assert base["export_growth"] == pytest.approx(0.3421, abs=5e-4)
    # Day 4's README: trailing-3yr average implied interest rate 7.38%.
    assert base["interest_rate"] == pytest.approx(0.0738, abs=5e-4)
    assert base["dividend_payout"] == 0.0
    assert base["amortization_rate"] == 0.10


# -- rank_levers ------------------------------------------------------------------


def test_rank_levers_covers_every_lever_sorted_by_impact():
    statements, segments = _real_inputs()
    rows, base_metric = rank_levers(statements, segments, 3, circular=True, trailing_years=3)
    assert base_metric is not None
    assert {r["name"] for r in rows} == set(LEVER_ORDER)
    impacts = [r["impact"] for r in rows]
    assert impacts == sorted(impacts, reverse=True)
    assert all(i >= 0.0 for i in impacts)


def test_rank_levers_dividend_payout_down_shock_is_a_no_op_at_the_floor():
    statements, segments = _real_inputs()
    rows, base_metric = rank_levers(statements, segments, 3, circular=True, trailing_years=3)
    row = next(r for r in rows if r["name"] == "dividend_payout")
    assert row["down_value"] == 0.0
    assert row["down_metric"] == pytest.approx(base_metric)


def test_rank_levers_non_circular_runs_without_error():
    statements, segments = _real_inputs()
    rows, base_metric = rank_levers(statements, segments, 3, circular=False, trailing_years=3)
    assert len(rows) == len(LEVER_ORDER)
    assert base_metric is not None


# -- sensitivity_grid --------------------------------------------------------------


def test_sensitivity_grid_shape_for_two_unfloored_levers():
    statements, segments = _real_inputs()
    rows, cols, table = sensitivity_grid(
        statements, segments, 3, "domestic_growth", "export_growth", True, 3, steps=2
    )
    assert len(rows) == 5
    assert len(cols) == 5
    assert len(table) == 5
    assert all(len(r) == 5 for r in table)


def test_sensitivity_grid_dedupes_a_floored_lever():
    statements, segments = _real_inputs()
    rows, cols, table = sensitivity_grid(
        statements, segments, 3, "dividend_payout", "domestic_growth", True, 3, steps=2
    )
    # dividend_payout defaults to 0.0; steps -2/-1/0 all floor to 0.0.
    assert rows == [0.0, pytest.approx(0.20), pytest.approx(0.40)]
    assert len(cols) == 5
    assert len(table) == 3


def test_sensitivity_grid_cell_matches_forecast_full_linkage_directly():
    statements, segments = _real_inputs()
    rows, cols, table = sensitivity_grid(
        statements, segments, 3, "ebitda_margin", "domestic_growth", True, 3, steps=1
    )
    row_var_value, col_var_value = rows[0], cols[0]
    direct = run_scenario(
        statements, segments, 3,
        {"ebitda_margin": row_var_value, "domestic_growth": col_var_value},
        True, 3,
    )
    assert table[0][0] == pytest.approx(net_debt_to_ebitda(direct[-1]))


def test_sensitivity_grid_every_cell_still_balances():
    statements, segments = _real_inputs()
    rows, cols, table = sensitivity_grid(
        statements, segments, 3, "ebitda_margin", "tax_rate", True, 3, steps=2
    )
    for rv in rows:
        for cv in cols:
            forecasts = run_scenario(
                statements, segments, 3, {"ebitda_margin": rv, "tax_rate": cv}, True, 3
            )
            assert all(f.balance_check_passed for f in forecasts)


# -- CLI ---------------------------------------------------------------------------


def test_cli_success_path(capsys):
    exit_code = sensitivity.run(
        "GULFOILLUB", GULFOILLUB_CSV, SEGMENT_CSV, forecast_years=3,
        circular=True, trailing_years=3, steps=1,
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Day 7 sensitivity ranking" in out
    assert "the two assumptions that actually move the answer" in out


def test_cli_missing_financials_file(tmp_path, capsys):
    exit_code = sensitivity.run(
        "NOPE", tmp_path / "financials.csv", SEGMENT_CSV, forecast_years=3,
        circular=True, trailing_years=3, steps=1,
    )
    assert exit_code == 1
    assert "no financials data" in capsys.readouterr().err


def test_cli_missing_segment_file(tmp_path, capsys):
    exit_code = sensitivity.run(
        "GULFOILLUB", GULFOILLUB_CSV, tmp_path / "segment_revenue.csv", forecast_years=3,
        circular=True, trailing_years=3, steps=1,
    )
    assert exit_code == 1
    assert "no segment revenue data" in capsys.readouterr().err


def test_cli_rejects_zero_forecast_years(capsys):
    exit_code = sensitivity.run(
        "GULFOILLUB", GULFOILLUB_CSV, SEGMENT_CSV, forecast_years=0,
        circular=True, trailing_years=3, steps=1,
    )
    assert exit_code == 1
    assert "--forecast-years" in capsys.readouterr().err


def test_main_rejects_non_positive_steps(capsys):
    exit_code = sensitivity.main(["--ticker", "GULFOILLUB", "--steps", "0"])
    assert exit_code == 1
    assert "--steps" in capsys.readouterr().err
