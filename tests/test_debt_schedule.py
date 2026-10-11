"""Day 4 tests: debt schedule — mandatory amortization, revolver, cash sweep,
interest on average debt behind an explicit circularity toggle. Reconciled
against the real committed fixture, synthetic edge cases, and the CLI end
to end."""

from pathlib import Path

import pytest

from model import debt
from model.debt_schedule import (
    DEFAULT_AMORTIZATION_RATE,
    HistoricalDebtYear,
    build_historical_debt_schedule,
    default_interest_rate,
    default_revolver_limit,
    forecast_debt_schedule,
)
from model.historical import load_historical_statements

ROOT = Path(__file__).resolve().parent.parent
GULFOILLUB_CSV = ROOT / "data" / "GULFOILLUB" / "financials.csv"
SEGMENT_CSV = ROOT / "data" / "GULFOILLUB" / "segment_revenue.csv"


# -- build_historical_debt_schedule ---------------------------------------------


def test_build_historical_debt_schedule_against_the_real_fixture():
    statements = load_historical_statements(GULFOILLUB_CSV)
    schedule = build_historical_debt_schedule(statements)

    assert len(schedule) == 10
    assert schedule[0].fiscal_year == "FY2014-15"
    assert schedule[0].implied_interest_rate is None

    second = schedule[1]
    assert second.fiscal_year == "FY2015-16"
    expected_rate = 1778.92 / ((21562.75 + 19471.91) / 2)
    assert second.implied_interest_rate == pytest.approx(expected_rate)


def test_build_historical_debt_schedule_is_sorted_earliest_first():
    statements = load_historical_statements(GULFOILLUB_CSV)
    schedule = build_historical_debt_schedule(statements)
    assert [s.fiscal_year for s in schedule] == sorted(s.fiscal_year for s in schedule)


# -- default_interest_rate / default_revolver_limit -----------------------------


def test_default_interest_rate_is_the_trailing_average_of_implied_rates():
    statements = load_historical_statements(GULFOILLUB_CSV)
    schedule = build_historical_debt_schedule(statements)
    rates = [h.implied_interest_rate for h in schedule if h.implied_interest_rate is not None]
    expected = sum(rates[-3:]) / 3
    assert default_interest_rate(schedule, trailing_years=3) == pytest.approx(expected)


def test_default_interest_rate_rejects_a_single_year_with_no_implied_rate():
    with pytest.raises(ValueError, match="need at least two historical years"):
        default_interest_rate([HistoricalDebtYear("FY2020-21", 100.0, 5.0, None)])


def test_default_revolver_limit_is_the_historical_peak_total_debt():
    statements = load_historical_statements(GULFOILLUB_CSV)
    schedule = build_historical_debt_schedule(statements)
    assert default_revolver_limit(schedule) == pytest.approx(max(s.total_debt for s in schedule))


# -- forecast_debt_schedule: structural / validation -----------------------------


def test_forecast_debt_schedule_rejects_empty_historical():
    with pytest.raises(ValueError, match="at least one historical debt year"):
        forecast_debt_schedule([], ["FY2024-25"], [1000.0])


def test_forecast_debt_schedule_rejects_no_forecast_years():
    historical = [HistoricalDebtYear("FY2020-21", 100.0, 5.0, None)]
    with pytest.raises(ValueError, match="at least one forecast year"):
        forecast_debt_schedule(historical, [], [])


def test_forecast_debt_schedule_rejects_mismatched_lengths():
    historical = [HistoricalDebtYear("FY2020-21", 100.0, 5.0, None)]
    with pytest.raises(ValueError, match="same length"):
        forecast_debt_schedule(historical, ["FY2024-25", "FY2025-26"], [1000.0])


# -- forecast_debt_schedule: amortization + opening balances ---------------------


def _two_year_historical() -> list[HistoricalDebtYear]:
    # Opening term debt for the forecast = 100,000; implied rate from year 2 = 10%.
    return [
        HistoricalDebtYear("FY2022-23", 100000.0, 9500.0, None),
        HistoricalDebtYear("FY2023-24", 100000.0, 10000.0, 0.10),
    ]


def test_forecast_debt_schedule_amortizes_a_flat_rate_of_the_opening_balance():
    historical = _two_year_historical()
    forecasts = forecast_debt_schedule(
        historical, ["FY2024-25", "FY2025-26"], [50000.0, 50000.0], amortization_rate=0.10, circular=False
    )
    f0, f1 = forecasts
    assert f0.opening_term_debt == pytest.approx(100000.0)
    assert f0.scheduled_amortization == pytest.approx(10000.0)
    assert f0.ending_term_debt == pytest.approx(90000.0)
    assert f1.opening_term_debt == pytest.approx(90000.0)
    assert f1.scheduled_amortization == pytest.approx(9000.0)


def test_forecast_debt_schedule_amortization_never_exceeds_the_opening_balance():
    historical = _two_year_historical()
    forecasts = forecast_debt_schedule(
        historical, ["FY2024-25"], [50000.0], amortization_rate=1.5, circular=False
    )
    assert forecasts[0].scheduled_amortization == pytest.approx(100000.0)
    assert forecasts[0].ending_term_debt == pytest.approx(0.0)


def test_forecast_debt_schedule_defaults_amortization_rate_when_not_overridden():
    historical = _two_year_historical()
    forecasts = forecast_debt_schedule(historical, ["FY2024-25"], [50000.0], circular=False)
    assert forecasts[0].scheduled_amortization == pytest.approx(100000.0 * DEFAULT_AMORTIZATION_RATE)


def test_forecast_debt_schedule_starts_the_revolver_at_zero():
    historical = _two_year_historical()
    forecasts = forecast_debt_schedule(
        historical, ["FY2024-25"], [50000.0], interest_rate=0.10, revolver_limit=20000.0, circular=False
    )
    assert forecasts[0].opening_revolver == pytest.approx(0.0)


def test_forecast_debt_schedule_accepts_a_nonzero_initial_revolver():
    """Day 5's full linkage calls this function one forecast year at a time
    (to resolve its own tax-vs-interest circularity before fixing the next
    year's opening balances) and needs to carry a drawn revolver balance
    across those separate calls -- this is what ``initial_revolver`` is for."""
    historical = _two_year_historical()
    forecasts = forecast_debt_schedule(
        historical,
        ["FY2024-25"],
        [50000.0],
        interest_rate=0.10,
        revolver_limit=20000.0,
        circular=False,
        initial_revolver=5000.0,
    )
    assert forecasts[0].opening_revolver == pytest.approx(5000.0)


# -- forecast_debt_schedule: non-circular (opening-balance) interest ------------


def test_non_circular_interest_uses_opening_balance_only():
    historical = _two_year_historical()
    forecasts = forecast_debt_schedule(
        historical,
        ["FY2024-25"],
        [50000.0],
        amortization_rate=0.10,
        interest_rate=0.10,
        circular=False,
    )
    f0 = forecasts[0]
    assert f0.interest_expense == pytest.approx(100000.0 * 0.10)
    assert f0.iterations == 1
    assert f0.converged is True


# -- forecast_debt_schedule: circular (average-balance) interest -----------------


def test_circular_interest_converges_on_the_average_balance_in_a_paydown_year():
    """When CFADS comfortably covers amortization + interest with no revolver
    activity, the converged interest expense must equal rate * average(opening,
    ending total debt) -- the definition circular mode is solving for."""
    historical = _two_year_historical()
    forecasts = forecast_debt_schedule(
        historical,
        ["FY2024-25"],
        [50000.0],
        amortization_rate=0.10,
        interest_rate=0.10,
        circular=True,
    )
    f0 = forecasts[0]
    assert f0.converged is True
    avg_balance = (f0.opening_term_debt + f0.opening_revolver + f0.ending_total_debt) / 2
    assert f0.interest_expense == pytest.approx(0.10 * avg_balance)
    # Average-balance interest is lower than opening-balance interest here,
    # since the balance is falling (amortization) and no revolver is drawn.
    assert f0.interest_expense < 100000.0 * 0.10


def test_circular_and_non_circular_interest_differ_in_a_paydown_year():
    historical = _two_year_historical()
    circular = forecast_debt_schedule(
        historical, ["FY2024-25"], [50000.0], amortization_rate=0.10, interest_rate=0.10, circular=True
    )[0]
    non_circular = forecast_debt_schedule(
        historical, ["FY2024-25"], [50000.0], amortization_rate=0.10, interest_rate=0.10, circular=False
    )[0]
    assert circular.interest_expense != pytest.approx(non_circular.interest_expense)


# -- forecast_debt_schedule: revolver draw / cash sweep / unmet gap --------------


def test_revolver_draws_when_cfads_is_short_of_amortization_and_interest():
    historical = _two_year_historical()
    forecasts = forecast_debt_schedule(
        historical,
        ["FY2024-25"],
        [5000.0],  # far short of ~20,000 amortization + interest
        amortization_rate=0.10,
        interest_rate=0.10,
        revolver_limit=50000.0,
        circular=False,
    )
    f0 = forecasts[0]
    assert f0.revolver_draw > 0
    assert f0.ending_revolver == pytest.approx(f0.revolver_draw)
    assert f0.unmet_financing_gap == pytest.approx(0.0)


def test_revolver_repays_and_sweeps_excess_cash_when_cfads_is_ample():
    historical = _two_year_historical()
    forecasts = forecast_debt_schedule(
        historical,
        ["FY2024-25", "FY2025-26"],
        [5000.0, 200000.0],  # year 1 draws, year 2 has ample cash to sweep it back
        amortization_rate=0.10,
        interest_rate=0.10,
        revolver_limit=50000.0,
        circular=False,
    )
    f0, f1 = forecasts
    assert f0.revolver_draw > 0
    assert f1.opening_revolver == pytest.approx(f0.ending_revolver)
    assert f1.revolver_repayment == pytest.approx(f1.opening_revolver)
    assert f1.ending_revolver == pytest.approx(0.0)
    assert f1.cash_after_debt_service > 0


def test_unmet_financing_gap_is_reported_when_the_revolver_limit_is_too_small():
    historical = _two_year_historical()
    forecasts = forecast_debt_schedule(
        historical,
        ["FY2024-25"],
        [0.0],
        amortization_rate=0.10,
        interest_rate=0.10,
        revolver_limit=1000.0,  # far smaller than the ~20,000 shortfall
        circular=False,
    )
    f0 = forecasts[0]
    assert f0.revolver_draw == pytest.approx(1000.0)
    assert f0.ending_revolver == pytest.approx(1000.0)
    assert f0.unmet_financing_gap > 0
    assert f0.cash_after_debt_service == pytest.approx(-f0.unmet_financing_gap)


# -- forecast_debt_schedule: chains onto Day 2/3 for real -----------------------


def test_forecast_debt_schedule_chains_onto_real_fixtures_with_no_financing_gap():
    """The real integration point: Day 3's EBITDA/capex/working-capital
    forecast feeds this module's CFADS proxy, and on this fixture's actual
    numbers CFADS comfortably covers debt service every year."""
    statements = load_historical_statements(GULFOILLUB_CSV)
    historical_debt = build_historical_debt_schedule(statements)

    exit_code = debt.run(
        "GULFOILLUB",
        GULFOILLUB_CSV,
        SEGMENT_CSV,
        forecast_years=3,
        amortization_rate=None,
        revolver_limit=None,
        interest_rate=None,
        circular=True,
        trailing_years=3,
    )
    assert exit_code == 0
    assert len(historical_debt) == 10


# -- CLI --------------------------------------------------------------------


def test_debt_cli_run_against_the_real_fixtures(capsys):
    exit_code = debt.run(
        "GULFOILLUB",
        GULFOILLUB_CSV,
        SEGMENT_CSV,
        forecast_years=3,
        amortization_rate=None,
        revolver_limit=None,
        interest_rate=None,
        circular=True,
        trailing_years=3,
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "GULFOILLUB: 10 fiscal years of historical debt" in out
    assert "FY2026-27" in out
    assert "average-balance, iterative" in out


def test_debt_cli_non_circular_mode_is_labeled_in_the_output(capsys):
    exit_code = debt.run(
        "GULFOILLUB",
        GULFOILLUB_CSV,
        SEGMENT_CSV,
        forecast_years=2,
        amortization_rate=None,
        revolver_limit=None,
        interest_rate=None,
        circular=False,
        trailing_years=3,
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "opening-balance, single-pass" in out


def test_debt_cli_rejects_zero_forecast_years(capsys):
    exit_code = debt.run(
        "GULFOILLUB",
        GULFOILLUB_CSV,
        SEGMENT_CSV,
        forecast_years=0,
        amortization_rate=None,
        revolver_limit=None,
        interest_rate=None,
        circular=True,
        trailing_years=3,
    )
    assert exit_code == 1
    assert "nothing to project" in capsys.readouterr().err


def test_debt_cli_reports_a_missing_segment_file_cleanly(tmp_path, capsys):
    exit_code = debt.run(
        "GULFOILLUB",
        GULFOILLUB_CSV,
        tmp_path / "missing.csv",
        forecast_years=3,
        amortization_rate=None,
        revolver_limit=None,
        interest_rate=None,
        circular=True,
        trailing_years=3,
    )
    assert exit_code == 1
    assert "no segment revenue data at" in capsys.readouterr().err


def test_debt_cli_reports_a_missing_financials_file_cleanly(tmp_path, capsys):
    exit_code = debt.run(
        "NOPE",
        tmp_path / "missing.csv",
        SEGMENT_CSV,
        forecast_years=3,
        amortization_rate=None,
        revolver_limit=None,
        interest_rate=None,
        circular=True,
        trailing_years=3,
    )
    assert exit_code == 1
    assert "no financials data at" in capsys.readouterr().err


def test_debt_cli_accepts_overrides(capsys):
    exit_code = debt.run(
        "GULFOILLUB",
        GULFOILLUB_CSV,
        SEGMENT_CSV,
        forecast_years=2,
        amortization_rate=0.05,
        revolver_limit=1000.0,
        interest_rate=0.065,
        circular=True,
        trailing_years=3,
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "amort 5.00%/yr" in out
    assert "revolver limit 1,000.00" in out
    assert "interest 6.50%" in out


def test_main_cli_end_to_end_against_the_real_fixtures(capsys):
    exit_code = debt.main(["--ticker", "GULFOILLUB"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "GULFOILLUB: 10 fiscal years of historical debt" in out


def test_main_cli_accepts_no_circular_flag(capsys):
    exit_code = debt.main(["--ticker", "GULFOILLUB", "--no-circular", "--forecast-years", "2"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "opening-balance, single-pass" in out
