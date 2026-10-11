"""Day 3 CLI: cost structure, D&A, capex and working-capital schedules.

    python -m model.costs --ticker GULFOILLUB
    python -m model.costs --ticker GULFOILLUB --forecast-years 3
    python -m model.costs --ticker GULFOILLUB --forecast-years 3 \\
        --ebitda-margin 0.15 --da-margin 0.015 --capex-margin 0.02 --nwc-margin 0.18

Loads ``data/<ticker>/financials.csv`` and ``data/<ticker>/segment_revenue.csv``,
builds the historical margin schedule (``model.schedules``), and chains it onto
Day 2's revenue forecast (``model.revenue_driver.forecast_revenue``) to project
EBITDA, D&A, EBIT, capex and working capital forward — each on a trailing
historical average margin of revenue, individually overridable.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from model.historical import load_historical_statements
from model.revenue_driver import forecast_revenue, load_segment_revenue
from model.schedules import DEFAULT_TRAILING_YEARS, build_schedule, forecast_schedule

ROOT = Path(__file__).resolve().parent.parent


def default_financials_path(ticker: str) -> Path:
    return ROOT / "data" / ticker / "financials.csv"


def default_segment_path(ticker: str) -> Path:
    return ROOT / "data" / ticker / "segment_revenue.csv"


def run(
    ticker: str,
    financials_path: Path,
    segment_path: Path,
    forecast_years: int,
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

    try:
        statements = load_historical_statements(financials_path)
        segments = load_segment_revenue(financials_path, segment_path)
    except ValueError as exc:
        print(f"schedule build failed: {exc}", file=sys.stderr)
        return 1

    schedule = build_schedule(statements)

    print(f"{ticker}: {len(schedule)} fiscal years of cost/D&A/capex/working-capital schedules (margin of revenue)")
    print(f"{'Fiscal year':<12} {'EBITDA mgn':>11} {'D&A mgn':>9} {'Capex mgn':>10} {'NWC mgn':>9}")
    for s in schedule:
        print(
            f"{s.fiscal_year:<12} {s.ebitda_margin:>11.2%} {s.da_margin:>9.2%} "
            f"{s.capex_margin:>10.2%} {s.nwc_margin:>9.2%}"
        )

    if forecast_years > 0:
        try:
            revenue_forecasts = forecast_revenue(segments, forecast_years)
        except ValueError as exc:
            print(f"revenue forecast failed: {exc}", file=sys.stderr)
            return 1
        forecasts = forecast_schedule(
            schedule,
            revenue_forecasts,
            ebitda_margin=ebitda_margin,
            da_margin=da_margin,
            capex_margin=capex_margin,
            nwc_margin=nwc_margin,
            trailing_years=trailing_years,
        )
        f0 = forecasts[0]
        print(
            f"\nforecast ({forecast_years}y, {trailing_years}y trailing average unless overridden): "
            f"EBITDA @ {f0.ebitda_margin_used:+.2%}, D&A @ {f0.da_margin_used:+.2%}, "
            f"capex @ {f0.capex_margin_used:+.2%}, NWC @ {f0.nwc_margin_used:+.2%}"
        )
        print(
            f"{'Fiscal year':<12} {'Revenue':>14} {'EBITDA':>12} {'D&A':>10} {'EBIT':>12} "
            f"{'Capex':>10} {'NWC':>12} {'Delta NWC':>12}"
        )
        for f in forecasts:
            print(
                f"{f.fiscal_year:<12} {f.revenue:>14,.2f} {f.ebitda:>12,.2f} {f.depreciation_amortization:>10,.2f} "
                f"{f.ebit:>12,.2f} {f.capex:>10,.2f} {f.net_working_capital:>12,.2f} {f.delta_nwc:>12,.2f}"
            )

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ticker", required=True, help="e.g. GULFOILLUB (no yfinance suffix)")
    parser.add_argument("--financials", default=None, help="defaults to data/<ticker>/financials.csv")
    parser.add_argument("--segments", default=None, help="defaults to data/<ticker>/segment_revenue.csv")
    parser.add_argument("--forecast-years", type=int, default=3, help="years to project forward (0 to skip)")
    parser.add_argument("--ebitda-margin", type=float, default=None, help="override EBITDA margin, e.g. 0.15")
    parser.add_argument("--da-margin", type=float, default=None, help="override D&A margin, e.g. 0.015")
    parser.add_argument("--capex-margin", type=float, default=None, help="override capex margin, e.g. 0.02")
    parser.add_argument("--nwc-margin", type=float, default=None, help="override NWC margin, e.g. 0.18")
    parser.add_argument(
        "--trailing-years",
        type=int,
        default=DEFAULT_TRAILING_YEARS,
        help="years of history to average for any margin not overridden",
    )
    args = parser.parse_args(argv)

    financials_path = Path(args.financials) if args.financials else default_financials_path(args.ticker)
    segment_path = Path(args.segments) if args.segments else default_segment_path(args.ticker)
    return run(
        args.ticker,
        financials_path,
        segment_path,
        args.forecast_years,
        args.ebitda_margin,
        args.da_margin,
        args.capex_margin,
        args.nwc_margin,
        args.trailing_years,
    )


if __name__ == "__main__":
    raise SystemExit(main())
