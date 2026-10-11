"""Day 3 tests: cost structure, D&A, capex and working-capital schedules,
reconciled against the real committed fixtures, and the CLI end to end."""

from pathlib import Path

import pytest

from model import costs
from model.historical import load_historical_statements
from model.revenue_driver import ForecastYear, forecast_revenue, load_segment_revenue
from model.schedules import (
    DEFAULT_TRAILING_YEARS,
    build_schedule,
    forecast_schedule,
    trailing_average,
)

ROOT = Path(__file__).resolve().parent.parent
GULFOILLUB_CSV = ROOT / "data" / "GULFOILLUB" / "financials.csv"
SEGMENT_CSV = ROOT / "data" / "GULFOILLUB" / "segment_revenue.csv"


# -- build_schedule ------------------------------------------------------------


def test_build_schedule_against_the_real_fixture_first_year():
    statements = load_historical_statements(GULFOILLUB_CSV)
    schedule = build_schedule(statements)

    assert len(schedule) == 10
    first = schedule[0]
    assert first.fiscal_year == "FY2014-15"
    assert first.ebitda_margin == pytest.approx(13861.35 / 96748.17)
    assert first.da_margin == pytest.approx(482.12 / 96748.17)
    assert first.capex_margin == pytest.approx(3545.52 / 96748.17)
    assert first.nwc_margin == pytest.approx(14797.06 / 96748.17)


def test_build_schedule_is_sorted_earliest_first():
    statements = load_historical_statements(GULFOILLUB_CSV)
    schedule = build_schedule(statements)
    assert [s.fiscal_year for s in schedule] == sorted(s.fiscal_year for s in schedule)
    assert schedule[-1].fiscal_year == "FY2023-24"


# -- trailing_average -----------------------------------------------------------


def test_trailing_average_uses_the_last_n_values():
    assert trailing_average([1.0, 2.0, 3.0, 4.0], n=2) == pytest.approx(3.5)


def test_trailing_average_uses_all_available_values_if_fewer_than_n():
    assert trailing_average([1.0, 2.0], n=5) == pytest.approx(1.5)


def test_trailing_average_rejects_n_below_one():
    with pytest.raises(ValueError, match="n must be >= 1"):
        trailing_average([1.0], n=0)


def test_trailing_average_rejects_empty_values():
    with pytest.raises(ValueError, match="at least one historical value"):
        trailing_average([], n=3)


# -- forecast_schedule ----------------------------------------------------------


def test_forecast_schedule_default_margins_are_the_trailing_average():
    statements = load_historical_statements(GULFOILLUB_CSV)
    schedule = build_schedule(statements)
    forecasts = forecast_schedule(schedule, [ForecastYear("FY2024-25", 300000.0, 20000.0)])

    expected_ebitda_margin = trailing_average([s.ebitda_margin for s in schedule], DEFAULT_TRAILING_YEARS)
    f = forecasts[0]
    assert f.fiscal_year == "FY2024-25"
    assert f.revenue == pytest.approx(320000.0)
    assert f.ebitda_margin_used == pytest.approx(expected_ebitda_margin)
    assert f.ebitda == pytest.approx(320000.0 * expected_ebitda_margin)
    assert f.ebit == pytest.approx(f.ebitda - f.depreciation_amortization)


def test_forecast_schedule_accepts_explicit_margin_overrides():
    statements = load_historical_statements(GULFOILLUB_CSV)
    schedule = build_schedule(statements)
    forecasts = forecast_schedule(
        schedule,
        [ForecastYear("FY2024-25", 300000.0, 20000.0)],
        ebitda_margin=0.15,
        da_margin=0.02,
        capex_margin=0.01,
        nwc_margin=0.20,
    )
    f = forecasts[0]
    assert f.ebitda_margin_used == pytest.approx(0.15)
    assert f.ebitda == pytest.approx(320000.0 * 0.15)
    assert f.da_margin_used == pytest.approx(0.02)
    assert f.depreciation_amortization == pytest.approx(320000.0 * 0.02)
    assert f.capex_margin_used == pytest.approx(0.01)
    assert f.capex == pytest.approx(320000.0 * 0.01)
    assert f.nwc_margin_used == pytest.approx(0.20)
    assert f.net_working_capital == pytest.approx(320000.0 * 0.20)


def test_forecast_schedule_delta_nwc_chains_from_the_last_historical_year():
    statements = load_historical_statements(GULFOILLUB_CSV)
    schedule = build_schedule(statements)
    last_nwc = schedule[-1].net_working_capital

    forecasts = forecast_schedule(
        schedule,
        [ForecastYear("FY2024-25", 300000.0, 20000.0), ForecastYear("FY2025-26", 330000.0, 23000.0)],
        nwc_margin=0.20,
    )
    assert forecasts[0].delta_nwc == pytest.approx(320000.0 * 0.20 - last_nwc)
    assert forecasts[1].delta_nwc == pytest.approx(353000.0 * 0.20 - 320000.0 * 0.20)


def test_forecast_schedule_rejects_no_forecast_years():
    statements = load_historical_statements(GULFOILLUB_CSV)
    schedule = build_schedule(statements)
    with pytest.raises(ValueError, match="at least one forecast year"):
        forecast_schedule(schedule, [])


def test_forecast_schedule_rejects_empty_historical():
    with pytest.raises(ValueError, match="at least one historical schedule year"):
        forecast_schedule([], [ForecastYear("FY2024-25", 300000.0, 20000.0)])


def test_forecast_schedule_chains_onto_day_two_revenue_forecast():
    """The real integration point: Day 2's own forecast_revenue output feeds
    straight into Day 3's forecast_schedule with no re-derivation of revenue."""
    statements = load_historical_statements(GULFOILLUB_CSV)
    schedule = build_schedule(statements)
    segments = load_segment_revenue(GULFOILLUB_CSV, SEGMENT_CSV)
    revenue_forecasts = forecast_revenue(segments, 3)

    forecasts = forecast_schedule(schedule, revenue_forecasts)

    assert [f.fiscal_year for f in forecasts] == [r.fiscal_year for r in revenue_forecasts]
    for f, r in zip(forecasts, revenue_forecasts):
        assert f.revenue == pytest.approx(r.total_revenue)


# -- CLI --------------------------------------------------------------------


def test_costs_cli_run_against_the_real_fixtures(capsys):
    exit_code = costs.run(
        "GULFOILLUB",
        GULFOILLUB_CSV,
        SEGMENT_CSV,
        forecast_years=3,
        ebitda_margin=None,
        da_margin=None,
        capex_margin=None,
        nwc_margin=None,
        trailing_years=DEFAULT_TRAILING_YEARS,
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "GULFOILLUB: 10 fiscal years" in out
    assert "forecast (3y" in out
    assert "FY2026-27" in out


def test_costs_cli_skips_the_forecast_section_when_forecast_years_is_zero(capsys):
    exit_code = costs.run(
        "GULFOILLUB",
        GULFOILLUB_CSV,
        SEGMENT_CSV,
        forecast_years=0,
        ebitda_margin=None,
        da_margin=None,
        capex_margin=None,
        nwc_margin=None,
        trailing_years=DEFAULT_TRAILING_YEARS,
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "forecast" not in out


def test_costs_cli_reports_a_missing_segment_file_cleanly(tmp_path, capsys):
    exit_code = costs.run(
        "GULFOILLUB",
        GULFOILLUB_CSV,
        tmp_path / "missing.csv",
        forecast_years=3,
        ebitda_margin=None,
        da_margin=None,
        capex_margin=None,
        nwc_margin=None,
        trailing_years=DEFAULT_TRAILING_YEARS,
    )
    assert exit_code == 1
    assert "no segment revenue data at" in capsys.readouterr().err


def test_costs_cli_reports_a_missing_financials_file_cleanly(tmp_path, capsys):
    exit_code = costs.run(
        "NOPE",
        tmp_path / "missing.csv",
        SEGMENT_CSV,
        forecast_years=3,
        ebitda_margin=None,
        da_margin=None,
        capex_margin=None,
        nwc_margin=None,
        trailing_years=DEFAULT_TRAILING_YEARS,
    )
    assert exit_code == 1
    assert "no financials data at" in capsys.readouterr().err


def test_costs_cli_accepts_margin_overrides(capsys):
    exit_code = costs.run(
        "GULFOILLUB",
        GULFOILLUB_CSV,
        SEGMENT_CSV,
        forecast_years=1,
        ebitda_margin=0.15,
        da_margin=0.02,
        capex_margin=0.01,
        nwc_margin=0.18,
        trailing_years=DEFAULT_TRAILING_YEARS,
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "EBITDA @ +15.00%" in out


def test_main_cli_end_to_end_against_the_real_fixtures(capsys):
    exit_code = costs.main(["--ticker", "GULFOILLUB"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "GULFOILLUB: 10 fiscal years" in out


def test_main_cli_accepts_explicit_overrides(capsys):
    exit_code = costs.main(
        ["--ticker", "GULFOILLUB", "--forecast-years", "2", "--trailing-years", "5", "--ebitda-margin", "0.16"]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "EBITDA @ +16.00%" in out
    assert "FY2025-26" in out
