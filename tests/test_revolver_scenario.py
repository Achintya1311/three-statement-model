"""Day 8 tests: the "what happens if they draw the revolver in year two"
scenario (``model.revolver_scenario``) and its CLI (``model.revolver``),
checked against the real committed fixture.

Day 4/5's own Limitations already established that the revolver never
draws organically on this fixture (CFADS covers debt service every real
forecast year), so these tests check the thing this day actually adds:
that a deliberate single-year EBITDA-margin shock draws the revolver in
exactly the shocked year, every other year still balances, and a shock
that reverts gets swept back down by the cash the model itself generates
— not that the fixture spontaneously produces a shortfall it never has.
"""

from pathlib import Path

import pytest

from model import revolver
from model.historical import load_historical_statements
from model.linkage import assert_balance_sheet_balances, forecast_full_linkage
from model.revenue_driver import load_segment_revenue
from model.revolver_scenario import simulate_revolver_draw_scenario

ROOT = Path(__file__).resolve().parent.parent
GULFOILLUB_CSV = ROOT / "data" / "GULFOILLUB" / "financials.csv"
SEGMENT_CSV = ROOT / "data" / "GULFOILLUB" / "segment_revenue.csv"


def _real_inputs():
    statements = load_historical_statements(GULFOILLUB_CSV)
    segments = load_segment_revenue(GULFOILLUB_CSV, SEGMENT_CSV)
    return statements, segments


# -- simulate_revolver_draw_scenario -------------------------------------------


def test_year_1_is_unshocked_and_healthy():
    statements, segments = _real_inputs()
    results = simulate_revolver_draw_scenario(statements, segments, 4, shock_year=2, shock_ebitda_margin=0.05)
    assert results[0].shocked is False
    assert results[0].linkage.revolver_draw == 0.0


def test_the_shocked_year_alone_draws_the_revolver():
    statements, segments = _real_inputs()
    results = simulate_revolver_draw_scenario(statements, segments, 4, shock_year=2, shock_ebitda_margin=0.05)
    shocked_years = [r for r in results if r.shocked]
    unshocked_years = [r for r in results if not r.shocked]
    assert [r.linkage.fiscal_year for r in shocked_years] == [results[1].linkage.fiscal_year]
    assert shocked_years[0].linkage.revolver_draw > 0
    assert all(r.linkage.revolver_draw == 0.0 for r in unshocked_years)


def test_shocked_year_ebitda_margin_is_the_override_not_the_baseline():
    statements, segments = _real_inputs()
    results = simulate_revolver_draw_scenario(statements, segments, 3, shock_year=2, shock_ebitda_margin=0.05)
    shocked = results[1].linkage
    assert shocked.ebitda / shocked.revenue == pytest.approx(0.05, abs=1e-9)


def test_the_draw_is_swept_down_once_the_shock_reverts():
    statements, segments = _real_inputs()
    results = simulate_revolver_draw_scenario(statements, segments, 4, shock_year=2, shock_ebitda_margin=0.05)
    draw_year = results[1].linkage
    recovery_year = results[2].linkage
    assert draw_year.revolver_draw > 0
    assert recovery_year.revolver_repayment == pytest.approx(draw_year.revolver_draw, rel=1e-6)


def test_the_scenario_recovers_to_the_unshocked_path_once_the_revolver_is_cleared():
    statements, segments = _real_inputs()
    shocked = simulate_revolver_draw_scenario(statements, segments, 4, shock_year=2, shock_ebitda_margin=0.05)
    baseline = forecast_full_linkage(statements, segments, 4)
    assert shocked[3].linkage.ending_total_debt == pytest.approx(baseline[3].ending_total_debt, rel=1e-9)
    assert shocked[0].linkage.ending_total_debt == pytest.approx(baseline[0].ending_total_debt, rel=1e-9)


def test_persistent_shock_keeps_drawing_until_growth_outruns_it():
    statements, segments = _real_inputs()
    results = simulate_revolver_draw_scenario(
        statements, segments, 4, shock_year=2, shock_duration=3, shock_ebitda_margin=0.05
    )
    assert [r.shocked for r in results] == [False, True, True, True]
    assert results[1].linkage.revolver_draw > 0
    # growing absolute EBITDA eventually outruns the fixed-margin shock even
    # without the margin reverting — net draws taper, not accelerate
    assert results[2].linkage.revolver_draw < results[1].linkage.revolver_draw
    assert results[3].linkage.revolver_draw == 0.0


def test_shock_starting_in_year_1_has_no_pre_shock_baseline_to_resolve_from():
    statements, segments = _real_inputs()
    results = simulate_revolver_draw_scenario(statements, segments, 3, shock_year=1, shock_ebitda_margin=0.05)
    assert results[0].shocked is True
    assert results[0].linkage.revolver_draw > 0
    # years after the shock still revert to the real historical baseline margin,
    # not the shocked one, even with no pre-shock year to resolve it from
    unshocked_margin = results[1].linkage.ebitda / results[1].linkage.revenue
    assert unshocked_margin > 0.10


def test_every_year_still_balances_under_the_shock():
    statements, segments = _real_inputs()
    results = simulate_revolver_draw_scenario(statements, segments, 4, shock_year=2, shock_ebitda_margin=0.05)
    assert_balance_sheet_balances([r.linkage for r in results])  # raises if any year fails to balance


def test_rejects_a_shock_span_that_does_not_fit_the_forecast():
    statements, segments = _real_inputs()
    with pytest.raises(ValueError, match="does not fit"):
        simulate_revolver_draw_scenario(statements, segments, 3, shock_year=3, shock_duration=2, shock_ebitda_margin=0.05)


def test_rejects_a_shock_year_below_one():
    statements, segments = _real_inputs()
    with pytest.raises(ValueError, match="does not fit"):
        simulate_revolver_draw_scenario(statements, segments, 3, shock_year=0, shock_ebitda_margin=0.05)


def test_rejects_zero_forecast_years():
    statements, segments = _real_inputs()
    with pytest.raises(ValueError, match="forecast_years"):
        simulate_revolver_draw_scenario(statements, segments, 0, shock_year=1, shock_ebitda_margin=0.05)


def test_rejects_zero_shock_duration():
    statements, segments = _real_inputs()
    with pytest.raises(ValueError, match="shock_duration"):
        simulate_revolver_draw_scenario(statements, segments, 3, shock_year=1, shock_duration=0, shock_ebitda_margin=0.05)


# -- CLI (model.revolver) ------------------------------------------------------


def test_revolver_cli_run_against_the_real_fixtures(capsys):
    exit_code = revolver.run(
        "GULFOILLUB",
        GULFOILLUB_CSV,
        SEGMENT_CSV,
        forecast_years=4,
        shock_year=2,
        shock_duration=1,
        shock_ebitda_margin=0.05,
        circular=True,
        trailing_years=3,
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "balance check passed for every forecast year" in out
    assert "year 2 only" in out
    assert "True" in out  # the Shocked column has at least one True row


def test_revolver_cli_no_circular_mode(capsys):
    exit_code = revolver.run(
        "GULFOILLUB",
        GULFOILLUB_CSV,
        SEGMENT_CSV,
        forecast_years=4,
        shock_year=2,
        shock_duration=1,
        shock_ebitda_margin=0.05,
        circular=False,
        trailing_years=3,
    )
    assert exit_code == 0
    assert "opening-balance, single-pass" in capsys.readouterr().out


def test_revolver_cli_reports_an_invalid_shock_span_cleanly(capsys):
    exit_code = revolver.run(
        "GULFOILLUB",
        GULFOILLUB_CSV,
        SEGMENT_CSV,
        forecast_years=3,
        shock_year=3,
        shock_duration=2,
        shock_ebitda_margin=0.05,
        circular=True,
        trailing_years=3,
    )
    assert exit_code == 1
    assert "does not fit" in capsys.readouterr().err


def test_revolver_cli_reports_a_missing_financials_file_cleanly(tmp_path, capsys):
    exit_code = revolver.run(
        "NOPE",
        tmp_path / "missing.csv",
        SEGMENT_CSV,
        forecast_years=4,
        shock_year=2,
        shock_duration=1,
        shock_ebitda_margin=0.05,
        circular=True,
        trailing_years=3,
    )
    assert exit_code == 1
    assert "no financials data at" in capsys.readouterr().err


def test_revolver_cli_reports_a_missing_segment_file_cleanly(tmp_path, capsys):
    exit_code = revolver.run(
        "GULFOILLUB",
        GULFOILLUB_CSV,
        tmp_path / "missing.csv",
        forecast_years=4,
        shock_year=2,
        shock_duration=1,
        shock_ebitda_margin=0.05,
        circular=True,
        trailing_years=3,
    )
    assert exit_code == 1
    assert "no segment revenue data at" in capsys.readouterr().err


def test_main_cli_end_to_end_against_the_real_fixtures(capsys):
    exit_code = revolver.main(["--ticker", "GULFOILLUB"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "balance check passed for every forecast year" in out


def test_main_cli_accepts_persistent_shock_duration(capsys):
    exit_code = revolver.main(
        ["--ticker", "GULFOILLUB", "--shock-year", "2", "--shock-duration", "3", "--forecast-years", "4"]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "years 2-4 only" in out
