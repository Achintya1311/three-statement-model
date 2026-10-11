"""Day 6 CLI: export the three-statement forecast to an Excel workbook with
live formulas, not pasted values.

    python -m model.build --ticker GULFOILLUB --years 3 --export outputs/model.xlsx
    python -m model.build --ticker GULFOILLUB --years 5 --tax-rate 0.26 --dividend-payout 0.2

Builds on Day 1/2/3/4/5's own loaders and assumption-resolution logic
(``model.excel_export.build_workbook``), in non-circular mode only — see
that module's docstring for why. Every rate/margin/limit the model needs is
written once, as a value, to the workbook's Assumptions sheet; the Forecast
sheet is formulas only past the Base column.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from model.excel_export import export_workbook
from model.historical import load_historical_statements
from model.revenue_driver import load_segment_revenue
from model.schedules import DEFAULT_TRAILING_YEARS

ROOT = Path(__file__).resolve().parent.parent


def default_financials_path(ticker: str) -> Path:
    return ROOT / "data" / ticker / "financials.csv"


def default_segment_path(ticker: str) -> Path:
    return ROOT / "data" / ticker / "segment_revenue.csv"


def default_export_path(ticker: str) -> Path:
    return ROOT / "outputs" / f"{ticker}_model.xlsx"


def run(
    ticker: str,
    financials_path: Path,
    segment_path: Path,
    forecast_years: int,
    export_path: Path,
    tax_rate: float | None,
    dividend_payout: float | None,
    amortization_rate: float | None,
    revolver_limit: float | None,
    interest_rate: float | None,
    domestic_growth: float | None,
    export_growth: float | None,
    ebitda_margin: float | None,
    da_margin: float | None,
    capex_margin: float | None,
    nwc_margin: float | None,
    trailing_years: int,
) -> int:
    if not financials_path.exists():
        print(f"no financials data at {financials_path}", file=sys.stderr)
        return 1
    if not segment_path.exists():
        print(f"no segment revenue data at {segment_path}", file=sys.stderr)
        return 1
    if forecast_years < 1:
        print("--years must be >= 1 (the workbook has nothing to project otherwise)", file=sys.stderr)
        return 1

    try:
        statements = load_historical_statements(financials_path)
        segments = load_segment_revenue(financials_path, segment_path)
    except ValueError as exc:
        print(f"workbook build failed: {exc}", file=sys.stderr)
        return 1

    export_workbook(
        ticker,
        statements,
        segments,
        forecast_years,
        export_path,
        tax_rate=tax_rate,
        dividend_payout=dividend_payout,
        amortization_rate=amortization_rate,
        revolver_limit=revolver_limit,
        interest_rate=interest_rate,
        domestic_growth=domestic_growth,
        export_growth=export_growth,
        ebitda_margin=ebitda_margin,
        da_margin=da_margin,
        capex_margin=capex_margin,
        nwc_margin=nwc_margin,
        trailing_years=trailing_years,
    )
    print(f"{ticker}: wrote {forecast_years}y non-circular forecast workbook to {export_path}")
    print("Assumptions sheet holds every rate/margin/limit; Forecast sheet is formulas past the Base column.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ticker", required=True, help="e.g. GULFOILLUB (no yfinance suffix)")
    parser.add_argument("--financials", default=None, help="defaults to data/<ticker>/financials.csv")
    parser.add_argument("--segments", default=None, help="defaults to data/<ticker>/segment_revenue.csv")
    parser.add_argument("--years", type=int, default=3, help="forecast years to export (>= 1)")
    parser.add_argument("--export", default=None, help="output .xlsx path; defaults to outputs/<ticker>_model.xlsx")
    parser.add_argument("--tax-rate", type=float, default=None, help="override effective tax rate, e.g. 0.26")
    parser.add_argument("--dividend-payout", type=float, default=None, help="override dividend payout ratio")
    parser.add_argument("--amort-rate", type=float, default=None, help="override mandatory amortization rate")
    parser.add_argument("--revolver-limit", type=float, default=None, help="override revolver facility size")
    parser.add_argument("--interest-rate", type=float, default=None, help="override interest rate")
    parser.add_argument("--domestic-growth", type=float, default=None, help="override domestic revenue growth")
    parser.add_argument("--export-growth", type=float, default=None, help="override export revenue growth")
    parser.add_argument("--ebitda-margin", type=float, default=None, help="override EBITDA margin")
    parser.add_argument("--da-margin", type=float, default=None, help="override D&A margin")
    parser.add_argument("--capex-margin", type=float, default=None, help="override capex margin")
    parser.add_argument("--nwc-margin", type=float, default=None, help="override NWC margin")
    parser.add_argument(
        "--trailing-years",
        type=int,
        default=DEFAULT_TRAILING_YEARS,
        help="years of history to average for any rate/margin not overridden",
    )
    args = parser.parse_args(argv)

    financials_path = Path(args.financials) if args.financials else default_financials_path(args.ticker)
    segment_path = Path(args.segments) if args.segments else default_segment_path(args.ticker)
    export_path = Path(args.export) if args.export else default_export_path(args.ticker)
    return run(
        args.ticker,
        financials_path,
        segment_path,
        args.years,
        export_path,
        args.tax_rate,
        args.dividend_payout,
        args.amort_rate,
        args.revolver_limit,
        args.interest_rate,
        args.domestic_growth,
        args.export_growth,
        args.ebitda_margin,
        args.da_margin,
        args.capex_margin,
        args.nwc_margin,
        args.trailing_years,
    )


if __name__ == "__main__":
    raise SystemExit(main())
