"""Day 2 tests: domestic/export revenue driver build, reconciled against the
real committed fixtures, and the CLI end to end."""

from pathlib import Path

import pandas as pd
import pytest

from model import revenue
from model.historical import load_historical_statements
from model.revenue_driver import (
    ForecastYear,
    SegmentRevenue,
    build_segment_revenue,
    fiscal_year_span,
    forecast_revenue,
    load_segment_csv,
    load_segment_revenue,
    next_fiscal_year,
    segment_cagr,
)

ROOT = Path(__file__).resolve().parent.parent
GULFOILLUB_CSV = ROOT / "data" / "GULFOILLUB" / "financials.csv"
SEGMENT_CSV = ROOT / "data" / "GULFOILLUB" / "segment_revenue.csv"


def write_segment_csv(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "segment_revenue.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


# -- fiscal-year label helpers ------------------------------------------------


def test_next_fiscal_year():
    assert next_fiscal_year("FY2023-24") == "FY2024-25"
    assert next_fiscal_year("FY2014-15") == "FY2015-16"
    assert next_fiscal_year("FY1999-00") == "FY2000-01"


def test_next_fiscal_year_rejects_a_bad_label():
    with pytest.raises(ValueError, match="not a recognized fiscal-year label"):
        next_fiscal_year("2023-24")


def test_fiscal_year_span():
    assert fiscal_year_span("FY2014-15", "FY2023-24") == 9
    assert fiscal_year_span("FY2023-24", "FY2023-24") == 0


# -- load_segment_csv ----------------------------------------------------------


def test_load_segment_csv_reads_the_real_committed_fixture():
    df = load_segment_csv(SEGMENT_CSV)
    assert list(df.columns) == ["fiscal_year", "export_revenue"]
    assert len(df) == 10


def test_load_segment_csv_rejects_missing_columns(tmp_path):
    bad = write_segment_csv(tmp_path, [{"fiscal_year": "FY2023-24"}])
    with pytest.raises(ValueError, match="missing columns"):
        load_segment_csv(bad)


def test_load_segment_csv_rejects_duplicate_fiscal_years(tmp_path):
    row = {"fiscal_year": "FY2023-24", "export_revenue": "20161.22"}
    bad = write_segment_csv(tmp_path, [row, row])
    with pytest.raises(ValueError, match="duplicate fiscal_year"):
        load_segment_csv(bad)


# -- build_segment_revenue / reconciliation -----------------------------------


def test_build_segment_revenue_reconciles_exactly_against_financials_csv():
    """Domestic + export must sum to financials.csv's revenue for every year --
    the whole point of deriving domestic as a residual rather than storing it
    as a second, independently-sourced number that could drift."""
    statements = load_historical_statements(GULFOILLUB_CSV)
    segment_df = load_segment_csv(SEGMENT_CSV)
    segments = build_segment_revenue(statements, segment_df)

    assert len(segments) == 10
    revenue_by_year = {s.fiscal_year: s.income.revenue for s in statements}
    for s in segments:
        assert s.total_revenue == pytest.approx(revenue_by_year[s.fiscal_year])


def test_build_segment_revenue_known_values_for_the_last_fiscal_year():
    statements = load_historical_statements(GULFOILLUB_CSV)
    segment_df = load_segment_csv(SEGMENT_CSV)
    segments = build_segment_revenue(statements, segment_df)
    last = segments[-1]

    assert last.fiscal_year == "FY2023-24"
    assert last.export_revenue == pytest.approx(20161.22)
    assert last.domestic_revenue == pytest.approx(328409.68 - 20161.22)
    assert last.export_share == pytest.approx(20161.22 / 328409.68)


def test_build_segment_revenue_rejects_a_fiscal_year_mismatch(tmp_path):
    statements = load_historical_statements(GULFOILLUB_CSV)
    segment_df = load_segment_csv(SEGMENT_CSV).iloc[1:]  # drop FY2014-15
    with pytest.raises(ValueError, match="don't match financials.csv"):
        build_segment_revenue(statements, segment_df)


def test_build_segment_revenue_rejects_export_revenue_exceeding_total(tmp_path):
    statements = load_historical_statements(GULFOILLUB_CSV)
    segment_df = load_segment_csv(SEGMENT_CSV).copy()
    segment_df.loc[segment_df["fiscal_year"] == "FY2023-24", "export_revenue"] = "999999999"
    with pytest.raises(ValueError, match="outside \\[0, total_revenue"):
        build_segment_revenue(statements, segment_df)


def test_build_segment_revenue_rejects_negative_export_revenue(tmp_path):
    statements = load_historical_statements(GULFOILLUB_CSV)
    segment_df = load_segment_csv(SEGMENT_CSV).copy()
    segment_df.loc[segment_df["fiscal_year"] == "FY2023-24", "export_revenue"] = "-1"
    with pytest.raises(ValueError, match="outside \\[0, total_revenue"):
        build_segment_revenue(statements, segment_df)


def test_load_segment_revenue_end_to_end():
    segments = load_segment_revenue(GULFOILLUB_CSV, SEGMENT_CSV)
    assert [s.fiscal_year for s in segments] == sorted(s.fiscal_year for s in segments)
    assert segments[0].fiscal_year == "FY2014-15"
    assert segments[-1].fiscal_year == "FY2023-24"


# -- segment_cagr --------------------------------------------------------------


def test_segment_cagr_domestic_and_export_on_the_real_fixture():
    segments = load_segment_revenue(GULFOILLUB_CSV, SEGMENT_CSV)
    first, last = segments[0], segments[-1]

    expected_domestic_cagr = (last.domestic_revenue / first.domestic_revenue) ** (1 / 9) - 1
    expected_export_cagr = (last.export_revenue / first.export_revenue) ** (1 / 9) - 1

    assert segment_cagr(segments, "domestic_revenue") == pytest.approx(expected_domestic_cagr)
    assert segment_cagr(segments, "export_revenue") == pytest.approx(expected_export_cagr)
    # Export grew off a much smaller base and should outpace domestic by a wide margin.
    assert segment_cagr(segments, "export_revenue") > segment_cagr(segments, "domestic_revenue")


def test_segment_cagr_requires_two_distinct_fiscal_years():
    one = [SegmentRevenue("FY2023-24", 100.0, 10.0)]
    with pytest.raises(ValueError, match="at least two distinct fiscal years"):
        segment_cagr(one, "domestic_revenue")


# -- forecast_revenue -----------------------------------------------------------


def test_forecast_revenue_default_growth_compounds_each_segment_at_its_own_cagr():
    segments = load_segment_revenue(GULFOILLUB_CSV, SEGMENT_CSV)
    d_cagr = segment_cagr(segments, "domestic_revenue")
    e_cagr = segment_cagr(segments, "export_revenue")
    last = segments[-1]

    forecasts = forecast_revenue(segments, 3)
    assert [f.fiscal_year for f in forecasts] == ["FY2024-25", "FY2025-26", "FY2026-27"]

    expected_domestic_y3 = last.domestic_revenue * (1 + d_cagr) ** 3
    expected_export_y3 = last.export_revenue * (1 + e_cagr) ** 3
    assert forecasts[-1].domestic_revenue == pytest.approx(expected_domestic_y3)
    assert forecasts[-1].export_revenue == pytest.approx(expected_export_y3)
    assert forecasts[-1].total_revenue == pytest.approx(expected_domestic_y3 + expected_export_y3)


def test_forecast_revenue_accepts_an_explicit_override_per_segment():
    segments = load_segment_revenue(GULFOILLUB_CSV, SEGMENT_CSV)
    last = segments[-1]

    forecasts = forecast_revenue(segments, 1, domestic_growth=0.10, export_growth=0.0)
    assert forecasts[0].domestic_revenue == pytest.approx(last.domestic_revenue * 1.10)
    assert forecasts[0].export_revenue == pytest.approx(last.export_revenue)


def test_forecast_revenue_rejects_fewer_than_one_year():
    segments = load_segment_revenue(GULFOILLUB_CSV, SEGMENT_CSV)
    with pytest.raises(ValueError, match="n_years must be >= 1"):
        forecast_revenue(segments, 0)


def test_forecast_year_total_revenue_property():
    f = ForecastYear("FY2024-25", 100.0, 10.0)
    assert f.total_revenue == pytest.approx(110.0)


# -- CLI --------------------------------------------------------------------


def test_revenue_cli_run_against_the_real_fixtures(capsys):
    exit_code = revenue.run(
        "GULFOILLUB", GULFOILLUB_CSV, SEGMENT_CSV, forecast_years=3, domestic_growth=None, export_growth=None
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "GULFOILLUB: 10 fiscal years" in out
    assert "historical CAGR FY2014-15->FY2023-24" in out
    assert "forecast (3y" in out
    assert "FY2026-27" in out


def test_revenue_cli_skips_the_forecast_section_when_forecast_years_is_zero(capsys):
    exit_code = revenue.run(
        "GULFOILLUB", GULFOILLUB_CSV, SEGMENT_CSV, forecast_years=0, domestic_growth=None, export_growth=None
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "forecast" not in out


def test_revenue_cli_reports_a_missing_segment_file_cleanly(tmp_path, capsys):
    exit_code = revenue.run(
        "GULFOILLUB", GULFOILLUB_CSV, tmp_path / "missing.csv", forecast_years=3, domestic_growth=None,
        export_growth=None,
    )
    assert exit_code == 1
    assert "no segment revenue data at" in capsys.readouterr().err


def test_revenue_cli_reports_a_missing_financials_file_cleanly(tmp_path, capsys):
    exit_code = revenue.run(
        "NOPE", tmp_path / "missing.csv", SEGMENT_CSV, forecast_years=3, domestic_growth=None, export_growth=None
    )
    assert exit_code == 1
    assert "no financials data at" in capsys.readouterr().err


def test_revenue_cli_reports_a_reconciliation_failure_cleanly(tmp_path, capsys):
    bad_segment = write_segment_csv(tmp_path, [{"fiscal_year": "FY1999-00", "export_revenue": "1.0"}])
    exit_code = revenue.run(
        "GULFOILLUB", GULFOILLUB_CSV, bad_segment, forecast_years=3, domestic_growth=None, export_growth=None
    )
    assert exit_code == 1
    assert "segment revenue build failed" in capsys.readouterr().err


def test_revenue_cli_accepts_growth_overrides(capsys):
    exit_code = revenue.run(
        "GULFOILLUB", GULFOILLUB_CSV, SEGMENT_CSV, forecast_years=1, domestic_growth=0.10, export_growth=0.20
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "domestic @ +10.00%, export @ +20.00%" in out


def test_main_cli_end_to_end_against_the_real_fixtures(capsys):
    exit_code = revenue.main(["--ticker", "GULFOILLUB"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "GULFOILLUB: 10 fiscal years" in out


def test_main_cli_accepts_explicit_paths_and_overrides(capsys):
    exit_code = revenue.main(
        [
            "--ticker", "GULFOILLUB",
            "--financials", str(GULFOILLUB_CSV),
            "--segments", str(SEGMENT_CSV),
            "--forecast-years", "2",
            "--domestic-growth", "0.08",
            "--export-growth", "0.12",
        ]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "domestic @ +8.00%, export @ +12.00%" in out
    assert "FY2025-26" in out
