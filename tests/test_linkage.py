"""Day 5 tests: full three-statement linkage and the balance-check
assertion. Checked against the real committed fixture, a synthetic broken
linkage (to prove the assertion actually fails loudly), and the CLI end to
end."""

import dataclasses
from pathlib import Path

import pytest

from model import statements
from model.historical import load_historical_statements
from model.linkage import (
    DEFAULT_DIVIDEND_PAYOUT,
    HistoricalLinkageYear,
    assert_balance_sheet_balances,
    build_historical_linkage,
    default_tax_rate,
    forecast_full_linkage,
)
from model.revenue_driver import load_segment_revenue

ROOT = Path(__file__).resolve().parent.parent
GULFOILLUB_CSV = ROOT / "data" / "GULFOILLUB" / "financials.csv"
SEGMENT_CSV = ROOT / "data" / "GULFOILLUB" / "segment_revenue.csv"


def _real_inputs():
    statements_ = load_historical_statements(GULFOILLUB_CSV)
    segments = load_segment_revenue(GULFOILLUB_CSV, SEGMENT_CSV)
    return statements_, segments


# -- build_historical_linkage --------------------------------------------------


def test_build_historical_linkage_decomposes_the_real_fixture():
    statements_, _ = _real_inputs()
    linkage = build_historical_linkage(statements_)

    assert len(linkage) == 10
    assert [h.fiscal_year for h in linkage] == sorted(h.fiscal_year for h in linkage)

    last = linkage[-1]
    assert last.fiscal_year == "FY2023-24"
    # Hand-computed from the real fixture row: total_assets=230449.91,
    # cash=70223.75, nwc=47469.15, total_debt=32931.01.
    assert last.other_assets == pytest.approx(230449.91 - 70223.75 - 47469.15)
    assert last.equity_and_other_liabilities == pytest.approx(230449.91 - 32931.01)
    assert last.total_assets == pytest.approx(last.cash + last.net_working_capital + last.other_assets)
    assert last.total_assets == pytest.approx(last.total_debt + last.equity_and_other_liabilities)


def test_historical_linkage_pretax_income_and_tax_rate_are_hand_checked():
    statements_, _ = _real_inputs()
    linkage = build_historical_linkage(statements_)
    last = linkage[-1]
    # FY2023-24: ebit=43906.45, interest_expense=2560.94, tax_expense=10535.66.
    assert last.pretax_income == pytest.approx(43906.45 - 2560.94)
    assert last.effective_tax_rate == pytest.approx(10535.66 / (43906.45 - 2560.94))


# -- default_tax_rate -----------------------------------------------------------


def test_default_tax_rate_is_the_trailing_average_of_implied_rates():
    statements_, _ = _real_inputs()
    linkage = build_historical_linkage(statements_)
    rates = [h.effective_tax_rate for h in linkage if h.effective_tax_rate is not None]
    expected = sum(rates[-3:]) / 3
    assert default_tax_rate(linkage, trailing_years=3) == pytest.approx(expected)


def test_default_tax_rate_rejects_no_year_with_positive_pretax_income():
    broken = [
        HistoricalLinkageYear(
            "FY2020-21", 1.0, 1.0, 1.0, 1.0, 1.0, 1.0,
            pretax_income=-5.0, tax_expense=0.0, effective_tax_rate=None,
        )
    ]
    with pytest.raises(ValueError, match="positive pretax income"):
        default_tax_rate(broken)


# -- forecast_full_linkage: validation ------------------------------------------


def test_forecast_full_linkage_rejects_empty_statements():
    with pytest.raises(ValueError, match="at least one historical statement"):
        forecast_full_linkage([], [], 3)


def test_forecast_full_linkage_rejects_zero_forecast_years():
    statements_, segments = _real_inputs()
    with pytest.raises(ValueError, match="forecast_years must be >= 1"):
        forecast_full_linkage(statements_, segments, 0)


# -- forecast_full_linkage: the real integration --------------------------------


def test_balance_sheet_balances_for_every_forecast_year_on_the_real_fixture():
    """The Day 5 'done when' gate: on the real company's own numbers, the
    independently-computed asset side and liability+equity side must agree
    for every forecast year, to the balance-check tolerance."""
    statements_, segments = _real_inputs()
    forecasts = forecast_full_linkage(statements_, segments, 3)

    assert len(forecasts) == 3
    assert_balance_sheet_balances(forecasts)  # must not raise
    for f in forecasts:
        assert f.balance_check_passed is True
        assert abs(f.balance_difference) < 0.01


def test_full_linkage_converges_on_the_real_fixture():
    statements_, segments = _real_inputs()
    forecasts = forecast_full_linkage(statements_, segments, 3)
    for f in forecasts:
        assert f.debt_converged is True
        assert f.tax_converged is True


def test_full_linkage_retains_all_earnings_by_default_with_no_dividend_data():
    statements_, segments = _real_inputs()
    forecasts = forecast_full_linkage(statements_, segments, 1)
    assert DEFAULT_DIVIDEND_PAYOUT == 0.0
    assert forecasts[0].dividends == pytest.approx(0.0)


def test_full_linkage_dividend_payout_override_reduces_equity_growth():
    statements_, segments = _real_inputs()
    no_dividend = forecast_full_linkage(statements_, segments, 1, dividend_payout=0.0)[0]
    with_dividend = forecast_full_linkage(statements_, segments, 1, dividend_payout=0.5)[0]
    assert with_dividend.dividends == pytest.approx(0.5 * with_dividend.net_income)
    assert with_dividend.equity_and_other_liabilities < no_dividend.equity_and_other_liabilities
    # Both must still balance -- the dividend is subtracted from cash (CFF)
    # and from equity identically, so the identity holds either way.
    assert abs(with_dividend.balance_difference) < 0.01


def test_full_linkage_tax_rate_override_changes_net_income_but_still_balances():
    statements_, segments = _real_inputs()
    low_tax = forecast_full_linkage(statements_, segments, 1, tax_rate=0.10)[0]
    high_tax = forecast_full_linkage(statements_, segments, 1, tax_rate=0.40)[0]
    assert low_tax.net_income > high_tax.net_income
    assert abs(low_tax.balance_difference) < 0.01
    assert abs(high_tax.balance_difference) < 0.01


def test_full_linkage_carries_debt_balance_forward_across_forecast_years():
    statements_, segments = _real_inputs()
    forecasts = forecast_full_linkage(statements_, segments, 3)
    # Ending total debt should decline year over year on this fixture --
    # CFADS comfortably covers debt service (Day 4's own finding), so only
    # mandatory amortization shrinks the balance, confirmed hand-checkable
    # against model/debt.py's own Day 4 output for the same fixture.
    debts = [f.ending_total_debt for f in forecasts]
    assert debts[0] > debts[1] > debts[2]


def test_full_linkage_no_circular_mode_also_balances():
    statements_, segments = _real_inputs()
    forecasts = forecast_full_linkage(statements_, segments, 2, circular=False)
    assert_balance_sheet_balances(forecasts)
    for f in forecasts:
        assert f.debt_converged is True  # non-circular mode is always "converged" (one pass)


# -- assert_balance_sheet_balances: proving it fails loudly ---------------------


def test_assert_balance_sheet_balances_raises_loudly_on_a_broken_year():
    """A deliberately broken synthetic year (one schedule's output silently
    dropped from one side) must be caught, named, and raised -- this is the
    actual test NEXT_STEPS.md Day 5 asks for."""
    statements_, segments = _real_inputs()
    forecasts = forecast_full_linkage(statements_, segments, 2)
    broken_year = dataclasses.replace(forecasts[1], total_assets=forecasts[1].total_assets + 1000.0)
    broken = [forecasts[0], broken_year]

    with pytest.raises(AssertionError, match=f"{broken_year.fiscal_year}.*diff"):
        assert_balance_sheet_balances(broken, tolerance=0.01)


def test_assert_balance_sheet_balances_passes_silently_when_everything_is_wired():
    statements_, segments = _real_inputs()
    forecasts = forecast_full_linkage(statements_, segments, 3)
    assert assert_balance_sheet_balances(forecasts) is None


# -- CLI --------------------------------------------------------------------


def test_statements_cli_run_against_the_real_fixtures(capsys):
    exit_code = statements.run(
        "GULFOILLUB",
        GULFOILLUB_CSV,
        SEGMENT_CSV,
        forecast_years=3,
        tax_rate=None,
        dividend_payout=None,
        amortization_rate=None,
        revolver_limit=None,
        interest_rate=None,
        circular=True,
        trailing_years=3,
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "balance check passed for every forecast year" in out
    assert "FY2026-27" in out


def test_statements_cli_no_circular_mode(capsys):
    exit_code = statements.run(
        "GULFOILLUB",
        GULFOILLUB_CSV,
        SEGMENT_CSV,
        forecast_years=2,
        tax_rate=None,
        dividend_payout=None,
        amortization_rate=None,
        revolver_limit=None,
        interest_rate=None,
        circular=False,
        trailing_years=3,
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "opening-balance, single-pass" in out
    assert "balance check passed for every forecast year" in out


def test_statements_cli_rejects_zero_forecast_years(capsys):
    exit_code = statements.run(
        "GULFOILLUB",
        GULFOILLUB_CSV,
        SEGMENT_CSV,
        forecast_years=0,
        tax_rate=None,
        dividend_payout=None,
        amortization_rate=None,
        revolver_limit=None,
        interest_rate=None,
        circular=True,
        trailing_years=3,
    )
    assert exit_code == 1
    assert "nothing to project" in capsys.readouterr().err


def test_statements_cli_reports_a_missing_segment_file_cleanly(tmp_path, capsys):
    exit_code = statements.run(
        "GULFOILLUB",
        GULFOILLUB_CSV,
        tmp_path / "missing.csv",
        forecast_years=3,
        tax_rate=None,
        dividend_payout=None,
        amortization_rate=None,
        revolver_limit=None,
        interest_rate=None,
        circular=True,
        trailing_years=3,
    )
    assert exit_code == 1
    assert "no segment revenue data at" in capsys.readouterr().err


def test_statements_cli_reports_a_missing_financials_file_cleanly(tmp_path, capsys):
    exit_code = statements.run(
        "NOPE",
        tmp_path / "missing.csv",
        SEGMENT_CSV,
        forecast_years=3,
        tax_rate=None,
        dividend_payout=None,
        amortization_rate=None,
        revolver_limit=None,
        interest_rate=None,
        circular=True,
        trailing_years=3,
    )
    assert exit_code == 1
    assert "no financials data at" in capsys.readouterr().err


def test_statements_cli_accepts_overrides(capsys):
    exit_code = statements.run(
        "GULFOILLUB",
        GULFOILLUB_CSV,
        SEGMENT_CSV,
        forecast_years=2,
        tax_rate=0.25,
        dividend_payout=0.3,
        amortization_rate=0.05,
        revolver_limit=50000.0,
        interest_rate=0.07,
        circular=True,
        trailing_years=3,
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "30% dividend payout" in out


def test_main_cli_end_to_end_against_the_real_fixtures(capsys):
    exit_code = statements.main(["--ticker", "GULFOILLUB"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "balance check passed for every forecast year" in out
