"""Day 5 tests: full three-statement linkage and the balance-check
assertion. Checked against the real committed fixture, a synthetic broken
linkage (to prove the assertion actually fails loudly), and the CLI end to
end."""

import dataclasses
import json
from pathlib import Path

import pytest

from model import statements
from model.historical import LAKH_TO_RUPEES, load_historical_statements
from model.linkage import (
    DEFAULT_DIVIDEND_PAYOUT,
    HistoricalLinkageYear,
    assert_balance_sheet_balances,
    build_historical_linkage,
    default_tax_rate,
    forecast_full_linkage,
    forecast_linkage_from_cost_forecasts,
    to_fundamentals_contract,
)
from model.revenue_driver import forecast_revenue, load_segment_revenue
from model.schedules import build_schedule, forecast_schedule

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


# -- forecast_full_linkage / forecast_linkage_from_cost_forecasts: tax_rate
# and dividend_payout override bounds (P59). P59's own evidence:
# --dividend-payout 5 drives total assets and equity negative
# (FY2025-26 -73,374.52/-100,048.64) with "balance check passed" printed
# anyway -- paying out 5x net income every year is not a real scenario.


def test_forecast_full_linkage_rejects_a_dividend_payout_above_one():
    statements_, segments = _real_inputs()
    with pytest.raises(ValueError, match=r"dividend_payout=5 is outside the allowed range"):
        forecast_full_linkage(statements_, segments, 3, dividend_payout=5)


def test_forecast_full_linkage_rejects_a_negative_dividend_payout():
    statements_, segments = _real_inputs()
    with pytest.raises(ValueError, match=r"dividend_payout=-0\.1 is outside the allowed range"):
        forecast_full_linkage(statements_, segments, 3, dividend_payout=-0.1)


def test_forecast_full_linkage_rejects_a_tax_rate_outside_zero_one():
    statements_, segments = _real_inputs()
    with pytest.raises(ValueError, match=r"tax_rate=1\.5 is outside the allowed range"):
        forecast_full_linkage(statements_, segments, 3, tax_rate=1.5)


# -- forecast_linkage_from_cost_forecasts: Day 8 pulled this loop out of
# forecast_full_linkage so model.revolver_scenario can drive it with a
# per-year-different cost forecast; these check the extraction changed
# nothing about forecast_full_linkage's own real-fixture behavior. --------------


def test_forecast_linkage_from_cost_forecasts_matches_forecast_full_linkage():
    statements_, segments = _real_inputs()
    schedule = build_schedule(statements_)
    revenue_forecasts = forecast_revenue(segments, 3)
    cost_forecasts = forecast_schedule(schedule, revenue_forecasts)

    direct = forecast_full_linkage(statements_, segments, 3)
    via_cost_forecasts = forecast_linkage_from_cost_forecasts(statements_, cost_forecasts)

    assert [f.revenue for f in via_cost_forecasts] == [f.revenue for f in direct]
    assert [f.ending_total_debt for f in via_cost_forecasts] == [f.ending_total_debt for f in direct]
    assert [f.balance_check_passed for f in via_cost_forecasts] == [f.balance_check_passed for f in direct]


def test_forecast_linkage_from_cost_forecasts_rejects_empty_cost_forecasts():
    statements_, _ = _real_inputs()
    with pytest.raises(ValueError, match="at least one forecast year"):
        forecast_linkage_from_cost_forecasts(statements_, [])


def test_forecast_linkage_from_cost_forecasts_rejects_empty_statements():
    _, segments = _real_inputs()
    schedule = build_schedule(load_historical_statements(GULFOILLUB_CSV))
    cost_forecasts = forecast_schedule(schedule, forecast_revenue(segments, 1))
    with pytest.raises(ValueError, match="at least one historical statement"):
        forecast_linkage_from_cost_forecasts([], cost_forecasts)


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


# -- per-share metrics (P30): shares outstanding held flat, EPS/DPS/BVPS ------


def test_forecast_shares_outstanding_is_held_flat_at_the_last_historical_value():
    statements_, segments = _real_inputs()
    forecasts = forecast_full_linkage(statements_, segments, 3)
    last_historical_shares = sorted(statements_, key=lambda s: s.fiscal_year)[-1].shares_outstanding
    assert last_historical_shares == pytest.approx(49168433)
    for f in forecasts:
        assert f.shares_outstanding == pytest.approx(last_historical_shares)


def test_forecast_eps_converts_net_income_from_lakh_to_rupees_per_share():
    statements_, segments = _real_inputs()
    forecasts = forecast_full_linkage(statements_, segments, 3)
    for f in forecasts:
        assert f.eps == pytest.approx(f.net_income * LAKH_TO_RUPEES / f.shares_outstanding)


def test_forecast_dividend_per_share_is_zero_with_the_default_zero_payout():
    statements_, segments = _real_inputs()
    forecasts = forecast_full_linkage(statements_, segments, 1)
    assert forecasts[0].dividends == pytest.approx(0.0)
    assert forecasts[0].dividend_per_share == pytest.approx(0.0)


def test_forecast_dividend_per_share_tracks_a_nonzero_payout_override():
    statements_, segments = _real_inputs()
    forecasts = forecast_full_linkage(statements_, segments, 1, dividend_payout=0.5)
    f = forecasts[0]
    assert f.dividends > 0.0
    assert f.dividend_per_share == pytest.approx(f.dividends * LAKH_TO_RUPEES / f.shares_outstanding)


def test_forecast_book_value_per_share_tracks_ending_equity_and_other_liabilities():
    statements_, segments = _real_inputs()
    forecasts = forecast_full_linkage(statements_, segments, 3)
    for f in forecasts:
        assert f.book_value_per_share == pytest.approx(
            f.equity_and_other_liabilities * LAKH_TO_RUPEES / f.shares_outstanding
        )


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


# -- to_fundamentals_contract (v0.8) -----------------------------------------


def test_to_fundamentals_contract_matches_the_committed_shape_on_the_real_fixture():
    """The exact block shape NEXT_STEPS.md's v0.8 section committed to."""
    statements_, segments = _real_inputs()
    forecasts = forecast_full_linkage(statements_, segments, 3)

    contract = to_fundamentals_contract(statements_, forecasts)

    assert set(contract) == {"fundamentals"}
    fundamentals = contract["fundamentals"]
    assert set(fundamentals) == {
        "fy3_revenue_cagr",
        "fy3_ebit_margin",
        "net_debt_ebitda_fy3",
        "balance_check",
        "base_fiscal_year",
        "fy3_fiscal_year",
    }
    assert fundamentals["balance_check"] == "passed"
    fy3 = forecasts[2]
    base_revenue = statements_[-1].income.revenue
    assert fundamentals["fy3_revenue_cagr"] == pytest.approx((fy3.revenue / base_revenue) ** (1 / 3) - 1)
    assert fundamentals["fy3_ebit_margin"] == pytest.approx(fy3.ebit / fy3.revenue)
    assert fundamentals["net_debt_ebitda_fy3"] == pytest.approx(
        (fy3.ending_total_debt - fy3.cash) / fy3.ebitda
    )


def test_to_fundamentals_contract_names_its_base_and_fy3_years():
    """D48: the fy3 figures are a forecast; the contract says which years it spans."""
    statements_, segments = _real_inputs()
    forecasts = forecast_full_linkage(statements_, segments, 3)

    fundamentals = to_fundamentals_contract(statements_, forecasts)["fundamentals"]

    assert fundamentals["base_fiscal_year"] == "FY2023-24"
    assert fundamentals["fy3_fiscal_year"] == "FY2026-27"
    assert fundamentals["base_fiscal_year"] == statements_[-1].fiscal_year
    assert fundamentals["fy3_fiscal_year"] == forecasts[2].fiscal_year


def test_to_fundamentals_contract_rejects_fewer_than_three_forecast_years():
    statements_, segments = _real_inputs()
    forecasts = forecast_full_linkage(statements_, segments, 2)

    with pytest.raises(ValueError, match="at least 3 forecast years"):
        to_fundamentals_contract(statements_, forecasts)


def test_to_fundamentals_contract_rejects_empty_statements():
    statements_, segments = _real_inputs()
    forecasts = forecast_full_linkage(statements_, segments, 3)

    with pytest.raises(ValueError, match="at least one historical statement"):
        to_fundamentals_contract([], forecasts)


def test_to_fundamentals_contract_reports_a_failed_balance_check_without_raising():
    """Mirrors test_assert_balance_sheet_balances_raises_loudly_on_a_broken_year's
    synthetic break, but the contract function reports the honest result
    instead of asserting -- the CLI's own balance-check gate (run before it
    ever calls this function) is what actually stops a broken linkage from
    publishing a contract."""
    statements_, segments = _real_inputs()
    forecasts = forecast_full_linkage(statements_, segments, 3)
    broken_year = dataclasses.replace(forecasts[2], total_assets=forecasts[2].total_assets + 1000.0)
    broken = [forecasts[0], forecasts[1], broken_year]

    contract = to_fundamentals_contract(statements_, broken)

    assert contract["fundamentals"]["balance_check"] == "failed"


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


def test_statements_cli_prints_the_sebi_disclaimer(capsys):
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
    assert (
        "Educational research on historical data. Not investment advice. "
        "Not a SEBI-registered research analyst." in out
    )


def test_statements_cli_prints_per_share_metrics(capsys):
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
    assert "EPS" in out
    assert "BVPS" in out
    assert "held flat at the last historical value" in out


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


def test_statements_cli_writes_fundamentals_contract(tmp_path, capsys):
    """v0.8 integration: the CLI writes the fundamentals block as a JSON
    file, never a Python import -- the same contract shape
    to_fundamentals_contract tests above assert directly."""
    contract_path = tmp_path / "contract.json"
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
        contract_path=contract_path,
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert f"wrote fundamentals contract to {contract_path}" in out

    contract = json.loads(contract_path.read_text())
    assert set(contract["fundamentals"]) == {
        "fy3_revenue_cagr",
        "fy3_ebit_margin",
        "net_debt_ebitda_fy3",
        "balance_check",
        "base_fiscal_year",
        "fy3_fiscal_year",
    }
    assert contract["fundamentals"]["balance_check"] == "passed"


def test_main_cli_writes_contract_end_to_end(tmp_path, capsys):
    contract_path = tmp_path / "fundamentals.json"
    exit_code = statements.main(["--ticker", "GULFOILLUB", "--contract", str(contract_path)])
    assert exit_code == 0
    assert contract_path.exists()
    assert json.loads(contract_path.read_text())["fundamentals"]["balance_check"] == "passed"


def test_main_cli_rejects_contract_with_too_few_forecast_years(capsys):
    with pytest.raises(SystemExit):
        statements.main(["--ticker", "GULFOILLUB", "--forecast-years", "2", "--contract", "out.json"])
    assert "--forecast-years >= 3" in capsys.readouterr().err
